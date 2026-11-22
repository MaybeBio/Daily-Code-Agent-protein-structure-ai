"""AUROC of units against terms under the compendium's rule for negatives, exact and on the GPU.

A term's positives are the proteins holding it at a tier their split scores; its negatives are the proteins observed in its
unit (an aspect within a fundamental aspect, `compendium`) that neither hold it nor are masked for it; every other protein is
unknown for it and enters neither (CAFA's closed world, the release's own). So each term ranks a different set of proteins,
and the one ranking the atlas study's `global_from_ranks` shares across terms no longer serves.

Each pole's scores are ranked once (dense ranks, ties equal). Every (unit, protein) observation and every (term, protein)
masked carrier becomes a sorted integer key, `group * G + rank`, and two binary searches per positive give, for each term at
once, how many proteins of its unit and how many of its masked carriers rank below or tie the positive. With B_S(p), the
unit's proteins below p plus half those tied with it, and U_M, the masked carriers below a positive plus half the tied ones,
summed over the positives:

    U(positives, negatives) = sum_p B_S(p) - |P| (|P| - 1) / 2 - U_M,    AUROC = U / (|P| |N|),

where |N| = |S| - |P| - |M|: the positives' own pairs give |P| (|P| - 1) / 2 in total, ties counting half, and the masked
carriers are taken out exactly. `tests/test_units_observed.py` holds this to a pair-by-pair count.

Symbols: n proteins; c poles; b poles of one block; t terms; u units; e entries of a sparse table.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp
import torch

from collections.abc import Sequence
from dataclasses import dataclass
from scipy import stats

from .specificity import MIN_SUPPORT


BLOCK = 64  # poles ranked together


def rows_matrix(rows: Sequence[Sequence[int]], width: int) -> sp.csr_matrix:
    indptr = np.zeros(len(rows) + 1, dtype=np.int64)  # (n + 1,)
    indptr[1:] = np.cumsum([len(row) for row in rows])
    indices = np.concatenate([np.asarray(row, dtype=np.int64) for row in rows]) if len(rows) else np.zeros(0, dtype=np.int64)
    matrix = sp.csr_matrix((np.ones(len(indices), dtype=bool), indices, indptr), shape=(len(rows), width))  # (n, width)
    matrix.sum_duplicates()
    return matrix


@dataclass(frozen=True)
class TermLabels:
    """Each protein's positives, masked carriers and observation units, and each term's unit."""

    positives: sp.csr_matrix  # (n, t)
    masked: sp.csr_matrix  # (n, t), only carriers observed in the term's unit, none of them positive
    observed: sp.csr_matrix  # (n, u)
    unit: np.ndarray  # (t,), -1 for a term no unit scores

    def __post_init__(self) -> None:
        n, t = self.positives.shape
        if self.masked.shape != (n, t) or self.observed.shape[0] != n or self.unit.shape != (t,):
            raise ValueError("Positives, masked carriers, observations and units disagree in shape.")
        rows, columns = self.positives.nonzero()  # (e,), (e,)
        units = self.unit[columns]  # (e,)
        if (units < 0).any():
            raise ValueError("A protein holds a term that no unit scores.")
        if not np.asarray(self.observed[rows, units]).all():
            raise ValueError("A positive lies outside its term's observed unit.")

    @classmethod
    def from_frame(cls, frame: pd.DataFrame, n_terms: int, unit: np.ndarray) -> TermLabels:
        """From an atlas frame's `annotations`, `masked` and `units` columns; masked carriers outside the term's unit, who
        are unknown for it anyway, are dropped."""
        # unit: (t,)
        n_units = int(unit.max()) + 1 if len(unit) and unit.max() >= 0 else 0
        observed = rows_matrix(list(frame["units"]), n_units)  # (n, u)
        masked = rows_matrix(list(frame["masked"]), n_terms).tocoo()  # (n, t)
        kept = (unit[masked.col] >= 0)  # (e,)
        kept[kept] = np.asarray(observed[masked.row[kept], unit[masked.col[kept]]]).ravel()
        masked = sp.csr_matrix((np.ones(int(kept.sum()), dtype=bool), (masked.row[kept], masked.col[kept])), shape=(len(frame), n_terms))
        return cls(rows_matrix(list(frame["annotations"]), n_terms), masked, observed, np.asarray(unit, dtype=np.int64))

    def rows(self, index: np.ndarray) -> TermLabels:
        """The labels of some proteins, in the given order."""
        # index: (m,)
        return TermLabels(self.positives[index], self.masked[index], self.observed[index], self.unit)

    def counts(self) -> tuple[np.ndarray, np.ndarray]:
        """Each term's positives and negatives."""
        n_positive = np.asarray(self.positives.sum(axis=0)).ravel()  # (t,)
        n_observed = np.asarray(self.observed.sum(axis=0)).ravel()  # (u,)
        n_masked = np.asarray(self.masked.sum(axis=0)).ravel()  # (t,)
        in_unit = np.where(self.unit >= 0, n_observed[np.maximum(self.unit, 0)], 0)  # (t,)
        return n_positive, in_unit - n_positive - n_masked  # (t,), (t,)


def _entries(matrix: sp.csr_matrix, groups: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """A sparse table's (group, row) entries, sorted by group then row, with each column mapped to its group."""
    # groups: (k,) the group of each of the matrix's k columns
    coo = matrix.tocoo()
    group = groups[coo.col]  # (e,)
    order = np.lexsort((coo.row, group))  # (e,)
    return group[order].astype(np.int64), coo.row[order].astype(np.int64)  # (e,), (e,)


def observed_auroc(scores: np.ndarray, labels: TermLabels, *, min_support: int = MIN_SUPPORT, device: str = "cpu",
                   block: int = BLOCK) -> np.ndarray:
    """AUROC of every pole against every term with `min_support` positives and negatives under the observation rule; NaN
    for any other term."""
    # scores: (n, c) protein scores, ties equal; labels over the same n proteins
    n, n_poles = scores.shape
    n_terms = labels.positives.shape[1]
    if labels.positives.shape[0] != n:
        raise ValueError(f"{labels.positives.shape[0]} label rows for {n} proteins.")
    n_positive, n_negative = labels.counts()  # (t,), (t,)
    valid = (labels.unit >= 0) & (n_positive >= min_support) & (n_negative >= min_support)  # (t,)
    auroc = np.full((n_poles, n_terms), np.nan)  # (c, t)
    if not valid.any() or n_poles == 0:
        return auroc  # (c, t)
    terms = np.flatnonzero(valid)  # (t_valid,)
    compact = np.full(n_terms, -1, dtype=np.int64)  # (t,)
    compact[terms] = np.arange(len(terms))
    units = np.unique(labels.unit[terms])  # (u_used,)
    unit_compact = np.full(labels.observed.shape[1], -1, dtype=np.int64)  # (u,)
    unit_compact[units] = np.arange(len(units))
    observed_unit, observed_row = _entries(labels.observed[:, units], np.arange(len(units)))  # (e_s,)
    positive_term, positive_row = _entries(labels.positives[:, terms], np.arange(len(terms)))  # (e_p,)
    masked_term, masked_row = _entries(labels.masked[:, terms], np.arange(len(terms)))  # (e_m,)
    positive_unit = unit_compact[labels.unit[terms]][positive_term]  # (e_p,)
    observed_start = np.searchsorted(observed_unit, np.arange(len(units)))  # (u_used,) each unit's first entry
    masked_start = np.searchsorted(masked_term, np.arange(len(terms)))  # (t_valid,) each term's first masked entry
    span = n + 1  # dense ranks lie in [0, n)
    as_tensor = lambda array: torch.as_tensor(array, dtype=torch.long, device=device)  # noqa: E731
    s_group, s_row = as_tensor(observed_unit), as_tensor(observed_row)  # (e_s,)
    m_group, m_row = as_tensor(masked_term), as_tensor(masked_row)  # (e_m,)
    p_unit, p_term, p_row = as_tensor(positive_unit), as_tensor(positive_term), as_tensor(positive_row)  # (e_p,)
    s_first = as_tensor(observed_start)[p_unit]  # (e_p,)
    m_first = as_tensor(masked_start)[p_term]  # (e_p,)
    positives = torch.as_tensor(n_positive[terms], dtype=torch.float64, device=device)  # (t_valid,)
    negatives = torch.as_tensor(n_negative[terms], dtype=torch.float64, device=device)  # (t_valid,)
    for start in range(0, n_poles, block):
        values = torch.as_tensor(np.ascontiguousarray(scores[:, start:start + block]), device=device)  # (n, b)
        ordered, order = torch.sort(values, dim=0)  # (n, b) each
        steps = torch.ones_like(ordered, dtype=torch.long)  # (n, b)
        steps[0] = 0
        steps[1:] = (ordered[1:] != ordered[:-1]).long()
        ranks = torch.empty_like(order).scatter_(0, order, steps.cumsum(dim=0))  # (n, b) dense rank of each protein
        observed_keys = torch.sort(s_group * span + ranks[s_row].T, dim=1).values.contiguous()  # (b, e_s)
        query = (p_unit * span + ranks[p_row].T).contiguous()  # (b, e_p)
        low = torch.searchsorted(observed_keys, query, right=False)  # (b, e_p)
        high = torch.searchsorted(observed_keys, query, right=True)  # (b, e_p)
        value = (low - s_first).double() + 0.5 * (high - low - 1).double()  # (b, e_p) B_S of each positive
        if m_row.numel():
            masked_keys = torch.sort(m_group * span + ranks[m_row].T, dim=1).values.contiguous()  # (b, e_m)
            query = (p_term * span + ranks[p_row].T).contiguous()  # (b, e_p)
            low = torch.searchsorted(masked_keys, query, right=False)  # (b, e_p)
            high = torch.searchsorted(masked_keys, query, right=True)  # (b, e_p)
            value -= (low - m_first).double() + 0.5 * (high - low).double()
        summed = value.new_zeros((value.shape[0], len(terms))).index_add_(1, p_term, value)  # (b, t_valid)
        u_statistic = summed - positives * (positives - 1) / 2  # (b, t_valid)
        auroc[start:start + block, terms] = (u_statistic / (positives * negatives)).cpu().numpy()
    return auroc  # (c, t)


def held_out_auroc(scores: np.ndarray, labels: TermLabels, selected: np.ndarray, min_support: int = MIN_SUPPORT) -> np.ndarray:
    """Tie-corrected AUROC on held-out proteins of each pole's selected term under the observation rule; NaN without the
    support."""
    # scores: (n, p) held-out scores; labels over the same n proteins; selected: (p,) term per pole, -1 for none
    n_poles = scores.shape[1]
    held_out = np.full(n_poles, np.nan)  # (p,)
    positives, masked, observed = sp.csc_matrix(labels.positives), sp.csc_matrix(labels.masked), sp.csc_matrix(labels.observed)
    for term in np.unique(selected[selected >= 0]):
        unit = int(labels.unit[term])
        if unit < 0:
            continue
        is_positive = positives[:, int(term)].toarray().ravel()  # (n,)
        eligible = observed[:, unit].toarray().ravel() & ~masked[:, int(term)].toarray().ravel()  # (n,)
        n_positive = int(is_positive.sum())
        n_negative = int(eligible.sum()) - n_positive
        if n_positive < min_support or n_negative < min_support:
            continue
        poles = np.flatnonzero(selected == term)  # (p_term,)
        ranks = stats.rankdata(np.asarray(scores[eligible][:, poles], dtype=np.float64), axis=0, method="average")  # (n_e, p_term)
        u_statistic = ranks[is_positive[eligible]].sum(axis=0) - n_positive * (n_positive + 1) / 2  # (p_term,)
        held_out[poles] = u_statistic / (n_positive * n_negative)
    return held_out  # (p,)
