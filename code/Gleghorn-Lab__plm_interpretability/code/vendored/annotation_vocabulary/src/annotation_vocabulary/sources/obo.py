"""Streaming parser for the fields needed from an OBO file: GO Basic, and the other OBO ontologies the compendium reads.

A term keeps its `is_a` parents, its other typed relationships (`part_of` and the rest, as `(relation, target)` pairs), its
definition text and its synonyms with their sources, so a reader that needs only names and parents is unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from foundry.compression import open_text_maybe_gzip


@dataclass(frozen=True)
class OBOTerm:
    """A GO term stanza reduced to migration-relevant fields."""

    id: str
    name: str | None
    namespace: str | None
    alt_ids: tuple[str, ...]
    is_obsolete: bool
    replaced_by: tuple[str, ...]
    consider: tuple[str, ...]
    parents: tuple[str, ...] = ()
    # `relationship:` lines as (relation, target), such as ("part_of", "GO:0005634"), in file order, each once.
    relationships: tuple[tuple[str, str], ...] = ()
    # The quoted text of the `def:` line, without its references.
    definition: str | None = None
    # `synonym:` lines as (text, source), the quoted text and its bracketed cross-references, such as ("2-oxoglutarate",
    # "uniprot_ft"), in file order.
    synonyms: tuple[tuple[str, str], ...] = ()

    @property
    def replacement_targets(self) -> tuple[str, ...]:
        """Return only targets that GO marks safe for automatic replacement."""

        return _unique(self.replaced_by)

    @property
    def manual_review_targets(self) -> tuple[str, ...]:
        """Return GO ``consider`` suggestions without treating them as replacements."""

        return _unique(self.consider)


class OBOIndex:
    """Current-term lookup and explicit obsolete-term replacement mappings."""

    def __init__(self, terms: tuple[OBOTerm, ...]) -> None:
        self.terms = terms
        self.current_lookup: dict[str, OBOTerm] = {}
        self.replacement_map: dict[str, tuple[str, ...]] = {}
        self.consider_map: dict[str, tuple[str, ...]] = {}
        self.parent_map: dict[str, tuple[str, ...]] = {}
        for term in terms:
            self.parent_map[term.id] = term.parents
            if term.is_obsolete:
                self.replacement_map[term.id] = term.replacement_targets
                self.consider_map[term.id] = term.manual_review_targets
                continue
            self.current_lookup[term.id] = term
            for alt_id in term.alt_ids:
                self.current_lookup[alt_id] = term

    @classmethod
    def from_file(cls, path: Path) -> OBOIndex:
        """Parse terms from a plain or gzip OBO file without loading it as one string."""

        with open_text_maybe_gzip(path, encoding="utf-8") as source:
            return cls(tuple(iter_terms(source)))

    def lookup(self, term_id: str) -> OBOTerm | None:
        """Return the current term for a canonical or alternate ID."""

        return self.current_lookup.get(term_id)

    def replacements(self, term_id: str) -> tuple[str, ...]:
        """Return only automatic ``replaced_by`` targets for an obsolete ID."""

        return self.replacement_map.get(term_id, ())

    def considerations(self, term_id: str) -> tuple[str, ...]:
        """Return manual-review ``consider`` suggestions for an obsolete ID."""

        return self.consider_map.get(term_id, ())

    def parents(self, term_id: str) -> tuple[str, ...]:
        """Return direct ``is_a`` parent GO identifiers for a canonical term."""

        current = self.lookup(term_id)
        canonical_id = current.id if current is not None else term_id
        return self.parent_map.get(canonical_id, ())


def iter_terms(source: TextIO) -> Iterator[OBOTerm]:
    """Yield ``[Term]`` stanzas incrementally from an open OBO stream."""

    fields: dict[str, list[str]] = {}
    in_term = False
    for raw_line in source:
        line = raw_line.strip()
        if not line:
            if in_term:
                yield _term_from_fields(fields)
                fields = {}
                in_term = False
            continue
        if line.startswith("["):
            if in_term:
                yield _term_from_fields(fields)
                fields = {}
            in_term = line == "[Term]"
            continue
        if not in_term or line.startswith("!") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields.setdefault(key, []).append(value.strip())
    if in_term:
        yield _term_from_fields(fields)


def _term_from_fields(fields: dict[str, list[str]]) -> OBOTerm:
    term_id = _single(fields, "id")
    if term_id is None:
        raise ValueError("OBO Term stanza is missing id")
    return OBOTerm(
        id=term_id,
        name=_single(fields, "name"),
        namespace=_single(fields, "namespace"),
        alt_ids=tuple(fields.get("alt_id", ())),
        is_obsolete=_single(fields, "is_obsolete") == "true",
        replaced_by=tuple(fields.get("replaced_by", ())),
        consider=tuple(fields.get("consider", ())),
        parents=_references(fields.get("is_a", ())),
        relationships=_relationships(fields.get("relationship", ())),
        definition=_quoted(_single(fields, "def")),
        synonyms=_synonyms(fields.get("synonym", ())),
    )


def _relationships(values: list[str] | tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """`part_of GO:0005634 ! nucleus` lines as (relation, target) pairs, each once; a line without a target is skipped."""
    pairs: list[tuple[str, str]] = []
    for value in values:
        parts = value.split("!", 1)[0].split()
        if len(parts) >= 2:
            pairs.append((parts[0], parts[1]))
    return tuple(dict.fromkeys(pairs))


def _synonyms(values: list[str] | tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """`"2-oxoglutarate" RELATED [uniprot_ft]` values as (text, source) pairs, the source the bracketed list the value ends with;
    a value without quoted text is skipped."""
    pairs: list[tuple[str, str]] = []
    for value in values:
        text = _quoted(value)
        if text is not None:
            pairs.append((text, value[value.rfind("[") + 1:-1].strip() if value.endswith("]") else ""))
    return tuple(pairs)


def _quoted(value: str | None) -> str | None:
    """The quoted text a `def:` or `synonym:` value opens with, such as `"A membrane." [GOC:mah]`, unescaped; None when it holds
    no quoted text."""
    if not value or not value.startswith('"'):
        return None
    text, escaped = [], False
    for character in value[1:]:
        if escaped:
            text.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"':
            return "".join(text)
        else:
            text.append(character)
    return None


def _single(fields: dict[str, list[str]], key: str) -> str | None:
    values = fields.get(key, [])
    return values[0] if values else None


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _references(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    references = tuple(value.split("!", 1)[0].strip() for value in values)
    return _unique(tuple(reference for reference in references if reference))
