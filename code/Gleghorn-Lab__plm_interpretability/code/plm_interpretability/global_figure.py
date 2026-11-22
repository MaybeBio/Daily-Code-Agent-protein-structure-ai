"""Fig. 2 of the interpretability paper: where along ESMC concepts become readable, how model size moves it, where the
model starts to depend on them, and what a nonlinear readout adds, all on one relative depth axis (0 the token
embedding, 1 the final layer norm).

    python -m plm_interpretability.global_figure --survey SURVEY --pooling POOLING --out fig2_global.png [--pdf fig2_global.pdf] [--erasure strips]

`SURVEY` is the survey archive (`GleghornLab/esmc_tap_probing_results`): its `analyses/final2/<model>/summary.parquet`
are the probe summaries Protify wrote when the survey's figures were drawn, which `reproduce.verify` checks the
rebuilt ones against. `POOLING` is the pooling study's archive (`GleghornLab/esmc_tap_probing_pooling_results`): its
`runs/tables` (`pooling_study.gains_table`), `runs/<condition>_s<seed>` (`probe_gap.state_scores`) and `causal`
(`causal_figures.erasure_tables`).

- A: the emergence maps of `cross_model.emergence_maps`, one column per model across the full width: each of the 22
  tasks' residual stream along depth as a share of its highest score, each task's onset (the first depth within 5% of
  its highest score) as a white bar, and each kind's median onset as a gold line.
- B: in ESMC-600, one row per erased concept, earliest readable first, on one loss scale: a blue band from the onset of
  the concept's linear readability to depth 1, and at each erased depth a bar of the masked-residue loss that LEACE
  erasure of the concept costs beyond the random-direction control, with its 95% interval as a whisker. With
  `--erasure strips`, one heat strip per concept instead, a cell per erased depth shaded by that cost.
- C: the mean over the 13 protein tasks of each probe's score at its chosen state (mean and variance pooling).
- D: InterPro membership along ESMC-600's stream under the linear probe, the MLP without its activation and the MLP
  (the pooled mean, the decomposition's design), as `probe_gap.probe_gap_figure` draws it in its panel D.
"""

from __future__ import annotations

import argparse
import numpy as np
import pandas as pd

from pathlib import Path
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from src.protify.interpretability import figures, trends
from src.protify.interpretability.figures import BLUE_RAMP, GRID, INK, INK_SECONDARY, MUTED, SHORT_LABELS
from src.protify.interpretability.trends import CATEGORIES, CATEGORY_OF, SHARE_FLOOR

from plm_interpretability import archive, causal_figures, figure_style, pooling_study, probe_gap
from plm_interpretability.cross_model import ONSET_ORDER, kind_onsets
from plm_interpretability.figure_style import GOLD, PROBE_COLORS


WIDTH, HEIGHT = 7.09, 7.25  # inches: 180 mm, the journal's full width, by 184 mm
RASTER_DPI = 600  # the PDF's heatmap cells, rasterized inside an otherwise vector page
REGION_GAP = 0.3  # inches of white between A's keys and the letters of B, C and D
LETTER_HEIGHT = 0.13  # inches: a 9 pt panel letter
LETTER_DROP, KEY_DROP = 0.1, 0.12  # inches from the letters' baseline to their keys' centers, and from those to the axes
MODELS = ("ESMC-300", "ESMC-600", "ESMC-6B")
SUMMARIES = {"ESMC-300": "main", "ESMC-600": "esmc600", "ESMC-6B": "esmc6b"}  # each model's folder of `analyses/final2`
CONDITIONS = {"ESMC-300": "esmc300_norm", "ESMC-600": "esmc600_norm", "ESMC-6B": "esmc6b_norm"}  # the pooling study's
# C's probes on mean and variance pooling, by their quantity in the gains table
READOUTS = (("score_linear", "linear, AdamW", PROBE_COLORS["linear"]), ("score_linear_solver", "linear, converged", PROBE_COLORS["converged"]),
            ("score_mlp", "MLP", PROBE_COLORS["MLP"]))
# D's probes on the pooled mean, by their results label
DEPTH_READOUTS = (("linear_mean", "linear, AdamW", PROBE_COLORS["linear"]), ("bottleneck_mean", "MLP without activation", PROBE_COLORS["no activation"]),
                  ("mlp_mean", "MLP", PROBE_COLORS["MLP"]))
FOCUS = "ESMC-600"  # the one model of B and D
INTERPRO = "InterPro membership"

# A: the emergence maps' marks, as `cross_model.emergence_maps` draws them, at a row height that prints the task names
# at 6 pt.
ROW_INCHES = 0.165
EMERGENCE_RAMP = ("#ffffff", *BLUE_RAMP)  # white at a share of one half or less, as in the survey's emergence maps
ONSET_BAR, ONSET_EDGE = 1.0, 1.5  # widths in points of a task's white onset bar and its dark edge
MEDIAN_LINE, MEDIAN_EDGE = 1.4, 2.2  # widths in points of a kind's gold median-onset line and its dark edge

# B: the erased concepts, earliest readable first, each drawn only at the depths that were erased. Readability is A's
# blue; the cost of erasing is a dark neutral that no model or probe of the paper takes. The first erased block is not
# drawn: random directions cost more there than erasing three of the four concepts.
ERASED = ("prot_param", "interpro_family", "localization", "ssp_q3")
ERASED_NAMES = dict(causal_figures.CONCEPTS)
UNDRAWN_BLOCK = 1  # the first of ESMC-600's erased blocks (1, 9, 16, 21, 25, 30, 33, 36)
READABLE = BLUE_RAMP[4]  # a concept linearly readable from its onset on
COST = INK_SECONDARY  # the loss its erasure costs beyond the control
ERASURE_FORMS = ("bars", "strips")  # B as one row of bars per concept, or as one heat strip per concept
B_LEFT, B_RIGHT = 0.5, 2.45  # inches: B's plotting area, between its y label and C's
C_LEFT, C_RIGHT = 3.28, 4.58  # inches: C's plotting area
D_LEFT, D_RIGHT = 5.27, 6.97  # inches: D's plotting area
LETTER_INSET = 0.5  # inches from a panel's plotting area to its letter, past the y label
ROW_GAP = 0.07  # inches between two concepts' rows of bars
BAR_WIDTH = 0.036  # relative depth: about half the closest pair of erased depths (0.81, 0.89)
COST_TICKS = (0.0, 0.1)
BAND_ROOM = 0.034  # nats under zero in each row, which holds its readable band
BAND_SPAN = (-0.026, -0.011)  # nats: the band's bottom and top
STRIP_CELL = 0.066  # relative depth: the width of one erased depth's cell
COST_RAMP = ("#ffffff", "#d9d8d4", "#a3a29d", INK_SECONDARY, INK)  # white at no cost, darkest at the highest
LABEL_SIZE = 5.5


# -- tables -----------------------------------------------------------------------------------------------------------


def stream_summaries(survey: Path) -> dict[str, pd.DataFrame]:
    """Each model's concept probes as Protify summarized them, with blocks, depth and relative depth."""
    summaries = {}
    for model, folder in SUMMARIES.items():
        summary = pd.read_parquet(survey / "analyses" / "final2" / folder / "summary.parquet")
        summary = summary[~summary["task"].isin(trends.PAIR_TASKS)]
        summaries[model] = trends._with_relative_depth(summary, archive.BLOCKS[model]).assign(model=model)
    return summaries


def task_rows(summaries: dict[str, pd.DataFrame]) -> list[str]:
    """A's rows: every task with a stream, grouped by kind in `ONSET_ORDER`, as `cross_model.emergence_maps` orders them."""
    present = set().union(*(set(trends._stream(summary)["task"]) for summary in summaries.values()))
    members = dict(CATEGORIES)
    rows = [task for kind in ONSET_ORDER for task in members[kind] if task in present]
    assert present <= set(rows), f"The onset order leaves out {sorted(present - set(rows))}."
    assert len(rows) == 22, f"A has {len(rows)} tasks, not 22."
    return rows


def readout_gains(tables: Path) -> pd.DataFrame:
    """`pooling_study`'s gains of the three trained models on unit-norm states. The training-set sizes it puts beside
    each task are not read here, so they are NaN."""
    sizes = dict.fromkeys(pooling_study.KIND_OF, np.nan)
    rows = []
    for condition in CONDITIONS.values():
        found = pooling_study.quantities(pooling_study.label_draws(pooling_study.read_condition(tables / condition)))
        rows += pooling_study.condition_rows(condition, found, sizes)
    return pd.DataFrame(rows)


def interpro_profiles(roots: Path, condition: str = CONDITIONS[FOCUS]) -> pd.DataFrame:
    """InterPro membership along the stream of `condition` under each of D's probes, as `probe_gap.probe_gap_figure`
    draws its panel D: each task's score as a share of its highest stream score, averaged over the seven tasks."""
    table = None
    for label, _, _ in DEPTH_READOUTS:
        scores = probe_gap.state_scores(roots, condition, label)[["task", "site", "layer", "relative_depth", "score"]].rename(columns={"score": label})
        table = scores if table is None else table.merge(scores.drop(columns="relative_depth"), on=["task", "site", "layer"])
    stream = table[table["site"].isin(probe_gap.STREAM) & (table["task"].map(pooling_study.KIND_OF) == INTERPRO)]
    assert stream["task"].nunique() == 7, f"InterPro membership has {stream['task'].nunique()} tasks along the stream, not 7."
    profiles = {label: (stream[label] / stream.groupby("task")[label].transform("max")).groupby(stream["relative_depth"]).mean()
                for label, _, _ in DEPTH_READOUTS}
    return pd.DataFrame(profiles).rename_axis("relative_depth").reset_index()


def erasure_costs(causal: Path, model: str = FOCUS) -> pd.DataFrame:
    """The masked-residue loss (nats per masked residue) that LEACE erasure costs beyond random directions of the same
    rank, per concept and erased depth of `model`, with intervals: the quantity the text quotes."""
    mlm, _ = causal_figures.erasure_tables(causal)
    costs = mlm[(mlm["model"] == model) & (mlm["condition"] == "leace_minus_random") & (mlm["metric"] == "nll")]
    assert set(costs["concept"]) == {ERASED_NAMES[task] for task in ERASED}, f"Erased concepts of {model}: {sorted(set(costs['concept']))}."
    return costs


# -- A ----------------------------------------------------------------------------------------------------------------


def emergence_map(axis: Axes, summary: pd.DataFrame, profiles: pd.DataFrame, rows: list[str]) -> None:
    """One model's column of A, drawn as `cross_model.emergence_maps` draws it without the best-depth dots: each task's
    stream as a share of its highest score, its onset as a white bar, and each kind's median onset as a gold line
    across the kind's rows."""
    from matplotlib.patheffects import withStroke

    stream = trends._stream(summary)
    blocks = int(summary["blocks"].iloc[0])
    edges = (np.arange(blocks + 3) - 0.5) / (blocks + 1)  # (blocks + 3,): one cell per depth 0..blocks + 1
    matrix = np.full((len(rows), blocks + 2), np.nan)  # (tasks, depths)
    for row, task in enumerate(rows):
        line = stream[stream["task"] == task]
        peak = line["full"].max()
        assert np.isfinite(peak) and peak > 0, f"{task}: no stream score above zero."
        matrix[row, line["depth"].to_numpy()] = np.clip(line["full"].to_numpy() / peak, 0.0, 1.0)
    axis.pcolormesh(edges, np.arange(len(rows) + 1) - 0.5, matrix, cmap=figures._colormap(EMERGENCE_RAMP, "emergence"), vmin=SHARE_FLOOR, vmax=1.0,
                    shading="flat", rasterized=True)
    medians = kind_onsets(profiles)
    for kind in ONSET_ORDER:  # under the tasks' own bars, so a kind of one task shows both
        span = [row for row, task in enumerate(rows) if CATEGORY_OF[task] == kind]
        axis.plot([medians[kind]] * 2, [span[0] - 0.5, span[-1] + 0.5], color=GOLD, lw=MEDIAN_LINE, solid_capstyle="butt",
                  path_effects=[withStroke(linewidth=MEDIAN_EDGE, foreground=INK)], zorder=1.9)
    onsets = profiles.set_index("task")["onset_depth"]
    for row, task in enumerate(rows):
        axis.plot([onsets[task]] * 2, [row - 0.42, row + 0.42], color="white", lw=ONSET_BAR, solid_capstyle="butt",
                  path_effects=[withStroke(linewidth=ONSET_EDGE, foreground=INK)], zorder=2)
    for row in range(1, len(rows)):
        if CATEGORY_OF[rows[row]] != CATEGORY_OF[rows[row - 1]]:
            axis.axhline(row - 0.5, color="white", lw=1.8, zorder=2.5)
    axis.set_ylim(len(rows) - 0.5, -0.5)
    axis.set_xlim(edges[0], edges[-1])
    axis.set_xticks([0.0, 0.5, 1.0])
    axis.tick_params(axis="y", length=0)
    figures._bare(axis)


# -- B, C, D ----------------------------------------------------------------------------------------------------------


def drawn_costs(costs: pd.DataFrame, task: str) -> pd.DataFrame:
    """One concept's erasure costs at the depths B draws: every erased depth but the first, by depth."""
    frame = costs[costs["concept"] == ERASED_NAMES[task]].sort_values("depth")
    assert frame["depth"].iloc[0] == UNDRAWN_BLOCK, f"{task}: erased blocks {frame['depth'].tolist()}."
    return frame[frame["depth"] != UNDRAWN_BLOCK]  # the caption says the first block is left out


def readable_band(axis: Axes, onset: float, low: float, high: float) -> None:
    """A concept's onset of linear readability: a band in `READABLE` from its onset to depth 1 between `low` and
    `high`, opened by A's white onset bar."""
    from matplotlib.patches import Rectangle
    from matplotlib.patheffects import withStroke

    axis.add_patch(Rectangle((onset, low), 1.0 - onset, high - low, facecolor=READABLE, lw=0, zorder=2))
    reach = 0.5 * (high - low)
    axis.plot([onset] * 2, [low - reach, high + reach], color="white", lw=ONSET_BAR, solid_capstyle="butt",
              path_effects=[withStroke(linewidth=ONSET_EDGE, foreground=INK)], zorder=4)


def erasure_bars(axes: list[Axes], costs: pd.DataFrame, onsets: pd.Series) -> None:
    """B as one row per concept on one loss scale: at each erased depth a bar of the loss its erasure costs beyond the
    control, its 95% interval as a whisker, and under the row's zero its readable band, the concept named in the row's
    empty top left."""
    top = float(costs.loc[costs["depth"] != UNDRAWN_BLOCK, "high"].max()) * 1.04
    for index, (axis, task) in enumerate(zip(axes, ERASED, strict=True)):
        frame = drawn_costs(costs, task)
        assert (frame["low"] > -BAND_ROOM / 4).all(), f"{task}: an interval reaches the readable band."
        depths = frame["relative_depth"].to_numpy()  # (erased depths,)
        axis.bar(depths, frame["estimate"].to_numpy(), width=BAR_WIDTH, color=COST, lw=0, zorder=3)
        axis.vlines(depths, frame["low"].to_numpy(), frame["high"].to_numpy(), color=INK, lw=0.6, zorder=3.5)
        axis.axhline(0, color=MUTED, lw=0.4, zorder=1)
        readable_band(axis, float(onsets[task]), *BAND_SPAN)
        axis.text(0.01, top, ERASED_NAMES[task], fontsize=LABEL_SIZE + 0.5, color=INK, ha="left", va="top")
        axis.set_xlim(0, 1)
        axis.set_ylim(-BAND_ROOM, top)
        axis.set_yticks(COST_TICKS)
        axis.set_yticklabels([f"{tick:g}" for tick in COST_TICKS])
        axis.spines["left"].set_bounds(0, top)
        axis.tick_params(axis="y", labelsize=LABEL_SIZE, length=2, pad=1.5)
        axis.grid(axis="y", color=GRID, lw=0.5)
        axis.set_axisbelow(True)
        last = index == len(axes) - 1
        axis.spines["bottom"].set_visible(last)
        axis.tick_params(axis="x", bottom=last, labelbottom=last)
    axes[-1].spines["bottom"].set_bounds(0, 1)
    axes[-1].spines["bottom"].set_position(("data", -BAND_ROOM))
    axes[-1].set_xticks([0.0, 0.5, 1.0])
    axes[-1].set_xticklabels(["0", "0.5", "1"])
    axes[-1].set_xlabel(f"erased depth ({FOCUS})")


def erasure_strips(axis: Axes, costs: pd.DataFrame, onsets: pd.Series, color_key: Axes) -> None:
    """B as one heat strip per concept: a cell at each erased depth, darker as its erasure costs more beyond the
    control, and under the strip its readable band; the concepts named on the left."""
    from matplotlib.colors import Normalize
    from matplotlib.patches import Rectangle

    colormap = figures._colormap(COST_RAMP, "erasure_cost")
    top = float(costs.loc[costs["depth"] != UNDRAWN_BLOCK, "estimate"].max())
    scale = Normalize(0.0, top)
    for row, task in enumerate(ERASED):
        frame = drawn_costs(costs, task)
        for depth, estimate in zip(frame["relative_depth"], frame["estimate"], strict=True):
            axis.add_patch(Rectangle((depth - STRIP_CELL / 2, row - 0.36), STRIP_CELL, 0.5, facecolor=colormap(scale(max(estimate, 0.0))),
                                     edgecolor=MUTED, lw=0.3, zorder=2))
        readable_band(axis, float(onsets[task]), row + 0.2, row + 0.34)
    axis.set_xlim(0, 1)
    axis.set_ylim(len(ERASED) - 0.5, -0.5)
    axis.set_yticks(range(len(ERASED)))
    axis.set_yticklabels([ERASED_NAMES[task] for task in ERASED])
    axis.tick_params(axis="y", length=0, labelsize=LABEL_SIZE + 0.5)
    axis.spines["left"].set_visible(False)
    axis.spines["bottom"].set_bounds(0, 1)
    axis.set_xticks([0.0, 0.5, 1.0])
    axis.set_xticklabels(["0", "0.5", "1"])
    axis.set_xlabel(f"erased depth ({FOCUS})")
    shades = np.linspace(0.0, top, 256)  # (256,)
    color_key.imshow(shades[None, :], aspect="auto", cmap=colormap, vmin=0.0, vmax=top, extent=(0.0, top, 1, 0))
    color_key.set_xlim(0.0, top)
    color_key.set_yticks([])
    color_key.set_xticks([0.0, 0.05, 0.1, 0.15])
    color_key.set_xticklabels(["0", "0.05", "0.1", "0.15"])
    color_key.tick_params(axis="x", labelsize=LABEL_SIZE, length=1.5, pad=1)
    color_key.text(-0.04, 0.5, "excess loss (nats)", transform=color_key.transAxes, ha="right", va="center", fontsize=LABEL_SIZE, color=INK)
    for spine in color_key.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.4)
        spine.set_color(INK_SECONDARY)


def readout_scale(axis: Axes, gains: pd.DataFrame) -> None:
    """C: each probe's mean score over the 13 protein tasks at its chosen state in the three models, with 95%
    intervals over draws of the test proteins."""
    for quantity, name, color in READOUTS:
        estimates = []
        for x, model in enumerate(MODELS):
            row = pooling_study.rows_of(gains, CONDITIONS[model], "any", quantity)
            row = row[row["task"] == "mean"]
            assert len(row) == 1, f"{model}: {len(row)} rows of the mean {quantity}."
            estimate, low, high = row[["estimate", "low", "high"]].iloc[0]
            axis.errorbar(x, estimate, yerr=[[estimate - low], [high - estimate]], fmt="o", ms=3.0, color=color, lw=0.9, zorder=3)
            estimates.append(estimate)
        axis.plot(range(len(MODELS)), estimates, color=color, lw=0.9, zorder=2, label=name)
    axis.set_xticks(range(len(MODELS)))
    axis.set_xticklabels(MODELS)
    axis.set_xlim(-0.3, len(MODELS) - 0.7)
    axis.set_ylabel("mean best score")
    axis.grid(axis="y", color=GRID, lw=0.5)
    axis.set_axisbelow(True)


def readout_depth(axis: Axes, profiles: pd.DataFrame) -> None:
    """D: InterPro membership along ESMC-600's stream under each of D's probes."""
    for label, name, color in DEPTH_READOUTS:
        axis.plot(profiles["relative_depth"], profiles[label], color=color, lw=1.1, label=name)
    axis.set_xlim(0, 1)
    axis.set_ylim(0.45, 1.02)
    axis.set_xticks([0.0, 0.5, 1.0])
    axis.set_xticklabels(["0", "0.5", "1"])
    axis.set_xlabel(f"relative depth ({FOCUS})")
    axis.set_ylabel("share of best")
    axis.grid(color=GRID, lw=0.5)
    axis.set_axisbelow(True)


# -- the figure -------------------------------------------------------------------------------------------------------


def panel_letter(figure: Figure, letter: str, x: float, y: float) -> None:
    """A panel letter with its bottom left corner at (`x`, `y`) inches."""
    figure.text(x / WIDTH, y / HEIGHT, letter, fontsize=9, fontweight="bold", va="bottom", ha="left", color=INK)


def save_pdf(figure: Figure, path: Path) -> Path:
    """The figure as a vector PDF at `path`, cropped as the PNG is: text, lines and marks stay vector with their fonts
    embedded as TrueType, and the rasterized heatmap cells are drawn at `RASTER_DPI`. Call after the PNG is saved, which
    gives the figure its final names and look."""
    from matplotlib import rc_context

    path.parent.mkdir(parents=True, exist_ok=True)
    with rc_context({"pdf.fonttype": 42}):
        figure.savefig(path, dpi=RASTER_DPI, bbox_inches="tight", facecolor="white")
    return path


def global_figure(survey: Path, pooling: Path, path: Path, erasure: str = "bars", pdf: Path | None = None) -> Path:
    """Draw the four panels from the two archives, B in the form `erasure` of `ERASURE_FORMS`, and save the figure at
    `path` and, given `pdf`, as a vector PDF there too."""
    assert erasure in ERASURE_FORMS, f"B is drawn as one of {ERASURE_FORMS}, not {erasure!r}."
    plt = figures._pyplot()
    summaries = stream_summaries(survey)
    profiles = trends.stream_profiles(pd.concat(list(summaries.values()), ignore_index=True))
    rows = task_rows(summaries)
    gains = readout_gains(pooling / "runs" / "tables")
    depth = interpro_profiles(pooling / "runs")
    costs = erasure_costs(pooling / "causal")

    figure: Figure = plt.figure(figsize=(WIDTH, HEIGHT))

    def box(left: float, bottom: float, width: float, height: float) -> tuple[float, float, float, float]:
        """A rectangle given in inches, as figure fractions."""
        return left / WIDTH, bottom / HEIGHT, width / WIDTH, height / HEIGHT

    # A: three columns of maps between the task names and the kinds' names.
    map_left, map_right, map_gap, map_top = 0.98, 0.98, 0.1, HEIGHT - 0.2
    map_height = ROW_INCHES * len(rows)
    map_width = (WIDTH - map_left - map_right - 2 * map_gap) / len(MODELS)
    map_bottom = map_top - map_height
    maps = [figure.add_axes(box(map_left + index * (map_width + map_gap), map_bottom, map_width, map_height)) for index in range(len(MODELS))]
    for index, (axis, model) in enumerate(zip(maps, MODELS, strict=True)):
        emergence_map(axis, summaries[model], profiles[profiles["model"] == model], rows)
        axis.set_xticklabels(["0", "0.5", "1" if index == len(MODELS) - 1 else ""])  # beside the next map's 0
        axis.set_yticks([])
        figures._tag(axis, model)
    maps[0].set_yticks(range(len(rows)))
    maps[0].set_yticklabels([SHORT_LABELS.get(task, task) for task in rows])
    for kind in ONSET_ORDER:
        span = [row for row, task in enumerate(rows) if CATEGORY_OF[task] == kind]
        figure_style.kind_tag(maps[-1], (span[0] + span[-1]) / 2, kind, maps[-1].get_yaxis_transform())
    maps[1].set_xlabel("relative depth", labelpad=2)
    key_y = map_bottom - 0.4
    share_key(figure.add_axes(box(map_left + 0.42, key_y, map_width - 0.5, 0.055)))
    mark_key(figure, ((map_left + 2 * (map_width + map_gap) + 0.05) / WIDTH, (key_y + 0.03) / HEIGHT))

    # B, C, D in one row under A, after a band of white: each panel's letter first, then under the letters B's key over
    # B and the probes' key over C and D, then the panels.
    letter_y = key_y - 0.12 - REGION_GAP - LETTER_HEIGHT  # 0.12 in: the colorbar's tick labels under it
    legend_y = letter_y - LETTER_DROP
    low, high = 0.42, legend_y - KEY_DROP
    onsets = profiles[profiles["model"] == FOCUS].set_index("task")["onset_depth"]
    assert list(ERASED) == sorted(ERASED, key=onsets.get), f"B's concepts are not in their order of onset: {onsets[list(ERASED)].to_dict()}."
    if erasure == "bars":
        row = (high - low - (len(ERASED) - 1) * ROW_GAP) / len(ERASED)
        erased = [figure.add_axes(box(B_LEFT, high - (index + 1) * row - index * ROW_GAP, B_RIGHT - B_LEFT, row)) for index in range(len(ERASED))]
        erasure_bars(erased, costs, onsets)
        figure.text(0.08 / WIDTH, (low + high) / 2 / HEIGHT, "excess loss (nats)", rotation=90, ha="left", va="center",
                    fontsize=plt.rcParams["axes.labelsize"], color=INK)
        erasure_key(figure, ((B_LEFT + B_RIGHT) / 2 / WIDTH, legend_y / HEIGHT), bars=True)
    else:
        strip_left = B_LEFT + 0.42  # room for the concepts' names
        erased = [figure.add_axes(box(strip_left, low, B_RIGHT - strip_left, high - low))]
        color_key = figure.add_axes(box(B_LEFT + 1.15, legend_y - 0.0275, B_RIGHT - B_LEFT - 1.2, 0.055))  # centered on the key's row
        erasure_strips(erased[0], costs, onsets, color_key)
        erasure_key(figure, (B_LEFT / WIDTH, legend_y / HEIGHT), bars=False)
    scale = figure.add_axes(box(C_LEFT, low, C_RIGHT - C_LEFT, high - low))
    along = figure.add_axes(box(D_LEFT, low, D_RIGHT - D_LEFT, high - low))
    readout_scale(scale, gains)
    readout_depth(along, depth)
    readout_key(figure, ((C_LEFT - LETTER_INSET + D_RIGHT) / 2 / WIDTH, legend_y / HEIGHT))

    panel_letter(figure, "A", 0.04, map_top + 0.15)
    for letter, x in zip("BCD", (0.04, C_LEFT - LETTER_INSET, D_LEFT - LETTER_INSET), strict=True):
        panel_letter(figure, letter, x, letter_y)
    plt.rcParams["savefig.pad_inches"] = 0.02  # the tight box keeps the figure at its 180 mm
    figures._save(figure, path)
    if pdf is not None:
        save_pdf(figure, pdf)
    return path


def share_key(axis: Axes) -> None:
    """A's colorbar: the share of a task's highest stream score, white at one half or less."""
    shares = np.linspace(SHARE_FLOOR, 1.0, 256)  # (256,)
    axis.imshow(shares[None, :], aspect="auto", cmap=figures._colormap(EMERGENCE_RAMP, "emergence_key"), vmin=SHARE_FLOOR, vmax=1.0,
                extent=(SHARE_FLOOR, 1.0, 1, 0))
    axis.set_xlim(SHARE_FLOOR, 1.0)
    axis.set_yticks([])
    axis.set_xticks([0.5, 0.75, 1.0])
    axis.set_xticklabels(["≤0.5", "0.75", "1"])
    axis.tick_params(axis="x", labelsize=LABEL_SIZE, length=1.5, pad=1)
    axis.text(-0.04, 0.5, "share of best", transform=axis.transAxes, ha="right", va="center", fontsize=LABEL_SIZE, color=INK)
    for spine in axis.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.4)
        spine.set_color(INK_SECONDARY)


def mark_key(figure: Figure, anchor: tuple[float, float]) -> None:
    """A's marks: a task's onset and a kind's median onset."""
    from matplotlib.lines import Line2D
    from matplotlib.patheffects import withStroke

    keys = [Line2D([], [], ls="none", marker="|", ms=7.5, mew=ONSET_BAR, color="white", path_effects=[withStroke(linewidth=ONSET_EDGE, foreground=INK)]),
            Line2D([], [], ls="none", marker="|", ms=7, mew=MEDIAN_LINE, color=GOLD, path_effects=[withStroke(linewidth=MEDIAN_EDGE, foreground=INK)])]
    figure.legend(keys, ["onset", "median onset of the kind"], loc="center left", bbox_to_anchor=anchor, ncol=2, frameon=False, fontsize=LABEL_SIZE,
                  handletextpad=0.2, columnspacing=1.0)


def erasure_key(figure: Figure, anchor: tuple[float, float], bars: bool) -> None:
    """B's marks in one row over B: the readable band and, when B draws bars, the cost of erasing."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    keys = [Line2D([], [], color=READABLE, lw=2.4, solid_capstyle="butt")]
    names = ["readable"]
    if bars:
        keys.append(Patch(facecolor=COST, lw=0))
        names.append("cost of erasing")
    figure.legend(keys, names, loc="center", bbox_to_anchor=anchor, ncol=len(keys), frameon=False, fontsize=LABEL_SIZE, handlelength=1.5,
                  handleheight=0.6, handletextpad=0.3, columnspacing=1.0)


def readout_key(figure: Figure, anchor: tuple[float, float]) -> None:
    """C's and D's probes, in one row over both panels."""
    from matplotlib.lines import Line2D

    shown = (*READOUTS[:2], DEPTH_READOUTS[1], READOUTS[2])
    figure.legend([Line2D([], [], color=color, lw=1.1) for _, _, color in shown], [name for _, name, _ in shown], loc="center", bbox_to_anchor=anchor,
                  ncol=len(shown), frameon=False, fontsize=LABEL_SIZE, handlelength=1.5, handletextpad=0.3, columnspacing=0.9)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--survey", type=Path, required=True, help="the survey archive, downloaded")
    parser.add_argument("--pooling", type=Path, required=True, help="the pooling study's archive, downloaded")
    parser.add_argument("--out", type=Path, required=True, help="the PNG to write")
    parser.add_argument("--pdf", type=Path, default=None, help="also the figure as a vector PDF, its heatmap cells rasterized")
    parser.add_argument("--erasure", choices=ERASURE_FORMS, default="bars", help="B as one row of bars per concept, or as one heat strip per concept")
    args = parser.parse_args()
    figure_style.install()
    print(global_figure(args.survey, args.pooling, args.out, args.erasure, args.pdf))
    if args.pdf is not None:
        print(args.pdf)


if __name__ == "__main__":
    main()
