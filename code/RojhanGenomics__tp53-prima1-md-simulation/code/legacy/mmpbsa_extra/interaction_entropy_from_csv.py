#!/usr/bin/env python3
# DEPRECATED in v2.0.1: wrong sign (-kT ln<exp(+dE/kT)> is always <= 0) and total dG used instead of the interaction energy  (see legacy/README.md)
"""
Computes the Interaction Entropy (-TdS) term of gmx_MMPBSA (Duan et al. 2016
method) directly from a per-frame energy CSV, bypassing gmx_MMPBSA's own IE
calculation (which raised an OverflowError on this system's more variable
frames). Uses the last 25% of frames by default (ie_segment=25).

Usage: python3 interaction_entropy_from_csv.py <energy_csv> <skiprows> <nrows>
Example: python3 interaction_entropy_from_csv.py mmpbsa_run1_energy.csv 614 201
"""
import sys
import numpy as np
import pandas as pd

def main(csv_path, skiprows, nrows, segment=0.25):
    df = pd.read_csv(csv_path, skiprows=int(skiprows), nrows=int(nrows))
    vals = df["TOTAL"].values
    k, T = 0.0019872041, 300.0
    n_last = int(len(vals) * segment)
    seg = vals[-n_last:]
    mean_seg = seg.mean()
    deint = seg - mean_seg
    exp_terms = np.exp(deint / (k * T))
    ie = -k * T * np.log(np.mean(exp_terms))
    print(f"Full-trajectory MM-PBSA: {vals.mean():.2f} +/- {vals.std():.2f} kcal/mol")
    print(f"-TdS (Interaction Entropy, last {segment*100:.0f}%): {ie:.2f} kcal/mol")
    print(f"dG_eff (dH + IE): {mean_seg + ie:.2f} kcal/mol")

if __name__ == "__main__":
    main(*sys.argv[1:])
