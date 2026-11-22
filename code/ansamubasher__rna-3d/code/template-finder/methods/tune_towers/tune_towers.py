"""
tune_towers.py - Kaggle script: step 4, tune the two-tower retriever on the held-out families.

Same data, towers and evaluation as train_towers.py. What step 3 showed: validation scores peak
after ~45 passes while training scores keep rising (the model stops generalising), and the model
is ahead of simple 3-mer sequence similarity at rank 1 but not in the top 5-10.

Five variants are trained one after the other, 60 passes each, to test three ideas:
    combined loss          regression + contrastive in one loss (step 3 trained them separately)
    stronger regularising  more dropout and weight decay, or a smaller model
    template sequence      the template vector also uses the template's SEQUENCE, read by the same
                           sequence tower as the query:  template = structure tower + sequence tower.
                           Still two towers; the template side simply sees both things we know about it.

    name            loss       dropout  weight decay  size    template sequence
    combined        combined   0.1      0.01          full    no
    combined_reg    combined   0.3      0.1           full    no
    hybrid          combined   0.1      0.01          full    yes
    hybrid_reg      combined   0.3      0.1           full    yes
    hybrid_small    combined   0.2      0.05          half    yes

The checkpoint of each variant is chosen by the mean of best_tm@1, @5 and @10 on validation
(step 3 used best_tm@5 alone; the mean is less noisy with only 159 queries).
One extra row per variant, "<name> + 3-mer", adds the 3-mer similarity to the model score
(both standardised per query). It is a diagnostic: it shows whether the model and 3-mer
similarity find DIFFERENT templates. The test split is never read here.

Inputs : alizehadeel/build-features (features.npz), alizehadeel/label-check (pairs_train/val.parquet)
Outputs: tune_metrics.json, tune_summary.csv, tune_history.csv, model_<name>.pt, val_scores.npz
"""
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F

INPUT = Path(os.environ.get("TT_INPUT", "/kaggle/input"))      # overridable for local tests
WORK = Path(os.environ.get("TT_WORK", "/kaggle/working"))

CFG = dict(
    seed=0,
    epochs=int(os.environ.get("TT_EPOCHS", 60)),      # one epoch = every train chain used once as a query
    eval_every=int(os.environ.get("TT_EVAL_EVERY", 5)),
    max_minutes_per_objective=float(os.environ.get("TT_MAX_MIN", 45)),
    batch_queries=32,
    lr=3e-4, weight_decay=0.01, warmup_steps=200, grad_clip=1.0, dropout=0.1,
    emb_dim=128,
    seq_dim=128, seq_layers=4, seq_heads=4,
    node_s=128, node_v=16, gvp_layers=3, knn=16,
    pos_tm=0.45, neg_tm=0.35,                # trial thresholds from the methodology, not tuned values
    reg_pos_weight=5.0,                      # regression: weight of pairs with TM >= pos_tm
    temperature=0.1,                         # contrastive
    topk_saved=20,
    objective="combined", con_weight=0.1,    # combined loss = regression + con_weight * contrastive
    template_seq=False,                      # template vector also uses the template's sequence
)
SMALL = dict(seq_dim=64, seq_layers=2, node_s=64, node_v=8, gvp_layers=2, emb_dim=64)
EXPERIMENTS = {
    "combined": dict(),
    "combined_reg": dict(dropout=0.3, weight_decay=0.1),
    "hybrid": dict(template_seq=True),
    "hybrid_reg": dict(template_seq=True, dropout=0.3, weight_decay=0.1),
    "hybrid_small": dict(template_seq=True, dropout=0.2, weight_decay=0.05, **SMALL),
}
ATOM_C4, ATOM_C1, ATOM_C3, ATOM_P, ATOM_N = 1, 2, 3, 0, 4      # order in features.npz: P, C4', C1', C3', N


def find(name):
    hits = sorted(INPUT.rglob(name))
    if not hits:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0]


# =============================================================================== data
def load_data():
    f = np.load(find("features.npz"))
    ids = [str(x) for x in f["chain_ids"]]
    n = len(ids)
    seq = [torch.from_numpy(f["seq_tok"][f["seq_off"][i]:f["seq_off"][i + 1]].astype(np.int64)) for i in range(n)]
    xyz, base = [], []
    for i in range(n):
        s = slice(f["res_off"][i], f["res_off"][i + 1])
        x = f["res_xyz"][s]
        keep = ~np.isnan(x[:, :4, 0]).all(1)           # drop residues with no backbone atom at all
        xyz.append(torch.from_numpy(x[keep]))
        base.append(torch.from_numpy(f["res_base"][s][keep].astype(np.int64)))

    tr = pd.read_parquet(find("pairs_train.parquet"), columns=["idx_a", "idx_b", "tm_a", "tm_b"])
    va = pd.read_parquet(find("pairs_val.parquet"), columns=["idx_q", "idx_t", "tm_q", "template_before_query"])
    # tm[q, t] = TM-score of the pair normalised by the length of q.  NaN = pair not available here.
    tm = np.full((n, n), np.nan, dtype=np.float32)
    tm[tr.idx_a, tr.idx_b] = tr.tm_a
    tm[tr.idx_b, tr.idx_a] = tr.tm_b
    tm[va.idx_q, va.idx_t] = va.tm_q
    before = np.zeros((n, n), dtype=bool)
    before[va.idx_q, va.idx_t] = va.template_before_query
    train_idx = np.unique(np.concatenate([tr.idx_a, tr.idx_b]))
    val_idx = np.unique(va.idx_q)
    tm[train_idx, train_idx] = 1.0                      # a chain's own structure
    return dict(ids=ids, seq=seq, xyz=xyz, base=base, tm=tm, before=before, train_idx=train_idx, val_idx=val_idx)


def pad_seq(seqs, dev):
    L = max(len(s) for s in seqs)
    tok = torch.full((len(seqs), L), 5, dtype=torch.long)
    for i, s in enumerate(seqs):
        tok[i, :len(s)] = s
    return tok.to(dev)


def pad_struct(xyzs, bases, dev):
    L = max(len(x) for x in xyzs)
    X = torch.full((len(xyzs), L, 5, 3), float("nan"))
    Bs = torch.full((len(xyzs), L), 5, dtype=torch.long)
    mask = torch.zeros((len(xyzs), L), dtype=torch.bool)
    for i, (x, b) in enumerate(zip(xyzs, bases)):
        X[i, :len(x)] = x
        Bs[i, :len(b)] = b
        mask[i, :len(x)] = True
    return X.to(dev), Bs.to(dev), mask.to(dev)


# =============================================================================== structure features
def unit(v):
    return v / (v.norm(dim=-1, keepdim=True) + 1e-6)


def featurize(X, base, mask, knn):
    """Coordinates -> graph. X [B,L,5,3] with NaN for missing atoms, base [B,L], mask [B,L].
    Returns node scalars [B,L,14], node vectors [B,L,5,3], neighbour index [B,L,K],
            edge distance [B,L,K], edge offset in residue order [B,L,K], edge vectors [B,L,K,1,3], edge mask [B,L,K]."""
    B, L = mask.shape
    have = ~torch.isnan(X[..., 0])                                   # [B,L,5]
    X = torch.nan_to_num(X, nan=0.0)
    # centre of a residue: C4', else C1', else C3', else P
    C = torch.zeros(B, L, 3, device=X.device)
    done = torch.zeros(B, L, dtype=torch.bool, device=X.device)
    for a in (ATOM_C4, ATOM_C1, ATOM_C3, ATOM_P):
        use = have[..., a] & ~done
        C = torch.where(use[..., None], X[..., a, :], C)
        done |= use
    mask = mask & done

    def to_atom(a):
        ok = (have[..., a] & mask)[..., None].float()
        d = (X[..., a, :] - C) * ok
        return unit(d) * ok, d.norm(dim=-1, keepdim=True) / 10.0

    vP, dP = to_atom(ATOM_P)
    vN, dN = to_atom(ATOM_N)
    v1, _ = to_atom(ATOM_C1)
    nxt = torch.zeros_like(C)
    prv = torch.zeros_like(C)
    ok_n = torch.zeros(B, L, 1, device=X.device)
    ok_p = torch.zeros(B, L, 1, device=X.device)
    nxt[:, :-1] = C[:, 1:] - C[:, :-1]
    prv[:, 1:] = C[:, :-1] - C[:, 1:]
    ok_n[:, :-1, 0] = (mask[:, 1:] & mask[:, :-1]).float()
    ok_p[:, 1:, 0] = (mask[:, 1:] & mask[:, :-1]).float()
    nxt, prv = nxt * ok_n, prv * ok_p
    node_v = torch.stack([vP, vN, v1, unit(nxt) * ok_n, unit(prv) * ok_p], dim=2)             # [B,L,5,3]
    node_s = torch.cat([F.one_hot(base.clamp(max=4), 5).float(), have.float(), dP, dN,
                        nxt.norm(dim=-1, keepdim=True) / 10.0, prv.norm(dim=-1, keepdim=True) / 10.0], -1)
    node_s = node_s * mask[..., None].float()

    D = torch.cdist(C, C)
    bad = ~(mask[:, :, None] & mask[:, None, :]) | torch.eye(L, dtype=torch.bool, device=X.device)[None]
    D = D.masked_fill(bad, float("inf"))
    k = min(knn, L)
    dist, idx = D.topk(k, dim=-1, largest=False)                     # [B,L,k]
    emask = torch.isfinite(dist)
    dist = torch.where(emask, dist, torch.zeros_like(dist))
    bi = torch.arange(B, device=X.device)[:, None, None]
    edge_v = unit(C[bi, idx] - C[:, :, None, :]) * emask[..., None].float()
    offset = idx - torch.arange(L, device=X.device)[None, :, None]
    return node_s, node_v, idx, dist, offset, edge_v[:, :, :, None, :], emask, mask


# =============================================================================== model
class GVP(nn.Module):
    """Geometric vector perceptron: maps (scalars, 3D vectors) -> (scalars, 3D vectors).
    Scalars see only the LENGTHS of vectors, and vectors are only mixed linearly and rescaled,
    so rotating the input rotates the output vectors and leaves the scalars unchanged."""

    def __init__(self, si, vi, so, vo, act=True):
        super().__init__()
        h = max(vi, vo)
        self.wh = nn.Linear(vi, h, bias=False)
        self.ws = nn.Linear(si + h, so)
        self.wv = nn.Linear(h, vo, bias=False)
        self.act = act

    def forward(self, s, v):                                          # s [..., si], v [..., vi, 3]
        vh = self.wh(v.transpose(-1, -2))                             # [..., 3, h]
        s = self.ws(torch.cat([s, torch.sqrt((vh ** 2).sum(-2) + 1e-8)], -1))
        v = self.wv(vh).transpose(-1, -2)                             # [..., vo, 3]
        if self.act:
            s = F.relu(s)
            v = v * torch.sigmoid(torch.sqrt((v ** 2).sum(-1, keepdim=True) + 1e-8))
        return s, v


class Norm(nn.Module):
    def __init__(self, ns):
        super().__init__()
        self.ln = nn.LayerNorm(ns)

    def forward(self, s, v):
        return self.ln(s), v / torch.sqrt((v ** 2).sum(-1, keepdim=True).mean(-2, keepdim=True) + 1e-8)


class GVPLayer(nn.Module):
    """One round of message passing: each residue gathers messages from its 3D neighbours."""

    def __init__(self, ns, nv, es, ev, dropout):
        super().__init__()
        self.m1 = GVP(2 * ns + es, 2 * nv + ev, ns, nv)
        self.m2 = GVP(ns, nv, ns, nv)
        self.m3 = GVP(ns, nv, ns, nv, act=False)
        self.f1 = GVP(ns, nv, 2 * ns, 2 * nv)
        self.f2 = GVP(2 * ns, 2 * nv, ns, nv, act=False)
        self.n1, self.n2 = Norm(ns), Norm(ns)
        self.drop = nn.Dropout(dropout)

    def forward(self, s, v, idx, es, ev, emask, mask):
        B, L, K = idx.shape
        bi = torch.arange(B, device=s.device)[:, None, None]
        ms = torch.cat([s[:, :, None].expand(-1, -1, K, -1), s[bi, idx], es], -1)
        mv = torch.cat([v[:, :, None].expand(-1, -1, K, -1, -1), v[bi, idx], ev], -2)
        ms, mv = self.m3(*self.m2(*self.m1(ms, mv)))
        w = emask.float()
        cnt = w.sum(-1).clamp(min=1.0)
        ds = (ms * w[..., None]).sum(2) / cnt[..., None]
        dv = (mv * w[..., None, None]).sum(2) / cnt[..., None, None]
        s, v = self.n1(s + self.drop(ds), v + dv)
        fs, fv = self.f2(*self.f1(s, v))
        s, v = self.n2(s + self.drop(fs), v + fv)
        m = mask.float()
        return s * m[..., None], v * m[..., None, None]


class StructureTower(nn.Module):
    N_RBF, MAX_OFF = 16, 32

    def __init__(self, c):
        super().__init__()
        ns, nv, es = c["node_s"], c["node_v"], 32
        self.knn = c["knn"]
        self.node_in = GVP(14, 5, ns, nv, act=False)
        self.off_emb = nn.Embedding(2 * self.MAX_OFF + 1, 16)
        self.edge_in = nn.Linear(self.N_RBF + 16, es)
        self.layers = nn.ModuleList([GVPLayer(ns, nv, es, 1, c["dropout"]) for _ in range(c["gvp_layers"])])
        self.out = GVP(ns, nv, ns, 1)
        self.head = nn.Sequential(nn.Linear(ns, ns), nn.ReLU(), nn.Linear(ns, c["emb_dim"]))
        self.register_buffer("centres", torch.linspace(2.0, 22.0, self.N_RBF))

    def forward(self, X, base, mask):
        node_s, node_v, idx, dist, offset, ev, emask, mask = featurize(X, base, mask, self.knn)
        rbf = torch.exp(-((dist[..., None] - self.centres) / 1.5) ** 2)
        off = self.off_emb(offset.clamp(-self.MAX_OFF, self.MAX_OFF) + self.MAX_OFF)
        es = self.edge_in(torch.cat([rbf, off], -1)) * emask[..., None].float()
        s, v = self.node_in(node_s, node_v)
        for layer in self.layers:
            s, v = layer(s, v, idx, es, ev, emask, mask)
        s, _ = self.out(s, v)
        m = mask.float()
        pooled = (s * m[..., None]).sum(1) / m.sum(1, keepdim=True).clamp(min=1.0)
        return F.normalize(self.head(pooled), dim=-1)


class SequenceTower(nn.Module):
    def __init__(self, c):
        super().__init__()
        d = c["seq_dim"]
        self.emb = nn.Embedding(6, d, padding_idx=5)
        layer = nn.TransformerEncoderLayer(d, c["seq_heads"], 2 * d, c["dropout"], batch_first=True, norm_first=True)
        self.enc = nn.TransformerEncoder(layer, c["seq_layers"], enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d)
        self.head = nn.Sequential(nn.Linear(d, d), nn.ReLU(), nn.Linear(d, c["emb_dim"]))
        self.d = d

    def forward(self, tok):
        pad = tok == 5
        L = tok.shape[1]
        pos = torch.arange(L, device=tok.device)[:, None]
        freq = torch.exp(torch.arange(0, self.d, 2, device=tok.device) * (-math.log(10000.0) / self.d))
        pe = torch.zeros(L, self.d, device=tok.device)
        pe[:, 0::2], pe[:, 1::2] = torch.sin(pos * freq), torch.cos(pos * freq)
        h = self.norm(self.enc(self.emb(tok) + pe[None], src_key_padding_mask=pad))
        m = (~pad).float()
        pooled = (h * m[..., None]).sum(1) / m.sum(1, keepdim=True).clamp(min=1.0)
        return F.normalize(self.head(pooled), dim=-1)


class TwoTower(nn.Module):
    def __init__(self, c):
        super().__init__()
        self.seq, self.struct = SequenceTower(c), StructureTower(c)
        self.mix = nn.Linear(c["emb_dim"], c["emb_dim"]) if c["template_seq"] else None

    def template(self, X, base, mask, tok):
        e = self.struct(X, base, mask)
        if self.mix is not None:
            e = F.normalize(e + self.mix(self.seq(tok)), dim=-1)
        return e


# =============================================================================== losses
def loss_regression(sim, tm, c):
    ok = ~torch.isnan(tm)
    w = torch.where(tm >= c["pos_tm"], c["reg_pos_weight"], 1.0) * ok
    return ((sim - torch.nan_to_num(tm)).abs() * w).sum() / w.sum()


def loss_contrastive(sim, tm, c):
    pos = tm >= c["pos_tm"]
    use = pos | (tm < c["neg_tm"])                                    # NaN and the grey zone drop out
    logits = (sim / c["temperature"]).masked_fill(~use, float("-inf"))
    logp = logits - torch.logsumexp(logits, dim=1, keepdim=True)
    n_pos = pos.sum(1)
    per_q = -(torch.where(pos, logp, torch.zeros_like(logp))).sum(1) / n_pos.clamp(min=1)
    return per_q[n_pos > 0].mean()


# =============================================================================== evaluation
def rank_metrics(score, tm, allowed, c, ks=(1, 5, 10)):
    """score, tm, allowed: [n_queries, n_templates] numpy. Templates with allowed=False are removed."""
    out = {}
    s = np.where(allowed, score, -np.inf)
    t = np.where(allowed, tm, -1.0)
    order = np.argsort(-s, axis=1, kind="stable")
    t_sorted = np.take_along_axis(t, order, 1)
    has_pos = (t >= c["pos_tm"]).any(1)
    out["queries"] = int(len(t))
    out["queries_with_a_similar_template"] = int(has_pos.sum())
    for k in ks:
        top = t_sorted[:, :k]
        out[f"hit@{k}"] = float((top[has_pos] >= c["pos_tm"]).any(1).mean()) if has_pos.any() else None
        out[f"best_tm@{k}"] = float(np.clip(top.max(1), 0, None).mean())
    out["best_tm_possible"] = float(np.clip(t.max(1), 0, None).mean())
    rho = []
    for i in range(len(t)):
        a = allowed[i]
        if a.sum() > 2:
            rho.append(pd.Series(score[i][a]).corr(pd.Series(tm[i][a]), method="spearman"))
    out["spearman"] = float(np.nanmean(rho)) if rho else None
    return out


@torch.no_grad()
def embed(model, data, idxs, which, dev, bs=64):
    model.eval()
    order = sorted(idxs, key=lambda i: len(data["seq"][i] if which == "seq" else data["xyz"][i]))
    out = {}
    for s in range(0, len(order), bs):
        b = order[s:s + bs]
        if which == "seq":
            e = model.seq(pad_seq([data["seq"][i] for i in b], dev))
        else:
            e = model.template(*pad_struct([data["xyz"][i] for i in b], [data["base"][i] for i in b], dev),
                               pad_seq([data["seq"][i] for i in b], dev))
        for i, v in zip(b, e.float().cpu().numpy()):
            out[i] = v
    return np.stack([out[i] for i in idxs])


def kmer_vectors(seqs, k=3):
    v = np.zeros((len(seqs), 4 ** k), dtype=np.float32)
    for i, s in enumerate(seqs):
        s = s.numpy()
        for j in range(len(s) - k + 1):
            w = s[j:j + k]
            if (w < 4).all():
                v[i, int((w * 4 ** np.arange(k)).sum())] += 1
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-8)


# =============================================================================== training
def loss_combined(sim, tm, c):
    return loss_regression(sim, tm, c) + c["con_weight"] * loss_contrastive(sim, tm, c)


def select_score(m):
    return (m["best_tm@1"] + m["best_tm@5"] + m["best_tm@10"]) / 3


def train_one(objective, data, dev, c):                              # `objective` here = the variant's name
    torch.manual_seed(c["seed"])
    rng = np.random.default_rng(c["seed"])
    model = TwoTower(c).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=c["lr"], weight_decay=c["weight_decay"])
    tr, va = data["train_idx"], data["val_idx"]
    tm = data["tm"]
    partners = {q: np.where((tm[q, tr] >= c["pos_tm"]) & (tr != q))[0] for q in tr}
    steps_per_epoch = math.ceil(len(tr) / c["batch_queries"])
    total = c["epochs"] * steps_per_epoch
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / c["warmup_steps"]) *
                                              0.5 * (1 + math.cos(math.pi * min(s, total) / total)))
    loss_fn = {"regression": loss_regression, "contrastive": loss_contrastive, "combined": loss_combined}[c["objective"]]
    tm_val = tm[np.ix_(va, tr)]
    everything = np.ones_like(tm_val, dtype=bool)
    dated = data["before"][np.ix_(va, tr)]
    probe = rng.choice(tr, min(300, len(tr)), replace=False)          # train chains used to watch over-fitting
    tm_probe = tm[np.ix_(probe, tr)]
    not_self = probe[:, None] != tr[None, :]

    history, best, t0, step = [], None, time.time(), 0
    for epoch in range(1, c["epochs"] + 1):
        model.train()
        perm = rng.permutation(tr)
        run = []
        for s in range(0, len(perm), c["batch_queries"]):
            q = perm[s:s + c["batch_queries"]]
            extra = [tr[rng.choice(partners[i])] if len(partners[i]) and rng.random() < 0.9 else rng.choice(tr) for i in q]
            t = np.concatenate([q, np.array(extra)])
            eq = model.seq(pad_seq([data["seq"][i] for i in q], dev))
            et = model.template(*pad_struct([data["xyz"][i] for i in t], [data["base"][i] for i in t], dev),
                                pad_seq([data["seq"][i] for i in t], dev))
            loss = loss_fn(eq @ et.T, torch.from_numpy(tm[np.ix_(q, t)]).to(dev), c)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), c["grad_clip"])
            opt.step()
            sched.step()
            step += 1
            run.append(loss.item())
        minutes = (time.time() - t0) / 60
        last = epoch == c["epochs"] or minutes > c["max_minutes_per_objective"]
        if epoch % c["eval_every"] == 0 or last:
            et = embed(model, data, list(tr), "struct", dev)
            m = rank_metrics(embed(model, data, list(va), "seq", dev) @ et.T, tm_val, everything, c)
            p = rank_metrics(embed(model, data, list(probe), "seq", dev) @ et.T, tm_probe, not_self, c)
            row = dict(variant=objective, select=select_score(m), epoch=epoch, minutes=round(minutes, 1), train_loss=float(np.mean(run)),
                       **{f"val_{k}": v for k, v in m.items() if "@" in k or k == "spearman"},
                       **{f"train_{k}": p[k] for k in ("hit@5", "best_tm@5", "spearman")})
            history.append(row)
            print(json.dumps(row), flush=True)
            if best is None or row["select"] > best["select"]:
                best = dict(row)
                torch.save({"model": model.state_dict(), "cfg": c, "objective": objective, "epoch": epoch},
                           WORK / f"model_{objective}.pt")
        if last:
            if epoch < c["epochs"]:
                print(f"{objective}: time budget reached at epoch {epoch}", flush=True)
            break

    # ---- final numbers from the best checkpoint
    model.load_state_dict(torch.load(WORK / f"model_{objective}.pt", map_location=dev)["model"])
    score = embed(model, data, list(va), "seq", dev) @ embed(model, data, list(tr), "struct", dev).T
    res = {"best_epoch": best["epoch"], "epochs_run": epoch, "minutes": round((time.time() - t0) / 60, 1),
           "parameters": int(sum(p.numel() for p in model.parameters())),
           "val": rank_metrics(score, tm_val, everything, c),
           "val_date_filter": rank_metrics(score, tm_val, dated, c),
           "mean_abs_error_cosine_vs_tm": float(np.abs(score - tm_val).mean())}
    k = min(c["topk_saved"], len(tr))
    order = np.argsort(-score, axis=1, kind="stable")[:, :k]
    top = pd.DataFrame({"objective": objective, "query": np.repeat([data["ids"][i] for i in va], k),
                        "rank": np.tile(np.arange(1, k + 1), len(va)),
                        "template": [data["ids"][tr[j]] for j in order.ravel()],
                        "score": np.take_along_axis(score, order, 1).ravel(),
                        "tm_q": np.take_along_axis(tm_val, order, 1).ravel()})
    return res, history, top, score


def main():
    c = CFG
    dev = torch.device("cpu")
    if torch.cuda.is_available():
        try:                                                          # some Kaggle GPUs are too old for the installed PyTorch
            torch.zeros(4, device="cuda").sum().item()
            dev = torch.device("cuda")
        except Exception as exc:
            print("GPU present but unusable, falling back to CPU:", exc, flush=True)
    print("device:", dev, torch.cuda.get_device_name(0) if dev.type == "cuda" else "", "| config:", json.dumps(c), flush=True)
    data = load_data()
    tr, va = data["train_idx"], data["val_idx"]
    print(f"{len(tr)} train chains, {len(va)} val queries", flush=True)

    # ---- reference methods on the same queries and templates
    tm_val = data["tm"][np.ix_(va, tr)]
    everything, dated = np.ones_like(tm_val, dtype=bool), data["before"][np.ix_(va, tr)]
    len_q = np.array([len(data["seq"][i]) for i in va])[:, None]
    len_t = np.array([len(data["seq"][i]) for i in tr])[None, :]
    refs = {"random order": np.random.default_rng(0).random(tm_val.shape),
            "closest length": -np.abs(len_q - len_t).astype(np.float32),
            "3-mer sequence similarity": kmer_vectors([data["seq"][i] for i in va]) @ kmer_vectors([data["seq"][i] for i in tr]).T}
    metrics = {"config": c, "device": str(dev), "train_chains": int(len(tr)), "val_queries": int(len(va)),
               "reference": {k: {"val": rank_metrics(s, tm_val, everything, c),
                                 "val_date_filter": rank_metrics(s, tm_val, dated, c)} for k, s in refs.items()}}
    print(json.dumps(metrics["reference"], indent=1), flush=True)

    def z(x):
        return (x - x.mean(1, keepdims=True)) / (x.std(1, keepdims=True) + 1e-8)

    history, summary, scores = [], [], {"kmer3": refs["3-mer sequence similarity"], "tm": tm_val, "dated": dated}
    for name, r in metrics["reference"].items():
        summary.append({"variant": name, **r["val"]})
    for name, over in EXPERIMENTS.items():
        cc = {**c, **over}
        print(f"=== {name}: {json.dumps(over)}", flush=True)
        res, h, _, score = train_one(name, data, dev, cc)
        fused = z(score) + z(refs["3-mer sequence similarity"])
        res["plus_3mer"] = {"val": rank_metrics(fused, tm_val, everything, c),
                            "val_date_filter": rank_metrics(fused, tm_val, dated, c)}
        res["overrides"] = over
        metrics[name] = res
        history += h
        scores[name] = score
        summary.append({"variant": name, "best_epoch": res["best_epoch"], **res["val"]})
        summary.append({"variant": name + " + 3-mer", **res["plus_3mer"]["val"]})
        pd.DataFrame(history).to_csv(WORK / "tune_history.csv", index=False)
        pd.DataFrame(summary).to_csv(WORK / "tune_summary.csv", index=False)
        (WORK / "tune_metrics.json").write_text(json.dumps(metrics, indent=2))
        np.savez_compressed(WORK / "val_scores.npz", val_ids=np.array([data["ids"][i] for i in va]),
                            train_ids=np.array([data["ids"][i] for i in tr]), **scores)
        print(pd.DataFrame(summary).round(3).to_string(index=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
