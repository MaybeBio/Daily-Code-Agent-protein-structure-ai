from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from plm_interpretability.units import sae_labels


def test_descriptions_and_documents_follow_version_one() -> None:
    table = pd.DataFrame({"feature_id": [2, 0, 1], "summary": [" Binds zinc. ", "", "Kinase"],
                          "activation_pattern": ["", " ", "On the loop."], "category": ["Domain", "Disorder", None]})
    described = sae_labels.descriptions(table)
    assert described["feature_id"].tolist() == [2, 1]  # a latent with no text is left out
    assert described["semantic_text"].tolist() == ["Binds zinc.", "Kinase\nOn the loop."]
    assert sae_labels.term_documents(["zinc", "kinase"], ["A metal.", None]) == ["zinc. A metal.", "kinase"]


def test_representatives_follow_the_frozen_rule() -> None:
    scores = pd.DataFrame({"pole": range(4), "best_term": [3, 5, -1, 7], "best_auroc": [0.7, 0.59, np.nan, 0.6]})
    labels = pd.DataFrame({"pole": [0, 0, 1, 1, 3], "term": [11, 12, 12, 40, 41], "mean_difference": [0.2, 0.5, 0.3, 0.9, 0.4]})
    chosen = sae_labels.representatives(scores, labels, vocabulary_size=30)
    assert chosen["global"].tolist() == [3, -1, -1, 7]
    assert chosen["local"].tolist() == [12, 12, -1, -1]  # an intrinsic token, past the vocabulary, is never one
    with pytest.raises(ValueError, match="pole order"):
        sae_labels.representatives(scores.iloc[::-1], labels, vocabulary_size=30)


def test_agreement_finds_matching_descriptions() -> None:
    rng = np.random.default_rng(4)
    n, n_terms = 80, 40
    documents = sae_labels.term_documents([f"concept{index} protein" for index in range(n_terms)],
                                          [f"definition of concept{index}" for index in range(n_terms)])
    tokens = rng.integers(0, n_terms, n)  # (f,)
    described = pd.DataFrame({"feature_id": np.arange(n), "category": rng.choice(["Domain", "Repeat"], n),
                              "semantic_text": [f"This latent fires on concept{token} sites in many proteins" for token in tokens]})
    chosen = pd.DataFrame({"feature_id": np.arange(n), "global": tokens,
                           "local": np.where(np.arange(n) % 4 == 0, -1, (tokens + 1) % n_terms)})
    frame, summary = sae_labels.agreement(described, chosen, documents, permutations=200, bootstrap_replicates=100)
    global_arm, local_arm = summary["arms"]["global"], summary["arms"]["local"]
    assert global_arm["included"] == n and global_arm["mean_matched_win_probability"] > 0.9
    assert global_arm["one_sided_permutation_p"] == pytest.approx(1 / 201)
    assert local_arm["included"] == n - n // 4  # latents without a representative stay as controls only
    assert 0.3 < local_arm["mean_matched_win_probability"] < 0.55  # another concept's term scores near chance
    assert set(frame["arm"]) == {"global", "local"} and len(frame) == 2 * n


def test_label_summary_counts_and_medians() -> None:
    scores = pd.DataFrame({"pole": range(6), "best_term": [1, 2, 3, -1, 4, 5], "best_auroc": [0.8, 0.65, 0.55, np.nan, 0.9, 0.61],
                           "held_out_auroc": [0.7, np.nan, 0.5, np.nan, 0.8, 0.6],
                           "dominant": [True, False, False, False, True, False]})
    labels = pd.DataFrame({"pole": [0, 0, 1, 4], "term": [10, 40, 11, 12], "mean_difference": [0.1, 0.2, 0.3, 0.4]})
    inheritance = pd.DataFrame({"precision_before": [0.1, 0.2, np.nan], "precision_after": [0.2, 0.3, np.nan],
                                "prevalence_before": [0.01, 0.02, 0.03], "prevalence_after": [0.02, 0.03, 0.04]})
    summary = sae_labels.label_summary(scores, labels, inheritance, vocabulary_size=30)
    assert summary["global_labeled"] == 4 and summary["with_testable_term"] == 5
    assert summary["held_out_auroc"]["estimate"] == pytest.approx(0.65) and summary["held_out_auroc_labeled"]["units"] == 3
    assert summary["with_local_label"] == 3 and summary["with_release_local_label"] == 3 and summary["median_local_labels"] == 1
    assert summary["precision_before"]["estimate"] == pytest.approx(0.15) and summary["dominant_share"] == pytest.approx(2 / 6)
