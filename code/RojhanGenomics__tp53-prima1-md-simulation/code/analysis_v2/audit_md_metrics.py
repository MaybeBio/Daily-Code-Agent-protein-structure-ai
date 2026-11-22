#!/usr/bin/env python3
"""
audit_md_metrics.py -- re-derive the structural metrics of the manuscript from the raw trajectories

For every system (Run1-4, negative control), using frames 0 - tmax (default 20 ns), whole molecules
(on-the-fly unwrap) and the minimum-image convention for every distance:

  1. protein backbone RMSD (N,CA,C,O; fit to frame 0)   mean +- SD over 10-20 ns and over all frames
     (the C-alpha-only variant is printed too, so the definition used in the manuscript can be identified)
  2. radius of gyration of the protein                   mean +- SD, all frames and 10-20 ns
  3. C-alpha RMSF of the nine docking-pocket residues    (Table 2 of the manuscript)
  4. DSSP composition (coil / beta-sheet / helix, %)     (excluding the C-terminal residue, as in the Methods)
  5. structural Zn2+: minimum-image distance to the four native ligands (Cys176 SG, His179 ND1, Cys238 SG, Cys242 SG),
     nearest protein atom, and number of water oxygens within 3.0 A, at several times (Figure 8 / Section 3.8)

Each recomputed number is printed next to the value stated in the manuscript and flagged OK / DIFFERENT.

Usage
-----
    conda activate tp53_md
    cd ~/tp53_md_project
    python audit_md_metrics.py 2>&1 | tee audit_md_metrics_report.txt
    python audit_md_metrics.py --only Run1 --no-dssp

Read-only.  Needs numpy and MDAnalysis (>= 2.8 for DSSP).
"""
import argparse
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tp53_checks import (DEFAULT_SYSTEMS, EXTRA, OFFSET, POCKET, PROT_SEL, kabsch,  # noqa: E402
                         resolve_numbering, select_frames)

# values printed in the manuscript (Sci Rep version)
MS_RMSD = {"Run1": (0.220, 0.020), "Run2": (0.195, 0.021), "Run3": (0.171, 0.025),
           "Run4": (0.163, 0.016), "NegCtrl": (0.171, 0.021)}
MS_RG = {"Run1": (1.651, 0.007), "Run2": (1.660, 0.010), "Run3": (1.647, 0.010)}
MS_DSSP = {"Run1": (58.2, 34.9, 6.9), "Run2": (58.6, 34.9, 6.5), "Run3": (59.7, 33.4, 6.9)}
MS_RMSF = {  # pocket residue (PDB number): (Run1, Run2, Run3)
    102: (0.078, 0.080, 0.070), 104: (0.080, 0.074, 0.068), 110: (0.066, 0.053, 0.057),
    111: (0.062, 0.056, 0.056), 126: (0.071, 0.052, 0.057), 131: (0.119, 0.092, 0.074),
    268: (0.050, 0.050, 0.045), 269: (0.052, 0.050, 0.047), 270: (0.054, 0.048, 0.050)}
ZN_LIGANDS = [(176, "CYS", "SG"), (179, "HIS", "ND1"), (238, "CYS", "SG"), (242, "CYS", "SG")]   # 2OCJ chain A: His179 ND1 2.06 A (NE2 4.13 A)


def flag(val, ref, tol):
    return "OK" if abs(val - ref) <= tol else "DIFFERENT"


def analyse(name, top, traj, a):
    import MDAnalysis as mda
    from MDAnalysis import transformations as trans
    from MDAnalysis.lib.distances import distance_array

    print("\n" + "=" * 96)
    print(f"[{name}]  {top}  |  {traj}")
    print("=" * 96)
    u = mda.Universe(top, traj)
    if not hasattr(u, "bonds") or len(u.bonds) == 0:
        try:
            u.atoms.guess_bonds()
        except Exception:
            pass
    prot = u.select_atoms(PROT_SEL)
    try:
        u.trajectory.add_transformations(trans.unwrap(prot))
    except Exception as e:
        print(f"  [warn] could not add the unwrap transformation ({e}); protein may be broken across the box")

    wanted = {**POCKET, **EXTRA}
    shift, label, names = resolve_numbering(u, wanted)
    if shift is None:
        print("  !! residue names do not match the expected residues; numbering unknown, skipping this system")
        return
    print(f"  numbering: {label}")
    rid = lambda pdb: pdb - shift

    bb = u.select_atoms(f"({PROT_SEL}) and backbone")
    ca = u.select_atoms(f"({PROT_SEL}) and name CA")
    pocket_ca = u.select_atoms(f"({PROT_SEL}) and name CA and resid " + " ".join(str(rid(p)) for p in POCKET))
    zn = u.select_atoms("resname ZN")
    water_o = u.select_atoms("resname SOL and name OW")
    prot_heavy = u.select_atoms(f"({PROT_SEL}) and not name H*")
    zn_lig = []
    if len(zn) == 1:
        for pdb, rn, an in ZN_LIGANDS:
            g = u.select_atoms(f"({PROT_SEL}) and resid {rid(pdb)} and name {an}")
            zn_lig.append((f"{rn.title()}{pdb} {an}", g if len(g) == 1 else None))

    times = np.array([ts.time for ts in u.trajectory])
    keep, dup, back, beyond = select_frames(times, a.tmax, a.stride)
    print(f"  frames used: {len(keep)} (up to {a.tmax:g} ns; dropped: {beyond} beyond tmax, {dup} duplicate, {back} out of order)")

    t, rmsd_bb, rmsd_ca, rg = [], [], [], []
    pk_fit, zn_d, zn_prot, zn_w3, zn_w25, zn_wmin = [], [], [], [], [], []
    ref_bb = ref_ca = None
    for ts in u.trajectory[keep]:
        t.append(ts.time / 1000.0)
        b = bb.positions.astype(float)
        c = ca.positions.astype(float)
        if ref_bb is None:
            ref_bb, ref_ca = b.copy(), c.copy()
        R, Pc, Qc = kabsch(b, ref_bb)
        fb = (b - Pc) @ R + Qc
        rmsd_bb.append(np.sqrt(((fb - ref_bb) ** 2).sum(1).mean()) / 10.0)
        R2, Pc2, Qc2 = kabsch(c, ref_ca)
        rmsd_ca.append(np.sqrt((((c - Pc2) @ R2 + Qc2 - ref_ca) ** 2).sum(1).mean()) / 10.0)
        rg.append(prot.radius_of_gyration() / 10.0)
        pk_fit.append(((pocket_ca.positions.astype(float) - Pc) @ R + Qc) / 10.0)
        if len(zn) == 1:
            zp = zn.positions
            zn_d.append([distance_array(zp, g.positions, box=ts.dimensions)[0, 0] if g is not None else np.nan
                         for _, g in zn_lig])
            zn_prot.append(distance_array(zp, prot_heavy.positions, box=ts.dimensions).min())
            dw = distance_array(zp, water_o.positions, box=ts.dimensions)[0]
            zn_w3.append(int((dw <= 3.0).sum()))
            zn_w25.append(int((dw <= 2.5).sum()))
            zn_wmin.append(dw.min())
    t = np.array(t)
    win = t >= a.win_start
    pk_fit = np.array(pk_fit)
    ms = lambda x, m: (np.mean(x[m]), np.std(x[m], ddof=1))

    if not a.zn_only:
        # 1. RMSD ------------------------------------------------------------------------------------------------
        print("\n  1. protein RMSD (nm), fit to frame 0")
        for lab, arr in (("backbone N,CA,C,O", np.array(rmsd_bb)), ("C-alpha only    ", np.array(rmsd_ca))):
            m1, s1 = ms(arr, win)
            m2, s2 = ms(arr, np.ones_like(win))
            print(f"     {lab}: {a.win_start:g}-{a.tmax:g} ns {m1:.3f} +- {s1:.3f}   |   all frames {m2:.3f} +- {s2:.3f}")
        if name in MS_RMSD:
            m, s = ms(np.array(rmsd_bb), win)
            print(f"     manuscript: {MS_RMSD[name][0]:.3f} +- {MS_RMSD[name][1]:.3f}  ->  mean {flag(m, MS_RMSD[name][0], 0.005)}, "
                  f"SD {flag(s, MS_RMSD[name][1], 0.005)}")

        # 2. Rg --------------------------------------------------------------------------------------------------
        rg = np.array(rg)
        m1, s1 = ms(rg, win)
        m2, s2 = ms(rg, np.ones_like(win))
        print(f"\n  2. radius of gyration (nm): {a.win_start:g}-{a.tmax:g} ns {m1:.3f} +- {s1:.3f}   |   all frames {m2:.3f} +- {s2:.3f}")
        if name in MS_RG:
            print(f"     manuscript: {MS_RG[name][0]:.3f} +- {MS_RG[name][1]:.3f}  ->  all-frames mean {flag(m2, MS_RG[name][0], 0.003)}, "
                  f"{a.win_start:g}-{a.tmax:g} ns mean {flag(m1, MS_RG[name][0], 0.003)}")

        # 3. RMSF ------------------------------------------------------------------------------------------------
        rmsf = np.sqrt(((pk_fit - pk_fit.mean(0)) ** 2).sum(2).mean(0))
        print("\n  3. pocket C-alpha RMSF (nm), all frames, after fitting the backbone to frame 0")
        idx = {"Run1": 0, "Run2": 1, "Run3": 2}
        for pdb, v in zip(POCKET, rmsf):
            ref = MS_RMSF[pdb][idx[name]] if name in idx else None
            extra = f"   manuscript {ref:.3f}  {flag(v, ref, 0.005)}" if ref is not None else ""
            print(f"     {POCKET[pdb].title()}{pdb:<4d} {v:.3f}{extra}")

        # 4. DSSP ------------------------------------------------------------------------------------------------
        if not a.no_dssp:
            try:
                from MDAnalysis.analysis.dssp import DSSP
                last = max(r.resid for r in prot.residues)
                sel = u.select_atoms(f"({PROT_SEL}) and not resid {last}")
                d = DSSP(sel).run(frames=keep)
                arr = np.asarray(d.results.dssp)
                tot = arr.size
                coil = 100.0 * (arr == "-").sum() / tot
                sheet = 100.0 * (arr == "E").sum() / tot
                helix = 100.0 * (arr == "H").sum() / tot
                print(f"\n  4. DSSP (3-state, C-terminal residue excluded): coil {coil:.1f}%  sheet {sheet:.1f}%  helix {helix:.1f}%")
                if name in MS_DSSP:
                    r = MS_DSSP[name]
                    print(f"     manuscript: coil {r[0]}%  sheet {r[1]}%  helix {r[2]}%  ->  "
                          f"{flag(coil, r[0], 0.6)}/{flag(sheet, r[1], 0.6)}/{flag(helix, r[2], 0.6)}")
            except Exception as e:
                print(f"\n  4. DSSP skipped ({type(e).__name__}: {e})")

    # 5. Zn --------------------------------------------------------------------------------------------------
    if len(zn) == 1:
        zn_d = np.array(zn_d)
        zn_prot, zn_w3, zn_w25, zn_wmin = map(np.array, (zn_prot, zn_w3, zn_w25, zn_wmin))
        print("\n  5. structural Zn2+ (minimum-image distances in A)")
        head = "     time(ns)  " + "  ".join(f"{n:>13s}" for n, _ in zn_lig) + "   nearest protein atom   waters<=3.0A (<=2.5A)  nearest O"
        print(head)
        picks = sorted({0, int(np.searchsorted(t, 0.1)), int(np.searchsorted(t, 1.0)), int(np.searchsorted(t, 5.0)),
                        int(np.searchsorted(t, 10.0)), len(t) - 1})
        for i in [p for p in picks if p < len(t)]:
            print(f"     {t[i]:7.2f}   " + "  ".join(f"{x:13.2f}" for x in zn_d[i]) +
                  f"   {zn_prot[i]:19.2f}   {zn_w3[i]:9d} ({zn_w25[i]})        {zn_wmin[i]:6.2f}")
        near = np.all(np.nan_to_num(zn_d, nan=99) < 3.5, axis=1)
        print(f"     all four native ligands within 3.5 A: {100.0 * near.mean():.1f}% of frames;   "
              f"max distance to Cys242 SG over the run: {np.nanmax(zn_d[:, 3]):.1f} A;  "
              f"max possible with minimum image in this box: ~{np.median([ts.dimensions[0] for ts in u.trajectory[keep[:3]]]) * np.sqrt(3) / 2:.0f} A")
        print(f"     waters within 3.0 A of Zn at the end: {zn_w3[-1]} (manuscript: six within 2.5-3.0 A; nearest 1.83-1.87 A)")
    else:
        print("\n  5. Zn: no single ZN residue found, skipped")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="~/tp53_md_project")
    ap.add_argument("--system", nargs=3, action="append", metavar=("NAME", "TOP", "TRAJ"))
    ap.add_argument("--only", nargs="+")
    ap.add_argument("--tmax", type=float, default=20.0)
    ap.add_argument("--win-start", type=float, default=10.0)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--no-dssp", action="store_true")
    ap.add_argument("--zn-only", action="store_true", help="print only the zinc section (RMSD, Rg, RMSF, DSSP are skipped)")
    a = ap.parse_args()
    root = os.path.expanduser(a.root)
    systems = {k: (os.path.join(root, v[0]), os.path.join(root, v[1])) for k, v in DEFAULT_SYSTEMS.items()}
    for nm, top, trj in (a.system or []):
        systems[nm] = (os.path.expanduser(top), os.path.expanduser(trj))
    if a.only:
        systems = {k: v for k, v in systems.items() if k in a.only}
    for nm, (top, trj) in systems.items():
        if not (os.path.exists(top) and os.path.exists(trj)):
            print(f"[{nm}] skipped: file not found")
            continue
        analyse(nm, top, trj, a)
    print("\nDone.  'DIFFERENT' is not automatically an error: first check the definition (reference frame, atom selection, "
          "time window); then decide which number the manuscript should state.")


if __name__ == "__main__":
    main()
