"""Shared portfolio plotting style for Protein Function GNN."""

from __future__ import annotations

from pathlib import Path
import matplotlib as mpl
import matplotlib.pyplot as plt
import seaborn as sns

OKABE_ITO = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#F0E442", "#000000"]
EXTENDED = OKABE_ITO + ["#882255", "#44AA99", "#999933", "#AA4499"]


def set_style() -> None:
    """Apply the shared seaborn/matplotlib theme."""
    sns.set_theme(context="notebook", style="ticks", palette=OKABE_ITO)
    mpl.rcParams.update(
        {
            "figure.dpi": 110,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "savefig.facecolor": "white",
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.titleweight": "bold",
            "axes.labelsize": 11,
            "legend.fontsize": 9,
            "legend.frameon": False,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.25,
        }
    )


def save(fig: plt.Figure, path: str | Path) -> None:
    """Save a figure as PNG (300 dpi) and close it."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def panel_label(ax: plt.Axes, letter: str, x: float = -0.12, y: float = 1.06) -> None:
    """Add a bold panel letter (A, B, ...) to the top-left corner of an axis."""
    ax.text(x, y, letter, transform=ax.transAxes, fontsize=15, fontweight="bold", va="bottom")

