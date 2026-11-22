#!/usr/bin/env python3
"""
analyze_decomp.py -- per-residue BINDING contributions (Delta = complex - receptor - ligand) from a gmx_MMPBSA
decomposition CSV (-deo), with three safeguards:

  1. only the 'DELTAS' section is used (the 'Complex' TDC values are NOT binding contributions: they contain each
     residue's own internal energy and its interactions with the rest of the protein);
  2. the sum of the per-residue Delta TOTAL over all printed residues is compared, frame by frame, with the total
     Delta G of the same frames (QUICK/FINAL energy CSV).  If all residues were printed they must agree;
  3. the contribution of each residue is shown next to its MD contact occupancy, so energy without contact is flagged.

Usage
-----
    python analyze_decomp.py --decomp-csv mmpbsa_decomp_all_quick/DECOMP.csv \
                             --energy-csv mmpbsa_decomp_all_quick/ENERGY.csv \
                             --occupancy analysis_checks/Run1_residue_occupancy.csv \
                             --out mmpbsa_decomp_all_quick

Only numpy is required.  Read-only for the input files; writes decomp_delta_summary.csv into --out.
"""
import argparse
import os
import re
import sys
from collections import defaultdict

import numpy as np

SEC_RE = re.compile(r"^\s*(Complex|Receptor|Ligand|DELTAS?|Delta)\s*:?\s*$", re.I)
SUB_RE = re.compile(r"^\s*(Total|Sidechain|Backbone)\s+Decomposition", re.I)
COLS = ["Internal", "vdW", "Electrostatic", "PolarSolv", "NonPolar", "TOTAL"]


def parse_decomp_csv(path):
    """-> data[section][sub][residue_label] = array(frames, 6) ; frames list (per residue, same order)."""
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    frames = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    sec = sub = None
    with open(path, errors="replace") as fh:
        for raw in fh:
            line = raw.strip().strip('"')
            if not line:
                continue
            m = SEC_RE.match(line)
            if m:
                sec = "DELTAS" if m.group(1).upper().startswith("DELTA") else m.group(1).capitalize()
                sub = None
                continue
            m = SUB_RE.match(line)
            if m:
                sub = m.group(1).capitalize()
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 8 and parts[0].replace(".", "", 1).isdigit() and ":" in parts[1] and sec and sub:
                try:
                    vals = [float(x) for x in parts[2:8]]
                except ValueError:
                    continue
                data[sec][sub][parts[1]].append(vals)
                frames[sec][sub][parts[1]].append(int(float(parts[0])))
    for s in data:
        for b in data[s]:
            for r in data[s][b]:
                data[s][b][r] = np.array(data[s][b][r], float)
    return data, frames


def read_energy_total(path):
    """per-frame Delta TOTAL and Delta ENPOLAR (if present) from a gmx_MMPBSA energy CSV (-eo)."""
    sec, header, tot, enp, frm = None, None, [], [], []
    with open(path, errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            nums = []
            for p in parts:
                try:
                    nums.append(float(p))
                except ValueError:
                    nums.append(None)
            if all(n is None for n in nums):
                if len(parts) == 1 or all(p == "" for p in parts[1:]):
                    sec, header = parts[0], None
                else:
                    header = parts
            elif sec and "delta" in sec.lower() and header and "TOTAL" in header:
                frm.append(int(nums[0]))
                tot.append(nums[header.index("TOTAL")])
                enp.append(nums[header.index("ENPOLAR")] if "ENPOLAR" in header else float("nan"))
    if not tot:
        sys.exit(f"no Delta TOTAL column found in {path}")
    return np.array(frm), np.array(tot), np.array(enp)


def read_occupancy(path):
    occ = {}
    if path and os.path.exists(path):
        with open(path) as fh:
            next(fh)
            for line in fh:
                p = line.strip().split(",")
                if len(p) >= 4:
                    occ[int(p[0])] = float(p[2])
    return occ


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--decomp-csv", required=True)
    ap.add_argument("--energy-csv", required=True)
    ap.add_argument("--occupancy", default="analysis_checks/Run1_residue_occupancy.csv")
    ap.add_argument("--out", default=".")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--contact-pct", type=float, default=10.0, help="occupancy (%%) above which a residue counts as in contact")
    ap.add_argument("--tol", type=float, default=0.3, help="tolerance (kcal/mol) for the sum check (195 residues rounded to 0.01 give ~0.04)")
    a = ap.parse_args()

    data, frames = parse_decomp_csv(a.decomp_csv)
    print(f"sections found: { {s: sorted(d.keys()) for s, d in data.items()} }")
    if "DELTAS" not in data or "Total" not in data["DELTAS"]:
        sys.exit("No 'DELTAS' / Total Decomposition Contribution section found in the CSV.\n"
                 "Send me: grep -n -i -E 'complex|receptor|ligand|delta|decomposition' <decomp csv> | head -40")
    D = data["DELTAS"]["Total"]
    F = frames["DELTAS"]["Total"]
    labels = list(D.keys())
    nfr = len(next(iter(D.values())))
    print(f"Delta section: {len(labels)} residues (ligand + receptor), {nfr} frames")

    # ---- 2. sum check against the total Delta G of the same frames ------------------------------------------
    f0 = F[labels[0]]
    ef, et, ep = read_energy_total(a.energy_csv)
    tmap = dict(zip(ef.tolist(), et.tolist()))
    nmap = dict(zip(ef.tolist(), ep.tolist()))
    sums = np.sum([D[l][:, 5] for l in labels], axis=0)
    ok = [(f, s_) for f, s_ in zip(f0, sums) if f in tmap]
    s_res = np.array([s_ for _, s_ in ok])
    t_tot = np.array([tmap[f] for f, _ in ok])
    t_np = np.array([nmap[f] for f, _ in ok])
    have_np = not np.isnan(t_np).any()
    print("\nSUM CHECK  (per frame: sum over all printed residues of Delta TOTAL  vs  total Delta G)")
    print(f"   sum of residues             : mean {s_res.mean():8.3f}")
    print(f"   total Delta G               : mean {t_tot.mean():8.3f}")
    if have_np:
        print(f"   Delta ENPOLAR (non-polar solvation; the PB decomposition prints 0 for it in every residue): mean {t_np.mean():8.3f}")
        d2 = s_res + t_np - t_tot
        print(f"   residues + Delta ENPOLAR - total Delta G : mean {d2.mean():+.3f}  max |diff| = {np.abs(d2).max():.3f} kcal/mol over {len(ok)} frames")
        complete = np.abs(d2).max() < a.tol
        print("   ->", "CONSISTENT: residues + the (non-decomposed) non-polar term add up to the total Delta G" if complete else
              "NOT equal even after adding the non-polar term: some residues are missing or something is inconsistent")
    else:
        d1 = s_res - t_tot
        print(f"   max |sum - total| = {np.abs(d1).max():.3f} kcal/mol (no ENPOLAR column in the energy file to explain a difference)")
        complete = np.abs(d1).max() < a.tol
        print("   ->", "CONSISTENT" if complete else "NOT equal (check print_res and the non-polar term)")

    # ---- 1. per-residue Delta statistics ---------------------------------------------------------------------
    occ = read_occupancy(a.occupancy)
    rows = []
    for l in labels:
        v = D[l]
        n = len(v)
        pdb = int(l.split(":")[-1])
        rows.append({"label": l, "pdb": pdb, "kind": l.split(":")[0],
                     "mean": v[:, 5].mean(), "sd": v[:, 5].std(ddof=1) if n > 1 else 0.0,
                     "sem": v[:, 5].std(ddof=1) / np.sqrt(n) if n > 1 else 0.0,
                     "vdw": v[:, 1].mean(), "ele": v[:, 2].mean(), "pol": v[:, 3].mean(), "npol": v[:, 4].mean(),
                     "int": v[:, 0].mean(), "occ": occ.get(pdb, float("nan"))})
    rows.sort(key=lambda r: r["mean"])

    def fmt(r):
        o = "   n/a" if np.isnan(r["occ"]) else f"{r['occ']:5.1f}%"
        return (f"   {r['label']:14s} total {r['mean']:8.2f} +- {r['sem']:5.2f} (SEM)   vdW {r['vdw']:7.2f}  ele {r['ele']:8.2f}  "
                f"polar {r['pol']:7.2f}  nonpolar {r['npol']:6.2f}   contact {o}")

    lig = [r for r in rows if r["kind"] == "L"]
    prot = [r for r in rows if r["kind"] != "L"]
    print("\nLIGAND (complex - ligand):")
    for r in lig:
        print(fmt(r))
    print(f"\nMOST FAVOURABLE receptor residues (Delta = effect of the ligand on that residue), top {a.top}:")
    for r in prot[: a.top]:
        print(fmt(r))
    print(f"\nLEAST FAVOURABLE (opposing binding), top 8:")
    for r in prot[::-1][:8]:
        print(fmt(r))
    print("\nBREAKDOWN of the mean total Delta G (kcal/mol):")
    print(f"   ligand (complex - ligand)         : {sum(r['mean'] for r in lig):8.2f}")
    print(f"   sum of the {len(prot)} receptor residues{' ' * max(0, 11 - len(str(len(prot))))}: {sum(r['mean'] for r in prot):8.2f}")
    if have_np:
        print(f"   non-polar solvation (not decomposed): {t_np.mean():8.2f}")
    print(f"   total Delta G (same frames)       : {t_tot.mean():8.2f}")
    sig = [r for r in prot if abs(r["mean"]) > 2 * r["sem"] and abs(r["mean"]) > 0.1]
    print(f"   receptor residues with |mean| > 2 SEM and > 0.1 kcal/mol: {len(sig)}  "
          f"({', '.join(r['label'].split(':',1)[1] for r in sorted(sig, key=lambda r: r['mean'])[:10])}{' ...' if len(sig) > 10 else ''})")
    far = [r for r in prot if not np.isnan(r["occ"]) and r["occ"] < a.contact_pct and abs(r["mean"]) > 2.0]
    print(f"\nWARNING LIST: residues with |Delta| > 2 kcal/mol but contact occupancy < {a.contact_pct:g}% "
          f"(indirect / long-range electrostatic or solvation effect, NOT a direct contact): {len(far)}")
    for r in far[:12]:
        print(fmt(r))

    os.makedirs(a.out, exist_ok=True)
    outp = os.path.join(a.out, "decomp_delta_summary.csv")
    with open(outp, "w") as fh:
        fh.write("label,pdb_resnum,mean_total,sd,sem,vdw,ele,polar,nonpolar,internal,contact_window_pct\n")
        for r in rows:
            fh.write(f"{r['label']},{r['pdb']},{r['mean']:.3f},{r['sd']:.3f},{r['sem']:.3f},{r['vdw']:.3f},{r['ele']:.3f},"
                     f"{r['pol']:.3f},{r['npol']:.3f},{r['int']:.3f},{r['occ']:.1f}\n")
    print(f"\nwritten: {outp}")


if __name__ == "__main__":
    main()
