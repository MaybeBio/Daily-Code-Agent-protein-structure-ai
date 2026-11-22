#!/usr/bin/env python3
"""Interleaved same-machine MD-step A/B for LoupMD (NbCl5 3x3x3 and SrTiO3 10x10x10, Langevin 300 K, 1 fs, skin 0.5).

  python bench_md.py MODEL CIF_NBCL5 [ENV=VAL,ENV=VAL ...]

Each argument after the two paths is one side: comma-separated environment settings ("-" for none). Sides run
in a fresh process each, in the order a b b a, so drift and build order are both covered.
"""
from __future__ import annotations

import os
import statistics
import subprocess
import sys

CHILD = r"""
import os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[1])))))
import numpy as np
from ase import Atoms
from ase.io import read as ase_read
from ase.md.velocitydistribution import MaxwellBoltzmannDistribution
from loupmd import LoupEngine, ensure_loup_bundle
model_path, cif = sys.argv[2], sys.argv[3]
out = []
nb = ase_read(cif).repeat((3, 3, 3))
a = 3.905
sto = Atoms(symbols=["Sr", "Ti", "O", "O", "O"],
            scaled_positions=[[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]],
            cell=[a, a, a], pbc=True).repeat((10, 10, 10))
for at in (nb, sto):
    MaxwellBoltzmannDistribution(at, temperature_K=300.0, rng=np.random.default_rng(42))
    eng = LoupEngine(ensure_loup_bundle(model_path, at.get_atomic_numbers().tolist()), device_id=0)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.set_state(at.positions, at.get_velocities(), at.cell.array)
    eng.run_langevin(100, dt_fs=1.0, temp_k=300.0, friction_per_fs=0.01, seed=1)
    s = [eng.run_langevin(256, dt_fs=1.0, temp_k=300.0, friction_per_fs=0.01, seed=b + 2).step_ms for b in range(6)]
    out.append(statistics.median(s))
print(f"{out[0]:.4f} {out[1]:.4f}")
"""


def run(side, model, cif):
    env = dict(os.environ)
    if side != "-":
        for kv in side.split(","):
            k, v = kv.split("=", 1)
            env[k] = v
    here = os.path.abspath(__file__)
    res = subprocess.run([sys.executable, "-c", CHILD, here, model, cif], env=env, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(res.stderr[-3000:])
    nb, sto = map(float, res.stdout.strip().splitlines()[-1].split())
    return nb, sto


def main():
    model, cif, sides = sys.argv[1], sys.argv[2], sys.argv[3:] or ["-"]
    order = sides + sides[::-1]
    results = {s: [] for s in sides}
    for s in order:
        nb, sto = run(s, model, cif)
        results[s].append((nb, sto))
        print(f"{s:30s} NbCl5 {nb:.3f} ms  SrTiO3 {sto:.3f} ms", flush=True)
    base = results[sides[0]]
    for s in sides:
        nb = statistics.mean(r[0] for r in results[s])
        sto = statistics.mean(r[1] for r in results[s])
        nb0 = statistics.mean(r[0] for r in base)
        sto0 = statistics.mean(r[1] for r in base)
        print(f"MEAN {s:25s} NbCl5 {nb:.3f} ({nb / nb0:.4f})  SrTiO3 {sto:.3f} ({sto / sto0:.4f})")


if __name__ == "__main__":
    main()
