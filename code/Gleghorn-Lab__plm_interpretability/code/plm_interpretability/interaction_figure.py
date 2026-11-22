"""The interpretability paper's Fig. 6: where a frozen ESMC is read decides how well a simple probe predicts interaction.

    python -m plm_interpretability.interaction_figure --survey SURVEY --pooling POOLING --out PNG --values CSV

`SURVEY` and `POOLING` are local copies of the two archives (`archive.REPO` at the pin of `published.SUMMARY_REVISION`,
which holds the survey and the tuned pair probes, and `archive.POOLING_REPO`, whose `survey/` folder adds the baseline
encodings' probes of the 2024 gold standard). The figure reads the 2024 gold standard of Bernett and colleagues (task
`ppi`). The survey archive also holds probes of their 2026 gold standard (`ppi2`), which the paper does not report
(2026-11-18), so no figure here draws them. A site of this code is a state type in the paper. The panels hold

- A, left, the survey's pair probe (test MCC) on each residual-stream state along relative depth, for every trained
  model and the randomly initialized ESMC-300, the one-hot encoding as a level (random vectors, at chance, are in C),
  each model's best stream state chosen on validation as an open circle on its curve, and the best published MCC as a
  dashed level. A, right, the best states, one column per model on the same MCC axis: the survey's probe at the best
  stream state (open circle) and at the best state inside the block (star, its site and block below), an arrow from
  one to the other, and the tuned MLP at the state inside the block (crimson star, C's crimson bar).
- B, each site's best probe, the structure stream's (ESMFold2's learned mixture of the model's residual-stream
  states, from the roots of `archive.SITE_ROOTS`) among them, minus the best residual-stream probe (MCC), per model,
  both chosen on validation; the stream after each block, every model's best stream state and so zero, has no row.
- C, the tuned MLP's test MCC, ROC AUC and PR AUC on each row of `published.ROWS` beside the published predictors of
  `published.PUBLISHED`, ordered as `published.table` orders them, as bars from each axis's floor (0 for MCC, chance
  for the AUCs) without intervals, since the published predictors report none.
- D, the paired gains in test ROC AUC under the same tuned MLP from reading each model's state inside the block or best
  stream state instead of its last hidden state, and from tuning the head on the last hidden state.

The per-model probe summaries are rebuilt from the run tables and checked against the archive's reference summaries
(`REFERENCES`) before anything is drawn, as `plm_interpretability.reproduce` checks them. Every plotted value also goes to the
CSV.
"""

from __future__ import annotations

import argparse
import numpy as np
import pandas as pd

from collections.abc import Sequence
from pathlib import Path
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter
from src.protify.interpretability import figures
from src.protify.interpretability.figures import GRID, INK, INK_SECONDARY, MUTED, RESIDUAL

from plm_interpretability import archive, cross_model, figure_style, published
from plm_interpretability.figure_style import CONTROLS, CRIMSON, MODEL_COLORS, PUBLISHED_COLOR, READ_STATE_COLORS, ROW_BAND, interval_marks, site_math


# The archive's summaries written when the survey's figures were first drawn, which the rebuilt ones must match.
REFERENCES = {"ESMC-300": "analyses/final2/main/summary.parquet", "ESMC-600": "analyses/final2/esmc600/summary.parquet",
              "ESMC-6B": "analyses/final2/esmc6b/summary.parquet", "ESMC-300 random init": "analyses/final2/main/summary_random_init.parquet"}
DIFFERENCES = "analyses/last_hidden_controls/differences.parquet"  # paired differences between the tuned probes' arms
GOLD_2024 = "ppi"
BASELINE_NAMES = {"OneHot-Protein": "one-hot", "Random": "random vectors"}
RANDOM_INIT = "ESMC-300 random init"
CONTROL_STYLES = {RANDOM_INIT: "random init", **BASELINE_NAMES}  # each control encoding's look in `CONTROLS`
STRUCTURE = "structural"  # ESMFold2's structure stream, read as one more state of the model whose states it mixes
STREAM_REFERENCE = "resid_post"  # every model's best stream state on the 2024 gold standard, B's zero, so B has no row for it
# D's comparisons, as (first arm, second arm, row label): the same tuned MLP at another state, and the tuned MLP
# against the survey's probe at the last hidden state. `naive` is the survey's probe under its own setting.
GAINS = (("inside_mlp", "last_mlp", "choose state"), ("stream_mlp", "last_mlp", "choose depth"), ("last_mlp", "last_naive", "tune head"))
GAIN_METRIC = "test.roc_auc"
# C's metrics as (axis label, axis start, axis end, the bars' floor).
C_METRICS = {"mcc": ("test MCC", 0.0, 0.34, 0.0), "roc_auc": ("test ROC AUC", 0.485, 0.75, 0.5), "pr_auc": ("test PR AUC", 0.485, 0.75, 0.5)}
CHANCE = 0.5  # ROC AUC and, with balanced negatives, PR AUC of a guess
AUC_TICKS = (0.5, 0.6, 0.7)
BAR_HEIGHT = 0.62  # rows are 1 apart
DEPTH_MCC = (0.135, 0.33)  # A's y axis: the one-hot level to the tuned MLP's best MCC, with room for its star
DEPTH_TICKS = (0.15, 0.2, 0.25, 0.3)
LABEL_SIZE = 5.6  # row labels, direct labels and keys
SEED_OFFSETS = (-0.22, 0.0, 0.22)  # rows of three seeds or three models spread their marks over the row
# A's best-state columns: the survey's probe and the tuned MLP at these offsets from each model's column.
LINEAR_OFFSET, TUNED_OFFSET = -0.12, 0.22
STAR_SIZE, CIRCLE_SIZE = 46, 15
PAGE_WIDTH = 6.3  # inches: the text width of an sn-jnl page
# Each panel's axes as (left, bottom, width, height) in inches from the figure's lower left corner, so the gutters
# between the four regions read directly; C's three metric columns share its box in `C_WIDTHS` with `C_SPACE` inches
# between them. A's region is the top row; C's the lower left; B and D, which share a key, the lower right.
WIDTH, HEIGHT = 6.15, 6.0
BOXES = {"A": (0.42, 3.78, 4.12, 1.88), "A best": (4.62, 3.78, 1.36, 1.88), "B": (0.65, 1.62, 1.38, 1.33), "C": (3.52, 0.42, 2.36, 2.53),
         "D": (0.65, 0.42, 1.38, 0.56)}
C_WIDTHS, C_SPACE = (1.5, 1.0, 1.0), 0.07
LETTERS = {"A": (0.0, 6.0), "B": (0.0, 3.26), "C": (2.2, 3.26), "D": (0.0, 1.12)}  # each letter's top left corner, inches
KEYS = {"A": (0.36, 5.68), "B": (0.13, 3.0), "C": (2.56, 3.0)}  # each key's lower left corner, inches; B's key is D's too


# -- reading ----------------------------------------------------------------------------------------------------------


def task_folder(survey: Path, pooling: Path, root: str, task: str) -> Path:
    """The folder holding `root`'s survey probes of `task`: the survey archive's, or the pooling archive's additions
    (`survey/`), never both."""
    candidates = [base / "runs" / root / "linear" / task for base in (survey, pooling / "survey")]
    found = [folder for folder in candidates if (folder / "scores.parquet").exists()]
    if len(found) != 1:
        raise FileNotFoundError(f"{root}'s {task} probes are in {len(found)} of {[str(folder) for folder in candidates]}, not one.")
    return found[0]


def pair_summary(folders: Sequence[Path], blocks: int) -> pd.DataFrame:
    """One model's pair-task summary from its replicates' task folders (one per seed): `archive.summarize` of the
    compacted scores with each probe's validation score, and each state's depth and relative depth."""
    scores = pd.concat([pd.read_parquet(folder / "scores.parquet").assign(replicate=index) for index, folder in enumerate(folders)], ignore_index=True)
    validation = pd.concat([pd.read_parquet(folder / "probes.parquet")[archive.VALIDATION].assign(replicate=index) for index, folder in enumerate(folders)],
                           ignore_index=True)
    return cross_model.relative(archive.summarize(scores, validation), blocks)


def encodings() -> dict[str, tuple[tuple[str, ...], int]]:
    """Every encoding the figure reads, by name: its replicate roots (one per seed) and its blocks."""
    groups = {**archive.MODELS, **archive.RANDOM, **archive.BASELINES}
    blocks = {**archive.BLOCKS, RANDOM_INIT: archive.BLOCKS["ESMC-300"], "OneHot-Protein": 0, "Random": 0}
    return {name: (roots, blocks[name]) for name, roots in groups.items()}


def structure_folders(survey: Path, roots: Sequence[str], task: str) -> list[Path]:
    """The task folders of the structure-stream probes completing `roots`, one per root (seed): the roots of
    `archive.SITE_ROOTS` that complete each root and hold `task`."""
    folders = []
    for root in roots:
        sources = [source for source, target in archive.SITE_ROOTS.items() if target == root]
        found = [survey / "runs" / source / "linear" / task for source in sources]
        found = [folder for folder in found if (folder / "scores.parquet").exists()]
        assert len(found) == 1, f"{root} has {len(found)} roots of more sites holding {task}: {[str(folder) for folder in found]}"
        folders.append(found[0])
    return folders


def read_structure(survey: Path, task: str) -> dict[str, pd.DataFrame]:
    """Each trained and randomly initialized model's summary of its structure-stream probes (ESMFold2's learned mixture
    of the model's residual-stream states) on `task`, one replicate per seed as the model's own probes have."""
    summaries = {}
    for name, roots in {**archive.MODELS, **archive.RANDOM}.items():
        blocks = archive.BLOCKS["ESMC-300" if name == RANDOM_INIT else name]
        summary = pair_summary(structure_folders(survey, roots, task), blocks)
        assert set(summary["site"]) == {STRUCTURE}, f"{name}'s structure-stream roots hold sites {set(summary['site'])}"
        assert (summary["replicates"] == len(roots)).all(), f"{name}'s structure-stream probes lack a seed"
        summaries[name] = summary
    return summaries


def joined(summaries: dict[str, pd.DataFrame], structure: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Each encoding's summary with its structure-stream probes appended, so the structure stream is one more state."""
    return {name: pd.concat([summary, structure[name]], ignore_index=True) if name in structure else summary for name, summary in summaries.items()}


def read_task(survey: Path, pooling: Path, task: str) -> dict[str, pd.DataFrame]:
    """Each encoding's summary on `task`, the survey's models checked against `REFERENCES`."""
    summaries = {}
    for name, (roots, blocks) in encodings().items():
        folders = [task_folder(survey, pooling, root, task) for root in roots]
        summaries[name] = pair_summary(folders, blocks)
        if name in REFERENCES:
            reference = pd.read_parquet(survey / REFERENCES[name])
            reference = reference[reference["task"] == task].reset_index(drop=True)
            difference = archive.verify(summaries[name].drop(columns=["depth", "relative_depth"]).reset_index(drop=True), reference)
            print(f"{name} on {task}: summary matches the archive's to {difference:.1e}")
    return summaries


def full_states(summary: pd.DataFrame, sites: Sequence[str]) -> pd.DataFrame:
    """The full-width probes of the trained model on original inputs at `sites`, by depth."""
    trained = figures.headline(summary)
    return trained[(trained["family"] == "full") & trained["site"].isin(sites)].sort_values("depth")


def chosen_states(summaries: dict[str, pd.DataFrame], tuned: pd.DataFrame) -> pd.DataFrame:
    """Each trained model's intra-block and residual-stream states for the 2024 gold standard, chosen on validation
    from the survey's probes, checked against the states the tuned probes read."""
    rows = []
    for model in MODEL_COLORS:
        for kind, sites in (("inside", cross_model.INSIDE), ("stream", RESIDUAL)):
            state = figures._choose(full_states(summaries[model], sites))
            arm = tuned[(tuned["task"] == GOLD_2024) & (tuned["model"] == model) & (tuned["kind"] == kind)]
            assert {(state["site"], int(state["layer"]))} == set(zip(arm["site"], arm["layer"].astype(int), strict=True)), \
                f"{model}'s {kind} state {state['site']} {state['layer']} is not the tuned probes' {set(zip(arm['site'], arm['layer'], strict=True))}"
            rows.append({"model": model, "kind": kind, "site": state["site"], "layer": int(state["layer"]), "mcc": float(state["full"]),
                         "relative_depth": float(state["relative_depth"])})
    return pd.DataFrame(rows)


def tuned_inside(tuned: pd.DataFrame, chosen: pd.DataFrame) -> pd.DataFrame:
    """Each trained model's tuned MLP at its chosen state inside the block on the 2024 gold standard (test MCC, mean of
    three seeds), the value of its crimson bar in C."""
    rows = []
    for model in MODEL_COLORS:
        arm = tuned[(tuned["task"] == GOLD_2024) & (tuned["model"] == model) & (tuned["kind"] == "inside") & (tuned["probe"] == "mlp")]
        state = chosen[(chosen["model"] == model) & (chosen["kind"] == "inside")]
        assert len(arm) == 1 and len(state) == 1, f"{model} has {len(arm)} tuned MLPs and {len(state)} chosen states inside the block"
        assert (arm["site"].iloc[0], int(arm["layer"].iloc[0])) == (state["site"].iloc[0], int(state["layer"].iloc[0])), f"{model}'s tuned MLP reads another state"
        rows.append({"model": model, "kind": "inside", "site": state["site"].iloc[0], "layer": int(state["layer"].iloc[0]), "mcc": float(arm["test_mcc"].iloc[0])})
    return pd.DataFrame(rows)


def gains(differences: pd.DataFrame) -> pd.DataFrame:
    """D's paired differences on the 2024 gold standard, one row per model and comparison."""
    rows = []
    for model in MODEL_COLORS:
        for first, second, label in GAINS:
            match = differences[(differences["task"] == GOLD_2024) & (differences["first_model"] == model) & (differences["second_model"] == model)
                                & (differences["first"] == first) & (differences["second"] == second) & (differences["split_metric"] == GAIN_METRIC)]
            assert len(match) == 1, f"{model}: {len(match)} rows of {first} minus {second}"
            row = match.iloc[0]
            rows.append({"model": model, "comparison": label, "first": first, "second": second, "gain": float(row["mean_draw"]),
                         "low": float(row["low"]), "high": float(row["high"])})
    return pd.DataFrame(rows)


# -- drawing ----------------------------------------------------------------------------------------------------------


def inches(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """A box in inches from the main figure's lower left corner as figure fractions."""
    left, bottom, width, height = box
    return left / WIDTH, bottom / HEIGHT, width / WIDTH, height / HEIGHT


def published_level(axis: Axes, best_published: float) -> None:
    """The best published MCC as a dashed violet level, over the grid."""
    axis.axhline(best_published, color=PUBLISHED_COLOR, lw=0.8, ls=(0, (4, 2)), zorder=2)


def draw_depth(axis: Axes, summaries: dict[str, pd.DataFrame], chosen: pd.DataFrame, best_published: float) -> pd.DataFrame:
    """A, left: the survey's pair probe along the residual stream, the controls labeled at their right ends, and each
    model's best stream state as an open circle on its curve. Returns the curves' values."""
    random_style, onehot_style = CONTROLS["random init"], CONTROLS["one-hot"]
    published_level(axis, best_published)
    axis.text(0.005, best_published, "best published", color=PUBLISHED_COLOR, fontsize=LABEL_SIZE, va="bottom", ha="left", transform=axis.get_yaxis_transform())
    # random vectors sit at chance (C shows them), so A's axis starts just under the one-hot level
    onehot = full_states(summaries["OneHot-Protein"], ("embedding",))
    assert len(onehot) == 1, f"the one-hot encoding has {len(onehot)} states"
    onehot_level = float(onehot["full"].iloc[0])
    axis.axhline(onehot_level, color=onehot_style.color, ls=onehot_style.dash, lw=0.9, zorder=1)
    axis.text(1.0, onehot_level - 0.002, "one-hot", color=onehot_style.color, fontsize=LABEL_SIZE, va="top", ha="right")
    random_stream = full_states(summaries[RANDOM_INIT], RESIDUAL)
    axis.plot(random_stream["relative_depth"], random_stream["full"], color=random_style.color, ls=random_style.dash, lw=1.0, zorder=2)
    late = random_stream[random_stream["relative_depth"] >= 0.85]["full"]  # (late states,)
    axis.text(1.0, float(late.max()) + 0.002, "random init", color=random_style.color, fontsize=LABEL_SIZE, va="bottom", ha="right")
    curves = [random_stream.assign(model=RANDOM_INIT)]
    for model, color in MODEL_COLORS.items():
        stream = full_states(summaries[model], RESIDUAL)
        axis.plot(stream["relative_depth"], stream["full"], color=color, lw=1.1, zorder=3)
        best = chosen[(chosen["model"] == model) & (chosen["kind"] == "stream")].iloc[0]
        axis.scatter([best["relative_depth"]], [best["mcc"]], s=CIRCLE_SIZE, facecolors="white", edgecolors=color, linewidths=0.9, zorder=5)
        curves.append(stream.assign(model=model))
    plotted = np.concatenate([line.get_ydata() for line in axis.get_lines()])  # (points,)
    assert DEPTH_MCC[0] < plotted.min() and plotted.max() < DEPTH_MCC[1], f"A's values span {plotted.min():.3f} to {plotted.max():.3f}"
    axis.set_xlim(0, 1.0)
    axis.set_ylim(DEPTH_MCC)
    axis.set_yticks(DEPTH_TICKS)
    axis.set_xticks([0.0, 0.5, 1.0])
    axis.set_xlabel("relative depth", labelpad=2)
    axis.set_ylabel("test MCC")
    axis.grid(axis="y", color=GRID, lw=0.5)
    curves = pd.concat(curves, ignore_index=True)
    return curves[["model", "site", "layer", "relative_depth"]].assign(mcc=curves["full"], mark="curve")


def draw_best_states(axis: Axes, chosen: pd.DataFrame, tuned: pd.DataFrame, best_published: float) -> None:
    """A, right: per model, on A's MCC axis, the survey's probe at its best stream state (open circle) and at its best
    state inside the block (star), an arrow for the gain, and the tuned MLP at that state (crimson star); each column
    names its state inside the block."""
    published_level(axis, best_published)
    names = []
    for column, (model, color) in enumerate(MODEL_COLORS.items()):
        stream = chosen[(chosen["model"] == model) & (chosen["kind"] == "stream")].iloc[0]
        inside = chosen[(chosen["model"] == model) & (chosen["kind"] == "inside")].iloc[0]
        tuned_mcc = float(tuned.loc[tuned["model"] == model, "mcc"].iloc[0])
        x = column + LINEAR_OFFSET
        axis.annotate("", xy=(x, inside["mcc"]), xytext=(x, stream["mcc"]), zorder=4,
                      arrowprops={"arrowstyle": "-|>,head_length=0.3,head_width=0.15", "color": color, "lw": 0.9, "shrinkA": 2.6, "shrinkB": 4.2})
        axis.scatter([x], [stream["mcc"]], s=CIRCLE_SIZE, facecolors="white", edgecolors=color, linewidths=0.9, zorder=5)
        axis.scatter([x], [inside["mcc"]], s=STAR_SIZE, marker="*", color=color, edgecolors="white", linewidths=0.4, zorder=5)
        axis.plot([x, column + TUNED_OFFSET], [inside["mcc"], tuned_mcc], color=CRIMSON, lw=0.5, ls=(0, (1, 1.2)), zorder=3)
        axis.scatter([column + TUNED_OFFSET], [tuned_mcc], s=STAR_SIZE, marker="*", color=CRIMSON, edgecolors="white", linewidths=0.4, zorder=5)
        names.append(f"{site_math(inside['site'])}\n{int(inside['layer'])}")
    axis.set_xlim(-0.55, len(MODEL_COLORS) - 0.45)
    axis.set_xticks(range(len(MODEL_COLORS)), names, fontsize=LABEL_SIZE, linespacing=1.0)
    axis.tick_params(axis="x", length=0, pad=2)
    axis.tick_params(axis="y", labelleft=False, length=0)
    axis.grid(axis="y", color=GRID, lw=0.5)


def depth_key(figure: Figure) -> None:
    """A's key across its region: the models' curves and the marks of the best states."""
    handles = [Line2D([], [], color=color, lw=1.2) for color in MODEL_COLORS.values()]
    handles.append(Line2D([], [], ls="none", marker="o", ms=3.6, markerfacecolor="white", markeredgecolor=INK, markeredgewidth=0.8))
    handles.append(Line2D([], [], ls="none", marker="*", ms=6.5, color=INK, markeredgecolor="white", markeredgewidth=0.3))
    handles.append(Line2D([], [], ls="none", marker="*", ms=6.5, color=CRIMSON, markeredgecolor="white", markeredgewidth=0.3))
    labels = [*MODEL_COLORS, "best stream state", "best inside block", "tuned MLP"]
    left, bottom = KEYS["A"]
    figure.legend(handles, labels, loc="lower left", bbox_to_anchor=(left / WIDTH, bottom / HEIGHT), ncols=len(labels), frameon=False, fontsize=5.8,
                  handlelength=1.3, handletextpad=0.35, columnspacing=1.0, borderaxespad=0.0)


def draw_site_gaps(axis: Axes, summaries: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """B: each site's best probe, the structure stream's among them, minus the best stream probe, per model, sites
    ordered by their mean over models; the stream after each block, the best stream state of every model, is the zero
    line and has no row."""
    gaps = pd.DataFrame({model: figures.site_gaps(summaries[model], (GOLD_2024,)).loc[GOLD_2024] for model in MODEL_COLORS})  # (sites, models)
    assert STRUCTURE in gaps.index and gaps.notna().all().all(), "B lacks the structure stream or a site of a model"
    assert np.allclose(gaps.loc[STREAM_REFERENCE], 0.0, atol=1e-12), f"{STREAM_REFERENCE} is no longer every model's best stream state"
    gaps = gaps.drop(index=STREAM_REFERENCE)
    gaps = gaps.loc[gaps.mean(axis=1).sort_values(ascending=False).index]
    rows = np.arange(len(gaps))  # (sites,)
    figure_style.row_bands(axis, len(gaps))
    axis.axvline(0.0, color=INK_SECONDARY, lw=0.6, zorder=1)
    for offset, (model, color) in zip(SEED_OFFSETS, MODEL_COLORS.items(), strict=True):
        axis.scatter(gaps[model], rows + offset, s=8, color=color, edgecolors="white", linewidths=0.3, zorder=3)
    axis.set_yticks(rows, [site_math(site) for site in gaps.index], fontsize=LABEL_SIZE)
    axis.set_xticks([-0.04, 0.0, 0.04])
    axis.xaxis.set_major_formatter(FuncFormatter(lambda value, _: "0" if abs(value) < 1e-9 else f"{value:.2f}".replace("-", "−")))  # no "-0.00"
    axis.set_xlabel("state minus stream, MCC", labelpad=2)
    axis.grid(axis="x", color=GRID, lw=0.5)
    return gaps


def published_rows(tuned: pd.DataFrame) -> pd.DataFrame:
    """C's rows: the tuned MLP of each row of this study and each published method, from `published.table`, with each
    row's bar color (a control's own gray, a kind of state's color, or the published color)."""
    bars = published.table(tuned)
    bars = bars[bars["probe"].isin(("mlp", "published"))].reset_index(drop=True)
    assert bars["row"].is_unique, "a row of C holds more than one bar"
    colors = []
    for label, color in zip(bars["label"], bars["color"], strict=True):
        control = next((name for name in set(CONTROL_STYLES.values()) if label.startswith(name)), None)
        colors.append(CONTROLS[control].color if control and color != PUBLISHED_COLOR else color)
    return bars.assign(bar_color=colors)


def draw_bars(axis: Axes, values: pd.Series, rows: np.ndarray, colors: pd.Series, floor: float) -> None:
    """Horizontal bars from `floor` to each value, one per row; a value under the floor draws its bar leftward."""
    # values, rows, colors: (bars,) each
    axis.barh(rows, values - floor, left=floor, height=BAR_HEIGHT, color=colors, lw=0, zorder=2)


def auc_axis(axis: Axes, low: float, high: float, floor: float) -> None:
    """An axis's x range, ticks and grid; on an AUC axis, chance is a ticked line the bars start from."""
    axis.set_xlim(low, high)
    if floor == CHANCE:
        axis.axvline(CHANCE, color=MUTED, lw=0.6, zorder=1)
        axis.set_xticks(AUC_TICKS)
    axis.grid(axis="x", color=GRID, lw=0.5)


def draw_published(axes: Sequence[Axes], bars: pd.DataFrame) -> None:
    """C: one column per metric, bars from each axis's floor; the tuned MLP's mean over three seeds and published values
    as they are reported, neither with an interval, and the best published value of each metric as a dashed line."""
    rows = len(bars)
    for axis, (metric, (label, low, high, floor)) in zip(axes, C_METRICS.items(), strict=True):
        for row in range(rows - 2, -1, -2):
            axis.axhspan(row - 0.5, row + 0.5, color=ROW_BAND, lw=0, zorder=0)
        best = float(bars.loc[bars["probe"] == "published", metric].max())
        axis.axvline(best, color=PUBLISHED_COLOR, lw=0.7, ls=(0, (4, 2)), zorder=3)
        draw_bars(axis, bars[metric], bars["row"].to_numpy(), bars["bar_color"], floor)
        assert bars[metric].min() >= low and bars[metric].max() <= high, f"a {metric} value falls outside its axis"
        auc_axis(axis, low, high, floor)
        axis.set_ylim(-0.5, rows - 0.5)
        axis.set_xlabel(label, labelpad=2)
        axis.tick_params(axis="y", length=0)
    labels = bars.sort_values("row")
    top = rows - 1
    names = [name.replace(r"\mathrm", r"\mathbf") if row == top else name for row, name in zip(labels["row"], labels["label"], strict=True)]
    axes[0].set_yticks(labels["row"].tolist(), names, fontsize=LABEL_SIZE)
    axes[0].get_yticklabels()[top].set_fontweight("bold")
    for axis in axes[1:]:
        axis.tick_params(labelleft=False)


def state_key(figure: Figure) -> None:
    """C's key over its region: what each row of this study reads, and the published predictors."""
    kinds = {"inside": "best inside block", "stream": "best stream state", "last": "last hidden state"}
    handles = [Rectangle((0, 0), 1, 1, color=READ_STATE_COLORS[kind][0]) for kind in kinds]
    handles.append(Rectangle((0, 0), 1, 1, color=PUBLISHED_COLOR))
    left, bottom = KEYS["C"]
    figure.legend(handles, [*kinds.values(), "published"], loc="lower left", bbox_to_anchor=(left / WIDTH, bottom / HEIGHT), ncols=4, frameon=False, fontsize=5.8,
                  handlelength=1.0, handleheight=0.7, handletextpad=0.3, columnspacing=0.8, borderaxespad=0.0)


def draw_gains(axis: Axes, table: pd.DataFrame) -> None:
    """D: each comparison's paired gain in test ROC AUC per model, with its 95% interval."""
    figure_style.row_bands(axis, len(GAINS))
    axis.axvline(0.0, color=INK_SECONDARY, lw=0.6, zorder=1)
    for offset, (model, color) in zip(SEED_OFFSETS, MODEL_COLORS.items(), strict=True):
        rows = table[table["model"] == model].set_index("comparison").loc[[label for *_, label in GAINS]]
        interval_marks(axis, rows["gain"], np.arange(len(rows)) + offset, rows["low"], rows["high"], color, size=8)
    axis.set_yticks(np.arange(len(GAINS)), [label for *_, label in GAINS], fontsize=LABEL_SIZE)
    axis.set_xticks([0.0, 0.02, 0.04])
    axis.set_xlabel("gain in test ROC AUC", labelpad=2)
    axis.grid(axis="x", color=GRID, lw=0.5)


def model_key(figure: Figure) -> None:
    """B's and D's shared key over their region: the models' dots."""
    handles = [Line2D([], [], ls="none", marker="o", ms=3.4, color=color, markeredgecolor="white", markeredgewidth=0.3) for color in MODEL_COLORS.values()]
    left, bottom = KEYS["B"]
    figure.legend(handles, list(MODEL_COLORS), loc="lower left", bbox_to_anchor=(left / WIDTH, bottom / HEIGHT), ncols=len(handles), frameon=False, fontsize=5.8,
                  handlelength=0.8, handletextpad=0.25, columnspacing=0.9, borderaxespad=0.0)


def check_width(plt: object, path: Path) -> None:
    """Raise unless the saved figure fits the page's text width; print its size."""
    pixels_high, pixels_wide, _ = plt.imread(path).shape  # (pixels, pixels, channels)
    assert pixels_wide <= PAGE_WIDTH * 300 + 1, f"{path} is saved {pixels_wide / 300:.2f} in wide, past the {PAGE_WIDTH} in text width."
    print(f"{path}: {pixels_wide / 300:.2f} in by {pixels_high / 300:.2f} in")


def draw(survey: Path, pooling: Path, path: Path, values: Path) -> Path:
    """The figure at `path` and its plotted values at `values` (CSV)."""
    tuned = pd.read_parquet(survey / published.SUMMARY_FILE)
    summaries = joined(read_task(survey, pooling, GOLD_2024), read_structure(survey, GOLD_2024))
    chosen = chosen_states(summaries, tuned)
    tuned_states = tuned_inside(tuned, chosen)
    bars = published_rows(tuned)
    table_gains = gains(pd.read_parquet(survey / DIFFERENCES))

    plt = figures._pyplot()
    figure = plt.figure(figsize=(WIDTH, HEIGHT))
    depth_axis = figure.add_axes(inches(BOXES["A"]))
    best_axis = figure.add_axes(inches(BOXES["A best"]), sharey=depth_axis)
    gap_axis = figure.add_axes(inches(BOXES["B"]))
    left, bottom, width, height = BOXES["C"]
    column = (width - 2 * C_SPACE) / sum(C_WIDTHS)
    starts = left + np.cumsum([0.0, *C_WIDTHS[:-1]]) * column + np.arange(3) * C_SPACE  # (metrics,)
    metric_axes = [figure.add_axes(inches((start, bottom, share * column, height))) for start, share in zip(starts, C_WIDTHS, strict=True)]
    gain_axis = figure.add_axes(inches(BOXES["D"]))

    best_mcc = max(values[0] for values, _ in published.PUBLISHED.values())
    curves = draw_depth(depth_axis, summaries, chosen, best_mcc)
    draw_best_states(best_axis, chosen, tuned_states, best_mcc)
    depth_key(figure)
    gaps = draw_site_gaps(gap_axis, summaries)
    draw_published(metric_axes, bars)
    state_key(figure)
    draw_gains(gain_axis, table_gains)
    model_key(figure)
    for letter, (x, y) in LETTERS.items():
        figure.text(x / WIDTH, y / HEIGHT, letter, fontsize=9, fontweight="bold", ha="left", va="top", color=INK)

    values.parent.mkdir(parents=True, exist_ok=True)
    marks = {"inside": "best inside block", "stream": "best stream state"}
    plotted = [curves.assign(panel="A"), chosen.assign(panel="A", probe="survey linear", mark=chosen["kind"].map(marks)),
               tuned_states.assign(panel="A", probe="tuned MLP", mark="tuned MLP"),
               gaps.stack().rename("gap").reset_index().rename(columns={"level_0": "site", "level_1": "model"}).assign(panel="B"),
               bars.drop(columns=["color", *bars.filter(regex="_(low|high)$").columns]).assign(panel="C"), table_gains.assign(panel="D")]
    pd.concat(plotted, ignore_index=True).to_csv(values, index=False, float_format="%.4f")
    path = figures._save(figure, path)
    check_width(plt, path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--survey", type=Path, required=True, help="the survey archive's tables, as `archive.download` writes them")
    parser.add_argument("--pooling", type=Path, required=True, help="the pooling archive's tables, as `archive.download_pooling` writes them")
    parser.add_argument("--out", type=Path, required=True, help="the figure's PNG")
    parser.add_argument("--values", type=Path, required=True, help="the CSV of every value the figure plots")
    args = parser.parse_args()
    figure_style.install()  # the paper's names of states, checked as the figure is saved
    print(draw(args.survey, args.pooling, args.out, args.values))


if __name__ == "__main__":
    main()
