import argparse
import time
import numpy as np
import pandas as pd
import torch
from pathlib import Path
from torch.utils.data import DataLoader

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


@torch.no_grad()
def benchmark_variant(
    exp_cfg: dict,
    args,
    device: torch.device,
    test_mm: MultimodalProteinDataset,
    test_evo: FastDescriptorOnlyView,
    base_dir: Path,
):
    model, _ = build_variant_model(exp_cfg, args, device)
    model.eval()

    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)

    v_key = exp_cfg["key"]
    ckpt_path = base_dir / f"model_{v_key}.fold1.pt"
    ckpt_mb = round(ckpt_path.stat().st_size / (1024 * 1024), 2) if ckpt_path.exists() else None

    mode = exp_cfg["mode"]
    if mode == "evo_only":
        ds, collate_fn = test_evo, collate_evo_only_batch
    elif mode == "gt_only":
        ds, collate_fn = test_mm.base_ds, collate_graph_transformer_batch
    else:
        ds, collate_fn = test_mm, collate_multimodal_batch

    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False, collate_fn=collate_fn)
    batches = list(loader)

    # Pre-stage batches on GPU so latency measures pure model forward inference (excluding CPU-GPU copy)
    gpu_batches = []
    for batch in batches:
        if mode == "evo_only":
            desc, _, _ = batch
            gpu_batches.append((desc.to(device),))
        elif mode == "gt_only":
            px, mask, _, _ = batch
            gpu_batches.append((px.to(device), mask.to(device)))
        else:
            px, mask, desc, _, _ = batch
            gpu_batches.append((px.to(device), mask.to(device), desc.to(device)))

    # Warmup passes
    for _ in range(args.warmup_runs):
        for gb in gpu_batches[: min(5, len(gpu_batches))]:
            if mode == "evo_only":
                _ = model(gb[0])
            elif mode == "gt_only":
                _ = model(gb[0], gb[1])
            else:
                _ = model(gb[0], gb[1], gb[2])
    if device.type == "cuda":
        torch.cuda.synchronize()

    # Timed passes across entire test set (1,420 proteins)
    total_proteins = len(ds)
    pass_times_ms = []
    for _ in range(args.timed_runs):
        if device.type == "cuda":
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        for gb in gpu_batches:
            if mode == "evo_only":
                _ = model(gb[0])
            elif mode == "gt_only":
                _ = model(gb[0], gb[1])
            else:
                _ = model(gb[0], gb[1], gb[2])
        if device.type == "cuda":
            torch.cuda.synchronize()
        pass_times_ms.append((time.perf_counter() - t0) * 1000.0)

    total_ms = float(np.mean(pass_times_ms))
    ms_per_protein = total_ms / max(total_proteins, 1)
    ms_per_batch = total_ms / max(len(gpu_batches), 1)

    return {
        "Variant": exp_cfg["name"],
        "Variant_Key": v_key,
        "Total_Params": int(total_params),
        "Trainable_Params": int(trainable_params),
        "Trainable_Params_M": round(trainable_params / 1e6, 4),
        "Ckpt_Size_MB": ckpt_mb,
        "Latency_TestSet_ms": round(total_ms, 2),
        "Latency_ms_per_Batch32": round(ms_per_batch, 3),
        "Latency_ms_per_Protein": round(ms_per_protein, 4),
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark Trainable Parameters & GPU Inference Latency across all variants")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--hidden-dim", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--algpro-dir", type=str, default="descriptors")
    parser.add_argument("--warmup-runs", type=int, default=3)
    parser.add_argument("--timed-runs", type=int, default=10)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Benchmarking on: {device} ({torch.cuda.get_device_name(0) if device.type == 'cuda' else 'CPU'})")

    base_dir = Path(__file__).resolve().parent
    data_dir = resolve_data_dir()
    cache_dir = base_dir / "cache_prott5"

    algpro_dir = resolve_algpro_dir(args.algpro_dir, data_dir, base_dir)
    algpro_lookup = load_multimodal_algpro_lookup(algpro_dir) if algpro_dir is not None else None

    extractor = ProtT5BatchExtractor(device=device, cache_dir=cache_dir)
    test_base = ProteinGraphTransformerDataset(data_dir / "all.test.fasta", extractor=extractor)
    extractor.unload_from_gpu()

    test_mm = MultimodalProteinDataset(test_base, algpro_lookup=algpro_lookup)
    test_evo = FastDescriptorOnlyView(test_mm)

    rows = []
    for exp_cfg in EXPERIMENT_SUITE:
        res = benchmark_variant(exp_cfg, args, device, test_mm, test_evo, base_dir)
        rows.append(res)
        print(
            f"[{res['Variant_Key']:16s}] Params: {res['Trainable_Params']:>9,d} ({res['Trainable_Params_M']:.3f}M) | "
            f"Batch(32): {res['Latency_ms_per_Batch32']:6.2f} ms | "
            f"Per-Protein: {res['Latency_ms_per_Protein']:.4f} ms | "
            f"Full 1420 Test: {res['Latency_TestSet_ms']:7.2f} ms"
        )

    df_bench = pd.DataFrame(rows)
    out_csv = base_dir / "model_params_and_latency.csv"
    df_bench.to_csv(out_csv, index=False)

    ens_csv = base_dir / "ensemble_summary_results.csv"
    if ens_csv.exists():
        df_ens = pd.read_csv(ens_csv)
        merged = pd.merge(df_ens, df_bench, on=["Variant", "Variant_Key"], how="left")
        merged_csv = base_dir / "model_efficiency_and_accuracy.csv"
        merged.to_csv(merged_csv, index=False)
        print(f"\nMerged accuracy + efficiency table saved to: {merged_csv}")
    else:
        print(f"\nSaved parameter & latency table to: {out_csv}")


if __name__ == "__main__":
    main()