"""The annotation compendium as the atlas set reads it (preregistration, `data.atlas_inputs`).

`Synthyra/annotation_compendium_v1` keeps every annotation of its pooled proteins with its evidence tier, and its released rows
apply one tier rule per split (`annotation_vocabulary.compendium.views`): in train and calibration a term is a label at any
label tier (experimental, signature, curated); in validation and test only experimental and signature labels score, and a
curated one is masked; a guard (electronic, rule-based or family-tree inference) is masked everywhere, never a positive or a
negative. A protein gives negatives only within its observation units, each an aspect within its fundamental aspect, the units
it holds a positive in. The atlas set keeps each protein's release split (`split.atlas_sample`), so every rule holds as
released:

- Global terms are the release's tokens. A protein's positives are its row's tokens, its masked terms those of its row's
  `masked` that are tokens, and its units its row's `observed_units` with each positive's own unit added, so every positive
  sits inside the unit its negatives come from. The organism aspect is left out; E10 reads taxonomy on its own panel.
- Local terms are the residue tables' classes, a located feature, a modification site or the disordered region, each with
  its positive and masked residues, and InterPro's and Pfam's located matches from the assertions (signature tier, scored in
  every split). A modification site's negatives are the other residues of its amino acid (its `scope`); every other local
  term's are the rest of the chain.

Positions are 1-based and inclusive throughout, as the release writes them.

Symbols: n proteins; t tokens.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import scipy.sparse as sp

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from annotation_vocabulary.compendium.views import DISORDERED, TYPE_TERMS

from .intrinsic import AMINO_ACIDS
from .split import CLUSTER_LEVEL, SPLITS


ORGANISM = "organism"  # the fundamental aspect left out of the atlas
SIGNATURE_ASPECTS = ("local_interpro", "local_pfam")  # located matches, read from the assertions
SIGNATURE_TIER = "signature"
RELATED_EDGES = ("is_a", "part_of", "ec_parent", "clan_member", "family_member")  # the hierarchy's parent relations
CHAIN = -1  # the scope of a local term whose negatives are the rest of the chain
TERM_COLUMNS = ("token", "term_id", "label", "aspect", "fundamental_aspect", "source_database", "accession", "unit",
                "is_local", "scope")
LOCAL_COLUMNS = ("local_term_ids", "local_starts", "local_ends", "masked_term_ids", "masked_starts", "masked_ends")
RESIDUE_TABLES = ("located_features", "modification_sites", "disordered_regions")
RELEASE_FILES = (  # what the atlas reads of the release, in its Hub layout
    *(f"{split}.parquet" for split in SPLITS),
    *(f"tables/{name}.parquet" for name in ("vocabulary", "tokens", "hierarchy", "proteins", "split", "clusters", "assertions",
                                            "lineage", "neighbours", *RESIDUE_TABLES)),
)
EXAMINED_FILES = ("data/validation-*.parquet", "data/test-*.parquet")  # the atlas study's held-out shards


def unit_name(aspect: str, fundamental_aspect: str) -> str:
    """An observation unit as the release names it, `aspect/fundamental aspect` (`views.observation_units`)."""
    return f"{aspect}/{fundamental_aspect}"


@dataclass(frozen=True)
class Vocabulary:
    """The release's tokens with their observation units, local scopes and names."""

    terms: pd.DataFrame  # TERM_COLUMNS, one row per token in token order
    units: tuple[str, ...]  # observation units in index order, the organism aspect's left out

    @property
    def size(self) -> int:
        return len(self.terms)

    def token_of(self) -> dict[str, int]:
        return dict(zip(self.terms["term_id"], self.terms["token"].astype(int), strict=True))


def vocabulary(table: pd.DataFrame, tokens: pd.DataFrame, residues: Mapping[str, str]) -> Vocabulary:
    """The release's tokens (`tables/tokens.parquet`) described by its term table (`tables/vocabulary.parquet`); `residues`
    gives each modification site class its amino acid (`site_residues`). A token of the organism aspect has unit -1."""
    terms = tokens.merge(table, on="term_id", how="left", validate="one_to_one").sort_values("token").reset_index(drop=True)
    if terms["aspect"].isna().any():
        raise ValueError(f"{int(terms['aspect'].isna().sum())} tokens have no row in the term table.")
    if not np.array_equal(terms["token"].to_numpy(), np.arange(len(terms))):
        raise ValueError("Tokens must be unique and contiguous from zero.")
    names = [unit_name(aspect, fundamental) for aspect, fundamental in zip(terms["aspect"], terms["fundamental_aspect"], strict=True)]
    kept = (terms["fundamental_aspect"] != ORGANISM).to_numpy()  # (t,)
    units = tuple(sorted({name for name, keep in zip(names, kept, strict=True) if keep}))
    index = {name: position for position, name in enumerate(units)}
    unknown = sorted(set(residues) - set(terms["term_id"]))
    if unknown:
        raise ValueError(f"Site classes {unknown[:5]} are not tokens.")
    terms = terms.assign(
        unit=[index[name] if keep else -1 for name, keep in zip(names, kept, strict=True)],
        is_local=terms["aspect"].str.startswith("local_"),
        scope=[AMINO_ACIDS.index(residues[term]) if term in residues else CHAIN for term in terms["term_id"]],
        label=terms["name"].fillna(terms["term_id"]),
    )
    return Vocabulary(terms[list(TERM_COLUMNS)], units)


def global_labels(rows: pd.DataFrame, words: Vocabulary) -> pd.DataFrame:
    """Each protein's positives, masked tokens and observation units from its released row (`protein_id`, `tokens`,
    `masked`, `observed_units`), the organism aspect left out. Returns protein_id, annotations, masked and units."""
    token_of = words.token_of()
    unit = words.terms["unit"].to_numpy()  # (t,)
    index = {name: position for position, name in enumerate(words.units)}
    annotations, masked, units = [], [], []
    for tokens, hidden, observed in zip(rows["tokens"], rows["masked"], rows["observed_units"], strict=True):
        positives = sorted({int(token) for token in tokens if unit[int(token)] >= 0})
        annotations.append(np.asarray(positives, dtype=np.int64))
        held = {token_of[term] for term in hidden if term in token_of and unit[token_of[term]] >= 0} - set(positives)
        masked.append(np.asarray(sorted(held), dtype=np.int64))
        units.append(np.asarray(sorted({index[name] for name in observed if name in index}
                                       | {int(unit[token]) for token in positives}), dtype=np.int64))
    return pd.DataFrame({"protein_id": rows["protein_id"].to_numpy(), "annotations": annotations, "masked": masked, "units": units})


def runs_of(positions: Iterable[int]) -> list[tuple[int, int]]:
    """Sorted distinct positions as maximal runs of consecutive ones, (start, end) inclusive."""
    runs: list[tuple[int, int]] = []
    for position in sorted({int(position) for position in positions}):
        if runs and position == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], position)
        else:
            runs.append((position, position))
    return runs


def site_residues(sites: pd.DataFrame) -> dict[str, str]:
    """Each modification site class's amino acid, from the site table's entries; a class on two raises."""
    found: dict[str, str] = {}
    for entries in sites["sites"]:
        for entry in entries:
            name, residue = str(entry["modification"]), str(entry["residue"])
            if found.setdefault(name, residue) != residue:
                raise ValueError(f"Site class {name} sits on {found[name]} and on {residue}.")
            if residue not in AMINO_ACIDS:
                raise ValueError(f"Site class {name} sits on {residue!r}, not one of the 20 amino acids.")
    return found


class _Runs:
    """One protein's local positive and masked runs as they are gathered."""

    def __init__(self) -> None:
        self.positive: list[tuple[int, int, int]] = []
        self.masked: list[tuple[int, int, int]] = []

    def add(self, token: int, positive: Iterable[tuple[int, int]], masked: Iterable[tuple[int, int]]) -> None:
        self.positive.extend((token, start, end) for start, end in positive)
        self.masked.extend((token, start, end) for start, end in masked)


def _columns(triples: Sequence[tuple[int, int, int]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ordered = sorted(triples)
    return tuple(np.asarray([triple[index] for triple in ordered], dtype=np.int64) for index in range(3))  # (a,) each


def local_runs(located: pd.DataFrame, sites: pd.DataFrame, disorder: pd.DataFrame, signatures: pd.DataFrame,
               words: Vocabulary) -> pd.DataFrame:
    """Each protein's residue-level positive and masked runs under local tokens, from the release's three residue tables
    (`features`, `sites`, and `disordered` with `masked` positions) and the signature spans (`protein_id`, `term_id`, `start`,
    `end`, from `signature_spans`). Returns protein_id and `LOCAL_COLUMNS`, one row per protein with any run."""
    token_of = words.token_of()
    if DISORDERED not in token_of:
        raise ValueError(f"The disorder view's class {DISORDERED} is not a token.")
    gathered: dict[str, _Runs] = {}
    for protein, entries in zip(located["protein_id"], located["features"], strict=True):
        runs = gathered.setdefault(protein, _Runs())
        for entry in entries:
            runs.add(token_of[str(entry["feature"])], ((int(run["start"]), int(run["end"])) for run in entry["residues"]),
                     ((int(run["start"]), int(run["end"])) for run in entry["masked"]))
    for protein, entries in zip(sites["protein_id"], sites["sites"], strict=True):
        runs = gathered.setdefault(protein, _Runs())
        for entry in entries:
            runs.add(token_of[str(entry["modification"])], runs_of(entry["positions"]), runs_of(entry["masked"]))
    for protein, disordered, masked in zip(disorder["protein_id"], disorder["disordered"], disorder["masked"], strict=True):
        gathered.setdefault(protein, _Runs()).add(token_of[DISORDERED], runs_of(disordered), runs_of(masked))
    for protein, term, start, end in zip(signatures["protein_id"], signatures["term_id"], signatures["start"], signatures["end"],
                                         strict=True):
        gathered.setdefault(protein, _Runs()).add(token_of[str(term)], [(int(start), int(end))], [])
    rows = []
    for protein in sorted(gathered):
        runs = gathered[protein]
        rows.append({"protein_id": protein, **dict(zip(LOCAL_COLUMNS, (*_columns(runs.positive), *_columns(runs.masked)),
                                                       strict=True))})
    return pd.DataFrame(rows, columns=["protein_id", *LOCAL_COLUMNS])


@dataclass(frozen=True)
class SignatureSpans:
    """InterPro's and Pfam's located matches kept as local runs, and how many the release's rules leave out."""

    spans: pd.DataFrame  # protein_id, term_id, start, end
    off_sequence: int  # matches off their protein's sequence, left out as the release's located view does
    outside_vocabulary: int  # distinct spans of a term that is no token: fewer than 10 train proteins carry it at a label tier
    terms_outside_vocabulary: int  # their distinct terms


def signature_spans(assertions: pd.DataFrame, lengths: Mapping[str, int], terms: Collection[str]) -> SignatureSpans:
    """InterPro's and Pfam's located matches of the given proteins (`lengths`, each protein's residues) at the signature
    tier, from the assertion table's rows (`protein_id`, `term_id`, `aspect`, `tier`, `negated`, `start`, `end`), as spans
    of the vocabulary's `terms`. A match off its sequence is left out, as the release's located view leaves it, and so is
    one of a term the vocabulary lacks, which labels no protein; both are counted."""
    wanted = assertions[assertions["aspect"].isin(SIGNATURE_ASPECTS) & (assertions["tier"] == SIGNATURE_TIER)
                        & ~assertions["negated"].astype(bool) & assertions["start"].notna() & assertions["end"].notna()
                        & assertions["protein_id"].isin(lengths)]
    length = wanted["protein_id"].map(lengths).to_numpy()  # (s,)
    start, end = wanted["start"].to_numpy(dtype=np.int64), wanted["end"].to_numpy(dtype=np.int64)  # (s,) each
    inside = (start >= 1) & (start <= end) & (end <= length)  # (s,)
    spans = wanted.loc[inside, ["protein_id", "term_id", "start", "end"]].drop_duplicates()
    known = spans["term_id"].isin(set(terms)).to_numpy()  # (u,)
    return SignatureSpans(spans[known].reset_index(drop=True).astype({"start": np.int64, "end": np.int64}),
                          int((~inside).sum()), int((~known).sum()), int(spans.loc[~known, "term_id"].nunique()))


def ancestor_matrix(words: Vocabulary, hierarchy: pd.DataFrame) -> sp.csr_matrix:
    """Row i marks the tokens related to token i from above: every token whose concept is an ancestor of i's along the
    hierarchy's parent relations (`RELATED_EDGES`), every other token of i's own concept (the same InterPro entry read
    protein-level and located, for one), and a located aspect's type term above its other classes (`TYPE_TERMS`)."""
    terms = words.terms
    concept = list(zip(terms["source_database"], terms["accession"], strict=True))  # (t,)
    tokens_of: dict[tuple[str, str], list[int]] = {}
    for token, key in enumerate(concept):
        tokens_of.setdefault(key, []).append(token)
    edges = hierarchy[hierarchy["relation"].isin(RELATED_EDGES)]
    parents: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for child_database, child, parent_database, parent in zip(edges["child_database"], edges["child"], edges["parent_database"],
                                                              edges["parent"], strict=True):
        parents.setdefault((child_database, child), set()).add((parent_database, parent))
    closure: dict[tuple[str, str], set[tuple[str, str]]] = {}

    def above(key: tuple[str, str]) -> set[tuple[str, str]]:
        if key not in closure:
            closure[key] = set()  # a cycle stops here rather than recursing
            found: set[tuple[str, str]] = set()
            for parent in parents.get(key, ()):
                found |= {parent} | above(parent)
            closure[key] = found - {key}
        return closure[key]

    token_of = words.token_of()
    rows, columns = [], []
    for token, key in enumerate(concept):
        related = {other for ancestor in above(key) for other in tokens_of.get(ancestor, ())}
        related |= set(tokens_of[key]) - {token}
        type_term = TYPE_TERMS.get(str(terms["aspect"].iloc[token]))
        if type_term in token_of and token_of[type_term] != token:
            related.add(token_of[type_term])
        rows.extend([token] * len(related))
        columns.extend(sorted(related))
    size = words.size
    return sp.csr_matrix((np.ones(len(rows), dtype=bool), (rows, columns)), shape=(size, size))  # (t, t)


def read_pool(folder: Path) -> pd.DataFrame:
    """Every pooled protein of a release folder (`RELEASE_FILES`) with its split, eligibility, review state, accessions
    and 0.3-identity cluster: `split.atlas_sample`'s pool."""
    tables = folder / "tables"
    pool = (pd.read_parquet(tables / "split.parquet", columns=["protein_id", "split", "eligible"])
            .merge(pd.read_parquet(tables / "proteins.parquet", columns=["protein_id", "accessions", "reviewed"]),
                   on="protein_id", validate="one_to_one")
            .merge(pd.read_parquet(tables / "clusters.parquet", columns=["protein_id", CLUSTER_LEVEL]), on="protein_id",
                   validate="one_to_one"))
    return pool.rename(columns={CLUSTER_LEVEL: "cluster"})


def read_examined(folder: Path) -> frozenset[str]:
    """The accessions the atlas study held out, from its release's validation and test shards (`EXAMINED_FILES`)."""
    shards = sorted(path for pattern in EXAMINED_FILES for path in folder.glob(pattern))
    if len(shards) < 2:
        raise ValueError(f"{folder} lacks the atlas study's validation and test shards.")
    return frozenset(accession for shard in shards for accession in pd.read_parquet(shard, columns=["accession"])["accession"])


def _filtered(path: Path, columns: Sequence[str], proteins: Collection[str], condition: pc.Expression | None = None) -> pd.DataFrame:
    wanted = pc.is_in(pc.field("protein_id"), value_set=pa.array(sorted(proteins), pa.string()))
    return ds.dataset(path).to_table(columns=list(columns), filter=wanted if condition is None else wanted & condition).to_pandas()


def read_proteins(folder: Path, proteins: Collection[str], columns: Sequence[str]) -> pd.DataFrame:
    """Some proteins' rows of the release's protein table."""
    return _filtered(folder / "tables" / "proteins.parquet", columns, proteins)


def read_rows(folder: Path, proteins: Collection[str]) -> pd.DataFrame:
    """The released whole-vocabulary rows of some proteins, from every split's file."""
    columns = ("protein_id", "tokens", "masked", "observed_units")
    return pd.concat([_filtered(folder / f"{split}.parquet", columns, proteins) for split in SPLITS], ignore_index=True)


def read_residue_tables(folder: Path, proteins: Collection[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """The located feature, modification site and disordered region rows of some proteins."""
    columns = {"located_features": ("protein_id", "features"), "modification_sites": ("protein_id", "sites"),
               "disordered_regions": ("protein_id", "disordered", "masked")}
    return tuple(_filtered(folder / "tables" / f"{name}.parquet", columns[name], proteins) for name in RESIDUE_TABLES)


def read_signature_assertions(folder: Path, proteins: Collection[str]) -> pd.DataFrame:
    """The assertions of InterPro's and Pfam's located matches for some proteins, for `signature_spans`."""
    columns = ("protein_id", "term_id", "aspect", "tier", "negated", "start", "end")
    located = pc.is_in(pc.field("aspect"), value_set=pa.array(list(SIGNATURE_ASPECTS), pa.string()))
    return _filtered(folder / "tables" / "assertions.parquet", columns, proteins, located)


def read_vocabulary(folder: Path) -> tuple[Vocabulary, pd.DataFrame]:
    """The release's vocabulary, its site classes' amino acids read from the site table, and its hierarchy."""
    tables = folder / "tables"
    sites = pd.read_parquet(tables / "modification_sites.parquet", columns=["sites"])
    words = vocabulary(pd.read_parquet(tables / "vocabulary.parquet"), pd.read_parquet(tables / "tokens.parquet"), site_residues(sites))
    return words, pd.read_parquet(tables / "hierarchy.parquet")
