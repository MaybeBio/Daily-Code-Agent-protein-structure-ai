"""Probe correctness against ESMC's familiarity with the protein: the main text's figure and the Supplement's.

    python -m plm_interpretability.familiarity --source FAMILIARITY --out OUT

`FAMILIARITY/<encoder>/` holds what experiment 2026-10-20_esmc_ppll_familiarity wrote for each encoder (`esmc300`,
`esmc600`, `esmc6b`, `random300`, `onehot`): `predictions.parquet`, one row per task, seed and test protein with the
probe's per-protein score at the task's chosen stream state, the protein's length and its label prevalence;
`checks.parquet`; and, for the trained models, `ppll.parquet`, each test sequence's unmasked pseudo log likelihood
(PPLL, the mean log probability of its observed residues). A protein's score is averaged over the three seeds.

The experiment fixed its statistics before launch. Per task and encoder, Spearman's rho between the trained model's
PPLL and the per-protein score; per task, rho between PPLL and the trained model's gain over each control (its score
minus the control's), raw and partial on length and label prevalence; 95% intervals over 1,000 bootstrap draws of the
test proteins. A kind of concept reads as familiarity-driven when the median over its tasks of the partial rho between
PPLL and the gain over the randomly initialized model exceeds 0.1 and at least half of those tasks' intervals exclude
zero. Outputs: `familiarity_proteins.csv`, `familiarity_correlations.csv`, `familiarity_kinds.csv`,
`familiarity_quintiles.csv`, `familiarity_models.csv`, and the figures `familiarity.png` (main text) and
`familiarity_models.png` (Supplement).

Symbols: n test proteins of a task; B bootstrap draws; k covariates.
"""

from __future__ import annotations

import argparse
import numpy as np
import pandas as pd

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING
from scipy.stats import rankdata

from plm_interpretability.figure_style import CONTROLS as CONTROL_STYLES, MODEL_COLORS, interval_marks, kind_tag, row_bands
from plm_interpretability.pooling_study import KIND_OF, KINDS


if TYPE_CHECKING:
    from matplotlib.axes import Axes


TRAINED = (("esmc300", "ESMC-300"), ("esmc600", "ESMC-600"), ("esmc6b", "ESMC-6B"))
CONTROLS = (("random300", "random-init ESMC-300"), ("onehot", "one-hot"))
FOCUS = "esmc300"  # the model the controls figure compares with its random-init twin and the one-hot encoding
DRAWS = 1000
DRAW_SEED = 0
QUINTILES = 5
THRESHOLD = 0.1  # a kind reads as familiarity-driven above this median partial rho (fixed before launch)
TASKS = tuple(task for _, tasks in KINDS for task in tasks)


# -- tables ----------------------------------------------------------------------------------------------------------


def protein_scores(source: Path, encoder: str) -> pd.DataFrame:
    """One encoder's per-protein scores averaged over its seeds: task, protein, id, sequence, length, prevalence,
    score and the number of seeds."""
    table = pd.read_parquet(source / encoder / "predictions.parquet", columns=["task", "seed", "protein", "id", "sequence", "length", "prevalence", "score"])
    keys = ["task", "protein", "id", "sequence", "length", "prevalence"]
    grouped = table.groupby(keys, dropna=False)["score"].agg(score="mean", seeds="count").reset_index()
    if grouped["seeds"].nunique() != 1:
        raise ValueError(f"{encoder}: proteins carry different numbers of seeds, {sorted(grouped['seeds'].unique())}.")
    return grouped


def protein_ppll(source: Path, encoder: str) -> pd.Series:
    """Each test sequence's PPLL under a trained model, indexed by sequence."""
    table = pd.read_parquet(source / encoder / "ppll.parquet", columns=["sequence", "ppll"])
    return table.set_index("sequence")["ppll"]


def proteins_table(source: Path, trained: str = FOCUS) -> pd.DataFrame:
    """Per task and test protein: the trained model's PPLL and score, each control's score, and the gains over them."""
    table = protein_scores(source, trained).rename(columns={"score": "score_trained"}).drop(columns="seeds")
    for control, _ in CONTROLS:
        scores = protein_scores(source, control)[["task", "protein", "sequence", "score"]].rename(columns={"score": f"score_{control}"})
        table = table.merge(scores, on=["task", "protein", "sequence"], how="left", validate="one_to_one")
        table[f"gain_{control}"] = table["score_trained"] - table[f"score_{control}"]
    table["ppll"] = table["sequence"].map(protein_ppll(source, trained))
    if table["ppll"].isna().any():
        raise ValueError(f"{int(table['ppll'].isna().sum())} test proteins have no PPLL under {trained}.")
    table["kind"] = table["task"].map(KIND_OF)
    return table


# -- statistics ------------------------------------------------------------------------------------------------------


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman's rho with average ranks for ties; NaN when either side is constant."""
    # x, y: (n,)
    return _pearson(rankdata(x), rankdata(y))


def partial_spearman(x: np.ndarray, y: np.ndarray, covariates: np.ndarray) -> float:
    """Spearman's rho of x and y after removing from both ranks a least-squares fit on the covariates' ranks."""
    # x, y: (n,); covariates: (n, k)
    design = np.column_stack([np.ones(len(x)), *(rankdata(column) for column in covariates.T)])  # (n, k + 1)
    residual_x = _residual(design, rankdata(x))  # (n,)
    residual_y = _residual(design, rankdata(y))  # (n,)
    return _pearson(residual_x, residual_y)


def _residual(design: np.ndarray, values: np.ndarray) -> np.ndarray:
    # design: (n, k + 1); values: (n,)
    coefficients, *_ = np.linalg.lstsq(design, values, rcond=None)  # (k + 1,)
    return values - design @ coefficients  # (n,)


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    # x, y: (n,)
    x, y = x - x.mean(), y - y.mean()
    denominator = np.sqrt((x * x).sum() * (y * y).sum())
    return float((x * y).sum() / denominator) if denominator > 0 else float("nan")


def bootstrap(statistic: Callable[[np.ndarray], float], proteins: int, draws: int = DRAWS, seed: int = DRAW_SEED) -> tuple[float, float]:
    """The 2.5th and 97.5th percentiles of `statistic` over draws of the proteins with replacement; `statistic` takes
    the drawn row indices."""
    # statistic: (n,) row indices -> a float
    rng = np.random.default_rng(seed)
    values = np.array([statistic(rng.integers(0, proteins, proteins)) for _ in range(draws)])  # (B,)
    values = values[np.isfinite(values)]
    return float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))


def covariates_of(rows: pd.DataFrame) -> np.ndarray:
    """Length and, where the task has one, label prevalence: (n, k)."""
    columns = [rows["length"].to_numpy(dtype=np.float64)]
    if rows["prevalence"].notna().all():
        columns.append(rows["prevalence"].to_numpy(dtype=np.float64))
    return np.column_stack(columns)  # (n, k)


def correlations(proteins: pd.DataFrame, draws: int = DRAWS) -> pd.DataFrame:
    """Per task, each quantity's rho with PPLL and its interval: the score of the trained model and of each control, and
    the gain over each control, raw and partial on length and prevalence."""
    rows = []
    for task in [task for task in TASKS if task in set(proteins["task"])]:
        table = proteins[proteins["task"] == task].reset_index(drop=True)
        ppll = table["ppll"].to_numpy()  # (n,)
        covariates = covariates_of(table)  # (n, k)
        quantities = [("score", "trained"), *[("score", control) for control, _ in CONTROLS], *[("gain", control) for control, _ in CONTROLS]]
        for quantity, encoder in quantities:
            values = table[f"{quantity}_{encoder}"].to_numpy()  # (n,)
            for partial in (False, True):
                if partial and quantity == "score" and encoder != "trained":
                    continue

                def statistic(rows: np.ndarray, values: np.ndarray = values, partial: bool = partial) -> float:
                    # rows: (n,) drawn indices; values: (n,)
                    if partial:
                        return partial_spearman(ppll[rows], values[rows], covariates[rows])
                    return spearman(ppll[rows], values[rows])

                every = np.arange(len(table))
                low, high = bootstrap(statistic, len(table), draws)
                rows.append({"task": task, "kind": KIND_OF[task], "quantity": quantity, "encoder": encoder, "partial": partial,
                             "rho": statistic(every), "low": low, "high": high, "proteins": len(table)})
    return pd.DataFrame(rows)


def kind_readings(correlation: pd.DataFrame) -> pd.DataFrame:
    """The reading fixed before launch, per kind of concept: the median over its tasks of the partial rho between PPLL
    and the gain over the randomly initialized model, the share of tasks whose interval excludes zero, and whether the
    kind reads as familiarity-driven; beside it the same for the one-hot gain, and the median rho of PPLL with each
    encoder's score."""
    rows = []
    for kind, tasks in KINDS:
        present = correlation[correlation["task"].isin(tasks)]
        if present.empty:
            continue
        row: dict[str, object] = {"kind": kind, "tasks": present["task"].nunique()}
        for control, _ in CONTROLS:
            gain = present[(present["quantity"] == "gain") & (present["encoder"] == control) & present["partial"]]
            excluded = ((gain["low"] > 0) | (gain["high"] < 0)).mean()
            row[f"median_partial_gain_{control}"] = float(gain["rho"].median())
            row[f"share_excluding_zero_{control}"] = float(excluded)
            row[f"familiarity_driven_{control}"] = bool(gain["rho"].median() > THRESHOLD and excluded >= 0.5)
        for encoder in ("trained", *(control for control, _ in CONTROLS)):
            score = present[(present["quantity"] == "score") & (present["encoder"] == encoder) & ~present["partial"]]
            row[f"median_score_rho_{encoder}"] = float(score["rho"].median())
        rows.append(row)
    return pd.DataFrame(rows)


def quintile_table(proteins: pd.DataFrame) -> pd.DataFrame:
    """Per task and PPLL quintile (1 the least predictable fifth of its test proteins), each encoder's mean score."""
    frames = []
    for task, table in proteins.groupby("task", sort=False):
        ranks = rankdata(table["ppll"], method="ordinal")  # (n,)
        quintile = np.ceil(ranks * QUINTILES / len(table)).astype(int)  # (n,)
        columns = ["score_trained", *[f"score_{control}" for control, _ in CONTROLS]]
        means = table[columns].groupby(quintile).mean()
        means["ppll"] = table["ppll"].groupby(quintile).median()
        means["proteins"] = table["ppll"].groupby(quintile).size()
        frames.append(means.rename_axis("quintile").reset_index().assign(task=task, kind=KIND_OF[task]))
    return pd.concat(frames, ignore_index=True)


def model_correlations(source: Path, draws: int = DRAWS) -> pd.DataFrame:
    """Per trained model and task: rho between the model's own PPLL and its own per-protein score, with its interval,
    raw and partial; and rho between the model's PPLL and ESMC-300's."""
    rows = []
    reference = protein_ppll(source, FOCUS) if (source / FOCUS / "ppll.parquet").exists() else None
    for encoder, model in TRAINED:
        if not (source / encoder / "ppll.parquet").exists():
            continue
        table = protein_scores(source, encoder)
        own = protein_ppll(source, encoder)
        table["ppll"] = table["sequence"].map(own)
        for task in [task for task in TASKS if task in set(table["task"])]:
            rows_of_task = table[table["task"] == task].reset_index(drop=True)
            ppll, score = rows_of_task["ppll"].to_numpy(), rows_of_task["score"].to_numpy()  # (n,) each
            covariates = covariates_of(rows_of_task)  # (n, k)
            for partial in (False, True):

                def statistic(rows: np.ndarray, partial: bool = partial) -> float:
                    # rows: (n,) drawn indices
                    if partial:
                        return partial_spearman(ppll[rows], score[rows], covariates[rows])
                    return spearman(ppll[rows], score[rows])

                low, high = bootstrap(statistic, len(rows_of_task), draws)
                agreement = spearman(ppll, rows_of_task["sequence"].map(reference).to_numpy()) if reference is not None else float("nan")
                rows.append({"model": model, "task": task, "kind": KIND_OF[task], "partial": partial, "rho": statistic(np.arange(len(rows_of_task))),
                             "low": low, "high": high, "ppll_rho_with_esmc300": agreement, "mean_score": float(score.mean())})
    return pd.DataFrame(rows)


# -- figures ---------------------------------------------------------------------------------------------------------


def _task_rows(tasks: Sequence[str]) -> list[str]:
    return [task for task in TASKS if task in set(tasks)]


def _kind_rules(axis: Axes, rows: list[str], named: bool = False) -> None:
    """Rules between kinds of concept on a task axis; with `named`, each kind named at the right."""
    from src.protify.interpretability.figures import MUTED

    start = 0
    for kind, tasks in KINDS:
        members = [row for row in rows if row in tasks]
        if not members:
            continue
        stop = start + len(members)
        if start > 0:
            axis.axhline(start - 0.5, color=MUTED, lw=0.5, zorder=1)
        if named:
            kind_tag(axis, 1 - (start + stop) / 2 / len(rows), kind, axis.transAxes)
        start = stop


def _task_axis(axis: Axes, rows: list[str]) -> None:
    """A panel with one row per task: bands behind the rows and vertical gridlines."""
    from src.protify.interpretability.figures import GRID, SHORT_LABELS

    row_bands(axis, len(rows))
    axis.set_yticks(range(len(rows)))
    axis.set_yticklabels([SHORT_LABELS.get(task, task) for task in rows], fontsize=6)
    axis.grid(axis="x", color=GRID, lw=0.5)
    axis.set_axisbelow(True)
    axis.tick_params(labelsize=6)


def familiarity_figure(correlation: pd.DataFrame, quintiles: pd.DataFrame, path: Path) -> Path:
    """A: per task, rho between ESMC-300's PPLL and each encoder's per-protein score. B: per task, the partial rho
    between PPLL and ESMC-300's gain over each control, in the control's color, with 95% intervals. C to F: per kind,
    each encoder's mean score by PPLL quintile, averaged over the kind's tasks. One legend, at the top."""
    from matplotlib.lines import Line2D
    from src.protify.interpretability.figures import GRID, INK_SECONDARY, _letter, _pyplot, _save, _tag

    plt = _pyplot()
    rows = _task_rows(correlation["task"])
    positions = {task: index for index, task in enumerate(rows)}
    colors = {"trained": MODEL_COLORS["ESMC-300"], "random300": CONTROL_STYLES["random init"].color, "onehot": CONTROL_STYLES["one-hot"].color}
    marks = {"trained": "o", "random300": CONTROL_STYLES["random init"].marker, "onehot": CONTROL_STYLES["one-hot"].marker}
    names = {"trained": "ESMC-300", "random300": "random init", "onehot": "one-hot"}
    figure = plt.figure(figsize=(7.2, 4.8))
    top = figure.add_gridspec(1, 2, left=0.125, right=0.88, top=0.905, bottom=0.415, wspace=0.05)
    left, right = figure.add_subplot(top[0, 0]), figure.add_subplot(top[0, 1])
    offsets = {"trained": -0.25, "random300": 0.0, "onehot": 0.25}
    for encoder in ("trained", "random300", "onehot"):
        table = correlation[(correlation["quantity"] == "score") & (correlation["encoder"] == encoder) & ~correlation["partial"]]
        y = np.array([positions[task] for task in table["task"]]) + offsets[encoder]
        interval_marks(left, table["rho"], y, table["low"], table["high"], colors[encoder], marker=marks[encoder])
    for control, offset in (("random300", -0.15), ("onehot", 0.15)):
        table = correlation[(correlation["quantity"] == "gain") & (correlation["encoder"] == control) & correlation["partial"]]
        y = np.array([positions[task] for task in table["task"]]) + offset
        interval_marks(right, table["rho"], y, table["low"], table["high"], colors[control], marker=marks[control])
    for axis, label in ((left, r"$\rho$, PPLL with score"), (right, r"partial $\rho$, PPLL with gain over control")):
        _task_axis(axis, rows)
        axis.axvline(0, color=INK_SECONDARY, lw=0.6, zorder=1)
        axis.set_xlabel(label, fontsize=6.5)
    right.set_yticklabels([])
    _kind_rules(left, rows)
    _kind_rules(right, rows, named=True)
    _letter(left, "A", x=-0.27)
    _letter(right, "B", x=-0.02)
    kinds = [kind for kind, tasks in KINDS if set(tasks) & set(quintiles["task"])]
    bottom = figure.add_gridspec(1, len(kinds), left=0.055, right=0.995, top=0.285, bottom=0.07, wspace=0.2)
    axes = [figure.add_subplot(bottom[0, index]) for index in range(len(kinds))]
    for index, (axis, kind) in enumerate(zip(axes, kinds, strict=True)):
        table = quintiles[quintiles["kind"] == kind].groupby("quintile")[["score_trained", "score_random300", "score_onehot"]].mean()
        for column, encoder in (("score_trained", "trained"), ("score_random300", "random300"), ("score_onehot", "onehot")):
            axis.plot(table.index, table[column], marker=marks[encoder], ms=2.5, lw=1.0, color=colors[encoder])
        axis.set_xticks(range(1, QUINTILES + 1))
        axis.set_xlabel("PPLL quintile", fontsize=6.5)
        if index == 0:
            axis.set_ylabel("mean score", fontsize=6.5)
        axis.grid(color=GRID, lw=0.5)
        axis.tick_params(labelsize=6)
        _tag(axis, kind)
        _letter(axis, "CDEF"[index], x=-0.02)
    key = [Line2D([], [], color=colors[encoder], marker=marks[encoder], ms=3, lw=1.0) for encoder in ("trained", "random300", "onehot")]
    figure.legend(key, [names[encoder] for encoder in ("trained", "random300", "onehot")], loc="upper center", bbox_to_anchor=(0.5, 1.0),
                  ncol=3, fontsize=6.5, frameon=False)
    return _save(figure, path)


def models_figure(models: pd.DataFrame, proteins: pd.DataFrame, pplls: dict[str, pd.Series], path: Path) -> Path:
    """A: per task, rho between each trained model's own PPLL and its own per-protein score, with 95% intervals. B: the
    distribution of ESMC-300's PPLL over each task's test proteins. C: ESMC-300's PPLL against length over every test
    protein. D: the larger models' PPLL against ESMC-300's over every test sequence (`pplls`, by model name). One legend,
    at the top."""
    from matplotlib.lines import Line2D
    from src.protify.interpretability.figures import GRID, INK_SECONDARY, _letter, _pyplot, _save

    plt = _pyplot()
    rows = _task_rows(models["task"])
    positions = {task: index for index, task in enumerate(rows)}
    figure, axes = plt.subplots(1, 4, figsize=(7.2, 2.75), gridspec_kw={"width_ratios": [1.3, 0.85, 1.0, 1.0], "wspace": 0.42, "left": 0.125, "right": 0.995,
                                                                        "top": 0.824, "bottom": 0.14})  # 0.1 in under the legend, clear of the letters
    for index, (_, model) in enumerate(TRAINED):
        table = models[(models["model"] == model) & ~models["partial"]]
        if table.empty:
            continue
        y = np.array([positions[task] for task in table["task"]]) + (index - 1) * 0.25
        interval_marks(axes[0], table["rho"], y, table["low"], table["high"], MODEL_COLORS[model])
    distributions = [proteins[proteins["task"] == task]["ppll"].to_numpy() for task in rows]
    parts = axes[1].violinplot(distributions, positions=range(len(rows)), vert=False, widths=0.8, showmedians=True, showextrema=False)
    for body in parts["bodies"]:
        body.set_facecolor(MODEL_COLORS["ESMC-300"])
        body.set_alpha(0.35)
    parts["cmedians"].set_color(MODEL_COLORS["ESMC-300"])
    for axis in axes[:2]:
        _task_axis(axis, rows)
    axes[0].axvline(0, color=INK_SECONDARY, lw=0.6, zorder=1)
    axes[0].set_xlabel(r"$\rho$, own PPLL with own score", fontsize=6.5)
    axes[0].set_xticks([-0.4, -0.2, 0.0, 0.2])
    axes[1].set_xlabel("ESMC-300 PPLL", fontsize=6.5)
    axes[1].set_yticklabels([])
    unique = proteins.drop_duplicates("sequence")
    axes[2].scatter(unique["length"], unique["ppll"], s=1.5, alpha=0.25, color=MODEL_COLORS["ESMC-300"], lw=0, rasterized=True)
    axes[2].set_xscale("log")
    axes[2].set_xlabel("length (residues)", fontsize=6.5)
    axes[2].set_ylabel("ESMC-300 PPLL", fontsize=6.5)
    axes[2].grid(color=GRID, lw=0.5)
    axes[2].set_axisbelow(True)
    axes[2].tick_params(labelsize=6)
    key = [Line2D([], [], color=MODEL_COLORS[model], marker="o", ms=3, ls="none") for _, model in TRAINED]
    figure.legend(key, [model for _, model in TRAINED], loc="upper center", bbox_to_anchor=(0.5, 1.0), ncol=3, fontsize=6.5, frameon=False)
    reference = pplls.get("ESMC-300")
    for _, model in TRAINED[1:]:
        if reference is None or model not in pplls:
            continue
        shared = reference.index.intersection(pplls[model].index)
        axes[3].scatter(reference[shared], pplls[model][shared], s=0.7, alpha=0.1, color=MODEL_COLORS[model], lw=0, rasterized=True)  # thousands of points: a light wash
    axes[3].plot([-4, 0], [-4, 0], color=INK_SECONDARY, lw=0.6, zorder=0)
    axes[3].text(-3.3, -3.95, "y = x", fontsize=5.5, color=INK_SECONDARY)
    axes[3].set_xlabel("ESMC-300 PPLL", fontsize=6.5)
    axes[3].set_ylabel("larger model's PPLL", fontsize=6.5)
    axes[3].grid(color=GRID, lw=0.5)
    axes[3].set_axisbelow(True)
    axes[3].tick_params(labelsize=6)
    for axis, letter, x in zip(axes, "ABCD", (-0.42, -0.04, -0.25, -0.25), strict=True):
        _letter(axis, letter, x=x)
    return _save(figure, path)


def write_all(source: Path, out: Path, draws: int = DRAWS) -> list[Path]:
    """Every table and figure of the familiarity analysis from the experiment's outputs under `source`."""
    out.mkdir(parents=True, exist_ok=True)
    proteins = proteins_table(source)
    correlation = correlations(proteins, draws)
    readings = kind_readings(correlation)
    quintiles = quintile_table(proteins)
    models = model_correlations(source, draws)
    written = []
    for name, table in (("proteins", proteins.drop(columns="sequence")), ("correlations", correlation), ("kinds", readings),
                        ("quintiles", quintiles), ("models", models)):
        path = out / f"familiarity_{name}.csv"
        table.to_csv(path, index=False, lineterminator="\n")
        written.append(path)
    written.append(familiarity_figure(correlation, quintiles, out / "familiarity.png"))
    pplls = {model: protein_ppll(source, encoder) for encoder, model in TRAINED if (source / encoder / "ppll.parquet").exists()}
    written.append(models_figure(models, proteins, pplls, out / "familiarity_models.png"))
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="the experiment's outputs, one folder per encoder")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--draws", type=int, default=DRAWS)
    args = parser.parse_args()
    for path in write_all(args.source, args.out, args.draws):
        print(path)


if __name__ == "__main__":
    main()
