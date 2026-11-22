"""
Phase 9: publication figures (300 DPI) and IEEE-style tables built from the saved result CSVs.
No torch needed. Produces:
  results/figures/ablation_barchart.png
  results/figures/cold_split_identity_hist.png
  results/final_tables.md
(degree_distribution.png comes from network_analysis.py; roc_curves.png from roc_curves.py)
STRING outputs are included automatically when results/string_*.csv exist.
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yaml

COL_W = 7.16  # IEEE double-column width (inches)
ORDER = [("GCN", "Structure Only", "Structure only"),
         ("GCN", "Sequence + Structure", "GCN + ESM-2"),
         ("GCN", "Classical + Structure", "GCN + Classical"),
         ("RandomForest", "Classical Sequence", "RF (Classical)")]
SPLITS = ["Random Split", "Cold-Protein Split"]
plt.rcParams.update({"font.size": 8, "axes.titlesize": 9, "font.family": "serif"})


def read(path):
    return pd.read_csv(path) if os.path.exists(path) else None


def pick(df, model, feat, split):
    r = df[(df.Model == model) & (df.Features == feat) & (df.Split == split)]
    return None if r.empty else r.iloc[0]


def ablation_chart(datasets, out):
    fig, axes = plt.subplots(1, len(datasets), figsize=(COL_W, 2.9), sharey=True, squeeze=False)
    width = 0.19
    for ax, (title, df) in zip(axes[0], datasets):
        x = np.arange(len(SPLITS))
        for i, (m, f, label) in enumerate(ORDER):
            means = [pick(df, m, f, s)["AUC_mean"] for s in SPLITS]
            stds = [pick(df, m, f, s)["AUC_std"] for s in SPLITS]
            ax.bar(x + (i - 1.5) * width, means, width, yerr=stds, capsize=2, label=label,
                   edgecolor="black", linewidth=0.4)
        ax.axhline(0.5, color="gray", ls="--", lw=0.8)
        ax.set_xticks(x); ax.set_xticklabels(["Random", "Cold-protein"])
        ax.set_title(title); ax.set_ylim(0.5, 1.0); ax.grid(axis="y", alpha=0.3)
    axes[0][0].set_ylabel("Test AUC (mean ± std, 5 seeds)")
    axes[0][-1].legend(loc="upper right", fontsize=6.5, frameon=True)
    fig.tight_layout(); fig.savefig(out, dpi=300); plt.close(fig)


def identity_hist(ident, summ, out):
    v = ident["max_sequence_identity"] * 100
    fig, ax = plt.subplots(figsize=(3.5, 2.6))
    ax.hist(v, bins=40, edgecolor="black", linewidth=0.3)
    ax.axvline(30, color="red", ls="--", lw=1)
    ax.set_xlabel("Max. sequence identity to any training protein (%)")
    ax.set_ylabel("Cold test proteins")
    pct = summ["Pct_Under_30"].iloc[0]
    ax.text(0.97, 0.95, f"{pct:.1f}% below 30%\n(n = {len(v)})", transform=ax.transAxes,
            ha="right", va="top", fontsize=7)
    fig.tight_layout(); fig.savefig(out, dpi=300); plt.close(fig)


def md_table(df):
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def perf_table(df):
    rows = []
    for m, f, label in ORDER:
        row = {"Model": label}
        for s, sl in zip(SPLITS, ["Random", "Cold-protein"]):
            r = pick(df, m, f, s)
            row[f"AUC ({sl})"] = f"{r['AUC_mean']:.3f} ± {r['AUC_std']:.3f}"
        rows.append(row)
    return pd.DataFrame(rows)


def wil_table(w):
    w = w.copy()
    w["Comparison"] = w["B"] + " vs " + w["A"]
    out = w[["Split", "Comparison", "mean_AUC_diff(B-A)", "B_wins", "p_two_sided", "p_one_sided(B>A)"]].copy()
    out.columns = ["Split", "Comparison (B vs A)", "Mean ΔAUC", "B wins /n", "p (two-sided)", "p (one-sided, B>A)"]
    out["B wins /n"] = [f"{b}/{n}" for b, n in zip(w["B_wins"], w["n_pairs"])]
    out["Mean ΔAUC"] = out["Mean ΔAUC"].map(lambda v: f"{v:+.4f}")
    out["p (two-sided)"] = out["p (two-sided)"].map(lambda v: f"{v:.4f}")
    out["p (one-sided, B>A)"] = out["p (one-sided, B>A)"].map(lambda v: f"{v:.4f}")
    return out


def main():
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    res, figs = cfg["data"]["results_dir"], cfg["data"]["figures_dir"]
    os.makedirs(figs, exist_ok=True)
    P = lambda n: os.path.join(res, n)

    pk, st = read(P("multiseed_metrics.csv")), read(P("string_multiseed_metrics.csv"))
    if pk is None:
        raise FileNotFoundError("results/multiseed_metrics.csv missing - run src/multiseed.py first")
    sets = [("PrimeKG", pk)] + ([("STRING (shared proteins)", st)] if st is not None else [])
    ablation_chart(sets, os.path.join(figs, "ablation_barchart.png"))

    ident, summ = read(P("cold_split_identities.csv")), read(P("cold_split_identity_summary.csv"))
    if ident is not None and summ is not None:
        identity_hist(ident, summ, os.path.join(figs, "cold_split_identity_hist.png"))

    md = ["# Final Tables\n",
          "*Test AUC is the headline metric. Precision/recall/F1 are omitted because the dot-product decoder "
          "predicts 'interaction' for nearly every pair at the 0.5 threshold in several GCN settings "
          "(precision 0.5, recall 1.0), so those numbers are degenerate.*\n"]
    n = 1
    md.append(f"**Table {n}. Link-prediction test AUC on PrimeKG (5 seeds).**\n\n{md_table(perf_table(pk))}\n"); n += 1
    if st is not None:
        md.append(f"**Table {n}. Link-prediction test AUC on STRING v12.0 physical links (score ≥ 700, proteins shared with PrimeKG; 5 seeds).**\n\n{md_table(perf_table(st))}\n"); n += 1
    for name, fn in [("PrimeKG", "wilcoxon_tests.csv"), ("STRING", "string_wilcoxon_tests.csv")]:
        w = read(P(fn))
        if w is not None:
            md.append(f"**Table {n}. Paired Wilcoxon signed-rank tests on test AUC, {name} (exact p-values). "
                      f"With {int(w['n_pairs'].iloc[0])} pairs the smallest attainable two-sided p is "
                      f"{2 / 2 ** int(w['n_pairs'].iloc[0]):.4f}.**\n\n{md_table(wil_table(w))}\n"); n += 1
    ns, hubs = read(P("network_stats.csv")), read(P("top10_hubs.csv"))
    if ns is not None:
        ns = ns.rename(columns={ns.columns[0]: "Statistic"})
        ns["value"] = ns["value"].map(lambda v: f"{int(float(v)):,}" if float(v).is_integer() else f"{float(v):.4g}")
        md.append(f"**Table {n}. PrimeKG PPI network statistics.**\n\n{md_table(ns)}\n"); n += 1
    if hubs is not None:
        md.append(f"**Table {n}. Top-10 hub proteins by degree (PrimeKG).**\n\n{md_table(hubs)}\n"); n += 1
    if summ is not None:
        s = summ.iloc[0]
        t = pd.DataFrame([{"Cold test proteins": int(s["Sample_Size"]), "Mean identity": f"{s['Mean_Identity']:.3f}",
                           "Median identity": f"{s['Median_Identity']:.3f}", "% < 30%": s["Pct_Under_30"],
                           "% < 40%": s["Pct_Under_40"], "% > 70%": s["Pct_Over_70"]}])
        md.append(f"**Table {n}. Homology audit of the cold-protein test set (Smith-Waterman identity to nearest training protein).**\n\n{md_table(t)}\n"); n += 1
    mp = read(P("string_mapping_report.csv"))
    if mp is not None:
        md.append(f"**Table {n}. STRING graph construction.**\n\n{md_table(mp)}\n")
    with open(P("final_tables.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print("Wrote figures and", P("final_tables.md"))


if __name__ == "__main__":
    main()
