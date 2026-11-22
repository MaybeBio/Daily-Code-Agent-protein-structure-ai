"""Step 3: MLP + kNN blend on concatenated ESM2-150M + ESM2-650M embeddings.
Validates on a KMeans-cluster holdout, then writes /kaggle/working/submission_blend.tsv.
Exported from the Kaggle notebook cells (paths are Kaggle paths; DEBUG=True runs a tiny CPU smoke test)."""
import os, time, pickle, collections, numpy as np, pandas as pd, torch, torch.nn as nn, torch.nn.functional as F
from sklearn.cluster import MiniBatchKMeans
DEBUG = not torch.cuda.is_available(); dev = 'cpu' if DEBUG else 'cuda:0'
D = '/kaggle/input/competitions/cafa-6-protein-function-prediction'; PI = '/kaggle/input/notebooks/sijanregmi/notebookceef1c790f'
prot, parents, ns, iad = pickle.load(open(f'{PI}/labels.pkl', 'rb'))
def read_ids(path):
    out = []
    for l in open(path):
        if l.startswith('>'):
            h = l[1:].split()[0]; out.append(h.split('|')[1] if '|' in h else h)
    return out
tr_ids = read_ids(f'{D}/Train/train_sequences.fasta'); te_ids = read_ids(f'{D}/Test/testsuperset.fasta')
cnt = collections.Counter(t for s in prot.values() for t in s)
NSN = {'BPO': 'biological_process', 'MFO': 'molecular_function', 'CCO': 'cellular_component'}
ROOTS = {'GO:0008150', 'GO:0003674', 'GO:0005575'}
terms = []; aspect_of = []
for a, nn_ in NSN.items():
    ts = sorted(t for t, v in cnt.items() if ns.get(t) == nn_ and v >= 50 and t not in ROOTS)
    terms += ts; aspect_of += [a] * len(ts)
aspect_of = np.array(aspect_of); tix = {t: i for i, t in enumerate(terms)}
w = np.array([iad.get(t, 0.0) for t in terms], dtype=np.float32)
Y = np.zeros((len(tr_ids), len(terms)), np.uint8)
for r, p in enumerate(tr_ids):
    for t in prot[p]:
        j = tix.get(t)
        if j is not None: Y[r, j] = 1
edges = np.array([(tix[c], tix[p]) for c in terms for p in parents.get(c, ()) if p in tix])
te_pos = {p: i for i, p in enumerate(te_ids)}; tr_te = np.array([te_pos[p] for p in tr_ids])
X = np.zeros((len(te_ids), 640), np.float16)
for s in (0, 1): X[np.load(f'{PI}/idx_{s}.npy')] = np.load(f'{PI}/emb_{s}.npy')
Xf = X.astype(np.float32); Xs = (Xf - Xf.mean(0)) / (Xf.std(0) + 1e-6); del Xf, X
if DEBUG: Y, tr_te = Y[:8000], tr_te[:8000]
Xtr = Xs[tr_te]; print('DEBUG', DEBUG, 'terms', len(terms), 'Y', Y.shape, 'Xtr', Xtr.shape, 'edges', edges.shape)
wt = torch.tensor(w, device=dev); E = torch.tensor(edges, device=dev)
cols = {a: torch.tensor(np.where(aspect_of == a)[0], device=dev) for a in NSN}
def wmaxf(P, Yt, a):
    c = cols[a]; p = P[:, c]; y = Yt[:, c]; ww = wt[c]
    tw = y @ ww; keep = tw > 0; p, y, tw = p[keep], y[keep], tw[keep]
    best = 0.0
    for th in np.arange(0.02, 0.99, 0.02):
        pr = (p >= th).float(); pw = pr @ ww; tp = (pr * y) @ ww; has = pw > 0
        if has.sum() == 0: continue
        prec = (tp[has] / pw[has]).mean(); rec = (tp / tw).mean()
        best = max(best, (2 * prec * rec / (prec + rec + 1e-9)).item())
    return best
def score(P, Yt):
    r = {a: wmaxf(P, Yt, a) for a in NSN}; r['mean'] = float(np.mean(list(r.values()))); return {k: round(v, 4) for k, v in r.items()}
def propagate(P, iters=20):
    P = P.clone()
    for _ in range(iters): P.index_reduce_(1, E[:, 1], P[:, E[:, 0]], 'amax')
    return P

# ---- add the ESM2-650M embeddings (output of embed.py run with the 650M settings) ----
P6 = '/kaggle/input/notebooks/sijanregmi/notebooka646ba0f0b'
X6 = np.zeros((len(te_ids), 1280), np.float16)
for s in (0, 1): X6[np.load(f'{P6}/idx650_{s}.npy')] = np.load(f'{P6}/emb650_{s}.npy')
X6 = X6.astype(np.float32); X6 = (X6 - X6.mean(0)) / (X6.std(0) + 1e-6)
Xs = np.concatenate([Xs, X6], 1); del X6
Xtr = Xs[tr_te]; print('combined features', Xs.shape, Xtr.shape)
_Linear = nn.Linear
nn.Linear = lambda i, o, *a, **k: _Linear(Xs.shape[1] if i == 640 else i, o, *a, **k)  # first MLP layer takes the combined features

# ---- MLP: cluster holdout, fit, predict ----
NC = 40 if DEBUG else 300; EPOCHS = 1 if DEBUG else 15; NSEED = 1 if DEBUG else 5
cl = MiniBatchKMeans(NC, random_state=0, n_init=3, batch_size=4096).fit_predict(Xtr)
ho = np.isin(cl, np.random.RandomState(0).choice(NC, NC // 10, replace=False)); print('holdout', ho.sum(), 'train', (~ho).sum())
def fit(Xa, Ya, epochs, seed=0, bs=512):
    torch.manual_seed(seed); T = Ya.shape[1]
    m = nn.Sequential(nn.Linear(640, 1536), nn.BatchNorm1d(1536), nn.ReLU(), nn.Dropout(0.3), nn.Linear(1536, 1536), nn.BatchNorm1d(1536), nn.ReLU(), nn.Dropout(0.3), nn.Linear(1536, T)).to(dev)
    Xg = torch.tensor(Xa, device=dev); Yg = torch.tensor(Ya, device=dev); n = len(Xg); spe = (n + bs - 1) // bs
    opt = torch.optim.AdamW(m.parameters(), 1e-3, weight_decay=1e-2)
    sch = torch.optim.lr_scheduler.OneCycleLR(opt, 2e-3, total_steps=epochs * spe)
    for ep in range(epochs):
        m.train(); perm = torch.randperm(n, device=dev); tot = 0
        for i in range(0, n, bs):
            ix = perm[i:i + bs]; loss = F.binary_cross_entropy_with_logits(m(Xg[ix]), Yg[ix].float())
            opt.zero_grad(); loss.backward(); opt.step(); sch.step(); tot += loss.item()
        print('epoch', ep, round(tot / spe, 5), flush=True)
    return m.eval()
def predict(m, Xa, bs=4096):
    with torch.no_grad(): return torch.cat([torch.sigmoid(m(torch.tensor(Xa[i:i + bs], device=dev))) for i in range(0, len(Xa), bs)])
t0 = time.time(); m1 = fit(Xtr[~ho], Y[~ho], EPOCHS); print('holdout-fit secs', round(time.time() - t0))
Yh = torch.tensor(Y[ho], dtype=torch.float32, device=dev); Ph = predict(m1, Xtr[ho])
print('MLP raw       :', score(Ph, Yh)); print('MLP propagated:', score(propagate(Ph), Yh))
fq = torch.tensor(Y[~ho].mean(0), dtype=torch.float32, device=dev); print('freq prior    :', score(fq.expand(Yh.shape[0], -1).contiguous(), Yh))
models = [fit(Xtr, Y, EPOCHS, seed=s) for s in range(NSEED)]
n_te = 2000 if DEBUG else len(te_ids); K = 100; TH = 0.03; tarr = np.array(terms); idarr = np.array(te_ids)

# ---- kNN label transfer + per-ontology blend weight ----
Xn = torch.tensor(Xs / (np.linalg.norm(Xs, axis=1, keepdims=True) + 1e-8)).to(dev)
Yall = torch.tensor(Y, device=dev)
def topk_sims(Q, DB, k, bs=2048):
    S, I = [], []
    for i in range(0, len(Q), bs):
        v, ix = torch.topk(Q[i:i + bs] @ DB.T, k, dim=1); S.append(v); I.append(ix)
    return torch.cat(S), torch.cat(I)
def knn_pred(S, I, Ydb, k, p, bs=512):
    out = []
    for i in range(0, len(S), bs):
        s = S[i:i + bs, :k].clamp(min=0) ** p; wg = s / (s.sum(1, keepdim=True) + 1e-9)
        out.append((wg.unsqueeze(-1) * Ydb[I[i:i + bs, :k]].float()).sum(1))
    return torch.cat(out)
hoi = np.where(ho)[0]; dbi = np.where(~ho)[0]; dbt = torch.tensor(dbi, device=dev)
S, I = topk_sims(Xn[tr_te[hoi]], Xn[tr_te[dbi]], 30)
best = (-1, None, None)
for k in (10, 30):
    for p in (4, 12):
        Pk = knn_pred(S, I, Yall[dbt], k, p); sc = score(propagate(Pk), Yh); print('kNN k', k, 'p', p, sc)
        if sc['mean'] > best[0]: best = (sc['mean'], (k, p), Pk)
kb, pb_ = best[1]; Pk = best[2]; print('best kNN', best[1])
res = {}
for a in (0.0, 0.25, 0.5, 0.75, 1.0):
    res[a] = score(propagate(a * Ph + (1 - a) * Pk), Yh); print('alpha(MLP weight)', a, res[a])
alpha = {asp: max(res, key=lambda a: res[a][asp]) for asp in NSN}
print('chosen alpha per ontology', alpha, 'blend mean', round(float(np.mean([res[alpha[a]][a] for a in NSN])), 4))

# ---- final blended submission (top-K terms per protein, score >= TH) ----
Avec = torch.tensor([alpha[a] for a in aspect_of], device=dev, dtype=torch.float32)
DBf = Xn[tr_te]; sub2 = '/kaggle/working/submission_blend.tsv'
if os.path.exists(sub2): os.remove(sub2)
for i in range(0, n_te, 4096):
    j = min(i + 4096, n_te); xb = Xs[i:j]
    S2, I2 = topk_sims(Xn[i:j], DBf, kb)
    pm = sum(predict(m, xb) for m in models) / len(models)
    pb = propagate(Avec * pm + (1 - Avec) * knn_pred(S2, I2, Yall, kb, pb_))
    v, ix = torch.topk(pb, K, dim=1); v, ix = v.cpu().numpy(), ix.cpu().numpy()
    msk = v >= TH; rows = np.repeat(np.arange(len(xb)), K).reshape(len(xb), K)[msk]
    pd.DataFrame({'a': idarr[i:j][rows], 'b': tarr[ix[msk]], 'c': v[msk]}).to_csv(sub2, sep='\t', header=False, index=False, float_format='%.3f', mode='a')
print(round(os.path.getsize(sub2) / 1e6, 1), 'MB'); print(open(sub2).read()[:200])
