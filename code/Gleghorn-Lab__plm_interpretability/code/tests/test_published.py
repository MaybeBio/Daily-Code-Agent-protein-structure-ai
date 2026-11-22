"""The published-predictors figure: its rows, their names and their order."""

from __future__ import annotations

import pandas as pd

from pathlib import Path

from plm_interpretability import published
from plm_interpretability.figure_style import site_math


STATES = {"inside": ("mlp_up", 7), "stream": ("resid_post", 4), "last": ("final_norm", 0)}


def _summary() -> pd.DataFrame:
    """A tuned-probe summary with every row of the figure: this study's rows score lower down `published.ROWS`."""
    arms = []
    for rank, (model, kind, _) in enumerate(published.ROWS):
        site, layer = ("embedding", 0) if model in published.BASELINE_ENCODINGS else STATES.get(kind, ("q", 1))
        for probe, lead in (("mlp", 0.02), ("naive", 0.0), ("linear", 0.01)):
            score = 0.40 - 0.03 * rank + lead  # every bar and whisker stays short of the figure's value column
            arms.append({"task": "ppi", "model": model, "kind": kind, "site": site, "layer": layer, "probe": probe, "test_mcc": score - 0.1,
                         "test_roc_auc": score + 0.3, "test_average_precision": score + 0.3, "test.roc_auc_low": score + 0.29, "test.roc_auc_high": score + 0.31,
                         "test.average_precision_low": score + 0.29, "test.average_precision_high": score + 0.31})
    other_task = [{**arm, "task": "ppi2", "test_mcc": 0.9} for arm in arms]
    return pd.DataFrame(arms + other_task)


def test_each_method_has_its_bars_and_one_row() -> None:
    bars = published.table(_summary())
    counts = bars.groupby("label")["probe"].apply(sorted)
    for name in published.PUBLISHED:
        assert counts[name] == ["published"]
    ours = counts.drop(list(published.PUBLISHED))
    assert len(ours) == len(published.ROWS) and all(probes == ["mlp", "naive"] for probes in ours)
    assert bars.groupby("label")["row"].nunique().eq(1).all()
    assert sorted(bars["row"].unique()) == list(range(len(published.PUBLISHED) + len(published.ROWS)))


def test_a_row_names_its_state_except_a_baseline_encoding() -> None:
    labels = set(published.table(_summary())["label"])
    assert f"ESMC-6B {site_math('mlp_up')} 7" in labels
    assert f"ESMC-600 {site_math('final_norm')}" in labels  # the last hidden state has no block
    assert f"random init ESMC-300 {site_math('q')} 1" in labels
    assert {"one-hot", "random vectors"} <= labels


def test_rows_are_ordered_by_the_tuned_probe_and_the_published_mean() -> None:
    bars = published.table(_summary())
    leaders = bars[bars["probe"].isin(("mlp", "published"))].set_index("label")
    means = leaders[list(published.METRICS)].mean(axis=1).round(4)
    by_row = leaders["row"].sort_values().index
    assert means[by_row].is_monotonic_increasing
    assert by_row[-1] == f"ESMC-6B {site_math('mlp_up')} 7"
    # equal published means, at two decimals, are ordered by MCC
    assert leaders.loc["TUnA", "row"] > leaders.loc["C3PI", "row"] > leaders.loc["PLM-interact", "row"]


def test_write_all_draws_the_figure_and_its_table(tmp_path: Path) -> None:
    summary = tmp_path / "summary.parquet"
    _summary().to_parquet(summary)
    figure, plotted = published.write_all(summary, tmp_path / "out")
    assert figure.stat().st_size > 0
    table = pd.read_csv(plotted)
    assert "color" not in table.columns and len(table) == len(published.PUBLISHED) + 2 * len(published.ROWS)
