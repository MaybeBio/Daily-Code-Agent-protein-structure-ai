"""Stream UniProtKB/Swiss-Prot flat files into annotation records."""

from __future__ import annotations

import gzip
import re

from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import TextIO
from Bio import SwissProt
from Bio.SeqFeature import ExactPosition, UnknownPosition

from ..grammar import LOCAL_FEATURE_ASPECTS, source_global_term_sort_key
from ..schema import LocalAnnotation, ProteinRecord, TermAnnotation, TermKey


SwissProtInput = str | PathLike[str] | TextIO

_GO_ASPECTS = {"P": "go_bp", "C": "go_cc", "F": "go_mf"}
_FEATURE_LABELS = {
    "ACT_SITE": "Active site",
    "BINDING": "Binding site",
    "SITE": "Site",
    "REGION": "Region",
    "DOMAIN": "Domain",
    "MOTIF": "Motif",
    "DNA_BIND": "DNA-binding region",
    "ZN_FING": "Zinc finger",
    "REPEAT": "Repeat",
    "SIGNAL": "Signal peptide",
    "TRANSIT": "Transit peptide",
    "TRANSMEM": "Transmembrane region",
    "INTRAMEM": "Intramembrane region",
    "TOPO_DOM": "Topological domain",
    "CHAIN": "Chain",
    "PEPTIDE": "Peptide",
    "PROPEP": "Propeptide",
    "MOD_RES": "Modified residue",
    "CARBOHYD": "Glycosylation site",
    "LIPID": "Lipidation site",
    "DISULFID": "Disulfide bond",
    "CROSSLNK": "Cross-link",
    "HELIX": "Helix",
    "STRAND": "Beta strand",
    "TURN": "Turn",
    "COILED": "Coiled-coil region",
    "COMPBIAS": "Compositional bias",
}
_BOND_FEATURE_TYPES = frozenset({"DISULFID", "CROSSLNK"})
_EC_PATTERN = re.compile(
    r"\bEC=(?P<accession>[0-9n.-]+)(?:\s+\{(?P<evidence>[^}]*)\})?;"
)
_EVIDENCE_BLOCK_PATTERN = re.compile(r"\{([^{}]*ECO:[^{}]+)\}")
_EVIDENCE_SEPARATOR = re.compile(r",\s*(?=ECO:)")
_RHEA_PATTERN = re.compile(r"Rhea:(RHEA:\d+)")
_REACTION_PATTERN = re.compile(r"(?:CATALYTIC ACTIVITY:\s*|;\s*)Reaction=(.*?);")
_COFACTOR_PATTERN = re.compile(
    r"Name=(?P<label>[^;]+);\s*Xref=ChEBI:(?P<accession>(?:CHEBI:)?\d+);"
)
_DISEASE_MIM_PATTERN = re.compile(
    r"^DISEASE:\s*(?P<label>.+?)\s+\[MIM:(?P<accession>\d+)\]:\s*"
    r"(?P<description>.*)$"
)
_CHEBI_PATTERN = re.compile(r"(?i)(?:ChEBI:)+(\d+)")


@dataclass(slots=True)
class SwissProtParserAudit:
    """Counts records, emitted annotations, and excluded feature reasons."""

    records_seen: int = 0
    records_emitted: int = 0
    global_annotations_emitted: int = 0
    local_features_seen: int = 0
    local_annotations_emitted: int = 0
    local_feature_exclusions: Counter[str] = field(default_factory=Counter)
    ignored_feature_types: Counter[str] = field(default_factory=Counter)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable audit summary."""

        return {
            "records_seen": self.records_seen,
            "records_emitted": self.records_emitted,
            "global_annotations_emitted": self.global_annotations_emitted,
            "local_features_seen": self.local_features_seen,
            "local_annotations_emitted": self.local_annotations_emitted,
            "local_feature_exclusions": dict(sorted(self.local_feature_exclusions.items())),
            "ignored_feature_types": dict(sorted(self.ignored_feature_types.items())),
        }


def parse_swissprot(
    source: SwissProtInput,
    *,
    audit: SwissProtParserAudit | None = None,
) -> Iterator[ProteinRecord]:
    """Yield records from a plain or gzip-compressed Swiss-Prot flat file."""

    parser_audit = audit if audit is not None else SwissProtParserAudit()
    if isinstance(source, (str, PathLike)):
        path = Path(source)
        if path.suffix.casefold() == ".gz":
            with gzip.open(path, mode="rt", encoding="ascii") as handle:
                yield from _parse_handle(handle, parser_audit)
        else:
            with path.open(mode="r", encoding="ascii") as handle:
                yield from _parse_handle(handle, parser_audit)
        return

    yield from _parse_handle(source, parser_audit)


def _parse_handle(handle: TextIO, audit: SwissProtParserAudit) -> Iterator[ProteinRecord]:
    for source_record in SwissProt.parse(handle):
        audit.records_seen += 1
        global_annotations = _global_annotations(source_record)
        local_annotations = _local_annotations(
            source_record,
            accession=_primary_accession(source_record),
            sequence_length=len(source_record.sequence),
            audit=audit,
        )
        protein = _protein_record(source_record, global_annotations, local_annotations)
        audit.records_emitted += 1
        audit.global_annotations_emitted += len(global_annotations)
        audit.local_annotations_emitted += len(local_annotations)
        yield protein


def _protein_record(
    record: SwissProt.Record,
    global_annotations: tuple[TermAnnotation, ...],
    local_annotations: tuple[LocalAnnotation, ...],
) -> ProteinRecord:
    taxonomy_ids = tuple(int(taxon_id) for taxon_id in record.taxonomy_id)
    organism_raw = str(record.organism).strip()
    metadata = {
        "annotation_update_date": _record_date(record.annotation_update),
        "created_date": _record_date(record.created),
        "comments": tuple(record.comments),
        "data_class": record.data_class or "",
        "description": str(record.description),
        "molecule_type": record.molecule_type or "",
        "organism_raw": organism_raw,
        "protein_existence": record.protein_existence,
        "secondary_accessions": tuple(record.accessions[1:]),
        "sequence_update_date": _record_date(record.sequence_update),
        "taxonomy_ids": taxonomy_ids,
    }
    return ProteinRecord(
        accession=_primary_accession(record),
        sequence=str(record.sequence).upper(),
        entry_name=str(record.entry_name or ""),
        organism=organism_raw.rstrip("."),
        taxon_id=taxonomy_ids[0] if taxonomy_ids else None,
        lineage_names=tuple(record.organism_classification),
        entry_version=_record_version(record.annotation_update),
        sequence_version=_record_version(record.sequence_update),
        global_annotations=global_annotations,
        local_annotations=local_annotations,
        metadata=metadata,
    )


def _primary_accession(record: SwissProt.Record) -> str:
    if not record.accessions:
        raise ValueError(f"Swiss-Prot record {record.entry_name!r} has no accession")
    return str(record.accessions[0])


def _record_date(update: tuple[str, int | str] | None) -> str:
    return str(update[0]) if update is not None else ""


def _record_version(update: tuple[str, int | str] | None) -> int | None:
    if update is None or not isinstance(update[1], int):
        return None
    return update[1]


def _global_annotations(record: SwissProt.Record) -> tuple[TermAnnotation, ...]:
    annotations: list[TermAnnotation] = []
    catalytic_comments = [
        comment for comment in record.comments if comment.startswith("CATALYTIC ACTIVITY:")
    ]
    annotations.extend(_ec_annotations((str(record.description), *catalytic_comments)))
    annotations.extend(_rhea_annotations(catalytic_comments))
    annotations.extend(
        annotation
        for comment in record.comments
        if comment.startswith("COFACTOR:")
        for annotation in _cofactor_annotations(comment)
    )

    disease_annotations = _mim_comment_annotations(record.comments)
    annotations.extend(disease_annotations)
    mim_labels = {
        annotation.key.accession.removeprefix("MIM:"): annotation.label
        for annotation in disease_annotations
    }

    for cross_reference in record.cross_references:
        annotation = _cross_reference_annotation(cross_reference, mim_labels)
        if annotation is not None:
            annotations.append(annotation)

    annotations.extend(_keyword_annotations(record.keywords))
    merged = _merge_annotations(annotations)
    return tuple(
        sorted(
            merged.values(),
            key=lambda annotation: source_global_term_sort_key(annotation.key),
        )
    )


def _ec_annotations(raw_values: Iterable[str]) -> list[TermAnnotation]:
    annotations: list[TermAnnotation] = []
    for raw_value in raw_values:
        for match in _EC_PATTERN.finditer(raw_value):
            accession = match.group("accession")
            evidence, references = _evidence_components((match.group("evidence") or "",))
            annotations.append(
                TermAnnotation(
                    key=TermKey("ec", "EC", accession),
                    label=f"EC {accession}",
                    evidence=evidence,
                    raw_value=raw_value,
                    relation="has_enzyme_class",
                    source_references=references,
                )
            )
    return annotations


def _rhea_annotations(comments: Iterable[str]) -> list[TermAnnotation]:
    annotations: list[TermAnnotation] = []
    for comment in comments:
        reaction_match = _REACTION_PATTERN.search(comment)
        reaction = reaction_match.group(1).strip() if reaction_match is not None else ""
        evidence, references = _evidence_from_text(comment)
        for accession in _ordered_unique(_RHEA_PATTERN.findall(comment)):
            annotations.append(
                TermAnnotation(
                    key=TermKey("rhea", "Rhea", accession),
                    label=reaction or accession,
                    description=reaction,
                    evidence=evidence,
                    raw_value=comment,
                    relation="catalyzes",
                    source_references=references,
                )
            )
    return annotations


def _cofactor_annotations(comment: str) -> list[TermAnnotation]:
    evidence, references = _evidence_from_text(comment)
    note = _trailing_field(comment, "Note")
    annotations: list[TermAnnotation] = []
    for match in _COFACTOR_PATTERN.finditer(comment):
        accession = _normalize_chebi(match.group("accession"))
        annotations.append(
            TermAnnotation(
                key=TermKey("cofactor", "ChEBI", accession),
                label=match.group("label").strip(),
                description=note,
                evidence=evidence,
                raw_value=comment,
                relation="has_cofactor",
                source_references=references,
            )
        )
    return annotations


def _mim_comment_annotations(comments: Iterable[str]) -> list[TermAnnotation]:
    annotations: list[TermAnnotation] = []
    for comment in comments:
        match = _DISEASE_MIM_PATTERN.match(comment)
        if match is None:
            continue
        accession = f"MIM:{match.group('accession')}"
        evidence, references = _evidence_from_text(comment)
        annotations.append(
            TermAnnotation(
                key=TermKey("disease", "MIM", accession),
                label=match.group("label").strip(),
                description=match.group("description").strip(),
                evidence=evidence,
                raw_value=comment,
                relation="associated_with",
                source_references=references,
            )
        )
    return annotations


def _cross_reference_annotation(
    cross_reference: tuple[str, ...],
    mim_labels: dict[str, str],
) -> TermAnnotation | None:
    if len(cross_reference) < 2:
        raise ValueError(f"Malformed Swiss-Prot cross-reference: {cross_reference!r}")
    database, accession = cross_reference[:2]
    raw_value = f"DR   {'; '.join(cross_reference)}."

    if database == "GO":
        if len(cross_reference) < 3 or ":" not in cross_reference[2]:
            raise ValueError(f"Malformed GO cross-reference: {cross_reference!r}")
        source_aspect, label = cross_reference[2].split(":", maxsplit=1)
        try:
            aspect = _GO_ASPECTS[source_aspect]
        except KeyError as error:
            raise ValueError(f"Unknown GO aspect in {cross_reference!r}") from error
        evidence, references = _go_qualifier_components(cross_reference[3:])
        return TermAnnotation(
            key=TermKey(aspect, "GO", accession),
            label=label,
            evidence=evidence,
            raw_value=raw_value,
            source_references=references,
        )

    if database == "InterPro":
        return _domain_annotation("interpro", "InterPro", accession, cross_reference, raw_value)
    if database == "Gene3D":
        gene3d_accession = accession if accession.startswith("G3DSA:") else f"G3DSA:{accession}"
        return _domain_annotation(
            "gene3d", "Gene3D", gene3d_accession, cross_reference, raw_value
        )
    if database == "Pfam":
        return _domain_annotation("pfam", "Pfam", accession, cross_reference, raw_value)

    if database == "MIM" and len(cross_reference) >= 3:
        reference_type = cross_reference[2]
        if "phenotype" not in reference_type.casefold():
            return None
        return TermAnnotation(
            key=TermKey("disease", "MIM", f"MIM:{accession}"),
            label=mim_labels.get(accession, f"MIM:{accession}"),
            description=reference_type,
            raw_value=raw_value,
            relation="associated_with",
        )

    if database == "Orphanet":
        orphanet_accession = accession if accession.startswith("ORPHA:") else f"ORPHA:{accession}"
        return TermAnnotation(
            key=TermKey("disease", "Orphanet", orphanet_accession),
            label=_cross_reference_label(cross_reference, orphanet_accession),
            raw_value=raw_value,
            relation="associated_with",
        )
    return None


def _domain_annotation(
    aspect: str,
    database: str,
    accession: str,
    cross_reference: tuple[str, ...],
    raw_value: str,
) -> TermAnnotation:
    label = _cross_reference_label(cross_reference, accession)
    return TermAnnotation(
        key=TermKey(aspect, database, accession),
        label=label,
        description=label if label != accession else "",
        raw_value=raw_value,
        relation="has_match",
    )


def _cross_reference_label(cross_reference: tuple[str, ...], fallback: str) -> str:
    if len(cross_reference) >= 3 and cross_reference[2] not in {"", "-"}:
        return cross_reference[2]
    return fallback


def _keyword_annotations(keywords: Iterable[str]) -> list[TermAnnotation]:
    return [
        TermAnnotation(
            key=TermKey("keyword", "UniProtKB-KW", keyword),
            label=keyword,
            raw_value=keyword,
            relation="has_keyword",
        )
        for keyword in keywords
        if keyword
    ]


def _merge_annotations(annotations: Iterable[TermAnnotation]) -> dict[TermKey, TermAnnotation]:
    merged: dict[TermKey, TermAnnotation] = {}
    for annotation in annotations:
        current = merged.get(annotation.key)
        if current is None:
            merged[annotation.key] = annotation
            continue
        merged[annotation.key] = TermAnnotation(
            key=current.key,
            label=current.label,
            description=current.description or annotation.description,
            evidence=_ordered_unique((*current.evidence, *annotation.evidence)),
            raw_value=_join_raw_values(current.raw_value, annotation.raw_value),
            relation=current.relation or annotation.relation,
            negated=current.negated or annotation.negated,
            source_references=_ordered_unique(
                (*current.source_references, *annotation.source_references)
            ),
        )
    return merged


def _local_annotations(
    record: SwissProt.Record,
    *,
    accession: str,
    sequence_length: int,
    audit: SwissProtParserAudit,
) -> tuple[LocalAnnotation, ...]:
    annotations: list[LocalAnnotation] = []
    for feature_index, feature in enumerate(record.features, start=1):
        feature_type = str(feature.type)
        if feature_type not in LOCAL_FEATURE_ASPECTS:
            audit.ignored_feature_types[feature_type] += 1
            continue
        audit.local_features_seen += 1

        coordinates, exclusion_reason = _exact_coordinates(feature, sequence_length)
        if exclusion_reason is not None:
            audit.local_feature_exclusions[exclusion_reason] += 1
            continue
        assert coordinates is not None
        start, end = coordinates
        if feature_type in _BOND_FEATURE_TYPES and start == end:
            audit.local_feature_exclusions["bond_without_partner"] += 1
            continue

        evidence, references = _evidence_components((_qualifier(feature, "evidence"),))
        description = _feature_description(feature)
        ligand_label = _qualifier(feature, "ligand")
        ligand_chebi_id = _normalize_chebi(_qualifier(feature, "ligand_id"))
        feature_id = f"{accession}:FT:{feature_index}"
        term = TermAnnotation(
            key=TermKey(
                LOCAL_FEATURE_ASPECTS[feature_type],
                "UniProtKB-FT",
                feature_type,
            ),
            label=_FEATURE_LABELS[feature_type],
            evidence=evidence,
            raw_value=_raw_feature_value(feature, start, end),
            relation="feature_at",
            source_references=references,
        )
        source_feature_id = str(feature.id or "")

        if feature_type in _BOND_FEATURE_TYPES:
            for coordinate, pair_member in ((start, 1), (end, 2)):
                annotations.append(
                    LocalAnnotation(
                        term=term,
                        start=coordinate,
                        end=coordinate,
                        feature_type=feature_type,
                        description=description,
                        feature_id=feature_id,
                        source_feature_id=source_feature_id,
                        ligand_chebi_id=ligand_chebi_id,
                        ligand_label=ligand_label,
                        pair_member=pair_member,
                    )
                )
            continue

        annotations.append(
            LocalAnnotation(
                term=term,
                start=start,
                end=end,
                feature_type=feature_type,
                description=description,
                feature_id=feature_id,
                source_feature_id=source_feature_id,
                ligand_chebi_id=ligand_chebi_id,
                ligand_label=ligand_label,
            )
        )
    return tuple(annotations)


def _exact_coordinates(
    feature: SwissProt.FeatureTable,
    sequence_length: int,
) -> tuple[tuple[int, int] | None, str | None]:
    location = feature.location
    if location is None:
        return None, "missing_location"
    if location.ref is not None:
        return None, "noncanonical_sequence"
    if isinstance(location.start, UnknownPosition):
        return None, "unknown_start"
    if isinstance(location.end, UnknownPosition):
        return None, "unknown_end"
    if not isinstance(location.start, ExactPosition):
        return None, "fuzzy_start"
    if not isinstance(location.end, ExactPosition):
        return None, "fuzzy_end"

    start = int(location.start) + 1
    end = int(location.end)
    if start < 1 or end < start:
        return None, "invalid_coordinates"
    if end > sequence_length:
        return None, "out_of_bounds"
    return (start, end), None


def _qualifier(feature: SwissProt.FeatureTable, name: str) -> str:
    value = feature.qualifiers.get(name, "")
    return str(value).strip()


def _feature_description(feature: SwissProt.FeatureTable) -> str:
    components: list[str] = []
    note = _qualifier(feature, "note") or _qualifier(feature, "description")
    if note:
        components.append(note)

    ligand = _qualifier(feature, "ligand")
    ligand_id = _normalize_chebi(_qualifier(feature, "ligand_id"))
    if ligand:
        suffix = f" ({ligand_id})" if ligand_id else ""
        components.append(f"Ligand: {ligand}{suffix}")

    ligand_part = _qualifier(feature, "ligand_part")
    ligand_part_id = _normalize_chebi(_qualifier(feature, "ligand_part_id"))
    if ligand_part:
        suffix = f" ({ligand_part_id})" if ligand_part_id else ""
        components.append(f"Ligand part: {ligand_part}{suffix}")
    return "; ".join(components)


def _raw_feature_value(feature: SwissProt.FeatureTable, start: int, end: int) -> str:
    location = str(start) if start == end else f"{start}..{end}"
    qualifiers = "; ".join(
        f"{name}={value}" for name, value in feature.qualifiers.items()
    )
    raw_value = f"FT   {feature.type} {location}"
    return f"{raw_value}; {qualifiers}" if qualifiers else raw_value


def _evidence_from_text(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return _evidence_components(_EVIDENCE_BLOCK_PATTERN.findall(text))


def _evidence_components(
    evidence_values: Iterable[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    evidence_codes: list[str] = []
    references: list[str] = []
    for evidence_value in evidence_values:
        for assertion in _EVIDENCE_SEPARATOR.split(evidence_value):
            assertion = assertion.strip()
            if not assertion:
                continue
            components = [component.strip() for component in assertion.split("|")]
            evidence_codes.append(components[0])
            references.extend(component for component in components[1:] if component)
    return _ordered_unique(evidence_codes), _ordered_unique(references)


def _go_qualifier_components(
    qualifiers: Iterable[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    evidence_codes: list[str] = []
    assigned_by_references: list[str] = []
    for raw_qualifier in qualifiers:
        qualifier = raw_qualifier.strip()
        if not qualifier or qualifier == "-":
            continue
        evidence_code, separator, assigned_by = qualifier.partition(":")
        evidence_code = evidence_code.strip()
        assigned_by = assigned_by.strip()
        if not separator or not evidence_code or not assigned_by:
            raise ValueError(f"Malformed GO evidence qualifier: {raw_qualifier!r}")
        evidence_codes.append(evidence_code)
        assigned_by_references.append(assigned_by)
    return _ordered_unique(evidence_codes), _ordered_unique(assigned_by_references)


def _normalize_chebi(value: str) -> str:
    if not value:
        return ""
    match = _CHEBI_PATTERN.fullmatch(value.strip())
    return f"CHEBI:{match.group(1)}" if match is not None else ""


def _trailing_field(text: str, field_name: str) -> str:
    marker = f"{field_name}="
    if marker not in text:
        return ""
    return text.rsplit(marker, maxsplit=1)[1].rstrip("; ").strip()


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _join_raw_values(left: str, right: str) -> str:
    if not left:
        return right
    if not right or right == left:
        return left
    return f"{left}\n{right}"
