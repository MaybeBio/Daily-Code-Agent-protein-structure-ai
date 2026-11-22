"""The EC view's non-enzymes: the pooled proteins a reviewed entry makes a confident non-enzyme, and the enzymes matched to them.

The definition is `ec_experimental_v3`'s (`foundry.protein.non_enzymes`; the decision record `2026-10-01_ec_non_enzyme_class.md`
gives each rule's reason), applied to the facts of every Swiss-Prot entry of the compendium's release, with the keywords and
domains that nearly only enzymes carry read from all of them and the catalytic GO terms from the compendium's own GO. A pooled
protein is a candidate when one of its reviewed entries breaks no rule and none of its accessions, reviewed or not, holds a sign of
catalysis at any tier, guards included: an EC number, a Rhea reaction, a cofactor, an active site or a catalytic GO term
(`CATALYSIS_ASPECTS`). The second test reaches the TrEMBL entries and GOA lines merged into the sequence, as v3's set-aside of a
candidate whose sequence an EC-numbered entry shares reaches the other reviewed ones.

`matched` marks, in each split, the rows `matching.match_cells` keeps at v2's and v3's class share, 2 non-enzymes in 5
(`Definition.share`, 1.5 enzymes a non-enzyme): every (order, length bin) cell keeps as many non-enzymes as its enzymes can match
and 1.5 enzymes for each, at most one of either from a 0.5-identity cluster in a cell, so neither lineage nor length tells the matched
classes apart. Drawing the enzymes to the non-enzymes' cells and keeping every non-enzyme, the first design, failed the gate
(held-out AUROC 0.74): confident non-enzymes sit mostly in eukaryotic model organisms, and the enzymes, experimental ones
included, spread over bacteria, so a lineage one class lacks cannot be matched by drawing the other. The matched rows answer
whether a protein is an enzyme; every enzyme row answers its EC levels.
"""

from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict

from foundry.protein.non_enzymes import Definition, EntryFacts, context_of, rule_failures
from .matching import LENGTH_EDGES, Candidate, length_bin, match_cells


NON_ENZYME = "non_enzyme"
# The aspects whose every positive assertion is a sign of catalysis; GO's catalytic terms are the `go_mf` rows of the enzyme
# fundamental aspect. Metal binding is in the enzyme aspect too, and is no such sign: calmodulin binds calcium.
CATALYSIS_ASPECTS = ("ec", "rhea", "cofactor", "local_active_site")
# The pooled assertion columns `catalysis_signs` reads.
CATALYSIS_COLUMNS = ["protein_id", "aspect", "fundamental_aspect", "negated"]
# The ranks a protein's matching stratum is read from, finest first: its order, or the first rank above it the lineage names.
STRATUM_RANKS = ("order", "class", "phylum", "domain")
CLUSTER_COLUMN = "c050"
CANDIDATE_SCHEMA = pa.schema([("protein_id", pa.string()), ("accession", pa.string())])


def catalysis_filter() -> pc.Expression:
    """The pooled rows that are a sign of catalysis: positive, and of a catalysis aspect or a catalytic GO term."""
    catalytic = pc.field("aspect").isin(list(CATALYSIS_ASPECTS)) | (
        (pc.field("aspect") == "go_mf") & (pc.field("fundamental_aspect") == "enzyme"))
    return catalytic & ~pc.field("negated")


def catalysis_signs(assertions: pa.Table) -> dict[str, set[str]]:
    """Each protein holding a sign of catalysis (`catalysis_filter`), by the aspect it holds it in (`go_mf` for a catalytic term)."""
    signs = assertions.filter(catalysis_filter()).group_by(["protein_id", "aspect"]).aggregate([])
    found: dict[str, set[str]] = {}
    for protein, aspect in zip(signs["protein_id"].to_pylist(), signs["aspect"].to_pylist(), strict=True):
        found.setdefault(aspect, set()).add(protein)
    return found


def candidates(
    facts: Sequence[EntryFacts], accession_to_protein: Mapping[str, str], signs: Mapping[str, Iterable[str]], go_terms: frozenset[str],
    definition: Definition | None = None,
) -> tuple[pa.Table, dict[str, object]]:
    """The candidate non-enzymes (`CANDIDATE_SCHEMA`, protein-id order, each with its first passing reviewed accession) and the
    funnel that made them.

    `facts` are every reviewed entry of the release, `accession_to_protein` the pooled accessions' proteins, `signs` the proteins
    `catalysis_signs` names by aspect, and `go_terms` catalytic activity and every GO term below it; `definition` is v3's when None.
    """
    definition = definition or Definition()
    context = context_of(facts, definition, go_terms)
    broken: Counter[str] = Counter()
    passing: dict[str, str] = {}
    clean = unpooled = 0
    for row in sorted(facts, key=lambda item: item["accession"]):
        failures = rule_failures(row, definition, context)
        broken.update(failures)
        if failures:
            continue
        clean += 1
        protein = accession_to_protein.get(row["accession"])
        if protein is None:
            unpooled += 1
        else:
            passing.setdefault(protein, row["accession"])
    marked = {aspect: set(proteins) & set(passing) for aspect, proteins in signs.items()}
    catalytic = set().union(*marked.values()) if marked else set()
    kept = sorted(protein for protein in passing if protein not in catalytic)
    table = pa.table({"protein_id": kept, "accession": [passing[protein] for protein in kept]}, schema=CANDIDATE_SCHEMA)
    funnel = {
        "entries": len(facts), "broken_rules": dict(sorted(broken.items())), "without_any_broken_rule": clean,
        "outside_the_pool": unpooled, "pooled_proteins": len(passing),
        "with_a_sign_of_catalysis": {aspect: len(found) for aspect, found in sorted(marked.items()) if found},
        "set_aside_for_catalysis": len(catalytic), "candidates": len(kept),
    }
    record = {
        "definition": asdict(definition),
        "context": {"catalytic_keywords": sorted(context.catalytic_keywords), "enzyme_domains": sorted(context.enzyme_domains),
                    "catalytic_go_terms": len(go_terms)},
        "funnel": funnel,
    }
    return table, record


def stratum(ranks: Mapping[str, str | None], names: Sequence[str] = STRATUM_RANKS) -> str:
    """A protein's matching stratum: the first of `names` its lineage names, as `rank:name`, or `unknown`."""
    for rank in names:
        if ranks.get(rank):
            return f"{rank}:{ranks[rank]}"
    return "unknown"


def matched_rows(
    view: pa.Table, strata: Mapping[str, str], clusters: Mapping[str, str], *, ratio: float, cluster_cap: int = 1, seed: int = 7,
    edges: Sequence[int] = LENGTH_EDGES,
) -> tuple[set[str], dict[str, object]]:
    """The proteins of the EC view the matching keeps, and its report per split.

    `view` holds `protein_id`, `sequence`, `split` and `level_1`; `strata` and `clusters` give each row's stratum (`stratum`) and
    its cluster at 0.5 identity, and `edges` the length bins. In each split every (stratum, length bin) cell keeps the non-enzymes
    its enzymes can match at `ratio` each, and those enzymes, `cluster_cap` of either from a cluster (`matching.match_cells`).
    """
    proteins = view["protein_id"].to_pylist()
    splits = view["split"].to_pylist()
    lengths = pc.utf8_length(view["sequence"]).to_pylist()
    kinds = view["level_1"].to_pylist()
    sides: dict[str, dict[str, list[Candidate]]] = {}
    for protein, split, length, kind in zip(proteins, splits, lengths, kinds, strict=True):
        side = "non_enzymes" if kind == NON_ENZYME else "enzymes"
        unit = Candidate(protein, strata[protein], length_bin(length, edges), clusters[protein])
        sides.setdefault(split, {"enzymes": [], "non_enzymes": []})[side].append(unit)
    kept: set[str] = set()
    report: dict[str, object] = {"ratio": ratio, "cluster_cap": cluster_cap, "length_bins": len(edges) + 1, "splits": {}}
    for split in sorted(sides):
        enzymes, non_enzymes = sides[split]["enzymes"], sides[split]["non_enzymes"]
        chosen_non_enzymes, chosen_enzymes, cells = match_cells(non_enzymes, enzymes, ratio=ratio, cluster_cap=cluster_cap, seed=seed)
        kept.update(chosen_non_enzymes)
        kept.update(chosen_enzymes)
        total = len(chosen_non_enzymes) + len(chosen_enzymes)
        report["splits"][split] = {
            "enzymes": len(enzymes), "non_enzymes": len(non_enzymes), "matched_enzymes": len(chosen_enzymes),
            "matched_non_enzymes": len(chosen_non_enzymes), "non_enzyme_share": round(len(chosen_non_enzymes) / total, 4) if total else None,
            "cells": cells["cells"], "matched_cells": cells["matched_cells"],
        }
    return kept, report
