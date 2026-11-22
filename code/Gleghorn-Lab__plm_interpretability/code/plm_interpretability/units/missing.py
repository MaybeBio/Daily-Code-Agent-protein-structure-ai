"""Missing annotations: test proteins' labels inherited from close homologs, and every basis scored again.

An absent annotation is not an absent feature, so a pole that fires on a carrier nobody annotated is scored as an error.
The compendium already keeps a protein's negatives inside the units it is annotated in (`observed`), which removes the
gaps of whole unannotated aspects; this correction addresses the gaps left inside an annotated one. Each test protein
inherits the positives of every release protein of `TARGET_SPLITS` it matches at `MIN_IDENTITY` or more over
`MIN_COVERAGE` of both sequences (UniRef50's identity, with the coverage asked of both), found by one MMseqs2 search
(`SEARCH`), except the terms of `UNINHERITED_ASPECTS`, which describe an entry as often as its sequence. The targets are the
splits whose released labels follow the test proteins' tier rule (experimental and signature, a curated term masked). The
release's twelve directed comparisons between its splits found no pair at 0.5 identity or more, over half of the query, so
no train or calibration protein can be a match, and a validation match is counted in the receipt. An inherited positive
makes its unit observed, so inheritance can change a term's negatives as well as its positives. Each pole's best training term is then scored on the test proteins before and after: AUROC under the
observation rule (`observed.held_out_auroc`), and average precision, which the false positives of an incomplete annotation
lower most directly. Only poles whose term's labels change are scored again; the rest keep their scores.

Local association compares residues inside proteins annotated with the term, so an annotation missing from a whole
protein never enters it; the correction is therefore global.

Symbols: n test proteins; p poles; t terms; u units; q queries; c poles scored together.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp

from collections.abc import Mapping, Sequence
from pathlib import Path

from foundry.datasets.homology import SearchConfig
from .experiments import stem
from .observed import TermLabels, held_out_auroc
from .specificity import MIN_SUPPORT


MIN_IDENTITY = 0.5
MIN_COVERAGE = 0.8
TARGET_SPLITS = ("validation", "test")  # the release splits scored by the test proteins' tier rule
UNINHERITED_ASPECTS = ("keyword",)
MMSEQS_VERSION = "8cc5ce367b5638c4306c2d7cfc652dd099a4643f"  # release 18-8cc5c, as `mmseqs version` prints it
# foundry's search defaults (e-value 1e-3, sensitivity 7.5, at most 2,000 targets a query) with coverage of both sequences.
SEARCH = SearchConfig(min_coverage=MIN_COVERAGE, coverage_mode=0, alignment_mode=3, expected_version=MMSEQS_VERSION)
CHUNK = 1024
METRICS = ("auroc_before", "auroc_after", "precision_before", "precision_after", "prevalence_before", "prevalence_after")


def table_path(root: Path, experiment: str, key: str) -> Path:
    """Where a run keeps one basis's scores before and after inheritance (`basis_scores`)."""
    return root / "missing" / experiment / f"{stem(experiment, key)}.parquet"


def inheritable(terms: pd.DataFrame) -> np.ndarray:
    """Whether each token's term is inherited, in token order: every scored term outside `UNINHERITED_ASPECTS`."""
    # terms: one row per token, with `token`, `aspect` and `unit`
    ordered = terms.sort_values("token")
    if not np.array_equal(ordered["token"].to_numpy(), np.arange(len(ordered))):
        raise ValueError("Vocabulary tokens must be unique and contiguous from zero.")
    return (~ordered["aspect"].isin(UNINHERITED_ASPECTS) & (ordered["unit"] >= 0)).to_numpy()  # (t,)


def inherited_positives(queries: Sequence[str], matches: Mapping[str, Sequence[str]],
                        annotations: Mapping[str, Sequence[int]], inherit: np.ndarray) -> sp.csr_matrix:
    """Row i marks the inheritable terms that query i's matches hold; a query never inherits from itself, and a query
    the search did not cover raises."""
    # inherit: (t,)
    rows: list[int] = []
    columns: list[int] = []
    for row, query in enumerate(queries):
        carried = {int(token) for match in matches[query] if match != query for token in annotations.get(match, ())}
        kept = sorted(token for token in carried if inherit[token])
        rows.extend([row] * len(kept))
        columns.extend(kept)
    return sp.csr_matrix((np.ones(len(rows), dtype=bool), (rows, columns)), shape=(len(queries), len(inherit)))  # (q, t)


def with_inherited(own: TermLabels, inherited: sp.spmatrix) -> TermLabels:
    """The labels after inheritance: a protein holds a term it is annotated with or inherits, observes each inherited
    term's unit, and stays masked only for terms it still does not hold."""
    # inherited: (n, t)
    positives = sp.csr_matrix((sp.csr_matrix(own.positives, dtype=np.int8) + sp.csr_matrix(inherited, dtype=np.int8)) > 0)  # (n, t)
    added = sp.csr_matrix(inherited, dtype=bool).tocoo()
    units = sp.csr_matrix((np.ones(added.nnz, dtype=bool), (added.row, own.unit[added.col])), shape=own.observed.shape)  # (n, u)
    observed = sp.csr_matrix((sp.csr_matrix(own.observed, dtype=np.int8) + sp.csr_matrix(units, dtype=np.int8)) > 0)  # (n, u)
    masked = sp.csr_matrix(own.masked, dtype=bool) > positives  # (n, t)
    return TermLabels(positives, sp.csr_matrix(masked), observed, own.unit)


def changed_terms(own: TermLabels, propagated: TermLabels) -> np.ndarray:
    """Whether inheritance changes a term's positives, its masked carriers or its unit's observed proteins."""
    def differs(first: sp.spmatrix, second: sp.spmatrix) -> np.ndarray:
        return np.asarray((sp.csr_matrix(first, dtype=bool) != sp.csr_matrix(second, dtype=bool)).sum(axis=0)).ravel() > 0  # (k,)

    unit_changed = differs(own.observed, propagated.observed)  # (u,)
    by_unit = np.where(own.unit >= 0, unit_changed[np.maximum(own.unit, 0)], False)  # (t,)
    return differs(own.positives, propagated.positives) | differs(own.masked, propagated.masked) | by_unit  # (t,)


def average_precision(scores: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Each row's average precision against one labeling: the precision at each distinct score, from the highest,
    weighted by the recall it adds, so tied scores share one threshold (scikit-learn's `average_precision_score`)."""
    # scores: (c, n); labels: (n,) bool with at least one positive
    order = np.argsort(-scores, axis=1, kind="stable")  # (c, n)
    ranked = np.take_along_axis(scores, order, axis=1)  # (c, n)
    found = np.cumsum(labels[order], axis=1)  # (c, n) positives at or above each place
    last = np.ones(ranked.shape, dtype=bool)  # (c, n) the last place of each run of tied scores
    last[:, :-1] = ranked[:, :-1] != ranked[:, 1:]
    previous = np.zeros_like(found)  # (c, n) positives at the threshold before each place
    previous[:, 1:] = np.maximum.accumulate(np.where(last, found, 0)[:, :-1], axis=1)
    precision = found / np.arange(1, scores.shape[1] + 1)  # (c, n)
    return np.where(last, (found - previous) * precision, 0.0).sum(axis=1) / labels.sum()  # (c,)


def _scored(labels: TermLabels, term: int) -> tuple[np.ndarray, np.ndarray]:
    """One term's scored proteins (positives and negatives under the observation rule) and which of them are positive."""
    positive = sp.csc_matrix(labels.positives)[:, term].toarray().ravel()  # (n,)
    unit = int(labels.unit[term])
    eligible = sp.csc_matrix(labels.observed)[:, unit].toarray().ravel() & ~sp.csc_matrix(labels.masked)[:, term].toarray().ravel()  # (n,)
    return eligible, positive[eligible]  # (n,), (n_eligible,)


def held_out_average_precision(scores: np.ndarray, labels: TermLabels, selected: np.ndarray,
                               min_support: int = MIN_SUPPORT, chunk: int = CHUNK) -> np.ndarray:
    """Average precision on test proteins of each pole's selected term over the term's scored proteins, under
    `held_out_auroc`'s support rule; NaN without it."""
    # scores: (n, p) test global scores; selected: (p,) term per pole, -1 for none
    precision = np.full(scores.shape[1], np.nan)  # (p,)
    for term in np.unique(selected[selected >= 0]):
        if labels.unit[term] < 0:
            continue
        eligible, positive = _scored(labels, int(term))  # (n,), (n_eligible,)
        n_positive = int(positive.sum())
        if n_positive < min_support or len(positive) - n_positive < min_support:
            continue
        poles = np.flatnonzero(selected == term)  # (c_term,)
        for start in range(0, len(poles), chunk):
            block = poles[start:start + chunk]  # (c,)
            precision[block] = average_precision(np.ascontiguousarray(np.asarray(scores[eligible][:, block]).T), positive)
    return precision  # (p,)


def prevalence(labels: TermLabels) -> np.ndarray:
    """Each term's share of positives among its scored proteins; NaN where it has none."""
    n_positive, n_negative = labels.counts()  # (t,), (t,)
    scored = n_positive + n_negative  # (t,)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(scored > 0, n_positive / scored, np.nan)  # (t,)


def basis_scores(maxima: np.ndarray, own: TermLabels, propagated: TermLabels, table: pd.DataFrame, *,
                 min_support: int = MIN_SUPPORT) -> pd.DataFrame:
    """One basis's poles on the test proteins before and after inheritance: the AUROC, average precision and prevalence
    of each pole's best training term. A pole whose term inheritance leaves unchanged keeps its scores; for the others
    the AUROC before inheritance is computed again and must equal the score table's, which ties `maxima`'s rows to the
    pass's test proteins."""
    # maxima: (n, p) the test proteins' maxima in the pass's order; table: `global_scores`'s
    best = table["best_term"].to_numpy(dtype=np.int64)  # (p,)
    if len(best) != maxima.shape[1] or not np.array_equal(table["pole"].to_numpy(), np.arange(len(best))):
        raise ValueError("The score table must hold one row per pole of the maxima, in pole order.")
    maxima = np.asarray(maxima, dtype=np.float64)  # (n, p) as `global_scores` ranks them; SciPy ranks float32 in float32
    again = (best >= 0) & changed_terms(own, propagated)[np.maximum(best, 0)]  # (p,)
    redo = np.where(again, best, -1)  # (p,)
    recorded = table["held_out_auroc"].to_numpy(dtype=np.float64)  # (p,)
    if not np.allclose(held_out_auroc(maxima, own, redo, min_support)[again], recorded[again], rtol=0, atol=1e-12,
                       equal_nan=True):
        raise ValueError("The test AUROC before inheritance differs from the score table's; the rows are not the pass's.")
    precision_before = held_out_average_precision(maxima, own, best, min_support)  # (p,)
    share_before, share_after = prevalence(own), prevalence(propagated)  # (t,), (t,)
    return pd.DataFrame({
        "pole": np.arange(len(best)), "best_term": best, "rescored": again,
        "auroc_before": recorded,
        "auroc_after": np.where(again, held_out_auroc(maxima, propagated, redo, min_support), recorded),
        "precision_before": precision_before,
        "precision_after": np.where(again, held_out_average_precision(maxima, propagated, redo, min_support), precision_before),
        "prevalence_before": np.where(best >= 0, share_before[np.maximum(best, 0)], np.nan),
        "prevalence_after": np.where(best >= 0, share_after[np.maximum(best, 0)], np.nan),
    })


def missing_summary(tables: Mapping[str, pd.DataFrame]) -> dict[str, dict[str, object]]:
    """Per basis: its poles, those rescored, those scored only after inheritance, and over the poles scored both ways
    the medians of every metric, the median gain in average precision and the share of poles it raised."""
    summary: dict[str, dict[str, object]] = {}
    for key, table in tables.items():
        before, after = np.isfinite(table["auroc_before"]), np.isfinite(table["auroc_after"])
        both = table[before & after]
        gain = (both["precision_after"] - both["precision_before"]).to_numpy()  # (a,)
        summary[key] = {
            "poles": len(table), "rescored": int(table["rescored"].sum()), "scored_both": len(both),
            "scored_after_only": int((~before & after).sum()),
            **{f"median_{metric}": float(np.median(both[metric])) if len(both) else None for metric in METRICS},
            "median_precision_gain": float(np.median(gain)) if len(both) else None,
            "share_raised": float(np.mean(gain > 0)) if len(both) else None,
        }
    return summary
