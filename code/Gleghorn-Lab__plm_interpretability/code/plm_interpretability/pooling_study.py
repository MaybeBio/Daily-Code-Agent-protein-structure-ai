"""The three-seed pooling and MLP study: pooling gains, their difference between probe kinds, and the Supplement's
figures and table, from the bootstrap tables of Protify's `protein-intervals` and `solve`.

    python -m plm_interpretability.pooling_study --tables TABLES --out OUT [--data CONCEPTS]

`TABLES` holds one folder per condition, a model and an input treatment such as `esmc300_norm`, each with
`intervals/<task>.parquet` and `solver/<task>.parquet`: every label's score on the whole test split (draw -1) and on
1,000 draws of its test proteins, shared by every model, seed and label and averaged over the three seeds draw by draw.
For each condition, task, reported state (`stream`, `any`) and metric:

- G(kind) = S(kind, mean and variance) - S(kind, mean alone), for `linear`, `mlp` and the converged `linear_solver`;
- the interaction, G(mlp) - G(linear), and G(mlp) - G(linear_solver);
- the MLP's lead over the linear probe at each pooling, and over the converged linear fit.

Each is reported on the whole split with the 2.5% and 97.5% quantiles of its draws, per task and as the mean over
tasks (taken draw by draw). Balanced MCC exists on the whole split alone and gets no interval. Beside each task: its
training-set size, and per condition the Spearman correlation of each per-task quantity with it.

Outputs: `gains.csv`, `size_correlations.csv`, `pooling_gains[_raw].png`, `mlp_lead[_raw].png` (the MLP's leads on mean
and variance, the main text's pooling), `mlp_lead_mean[_raw].png` (on the mean alone), `pooling_table.tex` and
`ranking_table.tex`. The `decomposition` tables, ESMC-600's bottleneck and quadratic probes, enter `gains.csv` as
their `score_*` rows.
"""

from __future__ import annotations

import argparse
import numpy as np
import pandas as pd

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from plm_interpretability.figure_style import GOLD, PROBE_COLORS, ROW_BAND, interval_marks


GAINS = {"linear": ("linear", "linear_mean"), "mlp": ("mlp", "mlp_mean"), "linear_solver": ("linear_solver", "linear_mean_solver")}
LEADS = {"mean_var": ("mlp", "linear"), "mean": ("mlp_mean", "linear_mean")}
MAIN = ("esmc300_norm", "any", "score")  # the condition, state and metric the hypothesis is decided on
MODELS = (("esmc300", "ESMC-300"), ("esmc600", "ESMC-600"), ("esmc6b", "ESMC-6B"), ("random300", "Random-init ESMC-300"))
TREATMENTS = (("norm", "unit-norm"), ("raw", "raw"))
SCORES = (("linear_mean", "Linear, mean"), ("linear", "Linear, mean and variance"), ("mlp_mean", "MLP, mean"), ("mlp", "MLP, mean and variance"))
# The kinds of concept the protein tasks fall in (Protify's `trends.CATEGORIES`, whose secondary-structure and residue
# kinds hold no protein task); each kind's mean over its tasks is reported beside the mean over all tasks.
KINDS = (("composition", ("prot_param",)), ("sorting and topology", ("localization",)),
         ("InterPro membership", ("interpro_family", "interpro_domain", "interpro_homologous_superfamily", "interpro_repeat",
                                  "interpro_conserved_site", "interpro_active_site", "interpro_binding_site")),
         ("function", ("go_mf", "go_bp", "go_cc", "metal_ion_binding")))
KIND_OF = {task: kind for kind, tasks in KINDS for task in tasks}


# -- gains --------------------------------------------------------------------------------------------------------


def label_draws(table: pd.DataFrame) -> dict[tuple[str, str, str, str], np.ndarray]:
    """(task, choice, metric, label) -> the value on the whole split followed by every draw: (B + 1,)."""
    ordered = table.sort_values("draw")
    return {key: group["value"].to_numpy(dtype=np.float64) for key, group in ordered.groupby(["task", "choice", "metric", "label"])}  # (B + 1,) each


def quantities(draws: dict[tuple[str, str, str, str], np.ndarray]) -> dict[tuple[str, str, str, str], np.ndarray]:
    """Every reported difference and score, keyed by (task, choice, metric, quantity), over the whole split and the draws."""
    found = {}  # draws: (B + 1,) each
    for task, choice, metric in {key[:3] for key in draws}:
        values = {key[3]: value for key, value in draws.items() if key[:3] == (task, choice, metric)}
        gains = {kind: values[full] - values[mean] for kind, (full, mean) in GAINS.items() if full in values and mean in values}
        for kind, gain in gains.items():
            found[(task, choice, metric, f"gain_{kind}")] = gain
        if "mlp" in gains and "linear" in gains:
            found[(task, choice, metric, "interaction")] = gains["mlp"] - gains["linear"]
        if "mlp" in gains and "linear_solver" in gains:
            found[(task, choice, metric, "interaction_solver")] = gains["mlp"] - gains["linear_solver"]
        for pooling, (mlp, linear) in LEADS.items():
            if mlp in values and linear in values:
                found[(task, choice, metric, f"mlp_lead_{pooling}")] = values[mlp] - values[linear]
            if mlp in values and f"{linear}_solver" in values:
                found[(task, choice, metric, "mlp_lead_solver" + ("" if pooling == "mean_var" else "_mean"))] = values[mlp] - values[f"{linear}_solver"]
        for label, value in values.items():
            found[(task, choice, metric, f"score_{label}")] = value
    return found  # (B + 1,) each


def summarize(values: np.ndarray) -> tuple[float, float, float]:
    """The whole split's value and the 95% percentile interval of the draws (NaN without draws)."""
    drawn = values[1:]  # values: (B + 1,)
    drawn = drawn[np.isfinite(drawn)]
    if not len(drawn):
        return float(values[0]), np.nan, np.nan
    low, high = np.percentile(drawn, [2.5, 97.5])
    return float(values[0]), float(low), float(high)


def condition_rows(name: str, found: dict[tuple[str, str, str, str], np.ndarray], sizes: dict[str, int]) -> list[dict[str, object]]:
    """One row per task and quantity, and one per quantity for the mean over tasks, taken draw by draw."""
    rows = []  # found: (B + 1,) each
    for (task, choice, metric, quantity), values in sorted(found.items()):
        estimate, low, high = summarize(values)
        rows.append({"condition": name, "task": task, "choice": choice, "metric": metric, "quantity": quantity,
                     "estimate": estimate, "low": low, "high": high, "train_size": sizes[task]})
    groups: dict[tuple[str, str, str, str], list[np.ndarray]] = {}
    for (task, choice, metric, quantity), values in found.items():
        groups.setdefault(("mean", choice, metric, quantity), []).append(values)
        groups.setdefault((f"kind:{KIND_OF[task]}", choice, metric, quantity), []).append(values)
    for (group, choice, metric, quantity), members in sorted(groups.items()):
        estimate, low, high = summarize(np.mean(np.stack(members), axis=0))
        rows.append({"condition": name, "task": group, "choice": choice, "metric": metric, "quantity": quantity,
                     "estimate": estimate, "low": low, "high": high, "train_size": np.nan, "tasks": len(members)})
    return rows


def read_condition(folder: Path) -> pd.DataFrame:
    """A condition's interval, solver and probe-variant (`decomposition`) tables as one long table (the solver's
    `_fits` records left out). The decomposition also rescores the labels it is compared with; those rows must equal
    the interval tables' and are kept once."""
    def read(kind: str) -> list[pd.DataFrame]:
        parts = [pd.read_parquet(path) for path in sorted((folder / kind).glob("*.parquet")) if not path.name.endswith("_fits.parquet")]
        return [part for part in parts if len(part)]

    parts = read("intervals") + read("solver")
    known = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["task", "choice", "metric", "label", "draw", "value"])
    for part in read("decomposition"):
        repeated = part["label"].isin(set(known["label"]))
        keys = ["task", "choice", "metric", "label", "draw"]
        shared = part[repeated].merge(known, on=keys, how="left", suffixes=("", "_known"), indicator=True)
        if (shared["_merge"] != "both").any() or not np.array_equal(shared["value"].to_numpy(), shared["value_known"].to_numpy(), equal_nan=True):
            raise ValueError(f"{folder.name}: the decomposition's rescored {sorted(set(part.loc[repeated, 'label']))} differ from the interval tables")
        parts.append(part[~repeated])
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def gains_table(tables: Path, sizes: dict[str, int]) -> pd.DataFrame:
    """Every condition folder under `tables`, as `condition_rows`."""
    rows = []
    for folder in sorted(path for path in tables.iterdir() if path.is_dir()):
        table = read_condition(folder)
        if len(table):
            rows += condition_rows(folder.name, quantities(label_draws(table)), sizes)
    return pd.DataFrame(rows)


def size_correlations(frame: pd.DataFrame) -> pd.DataFrame:
    """Spearman correlation of each per-task difference with training-set size, per condition, state and metric."""
    from scipy.stats import spearmanr

    rows = []
    per_task = frame[frame["train_size"].notna()]
    for (condition, choice, metric, quantity), group in per_task.groupby(["condition", "choice", "metric", "quantity"]):
        if quantity.startswith("score_") or len(group) < 4 or group["estimate"].nunique() < 2:
            continue
        rho, p = spearmanr(group["train_size"], group["estimate"])
        rows.append({"condition": condition, "choice": choice, "metric": metric, "quantity": quantity, "spearman": rho, "p": p, "tasks": len(group)})
    return pd.DataFrame(rows)


# -- the Supplement's table -----------------------------------------------------------------------------------------


def rows_of(gains: pd.DataFrame, condition: str, state: str, quantity: str, metric: str = "score") -> pd.DataFrame:
    return gains[(gains["condition"] == condition) & (gains["choice"] == state) & (gains["metric"] == metric) & (gains["quantity"] == quantity)]


def model_columns(gains: pd.DataFrame, treatment: str) -> list[tuple[str, str]]:
    """(condition, model name) of each model run under `treatment`, in the paper's order."""
    present = set(gains["condition"])
    return [(f"{stem}_{treatment}", name) for stem, name in MODELS if f"{stem}_{treatment}" in present]


def number(value: float, signed: bool) -> str:
    """Three decimals, with a typeset minus, and a plus too when the sign is the point."""
    text = f"{abs(value):.3f}"
    if value < 0 and text != "0.000":
        return f"$-${text}"
    return f"$+${text}" if signed else text


def cell(gains: pd.DataFrame, condition: str, state: str, quantity: str, signed: bool = False, metric: str = "score",
         interval: bool = True) -> str:
    """The mean over tasks, and in small type below it its 95% interval, `(low, high)`."""
    row = rows_of(gains, condition, state, quantity, metric)
    row = row[row["task"] == "mean"]
    if row.empty:
        return "--"
    estimate, low, high = row[["estimate", "low", "high"]].iloc[0]
    if not interval or np.isnan(low):
        return number(estimate, signed)
    return (rf"\begin{{tabular}}[t]{{@{{}}c@{{}}}}{number(estimate, signed)} \\ "
            rf"{{\scriptsize ({number(low, signed)}, {number(high, signed)})}}\end{{tabular}}")


def pooling_table(gains: pd.DataFrame, state: str) -> str:
    """Per model and input treatment: each probe's mean best score over the 13 tasks, then the gains of the variance
    for AdamW linear, converged linear and MLP probes and the difference of the MLP's and AdamW linear's, with their
    intervals."""
    lines = [r"\begin{tabular}{@{}l l c c c c c c c c@{}}", r"\toprule",
             r"Model & Tokens & \multicolumn{2}{c}{Linear} & \multicolumn{2}{c}{MLP} & \multicolumn{3}{c}{Gain of the variance} & Difference \\",
             r"\cmidrule(lr){3-4}\cmidrule(lr){5-6}\cmidrule(lr){7-9}",
             r" & & mean & mean, var. & mean & mean, var. & linear & converged & MLP & MLP $-$ linear \\", r"\midrule"]
    for treatment, treatment_name in TREATMENTS:
        for condition, name in model_columns(gains, treatment):
            cells = [cell(gains, condition, state, f"score_{label}", interval=False) for label, _ in SCORES]
            cells += [cell(gains, condition, state, f"gain_{kind}", signed=True) for kind in ("linear", "linear_solver", "mlp")]
            cells.append(cell(gains, condition, state, "interaction", signed=True))
            lines.append(f"{name} & {treatment_name} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


RANKING = (("roc_auc", "ROC AUC"), ("average_precision", "Average precision"), ("balanced_mcc", "Balanced MCC"))


def ranking_table(gains: pd.DataFrame, state: str, treatment: str = "norm") -> str:
    """Per model and probe kind: the mean over the classification tasks of each ranking metric under the mean alone
    and under mean and variance pooling, at each task's chosen state."""
    lines = [r"\begin{tabular}{@{}l l c c c c c c@{}}", r"\toprule",
             r"Model & Probe & " + " & ".join(rf"\multicolumn{{2}}{{c}}{{{name}}}" for _, name in RANKING) + r" \\",
             r"\cmidrule(lr){3-4}\cmidrule(lr){5-6}\cmidrule(lr){7-8}",
             r" & & " + " & ".join(["mean", "mean, var."] * len(RANKING)) + r" \\", r"\midrule"]
    for index, (condition, name) in enumerate(model_columns(gains, treatment)):
        if index:
            lines.append(r"\midrule")
        for row_index, (kind, kind_name) in enumerate((("linear", "linear"), ("mlp", "MLP"))):
            cells = []
            for metric, _ in RANKING:
                for label in (f"{kind}_mean", kind):
                    row = rows_of(gains, condition, state, f"score_{label}", metric)
                    row = row[row["task"] == "mean"]
                    cells.append(number(row["estimate"].iloc[0], signed=False) if len(row) else "--")
            lines.append(f"{'' if row_index else name} & {kind_name} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


# -- the Supplement's figures, drawn with Protify's helpers so they match the paper's others ---------------------------


def task_order(gains: pd.DataFrame) -> list[str]:
    """Protein tasks by training-set size, smallest first."""
    sizes = gains[gains["train_size"].notna()].groupby("task")["train_size"].first()
    return list(sizes.sort_values().index)


def interval_panel(axis: Any, gains: pd.DataFrame, condition: str, state: str, series: Sequence[tuple[str, str, str]], tasks: list[str],
                   sizes: pd.Series, labelled: bool) -> None:
    """One model's per-task quantities (rows) for each (quantity, legend, color) series, with intervals, and the mean
    over tasks in the last row."""
    from matplotlib.ticker import MaxNLocator
    from src.protify.interpretability.figures import GRID, INK_SECONDARY, SHORT_LABELS

    rows = tasks + ["mean"]
    positions = np.arange(len(rows), dtype=float)
    for position in positions[::2]:
        axis.axhspan(position - 0.5, position + 0.5, color=ROW_BAND, lw=0, zorder=0)
    axis.tick_params(axis="y", length=0)
    axis.xaxis.set_major_locator(MaxNLocator(4))
    axis.axhline(len(tasks) - 0.5, color=INK_SECONDARY, lw=0.5)
    axis.axvline(0.0, color=INK_SECONDARY, lw=0.7)
    axis.grid(axis="x", color=GRID, lw=0.5)
    offsets = np.linspace(-0.18, 0.18, len(series)) if len(series) > 1 else [0.0]
    for (quantity, label, color), offset in zip(series, offsets, strict=True):
        frame = rows_of(gains, condition, state, quantity).set_index("task").reindex(rows)
        y = positions + offset
        interval_marks(axis, frame["estimate"], y, frame["low"], frame["high"], color, size=11)
        axis.scatter([], [], s=11, color=color, label=label)
    if labelled:  # the panels share the y axis, so the first sets its ticks and the others only hide their labels
        axis.set_yticks(positions)
        axis.set_yticklabels([f"{SHORT_LABELS.get(task, task)} ({sizes[task]:,})" for task in tasks] + ["Mean over tasks"])
        axis.set_ylim(len(rows) - 0.5, -0.5)
    else:
        axis.tick_params(axis="y", labelleft=False)


def per_model_figure(gains: pd.DataFrame, state: str, treatment: str, series: Sequence[tuple[str, str, str]], xlabel: str, path: Path) -> Path:
    """One panel per model of `treatment`, tasks by training-set size, the series legend above the panels."""
    from src.protify.interpretability.figures import INK, _letter, _pyplot, _save, _tag

    plt = _pyplot()
    columns = model_columns(gains, treatment)
    tasks = task_order(gains)
    sizes = gains[gains["train_size"].notna()].groupby("task")["train_size"].first().astype(int)
    figure, axes = plt.subplots(1, len(columns), figsize=(7.2, 0.17 * len(tasks) + 1.0), sharey=True, squeeze=False)
    for index, (axis, (condition, name)) in enumerate(zip(axes[0], columns, strict=True)):
        interval_panel(axis, gains, condition, state, series, tasks, sizes, labelled=index == 0)
        _tag(axis, name)
        _letter(axis, "ABCDEFGH"[index], x=-0.04 if index else -0.55)
    figure.supxlabel(xlabel, fontsize=7, color=INK)
    # the legend sits outside the layout, so it widens no gap between the panels
    figure.tight_layout(w_pad=0.6, rect=(0, 0, 1, 1 - 0.3 / figure.get_figheight()))
    handles, labels = axes[0][0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 1.0), ncol=len(labels), frameon=False)
    return _save(figure, path)


def draw_pooling_gains(gains: pd.DataFrame, state: str, treatment: str, path: Path) -> Path:
    """Each task's gain of the variance for linear and MLP probes, per model."""
    series = (("gain_linear", "linear probe", PROBE_COLORS["linear"]), ("gain_mlp", "MLP probe", PROBE_COLORS["MLP"]))
    return per_model_figure(gains, state, treatment, series, "score under mean and variance pooling minus under the mean alone", path)


def draw_mlp_lead(gains: pd.DataFrame, state: str, treatment: str, path: Path, pooling: str = "mean_var") -> Path:
    """Each task's best MLP score minus its best linear score, AdamW and converged, per model, under `pooling`."""
    solver, name = ("mlp_lead_solver_mean", "the mean alone") if pooling == "mean" else ("mlp_lead_solver", "mean and variance pooling")
    series = ((f"mlp_lead_{pooling}", "MLP minus AdamW linear", PROBE_COLORS["linear"]), (solver, "MLP minus converged linear", GOLD))
    return per_model_figure(gains, state, treatment, series, f"best MLP score minus best linear score, {name}", path)


def task_sizes(concepts_folder: str | None) -> dict[str, int]:
    """Training proteins of every protein task, from the concept datasets (local, or the Hub's)."""
    from src.protify.interpretability.concepts import PROTEIN_TASKS, load_concept

    return {name: len(load_concept(name, local_dir=concepts_folder).splits["train"].sequences) for name in PROTEIN_TASKS}


def decision(gains: pd.DataFrame) -> pd.DataFrame:
    """The rows the hypothesis is decided on (`MAIN`), with the gains and differences beside them."""
    condition, choice, metric = MAIN
    return gains[(gains["condition"] == condition) & (gains["choice"] == choice) & (gains["metric"] == metric) & (gains["task"] == "mean")
                 & gains["quantity"].isin(["gain_linear", "gain_mlp", "gain_linear_solver", "interaction", "interaction_solver"])]


def write_all(tables: Path, out: Path, sizes: dict[str, int], state: str = "any") -> list[Path]:
    """Every output of the module from the condition folders under `tables`."""
    out.mkdir(parents=True, exist_ok=True)
    gains = gains_table(tables, sizes)
    written = [out / "gains.csv", out / "size_correlations.csv", out / "pooling_table.tex", out / "ranking_table.tex"]
    gains.to_csv(written[0], index=False)
    size_correlations(gains).to_csv(written[1], index=False)
    written[2].write_text(pooling_table(gains, state), encoding="utf-8", newline="\n")
    written[3].write_text(ranking_table(gains, state), encoding="utf-8", newline="\n")
    for treatment, _ in TREATMENTS:
        if model_columns(gains, treatment):
            suffix = "" if treatment == "norm" else "_raw"
            written.append(draw_pooling_gains(gains, state, treatment, out / f"pooling_gains{suffix}.png"))
            written.append(draw_mlp_lead(gains, state, treatment, out / f"mlp_lead{suffix}.png"))
            written.append(draw_mlp_lead(gains, state, treatment, out / f"mlp_lead_mean{suffix}.png", pooling="mean"))
    print(decision(gains).to_string(index=False))
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tables", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--data", default=None, help="a local copy of the concept datasets (default: the Hub's)")
    parser.add_argument("--state", default="any", choices=("any", "stream"), help="the state the figures and tables report")
    args = parser.parse_args()
    for path in write_all(args.tables, args.out, task_sizes(args.data), args.state):
        print(path)


if __name__ == "__main__":
    main()
