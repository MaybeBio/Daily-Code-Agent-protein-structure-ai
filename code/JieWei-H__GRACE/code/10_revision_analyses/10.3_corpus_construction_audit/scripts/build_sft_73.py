#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build the 7:3 leakage-controlled SFT corpus.

Same rule as the pre-training corpus: drop any noisy complex whose Jaccard
similarity to a held-out complex is >= 0.3.  The filtered complexes are then
serialised with the original SFT builder, so the output format is identical to
finetune_data/sft_0.json.
"""
import importlib.util
import os
import pickle
import sys
import time

sys.modules["__main__"].TokenIDGene = type("TokenIDGene", (), {})

SRC = "/root/LLM/Model-Heltout/Dataset"
OUT = "/root/LLM73"
TEST_SETS = "/root/gpu_runs/test_complex_idsets_73.pkl"
THRESH = 0.3

os.makedirs(OUT, exist_ok=True)


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


log("loading PPI / token / held-out sets")
ppi = pickle.load(open(os.path.join(SRC, "Graph_init/graph.pkl"), "rb"))
tok = pickle.load(open(os.path.join(SRC, "Graph_init/token_id_gene.pkl"), "rb"))
tests = [frozenset(int(n) for n in s) for s in pickle.load(open(TEST_SETS, "rb"))]
tests = [t for t in tests if t]
inv = {}
for i, t in enumerate(tests):
    for n in t:
        inv.setdefault(n, []).append(i)


def is_leak(nodes):
    cand = set()
    for n in nodes:
        c = inv.get(n)
        if c:
            cand.update(c)
    if not cand:
        return False
    ln = len(nodes)
    for ci in cand:
        t = tests[ci]
        inter = len(nodes & t)
        if inter and inter / float(ln + len(t) - inter) >= THRESH:
            return True
    return False


src = "/root/GraphModuleGenerate/Subgraph/dynamic_complex.pkl"
log("loading %s" % src)
obj = pickle.load(open(src, "rb"))
log("entries %d, element type %s" % (len(obj), type(obj[0])))

sample = obj[0]
is_tuple = isinstance(sample, (tuple, list)) and hasattr(sample[0], "nodes")
log("element layout: %s" % ("(graph, label)" if is_tuple else "graph"))

kept, dropped = [], 0
for item in obj:
    g = item[0] if is_tuple else item
    nodes = frozenset(int(n) for n in g.nodes())
    if is_leak(nodes):
        dropped += 1
        continue
    kept.append(item)
log("kept %d, dropped %d (%.1f%%)" % (len(kept), dropped, 100.0 * dropped / max(1, len(obj))))

if is_tuple:
    graphs = [it[0] for it in kept]
    labels = [it[1] for it in kept]
    tmp = os.path.join(OUT, "dynamic_complex_73.pkl")
    pickle.dump(graphs, open(tmp, "wb"))
    pickle.dump(labels, open(os.path.join(OUT, "dynamic_complex_label_73.pkl"), "wb"))
else:
    tmp = os.path.join(OUT, "dynamic_complex_73.pkl")
    pickle.dump(kept, open(tmp, "wb"))
log("filtered complexes -> %s" % tmp)

# serialise with the original SFT builder
spec = importlib.util.spec_from_file_location(
    "sftmod", os.path.join(SRC, "GraphTransform_BFS_SFT-1.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

out_dir = os.path.join(OUT, "finetune_data")
os.makedirs(out_dir, exist_ok=True)
sft_file = m.process_chunk(0, ppi, tok, "/root/GraphModuleGenerate/Subgraph", out_dir, tmp)
log("SFT corpus -> %s (%.1f MB)" % (sft_file, os.path.getsize(sft_file) / 1e6))
log("DONE sft73")
