"""Turn results/runs.csv and the pretraining logs into the tables and figures.

Run from the repo root:  python scripts/make_report.py

Writes results/report.md, results/figures/effective_rank.png and
results/figures/arm_comparison.png (each also in a dark variant).
"""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

RESULTS = Path("results")
FIGURES = RESULTS / "figures"

ARM_NAMES = {"A": "A  none", "B": "B  vector", "C": "C  letter", "D": "D  both"}
ARM_ORDER = ["A", "B", "C", "D"]

# Validated with the dataviz skill's checker (light and dark surfaces).
THEME = {
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df",
              "series": {"A": "#52514e", "B": "#eb6834", "C": "#2a78d6", "D": "#1baf7a"}},
    "dark": {"surface": "#1a1a19", "ink": "#f0efec", "muted": "#c3c2b7", "grid": "#343431",
             "series": {"A": "#c3c2b7", "B": "#d95926", "C": "#3987e5", "D": "#199e70"}},
}


def load_runs(corpus_key):
    df = pd.read_csv(RESULTS / "runs.csv")
    df["arm"] = df.arm.astype(str)
    if "corpus" in df:
        # Arm A has no pretraining, so its corpus is "none". Older pilot rows are
        # tagged "pilot" and left out so they don't double-count a seed.
        df = df[df.corpus.isin([corpus_key, "none"])]
    # A re-run of the same configuration supersedes the earlier row.
    return df.drop_duplicates(["arm", "seed", "finetune_mode"], keep="last")


def load_pretrain_logs(corpus_key):
    frames = []
    # Only this corpus's logs; pilot runs live in pretrain_*_pilot_seed*.csv.
    for path in sorted(RESULTS.glob(f"pretrain_*_{corpus_key}_seed*.csv")):
        frame = pd.read_csv(path)
        # A resumed run re-logs the epochs after its last save point.
        frame = frame.drop_duplicates(["arm", "seed", "epoch"], keep="last")
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def summarise(df, columns):
    """mean ± sd per arm, with the number of seeds behind it."""
    rows = []
    for arm in ARM_ORDER:
        part = df[df.arm == arm]
        if part.empty:
            continue
        row = {"arm": ARM_NAMES[arm], "seeds": len(part)}
        for column in columns:
            sd = part[column].std()
            row[column] = (f"{part[column].mean():.3f} ± {sd:.3f}"
                           if len(part) > 1 else f"{part[column].mean():.3f}")
        rows.append(row)
    return pd.DataFrame(rows)


def markdown_table(df):
    return df.to_markdown(index=False) if not df.empty else "_no runs yet_"


def style(ax, theme, xlabel, ylabel, title):
    colors = THEME[theme]
    ax.set_facecolor(colors["surface"])
    ax.figure.set_facecolor(colors["surface"])
    ax.set_xlabel(xlabel, color=colors["muted"], fontsize=9)
    ax.set_ylabel(ylabel, color=colors["muted"], fontsize=9)
    ax.set_title(title, color=colors["ink"], fontsize=11, loc="left", pad=12)
    ax.tick_params(colors=colors["muted"], labelsize=8, length=0)
    ax.grid(True, color=colors["grid"], linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)


def rank_figure(logs, theme):
    colors = THEME[theme]
    fig, ax = plt.subplots(figsize=(7, 4.2))

    for arm in ARM_ORDER:
        part = logs[(logs.arm == arm) & (logs.seed == logs.seed.min())]
        if part.empty or "val_effective_rank" not in part:
            continue
        part = part.sort_values("epoch")
        colour = colors["series"][arm]
        ax.plot(part.epoch, part.val_effective_rank, color=colour, linewidth=2)
        ax.annotate(ARM_NAMES[arm].split()[1], xy=(part.epoch.iloc[-1],
                                                   part.val_effective_rank.iloc[-1]),
                    xytext=(6, 0), textcoords="offset points", color=colour,
                    fontsize=9, va="center", fontweight="medium")

    style(ax, theme, "pretraining epoch", "effective rank (of 128)",
          "Arm B collapses, then climbs out — and still transfers worst")
    ax.set_xlim(left=-2)
    ax.margins(x=0.12)
    fig.tight_layout()
    return fig


def comparison_figure(runs, theme):
    colors = THEME[theme]
    frozen = runs[runs.finetune_mode == "frozen"]
    full = runs[runs.finetune_mode == "full"]

    fig, ax = plt.subplots(figsize=(7, 4.2))
    labels, positions = [], []
    for i, arm in enumerate(ARM_ORDER):
        colour = colors["series"][arm]
        for offset, part, marker in ((-0.14, full, "o"), (0.14, frozen, "D")):
            values = part[part.arm == arm].test_pooled_spearman
            if values.empty:
                continue
            ax.scatter([i + offset] * len(values), values, s=46, color=colour,
                       marker=marker, edgecolor=colors["surface"], linewidth=1.5, zorder=3)
            if len(values) > 1:
                ax.plot([i + offset, i + offset], [values.min(), values.max()],
                        color=colour, linewidth=2, alpha=0.5, zorder=2)
        labels.append(ARM_NAMES[arm])
        positions.append(i)

    baseline = runs[(runs.arm == "A")].test_pooled_spearman.mean()
    ax.axhline(baseline, color=colors["muted"], linewidth=1, linestyle=(0, (4, 3)))
    ax.annotate("no pretraining", xy=(len(ARM_ORDER) - 0.5, baseline), xytext=(0, 5),
                textcoords="offset points", color=colors["muted"], fontsize=8, ha="right")

    ax.set_xticks(positions)
    ax.set_xticklabels(labels)
    style(ax, theme, "", "test pooled Spearman",
          "Circles: full fine-tuning.  Diamonds: frozen encoder.  One point per seed.")
    fig.tight_layout()
    return fig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="SCOPe, 11,566 domains")
    parser.add_argument("--corpus-key", default="scope",
                        help="value of the corpus column in runs.csv to report on")
    args = parser.parse_args()
    key = args.corpus_key

    FIGURES.mkdir(parents=True, exist_ok=True)
    runs = load_runs(key)
    logs = load_pretrain_logs(key)

    metrics = ["test_pooled_spearman", "test_per_protein_median_spearman", "test_rmse"]
    frozen = summarise(runs[runs.finetune_mode == "frozen"], metrics)
    full = summarise(runs[runs.finetune_mode == "full"], metrics)

    embedding = pd.DataFrame()
    cost = pd.DataFrame()
    if not logs.empty:
        last = logs.sort_values("epoch").groupby(["arm", "seed"]).last().reset_index()
        embedding = summarise(last, ["val_effective_rank"])
        if "val_letter_accuracy" in last:
            accuracy = summarise(last.dropna(subset=["val_letter_accuracy"]),
                                 ["val_letter_accuracy"])
            embedding = embedding.merge(accuracy, on=["arm", "seeds"], how="left")
        cost = summarise(logs.groupby(["arm", "seed"]).seconds.mean().reset_index(),
                         ["seconds"])

    n_residues = (int(logs.val_n_residues_for_rank.iloc[0])
                  if "val_n_residues_for_rank" in logs else "?")

    report = f"""# Results

Pretraining corpus: {args.corpus}. Fine-tuning: MegaScale, 271,231 single mutations over
298 proteins, ThermoMPNN splits, test set 28 proteins.

A difference under 0.012 pooled or 0.016 per-protein median is a tie: that is roughly two
standard deviations of arm A across seeds, fixed before any pretrained arm was run.

## Main table, frozen encoder

Arm A has nothing to freeze, so it appears only in the full table below.

{markdown_table(frozen)}

## Full fine-tuning

{markdown_table(full)}

## Embeddings

Effective rank at the end of pretraining, measured on {n_residues} held-out residues.
Rank is only comparable between runs measured the same way, and as the main table shows,
it does not predict which arm transfers best.

{markdown_table(embedding)}

## Cost

Seconds per pretraining epoch.

{markdown_table(cost)}

## Figures

- `figures/effective_rank_{key}.png` — effective rank through pretraining
- `figures/arm_comparison_{key}.png` — every seed's test score, by arm
"""
    (RESULTS / f"report_{key}.md").write_text(report)

    # Named per corpus, so reporting on one does not overwrite the other's figures.
    for theme in ("light", "dark"):
        suffix = f"_{key}" + ("" if theme == "light" else "_dark")
        if not logs.empty:
            fig = rank_figure(logs, theme)
            fig.savefig(FIGURES / f"effective_rank{suffix}.png", dpi=200,
                        facecolor=fig.get_facecolor())
            plt.close(fig)
        fig = comparison_figure(runs, theme)
        fig.savefig(FIGURES / f"arm_comparison{suffix}.png", dpi=200,
                    facecolor=fig.get_facecolor())
        plt.close(fig)

    print(report)
    print(f"wrote {RESULTS / f'report_{key}.md'} and figures in {FIGURES}")


if __name__ == "__main__":
    main()
