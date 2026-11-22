"""Fig. 3 of the interpretability paper: which kind of state inside a block reads which kind of concept.

    python -m plm_interpretability.state_figure --survey SURVEY --pooling POOLING --out fig3_states.png [--pdf fig3_states.pdf]

`SURVEY` is the survey's archive (`GleghornLab/esmc_tap_probing_results`) and `POOLING` the pooling and MLP study's
(`GleghornLab/esmc_tap_probing_pooling_results`), as downloaded; neither is changed. The survey's compacted tables are
read in place, ESMC-6B's residue probes inside its blocks and each root's structure-stream probes joined to their own
root as `archive.merge_sites` joins them, and each model's rebuilt summary is checked against the one Protify wrote
before anything is drawn.

- A: each site's best probe over blocks minus the task's best residual-stream probe, as the median over a kind's tasks
  (`cross_model.kind_gaps`), with the kinds in rows, one row per model, and the sites in columns ordered by the text's
  groups (`MAP_GROUPS`), each group named over its columns and each column's family in its tick label's hue and a bar.
- B: each task's best state of all against its best stream state, for every model, with the tasks that lead most named
  with their chosen state.
- C, D: ESMC-6B's binding sites (C) and active sites (D) along its blocks, read by linear probes of the stream and of
  attention's queries or keys, and by MLP probes of the stream, with the gap between the two linear probes shaded and
  the state inside a block chosen on validation (`cross_model.intra_block_gaps`) marked.

Hues here: the models' own (`MODEL_COLORS`); the block's families as the overview schematic draws them
(`FAMILY_COLORS`); the stream read by a linear probe in slate and by an MLP probe in crimson (`PROBE_COLORS`).
"""

from __future__ import annotations

import argparse
import matplotlib.patches as patches
import numpy as np
import pandas as pd

from collections.abc import Sequence
from pathlib import Path
from matplotlib.axes import Axes
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.image import AxesImage
from matplotlib.lines import Line2D
from src.protify.interpretability import figures, trends
from src.protify.interpretability.figures import DIVERGING, INK, MUTED, SHORT_LABELS, TASK_LABELS
from src.protify.interpretability.trends import CATEGORIES

from plm_interpretability import archive, cross_model, figure_style
from plm_interpretability.figure_style import FAMILY_COLORS, KIND_TAGS, MODEL_COLORS, PROBE_COLORS, site_math
from plm_interpretability.global_figure import save_pdf


# The survey's roots joined to the root whose probes they complete: ESMC-6B's residue probes inside its blocks and every
# root's structure-stream probes.
JOINED_ROOTS = archive.SITE_ROOTS
REFERENCES = {"ESMC-300": "main", "ESMC-600": "esmc600", "ESMC-6B": "esmc6b"}  # Protify's summaries under analyses/final2
MLP_ROOTS = archive.POOLING_ROOTS["ESMC-6B"]
# Each site's family: the stream between the branches, at the final norm and as ESMFold2's structure stream (a learned
# mixture of the stream's states), then attention's and the feed-forward branch's states. The stream after each block
# (`resid_post`) rounds to zero in every cell and has no column.
FAMILY_SITES = (("stream", ("resid_mid", "final_norm", "structural")),
                ("attention", ("attn_ln", "q", "k", "v", "q_rot", "k_rot", "attn_context", "attn_out")),
                ("feed-forward", ("mlp_ln", "mlp_gate", "mlp_up", "mlp_act", "mlp_out")))
FAMILY_OF = {site: family for family, sites in FAMILY_SITES for site in sites}
# A's columns in the text's groups, each under its header: states one normalization or one linear map from the stream;
# states one step further into a branch; the rotated queries and keys and the SwiGLU product; and last the stream's two
# outputs, the final norm and the structure stream, which lose composition and residue sites by far more than any group.
MAP_GROUPS = (("one map from stream", ("resid_mid", "attn_ln", "q", "k", "v", "mlp_ln")),
              ("further into a branch", ("attn_context", "attn_out", "mlp_gate", "mlp_up", "mlp_out")),
              ("rotated or gated", ("q_rot", "k_rot", "mlp_act")),
              ("stream outputs", ("final_norm", "structural")))
MAP_SITES = tuple(site for _, sites in MAP_GROUPS for site in sites)
GROUP_GAP = 0.35  # columns of white between A's groups
MAP_LIMIT = 0.1
# C and D: ESMC-6B's tasks, the y range, and the lines as (line, color, dash, width, direct label). The MLP probe's
# crimson lies near attention's rose, so its line is dashed.
DEPTH_TASKS = ("interpro_binding_site", "interpro_active_site")
PROJECTIONS = ("q", "k")
DEPTH_RANGE = (0.3, 1.06)
DEPTH_LINES = (("stream, MLP", PROBE_COLORS["MLP"], (0, (3.2, 1.4)), 1.2, "stream, MLP probe"),
               ("attention, linear", FAMILY_COLORS["attention"], "-", 1.4, f"{site_math('q')} or {site_math('k')},\nlinear probe"),
               ("stream, linear", PROBE_COLORS["linear"], "-", 1.4, "stream, linear probe"))
# C's direct labels, one per line of `DEPTH_LINES`, as (block, score, horizontal, vertical alignment): where the lines lie
# apart, the MLP probe's over its line, attention's inside the shaded gap, the stream's under its line. D keeps C's style
# and has no labels.
DEPTH_LABELS = ((79, 0.995, "right", "bottom"), (15, 0.735, "left", "top"), (79, 0.375, "right", "top"))
GAP_FILL = 0.22  # opacity of the shaded gap where attention's linear probe leads the stream's
LABELED_LEADS = 0.1  # B names each task whose best state of all leads its best stream state by this much
FIGURE_SIZE = (6.93, 5.64)  # inches; saved with a 0.1 in margin around what is drawn, at most 180 mm wide
PAGE_WIDTH = 7.09  # 180 mm, in inches
# The panels' rectangles in inches as (left, bottom, width, height), A's bottoms as drops from the figure's top: A hangs
# from the top, and B, C and D sit a band of white under A's labels, each a gap from the next past its y label.
A_STRIP = (1.04, 0.527, 5.856, 0.25)  # A's group header
A_MAP = (1.04, 2.303, 5.856, 1.748)  # A's map
A_COLORBAR = (0.208, 2.636, 0.624, 0.067)  # A's colorbar under its kinds
LEAD_BOX = (0.45, 0.416, 1.75, 1.83)  # B, square at the bottom of its box, its x axis level with C's and D's
BINDING_BOX = (2.98, 0.416, 1.58, 1.83)  # C
ACTIVE_BOX = (5.29, 0.416, 1.58, 1.83)  # D
LETTER_INSET = 0.55  # inches from C's and D's plotting areas to their letters, past the y label
LETTER_RISE = 0.167  # inches from the top of B, C and D's boxes to their letters
TICK_SIZE = 6.0
CELL_SIZE = 5.5


# -- inputs -------------------------------------------------------------------------------------------------------


def survey_scores(runs: Path, roots: Sequence[str], label: str = "linear") -> tuple[pd.DataFrame, pd.DataFrame]:
    """A model's compacted scores and probe records, read in the archive's layout (`runs/<root>/<label>/<task>/`), one
    replicate per root; each root of `JOINED_ROOTS` that completes one of `roots` joins that root's replicate."""
    scores, validation = [], []
    for index, root in enumerate(roots):
        members = [root, *(source for source, target in JOINED_ROOTS.items() if target == root)]
        for member in members:
            assert (runs / member / label).is_dir(), f"The survey's archive has no {member}/{label}."
            scores.append(figures.read_table(runs / member, label, "scores", folder="").assign(replicate=index))
            validation.append(figures.read_table(runs / member, label, "probes", folder="")[archive.VALIDATION].assign(replicate=index))
    scores, validation = pd.concat(scores, ignore_index=True), pd.concat(validation, ignore_index=True)
    duplicated = validation.duplicated(["task", "family", "probe_name", "replicate"])
    assert not duplicated.any(), f"{int(duplicated.sum())} probes are in a root and in the root that completes it."
    return scores, validation


def survey_summaries(survey: Path) -> dict[str, pd.DataFrame]:
    """Each model's summary of every probe, checked against Protify's own where its probes overlap that summary's."""
    summaries = {}
    for model, roots in archive.MODELS.items():
        scores, validation = survey_scores(survey / "runs", roots)
        summary = archive.summarize(scores, validation)
        reference = pd.read_parquet(survey / "analyses" / "final2" / REFERENCES[model] / "summary.parquet")
        known = set(map(tuple, reference[["task", "family", "probe_name"]].itertuples(index=False)))
        original = summary[[key in known for key in zip(summary["task"], summary["family"], summary["probe_name"], strict=True)]]
        difference = archive.verify(original.reset_index(drop=True), reference)
        print(f"{model}: {len(summary)} probes, {len(summary) - len(original)} joined; the rest match Protify's summary to {difference:.1e}")
        summaries[model] = summary
    return summaries


def mlp_stream(pooling: Path, tasks: Sequence[str] = DEPTH_TASKS) -> pd.DataFrame:
    """ESMC-6B's MLP probes of the stream after each block, over the three seeds of the MLP study: Protify's summary of
    its uncompacted scores (`full`, the mean over seeds, and `std`, over every seed's test halves)."""
    roots = [pooling / "runs" / root for root in MLP_ROOTS]
    paths = [root / "results" / "mlp" / task / name for root in roots for task in tasks for name in ("scores.parquet", "validation.parquet")]
    missing = [path for path in paths if not path.exists()]
    assert not missing, f"The pooling archive lacks {len(missing)} tables, such as {missing[0]}."
    scores = pd.concat([pd.read_parquet(root / "results" / "mlp" / task / "scores.parquet").assign(replicate=index)
                        for index, root in enumerate(roots) for task in tasks], ignore_index=True)
    validation = pd.concat([pd.read_parquet(root / "results" / "mlp" / task / "validation.parquet").assign(replicate=index)
                            for index, root in enumerate(roots) for task in tasks], ignore_index=True)
    summary = figures.headline(figures.summarize(scores, validation))
    stream = summary[(summary["family"] == "full") & (summary["site"] == "resid_post")]
    assert (stream["replicates"] == len(roots)).all(), "An MLP probe of the stream lacks a seed."
    return stream.sort_values(["task", "layer"]).reset_index(drop=True)


def figure_tables(summaries: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """The tables the panels read: A's kind gaps (`kinds`, sites by kinds per model), B's best states (`best`) and its
    named tasks (`leads`), and the state inside a block chosen for each of ESMC-6B's tasks in C and D (`chosen`)."""
    concepts = {model: summary[~summary["task"].isin(trends.PAIR_TASKS)] for model, summary in summaries.items()}
    kinds = pd.concat([cross_model.kind_gaps(summary).assign(model=model) for model, summary in concepts.items()])
    best = cross_model.best_table(concepts, archive.BLOCKS)
    best = best.assign(lead=best["any_score"] - best["residual_score"])
    leads = best[best["lead"] >= LABELED_LEADS]
    leads = leads.loc[leads.groupby("task")["any_score"].idxmax()]  # each task's largest-model lead, named beside its own dot
    leads = leads[["model", "task", "any_site", "any_layer", "any_score", "residual_score", "lead"]].sort_values("lead", ascending=False)
    summary = summaries["ESMC-6B"]
    chosen = cross_model.intra_block_gaps(summary[summary["task"].isin(DEPTH_TASKS)], archive.BLOCKS["ESMC-6B"])
    assert sorted(chosen["task"]) == sorted(DEPTH_TASKS), f"ESMC-6B lacks a state inside a block for {DEPTH_TASKS}."
    return {"kinds": kinds, "best": best, "leads": leads.reset_index(drop=True), "chosen": chosen}


def depth_lines(summary: pd.DataFrame, mlp: pd.DataFrame) -> pd.DataFrame:
    """C's and D's lines: per task, line of `DEPTH_LINES` (`line`) and block, the test score of the block's probe, the
    site it reads (`site`) and its spread over test halves. The attention line takes, at each block, whichever of the
    queries and keys scores higher on validation."""
    trained = figures.headline(summary)
    linear = trained[(trained["family"] == "full") & trained["task"].isin(DEPTH_TASKS)]
    projections = figures._choose(linear[linear["site"].isin(PROJECTIONS)], ["task", "layer"])
    frames = [linear[linear["site"] == "resid_post"].assign(line="stream, linear"), projections.assign(line="attention, linear"),
              mlp[mlp["task"].isin(DEPTH_TASKS)].assign(line="stream, MLP")]
    lines = pd.concat(frames, ignore_index=True)[["task", "line", "site", "layer", "full", "std"]]
    lines = lines.astype({"layer": int, "full": float, "std": float}).sort_values(["task", "line", "layer"]).reset_index(drop=True)
    for task in DEPTH_TASKS:
        for line, *_ in DEPTH_LINES:
            part = lines[(lines["task"] == task) & (lines["line"] == line)]
            assert part["layer"].tolist() == list(range(archive.BLOCKS["ESMC-6B"])), f"{task}: the {line} line lacks blocks."
    return lines


# -- panels -------------------------------------------------------------------------------------------------------


def column_positions() -> np.ndarray:
    """A's column centers in data units: one unit per site, `GROUP_GAP` more between groups."""
    positions, start = [], 0.0
    for _, sites in MAP_GROUPS:
        positions.extend(start + np.arange(len(sites)))
        start += len(sites) + GROUP_GAP
    return np.array(positions, dtype=float)  # (sites,)


def kind_map(axis: Axes, kinds: pd.DataFrame) -> AxesImage:
    """A: kinds of concept in rows, one row per model, by sites in columns grouped as `MAP_GROUPS`, each site's tick label
    in its family's hue; returns the first group's image."""
    assert set(MAP_SITES) == set(FAMILY_OF), "A's groups and families name different sites."
    names = [kind for kind, _ in CATEGORIES if kind in kinds.columns]
    rows = [(kind, model) for kind in names for model in MODEL_COLORS]
    stale = kinds.loc["resid_post"].drop(columns="model").to_numpy(dtype=float)  # (models, kinds)
    assert np.all(np.abs(stale) < 0.005), "The stream after each block no longer rounds to zero; it needs its column back."
    matrix = np.array([[kinds[kinds["model"] == model].at[site, kind] for site in MAP_SITES] for kind, model in rows])  # (kinds * models, sites)
    assert np.all(np.isfinite(matrix)), "A site lacks every task of a kind; the map needs a not-probed key."
    positions = column_positions()  # (sites,)
    colormap = figures._colormap(DIVERGING, "state_kinds")
    images, start = [], 0
    for _, sites in MAP_GROUPS:
        stop = start + len(sites)
        extent = (positions[start] - 0.5, positions[stop - 1] + 0.5, len(rows) - 0.5, -0.5)
        images.append(axis.imshow(matrix[:, start:stop], cmap=colormap, vmin=-MAP_LIMIT, vmax=MAP_LIMIT, aspect="auto", extent=extent,
                                  interpolation="nearest"))
        start = stop
    for row, column in zip(*np.nonzero(np.round(np.abs(matrix), 2) > 0), strict=True):
        value = matrix[row, column]
        axis.text(positions[column], row, cross_model._cell(value), ha="center", va="center", fontsize=CELL_SIZE,
                  color="white" if abs(value) > 0.65 * MAP_LIMIT else INK)
    models = len(MODEL_COLORS)
    boundaries = np.arange(models, len(rows), models) - 0.5  # (kinds - 1,)
    # past the map's edges, so no sliver of a cell shows beyond a separator
    axis.hlines(boundaries, positions[0] - 0.55, positions[-1] + 0.55, color="white", lw=2.2, clip_on=False)
    # each row's model as a small square in its hue, between the kind's name and the map
    for row, (_, model) in enumerate(rows):
        axis.add_patch(patches.Rectangle((-0.5 - 0.3, row - 0.36), 0.2, 0.72, facecolor=MODEL_COLORS[model], lw=0, clip_on=False))
    axis.set_xlim(positions[0] - 0.5, positions[-1] + 0.5)
    axis.set_ylim(len(rows) - 0.5, -0.5)
    axis.set_yticks([index * models + (models - 1) / 2 for index in range(len(names))])
    axis.set_yticklabels([KIND_TAGS.get(kind, kind) for kind in names], fontsize=TICK_SIZE, linespacing=0.95, color=INK)
    axis.tick_params(axis="y", length=0, pad=11)
    axis.set_xticks(positions)
    axis.set_xticklabels([site_math(site) for site in MAP_SITES], rotation=90, fontsize=TICK_SIZE)
    for label, site in zip(axis.get_xticklabels(), MAP_SITES, strict=True):
        label.set_color(FAMILY_COLORS[FAMILY_OF[site]])
    axis.tick_params(axis="x", length=0, pad=2)
    figures._bare(axis)
    return images[0]


def group_strip(axis: Axes) -> None:
    """A's column header: each group's words over its columns, and a bar over each column in its family's hue."""
    positions = column_positions()  # (sites,)
    axis.set_xlim(positions[0] - 0.5, positions[-1] + 0.5)
    axis.set_ylim(0, 1)
    axis.axis("off")
    start = 0
    for words, sites in MAP_GROUPS:
        stop = start + len(sites)
        axis.text((positions[start] + positions[stop - 1]) / 2, 0.42, words, ha="center", va="bottom", fontsize=TICK_SIZE, color=INK)
        start = stop
    for position, site in zip(positions, MAP_SITES, strict=True):
        axis.add_patch(patches.Rectangle((position - 0.47, 0.0), 0.94, 0.22, facecolor=FAMILY_COLORS[FAMILY_OF[site]], lw=0))


def lead_panel(axis: Axes, best: pd.DataFrame, leads: pd.DataFrame) -> None:
    """B: every task's best state of all against its best stream state, each chosen on validation, for every model,
    with each task of `leads` named beside its dot with its chosen state."""
    axis.plot([0, 1], [0, 1], color=MUTED, lw=0.7, zorder=1)
    for model, color in MODEL_COLORS.items():
        part = best[best["model"] == model]
        axis.scatter(part["residual_score"], part["any_score"], s=9, color=color, edgecolors="white", linewidths=0.3, zorder=3, label=model)
    for task, site, layer, x, y in zip(leads["task"], leads["any_site"], leads["any_layer"], leads["residual_score"], leads["any_score"], strict=True):
        left = x > 0.3
        axis.text(x - 0.035 if left else x + 0.035, y, f"{TASK_LABELS[task]}\n{site_math(site)} {int(layer)}", ha="right" if left else "left",
                  va="center", fontsize=CELL_SIZE, color=INK, linespacing=0.95)
    axis.set_xlim(0.0, 1.0)
    axis.set_ylim(0.0, 1.0)
    axis.set_xticks([0.0, 0.5, 1.0])
    axis.set_yticks([0.0, 0.5, 1.0])
    axis.set_aspect("equal", anchor="S")
    axis.set_xlabel("best stream state")
    axis.set_ylabel("best state of all")
    axis.grid(color=figures.GRID, lw=0.5, zorder=0)
    # the models' key in B's empty lower right, under the diagonal no task can fall below
    models = [Line2D([], [], ls="none", marker="o", ms=3.4, mfc=color, mec="white", mew=0.3) for color in MODEL_COLORS.values()]
    axis.legend(models, list(MODEL_COLORS), loc="lower right", frameon=False, fontsize=CELL_SIZE, handletextpad=0.1, labelspacing=0.3,
                borderaxespad=0.2, handlelength=1.0)


def smoothed_lines(lines: pd.DataFrame, task: str) -> pd.DataFrame:
    """C's or D's lines for one task, blocks by line: each line's running mean over `cross_model.RUNNING_MEAN` blocks."""
    scores = lines[lines["task"] == task].pivot(index="layer", columns="line", values="full")  # (n_b, lines)
    return scores.rolling(cross_model.RUNNING_MEAN, center=True, min_periods=1).mean()  # (n_b, lines)


def depth_panel(axis: Axes, lines: pd.DataFrame, chosen: pd.DataFrame, task: str, labeled: bool) -> None:
    """C or D: one task of ESMC-6B along its blocks, every line of `DEPTH_LINES` as its running mean (labeled at the line
    when `labeled`), the gap shaded where attention's linear probe leads the stream's, and the task's chosen state inside
    a block as a dot."""
    smoothed = smoothed_lines(lines, task)  # (n_b, lines)
    blocks = smoothed.index.to_numpy()  # (n_b,)
    attention, stream = smoothed["attention, linear"].to_numpy(), smoothed["stream, linear"].to_numpy()  # (n_b,) each
    gap_color = to_rgba(FAMILY_COLORS["attention"], GAP_FILL)  # in the color, so the saved look leaves the fill alone
    axis.fill_between(blocks, stream, attention, where=attention > stream, interpolate=True, facecolor=gap_color, lw=0, zorder=1)
    for (name, color, dash, width, label), (block, score, horizontal, vertical) in zip(DEPTH_LINES, DEPTH_LABELS, strict=True):
        axis.plot(blocks, smoothed[name].to_numpy(), color=color, ls=dash, lw=width, zorder=2)
        if labeled:
            axis.text(block, score, label, ha=horizontal, va=vertical, fontsize=TICK_SIZE, color=color, linespacing=0.95, zorder=4)
    state = chosen[chosen["task"] == task].iloc[0]
    assert state["inside_site"] in PROJECTIONS, f"The chosen state for {task} is not a query or key: {state['inside_site']}."
    axis.scatter([state["inside_layer"]], [state["inside_score"]], s=20, color=FAMILY_COLORS["attention"], edgecolors="white", linewidths=0.6,
                 zorder=5)
    axis.set_xlim(-1, archive.BLOCKS["ESMC-6B"])
    axis.set_ylim(*DEPTH_RANGE)
    axis.set_yticks([0.4, 0.6, 0.8, 1.0])
    axis.set_xticks([0, 20, 40, 60, 79])
    axis.set_xlabel("ESMC-6B block")
    axis.set_ylabel(f"test MCC, {SHORT_LABELS[task].lower()}")
    axis.grid(axis="y", color=figures.GRID, lw=0.5, zorder=0)


# -- the figure -----------------------------------------------------------------------------------------------------


def _letter(figure: Figure, letter: str, x: float, y: float) -> None:
    """A panel letter at figure coordinates (`x`, `y`), its bottom left corner."""
    figure.text(x, y, letter, fontsize=9, fontweight="bold", ha="left", va="bottom", color=INK)


def keys(figure: Figure) -> None:
    """A's keys, the models' and the families', side by side over its header in the row of its letter."""
    models = [Line2D([], [], ls="none", marker="s", ms=4, color=color) for color in MODEL_COLORS.values()]
    families = [Line2D([], [], color=color, lw=3, solid_capstyle="butt") for color in FAMILY_COLORS.values()]
    style = {"frameon": False, "fontsize": TICK_SIZE, "handletextpad": 0.3, "columnspacing": 0.9, "borderaxespad": 0.0}
    figure.legend(models, list(MODEL_COLORS), loc="upper right", bbox_to_anchor=(0.995, 1.0), ncol=3, **style)
    figure.legend(families, list(FAMILY_COLORS), loc="upper right", bbox_to_anchor=(0.66, 1.0), ncol=3, handlelength=1.2, **style)


def draw(tables: dict[str, pd.DataFrame], lines: pd.DataFrame, path: Path, pdf: Path | None = None) -> Path:
    """The four panels on one page, 180 mm wide: A across the top, then B, C and D in one row; saved at `path` and,
    given `pdf`, as a vector PDF there too."""
    plt = figures._pyplot()
    inches_wide, inches_high = FIGURE_SIZE
    figure = plt.figure(figsize=FIGURE_SIZE)

    def box(left: float, bottom: float, box_width: float, box_height: float) -> tuple[float, float, float, float]:
        """A rectangle given in inches, as figure fractions."""
        return left / inches_wide, bottom / inches_high, box_width / inches_wide, box_height / inches_high

    def hung(left: float, drop: float, box_width: float, box_height: float) -> tuple[float, float, float, float]:
        """A rectangle whose bottom is `drop` inches under the figure's top, as figure fractions."""
        return box(left, inches_high - drop, box_width, box_height)

    strip = figure.add_axes(hung(*A_STRIP))
    kind_axis = figure.add_axes(hung(*A_MAP))
    bar_axis = figure.add_axes(hung(*A_COLORBAR))  # under A's kinds, beside its site names
    lead_axis = figure.add_axes(box(*LEAD_BOX))
    binding_axis = figure.add_axes(box(*BINDING_BOX))
    active_axis = figure.add_axes(box(*ACTIVE_BOX))

    group_strip(strip)
    image = kind_map(kind_axis, tables["kinds"])
    colorbar = figure.colorbar(image, cax=bar_axis, extend="both", orientation="horizontal")
    colorbar.solids.set_rasterized(True)  # a vector ramp shows seams between its cells
    colorbar.set_ticks([-MAP_LIMIT, 0.0, MAP_LIMIT])
    colorbar.ax.tick_params(labelsize=CELL_SIZE + 0.5, length=2)
    colorbar.set_label("state minus stream", fontsize=TICK_SIZE)  # "site" is kept for biology in the figures
    colorbar.ax.xaxis.set_label_position("top")
    colorbar.outline.set_visible(False)
    keys(figure)
    lead_panel(lead_axis, tables["best"], tables["leads"])
    for axis, task, labeled in ((binding_axis, DEPTH_TASKS[0], True), (active_axis, DEPTH_TASKS[1], False)):
        depth_panel(axis, lines, tables["chosen"], task, labeled)

    _letter(figure, "A", 0.005, 1.0 - 0.15 / inches_high)  # in the row of A's keys
    bottom = (LEAD_BOX[1] + LEAD_BOX[3] + LETTER_RISE) / inches_high
    for letter, left in zip("BCD", (0.035, BINDING_BOX[0] - LETTER_INSET, ACTIVE_BOX[0] - LETTER_INSET), strict=True):
        _letter(figure, letter, left / inches_wide, bottom)
    path = figures._save(figure, path)
    if pdf is not None:
        print(save_pdf(figure, pdf))
    height, width, _ = plt.imread(path).shape  # (pixels, pixels, channels)
    assert width <= PAGE_WIDTH * 300 + 1, f"The figure is saved {width / 300:.2f} in wide, past 180 mm."
    print(f"{path}: {width / 300 * 25.4:.0f} mm by {height / 300 * 25.4:.0f} mm")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--survey", type=Path, required=True, help="the survey's archive, downloaded")
    parser.add_argument("--pooling", type=Path, required=True, help="the pooling and MLP study's archive, downloaded")
    parser.add_argument("--out", type=Path, required=True, help="the figure's PNG")
    parser.add_argument("--pdf", type=Path, default=None, help="also the figure as a vector PDF, its heatmap cells rasterized")
    parser.add_argument("--tables", type=Path, default=None, help="a folder for the numbers each panel draws, as CSV")
    args = parser.parse_args()
    figure_style.install()
    mlp = mlp_stream(args.pooling)  # read with Protify's own summary: the pooling archive is not compacted
    summaries = survey_summaries(args.survey)
    tables = figure_tables(summaries)
    lines = depth_lines(summaries["ESMC-6B"], mlp)
    if args.tables is not None:
        args.tables.mkdir(parents=True, exist_ok=True)
        kinds = tables["kinds"].loc[list(MAP_SITES)]  # A's columns, in A's order
        kinds.to_csv(args.tables / "kinds.csv", float_format="%.4f")
        tables["best"].to_csv(args.tables / "best.csv", index=False, float_format="%.4f")
        tables["leads"].to_csv(args.tables / "leads.csv", index=False, float_format="%.4f")
        tables["chosen"].to_csv(args.tables / "chosen.csv", index=False, float_format="%.4f")
        lines.to_csv(args.tables / "depth_lines.csv", index=False, float_format="%.4f")
        print(args.tables)
    print(draw(tables, lines, args.out, args.pdf))


if __name__ == "__main__":
    main()
