from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from torch import nn

from plm_interpretability.units import atlas, capture, near_misses, poles


CPU = torch.device("cpu")


@pytest.mark.parametrize(("note", "effect"), [
    ("Loss of activity.", "loss"),
    ("Abolishes kinase activity.", "loss"),
    ("No effect on activity.", "none"),
    ("No detectable effect on binding.", "none"),
    ("Does not affect localization.", "none"),
    ("Reduced activity.", None),
    ("Partial loss of activity.", None),
    ("Increases activity.", None),
    ("Abolishes interaction with X. No effect on localization.", None),
    ("Loss of activity; when associated with A-151.", None),
])
def test_effect_classes_keep_only_one_clear_effect(note: str, effect: str | None) -> None:
    assert near_misses.effect_class(note) == effect


def test_parse_mutagenesis_reads_single_residue_substitutions() -> None:
    field = ('MUTAGEN 5; /note="E->A: Loss of activity."; /evidence="ECO:0000269|PubMed:1"; '
             'MUTAGEN 11..14; /note="YPRK->AAAA: Abolishes binding."; MUTAGEN 20; /note="K->A,R: No effect on activity."; '
             'MUTAGEN 30; /note="H->A: Loss of activity; when associated with A-31."; MUTAGEN 40..60; /note="Missing: Loss."')
    found = near_misses.parse_mutagenesis(field)
    assert [(entry.position, entry.wild, entry.mutant, entry.effect) for entry in found] == [
        (5, "E", "A", "loss"), (20, "K", "A", "none"), (20, "K", "R", "none")]
    assert near_misses.parse_mutagenesis(float("nan")) == []


def _prepared() -> pd.DataFrame:
    return pd.DataFrame({
        "accession": ["P1", "P2", "P3"], "accessions": [["P1", "P1b"], ["P2"], ["P3"]], "cluster": ["c10", "c20", "c30"],
        "split": ["test", "train", "validation"], "sequence": ["MKTAYHEL", "MKKKKKKK", "ACDEFGHIK"],
        "local_term_ids": [np.array([7, 9]), np.array([7]), np.array([7, 7])],
        "local_starts": [np.array([2, 5]), np.array([1]), np.array([1, 7])],
        "local_ends": [np.array([4, 8]), np.array([8]), np.array([3, 9])],
    })


def test_held_out_substitutions_filter_and_count() -> None:
    entries = pd.DataFrame({"Entry": ["P1", "P2", "P3", "Q9", "P1b"], "Mutagenesis": [
        'MUTAGEN 2; /note="K->A: Loss of activity."; MUTAGEN 3; /note="W->A: No effect on activity."; '
        'MUTAGEN 20; /note="K->A: Loss of activity."',
        'MUTAGEN 2; /note="K->A: Loss of activity."',
        'MUTAGEN 6; /note="G->A: No effect on activity."',
        'MUTAGEN 1; /note="M->A: Loss of activity."',
        'MUTAGEN 4; /note="A->G: No effect on activity."']})
    table, counts = near_misses.held_out_substitutions(entries, _prepared())
    assert counts == {"classified": 7, "not_pooled": 1, "training_split": 1, "beyond_sequence": 1, "wild_mismatch": 1, "kept": 3}
    assert table[["accession", "cluster", "site", "wild", "mutant", "effect"]].values.tolist() == [
        ["P1", "c10", 1, "K", "A", "loss"], ["P3", "c30", 5, "G", "A", "none"], ["P1b", "c10", 3, "A", "G", "none"]]
    shared = _prepared().assign(accessions=[["P1"], ["P1"], ["P3"]])
    with pytest.raises(ValueError, match="two proteins"):
        near_misses.held_out_substitutions(entries, shared)


def test_covering_poles_follow_the_term_intervals() -> None:
    substitutions = pd.DataFrame({"row": [0, 0, 2, 2], "site": [1, 6, 0, 5]})
    labeled = pd.DataFrame({"pole": [3, 4, 8], "term": [7, 7, 9]})
    covering = near_misses.covering_poles(substitutions, _prepared(), labeled)
    # P1: term 7 spans residues 2-4 (sites 1-3), term 9 spans 5-8 (sites 4-7); P3: term 7 spans sites 0-2 and 6-8
    assert [entry.tolist() for entry in covering] == [[3, 4], [8], [3, 4], []]


def _brute_force(drops: np.ndarray, loss: np.ndarray, strata: np.ndarray, weights: np.ndarray) -> float:
    # drops, loss, strata, weights: (m,)
    wins = pairs = 0.0
    for first in np.flatnonzero(loss):
        for second in np.flatnonzero(~loss):
            if strata[first] == strata[second]:
                weight = weights[first] * weights[second]
                pairs += weight
                wins += weight * (1.0 if drops[first] > drops[second] else 0.5 if drops[first] == drops[second] else 0.0)
    return wins / pairs


def test_stratified_auroc_counts_pairs_within_strata() -> None:
    generator = np.random.default_rng(3)
    drops = np.round(generator.normal(size=60), 1)  # (m,), with ties
    loss = generator.random(60) < 0.5  # (m,)
    strata = generator.integers(0, 4, 60).astype(str)  # (m,)
    weights = generator.integers(0, 3, 60).astype(float)  # (m,)
    assert near_misses.stratified_auroc(drops, loss, strata, weights) == pytest.approx(_brute_force(drops, loss, strata, weights))
    assert np.isnan(near_misses.stratified_auroc(drops[:3], np.array([True, True, False]), np.array(["a", "a", "b"])))


def test_near_miss_table_and_summary_separate_labeled_from_placebo_poles() -> None:
    generator = np.random.default_rng(5)
    count, width = 80, 40
    effects = np.where(np.arange(count) % 2 == 0, "loss", "none")  # (m,)
    substitutions = pd.DataFrame({"accession": [f"P{index}" for index in range(count)], "cluster": np.arange(count) // 2,
                                  "wild": "H", "mutant": "A", "effect": effects})
    wild = torch.tensor(generator.uniform(0.5, 2.0, (count, width)), dtype=torch.float32)  # (m, p)
    kept = torch.tensor(generator.uniform(0.2, 0.8, (count, width)), dtype=torch.float32)  # (m, p), every pole keeps a share
    loses = torch.from_numpy(effects == "loss")[:, None] & (torch.arange(width) < 2)[None, :]  # (m, p): poles 0 and 1 track function
    mutant = torch.where(loses, torch.zeros_like(wild), wild * kept)  # (m, p)
    wild[0, :2] = 0.0  # the first substitution's covering poles are silent in the wild type
    covering = [np.array([0, 1]) for _ in range(count)]
    table = near_misses.near_miss_table(substitutions, covering, wild, mutant)
    assert table["status"].iloc[0] == "silent" and (table["status"].iloc[1:] == "tested").all()
    assert table["labeled_drop"].iloc[2] == pytest.approx(1.0) and (table["placebos"].iloc[1:] > 0).all()
    summary = near_misses.near_miss_summary(table, draws=200)
    assert summary["tested"] == {"loss": count // 2 - 1, "none": count // 2} and summary["strata_with_both"] == 1
    assert summary["labeled_auroc"]["estimate"] == pytest.approx(1.0)
    assert 0.3 < summary["placebo_auroc"]["estimate"] < 0.7 and summary["difference"]["low"] > 0
    with pytest.raises(ValueError, match="covering poles"):
        near_misses.near_miss_table(substitutions, covering[:-1], wild, mutant)


def test_site_poles_read_each_sequence_at_its_site(tiny_esmc: nn.Module) -> None:
    generator = np.random.default_rng(7)
    sequences = ["".join(generator.choice(list("ACDEFGHIKLMNPQRSTVWY"), size=length)) for length in (30, 12, 25, 8)]
    sites = [29, 0, 11, 7]
    batched = near_misses.site_poles(tiny_esmc, 1, sequences, sites, CPU, token_budget=64)  # (m, p): several batches
    for index, (sequence, site) in enumerate(zip(sequences, sites, strict=True)):
        read: list[torch.Tensor] = []
        input_ids, attention_mask, residues = atlas.encode_batch(tiny_esmc.tokenizer, [sequence], CPU)
        with capture.BlockReader(tiny_esmc, [1], lambda states: read.append(poles.swiglu_poles(states.gate, states.up).main())) as reader:
            reader.run(input_ids, attention_mask, residues)
        torch.testing.assert_close(batched[index], read[0][site], atol=1e-5, rtol=1e-4)
