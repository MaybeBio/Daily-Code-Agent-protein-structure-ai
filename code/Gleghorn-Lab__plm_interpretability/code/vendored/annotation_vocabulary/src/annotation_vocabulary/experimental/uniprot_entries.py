"""Read the experimentally supported assertions of UniProtKB XML entries, each paired with its own evidence.

An assertion is one XML element that names a term (an `ecNumber`, a catalytic `reaction`, a `cofactor`, a `disease`, a
subcellular `location`, `topology` or `orientation`), and the evidence it cites is the `evidence` attribute of that element
and no other: a comment that mixes experimental and inferred statements gives each statement its own verdict. The
`disease` comment is the exception the schema makes, because the evidence sits on the comment, so every disease of the
comment shares it. A comment scoped to an isoform, a chain or a peptide (`molecule`) describes another sequence than
the entry's and is excluded, counted by aspect, unless its caller counts that molecule the entry's own (`own_molecules`:
the displayed isoform, whose sequence the entry gives, for the compendium).

The same reader runs over Swiss-Prot and over the TrEMBL entries a REST fetch returns, since both write entries the same way.
"""

from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET
import pyarrow as pa
import pyarrow.parquet as pq

from collections import Counter
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from foundry.protein.experimental_evidence import is_experimental_eco
from foundry.protein.uniprot_xml import (
    EvidenceRecord,
    canonical_sequence,
    entry_accession,
    evidence_for,
    evidence_records,
    organism_record,
    uniprot_namespace,
)
from .terms import SOURCE_UNIPROT, Assertion
from ..schema import TermKey
from ..sources.uniprot_vocab import UniProtVocabularyRecord, iter_records


ENTRY_BATCH = 100_000
COMPLETE_EC = re.compile(r"[1-7]\.[0-9]+\.[0-9]+\.[0-9]+")
Admit = Callable[[TermKey, str, tuple[str, ...]], None]
Codes = Callable[[str | None, Mapping[str, EvidenceRecord], str], tuple[str, ...]]
LOCATION_ELEMENTS = {
    "location": "subcellular_location", "topology": "membrane_topology", "orientation": "membrane_orientation",
}


@dataclass(frozen=True, slots=True)
class SubcellVocabulary:
    """The preferred names of `subcell.txt`, by kind: a compartment, a membrane topology or a membrane orientation."""

    records: Mapping[str, Mapping[str, UniProtVocabularyRecord]]

    @classmethod
    def from_file(cls, path: Path) -> SubcellVocabulary:
        """Read the three kinds of record of a `subcell.txt`; a name that two records of one kind share is refused."""
        records: dict[str, dict[str, UniProtVocabularyRecord]] = {kind: {} for kind in LOCATION_ELEMENTS.values()}
        with path.open(encoding="utf-8") as handle:
            for record in iter_records(handle):
                if record.record_type not in records:
                    continue
                if record.label in records[record.record_type]:
                    raise ValueError(f"subcell.txt names two {record.record_type} records {record.label!r}")
                records[record.record_type][record.label] = record
        if not all(records.values()):
            raise ValueError("subcell.txt holds no compartment, topology or orientation record")
        return cls(records)

    def term(self, aspect: str, name: str) -> tuple[TermKey, str] | None:
        """The term and label of a preferred name in one kind, or None for a name the vocabulary does not hold."""
        record = self.records[aspect].get(name)
        if record is None:
            return None
        return TermKey(aspect, record.source_database, record.stable_id), record.label


@dataclass(slots=True)
class EntryExtract:
    """One entry: what the sequence tables need, and its experimentally supported non-GO assertions."""

    accession: str
    dataset: str
    sequence: str
    fragment: bool
    taxon_id: int | None
    organism: str
    assertions: list[Assertion] = field(default_factory=list)


@dataclass(slots=True)
class EntryAudit:
    """Per aspect, the assertions seen and the ones admitted, and what else was set aside."""

    counts: Counter[str] = field(default_factory=Counter)
    evidence_types: Counter[str] = field(default_factory=Counter)

    def to_dict(self) -> dict[str, object]:
        return {"counts": dict(sorted(self.counts.items())), "evidence_types": dict(sorted(self.evidence_types.items()))}


def experimental_codes(keys: str | None, records: Mapping[str, EvidenceRecord], where: str) -> tuple[str, ...]:
    """The distinct experimental evidence types among an element's evidence keys, sorted; empty when none is experimental."""
    cited = evidence_for(keys, records, where, "element")
    return tuple(sorted({item["type"] for item in cited if is_experimental_eco(item["type"])}))


def evidence_codes(keys: str | None, records: Mapping[str, EvidenceRecord], where: str) -> tuple[str, ...]:
    """Every distinct evidence type among an element's evidence keys, sorted; empty when it cites none."""
    return tuple(sorted({item["type"] for item in evidence_for(keys, records, where, "element")}))


def extract_entry(entry: ET.Element, namespace: str, vocabulary: SubcellVocabulary, audit: EntryAudit) -> EntryExtract:
    """One entry's sequence facts and its admitted assertions."""
    accession = entry_accession(entry, namespace)
    sequence_element, residues = canonical_sequence(entry, namespace, accession)
    organism = organism_record(entry, namespace)
    records = evidence_records(entry, namespace)
    audit.evidence_types.update(item["type"] for item in records.values())
    taxon = organism["taxon_id"]
    extract = EntryExtract(
        accession, entry.get("dataset", ""), residues, sequence_element.get("fragment") is not None,
        int(taxon) if taxon else None, organism["name"] or "",
    )
    seen: set[tuple[TermKey, str]] = set()

    def admit(term: TermKey, label: str, codes: tuple[str, ...]) -> None:
        audit.counts[f"{term.aspect}:seen"] += 1
        for code in codes:
            if (term, code) not in seen:
                seen.add((term, code))
                extract.assertions.append(Assertion(accession, term, label, SOURCE_UNIPROT, code))
        if codes:
            audit.counts[f"{term.aspect}:experimental"] += 1

    read_terms(entry, namespace, records, vocabulary, admit, audit, accession)
    return extract


def displayed_isoform(entry: ET.Element, namespace: str) -> frozenset[str]:
    """The molecule names a comment scoped to the entry's displayed isoform carries: "Isoform " and each of that isoform's names,
    from the alternative products comment; none when the entry describes no isoform."""
    return frozenset(
        f"Isoform {' '.join((name.text or '').split())}" for isoform in entry.iter(namespace + "isoform")
        if isoform.find(f"{namespace}sequence[@type='displayed']") is not None for name in isoform.findall(namespace + "name")
    )


def scoped_elsewhere(comment: ET.Element, namespace: str, own_molecules: Collection[str], kind: str, audit: EntryAudit) -> bool:
    """Whether a comment is scoped to a molecule other than `own_molecules`, counted by kind either way."""
    molecule = comment.find(namespace + "molecule")
    if molecule is None:
        return False
    if " ".join((molecule.text or "").split()) in own_molecules:
        audit.counts[f"{kind}:own_molecule"] += 1
        return False
    audit.counts[f"{kind}:molecule_scoped"] += 1
    return True


def read_terms(
    entry: ET.Element, namespace: str, records: Mapping[str, EvidenceRecord], vocabulary: SubcellVocabulary, admit: Admit,
    audit: EntryAudit, where: str, codes: Codes = experimental_codes, own_molecules: Collection[str] = (),
) -> None:
    """Pass `admit` each term an entry's EC numbers and comments name, with the evidence types `codes` keeps for it; a comment
    scoped to a molecule is read only when `own_molecules` holds that molecule."""
    for element in entry.iter(namespace + "ecNumber"):
        number = (element.text or "").strip()
        if COMPLETE_EC.fullmatch(number):
            admit(TermKey("ec", "EC", number), f"EC {number}", codes(element.get("evidence"), records, where))
        else:
            audit.counts["ec:incomplete"] += 1
    for comment in entry.findall(namespace + "comment"):
        kind = comment.get("type")
        if kind not in _COMMENT_READERS or scoped_elsewhere(comment, namespace, own_molecules, kind, audit):
            continue
        _COMMENT_READERS[kind](comment, namespace, records, vocabulary, admit, audit, where, codes)


def _catalytic_activity(comment: ET.Element, namespace: str, records: Mapping[str, EvidenceRecord], _vocabulary: SubcellVocabulary,
                        admit: Admit, audit: EntryAudit, where: str, codes: Codes) -> None:
    for reaction in comment.findall(namespace + "reaction"):
        cited = codes(reaction.get("evidence"), records, where)
        text = " ".join((reaction.findtext(namespace + "text") or "").split())
        for reference in reaction.findall(namespace + "dbReference"):
            identifier = reference.get("id", "")
            if reference.get("type") == "Rhea" and identifier.startswith("RHEA:"):
                admit(TermKey("rhea", "Rhea", identifier), text or identifier, cited)
            elif reference.get("type") == "EC" and COMPLETE_EC.fullmatch(identifier):
                admit(TermKey("ec", "EC", identifier), f"EC {identifier}", cited)


def _cofactor(comment: ET.Element, namespace: str, records: Mapping[str, EvidenceRecord], _vocabulary: SubcellVocabulary,
              admit: Admit, audit: EntryAudit, where: str, codes: Codes) -> None:
    for cofactor in comment.findall(namespace + "cofactor"):
        cited = codes(cofactor.get("evidence"), records, where)
        name = (cofactor.findtext(namespace + "name") or "").strip()
        for reference in cofactor.findall(namespace + "dbReference"):
            identifier = reference.get("id", "")
            if reference.get("type") == "ChEBI" and identifier.startswith("CHEBI:"):
                admit(TermKey("cofactor", "ChEBI", identifier), name or identifier, cited)


def _disease(comment: ET.Element, namespace: str, records: Mapping[str, EvidenceRecord], _vocabulary: SubcellVocabulary,
             admit: Admit, audit: EntryAudit, where: str, codes: Codes) -> None:
    cited = codes(comment.get("evidence"), records, where)
    for disease in comment.findall(namespace + "disease"):
        name = (disease.findtext(namespace + "name") or "").strip()
        mim = [item.get("id", "") for item in disease.findall(namespace + "dbReference") if item.get("type") == "MIM"]
        identifier = disease.get("id", "")
        if mim and mim[0]:
            admit(TermKey("disease", "MIM", f"MIM:{mim[0]}"), name or f"MIM:{mim[0]}", cited)
        elif identifier.startswith("DI-"):
            admit(TermKey("disease", "UniProtKB-Disease", identifier), name or identifier, cited)
        else:
            audit.counts["disease:unidentified"] += 1


def _subcellular_location(comment: ET.Element, namespace: str, records: Mapping[str, EvidenceRecord], vocabulary: SubcellVocabulary,
                          admit: Admit, audit: EntryAudit, where: str, codes: Codes) -> None:
    for group in comment.findall(namespace + "subcellularLocation"):
        for element_name, aspect in LOCATION_ELEMENTS.items():
            for element in group.findall(namespace + element_name):
                found = vocabulary.term(aspect, (element.text or "").strip())
                if found is None:
                    audit.counts[f"{aspect}:unknown_name"] += 1
                    continue
                admit(found[0], found[1], codes(element.get("evidence"), records, where))


_COMMENT_READERS = {
    "catalytic activity": _catalytic_activity,
    "cofactor": _cofactor,
    "disease": _disease,
    "subcellular location": _subcellular_location,
}


def iter_entries(source: BinaryIO) -> Iterator[tuple[ET.Element, str]]:
    """Each `entry` element of a UniProt XML stream with the namespace prefix, cleared from memory once the caller moves on."""
    context = ET.iterparse(source, events=("start", "end"))
    event, root = next(context)
    namespace = uniprot_namespace(root)
    for event, element in context:
        if event == "end" and element.tag == namespace + "entry":
            yield element, namespace
            root.remove(element)
            element.clear()


def read_entry_file(path: Path) -> Iterator[tuple[ET.Element, str]]:
    """`iter_entries` over a plain or gzip UniProt XML file."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as handle:
        yield from iter_entries(handle)


ENTRY_SCHEMA = pa.schema([
    ("accession", pa.string()), ("dataset", pa.string()), ("sequence", pa.string()), ("fragment", pa.bool_()),
    ("taxon_id", pa.int64()), ("organism", pa.string()),
])


def write_entries(path: Path, extracts: Iterable[EntryExtract]) -> int:
    """Write the sequence facts of entries (never their assertions) to one Parquet file, atomically, and return the count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    count = 0
    with pq.ParquetWriter(temporary, ENTRY_SCHEMA, compression="zstd") as writer:
        batch: list[EntryExtract] = []
        for extract in extracts:
            batch.append(extract)
            if len(batch) >= ENTRY_BATCH:
                writer.write_table(_entry_table(batch))
                count += len(batch)
                batch = []
        if batch:
            writer.write_table(_entry_table(batch))
            count += len(batch)
    temporary.replace(path)
    return count


def _entry_table(extracts: Sequence[EntryExtract]) -> pa.Table:
    return pa.table({
        "accession": [item.accession for item in extracts], "dataset": [item.dataset for item in extracts],
        "sequence": [item.sequence for item in extracts], "fragment": [item.fragment for item in extracts],
        "taxon_id": [item.taxon_id for item in extracts], "organism": [item.organism for item in extracts],
    }, schema=ENTRY_SCHEMA)


def read_entries(path: Path) -> Iterator[EntryExtract]:
    """The entries of a file `write_entries` made, without assertions."""
    for batch in pq.ParquetFile(path).iter_batches(batch_size=ENTRY_BATCH):
        rows = batch.to_pydict()
        for index in range(batch.num_rows):
            yield EntryExtract(
                rows["accession"][index], rows["dataset"][index], rows["sequence"][index], rows["fragment"][index],
                rows["taxon_id"][index], rows["organism"][index],
            )
