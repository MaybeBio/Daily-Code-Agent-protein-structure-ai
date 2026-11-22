"""Single-point comparison with OpenMM: the same system (our parameters) and
positions, energies by term and forces. OpenMM runs on its Reference
platform (double precision) unless --platform is given.

    python eval/compare_openmm.py data/systems/water216.vsys [--positions P] [--platform cuda]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "prep"))
from verlet_prep import openmm_ref as ref  # noqa: E402
from verlet_prep.topology import read_vsys, with_positions  # noqa: E402

EXE = os.path.join(ROOT, "engine", "build", "cm", "verlet")


def read_positions(path):
    with open(path) as f:
        box = np.array([float(x) for x in f.readline().split()[1:]])
        xyz = np.loadtxt(f)
    return xyz, box


def compare(vsys, positions=None, platform="cpu", omm_platform="Reference", cutoff=0.9, tol=5e-4, same_grid=True):
    s = read_vsys(vsys)
    if positions:
        xyz, box = read_positions(positions)
        s = with_positions(s, xyz, box)
    sysm = ref.openmm_system(s, cutoff=cutoff, ewald_tol=tol)
    nb = [f for f in sysm.getForces() if type(f).__name__ == "NonbondedForce"][0]
    import openmm as mm

    ctx = mm.Context(sysm, mm.VerletIntegrator(0.001), ref.platform(omm_platform))
    ctx.setPeriodicBoxVectors(mm.Vec3(s.box[0], 0, 0), mm.Vec3(0, s.box[1], 0), mm.Vec3(0, 0, s.box[2]))
    grid = nb.getPMEParametersInContext(ctx)
    del ctx
    with tempfile.TemporaryDirectory() as d:
        fpath = os.path.join(d, "forces.txt")
        cmd = [EXE, "energy", vsys, "--platform", platform, "--forces", fpath, "--cutoff", str(cutoff), "--tol", str(tol)]
        if positions:
            cmd += ["--positions", positions]
        if same_grid:
            cmd += ["--grid", ",".join(str(g) for g in grid[1:]), "--alpha", repr(grid[0])]
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
        ours = json.loads(out.stdout)
        f_ours = np.loadtxt(fpath)
    theirs, f_theirs = ref.energies(sysm, s.xyz, s.box, omm_platform, "double" if omm_platform == "CUDA" else None)
    rows = {
        "bond": (ours["bond"], theirs["bond"]),
        "angle": (ours["angle"], theirs["angle"]),
        "torsion": (ours["torsion"], theirs["torsion"]),
        "nonbonded": (ours["nonbonded"], theirs["nonbonded"]),
        "total": (ours["total"], theirs["total"]),
    }
    df = f_ours - f_theirs
    res = {
        "system": os.path.basename(vsys),
        "atoms": s.n,
        "openmm_pme": {"alpha": grid[0], "grid": list(grid[1:])},
        "same_grid": same_grid,
        "energies": {k: {"verlet": a, "openmm": b, "diff": a - b} for k, (a, b) in rows.items()},
        "terms": {k: ours[k] for k in ("lj", "coulomb_real", "coulomb_recip", "coulomb_self", "coulomb_excl", "dispersion", "pair14")},
        "force_rms_diff": float(np.sqrt((df**2).sum(1).mean())),
        "force_max_diff": float(np.abs(df).max()),
        "force_rms": float(np.sqrt((f_theirs**2).sum(1).mean())),
    }
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("vsys")
    ap.add_argument("--positions")
    ap.add_argument("--platform", default="cpu")
    ap.add_argument("--openmm-platform", default="Reference")
    ap.add_argument("--own-grid", action="store_true", help="let each program choose its PME grid")
    a = ap.parse_args()
    r = compare(a.vsys, a.positions, a.platform, a.openmm_platform, same_grid=not a.own_grid)
    print(json.dumps(r, indent=1))
