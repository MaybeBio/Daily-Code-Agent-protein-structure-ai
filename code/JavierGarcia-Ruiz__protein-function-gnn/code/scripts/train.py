"""Train and benchmark GNN architectures on 3D protein residue graphs for Enzyme Commission function prediction.

Experiments:
    1. cnn_baseline (1D Dilated CNN on sequence one-hot)
    2. gcn (Graph Convolutional Network on 3D contact graph)
    3. gat (Graph Attention Network on 3D contact graph)
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

from protgnn.data.constants import EC_CLASSES
from protgnn.data.dataset import ProteinGraphDataset, collate_protein_graphs
from protgnn.data.deepfri import load_ec_benchmark
from protgnn.models.factory import build_model
from protgnn.training.trainer import GNNTrainer
from protgnn.utils.common import get_logger, load_config, seed_everything


def run_benchmarks(config_path: str = "configs/default.yaml", quick: bool = False) -> None:
    cfg = load_config(config_path)
    seed = cfg.get("seed", 42)
    seed_everything(seed)

    logger = get_logger("protgnn.train", log_file=Path("logs/train.log"))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Using compute device: {device} ({torch.cuda.get_device_name(0) if device.type == 'cuda' else 'CPU'})")

    raw_dir = Path("data/raw")
    proc_dir = Path("data/processed")
    models_dir = Path("models")
    results_dir = Path("reports/results")
    proc_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    npz_path = raw_dir / "ec_pdb_splits.npz"
    if not npz_path.exists():
        logger.info("Raw benchmark not found. Running scripts/download_data.py...")
        from scripts.download_data import main as download_main
        download_main()

    logger.info(f"Loading packed PDB EC benchmark from {npz_path}...")
    data = np.load(npz_path, allow_pickle=True)
    pdb_chains = data["pdb_chains"]
    sequences = data["sequences"]
    splits = data["splits"]
    ec_annotations = data["ec_annotations"]
    coords = data["coords"]

    # Build split records
    records_tr, records_val, records_te = [], [], []
    for i in range(len(pdb_chains)):
        rec = {
            "pdb_chain": pdb_chains[i],
            "sequence": sequences[i],
            "ec_annotations": ec_annotations[i],
            "coords": coords[i],
        }
        sp = splits[i]
        if sp == "train":
            records_tr.append(rec)
        elif sp == "val":
            records_val.append(rec)
        elif sp == "test":
            records_te.append(rec)

    if quick:
        records_tr = records_tr[:300]
        records_val = records_val[:100]
        records_te = records_te[:100]

    logger.info(f"Train: {len(records_tr):,} proteins | Val: {len(records_val):,} proteins | Test (<30% id): {len(records_te):,} proteins")

    contact_th = cfg["data"].get("contact_threshold", 10.0)
    max_k = cfg["data"].get("max_neighbors", 30)
    num_rbf = cfg["data"].get("num_rbf", 16)
    batch_size = cfg["training"].get("batch_size", 32)

    logger.info(f"Building contact graph datasets (contact_th={contact_th}A, k={max_k}, num_rbf={num_rbf})...")
    ds_train = ProteinGraphDataset(records_tr, contact_threshold=contact_th, max_neighbors=max_k, num_rbf=num_rbf)
    ds_val = ProteinGraphDataset(records_val, contact_threshold=contact_th, max_neighbors=max_k, num_rbf=num_rbf)
    ds_test = ProteinGraphDataset(records_te, contact_threshold=contact_th, max_neighbors=max_k, num_rbf=num_rbf)

    loader_tr = DataLoader(ds_train, batch_size=batch_size, shuffle=True, collate_fn=collate_protein_graphs, num_workers=0)
    loader_val = DataLoader(ds_val, batch_size=batch_size, shuffle=False, collate_fn=collate_protein_graphs, num_workers=0)
    loader_te = DataLoader(ds_test, batch_size=batch_size, shuffle=False, collate_fn=collate_protein_graphs, num_workers=0)

    experiments = [
        {"name": "cnn_baseline", "model": "cnn_baseline", "epochs": 8 if not quick else 2},
        {"name": "gcn", "model": "gcn", "epochs": 10 if not quick else 2},
        {"name": "gat", "model": "gat", "epochs": 10 if not quick else 2},
    ]

    benchmark_records = []

    for exp in experiments:
        exp_name = exp["name"]
        logger.info(f"\n=======================================================")
        logger.info(f"STARTING EXPERIMENT: {exp_name.upper()}")
        logger.info(f"=======================================================")

        exp_cfg = copy.deepcopy(cfg)
        exp_cfg["model"]["name"] = exp["model"]
        exp_cfg["training"]["epochs"] = exp["epochs"]

        model = build_model(exp_cfg)
        trainer = GNNTrainer(model, exp_cfg, device=device, logger=logger)
        ckpt_path = models_dir / f"{exp_name}.pt"
        hist, best_th = trainer.fit(loader_tr, loader_val, save_path=ckpt_path)

        # Evaluate on Test Split (<30% homology)
        logger.info(f"Evaluating {exp_name} on held-out test split (<30% homology)...")
        m_test = trainer.evaluate(loader_te, thresholds=best_th)

        logger.info(
            f"TEST | Macro-F1: {m_test['macro_f1']:.4f} | Micro-F1: {m_test['micro_f1']:.4f} | "
            f"Macro-MCC: {m_test['macro_mcc']:.4f} | Macro-AUPR: {m_test['macro_aupr']:.4f} | LRAP: {m_test['lrap']:.4f}"
        )

        rec = {
            "experiment": exp_name,
            "model": exp["model"],
            "macro_f1": m_test["macro_f1"],
            "micro_f1": m_test["micro_f1"],
            "macro_mcc": m_test["macro_mcc"],
            "macro_aupr": m_test["macro_aupr"],
            "lrap": m_test["lrap"],
            "micro_precision": m_test["micro_precision"],
            "micro_recall": m_test["micro_recall"],
            "exact_match": m_test["exact_match"],
            "hamming_loss": m_test["hamming_loss"],
        }
        benchmark_records.append(rec)

        # Save predictions and real latent representations for every model
        np.save(results_dir / f"probs_test_{exp_name}.npy", m_test["y_probs"])
        if "sample_embeddings" in m_test:
            torch.save(
                {"embeddings": m_test["sample_embeddings"], "labels": m_test["sample_labels"]},
                results_dir / f"test_embeddings_{exp_name}.pt",
            )
        if exp_name == "gat":
            np.save(results_dir / "y_test_ground_truth.npy", m_test["y_true"])
            with (results_dir / "per_class_test_gat.json").open("w", encoding="utf-8") as f:
                json.dump({
                    "f1": m_test["per_class_f1"],
                    "mcc": m_test["per_class_mcc"],
                    "aupr": m_test["per_class_aupr"],
                }, f, indent=2)

    df_bench = pd.DataFrame(benchmark_records)
    df_bench.to_csv(results_dir / "metrics_benchmarks.csv", index=False)
    with (results_dir / "metrics_benchmarks.json").open("w", encoding="utf-8") as f:
        json.dump(benchmark_records, f, indent=2)

    logger.info("All Protein Function GNN benchmark experiments completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train GNN models on protein residue graphs")
    parser.add_argument("--config", type=str, default="configs/default.yaml")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    run_benchmarks(config_path=args.config, quick=args.quick)

