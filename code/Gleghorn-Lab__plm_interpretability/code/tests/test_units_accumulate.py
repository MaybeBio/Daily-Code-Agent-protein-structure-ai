from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from annotation_vocabulary.study.association import local_metrics, local_statistics

from plm_interpretability.units import accumulate
from plm_interpretability.units.intrinsic import AMINO_ACIDS


N_POLES = 12
TERM_TOKENS = np.array([101, 205, 307, 409, 511])  # the study's token ids, not columns


def _sequence(rng: np.random.Generator, length: int) -> str:
    return "".join(rng.choice(list(AMINO_ACIDS), size=length))


def _synthetic_batch(seed: int, n_proteins: int) -> tuple[list[str], list[accumulate.LocalRuns], torch.Tensor]:
    """Proteins with sparse nonnegative activations and local annotations, some whole-protein and some overlapping."""
    rng = np.random.default_rng(seed)
    lengths = rng.integers(15, 60, size=n_proteins).tolist()
    annotations = []
    for length in lengths:
        tokens, starts, ends = [], [], []
        for _ in range(rng.integers(0, 6)):
            token = int(rng.choice(np.append(TERM_TOKENS, 999)))  # 999 lies outside the endpoint list
            start = int(rng.integers(1, length + 1))
            end = int(rng.integers(start, length + 3))  # some intervals run past the observed length
            tokens.append(token)
            starts.append(start)
            ends.append(end)
        if rng.random() < 0.2:
            tokens.append(int(TERM_TOKENS[0]))
            starts.append(1)
            ends.append(length)  # covers the whole protein: never informative
        annotations.append(accumulate.LocalRuns.positives(tokens, starts, ends))
    values = rng.exponential(size=(sum(lengths), N_POLES)) * (rng.random((sum(lengths), N_POLES)) < 0.15)  # (r, p)
    values[: lengths[0], 3] = 0.0  # a unit silent in a whole protein still counts with zero contrast
    return [_sequence(rng, length) for length in lengths], annotations, torch.from_numpy(values)  # values (r, p)


def _reference(sequences: list[str], annotations: list[accumulate.LocalRuns], values: torch.Tensor) -> dict[str, np.ndarray]:
    """The atlas study's own computation, with every pole stored as a TopK slot."""
    # values: (r, p)
    proteins = pd.DataFrame({
        "local_term_ids": [runs.tokens for runs in annotations],
        "local_starts": [runs.starts for runs in annotations],
        "local_ends": [runs.ends for runs in annotations],
    })
    lengths = [len(sequence) for sequence in sequences]
    n_residues = values.shape[0]
    features = np.tile(np.arange(N_POLES), (n_residues, 1))  # (r, k)
    offsets = np.concatenate(([0], np.cumsum(lengths)[:-1]))  # (n,)
    return local_statistics(proteins, features, values.numpy(), offsets, np.array(lengths), np.arange(N_POLES),
                            TERM_TOKENS)  # each statistic (p, t) or (t,)


def _owner(sequences: list[str]) -> torch.Tensor:
    return accumulate.protein_index([len(sequence) for sequence in sequences])  # (r,)


def test_accumulator_matches_the_atlas_study_over_batches() -> None:
    batches = [_synthetic_batch(seed, n_proteins) for seed, n_proteins in ((0, 30), (1, 25), (2, 40))]
    columns = {int(token): column for column, token in enumerate(TERM_TOKENS)}
    accumulator = accumulate.LocalAccumulator(len(TERM_TOKENS), N_POLES)
    for sequences, annotations, values in batches:
        accumulator.update(values, _owner(sequences), accumulate.local_pairs(sequences, annotations, columns))
    ours = accumulator.study_sums()
    sequences = sum((batch[0] for batch in batches), [])
    annotations = sum((batch[1] for batch in batches), [])
    values = torch.cat([batch[2] for batch in batches])
    reference = _reference(sequences, annotations, values)
    for key in (*accumulate.SUM_KEYS, "n_informative", "inside_exposure", "outside_exposure"):
        np.testing.assert_allclose(ours[key], reference[key], rtol=1e-12, atol=1e-12, err_msg=key)
    ours_metrics, reference_metrics = local_metrics(ours), local_metrics(reference)
    for key in ("local_p", "mean_difference", "local_enrichment", "pooled_residue_enrichment"):
        np.testing.assert_allclose(ours_metrics[key], reference_metrics[key], rtol=1e-10, equal_nan=True, err_msg=key)


def _masked_batch(seed: int, n_proteins: int) -> tuple[list[str], list[accumulate.LocalRuns], torch.Tensor]:
    """Chain-scoped terms 101 and 205 with masked runs, and a site term 307 on serine with masked serines."""
    rng = np.random.default_rng(seed)
    sequences, annotations = [], []
    for _ in range(n_proteins):
        sequence = _sequence(rng, int(rng.integers(20, 50)))
        serines = [index + 1 for index, letter in enumerate(sequence) if letter == "S"]
        tokens, starts, ends, hidden, hidden_starts, hidden_ends = [], [], [], [], [], []
        for token in (101, 205):
            start = int(rng.integers(1, len(sequence) - 4))
            tokens.append(token)
            starts.append(start)
            ends.append(start + int(rng.integers(0, 4)))
            first = int(rng.integers(1, len(sequence) - 2))
            hidden.append(token)
            hidden_starts.append(first)
            hidden_ends.append(first + 2)  # may overlap the positive run, which wins
        if len(serines) >= 3:
            chosen = rng.choice(serines, size=2, replace=False)
            tokens.append(307)
            starts.append(int(chosen[0]))
            ends.append(int(chosen[0]))
            hidden.append(307)
            hidden_starts.append(int(chosen[1]))
            hidden_ends.append(int(chosen[1]))
        sequences.append(sequence)
        annotations.append(accumulate.LocalRuns(*(np.asarray(values, dtype=np.int64) for values in
                                                  (tokens, starts, ends, hidden, hidden_starts, hidden_ends))))
    values = rng.exponential(size=(sum(map(len, sequences)), N_POLES)) * (rng.random((sum(map(len, sequences)), N_POLES)) < 0.3)
    return sequences, annotations, torch.from_numpy(values)  # values (r, p)


def _brute_force(sequences: list[str], annotations: list[accumulate.LocalRuns], values: torch.Tensor,
                 columns: dict[int, int], scopes: dict[int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per (pole, term), the summed contrast, its count and the outside exposure, residue by residue."""
    # values: (r, p)
    total = np.zeros((N_POLES, len(columns)))  # (p, t)
    count = np.zeros(len(columns), dtype=np.int64)  # (t,)
    exposure = np.zeros(len(columns), dtype=np.int64)  # (t,)
    fires = values.numpy() > 0  # (r, p)
    offset = 0
    for sequence, runs in zip(sequences, annotations, strict=True):
        length = len(sequence)
        for token, column in columns.items():
            inside = {position - 1 for start, end, held in zip(runs.starts, runs.ends, runs.tokens, strict=True) if held == token
                      for position in range(start, min(end, length) + 1)}
            if not inside:
                continue
            masked = {position - 1 for start, end, held in zip(runs.masked_starts, runs.masked_ends, runs.masked_tokens, strict=True)
                      if held == token for position in range(start, min(end, length) + 1)} - inside
            scope = set(range(length)) if token not in scopes else {index for index, letter in enumerate(sequence)
                                                                     if letter == AMINO_ACIDS[scopes[token]]}
            outside = sorted(scope - inside - masked)
            if not outside:
                continue
            block = fires[offset:offset + length]  # (l, p)
            total[:, column] += block[sorted(inside)].mean(axis=0) - block[outside].mean(axis=0)
            count[column] += 1
            exposure[column] += len(outside)
        offset += length
    return total, count, exposure  # (p, t), (t,), (t,)


def test_masked_residues_and_scopes_against_brute_force() -> None:
    columns, scopes = {101: 0, 205: 1, 307: 2}, {307: AMINO_ACIDS.index("S")}
    accumulator = accumulate.LocalAccumulator(len(columns), N_POLES, chunk=5)
    batches = [_masked_batch(seed, 25) for seed in (6, 7)]
    for sequences, annotations, values in batches:
        accumulator.update(values, _owner(sequences), accumulate.local_pairs(sequences, annotations, columns, scopes))
    sums = accumulator.study_sums()
    sequences = sum((batch[0] for batch in batches), [])
    annotations = sum((batch[1] for batch in batches), [])
    total, count, exposure = _brute_force(sequences, annotations, torch.cat([batch[2] for batch in batches]), columns, scopes)
    assert count[2] > 0  # the site term is exercised
    np.testing.assert_allclose(sums["sum_difference"], total, rtol=1e-12, atol=1e-12)
    np.testing.assert_array_equal(sums["n_informative"], count)
    np.testing.assert_array_equal(sums["outside_exposure"], exposure)


def test_a_site_off_its_amino_acid_raises() -> None:
    runs = accumulate.LocalRuns.positives([307], [1], [1])
    with pytest.raises(ValueError):
        accumulate.local_pairs(["ASSS"], [runs], {307: 0}, {307: AMINO_ACIDS.index("S")})


def test_chunks_and_kept_keys_change_nothing() -> None:
    sequences, annotations, values = _synthetic_batch(3, 35)
    columns = {int(token): column for column, token in enumerate(TERM_TOKENS)}
    pairs = accumulate.local_pairs(sequences, annotations, columns)
    owner = _owner(sequences)
    whole = accumulate.LocalAccumulator(len(TERM_TOKENS), N_POLES)
    whole.update(values, owner, pairs)
    chunked = accumulate.LocalAccumulator(len(TERM_TOKENS), N_POLES, keys=("sum_difference", "n_active"), chunk=5)
    chunked.update(values, owner, pairs, n_proteins=len(sequences))
    expected, ours = whole.study_sums(), chunked.study_sums()
    assert set(ours) == {"sum_difference", "n_active", "n_informative", "inside_exposure", "outside_exposure"}
    for key in ours:
        np.testing.assert_array_equal(ours[key], expected[key], err_msg=key)


def test_state_round_trip_resumes_exactly() -> None:
    columns = {int(token): column for column, token in enumerate(TERM_TOKENS)}
    batches = [_synthetic_batch(seed, 20) for seed in (4, 5)]
    straight = accumulate.LocalAccumulator(len(TERM_TOKENS), N_POLES, dtype=torch.float32, keys=("sum_difference",))
    for sequences, annotations, values in batches:
        straight.update(values, _owner(sequences), accumulate.local_pairs(sequences, annotations, columns))
    first = accumulate.LocalAccumulator(len(TERM_TOKENS), N_POLES, dtype=torch.float32, keys=("sum_difference",))
    sequences, annotations, values = batches[0]
    first.update(values, _owner(sequences), accumulate.local_pairs(sequences, annotations, columns))
    resumed = accumulate.LocalAccumulator(len(TERM_TOKENS), N_POLES, dtype=torch.float32, keys=("sum_difference",))
    resumed.load_state_dict(first.state_dict())
    sequences, annotations, values = batches[1]
    resumed.update(values, _owner(sequences), accumulate.local_pairs(sequences, annotations, columns))
    for key, array in straight.study_sums().items():
        np.testing.assert_array_equal(resumed.study_sums()[key], array, err_msg=key)
    with pytest.raises(ValueError):
        accumulate.LocalAccumulator(len(TERM_TOKENS), N_POLES).load_state_dict(first.state_dict())


def test_pairs_skip_whole_protein_and_unlisted_terms() -> None:
    annotations = [accumulate.LocalRuns.positives([101, 999], [1, 2], [10, 3]),
                   accumulate.LocalRuns.positives([205, 205], [1, 4], [2, 5])]
    pairs = accumulate.local_pairs(["A" * 10, "A" * 8], annotations, {101: 0, 205: 1})
    # Protein 0's term 101 covers it entirely; 999 is unlisted; protein 1's two 205 intervals merge into one pair.
    assert pairs.size == 1
    assert pairs.protein.tolist() == [1] and pairs.term.tolist() == [1] and pairs.scope.tolist() == [accumulate.CHAIN]
    assert pairs.inside_length.tolist() == [4.0] and pairs.outside_length.tolist() == [4.0]
    assert pairs.inside_residue.tolist() == [10, 11, 13, 14]
    assert pairs.residue_kind.tolist() == [AMINO_ACIDS.index("A")] * 18


def test_protein_maxima_are_per_protein() -> None:
    values = torch.tensor([[1.0, 0.0], [3.0, 2.0], [0.5, 4.0]])  # (r, p)
    maxima = accumulate.protein_maxima(values, accumulate.protein_index([2, 1]), 2)  # (n, p)
    assert maxima.tolist() == [[3.0, 2.0], [0.5, 4.0]]


def test_mismatched_poles_raise() -> None:
    accumulator = accumulate.LocalAccumulator(2, 3)
    pairs = accumulate.local_pairs(["AAAA"], [accumulate.LocalRuns.positives([7], [1], [2])], {7: 0})
    with pytest.raises(ValueError):
        accumulator.update(torch.ones(4, 5), accumulate.protein_index([4]), pairs)
