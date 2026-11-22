"""Train and benchmark ProteinMPNN on real high-resolution X-ray crystal structures.

Trains ProteinMPNN on parsed backbone coordinate graphs from RCSB PDB, evaluates native sequence
recovery and perplexity on held-out test backbones, and benchmarks against:
  1. Random baseline (5.0%)
  2. Background amino acid frequency baseline
  3. Untrained random initialization
  4. Trained ProteinMPNN (36 real crystal backbones)
  5. Pretrained ProteinMPNN (trained on full PDB)
"""

import copy
import glob
import json
import os
import random
import sys
import numpy as np
import torch
import torch.nn as nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR

os.environ["MPLCONFIGDIR"] = "/tmp/matplotlib"
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Insert ProteinMPNN paths
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_DIR = os.path.join(REPO_DIR, "vendor", "ProteinMPNN-main")
TRAIN_DIR = os.path.join(VENDOR_DIR, "training")
sys.path.insert(0, VENDOR_DIR)
sys.path.insert(0, TRAIN_DIR)

from protein_mpnn_utils import parse_PDB
from model_utils import featurize, ProteinMPNN, loss_nll

ALPHABET = "ACDEFGHIKLMNPQRSTVWYX"
AA_CLASSES = {
    "Hydrophobic Core (V,I,L,M,F,W,Y)": set("VILMFWY"),
    "Polar / Charged Surface (D,E,K,R,H,S,T,N,Q)": set("DEKRHSTNQ"),
    "Conformational Pivots (G,P)": set("GP"),
    "Disulfide (C)": set("C"),
}


def load_dataset(structures_dir, min_len=70, max_len=250):
    """Load and quality-filter PDB structures (must be continuous, canonical amino acids)."""
    pdb_files = sorted(glob.glob(os.path.join(structures_dir, "*.pdb")))
    dataset = []
    canonical = set("ACDEFGHIKLMNPQRSTVWY")
    for path in pdb_files:
        try:
            parsed = parse_PDB(path)
            if not parsed:
                continue
            item = parsed[0]
            seq = item.get("seq", "")
            # Require canonical amino acids (no gaps '-' or unknown 'X') and length bounds
            if set(seq).issubset(canonical) and min_len <= len(seq) <= max_len:
                chains = [k.replace("seq_chain_", "") for k in item.keys() if k.startswith("seq_chain_")]
                item["masked_list"] = chains
                item["visible_list"] = []
                dataset.append(item)
        except Exception as exc:
            print(f"Skipping {path}: {exc}")
    return dataset


def cluster_by_similarity(dataset, k=5, threshold=0.3):
    """Group structures whose sequences resemble each other, by single-linkage on 5-mer Jaccard.

    The PDB is highly redundant: the same protein appears many times as mutants, different ligands
    or better resolutions. A random split therefore puts near-identical sequences on both sides and
    the model can simply recall them. Measured on an earlier random split here, 30 of 52 test
    structures shared more than half their 5-mers with a training structure and 13 shared all of
    them, which inflated held-out recovery to the point of beating the published full-PDB model.

    This is a cheap proxy for sequence identity, not a substitute for proper clustering (MMseqs2 or
    CD-HIT at 30% identity); it is deliberately conservative, since over-merging only costs data."""
    names = [d["name"] for d in dataset]
    kmers = {d["name"]: {d["seq"][i:i + k] for i in range(len(d["seq"]) - k + 1)} for d in dataset}
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in range(len(names)):
        ka = kmers[names[a]]
        for b in range(a + 1, len(names)):
            kb = kmers[names[b]]
            if ka and kb and len(ka & kb) / len(ka | kb) >= threshold:
                ra, rb = find(names[a]), find(names[b])
                if ra != rb:
                    parent[rb] = ra

    clusters = {}
    for n in names:
        clusters.setdefault(find(n), []).append(n)
    return list(clusters.values())


def split_dataset(dataset, val_fraction=0.15, test_fraction=0.15, seed=42):
    """Deterministic three-way split by PDB structure.

    Validation exists so the test set can be scored once, at the end. An earlier version of this
    script evaluated the test set every epoch and then reported the final number from it, which
    means the test set had been looked at forty times before it was published."""
    clusters = cluster_by_similarity(dataset)
    rng = random.Random(seed)
    rng.shuffle(clusters)
    by_name = {d["name"]: d for d in dataset}
    n = len(dataset)
    want_test, want_val = n * test_fraction, n * val_fraction

    test, val, train = [], [], []
    for group in clusters:                      # whole clusters only: homologs never straddle a split
        target = test if len(test) < want_test else (val if len(val) < want_val else train)
        target.extend(by_name[name] for name in group)
    return train, val, test


def compute_metrics(model, data_items, device="cpu", batch_size=4):
    """Compute cross-entropy loss, perplexity, and native sequence recovery."""
    model.eval()
    total_loss_sum = 0.0
    total_correct = 0.0
    total_tokens = 0.0

    class_correct = {k: 0.0 for k in AA_CLASSES}
    class_total = {k: 0.0 for k in AA_CLASSES}

    with torch.no_grad():
        for i in range(0, len(data_items), batch_size):
            batch = [copy.deepcopy(b) for b in data_items[i : i + batch_size]]
            X, S, mask, lengths, chain_M, residue_idx, mask_self, chain_encoding_all = featurize(
                batch, device=device
            )
            log_probs = model(X, S, mask, chain_M, residue_idx, chain_encoding_all)
            loss, loss_av, true_false = loss_nll(S, log_probs, mask)

            n_tokens = mask.sum().item()
            total_loss_sum += (loss * mask).sum().item()
            total_correct += (true_false * mask).sum().item()
            total_tokens += n_tokens

            # Biochemical class breakdown
            S_cpu = S.cpu().numpy()
            pred_cpu = torch.argmax(log_probs, -1).cpu().numpy()
            mask_cpu = mask.cpu().numpy()

            for b in range(S_cpu.shape[0]):
                for pos in range(S_cpu.shape[1]):
                    if mask_cpu[b, pos] > 0.5:
                        true_aa = ALPHABET[S_cpu[b, pos]]
                        pred_aa = ALPHABET[pred_cpu[b, pos]]
                        is_match = 1.0 if true_aa == pred_aa else 0.0
                        for cls_name, cls_set in AA_CLASSES.items():
                            if true_aa in cls_set:
                                class_total[cls_name] += 1.0
                                class_correct[cls_name] += is_match

    mean_loss = total_loss_sum / max(total_tokens, 1.0)
    perplexity = float(np.exp(mean_loss))
    recovery = total_correct / max(total_tokens, 1.0)

    class_recovery = {
        cls_name: (class_correct[cls_name] / max(class_total[cls_name], 1.0))
        for cls_name in AA_CLASSES
    }

    return {
        "loss": mean_loss,
        "perplexity": perplexity,
        "recovery": recovery,
        "class_recovery": class_recovery,
        "tokens": total_tokens,
    }


def compute_metrics_multi(model, data_items, device="cpu", n_orders=10, seed=0):
    """compute_metrics averaged over several decoding orders.

    ProteinMPNN draws a new decoding order on every forward pass, so a single call is one sample,
    not the model's expected recovery. Reported numbers average `n_orders` draws."""
    torch.manual_seed(seed)
    runs = [compute_metrics(model, data_items, device=device) for _ in range(n_orders)]
    out = {k: float(np.mean([r[k] for r in runs])) for k in ("loss", "perplexity", "recovery")}
    out["recovery_sd_over_orders"] = float(np.std([r["recovery"] for r in runs]))
    out["class_recovery"] = {c: float(np.mean([r["class_recovery"][c] for r in runs])) for c in AA_CLASSES}
    out["tokens"] = runs[0]["tokens"]
    out["n_orders"] = n_orders
    return out


def recovery_ci_over_structures(model, items, device="cpu", n_orders=10, n_boot=10000, seed=0):
    """Point estimate and 95% interval, resampling structures rather than residues.

    Residues within one protein share a fold, a composition and a crystallography run, so they are
    not independent observations; the structure is the unit of evidence."""
    torch.manual_seed(seed)
    per = []
    for item in items:
        runs = [compute_metrics(model, [item], device=device) for _ in range(n_orders)]
        per.append({"pdb_id": item.get("name", "?"), "residues": int(len(item["seq"])),
                    "recovery_mean": float(np.mean([r["recovery"] for r in runs]))})
    rec = np.array([r["recovery_mean"] for r in per])
    w = np.array([r["residues"] for r in per], float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(rec), (n_boot, len(rec)))
    draws = (rec[idx] * w[idx]).sum(1) / w[idx].sum(1)
    point = float((rec * w).sum() / w.sum())
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return point, float(lo), float(hi), per


def evaluate_frequency_baseline(train_set, test_set):
    """Baseline predicting marginal amino acid frequencies from train set."""
    train_counts = {aa: 0 for aa in ALPHABET[:20]}
    for item in train_set:
        for aa in item["seq"]:
            if aa in train_counts:
                train_counts[aa] += 1
    total_train = sum(train_counts.values())
    top_aa = max(train_counts, key=train_counts.get)
    top_freq = train_counts[top_aa] / total_train

    # Evaluate on test set
    test_correct = 0
    test_total = 0
    for item in test_set:
        for aa in item["seq"]:
            if aa in train_counts:
                test_total += 1
                if aa == top_aa:
                    test_correct += 1

    return {
        "top_amino_acid": top_aa,
        "train_frequency": top_freq,
        "test_recovery": test_correct / max(test_total, 1),
    }


def main():
    device = "cpu"
    seed = 42
    n_orders = 10          # decoding orders averaged per reported number
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

    structures_dir = os.path.join(REPO_DIR, "data", "structures")
    results_dir = os.path.join(REPO_DIR, "results")
    os.makedirs(results_dir, exist_ok=True)

    print("=== Loading Real Crystal Structures from RCSB PDB ===")
    dataset = load_dataset(structures_dir)
    print(f"Loaded {len(dataset)} valid structures.")

    train_set, val_set, test_set = split_dataset(dataset, seed=seed)
    print(f"Train: {len(train_set)} | Validation: {len(val_set)} | Held-out test: {len(test_set)} structures")
    print("The test set is scored once, after training, using the checkpoint chosen on validation.")
    print("Splits are by sequence-similarity cluster, so homologous structures cannot straddle them.")

    # Confirm the split actually separates homologs, and record it.
    def kmers(s, k=5):
        return {s[i:i + k] for i in range(len(s) - k + 1)}
    train_k = [kmers(d["seq"]) for d in train_set]
    leak = []
    for d in test_set:
        kt = kmers(d["seq"])
        worst = max((len(kt & kr) / max(len(kt), 1) for kr in train_k), default=0.0)
        if worst > 0.5:
            leak.append((d["name"], worst))
    print(f"Test structures sharing more than half their 5-mers with any training structure: "
          f"{len(leak)} of {len(test_set)}")

    # Save split info
    split_info = {
        "train_pdb_ids": [d["name"] for d in train_set],
        "val_pdb_ids": [d["name"] for d in val_set],
        "test_pdb_ids": [d["name"] for d in test_set],
        "total_train_residues": sum(len(d["seq"]) for d in train_set),
        "total_val_residues": sum(len(d["seq"]) for d in val_set),
        "total_test_residues": sum(len(d["seq"]) for d in test_set),
    }
    with open(os.path.join(structures_dir, "splits.json"), "w") as fh:
        json.dump(split_info, fh, indent=2)

    # 1. Frequency Baseline
    freq_base = evaluate_frequency_baseline(train_set, test_set)
    print(f"Frequency Baseline (Most common AA = {freq_base['top_amino_acid']}): "
          f"Recovery = {freq_base['test_recovery']*100:.2f}%")

    # 2. Random Baseline
    random_recovery = 1.0 / 20.0
    random_perplexity = 20.0
    print(f"Random Baseline: Recovery = {random_recovery*100:.2f}%, Perplexity = {random_perplexity:.1f}")

    # Initialize ProteinMPNN Model
    # 3 encoder layers, 3 decoder layers, hidden_dim=128, k=24
    model = ProteinMPNN(
        num_letters=21,
        node_features=128,
        edge_features=128,
        hidden_dim=128,
        num_encoder_layers=3,
        num_decoder_layers=3,
        k_neighbors=24,
        augment_eps=0.05,  # Coordinate jitter regularization
        dropout=0.1,
    )
    model.to(device)

    # 3. Untrained Model Evaluation
    untrained_metrics = compute_metrics_multi(model, test_set, device=device, n_orders=n_orders)
    print(f"Untrained ProteinMPNN: Loss = {untrained_metrics['loss']:.4f}, "
          f"Perplexity = {untrained_metrics['perplexity']:.2f}, "
          f"Recovery = {untrained_metrics['recovery']*100:.2f}%")

    # 4. Training on Real Crystal Backbones
    epochs = 40
    batch_size = 4
    lr = 1e-3
    optimizer = AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-4)

    history = {
        "epoch": [],
        "train_loss": [],
        "train_recovery": [],
        "val_loss": [],
        "val_perplexity": [],
        "val_recovery": [],
    }
    best = {"val_recovery": -1.0, "epoch": 0, "state": None}
    patience, since_best = 10, 0

    print("\n=== Training ProteinMPNN on Real Backbone Graphs ===")
    for epoch in range(1, epochs + 1):
        model.train()
        random.shuffle(train_set)
        epoch_loss_sum = 0.0
        epoch_correct = 0.0
        epoch_tokens = 0.0

        for i in range(0, len(train_set), batch_size):
            batch = [copy.deepcopy(b) for b in train_set[i : i + batch_size]]
            X, S, mask, lengths, chain_M, residue_idx, mask_self, chain_encoding_all = featurize(
                batch, device=device
            )

            optimizer.zero_grad()
            log_probs = model(X, S, mask, chain_M, residue_idx, chain_encoding_all)
            loss, loss_av, true_false = loss_nll(S, log_probs, mask)

            loss_av.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            n_tokens = mask.sum().item()
            epoch_loss_sum += (loss * mask).sum().item()
            epoch_correct += (true_false * mask).sum().item()
            epoch_tokens += n_tokens

        scheduler.step()

        train_loss = epoch_loss_sum / max(epoch_tokens, 1.0)
        train_rec = epoch_correct / max(epoch_tokens, 1.0)

        # Evaluate on validation only. The test set is not touched inside this loop.
        val_m = compute_metrics(model, val_set, device=device)

        history["epoch"].append(epoch)
        history["train_loss"].append(train_loss)
        history["train_recovery"].append(train_rec)
        history["val_loss"].append(val_m["loss"])
        history["val_perplexity"].append(val_m["perplexity"])
        history["val_recovery"].append(val_m["recovery"])

        if val_m["recovery"] > best["val_recovery"]:
            best = {"val_recovery": val_m["recovery"], "epoch": epoch,
                    "state": copy.deepcopy(model.state_dict())}
            since_best = 0
        else:
            since_best += 1

        if epoch % 5 == 0 or epoch == 1 or epoch == epochs:
            print(f"Epoch {epoch:2d}/{epochs:2d} | Train Loss: {train_loss:.4f} (Rec: {train_rec*100:.1f}%) | "
                  f"Val Loss: {val_m['loss']:.4f} | Val Ppl: {val_m['perplexity']:.2f} | "
                  f"Val Rec: {val_m['recovery']*100:.2f}%")

        if since_best >= patience:
            print(f"No validation improvement for {patience} epochs; stopping at epoch {epoch}.")
            break

    # Restore the checkpoint chosen on validation, then score the test set once.
    if best["state"] is not None:
        model.load_state_dict(best["state"])
    print(f"\nBest validation recovery {best['val_recovery']*100:.2f}% at epoch {best['epoch']}; "
          f"scoring the held-out test set now, for the first time.")
    final_trained_metrics = compute_metrics_multi(model, test_set, device=device, n_orders=n_orders)
    t_point, t_lo, t_hi, t_per = recovery_ci_over_structures(model, test_set, device=device, n_orders=n_orders)
    final_trained_metrics.update({"recovery_ci_over_structures": [t_lo, t_hi], "per_structure": t_per,
                                  "selected_epoch": best["epoch"],
                                  "val_recovery_at_selection": best["val_recovery"]})
    print(f"Test recovery {t_point*100:.2f}%  95% CI over structures [{t_lo*100:.1f}%, {t_hi*100:.1f}%]")
    torch.save(model.state_dict(), os.path.join(results_dir, "mpnn_trained_weights.pt"))

    # 5. Pretrained ProteinMPNN Benchmark
    pretrained_path = os.path.join(VENDOR_DIR, "vanilla_model_weights", "v_48_020.pt")
    pretrained_metrics = None
    if os.path.exists(pretrained_path):
        print("\n=== Evaluating Pretrained ProteinMPNN (PDB-scale) ===")
        ckpt = torch.load(pretrained_path, map_location=device)
        p_model = ProteinMPNN(
            num_letters=21,
            node_features=128,
            edge_features=128,
            hidden_dim=128,
            num_encoder_layers=3,
            num_decoder_layers=3,
            k_neighbors=ckpt.get("num_edges", 48),
            augment_eps=0.0,
            dropout=0.0,
        )
        p_model.load_state_dict(ckpt["model_state_dict"])
        p_model.to(device)
        pretrained_metrics = compute_metrics_multi(p_model, test_set, device=device, n_orders=n_orders)
        p_point, p_lo, p_hi, p_per = recovery_ci_over_structures(p_model, test_set, device=device,
                                                                 n_orders=n_orders)
        pretrained_metrics.update({"recovery_ci_over_structures": [p_lo, p_hi], "per_structure": p_per,
                                   "caveat": "trained on the PDB; these test structures predate its "
                                             "training cutoff, so this is not a held-out score"})
        print(f"Pretrained Model: Loss = {pretrained_metrics['loss']:.4f}, "
              f"Perplexity = {pretrained_metrics['perplexity']:.2f}, "
              f"Recovery = {pretrained_metrics['recovery']*100:.2f}%")

    # 6. Generate Visualizations
    print("\n=== Generating Benchmark Visualizations ===")
    # Figure 1: Training & Validation Curves
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5), dpi=150)

    # Loss & Perplexity
    ax1.plot(history["epoch"], history["train_loss"], label="Train Loss (NLL)", color="#1f77b4", lw=2)
    ax1.plot(history["epoch"], history["val_loss"], label="Validation Loss", color="#ff7f0e", lw=2, ls="--")
    ax1.set_xlabel("Epoch", fontsize=11)
    ax1.set_ylabel("Cross-Entropy Loss (NLL)", fontsize=11)
    ax1.set_title("ProteinMPNN Optimization Curve", fontsize=12, fontweight="bold")
    ax1.grid(True, alpha=0.3)
    ax1.legend(frameon=True)

    # Sequence Recovery Rate
    ax2.plot(history["epoch"], [r * 100 for r in history["train_recovery"]], label="Train Recovery", color="#2ca02c", lw=2)
    ax2.plot(history["epoch"], [r * 100 for r in history["val_recovery"]], label="Validation Recovery", color="#d62728", lw=2, ls="--")
    ax2.axvline(final_trained_metrics["selected_epoch"], color="k", ls="-", lw=1, alpha=0.6, label="Checkpoint chosen")
    ax2.axhline(random_recovery * 100, color="gray", ls=":", label="Random (5.0%)")
    ax2.axhline(freq_base["test_recovery"] * 100, color="purple", ls=":", label=f"Frequency ({freq_base['test_recovery']*100:.1f}%)")
    if pretrained_metrics:
        ax2.axhline(pretrained_metrics["recovery"] * 100, color="navy", ls="-.", label=f"Pretrained PDB ({pretrained_metrics['recovery']*100:.1f}%)")
    ax2.set_xlabel("Epoch", fontsize=11)
    ax2.set_ylabel("Native Sequence Recovery (%)", fontsize=11)
    ax2.set_title("Native Sequence Recovery vs Baseline", fontsize=12, fontweight="bold")
    ax2.grid(True, alpha=0.3)
    ax2.legend(frameon=True, loc="lower right")

    plt.tight_layout()
    curves_path = os.path.join(results_dir, "mpnn_training_curves.png")
    plt.savefig(curves_path)
    plt.close()
    print(f"Saved: {curves_path}")

    # Figure 2: Model Benchmark Comparison
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    models = ["Random (1/20)", "Frequency Baseline", "Untrained Model", "Trained (36 Backbones)"]
    recoveries = [
        random_recovery * 100,
        freq_base["test_recovery"] * 100,
        untrained_metrics["recovery"] * 100,
        final_trained_metrics["recovery"] * 100,
    ]
    colors = ["#9e9e9e", "#ab47bc", "#ef5350", "#42a5f5"]

    if pretrained_metrics:
        models.append("Pretrained (Full PDB)")
        recoveries.append(pretrained_metrics["recovery"] * 100)
        colors.append("#2e7d32")

    bars = ax.bar(models, recoveries, color=colors, width=0.55, edgecolor="black", linewidth=0.8)
    ax.set_ylabel("Native Sequence Recovery on Held-out Crystal Backbones (%)", fontsize=11)
    ax.set_title("Empirical Sequence Recovery Benchmark (Held-out PDB Structures)", fontsize=12, fontweight="bold")
    ax.grid(axis="y", alpha=0.3)
    ax.set_ylim(0, max(recoveries) * 1.18)

    for bar in bars:
        h = bar.get_height()
        ax.annotate(f"{h:.1f}%", xy=(bar.get_x() + bar.get_width() / 2, h),
                    xytext=(0, 4), textcoords="offset points", ha="center", va="bottom",
                    fontweight="bold", fontsize=10)

    plt.xticks(rotation=15, ha="right", fontsize=10)
    plt.tight_layout()
    bench_path = os.path.join(results_dir, "benchmark_comparison.png")
    plt.savefig(bench_path)
    plt.close()
    print(f"Saved: {bench_path}")

    # Figure 3: Biochemical Class Breakdown
    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=150)
    classes = list(AA_CLASSES.keys())
    short_labels = ["Hydrophobic Core", "Polar / Charged Surface", "Conformational Pivots (G,P)", "Disulfide (C)"]
    trained_cls_rec = [final_trained_metrics["class_recovery"][c] * 100 for c in classes]

    x = np.arange(len(classes))
    width = 0.35

    if pretrained_metrics:
        pre_cls_rec = [pretrained_metrics["class_recovery"][c] * 100 for c in classes]
        b1 = ax.bar(x - width/2, trained_cls_rec, width, label="Trained (36 Backbones)", color="#42a5f5", edgecolor="black")
        b2 = ax.bar(x + width/2, pre_cls_rec, width, label="Pretrained (Full PDB)", color="#2e7d32", edgecolor="black")
        for b in list(b1) + list(b2):
            h = b.get_height()
            ax.annotate(f"{h:.1f}%", xy=(b.get_x() + b.get_width() / 2, h),
                        xytext=(0, 3), textcoords="offset points", ha="center", va="bottom",
                        fontsize=9)
    else:
        b1 = ax.bar(x, trained_cls_rec, width, label="Trained (36 Backbones)", color="#42a5f5", edgecolor="black")
        for b in b1:
            h = b.get_height()
            ax.annotate(f"{h:.1f}%", xy=(b.get_x() + b.get_width() / 2, h),
                        xytext=(0, 3), textcoords="offset points", ha="center", va="bottom",
                        fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(short_labels, fontsize=10)
    ax.set_ylabel("Sequence Recovery (%)", fontsize=11)
    ax.set_title("Held-out Recovery by Structural Microenvironment", fontsize=12, fontweight="bold")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(frameon=True)
    plt.tight_layout()
    cls_path = os.path.join(results_dir, "biochemical_class_recovery.png")
    plt.savefig(cls_path)
    plt.close()
    print(f"Saved: {cls_path}")

    # 7. Write Summary JSON Report
    report = {
        "dataset": {
            "total_structures": len(dataset),
            "train_structures": len(train_set),
            "val_structures": len(val_set),
            "test_structures": len(test_set),
            "total_train_residues": split_info["total_train_residues"],
            "total_val_residues": split_info["total_val_residues"],
            "total_test_residues": split_info["total_test_residues"],
            "train_pdb_ids": split_info["train_pdb_ids"],
            "val_pdb_ids": split_info["val_pdb_ids"],
            "test_pdb_ids": split_info["test_pdb_ids"],
            "protocol": "test scored once, after training, with the checkpoint chosen on validation",
            "split_by": "sequence-similarity cluster (5-mer Jaccard >= 0.3, single linkage)",
            "test_structures_sharing_half_their_kmers_with_train": len(leak),
        },
        "baselines": {
            "random": {"recovery": random_recovery, "perplexity": random_perplexity},
            "frequency": freq_base,
            "untrained": untrained_metrics,
        },
        "trained_model": {
            "epochs": epochs,
            "final_train_loss": history["train_loss"][-1],
            "final_train_recovery": history["train_recovery"][-1],
            "heldout_test_metrics": final_trained_metrics,
        },
        "pretrained_pdb_model": pretrained_metrics,
        "history": history,
    }
    report_path = os.path.join(results_dir, "training_summary.json")
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"Saved: {report_path}")

    print("\n=== Benchmark Summary ===")
    print(f"Random Baseline Recovery:      {random_recovery*100:.2f}% (Perplexity: 20.0)")
    print(f"Frequency Baseline Recovery:   {freq_base['test_recovery']*100:.2f}% (Most frequent: {freq_base['top_amino_acid']})")
    print(f"Untrained ProteinMPNN Recovery:{untrained_metrics['recovery']*100:.2f}% (Perplexity: {untrained_metrics['perplexity']:.2f})")
    print(f"Trained ProteinMPNN Recovery:  {final_trained_metrics['recovery']*100:.2f}% (Perplexity: {final_trained_metrics['perplexity']:.2f})")
    if pretrained_metrics:
        print(f"Pretrained ProteinMPNN Recovery: {pretrained_metrics['recovery']*100:.2f}% (Perplexity: {pretrained_metrics['perplexity']:.2f})")


if __name__ == "__main__":
    main()
