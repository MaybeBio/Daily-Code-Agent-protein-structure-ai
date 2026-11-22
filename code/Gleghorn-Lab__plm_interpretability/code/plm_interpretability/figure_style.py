"""The paper's one naming scheme for probed states, and the marks its interval panels share.

Every state is a family and a part, the part a true subscript: `MLP` and `gate` read as MLP with subscript gate. A
figure names a state in mathtext (`site_math`), a generated LaTeX table with the manuscript's macro (`site_tex`), and
`install` points Protify's drawing code at the scheme without changing Protify: its site labels become mathtext, the
few names its code spells out are replaced when a figure is saved, and a saved figure that still shows an old name
raises. The same `install` swaps in this package's layouts of the figures it names (`cross_model`).

Every figure also takes one look as it is saved, wherever it was drawn: row bands in `ROW_BAND`, shaded intervals with
a stronger fill and a thin edge in the series color (`_strengthen_bands`), and, for the figures Protify sizes itself,
the compact shape of `FIGURE_SHAPES`.

Color means one thing across the paper (`MODEL_COLORS`, `CONTROLS`, the block below them), and every figure takes its
colors from that block.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure


# Each site's family and part; the structure stream alone has no part.
SITE_PARTS = {
    "embedding": ("Resid", "embed"), "resid_mid": ("Resid", "mid"), "resid_post": ("Resid", "post"), "final_norm": ("Resid", "final"),
    "attn_ln": ("Attn", "LN"), "q": ("Attn", "Q"), "k": ("Attn", "K"), "v": ("Attn", "V"), "q_rot": ("Attn", "Qrot"), "k_rot": ("Attn", "Krot"),
    "attn_context": ("Attn", "ctx"), "attn_out": ("Attn", "out"),
    "mlp_ln": ("MLP", "LN"), "mlp_gate": ("MLP", "gate"), "mlp_up": ("MLP", "up"), "mlp_act": ("MLP", "act"), "mlp_out": ("MLP", "out"),
    "structural": ("Struct", ""),
}
# The labels Protify's code names states by. A multi-word label is stale anywhere in a text, a one-word label or a raw
# site key only as the whole text, since the words also appear in axis labels ("MLP minus linear").
STALE_ANYWHERE = ("attn LN", "Attention LN", "Q rotated", "K rotated", "attn context", "attn out", "resid mid", "resid post", "MLP LN", "MLP gate",
                  "MLP up", "MLP act", "MLP out", "final norm", "structure stream", "attn_", "mlp_", "resid_", "final_norm", "q_rot", "k_rot")
STALE_WHOLE = ("embedding", "Q", "K", "V", "structural")
ROW_BAND = "#ece9e2"  # alternating rows of every dot panel, dark enough to contrast with white
PROTIFY_ROW_BAND = "#f6f5f2"  # what Protify's code draws, replaced as a figure is saved
INTERVAL_FILL = 0.24  # opacity of a shaded interval along a line; three overlapping ones stay readable
INTERVAL_EDGE = 0.7  # opacity of its edge, in the series color, which separates overlapping intervals
INTERVAL_EDGE_WIDTH = 0.4
LINE_HALO = 0.7  # the white stroke, in points past the line's width, that lifts a line off its interval
LINE_MINIMUM = 0.9  # thinner lines are reference levels, which take no stroke
LEGEND_HEADROOM = 1.75  # how far `legend_headroom` raises the top of the y axis
PALE_FILL = 0.3  # a filled collection paler than this is a shaded interval; a violin body is not
INTERVAL_BAR = 0.42  # opacity of `interval_marks`' bars, over the row bands
TASK_NAMES = {"ppi": "Interaction (2024)", "ppi2": "Interaction (2026)"}  # the pair tasks, in figures that list tasks
# The kinds of concept, named in full in every figure; these break the long names beside a panel or over a column.
KIND_TAGS = {"secondary structure": "secondary\nstructure", "sorting and topology": "sorting and\ntopology", "InterPro membership": "InterPro\nmembership",
             "residue sites and modifications": "residue sites and\nmodifications"}
KIND_TAG_SIZE = 6.5
KIND_TAG_COLOR = "#2b2b2b"


@dataclass(frozen=True)
class ControlStyle:
    """A control's one look: its gray, its mark on a dot panel and its dash on a line panel."""

    color: str
    marker: str
    dash: str


# -- the paper's one color system -------------------------------------------------------------------------------------
# These three hues mean models and nothing else, in every figure; they are the first three of Protify's palette, which
# colors models by position.
MODEL_COLORS = {"ESMC-300": "#2a78d6", "ESMC-600": "#eb6834", "ESMC-6B": "#1baf7a"}
# Controls are neutral grays with one mark and one dash each, by the name figures show them under.
CONTROLS = {"random init": ControlStyle("#7f7f7f", "s", "--"), "one-hot": ControlStyle("#1f1f1f", "x", ":"), "random vectors": ControlStyle("#b0b0b0", "+", ":"),
            "scrambled": ControlStyle("#c4c4c4", "o", "-"), "untrained": ControlStyle("#c4c4c4", "v", "-.")}
# The hues that mean something other than a model, none near a model's; which meaning a figure gives them is below.
SLATE, GOLD, CRIMSON, CYAN, BROWN, PINK = "#44546a", "#d4a800", "#cc2a41", "#13a8c4", "#8c5a2b", "#e87ba4"
# Probes: what reads a state. A mean-only series is its probe's pale tone, dashed over the series under it.
PROBE_COLORS = {"linear": SLATE, "converged": GOLD, "MLP": CRIMSON, "no activation": CYAN, "quadratic": BROWN}
MEAN_ONLY_COLORS = {"linear": "#9db0c6", "MLP": "#f4a3ae"}
KIND_COLORS = {"sorting and topology": GOLD, "InterPro membership": CRIMSON, "function": SLATE}
STRUCTURE_COLORS = {"helix": CRIMSON, "strand": GOLD, "coil": SLATE}
LABEL_SET_COLORS = (CRIMSON, SLATE, GOLD, CYAN, PINK)  # the principal coordinates' label sets, most frequent first
OTHER_SERIES = (CRIMSON, GOLD, SLATE, CYAN, BROWN, PINK)  # any other series a figure tells apart by color
# The published-predictors figure: what each row of this study reads, as (tuned MLP, survey linear), and its methods.
READ_STATE_COLORS = {"inside": (CRIMSON, "#efb2ba"), "stream": (GOLD, "#f1e29c"), "last": (CYAN, "#a9e0ea"), "control": ("#bdbdbd", "#e3e3e3")}
PUBLISHED_COLOR = "#6f3fc0"  # violet: no other figure uses it, so the published predictors stand out
# The block's families, as the manuscript's overview schematic draws them (its `resid`, `attn` and `mlpc` colors).
FAMILY_COLORS = {"stream": "#5f7183", "attention": "#c4627c", "feed-forward": "#4d958d"}


@dataclass(frozen=True)
class FigureShape:
    """How a figure Protify draws is finished as it is saved: `size` in inches (the layout is redone), row bands on the
    axes `band_axes` (by position in `figure.axes`), the axes legend in one row of `legend_columns`, the first `letters`
    axes lettered, at most `max_x_ticks` ticks on the x axes, with `legend_headroom` an axes legend moved into new
    headroom above the data, and, with `task_map`, a grid of task maps whose colorbar and key move into its empty cells
    and whose over-panel values lose their word."""

    size: tuple[float, float] | None = None
    band_axes: tuple[int, ...] = ()
    legend_columns: int | None = None
    letters: int = 0
    max_x_ticks: int | None = None
    legend_headroom: bool = False
    task_map: bool = False


FIGURE_SHAPES = {
    "controls_summary.png": FigureShape(size=(7.2, 3.9), legend_columns=8),
    "model_size.png": FigureShape(size=(7.2, 4.2)),
    "variants_dots.png": FigureShape(size=(7.2, 4.1), max_x_ticks=6),
    "rotation.png": FigureShape(size=(5.4, 3.5), band_axes=(0,)),
    "random_init_summary.png": FigureShape(size=(7.2, 4.6), band_axes=(1,)),
    "site_families.png": FigureShape(size=(7.2, 4.6), legend_columns=4),
    "phospho.png": FigureShape(legend_headroom=True),
    "site_maps.png": FigureShape(task_map=True),
    "random_init_maps.png": FigureShape(task_map=True),
    "emergence.png": FigureShape(letters=3),
}
SHAPE_PREFIXES = {"variants_summary": FigureShape(band_axes=(1,))}  # the MLP's sites beside its best probes
MAP_GRID = (4, 1.55)  # the task maps' columns and row height in Protify's code
COMPACT_MAP_GRID = (6, 1.5)
PROTEIN_TASKS = 13  # six columns leave one panel alone on a third row
PROTEIN_TASK_COLUMNS = 7
MAP_SITE_SIZE = 4.2  # the maps' site labels, one per row of a shorter panel


def site_math(site: str) -> str:
    """A site's name in a figure, in mathtext: `$\\mathrm{MLP}_{\\mathrm{gate}}$`."""
    family, part = SITE_PARTS[site]
    return rf"$\mathrm{{{family}}}_{{\mathrm{{{part}}}}}$" if part else rf"$\mathrm{{{family}}}$"


def site_tex(site: str) -> str:
    """A site's name in a generated LaTeX table, with the manuscript's macro: `\\site{MLP}{gate}`."""
    family, part = SITE_PARTS[site]
    return rf"\site{{{family}}}{{{part}}}"


# The names Protify's code spells out instead of reading its site labels.
SPELLED_OUT = {"resid post": site_math("resid_post"), "final norm": site_math("final_norm")}


def stale_names(texts: Sequence[str]) -> list[str]:
    """The texts that still show a state under an old name."""
    return [text for text in texts if text in STALE_WHOLE or any(name in text for name in STALE_ANYWHERE)]


def _relabel(figure: Figure) -> None:
    """Replace the names Protify's code spells out, then raise on any old name left in the figure."""
    from matplotlib.text import Text

    figure.canvas.draw()  # tick labels hold their text only once drawn
    texts = figure.findobj(Text)
    for text in texts:
        if text.get_text() in SPELLED_OUT:
            text.set_text(SPELLED_OUT[text.get_text()])
    stale = stale_names([text.get_text() for text in texts])
    if stale:
        raise ValueError(f"A figure still names states the old way: {sorted(set(stale))}.")


def _strengthen_bands(figure: Figure) -> None:
    """Give every figure the same contrast: Protify's row bands in `ROW_BAND`, its pale connectors between row marks
    visible on them, and each shaded interval a stronger fill with a thin edge in its own color."""
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import to_rgba
    from matplotlib.patheffects import withStroke
    from src.protify.interpretability.figures import GRID, MUTED

    pale = to_rgba(PROTIFY_ROW_BAND)
    band = to_rgba(ROW_BAND)
    for axis in figure.axes:
        banded, intervals = False, False
        for patch in axis.patches:
            if patch.get_facecolor() in (pale, band):
                patch.set_facecolor(ROW_BAND)
                banded = True
        if banded:
            axis.tick_params(axis="y", length=0)
        for line in axis.lines:
            if line.get_color() == GRID and line.get_linewidth() >= 1.5:
                line.set_color(MUTED)
                line.set_linewidth(1.2)
        for collection in axis.collections:
            opacity = collection.get_alpha()
            if isinstance(collection, PolyCollection) and opacity is not None and opacity < PALE_FILL:
                red, green, blue, _ = collection.get_facecolor()[0]
                collection.set_alpha(None)
                collection.set_facecolor((red, green, blue, INTERVAL_FILL))
                collection.set_edgecolor((red, green, blue, INTERVAL_EDGE))
                collection.set_linewidth(INTERVAL_EDGE_WIDTH)
                intervals = True
        if intervals:
            for line in axis.lines:
                if line.get_linestyle() == "-" and line.get_linewidth() >= LINE_MINIMUM:  # a dashed line's halo speckles
                    line.set_path_effects([withStroke(linewidth=line.get_linewidth() + LINE_HALO, foreground="white")])


def _add_row_bands(axis: Axes) -> None:
    """Row bands on a panel Protify drew without them, from its y ticks or, where it hid them beside a labeled map, its
    limits; rows are the integers, and the top row is banded."""
    ticks = axis.get_yticks()
    rows = len(ticks) if len(ticks) else round(max(axis.get_ylim()) + 0.4)
    for row in range(rows - 1, -1, -2):
        axis.axhspan(row - 0.5, row + 0.5, color=ROW_BAND, lw=0, zorder=-1)  # under Protify's connectors, drawn at zorder 0
    axis.set_ylim(-0.5, rows - 0.5)


def _finish_task_map(figure: Figure) -> None:
    """A grid of task maps: panels to the figure's edge, the colorbar and any key in the grid's empty cells, shorter
    site labels, and each map's value without its word (`max 0.99` is `0.99`)."""
    hidden = [axis for axis in figure.axes if not axis.get_visible()]
    if len(hidden) < 2:
        raise ValueError(f"A task map needs two empty cells for its colorbar and key; it has {len(hidden)}.")
    figure.subplots_adjust(right=0.995)
    for axis in figure.axes:
        if axis.get_visible() and axis.images:
            for label in axis.get_yticklabels():
                label.set_fontsize(MAP_SITE_SIZE)
            for text in axis.texts:
                text.set_text(text.get_text().removeprefix("max ").removeprefix("mean "))
    cell = hidden[0].get_position()
    bar = figure.axes[-1]
    bar.set_position((cell.x0 + 0.3 * cell.width, cell.y0, 0.09 * cell.width, cell.height))
    for legend in figure.legends:
        key = hidden[1].get_position()
        legend.set_bbox_to_anchor((key.x0, key.y0 + key.height / 2), transform=figure.transFigure)
        legend.set_loc("center left")


def _finish_shape(figure: Figure, path: Path) -> None:
    """The figure's `FIGURE_SHAPES` entry, if it has one."""
    from matplotlib.ticker import MaxNLocator
    from src.protify.interpretability.figures import _letter

    name = Path(path).name
    prefix = next((shape for start, shape in SHAPE_PREFIXES.items() if name.startswith(start)), None)
    shape = FIGURE_SHAPES.get(name, prefix)
    if shape is None:
        return
    for index in shape.band_axes:
        _add_row_bands(figure.axes[index])
    if shape.legend_columns is not None:
        for axis in figure.axes:
            legend = axis.get_legend()
            if legend is not None:
                axis.legend(legend.legend_handles, [text.get_text() for text in legend.get_texts()], loc="lower center", bbox_to_anchor=(0.5, 1.0),
                            ncol=shape.legend_columns, frameon=False, fontsize=5.3, handletextpad=0.2, columnspacing=0.8)
    if shape.legend_headroom:
        for axis in figure.axes:
            if axis.get_legend() is not None:
                low, high = axis.get_ylim()
                axis.set_ylim(low, low + LEGEND_HEADROOM * (high - low))
                axis.get_legend().set_loc("upper center")
    if shape.size is not None:
        figure.set_size_inches(*shape.size)
        figure.tight_layout(w_pad=0.6, h_pad=0.6)
    for axis, letter in zip(figure.axes[:shape.letters], "ABCDEFGH", strict=False):
        _letter(axis, letter, x=-0.02)
    if shape.max_x_ticks is not None:
        for axis in figure.axes:
            axis.xaxis.set_major_locator(MaxNLocator(shape.max_x_ticks))
    if shape.task_map:
        _finish_task_map(figure)


def install() -> None:
    """Point Protify's labels, category bands, task names, saving and pair figure at this package's; safe to call twice.
    Figures drawn before this call keep Protify's look."""
    from src.protify.interpretability import figures, trends

    from plm_interpretability import cross_model

    missing = set(figures.SITE_LABELS) ^ set(SITE_PARTS)
    if missing:
        raise ValueError(f"Protify's sites and the naming scheme differ on {sorted(missing)}.")
    figures.SITE_LABELS.update({site: site_math(site) for site in SITE_PARTS})  # in place: other modules hold this dict
    figures.SHORT_LABELS.update(TASK_NAMES)
    if tuple(MODEL_COLORS.values()) != figures.PALETTE[:3]:
        raise ValueError(f"Protify colors models by {figures.PALETTE[:3]}, which `MODEL_COLORS` must equal.")
    trends.pair_figure = cross_model.pair_figure
    trends._category_bands = cross_model.category_bands
    trends.emergence_maps = cross_model.emergence_maps
    trends.controls_summary = cross_model.controls_summary
    figures.variant_depth_curves = cross_model.variant_depth_curves
    figures.pca_grid = cross_model.pca_grid
    figures.phospho_figure = cross_model.phospho_figure
    if getattr(figures._save, "relabels", False):
        return
    protify_save = figures._save
    protify_grid = figures._grid
    protify_target = figures.target_label

    def save(figure: Figure, path: Path) -> Path:
        _finish_shape(figure, path)
        _strengthen_bands(figure)
        _relabel(figure)
        return protify_save(figure, path)

    def grid(plt: object, count: int, columns: int, width: float = 7.2, row_height: float = 1.25, **kwargs: object) -> tuple[Figure, list[Axes]]:
        if (columns, row_height) == MAP_GRID:
            columns, row_height = COMPACT_MAP_GRID
        if (count, columns) == (PROTEIN_TASKS, 6):
            columns = PROTEIN_TASK_COLUMNS
        return protify_grid(plt, count, columns, width, row_height, **kwargs)

    def target(name: str) -> str:
        return protify_target(name).replace("charge at pH", "charge, pH")  # fits over its small multiple

    save.relabels = True
    figures._save = save
    figures._grid = grid
    figures.target_label = target


def row_bands(axis: Axes, rows: int) -> None:
    """Alternating bands behind the rows of a dot panel, in place of horizontal gridlines; ends with the first row at
    the top."""
    for row in range(0, rows, 2):
        axis.axhspan(row - 0.5, row + 0.5, color=ROW_BAND, lw=0, zorder=0)
    axis.set_ylim(rows - 0.5, -0.5)
    axis.tick_params(axis="y", length=0)


def interval_marks(axis: Axes, values: pd.Series | np.ndarray, rows: np.ndarray, lows: pd.Series | np.ndarray, highs: pd.Series | np.ndarray,
                   color: str, size: float = 9.0, marker: str = "o") -> None:
    """Estimates as marks, dots unless a control's, each on a soft bar spanning its interval, along the x axis."""
    # values, rows, lows, highs: (n,) each
    axis.hlines(rows, lows, highs, color=color, lw=2.2, alpha=INTERVAL_BAR, zorder=2, capstyle="round")
    edge = {"linewidths": 0.8} if marker in ("x", "+") else {"edgecolors": "white", "linewidths": 0.3}  # a line mark has no fill to outline
    axis.scatter(values, rows, s=size, color=color, marker=marker, zorder=3, **edge)


def kind_tag(axis: Axes, y: float, kind: str, transform: object) -> None:
    """A kind of concept named once beside its rows, at `y` under `transform`, past the panel's right edge."""
    axis.text(1.01, y, KIND_TAGS.get(kind, kind), transform=transform, fontsize=KIND_TAG_SIZE, color=KIND_TAG_COLOR, va="center", ha="left", linespacing=0.95)
