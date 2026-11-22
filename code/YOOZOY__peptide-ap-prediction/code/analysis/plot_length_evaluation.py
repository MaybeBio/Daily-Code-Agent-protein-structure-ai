"""Plot the aggregate metrics written to results/length_evaluation/by_length.csv."""

from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.ticker import MaxNLocator, PercentFormatter


ROOT = Path(__file__).resolve().parents[1]
MODEL_STYLES = {
    "MLP": {"color": "#A64800", "marker": "s", "linestyle": ":"},
    "LSTM": {"color": "#007C63", "marker": "^", "linestyle": "--"},
    "Transformer": {"color": "#205EA6", "marker": "o", "linestyle": "-"},
}


def main():
    rows = pd.read_csv(ROOT / "results" / "length_evaluation" / "by_length.csv")
    table = rows.pivot(index="length", columns="model", values=["mae", "mae_skill"]).sort_index()
    fig, (absolute, relative) = plt.subplots(1, 2, figsize=(9.4, 4.7), sharex=True)
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.24, top=0.75, wspace=0.28)

    for model, style in MODEL_STYLES.items():
        for axis, metric in [(absolute, "mae"), (relative, "mae_skill")]:
            axis.plot(
                table.index, table[metric, model], label=model, linewidth=2,
                markersize=7, markerfacecolor="white", markeredgewidth=1.5, **style,
            )

    absolute.set_title("A    Absolute prediction error", loc="left", fontsize=13, fontweight="bold")
    relative.set_title("B    Improvement over baseline", loc="left", fontsize=13, fontweight="bold")
    absolute.set_ylabel("Mean absolute error (AP units)")
    relative.set_ylabel("Reduction in mean absolute error")
    relative.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    for axis in (absolute, relative):
        axis.set_xlabel("Peptide length (residues)")
        axis.set_xticks(table.index)
        axis.margins(x=0.07, y=0.12)
        axis.yaxis.set_major_locator(MaxNLocator(nbins=5))
        axis.grid(axis="y", color="#DDE3E8", linewidth=0.8)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
        axis.spines[["bottom", "left"]].set_color("#81909B")
        axis.tick_params(length=3, color="#81909B")

    handles, labels = absolute.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, frameon=False,
               bbox_to_anchor=(0.5, 0.98), handlelength=2.7)
    fig.text(0.09, 0.05, "The baseline predicts the median training AP for each length. "
             "Error reduction = 1 − model MAE / baseline MAE.", fontsize=9)
    fig.savefig(ROOT / "figures" / "error_relative_to_length_baseline.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
