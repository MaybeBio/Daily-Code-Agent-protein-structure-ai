"""The tuned pair probes against published predictors on the 2024 Bernett gold standard.

    python -m plm_interpretability.published --out OUT [--summary SUMMARY]

Draws `ppi_published.png`: test MCC (A), ROC AUC (B) and PR AUC (C), methods ordered by the mean of the three metrics
(ties broken by MCC), a row of this study ranked by its tuned MLP. A row of this study holds two bars, the tuned MLP
(dark) and the survey's linear probe (light), and its color says what the row reads. Published values are `PUBLISHED`,
at their sources' two decimals; this study's are the rows of the tuned-probe summary, which the results archive holds
at `SUMMARY_FILE` and which is downloaded at `SUMMARY_REVISION` when `--summary` names no local copy. This study's PR
AUC is the average precision. Every plotted value and its source also go to `ppi_published.csv`.
"""

from __future__ import annotations

import argparse
import pandas as pd

from pathlib import Path
from huggingface_hub import hf_hub_download
from matplotlib.figure import Figure
from matplotlib.legend_handler import HandlerTuple
from matplotlib.patches import Rectangle
from src.protify.interpretability.figures import INK, INK_SECONDARY, _letter, _pyplot, _save

from plm_interpretability import archive
from plm_interpretability.figure_style import PUBLISHED_COLOR, READ_STATE_COLORS, ROW_BAND, site_math


# The tuned probes of every model's chosen states, last hidden state and controls, three seeds each.
SUMMARY_FILE = "analyses/last_hidden_controls/summary.parquet"
SUMMARY_REVISION = "0e526f4b"
# Published (MCC, ROC AUC, PR AUC) on the Bernett test split. DeepFE, PIPR, D-SCRIPT and Topsy-Turvy are Bernett and
# colleagues' re-evaluations as Ko and colleagues show them (their Figure 2b); TUnA and ESM2-MLP (frozen ESM-2
# embeddings and an MLP) are Ko and colleagues'; C3PI and PLM-interact are from their own publications. Left out:
# MINT, which reports PR AUC alone, and ProteomeLM-PPI, which reports no MCC and reads each pair within the whole
# proteome rather than from the two sequences. Where a method appears with and without early stopping, the variant with
# the higher MCC is kept.
PUBLISHED = {
    "TUnA": ((0.30, 0.70, 0.69), "Ko et al. 2024"),
    "C3PI": ((0.29, 0.70, 0.70), "Hosseini et al. 2025"),
    "PLM-interact": ((0.29, 0.70, 0.69), "Liu et al. 2025"),
    "ESM2-MLP": ((0.28, 0.70, 0.68), "Ko et al. 2024"),
    "D-SCRIPT": ((0.17, 0.56, 0.58), "Bernett et al. 2024, via Ko et al. 2024"),  # its early-stopped variant
    "Topsy-Turvy": ((0.15, 0.59, 0.59), "Bernett et al. 2024, via Ko et al. 2024"),
    "PIPR": ((0.04, 0.54, 0.53), "Bernett et al. 2024, via Ko et al. 2024"),  # its early-stopped variant
    "DeepFE": ((0.04, 0.52, 0.51), "Bernett et al. 2024, via Ko et al. 2024"),
}
# Plotted metric -> (summary column, bootstrap column or None, axis label, axis start, axis end); the axis ends leave
# the value column clear.
METRICS = {
    "mcc": ("test_mcc", None, "Test MCC", 0.0, 0.38),
    "roc_auc": ("test_roc_auc", "test.roc_auc", "Test ROC AUC", 0.5, 0.79),
    "pr_auc": ("test_average_precision", "test.average_precision", "Test PR AUC", 0.5, 0.79),
}
# (model, kind, the row's name) of each row of this study; None names it by model and state.
ROWS = (("ESMC-6B", "inside", None), ("ESMC-600", "inside", None), ("ESMC-300", "inside", None), ("ESMC-6B", "stream", None), ("ESMC-6B", "last", None), ("ESMC-600", "last", None),
        ("ESMC-300", "last", None), ("ESMC-300 random init", "control", "random init ESMC-300"), ("OneHot-Protein", "control", "one-hot"), ("Random", "control", "random vectors"))
FAMILIES = {"inside": "intra-block state", "stream": "best stream state", "last": "last hidden state", "control": "control"}
BASELINE_ENCODINGS = ("OneHot-Protein", "Random")  # they have one state, which their rows do not name
BAR_HEIGHT = 0.38
VALUE_SIZE = 5.0
VALUE_COLUMN = 0.885  # where every value starts, as a share of its axis: one column, past every bar and whisker


def own_row(arms: pd.DataFrame, label: str, kind: str) -> list[dict[str, object]]:
    """A state's two bars: `arms` holds one row per probe, indexed by probe."""
    bars = []
    for probe, shade in (("mlp", 0), ("naive", 1)):
        arm = arms.loc[probe]
        bar: dict[str, object] = {"label": label, "probe": probe, "source": "this study, mean of three seeds", "color": READ_STATE_COLORS[kind][shade]}
        for metric, (column, draws, *_) in METRICS.items():
            bar[metric] = float(arm[column])
            if draws:
                bar[f"{metric}_low"], bar[f"{metric}_high"] = float(arm[f"{draws}_low"]), float(arm[f"{draws}_high"])
        bars.append(bar)
    return bars


def table(summary: pd.DataFrame) -> pd.DataFrame:
    """One row per plotted bar, with its row's position `row`: published methods have one bar, this study's states two."""
    gold_2024 = summary[summary["task"] == "ppi"]
    bars: list[dict[str, object]] = [{"label": name, "probe": "published", "source": source, **dict(zip(METRICS, values, strict=True)), "color": PUBLISHED_COLOR}
                                     for name, (values, source) in PUBLISHED.items()]
    for model, kind, name in ROWS:
        arms = gold_2024[(gold_2024["model"] == model) & (gold_2024["kind"] == kind)].set_index("probe")
        site, layer = arms["site"].iloc[0], int(arms["layer"].iloc[0])
        state = "" if model in BASELINE_ENCODINGS else site_math(site) if site == "final_norm" else f"{site_math(site)} {layer}"
        bars += own_row(arms, f"{model} {state}" if name is None else f"{name} {state}".strip(), kind)
    plotted = pd.DataFrame(bars)
    leaders = plotted[plotted["probe"].isin(("mlp", "published"))].assign(mean=lambda rows: rows[list(METRICS)].mean(axis=1).round(4))
    # barh draws from the bottom, so the best method comes last; published values carry two decimals, so equal means tie
    order = leaders.sort_values(["mean", "mcc"], ascending=True, kind="stable")["label"].tolist()
    return plotted.assign(row=plotted["label"].map({label: position for position, label in enumerate(order)}))


def keys(figure: Figure, top: float) -> None:
    """The color key and the shade key, above the panels and clear of every bar."""
    swatches = [Rectangle((0, 0), 1, 1, color=READ_STATE_COLORS[kind][0]) for kind in FAMILIES] + [Rectangle((0, 0), 1, 1, color=PUBLISHED_COLOR)]
    shades = [tuple(Rectangle((0, 0), 1, 1, color=READ_STATE_COLORS[kind][shade]) for kind in ("inside", "stream", "last")) for shade in (0, 1)]
    figure.legend(swatches + shades, [*FAMILIES.values(), "published", "tuned MLP", "survey linear"], loc="lower center", bbox_to_anchor=(0.5, top), ncols=7, frameon=False, fontsize=6,
                  handlelength=1.8, handleheight=0.8, columnspacing=1.0, handletextpad=0.4, handler_map={tuple: HandlerTuple(ndivide=None, pad=0.0)})


def draw(bars: pd.DataFrame, path: Path) -> Path:
    plt = _pyplot()
    rows = bars["row"].nunique()
    figure, axes = plt.subplots(1, len(METRICS), figsize=(7.2, 0.27 * rows + 0.42), sharey=True, gridspec_kw={"wspace": 0.1})
    published = bars[bars["probe"] == "published"]
    offsets = {"mlp": BAR_HEIGHT / 2, "naive": -BAR_HEIGHT / 2, "published": 0.0}
    heights = {"mlp": BAR_HEIGHT, "naive": BAR_HEIGHT, "published": 0.72}
    banded = {row for row in range(rows) if (rows - 1 - row) % 2 == 1}
    for axis, letter, (metric, (_, draws, label, low, high)) in zip(axes, "ABC", METRICS.items(), strict=True):
        for row in banded:
            axis.axhspan(row - 0.5, row + 0.5, color=ROW_BAND, lw=0, zorder=0)
        positions = bars["row"] + bars["probe"].map(offsets)
        axis.barh(positions, (bars[metric] - low).clip(lower=0), left=low, color=bars["color"], height=bars["probe"].map(heights), zorder=2)
        if draws:
            ours = bars[bars[f"{metric}_low"].notna()]
            axis.errorbar(ours[metric], ours["row"] + ours["probe"].map(offsets), xerr=[ours[metric] - ours[f"{metric}_low"], ours[f"{metric}_high"] - ours[metric]],
                          fmt="none", ecolor=INK, elinewidth=0.6, capsize=1.1, zorder=3)
            assert bars[f"{metric}_high"].max() < low + VALUE_COLUMN * (high - low), f"a {metric} whisker reaches the value column"
        assert bars[metric].max() < low + VALUE_COLUMN * (high - low), f"a {metric} bar reaches the value column"
        axis.axvline(published[metric].max(), color=INK_SECONDARY, lw=0.7, ls="--", zorder=1)  # the best published value, behind the bars
        for position, value, probe in zip(positions, bars[metric], bars["probe"], strict=True):
            # published values carry their source's two decimals; x is a share of the axis, so every value starts at one place
            text = f"{value:.2f}" if probe == "published" else f"{value:.3f}"
            axis.text(VALUE_COLUMN, position, text, transform=axis.get_yaxis_transform(), va="center", ha="left", fontsize=VALUE_SIZE, color=INK, zorder=4)
        axis.set_xlim(low, high)
        axis.set_ylim(-0.5, rows - 0.5)
        axis.set_xlabel(label)
        axis.tick_params(axis="y", length=0)
        _letter(axis, letter, x=-0.08 if letter == "A" else -0.02)
    labels = bars.drop_duplicates("row").sort_values("row")
    top = len(labels) - 1
    # the top row's label in bold, its mathtext as well
    axes[0].set_yticks(labels["row"].tolist(), [name.replace(r"\mathrm", r"\mathbf") if row == top else name for row, name in zip(labels["row"], labels["label"], strict=True)])
    axes[0].get_yticklabels()[labels["row"].tolist().index(top)].set_fontweight("bold")
    keys(figure, 0.925)
    return _save(figure, path)


def write_all(summary: Path, out: Path) -> list[Path]:
    """The figure and its table of plotted values, from the tuned-probe summary at `summary`."""
    bars = table(pd.read_parquet(summary))
    out.mkdir(parents=True, exist_ok=True)
    bars.sort_values(["row", "probe"], ascending=[False, True]).drop(columns="color").to_csv(out / "ppi_published.csv", index=False)
    return [draw(bars, out / "ppi_published.png"), out / "ppi_published.csv"]


def download_summary(out: Path) -> Path:
    """The tuned-probe summary of the results archive at its pinned revision, under `out`."""
    return Path(hf_hub_download(archive.REPO, SUMMARY_FILE, repo_type="dataset", revision=SUMMARY_REVISION, local_dir=out))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path, default=None, help="a local copy of the summary (default: download it into <out>/archive)")
    args = parser.parse_args()
    for path in write_all(args.summary or download_summary(args.out / "archive"), args.out):
        print(path)


if __name__ == "__main__":
    main()
