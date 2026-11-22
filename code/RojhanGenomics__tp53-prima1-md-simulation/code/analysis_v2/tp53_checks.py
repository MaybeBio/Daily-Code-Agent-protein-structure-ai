#!/usr/bin/env python3
"""
tp53_checks.py (v2) -- verification checks for the PRIMA-1 / p53 DBD MD manuscript
===================================================================================

CHECK 1  (`extract-eint` then `ie`)
    Re-computes the Interaction-Entropy term from the per-frame gas-phase interaction
    energy (vdW + electrostatic).  By Jensen's inequality kT*ln<exp(beta*(E-<E>))> is
    always >= 0, so -T*dS must be >= 0 (unfavourable); the manuscript reports -3.87.

CHECK 2  (`md`)
    Ligand--pocket distances with the MINIMUM-IMAGE convention for every system,
    compared with the "naive" distance on the stored coordinates; minimum heavy-atom
    distance to the nine pocket residues; distance to Cys124/Cys277 SG; minimum
    distance to ANY protein atom; protein/periodic-image gap; ligand RMSD after
    C-alpha fit; first STABLE exit; longest contact interval.  Residue numbering
    (internal 1..194 vs PDB 96..289) is verified by residue NAMES first.

CHECK 3  (`md`, same run)
    Per-residue heavy-atom contact occupancy (cutoff 4.5 A, as in the PRIMA-1 scripts),
    in the MM-PBSA window and over the whole run, plus pose RMSD between two replicates.

v2 additions
------------
  * `extract-eint`  builds the per-frame vdW+ele energy file from the raw sander mdout files
                    (complex - receptor - ligand) and verifies it against the published mean
                    dE_vdW / dE_ele before the IE test is run.
  * --tmax          exact cut (default 20 ns); duplicate / non-monotonic frame times are
                    reported and dropped.
  * extra metrics   see CHECK 2; table1_summary.csv is written for the revised Table 1.
  * `compare-csv`   compares two gmx_MMPBSA per-frame CSVs on their common frames (validates a re-run).

Usage
-----
    conda activate tp53_md            # numpy + MDAnalysis>=2.1 (matplotlib optional)

    python tp53_checks.py selftest
    python tp53_checks.py md --root ~/tp53_md_project --plot
    python tp53_checks.py extract-eint --mdout-dir ~/tp53_md_project/run1_20ns --eint-out run1_eint.txt
    python tp53_checks.py ie --ie-file run1_eint.txt --reported-ie -3.87

Outputs go to ./analysis_checks/.  Nothing here modifies your original files.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

import numpy as np

# ----------------------------------------------------------------------------
# Constants / project-specific defaults  (edit here if your layout differs)
# ----------------------------------------------------------------------------
KB = 0.0019872041                      # kcal / (mol K)
OFFSET = 95                            # PDB number = internal resid + 95  (2OCJ chain A, 96-289)

POCKET = {102: "THR", 104: "GLN", 110: "ARG", 111: "LEU", 126: "TYR",
          131: "ASN", 268: "ASN", 269: "SER", 270: "PHE"}
EXTRA = {124: "CYS", 277: "CYS", 239: "ASN", 267: "ARG"}

PROT_SEL = "protein or resname HIE HID HIP HISE HISD HISH CYM CYX ASH GLH LYN"
NOT_LIGAND = (f"({PROT_SEL}) or resname SOL HOH WAT TIP3 TIP4 NA CL K ZN ZN2 "
              "CLA SOD POT NA+ CL- K+")

DEFAULT_SYSTEMS = {
    "Run1":    ("md.tpr",                                      "run1_20ns/md_fixed.xtc"),
    "Run2":    ("md_run2.tpr",                                 "run2_20ns/md_run2_fixed.xtc"),
    "Run3":    ("md_run3.tpr",                                 "run3_20ns/md_run3_fixed.xtc"),
    "Run4":    ("run4_20ns/md_run4.tpr",                       "run4_20ns/md_run4_fixed.xtc"),
    "NegCtrl": ("negative_control/v2_correct/md_negctrl.tpr",
                "negative_control/v2_correct/md_negctrl_final_fixed.xtc"),
}


# ----------------------------------------------------------------------------
# numerical helpers
# ----------------------------------------------------------------------------
def mic_vec(v, box):
    """Minimum-image of vectors (orthorhombic box, same units)."""
    return v - box * np.round(v / box)


def kabsch(P, Q):
    """Return (R, Pc, Qc) with (P - Pc) @ R ~= (Q - Qc), proper rotation."""
    Pc, Qc = P.mean(0), Q.mean(0)
    H = (P - Pc).T @ (Q - Qc)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(U @ Vt))
    return U @ np.diag([1.0, 1.0, d]) @ Vt, Pc, Qc


def ie_from_series(E, T=300.0):
    """kT ln< exp(beta (E-<E>)) >  (numerically stable).  Always >= 0."""
    kT = KB * T
    x = (np.asarray(E, float) - np.mean(E)) / kT
    m = x.max()
    return kT * (m + np.log(np.mean(np.exp(x - m))))


def frac(mask):
    return 100.0 * float(np.mean(mask)) if len(mask) else float("nan")


def bool_runs(mask):
    """List of (start, end_inclusive) index pairs of consecutive True values."""
    d = np.diff(np.r_[0, np.asarray(mask, int), 0])
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0] - 1))


def run_stats(t, in_contact, cut_ns):
    """First stable exit (>= cut_ns continuously out of contact AFTER the first contact),
    longest contact interval, number of exits."""
    in_contact = np.asarray(in_contact, bool)
    dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.0
    if not in_contact.any():
        return float("nan"), 0.0, 0
    first_in = int(np.argmax(in_contact))
    out_runs = [(s, e) for s, e in bool_runs(~in_contact) if s > first_in]
    exit_t = float("nan")
    for s, e in out_runs:
        if t[e] - t[s] + dt >= cut_ns - 1e-9:
            exit_t = float(t[s])
            break
    longest = max((t[e] - t[s] + dt for s, e in bool_runs(in_contact)), default=0.0)
    return exit_t, float(longest), len(out_runs)


def rmsd_matrix(X, Y):
    """RMSD (same units as input) between every pose of X (nx,n,3) and Y (ny,n,3); no fitting."""
    return np.sqrt(((X[:, None] - Y[None]) ** 2).sum(-1).mean(-1))


# ----------------------------------------------------------------------------
# CHECK 1a : build per-frame E_int from sander mdout files
# ----------------------------------------------------------------------------
_RE_VDW = re.compile(r"VDWAALS\s*=\s*(-?\d+\.\d+)")
_RE_EEL = re.compile(r"(?<!1-4 )\bEEL\s*=\s*(-?\d+\.\d+)")


_RE_META = {"run_on": re.compile(r"\|\s*Run on\s+(.+)"),
            "parm": re.compile(r"\|\s*PARM:\s*(\S+)"),
            "inptra": re.compile(r"\|INPTRA:\s*(\S+)"),
            "natom": re.compile(r"NATOM\s*=\s*(\d+)"),
            "nres": re.compile(r"NRES\s*=\s*(\d+)")}


def _meta(path):
    """Header facts of a sander mdout (date, parm file, trajectory, NATOM, NRES)."""
    out, txt = {}, ""
    with open(path, errors="replace") as fh:
        for _, line in zip(range(200), fh):
            txt += line
    for k, rx in _RE_META.items():
        m = rx.search(txt)
        out[k] = m.group(1).strip() if m else None
    return out


def _mdout_files(d, kind):
    fs = glob.glob(os.path.join(d, f"_GMXMMPBSA_{kind}_pb.mdout.*"))

    def key(f):
        tail = f.rsplit(".", 1)[-1]
        return int(tail) if tail.isdigit() else 10 ** 9
    return sorted(fs, key=key)


def _read_series(files):
    vdw, eel = [], []
    for f in files:
        with open(f, errors="replace") as fh:
            txt = fh.read()
        vdw += [float(x) for x in _RE_VDW.findall(txt)]
        eel += [float(x) for x in _RE_EEL.findall(txt)]
    return np.array(vdw), np.array(eel)


def run_extract(a):
    print("\n" + "=" * 78)
    print("EXTRACT per-frame vdW + ele (delta = complex - receptor - ligand) from sander mdout")
    print("=" * 78)
    d = os.path.expanduser(a.mdout_dir)
    series, meta = {}, {}
    for kind in ("complex", "receptor", "ligand"):
        fs = _mdout_files(d, kind)
        if not fs:
            sys.exit(f"No files _GMXMMPBSA_{kind}_pb.mdout.* in {d}\n"
                     "(run from the folder where gmx_MMPBSA ran, e.g. run1_20ns, or use --mdout-dir)")
        v, e = _read_series(fs)
        meta[kind] = _meta(fs[0])
        m = meta[kind]
        print(f"  {kind:9s}: {len(fs)} file(s), {len(v)} VDWAALS / {len(e)} EEL records | "
              f"run on {m['run_on']} | NATOM {m['natom']} NRES {m['nres']}")
        print(f"             parm={m['parm']}  traj={m['inptra']}")
        if len(v) != len(e) or len(v) == 0:
            _show_snippet(fs[0])
            sys.exit(f"  !! unexpected record counts for {kind}; see snippet above and send it to me")
        series[kind] = (v, e)
    n = {k: len(v[0]) for k, v in series.items()}
    if len(set(n.values())) != 1:
        sys.exit(f"  !! different frame counts {n}; the three runs must have the same frames")
    nfr = n["complex"]
    if a.expect_frames and nfr != a.expect_frames:
        print(f"  [warn] {nfr} frames found, expected {a.expect_frames}")
        if nfr > a.expect_frames and nfr % a.expect_frames == 0:
            print(f"  NOTE: {nfr} = {nfr // a.expect_frames} x {a.expect_frames}: these look like DECOMPOSITION outputs "
                  "(several energy tables per frame). Total energies cannot be extracted from them with this tool, so the "
                  "energy-based checks below are NOT meaningful for this folder. Header information (NATOM / NRES) is still valid.")

    print("\n  per-kind means (kcal/mol):")
    for kind, (v, e) in series.items():
        print(f"    {kind:9s} VDW {v.mean():12.2f} +- {v.std(ddof=1):8.2f}   EEL {e.mean():12.2f} +- {e.std(ddof=1):8.2f}")
    problems = []
    try:
        na = {k: int(meta[k]["natom"]) for k in meta}
        if na["complex"] != na["receptor"] + na["ligand"]:
            problems.append(f"NATOM complex ({na['complex']}) != receptor ({na['receptor']}) + ligand ({na['ligand']})")
    except (TypeError, ValueError):
        pass
    # the three sander runs of ONE gmx_MMPBSA job start at different times (sequential): only a different DATE is suspicious
    dates = {meta[k]["run_on"].split(" at ")[0] for k in meta if meta[k]["run_on"]}
    if len(dates) > 1:
        problems.append(f"the three files were written on different days {sorted(dates)} (mixed jobs?)")
    try:
        if int(meta["ligand"]["natom"]) != a.expect_ligand_atoms or int(meta["ligand"]["nres"]) != 1:
            problems.append(f"ligand group has {meta['ligand']['natom']} atoms / {meta['ligand']['nres']} residues, expected "
                            f"{a.expect_ligand_atoms} atoms / 1 residue -> another molecule (e.g. the Zn2+ ion) is probably inside the ligand group")
    except (TypeError, ValueError):
        pass
    if series["ligand"][0].mean() > 500 or series["complex"][0].mean() > 0:
        problems.append("unphysical absolute energies (positive vdW of a bound complex / small ligand, > +500 kcal/mol): "
                        "coordinates and topology do not match (atom order or wrong prmtop)")
    dv = series["complex"][0] - series["receptor"][0] - series["ligand"][0]
    de = series["complex"][1] - series["receptor"][1] - series["ligand"][1]
    r_cr = float(np.corrcoef(series["complex"][0], series["receptor"][0])[0, 1])
    print(f"\n  frame-matching test: corr(VDW complex, VDW receptor) = {r_cr:.3f}   "
          f"(should be ~1 if the three runs use the same frames)")
    print(f"  delta: dE_vdW = {dv.mean():9.3f} +- {dv.std(ddof=1):.3f}   dE_ele = {de.mean():9.3f} +- {de.std(ddof=1):.3f} kcal/mol")
    print(f"  manuscript:  dE_vdW = {a.expect_vdw:+.2f}   dE_ele = {a.expect_ele:+.2f}")
    if dv.std(ddof=1) > 10 or de.std(ddof=1) > 10:
        problems.append("frame-to-frame SD of the delta is >> 10 kcal/mol: complex/receptor/ligand frames are not matched")
    ok = (abs(dv.mean() - a.expect_vdw) < 0.05 and abs(de.mean() - a.expect_ele) < 0.05)
    if not ok:
        problems.append("delta means do not reproduce the published MM-PBSA means")
    if problems:
        print("\n  RESULT: NOT VERIFIED")
        for p_ in problems:
            print("   -", p_)
    else:
        print("\n  RESULT: OK - extraction reproduces the published MM-PBSA means")
    if problems and not a.force:
        print("  No energy file was written (use --force only for debugging).")
        return
    out = os.path.expanduser(a.eint_out)
    np.savetxt(out, np.column_stack([dv, de]), fmt="%.5f",
               header="dE_vdW dE_ele (kcal/mol), per frame, delta = complex - receptor - ligand")
    print(f"  written: {out}   (columns: vdW, ele -> the `ie` command sums them)")


def _show_snippet(path):
    print(f"  --- first lines containing energies in {path} ---")
    k = 0
    with open(path, errors="replace") as fh:
        for line in fh:
            if any(w in line for w in ("VDWAALS", "EEL", "BOND", "NSTEP")):
                print("   ", line.rstrip())
                k += 1
                if k >= 14:
                    break


# ----------------------------------------------------------------------------
# CHECK 1b : interaction entropy
# ----------------------------------------------------------------------------
def _num(s):
    try:
        return float(s)
    except ValueError:
        return None


def parse_gmx_mmpbsa_csv(path):
    """Best-effort parser of the per-frame CSV from gmx_MMPBSA (-eo): 'Delta' section, VDWAALS+EEL."""
    sections, cur, header = {}, None, None
    with open(path) as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            nums = [_num(p) for p in parts]
            if all(n is None for n in nums):
                if len(parts) == 1 or all(p == "" for p in parts[1:]):
                    cur, header = parts[0], None
                    sections.setdefault(cur, {})
                else:
                    header = parts
                    sections.setdefault(cur or "", {})
                    for h in header[1:]:
                        sections[cur or ""].setdefault(h, [])
            elif header is not None and cur is not None:
                for h, n in zip(header, nums):
                    if h.lower() in ("frame #", "frame"):
                        if n is not None:
                            sections[cur].setdefault("__FRAME__", []).append(n)
                    elif h and n is not None:
                        sections[cur].setdefault(h, []).append(n)
    cols = {}
    for title, d in sections.items():
        if "delta" in title.lower():
            for k, v in d.items():
                cols.setdefault(k.upper(), np.array(v, float))
    vdw = next((cols[k] for k in ("VDWAALS", "VDW", "EVDW") if k in cols), None)
    ele = next((cols[k] for k in ("EEL", "EELEC", "ELE") if k in cols), None)
    parse_gmx_mmpbsa_csv.cols = cols
    if vdw is None or ele is None or len(vdw) != len(ele):
        raise ValueError("Could not find VDWAALS and EEL in the 'Delta' section of the CSV "
                         f"(sections found: {list(sections)[:6]}). Send me the first ~30 lines of the file.")
    return vdw, ele


def load_eint(path, col=None):
    """Return (E_int per frame, (vdw, ele) or None).  CSV from gmx_MMPBSA is parsed by section."""
    if path.lower().endswith(".csv"):
        vdw, ele = parse_gmx_mmpbsa_csv(path)
        return vdw + ele, (vdw, ele)
    data = np.loadtxt(path, comments=("#", "@"))
    if data.ndim == 1:
        return data, None
    if col is not None:
        return data[:, col], None
    if data.shape[1] == 2:
        print("  [info] 2 columns found -> using vdW + ele")
        return data[:, 0] + data[:, 1], (data[:, 0], data[:, 1])
    if data.shape[1] == 3:
        print("  [info] 3 columns found -> using column1 + column2; use --ie-col to override")
        return data[:, 1] + data[:, 2], (data[:, 1], data[:, 2])
    raise ValueError("More than 3 columns: choose one with --ie-col")


def _delta_cols(path):
    parse_gmx_mmpbsa_csv(path)
    return dict(parse_gmx_mmpbsa_csv.cols)


def run_compare(a):
    print("\n" + "=" * 78)
    print("COMPARE two gmx_MMPBSA per-frame CSV files on their common frames (Delta section)")
    print("=" * 78)
    A, B = _delta_cols(os.path.expanduser(a.csv_a)), _delta_cols(os.path.expanduser(a.csv_b))
    if "__FRAME__" not in A or "__FRAME__" not in B:
        sys.exit("frame numbers not found in one of the files ('Frame #' column)")
    fa = {int(f): i for i, f in enumerate(A["__FRAME__"])}
    fb = {int(f): i for i, f in enumerate(B["__FRAME__"])}
    common = sorted(set(fa) & set(fb))
    print(f"  {a.csv_a}: {len(fa)} frames | {a.csv_b}: {len(fb)} frames | common frames: {len(common)}")
    if not common:
        sys.exit("  no common frames: use the same startframe/interval grid (e.g. interval a multiple of 5)")
    worst = 0.0
    for col in ("VDWAALS", "EEL", "EPB", "ENPOLAR", "GGAS", "GSOLV", "TOTAL"):
        if col in A and col in B:
            d = np.array([A[col][fa[f]] - B[col][fb[f]] for f in common])
            worst = max(worst, float(np.abs(d).max()))
            print(f"   {col:8s} max |diff| = {np.abs(d).max():8.3f}   mean diff = {d.mean():+8.3f}   "
                  f"(A mean {np.mean([A[col][fa[f]] for f in common]):9.3f}, B mean {np.mean([B[col][fb[f]] for f in common]):9.3f})")
    print("\n  VERDICT:", "IDENTICAL within rounding - same topology, coordinates and settings reproduce the original run"
          if worst < a.tol else
          f"DIFFERENT (largest difference {worst:.2f} kcal/mol > tolerance {a.tol}) - something differs "
          "(topology, atom order, frames, radii or PB settings)")


def block_resample(n, blk, rng):
    """Index array of length n built from random contiguous blocks (keeps autocorrelation)."""
    nb = int(np.ceil(n / blk))
    st = rng.integers(0, n - blk + 1, size=nb)
    return np.concatenate([np.arange(s, s + blk) for s in st])[:n]


def bootstrap_dG(E, dH, T, seg_frac, blk=5, nboot=3000, seed=1):
    """Joint block-bootstrap of IE and mean dH over the same last-seg_frac frames."""
    rng = np.random.default_rng(seed)
    n = len(E)
    k = max(2 * blk, int(round(n * seg_frac)))
    Es, Hs = np.asarray(E)[-k:], np.asarray(dH)[-k:]
    ie, dg = [], []
    for _ in range(nboot):
        idx = block_resample(k, blk, rng)
        i_ = ie_from_series(Es[idx], T)
        ie.append(i_)
        dg.append(Hs[idx].mean() + i_)
    q = lambda v: np.percentile(v, [2.5, 50, 97.5])
    return q(ie), q(dg)


def run_ie(a):
    print("\n" + "=" * 78)
    print("CHECK 1 -- interaction entropy sign / magnitude")
    print("=" * 78)
    path = os.path.expanduser(a.ie_file)
    if not os.path.exists(path):
        sys.exit(f"{path} not found. Create it first:\n"
                 "  python tp53_checks.py extract-eint --mdout-dir <folder with _GMXMMPBSA_*.mdout.*> "
                 f"--eint-out {a.ie_file}")
    E, comps = load_eint(path, a.ie_col)
    n = len(E)
    if comps is not None:
        dv, de = comps
        okv = abs(dv.mean() - a.expect_vdw) < 0.05 and abs(de.mean() - a.expect_ele) < 0.05
        print(f"  file check: {n} frames; mean dE_vdW = {dv.mean():.3f}, dE_ele = {de.mean():.3f} "
              f"(manuscript {a.expect_vdw:+.2f} / {a.expect_ele:+.2f}) -> {'MATCH' if okv else 'NO MATCH'}")
        if not okv and not a.force:
            sys.exit("  This file does not reproduce the published MM-PBSA means, so it is NOT the series behind "
                     "the manuscript (or it is corrupted). Stopping. (--force to ignore, for debugging only)")
    else:
        print("  [info] plain-text series: its origin cannot be verified automatically")
    nseg = max(2, int(round(n * a.ie_segment / 100.0)))
    seg = E[-nseg:]
    kT = KB * a.temp
    ie_seg = ie_from_series(seg, a.temp)
    print(f"frames: {n}   segment: last {a.ie_segment:g}% = {nseg} frames   T = {a.temp:g} K")
    print(f"<E_int> all frames : {E.mean():9.3f} +- {E.std(ddof=1):.3f} kcal/mol")
    print(f"<E_int> segment    : {seg.mean():9.3f} +- {seg.std(ddof=1):.3f} kcal/mol")
    print(f"\n-T*dS (IE, kT ln<exp(b dE)>), segment : {ie_seg:+8.3f} kcal/mol  (mathematically >= 0)")
    print(f"Gaussian estimate  b*sigma^2/2         : {0.5*seg.var(ddof=1)/kT:+8.3f} kcal/mol")
    print("\nSensitivity to segment length:")
    for pct in (10, 25, 50, 100):
        k = max(2, int(round(n * pct / 100.0)))
        print(f"   last {pct:3d}% ({k:3d} frames): -T*dS = {ie_from_series(E[-k:], a.temp):+8.3f}")
    print("Quartile blocks (-T*dS of each block):",
          "  ".join(f"{ie_from_series(b, a.temp):+.2f}" for b in np.array_split(E, 4)))

    rep = a.reported_ie
    print(f"\nValue reported in the manuscript: -T*dS = {rep:+.2f} kcal/mol")
    if rep < 0 <= ie_seg:
        if abs(ie_seg - abs(rep)) <= 0.5:
            print(f"  VERDICT: magnitude matches but the SIGN is opposite. -T*dS must be +{ie_seg:.2f} "
                  "kcal/mol (unfavourable); the manuscript sign is wrong.")
        else:
            print("  VERDICT: the reported value is negative, impossible for this definition, AND the "
                  "magnitude does not match this series. Check the energy terms / segment / frames.")
    elif abs(ie_seg - rep) <= 0.5:
        print("  VERDICT: consistent with the manuscript.")
    else:
        print("  VERDICT: values differ; re-check energy terms, segment and temperature.")
    print("\nCorrected effective free-energy estimates (dH + (-T*dS)):")
    print(f"   dH(segment) {a.dh_segment:+.2f} + {ie_seg:+.2f} = {a.dh_segment + ie_seg:+.2f} kcal/mol "
          "(same frames for dH and IE)")
    print(f"   dH(10-20ns) {a.dh_full:+.2f} + {ie_seg:+.2f} = {a.dh_full + ie_seg:+.2f} kcal/mol")
    print("   (manuscript currently: -14.90)")

    out = {"ie_segment_kcal": float(ie_seg), "n_frames": int(n), "segment_frames": int(nseg),
           "dG_eff_segment": float(a.dh_segment + ie_seg), "dG_eff_full": float(a.dh_full + ie_seg)}
    cols = getattr(parse_gmx_mmpbsa_csv, "cols", None) if path.lower().endswith(".csv") else None
    if cols and "TOTAL" in cols and len(cols["TOTAL"]) == n:
        tot = cols["TOTAL"]
        print("\nDelta energy terms from the file (mean +- SD, SEM = SD/sqrt(N); kcal/mol):")
        for k in ("VDWAALS", "EEL", "EPB", "ENPOLAR", "ECAVITY", "EDISPER", "GGAS", "GSOLV", "TOTAL"):
            if k in cols and len(cols[k]) == n:
                v = cols[k]
                print(f"   {k:8s} {v.mean():9.3f} +- {v.std(ddof=1):6.3f}   SEM {v.std(ddof=1)/np.sqrt(n):.3f}")
        print("   TOTAL in 4 sequential blocks:", "  ".join(f"{b.mean():+.2f}+-{b.std(ddof=1):.2f}" for b in np.array_split(tot, 4)))
        # effective sample size from lag-1 autocorrelation
        x = tot - tot.mean()
        r1 = float(np.dot(x[:-1], x[1:]) / np.dot(x, x))
        neff = n * (1 - r1) / (1 + r1) if r1 > 0 else n
        print(f"   lag-1 autocorrelation of TOTAL = {r1:.2f} -> effective N ~ {neff:.0f}; "
              f"SEM(corrected) = {tot.std(ddof=1)/np.sqrt(neff):.2f} kcal/mol")
        print("\nInteraction-entropy corrected free energy with block-bootstrap 95% intervals (block = 5 frames):")
        for frac_, lab in ((a.ie_segment / 100.0, f"last {a.ie_segment:g}%"), (1.0, "all frames")):
            iq, dq = bootstrap_dG(E, tot, a.temp, frac_)
            k = max(10, int(round(n * frac_)))
            print(f"   {lab:11s} ({k:3d} frames): -T*dS = {ie_from_series(E[-k:], a.temp):+6.2f}  [{iq[0]:+.1f}, {iq[2]:+.1f}]"
                  f"   dG_eff = {tot[-k:].mean() + ie_from_series(E[-k:], a.temp):+6.2f}  [{dq[0]:+.1f}, {dq[2]:+.1f}] kcal/mol")
            out[f"dG_eff_{'seg' if frac_ < 1 else 'all'}_ci95"] = [float(dq[0]), float(dq[2])]
        print("   (an interval that contains 0 means no net favourable binding free energy can be claimed)")
    return out


# ----------------------------------------------------------------------------
# CHECK 2 + 3 : geometry
# ----------------------------------------------------------------------------
def _name_ok(have, want):
    have = have.upper()
    return have.startswith("CY") if want == "CYS" else have[:3] == want


def resolve_numbering(u, wanted):
    prot = u.select_atoms(PROT_SEL)
    names = {int(r.resid): r.resname for r in prot.residues}
    for shift, label in ((OFFSET, "internal numbering (resid = PDB - 95)"),
                         (0, "PDB numbering (resid = PDB)")):
        if all(_name_ok(names.get(p - shift, ""), n) for p, n in wanted.items()):
            return shift, label, names
    return None, None, names


def describe_wrong_lists(names):
    return "; ".join(f"resid {r}={names.get(r, '?')} (PDB {r + OFFSET})"
                     for r in (102, 110, 111, 113, 126, 131))


def select_frames(times_ps, tmax_ns, stride):
    """Indices of frames with 0<=t<=tmax, strictly increasing time (first occurrence kept)."""
    keep, last, dup, back, beyond = [], -np.inf, 0, 0, 0
    for i, tp in enumerate(times_ps):
        if tp > tmax_ns * 1000.0 + 1e-6:
            beyond += 1
            continue
        if tp <= last + 1e-6:
            if abs(tp - last) <= 1e-6:
                dup += 1
            else:
                back += 1
            continue
        keep.append(i)
        last = tp
    return keep[::stride], dup, back, beyond


def analyse_system(name, top, traj, a, ctx):
    import MDAnalysis as mda
    from MDAnalysis.lib.distances import distance_array

    print("\n" + "-" * 78)
    print(f"[{name}]  top={top}\n         traj={traj}")
    u = mda.Universe(top, traj)
    if not hasattr(u, "bonds") or len(u.bonds) == 0:
        try:
            u.atoms.guess_bonds()
        except Exception as e:                              # pragma: no cover
            print(f"  [warn] no bonds and guess_bonds failed ({e}); molecules will not be unwrapped")

    wanted = {**POCKET, **EXTRA}
    shift, label, names = resolve_numbering(u, wanted)
    if shift is None:
        print("  !! Residue names do not match the expected residues under either numbering.")
        for p, nm in wanted.items():
            print(f"     PDB {p} expected {nm}: resid {p - OFFSET} = {names.get(p - OFFSET, '?')}, "
                  f"resid {p} = {names.get(p, '?')}")
        return None
    print(f"  numbering OK: {label}")
    if shift == OFFSET:
        print("  NOTE: the OLD list [102,110,111,113,126,131] would select -> " + describe_wrong_lists(names))
        print("        (not the L1/S3 pocket; here the pocket is resid "
              + ",".join(str(p - shift) for p in POCKET) + ")")
    resid_of = {p: p - shift for p in wanted}

    lig_sel = f"resname {a.ligand_resname}" if a.ligand_resname else f"not ({NOT_LIGAND})"
    lig = u.select_atoms(lig_sel)
    if len(lig.residues) != 1:
        print(f"  !! expected exactly 1 ligand residue, found {len(lig.residues)}: "
              f"{sorted(set(lig.resnames))}  (use --ligand-resname)")
        return None
    lig_hm = np.array([not n.upper().startswith("H") for n in lig.names])
    lig_heavy = lig[lig_hm]
    lig_masses = lig.masses.astype(float)
    n_prot_atoms = len(u.select_atoms(PROT_SEL))
    print(f"  ligand: {lig.resnames[0]} resid {lig.resids[0]}  ({len(lig)} atoms, {len(lig_heavy)} heavy); "
          f"protein atoms: {n_prot_atoms}")

    pr = " ".join(str(resid_of[p]) for p in POCKET)
    pocket_heavy = u.select_atoms(f"({PROT_SEL}) and resid {pr} and not name H*")
    pocket_ca = u.select_atoms(f"({PROT_SEL}) and resid {pr} and name CA")
    prot_all = u.select_atoms(PROT_SEL)
    prot_heavy = u.select_atoms(f"({PROT_SEL}) and not name H*")
    ca_all = u.select_atoms(f"({PROT_SEL}) and name CA")
    sgs = {c: u.select_atoms(f"({PROT_SEL}) and resid {resid_of[c]} and name SG") for c in (124, 277)}
    if any(len(g) != 1 for g in sgs.values()):
        print("  [warn] SG atom of Cys124/Cys277 not found uniquely; Cys distances skipped")
        sgs = {}

    ri = prot_heavy.resindices
    starts = np.r_[0, np.nonzero(np.diff(ri))[0] + 1]
    res_resids = prot_heavy.resids[starts]
    res_resnames = prot_heavy.resnames[starts]

    # ---- frame selection (uniform, no duplicates, <= tmax) ------------------
    times = np.array([ts.time for ts in u.trajectory])
    keep, dup, back, beyond = select_frames(times, a.tmax, a.stride)
    dts = np.unique(np.round(np.diff(times[np.array(keep)]), 3)) if len(keep) > 1 else []
    print(f"  stored frames: {len(times)}  (t = {times[0]/1000:.3f}-{times[-1]/1000:.3f} ns);  "
          f"used: {len(keep)} up to {a.tmax:g} ns")
    if dup or back or beyond:
        print(f"  frame filter: {beyond} beyond tmax, {dup} duplicate-time, {back} out-of-order frames dropped")
    if len(dts) > 1:
        print(f"  [warn] non-uniform time step in used frames (ps): {[float(x) for x in dts][:8]}")

    dims0 = u.trajectory.ts.dimensions
    if not np.allclose(dims0[3:], 90.0, atol=0.5):
        print(f"  [warn] non-orthorhombic box {dims0[3:]}: COM minimum-image and image gap are approximate")
    can_unwrap = hasattr(u, "bonds") and len(u.bonds) > 0

    t, com_naive, com_mic, minheavy, minprot = [], [], [], [], []
    dc124, dc277, res_min, boxL, ca_break, img_gap, poses = [], [], [], [], [], [], []
    for ts in u.trajectory[keep]:
        box = ts.dimensions[:3].astype(float)
        boxL.append(box[0])
        t.append(ts.time / 1000.0)
        com_naive.append(np.linalg.norm(lig.center_of_mass() - pocket_ca.center_of_mass()) / 10.0)
        if can_unwrap:
            prot_all.unwrap(compound="fragments")
            lig.unwrap(compound="fragments")

        pca = pocket_ca.positions.astype(float)
        pocket_com = pca[0] + mic_vec(pca - pca[0], box).mean(0)
        lpos = lig.positions.astype(float)
        lig_com = lpos[0] + (mic_vec(lpos - lpos[0], box) * lig_masses[:, None]).sum(0) / lig_masses.sum()
        com_mic.append(np.linalg.norm(mic_vec(lig_com - pocket_com, box)) / 10.0)

        lh = lig_heavy.positions
        minheavy.append(distance_array(lh, pocket_heavy.positions, box=ts.dimensions).min() / 10.0)
        Dall = distance_array(lh, prot_heavy.positions, box=ts.dimensions)
        minprot.append(Dall.min() / 10.0)
        res_min.append(np.minimum.reduceat(Dall.min(0), starts))
        if sgs:
            dc124.append(distance_array(lh, sgs[124].positions, box=ts.dimensions).min() / 10.0)
            dc277.append(distance_array(lh, sgs[277].positions, box=ts.dimensions).min() / 10.0)

        hp = prot_heavy.positions.astype(float)
        img_gap.append(float(np.min(box - (hp.max(0) - hp.min(0)))) / 10.0)   # conservative image gap (nm)

        ca = ca_all.positions.astype(float)
        ca_break.append(np.linalg.norm(np.diff(ca, axis=0), axis=1).max() / 10.0)
        lig_img = lpos - box * np.round((lig_com - pocket_com) / box)
        if ctx.get("ref_ca") is None:
            ctx["ref_ca"] = ca.copy()
        if len(ca) == len(ctx["ref_ca"]):
            R, Pc, Qc = kabsch(ca, ctx["ref_ca"])
            poses.append(((lig_img[lig_hm] - Pc) @ R + Qc) / 10.0)             # nm, common frame
        else:
            poses.append(np.full((int(lig_hm.sum()), 3), np.nan))

    t = np.array(t); com_naive = np.array(com_naive); com_mic = np.array(com_mic)
    minheavy = np.array(minheavy); minprot = np.array(minprot)
    res_min = np.array(res_min) / 10.0
    poses = np.array(poses)
    rmsd = np.sqrt(((poses - poses[0]) ** 2).sum(-1).mean(-1))
    img_gap = np.array(img_gap)
    cut = a.cutoff / 10.0
    L = float(np.median(boxL)) / 10.0
    win = (t >= a.win_start) & (t <= a.win_end)
    diff = com_naive - com_mic

    print(f"  frames={len(t)}  time {t[0]:.2f}-{t[-1]:.2f} ns  box edge {L:.3f} nm "
          f"(max possible MIC distance in a cubic box = {L*np.sqrt(3)/2:.2f} nm)")
    if np.max(ca_break) > 0.5:
        print(f"  [warn] protein not whole in some frames (max consecutive CA-CA {np.max(ca_break):.2f} nm)")
    print("  --- CHECK 2: ligand-pocket distance (COM ligand vs COM of 9 pocket CA, nm) ---")
    print(f"      naive (stored coords)  final {com_naive[-1]:7.3f}   max {com_naive.max():7.3f}")
    print(f"      minimum-image          final {com_mic[-1]:7.3f}   max {com_mic.max():7.3f}   "
          f"mean {com_mic.mean():.3f} +- {com_mic.std(ddof=1):.3f}")
    print(f"      frames where naive - MIC > 0.05 nm: {int((diff > 0.05).sum())}/{len(t)}")
    print(f"      min heavy-atom distance to docking pocket: min {minheavy.min():.3f}  "
          f"median {np.median(minheavy):.3f}  final {minheavy[-1]:.3f} nm")
    inc = minheavy <= cut
    exit_t, longest, n_exits = run_stats(t, inc, a.exit_ns)
    last_in = t[inc][-1] if inc.any() else float("nan")
    print(f"      in pocket contact (<= {cut:.2f} nm): all {frac(inc):.1f}%   window {a.win_start:g}-{a.win_end:g} ns "
          f"{frac(inc[win]):.1f}%   last 2 ns {frac(inc[t >= t[-1] - 2.0]):.1f}%")
    print(f"      last contact {last_in:.2f} ns | first STABLE exit (>= {a.exit_ns:g} ns no contact): "
          f"{'none' if np.isnan(exit_t) else f'{exit_t:.2f} ns'} | longest continuous contact {longest:.2f} ns "
          f"| exits from pocket: {n_exits}")
    elsewhere = (minprot <= cut) & ~inc
    print(f"      min distance to ANY protein atom: median {np.median(minprot):.3f} nm, final {minprot[-1]:.3f} nm; "
          f"touching protein but NOT the pocket in {frac(elsewhere):.1f}% of frames")
    print(f"      protein/periodic-image gap (conservative): min {img_gap.min():.2f} nm; "
          f"frames below {a.image_warn:g} nm: {int((img_gap < a.image_warn).sum())}")
    if sgs:
        d1, d2 = np.array(dc124), np.array(dc277)
        print(f"      distance to Cys124 SG: min {d1.min():.3f} median {np.median(d1):.3f} nm "
              f"| Cys277 SG: min {d2.min():.3f} median {np.median(d2):.3f} nm")
    print(f"      ligand RMSD (CA-fitted, vs first frame): mean {rmsd.mean():.3f}  max {rmsd.max():.3f} nm")

    occ_win = 100.0 * (res_min[win] <= cut).mean(0) if win.any() else np.full(res_min.shape[1], np.nan)
    occ_all = 100.0 * (res_min <= cut).mean(0)
    pdb_nums = res_resids + shift
    print(f"  --- CHECK 3: residue contact occupancy (cutoff {a.cutoff:g} A; window {a.win_start:g}-{a.win_end:g} ns) ---")
    order = np.argsort(-occ_win)[:12]
    print("      top residues in window:  " + "  ".join(
        f"{res_resnames[i].title()}{pdb_nums[i]}{'*' if pdb_nums[i] in POCKET else ''}:{occ_win[i]:.0f}%"
        for i in order if occ_win[i] > 0))
    print("      (* = docking-pocket residue)")
    print("      residue                              window   all-frames")
    for p in list(POCKET) + [239, 267, 124, 277]:
        i = int(np.where(pdb_nums == p)[0][0])
        tag = "pocket" if p in POCKET else "extra "
        print(f"        {tag} {res_resnames[i].title()}{p:<4d}                    {occ_win[i]:6.1f}%   {occ_all[i]:6.1f}%")

    os.makedirs(a.out, exist_ok=True)
    cols = [t, com_naive, com_mic, minheavy, minprot, rmsd, img_gap]
    hdr = ("time_ns,com_dist_naive_nm,com_dist_mic_nm,min_heavy_pocket_nm,min_dist_any_protein_nm,"
           "ligand_rmsd_nm,protein_image_gap_nm")
    if sgs:
        cols += [np.array(dc124), np.array(dc277)]
        hdr += ",min_dist_Cys124SG_nm,min_dist_Cys277SG_nm"
    np.savetxt(os.path.join(a.out, f"{name}_distances.csv"), np.column_stack(cols),
               delimiter=",", header=hdr, comments="", fmt="%.5f")
    with open(os.path.join(a.out, f"{name}_residue_occupancy.csv"), "w") as fh:
        fh.write("pdb_resnum,resname,occupancy_window_pct,occupancy_all_pct\n")
        for i in range(len(pdb_nums)):
            fh.write(f"{pdb_nums[i]},{res_resnames[i]},{occ_win[i]:.2f},{occ_all[i]:.2f}\n")

    row = {"system": name, "frames": len(t), "t_end_ns": float(t[-1]), "protein_atoms": n_prot_atoms,
           "final_com_mic_nm": float(com_mic[-1]), "mean_com_mic_nm": float(com_mic.mean()),
           "sd_com_mic_nm": float(com_mic.std(ddof=1)), "max_com_mic_nm": float(com_mic.max()),
           "final_min_heavy_pocket_nm": float(minheavy[-1]),
           "pct_contact_all": frac(inc), "pct_contact_window": frac(inc[win]),
           "last_contact_ns": float(last_in), "first_stable_exit_ns": float(exit_t),
           "longest_contact_ns": longest, "n_exits": n_exits,
           "ligand_atom_names": [str(x) for x in lig_heavy.names]}
    return {"t": t, "com_mic": com_mic, "minheavy": minheavy, "inc": inc, "win": win,
            "poses": poses, "row": row, "occ_window": {int(p): float(o) for p, o in zip(pdb_nums, occ_win) if o > 0}}


def pose_compare(res, a):
    A, B = a.pose_pair
    print("\n" + "=" * 78)
    print(f"CHECK 3b -- ligand pose similarity, {A} vs {B} (heavy atoms, CA-fitted common frame, nm)")
    print("=" * 78)
    if A not in res or B not in res:
        print("  skipped: both systems must be analysed")
        return None
    if res[A]["row"]["ligand_atom_names"] != res[B]["row"]["ligand_atom_names"]:
        print("  skipped: ligand heavy-atom names/order differ between the two systems")
        return None

    def pick(r):
        idx = np.where(r["inc"] & r["win"])[0]
        if len(idx) == 0:
            return None
        if len(idx) > a.pose_max_frames:
            idx = idx[np.linspace(0, len(idx) - 1, a.pose_max_frames).astype(int)]
        return r["poses"][idx]
    X, Y = pick(res[A]), pick(res[B])
    if X is None or Y is None or np.isnan(X).any() or np.isnan(Y).any():
        print("  skipped: no usable in-contact frames (or CA count mismatch)")
        return None
    cross = rmsd_matrix(X, Y)
    ia = rmsd_matrix(X, X)[np.triu_indices(len(X), 1)]
    ib = rmsd_matrix(Y, Y)[np.triu_indices(len(Y), 1)]
    q = lambda v: f"median {np.median(v):.3f}  (10-90%: {np.percentile(v,10):.3f}-{np.percentile(v,90):.3f})"
    print(f"  within {A}: {q(ia)}\n  within {B}: {q(ib)}\n  {A} vs {B}: {q(cross)}")
    ratio = np.median(cross) / max(np.median(ia), np.median(ib), 1e-6)
    print(f"  cross / within ratio = {ratio:.2f}  ->",
          "similar pose" if ratio < 1.5 else "different poses in the same region (report as 'same region', not 'same pose')")
    print("  (symmetry-equivalent atom swaps are not considered)")
    return {"within_A_median": float(np.median(ia)), "within_B_median": float(np.median(ib)),
            "cross_median": float(np.median(cross)), "ratio": float(ratio)}


def run_md(a):
    print("\n" + "=" * 78)
    print("CHECK 2 + 3 -- minimum-image distances, numbering verification, contacts")
    print("=" * 78)
    try:
        import MDAnalysis  # noqa: F401
    except ImportError:
        sys.exit("MDAnalysis is required: pip install 'MDAnalysis>=2.1'")
    root = os.path.expanduser(a.root)
    systems = {k: (os.path.join(root, v[0]), os.path.join(root, v[1])) for k, v in DEFAULT_SYSTEMS.items()}
    for nm, top, trj in (a.system or []):
        systems[nm] = (os.path.expanduser(top), os.path.expanduser(trj))
    if a.only:
        systems = {k: v for k, v in systems.items() if k in a.only}
    res, ctx = {}, {"ref_ca": None}
    for nm, (top, trj) in systems.items():
        if not (os.path.exists(top) and os.path.exists(trj)):
            print(f"\n[{nm}] skipped: file not found\n   {top}\n   {trj}")
            continue
        r = analyse_system(nm, top, trj, a, ctx)
        if r:
            res[nm] = r
    summary = {"systems": {k: {kk: vv for kk, vv in r["row"].items() if kk != "ligand_atom_names"}
                           for k, r in res.items()}}
    if res:
        os.makedirs(a.out, exist_ok=True)
        keys = [k for k in next(iter(res.values()))["row"] if k != "ligand_atom_names"]
        with open(os.path.join(a.out, "table1_summary.csv"), "w") as fh:
            fh.write(",".join(keys) + "\n")
            for r in res.values():
                fh.write(",".join(f"{r['row'][k]:.4g}" if isinstance(r["row"][k], float) else str(r["row"][k])
                                  for k in keys) + "\n")
        print(f"\ntable for the revised Table 1: {os.path.join(a.out, 'table1_summary.csv')}")
        sizes = {r["row"]["protein_atoms"] for r in res.values()}
        if len(sizes) > 1:
            print(f"[note] protein atom counts differ between systems: "
                  f"{ {k: r['row']['protein_atoms'] for k, r in res.items()} }  "
                  "(Methods claims atom-for-atom consistent topologies)")
        pc = pose_compare(res, a)
        if pc:
            summary["pose_compare"] = pc
    if a.plot and res:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(2, 1, figsize=(7, 6), sharex=True)
            for nm, r in res.items():
                ax[0].plot(r["t"], r["com_mic"], label=nm, lw=1)
                ax[1].plot(r["t"], r["minheavy"], label=nm, lw=1)
            ax[1].axhline(a.cutoff / 10.0, color="k", ls="--", lw=0.8)
            ax[0].set_ylabel("COM distance, minimum-image (nm)")
            ax[1].set_ylabel("min heavy-atom distance to pocket (nm)")
            ax[1].set_xlabel("Time (ns)")
            ax[0].legend(ncol=3, fontsize=8)
            fig.tight_layout()
            p = os.path.join(a.out, "fig_distance_mic.png")
            fig.savefig(p, dpi=300)
            print(f"plot written: {p}")
        except Exception as e:                                           # pragma: no cover
            print(f"[warn] plot failed: {e}")
    return summary


# ----------------------------------------------------------------------------
def selftest():
    rng = np.random.default_rng(1)
    sig, T = 2.0, 300.0
    E = rng.normal(-20.0, sig, 200000)
    ie, exp = ie_from_series(E, T), 0.5 * sig ** 2 / (KB * T)
    assert ie > 0 and abs(ie - exp) / exp < 0.05, (ie, exp)
    print(f"IE Gaussian test OK (computed {ie:.3f}, theory {exp:.3f}, always positive)")
    box = np.array([77.2, 77.2, 77.2])
    assert np.allclose(mic_vec(np.array([[70.0, -70.0, 10.0]]), box), [[-7.2, 7.2, 10.0]])
    print("minimum-image helper OK")
    P = rng.normal(size=(50, 3))
    th = 0.7
    Rt = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
    Q = P @ Rt + np.array([1.0, 2.0, 3.0])
    R, Pc, Qc = kabsch(P, Q)
    assert np.allclose((P - Pc) @ R + Qc, Q, atol=1e-8)
    print("Kabsch fit OK")
    t = np.arange(0, 20.0, 0.01)
    inc = np.ones(len(t), bool); inc[800:850] = False; inc[1500:] = False      # 0.5 ns gap (ignored), then stable exit at 15 ns
    ex, lg, ne = run_stats(t, inc, 1.0)
    assert abs(ex - 15.0) < 0.02 and ne == 2 and lg > 6.9, (ex, lg, ne)
    print(f"stable-exit logic OK (first stable exit {ex:.2f} ns, longest contact {lg:.2f} ns)")
    k, d, b, bey = select_frames(np.array([0, 10, 20, 20, 30, 25, 40, 50, 60.0]), 0.05, 1)
    assert k == [0, 1, 2, 4, 6, 7] and d == 1 and b == 1 and bey == 1, (k, d, b, bey)
    print("frame filter OK (duplicate, out-of-order and beyond-tmax frames dropped)")
    print("selftest passed")


def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["ie", "md", "all", "extract-eint", "compare-csv", "selftest"])
    p.add_argument("--root", default="~/tp53_md_project")
    p.add_argument("--system", nargs=3, action="append", metavar=("NAME", "TOP", "TRAJ"))
    p.add_argument("--only", nargs="+")
    p.add_argument("--ligand-resname", default=None)
    p.add_argument("--cutoff", type=float, default=4.5, help="contact cutoff, Angstrom")
    p.add_argument("--tmax", type=float, default=20.0, help="use frames up to this time, ns")
    p.add_argument("--win-start", type=float, default=10.0)
    p.add_argument("--win-end", type=float, default=20.0)
    p.add_argument("--exit-ns", type=float, default=1.0, help="min duration without contact = stable exit")
    p.add_argument("--image-warn", type=float, default=1.0, help="warn if protein/image gap below this (nm)")
    p.add_argument("--stride", type=int, default=1)
    p.add_argument("--pose-pair", nargs=2, default=["Run1", "Run4"])
    p.add_argument("--pose-max-frames", type=int, default=150)
    p.add_argument("--out", default="analysis_checks")
    p.add_argument("--plot", action="store_true")
    # energy extraction / IE
    p.add_argument("--mdout-dir", default=".", help="folder with _GMXMMPBSA_*_pb.mdout.* files")
    p.add_argument("--eint-out", default="run1_eint.txt")
    p.add_argument("--force", action="store_true", help="write the energy file even if verification fails")
    p.add_argument("--expect-frames", type=int, default=201)
    p.add_argument("--expect-ligand-atoms", type=int, default=28, help="atoms of the ligand prmtop (PRIMA-1: 28)")
    p.add_argument("--expect-vdw", type=float, default=-16.48)
    p.add_argument("--expect-ele", type=float, default=-6.97)
    p.add_argument("--csv-a", help="compare-csv: first per-frame CSV (e.g. the original mmpbsa_run1_energy.csv)")
    p.add_argument("--csv-b", help="compare-csv: second per-frame CSV (e.g. the re-run)")
    p.add_argument("--tol", type=float, default=0.05, help="compare-csv: tolerance in kcal/mol (CSV values are rounded to 0.01)")
    p.add_argument("--ie-file")
    p.add_argument("--ie-col", type=int, default=None)
    p.add_argument("--ie-segment", type=float, default=25.0)
    p.add_argument("--temp", type=float, default=300.0)
    p.add_argument("--reported-ie", type=float, default=-3.87)
    p.add_argument("--dh-segment", type=float, default=-11.02)
    p.add_argument("--dh-full", type=float, default=-10.71)
    return p


def main():
    a = build_parser().parse_args()
    if a.command == "selftest":
        selftest()
        return
    if a.command == "extract-eint":
        run_extract(a)
        return
    if a.command == "compare-csv":
        if not (a.csv_a and a.csv_b):
            sys.exit("--csv-a and --csv-b are required")
        run_compare(a)
        return
    out = {}
    os.makedirs(a.out, exist_ok=True)
    if a.command in ("ie", "all"):
        if not a.ie_file:
            if a.command == "ie":
                sys.exit("--ie-file is required for `ie`")
            print("[info] no --ie-file given: skipping CHECK 1")
        else:
            out["ie"] = run_ie(a)
    if a.command in ("md", "all"):
        out["md"] = run_md(a)
    with open(os.path.join(a.out, "summary.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nsummary written: {os.path.join(a.out, 'summary.json')}")


if __name__ == "__main__":
    main()
