"""Join the sources into the protein pool: one row per distinct sequence, with every term it is asserted for and why.

A protein is in the pool when its sequence is a whole, ordinary protein of at most 2,046 residues and at least one assertion
of a source that needs experimental evidence (GOA, UniProtKB) names a term of the release. InterPro matches then add terms to
those proteins and never admit one. Two accessions with one sequence are one row, with the union of their assertions, because
the split keeps a sequence in one place. A term that fewer than `minimum_support` pool sequences carry can never reach the
vocabulary, so it is dropped here, and a protein left with no term leaves the pool, both counted.
"""

from __future__ import annotations

import hashlib
import json
import pyarrow as pa
import pyarrow.parquet as pq

from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from foundry.protein.sequence import ProteinTextError, normalize_protein_ascii
from .terms import OBO_NAMESPACE_ASPECTS, Assertion, has_experimental_source
from .uniprot_entries import EntryExtract
from ..schema import TermKey
from ..sources.obo import OBOIndex


MAX_RESIDUES = 2046
MINIMUM_SUPPORT = 10


def protein_id(sequence: str) -> str:
    """SHA-256 of the sequence text, the release's one identity for a protein."""
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def format_provenance(items: Iterable[str]) -> str:
    """`source=code,code;source=code` from `source=code` items, sources and codes sorted, each once."""
    codes: dict[str, set[str]] = defaultdict(set)
    for item in items:
        source, _, code = item.partition("=")
        codes[source].add(code)
    return ";".join(f"{source}={','.join(sorted(found))}" for source, found in sorted(codes.items()))


@dataclass(slots=True)
class PoolAudit:
    """What the pool kept and set aside, each count by its reason."""

    entries: Counter[str] = field(default_factory=Counter)
    assertions: Counter[str] = field(default_factory=Counter)
    pool: Counter[str] = field(default_factory=Counter)

    def to_dict(self) -> dict[str, object]:
        return {
            "entries": dict(sorted(self.entries.items())), "assertions": dict(sorted(self.assertions.items())),
            "pool": dict(sorted(self.pool.items())),
        }


@dataclass(frozen=True, slots=True)
class PoolProtein:
    """One distinct sequence: its accessions and, for each term, the provenance text of its assertions."""

    protein_id: str
    sequence: str
    accessions: tuple[str, ...]
    datasets: tuple[str, ...]
    taxon_id: int | None
    provenance: Mapping[TermKey, str]


@dataclass(frozen=True, slots=True)
class Pool:
    proteins: tuple[PoolProtein, ...]
    labels: Mapping[TermKey, str]
    audit: PoolAudit


class PoolBuilder:
    """Collects entries and assertions in any order, then `build` joins them."""

    def __init__(self, ontology: OBOIndex, *, max_residues: int = MAX_RESIDUES, minimum_support: int = MINIMUM_SUPPORT) -> None:
        self._ontology = ontology
        self._max_residues = max_residues
        self._minimum_support = minimum_support
        self._entries: dict[str, EntryExtract] = {}
        self._terms: dict[str, dict[TermKey, set[str]]] = {}
        self._labels: dict[TermKey, str] = {}
        self._go: dict[str, tuple[TermKey, str] | None] = {}
        self._interned: dict[TermKey, TermKey] = {}
        self.audit = PoolAudit()

    def add_entry(self, extract: EntryExtract) -> bool:
        """Keep an entry whose sequence can be a row; count the reason otherwise."""
        reason = self._entry_exclusion(extract)
        self.audit.entries[reason or "kept"] += 1
        if reason is None:
            self._entries[extract.accession] = extract
        return reason is None

    def _entry_exclusion(self, extract: EntryExtract) -> str | None:
        if extract.fragment:
            return "fragment"
        if len(extract.sequence) > self._max_residues:
            return "over_length_limit"
        try:
            normalize_protein_ascii(extract.sequence)
        except ProteinTextError:
            return "invalid_residues"
        return None

    def _resolve_go(self, term: TermKey) -> tuple[TermKey, str] | None:
        """The current GO term of an asserted identifier: an alternate id follows its term and an obsolete one its only replacement."""
        cached = self._go.get(term.accession, False)
        if cached is not False:
            return cached if cached is None or cached[0].aspect == term.aspect else None
        found = self._ontology.lookup(term.accession)
        if found is None:
            targets = self._ontology.replacements(term.accession)
            found = self._ontology.lookup(targets[0]) if len(targets) == 1 else None
        resolved = None
        if found is not None and found.namespace in OBO_NAMESPACE_ASPECTS:
            resolved = (TermKey(OBO_NAMESPACE_ASPECTS[found.namespace], "GO", found.id), found.name or found.id)
        self._go[term.accession] = resolved
        return resolved if resolved is None or resolved[0].aspect == term.aspect else None

    def add_assertion(self, assertion: Assertion) -> bool:
        """Record an assertion about a kept entry; GO identifiers resolve against the ontology first. Returns whether it was kept."""
        if assertion.accession not in self._entries:
            self.audit.assertions["entry_not_in_pool"] += 1
            return False
        term, label = assertion.term, assertion.label
        if term.aspect.startswith("go_"):
            resolved = self._resolve_go(term)
            if resolved is None:
                self.audit.assertions["go_unresolved_or_obsolete"] += 1
                return False
            term, label = resolved
        term = self._interned.setdefault(term, term)
        self._labels.setdefault(term, label)
        self._terms.setdefault(assertion.accession, {}).setdefault(term, set()).add(assertion.provenance)
        self.audit.assertions[f"kept:{assertion.source}"] += 1
        return True

    def build(self) -> Pool:
        """One row per distinct sequence, restricted to terms that enough pool sequences carry."""
        by_sequence: dict[str, list[str]] = defaultdict(list)
        for accession, extract in self._entries.items():
            by_sequence[extract.sequence].append(accession)
        merged: dict[str, tuple[list[str], dict[TermKey, set[str]]]] = {}
        for sequence, accessions in by_sequence.items():
            terms: dict[TermKey, set[str]] = {}
            for accession in accessions:
                for term, provenance in self._terms.get(accession, {}).items():
                    terms.setdefault(term, set()).update(provenance)
            experimental = any(has_experimental_source(item) for found in terms.values() for item in found)
            self.audit.pool["with_experimental_assertion" if experimental else "without_experimental_assertion"] += 1
            if experimental:
                merged[sequence] = (sorted(accessions), terms)
        support = Counter(term for _, terms in merged.values() for term in terms)
        supported = {term for term, count in support.items() if count >= self._minimum_support}
        self.audit.pool["terms_seen"] = len(support)
        self.audit.pool["terms_supported"] = len(supported)
        proteins: list[PoolProtein] = []
        for sequence, (accessions, terms) in merged.items():
            kept = {term: format_provenance(found) for term, found in terms.items() if term in supported}
            if not kept:
                self.audit.pool["no_supported_term"] += 1
                continue
            extracts = [self._entries[accession] for accession in accessions]
            taxa = sorted({extract.taxon_id for extract in extracts if extract.taxon_id is not None})
            proteins.append(PoolProtein(
                protein_id(sequence), sequence, tuple(accessions), tuple(sorted({extract.dataset for extract in extracts})),
                taxa[0] if taxa else None, kept,
            ))
        proteins.sort(key=lambda protein: protein.protein_id)
        self.audit.pool["proteins"] = len(proteins)
        return Pool(tuple(proteins), {term: self._labels[term] for term in supported}, self.audit)


def drop_aspects(pool: Pool, aspects: Collection[str]) -> tuple[Pool, dict[str, int]]:
    """The pool without the terms of `aspects`, and what left: the terms of each aspect, and the proteins left with no term."""
    removed = Counter(term.aspect for term in pool.labels if term.aspect in aspects)
    proteins: list[PoolProtein] = []
    stranded = 0
    for protein in pool.proteins:
        kept = {term: text for term, text in protein.provenance.items() if term.aspect not in aspects}
        if not kept:
            stranded += 1
        else:
            proteins.append(protein if len(kept) == len(protein.provenance) else replace(protein, provenance=kept))
    labels = {term: label for term, label in pool.labels.items() if term.aspect not in aspects}
    return replace(pool, proteins=tuple(proteins), labels=labels), {**{f"terms:{name}": removed[name] for name in sorted(aspects)}, "proteins_left_with_no_term": stranded}


POOL_FILE = "pool.parquet"
LABEL_FILE = "pool_labels.parquet"
AUDIT_FILE = "pool_audit.json"


def write_pool(directory: Path, pool: Pool) -> None:
    """Save a pool so that a later stage reads it back unchanged: proteins, term labels and the audit."""
    directory.mkdir(parents=True, exist_ok=True)
    proteins = pa.table({
        "protein_id": [item.protein_id for item in pool.proteins],
        "sequence": [item.sequence for item in pool.proteins],
        "accessions": pa.array([list(item.accessions) for item in pool.proteins], pa.list_(pa.string())),
        "datasets": pa.array([list(item.datasets) for item in pool.proteins], pa.list_(pa.string())),
        "taxon_id": pa.array([item.taxon_id for item in pool.proteins], pa.int64()),
        "term_ids": pa.array([[term.term_id for term in item.provenance] for item in pool.proteins], pa.list_(pa.string())),
        "provenance": pa.array([list(item.provenance.values()) for item in pool.proteins], pa.list_(pa.string())),
    })
    pq.write_table(proteins, directory / POOL_FILE, compression="zstd")
    pq.write_table(
        pa.table({"term_id": [term.term_id for term in pool.labels], "label": list(pool.labels.values())}),
        directory / LABEL_FILE, compression="zstd",
    )
    (directory / AUDIT_FILE).write_text(json.dumps(pool.audit.to_dict(), indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def read_pool(directory: Path) -> Pool:
    """The pool `write_pool` saved."""
    table = pq.read_table(directory / POOL_FILE).to_pydict()
    keys: dict[str, TermKey] = {}
    proteins = tuple(
        PoolProtein(
            table["protein_id"][index], table["sequence"][index], tuple(table["accessions"][index]), tuple(table["datasets"][index]),
            table["taxon_id"][index],
            {keys.setdefault(term_id, TermKey.from_term_id(term_id)): text for term_id, text in zip(table["term_ids"][index], table["provenance"][index], strict=True)},
        )
        for index in range(len(table["protein_id"]))
    )
    labels = pq.read_table(directory / LABEL_FILE).to_pydict()
    audit = PoolAudit()
    record = json.loads((directory / AUDIT_FILE).read_text(encoding="utf-8"))
    audit.entries.update(record["entries"])
    audit.assertions.update(record["assertions"])
    audit.pool.update(record["pool"])
    return Pool(proteins, {TermKey.from_term_id(term_id): label for term_id, label in zip(labels["term_id"], labels["label"], strict=True)}, audit)
