"""Foldseek's composition-bias correction of a query: a per-position term added to every cell of that position.

Foldseek 10-941cd33 (`StructureSmithWaterman::ssw_init`, `--comp-bias-corr 1`, its default) calls MMseqs2's
`SubstitutionMatrix::calcLocalAaBiasCorrection` twice per query and adds both results to its query profile:

| Channel | Sequence read | Matrix and background | Scale |
|---|---|---|---|
| amino acids | the query's residues | BLOSUM62 at 1.4 bits (Foldseek's amino acid matrix) | 1 |
| 3Di | the query's 3Di states, read as amino acid letters (both alphabets are `ACDEFGHIKLMNPQRSTVWYX`) | the same amino acid matrix | 0.5 (`compBiasCorrectionScale`) |

At position i, with W the positions of a 40-wide window [i - 20, i + 20) clipped to the sequence, the term is
scale x (sum_a p_a s(q_i, a) - sum_{j in W, j != i} s(q_i, q_j) / |W|), in MMseqs's float arithmetic, rounded half
away from zero. A local window rich in what q_i scores well against makes the term negative. The reversed query of
Foldseek's reverse score gets its own terms, computed on the reversed strings (the window is not symmetric). Scores go
to `foundry.protein.gpu_alignment.align_profile_reference` and `align_profile_triton` as the bias.

Symbols: n sequences, l padded length, a matrix letters (21 with X).
"""

from __future__ import annotations

import numpy as np
import torch

from foundry.protein.alignment_scores import MATRICES, MMSEQS_ALIASES, mmseqs_matrix


WINDOW = 40  # `calcLocalAaBiasCorrection`'s windowSize
AMINO_BITS = 1.4  # Foldseek's amino acid matrix, as `alignment_scores.tables("foldseek")` builds it
SCALES = {"amino": 1.0, "three_di": 0.5}  # `ssw_init` passes 1.0 for amino acids, `compBiasCorrectionScale` for 3Di


def local_bias(indices: np.ndarray, matrix: np.ndarray, background: np.ndarray, scale: float) -> np.ndarray:
    """`calcLocalAaBiasCorrection` for one sequence of matrix indices (l), rounded as `ssw_init` rounds it: (l) int32.

    The float steps follow MMseqs's types: the window sum is an int, divided as a float by a double, then each
    background term added in double and stored back to float, and the scale multiplied in float."""
    # indices: (l); matrix: (a, a); background: (a)
    length = len(indices)
    position = np.arange(length)  # (l)
    low, high = np.maximum(0, position - WINDOW // 2), np.minimum(length, position + WINDOW // 2)  # (l)
    seen = np.zeros((length + 1, matrix.shape[0]), dtype=np.int64)  # (l + 1, a)
    seen[np.arange(1, length + 1), indices] = 1
    cumulative = np.cumsum(seen, axis=0)  # (l + 1, a)
    rows = matrix[indices].astype(np.int64)  # (l, a), s(q_i, .)
    window = ((cumulative[high] - cumulative[low]) * rows).sum(axis=1) - rows[position, indices]  # (l) int, own residue out
    delta = (window.astype(np.float32).astype(np.float64)
             / (-1.0 * (high - low).astype(np.float32).astype(np.float64))).astype(np.float32)  # (l)
    for letter in range(matrix.shape[0]):  # MMseqs adds the background terms one letter at a time
        delta = (delta.astype(np.float64) + background[letter] * rows[:, letter].astype(np.float32).astype(np.float64)).astype(np.float32)
    bias = (np.float32(scale) * delta).astype(np.float64)  # (l)
    return np.trunc(np.where(bias < 0.0, bias - 0.5, bias + 0.5)).astype(np.int32)  # (l)


def foldseek_query_bias(amino: list[str], three_di: list[str], length: int | None = None) -> torch.Tensor:
    """Foldseek's composition-bias correction of each query, both channels summed: (n, l) int32, zero past each
    query's length; `length` pads to a width (the longest query by default). Pass the reversed strings for the
    reverse score's terms."""
    alphabet, matrix, background = mmseqs_matrix(MATRICES / "blosum62.out", AMINO_BITS)
    lookup = np.full(256, -1, dtype=np.int64)  # (256), byte to matrix index
    lookup[np.frombuffer(alphabet.encode(), dtype=np.uint8)] = np.arange(len(alphabet))
    for letter, alias in MMSEQS_ALIASES.items():  # B, Z, J, U and O as MMseqs reads them
        lookup[ord(letter)] = alphabet.index(alias)
    width = max(len(text) for text in amino) if length is None else length
    out = torch.zeros(len(amino), width, dtype=torch.int32)  # (n, l)
    for row, (residues, states) in enumerate(zip(amino, three_di, strict=True)):
        if len(residues) != len(states):
            raise ValueError(f"Query {row} has {len(states)} 3Di states for {len(residues)} residues.")
        terms = np.zeros(len(residues), dtype=np.int32)  # (l_q)
        for text, channel in ((residues, "amino"), (states, "three_di")):
            indices = lookup[np.frombuffer(text.encode(), dtype=np.uint8)]  # (l_q)
            if (indices < 0).any():
                raise ValueError(f"Query {row} holds letters outside {alphabet!r}.")
            terms += local_bias(indices, matrix, background, SCALES[channel])
        out[row, : len(residues)] = torch.from_numpy(terms)
    return out  # (n, l)
