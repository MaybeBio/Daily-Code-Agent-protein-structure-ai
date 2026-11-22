"""E15's figures, each after a figure of the Goodfire report whose measurement it repeats on ESMC-600.

    python -m plm_interpretability.units.e15_figures --root RUN --out FOLDER

Reads a copy of E15's folders of the run (`write_sums`, `sparsify`, `communities`, `concept_groups`,
`erasure_levels`) and draws what it finds:

- `e15_basis.png`, after Tigges and colleagues' sparsification and feature taxonomy: the masked-token loss and the KL
  divergence as each residue keeps fewer coordinates, in the units' basis, in rotations of it, in random units and in
  the weakest; the share of one block's effect a cut keeps; and SAE decoder directions as sums of units' write vectors.
- `e15_communities.png`, after Shilov and colleagues' Figures 2 and 4: the share of held-out prompts a community
  explains against the shuffled baseline; the KL divergence with a community removed against kept alone; the model's
  confidence and top residue at the prompts explained; the first block of the explaining spans and the blocks
  communities span; each unit removed alone against all together; and the share of gate-closed cells among
  attributed cells (Tigges and colleagues' quadrants).
- `e15_groups.png`: each concept's group of labeled poles removed together against its placebo groups and its best
  single pole.
- `e15_erasure.png`, after Fel and colleagues' Figure 7a: readers of a concept at and after the block LEACE erased.

No figure carries a title, panels are lettered and the caption carries the rest.
"""

from __future__ import annotations

import argparse
import json
import matplotlib
import numpy as np
import pandas as pd

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from matplotlib.lines import Line2D

from .figures import INK, MUTED, NATIVE, ROTATION, SAE, STYLE, letter, new_figure, save_figure


if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure


RANDOM, WEAKEST = "#c9ced4", "#44546a"
BASIS_STYLES = {"native": ("neurons", NATIVE, "o"), "rotation": ("rotations", ROTATION, "s"), "random": ("random", RANDOM, "^"),
                "weakest": ("weakest", WEAKEST, "v")}
READER_STYLES = {"linear_original": ("original linear", MUTED, "--"), "linear": ("refit linear", INK, "-"),
                 "mlp": ("refit MLP", NATIVE, "-"), "linear_variance": ("variance, linear", SAE, "-")}
KIND_ORDER = ("Domain", "Region", "Motif", "Zinc finger", "Active site")
THRESHOLDS = (0.7, 0.2)  # necessity and sufficiency


def _curves(ax: Axes, rows: pd.DataFrame, value: str) -> None:
    """One line a basis along the kept count, rotations as their mean."""
    for basis, (name, color, marker) in BASIS_STYLES.items():
        series = rows[rows["basis"] == basis].groupby("kept")[value].mean()
        ax.plot(series.index, series.to_numpy(), color=color, marker=marker, markersize=3, label=name)
    ax.set_xscale("log", base=2)
    ax.set_xlabel("coordinates kept a residue")


def figure_basis(root: Path) -> Figure:
    table = pd.read_parquet(root / "sparsify" / "sparsify.parquet")
    report = json.loads((root / "write_sums" / "report.json").read_text(encoding="utf-8"))
    figure = new_figure(2.3)
    axes = figure.subplots(1, 4, gridspec_kw={"wspace": 0.55, "left": 0.07, "right": 0.99, "bottom": 0.2, "top": 0.9})
    whole = table[(table["scope"] == "all") & (table["kept"] > 0)]
    intact = table[table["basis"] == "intact"].iloc[0]
    removed = table[(table["scope"] == "all") & (table["basis"] == "removed")].iloc[0]
    _curves(axes[0], whole, "loss")
    axes[0].axhline(intact["loss"], color=MUTED, linewidth=0.6, linestyle=":")
    axes[0].axhline(removed["loss"], color=MUTED, linewidth=0.6, linestyle="--")
    axes[0].set_ylabel("masked-token loss (nats)")
    axes[0].legend(loc="lower left", handlelength=1.4)
    _curves(axes[1], whole, "kl")
    axes[1].set_yscale("log")
    axes[1].set_ylabel("KL from the intact model (nats)")
    single = table[table["scope"].str.startswith("block")]
    floor = float(single.loc[single["basis"] == "removed", "kl"].iloc[0])
    kept = single[single["kept"] > 0].assign(share=lambda rows: 1 - rows["kl"] / floor)
    _curves(axes[2], kept, "share")
    axes[2].set_ylabel(f"share of block {single['scope'].iloc[0].removeprefix('block')}'s effect kept")
    axes[2].set_ylim(top=1.02)
    name = next(key for key, entry in report["dictionaries"].items() if entry["reads"] == "write")
    entry = report["dictionaries"][name]
    bottoms = np.zeros(3)
    for part, color in (("copy", NATIVE), ("coalition", SAE), ("unmatched", RANDOM)):
        heights = np.array([entry[basis][part] for basis in ("native", "rotated", "random")])
        axes[3].bar(range(3), heights, bottom=bottoms, color=color, width=0.7,
                    label={"copy": "one neuron", "coalition": f"2 to {entry['cap']}", "unmatched": "none"}[part])
        bottoms += heights
    axes[3].set_xticks(range(3), ["neurons", "rotation", "random\ndirections"])
    axes[3].set_ylabel("share of directions rebuilt")
    axes[3].set_ylim(0, 1.5)  # headroom above the bars for the legend
    axes[3].set_yticks((0, 0.5, 1.0))
    axes[3].legend(loc="upper left", handlelength=1.0, borderaxespad=0.1)
    for ax, text in zip(axes, "ABCD", strict=True):
        letter(ax, text)
    return figure


def _coverage_panel(ax: Axes, readings: dict[str, object], activation: dict[str, object] | None) -> None:
    """The rule's tests as solid lines, each run with more candidate communities a prompt as dashed lines, and the
    dictionary by activation as dotted lines."""
    runs = [(readings["tests"], "-", f"{readings['tests']['candidates']} candidates"),
            *((readings[key], "--", f"{readings[key]['candidates']} candidates") for key in sorted(readings) if key.startswith("tests_"))]
    if activation is not None and "tests" in activation:
        runs.append((activation["tests"], ":", "by activation"))
    sizes = sorted(runs[0][0]["coverage_by_span"], key=int)
    for run, style, _ in runs:
        for name, color in (("discovered", NATIVE), ("shuffled", ROTATION)):
            ax.plot(range(len(sizes)), [100 * run["coverage_by_span"][size][name] for size in sizes], color=color, linestyle=style,
                    marker="o", markersize=3)
    ax.set_xticks(range(len(sizes)), [f"≥{size}" for size in sizes])
    ax.set_xlabel("blocks in the span")
    ax.set_ylabel("prompts explained (%)")
    ax.set_xlim(-0.3, len(sizes) - 0.7)
    ax.set_ylim(bottom=-0.02 * ax.get_ylim()[1], top=1.45 * ax.get_ylim()[1])  # headroom for the legend of line styles
    ax.legend(handles=[Line2D([], [], color=INK, linestyle=style, label=name) for _, style, name in runs], loc="upper right",
              handlelength=1.8, borderaxespad=0.1)


def _tests_panel(ax: Axes, results: pd.DataFrame) -> None:
    """Every tested community on a span whose blocks are necessary: the KL divergence with the community removed,
    discovered communities against shuffled ones, with the necessity threshold."""
    bins = np.logspace(-4, 1.2, 40)
    passed = results[results["necessity"].notna()]
    for name, color, kind in (("shuffled", ROTATION, "stepfilled"), ("discovered", NATIVE, "step")):
        values = passed.loc[passed["dictionary"] == name, "necessity"].clip(lower=bins[0], upper=bins[-1])  # (rows,)
        ax.hist(values, bins=bins, weights=np.full(len(values), 100 / max(len(values), 1)), color=color, histtype=kind, label=name)
    ax.axvline(THRESHOLDS[0], color=MUTED, linewidth=0.6, linestyle="--")
    ax.set_xscale("log")
    ax.set_xlabel("KL, community removed")
    ax.set_ylabel("tested spans (%)")
    handles, names = ax.get_legend_handles_labels()
    # Above every bar but the spike at the floor; its white ground interrupts the threshold line behind it.
    ax.legend(handles[::-1], names[::-1], loc="upper right", handlelength=1.0, borderaxespad=0.1, frameon=True, facecolor="white",
              edgecolor="none", framealpha=1.0)


def _alone_panel(ax: Axes, alone: pd.DataFrame) -> None:
    """Each of the most used communities at its rank: the median KL divergence with all its units removed, and with
    each unit removed alone."""
    order = alone.groupby("community")["median_together"].first().sort_values(ascending=False)
    rank = pd.Series(np.arange(1, len(order) + 1), index=order.index)
    ax.scatter(alone["community"].map(rank), alone["median_alone"].clip(lower=1e-4), s=3, color=NATIVE, alpha=0.35, linewidths=0,
               label="one neuron")
    ax.scatter(rank.to_numpy(), order.to_numpy(), s=9, color=INK, marker="D", linewidths=0, label="community")
    ax.axhline(THRESHOLDS[0], color=MUTED, linewidth=0.6, linestyle="--")
    ax.set_yscale("log")
    ax.set_ylim(7e-5, 8)
    ax.set_xlabel("community, by rank")
    ax.set_ylabel("KL, removed")
    handles, names = ax.get_legend_handles_labels()
    ax.legend(handles[::-1], names[::-1], loc=(0.03, 0.52), handlelength=1.0, handletextpad=0.3)  # between the two clouds


def figure_communities(root: Path, readings: dict[str, object], activation: dict[str, object] | None = None) -> Figure:
    folder = root / "communities"
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    members = pd.read_parquet(folder / "communities.parquet")
    results = pd.read_parquet(folder / "tests" / "results.parquet")
    prompts = pd.read_parquet(folder / "tests" / "prompts.parquet").reset_index(drop=True)
    explained = results[(results["dictionary"] == "discovered") & results["explains"]]
    chosen = prompts.loc[explained["prompt"].unique()]  # the prompts a discovered community explains
    figure = new_figure(3.9)
    axes = figure.subplots(2, 4, gridspec_kw={"wspace": 0.62, "hspace": 0.55, "left": 0.065, "right": 0.995, "bottom": 0.11, "top": 0.94,
                                              "width_ratios": (1, 1, 1, 1.4)})
    _coverage_panel(axes[0, 0], readings, activation)
    _tests_panel(axes[0, 1], results)
    bins = np.linspace(0, 1, 21)
    for rows, color, name, kind in ((prompts, ROTATION, "all", "stepfilled"), (chosen, NATIVE, "explained", "step")):
        axes[0, 2].hist(np.exp(rows["log_prob"]), bins=bins, weights=np.full(len(rows), 100 / max(len(rows), 1)), color=color,
                        histtype=kind, label=name)
    axes[0, 2].set_xlabel("probability of the top residue")
    axes[0, 2].set_ylabel("prompts (%)")
    axes[0, 2].legend(loc="upper center", handlelength=1.0)
    every = prompts["predicted_residue"].value_counts()
    share = (100 * chosen["predicted_residue"].value_counts().reindex(every.index, fill_value=0) / every).sort_values(ascending=False)
    axes[0, 3].bar(range(len(share)), share.to_numpy(), color=NATIVE, width=0.8)
    axes[0, 3].set_xticks(range(len(share)), share.index, fontsize=5)
    axes[0, 3].set_xlabel("top residue")
    axes[0, 3].set_ylabel("prompts explained (%)")
    # One span a prompt: its narrowest explaining span, the one that starts latest among equals.
    narrowest = explained.sort_values(["blocks", "first_block"], ascending=[True, False], kind="stable").drop_duplicates("prompt")
    depth = narrowest["first_block"].value_counts().reindex(range(int(members["block"].max()) + 1), fill_value=0)
    axes[1, 0].bar(depth.index, 100 * depth.to_numpy() / max(len(narrowest), 1), color=NATIVE, width=0.85)
    axes[1, 0].set_xlabel("first block of the span")
    axes[1, 0].set_ylabel("explained prompts (%)")
    spans = members.groupby("community")["block"].nunique()
    edges = np.arange(0.5, spans.max() + 1.5)
    axes[1, 1].hist(spans, bins=edges, color=ROTATION, label="all")
    axes[1, 1].hist(spans.reindex(explained["community"].unique()), bins=edges, color=NATIVE, label="explaining")
    axes[1, 1].set_yscale("log")
    axes[1, 1].set_xlabel("blocks a community spans")
    axes[1, 1].set_ylabel("communities")
    axes[1, 1].legend(handlelength=1.0)
    alone_path = folder / "tests" / "leave_one_out.parquet"
    alone = pd.read_parquet(alone_path) if alone_path.exists() else pd.DataFrame()
    if len(alone):
        _alone_panel(axes[1, 2], alone)
    quadrants = report["quadrants"]
    cells, attributed = np.array(quadrants["all_cells"], dtype=float), np.array(quadrants["attributed_cells"], dtype=float)  # (n, 4)
    blocks = np.arange(len(cells))
    axes[1, 3].plot(blocks, 100 * cells[:, 2:].sum(axis=1) / cells.sum(axis=1), color=ROTATION, label="all")
    axes[1, 3].plot(blocks, 100 * attributed[:, 2:].sum(axis=1) / attributed.sum(axis=1), color=NATIVE, label="attributed")
    axes[1, 3].set_xlabel("block")
    axes[1, 3].set_ylabel("gate closed (%)")
    axes[1, 3].legend(loc=(0.55, 0.2), handlelength=1.0)
    for ax, text in zip(axes.flat, "ABCDEFGH", strict=True):
        letter(ax, text)
    return figure


def figure_groups(root: Path) -> Figure:
    table = pd.read_parquet(root / "concept_groups" / "concept_groups.parquet")
    tested = table[table["status"] == "tested"].copy()
    tested["placebo"] = [float(np.mean(drops)) for drops in tested["placebo_drops"]]
    tested["kind"] = tested["concept"].str.split("_").str[0]
    figure = new_figure(2.6)
    axes = figure.subplots(1, 3, gridspec_kw={"wspace": 0.45, "left": 0.08, "right": 0.99, "bottom": 0.24, "top": 0.9,
                                              "width_ratios": (1, 1, 1.25)})
    floor = 1e-4
    axes[0].scatter(tested["placebo"].clip(lower=floor), tested["drop"].clip(lower=floor), s=6, color=NATIVE, alpha=0.6, linewidths=0)
    limits = [floor, max(tested["drop"].max(), 1.0) * 1.5]
    axes[0].plot(limits, limits, color=MUTED, linewidth=0.6, linestyle="--")
    axes[0].set_xscale("log")
    axes[0].set_yscale("log")
    axes[0].set_xlabel("fall, placebo groups (nats)")
    axes[0].set_ylabel("fall, the concept's group (nats)")
    axes[1].scatter(tested["single_drop"].clip(lower=floor), tested["drop"].clip(lower=floor), s=6, color=NATIVE, alpha=0.6, linewidths=0)
    axes[1].plot(limits, limits, color=MUTED, linewidth=0.6, linestyle="--")
    axes[1].set_xscale("log")
    axes[1].set_yscale("log")
    axes[1].set_xlabel("fall, the best single pole (nats)")
    axes[1].set_ylabel("fall, the concept's group (nats)")
    kinds =[kind for kind in KIND_ORDER if (tested["kind"] == kind).sum() >= 3]
    for offset, (column, color, name) in enumerate((("drop", NATIVE, "group"), ("single_drop", SAE, "best pole"),
                                                    ("placebo", ROTATION, "placebo"))):
        medians = [float(tested.loc[tested["kind"] == kind, column].median()) for kind in kinds]
        axes[2].bar(np.arange(len(kinds)) + (offset - 1) * 0.27, np.clip(medians, floor, None), width=0.25, color=color, label=name)
    axes[2].set_yscale("log")
    axes[2].set_ylim(floor / 1.5, 40)  # headroom above the tallest bar for the legend
    axes[2].set_xticks(range(len(kinds)), kinds, rotation=30, ha="right", rotation_mode="anchor")
    axes[2].set_ylabel("median fall (nats)")
    axes[2].legend(loc="upper right", handlelength=1.0, ncols=3, columnspacing=0.7, handletextpad=0.4, borderaxespad=0.1)
    for ax, text in zip(axes, "ABC", strict=True):
        letter(ax, text)
    return figure


def figure_erasure(root: Path) -> Figure:
    table = pd.read_parquet(root / "erasure_levels" / "erasure_levels.parquet")
    erased = sorted(table["erased_block"].unique())
    figure = new_figure(2.4)
    axes = figure.subplots(1, len(erased), sharey=True, squeeze=False,
                           gridspec_kw={"wspace": 0.1, "left": 0.08, "right": 0.99, "bottom": 0.2, "top": 0.9})[0]
    for ax, block, text in zip(axes, erased, "ABCDEF", strict=False):  # one letter for each erased block
        rows = table[table["erased_block"] == block]
        for reader, (name, color, style) in READER_STYLES.items():
            series = rows[rows["reader"] == reader].groupby("read_block")["balanced_accuracy"].mean()
            ax.plot(series.index, series.to_numpy(), color=color, linestyle=style, marker="o", markersize=3, label=name)
        intact = rows[rows["reader"] == "linear"].groupby("read_block")["intact_balanced_accuracy"].mean()
        ax.plot(intact.index, intact.to_numpy(), color=ROTATION, linestyle=":", label="intact, linear")
        ax.axvline(block, color=MUTED, linewidth=0.6, linestyle="--")
        ax.set_xlabel("block read")
        letter(ax, text)
    axes[0].set_ylabel("balanced accuracy")
    axes[len(axes) // 2].legend(loc="lower right", handlelength=1.6)  # the middle panel's lower right holds no line
    return figure


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    options = parser.parse_args()
    readings_path = options.root / "e15" / "readings.json"
    readings = json.loads(readings_path.read_text(encoding="utf-8")) if readings_path.exists() else {}
    figures: dict[str, tuple[tuple[str, ...], Callable[[], Figure]]] = {
        "e15_basis": (("sparsify/sparsify.parquet", "write_sums/report.json"), lambda: figure_basis(options.root)),
        "e15_communities": (("communities/tests/results.parquet", "e15/readings.json"),
                            lambda: figure_communities(options.root, readings["E15c"], readings.get("E15c_activation"))),
        "e15_groups": (("concept_groups/concept_groups.parquet",), lambda: figure_groups(options.root)),
        "e15_erasure": (("erasure_levels/erasure_levels.parquet",), lambda: figure_erasure(options.root)),
    }
    with matplotlib.rc_context(STYLE):
        for name, (needs, draw) in figures.items():
            if all((options.root / path).exists() for path in needs):
                print(save_figure(draw(), options.out / f"{name}.png"))


if __name__ == "__main__":
    main()
