#!/usr/bin/env python3
"""MD-step benchmark for any supported model on a family-appropriate system (Langevin 300 K, 1 fs, skin 0.5 A;
median of 6 x 256 steps after 100 warm-up steps, as bench_md.py).

  python bench_family.py MODEL SYSTEM [SYSTEM ...] [--head H]

Systems: nbcl5 (NbCl5 R2SCAN 3x3x3, 1,944 atoms), srtio3 (SrTiO3 10x10x10, 5,000), water (the 648-atom water box
2x2x2, 5,184), nacl (NaCl R2SCAN 6x6x6 conventional, 1,728).
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from pathlib import Path

os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repository root: the loupmd package

import numpy as np  # noqa: E402
from ase import Atoms  # noqa: E402
from ase.io import read as ase_read  # noqa: E402
from ase.md.velocitydistribution import MaxwellBoltzmannDistribution  # noqa: E402

from loupmd import LoupEngine, ensure_loup_bundle  # noqa: E402

# Directories holding ResearchModule/ and FastMACE/: LOUP_DATA_ROOT (other machines, e.g. the cluster) first.
ROOTS = [r for r in (os.environ.get("LOUP_DATA_ROOT"), "/mnt/d/Margraf", "/mnt/homes/zwingel") if r]


def _find(rel):
    for r in ROOTS:
        p = os.path.join(r, rel)
        if os.path.exists(p):
            return p
    raise SystemExit(f"{rel} not found under {ROOTS}")


def system(name):
    if name == "nbcl5":
        return ase_read(_find("FastMACE/fastmace/protocols/data/NbCl5_R2SCAN.cif")).repeat((3, 3, 3))
    if name == "srtio3":
        a = 3.905
        return Atoms(symbols=["Sr", "Ti", "O", "O", "O"],
                     scaled_positions=[[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]],
                     cell=[a, a, a], pbc=True).repeat((10, 10, 10))
    if name == "water":
        return ase_read(_find("ResearchModule/Structures/Organic/water_216.extxyz")).repeat((2, 2, 2))
    if name == "water216":  # FastMACE's MACE-OFF benchmark cell
        return ase_read(_find("ResearchModule/Structures/Organic/water_216.extxyz"))
    if name == "nacl216":  # FastMACE's MH-1 / POLAR-1 benchmark cell (3 x 3 x 3 conventional)
        return ase_read(_find("ResearchModule/Structures/Benchmark/R2SCAN/NaCl.cif")).repeat((3, 3, 3))
    if name == "nacl":
        at = ase_read(_find("ResearchModule/Structures/Benchmark/R2SCAN/NaCl.cif"))
        return at.repeat([max(1, int(round(34.0 / h))) for h in at.cell.cellpar()[:3]])
    raise SystemExit(f"unknown system {name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("systems", nargs="+")
    ap.add_argument("--head", default=None)
    a = ap.parse_args()
    for name in a.systems:
        at = system(name)
        MaxwellBoltzmannDistribution(at, temperature_K=300.0, rng=np.random.default_rng(42))
        eng = LoupEngine(ensure_loup_bundle(a.model, at.get_atomic_numbers().tolist(), head=a.head), device_id=0)
        eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
        eng.set_state(at.positions, at.get_velocities(), at.cell.array)
        eng.run_langevin(100, dt_fs=1.0, temp_k=300.0, friction_per_fs=0.01, seed=1)
        runs = [eng.run_langevin(256, dt_fs=1.0, temp_k=300.0, friction_per_fs=0.01, seed=b + 2) for b in range(6)]
        ms = statistics.median(r.step_ms for r in runs)
        T = runs[-1].final_temperature_k
        print(f"{Path(a.model).stem:28s} {name:7s} {len(at):6d} atoms  {ms:8.3f} ms/step  "
              f"({ms * 1e3 / len(at):.2f} us/atom-step, T {T:.0f} K, rebuilds {sum(r.rebuilds for r in runs)})"
              + ("" if np.isfinite(T) else "  UNSTABLE: timing not valid"),
              flush=True)
        del eng


if __name__ == "__main__":
    main()
