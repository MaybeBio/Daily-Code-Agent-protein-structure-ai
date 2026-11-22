#!/usr/bin/env python3
"""
audit_docking.py -- re-derive the docking statements of the manuscript from the raw AutoDock Vina files

Reads (all optional except --poses):
    --poses    docking_results.pdbqt          multi-model output of the blind docking (20 poses)
    --receptor receptor.pdbqt                  receptor used for docking (residue names / numbers = PDB numbering)
    --log      vina_log                        text log of the run (score table, version)
    --config   vina_config                     the configuration file (box centre / size, exhaustiveness)
    --poses2 / --log2                          the same for a second run (e.g. Vina 1.1.2 from the other laptop)

Prints
    1. the box and settings that were really used
    2. the score table (20 poses) and the energy gap between poses
    3. for the top pose: how many poses lie within 3 A (heavy-atom RMSD, no fitting) and a greedy clustering
       (so the sentence "8 of 20 poses within 3 A of the top pose / most populated cluster" can be checked)
    4. receptor residues in contact with the top pose (any heavy atoms closer than --cutoff, default 4.5 A) vs the nine residues
       of the manuscript, the closest approach to each of them, and the same for the top five poses
    5. if a second run is given: score agreement, pose RMSD between the two top poses, contact residues of both

Usage
-----
    python audit_docking.py --poses docking_results.pdbqt --receptor receptor.pdbqt --log vina_log --config vina_config
    python audit_docking.py --poses docking_results.pdbqt --receptor receptor.pdbqt --poses2 other/docking_results.pdbqt --log2 other/vina_log

Read-only.  Needs numpy only.
"""
import argparse
import os
import re
import sys

import numpy as np

MS_POCKET = {102: "THR", 104: "GLN", 110: "ARG", 111: "LEU", 126: "TYR", 131: "ASN", 268: "ASN", 269: "SER", 270: "PHE"}
MS_BOX_CENTER = (2.869, -0.294, 31.059)
MS_BOX_SIZE = (57, 49, 57)


def parse_atoms(lines):
    """-> list of dicts for ATOM/HETATM lines (PDBQT, fixed columns)."""
    out = []
    for ln in lines:
        if ln.startswith(("ATOM", "HETATM")):
            try:
                x, y, z = float(ln[30:38]), float(ln[38:46]), float(ln[46:54])
            except ValueError:
                continue
            t = ln[77:79].strip() if len(ln) >= 79 else ""
            name = ln[12:16].strip()
            hyd = t in ("H", "HD", "HS") or (not t and name.upper().startswith("H"))
            out.append({"name": name, "res": ln[17:20].strip(), "num": int(ln[22:26]), "xyz": (x, y, z), "H": hyd})
    return out


def read_poses(path):
    poses, cur, score, lb, ub = [], None, None, float("nan"), float("nan")
    with open(path) as fh:
        for ln in fh:
            if ln.startswith("MODEL"):
                cur, score = [], None
            elif ln.startswith("REMARK VINA RESULT"):
                f = ln.replace(":", " ").split()
                score = float(f[3])
                lb = float(f[4]) if len(f) > 4 else float("nan")
                ub = float(f[5]) if len(f) > 5 else float("nan")
            elif ln.startswith("ENDMDL"):
                at = parse_atoms(cur)
                poses.append({"score": score, "lb": lb, "ub": ub, "atoms": at})
                cur = None
            elif cur is not None:
                cur.append(ln)
    if not poses:
        sys.exit(f"no MODEL records found in {path}")
    return poses


INCLUDE_H = False


def heavy_xyz(p):
    return np.array([a["xyz"] for a in p["atoms"] if INCLUDE_H or not a["H"]], float)


def rmsd(a, b):
    return float(np.sqrt(((a - b) ** 2).sum(1).mean()))


def receptor_atoms(path):
    with open(path) as fh:
        at = parse_atoms(fh.readlines())
    return [a for a in at if INCLUDE_H or not a["H"]]


def min_dist_by_residue(pose_xyz, rec):
    rxyz = np.array([a["xyz"] for a in rec])
    d = np.sqrt(((pose_xyz[:, None, :] - rxyz[None, :, :]) ** 2).sum(-1)).min(0)
    out = {}
    for a_, dd in zip(rec, d):
        k = (a_["num"], a_["res"])
        out[k] = min(out.get(k, 1e9), float(dd))
    return out


def contacts(pose_xyz, rec, cutoff=4.5):
    rxyz = np.array([a["xyz"] for a in rec])
    d = np.sqrt(((pose_xyz[:, None, :] - rxyz[None, :, :]) ** 2).sum(-1))
    close = np.where((d <= cutoff).any(0))[0]
    return sorted({(rec[i]["num"], rec[i]["res"]) for i in close})


def read_log(path):
    ver, table = None, []
    with open(path, errors="replace") as fh:
        for ln in fh:
            if re.search(r"AutoDock Vina", ln) and ver is None:
                ver = ln.strip()
            m = re.match(r"^\s*(\d+)\s+(-?\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s*$", ln)
            if m:
                table.append((int(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))))
    return ver, table


def describe(label, poses_path, rec, log_path, a):
    print("\n" + "=" * 90)
    print(f"{label}: {poses_path}")
    print("=" * 90)
    poses = read_poses(poses_path)
    scores = [p["score"] for p in poses]
    n = len(poses)
    print(f"  models: {n}   heavy atoms of the ligand: {len(heavy_xyz(poses[0]))}")
    print("  scores (kcal/mol): " + "  ".join(f"{s:.2f}" for s in scores[:12]) + (" ..." if n > 12 else ""))
    lbs = np.array([p["lb"] for p in poses])
    ubs = np.array([p["ub"] for p in poses])
    print(f"  Vina's own symmetry-aware RMSD to the best mode (REMARK lines of the pdbqt): "
          f"l.b. <= 3.0 A in {int((lbs <= 3.0).sum())} of {n} models, u.b. <= 3.0 A in {int((ubs <= 3.0).sum())} of {n}")
    if log_path and os.path.exists(log_path):
        ver, table = read_log(log_path)
        print(f"  log: {ver}")
        if table:
            m = min(len(table), n)
            same = all(abs(t[1] - s_) < 0.006 for t, s_ in zip(table[:m], scores[:m]))
            print(f"  log score table: {len(table)} rows (pdbqt has {n} models); the first {m} rows are identical to the pdbqt scores: "
                  f"{'yes' if same else 'NO (check which file belongs to which run)'}")
            if len(table) < n:
                print(f"  note: the table of the log misses {n - len(table)} row(s) of the pdbqt (my parser needs the standard 4-column rows; "
                      "look at the end of the table in the log file)")
    xyz = [heavy_xyz(p) for p in poses]
    d_top = [rmsd(xyz[0], x) for x in xyz]
    print(f"  heavy-atom RMSD of every pose to the top pose (A): " + " ".join(f"{d:.1f}" for d in d_top[:12]) + (" ..." if n > 12 else ""))
    within3 = sum(1 for d in d_top if d <= 3.0)
    print(f"  poses within 3.0 A of the top pose (including itself): {within3} of {n}")
    # greedy clustering at 3 A, in score order
    seeds, members = [], []
    for i in range(n):
        for k, s in enumerate(seeds):
            if rmsd(xyz[s], xyz[i]) <= 3.0:
                members[k].append(i)
                break
        else:
            seeds.append(i)
            members.append([i])
    order = sorted(range(len(seeds)), key=lambda k: -len(members[k]))
    print(f"  greedy clusters (3.0 A, seeds in score order): {len(seeds)}")
    for k in order[:5]:
        print(f"     seed model {seeds[k] + 1:2d}  score {scores[seeds[k]]:.2f}  size {len(members[k])}")
    big = order[0]
    print(f"  top-scoring pose belongs to the most populated cluster: {'yes' if 0 in members[big] else 'NO'}")
    if rec is not None:
        print(f"\n  contact residues (any {'atoms' if INCLUDE_H else 'heavy atoms'} < {a.cutoff:g} A):")
        pocket = set(MS_POCKET)
        for m in range(min(5, n)):
            c = contacts(xyz[m], rec, a.cutoff)
            nums = {x[0] for x in c}
            hit = sorted(pocket & nums)
            extra = sorted(nums - pocket)
            print(f"     pose {m + 1} (score {scores[m]:.2f}): {len(c)} residues; manuscript pocket residues in contact: {len(hit)}/9 {hit}")
            if m == 0:
                md = min_dist_by_residue(xyz[0], rec)
                print("        closest approach (A) of pose 1 to each manuscript pocket residue: " +
                      "  ".join(f"{MS_POCKET[n].title()}{n}:{md[(n, MS_POCKET[n])]:.2f}" for n in MS_POCKET if (n, MS_POCKET[n]) in md))
                sg = {n: [a_["xyz"] for a_ in rec if a_["num"] == n and a_["name"] == "SG"] for n in (124, 277)}
                for n, lst in sg.items():
                    if lst:
                        dd = np.sqrt(((xyz[0][:, None, :] - np.array(lst)[None, :, :]) ** 2).sum(-1)).min()
                        print(f"        closest approach of pose 1 to Cys{n} SG: {dd:.2f} A")
                print("        all contact residues of pose 1: " + " ".join(f"{r.title()}{nu}" for nu, r in c))
                print(f"        extra residues not in the manuscript list: {extra}")
                miss = sorted(pocket - nums)
                if miss:
                    print(f"        manuscript residues NOT in contact: {miss}")
    return poses, xyz


def scan_cutoffs(pose, rec_all):
    """Which distance criterion gives exactly the nine manuscript residues?  (pose 1; heavy-only and with polar H)"""
    print("\n  SCAN: contact residues of pose 1 for different cut-offs")
    target = set(MS_POCKET)
    for lab, use_h in (("heavy atoms only", False), ("with polar H", True)):
        pxyz = np.array([a_["xyz"] for a_ in pose["atoms"] if use_h or not a_["H"]], float)
        rec = [a_ for a_ in rec_all if use_h or not a_["H"]]
        md = min_dist_by_residue(pxyz, rec)
        hits = []
        for c in np.arange(3.5, 6.01, 0.1):
            s_ = {n for (n, _), d in md.items() if d <= c}
            if s_ == target:
                hits.append(round(float(c), 1))
        print(f"   {lab}:")
        for c in (4.0, 4.5, 5.0, 5.5, 6.0):
            s_ = sorted(n for (n, _), d in md.items() if d <= c)
            print(f"      cut-off {c:.1f} A: {len(s_):2d} residues  {s_}")
        print(f"      cut-offs (3.5-6.0 A, step 0.1) that give EXACTLY the nine manuscript residues: {hits if hits else 'none'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--poses", required=True)
    ap.add_argument("--receptor")
    ap.add_argument("--log")
    ap.add_argument("--config")
    ap.add_argument("--poses2")
    ap.add_argument("--log2")
    ap.add_argument("--cutoff", type=float, default=4.5, help="contact cutoff in A (default 4.5)")
    ap.add_argument("--include-h", action="store_true", help="count polar hydrogens (HD) of ligand and receptor too")
    ap.add_argument("--scan", action="store_true", help="scan the contact cut-off and report which criterion gives exactly the nine manuscript residues")
    a = ap.parse_args()
    global INCLUDE_H
    INCLUDE_H = a.include_h
    for flag_, path_ in (("--config", a.config), ("--log", a.log), ("--receptor", a.receptor), ("--poses", a.poses),
                         ("--poses2", a.poses2), ("--log2", a.log2)):
        if path_ and not os.path.exists(path_):
            sys.exit(f"ERROR: {flag_} file not found: {path_}\n(find it with: ls -l *vina* *.pdbqt)")

    if a.config and os.path.exists(a.config):
        print("=" * 90)
        print(f"search box / settings in {a.config}")
        print("=" * 90)
        txt = open(a.config).read()
        for ln in txt.splitlines():
            if ln.strip() and not ln.strip().startswith("#"):
                print("   " + ln.strip())
        vals = {}
        for k in ("center_x", "center_y", "center_z", "size_x", "size_y", "size_z", "exhaustiveness", "num_modes"):
            m = re.search(rf"^\s*{k}\s*=\s*(-?\d+\.?\d*)", txt, re.M)
            if m:
                vals[k] = float(m.group(1))
        if all(k in vals for k in ("center_x", "center_y", "center_z")):
            c = (vals["center_x"], vals["center_y"], vals["center_z"])
            print(f"   centre {c}  manuscript {MS_BOX_CENTER}  -> {'OK' if all(abs(x - y) < 0.01 for x, y in zip(c, MS_BOX_CENTER)) else 'DIFFERENT'}")
        if all(k in vals for k in ("size_x", "size_y", "size_z")):
            s = (vals["size_x"], vals["size_y"], vals["size_z"])
            print(f"   size   {s}  manuscript {MS_BOX_SIZE}  -> {'OK' if all(abs(x - y) < 0.5 for x, y in zip(s, MS_BOX_SIZE)) else 'DIFFERENT'}")
        print(f"   exhaustiveness {vals.get('exhaustiveness', '?')} (manuscript 32), num_modes {vals.get('num_modes', '?')} (manuscript: 20 poses)")

    rec = receptor_atoms(a.receptor) if a.receptor and os.path.exists(a.receptor) else None
    if rec is not None:
        nums = sorted({x["num"] for x in rec})
        print(f"\nreceptor: {len(rec)} heavy atoms, residues {nums[0]}-{nums[-1]} ({len(nums)} residues)")
        chk = {n: next((x['res'] for x in rec if x['num'] == n), None) for n in MS_POCKET}
        bad = [n for n in MS_POCKET if chk[n] != MS_POCKET[n]]
        print(f"receptor residue names at the nine pocket numbers match the manuscript: {'yes' if not bad else 'NO ' + str(bad)}")
    p1, x1 = describe("RUN 1 (primary)", a.poses, rec, a.log, a)
    if a.scan and a.receptor:
        with open(a.receptor) as fh:
            scan_cutoffs(p1[0], parse_atoms(fh.readlines()))
    if a.poses2:
        p2, x2 = describe("RUN 2 (second engine)", a.poses2, rec, a.log2, a)
        print("\n" + "=" * 90)
        print("COMPARISON of the two runs")
        print("=" * 90)
        print(f"  top scores: {p1[0]['score']:.2f} vs {p2[0]['score']:.2f}")
        if len(x1[0]) == len(x2[0]):
            print(f"  heavy-atom RMSD between the two top poses: {rmsd(x1[0], x2[0]):.2f} A")
        n = min(len(p1), len(p2), 10)
        print("  scores of the first 10 poses: " + " | ".join(f"{p1[i]['score']:.2f}/{p2[i]['score']:.2f}" for i in range(n)))
        print("  (identical scores AND poses are expected if both versions use the same scoring function; "
              "that would be a reproducibility check of the software, not independent validation)")


if __name__ == "__main__":
    main()
