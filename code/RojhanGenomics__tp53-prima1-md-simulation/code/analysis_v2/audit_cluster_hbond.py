#!/usr/bin/env python3
"""
audit_cluster_hbond.py -- re-derive (A) the GROMOS conformational clustering and (B) the ligand-protein hydrogen bonds

(A) GROMOS clustering (Daura et al. 1999, the algorithm of `gmx cluster -method gromos`)
    * pairwise RMSD after optimal superposition of every pair of frames (Horn/quaternion method, numpy only)
    * two frames are neighbours if RMSD < cut-off (default 0.15 nm); the frame with most neighbours is the centre of the
      first cluster; it and its neighbours are removed; repeat.
    * atoms: C-alpha (the Methods say C-alpha, the Results say backbone -> both are computed with --atoms both)
    * manuscript: 35, 24 and 26 clusters for Replicates 1-3 (about 2000 frames each); largest cluster of Replicate 1 = 16.3 %

(B) ligand-protein hydrogen bonds (MDAnalysis HydrogenBondAnalysis, between the ligand and the protein only, i.e. water-mediated
    bonds are NOT counted), donor-acceptor < 3.5 A and donor-H-acceptor angle > 150 deg, minimum image convention.
    donors / acceptors: N and O atoms of the ligand and the protein; hydrogens: H bonded to N or O.
    manuscript: Replicate 3 "highest overall occupancy (77.4 % of frames)".

Usage
-----
    conda activate tp53_md
    cd ~/tp53_md_project
    python audit_cluster_hbond.py 2>&1 | tee audit_cluster_hbond_report.txt
    python audit_cluster_hbond.py --only Run1 --no-cluster
    python audit_cluster_hbond.py --selftest          # checks the RMSD matrix against a brute-force fit, no data needed

Frames: 0 - tmax (default 20 ns), whole molecules (unwrap on the fly).  Read-only.
Run time: about 1-3 minutes per system for the clustering (2001 frames), seconds for the hydrogen bonds.
"""
import argparse
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tp53_checks import (DEFAULT_SYSTEMS, EXTRA, NOT_LIGAND, POCKET, PROT_SEL, kabsch,  # noqa: E402
                         resolve_numbering, select_frames)

MS_CLUSTERS = {"Run1": 35, "Run2": 24, "Run3": 26}
MS_LARGEST_RUN1_PCT = 16.3
MS_HB_FRAMES_RUN3_PCT = 77.4


# ----------------------------------------------------------------------------------------------------------------
# GROMOS clustering
# ----------------------------------------------------------------------------------------------------------------
def pairwise_rmsd(X, den=None):
    """X: (n, N, 3), every frame centred (for mass weighting: centred on the mass centre and multiplied by sqrt(mass)).
    Returns the (n, n) matrix of RMSDs after optimal superposition (Horn 1987); den = N (or the sum of the weights)."""
    n, N, _ = X.shape
    if den is None:
        den = N
    G = (X ** 2).sum((1, 2))
    D = np.zeros((n, n))
    for i in range(n - 1):
        C = np.matmul(X[i].T[None, :, :], X[i + 1:])           # (m, 3, 3): C[p, q] = sum_a Xi[a, p] * Xj[a, q]
        Sxx, Sxy, Sxz = C[:, 0, 0], C[:, 0, 1], C[:, 0, 2]
        Syx, Syy, Syz = C[:, 1, 0], C[:, 1, 1], C[:, 1, 2]
        Szx, Szy, Szz = C[:, 2, 0], C[:, 2, 1], C[:, 2, 2]
        K = np.empty((C.shape[0], 4, 4))
        K[:, 0, 0] = Sxx + Syy + Szz
        K[:, 0, 1] = K[:, 1, 0] = Syz - Szy
        K[:, 0, 2] = K[:, 2, 0] = Szx - Sxz
        K[:, 0, 3] = K[:, 3, 0] = Sxy - Syx
        K[:, 1, 1] = Sxx - Syy - Szz
        K[:, 1, 2] = K[:, 2, 1] = Sxy + Syx
        K[:, 1, 3] = K[:, 3, 1] = Szx + Sxz
        K[:, 2, 2] = -Sxx + Syy - Szz
        K[:, 2, 3] = K[:, 3, 2] = Syz + Szy
        K[:, 3, 3] = -Sxx - Syy + Szz
        lam = np.linalg.eigvalsh(K)[:, -1]
        D[i, i + 1:] = np.sqrt(np.clip((G[i] + G[i + 1:] - 2.0 * lam) / den, 0.0, None))
    return D + D.T


def gromos(D, cutoff):
    """Daura et al. algorithm.  Returns a list of (centre_index, member_indices) in order of discovery."""
    n = len(D)
    adj = D < cutoff
    active = np.ones(n, bool)
    out = []
    while active.any():
        counts = (adj & active[None, :]).sum(1)
        counts[~active] = -1
        c = int(np.argmax(counts))
        members = np.where(adj[c] & active)[0]
        out.append((c, members))
        active[members] = False
    return out


def cluster_report(label, coords_nm, cutoff, ms_n=None, masses=None):
    if masses is None:
        X = coords_nm - coords_nm.mean(1, keepdims=True)
        D = pairwise_rmsd(X)
    else:                                                    # gmx cluster weights the fit and the RMSD with the atomic masses
        w = np.asarray(masses, float)
        cen = (coords_nm * w[None, :, None]).sum(1, keepdims=True) / w.sum()
        X = (coords_nm - cen) * np.sqrt(w)[None, :, None]
        D = pairwise_rmsd(X, den=w.sum())
    cl = gromos(D, cutoff)
    sizes = sorted((len(m) for _, m in cl), reverse=True)
    n = len(X)
    iu = D[np.triu_indices(n, 1)]
    print(f"     {label:9s}: {len(cl):3d} clusters (cut-off {cutoff:g} nm, {n} frames, {coords_nm.shape[1]} atoms) | largest {sizes[0]} = "
          f"{100.0 * sizes[0] / n:.1f} % | top 5 sizes {sizes[:5]} | single-frame clusters {sum(1 for s in sizes if s == 1)}")
    print(f"                pairwise RMSD ranges from {iu.min():.4f} to {iu.max():.4f} nm, average {iu.mean():.4f} nm "
          f"(your gmx cluster log for Run1: ranges 0.0740045 to 0.358607, average 0.223499)")
    if ms_n is not None:
        print(f"                manuscript: {ms_n} clusters  ->  {'OK' if len(cl) == ms_n else 'DIFFERENT'}")
    return len(cl), sizes, cl


# ----------------------------------------------------------------------------------------------------------------
# analysis of one system
# ----------------------------------------------------------------------------------------------------------------
def analyse(name, top, traj, a):
    import MDAnalysis as mda
    from MDAnalysis import transformations as trans
    from MDAnalysis.analysis.hydrogenbonds.hbond_analysis import HydrogenBondAnalysis as HBA

    print("\n" + "=" * 100)
    print(f"[{name}]  {top}  |  {traj}")
    print("=" * 100)
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
        print(f"  [warn] could not add the unwrap transformation ({e})")
    times = np.array([ts.time for ts in u.trajectory])
    keep, dup, back, beyond = select_frames(times, a.tmax, a.stride)
    print(f"  frames used: {len(keep)} (up to {a.tmax:g} ns; dropped {beyond} beyond tmax, {dup} duplicate, {back} out of order)")
    t = times[keep] / 1000.0
    win = t >= a.win_start
    summary = {"system": name}

    # ---------------------------------------------------------------- A. clustering
    if not a.no_cluster:
        print(f"\n  A. GROMOS clustering, C-alpha / backbone, cut-off {a.cutoff:g} nm, every {a.cluster_stride}-th used frame")
        sub = keep[:: a.cluster_stride]
        sets = []
        if a.atoms in ("ca", "both", "all"):
            sets.append(("C-alpha", u.select_atoms(f"({PROT_SEL}) and name CA")))
        if a.atoms in ("backbone", "both", "all"):
            sets.append(("backbone", u.select_atoms(f"({PROT_SEL}) and backbone")))
        if a.atoms in ("heavy", "all"):
            sets.append(("heavy", u.select_atoms(f"({PROT_SEL}) and not name H*")))
        if a.atoms in ("protein", "all"):
            sets.append(("protein", u.select_atoms(PROT_SEL)))
        for lab, ag in sets:
            coords = np.array([ag.positions.copy() for _ in u.trajectory[sub]], float) / 10.0
            ms_n = MS_CLUSTERS.get(name)
            nc, sizes, cl = cluster_report(lab, coords, a.cutoff, ms_n, ag.masses if a.mass_weighted else None)
            summary[f"clusters_{lab}"] = nc
            summary[f"largest_pct_{lab}"] = 100.0 * sizes[0] / len(coords)
            if name == "Run1":
                print(f"                manuscript: largest cluster {MS_LARGEST_RUN1_PCT} % of the frames  ->  "
                      f"{'OK' if abs(100.0 * sizes[0] / len(coords) - MS_LARGEST_RUN1_PCT) < 0.6 else 'DIFFERENT'}")
            # when is the central structure of the biggest cluster visited? (population of the biggest clusters over time)
            tt = t[:: a.cluster_stride]
            for k in range(min(3, len(cl))):
                m = cl[k][1]
                print(f"                cluster {k + 1}: {len(m)} frames, first at {tt[m].min():.2f} ns, last at {tt[m].max():.2f} ns, "
                      f"centre frame at {tt[cl[k][0]]:.2f} ns")

    # ---------------------------------------------------------------- B. hydrogen bonds
    if not a.no_hbond:
        lig = u.select_atoms(a.ligand_sel if a.ligand_sel else f"not ({NOT_LIGAND})")
        if len(lig) == 0:
            print("\n  B. hydrogen bonds: no ligand found, skipped")
            return summary
        lname = lig.resnames[0]
        shift, _, _ = resolve_numbering(u, {**POCKET, **EXTRA})
        print(f"\n  B. hydrogen bonds between {lname} ({len(lig)} atoms) and the protein (d(D-A) < {a.hb_dist:g} A, angle > {a.hb_angle:g} deg)")
        lsel = f"resname {lname}"
        hyd = f"(({lsel}) or ({PROT_SEL})) and mass 0.9:1.3 and (bonded name N* or bonded name O*)"
        heavy = f"(({lsel}) or ({PROT_SEL})) and (name N* or name O*)"
        try:
            hba = HBA(universe=u, between=[lsel, f"({PROT_SEL})"], donors_sel=heavy, hydrogens_sel=hyd, acceptors_sel=heavy,
                      d_h_cutoff=1.2, d_a_cutoff=a.hb_dist, d_h_a_angle_cutoff=a.hb_angle, update_selections=False)
            hba.run(frames=keep, verbose=False)
            hb = np.asarray(hba.results.hbonds)
        except Exception as e:
            print(f"     hydrogen-bond analysis failed: {type(e).__name__}: {e}")
            return summary
        idx = {int(f): i for i, f in enumerate(keep)}
        counts = np.zeros(len(keep))
        per_res = {}
        for row in hb:
            i = idx[int(row[0])]
            counts[i] += 1
            da, aa = u.atoms[int(row[1])], u.atoms[int(row[3])]
            patom = aa if (da.resname == lname) else da
            latom = da if (da.resname == lname) else aa
            key = (patom.resname, int(patom.resid) + (shift or 0), latom.name)
            per_res.setdefault(key, set()).add(i)
        if a.old_hbond:
            try:
                hb_old = HBA(universe=u, donors_sel=None, hydrogens_sel=None, acceptors_sel=None,
                             d_a_cutoff=a.hb_dist, d_h_a_angle_cutoff=a.hb_angle)
                sel_pl = f"({PROT_SEL}) or ({lsel})"
                hb_old.hydrogens_sel = hb_old.guess_hydrogens(sel_pl)
                hb_old.acceptors_sel = hb_old.guess_acceptors(sel_pl)
                hb_old.run(frames=keep, verbose=False)
                ob = np.asarray(hb_old.results.hbonds)
                lig_idx = set(int(i) for i in lig.indices)
                prot_idx = set(int(i) for i in prot.indices)
                cls = {"LP": np.zeros(len(keep), bool), "LL": np.zeros(len(keep), bool), "other": np.zeros(len(keep), bool)}
                other_partners = {}
                for row in ob:
                    d_, a_ = int(row[1]), int(row[3])
                    dl, al = d_ in lig_idx, a_ in lig_idx
                    if not (dl or al):
                        continue
                    k = "LL" if (dl and al) else ("LP" if ((dl and a_ in prot_idx) or (al and d_ in prot_idx)) else "other")
                    cls[k][idx[int(row[0])]] = True
                    if k == "other":
                        partner = u.atoms[a_ if dl else d_]
                        other_partners[(partner.resname, partner.name)] = other_partners.get((partner.resname, partner.name), 0) + 1
                either = cls["LP"] | cls["LL"] | cls["other"]
                print("     OLD definition (guess_hydrogens min charge 0.3, guess_acceptors charge <= -0.5; donor OR acceptor = ligand):")
                print(f"        frames with >= 1 bond of any kind: {100.0 * either.mean():.1f} %  "
                      f"(ligand-protein {100.0 * cls['LP'].mean():.1f} %, INTRAMOLECULAR ligand-ligand {100.0 * cls['LL'].mean():.1f} %, "
                      f"other {100.0 * cls['other'].mean():.1f} %)")
                print(f"        in {a.win_start:g}-{a.tmax:g} ns: any {100.0 * either[win].mean():.1f} %, ligand-protein {100.0 * cls['LP'][win].mean():.1f} %, "
                      f"intramolecular {100.0 * cls['LL'][win].mean():.1f} %")
                if other_partners:
                    tot_o = sum(other_partners.values())
                    top = sorted(other_partners.items(), key=lambda kv: -kv[1])[:4]
                    by_res = {}
                    for (rn, an), c in other_partners.items():
                        by_res[rn] = by_res.get(rn, 0) + c
                    print("        the 'other' bonds have as partner (residue name: % of those bonds): " +
                          ", ".join(f"{rn} {100.0 * c / tot_o:.1f} %" for rn, c in sorted(by_res.items(), key=lambda kv: -kv[1])[:4]) +
                          "   | top atoms: " + ", ".join(f"{rn}.{an} {100.0 * c / tot_o:.0f} %" for (rn, an), c in top))
                summary["old_any_pct"] = 100.0 * either.mean()
                summary["old_LL_pct"] = 100.0 * cls["LL"].mean()
            except Exception as e:
                print(f"     old-definition analysis failed: {type(e).__name__}: {e}")
        any_hb = counts > 0
        print(f"     frames with >= 1 ligand-protein hydrogen bond: {100.0 * any_hb.mean():.1f} % of all frames; "
              f"{100.0 * any_hb[win].mean():.1f} % in {a.win_start:g}-{a.tmax:g} ns")
        print(f"     number of simultaneous hydrogen bonds: mean {counts.mean():.2f} +- {counts.std(ddof=1):.2f} (max {int(counts.max())}); "
              f"{a.win_start:g}-{a.tmax:g} ns mean {counts[win].mean():.2f}")
        if name == "Run3":
            print(f"     manuscript: {MS_HB_FRAMES_RUN3_PCT} % of frames  ->  {'OK' if abs(100.0 * any_hb.mean() - MS_HB_FRAMES_RUN3_PCT) < 1.5 else 'DIFFERENT'}")
        ranked = sorted(per_res.items(), key=lambda kv: -len(kv[1]))[:8]
        print("     most persistent pairs (protein residue - ligand atom; % of frames with that bond):")
        for (rn, rid, latm), fr in ranked:
            print(f"        {rn.title()}{rid:<4d} - {latm:<4s} {100.0 * len(fr) / len(keep):5.1f} %")
        summary["hbond_any_pct"] = 100.0 * any_hb.mean()
        summary["hbond_mean_count"] = float(counts.mean())
    return summary


# ----------------------------------------------------------------------------------------------------------------
def selftest():
    rng = np.random.default_rng(3)
    n, N = 12, 40
    base = rng.normal(size=(N, 3))
    frames = []
    for _ in range(n):
        q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
        if np.linalg.det(q) < 0:
            q[:, 0] *= -1
        frames.append(base @ q + rng.normal(scale=0.05, size=(N, 3)) + rng.normal(size=3))
    X = np.array(frames)
    X = X - X.mean(1, keepdims=True)
    D = pairwise_rmsd(X)
    worst = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            R, Pc, Qc = kabsch(X[i], X[j])
            ref = np.sqrt((((X[i] - Pc) @ R + Qc - X[j]) ** 2).sum(1).mean())
            worst = max(worst, abs(ref - D[i, j]))
    assert worst < 1e-8, worst
    print(f"pairwise RMSD matrix equals the brute-force Kabsch fit (max difference {worst:.1e}) - OK")
    # three well separated conformations with noise -> exactly three clusters of known size
    confs = [rng.normal(size=(N, 3)) * 1.5 for _ in range(3)]
    fr, lab = [], []
    for k, cnt in enumerate((50, 30, 20)):
        for _ in range(cnt):
            fr.append(confs[k] + rng.normal(scale=0.03, size=(N, 3)))
            lab.append(k)
    X = np.array(fr)
    X = X - X.mean(1, keepdims=True)
    cl = gromos(pairwise_rmsd(X), 0.15)
    sizes = sorted((len(m) for _, m in cl), reverse=True)
    assert sizes == [50, 30, 20], sizes
    print("GROMOS algorithm finds the 3 known clusters of sizes", sizes, "- OK")
    # mass-weighted RMSD against an explicit weighted rotation
    w = rng.uniform(1.0, 30.0, size=N)
    Y = np.array(frames[:6])
    cen = (Y * w[None, :, None]).sum(1, keepdims=True) / w.sum()
    Xc = Y - cen
    Dw = pairwise_rmsd(Xc * np.sqrt(w)[None, :, None], den=w.sum())
    worst = 0.0
    for i in range(6):
        for j in range(i + 1, 6):
            H = (Xc[i] * w[:, None]).T @ Xc[j]
            U, _, Vt = np.linalg.svd(H)
            dd = np.sign(np.linalg.det(U @ Vt))
            R = U @ np.diag([1, 1, dd]) @ Vt
            ref = np.sqrt((w * ((Xc[i] @ R - Xc[j]) ** 2).sum(1)).sum() / w.sum())
            worst = max(worst, abs(ref - Dw[i, j]))
    assert worst < 1e-8, worst
    print(f"mass-weighted RMSD matrix equals an explicit weighted rotation (max difference {worst:.1e}) - OK")
    print("selftest passed")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="~/tp53_md_project")
    ap.add_argument("--system", nargs=3, action="append", metavar=("NAME", "TOP", "TRAJ"))
    ap.add_argument("--only", nargs="+")
    ap.add_argument("--tmax", type=float, default=20.0)
    ap.add_argument("--win-start", type=float, default=10.0)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--cutoff", type=float, default=0.15, help="GROMOS RMSD cut-off, nm")
    ap.add_argument("--atoms", choices=["ca", "backbone", "heavy", "protein", "both", "all"], default="both",
                    help="atoms of the clustering: ca, backbone, heavy (all protein heavy atoms), protein (all protein atoms incl. H), "
                         "both = ca + backbone, all = the four sets")
    ap.add_argument("--mass-weighted", action="store_true", help="mass-weighted fit and RMSD (what gmx cluster does)")
    ap.add_argument("--old-hbond", action="store_true",
                    help="also reproduce the definition of the old analyze_hbonds.py (MDAnalysis guess_* selections; a bond counts if "
                         "the donor OR the acceptor is the ligand) and split it into ligand-protein and ligand-ligand bonds")
    ap.add_argument("--cluster-stride", type=int, default=1, help="use every n-th frame for the clustering (n=1: all, as in the manuscript)")
    ap.add_argument("--hb-dist", type=float, default=3.5)
    ap.add_argument("--hb-angle", type=float, default=150.0)
    ap.add_argument("--ligand-sel", default=None, help="MDAnalysis selection of the ligand (default: auto-detect)")
    ap.add_argument("--no-cluster", action="store_true")
    ap.add_argument("--no-hbond", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    root = os.path.expanduser(a.root)
    systems = {k: (os.path.join(root, v[0]), os.path.join(root, v[1])) for k, v in DEFAULT_SYSTEMS.items()}
    for nm, top, trj in (a.system or []):
        systems[nm] = (os.path.expanduser(top), os.path.expanduser(trj))
    if a.only:
        systems = {k: v for k, v in systems.items() if k in a.only}
    rows = []
    for nm, (top, trj) in systems.items():
        if not (os.path.exists(top) and os.path.exists(trj)):
            print(f"[{nm}] skipped: file not found")
            continue
        rows.append(analyse(nm, top, trj, a))
    if rows:
        keys = sorted({k for r in rows for k in r})
        keys.remove("system")
        with open("audit_cluster_hbond_summary.csv", "w") as fh:
            fh.write("system," + ",".join(keys) + "\n")
            for r in rows:
                fh.write(r["system"] + "," + ",".join(f"{r[k]:.2f}" if k in r else "" for k in keys) + "\n")
        print("\nsummary written: audit_cluster_hbond_summary.csv")
    print("\nNote: the number of GROMOS clusters depends on the atom set, the cut-off, the frame set and tie-breaking; "
          "if it differs from the manuscript, `gmx cluster -method gromos -cutoff 0.15` on the same frames is the reference "
          "(your cluster_run1.log shows what was used).")


if __name__ == "__main__":
    main()
