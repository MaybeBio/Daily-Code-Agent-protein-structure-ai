"""Paired tests, by concept, of the neurons' poles against each random rotation at three quarters of each stack.

    python -m plm_interpretability.units.paired_rotations --root RUN --out TABLE.csv

Reads the `retest_esmc` folder of the neuron study's archive. Each of its per-concept tables gives, for every concept
and arm, the test F1 of the concept's best unit, chosen on validation. For each rotation of a model, a two-sided
Wilcoxon signed-rank test compares that F1 under the neurons' poles with the one under the rotation, paired by concept,
over the concepts scored under both. Holm's correction runs over every rotation of every model. The test was added
after the residue-level comparison and is not among the study's rules fixed in advance.

Symbols: c concepts; t tests (one a rotation).
"""

from __future__ import annotations

import argparse
import numpy as np
import pandas as pd

from pathlib import Path
from scipy.stats import wilcoxon


NEURONS = "mlp_poles"
ROTATION_PREFIX = "mlp_rotation"
CONCEPTS = 636  # InterPLM's concepts without the 20 of amino-acid identity
# Each model's run with the most rotations at its three-quarter block: the folder under `retest_esmc`, and the block.
SOURCES = {"ESMC-300": ("esmc_300", 22), "ESMC-600": ("esmc_600_rotations", 26), "ESMC-6B": ("esmc_6b_rotations", 59)}
COLUMNS = ("model", "block", "rotation", "pairs", "neurons_higher", "median_difference", "p_value")


def holm(p_values: np.ndarray) -> np.ndarray:
    """Holm's step-down adjusted p-values, in the order given."""
    # p_values: (t,)
    order = np.argsort(p_values, kind="stable")  # (t,)
    scaled = (len(p_values) - np.arange(len(p_values))) * p_values[order]  # (t,)
    adjusted = np.empty(len(p_values), dtype=np.float64)  # (t,)
    adjusted[order] = np.minimum(np.maximum.accumulate(scaled), 1.0)
    return adjusted  # (t,)


def rotation_tests(per_concept: pd.DataFrame, model: str, block: int) -> pd.DataFrame:
    """One row a rotation of one model: the concepts scored under both bases, how many the neurons score higher on,
    the median paired difference in test F1 (neurons minus rotation) and the signed-rank test's p-value."""
    at_block = per_concept[per_concept["layer"] == block]
    scores = at_block.pivot(index="concept", columns="arm", values="best_test_f1")  # (c, arms)
    assert len(scores) == CONCEPTS, f"{model}: {len(scores)} concepts at block {block}, expected {CONCEPTS}."
    rotations = sorted(arm for arm in scores.columns if arm.startswith(ROTATION_PREFIX))
    assert NEURONS in scores.columns and rotations, f"{model}: block {block} lacks the neurons' poles or a rotation."
    neurons = scores[NEURONS].to_numpy(dtype=np.float64)  # (c,)
    rows = []
    for arm in rotations:
        rotation = scores[arm].to_numpy(dtype=np.float64)  # (c,)
        scored = ~np.isnan(neurons) & ~np.isnan(rotation)  # (c,): a best unit was scored under both bases
        difference = neurons[scored] - rotation[scored]  # (pairs,)
        p_value = float(wilcoxon(neurons[scored], rotation[scored], alternative="two-sided").pvalue)
        rows.append((model, block, arm, int(scored.sum()), int((difference > 0).sum()), float(np.median(difference)), p_value))
    return pd.DataFrame(rows, columns=list(COLUMNS))


def paired_table(root: Path) -> pd.DataFrame:
    """Every rotation of every model, with Holm's correction over all of them."""
    tables = [rotation_tests(pd.read_parquet(root / "retest_esmc" / folder / "e13_per_concept.parquet"), model, block)
              for model, (folder, block) in SOURCES.items()]
    tests = pd.concat(tables, ignore_index=True)
    tests["p_holm"] = holm(tests["p_value"].to_numpy(dtype=np.float64))
    return tests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True, help="a copy of the neuron study's archive")
    parser.add_argument("--out", type=Path, required=True, help="the CSV of one row a rotation")
    args = parser.parse_args()
    tests = paired_table(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tests.to_csv(args.out, index=False, float_format="%.6g")
    for model, group in tests.groupby("model", sort=False):
        print(f"{model}: {len(group)} rotations, {group['pairs'].min()} to {group['pairs'].max()} concepts, median difference "
              f"{group['median_difference'].min():.3f} to {group['median_difference'].max():.3f}, largest corrected p "
              f"{group['p_holm'].max():.3g}")


if __name__ == "__main__":
    main()
