#!/usr/bin/env python3
"""Reproducible Bio & Protein AI Benchmark Suite on Google Cloud TPU v7x (TorchTPU).

Benchmarks MIT-licensed protein language models and 3D biomolecular structure models on
a single TPU v7x core:
  1. facebook/esm2_t36_3B_UR50D (3B protein language model, bf16, torch.compile)
  2. facebook/esm2_t48_15B_UR50D (15B protein language model, bf16, torch.compile)
  3. facebook/esmfold_v1 (3D protein folding with algebraic 3D cross-product TPU shim)
  4. boltz-community/boltz-2 (64-block PairformerModule Triangle Attention trunk, fp32)
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

UBIQUITIN_HUMAN = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"
UBIQUITIN_MUT = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGA"
LYSOZYME_HEN = "KVFGRCELAAAMKRHGLDNYRGYSLGNWVCAAKFESNFNTQATNRNTDGSTDYGILQINSRWWCNDGRTPGSRNLCNIPCSALLSSDITASVNCAKKIVSDGNGMNAWVAWRNRCKGTDVQAWIRGCRL"
GFP_AEQVI = "MSKGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLVTTFSYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGITHGMDELYK"


def download_model(repo_id: str, cache_root: Path) -> Path:
    from huggingface_hub import snapshot_download

    dst = cache_root / repo_id.replace("/", "__")
    marker = dst / ".download_ok"
    if not marker.exists():
        dst.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=repo_id, local_dir=str(dst))
        marker.write_text("ok")
    return dst


def emit(rec: dict, out_path: Path):
    line = json.dumps(rec)
    print("RECORD:", line, flush=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "a") as f:
        f.write(line + "\n")


def install_tpu_cross_shim(torch):
    """Algebraic 3D cross product replacing unimplemented aten::linalg_cross.out on TPU."""
    def _cross(a, b, dim=-1, *, out=None):
        if dim < 0:
            dim = a.ndim + dim
        am, bm = a.movedim(dim, -1), b.movedim(dim, -1)
        res = torch.stack([
            am[..., 1] * bm[..., 2] - am[..., 2] * bm[..., 1],
            am[..., 2] * bm[..., 0] - am[..., 0] * bm[..., 2],
            am[..., 0] * bm[..., 1] - am[..., 1] * bm[..., 0],
        ], dim=-1).movedim(-1, dim)
        if out is not None:
            out.copy_(res)
            return out
        return res

    torch.linalg.cross = lambda a, b, *, dim=-1, out=None: _cross(a, b, dim=dim, out=out)
    torch.cross = lambda a, b, dim=-1, *, out=None: _cross(a, b, dim=dim, out=out)
    torch.Tensor.cross = lambda self, other, dim=-1: _cross(self, other, dim=dim)


def run_esm2(repo_id: str, batch_map: dict, cache_root: Path, out_path: Path):
    import torch
    import torch_tpu  # noqa: F401
    from transformers import AutoModel, AutoTokenizer

    model_dir = str(download_model(repo_id, cache_root))
    device = torch.device("tpu:0")
    t0 = time.perf_counter()
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModel.from_pretrained(model_dir, dtype=torch.bfloat16).to(device).eval()
    torch.accelerator.synchronize()
    load_s = round(time.perf_counter() - t0, 2)

    q_in = tok([UBIQUITIN_HUMAN, UBIQUITIN_MUT, LYSOZYME_HEN], return_tensors="pt", padding=True, truncation=True, max_length=256)
    q_in = {k: v.to(device) for k, v in q_in.items()}
    with torch.no_grad():
        h = model(**q_in).last_hidden_state.float().cpu()
    mask = q_in["attention_mask"].cpu().unsqueeze(-1).float()
    emb = (h * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1.0)
    emb = emb / emb.norm(dim=-1, keepdim=True).clamp(min=1e-6)
    sim_homolog = float((emb[0] * emb[1]).sum())
    sim_unrelated = float((emb[0] * emb[2]).sum())
    valid_bio = bool(torch.isfinite(emb).all() and sim_homolog > sim_unrelated + 0.05)

    compiled = torch.compile(lambda ids, am: model(input_ids=ids, attention_mask=am).last_hidden_state, backend="tpu")
    for seq_len, batches in batch_map.items():
        for bs in batches:
            ids = torch.randint(4, 24, (bs, seq_len), device=device, dtype=torch.long)
            am = torch.ones((bs, seq_len), device=device, dtype=torch.long)
            with torch.no_grad():
                tc0 = time.perf_counter()
                y = compiled(ids, am)
                torch.accelerator.synchronize()
                cold_ms = (time.perf_counter() - tc0) * 1000.0
                for _ in range(3):
                    y = compiled(ids, am)
                    torch.accelerator.synchronize()
                lats = []
                for _ in range(12):
                    ts = time.perf_counter()
                    y = compiled(ids, am)
                    torch.accelerator.synchronize()
                    lats.append((time.perf_counter() - ts) * 1000.0)
            lats.sort()
            p50 = lats[len(lats) // 2]
            pps = bs / (p50 / 1000.0)
            emit({
                "category": "protein_plm", "model": repo_id, "engine": "torchtpu-compile-bf16",
                "chip": "v7x", "cores": 1, "seq_len": seq_len, "batch_size": bs,
                "load_s": load_s, "cold_ms": round(cold_ms, 2), "p50_ms": round(p50, 2),
                "p95_ms": round(lats[-1], 2), "proteins_per_sec": round(pps, 2),
                "residues_per_sec": round(pps * seq_len, 1), "dim": int(y.shape[-1]),
                "sim_homolog": round(sim_homolog, 4), "sim_unrelated": round(sim_unrelated, 4),
                "valid_bio": valid_bio, "finite": bool(torch.isfinite(y.float().cpu()).all()), "status": "ok",
            }, out_path)


def run_esmfold(cache_root: Path, out_path: Path):
    import torch
    import torch_tpu  # noqa: F401
    from transformers import AutoTokenizer, EsmForProteinFolding

    install_tpu_cross_shim(torch)
    repo_id = "facebook/esmfold_v1"
    model_dir = str(download_model(repo_id, cache_root))
    device = torch.device("tpu:0")
    t0 = time.perf_counter()
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = EsmForProteinFolding.from_pretrained(model_dir).to(device).eval()
    model.esm = model.esm.to(torch.bfloat16)
    torch.accelerator.synchronize()
    load_s = round(time.perf_counter() - t0, 2)

    for name, seq in [("ubiquitin_76aa", UBIQUITIN_HUMAN), ("lysozyme_129aa", LYSOZYME_HEN), ("gfp_238aa", GFP_AEQVI)]:
        ids = tok([seq], return_tensors="pt", add_special_tokens=False)["input_ids"].to(device)
        with torch.no_grad():
            tc0 = time.perf_counter()
            out = model(ids)
            torch.accelerator.synchronize()
            cold_ms = (time.perf_counter() - tc0) * 1000.0
            lats = []
            for _ in range(3):
                ts = time.perf_counter()
                out = model(ids)
                torch.accelerator.synchronize()
                lats.append((time.perf_counter() - ts) * 1000.0)
        plddt = out.plddt.float().cpu().numpy()
        mean_plddt = float(plddt.mean()) * (100.0 if float(plddt.mean()) <= 1.0 else 1.0)
        pos = out.positions.float().cpu().numpy()
        finite = bool(np.isfinite(pos).all() and np.isfinite(plddt).all())
        lats.sort()
        p50 = lats[len(lats) // 2]
        emit({
            "category": "protein_folding", "model": repo_id, "engine": "torchtpu-mixed-cross-shim",
            "chip": "v7x", "cores": 1, "protein_target": name, "seq_len": len(seq),
            "load_s": load_s, "cold_ms": round(cold_ms, 2), "p50_ms": round(p50, 2),
            "p95_ms": round(lats[-1], 2), "folds_per_min": round(60.0 / (p50 / 1000.0), 2),
            "mean_plddt": round(mean_plddt, 2), "finite": finite,
            "valid_fold": bool(finite and mean_plddt >= 70.0), "status": "ok",
        }, out_path)


def run_boltz2(cache_root: Path, out_path: Path):
    import torch
    import torch_tpu  # noqa: F401
    from boltz.model.layers.pairformer import PairformerModule

    repo_id = "boltz-community/boltz-2"
    model_dir = download_model(repo_id, cache_root)
    ckpt_path = model_dir / "boltz2_conf.ckpt"
    t0 = time.perf_counter()
    raw = torch.load(str(ckpt_path), map_location="cpu", weights_only=False)
    hp = dict(raw["hyper_parameters"])
    token_s = int(hp.get("token_s", 384))
    token_z = int(hp.get("token_z", 128))
    pf_args = dict(hp["pairformer_args"])
    pf_args["activation_checkpointing"] = False
    pf_args["use_trifast"] = False
    pf_args["v2"] = True

    pf = PairformerModule(token_s, token_z, **pf_args)
    pf_sd = {k[len("pairformer_module."):]: v for k, v in raw["state_dict"].items() if k.startswith("pairformer_module.")}
    pf.load_state_dict(pf_sd, strict=True)
    device = torch.device("tpu:0")
    pf = pf.to(device=device, dtype=torch.float32).eval()
    torch.accelerator.synchronize()
    load_s = round(time.perf_counter() - t0, 2)
    pf_params_m = round(sum(p.numel() for p in pf.parameters()) / 1e6, 1)
    tot_params_m = round(sum(v.numel() for v in raw["state_dict"].values() if torch.is_tensor(v)) / 1e6, 1)

    compiled_pf = torch.compile(lambda s, z, m, pm: pf(s, z, mask=m, pair_mask=pm), backend="tpu")
    for n_tok in [64, 128, 256, 384]:
        torch.manual_seed(42)
        s = torch.randn((1, n_tok, token_s), device=device, dtype=torch.float32) * 0.1
        z = torch.randn((1, n_tok, n_tok, token_z), device=device, dtype=torch.float32) * 0.1
        m = torch.ones((1, n_tok), device=device, dtype=torch.float32)
        pm = torch.ones((1, n_tok, n_tok), device=device, dtype=torch.float32)
        with torch.no_grad():
            tc0 = time.perf_counter()
            so, zo = compiled_pf(s, z, m, pm)
            torch.accelerator.synchronize()
            cold_ms = (time.perf_counter() - tc0) * 1000.0
            for _ in range(2):
                so, zo = compiled_pf(s, z, m, pm)
                torch.accelerator.synchronize()
            lats = []
            for _ in range(6):
                ts = time.perf_counter()
                so, zo = compiled_pf(s, z, m, pm)
                torch.accelerator.synchronize()
                lats.append((time.perf_counter() - ts) * 1000.0)
        so_c, zo_c = so.float().cpu(), zo.float().cpu()
        finite = bool(torch.isfinite(so_c).all() and torch.isfinite(zo_c).all())
        s_std, z_std = float(so_c.std()), float(zo_c.std())
        lats.sort()
        p50 = lats[len(lats) // 2]
        emit({
            "category": "biomolecular_pairformer", "model": repo_id,
            "component": "64-block PairformerModule (Triangle Attention trunk)",
            "engine": "torchtpu-compile-fp32", "chip": "v7x", "cores": 1,
            "n_tokens": n_tok, "num_blocks": int(pf_args.get("num_blocks", 64)),
            "trunk_params_m": pf_params_m, "total_params_m": tot_params_m,
            "load_s": load_s, "cold_ms": round(cold_ms, 2), "p50_ms": round(p50, 2),
            "p95_ms": round(lats[-1], 2), "passes_per_min": round(60.0 / (p50 / 1000.0), 2),
            "s_std": round(s_std, 4), "z_std": round(z_std, 4), "finite": finite,
            "valid_trunk": bool(finite and s_std > 0.01 and z_std > 0.01), "status": "ok",
        }, out_path)


RUNNERS = {
    "esm2_3b": lambda c, o: run_esm2("facebook/esm2_t36_3B_UR50D", {256: [1, 8, 32], 512: [1, 8, 32], 1024: [1, 8, 32]}, c, o),
    "esm2_15b": lambda c, o: run_esm2("facebook/esm2_t48_15B_UR50D", {256: [1, 4, 16], 512: [1, 4, 16], 1024: [1, 4]}, c, o),
    "esmfold": run_esmfold,
    "boltz2": run_boltz2,
}


def main():
    parser = argparse.ArgumentParser(description="Benchmark bio & protein foundation models on TPU v7x (TorchTPU).")
    parser.add_argument("--model-cache", type=Path, default=Path("/dev/shm/bio_models"))
    parser.add_argument("--output", type=Path, default=Path("results/v7x_bio_protein_models.jsonl"))
    parser.add_argument("--only", choices=list(RUNNERS.keys()), default=None)
    parser.add_argument("--child", choices=list(RUNNERS.keys()), default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.child:
        RUNNERS[args.child](args.model_cache, args.output)
        return

    targets = [args.only] if args.only else list(RUNNERS.keys())
    for name in targets:
        cmd = [sys.executable, "-u", __file__, "--child", name, "--model-cache", str(args.model_cache), "--output", str(args.output)]
        subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
