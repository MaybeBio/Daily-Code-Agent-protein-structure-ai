"""Streaming parser and ambiguity-aware index for UniProt vocabularies."""

from __future__ import annotations

import unicodedata

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO


LookupStatus = Literal["missing", "unique", "ambiguous"]
RecordType = Literal[
    "keyword",
    "keyword_category",
    "disease",
    "subcellular_location",
    "membrane_topology",
    "membrane_orientation",
    "ptm",
]
HierarchyRelation = Literal["is_a", "part_of"]

_RECORD_START_CODES = frozenset({"ID", "IC", "IT", "IO"})
_SOURCE_DATABASE_BY_PREFIX = {
    "KW": "UniProtKB-KW",
    "DI": "UniProtKB-Disease",
    "SL": "UniProtKB-Subcellular-Location",
    "PTM": "UniProtKB-PTM",
}


@dataclass(frozen=True)
class VocabularyReference:
    """A parsed external reference from a ``DR`` or ``GO`` line."""

    database: str
    identifier: str
    description: str | None = None


@dataclass(frozen=True)
class HierarchyLink:
    """One UniProt is-a or part-of hierarchy path."""

    relation: HierarchyRelation
    path: tuple[str, ...]


@dataclass(frozen=True)
class UniProtVocabularyRecord:
    """Fields shared by keyword, disease, subcellular and PTM (`ptmlist.txt`) records."""

    stable_id: str
    label: str
    source_database: str
    record_type: RecordType
    definition: str
    synonyms: tuple[str, ...]
    cross_references: tuple[VocabularyReference, ...]
    go_links: tuple[VocabularyReference, ...]
    hierarchy: tuple[HierarchyLink, ...]
    location_paths: tuple[str, ...] = ()
    # A keyword's category (`CA`), such as "Ligand".
    category: str | None = None
    # `KW` lines: the keyword a location implies (`KW-0496; Mitochondrion` in subcell.txt) or a modification implies, by name
    # alone in ptmlist.txt (identifier "").
    keyword_links: tuple[VocabularyReference, ...] = ()
    # A modification's feature key (`FT`, such as MOD_RES), the residue it modifies (`TG`) and where on the chain (`PP`, such as
    # "Anywhere" or "N-terminal"; a cross-link's two residues joined, "Anywhere-C-terminal").
    feature_key: str | None = None
    target: str | None = None
    position: str | None = None


@dataclass(frozen=True)
class VocabularyLookupResult:
    """All records matching a normalized query, with explicit cardinality."""

    normalized_query: str
    matches: tuple[UniProtVocabularyRecord, ...]

    @property
    def status(self) -> LookupStatus:
        if not self.matches:
            return "missing"
        if len(self.matches) == 1:
            return "unique"
        return "ambiguous"

    @property
    def unique_record(self) -> UniProtVocabularyRecord | None:
        """Return the sole match, never selecting from ambiguous matches."""

        return self.matches[0] if len(self.matches) == 1 else None


class UniProtVocabularyIndex:
    """Stable-ID, normalized-name, and external-reference lookup."""

    def __init__(self, records: Iterable[UniProtVocabularyRecord]) -> None:
        self.records = tuple(records)
        self._stable_id_lookup: dict[str, UniProtVocabularyRecord] = {}
        name_matches: dict[str, dict[str, UniProtVocabularyRecord]] = {}
        xref_matches: dict[tuple[str, str], dict[str, UniProtVocabularyRecord]] = {}
        location_path_matches: dict[str, dict[str, UniProtVocabularyRecord]] = {}

        for record in self.records:
            stable_key = _normalize_identifier(record.stable_id)
            if stable_key in self._stable_id_lookup:
                raise ValueError(f"duplicate UniProt vocabulary accession: {record.stable_id}")
            self._stable_id_lookup[stable_key] = record

            for name in (record.label, *record.synonyms):
                name_key = normalize_name(name)
                if name_key:
                    name_matches.setdefault(name_key, {})[record.stable_id] = record

            for reference in (*record.cross_references, *record.go_links):
                xref_key = _normalize_xref(reference.database, reference.identifier)
                xref_matches.setdefault(xref_key, {})[record.stable_id] = record

            for location_path in record.location_paths:
                path_key = normalize_name(location_path)
                if path_key:
                    location_path_matches.setdefault(path_key, {})[record.stable_id] = record

        self._name_lookup = _finalize_matches(name_matches)
        self._xref_lookup = _finalize_matches(xref_matches)
        self._location_path_lookup = _finalize_matches(location_path_matches)

    @classmethod
    def from_file(cls, path: Path) -> UniProtVocabularyIndex:
        """Parse one UniProt controlled-vocabulary file."""

        with path.open("r", encoding="utf-8") as source:
            return cls(iter_records(source))

    @classmethod
    def from_files(cls, paths: Iterable[Path]) -> UniProtVocabularyIndex:
        """Parse and combine several controlled-vocabulary files."""

        records: list[UniProtVocabularyRecord] = []
        for path in paths:
            with path.open("r", encoding="utf-8") as source:
                records.extend(iter_records(source))
        return cls(records)

    def lookup_stable_id(self, stable_id: str) -> UniProtVocabularyRecord | None:
        """Return the record for a stable UniProt vocabulary accession."""

        return self._stable_id_lookup.get(_normalize_identifier(stable_id))

    def lookup_name(self, name: str) -> VocabularyLookupResult:
        """Look up a label or synonym without resolving ambiguous names."""

        normalized_name = normalize_name(name)
        return VocabularyLookupResult(
            normalized_query=normalized_name,
            matches=self._name_lookup.get(normalized_name, ()),
        )

    def lookup_external_xref(self, database: str, identifier: str) -> VocabularyLookupResult:
        """Look up an external reference without resolving ambiguous links."""

        key = _normalize_xref(database, identifier)
        return VocabularyLookupResult(
            normalized_query=f"{key[0]}:{key[1]}",
            matches=self._xref_lookup.get(key, ()),
        )

    def lookup_xref(self, database: str, identifier: str) -> VocabularyLookupResult:
        """Alias for :meth:`lookup_external_xref`."""

        return self.lookup_external_xref(database, identifier)

    def lookup_location_path(self, path: str) -> VocabularyLookupResult:
        """Look up an exact normalized ``SL`` path without selecting ambiguity."""

        normalized_path = normalize_name(path)
        return VocabularyLookupResult(
            normalized_query=normalized_path,
            matches=self._location_path_lookup.get(normalized_path, ()),
        )


def normalize_name(value: str) -> str:
    """Normalize case, Unicode, spacing, and flat-file terminal punctuation."""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.split())
    return _strip_terminal_period(normalized).casefold()


def iter_records(source: TextIO) -> Iterator[UniProtVocabularyRecord]:
    """Yield block records from a UniProt controlled-vocabulary stream."""

    fields: list[tuple[str, str]] | None = None
    for raw_line in source:
        line = raw_line.rstrip("\r\n")
        if line == "//":
            if fields is not None:
                yield _record_from_fields(fields)
                fields = None
            continue

        parsed = _parse_field_line(line)
        if parsed is None:
            continue
        code, value = parsed
        if code in _RECORD_START_CODES:
            if fields is not None:
                raise ValueError("UniProt vocabulary record is missing its // terminator")
            fields = [(code, value)]
        elif fields is not None:
            fields.append((code, value))

    if fields is not None:
        raise ValueError("unterminated UniProt vocabulary record")


def _record_from_fields(fields: list[tuple[str, str]]) -> UniProtVocabularyRecord:
    start_code, raw_label = fields[0]
    stable_id = _single_value(fields, "AC")
    prefix = stable_id.partition("-")[0].upper()
    try:
        source_database = _SOURCE_DATABASE_BY_PREFIX[prefix]
    except KeyError as error:
        raise ValueError(f"unsupported UniProt vocabulary accession: {stable_id}") from error

    return UniProtVocabularyRecord(
        stable_id=stable_id,
        label=_strip_terminal_period(raw_label),
        source_database=source_database,
        record_type=_record_type(prefix, start_code),
        definition=join_wrapped(_values(fields, "DE")),
        synonyms=_parse_synonyms(_values(fields, "SY")),
        cross_references=tuple(_parse_dr(value) for value in _values(fields, "DR")),
        go_links=tuple(_parse_go(value) for value in _values(fields, "GO")),
        hierarchy=tuple(
            _parse_hierarchy(code, value)
            for code, value in fields
            if code in {"HI", "HP"}
        ),
        location_paths=_values(fields, "SL"),
        category=_optional_value(fields, "CA"),
        keyword_links=tuple(_parse_keyword_link(value) for value in _values(fields, "KW")),
        feature_key=_optional_value(fields, "FT"),
        target=_optional_value(fields, "TG"),
        position=_optional_value(fields, "PP"),
    )


def _optional_value(fields: list[tuple[str, str]], code: str) -> str | None:
    """The first line of `code`, without its terminal period, or None when the record has none."""
    values = _values(fields, code)
    return _strip_terminal_period(values[0]) or None if values else None


def _parse_keyword_link(value: str) -> VocabularyReference:
    """A `KW` line: `KW-0496; Mitochondrion.` names a keyword by accession, `Phosphoprotein.` by its name alone."""
    parts = _reference_parts(value)
    if not parts:
        raise ValueError("empty UniProt KW line")
    if parts[0].upper().startswith("KW-"):
        return VocabularyReference("UniProtKB-KW", parts[0], "; ".join(parts[1:]) or None)
    return VocabularyReference("UniProtKB-KW", "", "; ".join(parts))


def _record_type(prefix: str, start_code: str) -> RecordType:
    if prefix == "PTM" and start_code == "ID":
        return "ptm"
    if prefix == "KW":
        if start_code == "IC":
            return "keyword_category"
        if start_code == "ID":
            return "keyword"
    elif prefix == "DI" and start_code == "ID":
        return "disease"
    elif prefix == "SL":
        record_types: dict[str, RecordType] = {
            "ID": "subcellular_location",
            "IT": "membrane_topology",
            "IO": "membrane_orientation",
        }
        if start_code in record_types:
            return record_types[start_code]
    raise ValueError(f"invalid {start_code} record for a {prefix} accession")


def _parse_field_line(line: str) -> tuple[str, str] | None:
    if len(line) < 5 or line[2:5] != "   ":
        return None
    code = line[:2]
    if not code.isalpha() or not code.isupper():
        return None
    return code, line[5:].strip()


def _single_value(fields: list[tuple[str, str]], code: str) -> str:
    values = _values(fields, code)
    if len(values) != 1 or not values[0]:
        raise ValueError(f"UniProt vocabulary record requires exactly one {code} line")
    return _strip_terminal_period(values[0])


def _values(fields: list[tuple[str, str]], code: str) -> tuple[str, ...]:
    return tuple(value for observed_code, value in fields if observed_code == code)


def join_wrapped(values: Iterable[str]) -> str:
    """A field's wrapped lines as one text. A line that ends in a hyphen breaks inside a word, as UniProt's files and ENZYME's
    break a long chemical name, so the next joins it without a space, unless the next begins "and " or "or " after a suspended
    hyphen ("alternating alpha-(1->6)- and alpha-(1->3)-linkages")."""
    joined = ""
    for value in values:
        if not joined:
            joined = value
        elif joined.endswith("-") and not value.startswith(("and ", "or ")):
            joined += value
        else:
            joined += f" {value}"
    return joined


def _parse_synonyms(values: tuple[str, ...]) -> tuple[str, ...]:
    synonyms: list[str] = []
    pending = ""
    for value in values:
        pending = join_wrapped((pending, value)) if pending else value
        parts = pending.split(";")
        pending = parts.pop()
        synonyms.extend(part.strip() for part in parts if part.strip())
        if pending.rstrip().endswith("."):
            synonyms.append(_strip_terminal_period(pending))
            pending = ""
    if pending.strip():
        synonyms.append(_strip_terminal_period(pending))
    return tuple(dict.fromkeys(synonym for synonym in synonyms if synonym))


def _parse_dr(value: str) -> VocabularyReference:
    parts = _reference_parts(value)
    if len(parts) < 2:
        raise ValueError(f"malformed UniProt DR line: {value}")
    description = "; ".join(parts[2:]) or None
    return VocabularyReference(parts[0], parts[1], description)


def _parse_go(value: str) -> VocabularyReference:
    parts = _reference_parts(value)
    if not parts or not parts[0].upper().startswith("GO:"):
        raise ValueError(f"malformed UniProt GO line: {value}")
    description = "; ".join(parts[1:]) or None
    return VocabularyReference("GO", parts[0], description)


def _reference_parts(value: str) -> tuple[str, ...]:
    stripped = _strip_terminal_period(value)
    return tuple(part.strip() for part in stripped.split(";") if part.strip())


def _parse_hierarchy(code: str, value: str) -> HierarchyLink:
    relation: HierarchyRelation = "is_a" if code == "HI" else "part_of"
    path = tuple(
        _strip_terminal_period(part.strip()) for part in value.split(";") if part.strip()
    )
    if not path:
        raise ValueError(f"empty UniProt {code} hierarchy line")
    return HierarchyLink(relation, path)


def _strip_terminal_period(value: str) -> str:
    stripped = value.strip()
    return stripped[:-1].rstrip() if stripped.endswith(".") else stripped


def _normalize_identifier(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return _strip_terminal_period("".join(normalized.split())).casefold()


def _normalize_xref(database: str, identifier: str) -> tuple[str, str]:
    return normalize_name(database), _normalize_identifier(identifier)


def _finalize_matches(
    matches: dict[object, dict[str, UniProtVocabularyRecord]],
) -> dict[object, tuple[UniProtVocabularyRecord, ...]]:
    return {
        key: tuple(record_by_id[stable_id] for stable_id in sorted(record_by_id))
        for key, record_by_id in matches.items()
    }
