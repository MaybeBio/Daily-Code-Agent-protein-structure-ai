"""Exemplar tracks of chosen poles on InterPLM's evaluation: the chosen poles' F1 against E13's full report, the carrier
rule, and the track table (CPU)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from collections.abc import Iterator
from torch import nn

from plm_interpretability.units import concept_exemplars, retest
from test_units_retest import _proteins


BLOCK = 2
BUDGET = 80
DOMAIN_LEVEL = np.array([False, True, True])
NAMES = ("Helix", "Domain_a", "Region_b")


def _shards(seed: int) -> list[retest.RetestShard]:
    rng = np.random.default_rng(seed)
    shards = []
    for split, label_seed in (("valid", 7), ("test", 8), ("test", 9)):
        sequences = tuple("".join(rng.choice(list("ACDEFGHIKLMNPQRSTVWY"), size=int(length)))
                          for length in rng.integers(8, 30, size=6))
        shards.append(retest.RetestShard(split, sequences, _proteins(label_seed, [len(sequence) for sequence in sequences], DOMAIN_LEVEL)))
    return shards


def _concepts(shards: list[retest.RetestShard]) -> retest.ConceptSet:
    positives, domains = {}, {}
    for split in retest.SPLITS:
        labels = sp.vstack([shard.labels for shard in shards if shard.split == split]).toarray()  # (n, C)
        positives[split] = (labels > 0).sum(axis=0)
        domains[split] = np.array([len(np.unique(np.concatenate([np.unique(shard.labels[:, concept].data)
                                                                  for shard in shards if shard.split == split])))
                                   for concept in range(len(NAMES))])
    return retest.ConceptSet(NAMES, DOMAIN_LEVEL, positives, domains)


def test_chosen_poles_give_e13_s_counts_and_test_f1(tiny_esmc: nn.Module) -> None:
    shards = _shards(6)
    concepts = _concepts(shards)

    def stream(arms: tuple[str, ...] | None = None, seeds: tuple[int, ...] = retest.ROTATION_SEEDS) -> Iterator[retest.RetestBatch]:
        return retest.stream_esmc_arms(tiny_esmc, None, (BLOCK,), shards, {}, device="cpu", token_budget=BUDGET,
                                       rotation_seeds=seeds, arms=arms)

    full = retest.collect_counts(stream(), shards, retest.collect_ranges(stream()), concepts)  # E13, every arm
    _, per_concept = retest.retest_tables(full, concepts)
    native = per_concept[per_concept["arm"] == "mlp_native"]
    chosen = native[(native["best_feature"] >= 0) & np.isfinite(native["best_test_f1"])]
    assert len(chosen) >= 2
    choices = concept_exemplars.read_choices(pd.DataFrame({"model": "tiny", "concept": chosen["concept"],
                                                           "feature": chosen["best_feature"]}), concepts, "tiny")
    store = concept_exemplars.collect_chosen(stream(("mlp_native",), ()), shards, choices["feature"].tolist())
    ranges = concept_exemplars.chosen_ranges(store, BLOCK)
    counts = concept_exemplars.chosen_counts(store, shards, ranges, concepts, BLOCK, token_budget=BUDGET)
    columns = choices["feature"].to_numpy()  # (k,)
    for split in retest.SPLITS:
        reference = full[BLOCK, "mlp_native", split]
        np.testing.assert_array_equal(counts[split].positive.numpy(), reference.positive.numpy()[:, columns])
        np.testing.assert_array_equal(counts[split].domains.numpy(), reference.domains.numpy()[:, columns])
        np.testing.assert_array_equal(counts[split].fired.numpy(), reference.fired.numpy()[columns])
    scores = concept_exemplars.pole_scores(counts, concepts, choices)
    assert concept_exemplars.check_archived(scores, per_concept, BLOCK) == 0.0
    assert set(scores["valid_threshold"]) <= set(retest.THRESHOLDS)
    wrong = scores.assign(test_f1=scores["test_f1"] + 1e-6)
    with pytest.raises(ValueError, match="test F1"):
        concept_exemplars.check_archived(wrong, per_concept, BLOCK)
    with pytest.raises(ValueError, match="best pole"):
        concept_exemplars.check_archived(scores.assign(feature=scores["feature"] + 1), per_concept, BLOCK)


def test_collect_chosen_refuses_a_partial_pass(tiny_esmc: nn.Module) -> None:
    shards = _shards(11)
    batches = retest.stream_esmc_arms(tiny_esmc, None, (BLOCK,), shards, {}, device="cpu", token_budget=BUDGET,
                                      rotation_seeds=(), arms=("mlp_native",), batches=lambda plan: plan[:2])
    with pytest.raises(ValueError, match="did not read"):
        concept_exemplars.collect_chosen(batches, shards, [0, 3])


def test_read_choices_checks_the_model_and_the_concepts() -> None:
    concepts = retest.ConceptSet(NAMES, DOMAIN_LEVEL, {}, {})
    frame = pd.DataFrame({"model": ["m", "m"], "concept": ["Region_b", "Helix"], "feature": [4, 1]})
    chosen = concept_exemplars.read_choices(frame, concepts, "m")
    assert chosen["concept_index"].tolist() == [2, 0] and chosen["feature"].tolist() == [4, 1]
    with pytest.raises(ValueError, match="must be of"):
        concept_exemplars.read_choices(frame.assign(model=["m", "other"]), concepts, "m")
    with pytest.raises(ValueError, match="not in the evaluation"):
        concept_exemplars.read_choices(frame.assign(concept=["Region_b", "Motif_x"]), concepts, "m")
    with pytest.raises(ValueError, match="chosen twice"):
        concept_exemplars.read_choices(frame.assign(concept=["Helix", "Helix"]), concepts, "m")


def test_protein_maxima_and_carriers_follow_the_label_rows() -> None:
    lengths = [3, 2, 4]
    values = np.arange(18, dtype=np.float32).reshape(9, 2)  # (n, k)
    np.testing.assert_array_equal(concept_exemplars.protein_maxima(values, lengths), values[[2, 4, 8]])
    labels = sp.csr_matrix(np.array([[0, 0], [0, 1], [0, 0], [0, 0], [0, 0], [2, 0], [0, 0], [0, 3], [0, 0]]))  # (n, C)
    assert concept_exemplars.concept_carriers(labels, lengths, 0).tolist() == [False, False, True]
    assert concept_exemplars.concept_carriers(labels, lengths, 1).tolist() == [True, False, True]
    with pytest.raises(ValueError, match="rows for"):
        concept_exemplars.concept_carriers(labels, [3, 2], 0)


def test_choose_carriers_takes_the_strongest_then_random_carriers_and_a_negative() -> None:
    carries = np.array([True, True, True, False, True, True, True, False, True])  # (p,)
    maxima = np.array([5.0, 9.0, 7.0, 99.0, 9.0, 1.0, 2.0, 50.0, 3.0])  # (p,)
    sequences = ["AA", "CC", "DD", "EE", "CC", "FF", "GG", "HH", "II"]  # protein 4 repeats protein 1
    chosen = concept_exemplars.choose_carriers(2, carries, maxima, sequences)
    assert chosen["role"].tolist() == list(concept_exemplars.ROLES)
    assert chosen["protein"].tolist()[:3] == [1, 2, 0]  # 4 ties 1 but repeats its sequence
    generator = np.random.default_rng(concept_exemplars.SEED + 2)
    drawn = generator.choice(np.array([4, 5, 6, 8]), size=3, replace=False).tolist()
    negative = [3, 7][generator.integers(2)]
    assert chosen["protein"].tolist()[3:] == [*drawn, negative]
    np.testing.assert_array_equal(chosen["maximum"], maxima[chosen["protein"]])
    few = concept_exemplars.choose_carriers(0, carries & (maxima >= 7), maxima, sequences)  # carriers 1, 2 and 4
    assert few["role"].tolist() == ["top1", "top2", "drawn1", "negative"] and few["protein"].tolist()[:3] == [1, 2, 4]
    with pytest.raises(ValueError, match="no test carrier"):
        concept_exemplars.choose_carriers(0, np.zeros(9, dtype=bool), maxima, sequences)


def test_track_table_marks_the_concept_and_checks_the_maxima() -> None:
    sequences, accessions = ["ACDE", "FGH"], ["P1", "P2"]
    labels = sp.csr_matrix(np.array([[0, 0], [0, 4], [0, 4], [1, 0], [0, 0], [0, 0], [0, 0]]))  # (n, C)
    offsets = np.array([0, 4, 7])
    pairs = pd.DataFrame({"exemplar": [0, 0], "protein": [0, 1], "role": ["top1", "negative"], "kind": "Domain",
                          "feature": [5, 5], "concept": "Domain_a", "concept_index": 1, "threshold": 0.4,
                          "valid_f1": 0.7, "test_f1": 0.6, "maximum": [3.0, 1.0]})
    tracks = [np.array([[0, 3.0, 0, 0], [0, 2.0, 0, 0], [0, 1.0, 0, 0], [0, 0, 0.1, 0]], dtype=np.float32),
              np.array([[0, 0.9, 0, 0], [0, 0, 0, 0.2], [0, 0.5, 0, 0]], dtype=np.float32)]  # (l, 4) each
    table = concept_exemplars.concept_track_table(pairs, sequences, accessions, labels, offsets, tracks, units=4)
    assert table["in_term"].tolist() == [False, True, True, False, False, False, False]
    assert (table["own"] == "negative").all() and (table["term"] == 1).all()  # feature 5 of four units
    assert table["accession"].tolist() == ["P1"] * 4 + ["P2"] * 3 and table["position"].tolist() == [1, 2, 3, 4, 1, 2, 3]
    assert concept_exemplars.track_maxima_difference(pairs, tracks, 4) == pytest.approx(0.1)
    with pytest.raises(ValueError, match="does not cover"):
        concept_exemplars.concept_track_table(pairs, sequences, accessions, labels, offsets, [tracks[0], tracks[1][:2]], 4)
