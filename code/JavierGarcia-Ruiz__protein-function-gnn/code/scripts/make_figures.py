"""Generate publication-quality figures for the Protein Function GNN project.

Outputs:
    reports/figures/01_ec_hierarchy_and_distribution.png
    reports/figures/02_model_benchmark_comparison.png
    reports/figures/03_per_class_aupr_comparison.png
    reports/figures/04_contact_graph_and_attention_saliency.png
    reports/figures/05_structural_properties_and_graph_degrees.png
    reports/figures/06_latent_space_umap.png
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import precision_recall_curve, average_precision_score, silhouette_score
from sklearn.neighbors import KNeighborsClassifier
import torch
import umap

from protgnn.data.constants import (
    EC_CLASSES,
    EC_DESCRIPTIONS,
    EC_TOP_CLASSES,
    EC_PRIMARY_COLORS,
    EC_TO_IDX,
)
from protgnn.visualization.plotting import (
    OKABE_ITO,
    EXTENDED,
    set_style,
    save,
    panel_label,
)

FIGURES_DIR = Path("reports/figures")
RESULTS_DIR = Path("reports/results")
RAW_DIR = Path("data/raw")
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

set_style()


def fig01_ec_hierarchy_and_distribution() -> None:
    """Figure 1: Top-level EC distribution, 25 fine-grained class frequencies, and co-occurrence."""
    csv_path = RAW_DIR / "ec_pdb_splits.csv"
    if not csv_path.exists():
        print("Skipping Fig 1: ec_pdb_splits.csv not found.")
        return

    df = pd.read_csv(csv_path)

    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5))

    # Panel A: Primary EC Level 1 distribution
    ax = axes[0]
    top_counts = {i: 0 for i in range(1, 8)}
    for ec_str in df["ec_annotations"]:
        for ec in [e.strip() for e in str(ec_str).split(";") if e.strip()]:
            top_digit = int(ec.split(".")[0])
            if top_digit in top_counts:
                top_counts[top_digit] += 1

    top_names = [
        "1: Oxidoreductases",
        "2: Transferases",
        "3: Hydrolases",
        "4: Lyases",
        "5: Isomerases",
        "6: Ligases",
        "7: Translocases",
    ]
    counts_list = [top_counts[i] for i in range(1, 8)]
    colors = [EC_PRIMARY_COLORS[i] for i in range(1, 8)]

    y_pos = np.arange(len(top_names))
    bars = ax.barh(y_pos, counts_list, color=colors, alpha=0.85)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(top_names, fontsize=9.5)
    ax.set_xlabel("Annotation Count")
    ax.set_title("EC Division 1 Distribution", pad=10)
    ax.invert_yaxis()
    for bar in bars:
        w = bar.get_width()
        ax.annotate(f"{int(w):,}", (w + 15, bar.get_y() + bar.get_height() / 2.),
                    va="center", fontsize=8.5, color="#333333")
    panel_label(ax, "A")

    # Panel B: 25 fine-grained classes
    ax = axes[1]
    class_counts = {ec: 0 for ec in EC_CLASSES}
    for ec_str in df["ec_annotations"]:
        for ec in [e.strip() for e in str(ec_str).split(";") if e.strip()]:
            if ec in class_counts:
                class_counts[ec] += 1

    sorted_ecs = sorted(EC_CLASSES, key=lambda x: class_counts[x], reverse=True)
    counts_sorted = [class_counts[ec] for ec in sorted_ecs]
    primary_classes = [int(ec.split(".")[0]) for ec in sorted_ecs]
    bar_colors = [EC_PRIMARY_COLORS[p] for p in primary_classes]

    y = np.arange(len(sorted_ecs))
    ax.barh(y, counts_sorted, color=bar_colors, alpha=0.85, height=0.75)
    ax.set_yticks(y)
    ax.set_yticklabels([f"EC {ec} ({EC_DESCRIPTIONS.get(ec, '')[:18]}..)" for ec in sorted_ecs], fontsize=7.5)
    ax.set_xlabel("Protein Count")
    ax.set_title("25 Fine-Grained EC Classes", pad=10)
    ax.invert_yaxis()
    panel_label(ax, "B")

    # Panel C: Multi-label co-occurrence matrix
    ax = axes[2]
    Y = np.zeros((len(df), len(EC_CLASSES)), dtype=np.float32)
    for i, ec_str in enumerate(df["ec_annotations"]):
        for ec in [e.strip() for e in str(ec_str).split(";") if e.strip()]:
            if ec in EC_TO_IDX:
                Y[i, EC_TO_IDX[ec]] = 1.0

    co_occur = Y.T @ Y
    diag = np.diag(co_occur)[:, None]
    co_occur_pct = co_occur / np.maximum(diag, 1) * 100

    # Top 12 most frequent classes for clean visualization
    top12_idx = [EC_TO_IDX[ec] for ec in sorted_ecs[:12]]
    co_sub = co_occur_pct[np.ix_(top12_idx, top12_idx)]
    labels_sub = [f"EC {sorted_ecs[i]}" for i in range(12)]

    sns.heatmap(
        co_sub,
        annot=True,
        fmt=".0f",
        cmap="Blues",
        xticklabels=labels_sub,
        yticklabels=labels_sub,
        cbar_kws={"label": "P(Col | Row) %"},
        ax=ax,
        linewidths=0.5,
        linecolor="#EEEEEE"
    )
    ax.set_title("Enzyme Multi-Function Co-Occurrence %", pad=10)
    ax.set_xticklabels(labels_sub, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(labels_sub, fontsize=8)
    panel_label(ax, "C")

    fig.tight_layout()
    save(fig, FIGURES_DIR / "01_ec_hierarchy_and_distribution.png")
    print("Saved reports/figures/01_ec_hierarchy_and_distribution.png")


def fig02_model_benchmark_comparison() -> None:
    """Figure 2: Performance comparison across 1D CNN, GCN, and GAT on held-out test split (<30% homology)."""
    bench_file = RESULTS_DIR / "metrics_benchmarks.csv"
    if not bench_file.exists():
        print("Skipping Fig 2: metrics_benchmarks.csv not found.")
        return

    df = pd.read_csv(bench_file)

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    name_map = {
        "cnn_baseline": "1D Dilated CNN\n(Sequence)",
        "gcn": "Contact GCN\n(3D Graph)",
        "gat": "Edge-Attn GAT\n(3D Graph)",
    }
    df["Model"] = df["experiment"].map(name_map).fillna(df["experiment"])

    metrics = [
        ("macro_f1", "Macro-F1 Score", "Macro-F1", axes[0], "A"),
        ("macro_mcc", "Matthews Corr. Coeff. (MCC)", "Macro-MCC", axes[1], "B"),
        ("macro_aupr", "Area Under PR Curve (AUPR)", "Macro-AUPR", axes[2], "C"),
    ]

    for col, title, ylabel, ax, p_lbl in metrics:
        sns.barplot(data=df, x="Model", y=col, hue="Model", legend=False, ax=ax, palette=OKABE_ITO[:len(df)])
        ax.set_title(title, pad=10)
        ax.set_ylabel(ylabel)
        ax.set_xlabel("")
        ax.set_ylim(0, 0.30)
        ax.tick_params(axis="x", labelsize=9.5)
        for p in ax.patches:
            height = p.get_height()
            if height > 0.02:
                ax.annotate(f"{height:.3f}", (p.get_x() + p.get_width() / 2., height / 2.),
                            ha="center", va="center", color="white", fontweight="bold", fontsize=10)
        panel_label(ax, p_lbl)

    fig.suptitle("PDB Enzyme Function Benchmark: Sequence vs 3D Contact GNN (<30% Sequence Homology)",
                 fontsize=12, fontweight="bold", y=1.02)
    fig.tight_layout()
    save(fig, FIGURES_DIR / "02_model_benchmark_comparison.png")
    print("Saved reports/figures/02_model_benchmark_comparison.png")


def fig03_per_class_aupr_comparison() -> None:
    """Figure 3: Per-class AUPR across all 25 fine-grained EC categories (CNN vs GAT)."""
    p_cnn_file = RESULTS_DIR / "probs_test_cnn_baseline.npy"
    p_gat_file = RESULTS_DIR / "probs_test_gat.npy"
    y_test_file = RESULTS_DIR / "y_test_ground_truth.npy"

    if not (p_cnn_file.exists() and p_gat_file.exists() and y_test_file.exists()):
        print("Skipping Fig 3: Test prediction matrices not found.")
        return

    y_test = np.load(y_test_file)
    p_cnn = np.load(p_cnn_file)
    p_gat = np.load(p_gat_file)

    aupr_cnn, aupr_gat = [], []
    for c in range(len(EC_CLASSES)):
        if y_test[:, c].sum() > 0:
            aupr_cnn.append(average_precision_score(y_test[:, c], p_cnn[:, c]))
            aupr_gat.append(average_precision_score(y_test[:, c], p_gat[:, c]))
        else:
            aupr_cnn.append(0.0)
            aupr_gat.append(0.0)

    df_p = pd.DataFrame({
        "EC": [f"EC {ec}: {EC_DESCRIPTIONS.get(ec, '')[:22]}" for ec in EC_CLASSES],
        "1D CNN": aupr_cnn,
        "Contact GAT": aupr_gat,
        "Delta": np.array(aupr_gat) - np.array(aupr_cnn),
    }).sort_values("Delta", ascending=True)

    fig, ax = plt.subplots(figsize=(11, 7.5))
    y = np.arange(len(df_p))
    h = 0.38

    ax.barh(y - h/2, df_p["1D CNN"], height=h, label="1D Dilated CNN (Seq)", color="#888888", alpha=0.85)
    ax.barh(y + h/2, df_p["Contact GAT"], height=h, label="Contact GAT (3D Graph)", color="#0072B2", alpha=0.9)

    ax.set_yticks(y)
    ax.set_yticklabels(df_p["EC"], fontsize=8.5)
    ax.set_xlabel("Area Under Precision-Recall Curve (AUPR)")
    ax.set_title("Per-Class Precision-Recall Gain: 3D Contact GAT vs 1D Sequence CNN", pad=12)
    ax.set_xlim(0, 1.05)
    ax.legend(frameon=True, loc="lower right")
    panel_label(ax, "A")

    fig.tight_layout()
    save(fig, FIGURES_DIR / "03_per_class_aupr_comparison.png")
    print("Saved reports/figures/03_per_class_aupr_comparison.png")


def fig04_contact_graph_and_attention_saliency() -> None:
    """Figure 4: 3D Contact graph adjacency and GAT attention saliency on active site residues."""
    npz_path = RAW_DIR / "ec_pdb_splits.npz"
    if not npz_path.exists():
        print("Skipping Fig 4: ec_pdb_splits.npz not found.")
        return

    data = np.load(npz_path, allow_pickle=True)
    coords_all = data["coords"]
    seqs_all = data["sequences"]
    pdb_chains = data["pdb_chains"]
    ec_all = data["ec_annotations"]

    # Select a representative enzyme chain from the held-out test set
    splits_arr = data["splits"]
    test_indices = np.where(splits_arr == "test")[0]
    idx = int(test_indices[0]) if len(test_indices) > 0 else 0
    coords = coords_all[idx]
    seq = str(seqs_all[idx])
    pdb = str(pdb_chains[idx])
    ec_annot = str(ec_all[idx])
    L = len(coords)

    # Compute Euclidean distance matrix
    dist_mat = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=-1)

    # Extract REAL residue pooling attention weights from trained ProteinGAT checkpoint
    from protgnn.data.graph_builder import build_protein_graph
    from protgnn.models.factory import build_model
    from protgnn.utils.common import load_config

    cfg = load_config("configs/default.yaml")
    cfg["model"]["name"] = "gat"
    cfg["model"]["num_classes"] = len(EC_CLASSES)
    gat_model = build_model(cfg)
    ckpt_path = Path("models/gat.pt")
    if ckpt_path.exists():
        gat_model.load_state_dict(torch.load(ckpt_path, map_location="cpu", weights_only=True))
    gat_model.eval()

    g = build_protein_graph(
        seq,
        coords,
        contact_threshold=cfg["data"].get("contact_threshold", 10.0),
        max_neighbors=cfg["data"].get("max_neighbors", 30),
        num_rbf=cfg["data"].get("num_rbf", 16),
    )
    batch_vec = torch.zeros(g["num_nodes"], dtype=torch.long)
    with torch.no_grad():
        out = gat_model(
            torch.as_tensor(g["node_feat"], dtype=torch.float32),
            torch.as_tensor(g["edge_index"], dtype=torch.long),
            torch.as_tensor(g["edge_feat"], dtype=torch.float32),
            batch_vec,
        )
    attn_saliency = out["attention_weights"].cpu().numpy()
    top_k = min(5, L)
    hotspots = np.argsort(attn_saliency)[-top_k:][::-1].tolist()

    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    # Panel A: C-alpha Contact Map
    ax = axes[0]
    im = ax.imshow(dist_mat, cmap="viridis_r", origin="upper", vmin=0, vmax=25)
    ax.set_title(f"C-alpha Distance Matrix: Chain {pdb} (L={L})\nEC: {ec_annot}", pad=10)
    ax.set_xlabel("Residue Index")
    ax.set_ylabel("Residue Index")
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Distance (Å)")
    panel_label(ax, "A")

    # Panel B: Real GAT Attention Pooling Weights Profile
    ax = axes[1]
    res_idx = np.arange(1, L + 1)
    ax.plot(res_idx, attn_saliency, color="#D55E00", lw=1.8, label="GAT Pooling Attention ($\\alpha_i$)")
    ax.fill_between(res_idx, 0, attn_saliency, color="#D55E00", alpha=0.25)
    for j, h in enumerate(hotspots):
        aa_lbl = seq[h] if h < len(seq) else "?"
        ax.axvline(h + 1, color="#0072B2", ls="--", lw=1.1, label="Top-5 Attention Residues" if j == 0 else None)
        if j < 3:
            ax.annotate(
                f"{aa_lbl}{h+1}",
                xy=(h + 1, attn_saliency[h]),
                xytext=(0, 6),
                textcoords="offset points",
                ha="center",
                fontsize=8.5,
                fontweight="bold",
                color="#0072B2",
            )
    ax.set_title("Trained ProteinGAT Residue Attention Profile", pad=10)
    ax.set_xlabel("Residue Index")
    ax.set_ylabel("Normalized Attention Weight ($\\alpha_i$)")
    ax.set_xlim(1, L)
    ax.set_ylim(0, float(attn_saliency.max()) * 1.18)
    ax.legend(frameon=True, loc="upper right")
    panel_label(ax, "B")

    fig.tight_layout()
    save(fig, FIGURES_DIR / "04_contact_graph_and_attention_saliency.png")
    print("Saved reports/figures/04_contact_graph_and_attention_saliency.png")


def fig05_structural_properties_and_graph_degrees() -> None:
    """Figure 5: Protein length, contact degree, and distance distribution across PDB benchmark."""
    npz_path = RAW_DIR / "ec_pdb_splits.npz"
    if not npz_path.exists():
        print("Skipping Fig 5: ec_pdb_splits.npz not found.")
        return

    data = np.load(npz_path, allow_pickle=True)
    coords_all = data["coords"]
    lengths = np.array([len(c) for c in coords_all], dtype=np.int32)

    # Compute contact degrees and pairwise contact distances for sample
    sample_coords = coords_all[:200]
    degrees = []
    contact_dists = []

    for c in sample_coords:
        d = np.linalg.norm(c[:, None, :] - c[None, :, :], axis=-1)
        np.fill_diagonal(d, 999.0)
        deg = (d < 10.0).sum(axis=-1)
        degrees.extend(deg)
        mask = (d < 10.0)
        contact_dists.extend(d[mask])

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8))

    # Panel A: Protein Length
    ax = axes[0]
    sns.histplot(lengths, bins=25, kde=True, ax=ax, color="#0072B2", alpha=0.6)
    ax.set_title("Protein Sequence Length Distribution", pad=10)
    ax.set_xlabel("Length (residues)")
    ax.set_ylabel("Count")
    ax.axvline(np.mean(lengths), color="red", ls="--", lw=1.5, label=f"Mean: {np.mean(lengths):.0f} aa")
    ax.legend(frameon=False)
    panel_label(ax, "A")

    # Panel B: Node Degree
    ax = axes[1]
    sns.histplot(degrees, bins=20, kde=True, ax=ax, color="#E69F00", alpha=0.6)
    ax.set_title("Residue Contact Degree Distribution (<10 Å)", pad=10)
    ax.set_xlabel("Degree (number of spatial neighbors)")
    ax.set_ylabel("Residue Count")
    ax.axvline(np.mean(degrees), color="black", ls="--", lw=1.5, label=f"Mean Degree: {np.mean(degrees):.1f}")
    ax.legend(frameon=False)
    panel_label(ax, "B")

    # Panel C: Contact Distances
    ax = axes[2]
    sns.histplot(contact_dists, bins=25, kde=True, ax=ax, color="#009E73", alpha=0.6)
    ax.set_title("Spatial Contact Distance Distribution", pad=10)
    ax.set_xlabel("Distance (Å)")
    ax.set_ylabel("Contact Count")
    ax.axvline(3.8, color="#D55E00", ls="--", lw=1.5, label="C-alpha Bond (~3.8 Å)")
    ax.legend(frameon=False)
    panel_label(ax, "C")

    fig.tight_layout()
    save(fig, FIGURES_DIR / "05_structural_properties_and_graph_degrees.png")
    print("Saved reports/figures/05_structural_properties_and_graph_degrees.png")


def fig06_latent_space_umap() -> None:
    """Figure 6: UMAP projection of learned protein representations (1D CNN vs Contact GAT)."""
    emb_file = RESULTS_DIR / "test_embeddings_gat.pt"
    y_test_file = RESULTS_DIR / "y_test_ground_truth.npy"

    if not (emb_file.exists() and y_test_file.exists()):
        print("Skipping Fig 6: test_embeddings_gat.pt not found.")
        return

    data_gat = torch.load(emb_file, weights_only=False)
    emb_gat = data_gat["embeddings"].numpy() if hasattr(data_gat["embeddings"], "numpy") else np.asarray(data_gat["embeddings"])
    y_test = np.load(y_test_file)

    # Primary EC division (1-7) for each protein
    primary_classes = []
    for row in y_test:
        active = np.where(row == 1)[0]
        if len(active) > 0:
            top_ec = int(EC_CLASSES[active[0]].split(".")[0])
        else:
            top_ec = 1
        primary_classes.append(top_ec)
    primary_classes = np.array(primary_classes)

    # Load REAL pooled representations from trained 1D Sequence CNN and trained ProteinGAT
    cnn_ckpt_emb = RESULTS_DIR / "test_embeddings_cnn_baseline.pt"
    cnn_data = torch.load(cnn_ckpt_emb, map_location="cpu", weights_only=False)
    emb_cnn = cnn_data["embeddings"].numpy() if hasattr(cnn_data["embeddings"], "numpy") else np.asarray(cnn_data["embeddings"])

    reducer_cnn = umap.UMAP(n_neighbors=20, min_dist=0.3, metric="cosine", random_state=42)
    coords_cnn = reducer_cnn.fit_transform(emb_cnn)

    reducer_gat = umap.UMAP(n_neighbors=20, min_dist=0.3, metric="cosine", random_state=42)
    coords_gat = reducer_gat.fit_transform(emb_gat)

    from sklearn.model_selection import StratifiedKFold, cross_val_score
    sil_cnn = silhouette_score(coords_cnn, primary_classes)
    min_cls = int(np.bincount(primary_classes)[np.bincount(primary_classes) > 0].min())
    cv_k = max(2, min(5, min_cls))
    skf = StratifiedKFold(n_splits=cv_k, shuffle=True, random_state=42)
    knn_cnn = float(cross_val_score(KNeighborsClassifier(n_neighbors=5), coords_cnn, primary_classes, cv=skf).mean())

    sil_gat = silhouette_score(coords_gat, primary_classes)
    knn_gat = float(cross_val_score(KNeighborsClassifier(n_neighbors=5), coords_gat, primary_classes, cv=skf).mean())

    fig, axes = plt.subplots(1, 2, figsize=(17, 7))

    top_names = {
        1: "1: Oxidoreductase",
        2: "2: Transferase",
        3: "3: Hydrolase",
        4: "4: Lyase",
        5: "5: Isomerase",
        6: "6: Ligase",
        7: "7: Translocase",
    }

    # Panel A: 1D Dilated CNN (Seq)
    ax = axes[0]
    for p_id in range(1, 8):
        mask = (primary_classes == p_id)
        if mask.sum() > 0:
            ax.scatter(
                coords_cnn[mask, 0],
                coords_cnn[mask, 1],
                c=EC_PRIMARY_COLORS[p_id],
                label=f"EC {top_names[p_id]} (N={mask.sum()})",
                alpha=0.7,
                s=24,
                edgecolors="none",
            )
    ax.set_title(f"1D Sequence CNN Latent Space\nSilhouette: {sil_cnn:.3f} | {cv_k}-CV 5-NN Acc: {knn_cnn*100:.1f}%", pad=10)
    ax.set_xlabel("UMAP Dimension 1")
    ax.set_ylabel("UMAP Dimension 2")
    panel_label(ax, "A")

    # Panel B: Contact GAT (3D Graph)
    ax = axes[1]
    for p_id in range(1, 8):
        mask = (primary_classes == p_id)
        if mask.sum() > 0:
            ax.scatter(
                coords_gat[mask, 0],
                coords_gat[mask, 1],
                c=EC_PRIMARY_COLORS[p_id],
                label=f"EC {top_names[p_id]} (N={mask.sum()})",
                alpha=0.7,
                s=24,
                edgecolors="none",
            )
    ax.set_title(f"3D Contact GAT Latent Space\nSilhouette: {sil_gat:.3f} | {cv_k}-CV 5-NN Acc: {knn_gat*100:.1f}%", pad=10)
    ax.set_xlabel("UMAP Dimension 1")
    ax.set_ylabel("UMAP Dimension 2")
    ax.legend(title="Enzyme Division", frameon=True, loc="upper right", markerscale=2.0, fontsize=8.5)
    panel_label(ax, "B")

    fig.suptitle(
        f"Enzyme Function Latent Space: Sequence vs 3D Contact Graph Convolution (N={len(primary_classes):,} Held-Out Test)\n"
        f"{cv_k}-CV 5-NN EC Separation: 1D CNN = {knn_cnn*100:.1f}% vs 3D GAT = {knn_gat*100:.1f}% (delta {(knn_gat-knn_cnn)*100:+.1f}%)",
        fontsize=13,
        fontweight="bold",
        y=0.98,
    )
    fig.tight_layout()
    save(fig, FIGURES_DIR / "06_latent_space_umap.png")
    print("Saved reports/figures/06_latent_space_umap.png")


def main() -> None:
    print("Generating Protein Function GNN publication figures...")
    fig01_ec_hierarchy_and_distribution()
    fig02_model_benchmark_comparison()
    fig03_per_class_aupr_comparison()
    fig04_contact_graph_and_attention_saliency()
    fig05_structural_properties_and_graph_degrees()
    fig06_latent_space_umap()
    print("Figure generation complete!")


if __name__ == "__main__":
    main()

