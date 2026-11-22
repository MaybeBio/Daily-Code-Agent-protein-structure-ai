"""Figures and tables that put ESMC-300, ESMC-600 and ESMC-6B on one relative depth axis, for the Supplement, and this
package's layouts of the figures Protify draws, which `figure_style.install` swaps in.

Relative depth places the token embedding at 0, the output of block k of n_b at (k + 1)/(n_b + 1) and the final layer
norm at 1. Best states are chosen on validation and reported on test, as Protify's `figures.best_states` does.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from collections.abc import Sequence
from pathlib import Path
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from src.protify.interpretability import figures, trends
from src.protify.interpretability.figures import (ATTENTION, BLOCK_SITES, BLUE_RAMP, GRID, INK, INK_SECONDARY, MLP, MUTED, RESIDUAL, SHORT_LABELS, SITE_LABELS,
                                                  STRUCTURE, STRUCTURE_X, TASK_LABELS, TASK_ORDER)
from src.protify.interpretability.trends import CATEGORIES, CATEGORY_OF, CONCEPT_ORDER, SHARE_FLOOR

from plm_interpretability.figure_style import (CONTROLS, GOLD, KIND_TAGS, LABEL_SET_COLORS, MEAN_ONLY_COLORS, MODEL_COLORS, OTHER_SERIES, PROBE_COLORS, ROW_BAND,
                                      kind_tag, site_tex)


FAMILIES = (("residual", "residual stream"), ("attention", "attention sites"), ("mlp", "feed-forward sites"), ("head", "single head"))
# The emergence maps' kinds of concept, by ESMC-300's median onset (0.00, 0.19, 0.23, 0.42, 0.45, 0.84 on mean and
# variance pooling and on the pooled mean), in every panel, so the first reads as a staircase and the others break it.
ONSET_ORDER = ("composition", "residue sites and modifications", "sorting and topology", "InterPro membership", "function", "secondary structure")
# The states inside a block that the gap table reads: attention and feed-forward sites, the mid-block stream left out.
INSIDE = (*ATTENTION, *MLP)
# The gap table's task names: Protify's concept labels and the main text's pair task.
GAP_LABELS = {**TASK_LABELS, "ppi": "Interaction (2024)"}
# A task enters the gap table when its inside state leads the stream at its own depth and the best stream state by these.
SAME_DEPTH_LEAD = 0.05
BEST_LEAD = 0.02
# The controls summary's legend entries before the trained models, in the order the panel shows them from the left.
CONTROL_LEGEND = ("random vectors", "scrambled", "untrained", "one-hot", "random init")
RUNNING_MEAN = 5  # the points in the running mean that lifts a noisy curve off its raw values
SITE_GROUP_GAP = 1.8  # points of white between groups of sites in a map
SITE_MAP_PRINTED = 0.10  # the per-task site map prints a cell at least this large, so that neighbors do not collide


def relative(summary: pd.DataFrame, blocks: int) -> pd.DataFrame:
    """The summary with each state's depth on the residual-stream axis and its relative depth."""
    depths = np.array([figures.depth(site, layer, blocks) for site, layer in zip(summary["site"], summary["layer"], strict=True)], dtype=int)
    return summary.assign(depth=depths, relative_depth=depths / (blocks + 1))


def _stream(summary: pd.DataFrame) -> pd.DataFrame:
    trained = figures.headline(summary)
    return trained[(trained["family"] == "full") & trained["site"].isin(RESIDUAL)].sort_values("depth")


def structure_scores(summary: pd.DataFrame) -> pd.Series:
    """Each task's structure-stream test score, by task; empty where it was not probed."""
    trained = figures.headline(summary)
    return trained[(trained["family"] == "full") & trained["site"].isin(STRUCTURE)].set_index("task")["full"]


def depth_all(summaries: dict[str, pd.DataFrame], blocks: dict[str, int], random: pd.DataFrame, onehot: pd.DataFrame,
              path: Path, tasks: Sequence[str] = CONCEPT_ORDER) -> Path:
    """One panel per task: the residual-stream probe's test score along relative depth for every model (one standard
    deviation over test halves shaded), the randomly initialized ESMC-300's own probes (dashed) and the one-hot encoding
    (dotted level), and, past the final norm, each model's structure stream (diamonds) where it was probed."""
    plt = figures._pyplot()
    random_style, onehot_style = CONTROLS["random init"], CONTROLS["one-hot"]
    streams = {model: _stream(relative(summary, blocks[model])) for model, summary in summaries.items()}
    structures = {model: structure_scores(summary) for model, summary in summaries.items()}
    random_stream = _stream(relative(random, blocks["ESMC-300"]))
    random_structure = structure_scores(random)
    onehot_level = figures.headline(onehot).query("family == 'full'").groupby("task")["full"].max()
    tasks = [task for task in tasks if any((stream["task"] == task).any() for stream in streams.values())]
    figure, axes = figures._grid(plt, len(tasks) + 1, 6, width=7.2, row_height=1.02, sharex=True)
    for axis, task in zip(axes, tasks, strict=False):  # the grid has one panel more, for the legend
        for model, stream in streams.items():
            curve = stream[stream["task"] == task]
            axis.plot(curve["relative_depth"], curve["full"], color=MODEL_COLORS[model], lw=1.1)
            axis.fill_between(curve["relative_depth"], curve["mean"] - curve["std"], curve["mean"] + curve["std"],
                              color=MODEL_COLORS[model], alpha=0.15, lw=0)
            if task in structures[model].index:
                axis.scatter([STRUCTURE_X], [structures[model][task]], marker="D", s=9, color=MODEL_COLORS[model], zorder=3, lw=0)
        curve = random_stream[random_stream["task"] == task]
        axis.plot(curve["relative_depth"], curve["full"], color=random_style.color, ls=random_style.dash, lw=0.9)
        if task in random_structure.index:
            axis.scatter([STRUCTURE_X], [random_structure[task]], marker="D", s=9, facecolors="white", edgecolors=random_style.color, zorder=3, lw=0.7)
        if task in onehot_level.index:
            axis.axhline(onehot_level[task], color=onehot_style.color, ls=onehot_style.dash, lw=0.9)
        axis.grid(axis="y", color=GRID, lw=0.5)
        axis.set_xticks([0.0, 0.5, 1.0])
        axis.tick_params(labelbottom=True)
        figures._tag(axis, figures.SHORT_LABELS.get(task, task))
    figure.supxlabel("relative depth", fontsize=7, color=INK)
    legend = axes[len(tasks)]
    legend.set_visible(True)
    legend.axis("off")  # never `set_xticks([])`: the panels share this x axis, and it would clear every panel's ticks
    handles = [legend.plot([], [], color=color, lw=1.2)[0] for color in MODEL_COLORS.values()]
    handles += [legend.plot([], [], color=random_style.color, ls=random_style.dash)[0], legend.plot([], [], color=onehot_style.color, ls=onehot_style.dash)[0]]
    labels = list(MODEL_COLORS) + ["random init", "one-hot"]
    if any(not scores.empty for scores in structures.values()):
        handles.append(legend.plot([], [], ls="none", marker="D", ms=3, color=INK)[0])
        labels.append(SITE_LABELS["structural"])
    legend.legend(handles, labels, loc="center", frameon=False, fontsize=6)
    figure.tight_layout(h_pad=0.6, w_pad=0.5)
    return figures._save(figure, path)


def _cell(value: float) -> str:
    """A map cell's printed value: no leading zero, and no plus, since the color and the minus already give the sign and
    three maps across the page leave a cell little room."""
    return f"{value:.2f}".replace("0.", ".", 1)


def site_gaps_all(summaries: dict[str, pd.DataFrame], path: Path, tasks: Sequence[str] = CONCEPT_ORDER) -> Path:
    """One map per model: each site's best probe over blocks minus the task's best residual-stream probe, both chosen
    on validation; differences of at least `SITE_MAP_PRINTED` in size are printed, and states not probed are hatched gray."""
    plt = figures._pyplot()
    gaps = {model: figures.site_gaps(summary, tasks) for model, summary in summaries.items()}
    sites = [site for site in SITE_LABELS if any(site in gap.columns for gap in gaps.values())]
    rows = [task for task in tasks if any(task in gap.index for gap in gaps.values())]
    figure, axes = plt.subplots(1, len(gaps), figsize=(7.2, 0.17 * len(rows) + 1.2), sharey=True)
    colormap = figures._colormap(figures.DIVERGING, "gaps")
    colormap.set_bad("white")
    image, missing = None, False
    for letter, (axis, (model, gap)) in zip("ABC", zip(axes, gaps.items(), strict=True), strict=False):
        matrix = gap.reindex(index=rows, columns=sites).to_numpy(dtype=float)
        image = axis.imshow(np.ma.masked_invalid(matrix), cmap=colormap, vmin=-0.1, vmax=0.1, aspect="auto")
        missing |= _hatch_missing(axis, matrix)
        _set_apart_structure(axis, sites, "columns")
        for row, column in zip(*np.nonzero(np.abs(np.nan_to_num(matrix)) >= SITE_MAP_PRINTED), strict=True):
            axis.text(column, row, _cell(matrix[row, column]), ha="center", va="center", fontsize=4.5, color="white")
        axis.set_xticks(range(len(sites)))
        axis.set_xticklabels([SITE_LABELS[site] for site in sites], rotation=90)
        axis.set_yticks(range(len(rows)))
        axis.set_yticklabels([figures.SHORT_LABELS.get(task, task) for task in rows])
        axis.tick_params(length=0)
        figures._tag(axis, model)
        figures._letter(axis, letter, x=-0.02)
        figures._bare(axis)
    figure.tight_layout(w_pad=0.4, rect=(0, 0.05, 1, 1))
    bar = figure.colorbar(image, cax=figure.add_axes((0.35, 0.012, 0.3, 0.012)), orientation="horizontal", extend="both")
    bar.set_ticks([-0.1, -0.05, 0.0, 0.05, 0.1])
    bar.set_label("site minus residual stream (best state of each)", fontsize=5.5)
    bar.ax.tick_params(labelsize=5)
    if missing:
        _not_probed_key(figure, (0.7, 0.005, 0.2, 0.025))
    return figures._save(figure, path)


def kind_gaps(summary: pd.DataFrame, tasks: Sequence[str] = CONCEPT_ORDER) -> pd.DataFrame:
    """Sites by kinds of concept: the median over a kind's tasks of each site's best probe over blocks minus the task's
    best residual-stream probe, both chosen on validation (`figures.site_gaps`)."""
    gaps = figures.site_gaps(summary, tasks)
    kinds = [kind for kind, members in CATEGORIES if any(task in gaps.index for task in members)]
    return gaps.groupby(gaps.index.map(CATEGORY_OF)).median().reindex(kinds).T


def state_concepts(summaries: dict[str, pd.DataFrame], path: Path, limit: float = 0.1) -> Path:
    """One map per model of which kinds of state read which kinds of concept: `kind_gaps`, printed where the value
    rounds to a nonzero hundredth, hatched gray where no task of the kind was probed at the site. A site blank in every
    cell of every map (the stream after the block, whose best state is the stream's best on most tasks) has no row, and
    thin gaps set apart attention, the mid-block stream, the feed-forward sites and the stream's end."""
    plt = figures._pyplot()
    gaps = {model: kind_gaps(summary) for model, summary in summaries.items()}
    sites = [site for site in SITE_LABELS if any(site in gap.index and (gap.loc[site].abs().round(2) > 0).any() for gap in gaps.values())]
    kinds = [kind for kind, _ in CATEGORIES if any(kind in gap.columns for gap in gaps.values())]
    figure, axes = plt.subplots(1, len(gaps), figsize=(7.2, 0.16 * len(sites) + 1.3), sharey=True)
    colormap = figures._colormap(figures.DIVERGING, "kind_gaps")
    colormap.set_bad("white")
    image, missing = None, False
    for letter, (axis, (model, gap)) in zip("ABC", zip(axes, gaps.items(), strict=True), strict=False):
        matrix = gap.reindex(index=sites, columns=kinds).to_numpy(dtype=float)  # (sites, kinds)
        image = axis.imshow(np.ma.masked_invalid(matrix), cmap=colormap, vmin=-limit, vmax=limit, aspect="auto")
        missing |= _hatch_missing(axis, matrix)
        _set_apart_structure(axis, sites, "rows")
        for index in range(1, len(sites)):
            if _site_group(sites[index]) != _site_group(sites[index - 1]) and sites[index] not in STRUCTURE:
                axis.axhline(index - 0.5, color="white", lw=SITE_GROUP_GAP)
        for row, column in zip(*np.nonzero(np.isfinite(matrix)), strict=True):
            value = matrix[row, column]
            if round(abs(value), 2) == 0:
                continue
            axis.text(column, row, _cell(value), ha="center", va="center", fontsize=5.5,
                      color="white" if abs(value) > 0.7 * limit else INK)
        axis.set_xticks(range(len(kinds)))
        axis.set_xticklabels([KIND_TAGS.get(kind, kind) for kind in kinds], rotation=45, ha="right", rotation_mode="anchor", fontsize=5.5, linespacing=0.95)
        axis.set_yticks(range(len(sites)))
        axis.set_yticklabels([SITE_LABELS[site] for site in sites])
        axis.tick_params(length=0)
        figures._tag(axis, model)
        figures._letter(axis, letter, x=-0.02)
        figures._bare(axis)
    figure.tight_layout(w_pad=0.4, rect=(0, 0.06, 1, 1))
    bar = figure.colorbar(image, cax=figure.add_axes((0.3, 0.015, 0.3, 0.012)), orientation="horizontal", extend="both")
    bar.set_ticks([-limit, -limit / 2, 0.0, limit / 2, limit])
    bar.set_label("site minus residual stream (best state of each)", fontsize=5.5)
    bar.ax.tick_params(labelsize=5)
    if missing:
        _not_probed_key(figure, (0.66, 0.008, 0.2, 0.03))
    return figures._save(figure, path)


def _site_group(site: str) -> str:
    """A site's group in a map's rows: attention, the mid-block stream, the feed-forward sites or the stream's end."""
    return "attention" if site in ATTENTION else "mlp" if site in MLP else "mid" if site == "resid_mid" else "end"


def _set_apart_structure(axis: Axes, sites: list[str], along: str) -> None:
    """A rule before the structure stream's row or column of a site map, which is not a state of ESMC itself."""
    for index, site in enumerate(sites):
        if site in STRUCTURE and index:
            (axis.axhline if along == "rows" else axis.axvline)(index - 0.5, color=INK, lw=0.9)


def _hatch_missing(axis: Axes, matrix: np.ndarray) -> bool:
    """Hatch gray every cell of an `imshow` map whose value is missing, a state not probed; returns whether any was."""
    # matrix: (rows, columns)
    import matplotlib.patches as patches

    cells = list(zip(*np.nonzero(~np.isfinite(matrix)), strict=True))
    for row, column in cells:
        axis.add_patch(patches.Rectangle((column - 0.5, row - 0.5), 1, 1, facecolor=GRID, edgecolor=MUTED, hatch="////", lw=0))
    return bool(cells)


def _not_probed_key(figure: Figure, rect: tuple[float, float, float, float]) -> None:
    """A legend entry for `_hatch_missing`'s cells, in a small axes at `rect` (figure coordinates)."""
    import matplotlib.patches as patches

    key = figure.add_axes(rect)
    key.add_patch(patches.Rectangle((0.0, 0.2), 0.08, 0.6, facecolor=GRID, edgecolor=MUTED, hatch="////", lw=0))
    key.text(0.11, 0.5, "not probed", fontsize=5.5, va="center", ha="left", color=INK)
    key.set_xlim(0, 1)
    key.set_ylim(0, 1)
    key.axis("off")


def best_table(summaries: dict[str, pd.DataFrame], blocks: dict[str, int]) -> pd.DataFrame:
    """Per model and task, `figures.best_states` with each family's relative depth."""
    tables = []
    for model, summary in summaries.items():
        table = figures.best_states(summary, blocks[model])
        for family, _ in FAMILIES:
            if family == "head":
                table["head_depth"] = table["head_layer"] + 1 if "head_layer" in table else np.nan
            if f"{family}_depth" in table:
                table[f"{family}_relative_depth"] = table[f"{family}_depth"] / (blocks[model] + 1)
        tables.append(table.assign(model=model, blocks=blocks[model]))
    return pd.concat(tables, ignore_index=True)


def best_depth_all(best: pd.DataFrame, path: Path, tasks: Sequence[str] = CONCEPT_ORDER) -> Path:
    """One panel per family of states: the relative depth of each task's best state of that family, chosen on
    validation, for every model."""
    plt = figures._pyplot()
    rows = [task for task in tasks if task in set(best["task"])]
    positions = np.arange(len(rows))
    figure, axes = plt.subplots(1, len(FAMILIES), figsize=(7.2, 0.15 * len(rows) + 1.0), sharey=True)
    offsets = dict(zip(MODEL_COLORS, (-0.22, 0.0, 0.22), strict=True))
    for letter, (axis, (family, title)) in zip("ABCD", zip(axes, FAMILIES, strict=True), strict=True):
        for position in positions[::2]:
            axis.axhspan(position - 0.5, position + 0.5, color=ROW_BAND, lw=0, zorder=0)
        for model, color in MODEL_COLORS.items():
            table = best[best["model"] == model].set_index("task").reindex(rows)
            column = f"{family}_relative_depth"
            if column in table:
                axis.scatter(table[column], positions + offsets[model], s=9, color=color, zorder=3, label=model)
        axis.set_xlim(-0.04, 1.04)
        axis.set_xticks([0.0, 0.5, 1.0])
        axis.set_xlabel("relative depth")
        axis.grid(axis="x", color=GRID, lw=0.5)
        figures._tag(axis, title)
        figures._letter(axis, letter, x=-0.03 if letter != "A" else -0.62)
    axes[0].set_yticks(positions)
    axes[0].set_yticklabels([figures.SHORT_LABELS.get(task, task) for task in rows])
    axes[0].set_ylim(len(rows) - 0.5, -0.5)
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 1.0))
    figure.tight_layout(w_pad=0.5, rect=(0, 0, 1, 1 - 0.25 / figure.get_figheight()))
    return figures._save(figure, path)


def structure_table(summaries: dict[str, pd.DataFrame], best: pd.DataFrame) -> pd.DataFrame:
    """Per model and task whose structure stream was probed: its test score (`structure`), and those of the best
    residual-stream state (`residual`), the best state of any of the model's own sites (`any`), each chosen on
    validation, and the final norm (`final_norm`)."""
    rows = []
    for model, summary in summaries.items():
        trained = figures.headline(summary)
        final = trained[(trained["family"] == "full") & (trained["site"] == "final_norm")].set_index("task")["full"]
        table = best[best["model"] == model].set_index("task")
        for task, score in structure_scores(summary).items():
            rows.append({"model": model, "task": task, "category": CATEGORY_OF.get(task, task), "structure": float(score),
                         "residual": float(table.at[task, "residual_score"]), "any": float(table.at[task, "any_score"]),
                         "final_norm": float(final.get(task, np.nan))})
    return pd.DataFrame(rows, columns=["model", "task", "category", "structure", "residual", "any", "final_norm"])


def structure_gaps(table: pd.DataFrame, path: Path, tasks: Sequence[str] = CONCEPT_ORDER) -> Path:
    """Per task, for every model: the structure stream's test score minus that of the best residual-stream state,
    chosen on validation (A), and minus the final norm's (B)."""
    plt = figures._pyplot()
    rows = [task for task in tasks if task in set(table["task"])]
    positions = np.arange(len(rows))
    panels = (("residual", "minus best stream state"), ("final_norm", f"minus {SITE_LABELS['final_norm']}"))
    figure, axes = plt.subplots(1, len(panels), figsize=(7.2, 0.135 * len(rows) + 0.95), sharey=True)
    offsets = dict(zip(MODEL_COLORS, (-0.22, 0.0, 0.22), strict=True))
    for letter, (axis, (column, title)) in zip("AB", zip(axes, panels, strict=True), strict=True):
        category_bands(axis, rows, positions, right=axis is axes[-1])
        axis.axvline(0.0, color=INK_SECONDARY, lw=0.7, zorder=1)
        for model, color in MODEL_COLORS.items():
            part = table[table["model"] == model].set_index("task").reindex(rows)
            if part["structure"].notna().any():
                axis.scatter(part["structure"] - part[column], positions + offsets[model], s=9, color=color, zorder=3, label=model)
        axis.set_xlabel(f"{SITE_LABELS['structural']} {title}")
        axis.grid(axis="x", color=GRID, lw=0.5)
        figures._letter(axis, letter, x=-0.02)
    axes[0].set_yticks(positions)
    axes[0].set_yticklabels([figures.SHORT_LABELS.get(task, task) for task in rows])
    axes[0].set_ylim(len(rows) - 0.5, -0.5)
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 1.0))
    figure.tight_layout(w_pad=0.5, rect=(0, 0, 1, 1 - 0.25 / figure.get_figheight()))
    return figures._save(figure, path)


def intra_block_gaps(summary: pd.DataFrame, blocks: int) -> pd.DataFrame:
    """Per task: the best full-width state inside a block (`INSIDE`) and the best residual-stream state, each chosen on
    validation, and the better of the two stream states that enter and leave the inside state's block, all by test score.
    `lead` is the inside state's lead over the best stream state and `same_depth_lead` its lead over the stream around
    its own block."""
    trained = relative(figures.headline(summary), blocks)
    full = trained[trained["family"] == "full"]
    rows = []
    for task, states in full.groupby("task"):
        stream = states[states["site"].isin(RESIDUAL)]
        inside = states[states["site"].isin(INSIDE)]
        if stream.empty or inside.empty:
            continue
        best_stream = figures._choose(stream)
        best_inside = figures._choose(inside)
        # block k's states sit at depth k + 1, between the stream entering it (depth k) and leaving it (depth k + 1)
        depth = int(best_inside["depth"])
        around = stream[stream["depth"].isin((depth - 1, depth))]
        assert len(around) == 2, f"{task}: the stream states around depth {depth} are {list(around['probe_name'])}"
        same_depth = float(around["full"].max())
        rows.append({"task": task, "inside_site": best_inside["site"], "inside_layer": int(best_inside["layer"]),
                     "inside_score": float(best_inside["full"]), "stream_site": best_stream["site"],
                     "stream_layer": int(best_stream["layer"]), "stream_score": float(best_stream["full"]),
                     "same_depth_score": same_depth, "lead": float(best_inside["full"] - best_stream["full"]),
                     "same_depth_lead": float(best_inside["full"]) - same_depth})
    return pd.DataFrame(rows)


def gap_table(gaps: dict[str, pd.DataFrame], path: Path, same_depth_lead: float = SAME_DEPTH_LEAD, lead: float = BEST_LEAD) -> Path:
    """A LaTeX table of the largest gains inside the block: per model (smallest first, as in the figures), the tasks whose
    inside state leads the stream at its own depth by `same_depth_lead` and the best stream state by `lead`, by same-depth lead."""
    lines = [r"\begin{table}[!htbp]", r"\centering\small",
             r"\caption{\textbf{The largest gains inside the block.} For each model, the tasks, among the 22 concepts and the 2024 "
             r"interaction gold standard, on which the best intra-block "
             r"state (chosen on validation among full-width attention and feed-forward states) reads at least "
             rf"{same_depth_lead:.2f} above the stream at the same depth and {lead:.2f} above the best stream state. The two "
             rf"cutoffs are display thresholds that keep the table to the largest gains, and {same_depth_lead:.2f} lies above "
             r"the largest standard deviation over seeds at any task's best state in ESMC-300 (0.031, "
             r"Section~\ref{sec:supp_detail}). State is its "
             r"site and block, and Score its test score (MCC). Best stream is the test score of the best residual-stream state "
             r"chosen on validation, and Same depth that of the better of the two stream states entering and leaving the "
             r"state's block. ESMC-300's scores are means over three seeds, and ESMC-600's and ESMC-6B's come from one seed. Against the stream at its own depth, a state "
             r"inside the block can read what the stream there barely shows, most in ESMC-6B.}",
             r"\label{tab:gaps}", r"\begin{tabular}{@{}l l l c c c@{}}", r"\toprule",
             r"Model & Task & State & Score & Best stream & Same depth \\"]
    for model in MODEL_COLORS:
        table = gaps[model]
        kept = table[(table["same_depth_lead"] >= same_depth_lead) & (table["lead"] >= lead)]
        kept = kept.sort_values("same_depth_lead", ascending=False)
        if kept.empty:
            continue
        lines.append(r"\midrule")
        for index, row in enumerate(kept.itertuples(index=False)):
            name = model if index == 0 else ""
            lines.append(f"{name} & {GAP_LABELS[row.task]} & {_state(row.inside_site, row.inside_layer)} & {row.inside_score:.2f} & "
                         f"{row.stream_score:.2f} & {row.same_depth_score:.2f} " + r"\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _state(site: str, layer: float, head: float | None = None) -> str:
    """A state as the text names it: the site's macro name and its 0-indexed block; the embedding, the final norm and
    the structure stream have no block."""
    if not isinstance(site, str):
        return "--"
    if site in ("embedding", "final_norm", "structural"):
        return site_tex(site)
    text = f"{site_tex(site)} {int(layer)}"
    return text if head is None else f"{text}, h{int(head)}"


def best_block_tables(best: pd.DataFrame, path: Path, tasks: Sequence[str] = CONCEPT_ORDER) -> Path:
    """A LaTeX table per model: for each task, the best state of each family (site and block), chosen on validation,
    with its test score, and the structure stream's test score where it was probed."""
    lines = []
    for model in MODEL_COLORS:
        table = best[best["model"] == model].set_index("task")
        blocks = int(table["blocks"].iloc[0])
        structure = "structure_score" in table
        lines += [r"\begin{table}[!htbp]", r"\centering\scriptsize",
                  rf"\caption{{\textbf{{The best state of each family in {model}}} ({blocks} blocks, numbered from 0), chosen on validation, "
                  rf"with its test score in parentheses, {'a mean over three seeds' if model == 'ESMC-300' else 'from one seed'}. Stream states are the embedding, a block's output and the final norm. "
                  r"Heads are numbered from 0." + (r" The last column is the test score of the structure stream, ESMFold2's "
                                                   r"256-wide mixture of every hidden state, one state per model." if structure else "")
                  + r" The other families' best scores sit close to the stream's on most tasks and differ most on the small InterPro tasks and lipidation.}",
                  rf"\label{{tab:best_{model.lower().replace('-', '')}}}",
                  r"\begin{tabular}{@{}l l l l l" + (" r" if structure else "") + r"@{}}", r"\toprule",
                  r"Task & Residual stream & Attention & Feed-forward & Single head" + (r" & \site{Struct}{}" if structure else "") + r" \\",
                  r"\midrule"]
        for task in tasks:
            if task not in table.index:
                continue
            row = table.loc[task]
            cells = []
            for family, _ in FAMILIES:
                site = row.get(f"{family}_site")
                if not isinstance(site, str):
                    cells.append("--")
                    continue
                layer = row[f"{family}_layer"]
                state = _state(site, layer, row["head"] if family == "head" else None)
                cells.append(f"{state} ({row[f'{family}_score']:.2f})")
            if structure:
                cells.append(f"{row['structure_score']:.2f}" if np.isfinite(row["structure_score"]) else "--")
            lines.append(f"{figures.TASK_LABELS.get(task, task)} & " + " & ".join(cells) + r" \\")
        lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def category_bands(axis: Axes, rows: list[str], positions: np.ndarray, right: bool = False) -> None:
    """Protify's `trends._category_bands` as the row bands of the other dot panels, which `figure_style.install` swaps
    in: alternating rows, a rule between kinds of concept and, with `right`, each kind named once beside its rows."""
    # positions: (rows,)
    start = 0
    for position in positions[::2]:
        axis.axhspan(position - 0.5, position + 0.5, color=ROW_BAND, lw=0, zorder=0)
    axis.tick_params(axis="y", length=0)
    for index in range(1, len(rows) + 1):
        if index == len(rows) or CATEGORY_OF.get(rows[index]) != CATEGORY_OF.get(rows[start]):
            top, bottom = positions[start], positions[index - 1]
            if index < len(rows):
                axis.axhline(max(top, bottom) + 0.5, color=MUTED, lw=0.5, zorder=1)
            if right:
                kind_tag(axis, (top + bottom) / 2, CATEGORY_OF.get(rows[start], ""), axis.get_yaxis_transform())
            start = index


def pair_figure(task: str, summaries: dict[str, pd.DataFrame], kinds: dict[str, str], rankings: dict[str, pd.DataFrame], gaps: pd.DataFrame,
                path: Path, intervals: dict[str, pd.DataFrame] | None = None) -> Path:
    """Protify's `trends.pair_figure` (at `ca7bbd2`) with the main text's layout, which `figure_style.install` swaps in.
    First row: A, one pair task's MCC on its test pairs along the relative depth of the residual stream, for every
    trained model, the randomly initialized model and the baseline encodings (levels), with the first trained model's
    probes on scrambled partners and on an untrained model's states; B, ROC AUC along the same axis; and, when the task
    has an extra test split, C, its ROC AUC, on B's axis. Past the final norm, a diamond marks each model's structure
    stream where it was probed, and in B and C a line marks chance. Second row, the figure's whole width: each site's
    best state minus the best residual-stream state, per model.

    Where `intervals` holds them, B shades the first replicate's interval on the test pairs. A task with an extra split
    is the noisier one, near chance: there each curve is a faint raw line under its running mean, and B shades only the
    one-hot encoding's interval."""
    from matplotlib.ticker import MaxNLocator

    plt = figures._pyplot()
    trained = trends._ordered_models([model for model in summaries if kinds[model] == "trained"])
    colors = trends._model_colors(trained)
    random_style = CONTROLS["random init"]

    def stream_of(model: str) -> pd.DataFrame:
        ranking = rankings.get(model)
        if ranking is None:
            return pd.DataFrame(columns=["split", "relative_depth", "roc_auc"])
        return ranking[(ranking["task"] == task) & (ranking["family"] == "full") & ranking["site"].isin(RESIDUAL)].sort_values("relative_depth")

    extras = sorted({split for model in trained for split in stream_of(model)["split"].unique() if split != "test"})
    smoothed = bool(extras)
    columns = 3 if extras else 2
    figure = plt.figure(figsize=(7.2, 3.6))
    grid = figure.add_gridspec(2, columns, height_ratios=[1.75, 1.0])
    axes = [figure.add_subplot(grid[0, 0]), figure.add_subplot(grid[0, 1])]
    if extras:
        axes.append(figure.add_subplot(grid[0, 2], sharey=axes[1]))
        axes[2].tick_params(labelleft=False)
    axes.append(figure.add_subplot(grid[1, :]))
    auc_axes = {"test": axes[1]} | ({extras[0]: axes[2]} if extras else {})
    gap_axis = axes[-1]
    for axis, letter in zip(axes, "ABCD", strict=False):
        figures._letter(axis, letter, x=-0.04 if axis is gap_axis else -0.02 if smoothed else -0.08)

    def curve(summary: pd.DataFrame, plm: str = "trained", control: str = "original", site: Sequence[str] = RESIDUAL) -> pd.DataFrame:
        rows = summary[(summary["task"] == task) & (summary["family"] == "full") & summary["site"].isin(site)
                       & (summary["plm"] == plm) & (summary["probe"] == "trained") & (summary["control"] == control)]
        return rows.sort_values("depth")

    def level(axis: Axes, value: float, model: str, label: str | None = None) -> None:
        """A baseline encoding's one state, as a level the legend names."""
        style = CONTROLS[trends._display(model)]
        axis.axhline(value, color=style.color, lw=0.8, ls=style.dash, label=label)

    def interval_rows(model: str) -> pd.DataFrame | None:
        """The first replicate's intervals of the test pairs' ROC AUC along the residual stream."""
        table = (intervals or {}).get(model)
        if table is None:
            return None
        return table[(table["task"] == task) & (table["family"] == "full") & table["site"].isin(RESIDUAL) & (table["replicate"] == 0)
                     & (table["split"] == "test") & (table["metric"] == "roc_auc")].sort_values("relative_depth")

    def band(model: str, color: str) -> None:
        """A model's interval along the residual stream."""
        rows = interval_rows(model)
        if rows is not None:
            auc_axes["test"].fill_between(rows["relative_depth"], rows["low"], rows["high"], color=color, alpha=0.18, lw=0)

    def stream_line(axis: Axes, x: pd.Series, y: pd.Series, color: str, width: float, dash: str = "-", label: str | None = None) -> None:
        """A curve along the stream: as it is or, on a noisy task, faint under its running mean."""
        if smoothed:
            axis.plot(x, y, color=color, lw=0.6, alpha=0.25)
            y = y.rolling(RUNNING_MEAN, center=True, min_periods=1).mean()
            width += 0.3
        axis.plot(x, y, color=color, lw=width, ls=dash, label=label)

    structured = False
    for model in trained + [model for model in summaries if model not in trained]:
        line = curve(summaries[model])
        if line.empty:
            continue
        if kinds[model] in ("trained", "random-init") and not smoothed:
            band(model, colors.get(model, random_style.color))
        stream = stream_of(model)
        if kinds[model] == "trained":
            style = {"color": colors[model], "width": 1.3}
            stream_line(axes[0], line["relative_depth"], line["full"], label=model, **style)
        elif kinds[model] == "random-init":
            style = {"color": random_style.color, "width": 1.1, "dash": random_style.dash}
            stream_line(axes[0], line["relative_depth"], line["full"], label=trends._display(model), **style)
        else:
            level(axes[0], float(line["full"].iloc[0]), model, trends._display(model))
            for split, axis in auc_axes.items():
                auc = stream[stream["split"] == split]
                if not auc.empty:
                    level(axis, float(auc["roc_auc"].iloc[0]), model)
            rows = interval_rows(model)
            if smoothed and trends._display(model) == "one-hot" and rows is not None and len(rows):
                assert len(rows) == 1, f"The one-hot encoding has one state, not {len(rows)}."
                auc_axes["test"].axhspan(rows["low"].iloc[0], rows["high"].iloc[0], color=CONTROLS["one-hot"].color, alpha=0.1, lw=0, zorder=0)
            continue
        for split, axis in auc_axes.items():
            auc = stream[stream["split"] == split]
            stream_line(axis, auc["relative_depth"], auc["roc_auc"], **style)
        mark = {"color": style["color"]} if kinds[model] == "trained" else {"facecolors": "white", "edgecolors": random_style.color, "linewidths": 0.7}
        point = curve(summaries[model], site=STRUCTURE)
        if not point.empty:
            structured = True
            axes[0].scatter([STRUCTURE_X], point["full"].iloc[:1], marker="D", s=10, zorder=3, **mark)
            ranking = rankings.get(model)
            if ranking is not None:
                ranking = ranking[(ranking["task"] == task) & (ranking["family"] == "full") & ranking["site"].isin(STRUCTURE)]
                for split, axis in auc_axes.items():
                    auc = ranking.loc[ranking["split"] == split, "roc_auc"].iloc[:1]
                    axis.scatter([STRUCTURE_X] * len(auc), auc, marker="D", s=10, zorder=3, **mark)
    if structured:
        axes[0].scatter([], [], marker="D", s=10, color=INK, label=SITE_LABELS["structural"])
    if trained:
        reference = summaries[trained[0]]
        for plm, control, legend, name in (("trained", "scrambled", "scrambled partners", "scrambled"), ("untrained", "original", "untrained model", "untrained")):
            line = curve(reference, plm, control)
            if not line.empty:
                axes[0].plot(line["relative_depth"], line["full"], color=CONTROLS[name].color, ls=CONTROLS[name].dash, lw=0.7 if smoothed else 0.9, label=legend)
    axes[0].set_ylabel("MCC")
    axes[1].set_ylabel("ROC AUC")
    if extras:
        figures._tag(axes[1], "test")
        figures._tag(axes[2], "realistic test")
    for axis in auc_axes.values():
        axis.axhline(0.5, color=MUTED, lw=0.6)
        axis.annotate("chance", (0.99, 0.5), xycoords=axis.get_yaxis_transform(), xytext=(0, 3), textcoords="offset points", fontsize=5.5, color=INK_SECONDARY, va="bottom", ha="right",
                      bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.5})
    for axis in [axes[0], *auc_axes.values()]:
        axis.set_xlabel("relative depth")
        axis.set_xlim(0, STRUCTURE_X + 0.06 if structured else 1)
        axis.set_xticks([0.0, 0.5, 1.0])
        axis.grid(axis="y", color=GRID, lw=0.5)
    if not gaps.empty:
        models = trends._ordered_models([model for model in dict.fromkeys(gaps["model"]) if kinds.get(model) == "trained"])
        first = gaps[gaps["model"] == models[0]].set_index("site")["median"].sort_values(ascending=False) if models else pd.Series(dtype=float)
        sites = list(first.index)
        positions = np.arange(len(sites))
        offsets = np.linspace(-0.2, 0.2, len(models)) if len(models) > 1 else [0.0]
        gap_axis.axhline(0.0, color=INK_SECONDARY, lw=0.6)
        for offset, model in zip(offsets, models, strict=True):
            table = gaps[gaps["model"] == model].set_index("site").reindex(sites)
            gap_axis.scatter(positions + offset, table["median"], s=10, color=colors[model], zorder=3)
        gap_axis.set_xticks(positions)
        gap_axis.set_xticklabels([SITE_LABELS.get(site, site) for site in sites], fontsize=5.5)
        gap_axis.set_xlim(-0.6, len(sites) - 0.4)
        gap_axis.set_ylabel("site minus\nresidual stream")
        gap_axis.yaxis.set_major_locator(MaxNLocator(4))
        gap_axis.grid(axis="y", color=GRID, lw=0.5)
        gap_axis.tick_params(axis="x", length=0)
    handles, labels = axes[0].get_legend_handles_labels()
    figure.tight_layout(h_pad=0.5, w_pad=1.2, rect=(0, 0, 1, 1 - 0.25 / figure.get_figheight()))
    box = gap_axis.get_position()
    gap_axis.set_position((box.x0, box.y0, 0.995 - box.x0, box.height))  # to the figure's edge, past the first row's named levels
    figure.legend(handles, labels, loc="upper center", ncol=len(labels) or 1, frameon=False, bbox_to_anchor=(0.5, 1.0), fontsize=5.8, handlelength=1.8,
                  handletextpad=0.4, columnspacing=0.9)
    return figures._save(figure, path)


def kind_onsets(profiles: pd.DataFrame) -> pd.Series:
    """One model's median onset over the tasks of each kind of concept, by kind, as Protify's `category_profiles`
    reports it and the text quotes it."""
    return profiles.groupby("category")["onset_depth"].median()


def emergence_maps(summaries: dict[str, pd.DataFrame], profiles: pd.DataFrame, path: Path) -> Path:
    """Protify's `trends.emergence_maps` (at `ca7bbd2`), kinds of concept in `ONSET_ORDER`. One panel per model: each
    task's residual stream along relative depth, as a share of its highest score (the scale starts at one half, below
    which most tasks fall only at the embedding); a white bar marks the onset (the first depth within 5% of the highest),
    a dot the best stream state chosen on validation, and a gold line across a kind's rows that kind's median onset."""
    from matplotlib.lines import Line2D
    from matplotlib.patheffects import withStroke

    plt = figures._pyplot()
    bar_edge = [withStroke(linewidth=1.5, foreground=INK)]
    median_edge = [withStroke(linewidth=2.1, foreground=INK)]
    models = trends._ordered_models(list(summaries))
    present = set().union(*(set(trends._stream(summary)["task"]) for summary in summaries.values()))
    members = dict(CATEGORIES)
    rows = [task for kind in ONSET_ORDER for task in members[kind] if task in present]
    assert present <= set(rows), f"The onset order leaves out {sorted(present - set(rows))}."
    figure, axes = plt.subplots(1, len(models), figsize=(1.9 * len(models) + 1.7, 0.17 * len(rows) + 1.1), squeeze=False, sharey=True)
    colormap = figures._colormap(("#ffffff", *BLUE_RAMP), "emergence")
    image = None
    for index, (axis, model) in enumerate(zip(axes[0], models, strict=True)):
        stream = trends._stream(summaries[model])
        blocks = int(summaries[model]["blocks"].iloc[0])
        edges = (np.arange(blocks + 3) - 0.5) / (blocks + 1)  # one cell per depth 0..L + 1
        matrix = np.full((len(rows), blocks + 2), np.nan)  # (tasks, depths)
        for row, task in enumerate(rows):
            line = stream[stream["task"] == task]
            peak = line["full"].max() if not line.empty else np.nan
            if not np.isfinite(peak) or peak <= 0:
                continue
            matrix[row, line["depth"].to_numpy()] = np.clip(line["full"].to_numpy() / peak, 0.0, 1.0)
        image = axis.pcolormesh(edges, np.arange(len(rows) + 1) - 0.5, matrix, cmap=colormap, vmin=SHARE_FLOOR, vmax=1.0, shading="flat")
        medians = kind_onsets(profiles[profiles["model"] == model])
        for kind in ONSET_ORDER:  # under the tasks' own bars, so a kind of one task shows both
            span = [row for row, task in enumerate(rows) if CATEGORY_OF.get(task) == kind]
            if span and kind in medians.index:
                axis.plot([medians[kind]] * 2, [span[0] - 0.5, span[-1] + 0.5], color=GOLD, lw=1.3, solid_capstyle="butt", path_effects=median_edge,
                          zorder=1.9)
        marks = profiles[profiles["model"] == model].set_index("task")
        for row, task in enumerate(rows):
            if task in marks.index:
                axis.plot([marks.at[task, "onset_depth"]] * 2, [row - 0.42, row + 0.42], color="white", lw=1.0, solid_capstyle="butt", path_effects=bar_edge)
                axis.scatter(marks.at[task, "best_depth"], row, s=7, facecolors="white", edgecolors=INK, linewidths=0.6, zorder=3)
        axis.set_ylim(len(rows) - 0.5, -0.5)
        axis.set_xlim(edges[0], edges[-1])
        axis.set_xticks([0.0, 0.5, 1.0])
        if index < len(models) - 1:
            axis.set_xticklabels(["0.0", "0.5", ""])  # beside the next panel's 0.0
        axis.set_xlabel("relative depth")
        axis.tick_params(axis="y", length=0)
        figures._tag(axis, model)
        figures._bare(axis)
        if index == 0:
            axis.set_yticks(range(len(rows)))
            axis.set_yticklabels([SHORT_LABELS.get(task, task) for task in rows])
    for row in range(1, len(rows)):
        if CATEGORY_OF.get(rows[row]) != CATEGORY_OF.get(rows[row - 1]):
            for axis in axes[0]:
                axis.axhline(row - 0.5, color="white", lw=1.6)
    last = axes[0][-1]
    for kind in ONSET_ORDER:
        span = [row for row, task in enumerate(rows) if CATEGORY_OF.get(task) == kind]
        if span:
            kind_tag(last, (span[0] + span[-1]) / 2, kind, last.get_yaxis_transform())
    reserve = 0.3 / figure.get_figheight()  # inches kept under the panels for the colorbar
    figure.tight_layout(w_pad=0.6, rect=(0, reserve, 1, 1))
    left = axes[0][0].get_position().x0
    width, height = min(0.35, 0.9 - left), 0.07 / figure.get_figheight()
    bar = figure.colorbar(image, cax=figure.add_axes((left, 0.3 * reserve, width, height)), orientation="horizontal", extend="min")
    bar.set_label("score / task's highest residual-stream score", fontsize=5.5)
    bar.ax.tick_params(labelsize=5)
    keys = [Line2D([], [], ls="none", marker="|", ms=6, mew=1.0, color="white", path_effects=bar_edge),
            Line2D([], [], ls="none", marker="o", ms=3, mfc="white", mec=INK, mew=0.6),
            Line2D([], [], ls="none", marker="|", ms=6, mew=1.3, color=GOLD, path_effects=median_edge)]
    figure.legend(keys, ["onset", "best depth", "median onset of the kind"], loc="center left",
                  bbox_to_anchor=(left + width + 0.05, 0.3 * reserve + height / 2), ncol=3, frameon=False, fontsize=5.5, columnspacing=1.0)
    return figures._save(figure, path)


def controls_summary(best: pd.DataFrame, path: Path) -> Path:
    """Protify's `trends.controls_summary` (at `ca7bbd2`) in the paper's control colors. Per task, the best
    residual-stream score of every trained model, of the randomly initialized model and of each baseline encoding, and
    the first trained model's probes at that state on scrambled sequences and on an untrained model's states; tasks
    grouped by concept category. The controls that sit near zero are pale, so the two that read something stand out."""
    plt = figures._pyplot()
    names = list(dict.fromkeys(best["model"]))
    trained = trends._ordered_models([model for model in names if (best[best["model"] == model]["kind"] == "trained").all()])
    others = [model for model in names if model not in trained]
    rows = trends._task_rows(set(best["task"]))
    colors = trends._model_colors(trained)
    figure, axis = plt.subplots(figsize=(4.8, 0.2 * len(rows) + 1.1))
    positions = np.arange(len(rows))
    category_bands(axis, rows, positions, right=True)
    axis.axvline(0.0, color=INK_SECONDARY, lw=0.6, zorder=1)

    def scores(model: str, column: str = "residual_score") -> np.ndarray:
        table = best[best["model"] == model].set_index("task")
        return np.array([table.at[task, column] if task in table.index and column in table else np.nan for task in rows], dtype=float)  # (tasks,)

    for model in others:
        display = trends._display(model)
        style = CONTROLS[display]
        kept = display != "random vectors"
        axis.scatter(scores(model), positions, s=13 if style.marker == "s" else 14, marker=style.marker, color=style.color, linewidths=0.9 if style.marker in ("x", "+") else None,
                     zorder=3 if kept else 2.5, label=display)
    if trained:
        for column, legend, name in (("control_trained_trained_scrambled", "scrambled", "scrambled"), ("control_untrained_trained_original", "untrained", "untrained")):
            values = scores(trained[0], column)
            if np.isfinite(values).any():
                axis.scatter(values, positions, s=12, marker=CONTROLS[name].marker, facecolors="none", edgecolors=CONTROLS[name].color, linewidths=0.8, zorder=2.5, label=legend)
    for model in trained:
        axis.scatter(scores(model), positions, s=16, color=colors[model], zorder=4, label=model)
    axis.set_yticks(positions)
    axis.set_yticklabels([SHORT_LABELS.get(task, task) for task in rows])
    axis.set_ylim(len(rows) - 0.5, -0.5)
    axis.set_xlabel("best residual-stream score")
    axis.grid(axis="x", color=GRID, lw=0.5)
    handles, labels = axis.get_legend_handles_labels()
    # The legend reads left to right as the panel does: the controls near zero, the encodings that read something, the trained models.
    rank = {label: place for place, label in enumerate((*CONTROL_LEGEND, *trained))}
    order = sorted(range(len(labels)), key=lambda index: rank[labels[index]])
    axis.legend([handles[index] for index in order], [labels[index] for index in order], loc="lower center", bbox_to_anchor=(0.45, 1.0),
                ncol=3, frameon=False, fontsize=5.3)
    figure.tight_layout()
    return figures._save(figure, path)


def variant_depth_curves(variants: dict[str, pd.DataFrame], blocks: int, path: Path, tasks: Sequence[str] = TASK_ORDER) -> Path:
    """Protify's `figures.variant_depth_curves` (at `ca7bbd2`) on relative depth, one label under the panels. The
    residual stream of every task under each variant of the analysis, the final norm a hollow mark. A probe has its
    color; its mean-only series, drawn after it, is its pale tone, dashed, so that a series under it still shows."""
    plt = figures._pyplot()
    present = set.intersection(*(set(summary["task"]) for summary in variants.values()))
    tasks = [task for task in tasks if task in present]
    others = iter(OTHER_SERIES)
    styles = {}
    for name in variants:
        probe, _, pooling = name.partition(", ")
        if probe in PROBE_COLORS and pooling:
            styles[name] = (MEAN_ONLY_COLORS[probe], "--")
        else:
            styles[name] = (PROBE_COLORS[probe] if probe in PROBE_COLORS else next(others), "-")
    figure, axes = figures._grid(plt, len(tasks), 6, row_height=1.18, sharex=True)
    for axis, task in zip(axes, tasks, strict=False):
        for name, summary in variants.items():
            color, dash = styles[name]
            trained = figures.headline(summary)
            line = figures._with_depth(trained[(trained["task"] == task) & (trained["family"] == "full") & trained["site"].isin(RESIDUAL)], blocks)
            line = line.assign(relative_depth=line["depth"] / (blocks + 1))
            body = line[line["site"] != "final_norm"].sort_values("depth")
            axis.plot(body["relative_depth"], body["mean"], color=color, label=name, lw=1.2, ls=dash)
            axis.fill_between(body["relative_depth"], body["mean"] - body["std"], body["mean"] + body["std"], color=color, alpha=0.16, lw=0)
            norm = line[line["site"] == "final_norm"]
            if not norm.empty:
                axis.plot(norm["relative_depth"], norm["mean"], marker="o", ms=3, mfc="white", mec=color, mew=1.0, ls="none", gid="final_norm")
        figures._tag(axis, SHORT_LABELS.get(task, task))
        axis.set_xlim(-0.03, 1.03)
        axis.set_xticks([0.0, 0.5, 1.0])
        axis.tick_params(labelbottom=True)
        axis.grid(axis="y", color=GRID, lw=0.5)
        if axis.get_subplotspec().is_first_col():
            axis.set_ylabel("score")
    figure.supxlabel("relative depth", fontsize=7, color=INK, y=0.015)
    handles, labels = figures._stream_legend(axes)
    figures._legend_top(figure, handles, labels, len(labels), 0.3)
    return figures._save(figure, path)


def pca_grid(frames: dict[str, pd.DataFrame], path: Path, top: int = 5) -> Path:
    """Protify's `figures.pca_grid` (at `ca7bbd2`) with short names and a two-row legend. Two principal coordinates of
    pooled states per block (columns), rows A and B per model; proteins colored by label set (the most frequent sets of
    the first model fix the colors), scrambled copies and the rest gray."""
    from matplotlib.lines import Line2D

    plt = figures._pyplot()
    names = list(frames)
    first = frames[names[0]]
    layers = list(dict.fromkeys(first["layer"]))
    groups = [group for group in first["group"].value_counts().index if group not in ("other", "scrambled")][:top]
    # InterPro names arrive lowercased; restore the capital of the first letter and of GTPase.
    shown = {group: (group[:1].upper() + group[1:]).replace("gtpase", "GTPase").replace("G protein-coupled receptor", "GPCR").replace(" receptor", "")
             for group in groups} | {"scrambled": "scrambled test sequences"}
    colors = dict(zip(groups, LABEL_SET_COLORS, strict=False)) | {"scrambled": CONTROLS["scrambled"].color}
    figure, axes = plt.subplots(len(names), len(layers), figsize=(1.05 * len(layers) + 0.4, 1.15 * len(names) + 0.3), squeeze=False)
    for row, name in enumerate(names):
        frame = frames[name]
        for column, layer in enumerate(layers):
            axis = axes[row, column]
            block = frame[frame["layer"] == layer]
            other = block[~block["group"].isin(colors)]
            axis.scatter(other["pc1"], other["pc2"], s=0.8, color=GRID, lw=0, rasterized=True)
            for group, color in colors.items():
                chosen = block[block["group"] == group]
                axis.scatter(chosen["pc1"], chosen["pc2"], s=1.4, color=color, lw=0, rasterized=True, label=group)
            axis.set_xticks([])
            axis.set_yticks([])
            if not block.empty:
                axis.set_xlabel(f"PC1 {100 * block['explained_1'].iloc[0]:.0f}%", fontsize=5, labelpad=1)
                axis.set_ylabel(f"PC2 {100 * block['explained_2'].iloc[0]:.0f}%", fontsize=5, labelpad=1)
            if row == 0:
                axis.text(0.5, 1.04, f"block {layer}", transform=axis.transAxes, ha="center", fontsize=6, color=INK)
            if column == 0:
                axis.text(-0.32, 0.5, name.replace("random-init model", "random init"), transform=axis.transAxes, rotation=90, ha="center", va="center", fontsize=6, color=INK)
                figures._letter(axis, "ABCDEFGH"[row], x=-0.2)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    handles.append(Line2D([], [], ls="none", marker="o", ms=1.2, mew=0, color=GRID))
    labels.append("other test proteins")
    figure.tight_layout(w_pad=0.2, h_pad=0.4, rect=(0, 0, 1, 1 - 0.27 / figure.get_figheight()))
    figure.legend(handles, [shown.get(label, label) for label in labels], loc="upper center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 1.0), markerscale=4,
                  fontsize=5.5, handletextpad=0.2, columnspacing=1.0, labelspacing=0.3)
    return figures._save(figure, path)


def phospho_figure(tests: pd.DataFrame, blocks: int, path: Path) -> Path:
    """Protify's `figures.phospho_figure` (at `ca7bbd2`) on relative depth, its legend above the panels. A, B: the
    residual stream's mutant-activity MCC, averaged over proteins, on raw (A) and standardized (B) pooled means, against
    shuffled labels and the untrained model, with the 95% confidence interval of the mean over proteins shaded. C: the
    trained model's MCC on raw means at every site and block. D: the Bonferroni-corrected p-value of true against
    shuffled labels along the residual stream, per input treatment. The trained model is ESMC-300."""
    plt = figures._pyplot()
    treatments = [inputs for inputs in ("raw", "standardized") if inputs in set(tests["inputs"])]
    figure, axes = plt.subplots(1, len(treatments) + 2, figsize=(7.2, 2.18), gridspec_kw={"width_ratios": [1.0] * len(treatments) + [1.35, 0.8]})
    trained_color = MODEL_COLORS["ESMC-300"]
    pale = CONTROLS["untrained"].color
    curves = (("trained_true", "trained model, true labels", trained_color, "-"), ("trained_shuffled", "trained model, shuffled labels", pale, "--"),
              ("untrained_true", "untrained model, true labels", pale, "-"))
    stream = figures._with_depth(tests[tests["site"].isin(("embedding", "resid_post"))], blocks).sort_values("depth")
    stream = stream.assign(relative_depth=stream["depth"] / (blocks + 1))
    for axis, inputs, letter in zip(axes, treatments, "AB", strict=False):
        rows = stream[stream["inputs"] == inputs]
        for column, legend, color, dash in curves:
            interval = 1.96 * rows[f"{column}_std"] / np.sqrt(rows["proteins"])
            axis.plot(rows["relative_depth"], rows[column], color=color, label=legend, lw=1.2, ls=dash)
            axis.fill_between(rows["relative_depth"], rows[column] - interval, rows[column] + interval, color=color, alpha=0.2, lw=0)
        axis.set_xlabel("relative depth")
        axis.grid(axis="y", color=GRID, lw=0.5)
        figures._letter(axis, letter)
    axes[0].set_ylabel("mean test MCC over proteins")
    handles, labels = axes[0].get_legend_handles_labels()
    middle = axes[len(treatments)]
    raw = tests[(tests["inputs"] == treatments[0]) & tests["site"].isin(BLOCK_SITES)]
    grid = raw.pivot_table(index="site", columns="layer", values="trained_true")
    grid = grid.reindex([site for site in BLOCK_SITES if site in grid.index])
    image = middle.imshow(grid.to_numpy(), aspect="auto", cmap=figures._colormap(BLUE_RAMP, "blue"), interpolation="nearest")
    middle.set_yticks(range(len(grid)))
    middle.set_yticklabels([SITE_LABELS[site] for site in grid.index], fontsize=5)
    middle.set_xlabel("block")
    figures._bare(middle)
    bar = figure.colorbar(image, ax=middle, shrink=0.85, pad=0.02)
    bar.set_label(f"mean test MCC, {treatments[0]}", fontsize=5.5)
    bar.ax.tick_params(labelsize=5)
    figures._letter(middle, "ABC"[len(treatments)])
    right = axes[-1]
    for inputs, dash in zip(treatments, ("-", "--"), strict=False):
        rows = stream[stream["inputs"] == inputs]
        right.plot(rows["relative_depth"], -np.log10(rows["p_bonferroni"].clip(lower=1e-300)), color=trained_color, ls=dash, lw=1.1, label=inputs)
    right.axhline(-np.log10(0.05), color=INK_SECONDARY, ls=":", lw=0.7, label="p = 0.05")
    right.set_xlabel("relative depth")
    right.set_ylabel("-log10 corrected p", fontsize=6)
    right.grid(axis="y", color=GRID, lw=0.5)
    right.legend(frameon=False, fontsize=5.5, loc="center")
    figures._letter(right, "ABCD"[len(treatments) + 1])
    figure.tight_layout(rect=(0, 0, 1, 1 - 0.22 / figure.get_figheight()), w_pad=0.6)
    figure.legend(handles, labels, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 1.0))
    return figures._save(figure, path)
