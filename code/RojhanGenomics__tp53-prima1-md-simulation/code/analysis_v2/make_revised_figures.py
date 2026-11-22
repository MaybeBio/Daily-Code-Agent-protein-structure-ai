#!/usr/bin/env python3
"""
make_revised_figures.py -- all revised figures (1-8) and tables (1-3) of the manuscript, from the raw data, with the verified definitions

Definitions (identical to the audit scripts):
  * frames 0 - 20.00 ns only (Replicates 2 and 3 are cut at 20.00 ns), whole molecules, minimum-image distances
  * backbone RMSD = N,CA,C,O after least-squares fit to the first frame;  Rg = whole protein, mass-weighted
  * Calpha RMSF after fitting the backbone to the first frame (all frames)
  * ligand-protein hydrogen bonds: donor-acceptor < 3.5 A, angle > 150 deg, ligand <-> protein only (no water, no intramolecular bonds)
  * Zn2+: minimum-image distances to the four native ligands and to the nearest protein atom
  * ligand-pocket distances: read from analysis_checks/<system>_distances.csv written by `tp53_checks.py md`
  * energies: read from mmpbsa_run1_energy.csv (MM-PBSA) and mmpbsa_decomp_full/decomp_delta_summary.csv (decomposition)

Usage
-----
    conda activate tp53_md
    cd ~/tp53_md_project
    python make_revised_figures.py                 # everything (the trajectory part takes a few minutes, then it is cached)
    python make_revised_figures.py --only-figs 5 7 8
    python make_revised_figures.py --redo          # ignore the cache in figure_data/
    python make_revised_figures.py --selftest

Output (folder revised_figures/):  Figure1_pipeline.png ... Figure8_zinc.png (300 dpi, also .pdf with --pdf),
    Table1_revised.csv, Table2_revised.csv, Table3_energy.csv, figure_legends.txt, make_revised_figures_log.txt
A figure that cannot be drawn does not stop the others; the reason is printed and written to the log.
Read-only for all input files.
"""
import argparse
import os
import sys
import traceback
import warnings

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tp53_checks import (DEFAULT_SYSTEMS, EXTRA, NOT_LIGAND, POCKET, PROT_SEL, bootstrap_dG, ie_from_series,  # noqa: E402
                         kabsch, load_eint, parse_gmx_mmpbsa_csv, resolve_numbering, select_frames)

LABEL = {"Run1": "Replicate 1", "Run2": "Replicate 2", "Run3": "Replicate 3", "Run4": "Replicate 4",
         "NegCtrl": "Quinuclidine (exploratory)"}
COLOR = {"Run1": "#1f77b4", "Run2": "#ff7f0e", "Run3": "#2ca02c", "Run4": "#d62728", "NegCtrl": "#7f4fa8"}
ZN_LIG = [(176, "SG", "Cys176 Sγ"), (179, "ND1", "His179 Nδ1"), (238, "SG", "Cys238 Sγ"), (242, "SG", "Cys242 Sγ")]
LOG = []


def log(msg):
    print(msg)
    LOG.append(msg)


# ----------------------------------------------------------------------------------------------------------------
# trajectory-derived data (cached)
# ----------------------------------------------------------------------------------------------------------------
def compute_system(name, top, traj, a):
    import MDAnalysis as mda
    from MDAnalysis import transformations as trans
    from MDAnalysis.lib.distances import distance_array
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
        log(f"  [{name}] warning: unwrap failed ({e})")
    shift, _, _ = resolve_numbering(u, {**POCKET, **EXTRA})
    shift = 0 if shift is None else shift
    bb = u.select_atoms(f"({PROT_SEL}) and backbone")
    ca = u.select_atoms(f"({PROT_SEL}) and name CA")
    prot_heavy = u.select_atoms(f"({PROT_SEL}) and not name H*")
    zn = u.select_atoms("resname ZN")
    water_o = u.select_atoms("resname SOL and name OW")
    times = np.array([ts.time for ts in u.trajectory])
    keep, dup, back, beyond = select_frames(times, a.tmax, a.stride)
    log(f"  [{name}] {len(keep)} frames used (dropped {beyond} beyond {a.tmax:g} ns, {dup} duplicate, {back} out of order)")
    zl = []
    if len(zn) == 1:
        for pdb, an, _ in ZN_LIG:
            g = u.select_atoms(f"({PROT_SEL}) and resid {pdb - shift} and name {an}")
            zl.append(g if len(g) == 1 else None)
    t, rmsd, rg, ca_fit, zd, znear, zw = [], [], [], [], [], [], []
    ref = None
    for ts in u.trajectory[keep]:
        t.append(ts.time / 1000.0)
        b = bb.positions.astype(float)
        if ref is None:
            ref = b.copy()
        R, Pc, Qc = kabsch(b, ref)
        rmsd.append(np.sqrt((((b - Pc) @ R + Qc - ref) ** 2).sum(1).mean()) / 10.0)
        rg.append(prot.radius_of_gyration() / 10.0)
        ca_fit.append(((ca.positions.astype(float) - Pc) @ R + Qc) / 10.0)
        if len(zn) == 1:
            zp = zn.positions
            zd.append([distance_array(zp, g.positions, box=ts.dimensions)[0, 0] / 10.0 if g is not None else np.nan for g in zl])
            znear.append(distance_array(zp, prot_heavy.positions, box=ts.dimensions).min() / 10.0)
            zw.append(int((distance_array(zp, water_o.positions, box=ts.dimensions)[0] <= 3.0).sum()) if len(water_o) else 0)
    ca_fit = np.array(ca_fit)
    rmsf = np.sqrt(((ca_fit - ca_fit.mean(0)) ** 2).sum(2).mean(0))
    out = {"t": np.array(t), "rmsd": np.array(rmsd), "rg": np.array(rg), "rmsf": rmsf,
           "ca_resnum": ca.resids.astype(int) + shift}
    if len(zn) == 1:
        out.update({"zn_d": np.array(zd), "zn_near": np.array(znear), "zn_w": np.array(zw)})
    # ligand-protein hydrogen bonds (explicit definition)
    counts = np.full(len(keep), np.nan)
    if not a.skip_hbond:
        lig = u.select_atoms(f"not ({NOT_LIGAND})")
        if len(lig):
            try:
                from MDAnalysis.analysis.hydrogenbonds.hbond_analysis import HydrogenBondAnalysis as HBA
                lsel = f"resname {lig.resnames[0]}"
                hyd = f"(({lsel}) or ({PROT_SEL})) and mass 0.9:1.3 and (bonded name N* or bonded name O*)"
                heavy = f"(({lsel}) or ({PROT_SEL})) and (name N* or name O*)"
                hba = HBA(universe=u, between=[lsel, f"({PROT_SEL})"], donors_sel=heavy, hydrogens_sel=hyd, acceptors_sel=heavy,
                          d_h_cutoff=1.2, d_a_cutoff=3.5, d_h_a_angle_cutoff=150, update_selections=False)
                hba.run(frames=keep, verbose=False)
                hb = np.asarray(hba.results.hbonds)
                idx = {int(f): i for i, f in enumerate(keep)}
                counts = np.zeros(len(keep))
                for row in hb:
                    counts[idx[int(row[0])]] += 1
            except Exception as e:
                log(f"  [{name}] hydrogen-bond analysis failed: {type(e).__name__}: {e}")
    out["hb"] = counts
    return out


def load_data(a):
    root = os.path.expanduser(a.root)
    systems = {k: (os.path.join(root, v[0]), os.path.join(root, v[1])) for k, v in DEFAULT_SYSTEMS.items()}
    for nm, top, trj in (a.system or []):
        systems[nm] = (os.path.expanduser(top), os.path.expanduser(trj))
    if a.only:
        systems = {k: v for k, v in systems.items() if k in a.only}
    os.makedirs(os.path.join(root, "figure_data"), exist_ok=True)
    data = {}
    for nm, (top, trj) in systems.items():
        cache = os.path.join(root, "figure_data", f"{nm}.npz")
        if os.path.exists(cache) and not a.redo:
            z = np.load(cache, allow_pickle=True)
            data[nm] = {k: z[k] for k in z.files}
            log(f"  [{nm}] loaded from cache {cache}")
            continue
        if not (os.path.exists(top) and os.path.exists(trj)):
            log(f"  [{nm}] skipped: file not found")
            continue
        data[nm] = compute_system(nm, top, trj, a)
        np.savez(cache, **data[nm])
    return data


def read_distances(a, name):
    p = os.path.join(os.path.expanduser(a.root), a.checks_dir, f"{name}_distances.csv")
    if not os.path.exists(p):
        return None
    arr = np.genfromtxt(p, delimiter=",", names=True)
    if "com_dist_mic_nm" not in arr.dtype.names:
        log(f"  {p} has no minimum-image columns: run `python tp53_checks.py md` again")
        return None
    return arr


# ----------------------------------------------------------------------------------------------------------------
# plotting helpers
# ----------------------------------------------------------------------------------------------------------------
def mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "axes.linewidth": 0.8, "axes.labelsize": 8.5, "legend.fontsize": 7,
                         "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "savefig.dpi": 300, "figure.dpi": 130,
                         "axes.spines.top": False, "axes.spines.right": False})
    return plt


def save(fig, a, stem):
    out = os.path.join(os.path.expanduser(a.root), a.out)
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, stem + ".png")
    fig.savefig(p, bbox_inches="tight")
    if a.pdf:
        fig.savefig(os.path.join(out, stem + ".pdf"), bbox_inches="tight")
    log(f"  written {p}")
    return p


def panel(ax, letter):
    ax.text(-0.13, 1.04, letter, transform=ax.transAxes, fontsize=10, fontweight="bold", va="bottom")


def smooth(y, k):
    """running mean over the frames that exist (and are finite) inside the window: no artificial values at the ends"""
    y = np.asarray(y, float)
    ok = np.isfinite(y)
    k = max(1, min(int(k), len(y)))
    num = np.convolve(np.where(ok, y, 0.0), np.ones(k), mode="same")
    den = np.convolve(ok.astype(float), np.ones(k), mode="same")
    out = np.where(den > 0, num / np.maximum(den, 1e-12), np.nan)
    out[~ok] = np.nan
    return out


def fig_legend(fig, names, ncol=3):
    from matplotlib.lines import Line2D
    fig.legend([Line2D([0], [0], color=COLOR[n], lw=1.6) for n in names], [LABEL[n] for n in names], loc="lower center",
               bbox_to_anchor=(0.5, 0.995), ncol=ncol, frameon=False, handlelength=1.6, columnspacing=1.4)


def legend_runs(ax, names, loc="best", ncol=1):
    ax.legend([LABEL[n] for n in names], loc=loc, frameon=False, ncol=ncol, handlelength=1.6)


# ----------------------------------------------------------------------------------------------------------------
# figures
# ----------------------------------------------------------------------------------------------------------------
def fig1(a, data):
    plt = mpl()
    from matplotlib.patches import FancyBboxPatch
    fig, ax = plt.subplots(figsize=(6.4, 8.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 16.2)
    ax.axis("off")
    B = {}

    def box(key, x, y, w, h, txt, col):
        ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.04,rounding_size=0.12", fc=col, ec="#4a4a4a", lw=0.8))
        ax.text(x, y, txt, ha="center", va="center", fontsize=7.2, linespacing=1.4)
        B[key] = (x, y, w, h)

    def arrow(x0, k0, x1, k1):
        ax.annotate("", xy=(x1, B[k1][1] + B[k1][3] / 2 + 0.05), xytext=(x0, B[k0][1] - B[k0][3] / 2 - 0.05),
                    arrowprops=dict(arrowstyle="-|>", color="#4a4a4a", lw=0.9))

    blue, orange, green, purple, yellow = "#dce6f1", "#fde9d9", "#e2efda", "#e4dfec", "#fff2cc"
    box("pdb", 5, 15.2, 7.8, 1.2, "p53 DNA-binding domain (PDB 2OCJ, chain A, residues 96–289)\n+ PRIMA-1 (RDKit, MMFF94)", blue)
    box("dock", 5, 13.2, 7.8, 2.0, "Blind docking, AutoDock Vina 1.2.5\n(box 57.6 × 49.5 × 57.3 Å, exhaustiveness 32)\n"
        "checks: Vina 1.1.2 (same scoring function),\nVinardo (independent scoring function)", blue)
    box("sys", 5, 11.0, 7.8, 1.4, "MD system: AMBER99SB-ILDN, GAFF / AM1-BCC, TIP3P, 5 Cl⁻\n(Zn²⁺ as non-bonded ion), GROMACS 2020.1 / 2018.1", blue)
    box("eq", 5, 9.2, 7.8, 1.2, "Energy minimization, NVT (100 ps), NPT (100 ps),\nposition restraints", blue)
    box("prod", 5, 7.2, 7.8, 1.7, "Production, first 20 ns\nPRIMA-1 × 4 independent replicates\n+ quinuclidine × 1 (exploratory, incomplete protein topology)", orange)
    box("ana", 2.65, 4.8, 4.9, 2.4, "Trajectory analysis\nRMSD · Rg · RMSF · DSSP\nGROMOS clustering\nligand–pocket distance (minimum image)\nligand–protein H-bonds · Zn²⁺ behaviour", green)
    box("mm", 7.6, 4.8, 4.4, 2.4, "MM-PBSA, interaction entropy\nand per-residue decomposition\n(Replicate 1, 201 frames, 10–20 ns;\nZn²⁺ excluded)", green)
    box("mq", 5, 2.2, 7.8, 1.2, "MQ–Cys Michael-adduct geometry check\n(RDKit, MMFF94; auxiliary)", purple)
    box("fin", 5, 0.75, 7.8, 1.0, "Integrated structural and energetic assessment", yellow)
    for k0, k1 in (("pdb", "dock"), ("dock", "sys"), ("sys", "eq"), ("eq", "prod"), ("mq", "fin")):
        arrow(5, k0, 5, k1)
    arrow(3.4, "prod", 2.65, "ana")
    arrow(6.6, "prod", 7.6, "mm")
    arrow(2.65, "ana", 3.9, "mq")
    arrow(7.6, "mm", 6.1, "mq")
    return save(fig, a, "Figure1_pipeline")


def fig2(a, data):
    plt = mpl()
    names = [n for n in LABEL if n in data]
    fig, ax = plt.subplots(2, 1, figsize=(6.3, 5.6), sharex=True)
    for n in names:
        d = data[n]
        ax[0].plot(d["t"], d["rmsd"], color=COLOR[n], lw=0.8)
    ax[0].set_ylabel("Protein backbone RMSD (nm)")
    fig_legend(fig, names)
    panel(ax[0], "a")
    for n in names:
        dist = read_distances(a, n)
        if dist is None:
            continue
        r = np.where(dist["com_dist_mic_nm"] > a.mask_nm, np.nan, dist["ligand_rmsd_nm"])
        ax[1].plot(dist["time_ns"], r, color=COLOR[n], lw=0.4, alpha=0.25)
        k = max(1, int(round(0.5 / np.median(np.diff(dist["time_ns"])))))
        ax[1].plot(dist["time_ns"], smooth(r, k), color=COLOR[n], lw=1.1)
    ax[1].set_ylabel("Ligand RMSD (nm)")
    ax[1].set_xlabel("Time (ns)")
    panel(ax[1], "b")
    ax[1].set_xlim(0, a.tmax)
    return save(fig, a, "Figure2_rmsd")


def fig3(a, data):
    plt = mpl()
    names = [n for n in LABEL if n in data]
    fig, ax = plt.subplots(figsize=(6.3, 3.0))
    for n in names:
        ax.plot(data[n]["t"], data[n]["rg"], color=COLOR[n], lw=0.8)
    ax.set_xlabel("Time (ns)")
    ax.set_ylabel("Radius of gyration (nm)")
    ax.set_xlim(0, a.tmax)
    fig_legend(fig, names)
    return save(fig, a, "Figure3_rg")


def fig4(a, data):
    plt = mpl()
    names = [n for n in LABEL if n in data]
    fig, ax = plt.subplots(figsize=(6.6, 3.4))
    for n in names:
        ax.plot(data[n]["ca_resnum"], data[n]["rmsf"], color=COLOR[n], lw=0.9)
    for p in POCKET:
        ax.axvline(p, color="#999999", lw=0.5, ls=":")
    ax.set_xlabel("Residue number")
    ax.set_ylabel("Cα RMSF (nm)")
    fig_legend(fig, names)
    ax.text(0.99, 0.97, "dotted lines: the nine residues of the docked site", transform=ax.transAxes, ha="right", va="top",
            fontsize=6.5, color="#555555")
    return save(fig, a, "Figure4_rmsf")


def fig5(a, data):
    plt = mpl()
    names = [n for n in LABEL if n in data]
    fig, ax = plt.subplots(2, 1, figsize=(6.3, 5.6), sharex=True)
    for n in names:
        dist = read_distances(a, n)
        if dist is None:
            continue
        ax[0].plot(dist["time_ns"], dist["com_dist_mic_nm"], color=COLOR[n], lw=0.8)
        ax[1].plot(dist["time_ns"], dist["min_heavy_pocket_nm"], color=COLOR[n], lw=0.8)
    ax[0].set_ylabel("Ligand–pocket distance, COM (nm)")
    ax[1].set_ylabel("Minimum heavy-atom distance\nto the nine pocket residues (nm)")
    ax[1].axhline(0.45, color="k", lw=0.7, ls="--")
    ax[1].text(0.995, 0.45, "contact cut-off 0.45 nm", transform=ax[1].get_yaxis_transform(), ha="right", va="bottom", fontsize=6.5)
    ax[1].set_xlabel("Time (ns)")
    ax[1].set_xlim(0, a.tmax)
    fig_legend(fig, names)
    panel(ax[0], "a")
    panel(ax[1], "b")
    return save(fig, a, "Figure5_ligand_distance")


def fig6(a, data):
    plt = mpl()
    names = [n for n in LABEL if n in data and np.isfinite(np.nanmax(data[n]["hb"]) if len(data[n]["hb"]) else np.nan)]
    if not names:
        raise RuntimeError("no hydrogen-bond data (run without --skip-hbond and with --redo)")
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 3.2), gridspec_kw={"width_ratios": [1, 1.5]})
    x = np.arange(len(names))
    allp = [100.0 * np.mean(data[n]["hb"] > 0) for n in names]
    win = [100.0 * np.mean(data[n]["hb"][data[n]["t"] >= a.win_start] > 0) for n in names]
    ax[0].bar(x - 0.2, allp, 0.4, color=[COLOR[n] for n in names], label=f"0–{a.tmax:g} ns")
    ax[0].bar(x + 0.2, win, 0.4, color=[COLOR[n] for n in names], alpha=0.45, hatch="//", edgecolor="white", label=f"{a.win_start:g}–{a.tmax:g} ns")
    ax[0].set_xticks(x)
    ax[0].set_xticklabels([n.replace("NegCtrl", "QNC").replace("Run", "R") for n in names])
    ax[0].set_ylabel("Frames with ≥ 1 ligand–protein\nhydrogen bond (%)")
    ax[0].legend(frameon=False, loc="upper right")
    panel(ax[0], "a")
    for n in names:
        h = data[n]["hb"]
        k = max(1, int(round(1.0 / np.median(np.diff(data[n]["t"])))))
        run = smooth(h, k)
        ax[1].plot(data[n]["t"], run, color=COLOR[n], lw=0.9)
    ax[1].set_xlabel("Time (ns)")
    ax[1].set_ylabel("Number of hydrogen bonds\n(1-ns running mean)")
    ax[1].set_xlim(0, a.tmax)
    fig_legend(fig, names)
    panel(ax[1], "b")
    fig.tight_layout()
    return save(fig, a, "Figure6_hbonds")


def energy_numbers(a):
    p = os.path.join(os.path.expanduser(a.root), a.energy_csv)
    E, comps = load_eint(p)
    cols = dict(parse_gmx_mmpbsa_csv.cols)
    tot = cols["TOTAL"]
    n = len(E)
    res = {"n": n, "TOTAL": (tot.mean(), tot.std(ddof=1))}
    for k in ("VDWAALS", "EEL", "EPB", "ENPOLAR", "GGAS", "GSOLV"):
        res[k] = (cols[k].mean(), cols[k].std(ddof=1))
    for lab, frac in (("seg", 0.25), ("all", 1.0)):
        k = max(10, int(round(n * frac)))
        ie = ie_from_series(E[-k:], 300.0)
        iq, dq = bootstrap_dG(E, tot, 300.0, frac)
        res[f"IE_{lab}"] = (ie, iq[0], iq[2])
        res[f"dGeff_{lab}"] = (tot[-k:].mean() + ie, dq[0], dq[2])
    return res


def fig7(a, data):
    plt = mpl()
    root = os.path.expanduser(a.root)
    rows = []
    with open(os.path.join(root, a.decomp_csv)) as fh:
        next(fh)
        for line in fh:
            p = line.strip().split(",")
            rows.append({"label": p[0], "pdb": int(p[1]), "mean": float(p[2]), "sem": float(p[4]), "occ": float(p[10]) if p[10] != "nan" else np.nan})
    prot = sorted([r for r in rows if not r["label"].startswith("L:")], key=lambda r: r["mean"])
    lig = [r for r in rows if r["label"].startswith("L:")]
    show = prot[:9] + prot[-2:]
    show = sorted(show, key=lambda r: r["mean"])                      # most favourable first (drawn at the top)
    fig, ax = plt.subplots(1, 2, figsize=(7.4, 3.9), gridspec_kw={"width_ratios": [1, 1.15]})
    y = np.arange(len(show))
    cols = ["#d55e00" if r["mean"] > 0 else ("#0072b2" if (np.isnan(r["occ"]) or r["occ"] >= 10) else "#9db9d1") for r in show]
    ax[0].barh(y, [r["mean"] for r in show], xerr=[r["sem"] for r in show], color=cols, ecolor="k", error_kw={"lw": 0.7}, height=0.7)
    ax[0].set_yticks(y)
    ax[0].set_yticklabels([f"{r['label'].split(':')[2].title()}{r['pdb']}" for r in show])
    ax[0].axvline(0, color="k", lw=0.6)
    ax[0].set_xlabel("ΔE of the residue upon ligand binding\n(kcal/mol, mean ± SEM, 201 frames)")
    ax[0].invert_yaxis()
    ax[0].text(0.99, 0.99, "light blue: contact in\n< 10 % of the 10–20 ns frames", transform=ax[0].transAxes, ha="right", va="top", fontsize=6.3, color="#555555")
    panel(ax[0], "a")
    e = energy_numbers(a)
    labels = ["ΔE_vdW", "ΔE_ele", "ΔG_PB", "ΔG_np", "ΔG_MM-PBSA", "−TΔS\n(last 25 %)", "−TΔS\n(all)", "ΔG_eff\n(last 25 %)", "ΔG_eff\n(all)"]
    vals = [e["VDWAALS"][0], e["EEL"][0], e["EPB"][0], e["ENPOLAR"][0], e["TOTAL"][0], e["IE_seg"][0], e["IE_all"][0], e["dGeff_seg"][0], e["dGeff_all"][0]]
    lo = [e["VDWAALS"][1], e["EEL"][1], e["EPB"][1], e["ENPOLAR"][1], e["TOTAL"][1], 0, 0, 0, 0]
    err = np.zeros((2, len(vals)))
    err[0, :5] = [e[k][1] for k in ("VDWAALS", "EEL", "EPB", "ENPOLAR", "TOTAL")]
    err[1, :5] = err[0, :5]
    for j, key in zip((5, 6, 7, 8), ("IE_seg", "IE_all", "dGeff_seg", "dGeff_all")):
        err[0, j] = vals[j] - e[key][1]
        err[1, j] = e[key][2] - vals[j]
    colors = ["#56b4e9"] * 4 + ["#0072b2"] + ["#e69f00"] * 2 + ["#009e73"] * 2
    ax[1].bar(np.arange(len(vals)), vals, yerr=err, color=colors, ecolor="k", error_kw={"lw": 0.7, "capsize": 2})
    ax[1].axhline(0, color="k", lw=0.6)
    ax[1].set_xticks(np.arange(len(vals)))
    ax[1].set_xticklabels(labels, rotation=55, ha="right", fontsize=6.8)
    ax[1].set_ylabel("kcal/mol")
    ax[1].text(0.99, 0.03, "error bars: SD (MM-PBSA terms);\n95 % block-bootstrap interval (−TΔS, ΔG_eff)", transform=ax[1].transAxes,
               va="bottom", ha="right", fontsize=6.3, color="#555555")
    panel(ax[1], "b")
    fig.tight_layout()
    return save(fig, a, "Figure7_energetics")


def fig8(a, data):
    plt = mpl()
    names = [n for n in LABEL if n in data and "zn_d" in data[n]]
    if not names:
        raise RuntimeError("no Zn data")
    fig, ax = plt.subplots(2, 1, figsize=(6.3, 5.6), sharex=True)
    for n in names:
        d = data[n]
        ax[0].plot(d["t"], d["zn_d"][:, 3], color=COLOR[n], lw=0.8)
        ax[1].plot(d["t"], d["zn_near"], color=COLOR[n], lw=0.8)
    ax[0].axhline(0.240, color="k", lw=0.7, ls="--")
    ax[0].text(0.995, 0.255, "crystal Zn–Cys242 Sγ 0.240 nm", transform=ax[0].get_yaxis_transform(), ha="right", va="bottom", fontsize=6.5)
    ax[0].set_yscale("log")
    ax[0].axhline(6.69, color="#888888", lw=0.7, ls=":")
    ax[0].text(0.005, 6.69, "largest possible minimum-image distance (≈ 6.7 nm)", transform=ax[0].get_yaxis_transform(), ha="left", va="bottom", fontsize=6.3, color="#555555")
    ax[0].set_ylabel("Zn²⁺ – Cys242 Sγ\ndistance (nm)")
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter
    ax[0].set_ylim(0.2, 9.0)
    ax[0].yaxis.set_major_locator(FixedLocator([0.3, 0.5, 1, 2, 3, 5]))
    ax[0].yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax[0].yaxis.set_minor_formatter(NullFormatter())
    ax[1].set_ylabel("Zn²⁺ – nearest\nprotein atom (nm)")
    ax[1].set_xlabel("Time (ns)")
    ax[1].set_xlim(0, a.tmax)
    fig_legend(fig, names)
    panel(ax[0], "a")
    panel(ax[1], "b")
    return save(fig, a, "Figure8_zinc")


# ----------------------------------------------------------------------------------------------------------------
# tables and legends
# ----------------------------------------------------------------------------------------------------------------
def tables(a, data):
    root = os.path.expanduser(a.root)
    out = os.path.join(root, a.out)
    os.makedirs(out, exist_ok=True)
    t1 = os.path.join(root, a.checks_dir, "table1_summary.csv")
    if os.path.exists(t1):
        import csv
        with open(t1) as fh:
            rows = {r["system"]: r for r in csv.DictReader(fh)}
        with open(os.path.join(out, "Table1_revised.csv"), "w") as fh:
            fh.write("System,Final COM distance at 20.00 ns (nm),Mean ± SD (nm),Maximum (nm),Ligand in pocket contact 0-20 ns (%),"
                     "10-20 ns (%),Last contact (ns),First stable exit >= 1 ns (ns),Backbone RMSD 10-20 ns (nm)\n")
            for n in LABEL:
                if n not in rows:
                    continue
                r = rows[n]
                rm = ""
                if n in data:
                    m = data[n]["t"] >= a.win_start
                    rm = f"{data[n]['rmsd'][m].mean():.3f} ± {data[n]['rmsd'][m].std(ddof=1):.3f}"
                ex = "none" if r["first_stable_exit_ns"] in ("nan", "") else f"{float(r['first_stable_exit_ns']):.2f}"
                fh.write(f"{LABEL[n]},{float(r['final_com_mic_nm']):.2f},{float(r['mean_com_mic_nm']):.2f} ± {float(r['sd_com_mic_nm']):.2f},"
                         f"{float(r['max_com_mic_nm']):.2f},{float(r['pct_contact_all']):.1f},{float(r['pct_contact_window']):.1f},"
                         f"{float(r['last_contact_ns']):.2f},{ex},{rm}\n")
        log("  written Table1_revised.csv")
    else:
        log(f"  Table 1 skipped: {t1} not found (run: python tp53_checks.py md)")
    names = [n for n in LABEL if n in data]
    if names:
        with open(os.path.join(out, "Table2_revised.csv"), "w") as fh:
            fh.write("Residue," + ",".join(LABEL[n] for n in names) + "\n")
            for p, rn in POCKET.items():
                vals = []
                for n in names:
                    i = np.where(data[n]["ca_resnum"] == p)[0]
                    vals.append(f"{data[n]['rmsf'][i[0]]:.3f}" if len(i) else "")
                fh.write(f"{rn.title()}{p}," + ",".join(vals) + "\n")
        log("  written Table2_revised.csv")
    try:
        e = energy_numbers(a)
        with open(os.path.join(out, "Table3_energy.csv"), "w") as fh:
            fh.write("Term,Value (kcal/mol),Uncertainty\n")
            for k, lab in (("VDWAALS", "dE_vdW"), ("EEL", "dE_ele"), ("EPB", "dG_PB"), ("ENPOLAR", "dG_nonpolar"), ("GGAS", "dG_gas"),
                           ("GSOLV", "dG_solv"), ("TOTAL", "dG_MM-PBSA")):
                fh.write(f"{lab},{e[k][0]:.2f},SD {e[k][1]:.2f}\n")
            fh.write(f"-T*dS (last 25 % of frames),{e['IE_seg'][0]:.2f},95 % CI [{e['IE_seg'][1]:.1f}; {e['IE_seg'][2]:.1f}]\n")
            fh.write(f"-T*dS (all frames),{e['IE_all'][0]:.2f},95 % CI [{e['IE_all'][1]:.1f}; {e['IE_all'][2]:.1f}]\n")
            fh.write(f"dG_eff (last 25 %),{e['dGeff_seg'][0]:.2f},95 % CI [{e['dGeff_seg'][1]:.1f}; {e['dGeff_seg'][2]:.1f}]\n")
            fh.write(f"dG_eff (all frames),{e['dGeff_all'][0]:.2f},95 % CI [{e['dGeff_all'][1]:.1f}; {e['dGeff_all'][2]:.1f}]\n")
        log("  written Table3_energy.csv")
    except Exception as ex_:
        log(f"  Table 3 skipped: {type(ex_).__name__}: {ex_}")


LEGENDS = """Figure 1. Revised workflow of the study. Docking was used only to generate a starting pose; the site was not reproduced with an independent scoring function (Vinardo). Zn2+ was a non-bonded ion and was excluded from the MM-PBSA calculations. The quinuclidine simulation is exploratory (incomplete C-terminal residue in its protein topology).
Figure 2. (a) Protein backbone (N, CA, C, O) RMSD of the four PRIMA-1 replicates and of the quinuclidine simulation (fit to the first frame). (b) Heavy-atom RMSD of the ligand after fitting the protein C-alpha atoms, computed with the minimum-image convention; frames in which the ligand is farther than 3.4 nm from the pocket are not shown, because the RMSD is no longer defined unambiguously in a periodic box; thin lines are the 10-ps data, thick lines a 0.5-ns running mean.
Figure 3. Radius of gyration of the protein in the five simulations (first 20 ns).
Figure 4. Per-residue C-alpha RMSF (fit of the backbone to the first frame, 0-20 ns). Dotted lines mark the nine residues that line the docked site.
Figure 5. (a) Distance between the centre of mass of the ligand and the centre of mass of the C-alpha atoms of the nine site residues (minimum-image convention, 0-20.00 ns). (b) Minimum heavy-atom distance between the ligand and the nine site residues; the dashed line is the contact cut-off (0.45 nm).
Figure 6. Ligand-protein hydrogen bonds (donor-acceptor distance < 3.5 A, donor-H-acceptor angle > 150 degrees; water-mediated and intramolecular bonds are not counted). (a) Percentage of frames with at least one bond. (b) Number of bonds, 1-ns running mean (computed from the frames available in each window).
Figure 7. (a) Per-residue contribution to the binding energy (Delta = complex - receptor - ligand; MM-PBSA decomposition of Replicate 1, 201 frames, mean +- SEM). Light blue: residues in contact with the ligand in < 10 % of the 10-20 ns frames. The ligand itself contributes -5.61 +- 0.12 kcal/mol and no single residue contributes more than 0.6 kcal/mol in magnitude. (b) MM-PBSA energy terms (mean +- SD) and interaction-entropy corrected free energies with 95 % block-bootstrap intervals.
Figure 8. Behaviour of the structural Zn2+ ion (non-bonded model). (a) Distance to the Sgamma atom of Cys242 (minimum-image convention; the dashed line is the crystallographic distance). (b) Distance to the nearest protein atom. The ion left its site during equilibration and never returned in any simulation.
"""


def selftest():
    print("selftest: nothing numerical to check here; run `python make_revised_figures.py --only-figs 1` to test the plotting stack")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="~/tp53_md_project")
    ap.add_argument("--system", nargs=3, action="append", metavar=("NAME", "TOP", "TRAJ"))
    ap.add_argument("--only", nargs="+")
    ap.add_argument("--only-figs", nargs="+", type=int, help="draw only these figure numbers (1-8); tables are written when 5, 7 or 2 are included, or with 0")
    ap.add_argument("--tmax", type=float, default=20.0)
    ap.add_argument("--win-start", type=float, default=10.0)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--mask-nm", type=float, default=3.4, help="Figure 2b: hide ligand RMSD when the ligand is farther than this from the pocket")
    ap.add_argument("--out", default="revised_figures")
    ap.add_argument("--checks-dir", default="analysis_checks")
    ap.add_argument("--decomp-csv", default="mmpbsa_decomp_full/decomp_delta_summary.csv")
    ap.add_argument("--energy-csv", default="mmpbsa_run1_energy.csv")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--skip-hbond", action="store_true")
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    figs = {1: fig1, 2: fig2, 3: fig3, 4: fig4, 5: fig5, 6: fig6, 7: fig7, 8: fig8}
    want = a.only_figs if a.only_figs else list(figs) + [0]
    need_traj = any(k in want for k in (2, 3, 4, 6, 8, 0))
    data = {}
    if need_traj:
        log("trajectory-derived data (cached in figure_data/):")
        data = load_data(a)
    for k in want:
        if k == 0:
            continue
        try:
            log(f"Figure {k}:")
            figs[k](a, data)
        except Exception as e:
            log(f"  Figure {k} FAILED: {type(e).__name__}: {e}")
            LOG.append(traceback.format_exc())
    if 0 in want or any(k in want for k in (2, 5, 7)):
        log("tables:")
        try:
            tables(a, data)
        except Exception as e:
            log(f"  tables FAILED: {type(e).__name__}: {e}")
    out = os.path.join(os.path.expanduser(a.root), a.out)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "figure_legends.txt"), "w") as fh:
        fh.write(LEGENDS)
    with open(os.path.join(out, "make_revised_figures_log.txt"), "w") as fh:
        fh.write("\n".join(LOG))
    print(f"\nAll output is in {out}/")


if __name__ == "__main__":
    main()
