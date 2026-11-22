# -*- coding: utf-8 -*-
"""Overlap of the 7:3 pretraining corpus with the 7:3 held-out complexes.
The 7:3 corpus is a single-line JSON array, so sequences are streamed with a
regex over raw bytes instead of parsing JSON per line.
"""
import os
import json, pickle, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
SPLIT = os.path.join(ROOT, "data", "split_7-3") + os.sep
CORPUS = os.environ.get("CORPUS", "pretrain_combined_73_20m.json")  # not shipped; pass via env
OUTDIR = os.path.join(BASE, "results") + os.sep
MAP = os.path.join(ROOT, "data", "token_id_gene.pkl")

sys.modules['__main__'].TokenIDGene = type('TokenIDGene', (), {})
id_to_gene = pickle.load(open(MAP, 'rb')).id_to_gene

def load(fn):
    return pickle.load(open(SPLIT + fn, 'rb'))

tests = load("Complex_Test.pkl")
known = [frozenset(id_to_gene[n] for n in c.nodes() if n in id_to_gene) for c in tests]
unseen = {frozenset(c.nodes()) for c in load("Test_truly_unseen.pkl")}
overlap = {frozenset(c.nodes()) for c in load("Test_has_overlap.pkl")}
groups = ['unseen' if frozenset(c.nodes()) in unseen else
          ('overlap' if frozenset(c.nodes()) in overlap else 'unassigned') for c in tests]
print("HELDOUT", len(known), "groups", {g: groups.count(g) for g in set(groups)}, flush=True)

inv = {}
for i, s in enumerate(known):
    for g in s:
        inv.setdefault(g, []).append(i)

hit_sup = [0] * len(known)
hit_exact = [0] * len(known)
first = [-1] * len(known)

pat = re.compile(r'<\|im_start\|>([^<]*)<\|im_end\|>')
CHUNK = 64 * 1024 * 1024
n_seq = 0
carry = ""
t0 = time.time()
with open(CORPUS, 'r', encoding='utf-8', newline='') as f:
    while True:
        buf = f.read(CHUNK)
        if not buf:
            text = carry
            carry = ""
        else:
            text = carry + buf
            cut = text.rfind('<|im_start|>')
            if cut > 0:
                carry = text[cut:]
                text = text[:cut]
            else:
                carry = ""
        for seq in pat.findall(text):
            n_seq += 1
            gs = set(seq.split())
            ngs = len(gs)
            cand = set()
            for g in gs:
                cand.update(inv.get(g, ()))
            for i in cand:
                ks = known[i]
                if len(ks) <= ngs and ks <= gs:
                    hit_sup[i] += 1
                    if first[i] < 0:
                        first[i] = n_seq
                    if len(ks) == ngs:
                        hit_exact[i] += 1
        if not buf:
            break
        if n_seq and n_seq % 2000000 < 100000:
            print("PROGRESS seq", n_seq, "%.0fs" % (time.time() - t0), flush=True)
        if (time.time() - t0) > 3000:
            print("TIMEOUT_GUARD", flush=True)
            break

rows = [[i, groups[i], len(known[i]), hit_sup[i], hit_exact[i], first[i]] for i in range(len(known))]
import csv
with open(OUTDIR + "corpus_overlap_73.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["idx", "subset", "size", "n_hit_superset", "n_hit_exact", "first_hit_seq"])
    w.writerows(rows)

lines = ["bfs_sequences %d" % n_seq, "heldout_complexes %d" % len(known),
         "elapsed_sec %.1f" % (time.time() - t0)]
for g in ("overlap", "unseen", "unassigned"):
    idx = [i for i in range(len(known)) if groups[i] == g]
    if not idx:
        continue
    ns = sum(1 for i in idx if hit_sup[i] > 0)
    ne = sum(1 for i in idx if hit_exact[i] > 0)
    lines.append("%s n=%d hit_superset>=1 %d (%.1f%%) hit_exact>=1 %d (%.1f%%)" % (
        g, len(idx), ns, 100.0 * ns / len(idx), ne, 100.0 * ne / len(idx)))
txt = "\n".join(lines)
print(txt, flush=True)
open(OUTDIR + "corpus_overlap_73_summary.txt", "w").write(txt + "\n")
