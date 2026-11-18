# Protein Function Prediction via Graph Neural Networks on 3D Residue Graphs

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![PyTorch 2.5+](https://img.shields.io/badge/PyTorch-2.5%2B-ee4c2c.svg)](https://pytorch.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

> **Predicting multi-label Enzyme Commission (EC) catalytic function from experimental 3D protein structures using Contact Graph Convolutional Networks (GCN) and Edge-Conditioned Graph Attention Networks (GAT) evaluated under strict <30% sequence identity homology partitioning.**

---

## 🔬 Scientific Abstract & Problem Statement

Accurate annotation of enzyme catalytic function directly from 3D atomic coordinates is a central challenge in structural biology, protein engineering, and functional genomics. While sequence-based models often fail when functional convergence occurs between structurally homologous yet sequence-divergent proteins, **Graph Neural Networks (GNNs)** operating on residue-level 3D spatial contact networks can directly learn catalytic active-site geometric motifs.

This project implements an end-to-end geometric deep learning framework benchmarked on **4,709 real experimental crystal enzyme chains** combining **CATH 4.2 coordinates**, **RCSB GraphQL `rcsb_ec_lineage` annotations**, and **RCSB 30% sequence-identity clusters**:
1. **Geometric Graph Featurization**: 3D $C_\alpha$ backbone trajectories (chains 40–500 aa with $\ge 85\%$ resolved crystal density) are converted into spatial contact graphs ($r \le 10.0$ Å, $k$-NN $k \le 30$) with 26-dimensional node features (20 amino acid one-hot + 6 backbone pseudo-dihedral $\sin/\cos$ angles) and 17-dimensional edge attributes (16 Gaussian Radial Basis Function distance bins + normalized sequence separation).
2. **Architectures Evaluated**:
   - **1D Dilated Sequence CNN**: Baseline operating purely on primary sequence without 3D geometric awareness.
   - **Contact Graph Convolutional Network (GCN)**: Spatial message passing with edge feature modulation and global attention pooling.
   - **Edge-Conditioned Graph Attention Network (GAT)**: Multi-head attention dynamically weighting residue contacts and active-site topology.
3. **Rigorous Homology Partitioning**: Evaluated on **688 held-out test chains** partitioned strictly at **<30% sequence identity** (`3,578 train / 443 val / 688 test`; `0` cluster overlap) across the Top-25 populated fine-grained EC subclasses spanning EC 1, 2, 3, 4, and 6.

---

## 📊 Benchmark Results (<30% Sequence Identity Test Set)

All models evaluated on the held-out test split of **688 experimental crystal chains** across **25 fine-grained Enzyme Commission subclasses**:

| Model Architecture | Graph Modality | Macro-F1 | Micro-F1 | Macro-MCC | Macro-AUPR | LRAP |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| **1D Dilated CNN Baseline** | 1D Primary Sequence | 0.1322 | 0.1652 | 0.0987 | 0.1196 | 0.3566 |
| **Contact GCN** | 3D Residue Contact Graph | 0.1825 | 0.1930 | 0.1565 | 0.1924 | 0.4323 |
| **Edge-Conditioned GAT** | 3D Attentive Contact Graph | **0.2199** | **0.2227** | **0.2052** | **0.2230** | **0.4510** |

*Hardware: NVIDIA GeForce RTX 5090 (32 GB VRAM), PyTorch 2.11.0+cu128 with mixed precision (AMP bfloat16).*

---

## 📈 Publication-Quality Visualizations

### Figure 1: EC Hierarchy & Multi-Label Class Distribution
![Figure 1: EC Hierarchy](https://github.com/JavierGarcia-Ruiz/protein-function-gnn/raw/HEAD/reports/figures/01_ec_hierarchy_and_distribution.png)
*Panel A: Distribution across EC divisions (`4,709` chains across Oxidoreductases, Transferases, Hydrolases, Lyases, Ligases). Panel B: Frequency ranking of 25 benchmark fine-grained EC subclasses. Panel C: Multi-function co-occurrence conditional probability matrix $P(\text{Column} \mid \text{Row})\%$ (e.g., 22% co-occurrence between EC 2.7.11 and EC 2.7.1).*

---

### Figure 2: Model Benchmark Comparison on Held-Out Test Set (<30% Homology)
![Figure 2: Model Comparison](https://github.com/JavierGarcia-Ruiz/protein-function-gnn/raw/HEAD/reports/figures/02_model_benchmark_comparison.png)
*Comparison of 1D Sequence CNN vs Contact GCN vs Edge-Conditioned GAT across Macro-F1 (Panel A), Matthews Correlation Coefficient (Panel B), and Area Under the Precision-Recall Curve (Panel C).*

---

### Figure 3: Per-Class Precision-Recall Gain (GAT vs 1D CNN)
![Figure 3: Per-Class AUPR](https://github.com/JavierGarcia-Ruiz/protein-function-gnn/raw/HEAD/reports/figures/03_per_class_aupr_comparison.png)
*Per-class AUPR across all 25 fine-grained EC categories, demonstrating the advantage of 3D spatial contact awareness for structurally constrained catalytic pockets.*

---

### Figure 4: Contact Graph & Active-Site Saliency Profile
![Figure 4: Contact Graph Saliency](https://github.com/JavierGarcia-Ruiz/protein-function-gnn/raw/HEAD/reports/figures/04_contact_graph_and_attention_saliency.png)
*Panel A: $C_\alpha$ Euclidean distance matrix for test enzyme chain `153l.A` (`EC 3.2.1`). Panel B: Real trained `ProteinGAT` pooling attention weights highlighting contiguous structural regions (`N82, G85, G92`).*

---

### Figure 5: Structural Properties & Graph Degree Distributions
![Figure 5: Structural Properties](https://github.com/JavierGarcia-Ruiz/protein-function-gnn/raw/HEAD/reports/figures/05_structural_properties_and_graph_degrees.png)
*Panel A: Protein chain length distribution (mean **267 aa**). Panel B: Spatial contact degree distribution ($r < 10$ Å, mean degree **18.1**). Panel C: Pairwise contact distance distribution highlighting the canonical **$3.8$ Å** $C_\alpha\text{–}C_\alpha$ peptide bond peak and **$5.4$ Å** helical turn peak.*

---

### Figure 6: Enzyme Function Latent Space (UMAP Projection)
![Figure 6: Latent Space UMAP](https://github.com/JavierGarcia-Ruiz/protein-function-gnn/raw/HEAD/reports/figures/06_latent_space_umap.png)
*UMAP 2D latent space projection comparing **trained 1D Sequence CNN** vs **trained 3D Contact GAT** on **688 held-out test chains** (<30% sequence identity), colored by primary EC division. 3D Contact GAT improves 5-fold CV 5-NN EC separation from **52.2% -> 57.7%** (+5.5 pp; silhouette: `-0.120` CNN / `-0.161` GAT).*

---

## 🚀 Quickstart & Installation

```powershell
# Activate dedicated conda environment
conda activate protein-function-gnn

# Install package in editable development mode
pip install -e .

# Run test suite
pytest tests/ -v
```

### CLI Prediction
Predict top-ranked Enzyme Commission classes for any protein sequence:
```powershell
python scripts/predict.py --sequence "MALLALSLVALLALSSAQGKPVEVITVKETVETPTVEAPTVETPTVEAPTVETPTVEAPTVDFYVPKYPGTLTLKKDGNKVVVDVKKIKVGDRVVIKNQGDVTAVTLNVGKTVSVKPGT" --top_k 5
```

Output:
```
======================================================================
  PROTEIN FUNCTION GNN: ENZYME COMMISSION (EC) PREDICTION
======================================================================
Sequence Length:   179 aa
Primary Division:  EC 1: Oxidoreductases
----------------------------------------------------------------------
EC Number  | Probability  | Description
----------------------------------------------------------------------
EC 1.1.1   |  22.0% [#####--------------------]       | Dehydrogenases (CH-OH + NAD/NADP)
EC 1.14.13 |  12.1% [###----------------------]       | Oxygenases (NADH/NADPH donor)
EC 1.14.14 |   9.1% [##-----------------------]       | Cytochrome P450 monooxygenases
EC 1.6.5   |   8.0% [##-----------------------]       | NADH:quinone oxidoreductases
EC 2.1.1   |   8.0% [#------------------------]       | Methyltransferases
======================================================================
```

---

## 🧬 Repository Architecture

```
protein-function-gnn/
├── configs/
│   └── default.yaml           # Hyperparameters, graph cutoff, GNN depth
├── data/
│   ├── README.md              # Dataset documentation & split details
│   └── raw/                   # ec_pdb_splits.csv and ec_pdb_splits.npz
├── models/                    # Saved checkpoints (cnn_baseline.pt, gcn.pt, gat.pt)
├── notebooks/
│   ├── 01_eda.ipynb           # EDA: EC distributions & contact maps
│   └── 02_results_analysis.ipynb # Benchmark evaluation & representations
├── reports/
│   ├── figures/               # 6 publication-ready PNG figures (300 DPI)
│   └── results/               # metrics_benchmarks.csv & json predictions
├── scripts/
│   ├── download_data.py       # PDB EC benchmark generator
│   ├── train.py               # Multi-model training pipeline
│   ├── make_figures.py        # Figure generator
│   ├── predict.py             # CLI inference tool
│   └── generate_notebooks.py  # Jupyter notebook generator
├── src/protgnn/
│   ├── data/                  # Graph builders, datasets, collators
│   ├── models/                # GCN, GAT, and CNN architectures
│   ├── evaluation/            # Multi-label F1, MCC, AUPR, LRAP metrics
│   ├── training/              # Mixed-precision PyTorch trainer
│   └── visualization/         # Okabe-Ito color themes & plotting styles
├── tests/                     # Unit test suite (9 tests passing)
└── pyproject.toml             # Build system & dependencies
```

---

## 📜 References
1. Gligorijević, V. et al. "Structure-based protein function prediction using graph convolutional networks." *Nature Communications* 12, 3168 (2021). [DOI: 10.1038/s41467-021-23303-9](https://doi.org/10.1038/s41467-021-23303-9).
2. Veličković, P. et al. "Graph Attention Networks." *ICLR* (2018). [arXiv:1710.10903](https://arxiv.org/abs/1710.10903).
3. Bileschi, M. L. et al. "Using deep learning to annotate the protein universe." *Nature Biotechnology* 40, 932–937 (2022). [DOI: 10.1038/s41587-021-01179-w](https://doi.org/10.1038/s41587-021-01179-w).

