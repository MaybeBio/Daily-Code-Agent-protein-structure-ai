"""Domain records shared by vocabulary construction, migration, and analysis."""

import re

from dataclasses import dataclass, field
from typing import Any


TERM_ID_PREFIX = "av"
TERM_ID_SEPARATOR = "::"
_SEQUENCE_PATTERN = re.compile(r"[A-Z]+")


def canonical_term_id(aspect: str, source_database: str, accession: str) -> str:
    """Return the stable project identifier for one namespaced biological term."""
    components = {
        "aspect": aspect,
        "source_database": source_database,
        "accession": accession,
    }
    for name, value in components.items():
        if not value or value.strip() != value:
            raise ValueError(f"{name} must be non-empty and stripped")
        if TERM_ID_SEPARATOR in value:
            raise ValueError(f"{name} cannot contain {TERM_ID_SEPARATOR!r}")

    return TERM_ID_SEPARATOR.join((TERM_ID_PREFIX, aspect, source_database, accession))


@dataclass(frozen=True, slots=True)
class TermKey:
    """Canonical identity of one term, independent of any integer token."""

    aspect: str
    source_database: str
    accession: str

    def __post_init__(self) -> None:
        canonical_term_id(self.aspect, self.source_database, self.accession)

    @property
    def term_id(self) -> str:
        """Return the canonical string identity."""
        return canonical_term_id(self.aspect, self.source_database, self.accession)

    @classmethod
    def from_term_id(cls, term_id: str) -> "TermKey":
        """Parse a canonical term identifier."""
        parts = term_id.split(TERM_ID_SEPARATOR, 3)
        if len(parts) != 4 or parts[0] != TERM_ID_PREFIX:
            raise ValueError(f"Invalid canonical term identifier: {term_id!r}")
        return cls(aspect=parts[1], source_database=parts[2], accession=parts[3])


@dataclass(frozen=True, slots=True)
class TermAnnotation:
    """One source-backed annotation attached to a protein."""

    key: TermKey
    label: str
    description: str = ""
    evidence: tuple[str, ...] = ()
    raw_value: str = ""
    relation: str = ""
    negated: bool = False
    source_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("Term label must be non-empty")


@dataclass(frozen=True, slots=True)
class LocalAnnotation:
    """One exact residue or interval annotation in sequence coordinates."""

    term: TermAnnotation
    start: int
    end: int
    feature_type: str
    description: str = ""
    feature_id: str = ""
    source_feature_id: str = ""
    start_modifier: str = ""
    end_modifier: str = ""
    ligand_chebi_id: str = ""
    ligand_label: str = ""
    pair_member: int | None = None

    def __post_init__(self) -> None:
        if self.start < 1:
            raise ValueError("Local annotation start must be at least 1")
        if self.end < self.start:
            raise ValueError("Local annotation end cannot precede its start")
        if not self.feature_type:
            raise ValueError("Local annotation feature_type must be non-empty")
        if self.pair_member not in (None, 1, 2):
            raise ValueError("pair_member must be 1, 2, or None")


@dataclass(frozen=True, slots=True)
class ProteinRecord:
    """Parsed Swiss-Prot protein with global and coordinate-bearing annotations."""

    accession: str
    sequence: str
    entry_name: str = ""
    organism: str = ""
    taxon_id: int | None = None
    lineage_names: tuple[str, ...] = ()
    lineage_taxon_ids: tuple[int, ...] = ()
    entry_version: int | None = None
    sequence_version: int | None = None
    global_annotations: tuple[TermAnnotation, ...] = ()
    local_annotations: tuple[LocalAnnotation, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        if not self.accession.strip():
            raise ValueError("Protein accession must be non-empty")
        if not self.sequence or _SEQUENCE_PATTERN.fullmatch(self.sequence) is None:
            raise ValueError("Protein sequence must contain uppercase residue letters only")
        if any(
            not isinstance(name, str) or not name or name.strip() != name
            for name in self.lineage_names
        ):
            raise ValueError("Lineage names must be non-empty stripped strings")
        if any(type(taxon_id) is not int or taxon_id < 1 for taxon_id in self.lineage_taxon_ids):
            raise ValueError("Lineage taxon IDs must be positive integers")
        if self.lineage_taxon_ids and len(self.lineage_taxon_ids) != len(self.lineage_names):
            raise ValueError("Lineage taxon IDs and names must have equal length")

        sequence_length = len(self.sequence)
        invalid = [
            annotation
            for annotation in self.local_annotations
            if annotation.end > sequence_length
        ]
        if invalid:
            raise ValueError(
                f"{len(invalid)} local annotations exceed sequence length {sequence_length}"
            )
