import argparse
import copy
import random
import re
import shutil
import time
import numpy as np
import pandas as pd
import torch
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader, Subset
import matplotlib.pyplot as plt
from pathlib import Path
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    average_precision_score,
    matthews_corrcoef,
    roc_curve,
    precision_recall_curve,
)

from prott5_gt_dataset import (
    resolve_data_dir,
    ProtT5BatchExtractor,
    ProteinGraphTransformerDataset,
    collate_graph_transformer_batch,
)
from graph_transformer_model import (
    ProtT5GraphTransformer,
    LabelSmoothedFocalLoss,
    masked_l1_reconstruction_loss,
)
from pssm_evo_features import (
    extract_four_pssm_descriptors,
    load_multimodal_algpro_lookup,
)
from evo_hybrid_fusion_model import (
    EvoHybridOnlyClassifier,
    MultimodalGTHybridModel,
)


# Experiment Suite
EXPERIMENT_SUITE = [
    {
        "key": "full",
        "name": "Full_Multimodal_GT_MLP_CNN_MHSA",
        "description": "Full Model: ProtT5 4-Layer Graph Transformer + 4 Residual MLP Experts + DeepAlgPro CNN-MHSA + Bidirectional Cross-Modal Attention + Dual-Loss",
        "mode": "multimodal",
        "evo_arch": "hybrid",
        "use_cross_attn": True,
        "recon_weight": 0.1,
    },
    {
        "key": "gt_only",
        "name": "Ablation_1_GT_Only",
        "description": "Unimodal Structural: ProtT5 + 4-Layer Graph Transformer Only (w/o Evolutionary Branch & Cross-Modal Attention)",
        "mode": "gt_only",
        "evo_arch": "none",
        "use_cross_attn": False,
        "recon_weight": 0.1,
    },
    {
        "key": "evo_hybrid_only",
        "name": "Ablation_2_Evo_Hybrid_Only",
        "description": "Unimodal Evolutionary Hybrid: 4 Residual MLP Experts + DeepAlgPro CNN-MHSA Only (w/o Graph Transformer)",
        "mode": "evo_only",
        "evo_arch": "hybrid",
        "use_cross_attn": False,
        "recon_weight": 0.0,
    },
    {
        "key": "evo_mlp_only",
        "name": "Ablation_3_Evo_MLP_Only",
        "description": "Unimodal Evolutionary FNN: 4 Modality-Specific Residual MLP Experts Only (w/o Graph Transformer & w/o CNN-MHSA)",
        "mode": "evo_only",
        "evo_arch": "mlp",
        "use_cross_attn": False,
        "recon_weight": 0.0,
    },
    {
        "key": "evo_cnn_mhsa_only",
        "name": "Ablation_4_Evo_CNN_MHSA_Only",
        "description": "Unimodal Evolutionary CNN+MHSA: 20x60 Amino-Acid Profile 1D-CNN + Multi-Head Self-Attention Only (w/o Graph Transformer & w/o MLP Experts)",
        "mode": "evo_only",
        "evo_arch": "cnn_mhsa",
        "use_cross_attn": False,
        "recon_weight": 0.0,
    },
    {
        "key": "no_cnn_mhsa",
        "name": "Ablation_5_GT_plus_MLP_No_CNN_MHSA",
        "description": "Multimodal Ablation (w/o CNN-MHSA): ProtT5-GT + 4 Residual MLP Experts + Cross-Modal Attention + Dual-Loss",
        "mode": "multimodal",
        "evo_arch": "mlp",
        "use_cross_attn": True,
        "recon_weight": 0.1,
    },
    {
        "key": "no_mlp",
        "name": "Ablation_6_GT_plus_CNN_MHSA_No_MLP",
        "description": "Multimodal Ablation (w/o Residual MLPs): ProtT5-GT + DeepAlgPro CNN-MHSA + Cross-Modal Attention + Dual-Loss",
        "mode": "multimodal",
        "evo_arch": "cnn_mhsa",
        "use_cross_attn": True,
        "recon_weight": 0.1,
    },
    {
        "key": "no_cross_attn",
        "name": "Ablation_7_No_CrossModal_Attention",
        "description": "Multimodal Ablation (w/o Cross-Modal Attention): ProtT5-GT + 5-Expert Hybrid Evo fused via Direct Concatenation",
        "mode": "multimodal",
        "evo_arch": "hybrid",
        "use_cross_attn": False,
        "recon_weight": 0.1,
    },
    {
        "key": "no_recon_loss",
        "name": "Ablation_8_No_Reconstruction_Loss",
        "description": "Multimodal Ablation (w/o Dual-Loss Reconstruction): Full Architecture trained with Classification Loss Only (lambda_recon = 0)",
        "mode": "multimodal",
        "evo_arch": "hybrid",
        "use_cross_attn": True,
        "recon_weight": 0.0,
    },
]


def resolve_algpro_dir(explicit_dir: str, data_dir: Path, base_dir: Path) -> Path | None:
    if explicit_dir:
        p = Path(explicit_dir)
        p = p if p.is_absolute() else (base_dir / p)
        if not p.is_dir():
            raise FileNotFoundError(f"Multimodal-AlgPro Independent directory not found: {p}")
        return p

    for cand in [
        base_dir / "descriptors",
        data_dir / "descriptors",
        base_dir / "Independent",
        base_dir / "data" / "Independent",
        data_dir / "Independent",
        base_dir / "examples" / "Multimodal-AlgPro" / "data" / "Independent",
    ]:
        if (cand / "trpo-pssm400.txt").exists() and (cand / "trpos2840.txt").exists():
            return cand
    return None


def signed_log1p_descriptors(desc: torch.Tensor) -> torch.Tensor:
    """
    Compresses heavy-tailed outliers in PSSM400 (max ~183.7) and DPC_PSSM (max ~22.1)
    while preserving sign and zero before per-fold z-score standardization.
    """
    return torch.sign(desc) * torch.log1p(torch.abs(desc))


class ModelEMA:
    """
    Exponential Moving Average (EMA) of model weights.
    Smooths out batch-level stochastic oscillations so validation F1, AUROC, and AUPRC
    improve steadily across epochs without prematurely tripping patience=15.
    """
    def __init__(self, model: torch.nn.Module, decay: float = 0.992):
        self.ema = copy.deepcopy(model).eval()
        for p in self.ema.parameters():
            p.requires_grad_(False)
        self.decay = decay

    @torch.no_grad()
    def update(self, model: torch.nn.Module):
        for ema_p, p in zip(self.ema.parameters(), model.parameters()):
            ema_p.data.mul_(self.decay).add_(p.data, alpha=1.0 - self.decay)


class MultimodalProteinDataset(Dataset):
    """
    Wraps ProteinGraphTransformerDataset and attaches the 1,410-dim 4-property
    evolutionary descriptors (PSSM400, DPC_PSSM, DFMCA_PSSM, Single_Average).
    """
    def __init__(
        self,
        base_ds: ProteinGraphTransformerDataset,
        algpro_lookup: dict[str, torch.Tensor] | None = None,
    ):
        self.base_ds = base_ds
        self.records = base_ds.records
        self.descriptors = []

        t0 = time.perf_counter()
        matched_algpro = 0
        fallback_blosum = 0

        for _, seq_str, _ in self.records:
            norm_s = re.sub(r"[^A-Z]", "", seq_str.strip().upper())
            if algpro_lookup is not None and norm_s in algpro_lookup:
                raw_vec = algpro_lookup[norm_s]
                matched_algpro += 1
            else:
                raw_vec = extract_four_pssm_descriptors(seq_str)
                fallback_blosum += 1
            self.descriptors.append(signed_log1p_descriptors(raw_vec))

        print(
            f"Prepared 1,410-dim descriptors for {len(self.descriptors)} sequences in {time.perf_counter() - t0:.2f}s "
            f"(Multimodal-AlgPro PSI-BLAST: {matched_algpro}, BLOSUM62 fallback: {fallback_blosum})"
        )

    def __len__(self):
        return len(self.base_ds)

    def __getitem__(self, idx: int):
        x, y, rec_id = self.base_ds[idx]
        desc = self.descriptors[idx]
        return x, desc, y, rec_id


class FastDescriptorOnlyView(Dataset):
    """
    Lightweight view over MultimodalProteinDataset for Evolutionary-Only ablations
    (Ablation 2, 3, 4). Skips loading [L, 1024] ProtT5 tensors from disk so each
    evolutionary ablation trains in seconds per fold.
    """
    def __init__(self, mm_ds: MultimodalProteinDataset):
        self.records = mm_ds.records
        self.descriptors = mm_ds.descriptors

    def __len__(self):
        return len(self.records)

    def __getitem__(self, idx: int):
        rec_id, _, label = self.records[idx]
        desc = self.descriptors[idx]
        y = torch.tensor(label, dtype=torch.float32)
        return desc, y, rec_id


def collate_multimodal_batch(batch):
    xs, descs, ys, rec_ids = zip(*batch)
    batch_size = len(xs)
    feat_dim = xs[0].size(-1)
    max_len = max(x.size(0) for x in xs)

    padded_x = torch.zeros((batch_size, max_len, feat_dim), dtype=torch.float32)
    residue_mask = torch.zeros((batch_size, max_len), dtype=torch.bool)
    for i, x in enumerate(xs):
        v_len = x.size(0)
        padded_x[i, :v_len, :] = x
        residue_mask[i, :v_len] = True

    stacked_desc = torch.stack(descs, dim=0)  # [B, 1410]
    labels = torch.stack(ys, dim=0).view(batch_size, 1)
    return padded_x, residue_mask, stacked_desc, labels, list(rec_ids)


def collate_evo_only_batch(batch):
    descs, ys, rec_ids = zip(*batch)
    stacked_desc = torch.stack(descs, dim=0)  # [B, 1410]
    labels = torch.stack(ys, dim=0).view(len(descs), 1)
    return stacked_desc, labels, list(rec_ids)


def apply_node_feature_masking(
    padded_x: torch.Tensor, residue_mask: torch.Tensor, mask_prob: float = 0.15
) -> torch.Tensor:
    if mask_prob <= 0.0:
        return padded_x
    drop_mask = (torch.rand(residue_mask.shape, device=padded_x.device) < mask_prob) & residue_mask
    x_corrupted = padded_x.clone()
    x_corrupted[drop_mask] = 0.0
    return x_corrupted


def compute_metrics(y_true: np.ndarray, y_probs: np.ndarray, threshold: float = 0.5) -> dict:
    y_pred = (y_probs >= threshold).astype(np.int32)
    return {
        "acc": float(accuracy_score(y_true, y_pred)),
        "prec": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "auc": float(roc_auc_score(y_true, y_probs)),
        "auprc": float(average_precision_score(y_true, y_probs)),
        "mcc": float(matthews_corrcoef(y_true, y_pred)),
    }


@torch.no_grad()
def evaluate_variant_loader(
    model,
    loader,
    criterion_cls,
    device,
    mode: str,
    recon_weight: float = 0.1,
    desc_mean=None,
    desc_std=None,
):
    model.eval()
    all_probs, all_labels, all_ids = [], [], []
    total_loss = 0.0
    total_samples = 0

    for batch in loader:
        if mode == "evo_only":
            desc, labels, rec_ids = batch
            bs = desc.size(0)
            desc = desc.to(device)
            if desc_mean is not None and desc_std is not None:
                desc = (desc - desc_mean) / desc_std
            labels_dev = labels.to(device)
            logits = model(desc)
            loss = criterion_cls(logits, labels_dev)
        elif mode == "gt_only":
            padded_x, residue_mask, labels, rec_ids = batch
            bs = padded_x.size(0)
            padded_x = padded_x.to(device)
            residue_mask = residue_mask.to(device)
            labels_dev = labels.to(device)
            logits, x_recon, _ = model(padded_x, residue_mask)
            loss_cls = criterion_cls(logits, labels_dev)
            loss_recon = masked_l1_reconstruction_loss(x_recon, padded_x, residue_mask)
            loss = loss_cls + recon_weight * loss_recon
        else:
            padded_x, residue_mask, desc, labels, rec_ids = batch
            bs = padded_x.size(0)
            padded_x = padded_x.to(device)
            residue_mask = residue_mask.to(device)
            desc = desc.to(device)
            if desc_mean is not None and desc_std is not None:
                desc = (desc - desc_mean) / desc_std
            labels_dev = labels.to(device)
            logits, x_recon, _ = model(padded_x, residue_mask, desc)
            loss_cls = criterion_cls(logits, labels_dev)
            loss_recon = masked_l1_reconstruction_loss(x_recon, padded_x, residue_mask)
            loss = loss_cls + recon_weight * loss_recon

        total_loss += loss.item() * bs
        total_samples += bs

        probs = torch.sigmoid(logits).view(-1).cpu().numpy()
        all_probs.append(probs)
        all_labels.append(labels.view(-1).numpy().astype(np.int32))
        all_ids.extend(rec_ids)

    y_true = np.concatenate(all_labels, axis=0)
    y_probs = np.concatenate(all_probs, axis=0)
    metrics = compute_metrics(y_true, y_probs)
    metrics["loss"] = float(total_loss / max(total_samples, 1))
    return y_true, y_probs, all_ids, metrics


def upsert_dataframe_csv(csv_path: Path, new_rows: list[dict], key_cols: list[str]):
    """
    Inserts or updates rows in a CSV file on disk immediately after a model/fold finishes
    so results are continuously persisted without duplicates.
    """
    new_df = pd.DataFrame(new_rows)
    if csv_path.exists():
        try:
            old_df = pd.read_csv(csv_path)
            combined = pd.concat([old_df, new_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=key_cols, keep="last")
            combined.to_csv(csv_path, index=False)
            return
        except Exception:
            pass
    new_df.to_csv(csv_path, index=False)


def plot_single_variant_curves(
    variant_name: str, y_true: np.ndarray, y_probs: np.ndarray, metrics: dict, out_png: Path
):
    plt.rcParams.update({"font.size": 11, "font.family": "sans-serif"})
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5), dpi=300)

    fpr, tpr, _ = roc_curve(y_true, y_probs)
    prec, rec, _ = precision_recall_curve(y_true, y_probs)

    ax1.plot(
        fpr, tpr, color="#d62728", lw=2.4,
        label=f"{variant_name} (AUROC = {metrics['auc']:.4f})"
    )
    ax1.plot([0, 1], [0, 1], color="navy", lw=1.2, linestyle="--", alpha=0.6)
    ax1.set_xlim([0.0, 1.0])
    ax1.set_ylim([0.0, 1.02])
    ax1.set_xlabel("False Positive Rate", fontweight="bold")
    ax1.set_ylabel("True Positive Rate", fontweight="bold")
    ax1.set_title("Receiver Operating Characteristic (ROC) Curve", fontweight="bold", pad=10)
    ax1.legend(loc="lower right", frameon=True, fontsize=9)
    ax1.grid(True, linestyle=":", alpha=0.5)

    ax2.plot(
        rec, prec, color="#1f77b4", lw=2.4,
        label=f"{variant_name} (AUPRC = {metrics['auprc']:.4f})"
    )
    ax2.plot([0, 1], [1, 0], color="navy", lw=1.2, linestyle="--", alpha=0.6)
    ax2.set_xlim([0.0, 1.0])
    ax2.set_ylim([0.0, 1.02])
    ax2.set_xlabel("Recall", fontweight="bold")
    ax2.set_ylabel("Precision", fontweight="bold")
    ax2.set_title("Precision-Recall (PR) Curve", fontweight="bold", pad=10)
    ax2.legend(loc="lower left", frameon=True, fontsize=9)
    ax2.grid(True, linestyle=":", alpha=0.5)

    plt.tight_layout()
    plt.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close()


def plot_multi_variant_comparison(curve_store: list[dict], out_png: Path):
    if not curve_store:
        return
    plt.rcParams.update({"font.size": 10, "font.family": "sans-serif"})
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6.2), dpi=300)

    palette = [
        "#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e",
        "#8c564b", "#e377c2", "#17becf", "#7f7f7f",
    ]
    for idx, item in enumerate(curve_store):
        color = palette[idx % len(palette)]
        lw = 2.6 if idx == 0 else 1.7
        alpha = 1.0 if idx == 0 else 0.85
        fpr, tpr, _ = roc_curve(item["y_true"], item["y_probs"])
        prec, rec, _ = precision_recall_curve(item["y_true"], item["y_probs"])

        ax1.plot(
            fpr, tpr, color=color, lw=lw, alpha=alpha,
            label=f"{item['name']} (AUROC={item['metrics']['auc']:.4f})"
        )
        ax2.plot(
            rec, prec, color=color, lw=lw, alpha=alpha,
            label=f"{item['name']} (AUPRC={item['metrics']['auprc']:.4f})"
        )

    ax1.plot([0, 1], [0, 1], color="navy", lw=1.1, linestyle="--", alpha=0.5)
    ax1.set_xlim([0.0, 1.0])
    ax1.set_ylim([0.0, 1.02])
    ax1.set_xlabel("False Positive Rate", fontweight="bold")
    ax1.set_ylabel("True Positive Rate", fontweight="bold")
    ax1.set_title("Full Model vs. Ablations — Independent Test ROC", fontweight="bold")
    ax1.legend(loc="lower right", frameon=True, fontsize=8)
    ax1.grid(True, linestyle=":", alpha=0.5)

    ax2.plot([0, 1], [1, 0], color="navy", lw=1.1, linestyle="--", alpha=0.5)
    ax2.set_xlim([0.0, 1.0])
    ax2.set_ylim([0.0, 1.02])
    ax2.set_xlabel("Recall", fontweight="bold")
    ax2.set_ylabel("Precision", fontweight="bold")
    ax2.set_title("Full Model vs. Ablations — Independent Test PR", fontweight="bold")
    ax2.legend(loc="lower left", frameon=True, fontsize=8)
    ax2.grid(True, linestyle=":", alpha=0.5)

    plt.tight_layout()
    plt.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close()


def build_variant_model(exp_cfg: dict, args, device: torch.device):
    mode = exp_cfg["mode"]
    if mode == "gt_only":
        model = ProtT5GraphTransformer(
            prot_dim=1024, hidden_dim=args.hidden_dim, out_dim=192, num_heads=4, dropout=0.2
        ).to(device)
        optimizer = optim.AdamW(
            model.parameters(), lr=args.lr, weight_decay=1e-4, betas=(0.9, 0.999)
        )
        return model, optimizer

    if mode == "evo_only":
        model = EvoHybridOnlyClassifier(
            desc_dim=1410, hidden_dim=192, dropout=0.25, arch=exp_cfg["evo_arch"]
        ).to(device)
        optimizer = optim.AdamW(
            model.parameters(), lr=args.lr, weight_decay=5e-4, betas=(0.9, 0.999)
        )
        return model, optimizer

    model = MultimodalGTHybridModel(
        prot_dim=1024,
        gt_hidden_dim=args.hidden_dim,
        desc_dim=1410,
        hidden_dim=192,
        dropout=0.2,
        evo_arch=exp_cfg["evo_arch"],
        use_cross_attn=exp_cfg["use_cross_attn"],
    ).to(device)

    gt_params = list(model.gt_branch.parameters())
    evo_and_fusion_params = (
        list(model.evo_branch.parameters())
        + list(model.fusion_module.parameters())
        + list(model.fusion_proj.parameters())
        + list(model.classifier.parameters())
        + [model.fusion_logit_scale, model.evo_logit_scale]
    )
    optimizer = optim.AdamW(
        [
            {"params": gt_params, "lr": args.lr, "weight_decay": 1e-4},
            {"params": evo_and_fusion_params, "lr": args.lr * 0.6, "weight_decay": 1e-3},
        ],
        betas=(0.9, 0.999),
    )
    return model, optimizer


def run_single_experiment(
    exp_cfg: dict,
    args,
    device: torch.device,
    base_dir: Path,
    train_mm_ds: MultimodalProteinDataset,
    test_mm_ds: MultimodalProteinDataset,
    train_evo_ds: FastDescriptorOnlyView,
    test_evo_ds: FastDescriptorOnlyView,
    summary_csv_path: Path,
    details_csv_path: Path,
    epoch_csv_path: Path,
) -> dict:
    v_key = exp_cfg["key"]
    v_name = exp_cfg["name"]
    v_desc = exp_cfg["description"]
    mode = exp_cfg["mode"]
    recon_weight = exp_cfg["recon_weight"]

    print(f"\n{'#' * 100}")
    print(f"### STARTING EXPERIMENT: {v_name} ({v_key})")
    print(f"### Description: {v_desc}")
    print(
        f"### Locked Hyperparameters | batch_size={args.batch_size} | epochs={args.epochs} | "
        f"patience={args.patience} | folds={args.folds} | lr={args.lr:.1e}"
    )
    print(f"{'#' * 100}")

    t_exp_start = time.perf_counter()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    criterion_cls = LabelSmoothedFocalLoss(alpha=0.5, gamma=1.0, smoothing=0.1)
    final_model_path = base_dir / f"model_{v_key}.pt"
    if v_key == "full":
        # Also maintain canonical model_multimodal.pt for backwards compatibility
        canonical_full_path = base_dir / "model_multimodal.pt"
    else:
        canonical_full_path = None

    all_labels = np.array([int(rec[2]) for rec in train_mm_ds.records])
    skf = StratifiedKFold(n_splits=args.folds, shuffle=True, random_state=args.seed)
    use_amp = device.type == "cuda"

    fold_best_metrics = []
    fold_epochs_trained = []
    best_overall_score = -1.0
    best_fold_idx = 1
    best_norm_stats = None
    detail_rows = []
    epoch_rows = []

    for fold_idx, (train_idx, valid_idx) in enumerate(skf.split(np.zeros(len(all_labels)), all_labels), start=1):
        print(f"\n-------------------- [{v_name}] Fold {fold_idx} / {args.folds} --------------------")

        # Per-fold z-score standardization fit strictly on training fold descriptors
        if mode in ("multimodal", "evo_only"):
            train_desc_tensor = torch.stack([train_mm_ds.descriptors[i] for i in train_idx], dim=0)
            desc_mean = train_desc_tensor.mean(dim=0, keepdim=True).to(device)
            desc_std = train_desc_tensor.std(dim=0, keepdim=True).clamp(min=1e-6).to(device)
        else:
            desc_mean, desc_std = None, None

        if mode == "evo_only":
            train_loader = DataLoader(
                Subset(train_evo_ds, train_idx.tolist()),
                batch_size=args.batch_size,
                shuffle=True,
                collate_fn=collate_evo_only_batch,
            )
            valid_loader = DataLoader(
                Subset(train_evo_ds, valid_idx.tolist()),
                batch_size=args.batch_size,
                shuffle=False,
                collate_fn=collate_evo_only_batch,
            )
        elif mode == "gt_only":
            train_loader = DataLoader(
                Subset(train_mm_ds.base_ds, train_idx.tolist()),
                batch_size=args.batch_size,
                shuffle=True,
                collate_fn=collate_graph_transformer_batch,
            )
            valid_loader = DataLoader(
                Subset(train_mm_ds.base_ds, valid_idx.tolist()),
                batch_size=args.batch_size,
                shuffle=False,
                collate_fn=collate_graph_transformer_batch,
            )
        else:
            train_loader = DataLoader(
                Subset(train_mm_ds, train_idx.tolist()),
                batch_size=args.batch_size,
                shuffle=True,
                collate_fn=collate_multimodal_batch,
            )
            valid_loader = DataLoader(
                Subset(train_mm_ds, valid_idx.tolist()),
                batch_size=args.batch_size,
                shuffle=False,
                collate_fn=collate_multimodal_batch,
            )

        model, optimizer = build_variant_model(exp_cfg, args, device)
        ema = ModelEMA(model, decay=0.992)

        warmup_epochs = min(8, max(1, args.epochs // 10))
        warmup_sched = optim.lr_scheduler.LinearLR(
            optimizer, start_factor=0.1, end_factor=1.0, total_iters=warmup_epochs
        )
        cosine_sched = optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=max(1, args.epochs - warmup_epochs), eta_min=5e-6
        )
        scheduler = optim.lr_scheduler.SequentialLR(
            optimizer, schedulers=[warmup_sched, cosine_sched], milestones=[warmup_epochs]
        )
        scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

        fold_save_path = base_dir / f"model_{v_key}.fold{fold_idx}.pt"
        best_fold_score = -1.0
        best_fold_f1 = -1.0
        best_fold_auc = -1.0
        best_fold_auprc = -1.0
        best_fold_m = None
        best_epoch = 1
        epochs_no_improve = 0
        min_epochs = 20 if mode == "evo_only" else args.min_epochs

        for epoch in range(1, args.epochs + 1):
            t0 = time.perf_counter()
            model.train()
            train_loss_sum = 0.0
            train_samples = 0

            for batch in train_loader:
                optimizer.zero_grad()
                if mode == "evo_only":
                    desc, labels, _ = batch
                    bs = desc.size(0)
                    desc = (desc.to(device) - desc_mean) / desc_std
                    desc = desc + 0.03 * torch.randn_like(desc)
                    labels_dev = labels.to(device)
                    with torch.amp.autocast("cuda", enabled=use_amp):
                        logits = model(desc)
                        loss = criterion_cls(logits, labels_dev)
                elif mode == "gt_only":
                    padded_x, residue_mask, labels, _ = batch
                    bs = padded_x.size(0)
                    padded_x = padded_x.to(device)
                    residue_mask = residue_mask.to(device)
                    labels_dev = labels.to(device)
                    x_input = apply_node_feature_masking(padded_x, residue_mask, mask_prob=args.mask_prob)
                    with torch.amp.autocast("cuda", enabled=use_amp):
                        logits, x_recon, _ = model(x_input, residue_mask)
                        loss_cls = criterion_cls(logits, labels_dev)
                        loss_recon = masked_l1_reconstruction_loss(x_recon, padded_x, residue_mask)
                        loss = loss_cls + recon_weight * loss_recon
                else:
                    padded_x, residue_mask, desc, labels, _ = batch
                    bs = padded_x.size(0)
                    padded_x = padded_x.to(device)
                    residue_mask = residue_mask.to(device)
                    desc = (desc.to(device) - desc_mean) / desc_std
                    desc = desc + 0.03 * torch.randn_like(desc)
                    labels_dev = labels.to(device)
                    x_input = apply_node_feature_masking(padded_x, residue_mask, mask_prob=args.mask_prob)
                    with torch.amp.autocast("cuda", enabled=use_amp):
                        logits, x_recon, _, gt_logits, evo_logits = model(
                            x_input, residue_mask, desc, return_aux=True
                        )
                        loss_joint = criterion_cls(logits, labels_dev)
                        loss_gt = criterion_cls(gt_logits, labels_dev)
                        loss_evo = criterion_cls(evo_logits, labels_dev)
                        loss_recon = masked_l1_reconstruction_loss(x_recon, padded_x, residue_mask)
                        loss = loss_joint + 0.5 * loss_gt + 0.25 * loss_evo + recon_weight * loss_recon

                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=0.5)
                scaler.step(optimizer)
                scaler.update()

                ema.update(model)

                train_loss_sum += loss.item() * bs
                train_samples += bs

            scheduler.step()

            _, _, _, val_m_ema = evaluate_variant_loader(
                ema.ema, valid_loader, criterion_cls, device,
                mode=mode, recon_weight=recon_weight, desc_mean=desc_mean, desc_std=desc_std,
            )
            _, _, _, val_m_raw = evaluate_variant_loader(
                model, valid_loader, criterion_cls, device,
                mode=mode, recon_weight=recon_weight, desc_mean=desc_mean, desc_std=desc_std,
            )
            score_ema = val_m_ema["f1"] + 0.5 * (val_m_ema["auc"] + val_m_ema["auprc"])
            score_raw = val_m_raw["f1"] + 0.5 * (val_m_raw["auc"] + val_m_raw["auprc"])
            if score_ema >= score_raw:
                val_m = val_m_ema
                eval_score = score_ema
                active_state = ema.ema.state_dict()
            else:
                val_m = val_m_raw
                eval_score = score_raw
                active_state = model.state_dict()

            elapsed = time.perf_counter() - t0
            avg_train_loss = float(train_loss_sum / max(train_samples, 1))

            print(
                f"[{v_key}] Fold {fold_idx} | Epoch {epoch:03d}/{args.epochs:03d} ({elapsed:.1f}s) | "
                f"Train Loss: {avg_train_loss:.4f} | Val Loss: {val_m['loss']:.4f} | "
                f"ACC: {val_m['acc']:.4f} | F1: {val_m['f1']:.4f} | Prec: {val_m['prec']:.4f} | "
                f"Recall: {val_m['recall']:.4f} | AUROC: {val_m['auc']:.4f} | AUPRC: {val_m['auprc']:.4f} | MCC: {val_m['mcc']:.4f}"
            )

            epoch_rows.append({
                "Variant": v_name,
                "Variant_Key": v_key,
                "Fold": fold_idx,
                "Epoch": epoch,
                "Train_Loss": round(avg_train_loss, 6),
                "Val_Loss": round(val_m["loss"], 6),
                "Val_ACC": round(val_m["acc"], 6),
                "Val_Precision": round(val_m["prec"], 6),
                "Val_Recall": round(val_m["recall"], 6),
                "Val_F1": round(val_m["f1"], 6),
                "Val_AUROC": round(val_m["auc"], 6),
                "Val_AUPRC": round(val_m["auprc"], 6),
                "Val_MCC": round(val_m["mcc"], 6),
            })

            improved_any = (
                eval_score > best_fold_score + 1e-5
                or val_m["f1"] > best_fold_f1 + 1e-5
                or val_m["auc"] > best_fold_auc + 1e-4
                or val_m["auprc"] > best_fold_auprc + 1e-4
            )
            if improved_any:
                epochs_no_improve = 0
                best_fold_f1 = max(best_fold_f1, val_m["f1"])
                best_fold_auc = max(best_fold_auc, val_m["auc"])
                best_fold_auprc = max(best_fold_auprc, val_m["auprc"])
                if eval_score >= best_fold_score:
                    best_fold_score = eval_score
                    best_fold_m = dict(val_m)
                    best_fold_m["train_loss"] = avg_train_loss
                    best_epoch = epoch
                    torch.save(
                        {
                            "model_state": copy.deepcopy(active_state),
                            "desc_mean": None if desc_mean is None else desc_mean.detach().cpu(),
                            "desc_std": None if desc_std is None else desc_std.detach().cpu(),
                        },
                        fold_save_path,
                    )
            else:
                if epoch >= min_epochs:
                    epochs_no_improve += 1
                    if epochs_no_improve >= args.patience:
                        print(f"  [Early Stopping] Patience {args.patience} reached at Epoch {epoch}.")
                        break

        fold_epochs_trained.append(epoch)
        fold_best_metrics.append(best_fold_m)

        detail_rows.append({
            "Variant": v_name,
            "Variant_Key": v_key,
            "Description": v_desc,
            "Split": f"Fold_{fold_idx}_Val",
            "Best_Epoch": best_epoch,
            "Epochs_Run": epoch,
            "Train_Loss": round(best_fold_m["train_loss"], 4),
            "Eval_Loss": round(best_fold_m["loss"], 4),
            "ACC": round(best_fold_m["acc"], 4),
            "Precision": round(best_fold_m["prec"], 4),
            "Recall": round(best_fold_m["recall"], 4),
            "F1": round(best_fold_m["f1"], 4),
            "AUROC": round(best_fold_m["auc"], 4),
            "AUPRC": round(best_fold_m["auprc"], 4),
            "MCC": round(best_fold_m["mcc"], 4),
        })
        upsert_dataframe_csv(details_csv_path, detail_rows, key_cols=["Variant", "Split"])
        upsert_dataframe_csv(epoch_csv_path, epoch_rows, key_cols=["Variant", "Fold", "Epoch"])

        if best_fold_score > best_overall_score:
            best_overall_score = best_fold_score
            best_fold_idx = fold_idx
            best_norm_stats = (
                None if desc_mean is None else desc_mean.detach().cpu(),
                None if desc_std is None else desc_std.detach().cpu(),
            )
            shutil.copyfile(fold_save_path, final_model_path)
            if canonical_full_path is not None:
                shutil.copyfile(fold_save_path, canonical_full_path)

    # Compute 5-Fold CV Mean & Std
    cv_mean = {k: float(np.mean([m[k] for m in fold_best_metrics])) for k in ["train_loss", "loss", "acc", "prec", "recall", "f1", "auc", "auprc", "mcc"]}
    cv_std = {k: float(np.std([m[k] for m in fold_best_metrics])) for k in ["train_loss", "loss", "acc", "prec", "recall", "f1", "auc", "auprc", "mcc"]}

    detail_rows.append({
        "Variant": v_name,
        "Variant_Key": v_key,
        "Description": v_desc,
        "Split": "5Fold_CV_Mean",
        "Best_Epoch": best_fold_idx,
        "Epochs_Run": round(float(np.mean(fold_epochs_trained)), 1),
        "Train_Loss": round(cv_mean["train_loss"], 4),
        "Eval_Loss": round(cv_mean["loss"], 4),
        "ACC": round(cv_mean["acc"], 4),
        "Precision": round(cv_mean["prec"], 4),
        "Recall": round(cv_mean["recall"], 4),
        "F1": round(cv_mean["f1"], 4),
        "AUROC": round(cv_mean["auc"], 4),
        "AUPRC": round(cv_mean["auprc"], 4),
        "MCC": round(cv_mean["mcc"], 4),
    })
    detail_rows.append({
        "Variant": v_name,
        "Variant_Key": v_key,
        "Description": v_desc,
        "Split": "5Fold_CV_Std",
        "Best_Epoch": best_fold_idx,
        "Epochs_Run": round(float(np.std(fold_epochs_trained)), 1),
        "Train_Loss": round(cv_std["train_loss"], 4),
        "Eval_Loss": round(cv_std["loss"], 4),
        "ACC": round(cv_std["acc"], 4),
        "Precision": round(cv_std["prec"], 4),
        "Recall": round(cv_std["recall"], 4),
        "F1": round(cv_std["f1"], 4),
        "AUROC": round(cv_std["auc"], 4),
        "AUPRC": round(cv_std["auprc"], 4),
        "MCC": round(cv_std["mcc"], 4),
    })

    # ==========================================================================
    # Independent Test Set Evaluation (all.test.fasta)
    # ==========================================================================
    if mode == "evo_only":
        test_loader = DataLoader(
            test_evo_ds, batch_size=args.batch_size, shuffle=False, collate_fn=collate_evo_only_batch
        )
    elif mode == "gt_only":
        test_loader = DataLoader(
            test_mm_ds.base_ds, batch_size=args.batch_size, shuffle=False, collate_fn=collate_graph_transformer_batch
        )
    else:
        test_loader = DataLoader(
            test_mm_ds, batch_size=args.batch_size, shuffle=False, collate_fn=collate_multimodal_batch
        )

    best_model, _ = build_variant_model(exp_cfg, args, device)
    ckpt = torch.load(final_model_path, map_location=device, weights_only=True)
    if isinstance(ckpt, dict) and "model_state" in ckpt:
        best_model.load_state_dict(ckpt["model_state"], strict=True)
        t_mean = None if ckpt.get("desc_mean") is None else ckpt["desc_mean"].to(device)
        t_std = None if ckpt.get("desc_std") is None else ckpt["desc_std"].to(device)
    else:
        best_model.load_state_dict(ckpt, strict=True)
        t_mean = None if best_norm_stats is None or best_norm_stats[0] is None else best_norm_stats[0].to(device)
        t_std = None if best_norm_stats is None or best_norm_stats[1] is None else best_norm_stats[1].to(device)

    y_true, y_probs, rec_ids, test_m = evaluate_variant_loader(
        best_model, test_loader, criterion_cls, device,
        mode=mode, recon_weight=recon_weight, desc_mean=t_mean, desc_std=t_std,
    )

    wall_sec = round(time.perf_counter() - t_exp_start, 2)

    detail_rows.append({
        "Variant": v_name,
        "Variant_Key": v_key,
        "Description": v_desc,
        "Split": "Independent_Test",
        "Best_Epoch": best_fold_idx,
        "Epochs_Run": round(float(np.mean(fold_epochs_trained)), 1),
        "Train_Loss": round(cv_mean["train_loss"], 4),
        "Eval_Loss": round(test_m["loss"], 4),
        "ACC": round(test_m["acc"], 4),
        "Precision": round(test_m["prec"], 4),
        "Recall": round(test_m["recall"], 4),
        "F1": round(test_m["f1"], 4),
        "AUROC": round(test_m["auc"], 4),
        "AUPRC": round(test_m["auprc"], 4),
        "MCC": round(test_m["mcc"], 4),
    })
    upsert_dataframe_csv(details_csv_path, detail_rows, key_cols=["Variant", "Split"])

    # Upsert summary row into ablation_summary_results.csv immediately
    summary_row = {
        "Variant": v_name,
        "Variant_Key": v_key,
        "Description": v_desc,
        "CV_Train_Loss_Mean": round(cv_mean["train_loss"], 4),
        "CV_Val_Loss_Mean": round(cv_mean["loss"], 4),
        "CV_ACC_Mean": round(cv_mean["acc"], 4),
        "CV_ACC_Std": round(cv_std["acc"], 4),
        "CV_Precision_Mean": round(cv_mean["prec"], 4),
        "CV_Precision_Std": round(cv_std["prec"], 4),
        "CV_Recall_Mean": round(cv_mean["recall"], 4),
        "CV_Recall_Std": round(cv_std["recall"], 4),
        "CV_F1_Mean": round(cv_mean["f1"], 4),
        "CV_F1_Std": round(cv_std["f1"], 4),
        "CV_AUROC_Mean": round(cv_mean["auc"], 4),
        "CV_AUROC_Std": round(cv_std["auc"], 4),
        "CV_AUPRC_Mean": round(cv_mean["auprc"], 4),
        "CV_AUPRC_Std": round(cv_std["auprc"], 4),
        "CV_MCC_Mean": round(cv_mean["mcc"], 4),
        "CV_MCC_Std": round(cv_std["mcc"], 4),
        "Test_Loss": round(test_m["loss"], 4),
        "Test_ACC": round(test_m["acc"], 4),
        "Test_Precision": round(test_m["prec"], 4),
        "Test_Recall": round(test_m["recall"], 4),
        "Test_F1": round(test_m["f1"], 4),
        "Test_AUROC": round(test_m["auc"], 4),
        "Test_AUPRC": round(test_m["auprc"], 4),
        "Test_MCC": round(test_m["mcc"], 4),
        "Best_Fold": best_fold_idx,
        "Avg_Epochs_Trained": round(float(np.mean(fold_epochs_trained)), 1),
        "Wall_Time_Sec": wall_sec,
    }
    upsert_dataframe_csv(summary_csv_path, [summary_row], key_cols=["Variant"])

    # Save per-variant predictions TSV & ROC/PR plot
    tsv_path = base_dir / f"test_predictions_{v_key}.tsv"
    rows = [
        [rec_ids[i], int(y_true[i]), round(float(y_probs[i]), 6),
         "allergenicity" if y_probs[i] >= 0.5 else "non-allergenicity"]
        for i in range(len(rec_ids))
    ]
    pd.DataFrame(rows, columns=["protein", "true_label", "score", "predict_result"]).to_csv(
        tsv_path, sep="\t", index=False
    )
    if v_key == "full":
        shutil.copyfile(tsv_path, base_dir / "test_predictions_multimodal.tsv")

    out_png = base_dir / f"{v_key}_auroc_auprc.png"
    plot_single_variant_curves(v_name, y_true, y_probs, test_m, out_png)
    if v_key == "full":
        shutil.copyfile(out_png, base_dir / "multimodal_auroc_auprc.png")

    print(
        f"\n>>> COMPLETED [{v_name}] in {wall_sec:.1f}s\n"
        f"    5-Fold CV  | ACC: {cv_mean['acc']:.4f}+/-{cv_std['acc']:.4f} | F1: {cv_mean['f1']:.4f}+/-{cv_std['f1']:.4f} | "
        f"AUROC: {cv_mean['auc']:.4f} | AUPRC: {cv_mean['auprc']:.4f} | MCC: {cv_mean['mcc']:.4f}\n"
        f"    Indep Test | ACC: {test_m['acc']:.4f} | Prec: {test_m['prec']:.4f} | Recall: {test_m['recall']:.4f} | "
        f"F1: {test_m['f1']:.4f} | AUROC: {test_m['auc']:.4f} | AUPRC: {test_m['auprc']:.4f} | MCC: {test_m['mcc']:.4f}\n"
        f"    Saved & updated CSVs: {summary_csv_path.name}, {details_csv_path.name}"
    )

    return {
        "name": v_name,
        "key": v_key,
        "y_true": y_true,
        "y_probs": y_probs,
        "metrics": test_m,
        "summary_row": summary_row,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Continuous Full-Model & Per-Component Ablation Training + Testing Suite (5-Fold CV + Independent Test CSV Logger)"
    )
    # Locked Hyperparameter Template:
    # 1) Batch size = 32 | 2) Epochs = 100 | 3) Patience = 15 | 4) Folds = 5 | 5) LR = 1e-4
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--patience", type=int, default=15)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--hidden-dim", type=int, default=256)
    parser.add_argument("--mask-prob", type=float, default=0.15)
    parser.add_argument("--min-epochs", type=int, default=25)
    parser.add_argument("--algpro-dir", type=str, default="", help="Path to descriptors folder containing trpo/trne/tepo/tene files")
    parser.add_argument(
        "--variants",
        type=str,
        default="all",
        help="Comma-separated variant keys to run, or 'all' (default: runs Full Model followed continuously by all 8 ablations)",
    )
    parser.add_argument(
        "--summary-csv",
        type=str,
        default="ablation_summary_results.csv",
        help="Main CSV file storing Full Model and Ablation 5-Fold CV + Independent Test results",
    )
    parser.add_argument(
        "--details-csv",
        type=str,
        default="ablation_fold_and_test_details.csv",
        help="Detailed CSV file storing per-fold (Fold 1..5), CV Mean/Std, and Independent Test rows",
    )
    parser.add_argument(
        "--epoch-csv",
        type=str,
        default="ablation_epoch_history.csv",
        help="Epoch-by-epoch training and validation history CSV across all variants",
    )
    parser.add_argument(
        "--overwrite-csv",
        action="store_true",
        help="If set, deletes existing CSV files before starting instead of resuming/updating",
    )
    parser.add_argument(
        "--force-rerun",
        action="store_true",
        help="If set, reruns variants even if they are already recorded in --summary-csv",
    )
    parser.add_argument("--model-name", type=str, default="Rostlab/prot_t5_xl_uniref50")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device} ({torch.cuda.get_device_name(0) if device.type == 'cuda' else 'CPU'})")
    print(
        f"Locked Hyperparameters | Batch Size: {args.batch_size} | Epochs: {args.epochs} | "
        f"Patience: {args.patience} | Folds: {args.folds} | LR: {args.lr:.1e}"
    )

    base_dir = Path(__file__).resolve().parent
    data_dir = resolve_data_dir()
    cache_dir = base_dir / "cache_prott5"

    summary_csv_path = base_dir / args.summary_csv
    details_csv_path = base_dir / args.details_csv
    epoch_csv_path = base_dir / args.epoch_csv

    if args.overwrite_csv:
        for p in (summary_csv_path, details_csv_path, epoch_csv_path):
            if p.exists():
                p.unlink()

    algpro_dir = resolve_algpro_dir(args.algpro_dir, data_dir, base_dir)
    algpro_lookup = load_multimodal_algpro_lookup(algpro_dir) if algpro_dir is not None else None

    extractor = ProtT5BatchExtractor(
        model_name=args.model_name,
        device=device,
        cache_dir=cache_dir,
    )

    train_base = ProteinGraphTransformerDataset(data_dir / "all.train.fasta", extractor=extractor)
    test_base = ProteinGraphTransformerDataset(data_dir / "all.test.fasta", extractor=extractor)
    extractor.unload_from_gpu()

    train_mm_ds = MultimodalProteinDataset(train_base, algpro_lookup=algpro_lookup)
    test_mm_ds = MultimodalProteinDataset(test_base, algpro_lookup=algpro_lookup)

    train_evo_ds = FastDescriptorOnlyView(train_mm_ds)
    test_evo_ds = FastDescriptorOnlyView(test_mm_ds)

    if args.variants.strip().lower() == "all":
        selected_suite = EXPERIMENT_SUITE
    else:
        wanted = {k.strip().lower() for k in args.variants.split(",") if k.strip()}
        selected_suite = [cfg for cfg in EXPERIMENT_SUITE if cfg["key"].lower() in wanted]
        if not selected_suite:
            valid_keys = ", ".join(cfg["key"] for cfg in EXPERIMENT_SUITE)
            raise ValueError(f"No matching --variants found for '{args.variants}'. Valid keys: {valid_keys}")

    completed_variants = set()
    if summary_csv_path.exists() and not args.overwrite_csv and not args.force_rerun:
        try:
            existing_df = pd.read_csv(summary_csv_path)
            if "Variant" in existing_df.columns:
                completed_variants = set(existing_df["Variant"].dropna().astype(str).tolist())
        except Exception:
            completed_variants = set()

    curve_store = []
    for exp_cfg in selected_suite:
        if exp_cfg["name"] in completed_variants:
            print(f"\n[Skipping {exp_cfg['name']}] Already recorded in {summary_csv_path.name} (pass --force-rerun to re-train).")
            continue
        res = run_single_experiment(
            exp_cfg=exp_cfg,
            args=args,
            device=device,
            base_dir=base_dir,
            train_mm_ds=train_mm_ds,
            test_mm_ds=test_mm_ds,
            train_evo_ds=train_evo_ds,
            test_evo_ds=test_evo_ds,
            summary_csv_path=summary_csv_path,
            details_csv_path=details_csv_path,
            epoch_csv_path=epoch_csv_path,
        )
        curve_store.append(res)
        # Update combined multi-model ROC/PR comparison plot after each variant completes
        plot_multi_variant_comparison(curve_store, base_dir / "ablation_comparison_auroc_auprc.png")

    print("\n" + "=" * 110)
    print("ALL REQUESTED FULL-MODEL & ABLATION EXPERIMENTS COMPLETED!")
    print(f"  1. Summary Table CSV (CV Mean/Std + Indep Test) : {summary_csv_path}")
    print(f"  2. Per-Fold & Test Details CSV                  : {details_csv_path}")
    print(f"  3. Epoch-by-Epoch Learning Curve History CSV    : {epoch_csv_path}")
    print(f"  4. Combined Multi-Model ROC & PR Curve Plot     : {base_dir / 'ablation_comparison_auroc_auprc.png'}")
    print("=" * 110)
    if summary_csv_path.exists():
        df_final = pd.read_csv(summary_csv_path)
        cols = [
            "Variant", "CV_ACC_Mean", "CV_F1_Mean", "CV_AUROC_Mean", "CV_AUPRC_Mean", "CV_MCC_Mean",
            "Test_ACC", "Test_Precision", "Test_Recall", "Test_F1", "Test_AUROC", "Test_AUPRC", "Test_MCC",
        ]
        print(df_final[[c for c in cols if c in df_final.columns]].to_string(index=False))


if __name__ == "__main__":
    main()