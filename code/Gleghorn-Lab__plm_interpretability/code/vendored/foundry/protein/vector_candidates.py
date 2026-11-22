"""The candidate list a one-vector search hands to the exact alignment rerank, frozen where alignment_atlas's rulings
set it (`docs/decisions/representation/alignment_atlas/2026-10-18_beta_ship_conditions_and_stop_rules.md` and its
evidence) and shared by the atlas's benchmark and the alignment search service.

| Ruling | Rule | Here |
|---|---|---|
| A17 | each query's depth from a budget of alignment cells: as many candidates as fit a 400-residue query's cells at 4,000, from 4,000 to 16,000 | `cell_depths` |
| A18 | a query over 300 residues also searches with windows of 100 at stride 50; each window takes its own vector top, together half the depth, and the entries they add are appended once | `window_starts`, `window_depths`, `windowed_union` |

A database entry is one vector row, its sequence truncated to the encoder's residue cap (2,046 residues, ESMC's 2,048
tokens less CLS and EOS: `alignment_search.encoder.MAX_RESIDUES`). Logan, 2026-11-03: "always truncate to 2048 tokens
(2046 residues for ESMC)", retiring the review's E6 (entries over 1,000 residues as windows of 500 at stride 250 in a
lane of their own), which he had not approved
(`docs/decisions/serving/alignment_search/2026-11-03_one_row_per_entry_truncated.md`). Every candidate is reranked as
the whole query against the whole stored entry.
"""

from __future__ import annotations

import numpy as np


CELL_REFERENCE = 400  # A17: each query aligns at most the cells of a 400-residue query at CELL_BASE candidates
CELL_BASE, CELL_CAP = 4000, 16000  # A17: the depth's floor and ceiling
QUERY_WINDOW_MIN = 300  # A18: a query longer than this also searches with its windows
QUERY_WINDOW = (100, 50)  # A18: window size and stride, in residues
QUERY_WINDOW_SHARE = 0.5  # A18: the share of the depth that a query's windows' tops take together


def window_starts(length: int, size: int, stride: int) -> list[int]:
    """Window starts covering a sequence (A18's query windows): 0, stride, 2 x stride and on, then a last window ending
    at its end, so every residue is covered and any segment of `size - stride` residues or fewer lies whole in some
    window; one window when the sequence fits."""
    if length <= size:
        return [0]
    return list(range(0, length - size, stride)) + [length - size]


def cell_depths(query_lengths: np.ndarray, reference_length: int = CELL_REFERENCE, base: int = CELL_BASE,
                cap: int = CELL_CAP) -> np.ndarray:
    """Each query's candidate depth under a budget of alignment cells (A17): as many candidates as fit the cells of a
    `reference_length`-residue query at `base` candidates, rounded, from `base` to `cap`, since the exact rerank costs
    the query's length times its candidates' summed lengths: (q)."""
    # query_lengths: (q)
    return np.clip(np.round(base * reference_length / query_lengths), base, cap).astype(np.int64)  # (q)


def window_depths(depths: np.ndarray, windows: np.ndarray, share: float = QUERY_WINDOW_SHARE) -> np.ndarray:
    """Each window's own vector top under A18: ceil(depth x share / windows) for its query, so a query's windows take
    about `share` of its depth together; a query with no windows takes the value for one: (q)."""
    # depths, windows: (q)
    return np.ceil(np.asarray(depths) * share / np.maximum(windows, 1)).astype(np.int64)  # (q)


def windowed_union(base: np.ndarray, depths: np.ndarray, window_top: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """A18's candidates: each query's first `depths[q]` whole-query candidates (`base` (q, d)), then the entries its
    windows' own top lists add (`window_top[q]` (w_q, k_q), empty for a query with no windows), each entry once, in that
    order, as a matrix padded with each query's last candidate, and each query's count: (q, u), (q)."""
    # base: (q, d); depths: (q); window_top: (w_q, k_q) per query
    unions = []
    for query, depth in enumerate(depths):
        whole = base[query, :depth]  # (depth)
        added = window_top[query].reshape(-1)  # (w_q k_q), window by window, best first
        _, first = np.unique(added, return_index=True)
        added = added[np.sort(first)]
        unions.append(np.concatenate([whole, added[~np.isin(added, whole)]]))
    counts = np.array([len(union) for union in unions])  # (q)
    padded = np.stack([np.concatenate([union, np.full(counts.max() - len(union), union[-1])]) for union in unions])
    return padded, counts  # (q, u), (q)
