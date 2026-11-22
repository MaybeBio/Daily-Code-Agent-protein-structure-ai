"""
method3_embed.py - Kaggle script (GPU): recompute Method 3's RibonanzaNet2 embeddings for all our chains,
then turn them into a full score matrix for the selector.

Method 3 (all_methods.zip) used one vector per chain: the RibonanzaNet2 final-layer residue features,
averaged over the chain and scaled to unit length ("ribonanzanet2_mean_l2.npz"). That file is not
available, so it is recomputed here with the same RibonanzaNet2 weights RNAPro uses
(Kaggle model shujun717/ribonanzanet2, PyTorch/alpha/1) and RNAPro's own RibonanzaNet code
(rnapro/model/modules/ribonanzanet.py, loaded with strict=True as RNAPro does). Tokens: A0 C1 G2 U3,
as in RNAPro's inference pipeline; one chain at a time, so there is no padding.

The layer loop is the one of RibonanzaNet.get_embeddings, without stacking all 48 layers' pair features
(that alone would need several GB for a 500-residue chain). The mean of every layer is kept, so other
layers can be tried later without the GPU.

Then, exactly as method3_scores.py: "standardised" variant (statistics from train chains only),
cosine for every pair -> method_scores_emb.npz for selector-v3.

Env: M3_LIMIT=n embeds only the first n chains (smoke test; no score matrix is written).
Inputs : alizehadeel/dataprep (dataset.jsonl), alizehadeel/build-features (chains.tsv),
         theoviel/rnapro-src (ribonanzanet.py), model shujun717/ribonanzanet2 (pairwise.yaml, weights)
Outputs: ribonanzanet2_mean_l2.npz (chain_ids, vectors), ribonanzanet2_layer_means.npz (chain_ids, means
         float16 [n, layers, 384]), method_scores_emb.npz (chain_ids, emb), plain_scores_embplain.npz,
         method3_embed_check.json
"""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import subprocess

import numpy as np
import pandas as pd
import torch

try:
    import einops  # noqa: F401  (needed by ribonanzanet.py)
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "einops==0.8.1"], check=True)

INPUT = Path(os.environ.get("SV_INPUT", "/kaggle/input"))
WORK = Path(os.environ.get("SV_WORK", "/kaggle/working"))
LIMIT = int(os.environ.get("M3_LIMIT", "0"))
TOKENS = {"A": 0, "C": 1, "G": 2, "U": 3}


def find(name):
    hits = sorted(INPUT.rglob(name))
    if not hits:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0]


def load_model(device):
    spec = importlib.util.spec_from_file_location("ribonanzanet", find("ribonanzanet.py"))
    rn = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rn)
    model = rn.RibonanzaNet(rn.load_config_from_yaml(find("pairwise.yaml")))
    state = torch.load(find("pytorch_model_fsdp.bin"), map_location="cpu")
    model.load_state_dict(state, strict=True)
    return model.to(device).eval()


@torch.no_grad()
def layer_means(model, seq, device):
    """Per-layer mean of the residue features, following RibonanzaNet.get_embeddings."""
    src = torch.tensor([[TOKENS[c] for c in seq]], device=device)
    mask = torch.ones_like(src)
    x = model.encoder(src).reshape(1, len(seq), -1)
    pair = model.outer_product_mean(x) + model.pos_encoder(x)
    out = []
    for layer in model.transformer_encoder:
        x, pair = layer([x, pair, mask, False])
        out.append(x[0].float().mean(0))
    return torch.stack(out).cpu().numpy()                     # [layers, ninp]


def unit(X):
    return (X / np.linalg.norm(X, axis=-1, keepdims=True)).astype(np.float32)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ch = pd.read_csv(find("chains.tsv"), sep="\t")
    ids = [str(x) for x in ch.chain_id]
    seqs = {}
    for line in open(find("dataset.jsonl")):
        r = json.loads(line)
        seqs[str(r["chain_id"])] = str(r["sequence"]).upper().replace("T", "U")
    missing = [c for c in ids if c not in seqs]
    assert not missing, f"{len(missing)} chains have no sequence, e.g. {missing[:5]}"
    bad = [c for c in ids if set(seqs[c]) - set(TOKENS)]
    assert not bad, f"{len(bad)} sequences have letters other than ACGU, e.g. {bad[:5]}"
    run_ids = ids[:LIMIT] if LIMIT else ids

    model = load_model(device)
    print(f"device {device} ({torch.cuda.get_device_name(0) if device == 'cuda' else 'cpu'}) | "
          f"{len(model.transformer_encoder)} layers | {len(run_ids)} chains, longest "
          f"{max(len(seqs[c]) for c in run_ids)}", flush=True)
    t0 = time.time()
    order = sorted(range(len(run_ids)), key=lambda j: len(seqs[run_ids[j]]))   # short first
    M = [None] * len(run_ids)
    for done, j in enumerate(order):
        M[j] = layer_means(model, seqs[run_ids[j]], device)
        if (done + 1) % 200 == 0:
            print(f"  {done + 1}/{len(run_ids)} chains, {time.time() - t0:.0f} s", flush=True)
    M = np.stack(M)                                              # [n, layers, ninp]
    minutes = (time.time() - t0) / 60
    V = unit(M[:, -1])
    np.savez_compressed(WORK / "ribonanzanet2_mean_l2.npz", chain_ids=np.array(run_ids), vectors=V)
    np.savez_compressed(WORK / "ribonanzanet2_layer_means.npz", chain_ids=np.array(run_ids), means=M.astype(np.float16))
    check = {"chains": len(run_ids), "layers": int(M.shape[1]), "dimensions": int(M.shape[2]),
             "embed_minutes": round(minutes, 2), "device": device,
             "max_gpu_memory_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2) if device == "cuda" else None,
             "finite": bool(np.isfinite(M).all())}

    if not LIMIT:
        train = np.where(ch.split.to_numpy() == "train")[0]
        X = M[:, -1].astype(np.float64)
        mean, sd = X[train].mean(0), X[train].std(0)
        S = unit((X - mean) / np.where(sd > 0, sd, 1.0))
        emb, plain = S @ S.T, V @ V.T
        np.savez_compressed(WORK / "method_scores_emb.npz", chain_ids=np.array(ids), emb=emb)
        np.savez_compressed(WORK / "plain_scores_embplain.npz", chain_ids=np.array(ids), embplain=plain)
        off = ~np.eye(len(ids), dtype=bool)
        fam = ch.family.astype(str).to_numpy() if "family" in ch else None
        check.update({"emb_offdiag_mean": float(emb[off].mean()), "emb_offdiag_sd": float(emb[off].std()),
                      "plain_offdiag_mean": float(plain[off].mean()), "plain_offdiag_sd": float(plain[off].std())})
        if fam is not None:                                      # quick sanity check: nearest neighbour in same family?
            for name, A in (("plain", plain), ("standardised", emb)):
                A = np.where(off, A, -np.inf)
                nn = A.argmax(1)
                has = np.array([(fam == fam[i]).sum() > 1 for i in range(len(ids))])
                check[f"nn_same_family_{name}"] = float((fam[nn] == fam)[has].mean())
    (WORK / "method3_embed_check.json").write_text(json.dumps(check, indent=1))
    print(json.dumps(check, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
