"""
Phase 7 (part 2): Multi-seed benchmark + paired Wilcoxon tests.

For each seed in config['project']['seeds']:
  * build_splits(edges_path, seed) is called ONCE; the same split is reused for every
    model through with_features() -> matched pairs for the paired test.
Models: GCN Structure-only, GCN+ESM-2, GCN+Classical, RandomForest (Classical).
Outputs:
  results/multiseed_raw.csv      per-seed metrics
  results/multiseed_metrics.csv  mean +/- std
  results/wilcoxon_tests.csv     exact p-values
"""
import os
import itertools
import numpy as np
import pandas as pd
from scipy.stats import wilcoxon
from sklearn.ensemble import RandomForestClassifier

from utils import load_config, setup_logger, set_seed
from dataset import build_splits, with_features, make_random_features, load_node_features
from models import GCNModel
from train import run_experiment, get_device
from classical_ablation import run_sklearn_experiment

logger = setup_logger("multiseed")


def main():
    cfg = load_config("config.yaml")
    seeds = cfg["project"]["seeds"]
    device = get_device(cfg)
    proc, res = cfg["data"]["processed_dir"], cfg["data"]["results_dir"]
    edges_path = os.path.join(proc, "ppi_edges_uniprot.csv")
    h, do = cfg["training"]["hidden_dim"], cfg["training"]["dropout"]

    raw_path = os.path.join(res, "multiseed_raw.csv")
    rows = pd.read_csv(raw_path).to_dict("records") if os.path.exists(raw_path) else []  # resumable
    done = {(r["Seed"], r["Split"], r["Features"]) for r in rows}

    for seed in seeds:
        set_seed(seed)
        splits, node_to_idx, prots = build_splits(edges_path, seed)   # ONCE per seed
        feats = {
            "Structure Only": make_random_features(len(prots), 64, seed),
            "Sequence + Structure": load_node_features(os.path.join(proc, "esm2_embeddings.pt"), node_to_idx),
            "Classical + Structure": load_node_features(os.path.join(proc, "classical_features.pt"), node_to_idx),
        }
        for split_name, base in splits.items():
            for fname, x in feats.items():
                if (seed, split_name, fname) in done:
                    continue
                tr, va, te = with_features(base, x)
                set_seed(seed)  # identical init RNG state for every model
                m = run_experiment(GCNModel(x.size(1), h, do), tr, va, te, cfg, device,
                                   f"ms_{seed}_{fname}_{split_name}")
                m.update(Seed=seed, Split=split_name, Features=fname, Model="GCN")
                rows.append(m)
                pd.DataFrame(rows).to_csv(raw_path, index=False)
            # Random Forest on classical features (same split)
            if (seed, split_name, "Classical Sequence") not in done:
                tr, va, te = with_features(base, feats["Classical + Structure"])
                rf = RandomForestClassifier(n_estimators=50, max_depth=12, random_state=seed, n_jobs=-1)
                m = run_sklearn_experiment(rf, tr, te, f"ms_RF_{seed}_{split_name}")
                m.update(Seed=seed, Split=split_name, Features="Classical Sequence", Model="RandomForest")
                rows.append(m)
                pd.DataFrame(rows).to_csv(raw_path, index=False)

    df = pd.DataFrame(rows)
    # mean +/- std (sample std, ddof=1)
    g = df.groupby(["Model", "Features", "Split"])
    out = []
    for (mo, fe, sp), d in g:
        r = {"Model": mo, "Features": fe, "Split": sp, "n_seeds": len(d)}
        for c in ["AUC", "Precision", "Recall", "F1", "Precision@10"]:
            r[f"{c}_mean"], r[f"{c}_std"] = d[c].mean(), d[c].std(ddof=1)
            r[c] = f"{d[c].mean():.4f} ± {d[c].std(ddof=1):.4f}"
        out.append(r)
    pd.DataFrame(out).to_csv(os.path.join(res, "multiseed_metrics.csv"), index=False)

    # Paired Wilcoxon on test AUC (pairs matched by seed)
    tests = []
    comparisons = [("Structure Only", "Sequence + Structure"),
                   ("Structure Only", "Classical + Structure"),
                   ("Classical + Structure", "Sequence + Structure")]
    for split_name in df["Split"].unique():
        piv = df[df.Model == "GCN"].pivot_table(index="Seed", columns=["Split", "Features"], values="AUC")[split_name]
        for a, b in comparisons:
            d = (piv[b] - piv[a]).values
            two = wilcoxon(piv[b], piv[a], alternative="two-sided", method="exact")
            one = wilcoxon(piv[b], piv[a], alternative="greater", method="exact")
            tests.append({"Split": split_name, "A": a, "B": b, "n_pairs": len(d),
                          "mean_AUC_diff(B-A)": d.mean(), "B_wins": int((d > 0).sum()),
                          "W": two.statistic, "p_two_sided": two.pvalue, "p_one_sided(B>A)": one.pvalue})
    t = pd.DataFrame(tests)
    t.to_csv(os.path.join(res, "wilcoxon_tests.csv"), index=False)
    print(pd.DataFrame(out)[["Model", "Features", "Split", "AUC"]].to_string(index=False))
    print(t.to_string(index=False))
    n = len(seeds)
    logger.info(f"NOTE: with n={n} pairs the smallest attainable exact two-sided p is {2 / 2**n:.4f}.")


if __name__ == "__main__":
    main()
