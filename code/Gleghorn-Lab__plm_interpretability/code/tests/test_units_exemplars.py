"""Figure 4's exemplars: the frozen draw, the carriers chosen for each, and residue tracks against tested readings (CPU)."""

import numpy as np
import pandas as pd
import pytest
import torch

from torch import nn

from plm_interpretability.units import atlas, capture, exemplars, near_misses


CPU = torch.device("cpu")
UNITS = 256  # the tiny ESM++'s SwiGLU units


def test_draw_exemplars_takes_each_kinds_poles_with_the_seed() -> None:
    labeled = pd.DataFrame({"pole": [5, 1, 9, 3, 7, 11, 2], "term": [10, 10, 20, 20, 20, 30, 40]})
    kinds = {10: "site", 20: "structure", 30: "domain", 40: "composition"}
    drawn = exemplars.draw_exemplars(labeled, kinds)
    generator = np.random.default_rng(exemplars.SEED)
    site = np.array([1, 5])[np.sort(generator.choice(2, size=2, replace=False))]
    structure = np.array([3, 7, 9])[np.sort(generator.choice(3, size=2, replace=False))]
    assert drawn["kind"].tolist() == ["site", "site", "structure", "structure", "domain"]
    assert drawn["pole"].tolist() == [*site, *structure, 11]
    assert drawn["exemplar"].tolist() == list(range(5))
    shuffled = exemplars.draw_exemplars(labeled.sample(frac=1, random_state=0), kinds)
    pd.testing.assert_frame_equal(drawn, shuffled)  # the draw depends on the pool, not its order


def test_exemplar_carriers_rank_held_out_carriers_one_a_cluster() -> None:
    proteins = pd.DataFrame({
        "cluster": ["a", "a", "b", "c", "d", "e", "f"],
        "split": ["test", "test", "test", "train", "test", "test", "test"],
        "local_term_ids": [[10], [10], [10], [10], [10, 20], [20], [10]],
    })
    maxima = np.array([[0.9], [0.95], [0.5], [5.0], [0.7], [3.0], [0.1]])  # (n, p): one pole
    table = pd.DataFrame({"exemplar": [0, 1], "kind": ["site", "site"], "pole": [0, 0], "term": [10, 99]})
    carriers = exemplars.exemplar_carriers(table, proteins, maxima)
    assert set(carriers["exemplar"]) == {0}  # term 99 has no test carrier
    assert carriers.loc[carriers["role"] != "drawn", "row"].tolist() == [1, 4, 2]  # row 0 shares row 1's cluster
    assert carriers["role"].tolist() == ["top1", "top2", "top3", "drawn"]
    assert carriers.loc[carriers["role"] == "drawn", "row"].item() == [0, 6][np.random.default_rng(exemplars.SEED).integers(2)]
    np.testing.assert_allclose(carriers["maximum"], maxima[carriers["row"], 0])


def test_residue_tracks_match_the_tested_readings(tiny_esmc: nn.Module) -> None:
    generator = np.random.default_rng(3)
    sequences = ["".join(generator.choice(list("ACDEFGHIKLMNPQRSTVWY"), size=length)) for length in (20, 9)]
    units = [5, 200]
    tracks = exemplars.residue_tracks(tiny_esmc, 1, sequences, units, CPU)
    for sequence, unit, track in zip(sequences, units, tracks, strict=True):
        assert track.shape == (len(sequence), 4)
        main = near_misses.site_poles(tiny_esmc, 1, [sequence] * len(sequence), list(range(len(sequence))), CPU)  # (l, 2f)
        np.testing.assert_allclose(track[:, 0], main[:, unit].numpy(), atol=1e-5, rtol=1e-4)
        np.testing.assert_allclose(track[:, 1], main[:, UNITS + unit].numpy(), atol=1e-5, rtol=1e-4)
        read: list[torch.Tensor] = []
        input_ids, attention_mask, residues = atlas.encode_batch(tiny_esmc.tokenizer, [sequence], CPU)
        with capture.BlockReader(tiny_esmc, [1], lambda states: read.append(states.product()[:, unit])) as reader:
            reader.run(input_ids, attention_mask, residues)
        product = track[:, 0] - track[:, 1] + track[:, 2] - track[:, 3]  # (l,)
        np.testing.assert_allclose(product, read[0].numpy(), atol=1e-5, rtol=1e-4)
        assert (track >= 0).all() and ((track > 0).sum(axis=1) <= 1).all()  # one pole at a time
        assert (track[:, 2:] > 0).any()  # the leak is read, not dropped


def test_track_table_marks_the_term_and_the_threshold() -> None:
    proteins = pd.DataFrame({"accession": ["P1"], "sequence": ["ACDEFG"], "local_term_ids": [[10, 11]],
                             "local_starts": [[2, 1]], "local_ends": [[4, 6]]})
    pairs = pd.DataFrame({"exemplar": [0], "row": [0], "role": ["top1"], "maximum": [1.0], "kind": ["site"], "pole": [3],
                          "term": [10]})
    track = np.arange(24, dtype=np.float32).reshape(6, 4)  # (l, 4)
    table = exemplars.track_table(pairs, proteins, [track], np.array([0.0, 0.1, 0.2, 0.3]), units=2)
    assert table["in_term"].tolist() == [False, True, True, True, False, False]
    assert (table["threshold"] == 0.3).all() and (table["own"] == "negative").all()  # pole 3 of two units
    assert table["residue"].tolist() == list("ACDEFG") and table["position"].tolist() == [1, 2, 3, 4, 5, 6]
    np.testing.assert_array_equal(table["leak_negative"], track[:, 3])
    with pytest.raises(ValueError, match="does not cover"):
        exemplars.track_table(pairs, proteins, [track[:5]], np.zeros(4), units=2)
