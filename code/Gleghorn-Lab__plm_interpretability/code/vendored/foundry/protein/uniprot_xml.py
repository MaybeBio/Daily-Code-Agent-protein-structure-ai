"""Entry-level readers shared by every source that extracts facts from UniProtKB XML.

An entry states its evidence in ``evidence`` elements that its comments name by key, and a key reaches its publication
either directly or through the entry's own reference list. These helpers resolve that once, so every extraction gives
a key the same citations and refuses the same malformed entry. They read reviewed (Swiss-Prot) and unreviewed (TrEMBL)
entries alike; a caller that wants only reviewed ones says so in `entry_accession`.
"""

from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET
import pyarrow as pa
import pyarrow.parquet as pq

from collections.abc import Collection, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any, TypedDict
from tqdm.auto import tqdm

from foundry.digests import sha256_file


UNIPROT_NAMESPACES = ("{http://uniprot.org/uniprot}", "{https://uniprot.org/uniprot}")
DATASETS = ("Swiss-Prot", "TrEMBL")
# How UniProt names each dataset's review status, for refusals a reader can act on.
REVIEW_STATUS = {"Swiss-Prot": "reviewed", "TrEMBL": "unreviewed"}
EXPERIMENTAL = "ECO:0000269"
PUBMED = ("PubMed",)
# UniProtKB's accession grammar (uniprot.org/help/accession_numbers), and an isoform's identifier, `<accession>-<n>`.
ACCESSION = re.compile(r"[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2}")
ISOFORM = re.compile(f"(?:{ACCESSION.pattern})-[1-9][0-9]*")
# Where a comment text's sentence ends: a full stop that white space follows.
SENTENCE_BOUNDARY = re.compile(r"(?<=\.)\s+")


class ExtractionError(ValueError):
    """The XML or the extract is not the coherent UniProtKB record the reader is specified for."""


class EvidenceRecord(TypedDict):
    """One evidence key of an entry: its ECO code and the sorted ``PubMed:<id>`` citations it resolves to."""

    key: str
    type: str
    citations: list[str]


class OrganismRecord(TypedDict):
    name: str | None
    taxon_id: str | None
    lineage: list[str]


def uniprot_namespace(root: ET.Element) -> str:
    """The namespace prefix of the collection element, refusing a document that is not a UniProt collection."""
    namespace = root.tag.removesuffix("uniprot")
    if namespace not in UNIPROT_NAMESPACES:
        raise ExtractionError("source XML lacks the UniProt collection namespace")
    return namespace


def iter_entries(xml: Path, *, expected_entries: int | None = None, progress: bool = False,
                 description: str = "Swiss-Prot entry facts") -> Iterator[tuple[ET.Element, str]]:
    """Each entry element of a gzipped UniProt XML with the document's namespace, in document order; the entry is freed
    once the consumer asks for the next, so the consumer takes what it needs from each before moving on."""
    with gzip.open(xml, "rb") as handle:
        reader = ET.iterparse(handle, events=("start", "end"))
        _, root = next(reader)
        namespace = uniprot_namespace(root)
        with tqdm(total=expected_entries, desc=description, unit="entries", disable=not progress, mininterval=30) as bar:
            for event, entry in reader:
                if event != "end" or entry.tag != namespace + "entry":
                    continue
                yield entry, namespace
                root.remove(entry)
                entry.clear()
                bar.update(1)


def write_facts_table(
    xml: Path, path: Path, facts: Iterable[Mapping[str, Any]], schema: pa.Schema, *, xml_sha256: str, expected_entries: int,
    row_group: int, unique: str = "accession",
) -> tuple[int, str]:
    """Write one row per entry of a pinned gzipped UniProt XML to a zstd Parquet table, in row groups of `row_group`.

    `facts` yields the rows, as `iter_entries` consumers do; `xml` is refused when its digest is not `xml_sha256`, before
    the table's directory is made, which must not exist yet. A value of the `unique` column seen twice raises, as does
    a row count other than `expected_entries`, the count the release states. Returns the rows written and the table's
    SHA-256, for the receipt the caller writes beside it. The benignity and production_suite readers each carried this
    until 2026-11-01.
    """
    if sha256_file(xml) != xml_sha256:
        raise ValueError(f"pinned UniProtKB XML changed: {xml}")
    path.parent.mkdir(parents=True, exist_ok=False)
    rows = 0
    seen: set[Any] = set()
    batch: list[Mapping[str, Any]] = []
    with pq.ParquetWriter(path, schema, compression="zstd") as writer:
        for row in facts:
            if row[unique] in seen:
                raise ValueError(f"primary {unique} {row[unique]} appears in two entries")
            seen.add(row[unique])
            batch.append(row)
            rows += 1
            if len(batch) == row_group:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                batch = []
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))
    if rows != expected_entries:
        raise ValueError(f"the XML holds {rows} entries and its release states {expected_entries}")
    return rows, sha256_file(path)


def entry_accession(entry: ET.Element, namespace: str, datasets: Collection[str] = DATASETS) -> str:
    """The primary accession of an entry of one of `datasets`; an entry of another dataset or without an accession is refused."""
    accession = entry.findtext(namespace + "accession")
    if entry.get("dataset") not in datasets or not accession:
        statuses = ", ".join(REVIEW_STATUS.get(name, name) for name in sorted(datasets))
        raise ExtractionError(f"every entry must be one of {sorted(datasets)} ({statuses}) with a primary accession")
    return accession


def canonical_sequence(entry: ET.Element, namespace: str, accession: str) -> tuple[ET.Element, str]:
    """The entry's one sequence element and its residues, checked against the length the entry states."""
    sequence = entry.find(namespace + "sequence")
    if sequence is None or len(entry.findall(namespace + "sequence")) != 1:
        raise ExtractionError(f"{accession}: an entry holds exactly one canonical sequence")
    residues = "".join((sequence.text or "").split()).upper()
    if str(len(residues)) != sequence.get("length"):
        raise ExtractionError(f"{accession}: the sequence length differs from its stated length")
    return sequence, residues


def publication_identifiers(element: ET.Element, namespace: str, types: Collection[str] = PUBMED) -> set[str]:
    """Each database reference of one of `types` directly below an element, written ``<type>:<id>``."""
    return {f"{item.get('type')}:{item.get('id', '')}" for item in element.findall(namespace + "dbReference") if item.get("type") in types}


def pubmed_identifiers(element: ET.Element, namespace: str) -> set[str]:
    """Each PubMed database reference directly below an element, written ``PubMed:<id>``."""
    return publication_identifiers(element, namespace, PUBMED)


def evidence_records(entry: ET.Element, namespace: str, citation_types: Collection[str] = PUBMED) -> dict[str, EvidenceRecord]:
    """Each evidence key of one entry with its ECO code and the citations it resolves to, directly or through a reference.

    A citation is a database reference of one of `citation_types`, written ``<type>:<id>``: PubMed identifiers alone by
    default, and ``("PubMed", "DOI")`` for a source whose older papers have a DOI and no PubMed identifier.
    """
    references: dict[str, ET.Element] = {}
    for reference in entry.findall(namespace + "reference"):
        key = reference.get("key")
        if key is None or key in references:
            raise ExtractionError("entry reference keys must be present and unique")
        references[key] = reference
    records: dict[str, EvidenceRecord] = {}
    for item in entry.findall(namespace + "evidence"):
        key, code = item.get("key"), item.get("type")
        if key is None or code is None or key in records:
            raise ExtractionError("entry evidence keys and types must be present and unique")
        found: set[str] = set()
        source = item.find(namespace + "source")
        if source is not None:
            found |= publication_identifiers(source, namespace, citation_types)
            pointer = source.get("ref")
            if pointer is not None:
                if pointer not in references:
                    raise ExtractionError("evidence names an absent entry reference")
                citation = references[pointer].find(namespace + "citation")
                if citation is not None:
                    found |= publication_identifiers(citation, namespace, citation_types)
        records[key] = {"key": key, "type": code, "citations": sorted(found)}
    return records


def evidence_for(keys: str | None, records: Mapping[str, EvidenceRecord], where: str, noun: str) -> list[EvidenceRecord]:
    """The evidence records a space-separated ``evidence`` attribute names, refusing a key the entry does not define."""
    names = (keys or "").split()
    if any(name not in records for name in names):
        raise ExtractionError(f"{where}: {noun} names an absent evidence key")
    return [records[name] for name in names]


def organism_record(entry: ET.Element, namespace: str) -> OrganismRecord:
    """The source organism's scientific name, NCBI taxon and lineage."""
    organism = entry.find(namespace + "organism")
    if organism is None:
        raise ExtractionError("entry has no organism")
    names = [item.text or "" for item in organism.findall(namespace + "name") if item.get("type") == "scientific"]
    taxa = [item.get("id", "") for item in organism.findall(namespace + "dbReference") if item.get("type") == "NCBI Taxonomy"]
    lineage = organism.find(namespace + "lineage")
    return {
        "name": names[0] if names else None, "taxon_id": taxa[0] if taxa else None,
        "lineage": [item.text or "" for item in lineage.findall(namespace + "taxon")] if lineage is not None else [],
    }


def sentences_of(text: str) -> list[str]:
    """The sentences of a comment text, split after each full stop that white space follows, whitespace collapsed."""
    return [part for part in SENTENCE_BOUNDARY.split(" ".join(text.split())) if part]
