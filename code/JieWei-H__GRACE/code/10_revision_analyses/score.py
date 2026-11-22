# -*- coding: utf-8 -*-
"""Re-score a prediction pickle against the 3,837 CORUM reference complexes.

Usage:  python 10_revision_analyses/score.py [prediction.pkl]
Default target: 10.2_heldout_generalization/results/predictions/gen_noCL_5ep.pkl
"""
import csv, importlib.util, os, pickle, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
GOLD_CSV = os.path.join(ROOT, "data", "gold_complex.csv")
EVAL_PY = os.path.join(ROOT, "07_inference_evaluation", "Eval.py")
DEFAULT_PKL = os.path.join(HERE, "10.2_heldout_generalization", "results", "predictions", "gen_noCL_5ep.pkl")

sys.modules['__main__'].TokenIDGene = type('TokenIDGene', (), {})
spec = importlib.util.spec_from_file_location("E", EVAL_PY)
E = importlib.util.module_from_spec(spec); spec.loader.exec_module(E)

gold = []
with open(GOLD_CSV, encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        gold.append(frozenset(x.strip() for x in row["proteins"].split(",") if x.strip()))

path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PKL
raw = pickle.load(open(path, "rb"))
preds = [set(str(x["sft_response"]).split()) if isinstance(x, dict) else set(x) for x in raw]
n_all = len(preds)
preds = [p for p in preds if len(p) >= 2]
r = E.evaluate(gold, preds, threshold=0.2)
print("%s  n_gold=%d n_pred=%d P=%.4f R=%.4f F1=%.4f GMMR=%.4f MMMR=%.4f" % (
    os.path.basename(path), len(gold), len(preds),
    r["Precision"], r["Recall"], r["F1"], r["Global_MMR"], r["Mean_MMR"]))
