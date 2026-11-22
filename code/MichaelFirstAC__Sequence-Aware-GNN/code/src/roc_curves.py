"""
Phase 9: ROC curves (results/figures/roc_curves.png).

ROC curves need the per-pair test predictions, which multiseed.py does not save, so this script
retrains the four models ONCE (seed = config project.random_seed, default 42) on PrimeKG for both
splits and plots the test ROC curves. It keeps the best-validation weights in memory
(no .pt checkpoint files are written). Takes roughly as long as one seed of multiseed.py.
Usage: python src/roc_curves.py
"""
import copy
import os
import numpy as np
import torch
import torch.nn.functional as F
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_curve, roc_auc_score

from utils import load_config, setup_logger, set_seed
from dataset import build_splits, with_features, make_random_features, load_node_features
from models import GCNModel
from train import get_device, train_one_epoch, eval_model

logger = setup_logger("roc_curves")


def train_gcn(model, tr, va, te, cfg, device):
    model, tr, va, te = model.to(device), tr.to(device), va.to(device), te.to(device)
    opt = torch.optim.Adam(model.parameters(), lr=cfg["training"]["lr"])
    best, best_state, bad = 0.0, None, 0
    for _ in range(cfg["training"]["epochs"]):
        train_one_epoch(model, opt, tr)
        m, _, _ = eval_model(model, va)
        if m["AUC"] > best:
            best, best_state, bad = m["AUC"], copy.deepcopy(model.state_dict()), 0
        else:
            bad += 1
            if bad >= cfg["training"]["patience"]:
                break
    model.load_state_dict(best_state)
    _, probs, labels = eval_model(model, te)
    return labels, probs


def rf_probs(tr, te, seed):
    x, xt = tr.x.cpu().numpy(), te.x.cpu().numpy()
    s, d = tr.edge_label_index.cpu().numpy()
    Xtr = np.hstack([x[s], x[d]]); ytr = tr.edge_label.cpu().numpy().astype(int)
    s, d = te.edge_label_index.cpu().numpy()
    Xte = np.hstack([xt[s], xt[d]]); yte = te.edge_label.cpu().numpy().astype(int)
    rf = RandomForestClassifier(n_estimators=50, max_depth=12, random_state=seed, n_jobs=-1).fit(Xtr, ytr)
    return yte, rf.predict_proba(Xte)[:, 1]


def main():
    cfg = load_config("config.yaml")
    seed = cfg["project"]["random_seed"]
    device = get_device(cfg)
    proc, figs = cfg["data"]["processed_dir"], cfg["data"]["figures_dir"]
    os.makedirs(figs, exist_ok=True)
    h, do = cfg["training"]["hidden_dim"], cfg["training"]["dropout"]

    set_seed(seed)
    splits, node_to_idx, prots = build_splits(os.path.join(proc, "ppi_edges_uniprot.csv"), seed)
    feats = {
        "Structure only": make_random_features(len(prots), 64, seed),
        "GCN + ESM-2": load_node_features(os.path.join(proc, "esm2_embeddings.pt"), node_to_idx),
        "GCN + Classical": load_node_features(os.path.join(proc, "classical_features.pt"), node_to_idx),
    }
    fig, axes = plt.subplots(1, 2, figsize=(7.16, 3.2), sharey=True)
    for ax, (split_name, base) in zip(axes, splits.items()):
        curves = {}
        for label, x in feats.items():
            tr, va, te = with_features(base, x)
            set_seed(seed)
            curves[label] = train_gcn(GCNModel(x.size(1), h, do), tr, va, te, cfg, device)
        tr, va, te = with_features(base, feats["GCN + Classical"])
        curves["RF (Classical)"] = rf_probs(tr, te, seed)
        for label, (y, p) in curves.items():
            fpr, tpr, _ = roc_curve(y, p)
            ax.plot(fpr, tpr, lw=1.3, label=f"{label} (AUC = {roc_auc_score(y, p):.3f})")
        ax.plot([0, 1], [0, 1], "k--", lw=0.8)
        ax.set_title(split_name); ax.set_xlabel("False positive rate"); ax.grid(alpha=0.3)
        ax.legend(loc="lower right", fontsize=6.5)
    axes[0].set_ylabel("True positive rate")
    fig.tight_layout()
    fig.savefig(os.path.join(figs, "roc_curves.png"), dpi=300)
    logger.info("saved roc_curves.png")


if __name__ == "__main__":
    main()
