"""Step 2: mean-pooled ESM2 embeddings for the test superset (includes all train proteins).
Usage: python embed.py <shard> <nshard>   (one process per GPU).
Set MODEL/DIM/BUDGET/TAG below for ESM2-150M (default) or ESM2-650M (see README)."""
import sys, numpy as np, torch, time
from transformers import AutoTokenizer, EsmModel
MODEL, DIM, BUDGET, TAG = 'facebook/esm2_t30_150M_UR50D', 640, 12000, ''
# 650M variant: 'facebook/esm2_t33_650M_UR50D', 1280, 8000, '650'
shard, nshard = int(sys.argv[1]), int(sys.argv[2])
D = '/kaggle/input/competitions/cafa-6-protein-function-prediction'
ids, seqs, cur = [], [], []
for line in open(f'{D}/Test/testsuperset.fasta'):
    line = line.rstrip()
    if line.startswith('>'):
        if cur: seqs.append(''.join(cur)); cur = []
        ids.append(line[1:].split()[0])
    else: cur.append(line)
if cur: seqs.append(''.join(cur))
order = np.argsort([len(s) for s in seqs], kind='stable')[shard::nshard]
n = len(order)
tok = AutoTokenizer.from_pretrained(MODEL)
model = EsmModel.from_pretrained(MODEL, add_pooling_layer=False).half().cuda().eval()
batches = []; i = 0
while i < n:
    j = i + 1
    while j < n and (j - i + 1) * min(len(seqs[order[j]]), 1022) <= BUDGET: j += 1
    batches.append((i, j)); i = j
out = np.zeros((n, DIM), np.float16); t0 = time.time()
for b, (i, j) in enumerate(batches):
    enc = tok([seqs[k] for k in order[i:j]], return_tensors='pt', padding=True, truncation=True, max_length=1024).to('cuda')
    with torch.no_grad():
        h = model(**enc).last_hidden_state
    m = enc['attention_mask'].unsqueeze(-1).half()
    out[i:j] = ((h * m).sum(1) / m.sum(1)).float().cpu().numpy().astype(np.float16)
    if b % 50 == 0: print(b, len(batches), j, n, round(time.time() - t0), flush=True)
np.save(f'/kaggle/working/emb{TAG}_{shard}.npy', out)
np.save(f'/kaggle/working/idx{TAG}_{shard}.npy', order)
print('DONE', time.time() - t0, flush=True)
