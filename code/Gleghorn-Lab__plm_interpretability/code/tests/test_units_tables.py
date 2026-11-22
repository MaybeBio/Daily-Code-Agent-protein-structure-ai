"""The study's tables: every decision the run took becomes a row, read from details the hypothesis functions write, and
E11 and the missing-annotation correction become supplementary tables (CPU)."""

import json
import numpy as np
import pandas as pd
import pytest

from plm_interpretability.units import experiments, hypotheses, missing, payoff, tables


def _scores(margin: float, auroc: float, *, seed: int, n: int = 300, terms: int = 6) -> pd.DataFrame:
    generator = np.random.default_rng(seed)
    return pd.DataFrame({"pole": np.arange(n), "margin": generator.normal(margin, 0.02, n),
                         "held_out_auroc": generator.normal(auroc, 0.02, n), "best_term": generator.integers(0, terms, n)})


def _taken(name: str, site: str, decision: hypotheses.Decision) -> dict[str, object]:
    """A decision as the script's `analyze` stage writes it to `decisions.json`."""
    return json.loads(json.dumps({"hypothesis": name, "site": site, "taken": True, "passed": decision.passed,
                                  "details": decision.details}))


def _decisions() -> list[dict[str, object]]:
    native, residual, sae = _scores(0.10, 0.70, seed=1), _scores(0.05, 0.60, seed=2), _scores(0.11, 0.71, seed=3)
    rotations = [_scores(0.05, 0.60, seed=10 + seed) for seed in range(10)]
    kinds = {0: "site", 1: "site", 2: "structure", 3: "function", 4: "function", 5: "domain"}
    ablations = pd.DataFrame({"status": ["tested"] * 25 + ["silent"], "drop": [0.05] * 25 + [np.nan],
                              "placebo_drops": [[0.01, 0.02]] * 25 + [None]})
    return [
        _taken("H1", "esmc_600", hypotheses.h1_native_over_residual(native, residual)),
        _taken("H2", "esmc_600", hypotheses.h2_native_privileged(native, rotations)),
        _taken("H3", "esmc_600", hypotheses.h3_native_near_sae(native, sae)),
        _taken("H5", "esmc_600", hypotheses.h5_generalization(native, rotations)),
        _taken("H3_sign", "esmc_600", hypotheses.h3_native_near_sae(native, sae)),
        {"hypothesis": "H2_sign", "site": "esmc_6b", "taken": False, "rejected_matches": ["block59/sign@x"]},
        _taken("H4", "esmc_600", hypotheses.h4_pretraining(native, residual, kinds, min_poles=40)),
        _taken("H7", "three models", hypotheses.h7_scale([("esmc_300", residual), ("esmc_600", native), ("esmc_6b", sae)])),
        _taken("H6", "esmc_600 block 26", hypotheses.h6_used(ablations)),
        {"hypothesis": "H0", "site": "ESM-2", "taken": False, "reason": "E1 has not run on both models"},
    ]


def test_decision_rows_print_every_decision_from_its_details() -> None:
    decisions = _decisions()
    inherited = [_taken("H3", "esmc_6b", hypotheses.h3_native_near_sae(_scores(0.1, 0.7, seed=5), _scores(0.1, 0.7, seed=6)))]
    rows = tables.decision_rows(decisions, inherited)
    assert [row.hypothesis for row in rows] == ["H1", "H2", "H2", "H3", "H5", "H3", "H2", "H4", "H7", "H7", "H6", "H0",
                                                "H3, inherited labels"]
    h2 = [row for row in rows if row.hypothesis == "H2" and row.reading == "gate-tagged"]
    assert [row.quantity for row in h2] == ["median margin, native against the ten rotations",
                                            "median held-out AUROC, native against the ten rotations"]
    assert h2[0].outcome == "passed" and h2[0].site == "ESMC-600, block 26"
    signed = rows[5]
    assert (signed.reading, signed.outcome) == ("sign-only", "passed")
    rejected = rows[6]
    assert (rejected.reading, rejected.quantity, rejected.outcome) == ("sign-only", "rate match rejected", "not taken")
    generalization = decisions[3]["details"]
    difference = generalization["median_difference"]
    assert rows[4].estimate == f"{tables._number(difference, tables._decimals(difference))}, {tables._p(generalization['p_value'])}"
    by_kind = decisions[6]["details"]
    tested = [kind_test for kind_test in by_kind.values() if kind_test["tested"]]
    above = sum(kind_test["difference"]["low"] > 0 for kind_test in tested)
    assert rows[7].estimate == f"{above} of {len(tested)} tested; {len(by_kind) - len(tested)} with too few poles"
    assert 0 < len(tested) < len(by_kind)  # both kinds of kind are exercised
    assert rows[7].site == "ESMC-600, every block"  # e5_600 plans all 36 blocks, which H4 pools
    assert tables._site("H4", "esmc_6b") == "ESMC-6B, block 59"
    assert rows[8].quantity == "median margin, ESMC-600 minus ESMC-300"
    assert rows[10].quantity == "median drop minus placebos' mean drop, 25 poles tested" and rows[10].outcome == "passed"
    assert rows[10].site == "ESMC-600, block 26"  # the run names it "esmc_600 block 26", which LaTeX cannot set
    assert tables._site("H7", "three_models") == r"three\_models"
    assert (rows[11].quantity, rows[11].outcome) == ("E1 has not run on both models", "not taken")
    assert rows[12].site == "ESMC-6B, block 59"
    body = tables.decision_table(rows)
    assert body.count(r" \\") == len(rows) + 1  # the header and one line a row
    assert body.count(r"\addlinespace") == sum(first.hypothesis != second.hypothesis
                                               for first, second in zip(rows[:-1], rows[1:], strict=True))


def test_p_values_switch_to_scientific_notation() -> None:
    assert tables._p(0.0312) == "$p = 0.031$"
    assert tables._p(3.2e-5) == r"$p = 3.2 \times 10^{-5}$"


def test_payoff_table_reports_every_metric_by_model() -> None:
    generator = np.random.default_rng(0)
    prints = [("extremes", "native"), ("extremes", "rotation0"), ("mean", "native"), ("mean", "rotation0"), ("sae", "native")]
    table = pd.DataFrame([{"task": "go", "target": f"t{target}", "features": features, "basis": basis,
                           "pr_auc": generator.random(), "roc_auc": generator.random(), "balanced_mcc": generator.random()}
                          for target in range(12) for features, basis in prints])
    summary = payoff.payoff_summary(table)
    body = tables.payoff_table({"esmc_600": summary, "esmc_6b": summary})
    assert body.count("PR AUC") == body.count("ROC AUC") == body.count("balanced MCC") == 2 * 3
    assert body.count("ESMC-600") == 1 and body.count(r"\midrule") == 2
    first = summary.iloc[0]
    assert tables._interval({"estimate": first.difference, "low": first.low, "high": first.high}) in body
    assert body.count(r"\addlinespace") == 2 * 2  # between the three metrics, in each model's block


def test_numbers_take_a_true_minus_sign() -> None:
    assert tables._number(-0.0114) == "$-$0.011" and tables._number(0.5, 2) == "0.50"
    assert tables._interval({"estimate": -0.011, "low": -0.014, "high": 0.008}) == "$-$0.011 [$-$0.014, 0.008]"


def test_decision_numbers_keep_near_ceiling_differences_apart() -> None:
    assert tables._interval({"estimate": 0.00001, "low": -0.00004, "high": 0.00007}) == "0.00001 [$-$0.00004, 0.00007]"
    assert tables._decimals(0.99867, 0.99837, 0.99885) == 4 and tables._decimals(0.5) == 3
    assert tables._decimals(0.0014759) == 4  # a lone number keeps two significant digits
    assert tables._decimals(0.00031, 0.000005, 0.0013) == 6 == tables._decimals(1e-9)  # at most six
    assert tables._decimals(float("nan")) == 3


def test_inheritance_table_orders_bases_and_names_other_references() -> None:
    _, block, reference = experiments.HYPOTHESIS_SITES["esmc_600"]
    keys = experiments.site_keys(block, reference)
    others = [f"block{block}/native@esmc_600_layer27_k64_16384", f"block{block}/sae:esmc_600_layer27_k64_16384"]
    frame = pd.DataFrame({"auroc_before": [0.6, np.nan], "auroc_after": [0.7, 0.8], "precision_before": [0.1, np.nan],
                          "precision_after": [0.2, 0.3], "prevalence_before": [0.05, np.nan], "prevalence_after": [0.06, 0.07],
                          "rescored": [True, True]})
    summary = missing.missing_summary({key: frame for key in (*keys.rotated[::-1], keys.sae, *others, keys.residual, keys.native)})
    body = tables.inheritance_table({"sites": {"esmc_600": {"bases": summary}}})
    names = [line.split(" & ")[1] for line in body.splitlines() if line.count(" & ") == 5][1:]
    assert names == ["native, gate-tagged", "native, gate-tagged, at 16,384-latent rates",
                     *(f"rotation {seed}" for seed in range(10)),
                     "residual stream", "SAE", "SAE, 16,384 latents"]
    assert "0.600 & 0.700 & 0.100, 0.200" in body and body.count("ESMC-600, block 26") == 1


def test_sae_labels_table_reports_labels_and_both_arms() -> None:
    interval = {"estimate": 0.62, "low": 0.6, "high": 0.64, "units": 900}
    labels = {"latents": 16384, "with_testable_term": 16000, "best_auroc": interval, "global_labeled": 12000,
              "held_out_auroc": interval, "held_out_auroc_labeled": None, "precision_before": interval,
              "prevalence_before": interval, "precision_after": interval, "prevalence_after": interval, "local_labels": 52000,
              "with_local_label": 9000, "median_local_labels": 3.0, "with_release_local_label": 8800, "dominant": 410,
              "dominant_share": 0.025}
    arm = {"included": 15000, "mean_matched_win_probability": 0.71234, "one_sided_permutation_p": 1 / 1001,
           "mean_semantic_excess": 0.0213, "mean_excess_feature_bootstrap_95ci": [0.02, 0.0226]}
    body = tables.sae_labels_table({"labels": labels, "agreement": {"arms": {"global": arm, "local": {"included": 0}}}})
    assert r"16,000 of 16,384 \\" in body and r"The same, latents reaching 0.6 & -- \\" in body
    assert r"0.7123 of 15,000 latents, $p = 1.0 \times 10^{-3}$ \\" in body and "0.0213 [0.0200, 0.0226]" in body
    assert r"Matched win probability, local representatives & -- \\" in body


def test_write_tables_writes_what_the_run_holds(tmp_path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    (root / "decisions.json").write_text(json.dumps(_decisions()), encoding="utf-8")
    written = tables.write_tables(root, root / "tables")
    assert [path.name for path in written] == ["decisions.tex"]  # no E11 summaries or missing receipt yet
    with pytest.raises(FileNotFoundError):
        tables.write_tables(tmp_path / "empty", tmp_path / "empty" / "tables")
