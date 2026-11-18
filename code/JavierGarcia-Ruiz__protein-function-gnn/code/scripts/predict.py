"""CLI for Protein Enzyme Commission (EC) function prediction.

Usage:
    python scripts/predict.py --sequence "MALLALSLVALLALSSAQG..."
    python scripts/predict.py --pdb path/to/protein.pdb
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import numpy as np
import torch

from protgnn.data.constants import EC_CLASSES, EC_DESCRIPTIONS, EC_TOP_CLASSES, AMINO_ACIDS, AA_TO_IDX
from protgnn.data.graph_builder import build_protein_graph
from protgnn.models.factory import build_model
from protgnn.utils.common import load_config


def generate_synthetic_backbone(sequence: str, seed: int = 42) -> np.ndarray:
    """Generate a realistic C-alpha backbone trajectory for a protein sequence if no PDB coordinates are given."""
    rng = np.random.RandomState(seed)
    L = len(sequence)
    coords = np.zeros((L, 3), dtype=np.float32)
    cur_pos = np.zeros(3, dtype=np.float32)
    cur_dir = np.array([1.0, 0.0, 0.0], dtype=np.float32)

    for i in range(1, L):
        theta = rng.normal(0.65, 0.15)
        phi = rng.uniform(0, 2 * np.pi)
        perp = np.array([-cur_dir[1], cur_dir[0], 0.0], dtype=np.float32)
        if np.linalg.norm(perp) < 1e-4:
            perp = np.array([0.0, -cur_dir[2], cur_dir[1]], dtype=np.float32)
        perp /= np.linalg.norm(perp)
        cross = np.cross(cur_dir, perp)
        new_dir = (
            np.cos(theta) * cur_dir +
            np.sin(theta) * (np.cos(phi) * perp + np.sin(phi) * cross)
        )
        new_dir /= np.linalg.norm(new_dir)
        cur_pos = cur_pos + 3.8 * new_dir
        coords[i] = cur_pos
        cur_dir = new_dir

    coords -= coords.mean(axis=0)
    return coords


def predict_ec_function(
    sequence: str,
    coords: np.ndarray | None = None,
    model_path: str = "models/gat.pt",
    config_path: str = "configs/default.yaml",
    device: str | None = None,
) -> dict:
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    dev = torch.device(device)

    clean_seq = "".join(sequence.split()).upper()
    L = len(clean_seq)

    if coords is None:
        coords = generate_synthetic_backbone(clean_seq)

    cfg = load_config(config_path)
    model = build_model(cfg).to(dev)

    ckpt = Path(model_path)
    if ckpt.exists():
        model.load_state_dict(torch.load(ckpt, map_location=dev, weights_only=True))
    model.eval()

    # Build graph
    g = build_protein_graph(
        sequence=clean_seq,
        coords=coords,
        contact_threshold=cfg["data"].get("contact_threshold", 10.0),
        max_neighbors=cfg["data"].get("max_neighbors", 30),
        num_rbf=cfg["data"].get("num_rbf", 16),
    )

    batch_dict = {
        "x": g["node_feat"].float().to(dev) if isinstance(g["node_feat"], torch.Tensor) else torch.from_numpy(g["node_feat"]).float().to(dev),
        "edge_index": g["edge_index"].long().to(dev) if isinstance(g["edge_index"], torch.Tensor) else torch.from_numpy(g["edge_index"]).long().to(dev),
        "edge_attr": g["edge_feat"].float().to(dev) if isinstance(g["edge_feat"], torch.Tensor) else torch.from_numpy(g["edge_feat"]).float().to(dev),
        "batch": torch.zeros(L, dtype=torch.long).to(dev),
    }

    with torch.no_grad():
        out = model(**batch_dict)
        probs = out["probs"][0].cpu().numpy()

    ranked = sorted(
        [
            {
                "ec": ec,
                "description": EC_DESCRIPTIONS.get(ec, "Enzyme function"),
                "probability": float(probs[i]),
            }
            for i, ec in enumerate(EC_CLASSES)
        ],
        key=lambda x: x["probability"],
        reverse=True,
    )

    top_division = int(ranked[0]["ec"].split(".")[0])
    division_names = {
        1: "Oxidoreductases",
        2: "Transferases",
        3: "Hydrolases",
        4: "Lyases",
        5: "Isomerases",
        6: "Ligases",
        7: "Translocases",
    }

    return {
        "sequence_length": L,
        "primary_division": f"EC {top_division}: {division_names.get(top_division, 'Unknown')}",
        "predictions": ranked,
    }


def main():
    parser = argparse.ArgumentParser(description="Predict enzyme commission (EC) numbers for protein")
    parser.add_argument("--sequence", type=str, default=None, help="Amino acid sequence")
    parser.add_argument("--pdb", type=str, default=None, help="PDB file path")
    parser.add_argument("--model", type=str, default="models/gat.pt", help="Path to checkpoint")
    parser.add_argument("--top_k", type=int, default=5, help="Number of top predictions to display")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    default_seq = (
        "MALLALSLVALLALSSAQGKPVEVITVKETVETPTVEAPTVETPTVEAPTVETPTVEAPTV"
        "ETPTVEAPTVETPTVEAPTVETPTVEAPTVETPTVEAPTVETPTVEAPTVETPTVEAPTV"
        "DFYVPKYPGTLTLKKDGNKVVVDVKKIKVGDRVVIKNQGDVTAVTLNVGKTVSVKPGT"
    )

    seq = args.sequence if args.sequence else default_seq
    res = predict_ec_function(seq, model_path=args.model)

    if args.json:
        print(json.dumps(res, indent=2))
        return

    print("=" * 70)
    print("  PROTEIN FUNCTION GNN: ENZYME COMMISSION (EC) PREDICTION")
    print("=" * 70)
    print(f"Sequence Length:   {res['sequence_length']} aa")
    print(f"Primary Division:  {res['primary_division']}")
    print("-" * 70)
    print(f"{'EC Number':<10} | {'Probability':<12} | {'Description'}")
    print("-" * 70)

    for item in res["predictions"][:args.top_k]:
        prob = item["probability"]
        bar_len = int(prob * 25)
        bar = "#" * bar_len + "-" * (25 - bar_len)
        callout = " [POS]" if prob >= 0.50 else "      "
        print(f"EC {item['ec']:<7} | {prob * 100:5.1f}% [{bar}]{callout} | {item['description']}")

    print("=" * 70)


if __name__ == "__main__":
    main()

