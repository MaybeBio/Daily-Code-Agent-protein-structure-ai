"""The atlas set: the compendium proteins `split.atlas_sample` draws, with their labels, the local term columns and the
intrinsic terms.

`compendium` turns the release's rows into each protein's global positives, masked tokens and observation units and its local
positive and masked runs; this module joins them to the sample, appends the intrinsic local terms computed from each sequence
(`intrinsic`) under tokens past the vocabulary, and counts each local term's informative training proteins. Those counts
decide the term columns: at least 10 for the atlas study's selection, at least 50 for the dominant-term rule
(preregistration, `specificity`). Global terms are the vocabulary's tokens; local terms are its located tokens (`is_local`)
and the intrinsic ones.

A protein is informative for a local term when the term has a positive residue in it and the term's scope, the chain or a
modification site's amino acid, holds a residue that is neither positive nor masked (`accumulate.term_residues`).

Symbols: n proteins; t terms; u observation units.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .accumulate import LocalRuns, term_residues
from .atlas import PassProteins
from .compendium import CHAIN, LOCAL_COLUMNS, Vocabulary
from .intrinsic import TERMS as INTRINSIC_TERMS
from .intrinsic import intrinsic_terms
from .observed import TermLabels, rows_matrix
from .split import assignment_digest


MIN_SELECTION = 10  # the atlas study's min_support for local selection
MIN_DOMINANCE = 50  # specificity.MIN_INFORMATIVE, the dominant-term rule's support
SAMPLE_COLUMNS = ("protein_id", "cluster", "split")
PROTEIN_COLUMNS = ("protein_id", "primary_accession", "sequence", "reviewed")


@dataclass
class AtlasSet:
    """The atlas set's proteins and vocabulary, in a fixed protein order (by protein id)."""

    proteins: pd.DataFrame  # protein_id, accession, cluster, split, sequence, length, reviewed, annotations, masked, units, LOCAL_COLUMNS
    vocabulary_size: int  # global terms are tokens 0 .. vocabulary_size - 1
    unit: np.ndarray  # (vocabulary_size,) each global term's observation unit, -1 where none scores it
    n_units: int
    local_vocabulary: frozenset[int]  # the vocabulary's local tokens and the intrinsic ones
    scopes: dict[int, int]  # local token -> the amino acid it is scored on; every other local token is scored on the chain
    intrinsic_tokens: dict[str, int]
    informative: Counter[int]  # local token -> informative training proteins
    digest: str  # the sample's assignment digest

    def term_columns(self, minimum: int) -> dict[int, int]:
        """Local tokens with at least `minimum` informative training proteins, mapped to accumulator columns."""
        tokens = sorted(token for token, count in self.informative.items() if count >= minimum and token in self.local_vocabulary)
        return {token: column for column, token in enumerate(tokens)}

    def labels(self, split: str | None = None) -> TermLabels:
        """Global labels of the proteins of one split (all when None), in protein order."""
        rows = self.proteins if split is None else self.proteins[self.proteins["split"] == split]
        return TermLabels.from_frame(rows, self.vocabulary_size, self.unit)


def local_runs(row: pd.Series) -> LocalRuns:
    """One protein's local positive and masked runs, 1-based inclusive."""
    return LocalRuns(*(np.asarray(row[column], dtype=np.int64) for column in LOCAL_COLUMNS))


def with_intrinsic(proteins: pd.DataFrame, tokens: dict[str, int]) -> pd.DataFrame:
    """Append each protein's intrinsic intervals to its local positives under the intrinsic tokens."""
    term_ids, starts, ends = [], [], []
    for sequence, ids, left, right in zip(proteins["sequence"], proteins["local_term_ids"], proteins["local_starts"],
                                          proteins["local_ends"], strict=True):
        found = intrinsic_terms(sequence)
        added = [(tokens[term], start, end) for term, spans in found.items() for start, end in spans]
        term_ids.append(np.concatenate((np.asarray(ids, dtype=np.int64), [token for token, _, _ in added])).astype(np.int64))
        starts.append(np.concatenate((np.asarray(left, dtype=np.int64), [start for _, start, _ in added])).astype(np.int64))
        ends.append(np.concatenate((np.asarray(right, dtype=np.int64), [end for _, _, end in added])).astype(np.int64))
    return proteins.assign(local_term_ids=term_ids, local_starts=starts, local_ends=ends)


def informative_counts(sequences: Iterable[str], runs: Iterable[LocalRuns], vocabulary: frozenset[int],
                       scopes: dict[int, int]) -> Counter[int]:
    """For each local token, the proteins informative for it (`accumulate.term_residues`)."""
    counts: Counter[int] = Counter()
    for sequence, annotations in zip(sequences, runs, strict=True):
        for token, residues in term_residues(sequence, annotations, vocabulary, scopes).items():
            if residues.informative:
                counts[token] += 1
    return counts


def _arrays(cells: Iterable[object]) -> list[np.ndarray]:
    """List cells as int64 arrays; a cell a left join left empty becomes an empty array."""
    return [np.asarray(cell, dtype=np.int64) if isinstance(cell, (list, tuple, np.ndarray)) else np.zeros(0, dtype=np.int64)
            for cell in cells]  # (a_i,) each


def build_atlas_set(sample: pd.DataFrame, proteins: pd.DataFrame, labels: pd.DataFrame, local: pd.DataFrame,
                    words: Vocabulary) -> AtlasSet:
    """The atlas set from the sample (`split.atlas_sample`), the release's protein table (`PROTEIN_COLUMNS`), each protein's
    global labels (`compendium.global_labels`) and local runs (`compendium.local_runs`), and the vocabulary. A protein
    without a labelled row or a residue run has none of them."""
    for name, frame, columns in (("sample", sample, SAMPLE_COLUMNS), ("protein table", proteins, PROTEIN_COLUMNS),
                                 ("labels", labels, ("protein_id", "annotations", "masked", "units")),
                                 ("local runs", local, ("protein_id", *LOCAL_COLUMNS))):
        missing = sorted(set(columns) - set(frame.columns))
        if missing:
            raise ValueError(f"The {name} lacks {missing}.")
    frame = (sample[list(SAMPLE_COLUMNS)]
             .merge(proteins[list(PROTEIN_COLUMNS)], on="protein_id", how="left", validate="one_to_one")
             .merge(labels, on="protein_id", how="left", validate="one_to_one")
             .merge(local, on="protein_id", how="left", validate="one_to_one")
             .rename(columns={"primary_accession": "accession"})
             .sort_values("protein_id", kind="mergesort").reset_index(drop=True))
    if frame["sequence"].isna().any():
        raise ValueError("A sampled protein is missing from the protein table.")
    if frame["accession"].duplicated().any():
        raise ValueError("Two sampled proteins share a primary accession.")
    for column in ("annotations", "masked", "units", *LOCAL_COLUMNS):
        frame[column] = _arrays(frame[column])
    frame["length"] = frame["sequence"].str.len()
    vocabulary_size = words.size
    intrinsic = {term: vocabulary_size + index for index, term in enumerate(INTRINSIC_TERMS)}
    frame = with_intrinsic(frame, intrinsic)
    terms = words.terms
    local_vocabulary = frozenset(terms.loc[terms["is_local"].astype(bool), "token"].astype(int)) | frozenset(intrinsic.values())
    scopes = {int(token): int(scope) for token, scope in zip(terms["token"], terms["scope"], strict=True) if int(scope) != CHAIN}
    train = frame[frame["split"] == "train"]
    counts = informative_counts(train["sequence"], (local_runs(row) for _, row in train.iterrows()), local_vocabulary, scopes)
    return AtlasSet(proteins=frame, vocabulary_size=vocabulary_size, unit=terms["unit"].to_numpy(dtype=np.int64),
                    n_units=len(words.units), local_vocabulary=local_vocabulary, scopes=scopes, intrinsic_tokens=intrinsic,
                    informative=counts, digest=assignment_digest(sample))


def local_ancestors(ancestors: sp.csr_matrix, tokens: Sequence[int]) -> sp.csr_matrix:
    """The ancestor matrix among some local terms, in their order; intrinsic tokens, past the vocabulary, have none."""
    # ancestors: (t, t) over the vocabulary; tokens: (t_local,)
    tokens = np.asarray(tokens, dtype=np.int64)  # (t_local,)
    inside = np.flatnonzero(tokens < ancestors.shape[0])  # (t_inside,)
    block = ancestors[tokens[inside]][:, tokens[inside]].tocoo()  # (t_inside, t_inside)
    size = len(tokens)
    return sp.csr_matrix((block.data, (inside[block.row], inside[block.col])), shape=(size, size), dtype=bool)  # (t_local, t_local)


def local_presence(proteins: pd.DataFrame, tokens: Sequence[int]) -> sp.csr_matrix:
    """Which proteins carry each local term anywhere, in the frame's order and the tokens' order."""
    column_of = {int(token): column for column, token in enumerate(tokens)}
    rows = [sorted({column_of[int(token)] for token in term_ids if int(token) in column_of}) for term_ids in proteins["local_term_ids"]]
    return rows_matrix(rows, len(tokens)).astype(np.float64)  # (n, t_local)


PASS_SPLITS = ("train", "validation", "test")
SUBSET_SEED = 24895


def pass_proteins(proteins: pd.DataFrame, *, subset: int | None = None, seed: int = SUBSET_SEED) -> PassProteins:
    """The train, validation and test proteins as a pass, or a seeded subset of them in which each split keeps its share.

    Rows keep the frame's order; `PassProteins.ordered` sorts them for batching.
    """
    rows = proteins[proteins["split"].isin(PASS_SPLITS)]
    if subset is not None:
        if not 0 < subset <= len(rows):
            raise ValueError(f"A subset of {subset} proteins cannot be drawn from {len(rows)}.")
        generator = np.random.default_rng(seed)
        chosen = []
        for _, group in rows.groupby("split", sort=True):
            count = min(len(group), int(round(subset * len(group) / len(rows))))
            chosen.append(np.sort(generator.choice(group.index.to_numpy(), size=count, replace=False)))
        rows = rows.loc[np.sort(np.concatenate(chosen))]
    return _as_pass(rows)


def residue_budget_proteins(proteins: pd.DataFrame, residues: int, *, split: str = "train", seed: int = SUBSET_SEED) -> PassProteins:
    """A seeded random order of one split's proteins, cut at the protein whose residues bring the total to `residues`
    (every protein if the split holds fewer); rows keep the frame's order. The dictionary test and the rotation search
    read these."""
    rows = proteins[proteins["split"] == split]
    order = np.random.default_rng(seed).permutation(len(rows))  # (n_split,)
    totals = np.cumsum(rows["sequence"].str.len().to_numpy()[order])  # (n_split,)
    count = min(len(rows), int(np.searchsorted(totals, residues)) + 1)
    return _as_pass(rows.iloc[np.sort(order[:count])])


def _as_pass(rows: pd.DataFrame) -> PassProteins:
    return PassProteins(rows["accession"].tolist(), rows["sequence"].tolist(), rows["split"].to_numpy(),
                        [local_runs(row) for _, row in rows.iterrows()])


def calibration_sequences(proteins: pd.DataFrame) -> list[str]:
    """The calibration proteins' sequences, in the frame's order."""
    return proteins.loc[proteins["split"] == "calibration", "sequence"].tolist()
