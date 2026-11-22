import argparse
import numpy as np
import pandas as pd
import torch
from pathlib import Path
from torch.utils.data import DataLoader, Subset
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    average_precision_score,
    matthews_corrcoef,
)

from prott5_gt_dataset import (
    resolve_data_dir,
    ProtT5BatchExtractor,
    ProteinGraphTransformerDataset,
    collate_graph_transformer_batch,
)
from pssm_evo_features import load_multimodal_algpro_lookup
from train_and_test_multimodal import (
    EXPERIMENT_SUITE,
    resolve_algpro_dir,
    MultimodalProteinDataset,
    FastDescriptorOnlyView,
    collate_multimodal_batch,
    collate_evo_only_batch,
    build_variant_model,
)


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
def predict_fold(ckpt_path: Path, exp_cfg: dict, args, loader: DataLoader, device: torch.device):
    model, _ = build_variant_model(exp_cfg, args, device)
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=True)
    if isinstance(ckpt, dict) and "model_state" in ckpt:
        model.load_state_dict(ckpt["model_state"], strict=True)
        desc_mean = None if ckpt.get("desc_mean") is None else ckpt["desc_mean"].to(device)
        desc_std = None if ckpt.get("desc_std") is None else ckpt["desc_std"].to(device)
    else:
        model.load_state_dict(ckpt, strict=True)
        desc_mean, desc_std = None, None
    model.eval()

    mode = exp_cfg["mode"]
    probs_list, labels_list, ids_list = [], [], []
    for batch in loader:
        if mode == "evo_only":
            desc, labels, rec_ids = batch
            desc = desc.to(device)
            if desc_mean is not None and desc_std is not None:
                desc = (desc - desc_mean) / desc_std
            logits = model(desc)
        elif mode == "gt_only":
            padded_x, residue_mask, labels, rec_ids = batch
            logits, _, _ = model(padded_x.to(device), residue_mask.to(device))
        else:
            padded_x, residue_mask, desc, labels, rec_ids = batch
            desc = desc.to(device)
            if desc_mean is not None and desc_std is not None:
                desc = (desc - desc_mean) / desc_std
            logits, _, _ = model(padded_x.to(device), residue_mask.to(device), desc)

        probs_list.append(torch.sigmoid(logits).view(-1).cpu().numpy())
        labels_list.append(labels.view(-1).numpy().astype(np.int32))
        ids_list.extend(rec_ids)

    return np.concatenate(probs_list), np.concatenate(labels_list), ids_list


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate all 5 CV fold checkpoints per variant on all.test.fasta + 5-Fold Ensemble"
    )
    parser.add_argument(
        "--variants",
        type=str,
        default="all",
        help="Comma-separated variant keys (e.g. full,no_cnn_mhsa) or 'all' (auto-runs every variant with all 5 fold checkpoints)",
    )
    parser.add_argument("--variant-key", type=str, default="", help="Alias for a single variant key")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--hidden-dim", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--algpro-dir", type=str, default="descriptors")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    cfg_map = {cfg["key"]: cfg for cfg in EXPERIMENT_SUITE}
    if args.variant_key:
        selected_keys = [args.variant_key]
    elif args.variants.strip().lower() == "all":
        selected_keys = [cfg["key"] for cfg in EXPERIMENT_SUITE]
    else:
        selected_keys = [k.strip() for k in args.variants.split(",") if k.strip()]

    for k in selected_keys:
        if k not in cfg_map:
            raise ValueError(f"Unknown variant key '{k}'. Valid: {', '.join(cfg_map.keys())}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    base_dir = Path(__file__).resolve().parent
    data_dir = resolve_data_dir()
    cache_dir = base_dir / "cache_prott5"

    run_cfgs = []
    for k in selected_keys:
        missing = [f for f in range(1, args.folds + 1) if not (base_dir / f"model_{k}.fold{f}.pt").exists()]
        if missing:
            if args.variant_key or args.variants.strip().lower() != "all":
                raise FileNotFoundError(f"Missing fold checkpoints for '{k}': folds {missing}")
            print(f"[Skipping {k}] Missing fold checkpoints on disk (folds {missing}).")
        else:
            run_cfgs.append(cfg_map[k])

    if not run_cfgs:
        raise RuntimeError("No complete 5-fold checkpoints found on disk.")

    algpro_dir = resolve_algpro_dir(args.algpro_dir, data_dir, base_dir)
    algpro_lookup = load_multimodal_algpro_lookup(algpro_dir) if algpro_dir is not None else None

    extractor = ProtT5BatchExtractor(device=device, cache_dir=cache_dir)
    train_base = ProteinGraphTransformerDataset(data_dir / "all.train.fasta", extractor=extractor)
    test_base = ProteinGraphTransformerDataset(data_dir / "all.test.fasta", extractor=extractor)
    extractor.unload_from_gpu()

    train_mm = MultimodalProteinDataset(train_base, algpro_lookup=algpro_lookup)
    test_mm = MultimodalProteinDataset(test_base, algpro_lookup=algpro_lookup)

    all_labels = np.array([int(rec[2]) for rec in train_mm.records])
    skf = StratifiedKFold(n_splits=args.folds, shuffle=True, random_state=args.seed)
    splits = list(skf.split(np.zeros(len(all_labels)), all_labels))

    fold_rows = []
    summary_rows = []

    for exp_cfg in run_cfgs:
        v_key = exp_cfg["key"]
        v_name = exp_cfg["name"]
        mode = exp_cfg["mode"]

        if mode == "evo_only":
            train_eval_ds = FastDescriptorOnlyView(train_mm)
            test_eval_ds = FastDescriptorOnlyView(test_mm)
            collate_fn = collate_evo_only_batch
        elif mode == "gt_only":
            train_eval_ds = train_mm.base_ds
            test_eval_ds = test_mm.base_ds
            collate_fn = collate_graph_transformer_batch
        else:
            train_eval_ds = train_mm
            test_eval_ds = test_mm
            collate_fn = collate_multimodal_batch

        test_loader = DataLoader(test_eval_ds, batch_size=args.batch_size, shuffle=False, collate_fn=collate_fn)

        oof_probs = np.zeros(len(all_labels), dtype=np.float32)
        test_fold_probs = []
        fold_metrics_list = []
        y_test = None

        print(f"\n{'=' * 100}")
        print(f"VARIANT: {v_name} ({v_key})")
        print(f"{'-' * 100}")

        for fold_idx, (_, valid_idx) in enumerate(splits, start=1):
            ckpt_path = base_dir / f"model_{v_key}.fold{fold_idx}.pt"
            valid_loader = DataLoader(
                Subset(train_eval_ds, valid_idx.tolist()),
                batch_size=args.batch_size,
                shuffle=False,
                collate_fn=collate_fn,
            )
            vp, _, _ = predict_fold(ckpt_path, exp_cfg, args, valid_loader, device)
            oof_probs[valid_idx] = vp

            tp, y_test, _ = predict_fold(ckpt_path, exp_cfg, args, test_loader, device)
            test_fold_probs.append(tp)
            m_fold = compute_metrics(y_test, tp, threshold=0.5)
            fold_metrics_list.append(m_fold)

            print(
                f"[{v_key}] Fold {fold_idx} Test @ 0.50 | "
                f"ACC={m_fold['acc']:.4f} | Prec={m_fold['prec']:.4f} | Recall={m_fold['recall']:.4f} | "
                f"F1={m_fold['f1']:.4f} | AUROC={m_fold['auc']:.4f} | AUPRC={m_fold['auprc']:.4f} | MCC={m_fold['mcc']:.4f}"
            )
            fold_rows.append({
                "Variant": v_name,
                "Variant_Key": v_key,
                "Fold": fold_idx,
                "ACC": round(m_fold["acc"], 4),
                "Precision": round(m_fold["prec"], 4),
                "Recall": round(m_fold["recall"], 4),
                "F1": round(m_fold["f1"], 4),
                "AUROC": round(m_fold["auc"], 4),
                "AUPRC": round(m_fold["auprc"], 4),
                "MCC": round(m_fold["mcc"], 4),
            })

        best_thr, best_oof_f1 = 0.5, -1.0
        for thr in np.linspace(0.30, 0.70, 81):
            f1_val = f1_score(all_labels, (oof_probs >= thr).astype(np.int32), zero_division=0)
            if f1_val > best_oof_f1:
                best_oof_f1 = f1_val
                best_thr = float(thr)

        ens_probs = np.mean(test_fold_probs, axis=0)
        m_ens_05 = compute_metrics(y_test, ens_probs, threshold=0.5)
        m_ens_cal = compute_metrics(y_test, ens_probs, threshold=best_thr)

        mean_acc = float(np.mean([m["acc"] for m in fold_metrics_list]))
        std_acc = float(np.std([m["acc"] for m in fold_metrics_list]))
        mean_f1 = float(np.mean([m["f1"] for m in fold_metrics_list]))
        std_f1 = float(np.std([m["f1"] for m in fold_metrics_list]))

        print(f"{'-' * 100}")
        print(f"[{v_key}] 5-Fold Test Mean +/- Std   | ACC={mean_acc:.4f}+/-{std_acc:.4f} | F1={mean_f1:.4f}+/-{std_f1:.4f}")
        print(f"[{v_key}] 5-FOLD ENSEMBLE @ 0.500     | ACC={m_ens_05['acc']:.4f} | Prec={m_ens_05['prec']:.4f} | Recall={m_ens_05['recall']:.4f} | F1={m_ens_05['f1']:.4f} | AUROC={m_ens_05['auc']:.4f} | AUPRC={m_ens_05['auprc']:.4f} | MCC={m_ens_05['mcc']:.4f}")
        print(f"[{v_key}] 5-FOLD ENSEMBLE @ OOF={best_thr:.3f} | ACC={m_ens_cal['acc']:.4f} | Prec={m_ens_cal['prec']:.4f} | Recall={m_ens_cal['recall']:.4f} | F1={m_ens_cal['f1']:.4f} | AUROC={m_ens_cal['auc']:.4f} | AUPRC={m_ens_cal['auprc']:.4f} | MCC={m_ens_cal['mcc']:.4f}")

        summary_rows.append({
            "Variant": v_name,
            "Variant_Key": v_key,
            "Test_FoldMean_ACC": round(mean_acc, 4),
            "Test_FoldStd_ACC": round(std_acc, 4),
            "Test_FoldMean_F1": round(mean_f1, 4),
            "Test_FoldStd_F1": round(std_f1, 4),
            "Ens_ACC": round(m_ens_05["acc"], 4),
            "Ens_Precision": round(m_ens_05["prec"], 4),
            "Ens_Recall": round(m_ens_05["recall"], 4),
            "Ens_F1": round(m_ens_05["f1"], 4),
            "Ens_AUROC": round(m_ens_05["auc"], 4),
            "Ens_AUPRC": round(m_ens_05["auprc"], 4),
            "Ens_MCC": round(m_ens_05["mcc"], 4),
            "OOF_Thr": round(best_thr, 3),
            "Ens_Cal_F1": round(m_ens_cal["f1"], 4),
        })

    folds_csv = base_dir / "all_folds_test_results.csv"
    ens_csv = base_dir / "ensemble_summary_results.csv"
    pd.DataFrame(fold_rows).to_csv(folds_csv, index=False)
    pd.DataFrame(summary_rows).to_csv(ens_csv, index=False)

    print(f"\n{'=' * 100}")
    print(f"Evaluated {len(fold_rows)} total fold-on-test results across {len(run_cfgs)} variants!")
    print(f"Saved per-fold test results to : {folds_csv}")
    print(f"Saved 5-fold ensemble table to : {ens_csv}")
    print(f"{'=' * 100}")


if __name__ == "__main__":
    main()