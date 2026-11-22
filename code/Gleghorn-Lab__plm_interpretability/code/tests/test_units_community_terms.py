"""The enrichment of curated terms at a community's predictions: the comparison stays within the community's residue,
shuffled communities and the atlas's own tokens are left out, and the p-value is Fisher's exact one (CPU)."""

import pandas as pd
import pytest

from scipy.stats import fisher_exact

from plm_interpretability.units import community_terms


INTRINSIC = 99  # a token of the atlas that is not a curated term
CURATED = {1, 2}


def prompts() -> pd.DataFrame:
    """Twelve predictions: eight of cysteine, of which the first three carry term 1, and four of alanine."""
    terms = [[1, 2, INTRINSIC], [1], [1], [], [], [2], [], [INTRINSIC], [1], [1], [], []]
    return pd.DataFrame({"predicted_residue": ["C"] * 8 + ["A"] * 4, "local_terms": terms})


def results() -> pd.DataFrame:
    """Community 7 explains the first three cysteines (one of them on two spans), community 9 one alanine, and a
    shuffled community a fourth cysteine."""
    rows = [(0, "discovered", 7, True), (0, "discovered", 7, True), (1, "discovered", 7, True),
            (2, "discovered", 7, True), (4, "discovered", 7, False), (3, "shuffled", 7, True),
            (8, "discovered", 9, True)]
    return pd.DataFrame(rows, columns=["prompt", "dictionary", "community", "explains"])


def test_explained_predictions_keep_one_row_a_prediction_of_discovered_communities() -> None:
    explained = community_terms.explained_predictions(results())
    assert sorted(map(tuple, explained.to_numpy().tolist())) == [(7, 0), (7, 1), (7, 2), (9, 8)]


def test_term_tests_compare_within_the_residue_by_fishers_exact_test() -> None:
    explained = community_terms.explained_predictions(results())
    table = community_terms.term_tests(prompts(), explained, CURATED).set_index(["community", "term"])
    assert INTRINSIC not in table.index.get_level_values("term")
    first = table.loc[(7, 1)]
    # The alanines that carry term 1 are not cysteines, so they are not among the others.
    assert (first["residue"], first["explained"], first["others"]) == ("C", 3, 5)
    assert (first["explained_with"], first["others_with"]) == (3, 0)
    assert first["p_value"] == pytest.approx(fisher_exact([[3, 0], [0, 5]], alternative="greater").pvalue)
    second = table.loc[(7, 2)]
    assert (second["explained_with"], second["others_with"]) == (1, 1)
    assert second["p_value"] == pytest.approx(fisher_exact([[1, 2], [1, 4]], alternative="greater").pvalue)
    alanine = table.loc[(9, 1)]
    assert (alanine["residue"], alanine["explained"], alanine["others"], alanine["explained_with"]) == ("A", 1, 3, 1)


def test_enrichment_table_orders_by_q_value_and_names_each_term() -> None:
    table = community_terms.enrichment_table(prompts(), results(), {1: "site: one", 2: "site: two"}, CURATED)
    assert table["q_value"].is_monotonic_increasing and (table["q_value"] >= table["p_value"]).all()
    assert table.loc[0, "label"] == "site: one" and table.loc[0, "explained_share"] == pytest.approx(1.0)
    assert len(community_terms.enrichment_table(prompts(), results(), {}, CURATED, communities=1)) == 2
