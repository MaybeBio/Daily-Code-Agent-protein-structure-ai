"""Figures of the native-unit study, drawn from a run's outputs: version two's Figures 2 to 6 and its supplementary
figures (the depth atlas, and E13's residue-level readings).

A panel function draws one panel from tidy tables onto an axes; a loader reads a run directory into those tables,
the same score tables and decisions the hypotheses read (`experiments.score_table`, `decisions.json`); a figure
function lays panels out. Color follows the basis (`BASIS_COLORS`): native red, residual violet and SAE yellow, a set
that passes the dataviz validator's every-pair color-vision checks on white, with yellow below 3:1 contrast, so every
basis is also named on its axis. Rotations and random initialization are neutral grays, as controls are in version one
(`plm_interpretability.figure_style.CONTROLS`), and a panel that compares models colors them as version one does
(`MODEL_COLORS`). No figure carries a title, panels are lettered, and figures are saved as PNG at 300 dpi
(`save_figure`).

Symbols: l residues of one protein; a units of one basis; k copies of a basis (the rotations).
"""

from __future__ import annotations

import json
import re
import numpy as np
import pandas as pd

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import experiments, missing, payoff
from .bootstrap import Interval, median_interval
from .dictionary import THRESHOLDS
from .exemplars import POLE_NAMES
from .experiments import MODEL_NAMES, site_name
from .hypotheses import CONCEPT_KINDS, finite_values, input_kinds
from .rotation_search import RECOVERY_REFERENCE
from .steering import ARMS
from ..figure_style import CONTROLS, MODEL_COLORS, ROW_BAND


if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure


NATIVE, RESIDUAL, SAE = "#e34948", "#6250d6", "#eda100"
ROTATION, RANDOM_INIT = "#9aa3ad", CONTROLS["random init"].color
SEARCHED_ROTATION = "#525c68"  # the rotations the sparsity search found: the rotations' gray, darker, on square marks
OPPOSITE, LEAK = "#44546a", "#b8bfc6"  # a neuron's other main pole and its leaks, beside the pole a track is about
INK, MUTED = "#2b2b2b", "#6c7680"
BASIS_COLORS = {"native": NATIVE, "sign": NATIVE, "residual": RESIDUAL, "sae": SAE, "rotation": ROTATION,
                "random init": RANDOM_INIT}
WIDTH = 7.2  # inches, a two-column page
DPI = 300
STYLE = {
    "font.size": 7, "axes.labelsize": 7, "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "legend.fontsize": 6.5,
    "axes.linewidth": 0.6, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6, "axes.spines.top": False, "axes.spines.right": False,
    "lines.linewidth": 1.0, "legend.frameon": False,
}
CARRIER_ROLES = ("top1", "top2", "top3", "drawn")
ROLE_NAMES = {"top1": "strongest carrier", "top2": "second", "top3": "third", "drawn": "drawn at random"}
LABEL_WIDTH, LABEL_LINES = 22, 2  # a row label wraps at this many characters and is cut with an ellipsis past two lines
HEADROOM = 1.3  # a track's y axis rises this far above its exemplar's highest pole, so its accession clears the data
METRIC_NAMES = {"margin": "margin over the best\nunrelated term", "held_out_auroc": "held-out AUROC\nof the best term"}
# E1's arms drawn as marks, by arm: name, color and marker; the rotated intermediates (`mlp_rotation<seed>`) as a range.
E1_ARMS = {"residual": ("residual dimensions", RESIDUAL, "o"), "residual_poles": ("residual poles", RESIDUAL, "D"),
           "mlp_poles": ("intermediate poles", NATIVE, "o"), "mlp_positive": ("positive poles alone", NATIVE, "^"),
           "shuffled_mlp_poles": ("permuted-weight control", RANDOM_INIT, "s"), "sae": ("InterPLM's SAE", SAE, "o")}
E1_ROTATED = "mlp_rotation"
SWEEP_MARKERS = dict(zip(experiments.SWEEP_PASS_K, ("v", "o", "^"), strict=True))
# Figure 3B's bases, by the name `site_tables` gives them: name, color and whether the marker is hollow.
DOMINANCE_STYLES = {"native": ("native, gate-tagged", NATIVE, False), "sign": ("native, sign-only", NATIVE, True),
                    "rotation": ("ten rotations", ROTATION, False), "residual": ("residual stream", RESIDUAL, False),
                    "sae": ("SAE", SAE, False)}
# E7d's arms: name, color and dash. Sienna and deep cyan, with version one's random-vectors gray for the random control,
# pass the dataviz validator's color-vision (11.9) and normal-vision (18.0) checks on white (2026-11-06); the gray fails
# only the chroma floor, as every control's gray does, and is dashed and named in the key.
STEERING_STYLES = dict(zip(ARMS, (("along the manifold", "#a0522d", "-"), ("straight line", "#0e93ad", "-"),
                                  ("random direction", CONTROLS["random vectors"].color, (0, (3, 2)))), strict=True))
# E8's SAEs at each site in `experiments.dictionary_sites` order: the role a figure names and its marker.
DICTIONARY_ROLES = (("MLP-output SAE", "o"), ("size-matched residual SAE", "s"), ("larger residual SAE", "^"))
COMPARISON_NAMES = {"extremes: native - rotated": "maxima and minima,\nnative − rotated",
                    "mean: native - rotated": "means,\nnative − rotated",
                    "native extremes - SAE": "native maxima and\nminima − SAE latents"}


@dataclass(frozen=True)
class BasisGroup:
    """One basis in a panel: its axis label, its units' values, its color, whether its marker is hollow (the sign-only
    reading), its marker, and its units' values after a correction, drawn as a second marker when given."""

    label: str
    values: np.ndarray  # (a,)
    color: str
    hollow: bool = False
    after: np.ndarray | None = None  # (a,)
    marker: str = "o"


@dataclass(frozen=True)
class RangeGroup:
    """Several copies of one basis in a panel, the rotations: the range of their medians as a bar and the median of
    those medians as a dot, before and, when given, after a correction."""

    label: str
    medians: tuple[float, ...]  # (k,)
    color: str
    after: tuple[float, ...] | None = None  # (k,)


@dataclass(frozen=True)
class SiteTables:
    """One hypothesis site's per-pole score tables: the bases H1 to H5 compare and the random-init control's."""

    native: pd.DataFrame
    sign: pd.DataFrame
    residual: pd.DataFrame
    sae: pd.DataFrame
    rotated: tuple[pd.DataFrame, ...]
    random_init: pd.DataFrame


def new_figure(height: float, width: float = WIDTH) -> Figure:
    """An empty figure in the study's style, drawn without pyplot so no window or global state is involved."""
    import matplotlib

    from matplotlib.figure import Figure

    with matplotlib.rc_context(STYLE):
        return Figure(figsize=(width, height), dpi=DPI)


def save_figure(figure: Figure, path: Path) -> Path:
    """Save as PNG at 300 dpi, refusing a figure title: the caption carries it."""
    if figure.get_suptitle():
        raise ValueError("A figure carries no title; the caption does.")
    if path.suffix != ".png":
        raise ValueError(f"Figures are PNG, not {path.suffix}.")
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=DPI, facecolor="white")
    return path


def letter(ax: Axes, text: str) -> None:
    """The panel's letter at its top left, outside the data."""
    ax.text(-0.02, 1.02, text, transform=ax.transAxes, ha="right", va="bottom", fontsize=9, fontweight="bold", color=INK)


def _interval_bar(ax: Axes, x: float, interval: Interval, color: str, *, hollow: bool = False, marker: str = "o") -> None:
    ax.errorbar(x, interval.estimate, yerr=[[interval.estimate - interval.low], [interval.high - interval.estimate]],
                fmt=marker, color=color, markerfacecolor="white" if hollow else color, markeredgecolor=color,
                markeredgewidth=0.9, markersize=4.5, elinewidth=1.0, capsize=0, zorder=3)


def _range_bar(ax: Axes, x: float, medians: Sequence[float], color: str, *, hollow: bool = False, marker: str = "o") -> None:
    """Copies of a basis: the range of their medians as a bar, the median of those medians as a dot."""
    ax.vlines(x, min(medians), max(medians), color=color, linewidth=2.2, alpha=0.7, zorder=2)
    ax.plot(x, float(np.median(medians)), marker=marker, color=color, markerfacecolor="white" if hollow else color,
            markeredgecolor=color, markeredgewidth=0.9, markersize=4.5, linestyle="none", zorder=3)


def _dodge(count: int, width: float) -> np.ndarray:
    """Offsets that spread `count` marks evenly across `width`, centered on their row or column."""
    return np.linspace(-width / 2, width / 2, count) if count > 1 else np.zeros(1)  # (count,)


def _grid(ax: Axes, axis: str = "y") -> None:
    ax.grid(True, axis=axis, color=ROW_BAND, linewidth=0.6)
    ax.set_axisbelow(True)


def _key(ax: Axes, handles: Sequence[object], *, right: bool = False, columns: int | None = None, lift: float = 1.0) -> None:
    """A key in one or more rows just above an axes, or `lift` axes heights up, from its left edge or its right."""
    ax.legend(handles=handles, loc="lower right" if right else "lower left", bbox_to_anchor=(1.0 if right else 0.0, lift),
              ncol=columns or len(handles), handletextpad=0.5, columnspacing=1.0, borderaxespad=0.2)


def _band_handle() -> object:
    from matplotlib.patches import Patch

    return Patch(facecolor=ROTATION, alpha=0.35, edgecolor="none", label="range of the ten rotations' medians")


def basis_panel(ax: Axes, groups: Sequence[BasisGroup | RangeGroup], *, ylabel: str,
                band: tuple[float, float] | None = None, band_label: str | None = "ten rotations") -> None:
    """Each basis's units as a pale violin with its median and 95% unit-bootstrap interval, or a basis's copies as the
    range of their medians; the rotations' medians as a gray band, named in place unless `band_label` is None (a key
    names it); a corrected median, when given, as a hollow diamond beside the first, joined to it."""
    import matplotlib

    with matplotlib.rc_context(STYLE):
        if band is not None:
            ax.axhspan(band[0], band[1], color=ROTATION, alpha=0.35, linewidth=0, zorder=0)
            if band_label is not None:
                ax.text(len(groups) - 0.45, band[1], band_label, ha="right", va="bottom", color=MUTED, fontsize=6)
        for position, group in enumerate(groups):
            if isinstance(group, RangeGroup):
                _range_bar(ax, position, group.medians, group.color)
                if group.after is not None:
                    ax.plot([position, position + 0.3], [np.median(group.medians), np.median(group.after)],
                            color=group.color, linewidth=0.6, zorder=2)
                    _range_bar(ax, position + 0.3, group.after, group.color, hollow=True, marker="D")
                continue
            values = np.asarray(group.values, dtype=np.float64)
            values = values[np.isfinite(values)]  # (a_finite,)
            if values.size > 1:
                body = ax.violinplot(values, positions=[position], widths=0.7, showextrema=False)["bodies"][0]
                body.set_facecolor(group.color)
                body.set_edgecolor("none")
                body.set_alpha(0.12)
            before = median_interval(values)
            _interval_bar(ax, position, before, group.color, hollow=group.hollow, marker=group.marker)
            if group.after is not None:
                after = median_interval(group.after)
                ax.plot([position, position + 0.3], [before.estimate, after.estimate], color=group.color, linewidth=0.6,
                        zorder=2)
                _interval_bar(ax, position + 0.3, after, group.color, hollow=True, marker="D")
        ax.set_xticks(range(len(groups)), [group.label for group in groups])
        ax.set_xlim(-0.6, len(groups) - 0.4)
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", length=0)
        _grid(ax)


def interval_panel(ax: Axes, rows: Sequence[tuple[str, Mapping[str, float], str]], *, xlabel: str,
                   reference: float | None = None) -> None:
    """One row per estimate, a dot and its interval (`estimate`, `low`, `high`), with a reference line."""
    import matplotlib

    with matplotlib.rc_context(STYLE):
        if reference is not None:
            ax.axvline(reference, color=MUTED, linewidth=0.6, zorder=0)
        for position, (_, estimate, color) in enumerate(rows):
            ax.errorbar(estimate["estimate"], position,
                        xerr=[[estimate["estimate"] - estimate["low"]], [estimate["high"] - estimate["estimate"]]],
                        fmt="o", color=color, markersize=4.5, elinewidth=1.0, capsize=0, zorder=3)
        ax.set_yticks(range(len(rows)), [name for name, _, _ in rows])
        ax.set_ylim(len(rows) - 0.5, -0.5)
        ax.set_xlabel(xlabel)
        ax.tick_params(axis="y", length=0)


def track_panel(ax: Axes, track: pd.DataFrame, *, ymax: float, leaks: bool = True) -> None:
    """One exemplar on one carrier: its pole along the residues, its neuron's opposite pole and leaks beneath, the
    term's residues shaded and the pole's threshold dashed. `leaks=False` leaves the closed gate's small output out."""
    # track: one carrier's rows of `exemplars.track_table`
    import matplotlib

    track = track.sort_values("position")
    position = track["position"].to_numpy()  # (l,)
    own = str(track["own"].iloc[0])
    opposite = "negative" if own == "positive" else "positive"
    with matplotlib.rc_context(STYLE):
        inside = track["in_term"].to_numpy()  # (l,)
        starts = np.flatnonzero(inside & ~np.r_[False, inside[:-1]])  # (runs,)
        ends = np.flatnonzero(inside & ~np.r_[inside[1:], False])  # (runs,)
        # A run narrower than 1.5% of the carrier, such as a single site, widens about its center so it stays visible.
        least = 0.015 * len(position)
        for start, end in zip(starts, ends, strict=True):
            left, right = position[start] - 0.5, position[end] + 0.5
            pad = max(0.0, (least - (right - left)) / 2)
            ax.axvspan(left - pad, right + pad, color=ROW_BAND, linewidth=0, zorder=0)
        if leaks:
            leak = track["leak_positive"].to_numpy() + track["leak_negative"].to_numpy()  # (l,), one of them is zero
            ax.plot(position, leak, color=LEAK, linewidth=0.5, zorder=1)
        ax.plot(position, track[opposite].to_numpy(), color=OPPOSITE, linewidth=0.5, zorder=2)
        ax.plot(position, track[own].to_numpy(), color=NATIVE, linewidth=0.9, zorder=3)
        ax.axhline(float(track["threshold"].iloc[0]), color=MUTED, linewidth=0.5, linestyle=(0, (3, 2)), zorder=1)
        ax.set_xlim(position[0] - 0.5, position[-1] + 0.5)
        ax.set_ylim(0, ymax)
        ax.tick_params(length=2)
        ax.locator_params(axis="x", nbins=3)
        ax.locator_params(axis="y", nbins=2)


def _wrapped(label: str) -> str:
    """A term's label in at most `LABEL_LINES` lines of `LABEL_WIDTH` characters, cut with an ellipsis past them."""
    import textwrap

    lines = textwrap.wrap(label, LABEL_WIDTH)
    if len(lines) > LABEL_LINES:
        lines = lines[:LABEL_LINES]
        lines[-1] = lines[-1][:LABEL_WIDTH - 1] + "…"
    return "\n".join(lines)


def _track_legend(ax: Axes) -> None:
    """The key to the tracks, in an otherwise empty axes."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    handles = [Line2D([], [], color=NATIVE, linewidth=0.9, label="the exemplar's pole"),
               Line2D([], [], color=OPPOSITE, linewidth=0.5, label="its neuron's other pole"),
               Line2D([], [], color=LEAK, linewidth=0.5, label="its neuron's leak poles"),
               Line2D([], [], color=MUTED, linewidth=0.5, linestyle=(0, (3, 2)), label="rate-matched threshold"),
               Patch(facecolor=ROW_BAND, edgecolor="none", label="the term's residues")]
    ax.set_axis_off()
    ax.legend(handles=handles, loc="center left", frameon=False, handlelength=2.2)


def figure_4(root: Path) -> Figure:
    """Figure 4: (A) every exemplar drawn by the frozen rule on its strongest three carriers and one drawn at random;
    (B) curated substitutions as near misses, labeled poles against placebos."""
    import matplotlib

    tracks = pd.read_parquet(root / "exemplars" / "tracks.parquet")
    summary = json.loads((root / "causal" / "near_misses" / "receipt.json").read_text(encoding="utf-8"))["summary"]
    labels = pd.read_parquet(root / "inputs" / "terms.parquet").set_index("token")["label"]
    exemplar_ids = sorted(int(exemplar) for exemplar in tracks["exemplar"].unique())
    count = len(exemplar_ids)
    with matplotlib.rc_context(STYLE):
        height = 0.85 * count + 1.8
        figure = new_figure(height)
        # The bottom margin is fixed in inches, so panel B's axis label fits however many exemplars have carriers; the
        # row of height 0.3 is a spacer before B.
        grid = figure.add_gridspec(count + 2, len(CARRIER_ROLES), hspace=0.55, wspace=0.18, left=0.22, right=0.98,
                                   top=0.95, bottom=0.45 / height, height_ratios=[1] * count + [0.3, 1.2])
        first = None
        for row, exemplar in enumerate(exemplar_ids):
            chosen = tracks[tracks["exemplar"] == exemplar]
            highest = float(np.nanmax(chosen[list(POLE_NAMES)].to_numpy()))
            for column, role in enumerate(CARRIER_ROLES):
                ax = figure.add_subplot(grid[row, column])
                carrier = chosen[chosen["role"] == role]
                if carrier.empty:
                    ax.set_axis_off()
                    continue
                track_panel(ax, carrier, ymax=HEADROOM * highest if highest > 0 else 1.0)
                ax.text(0.98, 0.97, str(carrier["accession"].iloc[0]), transform=ax.transAxes, ha="right", va="top",
                        fontsize=5.5, color=MUTED)
                if row == 0:
                    ax.set_title(ROLE_NAMES[role], fontsize=6.5, color=INK, pad=3)
                if column == 0:
                    term = int(chosen["term"].iloc[0])
                    ax.set_ylabel(f"{chosen['kind'].iloc[0]}\n{_wrapped(str(labels.get(term, term)))}", fontsize=6,
                                  rotation=0, ha="right", va="center", labelpad=6)
                if row == count - 1:
                    ax.set_xlabel("residue", fontsize=6)
                first = first if first is not None else ax
        if first is not None:
            letter(first, "A")
        near = figure.add_subplot(grid[count + 1, :2])
        rows = [("labeled poles", summary["labeled_auroc"], NATIVE), ("placebo poles", summary["placebo_auroc"], ROTATION)]
        interval_panel(near, rows, xlabel="AUROC, loss of function against no effect", reference=0.5)
        letter(near, "B")
        _track_legend(figure.add_subplot(grid[count + 1, 2:]))
    return figure


# -- loaders: a run directory read into the tables the panels draw ---------------------------------------------------


def _median(values: pd.Series) -> float:
    return float(np.median(finite_values(values)))


def site_tables(root: Path, site: str) -> SiteTables:
    """One hypothesis site's score tables (`experiments.HYPOTHESIS_SITES`), with its random-init control read at the
    native pair on the control's own proteins."""
    experiment, block, reference = experiments.HYPOTHESIS_SITES[site]
    keys = experiments.site_keys(block, reference)

    def read(key: str) -> pd.DataFrame:
        return experiments.score_table(root, experiment, key)

    return SiteTables(read(keys.native), read(keys.sign), read(keys.residual), read(keys.sae),
                      tuple(read(key) for key in keys.rotated),
                      experiments.score_table(root, experiments.RANDOM_INIT_PASSES[experiment], keys.native))


def basis_groups(tables: SiteTables, metric: str) -> tuple[list[BasisGroup], tuple[float, float]]:
    """Figure 2B at one site and metric: each basis's poles, and the band the ten rotations' medians span (H2's)."""
    medians = [_median(table[metric]) for table in tables.rotated]  # (k,)
    groups = [BasisGroup("native\ngate-tagged", tables.native[metric].to_numpy(), NATIVE),
              BasisGroup("native\nsign-only", tables.sign[metric].to_numpy(), NATIVE, hollow=True),
              BasisGroup("random\ninit", tables.random_init[metric].to_numpy(), RANDOM_INIT,
                         marker=CONTROLS["random init"].marker),
              BasisGroup("residual\nstream", tables.residual[metric].to_numpy(), RESIDUAL),
              BasisGroup("SAE", tables.sae[metric].to_numpy(), SAE)]
    return groups, (min(medians), max(medians))


def inheritance_groups(root: Path, site: str) -> list[BasisGroup | RangeGroup]:
    """Figure 3A at one site: each basis's held-out AUROC before and after its test proteins inherit their homologs'
    annotations (`missing.basis_scores`), the rotations as the range of their ten medians."""
    experiment, block, reference = experiments.HYPOTHESIS_SITES[site]
    keys = experiments.site_keys(block, reference)

    def single(label: str, key: str, color: str, hollow: bool = False) -> BasisGroup:
        table = pd.read_parquet(missing.table_path(root, experiment, key))
        return BasisGroup(label, table["auroc_before"].to_numpy(), color, hollow=hollow, after=table["auroc_after"].to_numpy())

    rotated = [pd.read_parquet(missing.table_path(root, experiment, key)) for key in keys.rotated]
    return [single("native\ngate-tagged", keys.native, NATIVE), single("native\nsign-only", keys.sign, NATIVE, hollow=True),
            RangeGroup("ten\nrotations", tuple(_median(table["auroc_before"]) for table in rotated), ROTATION,
                       after=tuple(_median(table["auroc_after"]) for table in rotated)),
            single("residual\nstream", keys.residual, RESIDUAL), single("SAE", keys.sae, SAE)]


def e1_shares(root: Path) -> pd.DataFrame:
    """E1's report from every ESM-2 model (`retest.retest_tables` with a model column): model, layer, arm, share."""
    return pd.concat([pd.read_parquet(root / "retest" / model / "e1_summary.parquet") for model in experiments.RETEST_BUDGET_HOURS],
                     ignore_index=True)


def sweep_medians(root: Path, metric: str = "held_out_auroc") -> pd.DataFrame:
    """The sweep pass's median `metric` with its 95% unit-bootstrap interval for every planned pair: basis, k, codebook,
    the basis's unit count, estimate, low and high."""
    rows = []
    for planned in experiments.experiment_plans()["e2_sweep"].plan:
        name = planned.reference if planned.reference is not None else planned.basis.sae
        found = re.fullmatch(r".+_k(\d+)_(\d+)", str(name))
        if found is None:
            raise ValueError(f"Sweep member {name!r} does not name its k and codebook.")
        values = experiments.score_table(root, "e2_sweep", planned.key)[metric]
        interval = median_interval(values.to_numpy(dtype=np.float64))
        rows.append({"basis": planned.basis.kind, "k": int(found[1]), "codebook": int(found[2]), "units": len(values),
                     "estimate": interval.estimate, "low": interval.low, "high": interval.high})
    return pd.DataFrame(rows)


def sparse_probe_summary(root: Path, model: str) -> pd.DataFrame:
    """E6 on one model's mean-pooled products at its rotation block (`sparse_probes.rotation_summary`), by k."""
    plan, _ = experiments.concept_plans()[model]
    summary = pd.read_parquet(root / "concepts" / model / "e6_rotation_summary.parquet")
    chosen = summary[(summary["features"] == "mean") & (summary["block"] == plan.rotation_block)].sort_values("k")
    if chosen.empty:
        raise ValueError(f"E6 has no mean-pooled rows at {model}'s rotation block {plan.rotation_block}.")
    return chosen


def dominant_shares(tables: Mapping[str, Sequence[pd.DataFrame]], kinds: Mapping[int, str]) -> pd.DataFrame:
    """Per basis, copy and concept kind, the share of the basis's units whose single dominant local term
    (`scores.local_scores`) is of that kind, for every kind some basis has; a dominant term without a kind raises."""
    rows = []
    for basis, copies in tables.items():
        for copy, table in enumerate(copies):
            dominant = table["dominant"].to_numpy(dtype=bool)  # (p,)
            kind = table["best_local_term"].map(kinds)  # (p,)
            unknown = sorted(set(table.loc[dominant & kind.isna().to_numpy(), "best_local_term"]))
            if unknown:
                raise ValueError(f"Dominant terms {unknown[:5]} of the {basis} basis have no concept kind.")
            rows.extend({"basis": basis, "copy": copy, "kind": name, "share": float((dominant & (kind == name).to_numpy()).mean())}
                        for name in CONCEPT_KINDS)
    shares = pd.DataFrame(rows)
    present = shares.groupby("kind")["share"].max() > 0
    return shares[shares["kind"].map(present)].reset_index(drop=True)


def dominance_tables(tables: SiteTables) -> dict[str, list[pd.DataFrame]]:
    """Figure 3B's bases at one site, by `DOMINANCE_STYLES` name."""
    return {"native": [tables.native], "sign": [tables.sign], "rotation": list(tables.rotated), "residual": [tables.residual],
            "sae": [tables.sae]}


def scale_medians(root: Path) -> list[tuple[str, Interval]]:
    """H7's median margin with its 95% interval for each model, at `experiments.SCALE_SITES`."""
    return [(model, median_interval(experiments.score_table(root, experiment, key)["margin"].to_numpy(dtype=np.float64)))
            for model, experiment, key in experiments.SCALE_SITES]


def pretraining_decisions(root: Path) -> dict[str, dict[str, object]]:
    """H4's decision for each model from the run's `decisions.json`, by model."""
    decisions = json.loads((root / "decisions.json").read_text(encoding="utf-8"))
    return {str(entry["site"]): entry for entry in decisions if entry["hypothesis"] == "H4"}


# -- panels ------------------------------------------------------------------------------------------------------------


def e1_panel(ax: Axes, summary: pd.DataFrame) -> None:
    """Each arm's share of units associated with a concept at every (model, layer) cell, the rotated intermediates as
    the range of their shares; the models side by side."""
    # summary: model, layer, arm, share
    import matplotlib

    from matplotlib.lines import Line2D

    models = [model for model in experiments.RETEST_BUDGET_HOURS if (summary["model"] == model).any()]
    cells = [(model, int(layer)) for model in models for layer in sorted(summary.loc[summary["model"] == model, "layer"].unique())]
    position = {cell: index + models.index(cell[0]) for index, cell in enumerate(cells)}  # an empty slot between models
    percent = summary.assign(percent=100 * summary["share"]).set_index(["model", "layer", "arm"])["percent"].sort_index()
    offset = dict(zip([*E1_ARMS, E1_ROTATED], _dodge(len(E1_ARMS) + 1, 0.7), strict=True))
    with matplotlib.rc_context(STYLE):
        for (model, layer), x in position.items():
            cell = percent.loc[(model, layer)]  # arm -> percent
            rotated = cell[cell.index.str.startswith(E1_ROTATED)]
            if len(rotated):
                ax.vlines(x + offset[E1_ROTATED], rotated.min(), rotated.max(), color=ROTATION, linewidth=2.2, zorder=2)
            for arm, (_, color, marker) in E1_ARMS.items():
                if arm in cell.index:
                    ax.scatter(x + offset[arm], cell[arm], s=10, marker=marker, color=color, linewidths=0, zorder=3)
        transform = ax.get_xaxis_transform()
        for index, model in enumerate(models):
            xs = [x for (owner, _), x in position.items() if owner == model]
            ax.text(float(np.mean(xs)), -0.2, f"{MODEL_NAMES[model]} layer", transform=transform, ha="center", va="top",
                    color=INK)
            if index:
                ax.axvline(min(xs) - 1, color=ROW_BAND, linewidth=1.0, zorder=0)
        ax.set_xticks(list(position.values()), [str(layer) for _, layer in position])
        ax.set_xlim(-0.6, max(position.values()) + 0.6)
        ax.set_ylim(bottom=0)
        ax.set_ylabel("units associated\nwith a concept (%)")
        ax.tick_params(axis="x", length=0)
        _grid(ax)
        handles = [Line2D([], [], linestyle="none", marker=marker, color=color, markersize=3.5, label=name)
                   for name, color, marker in E1_ARMS.values()]
        handles.append(Line2D([], [], color=ROTATION, linewidth=2.2, label="rotated intermediates"))
        _key(ax, handles, columns=4)


def sweep_panel(ax: Axes, medians: pd.DataFrame, *, ylabel: str) -> None:
    """SAE medians against codebook size, a line for each k; the native poles at their own count, each k's read at the
    rates of that k's smallest codebook, spread a little along the axis so the three stay apart."""
    import matplotlib

    from matplotlib.lines import Line2D

    sae = medians[medians["basis"] == "sae"]
    native = medians[medians["basis"] == "native"]
    units = int(native["units"].iloc[0])
    shift = dict(zip(SWEEP_MARKERS, _dodge(len(SWEEP_MARKERS), 0.4), strict=True))  # in log2 steps
    with matplotlib.rc_context(STYLE):
        for k, marker in SWEEP_MARKERS.items():
            line = sae[sae["k"] == k].sort_values("units")
            ax.plot(line["units"], line["estimate"], color=SAE, linewidth=0.8, zorder=2)
            for row in line.itertuples():
                _interval_bar(ax, row.units, Interval(row.estimate, row.low, row.high), SAE, marker=marker)
            own = native[native["k"] == k].sort_values("codebook").iloc[0]
            _interval_bar(ax, units * 2 ** shift[k], Interval(own["estimate"], own["low"], own["high"]), NATIVE, marker=marker)
        codebooks = sorted(int(value) for value in sae["units"].unique())
        ax.set_xscale("log", base=2)
        ax.set_xticks(codebooks, [f"{tick:,}" for tick in codebooks])
        ax.minorticks_off()
        ax.set_xlim(units / 1.6, max(codebooks) * 1.5)
        ax.set_xlabel("units in the basis")
        ax.set_ylabel(ylabel)
        _grid(ax)
        handles = [Line2D([], [], color=SAE, linewidth=0.8, label="SAE"),
                   Line2D([], [], linestyle="none", marker="o", color=NATIVE, markersize=4, label=f"native poles ({units:,})"),
                   *(Line2D([], [], linestyle="none", marker=marker, color=MUTED, markersize=4, label=f"k = {k}")
                     for k, marker in SWEEP_MARKERS.items())]
        _key(ax, handles, columns=3)


def sparse_probe_panel(ax: Axes, summary: pd.DataFrame, *, ylabel: str | None) -> None:
    """The native median test score over targets by k, against the band the ten rotations' medians span."""
    # summary: k, native, best_rotation, rotation_range
    import matplotlib

    k = summary["k"].to_numpy()  # (s,)
    with matplotlib.rc_context(STYLE):
        ax.fill_between(k, summary["best_rotation"] - summary["rotation_range"], summary["best_rotation"], color=ROTATION,
                        alpha=0.35, linewidth=0, zorder=1)
        ax.plot(k, summary["native"], color=NATIVE, marker="o", markersize=3.5, zorder=3)
        ax.set_xscale("log", base=2)
        ax.set_xticks(k, [str(int(value)) for value in k])
        ax.minorticks_off()
        ax.set_xlabel("units per probe, k")
        if ylabel:
            ax.set_ylabel(ylabel)
        _grid(ax)


def dominant_panel(ax: Axes, shares: pd.DataFrame, *, legend: bool) -> None:
    """Rows of concept kinds, a mark per basis at the share of its units with a single dominant term of that kind; the
    rotations as the range of their shares with its median."""
    # shares: basis, copy, kind, share (`dominant_shares`)
    import matplotlib

    from matplotlib.lines import Line2D

    kinds = [kind for kind in CONCEPT_KINDS if kind in set(shares["kind"])]
    offset = dict(zip(DOMINANCE_STYLES, _dodge(len(DOMINANCE_STYLES), 0.6), strict=True))
    with matplotlib.rc_context(STYLE):
        for row, kind in enumerate(kinds):
            if row % 2:
                ax.axhspan(row - 0.5, row + 0.5, color=ROW_BAND, linewidth=0, zorder=0)
            for basis, (_, color, hollow) in DOMINANCE_STYLES.items():
                values = 100 * shares.loc[(shares["kind"] == kind) & (shares["basis"] == basis), "share"].to_numpy()  # (k,)
                if values.size == 0:
                    continue
                y = row + offset[basis]
                if values.size > 1:
                    ax.hlines(y, values.min(), values.max(), color=color, linewidth=2.2, alpha=0.7, zorder=2)
                ax.plot(float(np.median(values)), y, marker="o", color=color, markerfacecolor="white" if hollow else color,
                        markeredgecolor=color, markeredgewidth=0.9, markersize=4, linestyle="none", zorder=3)
        ax.set_yticks(range(len(kinds)), kinds)
        ax.set_ylim(len(kinds) - 0.5, -0.5)
        ax.set_xlim(left=0)
        ax.set_xlabel("units whose one dominant\nlocal term is of the kind (%)")
        ax.tick_params(axis="y", length=0)
        if legend:
            _key(ax, [Line2D([], [], linestyle="none", marker="o", color=color, markerfacecolor="white" if hollow else color,
                             markersize=4, label=name) for name, color, hollow in DOMINANCE_STYLES.values()])


def scale_panel(ax: Axes, medians: Sequence[tuple[str, Interval]]) -> None:
    """Each model's median margin with its 95% interval, smallest model first, in the model's color."""
    import matplotlib

    with matplotlib.rc_context(STYLE):
        for x, (model, interval) in enumerate(medians):
            _interval_bar(ax, x, interval, MODEL_COLORS[MODEL_NAMES[model]])
        ax.set_xticks(range(len(medians)), [MODEL_NAMES[model] for model, _ in medians])
        ax.set_xlim(-0.5, len(medians) - 0.5)
        ax.set_ylabel("median margin\nat the 75% block")
        ax.tick_params(axis="x", length=0)
        _grid(ax)


def pretraining_panel(ax: Axes, decisions: Mapping[str, Mapping[str, object]]) -> None:
    """Rows of concept kinds, each model's trained minus random-init median margin with its 95% interval (H4); a kind
    with too few poles in either arm is marked so, and a decision that was not taken is named in the key."""
    import matplotlib

    from matplotlib.lines import Line2D

    models = list(decisions)
    details = {model: dict(entry.get("details", {})) for model, entry in decisions.items()}  # kind -> its result
    kinds = [kind for kind in CONCEPT_KINDS if any(kind in detail for detail in details.values())]
    offset = dict(zip(models, _dodge(len(models), 0.3), strict=True))
    with matplotlib.rc_context(STYLE):
        ax.axvline(0, color=MUTED, linewidth=0.6, zorder=1)
        for row, kind in enumerate(kinds):
            if row % 2:
                ax.axhspan(row - 0.5, row + 0.5, color=ROW_BAND, linewidth=0, zorder=0)
            for model in models:
                kind_test = details[model].get(kind)
                if kind_test is None:
                    continue
                y = row + offset[model]
                if not kind_test["tested"]:
                    ax.text(0, y, " too few poles", va="center", ha="left", fontsize=5.5, color=MUTED)
                    continue
                difference = kind_test["difference"]
                ax.errorbar(difference["estimate"], y, xerr=[[difference["estimate"] - difference["low"]],
                                                             [difference["high"] - difference["estimate"]]],
                            fmt="o", color=MODEL_COLORS[MODEL_NAMES[model]], markersize=4, elinewidth=1.0, capsize=0, zorder=3)
        ax.set_yticks(range(len(kinds)), kinds)
        ax.set_ylim(len(kinds) - 0.5, -0.5)
        ax.set_xlabel("trained minus random-init median margin")
        ax.tick_params(axis="y", length=0)
        _key(ax, [Line2D([], [], linestyle="none", marker="o", color=MODEL_COLORS[MODEL_NAMES[model]], markersize=4,
                         label=MODEL_NAMES[model] + ("" if decisions[model]["taken"] else ", not taken")) for model in models],
             right=True)


def _inheritance_key(ax: Axes) -> None:
    from matplotlib.lines import Line2D

    _key(ax, [Line2D([], [], linestyle="none", marker="o", color=INK, markersize=4, label="as annotated"),
              Line2D([], [], linestyle="none", marker="D", color=INK, markerfacecolor="white", markersize=4,
                     label="with close homologs' annotations")], right=True, columns=1)


# -- figures -----------------------------------------------------------------------------------------------------------


def figure_2(root: Path) -> Figure:
    """Figure 2: (A) E1's shares at every ESM-2 cell; (B) margin and held-out AUROC by basis at each hypothesis site
    against the ten rotations' band; (C) the SAE sweep with the native poles at their own count; (D) E6's k-sparse
    probes, native against the rotations' band."""
    import matplotlib

    sites = list(experiments.HYPOTHESIS_SITES)
    tables = {site: site_tables(root, site) for site in sites}
    with matplotlib.rc_context(STYLE):
        figure = new_figure(7.6)
        outer = figure.add_gridspec(3, 1, height_ratios=[1.0, 2.1, 1.0], hspace=0.62, left=0.09, right=0.97, top=0.92,
                                    bottom=0.07)
        shares = figure.add_subplot(outer[0])
        e1_panel(shares, e1_shares(root))
        letter(shares, "A")
        bases = outer[1].subgridspec(2, 2, hspace=0.12, wspace=0.22)
        for row, metric in enumerate(("margin", "held_out_auroc")):
            for column, site in enumerate(sites):
                ax = figure.add_subplot(bases[row, column])
                groups, band = basis_groups(tables[site], metric)
                basis_panel(ax, groups, ylabel=METRIC_NAMES[metric] if column == 0 else "", band=band, band_label=None)
                if row == 0:
                    ax.set_title(site_name(site), loc="left", fontsize=7, color=INK, pad=4)
                    ax.tick_params(labelbottom=False)
                    if column == 0:
                        letter(ax, "B")
                    else:
                        _key(ax, [_band_handle()], right=True)
        lower = outer[2].subgridspec(1, 4, wspace=0.6)
        sweep = figure.add_subplot(lower[0, :2])
        sweep_panel(sweep, sweep_medians(root), ylabel=METRIC_NAMES["held_out_auroc"])
        letter(sweep, "C")
        for column, model in enumerate(experiments.concept_plans()):
            ax = figure.add_subplot(lower[0, 2 + column])
            sparse_probe_panel(ax, sparse_probe_summary(root, model), ylabel="median test score" if column == 0 else None)
            ax.set_title(MODEL_NAMES[model], fontsize=6.5, color=INK, pad=3)
            if column == 0:
                letter(ax, "D")
    return figure


def figure_3(root: Path) -> Figure:
    """Figure 3: (A) held-out AUROC by basis before and after inheriting close homologs' annotations; (B) the share of
    units with one dominant local term, by kind and basis; (C) median margin across scale (H7); (D) trained minus
    random-init median margin by kind (H4)."""
    import matplotlib

    sites = list(experiments.HYPOTHESIS_SITES)
    kinds = input_kinds(root / "inputs")
    with matplotlib.rc_context(STYLE):
        figure = new_figure(6.8)
        outer = figure.add_gridspec(3, 1, height_ratios=[1.2, 1.0, 1.0], hspace=0.75, left=0.11, right=0.97, top=0.92,
                                    bottom=0.08)
        upper, middle = outer[0].subgridspec(1, 2, wspace=0.22), outer[1].subgridspec(1, 2, wspace=0.22)
        for column, site in enumerate(sites):
            ax = figure.add_subplot(upper[0, column])
            basis_panel(ax, inheritance_groups(root, site), ylabel=METRIC_NAMES["held_out_auroc"] if column == 0 else "")
            ax.set_title(site_name(site), loc="left", fontsize=7, color=INK, pad=4)
            if column == 0:
                letter(ax, "A")
            else:
                _inheritance_key(ax)
        for column, site in enumerate(sites):
            ax = figure.add_subplot(middle[0, column])
            dominant_panel(ax, dominant_shares(dominance_tables(site_tables(root, site)), kinds), legend=column == 0)
            if column == 0:
                letter(ax, "B")
            else:
                ax.tick_params(labelleft=False)
        lower = outer[2].subgridspec(1, 2, width_ratios=[1.3, 2.7], wspace=0.35)
        scale = figure.add_subplot(lower[0, 0])
        scale_panel(scale, scale_medians(root))
        letter(scale, "C")
        pretraining = figure.add_subplot(lower[0, 1])
        pretraining_panel(pretraining, pretraining_decisions(root))
        letter(pretraining, "D")
    return figure


# -- Figures 5 and 6: what the model uses, and what lies beyond single units ---------------------------------------------


def ablation_table(root: Path) -> pd.DataFrame:
    """E7's labeled poles (`ablation.run_h6`), every status, each tested pole with its drop minus its placebos' mean
    drop (`excess`, H6's quantity)."""
    table = pd.read_parquet(root / "causal" / "h6.parquet")
    tested = (table["status"] == "tested").to_numpy()  # (a,)
    excess = np.full(len(table), np.nan)  # (a,)
    excess[tested] = table.loc[tested, "drop"].to_numpy(dtype=np.float64) - np.array(
        [np.mean(drops) for drops in table.loc[tested, "placebo_drops"]], dtype=np.float64)
    return table.assign(excess=excess)


def readout_conditions(root: Path) -> dict[str, object]:
    """E7b's masked-token readout with the weakest or the strongest activations removed (`ablation.weak_strong`)."""
    return json.loads((root / "causal" / "weak_strong.json").read_text(encoding="utf-8"))


def steering_outcome(root: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    """E7d's steered bin pairs (`steering.SteeringRun.pairs`) and its summary (`steering.steering_summary`)."""
    folder = root / "causal" / "steering"
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    return pd.read_parquet(folder / "steering.parquet"), receipt["summary"]


def attribution_table(root: Path) -> pd.DataFrame:
    """E9's mappable targets on ESMC-600 (`attribution.run_e9`)."""
    return pd.read_parquet(root / "concepts" / experiments.CAUSAL_MODEL / "e9_attribution.parquet")


def dictionary_report(root: Path, model: str) -> dict[str, object]:
    """E8 at one model's site (`passes.run_dictionary`'s receipt)."""
    return json.loads((root / "dictionary" / model / "receipt.json").read_text(encoding="utf-8"))


def subspace_rows(root: Path, model: str) -> pd.DataFrame:
    """E10's full-rank readouts of the units' mean products at each depth (`subspaces.run_e10`), with the block's
    relative depth and the model."""
    table = pd.read_parquet(root / "concepts" / model / "e10_subspaces.parquet")
    chosen = table[(table["features"] == "z_mean") & table["full"]]
    return chosen.assign(depth=(chosen["block"] + 1) / experiments.BLOCKS[model], model=model)


def payoff_differences(root: Path, metric: str = "pr_auc") -> pd.DataFrame:
    """E11's per-target differences between fingerprints (`payoff.paired_differences`) for every model, with a model
    column."""
    return pd.concat([payoff.paired_differences(pd.read_parquet(root / "concepts" / model / "e11_scores.parquet"), metric)
                      .assign(model=model) for model in experiments.concept_plans()], ignore_index=True)


def ablation_panel(ax: Axes, table: pd.DataFrame) -> None:
    """Each tested labeled pole's excess drop at its term's residues against its own drop outside the term, the
    in-distribution cost; the median excess dashed over its 95% interval."""
    # table: `ablation_table`
    import matplotlib

    from matplotlib.lines import Line2D

    tested = table[table["status"] == "tested"]
    excess = tested["excess"].to_numpy(dtype=np.float64)  # (a,)
    outside = tested["outside_drop"].to_numpy(dtype=np.float64)  # (a,), NaN where no masked residue lay outside
    interval = median_interval(excess)
    shown = np.isfinite(outside)  # (a,)
    with matplotlib.rc_context(STYLE):
        ax.axhline(0, color=MUTED, linewidth=0.6, zorder=1)
        ax.axvline(0, color=MUTED, linewidth=0.6, zorder=1)
        ax.axhspan(interval.low, interval.high, color=NATIVE, alpha=0.15, linewidth=0, zorder=0)
        ax.axhline(interval.estimate, color=NATIVE, linewidth=0.8, linestyle=(0, (3, 2)), zorder=2)
        ax.scatter(outside[shown], excess[shown], s=9, color=NATIVE, alpha=0.65, linewidths=0, zorder=3)
        ax.set_xlabel("drop at residues outside the term")
        ax.set_ylabel("drop at the term's residues\nminus its placebos' mean")
        _key(ax, [Line2D([], [], linestyle="none", marker="o", color=NATIVE, markersize=3.5,
                         label=f"{len(tested)} of {len(table)} labeled poles tested"),
                  Line2D([], [], color=NATIVE, linewidth=0.8, linestyle=(0, (3, 2)), label="median, 95% interval shaded")],
             columns=1)


def readout_panel(loss: Axes, accuracy: Axes, conditions: Mapping[str, object]) -> None:
    """Masked-token loss and accuracy on held-out proteins with the model intact, with each unit's weakest activations
    removed in every block, and with its strongest activations of the same total magnitude removed."""
    import matplotlib

    shares = conditions["removed_share"]
    names = {"intact": "intact", "weak": f"weakest {shares['weak']:.0%}\nremoved", "strong": f"strongest {shares['strong']:.0%}\nremoved"}
    with matplotlib.rc_context(STYLE):
        for ax, metric, label in ((loss, "loss", "masked-token loss"), (accuracy, "accuracy", "accuracy")):
            values = [conditions["readout"][condition][metric] for condition in names]
            ax.plot(values, range(len(names)), linestyle="none", marker="o", color=INK, markersize=4.5, zorder=3)
            ax.set_yticks(range(len(names)), list(names.values()))
            ax.set_ylim(len(names) - 0.5, -0.5)
            ax.set_xlabel(label)
            ax.tick_params(axis="y", length=0)
            _grid(ax, "x")
        accuracy.tick_params(labelleft=False)


def steering_panel(ax: Axes, pairs: pd.DataFrame, summary: Mapping[str, object]) -> None:
    """Median path energy over the steered bin pairs at each distance between their bins, by arm, with the natural
    outputs' median energy dashed and the isometry check named."""
    # pairs: start, end, arm, energy, ...; summary: `steering.steering_summary`
    import matplotlib

    from matplotlib.lines import Line2D

    medians = pairs.assign(distance=(pairs["end"] - pairs["start"]).abs()).groupby(["arm", "distance"])["energy"].median()
    isometry = summary["isometry"]
    with matplotlib.rc_context(STYLE):
        ax.axhline(float(summary["natural_energy"]), color=MUTED, linewidth=0.6, linestyle=(0, (1, 2)), zorder=1)
        for arm, (_, color, dash) in STEERING_STYLES.items():
            series = medians.loc[arm]
            ax.plot(series.index.to_numpy(), series.to_numpy(), color=color, linestyle=dash, marker="o", markersize=3,
                    zorder=3)
        # Between the steered paths, which sit high, and the natural outputs' line near the floor.
        ax.text(0.98, 0.40, f"geodesic distances correlate r = {isometry['geodesic_r']:.2f},\n"
                            f"straight ones r = {isometry['straight_r']:.2f}", transform=ax.transAxes, ha="right",
                va="center", fontsize=5.5, color=MUTED)
        ax.set_xlabel("bins between start and end")
        ax.set_ylabel("path energy")
        _grid(ax)
        handles = [Line2D([], [], color=color, linestyle=dash, label=name) for name, color, dash in STEERING_STYLES.values()]
        handles.append(Line2D([], [], color=MUTED, linewidth=0.6, linestyle=(0, (1, 2)), label="natural outputs"))
        _key(ax, handles, columns=2)


def attribution_panel(ax: Axes, table: pd.DataFrame) -> None:
    """Each mappable target's labeled-neuron share of its probe's separation against its matched null sets' mean
    share, filled where it clears the null's 95% interval."""
    # table: `attribution_table`
    import matplotlib

    from matplotlib.lines import Line2D

    scored = table.dropna(subset=["labeled_share", "null_mean"])
    null = scored["null_mean"].to_numpy(dtype=np.float64)  # (t,)
    share = scored["labeled_share"].to_numpy(dtype=np.float64)  # (t,)
    above = share > scored["null_high"].to_numpy(dtype=np.float64)  # (t,)
    with matplotlib.rc_context(STYLE):
        low, high = min(float(null.min()), float(share.min()), 0.0), max(float(null.max()), float(share.max()))
        ax.plot([low, high], [low, high], color=MUTED, linewidth=0.6, zorder=1)
        ax.scatter(null[~above], share[~above], s=14, facecolors="white", edgecolors=NATIVE, linewidths=0.8, zorder=3)
        ax.scatter(null[above], share[above], s=14, color=NATIVE, linewidths=0, zorder=3)
        ax.set_xlabel("matched unlabeled neurons' share")
        ax.set_ylabel("labeled neurons' share\nof the probe's separation")
        _key(ax, [Line2D([], [], linestyle="none", marker="o", color=NATIVE, markersize=4,
                         label=f"above the null's 95% interval ({int(above.sum())} of {len(scored)})"),
                  Line2D([], [], linestyle="none", marker="o", color=NATIVE, markerfacecolor="white", markersize=4,
                         label="within it or below")], columns=1)


def dictionary_panel(ax: Axes, dictionaries: Mapping[str, Mapping[str, object]], saes: Sequence[str], *, ylabel: bool) -> None:
    """For each SAE at a site, the share of its activation carried by latents whose best correlation with one pole
    reaches each threshold, with the native poles (solid) and a rotation's poles (dashed)."""
    import matplotlib

    with matplotlib.rc_context(STYLE):
        for name, (_, marker) in zip(saes, DICTIONARY_ROLES, strict=True):
            entry = dictionaries[name]
            for shares, color, dash in (("native_shares", NATIVE, "-"), ("rotated_shares", ROTATION, (0, (3, 2)))):
                ax.plot(THRESHOLDS, [100 * entry[shares][str(threshold)] for threshold in THRESHOLDS], color=color,
                        linestyle=dash, marker=marker, markersize=3.5, zorder=3)
        ax.set_xticks(THRESHOLDS, [f"{threshold:.1f}" for threshold in THRESHOLDS])
        ax.set_xlabel("best correlation with\none pole, at least")
        if ylabel:
            ax.set_ylabel("SAE activation in\nsuch latents (%)")
        ax.set_ylim(bottom=0)
        _grid(ax)


def search_panel(ax: Axes, search: Mapping[str, object], *, ylabel: bool) -> None:
    """Each sparsest-rotation search from its Haar start to where it stopped, by objective and closeness to the native
    axes, against the native basis (closeness 1 at its own objective) and the preregistered reference."""
    import matplotlib

    from matplotlib.ticker import FuncFormatter

    with matplotlib.rc_context(STYLE):
        ax.axhline(RECOVERY_REFERENCE, color=MUTED, linewidth=0.6, linestyle=(0, (3, 2)), zorder=1)
        for entry in search["searches"]:
            ax.annotate("", xy=(entry["objective"], entry["recovery"]), xytext=(entry["start_objective"], entry["start_recovery"]),
                        arrowprops={"arrowstyle": "-|>", "color": MUTED, "linewidth": 0.7, "shrinkA": 2, "shrinkB": 3},
                        zorder=2)
            ax.plot(entry["start_objective"], entry["start_recovery"], marker="o", color=ROTATION, markersize=3.5,
                    linestyle="none", zorder=3)
            ax.plot(entry["objective"], entry["recovery"], marker="o", color=INK, markersize=3.5, linestyle="none", zorder=3)
        ax.plot(search["native_objective"], 1.0, marker="*", color=NATIVE, markersize=7, linestyle="none", zorder=4)
        ax.set_ylim(0, 1.08)
        # In millions, so no scientific offset sits on the axis label
        ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1e6:g}"))
        ax.set_xlabel("fourth-power objective\n(millions)")  # on one line, the right panel's label passes the edge
        if ylabel:
            ax.set_ylabel("closeness to\nthe native axes")
        _grid(ax)


def subspace_panel(ax: Axes, rows: pd.DataFrame, family: str, *, ylabel: bool) -> None:
    """One family's dimension (solid) and stable rank (dashed) at each relative depth, in each model's color."""
    # rows: `subspace_rows` of every model
    import matplotlib

    with matplotlib.rc_context(STYLE):
        for model, group in rows[rows["family"] == family].groupby("model", sort=False):
            ordered = group.sort_values("depth")
            color = MODEL_COLORS[MODEL_NAMES[str(model)]]
            ax.plot(ordered["depth"], ordered["dimension"], color=color, marker="o", markersize=3, zorder=3)
            ax.plot(ordered["depth"], ordered["stable_rank"], color=color, linestyle=(0, (3, 2)), zorder=2)
        ax.set_xticks([0.25, 0.5, 0.75, 1.0], ["0.25", "0.5", "0.75", "1"])
        ax.set_xlim(0.15, 1.08)
        ax.set_ylim(bottom=0)
        ax.set_title(family, fontsize=6.5, color=INK, pad=3)
        ax.set_xlabel("relative depth")
        if ylabel:
            ax.set_ylabel("dimensions")
        _grid(ax)


def payoff_panel(ax: Axes, differences: pd.DataFrame, *, ylabel: str) -> None:
    """Per comparison of fingerprints, each target's difference under XGBoost as a pale dot, and each model's median
    difference with its 95% target-bootstrap interval."""
    # differences: `payoff_differences`
    import matplotlib

    from matplotlib.lines import Line2D

    comparisons = list(dict.fromkeys(differences["comparison"]))
    models = list(dict.fromkeys(differences["model"]))
    offset = dict(zip(models, _dodge(len(models), 0.36), strict=True))
    with matplotlib.rc_context(STYLE):
        ax.axhline(0, color=MUTED, linewidth=0.6, zorder=1)
        for x, comparison in enumerate(comparisons):
            for model in models:
                chosen = (differences["comparison"] == comparison) & (differences["model"] == model)
                values = differences.loc[chosen, "difference"].to_numpy(dtype=np.float64)  # (t,)
                if values.size == 0:
                    continue
                color = MODEL_COLORS[MODEL_NAMES[model]]
                spread = np.random.default_rng(x).uniform(-0.07, 0.07, values.size)  # (t,), the same jitter every draw
                ax.scatter(x + offset[model] + spread, values, s=6, color=color, alpha=0.35, linewidths=0, zorder=2)
                _interval_bar(ax, x + offset[model], median_interval(values), color)
        ax.set_xticks(range(len(comparisons)), [COMPARISON_NAMES.get(comparison, comparison) for comparison in comparisons])
        ax.set_xlim(-0.5, len(comparisons) - 0.5)
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", length=0)
        _grid(ax)
        _key(ax, [Line2D([], [], linestyle="none", marker="o", color=MODEL_COLORS[MODEL_NAMES[model]], markersize=4,
                         label=MODEL_NAMES[model]) for model in models], right=True)


def figure_5(root: Path) -> Figure:
    """Figure 5: (A) labeled poles' excess drop against their in-distribution cost (H6); (B) the readout with the weakest
    or the strongest activations removed; (C) steering along the manifold against a straight line; (D) probes read
    through labeled neurons."""
    import matplotlib

    pairs, summary = steering_outcome(root)
    with matplotlib.rc_context(STYLE):
        figure = new_figure(5.4)
        outer = figure.add_gridspec(2, 1, hspace=0.62, left=0.1, right=0.97, top=0.88, bottom=0.09)
        upper = outer[0].subgridspec(1, 2, width_ratios=[1.0, 1.0], wspace=0.5)
        ablation = figure.add_subplot(upper[0, 0])
        ablation_panel(ablation, ablation_table(root))
        letter(ablation, "A")
        readouts = upper[0, 1].subgridspec(1, 2, wspace=0.12)
        loss, accuracy = figure.add_subplot(readouts[0, 0]), figure.add_subplot(readouts[0, 1])
        readout_panel(loss, accuracy, readout_conditions(root))
        letter(loss, "B")
        lower = outer[1].subgridspec(1, 2, wspace=0.35)
        steered = figure.add_subplot(lower[0, 0])
        steering_panel(steered, pairs, summary)
        letter(steered, "C")
        probes = figure.add_subplot(lower[0, 1])
        attribution_panel(probes, attribution_table(root))
        letter(probes, "D")
    return figure


def figure_6(root: Path) -> Figure:
    """Figure 6: (A) SAE activation that copies a native pole, against a rotation's poles (E8); (B) the sparsest-rotation
    searches against the native axes; (C) each concept family's dimension and stable rank by depth (E10); (D) per-target
    differences between fingerprints under XGBoost (E11)."""
    import matplotlib

    from matplotlib.lines import Line2D

    sites = experiments.dictionary_sites()
    rows = pd.concat([subspace_rows(root, model) for model in experiments.concept_plans()], ignore_index=True)
    families = list(dict.fromkeys(rows["family"]))
    with matplotlib.rc_context(STYLE):
        figure = new_figure(7.0)
        outer = figure.add_gridspec(3, 1, height_ratios=[1.1, 0.9, 1.1], hspace=0.95, left=0.1, right=0.97, top=0.86,
                                    bottom=0.08)
        upper = outer[0].subgridspec(1, 4, wspace=0.55)
        for column, (model, site) in enumerate(sites.items()):
            report = dictionary_report(root, model)
            title = f"{MODEL_NAMES[model]}, block {site.block}"
            copies = figure.add_subplot(upper[0, column])
            dictionary_panel(copies, report["dictionaries"], site.saes, ylabel=column == 0)
            copies.set_title(title, loc="left", fontsize=6.5, color=INK, pad=3)
            searched = figure.add_subplot(upper[0, 2 + column])
            search_panel(searched, report["rotation_search"], ylabel=column == 0)
            searched.set_title(title, loc="left", fontsize=6.5, color=INK, pad=3)
            if column == 0:
                letter(copies, "A")
                letter(searched, "B")
                _key(copies, [*(Line2D([], [], linestyle="none", marker=marker, color=MUTED, markersize=3.5, label=role)
                                for role, marker in DICTIONARY_ROLES),
                              Line2D([], [], color=NATIVE, label="native poles"),
                              Line2D([], [], color=ROTATION, linestyle=(0, (3, 2)), label="rotated poles")],
                     columns=2, lift=1.16)
                _key(searched, [Line2D([], [], linestyle="none", marker="o", color=ROTATION, markersize=3.5, label="Haar start"),
                                Line2D([], [], linestyle="none", marker="o", color=INK, markersize=3.5, label="after the search"),
                                Line2D([], [], linestyle="none", marker="*", color=NATIVE, markersize=6, label="native basis"),
                                Line2D([], [], color=MUTED, linewidth=0.6, linestyle=(0, (3, 2)),
                                       label=f"reference {RECOVERY_REFERENCE}")], columns=2, lift=1.16)
        middle = outer[1].subgridspec(1, len(families), wspace=0.45)
        for column, family in enumerate(families):
            ax = figure.add_subplot(middle[0, column])
            subspace_panel(ax, rows, family, ylabel=column == 0)
            if column == 0:
                letter(ax, "C")
                _key(ax, [*(Line2D([], [], color=MODEL_COLORS[MODEL_NAMES[model]], label=MODEL_NAMES[model])
                            for model in experiments.concept_plans()),
                          Line2D([], [], color=MUTED, marker="o", markersize=3, label="dimension"),
                          Line2D([], [], color=MUTED, linestyle=(0, (3, 2)), label="stable rank")], columns=4, lift=1.2)
        fingerprints = figure.add_subplot(outer[2])
        payoff_panel(fingerprints, payoff_differences(root), ylabel="PR AUC difference per target")
        letter(fingerprints, "D")
    return figure


# -- supplementary figures ---------------------------------------------------------------------------------------------


def depth_atlas(root: Path, metric: str) -> pd.DataFrame:
    """E2's depth atlas on ESMC-600: at every block, the median `metric` with its 95% unit-bootstrap interval for the
    native poles, the first rotation's and the randomly initialized model's, all at the size-matched SAE's rates."""
    experiment, _, reference = experiments.HYPOTHESIS_SITES["esmc_600"]
    control = experiments.RANDOM_INIT_PASSES[experiment]
    rows = []
    for block in range(experiments.BLOCKS["esmc_600"]):
        for basis, source, key in (("native", experiment, f"block{block}/native@{reference}"),
                                   ("rotation", experiment, f"block{block}/rotation0@{reference}"),
                                   ("random init", control, f"block{block}/native@{reference}")):
            values = experiments.score_table(root, source, key)[metric].to_numpy(dtype=np.float64)  # (a,)
            interval = median_interval(values)
            rows.append({"block": block, "basis": basis, "estimate": interval.estimate, "low": interval.low,
                         "high": interval.high})
    return pd.DataFrame(rows)


def depth_panel(ax: Axes, atlas: pd.DataFrame, *, ylabel: str, site: int) -> None:
    """Each basis's median by block with its interval shaded, the hypothesis site's block marked."""
    # atlas: `depth_atlas`
    import matplotlib

    styles = {"native": (NATIVE, "-", "o"), "rotation": (ROTATION, (0, (3, 2)), "o"),
              "random init": (RANDOM_INIT, CONTROLS["random init"].dash, CONTROLS["random init"].marker)}
    with matplotlib.rc_context(STYLE):
        ax.axvline(site, color=ROW_BAND, linewidth=2.5, zorder=0)
        for basis, (color, dash, marker) in styles.items():
            line = atlas[atlas["basis"] == basis].sort_values("block")
            ax.fill_between(line["block"], line["low"], line["high"], color=color, alpha=0.2, linewidth=0, zorder=1)
            ax.plot(line["block"], line["estimate"], color=color, linestyle=dash, marker=marker, markersize=2.5, zorder=3,
                    label={"native": "native poles", "rotation": "rotated poles (seed 0)",
                           "random init": "randomly initialized model"}[basis])
        ax.set_xlim(-0.8, float(atlas["block"].max()) + 0.8)
        ax.set_ylabel(ylabel)
        _grid(ax)


def figure_depth_atlas(root: Path) -> Figure:
    """Supplementary figure: ESMC-600's depth atlas, margin and held-out AUROC at every block for the native poles, a
    rotation's and the randomly initialized model's, block 26 marked."""
    import matplotlib

    _, site, _ = experiments.HYPOTHESIS_SITES["esmc_600"]
    with matplotlib.rc_context(STYLE):
        figure = new_figure(4.2)
        grid = figure.add_gridspec(2, 1, hspace=0.15, left=0.1, right=0.97, top=0.88, bottom=0.11)
        for row, metric in enumerate(("margin", "held_out_auroc")):
            ax = figure.add_subplot(grid[row])
            depth_panel(ax, depth_atlas(root, metric), ylabel=METRIC_NAMES[metric], site=site)
            letter(ax, "AB"[row])
            if row == 0:
                ax.tick_params(labelbottom=False)
                ax.legend(loc="lower left", bbox_to_anchor=(0.0, 1.02), ncol=3, handletextpad=0.5, columnspacing=1.0,
                          borderaxespad=0.2)
            else:
                ax.set_xlabel("block of ESMC-600")
    return figure


# E13 and E13x on InterPLM's evaluation: the arms the depth panels draw, by arm: name, color, dash and whether the marker
# is hollow (the sign-only reading); each model's depth plans; and each site of the hypothesis-block panel, by model:
# its block and the plans read there, the model's E13 plan first.
RESIDUE_ARMS = {"mlp_native": ("native, gate-tagged", NATIVE, "-", False),
                "mlp_poles": ("native, sign-only", NATIVE, (0, (3, 2)), True),
                "mlp_rotation0": ("rotated poles (seed 0)", ROTATION, "-", False),
                "residual": ("residual dimensions", RESIDUAL, "-", False),
                "sae": ("each layer's SAE on the stream", SAE, "-", False)}
RESIDUE_DEPTHS = {"esmc_600": ("esmc_600_depth", "esmc_600_depth_sae"),
                  "esmc_6b": ("esmc_6b_depth_a", "esmc_6b_depth_b", "esmc_6b_depth_sae")}
RESIDUE_SITES = {"esmc_300": (22, ("esmc_300",)),
                 "esmc_600": (26, ("esmc_600", "esmc_600_rotations", "esmc_600_mlp", "esmc_600_search")),
                 "esmc_6b": (59, ("esmc_6b", "esmc_6b_rotations", "esmc_6b_mlp", "esmc_6b_search"))}
SEARCHED = "mlp_searched"  # E13s: the rotations E8's sparsest-rotation search found, read in its coordinates
# The hypothesis-block panel's readings: name, color, marker and whether the marker is hollow.
SITE_READINGS = {"mlp_native": ("native, gate-tagged", NATIVE, "o", False),
                 "mlp_poles": ("native, sign-only", NATIVE, "o", True),
                 "rotations": ("rotated poles", ROTATION, "o", False),
                 "searched": ("rotations found by the sparsity search", SEARCHED_ROTATION, "s", False),
                 "residual": ("residual dimensions", RESIDUAL, "o", False),
                 "stream_sae": ("SAE on the stream", SAE, "o", False),
                 "write_sae": ("SAE on the feed-forward write", SAE, "D", False)}


def residue_summary(root: Path) -> pd.DataFrame:
    """E13's and E13x's reports (`retest.retest_tables`) from every plan that has run, each row's plan in `plan`."""
    folder = root / "retest_esmc"
    frames = [pd.read_parquet(folder / name / "e13_summary.parquet").assign(plan=name)
              for name in experiments.esmc_retest_plans() if (folder / name / "e13_summary.parquet").exists()]
    if not frames:
        raise FileNotFoundError(f"No E13 plan has run under {folder}.")
    return pd.concat(frames, ignore_index=True)


def residue_sites(summary: pd.DataFrame) -> dict[str, dict[str, list[float]]]:
    """The hypothesis-block panel's readings at each site of `RESIDUE_SITES` whose plans have run, by site label: the
    concepts each reading identifies, a value per copy (each rotation seed once, from the first plan that read it; each
    rotation E13s's search found; each SAE once, those of the `_mlp` plans reading the feed-forward write)."""
    sites = {}
    for model, (block, plans) in RESIDUE_SITES.items():
        _require_plans(summary, plans)
        rows = summary[summary["plan"].isin(plans) & (summary["layer"] == block)]
        rows = rows.assign(order=rows["plan"].map(plans.index)).sort_values("order", kind="stable").drop_duplicates("arm")
        concepts = rows.set_index("arm")["identified_concepts"].astype(float)
        writes = {arm for plan, arm in zip(rows["plan"], rows["arm"], strict=True) if plan.endswith("_mlp") and arm.startswith("sae:")}
        readings = {arm: [float(concepts[arm])] for arm in ("mlp_native", "mlp_poles", "residual") if arm in concepts.index}
        readings["rotations"] = [float(value) for arm, value in concepts.items() if arm.startswith(E1_ROTATED)]
        readings["searched"] = [float(value) for arm, value in concepts.items() if arm.startswith(SEARCHED)]
        readings["stream_sae"] = [float(value) for arm, value in concepts.items() if arm.startswith("sae:") and arm not in writes]
        readings["write_sae"] = [float(concepts[arm]) for arm in sorted(writes)]
        sites[f"{MODEL_NAMES[model]}\nblock {block}"] = readings
    return sites


def _require_plans(summary: pd.DataFrame, plans: Sequence[str]) -> None:
    missing_plans = sorted(set(plans) - set(summary["plan"]))
    if missing_plans:
        raise ValueError(f"The residue-level figure needs {missing_plans}, which have not run.")


def residue_depth_panel(ax: Axes, summary: pd.DataFrame, plans: Sequence[str], *, model: str) -> None:
    """Concepts identified at every block a model's depth plans read, by arm, each block's own all-layer SAE drawn as
    one line and an arm two plans read taken from the first; the model's concept depths marked."""
    import matplotlib

    _require_plans(summary, plans)
    rows = summary[summary["plan"].isin(plans)]
    rows = rows.assign(arm=rows["arm"].where(~rows["arm"].str.startswith("sae:"), "sae"),
                       order=rows["plan"].map(list(plans).index))
    rows = rows.sort_values("order", kind="stable").drop_duplicates(["layer", "arm"])
    with matplotlib.rc_context(STYLE):
        for block in experiments.DEPTHS[model]:
            ax.axvline(block, color=ROW_BAND, linewidth=2.5, zorder=0)
        for arm, (label, color, dash, hollow) in RESIDUE_ARMS.items():
            line = rows[rows["arm"] == arm].sort_values("layer")
            ax.plot(line["layer"], line["identified_concepts"], color=color, linestyle=dash, marker="o", markersize=2.5,
                    markerfacecolor="white" if hollow else color, markeredgecolor=color, markeredgewidth=0.7, zorder=3,
                    label=label)
        ax.set_xlim(-0.8, experiments.BLOCKS[model] - 0.2)
        ax.set_ylim(bottom=0)
        ax.set_ylabel("concepts identified")
        ax.set_xlabel(f"block of {MODEL_NAMES[model]}")
        _grid(ax)


def residue_site_panel(ax: Axes, sites: Mapping[str, Mapping[str, Sequence[float]]]) -> None:
    """Concepts identified by each reading at each site, the readings side by side within a site: a mark per copy, the
    rotations as the range of theirs with their median."""
    import matplotlib

    from matplotlib.lines import Line2D

    offsets = dict(zip(SITE_READINGS, _dodge(len(SITE_READINGS), 0.7), strict=True))
    with matplotlib.rc_context(STYLE):
        for x, readings in enumerate(sites.values()):
            for reading, (_, color, marker, hollow) in SITE_READINGS.items():
                values = readings.get(reading, [])
                if reading == "rotations" and values:
                    _range_bar(ax, x + offsets[reading], values, color)
                for value in values if reading != "rotations" else []:
                    ax.plot(x + offsets[reading], value, marker=marker, color=color, markerfacecolor="white" if hollow else color,
                            markeredgecolor=color, markeredgewidth=0.9, markersize=4.5, linestyle="none", zorder=3)
        ax.set_xticks(range(len(sites)), list(sites))
        ax.set_xlim(-0.6, len(sites) - 0.4)
        ax.set_ylim(bottom=0)
        ax.set_ylabel("concepts identified")
        ax.tick_params(axis="x", length=0)
        _grid(ax)
        handles = [Line2D([], [], linestyle="none", marker=marker, color=color, markerfacecolor="white" if hollow else color,
                          markeredgecolor=color, markersize=3.5, label=label)
                   for reading, (label, color, marker, hollow) in SITE_READINGS.items() if reading != "rotations"]
        handles.insert(2, Line2D([], [], color=ROTATION, linewidth=2.2, label="rotated poles, range and median"))
        _key(ax, handles, columns=3)


def figure_residue(root: Path) -> Figure:
    """Supplementary figure, E13 and E13x on InterPLM's evaluation: concepts identified (A) at every ESMC-600 block and
    (B) at ESMC-6B's every fourth block, by native reading, a rotation, the stream's dimensions and each layer's SAE of
    the model's all-layer family, the concept depths marked; (C) by every reading at each model's hypothesis block
    (ESMC-300's 75% block), with the rotations' range, the rotations E13s's sparsity search found and the SAEs on the
    stream and on the feed-forward write."""
    import matplotlib

    summary = residue_summary(root)
    with matplotlib.rc_context(STYLE):
        figure = new_figure(6.6)
        grid = figure.add_gridspec(3, 1, height_ratios=[1.0, 1.0, 1.15], hspace=0.75, left=0.09, right=0.97, top=0.93,
                                   bottom=0.07)
        for row, (model, plans) in enumerate(RESIDUE_DEPTHS.items()):
            ax = figure.add_subplot(grid[row])
            residue_depth_panel(ax, summary, plans, model=model)
            letter(ax, "AB"[row])
            if row == 0:
                ax.legend(loc="lower left", bbox_to_anchor=(0.0, 1.02), ncol=4, handletextpad=0.5, columnspacing=1.0,
                          borderaxespad=0.2)
        sites = figure.add_subplot(grid[2])
        residue_site_panel(sites, residue_sites(summary))
        letter(sites, "C")
    return figure


# -- The metric figure: the same four bases over whole proteins, by two metrics, and at residues -------------------------

# The four bases, by the label an axis gives them: color, and the arm of E13's summary that reads the basis at residues
# (the rotations are every arm that starts with it, the SAE the site's own).
METRIC_BASES = {"neuron\npoles": (NATIVE, "mlp_native"), "ten\nrotations": (ROTATION, E1_ROTATED),
                "stream\npoles": (RESIDUAL, "residual_poles"), "SAE\nlatents": (SAE, "sae:")}
# A whole-protein metric of `missing.basis_scores` on the proteins' own labels: its axis name and limits.
PROTEIN_METRICS = {"auroc_before": ("held-out ROC AUC\nof the best term", (0.5, 1.03)),
                   "precision_before": ("held-out average precision\nof the best term", (0.0, 1.03))}


def metric_groups(root: Path, site: str, metric: str) -> list[BasisGroup | RangeGroup]:
    """One hypothesis site's four bases under one whole-protein metric (`PROTEIN_METRICS`): each unit's score for its
    best term on held-out proteins, the ten rotations as the range of their medians."""
    experiment, block, reference = experiments.HYPOTHESIS_SITES[site]
    keys = experiments.site_keys(block, reference)

    def scores(key: str) -> pd.Series:
        return pd.read_parquet(missing.table_path(root, experiment, key))[metric]  # (a,)

    poles, rotations, stream, latents = METRIC_BASES
    return [BasisGroup(poles, scores(keys.native).to_numpy(), NATIVE),
            RangeGroup(rotations, tuple(_median(scores(key)) for key in keys.rotated), ROTATION),
            BasisGroup(stream, scores(keys.residual).to_numpy(), RESIDUAL),
            BasisGroup(latents, scores(keys.sae).to_numpy(), SAE)]


def scored_units(root: Path, site: str) -> dict[str, str]:
    """How many units of each basis have a term to score on held-out proteins at one site, by axis label: a count, or
    the range of the ten rotations' counts."""
    experiment, block, reference = experiments.HYPOTHESIS_SITES[site]
    keys = experiments.site_keys(block, reference)

    def count(key: str) -> int:
        return int(finite_values(pd.read_parquet(missing.table_path(root, experiment, key))["auroc_before"]).size)

    poles, rotations, stream, latents = METRIC_BASES
    rotated = [count(key) for key in keys.rotated]  # (k,)
    return {poles: f"{count(keys.native):,}", rotations: f"{min(rotated):,} to {max(rotated):,}",
            stream: f"{count(keys.residual):,}", latents: f"{count(keys.sae):,}"}


def residue_concepts(summary: pd.DataFrame, site: str) -> dict[str, list[float]]:
    """The concepts the same four bases identify at residues at one hypothesis site (E13), by axis label: a value for
    the neurons' poles, the stream's poles and the site's own SAE, and one for each rotation."""
    _, block, reference = experiments.HYPOTHESIS_SITES[site]
    _, plans = RESIDUE_SITES[site]
    _require_plans(summary, plans)
    rows = summary[summary["plan"].isin(plans) & (summary["layer"] == block)]
    rows = rows.assign(order=rows["plan"].map(plans.index)).sort_values("order", kind="stable").drop_duplicates("arm")
    concepts = rows.set_index("arm")["identified_concepts"].astype(float)  # (arms,)
    readings = {}
    for label, (_, arm) in METRIC_BASES.items():
        if arm == E1_ROTATED:
            readings[label] = [float(value) for name, value in concepts.items() if name.startswith(arm)]
        else:
            readings[label] = [float(concepts[f"{arm}{reference}" if arm.endswith(":") else arm])]
    return readings


def concept_count_panel(ax: Axes, concepts: Mapping[str, Sequence[float]], *, ylabel: str) -> None:
    """The concepts each basis identifies at residues: a mark for a basis read once, and the range of the rotations'
    counts with their median."""
    import matplotlib

    with matplotlib.rc_context(STYLE):
        for position, (label, values) in enumerate(concepts.items()):
            color, _ = METRIC_BASES[label]
            if len(values) > 1:
                _range_bar(ax, position, values, color)
            else:
                ax.plot(position, values[0], marker="o", color=color, markersize=4.5, linestyle="none", zorder=3)
        ax.set_xticks(range(len(concepts)), list(concepts))
        ax.set_xlim(-0.6, len(concepts) - 0.4)
        ax.set_ylim(bottom=0)
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", length=0)
        _grid(ax)


def figure_metric(root: Path) -> Figure:
    """The metric figure, one hypothesis site a column: the neurons' poles, the ten rotations, the stream's poles and
    the site's SAE (A) by each unit's held-out ROC AUC for its best term over whole proteins, with the units scored
    written under each basis, (B) by its held-out average precision, and (C) by the concepts the basis identifies at
    residues on InterPLM's evaluation."""
    import matplotlib

    summary = residue_summary(root)
    with matplotlib.rc_context(STYLE):
        figure = new_figure(6.0)
        grid = figure.add_gridspec(3, 2, hspace=0.6, wspace=0.2, left=0.11, right=0.97, top=0.95, bottom=0.07)
        for column, site in enumerate(experiments.HYPOTHESIS_SITES):
            for row, (metric, (name, limits)) in enumerate(PROTEIN_METRICS.items()):
                ax = figure.add_subplot(grid[row, column])
                basis_panel(ax, metric_groups(root, site, metric), ylabel=name if column == 0 else "")
                ax.set_ylim(*limits)
                if row == 0:
                    ax.set_title(site_name(site), loc="left", fontsize=7, color=INK, pad=4)
                    for position, units in enumerate(scored_units(root, site).values()):
                        ax.text(position, limits[0] + 0.03, f"{units}\nunits", ha="center", va="bottom", fontsize=6, color=MUTED)
                if column == 0:
                    letter(ax, "AB"[row])
            ax = figure.add_subplot(grid[2, column])
            concept_count_panel(ax, residue_concepts(summary, site), ylabel="concepts identified\nat residues" if column == 0 else "")
            if column == 0:
                letter(ax, "C")
    return figure


# Every figure a run draws, by the name its file takes: the main text's by number, the supplement's by subject.
FIGURES: dict[str, Callable[[Path], Figure]] = {"2": figure_2, "3": figure_3, "4": figure_4, "5": figure_5, "6": figure_6,
                                                "depth_atlas": figure_depth_atlas, "residue": figure_residue,
                                                "metric": figure_metric}
