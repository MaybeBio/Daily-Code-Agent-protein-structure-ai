"""Specificity of a unit's labels, never coverage.

Every basis passes coverage: in the atlas study all 16,384 SAE latents had qualifying associations, and randomized
controls assigned nearly every latent too. What separates bases is how specific a unit's best label is, so each pole is
scored by (i) its best term's global AUROC, (ii) the margin of that AUROC over the best term unrelated to it, (iii)
whether one local term (with its relatives) stands alone within 0.05 of the pole's maximum occupancy contrast, and
(iv) the held-out-cluster AUROC of the term chosen on training clusters (preregistration, `specificity`).

Two terms are related when one is an ancestor of the other in the vocabulary or their training proteins overlap with a
Jaccard index of at least 0.5, so a pole that tracks a family and its parent, or two terms that always co-occur, is not
penalized for the vocabulary's redundancy.

Symbols: n proteins; p poles; t terms.
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp

from dataclasses import dataclass, field


JACCARD_RELATED = 0.5
DOMINANCE_WINDOW = 0.05
MIN_CONTRAST = 0.25
MIN_INFORMATIVE = 50
MIN_SUPPORT = 10


@dataclass
class TermRelations:
    """Which terms count as the same label for a margin: ancestors, descendants and heavily overlapping terms."""

    ancestors: sp.csr_matrix  # (t, t), row i marks the ancestors of term i
    membership: sp.csc_matrix  # (n, t), training proteins carrying each term
    jaccard_threshold: float = JACCARD_RELATED
    _cache: dict[int, np.ndarray] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        n_terms = self.membership.shape[1]
        if self.ancestors.shape != (n_terms, n_terms):
            raise ValueError(f"Ancestor matrix {self.ancestors.shape} does not match {n_terms} terms.")
        self.ancestors = sp.csr_matrix(self.ancestors, dtype=bool)  # (t, t)
        self._descendants = sp.csr_matrix(self.ancestors.T)  # (t, t), row i marks the descendants of term i
        self.membership = sp.csc_matrix(self.membership, dtype=np.float64)  # (n, t)
        self._sizes = np.asarray(self.membership.sum(axis=0)).ravel()  # (t,)

    def related(self, term: int) -> np.ndarray:
        """Terms that count as the same label as `term`, itself included."""
        if term not in self._cache:
            column = self.membership[:, term]  # (n, 1)
            overlap = np.asarray((column.T @ self.membership).todense()).ravel()  # (t,)
            union = self._sizes[term] + self._sizes - overlap  # (t,)
            with np.errstate(invalid="ignore", divide="ignore"):
                jaccard = np.where(union > 0, overlap / union, 0.0)  # (t,)
            mask = jaccard >= self.jaccard_threshold  # (t,)
            mask[self.ancestors[term].indices] = True
            mask[self._descendants[term].indices] = True
            mask[term] = True
            self._cache[term] = mask
        return self._cache[term]  # (t,)


@dataclass(frozen=True)
class GlobalSpecificity:
    """Each pole's best term and how far it stands above the best unrelated term."""

    best_term: np.ndarray  # (p,), -1 where the pole has no testable term
    best_auroc: np.ndarray  # (p,)
    unrelated_term: np.ndarray  # (p,)
    unrelated_auroc: np.ndarray  # (p,)

    @property
    def margin(self) -> np.ndarray:
        return self.best_auroc - self.unrelated_auroc  # (p,)


def global_specificity(auroc: np.ndarray, relations: TermRelations) -> GlobalSpecificity:
    """Best term and top-term margin of every pole from its (poles, terms) AUROC matrix; untestable terms are NaN."""
    # auroc: (p, t)
    n_poles, n_terms = auroc.shape
    testable = np.isfinite(auroc)  # (p, t)
    has_term = testable.any(axis=1)  # (p,)
    filled = np.where(testable, auroc, -np.inf)  # (p, t)
    best_term = np.where(has_term, filled.argmax(axis=1), -1)  # (p,)
    best_auroc = np.where(has_term, filled[np.arange(n_poles), np.maximum(best_term, 0)], np.nan)  # (p,)
    unrelated_term = np.full(n_poles, -1)  # (p,)
    unrelated_auroc = np.full(n_poles, np.nan)  # (p,)
    for term in np.unique(best_term[best_term >= 0]):
        rows = np.flatnonzero(best_term == term)  # (p_term,)
        candidates = np.where(relations.related(int(term))[None, :], -np.inf, filled[rows])  # (p_term, t)
        found = np.isfinite(candidates).any(axis=1)  # (p_term,)
        choice = candidates.argmax(axis=1)  # (p_term,)
        unrelated_term[rows[found]] = choice[found]
        unrelated_auroc[rows[found]] = candidates[found, choice[found]]
    return GlobalSpecificity(best_term, best_auroc, unrelated_term, unrelated_auroc)


def single_dominant_term(
    contrast: np.ndarray,
    n_informative: np.ndarray,
    relations: TermRelations,
    *,
    window: float = DOMINANCE_WINDOW,
    min_contrast: float = MIN_CONTRAST,
    min_informative: int = MIN_INFORMATIVE,
) -> tuple[np.ndarray, np.ndarray]:
    """Per pole, its best local term and whether that term (with its relatives) is the only one within `window` of the
    pole's maximum mean contrast, at a contrast of at least `min_contrast` on at least `min_informative` proteins.

    `relations` is built over the local terms, in the same column order as `contrast`.
    """
    # contrast: (p, t) mean paired contrast; n_informative: (t,)
    eligible = (n_informative >= min_informative)[None, :] & np.isfinite(contrast)  # (p, t)
    filled = np.where(eligible, contrast, -np.inf)  # (p, t)
    best_term = filled.argmax(axis=1)  # (p,)
    best = filled[np.arange(len(filled)), best_term]  # (p,)
    dominant = np.zeros(len(filled), dtype=bool)  # (p,)
    for term in np.unique(best_term[best >= min_contrast]):
        rows = np.flatnonzero((best_term == term) & (best >= min_contrast))  # (p_term,)
        others = np.where(relations.related(int(term))[None, :], -np.inf, filled[rows])  # (p_term, t)
        dominant[rows] = others.max(axis=1) < best[rows] - window
    return np.where(np.isfinite(best), best_term, -1), dominant  # (p,), (p,)
