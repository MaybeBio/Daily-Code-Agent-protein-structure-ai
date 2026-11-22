from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from plm_interpretability.units import hypotheses


def _table(margin_center: float, held_out_center: float, n: int = 400, seed: int = 0, terms: int = 6) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    margin = rng.normal(margin_center, 0.02, n)  # (a,)
    held_out = rng.normal(held_out_center, 0.02, n)  # (a,)
    margin[:5] = np.nan  # poles without a testable term
    return pd.DataFrame({"pole": np.arange(n), "margin": margin, "held_out_auroc": held_out,
                         "best_term": rng.integers(0, terms, n)})


def test_h0_needs_more_associated_poles_and_better_concepts_at_most_cells() -> None:
    rng = np.random.default_rng(11)
    summary, per_concept = [], []
    for model, layers in (("esm2_8m", (1, 2, 3)), ("esm2_650m", (1, 9))):
        for layer in layers:
            better = not (model == "esm2_650m" and layer == 9)  # one of five cells goes the other way
            shares = {"residual": 0.02, "mlp_poles": 0.10 if better else 0.01, "sae": 0.2}
            summary.extend({"model": model, "layer": layer, "arm": arm, "share": share} for arm, share in shares.items())
            base = rng.random(60) * 0.5  # (c,)
            for arm, shift in (("residual", 0.0), ("mlp_poles", 0.1 if better else -0.1)):
                per_concept.extend({"model": model, "layer": layer, "arm": arm, "concept": f"c{index}",
                                    "best_test_f1": value + shift} for index, value in enumerate(base))
    decision = hypotheses.h0_mlp_over_residual(pd.DataFrame(summary), pd.DataFrame(per_concept))
    assert decision.passed and decision.details["won"] == 4 and decision.details["of"] == 5
    lost = [cell for cell in decision.details["cells"] if not cell["won"]]
    assert [(cell["model"], cell["layer"]) for cell in lost] == [("esm2_650m", 9)]
    assert lost[0]["median_f1_difference"]["estimate"] == pytest.approx(-0.1)


def test_h1_and_h3() -> None:
    native, residual = _table(0.10, 0.70, seed=1), _table(0.05, 0.60, seed=2)
    assert hypotheses.h1_native_over_residual(native, residual).passed
    assert not hypotheses.h1_native_over_residual(residual, native).passed
    sae_close, sae_far = _table(0.12, 0.71, seed=3), _table(0.20, 0.80, seed=4)
    assert hypotheses.h3_native_near_sae(native, sae_close).passed
    assert not hypotheses.h3_native_near_sae(native, sae_far).passed


def test_h2_and_h5_against_rotations() -> None:
    native = _table(0.10, 0.70, seed=5)
    rotations = [_table(0.05 + 0.001 * seed, 0.60, seed=10 + seed) for seed in range(10)]
    decision = hypotheses.h2_native_privileged(native, rotations)
    assert decision.passed and decision.details["margin"]["rank_p"] == pytest.approx(1 / 11)
    assert hypotheses.h5_generalization(native, rotations).passed
    equal = [_table(0.10, 0.70, seed=20 + seed) for seed in range(10)]
    assert not hypotheses.h2_native_privileged(native, equal).passed
    assert not hypotheses.h5_generalization(native, equal).passed


def test_h4_by_concept_kind() -> None:
    terms = pd.DataFrame({"token": range(6), "aspect": ["go_mf", "go_bp", "go_cc", "interpro", "keyword", "local_binding"]})
    kinds = hypotheses.concept_kind(terms, intrinsic_tokens=[6])
    assert kinds[0] == "function" and kinds[5] == "site" and kinds[6] == "composition"
    trained, random = _table(0.10, 0.7, seed=30), _table(0.03, 0.6, seed=31)
    decision = hypotheses.h4_pretraining(trained, random, kinds)
    untested = [kind for kind, detail in decision.details.items() if not detail["tested"]]
    assert set(untested) == {"structure", "domain"} and not decision.passed  # kinds no pole's best term has fail
    covered = {kind: detail["difference"]["low"] > 0 for kind, detail in decision.details.items() if detail["tested"]}
    assert all(covered.values()) and set(covered) == {"function", "process", "location", "family", "keyword", "site"}
    with pytest.raises(ValueError):
        hypotheses.concept_kind(pd.DataFrame({"token": [0], "aspect": ["unknown_aspect"]}))
    compendium_terms = pd.DataFrame({"token": [0, 1, 2], "aspect": ["local_region", "local_region", "taxonomy"],
                                     "fundamental_aspect": ["biophysical_assembly", "domain_family", "organism"],
                                     "unit": [0, 1, -1]})
    assert hypotheses.concept_kind(compendium_terms) == {0: "structure", 1: "domain"}  # disorder is structure; organism none


def _ablations(excess: float, tested: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = [{"pole": pole, "status": "tested", "drop": 0.2 + excess + rng.normal(0, 0.05),
             "placebo_drops": list(0.2 + rng.normal(0, 0.05, 10))} for pole in range(tested)]
    rows += [{"pole": tested + 1, "status": "too_few"}, {"pole": tested + 2, "status": "silent"}]
    return pd.DataFrame(rows)


def test_h6_reads_the_excess_over_placebos() -> None:
    used = hypotheses.h6_used(_ablations(0.1, 60))
    assert used.passed and used.details["statuses"] == {"tested": 60, "too_few": 1, "silent": 1}
    assert used.details["median_excess"]["low"] > 0
    assert not hypotheses.h6_used(_ablations(-0.1, 60)).passed
    too_few = hypotheses.h6_used(_ablations(0.1, hypotheses.MIN_LABELED_POLES - 1))
    assert not too_few.passed and "fewer than" in too_few.details["reason"]


def test_h7_needs_every_step_to_rise() -> None:
    small, medium, large = _table(0.05, 0.6, seed=40), _table(0.08, 0.6, seed=41), _table(0.11, 0.6, seed=42)
    assert hypotheses.h7_scale([("esmc_300", small), ("esmc_600", medium), ("esmc_6b", large)]).passed
    decision = hypotheses.h7_scale([("esmc_300", small), ("esmc_600", large), ("esmc_6b", medium)])
    assert not decision.passed and set(decision.details) == {"esmc_600_minus_esmc_300", "esmc_6b_minus_esmc_600"}
