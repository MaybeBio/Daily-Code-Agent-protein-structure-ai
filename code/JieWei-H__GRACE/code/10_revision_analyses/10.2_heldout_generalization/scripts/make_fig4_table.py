# -*- coding: utf-8 -*-
"""Score the nine per-group generation files and write fig4ab_seed_conditional_subsets.csv."""
import csv, importlib.util, os, pickle, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
GEN = os.path.join(BASE, "results", "predictions", "fig4") + os.sep
OUTCSV = os.path.join(BASE, "results", "fig4ab_seed_conditional_subsets.csv")

sys.modules['__main__'].TokenIDGene = type('TokenIDGene', (), {})
spec = importlib.util.spec_from_file_location("E", os.path.join(ROOT, "07_inference_evaluation", "Eval.py"))
E = importlib.util.module_from_spec(spec); spec.loader.exec_module(E)

groups = pickle.load(open(GEN + "groups.pkl", "rb"))
rows = []
for name in groups:
    p = GEN + name + ".pkl"
    if not os.path.exists(p):
        print("MISSING", name, flush=True); continue
    raw = pickle.load(open(p, "rb"))
    preds = [set(str(x["sft_response"]).split()) for x in raw]
    n_all = len(preds)
    preds = [q for q in preds if len(q) >= 2]
    gold = [frozenset(x) for x in groups[name]["gold"]]
    r = E.evaluate(gold, preds, threshold=0.2)
    rows.append([name, groups[name]["axis"], groups[name]["bin"], len(gold), n_all, len(preds),
                 round(float(r["Recall"]), 4), round(float(r["Global_MMR"]), 4), round(float(r["Mean_MMR"]), 4),
                 "results/predictions/fig4/%s.pkl" % name,
                 "seeds = union of member proteins of the group; beta 2.0 / temp .85 / top_p .85 / top_k 10 / seed 20030201"])
    print("%-22s n_known=%4d n_scored=%5d R=%.4f GMMR=%.4f MMMR=%.4f" % (
        name, len(gold), len(preds), r["Recall"], r["Global_MMR"], r["Mean_MMR"]), flush=True)

with open(OUTCSV, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["set", "axis", "bin", "n_known", "n_pred_all", "n_pred_scored",
                "Recall", "Global_MMR", "Mean_MMR", "source_pkl", "note"])
    w.writerows(rows)
print("DONE rows", len(rows), "->", OUTCSV)
