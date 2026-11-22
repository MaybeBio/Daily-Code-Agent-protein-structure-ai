"""Deterministic aspect grammar and integer-token assignment."""

import re

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .schema import TermKey


LEGACY_ASPECT_ORDER = (
    "ec",
    "go_bp",
    "go_cc",
    "go_mf",
    "interpro",
    "cofactor",
    "keyword",
)

RECIPE_EXCLUDED_ASPECTS = frozenset({"gene3d"})

ADDED_GLOBAL_ASPECT_ORDER = (
    "rhea",
    "pfam",
    "disease",
    "subcellular_location",
    "membrane_topology",
    "membrane_orientation",
)

LOCAL_FEATURE_ASPECTS = {
    "ACT_SITE": "local_active_site",
    "BINDING": "local_binding",
    "SITE": "local_site",
    "REGION": "local_region",
    "DOMAIN": "local_domain",
    "MOTIF": "local_motif",
    "DNA_BIND": "local_dna_binding",
    "ZN_FING": "local_zinc_finger",
    "REPEAT": "local_repeat",
    "SIGNAL": "local_signal_peptide",
    "TRANSIT": "local_transit_peptide",
    "TRANSMEM": "local_transmembrane",
    "INTRAMEM": "local_intramembrane",
    "TOPO_DOM": "local_topological_domain",
    "CHAIN": "local_chain",
    "PEPTIDE": "local_peptide",
    "PROPEP": "local_propeptide",
    "MOD_RES": "local_modified_residue",
    "CARBOHYD": "local_glycosylation",
    "LIPID": "local_lipidation",
    "DISULFID": "local_disulfide",
    "CROSSLNK": "local_crosslink",
    "HELIX": "local_helix",
    "STRAND": "local_strand",
    "TURN": "local_turn",
    "COILED": "local_coiled_coil",
    "COMPBIAS": "local_compositional_bias",
}

ADDED_LOCAL_ASPECT_ORDER = (
    "local_interpro",
)

# The annotation compendium's own aspects (2026-10-20). They rank after every earlier aspect, in the compendium's order only, so
# the earlier releases keep their grammar: taxonomy stays metadata there and a label here (Logan asked for taxonomy labels).
COMPENDIUM_GLOBAL_ASPECT_ORDER = (
    "uniprot_pathway",
    "reactome",
    "ptm",
    "oligomeric_state",
    "uniprot_family",
    "cazy",
    "merops",
    "tcdb",
    "taxonomy",
)

COMPENDIUM_LOCAL_ASPECT_ORDER = (
    "local_pfam",
    "local_initiator_methionine",
    "local_disorder",
)

ASPECT_ORDER = (
    *LEGACY_ASPECT_ORDER,
    *ADDED_GLOBAL_ASPECT_ORDER,
    *LOCAL_FEATURE_ASPECTS.values(),
    *ADDED_LOCAL_ASPECT_ORDER,
)

# The organism traits Madin et al. 2020 compile (2026-10-22), each an aspect of its own so a protein observed in one is no negative
# of another, last so every earlier aspect keeps its place.
COMPENDIUM_TRAIT_ASPECT_ORDER = (
    "trait_gram_stain",
    "trait_oxygen",
    "trait_sporulation",
    "trait_motility",
    "trait_temperature_range",
    "trait_salinity_range",
    "trait_cell_shape",
    "trait_isolation_source",
)

COMPENDIUM_ASPECT_ORDER = (
    *ASPECT_ORDER,
    *COMPENDIUM_GLOBAL_ASPECT_ORDER,
    *COMPENDIUM_LOCAL_ASPECT_ORDER,
    *COMPENDIUM_TRAIT_ASPECT_ORDER,
)

SOURCE_GLOBAL_ASPECT_ORDER = (
    "ec",
    "go_bp",
    "go_cc",
    "go_mf",
    "interpro",
    "gene3d",
    "cofactor",
    "keyword",
    *ADDED_GLOBAL_ASPECT_ORDER,
)

LEGACY_SUFFIX_TO_ASPECT = {
    "ec": "ec",
    "bp": "go_bp",
    "cc": "go_cc",
    "mf": "go_mf",
    "ip": "interpro",
    "threed": "gene3d",
    "cofactor": "cofactor",
    "keywords": "keyword",
}

SPECIAL_TOKEN_NAMES = ("<pad>", "<bos>", "<eos>", "<mask>", "<unk>")
_NATURAL_COMPONENT = re.compile(r"(\d+)")


def natural_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """Return a stable natural-sort key for mixed numeric accessions."""
    components: list[tuple[int, int | str]] = []
    for component in _NATURAL_COMPONENT.split(value.casefold()):
        if not component:
            continue
        components.append((0, int(component)) if component.isdigit() else (1, component))
    return tuple(components)


def term_sort_key(
    term: TermKey, aspect_order: Sequence[str] = ASPECT_ORDER,
) -> tuple[int, tuple[tuple[int, int | str], ...], str, str]:
    """Return the grammar ordering for one term; the compendium passes `COMPENDIUM_ASPECT_ORDER`."""
    try:
        aspect_rank = aspect_order.index(term.aspect)
    except ValueError as error:
        raise ValueError(f"Unknown vocabulary aspect: {term.aspect!r}") from error
    return (
        aspect_rank,
        natural_key(term.accession),
        term.source_database.casefold(),
        term.term_id,
    )


def source_global_term_sort_key(
    term: TermKey,
) -> tuple[int, tuple[tuple[int, int | str], ...], str, str]:
    """Order raw global observations, including recipe-excluded source aspects."""

    try:
        aspect_rank = SOURCE_GLOBAL_ASPECT_ORDER.index(term.aspect)
    except ValueError as error:
        raise ValueError(f"Unknown source annotation aspect: {term.aspect!r}") from error
    return (
        aspect_rank,
        natural_key(term.accession),
        term.source_database.casefold(),
        term.term_id,
    )


@dataclass(frozen=True, slots=True)
class VocabularyIndex:
    """Bidirectional biological and special-token mapping for one vocabulary build."""

    term_to_token: Mapping[TermKey, int]
    token_to_term: Mapping[int, TermKey]
    special_tokens: Mapping[str, int]

    def __post_init__(self) -> None:
        if len(self.term_to_token) != len(self.token_to_term):
            raise ValueError("Term-to-token and token-to-term maps must have equal size")
        for term, token in self.term_to_token.items():
            if self.token_to_term.get(token) != term:
                raise ValueError("Vocabulary maps are not exact inverses")
        if set(self.term_to_token.values()) & set(self.special_tokens.values()):
            raise ValueError("Special tokens cannot collide with biological tokens")


def build_vocabulary_index(terms: Iterable[TermKey], *, aspect_order: Sequence[str] = ASPECT_ORDER) -> VocabularyIndex:
    """Assign biological tokens by grammar, then append collision-free special tokens."""
    ordered_terms = sorted(set(terms), key=lambda term: term_sort_key(term, aspect_order))
    term_to_token = {term: token for token, term in enumerate(ordered_terms)}
    token_to_term = {token: term for term, token in term_to_token.items()}
    special_offset = len(ordered_terms)
    special_tokens = {
        name: special_offset + index
        for index, name in enumerate(SPECIAL_TOKEN_NAMES)
    }
    return VocabularyIndex(
        term_to_token=term_to_token,
        token_to_term=token_to_term,
        special_tokens=special_tokens,
    )
