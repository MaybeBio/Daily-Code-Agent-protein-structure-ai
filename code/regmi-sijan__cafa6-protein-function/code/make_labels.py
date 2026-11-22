"""Step 1: parse the GO ontology, propagate train labels up the hierarchy (true-path rule),
and save (prot, parents, ns, ia) to labels.pkl.  Written for Kaggle paths."""
import numpy as np, pandas as pd, collections, pickle
D = '/kaggle/input/competitions/cafa-6-protein-function-prediction'
tr = pd.read_csv(f'{D}/Train/train_terms.tsv', sep='\t', header=0, names=['pid', 'term', 'aspect'])
parents = collections.defaultdict(set); ns = {}; cur = None
for line in open(f'{D}/Train/go-basic.obo'):
    line = line.strip()
    if line == '[Term]': cur = None
    elif line.startswith('id: GO:'): cur = line[4:]
    elif cur and line.startswith('namespace: '): ns[cur] = line.split()[1]
    elif cur and line.startswith('is_a: '): parents[cur].add(line.split()[1])
    elif cur and line.startswith('relationship: part_of '): parents[cur].add(line.split()[2])
anc = {}
def ancestors(t):
    if t not in anc:
        s = set()
        for p in parents.get(t, ()): s.add(p); s |= ancestors(p)
        anc[t] = s
    return anc[t]
prot = {}
for p, t in zip(tr.pid, tr.term):
    prot.setdefault(p, set()).add(t)
for p in prot:
    s = set(prot[p])
    for t in prot[p]: s |= ancestors(t)
    prot[p] = s
ia = pd.read_csv(f'{D}/IA.tsv', sep='\t', header=None, names=['term', 'ia']).set_index('term').ia
pickle.dump((prot, dict(parents), ns, ia.to_dict()), open('/kaggle/working/labels.pkl', 'wb'))
