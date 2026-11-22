"""The review's two readings of the survey: onsets under smoother definitions, and the validation-chosen stream state
against the query or key state (CPU)."""

import numpy as np
import pandas as pd

from plm_interpretability import survey_checks


DEPTHS = np.linspace(0, 1, 6)  # (d,)


def test_onset_is_the_first_depth_within_five_percent_of_the_highest() -> None:
    scores = np.array([0.1, 0.96, 0.5, 0.97, 1.0, 0.99])  # (d,)
    assert survey_checks.onset(scores, DEPTHS) == DEPTHS[1]


def test_running_mean_averages_three_depths_and_two_at_the_ends() -> None:
    scores = np.array([0.0, 3.0, 6.0, 3.0])  # (d,)
    np.testing.assert_allclose(survey_checks.running_mean(scores), [1.5, 3.0, 4.0, 4.5])


def test_a_single_high_depth_does_not_set_the_persistent_onset() -> None:
    scores = np.array([0.1, 0.96, 0.5, 0.97, 1.0, 0.99])  # (d,)
    assert survey_checks.persistent_onset(scores, DEPTHS) == DEPTHS[3]
    lone = np.array([0.1, 1.0, 0.2, 0.3, 0.2, 0.1])  # (d,): only its highest depth is within 5%
    assert np.isnan(survey_checks.persistent_onset(lone, DEPTHS))


def summary() -> pd.DataFrame:
    """One model's probes of two tasks: the stream reads the residue task best and the keys read the pooled one."""
    rows = [("functional_sites", "resid_post", 3, 0.60, 0.61), ("functional_sites", "resid_post", 4, 0.70, 0.58),
            ("functional_sites", "q", 3, 0.55, 0.59), ("functional_sites", "k", 2, 0.50, 0.66),
            ("interpro_binding_site", "embedding", 0, 0.40, 0.45), ("interpro_binding_site", "final_norm", 0, 0.62, 0.60),
            ("interpro_binding_site", "k", 5, 0.90, 0.88), ("interpro_binding_site", "mlp_up", 5, 0.99, 0.99)]
    table = pd.DataFrame(rows, columns=["task", "site", "layer", "validation_score", "full"])
    return table.assign(plm="trained", probe="trained", control="original", family="full")


def test_site_table_chooses_each_state_on_validation(monkeypatch) -> None:
    monkeypatch.setattr(survey_checks, "RESIDUE_TASKS", ("functional_sites",))
    monkeypatch.setattr(survey_checks, "POOLED_TASKS", ("interpro_binding_site",))
    table = survey_checks.site_table({"ESMC-300": summary()}).set_index("task")
    residue, pooled = table.loc["functional_sites"], table.loc["interpro_binding_site"]
    # The stream's block 4 has the higher validation score, so its lower test score is the one reported.
    assert (residue["stream_block"], residue["stream_score"], residue["projection_site"]) == (4, 0.58, "q")
    assert (pooled["stream_site"], pooled["projection_site"], pooled["projection_score"]) == ("final_norm", "k", 0.88)


def test_stream_curve_orders_the_embedding_the_blocks_and_the_final_norm() -> None:
    rows = [("task", "final_norm", 0, 0.5), ("task", "resid_post", 1, 0.4), ("task", "embedding", 0, 0.1),
            ("task", "resid_post", 0, 0.3), ("task", "q", 0, 0.9)]
    table = pd.DataFrame(rows, columns=["task", "site", "layer", "full"])
    table = table.assign(plm="trained", probe="trained", control="original", family="full")
    curve = survey_checks.stream_curve(table, "task", blocks=2)
    assert curve["full"].tolist() == [0.1, 0.3, 0.4, 0.5]
    np.testing.assert_allclose(curve["relative_depth"], [0, 1 / 3, 2 / 3, 1])
