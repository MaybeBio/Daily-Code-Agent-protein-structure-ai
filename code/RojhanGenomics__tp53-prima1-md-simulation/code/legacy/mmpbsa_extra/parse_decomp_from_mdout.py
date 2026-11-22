#!/usr/bin/env python3
# DEPRECATED in v2.0.1: sums the complex-only TDC energies and drops the ligand; these are not binding contributions  (see legacy/README.md)
"""
Extracts per-residue total energy decomposition (TDC lines) directly from a
raw sander PB mdout file, bypassing gmx_MMPBSA's own decomposition parser
(which raised a ValueError on residues 195/196 - Zn and ligand self-energy
terms exceeding the fixed-width output column and printing as '*********').
Skips residues >= 195 (the non-protein Zn/ligand self-energy rows) and
reports the mean total per-residue interaction energy across all frames.

Usage: python3 parse_decomp_from_mdout.py <complex_pb.mdout> [n_top]
"""
import sys
import numpy as np
from collections import defaultdict

def main(mdout_path, n_top=10):
    data = defaultdict(list)
    with open(mdout_path) as f:
        for line in f:
            if line.startswith("TDC"):
                parts = line.split()
                resid = int(parts[1])
                if resid >= 195:
                    continue
                try:
                    nums = [float(p) for p in parts[2:7]]
                except ValueError:
                    continue
                data[resid].append(sum(nums))

    means = {r: np.mean(v) for r, v in data.items() if len(v) > 50}
    top = sorted(means.items(), key=lambda x: x[1])[: int(n_top)]
    print(f"Top {n_top} most favorable residues (internal numbering, PDB = internal+95):")
    for r, e in top:
        print(f"  resid {r} (PDB {r+95}): {e:.2f} kcal/mol, n_frames={len(data[r])}")

if __name__ == "__main__":
    main(*sys.argv[1:])
