"""
riboseek_tokens.py - Kaggle script (GPU): RiboSeek RS-20 token predictions that are honest for every query.

The team's token model (Haleema, token_model_training.ipynb) predicts one RiboSeek RS-20 structural
token per nucleotide from the sequence. It was trained on all 1,549 train chains, so its predictions
for those chains are in-sample and too accurate for the selector's train queries. As for the
two-tower (crossfit-towers), the model is retrained 5 times on the same family folds: each train
chain is predicted by a model that never saw its fold. Validation and test chains use the released
model.pt unchanged.

Training recipe = the notebook's "base" run, unchanged: d_model 128, 4 heads, 4 layers, 2 conv
layers, dropout 0.2, AdamW lr 3e-4, weight decay 0.01, batch 16, family-balanced sampling
(1/sqrt(family size)), label smoothing 0.1, 3 warm-up epochs + cosine, up to 80 epochs, early stop
after 12 epochs without a better validation macro-F1 (validation = the val split, as in the notebook).

Inputs : alizehadeel/riboseek-tokens (tokens_dataset.jsonl, model.pt, probs_val.npz),
         alizehadeel/crossfit-towers (twotower_oof.npz: chain order, train fold of every chain)
Outputs: token_probs.npz (one float16 [length, 20] array per chain_id), riboseek_tokens_check.json
"""
import collections
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import f1_score
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

INPUT = Path(os.environ.get("SV_INPUT", "/kaggle/input"))
WORK = Path(os.environ.get("SV_WORK", "/kaggle/working"))
EPOCHS = int(os.environ.get("RS_EPOCHS", "80"))
CFG = dict(d_model=128, n_heads=4, n_layers=4, conv_layers=2, dropout=0.2, lr=3e-4, weight_decay=0.01,
           batch_size=16, epochs=EPOCHS, warmup_epochs=3, patience=12, label_smoothing=0.1, seed=42)
NUC = {"A": 1, "C": 2, "G": 3, "U": 4}
PAD_ID, IGNORE = 0, -1
LABELS = list(range(20))
DEV = "cuda" if torch.cuda.is_available() else "cpu"


def find(name):
    hits = sorted(INPUT.rglob(name))
    if not hits:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0]


class TokenPredictor(nn.Module):
    """The notebook's model, unchanged."""

    def __init__(self, n_classes=20, d_model=128, n_heads=4, n_layers=4, conv_layers=2, kernel=5, dropout=0.2,
                 max_len=512):
        super().__init__()
        self.embed = nn.Embedding(5, d_model, padding_idx=PAD_ID)
        pe = torch.zeros(max_len, d_model)
        pos = torch.arange(max_len).unsqueeze(1)
        div = torch.exp(torch.arange(0, d_model, 2) * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("pe", pe)
        self.convs = nn.ModuleList([nn.Sequential(nn.Conv1d(d_model, d_model, kernel, padding=kernel // 2),
                                                  nn.GELU(), nn.Dropout(dropout)) for _ in range(conv_layers)])
        self.conv_norm = nn.LayerNorm(d_model)
        layer = nn.TransformerEncoderLayer(d_model, n_heads, dim_feedforward=4 * d_model, dropout=dropout,
                                           batch_first=True, activation="gelu", norm_first=True)
        self.transformer = nn.TransformerEncoder(layer, n_layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d_model)
        self.head = nn.Linear(d_model, n_classes)

    def forward(self, X, mask):
        h = self.embed(X) + self.pe[: X.size(1)]
        c = h.transpose(1, 2)
        for conv in self.convs:
            c = c + conv(c)
        h = self.conv_norm(c.transpose(1, 2))
        h = h * mask.unsqueeze(-1)
        h = self.transformer(h, src_key_padding_mask=~mask)
        return self.head(self.norm(h))


class DS(Dataset):
    def __init__(self, records):
        self.records = records

    def __len__(self):
        return len(self.records)

    def __getitem__(self, i):
        d = self.records[i]
        return (torch.tensor([NUC[c] for c in d["sequence"]], dtype=torch.long),
                torch.tensor(d["rs20"], dtype=torch.long), d["chain_id"])


def collate(batch):
    xs, ys, ids = zip(*batch)
    L = max(len(x) for x in xs)
    X = torch.full((len(xs), L), PAD_ID, dtype=torch.long)
    Y = torch.full((len(xs), L), IGNORE, dtype=torch.long)
    mask = torch.zeros((len(xs), L), dtype=torch.bool)
    for i, (x, y) in enumerate(zip(xs, ys)):
        X[i, :len(x)] = x
        Y[i, :len(y)] = y
        mask[i, :len(x)] = True
    return X, Y, mask, list(ids)


def evaluate(model, loader):
    model.eval()
    yt, yp = [], []
    with torch.no_grad():
        for X, Y, mask, _ in loader:
            pred = model(X.to(DEV), mask.to(DEV)).argmax(-1).cpu()
            keep = Y != IGNORE
            yt += Y[keep].tolist()
            yp += pred[keep].tolist()
    yt, yp = np.array(yt), np.array(yp)
    return float((yt == yp).mean()), float(f1_score(yt, yp, labels=LABELS, average="macro", zero_division=0))


def train_model(records, val_records, tag):
    torch.manual_seed(CFG["seed"])
    np.random.seed(CFG["seed"])
    fam = collections.Counter(d["family"] for d in records)
    w = [1.0 / math.sqrt(fam[d["family"]]) for d in records]
    loader = DataLoader(DS(records), batch_size=CFG["batch_size"], collate_fn=collate,
                        sampler=WeightedRandomSampler(w, num_samples=len(records), replacement=True))
    vloader = DataLoader(DS(val_records), batch_size=32, shuffle=False, collate_fn=collate)
    model = TokenPredictor(d_model=CFG["d_model"], n_heads=CFG["n_heads"], n_layers=CFG["n_layers"],
                           conv_layers=CFG["conv_layers"], dropout=CFG["dropout"]).to(DEV)
    loss_fn = nn.CrossEntropyLoss(ignore_index=IGNORE, label_smoothing=CFG["label_smoothing"])
    opt = torch.optim.AdamW(model.parameters(), lr=CFG["lr"], weight_decay=CFG["weight_decay"])
    total, warm = CFG["epochs"] * len(loader), CFG["warmup_epochs"] * len(loader)

    def lr_lambda(step):
        if step < warm:
            return (step + 1) / warm
        return 0.5 * (1 + math.cos(math.pi * (step - warm) / max(1, total - warm)))

    sched = torch.optim.lr_scheduler.LambdaLR(opt, lr_lambda)
    scaler = torch.cuda.amp.GradScaler(enabled=DEV == "cuda")
    best, bad, best_state, best_ep = -1.0, 0, None, -1
    for ep in range(CFG["epochs"]):
        model.train()
        for X, Y, mask, _ in loader:
            X, Y, mask = X.to(DEV), Y.to(DEV), mask.to(DEV)
            with torch.autocast("cuda", dtype=torch.float16, enabled=DEV == "cuda"):
                logits = model(X, mask)
                loss = loss_fn(logits.float().reshape(-1, 20), Y.reshape(-1))
            opt.zero_grad()
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
        acc, f1 = evaluate(model, vloader)
        if f1 > best:
            best, bad, best_ep = f1, 0, ep
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
        if bad >= CFG["patience"]:
            break
    model.load_state_dict(best_state)
    print(f"[{tag}] best epoch {best_ep}, val macro-F1 {best:.3f}", flush=True)
    return model, best_ep, best


def predict_probs(model, records):
    model.eval()
    out = {}
    with torch.no_grad():
        for d in records:
            x = torch.tensor([[NUC[c] for c in d["sequence"]]], device=DEV)
            m = torch.ones_like(x, dtype=torch.bool)
            out[d["chain_id"]] = torch.softmax(model(x, m).float(), -1)[0].cpu().numpy()
    return out


def accuracy(probs, records):
    ok = n = 0
    for d in records:
        p = probs[d["chain_id"]].argmax(1)
        y = np.array(d["rs20"])
        keep = y != -1
        ok += int((p[keep] == y[keep]).sum())
        n += int(keep.sum())
    return ok / max(n, 1)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    data = [json.loads(line) for line in open(find("tokens_dataset.jsonl"))]
    by_id = {d["chain_id"]: d for d in data}
    o = np.load(find("twotower_oof.npz"))
    ids = [str(x) for x in o["chain_ids"]]
    assert set(ids) == set(by_id), "token dataset and two-tower chains differ"
    tr, fold = o["train_idx"].astype(int), o["fold"].astype(int)
    fold_of = {ids[i]: int(fold[i]) for i in tr}
    train = [d for d in data if d["split"] == "train"]
    val = [d for d in data if d["split"] == "val"]
    test = [d for d in data if d["split"] == "test"]
    assert {d["chain_id"] for d in train} == set(fold_of), "train chains differ from the two-tower's"

    probs, folds_info = {}, []
    for k in sorted(set(fold_of.values())):
        fit = [d for d in train if fold_of[d["chain_id"]] != k]
        held = [d for d in train if fold_of[d["chain_id"]] == k]
        model, ep, f1 = train_model(fit, val, f"fold {k}")
        p = predict_probs(model, held)
        probs.update(p)
        folds_info.append({"fold": k, "train_chains": len(fit), "held_out": len(held), "best_epoch": ep,
                           "val_macro_f1": round(f1, 4), "held_out_accuracy": round(accuracy(p, held), 4)})
        print(folds_info[-1], f"{(time.time() - t0) / 60:.1f} min", flush=True)

    ck = torch.load(find("model.pt"), map_location=DEV)
    c = ck["cfg"]
    released = TokenPredictor(d_model=c["d_model"], n_heads=c["n_heads"], n_layers=c["n_layers"],
                              conv_layers=c["conv_layers"], dropout=0.0).to(DEV)
    released.load_state_dict(ck["model"])
    pv = predict_probs(released, val + test)
    probs.update(pv)
    ref = np.load(find("probs_val.npz"))
    max_diff = max(float(np.abs(pv[cid].astype(np.float32) - ref[cid].astype(np.float32)).max()) for cid in ref.files)
    in_sample = predict_probs(released, train[:300])

    np.savez_compressed(WORK / "token_probs.npz", **{cid: probs[cid].astype(np.float16) for cid in ids})
    check = {"folds": folds_info,
             "out_of_fold_accuracy_train": round(accuracy(probs, train), 4),
             "released_model_accuracy_on_300_train_chains_in_sample": round(accuracy(in_sample, train[:300]), 4),
             "released_model_accuracy_val": round(accuracy(probs, val), 4),
             "released_model_accuracy_test": round(accuracy(probs, test), 4),
             "val_probs_max_difference_from_saved": max_diff,
             "minutes": round((time.time() - t0) / 60, 1)}
    (WORK / "riboseek_tokens_check.json").write_text(json.dumps(check, indent=1))
    print(json.dumps(check, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
