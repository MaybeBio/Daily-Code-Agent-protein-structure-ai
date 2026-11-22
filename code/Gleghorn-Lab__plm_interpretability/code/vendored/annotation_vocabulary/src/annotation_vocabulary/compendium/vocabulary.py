"""The compendium's vocabulary: every term with its support per tier and per split, its audit, name, definition and depth.

A protein's tier for a term is the best of its positive assertions' tiers. A term enters the vocabulary when at least
`MINIMUM_SUPPORT` train proteins carry it at a label tier (experimental, signature or curated; Logan, 2026-10-20) and no audit
flag holds it out: the GO stoplist (the roots, binding, protein binding, identical protein binding), and the family databases
whose licences keep them out of labels, CAZy and TCDB. Each held-out split's support counts the tiers it scores, validation and test experimental
and signature, calibration every label tier, as the global split's rows do.
"""

from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc

from collections import Counter
from collections.abc import Iterable, Mapping

from .ontologies import Edge
from .tables import split_frame
from .tiers import GO_STOPLIST, LABEL_TIERS, SCORED_TIERS, TIERS


MINIMUM_SUPPORT = 10
# What names a term, and the pooled assertion columns the vocabulary reads.
DESCRIBED = ["term_id", "aspect", "fundamental_aspect", "source_database", "term"]
VOCABULARY_COLUMNS = ["protein_id", *DESCRIBED, "label", "tier", "negated"]
# Family databases read from UniProt's cross-references whose licences hold them out of labels (Logan, 2026-10-20: they join
# after a licence check). Read on 2026-10-22: CAZy states only a copyright line and TCDB's share-alike would bind the release;
# MEROPS's LGPL lets its families label.
LICENCE_PENDING = frozenset({"cazy", "tcdb"})
SPLIT_TIERS = {"train": LABEL_TIERS, "validation": SCORED_TIERS, "test": SCORED_TIERS, "calibration": LABEL_TIERS}
VOCABULARY_SCHEMA = pa.schema([
    ("term_id", pa.string()), ("aspect", pa.string()), ("fundamental_aspect", pa.string()), ("source_database", pa.string()),
    ("accession", pa.string()), ("name", pa.string()), ("definition", pa.string()), ("depth", pa.int32()),
    *[(f"proteins_{tier}", pa.int64()) for tier in TIERS],
    *[(f"{split}_support", pa.int64()) for split in SPLIT_TIERS],
    ("in_vocabulary", pa.bool_()), ("audit_flag", pa.string()),
])


def tier_ranks(tiers: pa.ChunkedArray | pa.Array) -> pa.Array:
    """Each tier's rank in `TIERS`, experimental 0 to skip 4."""
    return pc.index_in(tiers, value_set=pa.array(TIERS))


def best_tiers(assertions: pa.Table) -> pa.Table:
    """(protein_id, term_id, rank): each protein's best tier rank for each term it is positively asserted for."""
    positive = assertions.filter(pc.invert(assertions["negated"]))
    table = pa.table({"protein_id": positive["protein_id"], "term_id": positive["term_id"], "rank": tier_ranks(positive["tier"])})
    return table.group_by(["protein_id", "term_id"]).aggregate([("rank", "min")]).rename_columns({"rank_min": "rank"})


def audit_flag(aspect: str, source_database: str, accession: str) -> str:
    """Why a term is held out of the vocabulary whatever its support, or "" when nothing holds it out."""
    if source_database == "GO" and accession in GO_STOPLIST:
        return "go_stoplist"
    if aspect in LICENCE_PENDING:
        return "licence_pending"
    return ""


def depths(edges: Iterable[Edge]) -> dict[tuple[str, str], int]:
    """Each concept's depth: the longest chain of `is_a`, `part_of`, `ec_parent` or `lineage` edges from it to a root."""
    up: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for child_database, child, parent_database, parent, relation in edges:
        if relation in ("is_a", "part_of", "ec_parent", "lineage"):
            up.setdefault((child_database, child), []).append((parent_database, parent))
    known: dict[tuple[str, str], int] = {}
    for node in list(up):
        stack = [(node, False)]
        visiting: set[tuple[str, str]] = set()
        while stack:
            current, expanded = stack.pop()
            if current in known:
                continue
            parents = up.get(current, [])
            if expanded or not parents:
                visiting.discard(current)
                known[current] = 1 + max((known.get(parent, 0) for parent in parents), default=-1)
                continue
            visiting.add(current)
            stack.append((current, True))
            # A cycle (none should exist) is cut where it closes, so every node still gets a depth.
            stack.extend((parent, False) for parent in parents if parent not in known and parent not in visiting)
    return known


def build_vocabulary(
    parts: Iterable[pa.Table], protein_to_split: Mapping[str, str], *, names: Mapping[tuple[str, str], tuple[str, str]],
    edges: Iterable[Edge], minimum_support: int = MINIMUM_SUPPORT,
) -> pa.Table:
    """One row per term (`VOCABULARY_SCHEMA`), in term-id order.

    `parts` are the pooled assertions (`VOCABULARY_COLUMNS` of them at least), whole or a partition at a time, each protein's rows in
    one part, since its tier for a term is the best of them. `names` maps a concept to its (name, definition) from the ontologies; a
    term no ontology names takes the label its assertions wrote. `protein_to_split` assigns every pooled protein.
    """
    splits = split_frame(protein_to_split)
    counts: dict[str, Counter[str]] = {}
    meta: dict[str, tuple[str, str, str, str]] = {}
    labels: dict[str, str] = {}
    for assertions in parts:
        best = best_tiers(assertions).join(splits, keys="protein_id", join_type="inner", use_threads=True)
        by_tier = best.group_by(["term_id", "rank"]).aggregate([("protein_id", "count")])
        for term_id, rank, count in zip(*(by_tier[name].to_pylist() for name in ("term_id", "rank", "protein_id_count")), strict=True):
            counts.setdefault(term_id, Counter())[f"proteins_{TIERS[rank]}"] += count
        by_split = best.group_by(["term_id", "split", "rank"]).aggregate([("protein_id", "count")])
        for term_id, split, rank, count in zip(*(by_split[name].to_pylist() for name in ("term_id", "split", "rank", "protein_id_count")), strict=True):
            if TIERS[rank] in SPLIT_TIERS[split]:
                counts.setdefault(term_id, Counter())[f"{split}_support"] += count
        described = assertions.group_by(DESCRIBED).aggregate([])
        meta.update((row[0], row[1:]) for row in zip(*(described[name].to_pylist() for name in DESCRIBED), strict=True))
        labelled = assertions.filter(pc.not_equal(assertions["label"], "")).group_by("term_id").aggregate([("label", "min")])
        for term_id, label in zip(labelled["term_id"].to_pylist(), labelled["label_min"].to_pylist(), strict=True):
            labels[term_id] = min(label, labels.get(term_id, label))
    depth = depths(edges)
    rows: dict[str, list[object]] = {name: [] for name in VOCABULARY_SCHEMA.names}
    for term_id in sorted(counts):
        aspect, fundamental, database, term = meta[term_id]
        name, definition = names.get((database, term), (labels.get(term_id, term), ""))
        flag = audit_flag(aspect, database, term)
        row = counts[term_id]
        values = {
            "term_id": term_id, "aspect": aspect, "fundamental_aspect": fundamental, "source_database": database, "accession": term,
            "name": name, "definition": definition, "depth": depth.get((database, term), 0),
            **{f"proteins_{tier}": row.get(f"proteins_{tier}", 0) for tier in TIERS},
            **{f"{split}_support": row.get(f"{split}_support", 0) for split in SPLIT_TIERS},
            "in_vocabulary": not flag and row.get("train_support", 0) >= minimum_support, "audit_flag": flag,
        }
        for column, value in values.items():
            rows[column].append(value)
    return pa.table(rows, schema=VOCABULARY_SCHEMA)
