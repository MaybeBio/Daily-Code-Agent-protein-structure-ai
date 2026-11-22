#!/usr/bin/env python
"""Dispersion kernel bake-off (plan task S6-D02): time candidates for the D3(BJ) two-body sum on the GPU and measure
each one's error against the converged sum.

Usage (WSL, the runtime environment of AGENTS.md):
    python tools/dev/d3_bakeoff.py build                    # nvcc src/dispersion/d3_proto.cu -> build/d3_proto.so
    python tools/dev/d3_bakeoff.py check                    # prototype vs simple-dftd3 at the same cutoffs, small cells
    python tools/dev/d3_bakeoff.py reference                # simple-dftd3 at 150 bohr on the bake-off systems (CPU,
                                                            # cached in ~/.cache/loupmd/d3_bakeoff/)
    python tools/dev/d3_bakeoff.py run OUT.json             # the candidates on the bake-off systems

Systems: NbCl5 3x3x3 (1,944 atoms), SrTiO3 10x10x10 (5,000), water 216 2x2x2 (5,184), each rattled by 0.05 A
(seed 1) so forces do not vanish by symmetry. PBE BJ parameters, no three-body term. The reference is simple-dftd3
(LGPL, used as an external program only) with a 150 bohr pair cutoff and its 40 bohr coordination-number cutoff.
The prototype's tables are torch-dftd 0.5.1's (MIT): c6ab, rcov (bohr, k2 included), r2r4.

The accuracy contract (docs/design/dispersion.md section 6.2): a candidate's error against the reference is no larger
than that of the plain 40 bohr real-space sum, in energy per atom, in pressure and in the largest force.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

BOHR = 0.529177210903
HARTREE = 27.211386245988
GPA = 160.21766208
MAXREF = 5
PBE_BJ = dict(s6=1.0, s8=0.7875, a1=0.4289, a2=4.4407)
ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "build" / "d3_proto.so"
CACHE = Path(os.path.expanduser("~/.cache/loupmd/d3_bakeoff"))
SYSTEMS = ("NbCl5 3x3x3", "SrTiO3 10x10x10", "water 216 2x2x2")


# --- tables -----------------------------------------------------------------------------------------------------
def tables():
    import torch_dftd

    d = np.load(Path(torch_dftd.__file__).parent / "nn" / "params" / "dftd3_params.npz")
    return d["c6ab"], d["rcov"], d["r2r4"]


class Species:
    """The per-species tables of one structure, in the prototype's layout."""

    def __init__(self, numbers):
        c6ab, rcov, r2r4 = tables()
        self.z = sorted(set(int(z) for z in numbers))
        index = {z: k for k, z in enumerate(self.z)}
        self.sp = np.array([index[int(z)] for z in numbers], dtype=np.int32)
        S = len(self.z)
        self.nref = np.array([int((c6ab[z, z, :, :, 0].diagonal() > 0).sum()) for z in self.z], dtype=np.int32)
        self.cnref = np.zeros((S, MAXREF))
        self.c6 = np.zeros((S, S, MAXREF, MAXREF))
        for a, za in enumerate(self.z):
            self.cnref[a, : self.nref[a]] = c6ab[za, za, : self.nref[a], 0, 1]
            for b, zb in enumerate(self.z):
                t = c6ab[za, zb, :, :, 0].copy()
                t[t < 0] = 0.0
                self.c6[a, b] = t
        self.rcov = np.array([rcov[z] for z in self.z])
        self.q = np.array([r2r4[z] for z in self.z])

    def weights(self, cn, k3=4.0):
        w = np.zeros((len(cn), MAXREF))
        for i, (s, c) in enumerate(zip(self.sp, cn)):
            m = self.nref[s]
            e = np.exp(-k3 * (c - self.cnref[s, :m]) ** 2)
            if e.sum() > 1e-300:
                w[i, :m] = e / e.sum()
            else:
                w[i, int(np.argmin(np.abs(c - self.cnref[s, :m])))] = 1.0
        return w


# --- the prototype ----------------------------------------------------------------------------------------------
def build():
    LIB.parent.mkdir(exist_ok=True)
    arch = os.environ.get("CUDA_ARCH", "sm_120")
    cmd = ["/usr/local/cuda/bin/nvcc", "-O3", "-std=c++17", f"-arch={arch}", "-shared", "-Xcompiler", "-fPIC",
           "--extended-lambda", str(ROOT / "src" / "dispersion" / "d3_proto.cu"), "-o", str(LIB)]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


_lib = None


def lib():
    global _lib
    if _lib is None:
        _lib = ctypes.CDLL(str(LIB))
        D, I = ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_int)
        _lib.d3_eval.argtypes = [ctypes.c_int, D, D, I, ctypes.c_int, I, D, D, D, D] + [ctypes.c_double] * 7 + \
            [ctypes.c_int, D, D, D, D, D, ctypes.c_int]
        _lib.d3_eval.restype = ctypes.c_int
    return _lib


def _p(a, t=ctypes.c_double):
    return a.ctypes.data_as(ctypes.POINTER(t))


VARIANT = int(os.environ.get("D3_VARIANT", "1"))


def proto(atoms, sp: Species, cut, cn_cut, cut_lo=0.0, repeat=1, param=PBE_BJ, variant=None):
    """Energy (eV), forces (eV/A), stress (eV/A^3, dE/d strain / V), times (ms: bins, CN, pairs, CN forces), CN."""
    n = len(atoms)
    pos = np.ascontiguousarray(atoms.positions, dtype=np.float64)
    cell = np.ascontiguousarray(np.asarray(atoms.cell), dtype=np.float64)
    e = np.zeros(1)
    f = np.zeros((n, 3))
    vir = np.zeros(6)
    t = np.zeros(4)
    cn = np.zeros(n)
    rc = lib().d3_eval(n, _p(pos), _p(cell), _p(sp.sp, ctypes.c_int), len(sp.z), _p(sp.nref, ctypes.c_int),
                       _p(np.ascontiguousarray(sp.cnref)), _p(sp.rcov), _p(sp.q), _p(np.ascontiguousarray(sp.c6)),
                       param["s6"], param["s8"], param["a1"], param["a2"], cut, cut_lo, cn_cut, repeat, _p(e), _p(f),
                       _p(vir), _p(t), _p(cn), VARIANT if variant is None else variant)
    if rc != 0:
        raise RuntimeError("d3_eval failed")
    xx, xy, xz, yy, yz, zz = vir
    stress = np.array([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]]) / atoms.get_volume()
    return float(e[0]), f, stress, t, cn


def tail(atoms, sp: Species, cn, rc, param=PBE_BJ):
    """The two-body sum beyond rc (bohr) for a uniform density: energy (eV) and stress (eV/A^3). C6 per atom pair
    from the atoms' own coordination numbers, summed per species; no force."""
    w = sp.weights(cn)
    V = atoms.get_volume() / BOHR ** 3
    r = np.linspace(rc, rc + 400.0, 400001)
    dr = r[1] - r[0]
    S = len(sp.z)
    wsum = np.array([w[sp.sp == b].sum(axis=0) for b in range(S)])           # [S, MAXREF]
    e = 0.0
    rup = 0.0                                                               # sum r u'(r) over the tail pairs
    for a in range(S):
        wa = w[sp.sp == a]                                                  # [na, MAXREF]
        for b in range(S):
            c6sum = float(np.einsum("ia,ab,b->", wa, sp.c6[a, b], wsum[b]))  # sum over i in a, j in b of C6_ij
            qq = 3.0 * sp.q[a] * sp.q[b]
            r0 = param["a1"] * np.sqrt(qq) + param["a2"]
            g = param["s6"] / (r ** 6 + r0 ** 6) + param["s8"] * qq / (r ** 8 + r0 ** 8)
            dg = -param["s6"] * 6 * r ** 5 / (r ** 6 + r0 ** 6) ** 2 - param["s8"] * qq * 8 * r ** 7 / (r ** 8 + r0 ** 8) ** 2
            i1 = np.trapz(4 * np.pi * r ** 2 * g, dx=dr)
            i2 = np.trapz(4 * np.pi * r ** 3 * dg, dx=dr)
            e += -0.5 * c6sum / V * i1
            rup += -0.5 * c6sum / V * i2
    # dE/d strain_aa = sum_pairs r u'(r) / 3 for an isotropic tail
    stress = np.eye(3) * (rup / 3.0) * HARTREE / atoms.get_volume()
    return e * HARTREE, stress


# --- reference --------------------------------------------------------------------------------------------------
def reference(atoms, disp2, cn=40.0, param="pbe"):
    from dftd3.interface import DispersionModel, RationalDampingParam

    model = DispersionModel(atoms.numbers, atoms.positions / BOHR, np.asarray(atoms.cell) / BOHR,
                            np.array([True, True, True]))
    model.set_realspace_cutoff(disp2=disp2, disp3=40.0, cn=cn)
    t0 = time.perf_counter()
    res = model.get_dispersion(RationalDampingParam(method=param, atm=False), grad=True)
    dt = time.perf_counter() - t0
    return (float(res["energy"]) * HARTREE, -np.asarray(res["gradient"]) * HARTREE / BOHR,
            np.asarray(res["virial"]) * HARTREE / atoms.get_volume(), dt)


def rattled(atoms, seed=1, sigma=0.05):
    atoms = atoms.copy()
    atoms.pbc = True
    atoms.positions += np.random.default_rng(seed).normal(0.0, sigma, atoms.positions.shape)
    return atoms


def bakeoff_system(name):
    sys.path.insert(0, str(ROOT))
    from loupmd.bench.suites import SYSTEMS as S

    return rattled(S[name]())


def cached_reference(name, disp2=150.0, cn=40.0):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name.replace(' ', '_')}_{disp2:g}_{cn:g}.npz"
    if path.exists():
        d = np.load(path)
        return float(d["e"]), d["f"], d["s"], float(d["t"])
    atoms = bakeoff_system(name)
    e, f, s, t = reference(atoms, disp2, cn)
    np.savez(path, e=e, f=f, s=s, t=t)
    return e, f, s, t


# --- comparisons ------------------------------------------------------------------------------------------------
def errors(n, a, b):
    """energy meV/atom, pressure GPa, largest force difference meV/A (norm per atom), largest stress element GPa."""
    (ea, fa, sa), (eb, fb, sb) = a, b
    pa, pb = -np.trace(sa) / 3, -np.trace(sb) / 3
    return dict(energy_meV_atom=abs(ea - eb) / n * 1e3, pressure_GPa=abs(pa - pb) * GPA,
                force_meV_A=float(np.linalg.norm(fa - fb, axis=1).max()) * 1e3,
                stress_GPa=float(np.abs(sa - sb).max()) * GPA)


def check():
    from ase import Atoms
    from ase.io import read

    sys.path.insert(0, str(ROOT))
    from loupmd.bench.suites import srtio3, structure_file

    cells = {"NbCl5": read(structure_file("nbcl5")), "SrTiO3 3x3x3": srtio3(3), "water 216": read(structure_file("water"))}
    worst = {}
    for name, atoms in cells.items():
        atoms = rattled(atoms)
        sp = Species(atoms.numbers)
        for cut, cn, variant in ((40.0, 40.0, 0), (40.0, 40.0, 1), (20.0, 20.0, 1)):
            e, f, s, _ = reference(atoms, cut, cn)[:3] + (None,)
            pe, pf, ps, _, _ = proto(atoms, sp, cut, cn, variant=variant)
            err = errors(len(atoms), (pe, pf, ps), (e, f, s))
            err["energy_rel"] = abs(pe - e) / abs(e)
            print(f"{name:14s} v{variant} pair {cut:g} / cn {cn:g} bohr: E {pe / len(atoms) * 1e3:9.3f} vs {e / len(atoms) * 1e3:9.3f}"
                  f" meV/atom; |dE| {err['energy_meV_atom']:.2e} meV/atom ({err['energy_rel']:.1e} rel), |dF| max "
                  f"{err['force_meV_A']:.2e} meV/A, |dS| max {err['stress_GPa']:.2e} GPa")
            for k, v in err.items():
                worst[k] = max(worst.get(k, 0.0), v)
    print("worst:", json.dumps(worst))
    return worst


def displaced(atoms, steps, dt_fs=1.0, T=300.0, seed=2):
    """Positions moved as far as atoms travel in `steps` steps at temperature T (ballistic, random directions)."""
    from ase import units

    rng = np.random.default_rng(seed)
    v = rng.normal(size=atoms.positions.shape) * np.sqrt(units.kB * T / atoms.get_masses())[:, None]   # A per ASE time
    out = atoms.copy()
    out.positions += v * steps * dt_fs * units.fs
    return out


def run(out_path):
    results = {"systems": {}, "param": PBE_BJ, "reference": "simple-dftd3 150 bohr pairs, 40 bohr CN, no ATM"}
    for name in SYSTEMS:
        atoms = bakeoff_system(name)
        n = len(atoms)
        sp = Species(atoms.numbers)
        ref = cached_reference(name)
        ref_e = ref[:3]
        row = {"atoms": n, "reference_energy_meV_atom": ref[0] / n * 1e3,
               "reference_pressure_GPa": -np.trace(ref[2]) / 3 * GPA, "reference_cpu_s": ref[3], "candidates": {}}
        # plain real-space sums
        for cut in (40.0, 30.0, 25.0, 20.0):
            for cn in ((40.0, 35.0, 30.0, 25.0, 20.0) if cut == 40.0 else (40.0,)):
                e, f, s, t, cnv = proto(atoms, sp, cut, cn, repeat=20)
                err = errors(n, (e, f, s), ref_e)
                row["candidates"][f"plain {cut:g} (cn {cn:g})"] = dict(err, ms=float(t[1:].sum()), times_ms=t.tolist())
                if cn == 40.0:
                    te, ts = tail(atoms, sp, cnv, cut)
                    err = errors(n, (e + te, f, s + ts), ref_e)
                    row["candidates"][f"tail {cut:g} (cn 40)"] = dict(err, ms=float(t[1:].sum()), times_ms=t.tolist(),
                                                                      tail_meV_atom=te / n * 1e3)
        # long-range shell [rs, 40) every k steps, short part every step
        for rs in (20.0, 25.0):
            e_s, f_s, s_s, t_s, _ = proto(atoms, sp, rs, 40.0, repeat=20)
            e_l, f_l, s_l, t_l, _ = proto(atoms, sp, 40.0, 40.0, cut_lo=rs, repeat=20)
            for k in (2, 5, 10, 20):
                moved = displaced(atoms, k)
                # the moved structure's full sum vs its short part plus the shell of the unmoved one
                me, mf, ms_, _, _ = proto(moved, sp, rs, 40.0)
                ref_moved = proto(moved, sp, 40.0, 40.0)[:3]
                stale = (me + e_l, mf + f_l, ms_ + s_l)
                err_stale = errors(n, stale, ref_moved)
                err_full = errors(n, (e_s + e_l, f_s + f_l, s_s + s_l), ref_e)
                ms = float(t_s[1:].sum() + t_l[1:].sum() / k)
                row["candidates"][f"shell {rs:g}-40 every {k}"] = dict(
                    err_full, ms=ms, stale_vs_plain40=err_stale,
                    note="error columns: the fresh split sum against the reference; stale_vs_plain40: after "
                         f"{k} steps of thermal motion (300 K, ballistic estimate) against a fresh 40 bohr sum")
        results["systems"][name] = row
        print(name, json.dumps(row, indent=1))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "check"
    if what == "build":
        build()
    elif what == "check":
        check()
    elif what == "reference":
        for name in SYSTEMS:
            e, f, s, t = cached_reference(name)
            print(f"{name}: {e:.6f} eV, {t:.1f} s")
    elif what == "time":       # both variants at 40 bohr on the bake-off systems
        for name in SYSTEMS:
            atoms = bakeoff_system(name)
            sp = Species(atoms.numbers)
            out = []
            for variant in (0, 1):
                e, f, s, t, _ = proto(atoms, sp, 40.0, 40.0, repeat=10, variant=variant)
                out.append((e, f))
                print(f"{name} v{variant}: bins {t[0]:.2f}, CN {t[1]:.2f}, pairs {t[2]:.2f}, CN forces {t[3]:.2f} ms")
            print(f"  v0 vs v1: dE {abs(out[0][0] - out[1][0]):.2e} eV, dF {np.abs(out[0][1] - out[1][1]).max():.2e} eV/A")
    elif what == "run":
        run(sys.argv[2])
    else:
        raise SystemExit(__doc__)
