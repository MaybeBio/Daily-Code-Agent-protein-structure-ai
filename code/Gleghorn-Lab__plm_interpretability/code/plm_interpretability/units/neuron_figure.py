"""The interpretability paper's Fig. 4, single neurons against other units, drawn from the neuron study's archive.

One figure joins two of `figures`: the residue-level depth curves and three-quarter-depth comparison of
`figure_residue`, and the whole-protein average precision of `figure_metric`, with InterPLM's replication on
ESM2-650M. Panels A and B reuse `residue_depth_panel` and E reuses `basis_panel`, so a hue means here what it means in
the study's other figures: neurons red, rotations gray, the residual stream violet, SAEs yellow. Every listing of kinds
of unit, the key's and each panel's, runs from the kind that identifies the fewest concepts to the one that identifies
the most. The sign-only reading of the neurons, which coincides with the gate-tagged one at every block, is left out.

Symbols: a units of one basis; k copies of a basis (the rotations); n layers of a model.
"""

from __future__ import annotations

import argparse
import dataclasses
import numpy as np
import pandas as pd

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import experiments
from .experiments import MODEL_NAMES, site_name
from .figures import (E1_ROTATED, INK, MUTED, NATIVE, PROTEIN_METRICS, RESIDUAL, RESIDUE_ARMS, RESIDUE_DEPTHS, RESIDUE_SITES,
                      ROTATION, SAE, SEARCHED, SEARCHED_ROTATION, STYLE, BasisGroup, RangeGroup, _grid, _require_plans,
                      basis_panel, e1_shares, letter, metric_groups, new_figure, residue_depth_panel, residue_sites,
                      residue_summary, save_figure)


if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure


WIDTH, HEIGHT = 7.09, 6.7  # inches: 180 mm wide, the journal's full width, and 170 mm tall
SIGN_ONLY = "mlp_poles"  # the neurons read by the sign of the product alone, left out of this figure
# The kinds of unit at a three-quarter block, worst to best, by `residue_sites` reading: the key's name, the color and
# the hatch of their bars in panel C.
SITE_KINDS = {"residual": ("residual stream", RESIDUAL, None), "rotations": ("random rotations", ROTATION, None),
              "searched": ("sparsest rotations", SEARCHED_ROTATION, None), "mlp_native": ("neuron poles", NATIVE, None),
              "stream_sae": ("SAE on the stream", SAE, None),
              "write_sae": ("SAE on the feed-forward write", SAE, "////")}
COPIED_KINDS = ("rotations", "searched")  # kinds read in several copies: a bar to their median, a whisker over their range
BAR_WIDTH, GROUP_GAP = 0.78, 1.0  # panel C: a bar's width and the space between two models, in bar slots
REPLICATION_MODEL = "esm2_650m"
# InterPLM's arms on ESM2 that the replication panel draws, worst to best: color; the rotations as a shaded range.
REPLICATION_ARMS = {"residual": RESIDUAL, "mlp_poles": NATIVE, "sae": SAE}
# The average-precision panel's bases, worst to best, by `figures.METRIC_BASES` label: the short label this figure
# gives them. The stream's poles are left out: 25 to 38 of them have a term to score.
METRIC_LABELS = {"ten\nrotations": "rotations", "neuron\npoles": "neurons", "SAE\nlatents": "SAE"}
PRECISION = "precision_before"
CONCEPT_LIMIT = 390  # the concepts axis of panels A, B and D, above the highest SAE count there (327)
SITE_LIMIT = 410  # panel C's concepts axis, with room for the count above its tallest bar (361)
# The stream SAE that panel C draws: the size released at every block of all three models, which panels A and B draw
# too. The other sizes read at one site (8,192 at ESMC-600, 65,536 at ESMC-6B) are reported in the text.
SHARED_SAE_LATENTS = 16_384


@dataclass(frozen=True)
class SiteBar:
    """One bar of panel C: its kind of unit (a `SITE_KINDS` key), the concepts each copy identifies, and the SAE's
    number of latents (None for a kind that is not an SAE)."""

    kind: str
    counts: tuple[float, ...]  # (k,)
    latents: int | None = None


def drop_sign_only(ax: Axes) -> None:
    """Remove the sign-only line that `residue_depth_panel` draws, found by its label."""
    label = RESIDUE_ARMS[SIGN_ONLY][0]
    lines = [line for line in ax.get_lines() if line.get_label() == label]
    assert len(lines) == 1, f"Expected one {label!r} line, found {len(lines)}."
    lines[0].remove()


def depth_panel(ax: Axes, summary: pd.DataFrame, model: str) -> None:
    """Concepts identified at every block one model's depth plans read (`RESIDUE_DEPTHS`), without the sign-only
    neurons, on the concepts axis (`CONCEPT_LIMIT`) that the replication panel shares."""
    residue_depth_panel(ax, summary, RESIDUE_DEPTHS[model], model=model)
    drop_sign_only(ax)
    ax.set_ylim(0, CONCEPT_LIMIT)


def site_bars(summary: pd.DataFrame) -> dict[str, list[SiteBar]]:
    """Panel C's bars at each site of `RESIDUE_SITES`, by site label, worst kind first and each SAE on its own bar
    with its size, smallest first. The rows are chosen as `residue_sites` chooses them, and its values are checked."""
    sites = {}
    for model, (block, plans) in RESIDUE_SITES.items():
        _require_plans(summary, plans)
        rows = summary[summary["plan"].isin(plans) & (summary["layer"] == block)]
        rows = rows.assign(order=rows["plan"].map(plans.index)).sort_values("order", kind="stable").drop_duplicates("arm")
        writes = rows["plan"].str.endswith("_mlp") & rows["arm"].str.startswith("sae:")
        saes = rows[rows["arm"].str.startswith("sae:")].sort_values("features")

        def counts(prefix: str, *, exact: bool = False) -> tuple[float, ...]:
            chosen = rows["arm"] == prefix if exact else rows["arm"].str.startswith(prefix)
            return tuple(rows.loc[chosen, "identified_concepts"].astype(float))  # (k,)

        bars = [SiteBar("residual", counts("residual", exact=True)), SiteBar("rotations", counts(E1_ROTATED))]
        if counts(SEARCHED):
            bars.append(SiteBar("searched", counts(SEARCHED)))
        bars.append(SiteBar("mlp_native", counts("mlp_native", exact=True)))
        for is_write in (False, True):
            chosen = saes[writes.loc[saes.index] == is_write]
            bars.extend(SiteBar("write_sae" if is_write else "stream_sae", (float(count),), int(latents))
                        for count, latents in zip(chosen["identified_concepts"], chosen["features"], strict=True))
        sites[f"{MODEL_NAMES[model]}\nblock {block}"] = bars
    _check_bars(sites, residue_sites(summary))
    return sites


def _check_bars(sites: Mapping[str, Sequence[SiteBar]], readings: Mapping[str, Mapping[str, Sequence[float]]]) -> None:
    """Every bar's counts are the ones `residue_sites` reads, kind by kind."""
    assert list(sites) == list(readings), "Panel C's sites differ from residue_sites'."
    for site, bars in sites.items():
        for kind in SITE_KINDS:
            drawn = sorted(count for bar in bars if bar.kind == kind for count in bar.counts)
            assert drawn == sorted(readings[site][kind]), f"{site}: {kind} draws {drawn}, residue_sites reads {readings[site][kind]}."


def shared_sae_bars(sites: Mapping[str, Sequence[SiteBar]]) -> dict[str, list[SiteBar]]:
    """`site_bars` without the stream SAEs of a size that not every model has: one stream SAE of
    `SHARED_SAE_LATENTS` latents at each site, and the write SAEs as they are."""
    shared = {site: [bar for bar in bars if bar.kind != "stream_sae" or bar.latents == SHARED_SAE_LATENTS]
              for site, bars in sites.items()}
    for site, bars in shared.items():
        drawn = [bar for bar in bars if bar.kind == "stream_sae"]
        assert len(drawn) == 1, f"{site}: expected one stream SAE of {SHARED_SAE_LATENTS} latents, found {len(drawn)}."
    return shared


def best_rotation_multiple(bars: Sequence[SiteBar]) -> float:
    """The neurons' count over the best random rotation's at one site."""
    (neurons,) = [bar.counts[0] for bar in bars if bar.kind == "mlp_native"]
    (rotations,) = [bar.counts for bar in bars if bar.kind == "rotations"]
    return neurons / max(rotations)


def site_bar_panel(ax: Axes, sites: Mapping[str, Sequence[SiteBar]], *, sizes: bool = True) -> None:
    """Concepts identified by each kind of unit at each model's three-quarter block, grouped by model, worst kind first.
    A kind read in several copies is a bar to their median with a whisker over their range; each bar's count is written
    above it (the median for copies), with `sizes` each SAE's size beneath it in whole thousands of latents (16,384 as
    16k, the convention of SAE releases), and the neurons' multiple of the best rotation inside their bar."""
    import matplotlib

    with matplotlib.rc_context(STYLE):
        transform = ax.get_xaxis_transform()
        x, centers = 0.0, []
        for bars in sites.values():
            start = x
            for bar in bars:
                _, color, hatch = SITE_KINDS[bar.kind]
                height = float(np.median(bar.counts))
                ax.bar(x, height, width=BAR_WIDTH, color=color, hatch=hatch, edgecolor="white" if hatch else color,
                       linewidth=0, zorder=2)
                top = height
                if bar.kind in COPIED_KINDS:
                    ax.vlines(x, min(bar.counts), max(bar.counts), color=INK, linewidth=0.8, zorder=3)
                    top = max(bar.counts)
                ax.text(x, top + 5, f"{height:.0f}", ha="center", va="bottom", fontsize=6, color=INK)
                if sizes and bar.latents is not None:
                    ax.text(x, -0.03, f"{bar.latents // 1000}k", transform=transform, ha="center", va="top", fontsize=5.5,
                            color=MUTED)
                if bar.kind == "mlp_native":
                    ax.text(x, height / 2, f"{best_rotation_multiple(bars):.1f}×", rotation=90, ha="center", va="center",
                            fontsize=6, color="white", fontweight="bold", zorder=4)
                x += 1.0
            centers.append((start + x - 1.0) / 2)
            x += GROUP_GAP
        ax.set_xticks(centers, [site.replace("\n", ", ") for site in sites])
        ax.tick_params(axis="x", length=0, pad=12)
        ax.set_xlim(-0.7, x - GROUP_GAP - 0.3)
        ax.set_ylim(0, SITE_LIMIT)
        ax.set_ylabel("concepts identified")
        _grid(ax)


def replication_counts(root: Path, model: str) -> pd.DataFrame:
    """Concepts identified at each layer of one ESM2 model under InterPLM's code, a column per arm (`e1_shares`)."""
    shares = e1_shares(root)
    rows = shares[shares["model"] == model]
    if rows.empty:
        raise ValueError(f"The archive holds no InterPLM retest of {model}.")
    return rows.pivot(index="layer", columns="arm", values="identified_concepts").sort_index()  # (n, arms)


def replication_panel(ax: Axes, counts: pd.DataFrame, *, model: str) -> None:
    """Concepts identified by layer: the residual stream's dimensions, the feed-forward poles and InterPLM's SAEs as
    lines, the rotations of the feed-forward units as the shaded range of their counts with their median, and the
    SAEs named in place."""
    # counts: `replication_counts`
    import matplotlib

    rotated = counts[[arm for arm in counts.columns if arm.startswith(E1_ROTATED)]].to_numpy(dtype=np.float64)  # (n, k)
    assert rotated.shape[1] > 1, "The replication needs several rotations to draw their range."
    layers = counts.index.to_numpy()  # (n,)
    with matplotlib.rc_context(STYLE):
        ax.fill_between(layers, rotated.min(axis=1), rotated.max(axis=1), color=ROTATION, alpha=0.35, linewidth=0, zorder=1)
        ax.plot(layers, np.median(rotated, axis=1), color=ROTATION, marker="o", markersize=2.5, zorder=2)
        for arm, color in REPLICATION_ARMS.items():
            ax.plot(layers, counts[arm].to_numpy(dtype=np.float64), color=color, marker="o", markersize=2.5, zorder=3)
        sae = counts["sae"]
        ax.text(float(layers[2]), float(sae.iloc[2]) + 14, "InterPLM's SAEs", ha="center", va="bottom", fontsize=6,
                color=INK)
        ax.set_xticks(layers)
        ax.set_xlim(layers.min() - 1.5, layers.max() + 1.5)
        ax.set_ylim(0, CONCEPT_LIMIT)
        ax.set_xlabel(f"layer of {MODEL_NAMES[model]}")
        ax.set_ylabel("concepts identified")
        _grid(ax)


def metric_site_groups(root: Path, metric: str) -> tuple[list[BasisGroup | RangeGroup], list[str]]:
    """Both hypothesis sites' rotations, neurons and SAE under one whole-protein metric, side by side, ordered and
    relabeled by `METRIC_LABELS`, with each site's name."""
    groups, names = [], []
    for site in experiments.HYPOTHESIS_SITES:
        by_label = {group.label: group for group in metric_groups(root, site, metric)}
        assert set(METRIC_LABELS) <= set(by_label), f"{site} lacks a basis of {list(METRIC_LABELS)}."
        groups.extend(dataclasses.replace(by_label[label], label=short) for label, short in METRIC_LABELS.items())
        names.append(site_name(site))
    return groups, names


def metric_panel(ax: Axes, root: Path, metric: str) -> None:
    """One whole-protein metric (`figures.PROTEIN_METRICS`) for both sites, each site named under its bases."""
    import matplotlib

    groups, names = metric_site_groups(root, metric)
    label, limits = PROTEIN_METRICS[metric]
    per_site = len(METRIC_LABELS)
    with matplotlib.rc_context(STYLE):
        basis_panel(ax, groups, ylabel=label)
        ax.set_ylim(*limits)
        transform = ax.get_xaxis_transform()
        for index, name in enumerate(names):
            ax.text(index * per_site + (per_site - 1) / 2, -0.2, name, transform=transform, ha="center", va="top",
                    color=INK)
            if index:
                ax.axvline(index * per_site - 0.5, color=MUTED, linewidth=0.5, zorder=0)


def key_handles(names: Mapping[str, str] | None = None) -> list[object]:
    """The figure's key, worst kind of unit first: a swatch of each kind's hue, as lines and bars carry it, named by
    `names` (a `SITE_KINDS` key -> name, every kind) or else by `SITE_KINDS`."""
    from matplotlib.patches import Patch

    if names is not None:
        assert set(names) == set(SITE_KINDS), f"Names {sorted(names)} differ from the kinds {sorted(SITE_KINDS)}."
    return [Patch(facecolor=color, edgecolor="white" if hatch else color, hatch=hatch, linewidth=0,
                  label=names[kind] if names is not None else name)
            for kind, (name, color, hatch) in SITE_KINDS.items()]


def figure_neurons(root: Path) -> Figure:
    """Fig. 4: concepts identified at residues (A) at every block of ESMC-600 and (B) every fourth block of ESMC-6B,
    (C) at three quarters of each model's stack, with the stream SAE every model has and the SAE on the feed-forward
    write, and (D) at each layer of ESM2-650M under InterPLM's code; and (E) each
    unit's held-out average precision for its best term over whole proteins at ESMC-600's block 26 and ESMC-6B's
    block 59."""
    import matplotlib

    summary = residue_summary(root)
    with matplotlib.rc_context(STYLE):
        figure = new_figure(HEIGHT, WIDTH)
        outer = figure.add_gridspec(3, 1, height_ratios=[1.0, 1.05, 0.95], hspace=0.6, left=0.075, right=0.985,
                                    top=0.93, bottom=0.08)
        depths = outer[0].subgridspec(1, 2, wspace=0.08)
        for column, model in enumerate(RESIDUE_DEPTHS):
            ax = figure.add_subplot(depths[column])
            depth_panel(ax, summary, model)
            if column:
                ax.set_ylabel("")
                ax.tick_params(labelleft=False)
            letter(ax, "AB"[column])
        sites = figure.add_subplot(outer[1])
        site_bar_panel(sites, shared_sae_bars(site_bars(summary)))
        letter(sites, "C")
        bottom = outer[2].subgridspec(1, 2, wspace=0.22)
        replication = figure.add_subplot(bottom[0])
        replication_panel(replication, replication_counts(root, REPLICATION_MODEL), model=REPLICATION_MODEL)
        letter(replication, "D")
        precision = figure.add_subplot(bottom[1])
        metric_panel(precision, root, PRECISION)
        letter(precision, "E")
        figure.legend(handles=key_handles(), loc="upper center", bbox_to_anchor=(0.5, 1.0), ncol=6, handlelength=1.2,
                      handleheight=0.9, handletextpad=0.4, columnspacing=1.2, borderaxespad=0.3)
    return figure


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True, help="the neuron study's archive (esmc_native_units_results)")
    parser.add_argument("--out", type=Path, required=True, help="the PNG to write")
    arguments = parser.parse_args()
    print(save_figure(figure_neurons(arguments.root), arguments.out))


if __name__ == "__main__":
    main()
