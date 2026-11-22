"""Re-score the held-out backbones with intervals that respect how few of them there are.

Three things the training script's single number does not show:

1. **The unit of evidence is the structure, not the residue.** Residues inside one protein share a
   fold, a composition and a crystallography run, so 850 residues from 7 proteins are nowhere near
   850 independent observations. Intervals here resample structures.
2. **Recovery is a random draw.** ProteinMPNN picks a new decoding order on every forward pass, so
   one call gives one sample. Each model is scored over several orders and the spread reported.
3. **The pretrained model's score is not held out.** It was trained on the PDB, so test structures
   deposited before its training cutoff were almost certainly in its training set. Those are
   flagged rather than compared as if they were unseen.
"""
import argparse
import copy
import json
import os
import sys

import numpy as np
import torch

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_DIR = os.path.join(REPO_DIR, "vendor", "ProteinMPNN-main")
sys.path.insert(0, VENDOR_DIR)
sys.path.insert(0, os.path.join(VENDOR_DIR, "training"))

from protein_mpnn_utils import parse_PDB  # noqa: E402
from model_utils import ProteinMPNN, featurize, loss_nll  # noqa: E402

ALPHABET = "ACDEFGHIKLMNPQRSTVWYX"
# ProteinMPNN's published weights were trained on PDB chains clustered at 30% identity, using
# structures deposited up to roughly mid-2021. Anything older is very likely in that training set.
PRETRAINED_CUTOFF = "2021-08"


def load_structures(structures_dir, pdb_ids, min_len=70, max_len=250):
    canonical = set("ACDEFGHIKLMNPQRSTVWY")
    out = []
    for pdb_id in pdb_ids:
        path = os.path.join(structures_dir, f"{pdb_id}.pdb")
        if not os.path.exists(path):
            continue
        parsed = parse_PDB(path)
        if not parsed:
            continue
        item = parsed[0]
        seq = item.get("seq", "")
        if not (set(seq).issubset(canonical) and min_len <= len(seq) <= max_len):
            continue
        item["masked_list"] = [k.replace("seq_chain_", "") for k in item if k.startswith("seq_chain_")]
        item["visible_list"] = []
        item["pdb_id"] = pdb_id
        out.append(item)
    return out


def deposition_year(path):
    """Year from the PDB HEADER record, used only to flag likely pretraining overlap."""
    try:
        with open(path) as fh:
            for line in fh:
                if line.startswith("HEADER"):
                    date = line[50:59].strip()
                    if len(date) == 9:
                        yy = int(date[-2:])
                        return 1900 + yy if yy > 50 else 2000 + yy
                    return None
                if line.startswith(("ATOM", "SEQRES")):
                    return None
    except OSError:
        return None
    return None


def per_structure_recovery(model, items, device="cpu", n_orders=10, seed=0):
    """Recovery for each structure, averaged over `n_orders` random decoding orders."""
    model.eval()
    torch.manual_seed(seed)
    rows = []
    with torch.no_grad():
        for item in items:
            per_order, losses = [], []
            for _ in range(n_orders):
                batch = [copy.deepcopy(item)]
                X, S, mask, _, chain_M, residue_idx, _, chain_encoding_all = featurize(batch, device=device)
                log_probs = model(X, S, mask, chain_M, residue_idx, chain_encoding_all)
                loss, _, true_false = loss_nll(S, log_probs, mask)
                tokens = mask.sum().item()
                per_order.append((true_false * mask).sum().item() / max(tokens, 1.0))
                losses.append((loss * mask).sum().item() / max(tokens, 1.0))
            rows.append({"pdb_id": item["pdb_id"], "residues": int(len(item["seq"])),
                         "recovery_mean": float(np.mean(per_order)),
                         "recovery_sd_over_orders": float(np.std(per_order)),
                         "loss_mean": float(np.mean(losses))})
    return rows


def bootstrap_over_structures(rows, key="recovery_mean", n=10000, seed=0):
    """Resample structures, not residues. Each draw is weighted by residue count, as the headline
    token-level recovery is, so the interval answers the same question the point estimate does."""
    rec = np.array([r[key] for r in rows], float)
    w = np.array([r["residues"] for r in rows], float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(rec), (n, len(rec)))
    draws = (rec[idx] * w[idx]).sum(1) / w[idx].sum(1)
    point = float((rec * w).sum() / w.sum())
    return point, *np.percentile(draws, [2.5, 97.5]).tolist()


def build_model(k_neighbors=24, augment_eps=0.0, dropout=0.0):
    return ProteinMPNN(num_letters=21, node_features=128, edge_features=128, hidden_dim=128,
                       num_encoder_layers=3, num_decoder_layers=3, k_neighbors=k_neighbors,
                       augment_eps=augment_eps, dropout=dropout)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--orders", type=int, default=10)
    ap.add_argument("--out", default=os.path.join(REPO_DIR, "results", "evaluation.json"))
    a = ap.parse_args()

    structures_dir = os.path.join(REPO_DIR, "data", "structures")
    with open(os.path.join(structures_dir, "splits.json")) as fh:
        test_ids = json.load(fh)["test_pdb_ids"]
    items = load_structures(structures_dir, test_ids)
    print(f"held-out structures: {len(items)} "
          f"({sum(len(i['seq']) for i in items)} residues)", flush=True)

    report = {"n_test_structures": len(items), "decoding_orders_per_structure": a.orders,
              "note": __doc__.strip()}

    models = {}
    trained_path = os.path.join(REPO_DIR, "results", "mpnn_trained_weights.pt")
    if os.path.exists(trained_path):
        m = build_model()
        m.load_state_dict(torch.load(trained_path, map_location="cpu"))
        models["trained_on_29_structures"] = m
    pre_path = os.path.join(VENDOR_DIR, "vanilla_model_weights", "v_48_020.pt")
    if os.path.exists(pre_path):
        ckpt = torch.load(pre_path, map_location="cpu")
        m = build_model(k_neighbors=ckpt.get("num_edges", 48))
        m.load_state_dict(ckpt["model_state_dict"])
        models["pretrained_full_pdb"] = m

    for name, model in models.items():
        rows = per_structure_recovery(model, items, n_orders=a.orders)
        point, lo, hi = bootstrap_over_structures(rows)
        spread = float(np.mean([r["recovery_sd_over_orders"] for r in rows]))
        report[name] = {"recovery": point, "ci_over_structures": [lo, hi],
                        "mean_sd_across_decoding_orders": spread, "per_structure": rows}
        print(f"\n{name}: recovery {point*100:.2f}%  "
              f"95% CI over structures [{lo*100:.1f}%, {hi*100:.1f}%]  "
              f"(sd across decoding orders {spread*100:.2f} points)", flush=True)
        for r in sorted(rows, key=lambda r: -r["recovery_mean"]):
            print(f"    {r['pdb_id']}  {r['residues']:4d} res  {r['recovery_mean']*100:5.1f}%", flush=True)

    # Which held-out structures predate the pretrained model's training cutoff?
    years = {i["pdb_id"]: deposition_year(os.path.join(structures_dir, f"{i['pdb_id']}.pdb")) for i in items}
    cutoff_year = int(PRETRAINED_CUTOFF.split("-")[0])
    likely_seen = sorted(p for p, y in years.items() if y is not None and y <= cutoff_year)
    report["pretraining_overlap"] = {"cutoff": PRETRAINED_CUTOFF, "deposition_years": years,
                                     "likely_in_pretraining_set": likely_seen}
    print(f"\nheld-out structures deposited on or before {PRETRAINED_CUTOFF}, so very likely inside "
          f"the pretrained model's training set: {len(likely_seen)} of {len(items)}", flush=True)
    print(f"  {', '.join(f'{p} ({years[p]})' for p in likely_seen)}", flush=True)
    print("  the pretrained row is therefore not a held-out comparison", flush=True)

    with open(a.out, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nwritten to {a.out}", flush=True)


if __name__ == "__main__":
    main()
