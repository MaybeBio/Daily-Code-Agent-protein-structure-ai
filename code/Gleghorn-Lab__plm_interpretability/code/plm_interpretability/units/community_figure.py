"""The interpretability paper's figure of neuron communities and concept groups, drawn from E15's outputs.

    python -m plm_interpretability.units.community_figure --root RUN --out FIGURE.png

Reads a copy of the run's `communities`, `concept_groups` and `e15` folders (E15c and E15d of the native-unit study,
after Shilov and colleagues' community discovery) and draws one figure for a single-column page:

- A, a schematic of a community: each block's feed-forward neurons as a slab of cells, a community's neurons in red,
  linked across depth.
- B, the share of held-out prompts a shuffled community of the same size in each block explains within a span of at
  least 1, 4 and 12 blocks, beside the share a discovered community explains, from the tests whose rule was fixed in
  advance.
- C, the intact model's probability for its top residue at every prompt and at the prompts explained.
- D, the share of prompts explained by the model's top residue, lowest first.
- E, the first block of each explained prompt's narrowest explaining span.
- F, for the communities that explain the most prompts, the KL divergence with its strongest neuron removed alone
  against that with the whole community removed.
- G, each concept's placebo groups, its best single pole, and its group of labeled poles removed together.

Within a panel the order runs from the control to the result, left to right (Logan, 2026-11-18). The run's tables
call a prediction a prompt, after Shilov and colleagues; the axes say prediction, as the paper does. Hues follow the
study's other figures: red for the model's own neurons (dark for a community or group removed together, light for one
neuron or pole alone) and gray for controls. Every number drawn is recomputed from the tables and checked against the
run's own readings before anything is drawn.

Symbols: p held-out prompts; s tested spans; c communities; g concept groups; z residue types; n blocks.
"""

from __future__ import annotations

import argparse
import json
import numpy as np
import pandas as pd

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .figures import INK, MUTED, NATIVE, ROTATION, STYLE, _grid, letter, new_figure, save_figure


if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure


WIDTH, HEIGHT = 6.3, 5.4  # inches: the single-column text width, with room on the page for the caption
SINGLE = "#f2a3a2"  # one neuron or pole removed alone: the neurons' red, lighter
SPANS = (1, 4, 12)  # the fixed reading's minimum spans, in blocks
BLOCKS = 36  # ESMC-600's blocks
FLOOR = 1e-4  # nats: values at or under it are drawn at it on a log axis
TOLERANCE = 1e-9
LOG_LIMITS = (5e-5, 6.0)  # nats: panels F and G's log axes, from under the floor to above the largest value (3.1)
SCHEMATIC_CELLS = 7  # neurons drawn in each block's slab
# The schematic's community, by slab: the rows of its member cells. Slab 4 is the gap that stands for omitted blocks.
SCHEMATIC_MEMBERS = {0: (), 1: (4,), 2: (1, 5), 3: (3,), 5: (5,), 6: (2, 6), 7: (3,), 8: ()}
SCHEMATIC_GAP = 4


@dataclass(frozen=True)
class CommunityTests:
    """E15c's tests at 2 candidate communities a prompt: every tested span, every held-out prompt, and the
    leave-one-out tests of the most used communities."""

    results: pd.DataFrame  # (s, columns)
    prompts: pd.DataFrame  # (p, columns)
    alone: pd.DataFrame  # (units tested, columns)

    @property
    def explained(self) -> pd.DataFrame:
        """The spans on which a discovered community explains its prompt."""
        return self.results[(self.results["dictionary"] == "discovered") & self.results["explains"]]

    @property
    def explained_prompts(self) -> pd.DataFrame:
        """The prompts some discovered community explains, one row each."""
        return self.prompts.loc[self.explained["prompt"].unique()]


def load_tests(root: Path) -> CommunityTests:
    folder = root / "communities" / "tests"
    prompts = pd.read_parquet(folder / "prompts.parquet").reset_index(drop=True)
    results = pd.read_parquet(folder / "results.parquet")
    assert results["prompt"].between(0, len(prompts) - 1).all(), "A tested span names a prompt outside prompts.parquet."
    return CommunityTests(results, prompts, pd.read_parquet(folder / "leave_one_out.parquet"))


def coverage(tests: CommunityTests) -> pd.DataFrame:
    """The share of held-out prompts explained within a span of at least each of `SPANS` blocks, a row a span and a
    column a dictionary (discovered, shuffled), as a fraction of every prompt tested."""
    explaining = tests.results[tests.results["explains"]]
    shares = {name: [explaining.loc[(explaining["dictionary"] == name) & (explaining["blocks"] >= span), "prompt"].nunique()
                      / len(tests.prompts) for span in SPANS] for name in ("discovered", "shuffled")}
    return pd.DataFrame(shares, index=pd.Index(SPANS, name="span"))  # (spans, 2)


def check_coverage(shares: pd.DataFrame, readings: dict[str, object]) -> None:
    """The recomputed coverage is the one the run's readings report for the tests at 2 candidates."""
    tests = readings["E15c"]["tests"]
    assert tests["candidates"] == 2 and tests["prompts"] == 38_985, f"Unexpected tests in readings: {tests['candidates']}, {tests['prompts']}."
    for span in SPANS:
        for name in shares.columns:
            reported = tests["coverage_by_span"][str(span)][name]
            assert abs(shares.loc[span, name] - reported) < TOLERANCE, f"Span {span}, {name}: {shares.loc[span, name]} against {reported}."


def narrowest_spans(tests: CommunityTests) -> pd.DataFrame:
    """One span a explained prompt: its narrowest explaining span, the one that starts latest among equals."""
    ordered = tests.explained.sort_values(["blocks", "first_block"], ascending=[True, False], kind="stable")
    narrowest = ordered.drop_duplicates("prompt")
    assert narrowest["first_block"].between(0, BLOCKS - 1).all(), "A span starts outside the model's blocks."
    return narrowest


def residue_shares(tests: CommunityTests) -> pd.Series:
    """The percent of prompts explained, by the model's top residue, lowest first."""
    every = tests.prompts["predicted_residue"].value_counts()  # (z,)
    explained = tests.explained_prompts["predicted_residue"].value_counts().reindex(every.index, fill_value=0)  # (z,)
    return (100 * explained / every).sort_values(ascending=True, kind="stable")  # (z,)


def strongest_neurons(alone: pd.DataFrame) -> pd.DataFrame:
    """Each leave-one-out community: the median KL divergence with all its tested neurons removed, and the largest
    median KL divergence of one of them removed alone."""
    per = alone.groupby("community").agg(together=("median_together", "first"), strongest=("median_alone", "max"),
                                         neurons=("unit", "size"))  # (c, 3)
    assert (alone.groupby("community")["median_together"].nunique() == 1).all(), "A community has two removal effects."
    return per.sort_values("together", ascending=False)


def concept_falls(root: Path) -> pd.DataFrame:
    """Each tested concept group's fall in the true residue's log probability, removed together, as its best single
    pole and as the mean of its placebo groups, checked against the stage's own report."""
    folder = root / "concept_groups"
    table = pd.read_parquet(folder / "concept_groups.parquet")
    tested = table[table["status"] == "tested"].copy()
    tested["placebo"] = [float(np.mean(drops)) for drops in tested["placebo_drops"]]
    report = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))["report"]
    assert len(tested) == report["tested"], f"{len(tested)} tested groups against the report's {report['tested']}."
    for column, key in (("drop", "median_drop"), ("single_drop", "median_single_drop"), ("placebo", "median_placebo_drop")):
        assert abs(tested[column].median() - report[key]) < TOLERANCE, f"{column}: {tested[column].median()} against {report[key]}."
    return tested[["concept", "drop", "single_drop", "placebo"]].reset_index(drop=True)  # (g, 4)


def schematic_panel(ax: Axes) -> None:
    """Blocks as slabs of neuron cells along depth, one community's neurons red and linked from block to block."""
    from matplotlib.patches import FancyArrowPatch, Rectangle

    slabs = max(SCHEMATIC_MEMBERS) + 1
    cell, pitch = 0.66, 1.0  # a cell's side and the distance between neighboring cells and slabs
    centers = {}
    for slab in range(slabs):
        if slab == SCHEMATIC_GAP:
            ax.text(slab * pitch, (SCHEMATIC_CELLS - 1) / 2, "···", ha="center", va="center", fontsize=8, color=MUTED)
            continue
        for row in range(SCHEMATIC_CELLS):
            member = row in SCHEMATIC_MEMBERS[slab]
            ax.add_patch(Rectangle((slab * pitch - cell / 2, row - cell / 2), cell, cell, facecolor=NATIVE if member else "white",
                                   edgecolor=NATIVE if member else ROTATION, linewidth=0.6, zorder=3))
            if member:
                centers.setdefault(slab, []).append((slab * pitch, float(row)))
    linked = sorted(centers)
    for left, right in zip(linked, linked[1:], strict=False):
        for start in centers[left]:
            for end in centers[right]:
                ax.plot([start[0], end[0]], [start[1], end[1]], color=NATIVE, linewidth=0.6, alpha=0.55, zorder=2)
    ax.add_patch(FancyArrowPatch((-0.4, -1.1), ((slabs - 1) * pitch + 0.4, -1.1), arrowstyle="-|>", mutation_scale=6,
                                 color=MUTED, linewidth=0.6))
    ax.text((slabs - 1) * pitch / 2, -1.5, "block", ha="center", va="top", color=INK)
    ax.set_xlim(-0.6, (slabs - 1) * pitch + 0.6)
    ax.set_ylim(-2.6, SCHEMATIC_CELLS - 0.4)
    ax.set_aspect("equal")
    ax.axis("off")


def coverage_panel(ax: Axes, shares: pd.DataFrame) -> None:
    """Paired bars a minimum span, the shuffled control gray on the left and discovered communities red on the right,
    each with its percent above. Every panel of this figure runs from the control to the result, left to right."""
    width = 0.42
    for offset, (name, color, label) in enumerate((("shuffled", ROTATION, "shuffled"), ("discovered", NATIVE, "communities"))):
        percents = 100 * shares[name].to_numpy()  # (spans,)
        positions = np.arange(len(SPANS)) + (offset - 0.5) * width  # (spans,)
        ax.bar(positions, percents, width=width * 0.9, color=color, label=label, zorder=2)
        for x, percent in zip(positions, percents, strict=True):
            # A shuffled bar's label sits a little to its left, clear of the taller red bar beside it.
            ax.text(x - 0.1 * (1 - offset), percent + 0.06, _percent_label(percent), ha="center", va="bottom", fontsize=6, color=INK)
    ax.set_xticks(range(len(SPANS)), [f"≥{span}" for span in SPANS])
    ax.tick_params(axis="x", length=0)
    ax.set_xlim(-0.7, len(SPANS) - 0.5)  # room at the left for the first shuffled bar's label
    ax.set_xlabel("blocks in the span")
    ax.set_ylabel("predictions explained (%)")
    ax.set_ylim(0, 3.6)
    ax.legend(loc="upper right", handlelength=1.0, borderaxespad=0.1)
    _grid(ax)


def _percent_label(percent: float) -> str:
    if percent == 0:
        return "0"
    return f"{percent:.2f}" if percent >= 0.1 else f"{percent:.3f}"


def confidence_panel(ax: Axes, tests: CommunityTests) -> None:
    """The intact model's probability for its top residue: every prompt gray, the prompts explained a red outline."""
    bins = np.linspace(0, 1, 21)  # (21,)
    for rows, color, name, kind in ((tests.prompts, ROTATION, "all", "stepfilled"), (tests.explained_prompts, NATIVE, "explained", "step")):
        probabilities = np.exp(rows["log_prob"].to_numpy(dtype=np.float64))  # (p,)
        ax.hist(probabilities, bins=bins, weights=np.full(len(probabilities), 100 / len(probabilities)), color=color, histtype=kind,
                linewidth=1.0, label=name)
    ax.set_xlim(0, 1)
    ax.set_xticks((0, 0.5, 1), ["0", "0.5", "1"])
    ax.set_xlabel("probability of top residue")
    ax.set_ylabel("predictions (%)")
    ax.legend(loc="upper left", handlelength=1.0, borderaxespad=0.1)


def residue_panel(ax: Axes, shares: pd.Series) -> None:
    ax.bar(range(len(shares)), shares.to_numpy(), color=NATIVE, width=0.75, zorder=2)
    ax.set_xticks(range(len(shares)), shares.index)
    ax.tick_params(axis="x", length=0)
    ax.set_xlim(-0.7, len(shares) - 0.3)
    ax.set_xlabel("top residue")
    ax.set_ylabel("predictions explained (%)")
    _grid(ax)


def depth_panel(ax: Axes, narrowest: pd.DataFrame) -> None:
    """Explained prompts by the first block of their narrowest explaining span, in percent of explained prompts."""
    counts = narrowest["first_block"].value_counts().reindex(range(BLOCKS), fill_value=0)  # (n,)
    ax.bar(counts.index, 100 * counts.to_numpy() / len(narrowest), color=NATIVE, width=0.8, zorder=2)
    ax.set_xticks((0, 9, 18, 27, 35))
    ax.set_xlim(-1, BLOCKS)
    ax.set_xlabel("first block of the span")
    ax.set_ylabel("explained predictions (%)")
    _grid(ax)


def _strip(ax: Axes, x: float, values: np.ndarray, color: str, *, spread: float, size: float, seed: int) -> np.ndarray:
    """Values as jittered points about `x` on a log axis, floored at `FLOOR`, with their median as a black tick;
    returns the points' horizontal positions."""
    # values: (points,)
    positions = x + np.random.default_rng(seed).uniform(-spread, spread, len(values))  # (points,)
    ax.scatter(positions, np.clip(values, FLOOR, None), s=size, color=color, linewidths=0, alpha=0.8, zorder=3)
    ax.hlines(max(float(np.median(values)), FLOOR), x - 0.3, x + 0.3, color=INK, linewidth=1.0, zorder=4)
    return positions  # (points,)


def _floored_log_axis(ax: Axes) -> None:
    """A log axis over `LOG_LIMITS` with a tick a decade, the lowest named as the floor the values were drawn at."""
    from matplotlib.ticker import NullLocator

    ax.set_yscale("log")
    ax.set_ylim(*LOG_LIMITS)
    decades = np.arange(round(np.log10(FLOOR)), 1)  # (decades,)
    ax.set_yticks(10.0 ** decades, ["≤$10^{%d}$" % decades[0], *(f"$10^{{{decade}}}$" for decade in decades[1:])])
    ax.yaxis.set_minor_locator(NullLocator())


def alone_panel(ax: Axes, strongest: pd.DataFrame) -> None:
    """Each leave-one-out community's strongest neuron removed alone (light red, left) and the community removed whole
    (dark red, right), joined by a line."""
    together = strongest["together"].to_numpy()  # (c,)
    single = strongest["strongest"].to_numpy()  # (c,)
    left = _strip(ax, 0.0, single, SINGLE, spread=0.08, size=6, seed=1)  # (c,)
    right = _strip(ax, 1.0, together, NATIVE, spread=0.08, size=6, seed=0)  # (c,)
    ax.plot(np.stack([left, right]), np.clip(np.stack([single, together]), FLOOR, None), color=ROTATION, linewidth=0.4, alpha=0.6,
            zorder=2)
    _floored_log_axis(ax)
    ax.set_xticks((0, 1), ["strongest\nneuron", "community"])
    ax.tick_params(axis="x", length=0)
    ax.set_xlim(-0.55, 1.55)
    ax.set_ylabel("KL when removed (nats)")
    _grid(ax)


def groups_panel(ax: Axes, falls: pd.DataFrame) -> None:
    """Each concept's fall as the mean over its placebo groups, with its best single pole removed, and with its group
    removed, from the control to the result."""
    for x, (column, color, seed) in enumerate((("placebo", ROTATION, 4), ("single_drop", SINGLE, 3), ("drop", NATIVE, 2))):
        _strip(ax, float(x), falls[column].to_numpy(dtype=np.float64), color, spread=0.22, size=2.5, seed=seed)
    _floored_log_axis(ax)
    ax.set_xticks((0, 1, 2), ["placebo\ngroups", "best\npole", "concept\ngroup"])
    ax.tick_params(axis="x", length=0)
    ax.set_xlim(-0.6, 2.6)
    ax.set_ylabel("fall in log probability (nats)")
    _grid(ax)


def figure_communities(root: Path) -> Figure:
    import matplotlib

    readings = json.loads((root / "e15" / "readings.json").read_text(encoding="utf-8"))
    tests = load_tests(root)
    shares = coverage(tests)
    check_coverage(shares, readings)
    with matplotlib.rc_context(STYLE):
        figure = new_figure(HEIGHT, WIDTH)
        outer = figure.add_gridspec(3, 1, height_ratios=(1.0, 1.0, 1.1), hspace=0.62, left=0.09, right=0.985, top=0.96, bottom=0.075)
        top = outer[0].subgridspec(1, 3, width_ratios=(0.95, 1.15, 1.0), wspace=0.45)
        middle = outer[1].subgridspec(1, 2, width_ratios=(1.25, 1.0), wspace=0.3)
        bottom = outer[2].subgridspec(1, 2, width_ratios=(1.0, 1.3), wspace=0.42)
        panels = {"A": top[0], "B": top[1], "C": top[2], "D": middle[0], "E": middle[1], "F": bottom[0], "G": bottom[1]}
        axes = {name: figure.add_subplot(spec) for name, spec in panels.items()}
        schematic_panel(axes["A"])
        coverage_panel(axes["B"], shares)
        confidence_panel(axes["C"], tests)
        residue_panel(axes["D"], residue_shares(tests))
        depth_panel(axes["E"], narrowest_spans(tests))
        alone_panel(axes["F"], strongest_neurons(tests.alone))
        groups_panel(axes["G"], concept_falls(root))
        for name, ax in axes.items():
            letter(ax, name)
    return figure


def caption_numbers(root: Path) -> dict[str, object]:
    """Every number the caption needs, read from the tables the figure draws."""
    tests = load_tests(root)
    shares = coverage(tests)
    explained = tests.explained_prompts
    narrowest = narrowest_spans(tests)
    strongest = strongest_neurons(tests.alone)
    falls = concept_falls(root)
    residues = residue_shares(tests)
    return {
        "prompts": len(tests.prompts),
        "coverage_percent": {span: {name: round(100 * float(shares.loc[span, name]), 4) for name in shares.columns} for span in SPANS},
        "explained_prompts": len(explained),
        "explaining_communities": int(tests.explained["community"].nunique()),
        "median_top_probability": {"all": float(np.median(np.exp(tests.prompts["log_prob"]))),
                                   "explained": float(np.median(np.exp(explained["log_prob"])))},
        "top_is_true": {"all": float((tests.prompts["true"] == tests.prompts["predicted"]).mean()),
                        "explained": float((explained["true"] == explained["predicted"]).mean())},
        "residue_percent": residues.round(2).to_dict(),
        "narrowest": {"median_blocks": float(narrowest["blocks"].median()), "median_first_block": float(narrowest["first_block"].median()),
                      "share_from_27": float((narrowest["first_block"] >= 27).mean()),
                      "share_before_9": float((narrowest["first_block"] < 9).mean())},
        "leave_one_out": {"communities": len(strongest), "neurons_min": int(strongest["neurons"].min()),
                          "neurons_max": int(strongest["neurons"].max()), "median_together": float(strongest["together"].median()),
                          "median_strongest": float(strongest["strongest"].median()), "max_strongest": float(strongest["strongest"].max()),
                          "max_ratio": float((strongest["strongest"] / strongest["together"]).max()),
                          "together_range": (float(strongest["together"].min()), float(strongest["together"].max())),
                          "floored": int((strongest["strongest"] <= FLOOR).sum())},
        "concept_groups": {"tested": len(falls), **{column: float(falls[column].median()) for column in ("drop", "single_drop", "placebo")},
                           **{f"{column}_floored": float((falls[column] <= FLOOR).mean()) for column in ("drop", "single_drop", "placebo")}},
    }


def main() -> None:
    import matplotlib

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True, help="a copy of E15's run folders (communities, concept_groups, e15)")
    parser.add_argument("--out", type=Path, required=True, help="the PNG to write")
    arguments = parser.parse_args()
    with matplotlib.rc_context(STYLE):
        print(save_figure(figure_communities(arguments.root), arguments.out))
    print(json.dumps(caption_numbers(arguments.root), indent=1, default=str))


if __name__ == "__main__":
    main()
