#!/usr/bin/env python3
"""Accuracy gate for LoupMD against MACE float64 and float32 references (3x float32 rule).

  python test_gate.py [MODEL] [--head H] [--set oxide|organic|crystals] [--ref-device cpu] [--no-ref-cache]
                      [--include-unstable]

The MACE references are cached (LOUP_GATE_CACHE, default ~/.cache/loupmd/gate_refs; see ref_cache_path for the key);
--no-ref-cache recomputes and overwrites them.

Structure sets: "oxide" (NaCl, SrTiO3, NbCl5; the default), "organic" (urea, naphthalene, paracetamol, the
648-atom water box; MACE-OFF's set) and "crystals" (NaCl, NaNbO3, NbCl5 R2SCAN cells; FastMACE's MH-1 / POLAR set).
Models with an lx 1 conv layer at C 128 are also evaluated with each conv forward variant forced
(GENERIC_VARIANTS), so every variant the per-system tuning can pick is gated.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repository root: the loupmd package

import numpy as np
from ase import Atoms
from ase.build import bulk
from ase.io import read as ase_read
from mace.calculators import MACECalculator

from loupmd import LoupEngine, _model_digest, ensure_loup_bundle
import polar_reference

# MACE references and complete POLAR strain targets are cached. Cached yardsticks remain fixed between
# comparisons; fresh float32 reductions can differ between evaluations. The key includes the model,
# configuration, device, package versions and reference protocol.
REF_CACHE_FORMAT = "gate-refs-3-polar-strain-autograd"
# Initial step for independent FD diagnostics only; production POLAR targets use strain autograd.
FD_STRESS_H = 1e-5


def ref_device_tag(ref_device):
    """The reference device as it affects rounding: for CUDA the GPU model, compute capability and CUDA version
    (a reference computed on another GPU is not reused), for the CPU the machine type."""
    import platform

    import torch

    if ref_device.startswith("cuda") and torch.cuda.is_available():
        idx = torch.device(ref_device).index or 0
        cap = torch.cuda.get_device_capability(idx)
        return f"cuda:{torch.cuda.get_device_name(idx)}:sm{cap[0]}{cap[1]}:cuda{torch.version.cuda}"
    return f"{ref_device}:{platform.machine()}"


def ref_cache_path(model_path, head, set_name, ref_device, configs, charge_spin=None):
    import hashlib

    import mace
    import torch

    h = hashlib.sha256()
    for part in (REF_CACHE_FORMAT, _model_digest(model_path), str(head), set_name, ref_device_tag(ref_device),
                 getattr(mace, "__version__", "?"), torch.__version__):
        h.update(part.encode() + b"\0")
    if charge_spin is not None and charge_spin != (None, None):  # OMOL-0 settings (keys of other runs unchanged)
        h.update(f"charge={charge_spin[0]}|spin={charge_spin[1]}".encode() + b"\0")
    for name, at in configs:
        h.update(name.encode() + b"\0")
        h.update(np.ascontiguousarray(at.get_atomic_numbers(), dtype=np.int64).tobytes())
        h.update(np.ascontiguousarray(at.positions, dtype=np.float64).tobytes())
        h.update(np.ascontiguousarray(at.cell.array, dtype=np.float64).tobytes())
        h.update(np.asarray(at.pbc, dtype=np.int8).tobytes())
    root = Path(os.environ.get("LOUP_GATE_CACHE") or Path.home() / ".cache" / "loupmd" / "gate_refs")
    return root / f"{Path(model_path).stem}_{set_name}_{h.hexdigest()[:20]}.npz"


def load_refs(path, n):
    """The cached references, or None if absent or unreadable (a truncated or foreign file is recomputed)."""
    if not path.exists():
        return None
    try:
        with np.load(path) as z:
            ref = lambda p, i: (float(z[f"{p}e"][i]), np.array(z[f"{p}f{i}"]), np.array(z[f"{p}s"][i]))  # noqa: E731
            return ([ref("r64", i) for i in range(n)], [ref("r32", i) for i in range(n)],
                    [np.array(z["sref"][i]) for i in range(n)])
    except Exception as exc:  # noqa: BLE001 (any unreadable cache entry means: recompute)
        print(f"ignoring unreadable reference cache {path}: {exc}")
        return None


def save_refs(path, ref64, ref32, stress_ref):
    arrays = {"sref": np.stack(stress_ref)}
    for p, refs in (("r64", ref64), ("r32", ref32)):
        arrays[f"{p}e"] = np.array([e for e, _, _ in refs])
        arrays[f"{p}s"] = np.stack([s for _, _, s in refs])
        for i, (_, f, _) in enumerate(refs):
            arrays[f"{p}f{i}"] = f
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + f".tmp{os.getpid()}.npz")
    np.savez(tmp, **arrays)
    os.replace(tmp, path)


def read_bundle_meta(path):
    from loupmd.export.bundle import read_bundle

    return read_bundle(path)[0]


# Directories holding ResearchModule/ and FastMACE/: LOUP_DATA_ROOT (other machines, e.g. the cluster) first.
DATA_ROOTS = [r for r in (os.environ.get("LOUP_DATA_ROOT"), "/mnt/d/Margraf", "/mnt/homes/zwingel") if r]
NBCL5_CIFS = [f"{r}/FastMACE/fastmace/protocols/data/NbCl5_R2SCAN.cif" for r in DATA_ROOTS]

# Forced kernel paths (environment read at engine creation, see include/loupmd.h): the conv forward variants of lx 1 layers at C 128 (GenericModel::tune_conv_variants picks one per
# system on sm_120; each is gated forced, on every configuration)
GENERIC_VARIANTS = [{"LOUP_CONV_FWD_VARIANT": v} for v in ("1", "2")]
VARIANT_KEYS = ("LOUP_CONV_FWD_VARIANT",)


def has_conv_variants(meta) -> bool:
    """A generic bundle with an lx 1, C 128 conv layer (launch_conv_fwd's conv_fwd_variants > 1)."""
    return meta.get("arch") == "generic" and any(
        not int(meta.get(f"L{t}.first_hidden", 0)) and int(meta.get(f"L{t}.lmax_x", -1)) == 1
        and int(meta.get(f"L{t}.C_x", 0)) == 128 for t in range(int(meta.get("n_layers", 0))))


STRUCTURE_ROOTS = [f"{r}/ResearchModule/Structures" for r in DATA_ROOTS]


def _structure(rel):
    for root in STRUCTURE_ROOTS:
        p = os.path.join(root, rel)
        if os.path.exists(p):
            return ase_read(p)
    raise SystemExit(f"structure {rel} not found under {STRUCTURE_ROOTS}")


def _configs(bases, schedule, seed=20261112):
    rng = np.random.default_rng(seed)
    configs = []
    for name, base in bases:
        for k, (strain, rattle) in enumerate(schedule):
            at = base.copy()
            F = np.eye(3) + strain * np.array([[1.0, 0.1, -0.05], [0.1, 0.8, 0.07], [-0.05, 0.07, 1.2]])
            at.set_cell(at.cell.array @ F.T, scale_atoms=True)
            at.positions += rng.normal(0.0, rattle, size=at.positions.shape)
            configs.append((f"{name}_c{k}", at))
    return configs


def make_organic():
    bases = [("urea_3x3x3", _structure("Organic/urea_cod1008787.cif").repeat((3, 3, 3))),
             ("naphthalene_2x2x2", _structure("Organic/naphthalene_cod2311090.cif").repeat((2, 2, 2))),
             ("paracetamol_2x2x2", _structure("Organic/paracetamol_cod2104364.cif").repeat((2, 2, 2))),
             ("water_216", _structure("Organic/water_216.extxyz"))]
    return _configs(bases, [(0.01, 0.02), (-0.008, 0.04)])


# Configurations where the model itself is not float32-reproducible, left out unless --include-unstable: POLAR-1-S on
# NaNbO3_c0 gives forces near 236,000 eV/A, MACE float32 is 27-90 eV/A off float64 there and LoupMD's energy takes one
# of several per-process values (STATUS 5.2); FastMACE excludes the configuration too. Keyed by (model stem, config).
UNSTABLE = {("MACE-POLAR-1-S", "NaNbO3_c0")}


def make_crystals():
    def rep_to(at, length=13.0):
        n = [max(1, int(np.ceil(length / h))) for h in at.cell.cellpar()[:3]]
        return at.repeat(n)

    bases = [(name, rep_to(_structure(f"Benchmark/R2SCAN/{name}.cif"))) for name in ("NaCl", "NaNbO3", "NbCl5")]
    return _configs(bases, [(0.02, 0.05), (-0.015, 0.08)])


def make_structures():
    # SrTiO3 3x3x3 cubic perovskite (135 atoms)
    a_sto = 3.905
    sto = Atoms(
        symbols=["Sr", "Ti", "O", "O", "O"],
        scaled_positions=[
            (0.0, 0.0, 0.0),
            (0.5, 0.5, 0.5),
            (0.5, 0.5, 0.0),
            (0.5, 0.0, 0.5),
            (0.0, 0.5, 0.5),
        ],
        cell=[a_sto, a_sto, a_sto],
        pbc=True,
    ).repeat((3, 3, 3))

    # NaCl 2x2x2 conventional (64 atoms)
    nacl = bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((2, 2, 2))

    bases = [("NaCl_2x2x2", nacl), ("SrTiO3_3x3x3", sto)]
    cif = next((c for c in NBCL5_CIFS if os.path.exists(c)), None)
    if cif is None:
        raise SystemExit(f"NbCl5 CIF not found (tried {NBCL5_CIFS}); the >= 512-atom structure is required")
    bases.append(("NbCl5_2x2x2", ase_read(cif).repeat((2, 2, 2))))  # 576 atoms

    rng = np.random.default_rng(20261112)
    configs = []
    for name, base in bases:
        for k, (strain, rattle) in enumerate([(0.02, 0.05), (-0.015, 0.08)]):
            at = base.copy()
            F = np.eye(3) + strain * np.array([[1.0, 0.1, -0.05], [0.1, 0.8, 0.07], [-0.05, 0.07, 1.2]])
            at.set_cell(at.cell.array @ F.T, scale_atoms=True)
            at.positions += rng.normal(0.0, rattle, size=at.positions.shape)
            configs.append((f"{name}_c{k}", at))
    return configs


def _with_charge_spin(a, charge, spin):
    """MACECalculator reads the total charge and the spin multiplicity from atoms.info["charge"] / ["spin"]
    (defaults 0 and 1)."""
    if charge is not None:
        a.info["charge"] = int(charge)
    if spin is not None:
        a.info["spin"] = int(spin)
    return a


def eval_mace(model_path: str, dtype: str, configs, head=None, device="cuda", charge=None, spin=None):
    kw = {"head": head} if head else {}
    calc = MACECalculator(model_paths=model_path, device=device, default_dtype=dtype, **kw)
    out = []
    for _, at in configs:
        a = _with_charge_spin(at.copy(), charge, spin)
        a.calc = calc
        e = float(a.get_potential_energy())
        f = np.asarray(a.get_forces(), dtype=np.float64)
        s = np.asarray(a.get_stress(voigt=False), dtype=np.float64)
        out.append((e, f, s))
    return out


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("model", nargs="?", default=(
        "/home/fzwin/models/mace-omat-0-medium.model"
        if os.path.exists("/home/fzwin/models/mace-omat-0-medium.model")
        else "/mnt/homes/zwingel/ResearchModule/Models/mace-omat-0-medium.model"))
    ap.add_argument("--head", default=None)
    ap.add_argument("--generic", action="store_true", help=argparse.SUPPRESS)  # accepted; every model is generic
    ap.add_argument("--set", default="oxide", choices=("oxide", "organic", "crystals"))
    ap.add_argument("--ref-device", default="cuda", help="device of the MACE references (cpu for models whose "
                    "float64 reference does not fit the GPU)")
    ap.add_argument("--no-ref-cache", action="store_true", help="recompute the MACE references (and overwrite the "
                    "cached ones) instead of reading them from LOUP_GATE_CACHE (default ~/.cache/loupmd/gate_refs)")
    ap.add_argument("--include-unstable", action="store_true", help="also gate the configurations in UNSTABLE")
    ap.add_argument("--charge", type=int, default=None, help="total charge (models with a charge embedding: OMOL-0)")
    ap.add_argument("--spin-multiplicity", type=int, default=None, help="2S + 1 (models with a spin embedding)")
    args = ap.parse_args()
    model_path, head = args.model, args.head
    if head is None:  # the exporter's default head of a multi-head model, named explicitly for MACECalculator
        import torch

        heads = list(getattr(torch.load(model_path, map_location="cpu", weights_only=False), "heads", None) or [])
        if len(heads) > 1:
            head = next((h for h in ("omat_pbe", "default", "Default") if h in heads), heads[-1])
            print(f"head: {head}")
    configs = {"oxide": make_structures, "organic": make_organic, "crystals": make_crystals}[args.set]()
    if not args.include_unstable:
        skipped = [n for n, _ in configs if (Path(model_path).stem, n) in UNSTABLE]
        configs = [(n, a) for n, a in configs if (Path(model_path).stem, n) not in UNSTABLE]
        if skipped:
            print(f"left out (model not float32-reproducible there, --include-unstable): {', '.join(skipped)}")
    print(f"{args.set} set: " + ", ".join(f"{n} ({len(a)})" for n, a in configs))
    import torch

    cs = (args.charge, args.spin_multiplicity)
    if cs != (None, None):
        print(f"charge {args.charge}, spin multiplicity {args.spin_multiplicity}")
    cache = ref_cache_path(model_path, head, args.set, args.ref_device, configs, cs)
    cached = None if args.no_ref_cache else load_refs(cache, len(configs))
    if cached is not None:
        print(f"MACE references from {cache}")
        ref64, ref32, stress_ref = cached
    else:
        print("Running MACE float64 reference...")
        ref64 = eval_mace(model_path, "float64", configs, head, args.ref_device, *cs)
        print("Running MACE float32 reference...")
        ref32 = eval_mace(model_path, "float32", configs, head, args.ref_device, *cs)
        polar = type(torch.load(model_path, map_location="cpu", weights_only=False)).__name__ == "PolarMACE"
        # POLAR's target differentiates the native energy through all cell-dependent geometry. Keep the
        # existing float32-vs-float64 autograd yardstick unchanged: this fixes the target, not the allowance.
        stress_ref = [s for _, _, s in ref64]
        if polar:
            print("PolarMACE: float64 native-energy strain gradient (complete cell dependence)")
            stress_ref = polar_reference.stress_reference(model_path, configs, device=args.ref_device)
        save_refs(cache, ref64, ref32, stress_ref)
        print(f"MACE references saved to {cache}")
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    conv_variants = {}

    engines = {}
    all_pass = True

    def run(name, at, refs, variant):
        nonlocal all_pass
        (e64, f64, s64), (e32, f32, s32), s_ref = refs
        zs = tuple(sorted(set(at.get_atomic_numbers().tolist())))
        key = (zs, tuple(sorted(variant.items())))
        if key not in engines:
            for k in VARIANT_KEYS:
                os.environ.pop(k, None)
            os.environ.update(variant)
            bundle = ensure_loup_bundle(model_path, list(zs), head=head, charge=args.charge,
                                        spin_multiplicity=args.spin_multiplicity)
            meta = read_bundle_meta(bundle)
            conv_variants[key] = has_conv_variants(meta)
            engines[key] = LoupEngine(bundle, device_id=0)
            for k in VARIANT_KEYS:
                os.environ.pop(k, None)
        eng = engines[key]
        eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
        e_l, f_l, s_l = eng.evaluate(at.positions, at.cell.array, compute_stress=True)

        nat = len(at)
        de_l = abs(e_l - e64) * 1000.0 / nat
        de_32 = abs(e32 - e64) * 1000.0 / nat
        df_l = float(np.abs(f_l - f64).max())
        df_32 = float(np.abs(f32 - f64).max())
        ds_l = float(np.abs(s_l - s_ref).max())
        ds_32 = float(np.abs(s32 - s64).max())

        rf = df_l / max(df_32, 1e-5 / 3.0)
        rs = ds_l / max(ds_32, 1e-7 / 3.0)
        ok = (de_l <= max(3.0 * de_32, 0.01)) and (df_l <= max(3.0 * df_32, 1e-5)) and (ds_l <= max(3.0 * ds_32, 1e-7))
        all_pass = all_pass and ok
        tag = ",".join(f"{k[5:].lower()}={v}" for k, v in variant.items()) or "default"
        print(f"{name:18s} {tag:24s} | {de_l:13.5f} | {df_l:13.3e} {rf:6.2f} | {ds_l:14.3e} {rs:6.2f} | {'PASS' if ok else 'FAIL'}")
        if not ok:
            print(f"  ref32: dE/atom={de_32:.5f} meV, dF={df_32:.3e}, dS={ds_32:.3e}")

    print("\n=== LoupMD vs MACE float64 / float32 (3x gate) ===")
    print(f"{'Config':18s} {'Variant':24s} | {'dE/atom (meV)':>13s} | {'dF_max (eV/A)':>13s} {'ratio':>6s} | {'dS_max (eV/A3)':>14s} {'ratio':>6s} | {'Pass'}")
    print("-" * 113)
    for (name, at), r64, r32, sr in zip(configs, ref64, ref32, stress_ref):
        run(name, at, (r64, r32, sr), {})
        zs = tuple(sorted(set(at.get_atomic_numbers().tolist())))
        if conv_variants.get((zs, ())):
            for variant in GENERIC_VARIANTS:
                run(name, at, (r64, r32, sr), variant)
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
