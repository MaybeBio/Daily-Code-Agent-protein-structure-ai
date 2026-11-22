"""What a gap between MLP and linear probes means: the main text's figure and the Supplement's decomposition and
geometry figures.

    python -m plm_interpretability.probe_gap --tables TABLES --roots ROOTS [--geometry GEOMETRY] --out OUT [--data CONCEPTS]

From the three-seed pooling study on unit-norm states:

- `TABLES/<condition>/{intervals,solver,decomposition}`: each probe's score at its chosen state on the whole test
  split and 1,000 shared bootstrap draws (`pooling_study.gains_table` reads them): the linear (AdamW and converged)
  and MLP probes of every model on both poolings, and ESMC-600's bottleneck (the MLP without its activation) and
  quadratic probes on the pooled mean, the decomposition's design;
- `ROOTS/<condition>_s<seed>/results/<label>`: every probe's scores at every state, for profiles along depth;
- `GEOMETRY/<condition>_s24895/{separability,geometry}.parquet`: Protify's `geometry` of ESMC-600's pooled means, the
  neighbor readout and the Bhattacharyya terms of every state, and the state's own shape.

The main text's figure reads mean and variance pooling, the main text's pooling, but for its geometry panel, which
follows InterPro membership along ESMC-600's stream on the pooled mean, the decomposition's design, under the linear
probe, the MLP without its activation (a linear map of the MLP's shape and training) and the MLP. Outputs:
`probe_gap.png` (main text), `probe_gap_states.csv` (every task and state: linear and MLP scores on both poolings,
ESMC-600's variants, the neighbor score and the Bhattacharyya terms), `decomposition.csv`, and the Supplement's
`decomposition.png`, `geometry_depth.png` and `separation_depth.png` (with the neighbor readout against the MLP).
"""

from __future__ import annotations

import argparse
import numpy as np
import pandas as pd

from pathlib import Path

from plm_interpretability.figure_style import CONTROLS, KIND_COLORS, KIND_TAGS, MODEL_COLORS, PROBE_COLORS, ROW_BAND, interval_marks, row_bands
from plm_interpretability.pooling_study import KIND_OF, KINDS, gains_table, rows_of, task_sizes


CONDITIONS = (("esmc300_norm", "ESMC-300"), ("esmc600_norm", "ESMC-600"), ("esmc6b_norm", "ESMC-6B"), ("random300_norm", "random-init ESMC-300"))
BLOCKS = {"esmc300_norm": 30, "esmc600_norm": 36, "esmc6b_norm": 80, "random300_norm": 30}
PROBES = (("score_linear", "linear, AdamW"), ("score_linear_solver", "linear, converged"), ("score_mlp", "MLP"))  # mean and variance
DECOMPOSITION = (("score_linear_mean", "linear, AdamW"), ("score_linear_mean_solver", "linear, converged"), ("score_quadratic_mean", "quadratic"),
                 ("score_bottleneck_mean", "MLP without activation"), ("score_mlp_mean", "MLP"))  # the pooled mean
LABELS = ("linear", "mlp", "linear_mean", "mlp_mean")  # each a results label and a column of the states table
VARIANTS = ("bottleneck_mean", "quadratic_mean")  # the decomposition's probes, columns where a condition has them
STREAM = ("embedding", "resid_post", "final_norm")
FOCUS = "esmc600_norm"  # the one model of the decomposition and the geometry, ESMC-600
CONDITION_COLORS = {condition: MODEL_COLORS.get(model, CONTROLS["random init"].color) for condition, model in CONDITIONS}
CONDITION_MARKS = {condition: "o" if model in MODEL_COLORS else CONTROLS["random init"].marker for condition, model in CONDITIONS}


def state_scores(roots: Path, condition: str, label: str) -> pd.DataFrame:
    """Every state's test score of `label` on the condition's three seed roots (mean over seeds), with the validation
    score, its site, layer and relative depth on the stream axis."""
    from src.protify.interpretability import figures

    replicates = [(path, label) for path in sorted(roots.glob(f"{condition}_s*")) if (path / "results" / label).exists()]
    summary = figures.summarize(figures.read_replicates([path for path, _ in replicates], label), figures.read_validation(replicates))
    summary = figures.headline(summary)
    summary = summary[summary["family"] == "full"].copy()
    blocks = BLOCKS[condition]
    summary["depth"] = [figures.depth(site, layer, blocks) for site, layer in zip(summary["site"], summary["layer"], strict=True)]
    summary["relative_depth"] = summary["depth"] / (blocks + 1)
    return summary[["task", "site", "layer", "depth", "relative_depth", "full", "validation_score"]].rename(columns={"full": "score"})


def states_table(roots: Path, geometry: Path | None) -> pd.DataFrame:
    """Every condition, task and state: the linear and MLP probes' scores on both poolings (`linear` and `mlp` on mean
    and variance, `linear_mean` and `mlp_mean` on the mean), with the linear probe's validation score on mean and
    variance, the decomposition's variants where they ran, and the geometry's neighbor score and Bhattacharyya terms
    where it ran."""
    frames = []
    for condition, model in CONDITIONS:
        if not any(roots.glob(f"{condition}_s*")):
            continue
        table = None
        for label in LABELS:
            scores = state_scores(roots, condition, label)
            if table is None:
                table = scores.rename(columns={"score": label})
            else:
                table = table.merge(scores[["task", "site", "layer", "score"]].rename(columns={"score": label}), on=["task", "site", "layer"])
        for label in VARIANTS:
            if any((path / "results" / label).exists() for path in roots.glob(f"{condition}_s*")):
                scores = state_scores(roots, condition, label)[["task", "site", "layer", "score"]].rename(columns={"score": label})
                table = table.merge(scores, on=["task", "site", "layer"], how="left")
        shapes = geometry / f"{condition}_s24895" / "separability.parquet" if geometry is not None else None
        if shapes is not None and shapes.exists():
            table = table.merge(pd.read_parquet(shapes), on=["task", "site", "layer"], how="left")
        frames.append(table.assign(condition=condition, model=model, kind=table["task"].map(KIND_OF)))
    table = pd.concat(frames, ignore_index=True)
    if "bhattacharyya_cov" in table:
        total = table["bhattacharyya_mean"] + table["bhattacharyya_cov"]
        table["covariance_share"] = table["bhattacharyya_cov"] / total.where(total > 0)
    return table


GROUPS = ["mean"] + [f"kind:{kind}" for kind, _ in KINDS]  # the mean over the 13 tasks, then each kind's


def neighbor_scores(states: pd.DataFrame, condition: str) -> pd.Series:
    """The neighbor readout's test score of each task at the state of the five sites where its validation score is
    highest: the probe-free counterpart of a probe's chosen-state score (empty where it did not run)."""
    if "knn_validation" not in states:
        return pd.Series(dtype=float)
    chosen = states[(states["condition"] == condition) & states["knn_validation"].notna()]
    return chosen.loc[chosen.groupby("task")["knn_validation"].idxmax()].set_index("task")["knn"]


def decomposition_table(gains: pd.DataFrame, states: pd.DataFrame, condition: str = FOCUS, state: str = "any") -> pd.DataFrame:
    """For the decomposition's model on the pooled mean, per group of tasks (all 13, then each kind): each probe's
    mean score at its chosen state with intervals, and the neighbor readout's (no interval)."""
    rows = []
    neighbors = neighbor_scores(states, condition)
    for group in GROUPS:
        for quantity, name in DECOMPOSITION:
            row = rows_of(gains, condition, state, quantity)
            row = row[row["task"] == group]
            if len(row):
                rows.append({"group": group, "probe": name, **row[["estimate", "low", "high"]].iloc[0].to_dict()})
        members = neighbors if group == "mean" else neighbors[neighbors.index.map(KIND_OF) == group.removeprefix("kind:")]
        if len(members):
            rows.append({"group": group, "probe": "neighbors", "estimate": float(members.mean()), "low": np.nan, "high": np.nan})
    return pd.DataFrame(rows)


def probe_gap_figure(gains: pd.DataFrame, states: pd.DataFrame, path: Path, state: str = "any") -> Path:
    """On mean and variance pooling: A, the mean over the 13 protein tasks of each probe's score at its chosen state, per
    model, with intervals. B, the MLP's lead over the converged linear fit per kind of concept. C, InterPro membership
    (each task's score as a share of its best stream score, averaged over the seven tasks) and composition along
    ESMC-600's residual stream under linear and MLP probes. On the pooled mean: D, InterPro membership along the same
    stream under the linear probe, the MLP without its activation and the MLP."""
    from matplotlib.lines import Line2D
    from matplotlib.ticker import MultipleLocator
    from src.protify.interpretability.figures import GRID, INK_SECONDARY, _letter, _pyplot, _save

    plt = _pyplot()
    has_variants = "bottleneck_mean" in states and states.loc[states["condition"] == FOCUS, "bottleneck_mean"].notna().any()
    figure, grid = plt.subplots(2, 2, figsize=(7.2, 3.7))
    axes = grid.ravel()
    if not has_variants:
        axes[3].remove()
    models = [(condition, model) for condition, model in CONDITIONS if (gains["condition"] == condition).any()]
    probes = [(quantity, name) for quantity, name in PROBES if (gains["quantity"] == quantity).any()]
    colors = {"linear, AdamW": PROBE_COLORS["linear"], "linear, converged": PROBE_COLORS["converged"], "MLP": PROBE_COLORS["MLP"]}
    offsets = np.linspace(-0.25, 0.25, len(probes))
    axis = axes[0]
    for x, (condition, _) in enumerate(models):
        for offset, (quantity, name) in zip(offsets, probes, strict=True):
            row = rows_of(gains, condition, state, quantity)
            row = row[row["task"] == "mean"]
            if len(row):
                estimate, low, high = row[["estimate", "low", "high"]].iloc[0]
                axis.errorbar(x + offset, estimate, yerr=[[estimate - low], [high - estimate]], fmt="o", ms=3, color=colors[name], lw=0.8,
                              label=name if x == 0 else None)
    axis.set_xticks(range(len(models)))
    axis.set_xticklabels([model.replace("random-init ESMC-300", "random init") for _, model in models], fontsize=6)
    axis.set_ylabel("mean score")
    top_key = {"frameon": False, "fontsize": 5.5, "loc": "lower center", "bbox_to_anchor": (0.5, 1.0), "handletextpad": 0.3, "columnspacing": 1.0}
    axis.legend(ncol=3, **top_key)
    axis = axes[1]
    kinds = [kind for kind, _ in KINDS]
    row_bands(axis, len(kinds))
    axis.axvline(0, color=INK_SECONDARY, lw=0.7, zorder=1)
    for index, (condition, _) in enumerate(models):
        leads = rows_of(gains, condition, state, "mlp_lead_solver").set_index("task").reindex([f"kind:{kind}" for kind in kinds])
        rows = np.arange(len(kinds)) + (index - (len(models) - 1) / 2) * 0.2  # (kinds,)
        interval_marks(axis, leads["estimate"], rows, leads["low"], leads["high"], CONDITION_COLORS[condition], size=12, marker=CONDITION_MARKS[condition])
    axis.set_yticks(range(len(kinds)))
    axis.set_yticklabels([KIND_TAGS.get(kind, kind) for kind in kinds], fontsize=6, linespacing=0.95)
    axis.xaxis.set_major_locator(MultipleLocator(0.05))
    axis.set_xlabel("MLP minus converged linear")
    key = [Line2D([], [], color=CONDITION_COLORS[condition], marker=CONDITION_MARKS[condition], ms=3, ls="none") for condition, _ in models]
    axis.legend(key,[model.replace("random-init ESMC-300", "random init") for _, model in models], ncol=len(models), **top_key)
    axis = axes[2]
    stream = states[(states["condition"] == FOCUS) & states["site"].isin(STREAM)]
    interpro = stream[stream["kind"] == "InterPro membership"]
    composition = stream[stream["task"] == "prot_param"].sort_values("relative_depth")
    for column, color, name in (("linear", PROBE_COLORS["linear"], "linear"), ("mlp", PROBE_COLORS["MLP"], "MLP")):
        best = interpro.groupby("task")[column].transform("max")
        profile = (interpro[column] / best).groupby(interpro["relative_depth"]).mean()
        axis.plot(profile.index, profile.values, color=color, lw=1.1, label=f"InterPro, {name}")
    for column, color, name in (("linear", PROBE_COLORS["linear"], "linear"), ("mlp", PROBE_COLORS["MLP"], "MLP")):
        axis.plot(composition["relative_depth"], composition[column] / composition[column].max(), color=color, ls=":", lw=1.0,
                  label=f"composition, {name}")
    axis.set_ylabel("relative score")
    axis.legend(frameon=False, fontsize=5.5, loc="lower right", ncol=2, handlelength=1.6, columnspacing=0.8)
    if has_variants:
        axis = axes[3]
        for column, color, name in (("linear_mean", PROBE_COLORS["linear"], "linear"), ("bottleneck_mean", PROBE_COLORS["no activation"], "MLP without activation"),
                                    ("mlp_mean", PROBE_COLORS["MLP"], "MLP")):
            best = interpro.groupby("task")[column].transform("max")
            profile = (interpro[column] / best).groupby(interpro["relative_depth"]).mean()
            axis.plot(profile.index, profile.values, color=color, lw=1.1, label=name)
        axis.set_ylabel("relative score")
        axis.set_ylim(axes[2].get_ylim())
        axis.legend(frameon=False, fontsize=5.5, loc="lower right", handlelength=1.6)
    for axis in axes[2:4] if has_variants else axes[2:3]:
        axis.set_xlabel(f"relative depth ({dict(CONDITIONS)[FOCUS]})")
        axis.set_xlim(0, 1)
    for letter, axis in zip("ABCD", axes if has_variants else axes[:3], strict=False):
        axis.grid(axis="x" if axis is axes[1] else "both", color=GRID, lw=0.5)
        axis.set_axisbelow(True)
        axis.tick_params(labelsize=6)
        _letter(axis, letter)
    figure.tight_layout(w_pad=1.0, h_pad=1.2)
    return _save(figure, path)


def decomposition_figure(table: pd.DataFrame, path: Path) -> Path:
    """ESMC-600 on the pooled mean, per group of tasks (all 13, then each kind): each probe's mean score at its chosen
    state with intervals, from the AdamW linear probe through the converged fit, the quadratic probe and the MLP
    without its activation to the MLP, and the neighbor readout."""
    from src.protify.interpretability.figures import GRID, INK_SECONDARY, _pyplot, _save

    plt = _pyplot()
    colors = {"linear, AdamW": PROBE_COLORS["linear"], "linear, converged": PROBE_COLORS["converged"], "quadratic": PROBE_COLORS["quadratic"],
              "MLP without activation": PROBE_COLORS["no activation"], "MLP": PROBE_COLORS["MLP"], "neighbors": INK_SECONDARY}  # the MLP without activation is a linear map of rank 256 at most
    groups = [group for group in GROUPS if (table["group"] == group).any()]
    probes = [probe for probe in colors if (table["probe"] == probe).any()]
    figure, axis = plt.subplots(figsize=(7.2, 2.3))
    offsets = np.linspace(-0.3, 0.3, len(probes))
    for x in range(0, len(groups), 2):
        axis.axvspan(x - 0.5, x + 0.5, color=ROW_BAND, lw=0, zorder=0)
    axis.set_xlim(-0.5, len(groups) - 0.5)
    axis.tick_params(axis="x", length=0)
    for x, group in enumerate(groups):
        for offset, probe in zip(offsets, probes, strict=True):
            row = table[(table["group"] == group) & (table["probe"] == probe)]
            if not len(row):
                continue
            estimate, low, high = row[["estimate", "low", "high"]].iloc[0]
            error = [[estimate - low], [high - estimate]] if np.isfinite(low) else None
            axis.errorbar(x + offset, estimate, yerr=error, fmt="D" if probe == "neighbors" else "o", ms=3, mfc="none" if probe == "neighbors" else None,
                          color=colors[probe], lw=0.8, label=probe if x == 0 else None)
    axis.set_xticks(range(len(groups)))
    axis.set_xticklabels(["all 13 tasks" if group == "mean" else group.removeprefix("kind:") for group in groups], fontsize=6)
    axis.set_ylabel("mean best score, pooled mean")
    axis.grid(axis="y", color=GRID, lw=0.5)
    axis.set_axisbelow(True)
    axis.legend(frameon=False, fontsize=5.5, ncol=len(probes), loc="lower center", bbox_to_anchor=(0.5, 1.0), handletextpad=0.3, columnspacing=1.0)
    figure.tight_layout()
    return _save(figure, path)


def geometry_depth_figure(geometry: Path, path: Path) -> Path:
    """The shape of every pooled mean state along the residual stream, per model: effective rank, the first
    component's share of variance, anisotropy and the largest coordinate's share of the squared norm. The TwoNN
    dimension stays in `geometry.parquet` only: near-duplicate homologs set the nearest-neighbor ratios it reads."""
    from src.protify.interpretability import figures
    from src.protify.interpretability.figures import GRID, _letter, _pyplot, _save, _tag

    plt = _pyplot()
    metrics =(("effective_rank", "effective rank"), ("first_component_share", "first component's share"), ("anisotropy", "anisotropy"),
               ("top_dimension_share", "largest coordinate's share"))
    figure, axes = plt.subplots(1, len(metrics), figsize=(7.2, 1.9))
    for condition, model in CONDITIONS:
        file = geometry / f"{condition}_s24895" / "geometry.parquet"
        if not file.exists():
            continue
        table = pd.read_parquet(file)
        table = table[table["site"].isin(STREAM)].copy()
        table["relative_depth"] = [figures.depth(site, layer, BLOCKS[condition]) / (BLOCKS[condition] + 1) for site, layer in zip(table["site"], table["layer"], strict=True)]
        table = table.sort_values("relative_depth")
        for axis, (metric, name) in zip(axes, metrics, strict=True):
            axis.plot(table["relative_depth"], table[metric], color=CONDITION_COLORS[condition], lw=1.0, label=model)
            _tag(axis, name)
    for letter, axis in zip("ABCD", axes, strict=True):
        axis.set_xlabel("relative depth")
        axis.set_xticks([0.0, 0.5, 1.0])
        axis.grid(color=GRID, lw=0.5)
        _letter(axis, letter, x=-0.02)
    if len(axes[0].get_lines()) > 1:
        axes[0].legend(frameon=False, fontsize=5)
    figure.tight_layout(w_pad=0.5)
    return _save(figure, path)


def separation_depth_figure(states: pd.DataFrame, path: Path, condition: str = FOCUS) -> Path:
    """A, along the residual stream, per kind of classification concept: the Bhattacharyya mean term (solid) and
    covariance term (dashed), averaged over the kind's tasks. At every state of the five sites and classification
    task, the MLP's lead over the linear probe on the pooled mean against B, the covariance term's share, and C, the
    neighbor readout's lead over the same linear probe."""
    from src.protify.interpretability.figures import GRID, INK_SECONDARY, _letter, _pyplot, _save, _tag

    plt = _pyplot()
    figure, axes = plt.subplots(1, 3, figsize=(7.2, 2.3))
    kinds = [kind for kind, _ in KINDS if kind != "composition"]
    chosen = states[(states["condition"] == condition) & states["bhattacharyya_cov"].notna()]
    stream = chosen[chosen["site"].isin(STREAM)]
    for kind in kinds:
        terms = stream[stream["kind"] == kind].groupby("relative_depth")[["bhattacharyya_mean", "bhattacharyya_cov"]].mean()
        axes[0].plot(terms.index, terms["bhattacharyya_mean"], color=KIND_COLORS[kind], lw=1.0, label=f"{kind}, means")
        axes[0].plot(terms.index, terms["bhattacharyya_cov"], color=KIND_COLORS[kind], lw=1.0, ls="--", label=f"{kind}, covariances")
        points = chosen[chosen["kind"] == kind]
        axes[1].scatter(points["covariance_share"], points["mlp_mean"] - points["linear_mean"], s=3, alpha=0.5, color=KIND_COLORS[kind], lw=0, label=kind)
        axes[2].scatter(points["knn"] - points["linear_mean"], points["mlp_mean"] - points["linear_mean"], s=3, alpha=0.5, color=KIND_COLORS[kind], lw=0, label=kind)
    _tag(axes[0], dict(CONDITIONS)[condition])
    axes[0].set_xlabel("relative depth")
    axes[0].set_ylabel("Bhattacharyya term")
    axes[0].set_yscale("log")
    colors = [plt.Line2D([], [], color=KIND_COLORS[kind], lw=0, marker="o", ms=3) for kind in kinds]
    styles = [plt.Line2D([], [], color=INK_SECONDARY, lw=1.0), plt.Line2D([], [], color=INK_SECONDARY, lw=1.0, ls="--")]
    axes[1].axhline(0, color=INK_SECONDARY, lw=0.7)
    axes[1].set_xlabel("covariance share of the Bhattacharyya distance")
    axes[1].set_ylabel("MLP minus linear (pooled mean)")
    axes[2].axhline(0, color=INK_SECONDARY, lw=0.7)
    axes[2].axvline(0, color=INK_SECONDARY, lw=0.7)
    axes[2].set_xlabel("neighbors minus linear")
    axes[2].set_ylabel("MLP minus linear (pooled mean)")
    for letter, axis in zip("ABC", axes, strict=True):
        axis.grid(color=GRID, lw=0.5)
        axis.set_axisbelow(True)
        _letter(axis, letter)
    figure.tight_layout(w_pad=1.0, rect=(0, 0, 1, 1 - 0.2 / figure.get_figheight()))
    figure.legend([*colors, *styles], [*kinds, "mean term", "covariance term"], loc="upper center",
                  bbox_to_anchor=(0.5, 1.0), ncol=len(kinds) + 2, frameon=False, fontsize=6)
    return _save(figure, path)


def write_all(tables: Path, roots: Path, geometry: Path | None, out: Path, sizes: dict[str, int]) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    gains = gains_table(tables, sizes)
    states = states_table(roots, geometry)
    decomposition = decomposition_table(gains, states)
    written = [out / "probe_gap_states.csv", out / "decomposition.csv"]
    states.to_csv(written[0], index=False, float_format="%.5f")
    decomposition.to_csv(written[1], index=False, float_format="%.5f")
    written.append(probe_gap_figure(gains, states, out / "probe_gap.png"))
    if len(decomposition):
        written.append(decomposition_figure(decomposition, out / "decomposition.png"))
    if geometry is not None and "bhattacharyya_cov" in states:
        written.append(geometry_depth_figure(geometry, out / "geometry_depth.png"))
        written.append(separation_depth_figure(states, out / "separation_depth.png"))
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tables", type=Path, required=True)
    parser.add_argument("--roots", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--data", default=None, help="a local copy of the concept datasets (default: the Hub's)")
    args = parser.parse_args()
    for path in write_all(args.tables, args.roots, args.geometry, args.out, task_sizes(args.data)):
        print(path)


if __name__ == "__main__":
    main()
