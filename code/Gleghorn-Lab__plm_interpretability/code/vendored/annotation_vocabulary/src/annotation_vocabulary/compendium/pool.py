"""Join what the readers kept into the pool: one row per distinct sequence, and every assertion keyed by its protein.

A sequence is in the pool when one of its entries is whole (no fragment), at most 2,046 residues of ordinary amino acids, and of
a subset Logan admitted (2026-10-20): Swiss-Prot, or TrEMBL with an experimental GOA assertion, annotation score 5 or 4, or
protein existence 1. Entries with one sequence are one row, with every accession, because a split keeps a sequence in one place.

An assertion then takes its protein, its current GO term (an alternate identifier follows its term, an obsolete one its only
replacement, anything else is dropped, counted), its tier and its fundamental aspect. Each entry's lineage joins them as the
taxonomy aspect, one taxon per named rank. A Swiss-Prot keyword takes the best tier of
the assertions that imply it on the same protein: the GO terms keywlist maps it to (or a term below them), the location or
modification that names it, or the feature it stands for (for Metal-binding, a binding site of a ChEBI metal ion; for Ubl
conjugation, a cross-link to ubiquitin or a ubiquitin-like protein); failing those, its own code's tier, and curated when it has
none. A TrEMBL keyword is a guard.
"""

from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc

from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from foundry.protein.experimental_evidence import UnknownEvidenceCode
from foundry.protein.sequence import ProteinTextError, normalize_protein_ascii
from .tables import ASSERTION_SCHEMA, POOLED_ASSERTION_SCHEMA
from .tiers import LABEL_TIERS, SOURCE_ORGANISM, TIER_RANK, TIERS, assertion_tier, fundamental_aspect
from .uniprot import UBIQUITIN_LIKE
from ..experimental.pool import MAX_RESIDUES, protein_id
from ..schema import canonical_term_id
from ..sources.obo import OBOIndex


REFERENCE_PROTEOME = "KW-1185"
SUBSETS = ("swissprot", "trembl_goa_experimental", "trembl_score_5", "trembl_score_4", "trembl_pe1")
# The keyword a feature stands for, by name as keywlist writes it.
FEATURE_KEYWORDS = {
    "local_transmembrane": "Transmembrane", "local_signal_peptide": "Signal", "local_disulfide": "Disulfide bond",
    "local_glycosylation": "Glycoprotein", "local_transit_peptide": "Transit peptide", "local_zinc_finger": "Zinc-finger",
    "local_repeat": "Repeat", "local_coiled_coil": "Coiled coil", "local_lipidation": "Lipoprotein", "metal_binding": "Metal-binding",
    "ubl_conjugation": "Ubl conjugation",
}
LOCATION_ASPECTS = ("subcellular_location", "membrane_topology", "membrane_orientation")


@dataclass(slots=True)
class PoolAudit:
    """What the pool kept and set aside, each count by its reason."""

    entries: Counter[str] = field(default_factory=Counter)
    proteins: Counter[str] = field(default_factory=Counter)
    assertions: Counter[str] = field(default_factory=Counter)

    def to_dict(self) -> dict[str, object]:
        return {name: dict(sorted(getattr(self, name).items())) for name in ("entries", "proteins", "assertions")}


def admission(entry: Mapping[str, object], scores: Mapping[str, int], goa_admitted: Collection[str]) -> list[str]:
    """The subsets that admit an entry, in `SUBSETS` order; none for a TrEMBL entry of no admitted subset."""
    if entry["dataset"] == "Swiss-Prot":
        return ["swissprot"]
    accession = str(entry["accession"])
    score = scores.get(accession)
    found = [
        name for name, admitted in (
            ("trembl_goa_experimental", accession in goa_admitted), ("trembl_score_5", score == 5), ("trembl_score_4", score == 4),
            ("trembl_pe1", entry["protein_existence"] == 1),
        ) if admitted
    ]
    return found


def entry_exclusion(entry: Mapping[str, object], max_residues: int = MAX_RESIDUES) -> str | None:
    """Why an entry's sequence cannot be a row, or None when it can."""
    if entry["fragment"]:
        return "fragment"
    sequence = str(entry["sequence"])
    if len(sequence) > max_residues:
        return "over_length_limit"
    try:
        normalize_protein_ascii(sequence)
    except ProteinTextError:
        return "invalid_residues"
    return None


def pool_proteins(
    entries: Iterable[Mapping[str, object]], *, scores: Mapping[str, int], goa_admitted: Collection[str],
    lineage: Mapping[int, Mapping[str, str]], reference_proteome: Collection[str], audit: PoolAudit,
    max_residues: int = MAX_RESIDUES,
) -> tuple[list[dict[str, object]], dict[str, str]]:
    """The pool's protein rows (`tables.PROTEIN_SCHEMA`) in protein-id order, and each pooled accession's protein id.

    `lineage` maps a taxon to its ancestors' names by named rank; `reference_proteome` holds the accessions whose entry carries
    the Reference proteome keyword. An accession read twice (Swiss-Prot and a fetch) keeps its first entry.
    """
    by_sequence: dict[str, list[tuple[Mapping[str, object], list[str]]]] = {}
    seen: set[str] = set()
    for entry in entries:
        accession = str(entry["accession"])
        if accession in seen:
            audit.entries["read_twice"] += 1
            continue
        seen.add(accession)
        reason = entry_exclusion(entry, max_residues)
        subsets = admission(entry, scores, goa_admitted)
        if reason is None and not subsets:
            reason = "no_admitted_subset"
        audit.entries[reason or "kept"] += 1
        if reason is None:
            by_sequence.setdefault(str(entry["sequence"]), []).append((entry, subsets))
    proteins: list[dict[str, object]] = []
    accession_to_protein: dict[str, str] = {}
    for sequence, members in by_sequence.items():
        # Swiss-Prot first, then by accession, so the primary accession is the reviewed one when there is one.
        members.sort(key=lambda item: (item[0]["dataset"] != "Swiss-Prot", str(item[0]["accession"])))
        primary = members[0][0]
        identifier = protein_id(sequence)
        accessions = [str(entry["accession"]) for entry, _ in members]
        for accession in accessions:
            accession_to_protein[accession] = identifier
        taxon = primary["taxon_id"]
        ranks = lineage.get(int(taxon), {}) if taxon is not None else {}
        subsets = {name for _, found in members for name in found}
        scored = [scores[accession] for accession in accessions if accession in scores]
        proteins.append({
            "protein_id": identifier, "sequence": sequence, "length": len(sequence), "accessions": accessions,
            "primary_accession": accessions[0], "reviewed": primary["dataset"] == "Swiss-Prot",
            "admitted_by": [name for name in SUBSETS if name in subsets],
            "protein_existence": min(int(entry["protein_existence"]) for entry, _ in members),
            "annotation_score": max(scored) if scored else None,
            "taxon_id": taxon, "taxa": sorted({int(entry["taxon_id"]) for entry, _ in members if entry["taxon_id"] is not None}),
            "organism": primary["organism"], **{rank: ranks.get(rank) for rank in ("domain", "kingdom", "phylum", "class", "order", "family", "genus", "species")},
            "proteomes": sorted({proteome for entry, _ in members for proteome in entry["proteomes"]}),
            "reference_proteome": any(accession in reference_proteome for accession in accessions),
            "structures": max(int(entry["structures"]) for entry, _ in members),
            "references": max(int(entry["references"]) for entry, _ in members),
            "created": min(str(entry["created"]) for entry, _ in members), "modified": max(str(entry["modified"]) for entry, _ in members),
            "protein_name": primary["protein_name"],
        })
        audit.proteins["merged_accessions"] += len(accessions) - 1
    proteins.sort(key=lambda row: str(row["protein_id"]))
    audit.proteins["proteins"] = len(proteins)
    for name in SUBSETS:
        audit.proteins[f"admitted_by:{name}"] = sum(name in row["admitted_by"] for row in proteins)
    return proteins, accession_to_protein


def taxonomy_assertions(entries: pa.Table, ranked: Mapping[int, Mapping[str, int]], lineage: Mapping[int, Mapping[str, str]]) -> pa.Table:
    """Each entry's lineage as assertion rows (`tables.ASSERTION_SCHEMA`): the taxon at every named rank its organism has, the rank
    its relation. `entries` holds `accession` and `taxon_id`; `ranked` maps a taxon to its ancestor at each rank and `lineage` to
    their names. A taxon the dump does not hold gives no row."""
    chains: dict[str, list[object]] = {"taxon_id": [], "term": [], "label": [], "relation": []}
    for taxon, chain in ranked.items():
        for rank, ancestor in chain.items():
            chains["taxon_id"].append(taxon)
            chains["term"].append(str(ancestor))
            chains["label"].append(lineage.get(taxon, {}).get(rank, str(ancestor)))
            chains["relation"].append(rank)
    table = pa.table(chains, schema=pa.schema([("taxon_id", pa.int64()), ("term", pa.string()), ("label", pa.string()), ("relation", pa.string())]))
    joined = entries.select(["accession", "taxon_id"]).join(table, keys="taxon_id", join_type="inner", use_threads=True)

    def constant(value: object, kind: pa.DataType | None = None) -> pa.Array:
        # A string column unless `kind` names another type.
        return pa.repeat(pa.scalar(value, kind if kind is not None else pa.string()), joined.num_rows)

    return pa.table({
        "accession": joined["accession"], "aspect": constant("taxonomy"), "source_database": constant("NCBITaxon"), "term": joined["term"],
        "label": joined["label"], "negated": constant(False, pa.bool_()), "code": constant(""), "source": constant(SOURCE_ORGANISM),
        "assigned_by": constant(""), "reference": constant(""), "relation": joined["relation"], "start": constant(None, pa.int32()),
        "end": constant(None, pa.int32()), "note": constant(""),
    }, schema=ASSERTION_SCHEMA)


def mapped(table: pa.Table, keys: Sequence[str], compute: Callable[..., object], name: str, kind: pa.DataType) -> pa.Table:
    """`table` with a column `name` computed once for each distinct combination of `keys`, joined back."""
    distinct = table.select(list(keys)).group_by(list(keys)).aggregate([])
    values = [compute(*row) for row in zip(*(distinct[key].to_pylist() for key in keys), strict=True)]
    lookup = distinct.append_column(name, pa.array(values, kind))
    return table.join(lookup, keys=list(keys), join_type="left outer", use_threads=True)


@dataclass(frozen=True, slots=True)
class PoolContext:
    """What tiering and grouping the assertions needs: GO, the catalytic GO terms, keyword categories, what implies a keyword, and
    the ChEBI metal ions (`tiers.METAL_CATION` and every entity below it)."""

    go: OBOIndex
    catalytic: frozenset[str]
    keyword_categories: Mapping[str, str]
    # (database, accession) of a GO term, location, modification or ("aspect", a feature aspect) to the keywords it implies.
    implies: Mapping[tuple[str, str], frozenset[str]]
    metal_ions: frozenset[str]


def resolve_go(go: OBOIndex, aspect: str, term: str) -> str | None:
    """The current GO term an asserted identifier names in its aspect, or None (obsolete without one replacement, another aspect)."""
    found = go.lookup(term)
    if found is None:
        targets = go.replacements(term)
        found = go.lookup(targets[0]) if len(targets) == 1 else None
    if found is None:
        return None
    namespaces = {"go_bp": "biological_process", "go_mf": "molecular_function", "go_cc": "cellular_component"}
    return found.id if namespaces.get(aspect) == found.namespace else None


def pool_assertions(table: pa.Table, accessions: pa.Table, context: PoolContext, audit: PoolAudit, source: str) -> pa.Table:
    """One reader's assertion rows, keyed by protein, GO terms resolved, with tier, term id and fundamental aspect.

    `accessions` holds each pooled accession with its protein id and whether its entry is reviewed. Rows of an accession outside
    the pool, of an unresolvable GO term, or of a term no fundamental aspect holds are dropped and counted. The result keeps a
    `reviewed` column for keyword inheritance, which `inherit_keyword_tiers` drops.
    """
    audit.assertions[f"{source}:read"] += table.num_rows
    joined = table.join(accessions, keys="accession", join_type="inner", use_threads=True)
    audit.assertions[f"{source}:accession_not_in_pool"] += table.num_rows - joined.num_rows
    is_go = pc.equal(joined["source_database"], "GO")
    if pc.any(is_go).as_py():
        joined = mapped(joined, ["aspect", "term", "source_database"],
                        lambda aspect, term, database: resolve_go(context.go, aspect, term) if database == "GO" else term,
                        "resolved", pa.string())
        unresolved = pc.is_null(joined["resolved"])
        audit.assertions[f"{source}:go_unresolved_or_other_aspect"] += pc.sum(pc.cast(unresolved, pa.int64())).as_py() or 0
        joined = joined.filter(pc.invert(unresolved))
        joined = joined.set_column(joined.schema.get_field_index("term"), "term", joined["resolved"]).drop_columns(["resolved"])
    unknown: set[str] = set()

    def tier(source_name: str, code: str, reviewed: bool) -> str | None:
        try:
            return assertion_tier(source_name, code, reviewed)
        except UnknownEvidenceCode:
            unknown.add(code)
            return None

    joined = mapped(joined, ["source", "code", "reviewed"], tier, "tier", pa.string())
    if unknown:
        raise UnknownEvidenceCode(f"{source}: evidence codes with no tier, add each to foundry.protein.experimental_evidence: {sorted(unknown)}")
    joined = mapped(joined, ["aspect", "source_database", "term"], canonical_term_id, "term_id", pa.string())
    joined = mapped(
        joined, ["aspect", "term"],
        lambda aspect, term: fundamental_aspect(
            aspect, term, catalytic=context.catalytic, keyword_categories=context.keyword_categories, metal_ions=context.metal_ions,
        ),
        "fundamental_aspect", pa.string(),
    )
    homeless = pc.is_null(joined["fundamental_aspect"])
    for aspect, count in Counter(joined.filter(homeless)["aspect"].to_pylist()).items():
        audit.assertions[f"{source}:no_fundamental_aspect:{aspect}"] += count
    joined = joined.filter(pc.invert(homeless))
    audit.assertions[f"{source}:kept"] += joined.num_rows
    return joined.select([*POOLED_ASSERTION_SCHEMA.names, "reviewed"])


def linked_assertions(table: pa.Table, metal_ions: Collection[str]) -> pa.Table:
    """(protein_id, link_database, link_term, tier) for every positive label-tier assertion that can imply a keyword; a binding
    site of one of `metal_ions` links as the feature `metal_binding`, and a cross-link to ubiquitin or a ubiquitin-like protein
    (`uniprot.UBIQUITIN_LIKE`) as `ubl_conjugation`."""
    usable = table.filter(pc.and_(pc.invert(table["negated"]), pc.is_in(table["tier"], pa.array(LABEL_TIERS))))
    parts = []
    go = usable.filter(pc.equal(usable["source_database"], "GO"))
    parts.append(pa.table({"protein_id": go["protein_id"], "link_database": go["source_database"], "link_term": go["term"], "tier": go["tier"]}))
    named = usable.filter(pc.is_in(usable["aspect"], pa.array([*LOCATION_ASPECTS, "ptm"])))
    parts.append(pa.table({"protein_id": named["protein_id"], "link_database": named["source_database"], "link_term": named["term"], "tier": named["tier"]}))
    features = usable.filter(pc.is_in(usable["aspect"], pa.array([aspect for aspect in FEATURE_KEYWORDS if aspect.startswith("local_")])))
    parts.append(pa.table({
        "protein_id": features["protein_id"], "link_database": pa.array(["aspect"] * features.num_rows, pa.string()),
        "link_term": features["aspect"], "tier": features["tier"],
    }))
    binding = usable.filter(pc.equal(usable["aspect"], "local_binding"))
    metal = binding.filter(pc.is_in(binding["term"], pa.array(sorted(metal_ions), pa.string())))
    parts.append(pa.table({
        "protein_id": metal["protein_id"], "link_database": pa.array(["aspect"] * metal.num_rows, pa.string()),
        "link_term": pa.array(["metal_binding"] * metal.num_rows, pa.string()), "tier": metal["tier"],
    }))
    crosslinks = usable.filter(pc.equal(usable["aspect"], "local_crosslink"))
    partners = sorted(term for term in pc.unique(crosslinks["term"]).to_pylist() if UBIQUITIN_LIKE.search(term))
    conjugated = crosslinks.filter(pc.is_in(crosslinks["term"], pa.array(partners, pa.string())))
    parts.append(pa.table({
        "protein_id": conjugated["protein_id"], "link_database": pa.array(["aspect"] * conjugated.num_rows, pa.string()),
        "link_term": pa.array(["ubl_conjugation"] * conjugated.num_rows, pa.string()), "tier": conjugated["tier"],
    }))
    return pa.concat_tables(parts)


def inherit_keyword_tiers(table: pa.Table, context: PoolContext, audit: PoolAudit) -> pa.Table:
    """Every pooled assertion, a reviewed keyword's tier replaced by the best tier among what implies it on the same protein."""
    implied = [(database, term, keyword) for (database, term), keywords in context.implies.items() for keyword in sorted(keywords)]
    implies = pa.table({
        "link_database": [row[0] for row in implied], "link_term": [row[1] for row in implied], "keyword": [row[2] for row in implied],
    }, schema=pa.schema([("link_database", pa.string()), ("link_term", pa.string()), ("keyword", pa.string())]))
    links = linked_assertions(table, context.metal_ions).join(implies, keys=["link_database", "link_term"], join_type="inner", use_threads=True)
    ranks = pc.index_in(links["tier"], value_set=pa.array(TIERS))
    inherited = (
        pa.table({"protein_id": links["protein_id"], "term": links["keyword"], "rank": ranks})
        .group_by(["protein_id", "term"]).aggregate([("rank", "min")])
        .rename_columns({"rank_min": "inherited_rank"})
    )
    is_keyword = pc.equal(table["aspect"], "keyword")
    keywords = table.filter(is_keyword).join(inherited, keys=["protein_id", "term"], join_type="left outer", use_threads=True)
    tiers = []
    for own, code, reviewed, rank in zip(*(keywords[name].to_pylist() for name in ("tier", "code", "reviewed", "inherited_rank")), strict=True):
        if not reviewed:
            tiers.append("guard")
        elif rank is None:
            tiers.append(own if code else "curated")
        else:
            tiers.append(TIERS[min(rank, TIER_RANK[own])] if code else TIERS[rank])
    audit.assertions["keyword:inherited"] += sum(rank is not None for rank in keywords["inherited_rank"].to_pylist())
    keywords = keywords.set_column(keywords.schema.get_field_index("tier"), "tier", pa.array(tiers, pa.string())).drop_columns(["inherited_rank"])
    rest = table.filter(pc.invert(is_keyword))
    return pa.concat_tables([rest.select(POOLED_ASSERTION_SCHEMA.names), keywords.select(POOLED_ASSERTION_SCHEMA.names)]).cast(POOLED_ASSERTION_SCHEMA)
