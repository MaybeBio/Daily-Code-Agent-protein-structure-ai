"""The ontologies the compendium's terms sit in, read into typed edges between concepts and the concepts' names.

An edge (`tables.HIERARCHY_SCHEMA`) joins two concepts, a term's (source database, accession) without its aspect, and says how:
`is_a` and `part_of` for GO, locations, keywords, PSI-MOD, ChEBI, Reactome and UniProt's pathway and family paths, `ec_parent`
for EC's classes, `lineage` between taxa of named ranks, `clan_member` for a Pfam or MEROPS family's clan, `family_member` for a
MEROPS code's family, and `maps_to` for a modification of `ptmlist.txt` and its PSI-MOD term. The compendium stores asserted
terms; a view propagates along these edges.

Each reader takes the file a source ships and returns `Ontology`: its edges, its concepts (`tables.CONCEPT_SCHEMA`) and, where a
later stage needs it, a lookup (keyword categories, the keywords a location or modification implies, taxa by named rank). A
concept's definition is its source's: GO's, a keyword's or location's, ChEBI's and PSI-MOD's text, an EC number's catalytic
activity, a modification's PSI-MOD definition, the first paragraph of an InterPro entry's abstract, and a MEROPS code's family;
the rest name their concepts without one.
"""

from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET

from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from foundry.compression import open_text_maybe_gzip
from ..sources.obo import OBOIndex, iter_terms
from ..sources.taxonomy import Taxonomy, TaxonomyError
from ..sources.uniprot_vocab import UniProtVocabularyRecord, iter_records, join_wrapped, normalize_name


Edge = tuple[str, str, str, str, str]
Concept = tuple[str, str, str, str, str]
GO_NAMESPACE_KINDS = {"biological_process": "go_bp", "molecular_function": "go_mf", "cellular_component": "go_cc"}
# Named ranks, broadest first. NCBI renamed its top rank from superkingdom to domain in 2025; either is the domain.
RANKS = ("domain", "kingdom", "phylum", "class", "order", "family", "genus", "species")
RANK_ALIASES = {"superkingdom": "domain", "domain": "domain"}
ENZCLASS_LINE = re.compile(r"^([1-7])\.\s*(\d+|-)\.\s*(\d+|-)\.\s*(\d+|-)\s+(.+?)\.?$")
# The brackets an InterPro abstract keeps once its `cite` elements are dropped, then the parentheses that held only those
# brackets or a citation, and the space left before punctuation.
EMPTY_BRACKETS = re.compile(r"\[[\s,;]*\]")
EMPTY_PARENTHESES = re.compile(r"\([\s,;]*\)")
SPACE_BEFORE = re.compile(r"\s+([,.;:)\]])")
# MEROPS's braces, which mark a name's italics, and the space a tab inside them leaves after a parenthesis.
MEROPS_ITALICS = re.compile(r"[{}]")
MEROPS_OPENING_SPACE = re.compile(r"\(\s+")


@dataclass(slots=True)
class Ontology:
    """Edges and concepts of one source, and whatever lookup a later stage reads from it."""

    edges: list[Edge] = field(default_factory=list)
    concepts: list[Concept] = field(default_factory=list)

    def extend(self, other: Ontology) -> None:
        self.edges.extend(other.edges)
        self.concepts.extend(other.concepts)


def go_ontology(path: Path) -> tuple[Ontology, OBOIndex]:
    """Every current GO term with its namespace, name and definition, its `is_a` parents and its `part_of` relations."""
    index = OBOIndex.from_file(path)
    found = Ontology()
    for term in index.terms:
        if term.is_obsolete:
            continue
        found.concepts.append(("GO", term.id, term.name or term.id, term.definition or "", GO_NAMESPACE_KINDS.get(term.namespace or "", "")))
        found.edges.extend(("GO", term.id, "GO", parent, "is_a") for parent in term.parents)
        found.edges.extend(("GO", term.id, "GO", target, "part_of") for relation, target in term.relationships if relation == "part_of")
    return found, index


def descendants(index: OBOIndex, root: str) -> frozenset[str]:
    """`root` and every current GO term below it by `is_a`."""
    children: dict[str, list[str]] = {}
    for term in index.terms:
        if not term.is_obsolete:
            for parent in term.parents:
                children.setdefault(parent, []).append(term.id)
    found, pending = {root}, [root]
    while pending:
        for child in children.get(pending.pop(), ()):
            if child not in found:
                found.add(child)
                pending.append(child)
    return frozenset(found)


def ec_parent(number: str) -> str | None:
    """The class one level above an EC number or class: 1.1.1.1 gives 1.1.1.-, and 1.-.-.- has none."""
    parts = number.split(".")
    known = [part for part in parts if part != "-"]
    if len(parts) != 4 or len(known) <= 1:
        return None
    return ".".join(known[:-1] + ["-"] * (5 - len(known)))


def enzyme_ontology(enzyme_dat: Path, enzclass: Path) -> Ontology:
    """EC numbers and classes, each joined to the class above it, an EC number defined by its catalytic activity (its `CA` lines,
    each numbered reaction in order); a transferred or deleted entry is a concept of that kind. A name or reaction wrapped after a
    hyphen, as ENZYME breaks a long chemical name, joins without a space (`join_wrapped`)."""
    found = Ontology()
    with open_text_maybe_gzip(enzclass, encoding="utf-8") as handle:
        for line in handle:
            matched = ENZCLASS_LINE.match(line.strip())
            if matched:
                number = ".".join(matched.group(index) for index in range(1, 5))
                found.concepts.append(("EC", number, matched.group(5).strip(), "", "class"))
    numbers: list[tuple[str, str, str, str]] = []
    with open_text_maybe_gzip(enzyme_dat, encoding="utf-8") as handle:
        identifier, names, reactions = "", [], []
        for line in handle:
            code, value = line[:2], line[5:].strip()
            if code == "ID":
                identifier, names, reactions = value, [], []
            elif code == "DE":
                names.append(value)
            elif code == "CA":
                reactions.append(value)
            elif code == "//" and identifier:
                name = join_wrapped(names).rstrip(".")
                kind = "transferred" if name.startswith("Transferred entry") else "deleted" if name.startswith("Deleted entry") else "enzyme"
                numbers.append((identifier, name, join_wrapped(reactions), kind))
                identifier = ""
    for number, name, reaction, kind in numbers:
        found.concepts.append(("EC", number, name, reaction, kind))
    for _, number, _, _, _ in list(found.concepts):
        parent = ec_parent(number)
        if parent is not None:
            found.edges.append(("EC", number, "EC", parent, "ec_parent"))
    return found


def taxonomy(taxdump: Path, wanted: Collection[int]) -> tuple[Ontology, dict[int, dict[str, int]]]:
    """The taxa of named ranks above each wanted taxon, their names, and the lineage edges between them.

    `taxdump` is NCBI's `taxdump.tar.gz`, read by `sources.taxonomy.Taxonomy`, which follows a taxon merged since the entry was
    written to the one it merged into. Returns each wanted taxon's ancestor at every named rank it has (itself, or what it merged
    into, included), by rank, as taxon identifiers; a deleted taxon, or one the dump never held, is absent.
    """
    dump = Taxonomy.from_tarball(taxdump)
    ranked: dict[int, dict[str, int]] = {}
    needed: set[int] = set()
    for taxon in set(wanted):
        try:
            lineage = dump.lineage(taxon)
        except TaxonomyError:
            continue
        chain: dict[str, int] = {}
        # Leaf first, so a rank that appears twice names the taxon nearest the leaf.
        for record in reversed(lineage):
            named = RANK_ALIASES.get(record.rank, record.rank)
            if named in RANKS and named not in chain:
                chain[named] = record.tax_id
        ranked[taxon] = chain
        needed.update(chain.values())
    found = Ontology()
    for taxon in sorted(needed):
        record = dump.records[taxon]
        found.concepts.append(("NCBITaxon", str(taxon), record.scientific_name, "", RANK_ALIASES.get(record.rank, record.rank)))
    edges: set[Edge] = set()
    for chain in ranked.values():
        ordered = [chain[name] for name in RANKS if name in chain]
        for broader, narrower in zip(ordered, ordered[1:], strict=False):
            edges.add(("NCBITaxon", str(narrower), "NCBITaxon", str(broader), "lineage"))
    found.edges.extend(sorted(edges))
    return found, ranked


def abstract_text(element: ET.Element) -> str:
    """An InterPro abstract element's text and its children's, a cross-reference as its accession and a citation as nothing."""
    parts = [element.text or ""]
    for child in element:
        if child.tag == "db_xref":
            parts.append(child.get("dbkey", ""))
        elif child.tag != "cite":
            parts.append(abstract_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def interpro_abstracts(path: Path) -> dict[str, str]:
    """Each InterPro entry's definition: the first paragraph of its abstract in `interpro.xml.gz` as plain text, its citations
    cut. An abstract a language model wrote that no curator reviewed (`is-llm` without `is-llm-reviewed`) defines nothing."""
    found: dict[str, str] = {}
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if element.tag != "interpro":
                continue
            abstract = element.find("abstract")
            if abstract is not None and (abstract.get("is-llm") != "true" or abstract.get("is-llm-reviewed") == "true"):
                paragraph = abstract.find("p")
                text = EMPTY_PARENTHESES.sub("", EMPTY_BRACKETS.sub("", abstract_text(abstract if paragraph is None else paragraph)))
                found[element.get("id", "")] = SPACE_BEFORE.sub(r"\1", " ".join(text.split()))
            element.clear()
    return found


def interpro_ontology(parent_child: Path, entry_list: Path, abstracts: Path) -> Ontology:
    """InterPro entries with their type, name and definition (`interpro_abstracts`), each joined to its parent in
    `ParentChildTreeFile.txt`."""
    defined = interpro_abstracts(abstracts)
    found = Ontology()
    with open_text_maybe_gzip(entry_list, encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) == 3 and fields[0].startswith("IPR"):
                found.concepts.append(("InterPro", fields[0], fields[2], defined.get(fields[0], ""), fields[1]))
    stack: list[str] = []
    with open_text_maybe_gzip(parent_child, encoding="utf-8") as handle:
        for line in handle:
            stripped = line.rstrip("\r\n")
            if not stripped:
                continue
            depth = (len(stripped) - len(stripped.lstrip("-"))) // 2
            accession = stripped.lstrip("-").split("::", 1)[0]
            del stack[depth:]
            if stack:
                found.edges.append(("InterPro", accession, "InterPro", stack[-1], "is_a"))
            stack.append(accession)
    return found


def pfam_ontology(clans: Path) -> Ontology:
    """Pfam families with their identifier and description, each joined to its clan when it has one."""
    found = Ontology()
    named: set[str] = set()
    with gzip.open(clans, "rt", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < 5 or not fields[0].startswith("PF"):
                continue
            family, clan, clan_id, family_id, description = fields[:5]
            found.concepts.append(("Pfam", family, family_id, description, "family"))
            if clan.startswith("CL"):
                found.edges.append(("Pfam", family, "Pfam", clan, "clan_member"))
                if clan not in named:
                    named.add(clan)
                    found.concepts.append(("Pfam", clan, clan_id, "", "clan"))
    return found


def merops_ontology(names: Path, families: Path) -> Ontology:
    """MEROPS's peptidase and inhibitor codes, each named by its recommended ("real") name in `protein_name.txt` and defined by
    its family in `family.txt`: the family's kind, clan and type example. A code is its family's identifier, a dot and a number or
    letters (S14.001, I04.UPW); each code is a `family_member` of its family, and a family of a clan its `clan_member`. A name that
    holds a tab spans more fields, and MEROPS's braces, which mark italics, are dropped."""
    found = Ontology()
    family_of: dict[str, tuple[str, str, str]] = {}
    clans: set[str] = set()
    for line in families.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) < 7 or not fields[0]:
            continue
        family, clan, example, kind = fields[0], fields[1], fields[3].strip(), fields[6] or "peptidase"
        # "A-" and its kind gather a catalytic type's families of no clan; "RM" holds families MEROPS moved elsewhere.
        clan = clan if clan and not clan.endswith("-") and clan != "RM" else ""
        family_of[family] = (clan, example, kind)
        found.concepts.append(("MEROPS", family, family, f"{merops_family_text(family, clan, example, kind)}.", "family"))
        if clan:
            found.edges.append(("MEROPS", family, "MEROPS", clan, "clan_member"))
            if clan not in clans:
                clans.add(clan)
                found.concepts.append(("MEROPS", clan, clan, "", "clan"))
    for line in names.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) < 4 or fields[-2] != "real":
            continue
        code = fields[0]
        name = MEROPS_OPENING_SPACE.sub("(", " ".join(MEROPS_ITALICS.sub("", "\t".join(fields[1:-2])).split()))
        family = code.split(".")[0]
        held = family_of.get(family)
        found.concepts.append(("MEROPS", code, name or code, f"A member of {merops_family_text(family, *held)}." if held else "",
                               held[2] if held else "code"))
        if held:
            found.edges.append(("MEROPS", code, "MEROPS", family, "family_member"))
    return found


def merops_family_text(family: str, clan: str, example: str, kind: str) -> str:
    """A MEROPS family as words: "MEROPS peptidase family S14 (clan SK), whose type example is ClpP endopeptidase"."""
    of_clan = f" (clan {clan})" if clan else ""
    example = f", whose type example is {example}" if example else ""
    return f"MEROPS {kind} family {family}{of_clan}{example}"


@dataclass(slots=True)
class KeywordOntology:
    ontology: Ontology
    # Keyword accession to its category, such as "Ligand", and to the GO terms keywlist maps it to.
    categories: dict[str, str]
    go_links: dict[str, frozenset[str]]
    by_name: dict[str, str]


def keyword_ontology(keywlist: Path) -> KeywordOntology:
    """UniProt keywords, each joined to the keyword above it on every `HI` path, with its category and its GO mapping."""
    with keywlist.open(encoding="utf-8") as handle:
        records = [record for record in iter_records(handle) if record.record_type == "keyword"]
    by_name = {normalize_name(record.label): record.stable_id for record in records}
    found = Ontology()
    edges: set[Edge] = set()
    for record in records:
        found.concepts.append(("UniProtKB-KW", record.stable_id, record.label, record.definition, record.category or ""))
        for link in record.hierarchy:
            if len(link.path) < 2:
                continue
            above = link.path[-2].split(":", 1)[-1] if ":" in link.path[-2] else link.path[-2]
            parent = by_name.get(normalize_name(above))
            if parent and parent != record.stable_id:
                edges.add(("UniProtKB-KW", record.stable_id, "UniProtKB-KW", parent, "is_a"))
    found.edges.extend(sorted(edges))
    return KeywordOntology(
        found, {record.stable_id: record.category or "" for record in records},
        {record.stable_id: frozenset(link.identifier for link in record.go_links) for record in records}, by_name,
    )


def location_ontology(subcell: Path) -> tuple[Ontology, dict[str, frozenset[str]]]:
    """Subcellular locations, topologies and orientations with their `is_a` and `part_of` parents, and the keywords each implies."""
    with subcell.open(encoding="utf-8") as handle:
        records = list(iter_records(handle))
    by_kind_name = {(record.record_type, normalize_name(record.label)): record.stable_id for record in records}
    found = Ontology()
    implied: dict[str, frozenset[str]] = {}
    for record in records:
        found.concepts.append((record.source_database, record.stable_id, record.label, record.definition, record.record_type))
        for link in record.hierarchy:
            parent = by_kind_name.get((record.record_type, normalize_name(link.path[-1])))
            if parent and parent != record.stable_id:
                found.edges.append((record.source_database, record.stable_id, record.source_database, parent, link.relation))
        implied[record.stable_id] = frozenset(link.identifier for link in record.keyword_links if link.identifier)
    return found, implied


def ptm_ontology(ptmlist: Path, psi_mod: Path) -> tuple[Ontology, dict[str, frozenset[str]]]:
    """The modifications of `ptmlist.txt`, each mapped to its PSI-MOD term and defined by it (by the first that has a definition,
    where ptmlist names several), PSI-MOD's own `is_a` tree, and the keyword names each modification implies (ptmlist names
    keywords by name, not accession)."""
    with ptmlist.open(encoding="utf-8") as handle:
        records: list[UniProtVocabularyRecord] = [record for record in iter_records(handle) if record.record_type == "ptm"]
    with open_text_maybe_gzip(psi_mod, encoding="utf-8") as handle:
        terms = [term for term in iter_terms(handle) if not term.is_obsolete]
    defined = {term.id: term.definition or "" for term in terms}
    found = Ontology()
    implied: dict[str, frozenset[str]] = {}
    for record in records:
        mapped = [reference.identifier for reference in record.cross_references if reference.database == "PSI-MOD"]
        definition = next((defined[identifier] for identifier in mapped if defined.get(identifier)), "")
        found.concepts.append(("UniProtKB-PTM", record.stable_id, record.label, definition, record.feature_key or ""))
        found.edges.extend(("UniProtKB-PTM", record.stable_id, "PSI-MOD", identifier, "maps_to") for identifier in mapped)
        implied[record.stable_id] = frozenset(link.description or "" for link in record.keyword_links if link.description)
    for term in terms:
        found.concepts.append(("PSI-MOD", term.id, term.name or term.id, term.definition or "", "modification"))
        found.edges.extend(("PSI-MOD", term.id, "PSI-MOD", parent, "is_a") for parent in term.parents)
    return found, implied


def reactome_ontology(relations: Path, pathways: Path) -> Ontology:
    """Reactome pathways with their names and species, each joined to the pathway that contains it."""
    found = Ontology()
    with open_text_maybe_gzip(pathways, encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) == 3:
                found.concepts.append(("Reactome", fields[0], fields[1], "", fields[2]))
    with open_text_maybe_gzip(relations, encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) == 2:
                found.edges.append(("Reactome", fields[1], "Reactome", fields[0], "part_of"))
    return found


def chebi_ontology(path: Path, wanted: Collection[str]) -> Ontology:
    """The wanted ChEBI entities (cofactors and binding ligands) and every ancestor by `is_a`, with names and definitions, walked
    from the wanted entities in sorted order, so the order of a set of them never reaches the tables."""
    with open_text_maybe_gzip(path, encoding="utf-8") as handle:
        terms = {term.id: term for term in iter_terms(handle) if not term.is_obsolete}
    found = Ontology()
    seen: set[str] = set()
    pending = sorted(identifier for identifier in wanted if identifier in terms)
    while pending:
        identifier = pending.pop()
        if identifier in seen:
            continue
        seen.add(identifier)
        term = terms[identifier]
        found.concepts.append(("ChEBI", identifier, term.name or identifier, term.definition or "", "chemical entity"))
        for parent in term.parents:
            if parent in terms:
                found.edges.append(("ChEBI", identifier, "ChEBI", parent, "is_a"))
                pending.append(parent)
    return found


def path_ontology(database: str, accessions: Iterable[str], relation: str) -> Ontology:
    """Concepts named by their path, "A; B; C", each joined to its prefix one level up: UniProt's pathways and families, read in
    sorted order, so the order of a set of paths never reaches the tables."""
    found = Ontology()
    seen: set[str] = set()
    for accession in sorted(accessions):
        parts = accession.split("; ")
        for depth in range(len(parts), 0, -1):
            name = "; ".join(parts[:depth])
            if name in seen:
                break
            seen.add(name)
            found.concepts.append((database, name, parts[depth - 1], "", f"level_{depth}"))
            if depth > 1:
                found.edges.append((database, name, database, "; ".join(parts[:depth - 1]), relation))
    return found


def edge_rows(edges: Iterable[Edge]) -> Iterator[dict[str, str]]:
    for child_database, child, parent_database, parent, relation in dict.fromkeys(edges):
        yield {"child_database": child_database, "child": child, "parent_database": parent_database, "parent": parent, "relation": relation}


def concept_rows(concepts: Iterable[Concept]) -> Iterator[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    for database, accession, name, definition, kind in concepts:
        if (database, accession) not in seen:
            seen.add((database, accession))
            yield {"source_database": database, "accession": accession, "name": name, "definition": definition, "kind": kind}


def ancestors(edges: Iterable[Edge], relations: Collection[str] = ("is_a", "part_of")) -> Mapping[tuple[str, str], frozenset[tuple[str, str]]]:
    """Each concept's ancestors along `relations`, itself excluded, as (database, accession) pairs."""
    up: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for child_database, child, parent_database, parent, relation in edges:
        if relation in relations:
            up.setdefault((child_database, child), set()).add((parent_database, parent))
    closed: dict[tuple[str, str], frozenset[tuple[str, str]]] = {}

    def closure(node: tuple[str, str]) -> frozenset[tuple[str, str]]:
        if node in closed:
            return closed[node]
        found: set[tuple[str, str]] = set()
        pending = list(up.get(node, ()))
        while pending:
            parent = pending.pop()
            if parent not in found:
                found.add(parent)
                pending.extend(up.get(parent, ()))
        closed[node] = frozenset(found)
        return closed[node]

    return {node: closure(node) for node in up}


def below(up: Mapping[tuple[str, str], Collection[tuple[str, str]]], root: tuple[str, str]) -> frozenset[str]:
    """The accession of `root` and of every concept of its database with `root` among its ancestors in `up` (`ancestors`)."""
    return frozenset({root[1]} | {accession for (database, accession), found in up.items() if database == root[0] and root in found})
