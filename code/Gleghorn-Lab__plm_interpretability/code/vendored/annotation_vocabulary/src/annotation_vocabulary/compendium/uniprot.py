"""Read every annotation of a UniProtKB XML entry, each statement with its own evidence codes.

One reader serves Swiss-Prot's XML file and the TrEMBL entries streamed from the REST service, since both write entries alike.
From an entry it keeps:
- the entry's metadata (`tables.ENTRY_SCHEMA`), the shortcut registry's raw material;
- EC numbers, Rhea reactions, cofactors and subcellular locations, topologies and orientations, read by the experimental release's
  reader (`experimental.uniprot_entries.read_terms`) with every code instead of the experimental ones;
- keywords, each with its own codes;
- features with their positions: sites, regions, domains, membrane spans, signal and transit peptides, processing, modified
  residues, glycans, lipids and cross-links (named by `ptmlist.txt`, a cross-link by its partner's placeholder, each also a
  protein-level PTM term; a site joined to ubiquitin or a ubiquitin-like protein keeps UniProt's name) and secondary structure;
- the pathway, subunit (oligomeric state) and similarity (family) comments, a subunit state with the evidence of the sentence
  that states it (`sentence_evidence`);
- the CAZy, MEROPS and TCDB families it cross-references, held behind their licence checks in the vocabulary;
- the biophysicochemical statements, raw, for the measurement readers.
A comment scoped to an isoform or a chain (`molecule`) describes another sequence than the entry's and is skipped, counted, but
for one scoped to the displayed isoform, whose sequence is the entry's (`experimental.uniprot_entries.displayed_isoform`).
"""

from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET
import requests

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tqdm.auto import tqdm

from foundry.downloads.uniprot import UNIPROT_BASE, request_with_retry
from foundry.protein.uniprot_xml import (
    SENTENCE_BOUNDARY,
    EvidenceRecord,
    canonical_sequence,
    entry_accession,
    evidence_for,
    evidence_records,
    organism_record,
    sentences_of,
)
from .tiers import SOURCE_UNIPROT
from ..experimental.uniprot_entries import EntryAudit, SubcellVocabulary, displayed_isoform, evidence_codes, read_terms, scoped_elsewhere
from ..grammar import LOCAL_FEATURE_ASPECTS
from ..schema import TermKey
from ..sources.uniprot_vocab import UniProtVocabularyRecord, iter_records


PROTEIN_EXISTENCE = {
    "evidence at protein level": 1, "evidence at transcript level": 2, "inferred from homology": 3, "predicted": 4, "uncertain": 5,
}
# The XML's feature types, by the flat file's feature key. Features of variants, conflicts and sequence uncertainty are not
# annotations of the canonical protein and are not read; CHAIN names the mature protein and is no term.
FEATURE_KEYS = {
    "active site": "ACT_SITE", "binding site": "BINDING", "site": "SITE", "region of interest": "REGION", "domain": "DOMAIN",
    "short sequence motif": "MOTIF", "DNA-binding region": "DNA_BIND", "zinc finger region": "ZN_FING", "repeat": "REPEAT",
    "signal peptide": "SIGNAL", "transit peptide": "TRANSIT", "transmembrane region": "TRANSMEM", "intramembrane region": "INTRAMEM",
    "topological domain": "TOPO_DOM", "peptide": "PEPTIDE", "propeptide": "PROPEP", "modified residue": "MOD_RES",
    "glycosylation site": "CARBOHYD", "lipid moiety-binding region": "LIPID", "disulfide bond": "DISULFID", "cross-link": "CROSSLNK",
    "helix": "HELIX", "strand": "STRAND", "turn": "TURN", "coiled-coil region": "COILED", "compositionally biased region": "COMPBIAS",
    "initiator methionine": "INIT_MET",
}
FEATURE_ASPECTS = {**LOCAL_FEATURE_ASPECTS, "INIT_MET": "local_initiator_methionine"}
# Feature keys whose term is the modification `ptmlist.txt` names, and which also assert the protein-level PTM.
MODIFICATION_KEYS = frozenset({"MOD_RES", "CARBOHYD", "LIPID", "CROSSLNK"})
# A cross-link's partner, which `ptmlist.txt` names by a placeholder: UniProt's "(interchain with G-Cter in SUMO2)" is its
# "(interchain with G-...)" and "(with Trp-108)" its "(with W-...)", so a cross-link and its record meet with the partner as "...".
CROSSLINK_PARTNER = re.compile(r"\((interchain with|with) [^()]*\)?$")
# A cross-link to the C-terminus of ubiquitin or a ubiquitin-like protein, as the 2026_03 entries name them. Its site keeps UniProt's
# name, whose partner tells ubiquitination from SUMOylation, and it implies the Ubl conjugation keyword (`pool.linked_assertions`).
UBIQUITIN_LIKE = re.compile(
    r"\(interchain with [A-Z]-Cter in [^()]*?\b(?:ubiquitin|SUMO|NEDD8|ISG15|UFM1|URM1|ATG12|SAMP|TtuB|Pup|pmt3|smo-1)", re.IGNORECASE,
)
# The term of a feature whose description names no class of its own.
FEATURE_TERMS = {
    "ACT_SITE": "Active site", "SITE": "Site", "SIGNAL": "Signal peptide", "TRANSMEM": "Transmembrane", "INTRAMEM": "Intramembrane",
    "PEPTIDE": "Peptide", "PROPEP": "Propeptide", "DISULFID": "Disulfide bond", "HELIX": "Helix", "STRAND": "Beta strand",
    "TURN": "Turn", "COILED": "Coiled coil", "INIT_MET": "Initiator methionine", "REGION": "Region", "DOMAIN": "Domain",
    "MOTIF": "Motif", "DNA_BIND": "DNA-binding region", "ZN_FING": "Zinc finger", "REPEAT": "Repeat", "TOPO_DOM": "Topological domain",
    "TRANSIT": "Transit peptide", "COMPBIAS": "Compositional bias", "BINDING": "Binding site",
}
# Features whose description is the protein's own name for the piece, never a class.
GENERIC_KEYS = frozenset({"SIGNAL", "PEPTIDE", "PROPEP", "DISULFID", "HELIX", "STRAND", "TURN", "COILED", "INIT_MET"})
FAMILY_XREFS = {"CAZy": "cazy", "MEROPS": "merops", "TCDB": "tcdb"}
FEATURE_NUMBERING = re.compile(r"\s+\d+$")
STEP =re.compile(r":\s*step\s+\d+/\d+\.?$", re.IGNORECASE)
MULTIPLIERS = ("mono", "di", "tri", "tetra", "penta", "hexa", "hepta", "octa", "nona", "deca", "undeca", "dodeca")
OLIGOMER = re.compile(
    r"^(?:forms (?:an? )?)?(homo|hetero)?(" + "|".join(MULTIPLIERS) + r")mers?(?: in solution)?(?:;.*)?$"
)
# A sentence's inline citations, as UniProt writes them in a comment of several sentences: "Homodimer (PubMed:1, PubMed:2)."
INLINE_CITATIONS = re.compile(r"\s*\((?:(?:PubMed|DOI):[^,()]+(?:,\s*)?)+\)")
CITATION = re.compile(r"(PubMed|DOI):([^,()\s]+)")


@dataclass(frozen=True, slots=True)
class EntryContext:
    """What reading an entry needs beyond the entry: the location vocabulary and the modifications of `ptmlist.txt`, by name and,
    for a cross-link, by its name with the partner as "..." (`partner_placeholder`)."""

    locations: SubcellVocabulary
    modifications: Mapping[str, UniProtVocabularyRecord]
    partnered: Mapping[str, UniProtVocabularyRecord]

    @classmethod
    def from_files(cls, subcell: Path, ptmlist: Path) -> EntryContext:
        with ptmlist.open(encoding="utf-8") as handle:
            modifications = {record.label: record for record in iter_records(handle) if record.record_type == "ptm"}
        partnered: dict[str, UniProtVocabularyRecord] = {}
        for label, record in modifications.items():
            if CROSSLINK_PARTNER.search(label):
                key = partner_placeholder(label)
                if key in partnered or key in modifications:
                    raise ValueError(f"{ptmlist}: {label!r} and another modification share the name {key!r}")
                partnered[key] = record
        return cls(SubcellVocabulary.from_file(subcell), modifications, partnered)

    def modification(self, name: str) -> UniProtVocabularyRecord | None:
        """The record a modified residue, glycan, lipid or cross-link `name` names, a cross-link's with its partner as ptmlist's."""
        found = self.modifications.get(name)
        return found if found is not None else self.partnered.get(partner_placeholder(name))


def partner_placeholder(name: str) -> str:
    """`name` with a cross-link's partner as "...": "Glycyl lysine isopeptide (Lys-Gly) (interchain with ...)"."""
    return CROSSLINK_PARTNER.sub(lambda found: f"({found.group(1)} ...)", name)


def closed(text: str) -> str:
    """`text` with each parenthesis a cut left open closed: a description's first clause, cut at a semicolon inside one."""
    return text + ")" * max(text.count("(") - text.count(")"), 0)


@dataclass(slots=True)
class EntryRead:
    """One entry: its metadata row, its assertion rows and its measurement statements."""

    entry: dict[str, object]
    assertions: list[dict[str, object]] = field(default_factory=list)
    measurements: list[dict[str, object]] = field(default_factory=list)


def read_entry(entry: ET.Element, namespace: str, context: EntryContext, audit: EntryAudit) -> EntryRead:
    """Everything the compendium keeps of one entry."""
    accession = entry_accession(entry, namespace)
    sequence_element, residues = canonical_sequence(entry, namespace, accession)
    records = evidence_records(entry, namespace, ("PubMed", "DOI"))
    organism = organism_record(entry, namespace)
    reviewed = entry.get("dataset") == "Swiss-Prot"
    audit.counts[f"entries:{entry.get('dataset')}"] += 1
    audit.evidence_types.update(item["type"] for item in records.values())
    existence = entry.find(namespace + "proteinExistence")
    references = [item for item in entry.findall(namespace + "dbReference")]
    read = EntryRead({
        "accession": accession,
        "secondary_accessions": [item.text or "" for item in entry.findall(namespace + "accession")[1:]],
        "entry_name": entry.findtext(namespace + "name") or "",
        "dataset": entry.get("dataset", ""),
        "sequence": residues,
        "fragment": sequence_element.get("fragment") is not None,
        "created": entry.get("created", ""),
        "modified": entry.get("modified", ""),
        "entry_version": int(entry.get("version", "0")),
        "sequence_version": int(sequence_element.get("version", "0")),
        "protein_existence": PROTEIN_EXISTENCE.get(existence.get("type", "") if existence is not None else "", 5),
        "taxon_id": int(organism["taxon_id"]) if organism["taxon_id"] else None,
        "organism": organism["name"] or "",
        "lineage": organism["lineage"],
        "proteomes": sorted({item.get("id", "") for item in references if item.get("type") == "Proteomes"}),
        "protein_name": _protein_name(entry, namespace),
        "references": len(entry.findall(namespace + "reference")),
        "structures": sum(1 for item in references if item.get("type") == "PDB"),
    })
    seen: set[tuple[object, ...]] = set()

    def add(term: TermKey, label: str, cited: list[tuple[str, str]], *, start: int | None = None, end: int | None = None,
            note: str = "") -> None:
        audit.counts[f"{term.aspect}:seen"] += 1
        for code, reference in cited or [("", "")]:
            key = (term, code, start, end)
            if key in seen:
                continue
            seen.add(key)
            read.assertions.append({
                "accession": accession, "aspect": term.aspect, "source_database": term.source_database, "term": term.accession,
                "label": label, "negated": False, "code": code, "source": SOURCE_UNIPROT, "assigned_by": "UniProt" if reviewed else "",
                "reference": reference, "relation": "", "start": start, "end": end, "note": note,
            })

    def admit(term: TermKey, label: str, codes: tuple[str, ...]) -> None:
        # Disease is no aspect of the compendium (Logan, 2026-10-20).
        if term.aspect != "disease":
            add(term, label, [(code, "") for code in codes])

    own = displayed_isoform(entry, namespace)
    read_terms(entry, namespace, records, context.locations, admit, audit, accession, codes=evidence_codes, own_molecules=own)
    _keywords(entry, namespace, records, accession, add)
    _features(entry, namespace, records, accession, context, add, audit)
    _comments(entry, namespace, records, accession, add, read, audit, own)
    for item in references:
        aspect = FAMILY_XREFS.get(item.get("type", ""))
        if aspect and item.get("id"):
            add(TermKey(aspect, item.get("type", ""), item.get("id", "")), item.get("id", ""), [])
    return read


def codes_of(evidence: Iterable[EvidenceRecord]) -> list[tuple[str, str]]:
    """Each distinct evidence code of `evidence`, with the citations of that code joined by "|"; sorted by code."""
    by_code: dict[str, set[str]] = {}
    for item in evidence:
        by_code.setdefault(item["type"], set()).update(item["citations"])
    return [(code, "|".join(sorted(citations))) for code, citations in sorted(by_code.items())]


def cited_codes(keys: str | None, records: Mapping[str, EvidenceRecord], where: str) -> list[tuple[str, str]]:
    """Each distinct evidence code an element's keys name, with the citations of that code joined by "|"; sorted by code."""
    return codes_of(evidence_for(keys, records, where, "element"))


def _protein_name(entry: ET.Element, namespace: str) -> str:
    protein = entry.find(namespace + "protein")
    if protein is None:
        return ""
    for path in ("recommendedName", "submittedName", "alternativeName"):
        name = protein.findtext(f"{namespace}{path}/{namespace}fullName")
        if name:
            return " ".join(name.split())
    return ""


Add = Callable[..., None]


def _keywords(entry: ET.Element, namespace: str, records: Mapping[str, EvidenceRecord], where: str, add: Add) -> None:
    for keyword in entry.findall(namespace + "keyword"):
        identifier = keyword.get("id", "")
        if identifier.startswith("KW-"):
            add(TermKey("keyword", "UniProtKB-KW", identifier), " ".join((keyword.text or identifier).split()),
                cited_codes(keyword.get("evidence"), records, where))


def _position(location: ET.Element, namespace: str) -> tuple[int | None, int | None]:
    """A feature location's first and last residue, None where the entry says the position is unknown."""
    single = location.find(namespace + "position")
    if single is not None:
        value = _residue(single)
        return value, value
    begin, end = location.find(namespace + "begin"), location.find(namespace + "end")
    return (_residue(begin) if begin is not None else None), (_residue(end) if end is not None else None)


def _residue(element: ET.Element) -> int | None:
    position = element.get("position")
    return int(position) if position and position.isdigit() and element.get("status") != "unknown" else None


def feature_term(key: str, description: str) -> str:
    """The class a feature names: its description without the numbering of repeats and the qualifiers after a semicolon, or the
    feature's own name when the description is the piece's name or absent."""
    if key in GENERIC_KEYS:
        return FEATURE_TERMS[key]
    base = FEATURE_NUMBERING.sub("", description.split(";")[0].strip())
    return " ".join(base.split()) or FEATURE_TERMS[key]


def _features(entry: ET.Element, namespace: str, records: Mapping[str, EvidenceRecord], where: str, context: EntryContext,
              add: Add, audit: EntryAudit) -> None:
    for feature in entry.findall(namespace + "feature"):
        key = FEATURE_KEYS.get(feature.get("type", ""))
        if key is None:
            audit.counts[f"feature_not_read:{feature.get('type', '')}"] += 1
            continue
        location = feature.find(namespace + "location")
        start, end = _position(location, namespace) if location is not None else (None, None)
        if start is None or end is None:
            audit.counts[f"{key}:unknown_position"] += 1
        cited = cited_codes(feature.get("evidence"), records, where)
        description = " ".join((feature.get("description") or "").split())
        aspect = FEATURE_ASPECTS[key]
        if key == "BINDING":
            ligand = feature.find(namespace + "ligand")
            name = " ".join((ligand.findtext(namespace + "name") or "").split()) if ligand is not None else ""
            chebi = [item.get("id", "") for item in (ligand.findall(namespace + "dbReference") if ligand is not None else ())
                     if item.get("type") == "ChEBI" and item.get("id", "").startswith("CHEBI:")]
            term = TermKey(aspect, "ChEBI", chebi[0]) if chebi else TermKey(aspect, "UniProtKB-FT", name or FEATURE_TERMS[key])
            add(term, name or term.accession, cited, start=start, end=end, note=description)
        elif key in MODIFICATION_KEYS:
            base = closed(description.split(";")[0].strip())
            record = context.modification(base)
            if record is None:
                audit.counts[f"{key}:unnamed_modification"] += 1
                add(TermKey(aspect, "UniProtKB-FT", base or FEATURE_TERMS.get(key, key)), base, cited, start=start, end=end, note=description)
                continue
            if UBIQUITIN_LIKE.search(base):
                add(TermKey(aspect, "UniProtKB-FT", base), base, cited, start=start, end=end, note=description)
            else:
                add(TermKey(aspect, "UniProtKB-PTM", record.stable_id), record.label, cited, start=start, end=end, note=description)
            add(TermKey("ptm", "UniProtKB-PTM", record.stable_id), record.label, cited)
        else:
            name = feature_term(key, description)
            add(TermKey(aspect, "UniProtKB-FT", name), name, cited, start=start, end=end, note=description)


def oligomeric_state(sentence: str) -> str | None:
    """The oligomeric state one sentence states whole, its inline citations aside, such as "Homodimer." or "Forms homotrimers
    (PubMed:1).", capitalized and singular ("Homodimer"), or None; a hedge ("May form homodimers") or a mixture is no state."""
    found = OLIGOMER.match(INLINE_CITATIONS.sub("", sentence).rstrip(".").strip().lower())
    if not found:
        return None
    prefix, multiplier = found.group(1) or "", found.group(2)
    return "Monomer" if multiplier == "mono" and not prefix else f"{prefix}{multiplier}mer".capitalize()


def oligomeric_states(text: str) -> list[str]:
    """The oligomeric states a subunit comment states, each a sentence of its own (`oligomeric_state`), in order."""
    return list(dict.fromkeys(state for sentence in sentences_of(text) if (state := oligomeric_state(sentence))))


def cited_in(sentence: str) -> set[str]:
    """The citations a sentence names inline, written `<type>:<id>` as an evidence record writes them."""
    return {f"{kind}:{name}" for kind, name in CITATION.findall(sentence)}


def sentence_evidence(sentence: str, sentences: Sequence[str], evidence: Sequence[EvidenceRecord]) -> list[EvidenceRecord]:
    """The evidence records of one sentence of a comment text.

    UniProt's XML gives a text one evidence list and, in a text of several sentences, cites each sentence's papers inline, so a
    text of one sentence holds every record, a sentence with inline citations the records they name, and an uncited sentence of
    several the records no sentence cites, as the flat file writes them. Given the whole list instead, 837 of the 9,212
    experimental states of a 2026_03 Swiss-Prot entry rested on another sentence's paper, and a sentence matched with its
    citations missed 2,133 (the build experiment's `subunit_evidence.py`, 2026-10-21).
    """
    if len(sentences) == 1:
        return list(evidence)
    own = cited_in(sentence)
    if own:
        return [item for item in evidence if own & set(item["citations"])]
    cited = set().union(*(cited_in(other) for other in sentences))
    return [item for item in evidence if not cited & set(item["citations"])]


def pathway_path(text: str) -> tuple[str, ...]:
    """A pathway comment's levels, from its class down, without the step: "Amino-acid biosynthesis; L-arginine biosynthesis"."""
    cleaned = STEP.sub("", " ".join(text.split())).rstrip(".").strip()
    return tuple(part.strip() for part in cleaned.split(";") if part.strip())


def family_path(text: str) -> tuple[str, ...]:
    """A similarity comment's families, from its superfamily down: "Belongs to the protein kinase superfamily. Ser/Thr protein
    kinase family." gives ("protein kinase superfamily", "Ser/Thr protein kinase family"); a comment of another form gives ()."""
    cleaned = " ".join(text.split())
    if not cleaned.startswith("Belongs to the "):
        return ()
    parts = [part.strip().rstrip(".") for part in SENTENCE_BOUNDARY.split(cleaned.removeprefix("Belongs to the "))]
    return tuple(part for part in parts if part and re.search(r"(?:super|sub)?family$", part))


def _comments(entry: ET.Element, namespace: str, records: Mapping[str, EvidenceRecord], where: str, add: Add, read: EntryRead,
              audit: EntryAudit, own: Collection[str]) -> None:
    for comment in entry.findall(namespace + "comment"):
        kind = comment.get("type")
        if kind not in ("pathway", "subunit", "similarity", "biophysicochemical properties"):
            continue
        if scoped_elsewhere(comment, namespace, own, kind, audit):
            continue
        if kind == "biophysicochemical properties":
            _measurements(comment, namespace, records, where, read)
            continue
        for text in comment.findall(namespace + "text"):
            evidence = evidence_for(text.get("evidence") or comment.get("evidence"), records, where, "element")
            value = " ".join((text.text or "").split())
            if kind == "pathway":
                path = pathway_path(value)
                if path:
                    add(TermKey("uniprot_pathway", "UniProtKB-Pathway", "; ".join(path)), path[-1], codes_of(evidence))
            elif kind == "subunit":
                sentences = sentences_of(value)
                for sentence in sentences:
                    state = oligomeric_state(sentence)
                    if state:
                        add(TermKey("oligomeric_state", "UniProtKB-Subunit", state), state,
                            codes_of(sentence_evidence(sentence, sentences, evidence)))
            else:
                path = family_path(value)
                if path:
                    add(TermKey("uniprot_family", "UniProtKB-Family", "; ".join(path)), path[-1], codes_of(evidence))
                else:
                    audit.counts["similarity:unparsed"] += 1


MEASUREMENT_ELEMENTS = (
    ("kinetics", "KM", "kinetics_km"), ("kinetics", "Vmax", "kinetics_vmax"), ("kinetics", "text", "kinetics_text"),
    ("phDependence", "text", "ph_dependence"), ("temperatureDependence", "text", "temperature_dependence"),
    ("redoxPotential", "text", "redox_potential"), ("absorption", "max", "absorption_max"),
)


def _measurements(comment: ET.Element, namespace: str, records: Mapping[str, EvidenceRecord], where: str, read: EntryRead) -> None:
    for group, element, kind in MEASUREMENT_ELEMENTS:
        for parent in comment.findall(namespace + group):
            for item in parent.findall(namespace + element):
                cited = cited_codes(item.get("evidence") or parent.get("evidence"), records, where)
                read.measurements.append({
                    "accession": read.entry["accession"], "kind": kind, "text": " ".join((item.text or "").split()),
                    "codes": [code for code, _ in cited], "references": [reference for _, reference in cited],
                })


STREAM_ENDPOINT = f"{UNIPROT_BASE}/uniprotkb/stream"
# TrEMBL entries of Swiss-Prot quality (Logan, 2026-10-20), whole and no longer than the pool admits.
TREMBL_QUERY = "(reviewed:false) AND ((annotation_score:4) OR (annotation_score:5) OR (existence:1)) AND (fragment:false) AND (length:[1 TO 2046])"
SWISSPROT_QUERY = "(reviewed:true)"
STREAM_TIMEOUT_SECONDS = 600.0


class ReleaseMismatch(RuntimeError):
    """UniProt answered from another release than the one the build pins."""


def stream_query(query: str, path: Path, *, expected_release: str, file_format: str, fields: str | None = None,
                 session: requests.Session | None = None, progress: bool = True) -> dict[str, object]:
    """Stream every entry `query` matches to `path`, gzip-compressed as UniProt sends it, refusing another release than the pin.

    The file is written beside its target and moved into place only once whole, so a stopped stream leaves nothing to mistake for
    a finished one. Returns the release and the bytes written.
    """
    client = session if session is not None else requests.Session()
    params = {"query": query, "format": file_format, "compressed": "true", **({"fields": fields} if fields else {})}
    response = request_with_retry(
        client, "GET", STREAM_ENDPOINT, timeout_s=STREAM_TIMEOUT_SECONDS, max_retries=4, backoff_base_s=4.0, backoff_max_s=120.0,
        params=params, stream=True,
    )
    release = response.headers.get("x-uniprot-release")
    if release != expected_release:
        response.close()
        raise ReleaseMismatch(f"UniProt answered from release {release}, not the pinned {expected_release}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    written = 0
    with temporary.open("wb") as handle, tqdm(desc=path.name, unit="B", unit_scale=True, mininterval=30, disable=not progress) as bar:
        for chunk in response.iter_content(chunk_size=1 << 20):
            handle.write(chunk)
            written += len(chunk)
            bar.update(len(chunk))
    temporary.replace(path)
    return {"query": query, "format": file_format, "fields": fields, "release": release, "bytes": written}


def read_scores(path: Path) -> dict[str, int]:
    """Accession to annotation score from a gzip TSV stream of `accession,annotation_score`."""
    scores: dict[str, int] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        if len(header) != 2:
            raise ValueError(f"{path.name} must hold two columns, the accession and the annotation score, got {header}")
        for line in handle:
            accession, _, score = line.rstrip("\n").partition("\t")
            if accession:
                scores[accession] = int(float(score))
    return scores
