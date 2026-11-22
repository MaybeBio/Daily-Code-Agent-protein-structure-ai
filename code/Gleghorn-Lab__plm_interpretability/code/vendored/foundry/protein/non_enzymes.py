"""The confident non-enzyme: the facts of a reviewed Swiss-Prot entry that decide it, and the rules that read them.

An enzyme class needs a negative class beside it, and a sampled negative is a label made by a process that leaves a fingerprint
([dataset biases](../../docs/conventions/dataset_biases.md), section 3). `entry_facts` reads what a curator states about one
reviewed entry, once, so that the definition, the matching of the class to the enzymes and a second reader that checks both work
from the entry's own record and none of them parses the XML again.

A protein is a confident non-enzyme when a curator of the reviewed entry describes a function from a cited experiment and the
entry carries no sign of catalysis anywhere: no EC number, no catalytic activity, cofactor or enzyme regulation comment, no active
site, no GO catalytic activity term at any evidence code, no keyword and no domain that nearly only enzymes carry. The rules are
`rule_failures`, each named, and the decision record `2026-10-01_ec_non_enzyme_class.md` holds the reason for each. UniProt
records no protein as tested and found to lack an activity, so the class is made by construction from what the entry does not
say, and a release says so.

Promoted on 2026-10-21 from production_suite's `uniprot_non_enzymes` and `non_enzyme_selection`, which `ec_experimental_v2` and
`v3` build with, when the annotation compendium's EC view became the second consumer.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import pyarrow as pa

from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from .uniprot_xml import ExtractionError, entry_accession, evidence_records, iter_entries, organism_record


EXPERIMENTAL = "ECO:0000269"
EXISTENCE = {
    "evidence at protein level": 1, "evidence at transcript level": 2, "inferred from homology": 3, "predicted": 4, "uncertain": 5,
}
# The comment types whose presence says a curator described catalysis, or what a catalyst needs or is regulated by.
CATALYTIC_COMMENTS = ("catalytic activity", "cofactor", "enzyme regulation", "pathway", "biophysicochemical properties")


class EntryFacts(TypedDict):
    """One reviewed entry's own statements, as `entry_facts` reads them. Lists are sorted and without repeats."""

    accession: str
    name: str
    full_name: str
    existence: int
    length: int
    fragment: str
    taxon_id: str
    organism: str
    lineage: list[str]
    ec: list[str]
    catalytic_comments: int
    cofactor_comments: int
    regulation_comments: int
    active_sites: int
    keywords: list[str]
    go_function: list[str]
    function_citations: list[str]
    families: list[str]
    pfam: list[str]
    interpro: list[str]


ARROW_SCHEMA = pa.schema([
    ("accession", pa.string()), ("name", pa.string()), ("full_name", pa.string()), ("existence", pa.int8()), ("length", pa.int32()),
    ("fragment", pa.string()), ("taxon_id", pa.string()), ("organism", pa.string()), ("lineage", pa.list_(pa.string())),
    ("ec", pa.list_(pa.string())), ("catalytic_comments", pa.int16()), ("cofactor_comments", pa.int16()),
    ("regulation_comments", pa.int16()), ("active_sites", pa.int16()), ("keywords", pa.list_(pa.string())),
    ("go_function", pa.list_(pa.string())), ("function_citations", pa.list_(pa.string())), ("families", pa.list_(pa.string())),
    ("pfam", pa.list_(pa.string())), ("interpro", pa.list_(pa.string())),
])


@dataclass(frozen=True, slots=True)
class Definition:
    """Every number of the definition and the matching, fixed before a release is scored; the decision record gives the reasons."""

    existence: int = 1
    max_length: int = 2046
    # A keyword is catalytic when this share of the reviewed entries that carry it, at least `keyword_min_entries` of them, name an EC number.
    keyword_ec_rate: float = 0.9
    keyword_min_entries: int = 30
    # A domain (Pfam) is enzyme-like when this share of the reviewed entries that carry it name an EC number, with at least this many that do.
    domain_ec_rate: float = 0.1
    domain_min_ec_entries: int = 5
    catalytic_root: str = "GO:0003824"
    # The class share of the matched release is non_enzyme_weight over the sum of both weights: 2 of 5 is 40 percent.
    enzyme_weight: int = 3
    non_enzyme_weight: int = 2
    length_bins: int = 10
    backoff_levels: int = 8
    seed: int = 7

    def share(self) -> float:
        return self.non_enzyme_weight / (self.enzyme_weight + self.non_enzyme_weight)


@dataclass(frozen=True, slots=True)
class Context:
    """The sets the rules read, derived from the whole table of entries and pinned in the selection record."""

    catalytic_keywords: frozenset[str]
    enzyme_domains: frozenset[str]
    catalytic_go_terms: frozenset[str]


def _text_of(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def entry_facts(entry: ET.Element, namespace: str) -> EntryFacts:
    """The facts of one reviewed entry: its existence level, organism, every EC number it names, and its catalytic annotations.

    An EC number counts wherever the entry states it: in any protein name, including a component or domain, and in the reaction of a
    catalytic activity comment. A GO molecular function is kept as `GO:id|ECO:code` for every evidence code, since a non-enzyme
    is decided by the absence of a catalytic term at any evidence level. Its characterization is the PubMed citations of the
    function comments whose evidence is an experiment (`function_citations`), which is empty when no cited experiment supports a function.
    """
    accession = entry_accession(entry, namespace, ("Swiss-Prot",))
    sequence = entry.find(namespace + "sequence")
    if sequence is None:
        raise ExtractionError(f"{accession}: an entry holds one canonical sequence")
    protein = entry.find(namespace + "protein")
    ec: set[str] = set()
    if protein is not None:
        ec.update(_text_of(item) for item in protein.iter(namespace + "ecNumber"))
    counts = dict.fromkeys(CATALYTIC_COMMENTS, 0)
    families: set[str] = set()
    keys_of_function: list[list[str]] = []
    for comment in entry.findall(namespace + "comment"):
        kind = comment.get("type", "")
        if kind in counts:
            counts[kind] += 1
        if kind == "catalytic activity":
            ec.update(item.get("id", "") for item in comment.iter(namespace + "dbReference") if item.get("type") == "EC")
        elif kind == "similarity":
            families.update(" ".join(_text_of(item).split()) for item in comment.findall(namespace + "text"))
        elif kind == "function":
            keys_of_function.extend((item.get("evidence") or "").split() for item in comment.findall(namespace + "text"))
    evidence = evidence_records(entry, namespace)
    citations = sorted({
        identifier for keys in keys_of_function for key in keys
        if key in evidence and evidence[key]["type"] == EXPERIMENTAL for identifier in evidence[key]["citations"]
    })
    functions: set[str] = set()
    pfam: set[str] = set()
    interpro: set[str] = set()
    for reference in entry.findall(namespace + "dbReference"):
        database, identifier = reference.get("type"), reference.get("id", "")
        if database == "GO":
            properties = {item.get("type"): item.get("value", "") for item in reference.findall(namespace + "property")}
            if properties.get("term", "").startswith("F:"):
                functions.add(f"{identifier}|{properties.get('evidence', '')}")
        elif database == "Pfam":
            pfam.add(identifier)
        elif database == "InterPro":
            interpro.add(identifier)
    organism = organism_record(entry, namespace)
    existence = entry.find(namespace + "proteinExistence")
    names = entry.find(namespace + "protein")
    recommended = names.find(namespace + "recommendedName/" + namespace + "fullName") if names is not None else None
    return {
        "accession": accession, "name": entry.findtext(namespace + "name") or "", "full_name": _text_of(recommended),
        "existence": EXISTENCE[existence.get("type", "")] if existence is not None else 0,
        "length": int(sequence.get("length", "0")), "fragment": sequence.get("fragment") or "",
        "taxon_id": organism["taxon_id"] or "", "organism": organism["name"] or "", "lineage": organism["lineage"],
        "ec": sorted(ec - {""}), "catalytic_comments": counts["catalytic activity"], "cofactor_comments": counts["cofactor"],
        "regulation_comments": counts["enzyme regulation"],
        "active_sites": sum(item.get("type") == "active site" for item in entry.findall(namespace + "feature")),
        "keywords": sorted(item.get("id", "") for item in entry.findall(namespace + "keyword")),
        "go_function": sorted(functions), "function_citations": citations,
        "families": sorted(families - {""}), "pfam": sorted(pfam), "interpro": sorted(interpro),
    }


def read_entry_facts(xml: Path, *, expected_entries: int | None = None, progress: bool = False) -> Iterator[EntryFacts]:
    """Yield the facts of each entry of a Swiss-Prot XML, in document order, freeing each entry as it goes."""
    for entry, namespace in iter_entries(xml, expected_entries=expected_entries, progress=progress):
        yield entry_facts(entry, namespace)


def high_ec_terms(entries: Iterable[tuple[bool, Sequence[str]]], rate: float, minimum: int, *, count_ec: bool) -> frozenset[str]:
    """The terms that nearly only entries with an EC number carry.

    `entries` are (names an EC number, the terms the entry carries). With `count_ec` the minimum counts the entries that name
    an EC number, as the domain rule asks; otherwise it counts every entry that carries the term, as the keyword rule asks.
    """
    carried: Counter[str] = Counter()
    named: Counter[str] = Counter()
    for has_ec, terms in entries:
        for term in set(terms):
            carried[term] += 1
            named[term] += has_ec
    return frozenset(
        term for term, total in carried.items()
        if (named[term] if count_ec else total) >= minimum and named[term] / total >= rate
    )


def context_of(facts: Sequence[EntryFacts], definition: Definition, go_terms: frozenset[str]) -> Context:
    """The keywords and domains the entries show to be enzyme-like, and the catalytic GO terms."""
    keywords = high_ec_terms(((bool(row["ec"]), row["keywords"]) for row in facts), definition.keyword_ec_rate, definition.keyword_min_entries, count_ec=False)
    domains = high_ec_terms(((bool(row["ec"]), row["pfam"]) for row in facts), definition.domain_ec_rate, definition.domain_min_ec_entries, count_ec=True)
    return Context(keywords, domains, go_terms)


def rule_failures(facts: EntryFacts, definition: Definition, context: Context) -> tuple[str, ...]:
    """Every rule of the definition the entry breaks, in a fixed order; empty when it is a confident non-enzyme."""
    failures = []
    if facts["existence"] != definition.existence:
        failures.append("not_protein_level_evidence")
    if facts["fragment"]:
        failures.append("fragment")
    if facts["length"] > definition.max_length:
        failures.append("longer_than_the_suite_embeds")
    if facts["ec"]:
        failures.append("names_an_ec_number")
    if facts["catalytic_comments"]:
        failures.append("catalytic_activity_comment")
    if facts["cofactor_comments"]:
        failures.append("cofactor_comment")
    if facts["regulation_comments"]:
        failures.append("enzyme_regulation_comment")
    if facts["active_sites"]:
        failures.append("active_site_feature")
    if any(keyword in context.catalytic_keywords for keyword in facts["keywords"]):
        failures.append("catalytic_keyword")
    if any(domain in context.enzyme_domains for domain in facts["pfam"]):
        failures.append("enzyme_like_domain")
    if any(term.split("|")[0] in context.catalytic_go_terms for term in facts["go_function"]):
        failures.append("catalytic_go_term")
    if not facts["function_citations"]:
        failures.append("function_not_from_a_cited_experiment")
    return tuple(failures)
