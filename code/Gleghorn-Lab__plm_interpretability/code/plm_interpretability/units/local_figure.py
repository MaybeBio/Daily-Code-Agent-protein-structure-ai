"""The interpretability paper's single-column figure of single neurons and their labels, and its supplementary companion,
laid out from the panels of `neuron_figure` and `label_figure`.

The main figure joins what were two figures: (A) concepts identified at every block of ESMC-600, (B) at three quarters
of each model's stack, (C) at each layer of ESM2-650M under InterPLM's code, (D) the held-out average precision of each
unit's best term over whole proteins, and (E) three labeled neurons of ESMC-600's block 26 along test proteins. The
supplementary figure holds (A) the depth curves of ESMC-6B, (B) the share of an SAE's activity that groups of poles
track, (C) curated labels against Biohub's descriptions, and (D) the concepts of each feature type read by the neurons,
the SAE, both or neither, which does not fit the main figure's page legibly. Every panel is drawn by the function that
drew it before, from the same archive; this module only places panels, shortens in-figure text and puts each key inside
the panels it describes. No in-figure text is smaller than `SMALLEST_TEXT` points.

    PYTHONPATH="<plm_interpretability>;<ws>;<ws>/projects/representation/annotation_vocabulary/src;<ws>/models" \
        py -m plm_interpretability.units.local_figure --root <archive> --tracks <exemplar_concepts/tracks.parquet> \
        --main fig5_neurons.png --supplement supp_units.png
"""

from __future__ import annotations

import argparse
import json
import numpy as np

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from .bootstrap import median_interval
from .experiments import MODEL_NAMES
from .figures import (INK, MUTED, NATIVE, RESIDUAL, ROTATION, SAE, STYLE, RangeGroup, letter, new_figure, residue_summary,
                      save_figure)
from .label_figure import (MODEL_MARKERS, MODELS, agreement_panel, agreement_report, coalition_lines, coverage_inputs,
                           exemplar_inputs, exemplar_rows, route_panel, site_title, track_handles)
from .neuron_figure import (PRECISION, REPLICATION_MODEL, SiteBar, depth_panel, key_handles, metric_panel,
                            metric_site_groups, replication_counts, replication_panel, shared_sae_bars, site_bar_panel,
                            site_bars)


if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure
    from matplotlib.gridspec import GridSpec


WIDTH = 6.3  # inches, the text width of a single-column sn-jnl page
MAIN_HEIGHT = 6.3  # inches, leaving room beneath for a caption of about 200 words
SUPPLEMENT_HEIGHT = 4.0  # inches
SMALLEST_TEXT = 6.0  # points: any smaller in-figure text is raised to this, legible in print
# The kinds of unit as the main figure's key names them, by `neuron_figure.SITE_KINDS` key.
KIND_NAMES = {"residual": "residual stream", "rotations": "random rotations", "searched": "sparsest rotations",
              "mlp_native": "neurons", "stream_sae": "stream SAE", "write_sae": "write SAE"}
# The labeled neurons the main figure draws, one row each. `label_figure.DEFAULT_CONCEPTS` without the LacI-type HTH,
# whose second random carrier stays below its threshold, so three rows fit the page and each shows a clean reading.
MAIN_CONCEPTS = ("Domain_Protein kinase", "Zinc finger_NR C4-type", "Transit peptide_Chloroplast")
# The tracks' key as the main figure names it, in `label_figure.track_handles` order without the leaks, which the
# paper's poles omit and which the tracks barely show.
TRACK_NAMES = ("neuron's activation", "its opposite pole", "threshold", "annotated residues")
# What the tracks' columns are, written once over each group so the panel reads without its caption (Logan,
# 2026-11-18, of a head over every column: "it's confusing. Very confusing."): the proteins that carry the neuron's
# concept, then the one that does not, set apart by a gap.
CARRIER_HEAD, CONTROL_HEAD = "random test proteins with that annotation", "test protein without it"
ROW_HEAD = "neuron's label"  # over the names at the left of the rows
CONTROL_GAP = 0.08  # the gap before the protein without the concept, in widths of a track
AGREEMENT_NAMES = {"global": "protein-level", "local": "residue-level"}  # by `label_figure.AGREEMENT_ARMS` key
DEPTH_SUPPLEMENT_MODEL = "esmc_6b"


# -- layout ------------------------------------------------------------------------------------------------------------


def frame(figure: Figure, *, left: float, right: float, top: float, bottom: float, rows: int = 1, columns: int = 1,
          **spacing: object) -> GridSpec:
    """A grid of axes whose outer edges sit at the given inches, left and right from the figure's left edge, top and
    bottom from its top edge."""
    width, height = figure.get_size_inches()
    assert 0 <= left < right <= width and 0 <= top < bottom <= height, "A frame lies outside the figure."
    return figure.add_gridspec(rows, columns, left=left / width, right=right / width, top=1 - top / height,
                               bottom=1 - bottom / height, **spacing)


def region_letter(figure: Figure, text: str, *, left: float, top: float) -> None:
    """A panel's letter with its right edge at `left` and its baseline at `top`, inches from the figure's left and top
    edges, so the letters of a column align whatever their panels' tick labels."""
    width, height = figure.get_size_inches()
    anchor = figure.add_axes((left / width, 1 - top / height, 0.01, 0.01))
    anchor.set_axis_off()
    letter(anchor, text)


def kind_names(sites: Mapping[str, Sequence[SiteBar]]) -> dict[str, str]:
    """`KIND_NAMES` with each SAE's size in whole thousands of latents, which one kind shares at every site."""
    names = dict(KIND_NAMES)
    for kind in ("stream_sae", "write_sae"):
        sizes = {bar.latents for bars in sites.values() for bar in bars if bar.kind == kind}
        assert len(sizes) == 1, f"The {kind} bars have sizes {sorted(sizes)}, not one size."
        (size,) = sizes
        names[kind] = f"{names[kind]} ({size // 1000}k)"
    return names


def raise_small_text(figure: Figure) -> None:
    """Raise every text of the figure smaller than `SMALLEST_TEXT` points to it."""
    from matplotlib.text import Text

    for text in figure.findobj(Text):
        if text.get_text() and text.get_fontsize() < SMALLEST_TEXT:
            text.set_fontsize(SMALLEST_TEXT)


def figure_key(figure: Figure, handles: Sequence[object], *, left: float, top: float, columns: int) -> None:
    """A key whose top left corner sits at the given inches from the figure's left and top edges."""
    width, height = figure.get_size_inches()
    figure.legend(handles=handles, loc="upper left", bbox_to_anchor=(left / width, 1 - top / height), ncol=columns,
                  handlelength=1.2, handleheight=0.9, handletextpad=0.4, columnspacing=1.1, borderaxespad=0.0,
                  borderpad=0.0)


def group_head(figure: Figure, axes: Sequence[Axes], text: str, *, rise: float = 0.05) -> None:
    """One head over a run of neighboring axes: a rule across their width, `rise` inches above them, and `text`
    centered over it."""
    from matplotlib.lines import Line2D

    height = figure.get_size_inches()[1]
    left, right = axes[0].get_position().x0, axes[-1].get_position().x1
    level = axes[0].get_position().y1 + rise / height
    figure.add_artist(Line2D([left, right], [level, level], transform=figure.transFigure, color=MUTED, linewidth=0.6))
    figure.text((left + right) / 2, level + 0.03 / height, text, ha="center", va="bottom", fontsize=6, color=MUTED)


def depth_key(ax: Axes) -> None:
    """The depth panel's key inside its empty top left: the hue of each line it draws, worst kind first."""
    from matplotlib.lines import Line2D

    handles = [Line2D([], [], color=color, marker="o", markersize=2.5, label=name)
               for name, color in (("residual", RESIDUAL), ("rotation", ROTATION), ("neurons", NATIVE), ("SAE", SAE))]
    ax.legend(handles=handles, loc="upper left", handlelength=1.4, handletextpad=0.4, labelspacing=0.3,
              borderaxespad=0.2)


def coalition_key(ax: Axes) -> None:
    """The pole-fit panel's key in the empty band between its rotated and neuron lines: the bases by line, the models
    by marker."""
    from matplotlib.lines import Line2D

    handles = [Line2D([], [], color=NATIVE, label="neurons"),
               Line2D([], [], color=ROTATION, linestyle=(0, (3, 2)), label="rotation")]
    handles += [Line2D([], [], color=INK, marker=MODEL_MARKERS[model], markersize=2.8, linestyle="none",
                       label=MODEL_NAMES[model]) for model in MODELS]
    ax.legend(handles=handles, loc="lower right", bbox_to_anchor=(1.0, 0.13), ncol=2, handlelength=1.6,
              handletextpad=0.4, columnspacing=1.0, labelspacing=0.3, borderaxespad=0.0)


# -- the figures -------------------------------------------------------------------------------------------------------


def figure_main(root: Path, tracks_path: Path, concepts: Sequence[str] = MAIN_CONCEPTS) -> Figure:
    """Single neurons and their labels: (A) concepts identified at every block of ESMC-600, (B) at three quarters of
    each model's stack, (C) at each layer of ESM2-650M under InterPLM's code, (D) each unit's held-out average
    precision for its best term over whole proteins, and (E) labeled neurons of ESMC-600's block 26 on three random
    test proteins that carry their concept and one that does not. One key above A and B names the kinds of unit of
    A to D; E's key sits above its tracks."""
    import matplotlib

    summary = residue_summary(root)
    sites = shared_sae_bars(site_bars(summary))
    tracks, labels, exemplars, columns = exemplar_inputs(root, tracks_path, concepts=concepts)
    with matplotlib.rc_context(STYLE):
        figure = new_figure(MAIN_HEIGHT, WIDTH)
        figure_key(figure, key_handles(kind_names(sites)), left=0.3, top=0.04, columns=len(KIND_NAMES))
        depth = figure.add_subplot(frame(figure, left=0.5, right=2.5, top=0.42, bottom=1.68)[0])
        depth_panel(depth, summary, "esmc_600")
        bars = figure.add_subplot(frame(figure, left=3.08, right=6.2, top=0.42, bottom=1.68)[0])
        site_bar_panel(bars, sites, sizes=False)  # the key gives each SAE's size, the same at every site
        bars.set_xticks(bars.get_xticks(), list(sites))  # each site's model over its block, on two lines
        bars.tick_params(axis="x", pad=3)
        bars.set_ylabel("concepts identified", labelpad=2)
        replication = figure.add_subplot(frame(figure, left=0.5, right=2.5, top=2.25, bottom=3.45)[0])
        replication_panel(replication, replication_counts(root, REPLICATION_MODEL), model=REPLICATION_MODEL)
        precision = figure.add_subplot(frame(figure, left=3.48, right=6.2, top=2.25, bottom=3.45)[0])
        metric_panel(precision, root, PRECISION)
        precision.set_ylabel("average precision", labelpad=2)
        tracks_left, tracks_top = 1.26, 4.42
        handles = track_handles(leaks=False)
        for handle, name in zip(handles, TRACK_NAMES, strict=True):
            handle.set_label(name)
        figure_key(figure, handles, left=tracks_left, top=4.0, columns=len(handles))
        carriers = len(columns) - 1  # every column but the last, the protein without the concept
        grid = frame(figure, left=tracks_left, right=6.1, top=tracks_top, bottom=5.92, rows=len(exemplars),
                     columns=len(columns) + 1, hspace=0.62, wspace=0.14,
                     width_ratios=[1.0] * carriers + [CONTROL_GAP, 1.0])
        places = [*range(carriers), carriers + 1]  # the gap's column stays empty
        ax_rows = [[figure.add_subplot(grid[row, place]) for place in places] for row in range(len(exemplars))]
        # The groups carry the heads, so no column has its own.
        exemplar_rows(ax_rows, tracks, exemplars, labels, dict.fromkeys(columns, ""), leaks=False)
        group_head(figure, ax_rows[0][:carriers], CARRIER_HEAD)
        group_head(figure, ax_rows[0][carriers:], CONTROL_HEAD)
        first = ax_rows[0][0].get_position()
        figure.text(first.x0 - 0.3 / WIDTH, first.y1 + 0.08 / MAIN_HEIGHT, ROW_HEAD, ha="right", va="bottom", fontsize=6,
                    color=MUTED)
        for ax in ax_rows[-1]:
            ax.set_xlabel("residue", labelpad=1)
        for text, left, top in (("A", 0.28, 0.4), ("B", 2.88, 0.4), ("C", 0.28, 2.23), ("D", 2.88, 2.23),
                                ("E", 0.28, 4.14)):
            region_letter(figure, text, left=left, top=top)
        raise_small_text(figure)
    return figure


def figure_supplement(root: Path) -> Figure:
    """The supplementary figure to `figure_main`: (A) concepts identified at every fourth block of ESMC-6B; (B) the
    share of each model's write-SAE activity that held-out fits of 1 to 64 neuron or rotated poles track; (C) the
    probability that a latent's curated label is closer to its own Biohub description than to a matched one, chance
    dashed; and (D) the concepts of each Swiss-Prot feature type read by the neurons only, both, the write SAE only or
    neither, at three quarters of ESMC-600 and ESMC-6B. Each key sits inside its panel."""
    import matplotlib

    summary = residue_summary(root)
    counts, reports = coverage_inputs(root)
    with matplotlib.rc_context(STYLE):
        figure = new_figure(SUPPLEMENT_HEIGHT, WIDTH)
        depth = figure.add_subplot(frame(figure, left=0.5, right=2.75, top=0.25, bottom=1.6)[0])
        depth_panel(depth, summary, DEPTH_SUPPLEMENT_MODEL)
        depth_key(depth)
        fits = figure.add_subplot(frame(figure, left=3.6, right=6.2, top=0.25, bottom=1.6)[0])
        coalition_lines(fits, reports, right=90.0)
        fits.set_xlabel("poles per fit")
        coalition_key(fits)
        agreement = figure.add_subplot(frame(figure, left=0.95, right=2.3, top=2.3, bottom=3.6)[0])
        agreement_panel(agreement, agreement_report(root), annotate=False, arm_names=AGREEMENT_NAMES)
        agreement.set_xlabel("P(own description closer)")
        grid = frame(figure, left=3.6, right=6.2, top=2.3, bottom=3.6, columns=len(MODELS), wspace=0.08)
        for column, model in enumerate(MODELS):
            coverage = figure.add_subplot(grid[0, column])
            route_panel(coverage, counts[model], labels=column == 0)
            coverage.set_title(site_title(model), loc="left", fontsize=6.5, color=INK, pad=3)
        for text, left, top in (("A", 0.28, 0.23), ("B", 3.1, 0.23), ("C", 0.28, 2.18), ("D", 2.75, 2.18)):
            region_letter(figure, text, left=left, top=top)
        raise_small_text(figure)
    return figure


def caption_numbers(root: Path) -> dict[str, object]:
    """The numbers a caption cites, read from the data the panels draw: each site's bars (`site_bars`), the
    whole-protein medians of panel D, and the coverage totals of each model."""
    summary = residue_summary(root)
    sites = shared_sae_bars(site_bars(summary))
    bars = {site.replace("\n", ", "): {bar.kind if bar.latents is None else f"{bar.kind}_{bar.latents}":
                                       [float(count) for count in bar.counts] for bar in site_bar}
            for site, site_bar in sites.items()}
    groups, names = metric_site_groups(root, PRECISION)
    per_site = len(groups) // len(names)
    precision = {}
    for index, name in enumerate(names):
        for group in groups[index * per_site:(index + 1) * per_site]:
            if isinstance(group, RangeGroup):  # the rotations: the range of their medians
                precision[f"{name}: {group.label}"] = {"median_range": [min(group.medians), max(group.medians)]}
            else:  # the dot `basis_panel` draws: the median and its 95% unit-bootstrap interval
                values = np.asarray(group.values, dtype=np.float64)  # (a,)
                interval = median_interval(values[np.isfinite(values)])
                precision[f"{name}: {group.label}"] = {"median": interval.estimate, "interval": [interval.low,
                                                                                               interval.high]}
    counts, _ = coverage_inputs(root)
    coverage = {model: {route: int(total) for route, total in table.sum().items()} for model, table in counts.items()}
    return {"bars": bars, "precision": precision, "coverage": coverage}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, required=True, help="the neuron study's archive (esmc_native_units_results)")
    parser.add_argument("--tracks", type=Path, required=True,
                        help="the tracks of the exemplar-concepts stage (exemplar_concepts/tracks.parquet)")
    parser.add_argument("--main", type=Path, required=True, help="the main figure's PNG to write")
    parser.add_argument("--supplement", type=Path, required=True, help="the supplementary figure's PNG to write")
    parser.add_argument("--numbers", action="store_true", help="also print the numbers a caption cites")
    arguments = parser.parse_args()
    print(save_figure(figure_main(arguments.root, arguments.tracks), arguments.main))
    print(save_figure(figure_supplement(arguments.root), arguments.supplement))
    if arguments.numbers:
        print(json.dumps(caption_numbers(arguments.root), indent=1))


if __name__ == "__main__":
    main()
