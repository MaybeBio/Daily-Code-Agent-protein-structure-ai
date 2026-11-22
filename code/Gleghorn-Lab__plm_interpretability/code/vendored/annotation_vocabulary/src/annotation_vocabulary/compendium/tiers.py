"""The tier of an assertion and the fundamental aspect of a term.

Tiers (Logan, 2026-10-20; `foundry.protein.evidence_tier` maps every code):
- experimental: the ECO:0000269 family, ECO:0007744, the eleven experimental GO codes, and primary measurements;
- signature: an InterPro or Pfam match, whose code is `match:<member database>`;
- curated: ECO:0000250, 0000255, 0000305 and GO ISS, ISO, ISA, ISM, IC, TAS;
- guard: everything else that asserts (rules, imports, electronic and phylogenetic inference), stored and never a label or a
  negative, and every TrEMBL statement without an evidence code;
- skip: a code that asserts nothing (GO ND, ECO:0000307).
A Swiss-Prot statement without an evidence code is curated; a keyword's tier is set again by inheritance (`pool.py`). The
organism a sequence was read from is observed, in Swiss-Prot and TrEMBL alike, so its lineage is experimental; since every protein
has one, the organism aspect makes no protein eligible for a held-out split and balances none (`UNIVERSAL_ASPECTS`). The organism's
traits that Madin et al. compile from culture collections and the literature (`traits.py`) are observed too, and inherited like
the lineage, in the same aspect.

The eight fundamental aspects group the aspects as Logan listed them, GO MF split at catalytic activity (GO:0003824).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from foundry.protein.experimental_evidence import evidence_tier
from ..grammar import COMPENDIUM_TRAIT_ASPECT_ORDER


SOURCE_GOA = "GOA"
SOURCE_UNIPROT = "UniProtKB"
SOURCE_INTERPRO = "InterPro"
SOURCE_REACTOME = "Reactome"
SOURCE_GLYGEN = "GlyGen"
SOURCE_DISPROT = "DisProt"
SOURCE_ORGANISM = "UniProtKB-Organism"
SOURCE_TRAITS = "bacteria-archaea-traits"
LABEL_TIERS = ("experimental", "signature", "curated")
TIERS = (*LABEL_TIERS, "guard", "skip")
# A protein's tier for a term is the best of its assertions' tiers.
TIER_RANK = {tier: rank for rank, tier in enumerate(TIERS)}
# The tiers validation and test score; curated labels train and calibrate only (the Atlas v3 pattern).
SCORED_TIERS = ("experimental", "signature")

CATALYTIC_ACTIVITY = "GO:0003824"
FUNDAMENTAL_ASPECTS = (
    "enzyme", "molecular_function", "domain_family", "localization", "process_pathway", "biophysical_assembly", "ptm_processing",
    "organism",
)
# Fundamental aspects every protein holds: they make no protein eligible for a held-out split and balance none.
UNIVERSAL_ASPECTS = ("organism",)
_BY_ASPECT = {
    "ec": "enzyme", "rhea": "enzyme", "cofactor": "enzyme", "local_active_site": "enzyme",
    "go_mf": "molecular_function", "local_site": "molecular_function",
    "interpro": "domain_family", "pfam": "domain_family", "local_interpro": "domain_family", "local_pfam": "domain_family",
    "local_domain": "domain_family", "local_repeat": "domain_family", "local_zinc_finger": "domain_family",
    "local_dna_binding": "domain_family", "local_motif": "domain_family", "local_region": "domain_family",
    "uniprot_family": "domain_family", "cazy": "domain_family", "merops": "domain_family", "tcdb": "domain_family",
    "go_cc": "localization", "subcellular_location": "localization", "membrane_topology": "localization",
    "membrane_orientation": "localization", "local_signal_peptide": "localization", "local_transit_peptide": "localization",
    "local_transmembrane": "localization", "local_intramembrane": "localization", "local_topological_domain": "localization",
    "go_bp": "process_pathway", "uniprot_pathway": "process_pathway", "reactome": "process_pathway",
    "oligomeric_state": "biophysical_assembly", "local_compositional_bias": "biophysical_assembly",
    "local_coiled_coil": "biophysical_assembly", "local_helix": "biophysical_assembly", "local_strand": "biophysical_assembly",
    "local_turn": "biophysical_assembly", "local_disorder": "biophysical_assembly",
    "ptm": "ptm_processing", "local_modified_residue": "ptm_processing", "local_glycosylation": "ptm_processing",
    "local_lipidation": "ptm_processing", "local_disulfide": "ptm_processing", "local_crosslink": "ptm_processing",
    "local_propeptide": "ptm_processing", "local_peptide": "ptm_processing", "local_initiator_methionine": "ptm_processing",
    "local_chain": "ptm_processing",
    "taxonomy": "organism", **dict.fromkeys(COMPENDIUM_TRAIT_ASPECT_ORDER, "organism"),
}
KEYWORD_CATEGORY_ASPECTS = {
    "Biological process": "process_pathway", "Molecular function": "molecular_function", "Ligand": "molecular_function",
    "Cellular component": "localization", "Domain": "domain_family", "PTM": "ptm_processing",
}
# Keyword categories that leave the vocabulary (Logan, 2026-10-20), and GO terms too general to say anything of a protein.
DROPPED_KEYWORD_CATEGORIES = frozenset({"Technical term", "Coding sequence diversity", "Disease", "Developmental stage"})
GO_STOPLIST = frozenset({"GO:0008150", "GO:0003674", "GO:0005575", "GO:0005488", "GO:0005515", "GO:0042802"})
# A disordered region is a biophysical property, not a family's.
DISORDER_TERMS = frozenset({"Disordered"})
# ChEBI's metal cation: it and every ChEBI entity below it by is_a are the metal ions (`ontologies.below`), and binding one belongs
# to the enzyme aspect. ChEBI is the rule, so NAD(+), H(+) and NH4(+), whose ligand names end in a charge, are not metal ions, and
# nor is an ion ChEBI does not yet place below it (praseodymium(3+) and neodymium(3+) in the 2026 file).
METAL_CATION = "CHEBI:25213"


def assertion_tier(source: str, code: str, reviewed: bool) -> str:
    """The tier of one assertion: an InterPro match is a signature, the source organism and its observed traits experimental, an
    uncoded statement takes its entry's review, and every code the one tier `evidence_tier` gives it."""
    if source == SOURCE_INTERPRO:
        return "signature"
    if source in (SOURCE_ORGANISM, SOURCE_TRAITS):
        return "experimental"
    if not code:
        return "curated" if reviewed else "guard"
    return evidence_tier(code)


def fundamental_aspect(
    aspect: str, accession: str, *, catalytic: Collection[str], keyword_categories: Mapping[str, str], metal_ions: Collection[str],
) -> str | None:
    """The fundamental aspect of a term, or None for a term no aspect holds (a dropped keyword category, disease).

    `catalytic` holds catalytic activity and every GO term below it; `keyword_categories` maps a keyword accession to its category;
    `metal_ions` holds the ChEBI metal ions (`METAL_CATION` and every entity below it).
    """
    if aspect == "go_mf":
        return "enzyme" if accession in catalytic else "molecular_function"
    if aspect == "keyword":
        return KEYWORD_CATEGORY_ASPECTS.get(keyword_categories.get(accession, ""))
    if aspect == "local_binding":
        return "enzyme" if accession in metal_ions else "molecular_function"
    if aspect == "local_region" and accession in DISORDER_TERMS:
        return "biophysical_assembly"
    return _BY_ASPECT.get(aspect)


def best_tier(tiers: Collection[str]) -> str:
    """The best of a protein's tiers for one term: experimental, then signature, curated, guard and skip."""
    return min(tiers, key=TIER_RANK.__getitem__)
