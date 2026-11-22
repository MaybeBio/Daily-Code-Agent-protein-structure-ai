"""Probe correctness against PPLL, from synthetic per-protein outputs in the layout the familiarity experiment writes."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pathlib import Path

from plm_interpretability.familiarity import bootstrap, correlations, kind_readings, partial_spearman, proteins_table, quintile_table, spearman


TASKS = {"interpro_family": 200, "go_bp": 160, "localization": 120, "prot_param": 150}


def write_outputs(root: Path, familiar_gain: bool) -> Path:
    """Three seeds of every encoder. The trained model's score rises with PPLL; with `familiar_gain` the controls'
    do not, so the gain tracks PPLL, and without it every encoder's does, so the gain does not."""
    generator = np.random.default_rng(24895)
    sequences = {task: [f"{task[:2]}{index:04d}" + "A" * int(generator.integers(50, 900)) for index in range(count)] for task, count in TASKS.items()}
    ppll = {sequence: float(generator.normal(-2.0, 0.3)) for proteins in sequences.values() for sequence in proteins}
    prevalence = {sequence: float(generator.uniform(0.01, 0.5)) for proteins in sequences.values() for sequence in proteins}
    for encoder in ("esmc300", "random300", "onehot"):
        rows = []
        for task, proteins in sequences.items():
            for seed in (24895, 24896, 24897):
                for index, sequence in enumerate(proteins):
                    familiar = ppll[sequence] + 2.0  # centered PPLL
                    trend = familiar if encoder == "esmc300" or not familiar_gain else 0.0
                    score = 0.5 + 0.4 * trend + generator.normal(0.0, 0.05)
                    rows.append({"task": task, "kind": "multilabel", "seed": seed, "protein": index, "id": f"P{index}", "sequence": sequence,
                                 "length": len(sequence), "probe_name": "resid_post:3", "score": score,
                                 "prevalence": np.nan if task == "prot_param" else prevalence[sequence],
                                 "logits": np.zeros(3, dtype=np.float32)})
        folder = root / encoder
        folder.mkdir(parents=True)
        pd.DataFrame(rows).to_parquet(folder / "predictions.parquet", index=False)
    table = pd.DataFrame({"sequence": list(ppll), "length": [len(sequence) for sequence in ppll], "ppll": list(ppll.values())})
    table.to_parquet(root / "esmc300" / "ppll.parquet", index=False)
    return root


def test_partial_spearman_removes_a_shared_covariate() -> None:
    generator = np.random.default_rng(0)
    length = generator.normal(size=2000)
    x = length + 0.3 * generator.normal(size=2000)
    y = length + 0.3 * generator.normal(size=2000)
    assert spearman(x, y) > 0.8
    assert abs(partial_spearman(x, y, length[:, None])) < 0.08


def test_bootstrap_interval_brackets_the_whole_sample() -> None:
    generator = np.random.default_rng(1)
    x = generator.normal(size=300)
    y = x + generator.normal(size=300)
    low, high = bootstrap(lambda rows: spearman(x[rows], y[rows]), 300, draws=200)
    assert low < spearman(x, y) < high


@pytest.mark.parametrize("familiar_gain", [True, False])
def test_kind_reading_follows_whether_the_gain_tracks_ppll(tmp_path: Path, familiar_gain: bool) -> None:
    proteins = proteins_table(write_outputs(tmp_path, familiar_gain))
    assert len(proteins) == sum(TASKS.values())
    correlation = correlations(proteins, draws=100)
    readings = kind_readings(correlation).set_index("kind")
    gain = correlation[(correlation["quantity"] == "gain") & (correlation["encoder"] == "random300") & correlation["partial"]].set_index("task")
    trained = correlation[(correlation["quantity"] == "score") & (correlation["encoder"] == "trained") & ~correlation["partial"]].set_index("task")
    assert (trained["rho"] > 0.8).all()
    if familiar_gain:
        assert (gain["rho"] > 0.8).all()
        assert readings["familiarity_driven_random300"].all()
    else:
        assert (gain["rho"].abs() < 0.3).all()
        assert not readings["familiarity_driven_random300"].any()


def test_quintiles_split_each_task_evenly(tmp_path: Path) -> None:
    quintiles = quintile_table(proteins_table(write_outputs(tmp_path, True)))
    counts = quintiles.groupby("task")["proteins"].agg(["min", "max"])
    assert ((counts["max"] - counts["min"]) <= 1).all()
    increasing = quintiles[quintiles["task"] == "go_bp"].sort_values("quintile")["score_trained"].to_numpy()
    assert (np.diff(increasing) > 0).all()
