"""The accuracy gate: LoupMD against MACE float64, judged by MACE's own float32 deviation (the 3x rule).

A quantity passes when LoupMD's deviation from MACE float64 is at most three times MACE float32's deviation from
MACE float64 on the same structure, or below the floor (0.01 meV/atom, 1e-5 eV/A, 1e-7 eV/A^3). Every kernel path
the engine can choose per system is gated: the conv forward variants of the models that have them. (The kernels
specialised to MACE-OMAT-0 medium and their forced variants were retired with JIT_DESIGN.md stage 5.)
"""
from __future__ import annotations

import datetime
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import config, models
from ..errors import GateUnavailable, PlanRefused
from . import references, sets

SCHEMA = "loupmd.gate/1"
# Forced kernel paths (environment read when an engine is created, see include/loupmd.h).
GENERIC_VARIANTS = [{"LOUP_CONV_FWD_VARIANT": v} for v in ("1", "2")]
# What a gate engine must not inherit from the caller's environment (a forced variant, the atom reorder)
VARIANT_KEYS = ("LOUP_REORDER", "LOUP_CONV_FWD_VARIANT")
TILES_PER_CELL = 4      # --capacity tiled: receivers per tile = atoms / 4, rounded up
# Configurations where the model itself is not float32-reproducible, left out unless asked for: POLAR-1-S on
# NaNbO3_c0 has forces near 236,000 eV/A and MACE float32 is 27 to 90 eV/A off float64 there. (model stem, config).
UNSTABLE = {("MACE-POLAR-1-S", "NaNbO3_c0")}


@dataclass(frozen=True)
class GateRow:
    config: str
    variant: str
    atoms: int
    de_meV_per_atom: float     # LoupMD against MACE float64
    df: float                  # eV/A, largest component
    ds: float                  # eV/A^3, largest component
    de32: float                # MACE float32 against MACE float64, same units
    df32: float
    ds32: float
    energy_ratio: float        # deviation / max(float32 deviation, floor / 3): passes up to 3
    force_ratio: float
    stress_ratio: float
    passed: bool
    failed: tuple              # of "energy", "force", "stress"


def variant_tag(variant) -> str:
    return ",".join(f"{key[5:].lower()}={value}" for key, value in variant.items()) or "default"


def compare(name, variant, atoms, result, ref64, ref32, stress_ref) -> GateRow:
    """One row: ``result``, ``ref64`` and ``ref32`` are ``(energy, forces, stress 3x3)``."""
    import numpy as np

    (e, f, s), (e64, f64, s64), (e32, f32, s32) = result, ref64, ref32
    de, de32 = abs(e - e64) * 1000.0 / atoms, abs(e32 - e64) * 1000.0 / atoms
    df, df32 = float(np.abs(f - f64).max()), float(np.abs(f32 - f64).max())
    ds, ds32 = float(np.abs(s - stress_ref).max()), float(np.abs(s32 - s64).max())
    factor = config.GATE_FACTOR
    floors = (config.GATE_ENERGY_FLOOR_MEV_PER_ATOM, config.GATE_FORCE_FLOOR_EV_PER_A,
              config.GATE_STRESS_FLOOR_EV_PER_A3)
    failed = tuple(what for what, own, noise, floor in (("energy", de, de32, floors[0]), ("force", df, df32, floors[1]),
                                                        ("stress", ds, ds32, floors[2]))
                   if not own <= max(factor * noise, floor))
    return GateRow(config=name, variant=variant_tag(variant), atoms=int(atoms), de_meV_per_atom=de, df=df, ds=ds,
                   de32=de32, df32=df32, ds32=ds32, energy_ratio=de / max(de32, floors[0] / factor),
                   force_ratio=df / max(df32, floors[1] / factor), stress_ratio=ds / max(ds32, floors[2] / factor),
                   passed=not failed, failed=failed)


def has_conv_variants(meta) -> bool:
    """A generic bundle with an lx 1, C 128 conv layer, whose forward variant the engine picks per system."""
    return meta.get("arch") == "generic" and any(
        not int(meta.get(f"L{t}.first_hidden", 0)) and int(meta.get(f"L{t}.lmax_x", -1)) == 1
        and int(meta.get(f"L{t}.C_x", 0)) == 128 for t in range(int(meta.get("n_layers", 0))))


def make_record(rows, reorder, passed, set_name, model, reference, library, left_out, gpu=None, charge=None,
                spin_multiplicity=None, package_version=None, capacity="whole") -> dict:
    rows = [dict(asdict(row), failed=list(row.failed)) for row in rows]
    worst = {key: max((row[key] for row in rows), default=0.0)
             for key in ("energy_ratio", "force_ratio", "stress_ratio")}
    return {"schema": SCHEMA,
            "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "loupmd": package_version, "library": library, "gpu": gpu, "model": dict(model), "set": set_name,
            "charge": charge, "spin_multiplicity": spin_multiplicity, "capacity": capacity,
            "reference": dict(reference),
            "rule": {"factor": config.GATE_FACTOR, "energy_floor_meV_per_atom": config.GATE_ENERGY_FLOOR_MEV_PER_ATOM,
                     "force_floor_eV_per_A": config.GATE_FORCE_FLOOR_EV_PER_A,
                     "stress_floor_eV_per_A3": config.GATE_STRESS_FLOOR_EV_PER_A3},
            "rows": rows, "reorder": list(reorder), "left_out": list(left_out), "worst": worst,
            "passed": bool(passed)}


def run_gate(model, *, head=None, checkpoint=None, sha256=None, trusted=False, download=False, set_name="oxide",
             structures=None, gate_config=None, generic=None, charge=None, spin_multiplicity=None, device=0,
             use_ref_cache=True, include_unstable=False, engine_factory=None, ensure_bundle=None, bundle_meta=None,
             reference=None, environ=None, progress=None, capacity="whole") -> dict:
    """Gate ``model`` on a set (``oxide``, ``organic``, ``crystals``) or on rattled copies of ``structures`` and
    return the ``loupmd.gate/1`` record; ``record["passed"]`` is the verdict.

    Refusals come first and in this order: checkpoint trust, the export extra (``GateUnavailable``), the
    structures. ``capacity="tiled"`` evaluates every configuration tile by tile, about four tiles per cell (plan
    task S5-T04); ``capacity="wavefront"`` does so in the wavefront order with the row pool (S5-T08; two-layer
    models). ``generic=False`` asked for the kernels specialised to MACE-OMAT-0 medium, which were retired: refused. ``reference(model_path, configs, head, device, charge, spin)``,
    ``engine_factory``,
    ``ensure_bundle`` and ``bundle_meta`` replace MACE, the engine, the exporter and the bundle reader (tests).
    """
    from .. import __version__

    if capacity not in ("whole", "tiled", "wavefront"):
        raise PlanRefused(f"capacity must be 'whole', 'tiled' or 'wavefront', got {capacity!r}")
    tiled, wavefront = capacity != "whole", capacity == "wavefront"
    if generic is False:
        raise PlanRefused("the kernels specialised to MACE-OMAT-0 medium were retired: every model runs the generic "
                          "kernels", next_step="Leave out --specialised (generic=False).")
    gate_config = gate_config or config.GateConfig()
    say = progress or (lambda text: None)
    resolved, digest, _ = models.trusted_checkpoint(model, head, checkpoint=checkpoint, sha256=sha256,
                                                    trusted=trusted, download=download, environ=environ)
    references.require()
    entry = resolved.label
    use_head = head if head is not None else (entry.head if entry is not None else None)
    if use_head is None and entry is None:
        use_head = references.default_head(resolved.path)
    if structures:
        configs, set_label = sets.user_configs(structures, gate_config), "user"
    else:
        configs, set_label = sets.configs(set_name, environ), set_name
    stems = {resolved.path.stem} | ({entry.label} if entry is not None else set())
    left_out = [] if include_unstable else [name for name, _ in configs if any((s, name) in UNSTABLE for s in stems)]
    configs = [(name, at) for name, at in configs if name not in left_out]

    charge_spin = (charge, spin_multiplicity)
    compute = reference or references.compute

    def references_on(ref_device):
        ref_file = references.cache_path(resolved.path.name, digest, use_head, set_label,
                                         references.device_tag(ref_device), references.versions(), configs,
                                         charge_spin, environ)
        cached = references.load(ref_file, len(configs)) if use_ref_cache else None
        if cached is not None:
            say(f"MACE references from {ref_file}")
            return ref_file, True, cached
        say(f"computing the MACE float64 and float32 references on {ref_device} ...")
        computed = compute(resolved.path, configs, use_head, ref_device, charge, spin_multiplicity)
        references.save(ref_file, *computed)
        return ref_file, False, computed

    ref_device = references.resolve_device(gate_config.reference_device)
    try:
        ref_file, cached, (ref64, ref32, stress_ref) = references_on(ref_device)
    except Exception as error:  # noqa: BLE001  (torch's out-of-memory error, without importing torch here)
        if "out of memory" not in str(error).lower() or not ref_device.startswith("cuda"):
            raise
        # MACE float64 on the structure does not fit the GPU. With reference_device="auto" the CPU computes it,
        # unless the time limit forbids the CPU; an explicit "cuda" is not replaced.
        if gate_config.reference_device != "auto" or gate_config.cpu_float64_time_limit_s == 0:
            raise GateUnavailable(
                f"the MACE float64 reference of {len(configs[0][1])} atoms does not fit the GPU",
                why=str(error).splitlines()[0][:200],
                next_step="Compute it on the CPU (--ref-device cpu, GateConfig(reference_device='cpu')), which is "
                          "slow for large cells, or gate a smaller cell of the same material.") from None
        say("the float64 reference does not fit the GPU: computing it on the CPU")
        ref_device = "cpu"
        ref_file, cached, (ref64, ref32, stress_ref) = references_on(ref_device)

    if ensure_bundle is None:
        from .. import bundles

        ensure_bundle = bundles.ensure_bundle
    if bundle_meta is None:
        from ..export.bundle import read_bundle

        def bundle_meta(path):
            return read_bundle(path)[0]
    library = "(engine replaced)"
    if engine_factory is None:
        from .. import _core

        engine_factory, library = _core.LoupEngine, _core.library_version()

    engines, kinds, rows = {}, {}, []

    def evaluate(name, at, refs, variant):
        elements = tuple(sorted(set(at.get_atomic_numbers().tolist())))
        key = (elements, tuple(sorted(variant.items())))
        if key not in engines:
            # The gate's engines are default ones: a caller's LOUP_CHAIN_FOLD does not reach them. (A tiled system
            # leaves the skip-chain fold off itself: its sweeps need every layer's output, which the fold never forms.)
            saved = {k: os.environ.pop(k) for k in VARIANT_KEYS + ("LOUP_CHAIN_FOLD",) if k in os.environ}
            os.environ.update(variant)                      # read by the library when the engine is created
            try:
                bundle = ensure_bundle(resolved.path, list(elements), head=use_head, charge=charge,
                                       spin_multiplicity=spin_multiplicity, environ=environ)
                engines[key] = engine_factory(bundle, device_id=device)
                if not variant:
                    kinds[elements] = "conv" if has_conv_variants(bundle_meta(bundle)) else "plain"
            finally:
                for k in VARIANT_KEYS + ("LOUP_CHAIN_FOLD",):
                    os.environ.pop(k, None)
                os.environ.update(saved)
        engine = engines[key]
        if tiled:
            receivers = -(-len(at) // TILES_PER_CELL)
            if wavefront:
                from .. import _core

                engine.set_execution(_core.LOUP_EXEC_WAVEFRONT, receivers, 0.9)
            result = engine.evaluate_tiled(at.get_atomic_numbers(), at.positions, at.cell.array, receivers,
                                           skin=0.5)[:3]
            if wavefront and engine.last_execution().mode != _core.LOUP_EXEC_WAVEFRONT:
                raise PlanRefused(f"{name}: the wavefront did not run on {len(at)} atoms in tiles of {receivers}")
        else:
            engine.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
            result = engine.evaluate(at.positions, at.cell.array, compute_stress=True)
        rows.append(compare(name, variant, len(at), result, *refs))
        say(format_row(rows[-1]))

    for (name, at), r64, r32, sref in zip(configs, ref64, ref32, stress_ref):
        evaluate(name, at, (r64, r32, sref), {})
        kind = kinds[tuple(sorted(set(at.get_atomic_numbers().tolist())))]
        for variant in (GENERIC_VARIANTS if kind == "conv" else []):
            evaluate(name, at, (r64, r32, sref), variant)

    # The record's "reorder" list held the retired specialised kernels' reorder-on / reorder-off comparison; the
    # field stays in loupmd.gate/1, empty.
    reorder = []
    passed = all(row.passed for row in rows)

    gpu = None
    try:
        from .. import _gpu

        name, driver, capability = _gpu.query_gpus()[device]
        gpu = {"name": name, "driver": driver, "compute_capability": f"{capability // 10}.{capability % 10}"}
    except (OSError, ValueError, IndexError):
        pass
    return make_record(rows, reorder, passed, set_label,
                       {"label": entry.label if entry is not None else None, "file": resolved.path.name,
                        "sha256": digest, "head": use_head},
                       {"device": references.device_tag(ref_device), "file": str(ref_file), "cached": cached,
                        "mace": references.versions()[0], "torch": references.versions()[1]},
                       library, left_out, gpu=gpu, charge=charge, spin_multiplicity=spin_multiplicity,
                       package_version=__version__, capacity=capacity)


# ---------------------------------------------------------------------------------------------------- text

HEADER = (f"{'Config':18s} {'Variant':30s} | {'dE/atom (meV)':>13s} | {'dF_max (eV/A)':>13s} {'ratio':>6s} | "
          f"{'dS_max (eV/A3)':>14s} {'ratio':>6s} | Pass")


def format_row(row) -> str:
    row = asdict(row) if isinstance(row, GateRow) else row
    text = (f"{row['config']:18s} {row['variant']:30s} | {row['de_meV_per_atom']:13.5f} | {row['df']:13.3e} "
            f"{row['force_ratio']:6.2f} | {row['ds']:14.3e} {row['stress_ratio']:6.2f} | "
            f"{'PASS' if row['passed'] else 'FAIL'}")
    if not row["passed"]:
        text += (f"\n  ref32: dE/atom={row['de32']:.5f} meV, dF={row['df32']:.3e}, dS={row['ds32']:.3e}; failed: "
                 f"{', '.join(row['failed'])}")
    return text


def format_gate(record) -> str:
    model = record["model"]
    reference = record["reference"]
    lines = [f"model: {model['label'] or model['file']} ({model['file']}, SHA-256 {model['sha256'][:16]}..."
             + (f", head {model['head']}" if model["head"] else "") + ")",
             f"set {record['set']}: " + ", ".join(dict.fromkeys(
                 f"{row['config']} ({row['atoms']})" for row in record["rows"])),
             f"MACE references ({reference['device']}, mace {reference['mace']}, torch {reference['torch']}): "
             f"{reference['file']}" + (" (cached)" if reference["cached"] else " (computed now)")]
    if record.get("capacity", "whole") != "whole":
        lines.append(f"capacity: {record['capacity']} (about {TILES_PER_CELL} tiles per cell)")
    if record["left_out"]:
        lines.append("left out (the model is not float32-reproducible there): " + ", ".join(record["left_out"]))
    lines += ["", "LoupMD against MACE float64, judged by MACE float32 (the 3x rule)", HEADER, "-" * len(HEADER)]
    lines += [format_row(row) for row in record["rows"]]
    for check in record["reorder"]:
        lines.append(f"{check['config']}: reorder on vs off dE/atom {check['de_meV_per_atom']:.2e} meV, dF "
                     f"{check['df']:.2e} eV/A, dS {check['ds']:.2e} eV/A3 -> {'PASS' if check['passed'] else 'FAIL'}")
    worst = record["worst"]
    lines.append(f"worst ratios: energy {worst['energy_ratio']:.2f}, force {worst['force_ratio']:.2f}, stress "
                 f"{worst['stress_ratio']:.2f} (a quantity passes up to {record['rule']['factor']:g}, or below its "
                 "floor)")
    return "\n".join(lines)


def write_record(record, target):
    import json

    text = json.dumps(record, indent=2)
    if str(target) == "-":
        print(text)
    else:
        Path(target).write_text(text + "\n")
