"""E16's figure: ESMC-600 with a fixed set of units in every block, against ESMC-300.

    python -m plm_interpretability.units.e16_figures --root RUN --out FOLDER

Reads a copy of E16's folders of the run (`prune_static`, `prune_heal`, `prune_probes`) and E15b's `sparsify`, and draws
`e16_pruning.png`: the masked-token loss as fewer units are kept, for each residue's own largest units (E15b) and for
fixed sets; how often each unit is among its block's largest; and the masked-token loss and the mean supervised
metric of each model. No title, lettered panels; the caption carries the rest.
"""

from __future__ import annotations

import argparse
import json
import matplotlib
import numpy as np
import pandas as pd

from pathlib import Path
from typing import TYPE_CHECKING

from .figures import INK, MUTED, NATIVE, ROTATION, SAE, STYLE, letter, new_figure, save_figure


if TYPE_CHECKING:
    from matplotlib.figure import Figure


TOP = 1_024  # the count of a token's largest activations that `units.parquet`'s top_share was read at
# The fixed set that training starts from is one color in every panel: the least-error set, refitted.
FIXED_SETS = {("top_share", "none"): ("fixed, by rank", ROTATION, "s"), ("obs", "refit"): ("fixed, by error", SAE, "o")}
MODELS = {"esmc_600": ("ESMC-600", INK), "esmc_300": ("ESMC-300", MUTED), "pruned_static": ("fixed set", SAE),
          "pruned_healed": ("fixed set,\ntrained", NATIVE)}


def figure_pruning(root: Path) -> Figure:
    static = pd.read_parquet(root / "prune_static" / "prune_static.parquet")
    receipt = json.loads((root / "prune_static" / "receipt.json").read_text(encoding="utf-8"))
    units = pd.read_parquet(root / "prune_static" / "units.parquet")
    probes = pd.read_parquet(root / "prune_probes" / "prune_probes.parquet")
    test = static[static["split"] == "test"]
    figure = new_figure(2.3)
    axes = figure.subplots(1, 4, gridspec_kw={"wspace": 0.6, "left": 0.07, "right": 0.99, "bottom": 0.24, "top": 0.9,
                                              "width_ratios": (1.35, 1, 1, 1)})

    whole = units["unit"].max() + 1
    cut = pd.read_parquet(root / "sparsify" / "sparsify.parquet")
    by_residue = cut[(cut["scope"] == "all") & (cut["basis"] == "native") & (cut["kept"] >= 256)].sort_values("kept")
    axes[0].plot(by_residue["kept"], by_residue["loss"], color=INK, marker="^", markersize=3, linewidth=1, label="per residue")
    for (order, repair), (label, color, marker) in FIXED_SETS.items():
        rows = test[(test["order"] == order) & (test["repair"] == repair)].sort_values("width")
        axes[0].plot(rows["width"], rows["loss"], color=color, marker=marker, markersize=3, linewidth=1, label=label)
    for model, style in (("esmc_600", ":"), ("esmc_300", "--")):
        axes[0].axhline(float(test.loc[test["model"] == model, "loss"].iloc[0]), color=MUTED, linewidth=0.6, linestyle=style)
    axes[0].set_xscale("log", base=2)
    axes[0].set_xticks((256, 512, 1024, 2048), ("256", "512", "1,024", "2,048"))
    axes[0].set_xlabel(f"units kept of {whole:,}")
    axes[0].set_ylabel("masked-token loss (nats)")
    axes[0].set_ylim(top=3.25)
    axes[0].legend(loc="upper left", handlelength=1.4, borderaxespad=0.3)

    axes[1].hist(units["top_share"], bins=np.linspace(0, 1, 41), weights=np.full(len(units), 100 / len(units)), color=MUTED)
    axes[1].axvline(TOP / whole, color=INK, linewidth=0.6, linestyle="--")
    axes[1].set_xlabel("share of tokens among\nthe block's largest third")
    axes[1].set_ylabel("units (%)")

    losses = {"esmc_600": float(test.loc[test["model"] == "esmc_600", "loss"].iloc[0]),
              "esmc_300": float(test.loc[test["model"] == "esmc_300", "loss"].iloc[0]),
              "pruned_static": float(test.loc[test["model"] == f"{receipt['chosen']['order']}_{receipt['chosen']['repair']}_"
                                                                  f"{receipt['matched_width']}", "loss"].iloc[0])}
    healed = root / "prune_heal" / "pruned" / "prune_heal.parquet"
    if healed.exists():
        rows = pd.read_parquet(healed)
        losses["pruned_healed"] = float(rows.loc[rows["split"] == "test", "loss"].iloc[0])
    means = probes.groupby("model")["primary"].mean()
    for ax, values, label in ((axes[2], losses, "masked-token loss (nats)"), (axes[3], means.to_dict(), "mean test metric, 13 tasks")):
        shown = [model for model in MODELS if model in values]
        ax.bar(range(len(shown)), [values[model] for model in shown], color=[MODELS[model][1] for model in shown], width=0.7)
        ax.set_xticks(range(len(shown)), [MODELS[model][0] for model in shown], rotation=30, ha="right")
        ax.set_ylabel(label)
    axes[2].set_ylim(1.8, 2.7)
    low = min(means[model] for model in MODELS if model in means)
    axes[3].set_ylim(np.floor(low * 50) / 50 - 0.02, np.ceil(means.max() * 50) / 50 + 0.01)
    for ax, text in zip(axes, "ABCD", strict=True):
        letter(ax, text)
    return figure


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    options = parser.parse_args()
    with matplotlib.rc_context(STYLE):
        print(save_figure(figure_pruning(options.root), options.out / "e16_pruning.png"))


if __name__ == "__main__":
    main()
