"""Generate well-documented Jupyter notebooks for exploratory data analysis and results analysis."""

from __future__ import annotations

import json
from pathlib import Path

NOTEBOOKS_DIR = Path("notebooks")
NOTEBOOKS_DIR.mkdir(parents=True, exist_ok=True)


def make_notebook(cells: list[dict], path: Path) -> None:
    nb = {
        "cells": cells,
        "metadata": {
            "language_info": {"name": "python", "version": "3.11.0"},
            "kernelspec": {"display_name": "Python 3.11", "language": "python", "name": "python3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(nb, f, indent=2)
    print(f"Generated {path}")


def create_eda_notebook() -> None:
    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# 01: Exploratory Data Analysis — PDB Enzyme Commission Benchmark\n",
                "\n",
                "This notebook explores the curated PDB Enzyme Commission (EC) dataset partitioned under **<30% sequence identity** homology splitting.\n",
                "\n",
                "**Key questions explored**:\n",
                "1. What is the frequency distribution of the 7 major enzyme divisions (EC 1 to 7)?\n",
                "2. How do sequence lengths and 3D contact degrees distribute across the fold space?\n",
                "3. What are the multi-label co-occurrence patterns between multi-functional enzymes?\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "from pathlib import Path\n",
                "import numpy as np\n",
                "import pandas as pd\n",
                "import matplotlib.pyplot as plt\n",
                "import seaborn as sns\n",
                "\n",
                "from protgnn.data.constants import EC_CLASSES, EC_DESCRIPTIONS, EC_TOP_CLASSES, EC_PRIMARY_COLORS\n",
                "from protgnn.visualization.plotting import set_style\n",
                "\n",
                "set_style()\n",
                "data_path = Path('../data/raw/ec_pdb_splits.csv')\n",
                "df = pd.read_csv(data_path)\n",
                "print(f'Total proteins: {len(df):,}')\n",
                "df.head()\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 1. Top-Level Enzyme Commission Division Breakdown\n",
                "\n",
                "Enzymes are classified into 7 primary catalytic categories:\n",
                "- **EC 1**: Oxidoreductases\n",
                "- **EC 2**: Transferases\n",
                "- **EC 3**: Hydrolases\n",
                "- **EC 4**: Lyases\n",
                "- **EC 5**: Isomerases\n",
                "- **EC 6**: Ligases\n",
                "- **EC 7**: Translocases\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "top_counts = {i: 0 for i in range(1, 8)}\n",
                "for ec_str in df['ec_annotations']:\n",
                "    for ec in ec_str.split('; '):\n",
                "        top_digit = int(ec.split('.')[0])\n",
                "        if top_digit in top_counts:\n",
                "            top_counts[top_digit] += 1\n",
                "\n",
                "fig, ax = plt.subplots(figsize=(9, 4.5))\n",
                "names = [EC_TOP_CLASSES[i-1] for i in range(1, 8)]\n",
                "counts = [top_counts[i] for i in range(1, 8)]\n",
                "colors = [EC_PRIMARY_COLORS[i] for i in range(1, 8)]\n",
                "\n",
                "ax.barh(names, counts, color=colors, alpha=0.85)\n",
                "ax.set_xlabel('Number of Annotated Domains')\n",
                "ax.set_title('Distribution of Top-Level Enzyme Divisions')\n",
                "ax.invert_yaxis()\n",
                "plt.tight_layout()\n",
                "plt.show()\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 2. 3D Contact Map Inspection\n",
                "\n",
                "We can inspect the spatial C-alpha contact map for a sample enzyme.\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "npz_path = Path('../data/raw/ec_pdb_splits.npz')\n",
                "data = np.load(npz_path, allow_pickle=True)\n",
                "coords = data['coords'][0]\n",
                "seq = data['sequences'][0]\n",
                "pdb = data['pdb_chains'][0]\n",
                "\n",
                "dist_matrix = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=-1)\n",
                "contact_map = (dist_matrix < 10.0).astype(float)\n",
                "\n",
                "fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))\n",
                "im1 = ax1.imshow(dist_matrix, cmap='viridis_r', origin='upper')\n",
                "ax1.set_title(f'Distance Matrix ({pdb}, L={len(seq)})')\n",
                "fig.colorbar(im1, ax=ax1, fraction=0.046, pad=0.04)\n",
                "\n",
                "im2 = ax2.imshow(contact_map, cmap='Greys', origin='upper')\n",
                "ax2.set_title('Binary Contact Map (< 10 Å)')\n",
                "fig.colorbar(im2, ax=ax2, fraction=0.046, pad=0.04)\n",
                "plt.tight_layout()\n",
                "plt.show()\n",
            ],
        },
    ]
    make_notebook(cells, NOTEBOOKS_DIR / "01_eda.ipynb")


def create_results_notebook() -> None:
    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# 02: Model Benchmark & Representation Analysis\n",
                "\n",
                "This notebook benchmarks **1D Dilated CNN (sequence baseline)** against **Contact GCN** and **Edge-Attentive GAT (3D graph models)** on held-out test proteins (<30% sequence homology).\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "from pathlib import Path\n",
                "import numpy as np\n",
                "import pandas as pd\n",
                "import matplotlib.pyplot as plt\n",
                "import seaborn as sns\n",
                "\n",
                "from protgnn.data.constants import EC_CLASSES, EC_DESCRIPTIONS\n",
                "from protgnn.visualization.plotting import set_style\n",
                "\n",
                "set_style()\n",
                "bench_path = Path('../reports/results/metrics_benchmarks.csv')\n",
                "df_bench = pd.read_csv(bench_path)\n",
                "df_bench\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 1. Multi-Metric Benchmark Comparison\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))\n",
                "metrics = [('macro_f1', 'Macro-F1'), ('macro_mcc', 'Macro-MCC'), ('macro_aupr', 'Macro-AUPR')]\n",
                "for ax, (m, label) in zip(axes, metrics):\n",
                "    sns.barplot(data=df_bench, x='experiment', y=m, ax=ax, palette='Blues_d')\n",
                "    ax.set_title(label)\n",
                "    ax.set_ylim(0, 1.0)\n",
                "plt.tight_layout()\n",
                "plt.show()\n",
            ],
        },
    ]
    make_notebook(cells, NOTEBOOKS_DIR / "02_results_analysis.ipynb")


def main() -> None:
    create_eda_notebook()
    create_results_notebook()


if __name__ == "__main__":
    main()

