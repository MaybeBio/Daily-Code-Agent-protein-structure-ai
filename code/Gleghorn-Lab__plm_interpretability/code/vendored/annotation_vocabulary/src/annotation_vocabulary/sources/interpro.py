"""Stream InterPro protein-to-entry coordinates and join them to Swiss-Prot records."""

from __future__ import annotations

import gzip
import re

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from os import PathLike
from pathlib import Path
from typing import TextIO

from ..schema import LocalAnnotation, ProteinRecord, TermAnnotation, TermKey


InterProInput = str | PathLike[str] | TextIO

LOCAL_INTERPRO_ASPECT = "local_interpro"
INTERPRO_SOURCE_DATABASE = "InterPro"
INTERPRO_FEATURE_TYPE = "INTERPRO"
_INTERPRO_ACCESSION = re.compile(r"IPR\d{6}")


@dataclass(frozen=True, slots=True)
class InterProCoordinateMatch:
    """One InterPro interval matched to a target Swiss-Prot accession."""

    protein_accession: str
    annotation: LocalAnnotation


@dataclass(slots=True)
class InterProParserAudit:
    """Count emitted spans and mutually exclusive source-row dispositions.

    ``duplicate_rows`` counts exact source-row repeats. Distinct source rows
    collapsed into one conceptual span increment
    ``conceptual_duplicate_rows_merged``. A row with a nonempty first field that
    is absent from the target map is classified as non-Swiss-Prot before its
    remaining columns are validated.
    """

    rows_seen: int = 0
    rows_emitted: int = 0
    malformed_rows: int = 0
    out_of_bounds_rows: int = 0
    duplicate_rows: int = 0
    conceptual_duplicate_rows_merged: int = 0
    non_swissprot_rows: int = 0
    malformed_reasons: Counter[str] = field(default_factory=Counter)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible audit summary."""

        return {
            "rows_seen": self.rows_seen,
            "rows_emitted": self.rows_emitted,
            "malformed_rows": self.malformed_rows,
            "out_of_bounds_rows": self.out_of_bounds_rows,
            "duplicate_rows": self.duplicate_rows,
            "conceptual_duplicate_rows_merged": (
                self.conceptual_duplicate_rows_merged
            ),
            "non_swissprot_rows": self.non_swissprot_rows,
            "malformed_reasons": dict(sorted(self.malformed_reasons.items())),
        }


@dataclass(frozen=True, slots=True)
class InterProRow:
    protein_accession: str
    interpro_accession: str
    entry_name: str
    signature_accession: str
    start: int
    end: int
    raw_value: str


@dataclass(frozen=True, slots=True)
class _ConceptualInterProSpan:
    interpro_accession: str
    start: int
    end: int


def parse_interpro_coordinates(
    source: InterProInput,
    swissprot_sequence_lengths: Mapping[str, int],
    *,
    audit: InterProParserAudit | None = None,
) -> Iterator[InterProCoordinateMatch]:
    """Yield exact InterPro 1-based inclusive intervals for target Swiss-Prot proteins.

    ``protein2ipr.dat.gz`` is read one line at a time. Beyond the supplied
    Swiss-Prot accession mapping, only the current protein group is retained. The
    official file is grouped by protein accession, so duplicate and conceptual-span
    tracking are bounded by the largest protein match group. Non-target rows with
    a nonempty accession are rejected before their remaining columns are parsed.
    """

    parser_audit = audit if audit is not None else InterProParserAudit()
    if isinstance(source, (str, PathLike)):
        path = Path(source)
        if path.suffix.casefold() == ".gz":
            with gzip.open(path, mode="rt", encoding="utf-8") as handle:
                yield from _parse_handle(handle, swissprot_sequence_lengths, parser_audit)
        else:
            with path.open(mode="r", encoding="utf-8") as handle:
                yield from _parse_handle(handle, swissprot_sequence_lengths, parser_audit)
        return

    yield from _parse_handle(source, swissprot_sequence_lengths, parser_audit)


def join_interpro_coordinates(
    records: Sequence[ProteinRecord],
    source: InterProInput,
    *,
    audit: InterProParserAudit | None = None,
) -> tuple[ProteinRecord, ...]:
    """Append streamed InterPro intervals to a materialized Swiss-Prot record sequence."""

    sequence_lengths: dict[str, int] = {}
    for record in records:
        if record.accession in sequence_lengths:
            raise ValueError(f"Duplicate Swiss-Prot accession: {record.accession}")
        sequence_lengths[record.accession] = len(record.sequence)

    annotations_by_accession: dict[str, list[LocalAnnotation]] = {}
    for match in parse_interpro_coordinates(
        source,
        sequence_lengths,
        audit=audit,
    ):
        annotations_by_accession.setdefault(match.protein_accession, []).append(
            match.annotation
        )

    return tuple(
        replace(
            record,
            local_annotations=(
                *record.local_annotations,
                *annotations_by_accession.get(record.accession, ()),
            ),
        )
        for record in records
    )


def _parse_handle(
    source: TextIO,
    swissprot_sequence_lengths: Mapping[str, int],
    audit: InterProParserAudit,
) -> Iterator[InterProCoordinateMatch]:
    current_accession = ""
    seen_rows: set[InterProRow] = set()
    conceptual_rows: dict[_ConceptualInterProSpan, list[InterProRow]] = {}

    for raw_line in source:
        audit.rows_seen += 1
        raw_value = raw_line.rstrip("\r\n")
        protein_accession, separator, _ = raw_value.partition("\t")
        if (
            separator
            and protein_accession
            and protein_accession not in swissprot_sequence_lengths
        ):
            if protein_accession != current_accession:
                yield from _emit_group(current_accession, conceptual_rows, audit)
                current_accession = protein_accession
                seen_rows.clear()
                conceptual_rows.clear()
            audit.non_swissprot_rows += 1
            continue

        row, malformed_reason = parse_interpro_row(raw_value)
        if malformed_reason is not None:
            audit.malformed_rows += 1
            audit.malformed_reasons[malformed_reason] += 1
            continue
        assert row is not None

        if row.protein_accession != current_accession:
            yield from _emit_group(current_accession, conceptual_rows, audit)
            current_accession = row.protein_accession
            seen_rows.clear()
            conceptual_rows.clear()
        if row in seen_rows:
            audit.duplicate_rows += 1
            continue
        seen_rows.add(row)

        if row.protein_accession not in swissprot_sequence_lengths:
            audit.non_swissprot_rows += 1
            continue
        sequence_length = swissprot_sequence_lengths[row.protein_accession]
        _validate_sequence_length(row.protein_accession, sequence_length)
        if row.start < 1 or row.end > sequence_length:
            audit.out_of_bounds_rows += 1
            continue

        conceptual_span = _ConceptualInterProSpan(
            interpro_accession=row.interpro_accession,
            start=row.start,
            end=row.end,
        )
        matching_rows = conceptual_rows.setdefault(conceptual_span, [])
        if matching_rows:
            audit.conceptual_duplicate_rows_merged += 1
        matching_rows.append(row)

    yield from _emit_group(current_accession, conceptual_rows, audit)


def _emit_group(
    protein_accession: str,
    conceptual_rows: Mapping[_ConceptualInterProSpan, Sequence[InterProRow]],
    audit: InterProParserAudit,
) -> Iterator[InterProCoordinateMatch]:
    for conceptual_span, rows in conceptual_rows.items():
        audit.rows_emitted += 1
        yield InterProCoordinateMatch(
            protein_accession=protein_accession,
            annotation=_local_annotation(
                protein_accession,
                conceptual_span,
                rows,
            ),
        )


def parse_interpro_row(raw_value: str) -> tuple[InterProRow | None, str | None]:
    columns = raw_value.split("\t")
    if len(columns) != 6:
        return None, "column_count"

    protein_accession, interpro_accession, entry_name, signature_accession = columns[:4]
    if not protein_accession:
        return None, "empty_protein_accession"
    if _INTERPRO_ACCESSION.fullmatch(interpro_accession) is None:
        return None, "invalid_interpro_accession"
    if not entry_name:
        return None, "empty_entry_name"
    if not signature_accession:
        return None, "empty_signature_accession"

    try:
        start = int(columns[4])
    except ValueError:
        return None, "non_integer_start"
    try:
        end = int(columns[5])
    except ValueError:
        return None, "non_integer_end"
    if end < start:
        return None, "reversed_interval"

    return (
        InterProRow(
            protein_accession=protein_accession,
            interpro_accession=interpro_accession,
            entry_name=entry_name,
            signature_accession=signature_accession,
            start=start,
            end=end,
            raw_value=raw_value,
        ),
        None,
    )


def _validate_sequence_length(accession: str, sequence_length: int) -> None:
    if (
        isinstance(sequence_length, bool)
        or not isinstance(sequence_length, int)
        or sequence_length < 1
    ):
        raise ValueError(
            f"Swiss-Prot sequence length for {accession!r} must be a positive integer"
        )


def _local_annotation(
    protein_accession: str,
    conceptual_span: _ConceptualInterProSpan,
    rows: Sequence[InterProRow],
) -> LocalAnnotation:
    signature_accessions = tuple(
        sorted({row.signature_accession for row in rows})
    )
    entry_names = tuple(
        sorted(
            {row.entry_name for row in rows},
            key=lambda value: (value.casefold(), value),
        )
    )
    raw_value = "\n".join(sorted({row.raw_value for row in rows}))
    preferred_entry_name = entry_names[0]
    term = TermAnnotation(
        key=TermKey(
            aspect=LOCAL_INTERPRO_ASPECT,
            source_database=INTERPRO_SOURCE_DATABASE,
            accession=conceptual_span.interpro_accession,
        ),
        label=preferred_entry_name,
        description=" | ".join(entry_names),
        raw_value=raw_value,
        relation="matches_at",
        source_references=signature_accessions,
    )
    return LocalAnnotation(
        term=term,
        start=conceptual_span.start,
        end=conceptual_span.end,
        feature_type=INTERPRO_FEATURE_TYPE,
        description=" | ".join(entry_names),
        feature_id=(
            f"{protein_accession}:IPR:{conceptual_span.interpro_accession}:"
            f"{conceptual_span.start}-{conceptual_span.end}"
        ),
        source_feature_id=(
            signature_accessions[0] if len(signature_accessions) == 1 else ""
        ),
    )


__all__ = [
    "INTERPRO_FEATURE_TYPE",
    "INTERPRO_SOURCE_DATABASE",
    "LOCAL_INTERPRO_ASPECT",
    "InterProCoordinateMatch",
    "InterProRow",
    "InterProInput",
    "InterProParserAudit",
    "join_interpro_coordinates",
    "parse_interpro_row",
    "parse_interpro_coordinates",
]
