# -*- coding: utf-8 -*-
"""10 methods x 3 subsets, seed-conditional (per-subset seed union filter)."""
import csv, importlib.util, os, pickle, sys
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
PRED = os.path.join(BASE, "results", "predictions") + os.sep
sys.modules['__main__'].TokenIDGene = type('TokenIDGene', (), {})
spec = importlib.util.spec_from_file_location("E", os.path.join(ROOT, "07_inference_evaluation", "Eval.py"))
E = importlib.util.module_from_spec(spec); spec.loader.exec_module(E)
idmap = pickle.load(open(os.path.join(ROOT, "data", "token_id_gene.pkl"), "rb")).id_to_gene

groups = pickle.load(open(PRED + "fig4" + os.sep + "groups.pkl", "rb"))
ALGO = PRED + "baselines" + os.sep
BASE = [("clusterone", "ClusterONE.pkl"), ("mcode", "MCODE.pkl"), ("coach", "COACH.pkl"),
        ("mcl", "MCL.pkl"), ("graphentropy", "GraphEntropy.pkl"), ("dpclus", "DPClus.pkl"),
        ("pcgan", "PCGAN_matched.pkl"), ("ipca", "IPCA_matched.pkl"), ("core", "Core.pkl")]

def to_set(items):
    out = set()
    for m in items:
        if isinstance(m, str):
            out.add(idmap[int(m)] if m.isdigit() and int(m) in idmap else m)
        else:
            out.add(idmap.get(int(m), str(m)))
    return frozenset(out)

# 预载基线预测
base_preds = {}
for name, fn in BASE:
    p = ALGO + fn
    if os.path.exists(p):
        raw = pickle.load(open(p, "rb"))
        base_preds[name] = [to_set(x) for x in raw]

rows = []
for gname in ["fig4a_training", "fig4a_overlap", "fig4a_unseen"]:
    g = groups[gname]
    seeds = set(g["seeds"])
    gold = [frozenset(x) for x in g["gold"]]
    # GRACE：该组自己的种子生成
    raw = pickle.load(open(PRED + "fig4" + os.sep + gname + ".pkl", "rb"))
    gp = [set(str(x["sft_response"]).split()) for x in raw]
    gp = [p for p in gp if len(p) >= 2]
    r = E.evaluate(gold, gp, threshold=0.2)
    rows.append([gname, "GRACE", len(gold), len(gp), round(float(r["Precision"]),4), round(float(r["Recall"]),4),
                 round(float(r["F1"]),4), round(float(r["Global_MMR"]),4), round(float(r["Mean_MMR"]),4),
                 PRED + "fig4/" + gname + ".pkl", "per-subset generation"])
    print(gname, "GRACE", len(gp), "R=%.4f MMMR=%.4f" % (r["Recall"], r["Mean_MMR"]), flush=True)
    for name, preds in base_preds.items():
        sub = [p for p in preds if len(p) >= 2 and (set(p) & seeds)]
        if not sub:
            print(gname, name, "NO PRED"); continue
        r = E.evaluate(gold, sub, threshold=0.2)
        rows.append([gname, name, len(gold), len(sub), round(float(r["Precision"]),4), round(float(r["Recall"]),4),
                     round(float(r["F1"]),4), round(float(r["Global_MMR"]),4), round(float(r["Mean_MMR"]),4),
                     ALGO + dict(BASE)[name], "filtered: contains >=1 protein of the subset"])
        print(gname, name, len(sub), "R=%.4f MMMR=%.4f" % (r["Recall"], r["Mean_MMR"]), flush=True)

with open(os.path.join(BASE, "results", "grid10_by_subset.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["set","method","n_known","n_pred_scored","Precision","Recall","F1","Global_MMR","Mean_MMR","source_pkl","note"])
    w.writerows(rows)
print("DONE", len(rows))
