"""Pooling gains and their difference between probe kinds, from interval tables in the layout Protify writes."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pathlib import Path

from plm_interpretability.pooling_study import gains_table, pooling_table, ranking_table, rows_of, size_correlations


LIFTS = {"linear": 0.01, "linear_mean": 0.0, "mlp": 0.05, "mlp_mean": 0.0, "linear_solver": 0.02, "linear_mean_solver": 0.015,
         "bottleneck_mean": 0.03}
SIZES = {"go_cc": 11409, "interpro_repeat": 819, "prot_param": 12747, "interpro_family": 2097}


def interval_table(task: str, labels: list[str], noise: np.ndarray) -> pd.DataFrame:
    """The whole split's value is the label's lift exactly; each draw adds the task's noise, shared by every label."""
    # noise: (B,) one draw per resample
    rows = []
    for label in labels:
        for choice in ("stream", "any"):
            for metric in ("score", "roc_auc", "balanced_mcc"):
                values = [0.5 + LIFTS[label]] + ([] if metric == "balanced_mcc" else list(0.5 + LIFTS[label] + noise))
                rows += [{"task": task, "label": label, "choice": choice, "probe_name": "resid_post:3", "metric": metric,
                          "draw": draw - 1, "value": value} for draw, value in enumerate(values)]
    return pd.DataFrame(rows)


def write_tables(root: Path, conditions: tuple[str, ...], decomposition: bool = False) -> Path:
    generator = np.random.default_rng(24895)
    kinds = (("intervals", ["linear", "linear_mean", "mlp", "mlp_mean"]), ("solver", ["linear_solver", "linear_mean_solver"]))
    if decomposition:  # the variants' run rescores the labels it is compared with
        kinds += (("decomposition", ["linear_mean", "mlp_mean", "bottleneck_mean"]),)
    for condition in conditions:
        for task in SIZES:
            noise = generator.normal(0.0, 0.01, size=200)
            for kind, labels in kinds:
                folder = root / condition / kind
                folder.mkdir(parents=True, exist_ok=True)
                interval_table(task, labels, noise).to_parquet(folder / f"{task}.parquet", index=False)
            pd.DataFrame({"root": ["x"]}).to_parquet(root / condition / "solver" / f"{task}_fits.parquet", index=False)
    return root


def test_gains_and_their_difference_from_shared_draws(tmp_path: Path) -> None:
    gains = gains_table(write_tables(tmp_path, ("esmc300_norm",)), SIZES)
    mean = gains[gains["task"] == "mean"]
    for quantity, expected in (("gain_linear", 0.01), ("gain_mlp", 0.05), ("gain_linear_solver", 0.005), ("interaction", 0.04),
                               ("interaction_solver", 0.045), ("mlp_lead_mean_var", 0.04), ("mlp_lead_solver", 0.03), ("score_mlp", 0.55)):
        row = rows_of(mean, "esmc300_norm", "any", quantity).iloc[0]
        assert row["estimate"] == pytest.approx(expected, abs=1e-12)
        if quantity.startswith("score_"):
            assert row["low"] < row["estimate"] < row["high"]  # the draws' shared noise gives a score an interval
        else:
            # every label of a task shares its draws' noise, so a difference has no spread at all
            assert row["low"] == pytest.approx(expected, abs=1e-12) and row["high"] == pytest.approx(expected, abs=1e-12)
    assert set(mean["tasks"]) == {len(SIZES)}
    per_task = rows_of(gains, "esmc300_norm", "stream", "interaction")
    assert dict(zip(per_task["task"], per_task["train_size"], strict=True))["interpro_repeat"] == 819
    balanced = rows_of(mean, "esmc300_norm", "any", "score_mlp", metric="balanced_mcc").iloc[0]
    assert balanced["estimate"] == pytest.approx(0.55) and np.isnan(balanced["low"])  # the whole split alone


def test_table_lists_each_model_and_treatment(tmp_path: Path) -> None:
    gains = gains_table(write_tables(tmp_path, ("esmc300_norm", "esmc6b_norm", "esmc300_raw", "canon6b_raw")), SIZES)
    table = pooling_table(gains, "any")
    lines = [line for line in table.splitlines() if line.startswith(("ESMC", "Random"))]
    assert [line.split(" & ")[:2] for line in lines] == [["ESMC-300", "unit-norm"], ["ESMC-6B", "unit-norm"], ["ESMC-300", "raw"]]
    cells = lines[0].removesuffix(r" \\").split(" & ")
    assert cells[5] == "0.550"  # a score without its interval
    assert cells[9] == r"\begin{tabular}[t]{@{}c@{}}$+$0.040 \\ {\scriptsize ($+$0.040, $+$0.040)}\end{tabular}"
    assert size_correlations(gains).empty  # every task's difference is the same here, so no correlation is defined
    ranking = [line for line in ranking_table(gains, "any").splitlines() if " linear " in line or " MLP " in line]
    assert [line.split(" & ")[:2] for line in ranking] == [["ESMC-300", "linear"], ["", "MLP"], ["ESMC-6B", "linear"], ["", "MLP"]]  # one name per model
    # ROC AUC and balanced MCC under the mean alone and under mean and variance; this table has no average precision
    assert ranking[1].split(" & ")[2:4] == ["0.500", "0.550"] and ranking[0].split(" & ")[4:6] == ["--", "--"]


def test_decomposition_rescores_are_kept_once_and_must_agree(tmp_path: Path) -> None:
    write_tables(tmp_path, ("esmc600_norm",), decomposition=True)
    for path in (tmp_path / "esmc600_norm").glob("[!s]*/*.parquet"):  # balanced MCC's draws are NaN in Protify's tables
        table = pd.read_parquet(path)
        whole = table[table["metric"] == "balanced_mcc"]
        extra = [whole.assign(draw=draw, value=np.nan) for draw in range(200)]
        pd.concat([table, *extra], ignore_index=True).to_parquet(path, index=False)
    gains = gains_table(tmp_path, SIZES)
    mean = gains[gains["task"] == "mean"]
    for quantity, expected in (("score_bottleneck_mean", 0.53), ("score_linear_mean", 0.5), ("mlp_lead_mean", 0.0)):
        assert rows_of(mean, "esmc600_norm", "any", quantity).iloc[0]["estimate"] == pytest.approx(expected, abs=1e-12)
    path = tmp_path / "esmc600_norm" / "decomposition" / "go_cc.parquet"
    table = pd.read_parquet(path)
    table.loc[table["label"] == "linear_mean", "value"] += 0.001
    table.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="differ from the interval tables"):
        gains_table(tmp_path, SIZES)
