#!/usr/bin/env python3
# DEPRECATED in v2.0.1: superseded by analysis_v2/audit_md_metrics.py (minimum-image distances, His179 Nd1)  (see legacy/README.md)
"""
Tracks the distance between the structural Zn2+ ion and its four
coordinating residues (Cys176, His179, Cys238, Cys242) across the
equilibration (EM/NVT/NPT) and production stages of a simulation, and
characterizes the ion's final hydration state.

Usage: python3 analyze_zn_coordination.py <tpr_or_gro> <xtc_or_none>

Background: in this system, Zn2+ is modeled as a simple nonbonded ion
(standard Lennard-Jones + Coulomb parameters, no explicit bonded restraint
to the coordinating Cys/His side chains). Across all three independent
PRIMA-1 replicates (Run1-3), the ion was found to leave its crystallographic
coordination site within the first ~10 ps of NVT equilibration and settle
into a standard octahedral aqua complex (6 waters within 2.5-3.0 A) by the
start of production. This is consistent with known limitations of
non-polarizable, nonbonded Zn2+ models for protein metal centers (see
Discussion). The finding is independent of ligand (PRIMA-1) behavior and
reproducible across all three replicates.
"""
import sys
import MDAnalysis as mda
import numpy as np

def min_image_dist(p1, p2, box):
    d = p1 - p2
    d -= box * np.round(d / box)
    return np.linalg.norm(d)

def main(structure, trajectory=None):
    u = mda.Universe(structure, trajectory) if trajectory else mda.Universe(structure)
    zn = u.select_atoms("resname ZN")
    targets = {176: "SG", 179: "NE2", 238: "SG", 242: "SG"}

    frames = [u.trajectory[0]] if not trajectory else u.trajectory
    for ts in frames:
        box = ts.dimensions[:3] if trajectory else u.dimensions[:3]
        print(f"\n--- t = {getattr(ts, 'time', 0):.1f} ps ---")
        for resid, atomname in targets.items():
            sel = u.select_atoms(f"resid {resid} and name {atomname}")
            if len(sel) == 0:
                continue
            d = min_image_dist(zn.positions[0], sel.positions[0], box)
            print(f"  Zn-{resid}({atomname}): {d:.2f} A")

    # Hydration shell in the last available frame
    water = u.select_atoms("resname SOL and name OW")
    box = u.dimensions[:3]
    dists = np.array([min_image_dist(zn.positions[0], w, box) for w in water.positions])
    print(f"\nNearest water: {dists.min():.2f} A")
    print(f"Hydration shell (<3.0 A): {(dists < 3.0).sum()} waters")

if __name__ == "__main__":
    main(*sys.argv[1:])
