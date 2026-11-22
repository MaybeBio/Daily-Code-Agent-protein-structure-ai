# -*- coding: utf-8 -*-
"""Build the nine evaluation groups (Fig. 4A + size/degree strata) from the 7:3 partition.

Outputs, under results/predictions/fig4/: groups.pkl and seeds/<group>.pkl
"""
import os, pickle, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.normpath(os.path.join(HERE, ".."))          # 10.2_heldout_generalization/
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
SPLIT = os.path.join(ROOT, "data", "split_7-3") + os.sep
DATA = os.path.join(ROOT, "data") + os.sep
OUT = os.path.join(BASE, "results", "predictions", "fig4") + os.sep

sys.modules['__main__'].TokenIDGene = type('TokenIDGene', (), {})
id_to_gene = pickle.load(open(DATA + "token_id_gene.pkl", "rb")).id_to_gene
graph = pickle.load(open(DATA + "graph.pkl", "rb"))
load = lambda fn: pickle.load(open(SPLIT + fn, "rb"))
to_sets = lambda cs: [frozenset(id_to_gene[n] for n in c.nodes() if n in id_to_gene) for c in cs]

train, test = load("Complex_Train.pkl"), load("Complex_Test.pkl")
ov, un = load("Test_has_overlap.pkl"), load("Test_truly_unseen.pkl")

def mean_deg(c):
    ns = [n for n in c.nodes() if graph.has_node(n)]
    return sum(graph.degree(n) for n in ns) / float(max(1, len(ns)))

groups = {}
def put(name, axis, binname, complexes):
    gs = to_sets(complexes)
    groups[name] = dict(axis=axis, bin=binname, seeds=sorted({p for s in gs for p in s}),
                        gold=[sorted(s) for s in gs], n_known=len(gs))
    print("%-22s %-7s %-18s n_known=%4d seeds=%5d" % (name, axis, binname, len(gs), len(groups[name]["seeds"])), flush=True)

put("fig4a_training", "fig4a", "", train)
put("fig4a_overlap", "fig4a", "", ov)
put("fig4a_unseen", "fig4a", "", un)

sizes = np.array([len(s) for s in to_sets(test)])
degs = np.array([mean_deg(c) for c in test])
q1, q2 = np.percentile(degs, [33.3333, 66.6667])
sbin = lambda n: "2-3" if n <= 3 else ("4-5" if n <= 5 else "6+")
dbin = lambda d: "low(<=60.0)" if d <= q1 else ("mid(60.0-143.3)" if d <= q2 else "high(>143.3)")
for b in ["2-3", "4-5", "6+"]:
    idx = [i for i in range(len(test)) if sbin(sizes[i]) == b]
    put("fig4b_size_" + b, "size", b, [test[i] for i in idx])
for b in ["low", "mid", "high"]:
    idx = [i for i in range(len(test)) if dbin(degs[i]).startswith(b + "(")]
    put("fig4b_degree_" + b, "degree", dbin(degs[idx[0]]), [test[i] for i in idx])

os.makedirs(os.path.join(OUT, "seeds"), exist_ok=True)
pickle.dump(groups, open(OUT + "groups.pkl", "wb"))
for n, g in groups.items():
    pickle.dump(g["seeds"], open(OUT + "seeds/%s.pkl" % n, "wb"))
print("WROTE", OUT + "groups.pkl", "| groups", len(groups), "| q1=%.1f q2=%.1f" % (q1, q2))
