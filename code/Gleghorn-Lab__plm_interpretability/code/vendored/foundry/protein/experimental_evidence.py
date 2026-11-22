"""Which evidence codes count as experimental, in the Gene Ontology and in UniProtKB, and the tier each code takes.

Every release that admits labels on experimental evidence (the GO, EC and location releases of the
production suite and the annotation release of annotation_vocabulary) reads the two experimental sets, so the
meaning of "experimental" is stated once. Gene Ontology categories follow
https://geneontology.org/docs/guide-go-evidence-codes/ and UniProt's evidence ontology codes follow
https://www.uniprot.org/help/evidences .

The annotation compendium (Logan, 2026-10-20) reads every code and gives each a tier with `evidence_tier`:

- `experimental`: the two experimental sets, plus UniProt's combinatorial manual code ECO:0007744 (published large-scale
  proteomics and part of the 3D-structure annotation), which the earlier releases leave out. Those releases keep calling
  `is_experimental_go` and `is_experimental_eco`, whose meaning does not change.
- `curated`: a curator's inference: sequence similarity, a sequence model applied by hand, a curator's or a traceable author's
  statement.
- `guard`: computed or imported assertions (automatic rules, phylogenetic propagation, electronic mappings, untraceable
  statements). A guarded term is recorded and is never a label and never a negative.
- `skip`: a code that says no evidence exists (GO `ND`, ECO:0000307).

An unknown code raises, so a source that starts writing a new code stops the build instead of choosing a tier for it.
"""

from __future__ import annotations

from typing import Literal


EvidenceTier = Literal["experimental", "curated", "guard", "skip"]
EVIDENCE_TIERS: tuple[EvidenceTier, ...] = ("experimental", "curated", "guard", "skip")

# Experimental and high-throughput experimental GO evidence codes, as GAF 2.2 column 7 writes them.
GO_EXPERIMENTAL_CODES = frozenset({
    "EXP", "IDA", "IPI", "IMP", "IGI", "IEP", "HTP", "HDA", "HMP", "HGI", "HEP",
})
# `ECO:0000269` is UniProt's "experimental evidence used in manual assertion", the only experimental code its
# comments carry. The others are the experimental assertion types of the evidence ontology that a curated
# source can name; the combinatorial ECO:0007744 (computational and experimental together) is not among them.
UNIPROT_EXPERIMENTAL_ECO = frozenset({
    "ECO:0000269", "ECO:0000314", "ECO:0000315", "ECO:0000316", "ECO:0000353", "ECO:0000270",
})
# UniProt's combinatorial evidence used in manual assertion: published large-scale proteomics and a subset of the
# 3D-structure annotation. Experimental in the compendium's tiers only.
UNIPROT_COMBINATORIAL_ECO = frozenset({"ECO:0007744"})
# Sequence similarity, curator inference and traceable author statement, in GAF codes, and the sequence-model codes a
# curator applies by hand (ISA, ISM).
GO_CURATED_CODES = frozenset({"ISS", "ISO", "ISA", "ISM", "IC", "TAS"})
# Phylogenetic propagation, electronic and reviewed computational annotation, genomic context, and non-traceable author
# statement. IMR is the retired name of IKR, still written by old annotations.
GO_GUARD_CODES = frozenset({"IBA", "IBD", "IKR", "IRD", "IMR", "IEA", "RCA", "IGC", "NAS"})
GO_SKIPPED_CODES = frozenset({"ND"})
# Sequence similarity (`By similarity`), a sequence model applied in a manual assertion, and curator inference.
UNIPROT_CURATED_ECO = frozenset({"ECO:0000250", "ECO:0000255", "ECO:0000305"})
# Automatic assertions (rules, the sequence models they apply, imports, the combinatorial automatic code, deep learning), the
# electronic GO code, and the two manual codes that cite no experiment or curator judgement (non-traceable author statement,
# information imported in a manual assertion).
UNIPROT_GUARD_ECO = frozenset({
    "ECO:0000256", "ECO:0000259", "ECO:0000303", "ECO:0000312", "ECO:0000313", "ECO:0000501", "ECO:0007829",
    "ECO:0008006",
})
UNIPROT_SKIPPED_ECO = frozenset({"ECO:0000307"})

__all__ = [
    "EVIDENCE_TIERS", "EvidenceTier", "GO_CURATED_CODES", "GO_EXPERIMENTAL_CODES", "GO_GUARD_CODES", "GO_SKIPPED_CODES",
    "UNIPROT_COMBINATORIAL_ECO", "UNIPROT_CURATED_ECO", "UNIPROT_EXPERIMENTAL_ECO", "UNIPROT_GUARD_ECO", "UNIPROT_SKIPPED_ECO",
    "UnknownEvidenceCode", "evidence_tier", "is_experimental_eco", "is_experimental_go",
]


class UnknownEvidenceCode(ValueError):
    """A GAF or ECO code that no tier names."""


def is_experimental_go(code: str) -> bool:
    """Whether a GAF evidence code (`IDA`, `IEA`) is an experimental one."""
    return code in GO_EXPERIMENTAL_CODES


def is_experimental_eco(code: str) -> bool:
    """Whether a UniProt evidence type (`ECO:0000269`) is an experimental one."""
    return code in UNIPROT_EXPERIMENTAL_ECO


_TIER_SETS: tuple[tuple[EvidenceTier, frozenset[str]], ...] = (
    ("experimental", GO_EXPERIMENTAL_CODES | UNIPROT_EXPERIMENTAL_ECO | UNIPROT_COMBINATORIAL_ECO),
    ("curated", GO_CURATED_CODES | UNIPROT_CURATED_ECO),
    ("guard", GO_GUARD_CODES | UNIPROT_GUARD_ECO),
    ("skip", GO_SKIPPED_CODES | UNIPROT_SKIPPED_ECO),
)


def evidence_tier(code: str) -> EvidenceTier:
    """The compendium's tier of one GAF code (`IDA`) or UniProt evidence type (`ECO:0000269`); an unknown code raises."""
    for tier, codes in _TIER_SETS:
        if code in codes:
            return tier
    raise UnknownEvidenceCode(f"no evidence tier names {code!r}; add it to a tier of foundry.protein.experimental_evidence")
