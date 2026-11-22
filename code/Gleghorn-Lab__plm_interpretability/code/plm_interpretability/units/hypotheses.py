"""The preregistered decisions H1 to H7, each read off per-pole tables with the rules frozen in the preregistration's
`hypotheses` block: H1 to H5 and H7 from score tables (`scores.global_scores` and `scores.local_scores` merged), H6 from
E7's ablation table (`ablation.run_h6`). H0, the InterPLM re-test, comes from E1.

A table has one row per pole with at least `margin` (best training term's AUROC minus the best unrelated term's),
`held_out_auroc` (the test AUROC of the best training term) and `best_term`. Medians drop poles without a testable term.

Symbols: a, b poles of two bases; k rotations.
"""

from __future__ import annotations

import json
import numpy as np
import pandas as pd

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from scipy import stats

from .bootstrap import Interval, median_difference, median_interval, rotation_test


MIN_KIND_POLES = 20  # a concept kind is tested only with this many poles in each arm
MIN_LABELED_POLES = 20  # H6 is decided only with this many tested labeled poles
CONCEPT_KINDS = {  # the compendium's aspects by kind (preregistration, `H4_kinds`); organism's are never scored
    "function": ("go_mf", "ec", "rhea", "cofactor", "oligomeric_state"),
    "process": ("go_bp", "reactome", "uniprot_pathway"),
    "location": ("go_cc", "subcellular_location", "membrane_orientation", "membrane_topology"),
    "family": ("interpro", "pfam", "uniprot_family", "merops"),
    "keyword": ("keyword", "ptm"),
    "site": ("local_active_site", "local_binding", "local_site", "local_modified_residue", "local_glycosylation",
             "local_lipidation", "local_crosslink", "local_disulfide", "local_dna_binding", "local_zinc_finger", "local_motif",
             "local_initiator_methionine"),
    "structure": ("local_strand", "local_coiled_coil", "local_transmembrane", "local_intramembrane", "local_topological_domain",
                  "local_signal_peptide", "local_transit_peptide", "local_propeptide", "local_peptide", "local_disorder"),
    "domain": ("local_domain", "local_region", "local_repeat", "local_interpro", "local_pfam"),
    "composition": ("intrinsic",),
}
KIND_OF_ASPECT = {aspect: kind for kind, aspects in CONCEPT_KINDS.items() for aspect in aspects}
# A unit whose kind is not its aspect's: UniProt's disordered region is a `local_region` of the biophysical aspect.
KIND_OF_UNIT = {"local_region/biophysical_assembly": "structure"}


@dataclass(frozen=True)
class Decision:
    hypothesis: str
    passed: bool
    details: dict[str, object] = field(default_factory=dict)


def finite_values(values: pd.Series) -> np.ndarray:
    array = values.to_numpy(dtype=np.float64)  # (a,)
    return array[np.isfinite(array)]  # (a_finite,)


def _interval(interval: Interval) -> dict[str, float]:
    return {"estimate": interval.estimate, "low": interval.low, "high": interval.high}


def h0_mlp_over_residual(summary: pd.DataFrame, per_concept: pd.DataFrame) -> Decision:
    """On InterPLM's evaluation ESM-2's intermediate poles beat its residual dimensions: at a majority of the evaluated
    (model, layer) cells, a larger share of the poles than of the dimensions is associated with a concept, and the median
    over concepts of the paired difference in best test F1 has its concept-bootstrap interval above zero."""
    # summary: model, layer, arm, share (`retest.retest_tables` with a model column); per_concept: model, layer, arm,
    # concept, best_test_f1
    cells = []
    for (model, layer), group in summary.groupby(["model", "layer"]):
        share = group.set_index("arm")["share"]
        scores = per_concept[(per_concept["model"] == model) & (per_concept["layer"] == layer)]
        wide = scores.pivot(index="concept", columns="arm", values="best_test_f1")  # (concepts, arms)
        paired = (wide["mlp_poles"] - wide["residual"]).dropna().to_numpy()  # (c,)
        difference = median_interval(paired)
        won = bool(share["mlp_poles"] > share["residual"]) and difference.low > 0
        cells.append({"model": model, "layer": int(layer), "won": won, "concepts": len(paired),
                      "median_f1_difference": _interval(difference),
                      "shares": {arm: float(value) for arm, value in share.items()}})
    passed = sum(cell["won"] for cell in cells) > len(cells) / 2
    return Decision("H0", passed, {"cells": cells, "won": sum(cell["won"] for cell in cells), "of": len(cells)})


def h1_native_over_residual(native: pd.DataFrame, residual: pd.DataFrame) -> Decision:
    """Native poles are more specific than the residual stream's: the median margin's difference has its interval above zero."""
    difference = median_difference(finite_values(native["margin"]), finite_values(residual["margin"]))
    return Decision("H1", difference.low > 0, {"margin_difference": _interval(difference)})


def h2_native_privileged(native: pd.DataFrame, rotations: Sequence[pd.DataFrame]) -> Decision:
    """Native medians of margin and held-out AUROC above every rotation's, by more than the rotations' range, for both."""
    details: dict[str, object] = {}
    passed = True
    for metric in ("margin", "held_out_auroc"):
        test = rotation_test(finite_values(native[metric]), [finite_values(rotated[metric]) for rotated in rotations])
        details[metric] = {"native": test.native, "rotations": list(test.rotations), "rank_p": test.rank_p,
                           "range_gap": test.range_gap, "privileged": test.privileged}
        passed &= test.privileged
    return Decision("H2", passed, details)


def h3_native_near_sae(native: pd.DataFrame, sae: pd.DataFrame, *, level: float = 0.90, bound: float = 0.05) -> Decision:
    """Native poles approach the size-matched SAE: the 90% interval of the held-out AUROC median difference lies in +-0.05."""
    difference = median_difference(finite_values(native["held_out_auroc"]), finite_values(sae["held_out_auroc"]), level=level)
    return Decision("H3", difference.inside(-bound, bound), {"held_out_difference": _interval(difference)})


def concept_kind(terms: pd.DataFrame, intrinsic_tokens: Sequence[int] = ()) -> dict[int, str]:
    """Each scored term's concept kind from its unit (`KIND_OF_UNIT`) or else its aspect; intrinsic tokens are
    composition. A term no unit scores (`unit` -1, the organism aspect) has none; an unmapped aspect raises."""
    scored = terms[terms["unit"] >= 0] if "unit" in terms else terms
    units = (scored["aspect"] + "/" + scored["fundamental_aspect"]) if "fundamental_aspect" in scored else scored["aspect"]
    unknown = sorted(set(scored.loc[~units.isin(KIND_OF_UNIT), "aspect"]) - set(KIND_OF_ASPECT))
    if unknown:
        raise ValueError(f"Aspects {unknown} have no concept kind; extend CONCEPT_KINDS in the preregistration first.")
    kinds = {int(token): KIND_OF_UNIT.get(unit, KIND_OF_ASPECT.get(aspect, "")) for token, aspect, unit
             in zip(scored["token"], scored["aspect"], units, strict=True)}
    kinds.update({int(token): "composition" for token in intrinsic_tokens})
    return kinds


def input_kinds(inputs: Path) -> dict[int, str]:
    """Every term's concept kind in a run's inputs folder: its terms table and its atlas set's intrinsic tokens."""
    description = json.loads((inputs / "atlas_set.json").read_text(encoding="utf-8"))
    return concept_kind(pd.read_parquet(inputs / "terms.parquet"), list(description["intrinsic_tokens"].values()))


def h4_pretraining(trained: pd.DataFrame, random: pd.DataFrame, kinds: Mapping[int, str], *,
                   excluded: Sequence[str] = ("composition",), min_poles: int = MIN_KIND_POLES) -> Decision:
    """Trained minus random-init median margin, by the concept kind of each pole's best term, above zero for every tested
    kind but composition; a kind with too few poles in either arm is reported and fails the rule."""
    details: dict[str, object] = {}
    passed = True
    for kind in sorted(set(CONCEPT_KINDS) - set(excluded)):
        ours = finite_values(trained.loc[trained["best_term"].map(kinds) == kind, "margin"])  # (a,)
        theirs = finite_values(random.loc[random["best_term"].map(kinds) == kind, "margin"])  # (b,)
        if min(len(ours), len(theirs)) < min_poles:
            details[kind] = {"tested": False, "trained_poles": len(ours), "random_poles": len(theirs)}
            passed = False
            continue
        difference = median_difference(ours, theirs)
        details[kind] = {"tested": True, "difference": _interval(difference), "trained_poles": len(ours),
                         "random_poles": len(theirs)}
        passed &= difference.low > 0
    return Decision("H4", passed, details)


def h5_generalization(native: pd.DataFrame, rotations: Sequence[pd.DataFrame], *, alpha: float = 0.01) -> Decision:
    """Native held-out AUROC of the selected terms exceeds the pooled rotated units': one-sided Mann-Whitney below alpha
    and a positive median difference."""
    ours = finite_values(native["held_out_auroc"])  # (a,)
    pooled = np.concatenate([finite_values(rotated["held_out_auroc"]) for rotated in rotations])  # (k * a,)
    test = stats.mannwhitneyu(ours, pooled, alternative="greater")
    difference = float(np.median(ours) - np.median(pooled))
    return Decision("H5", bool(test.pvalue < alpha and difference > 0),
                    {"p_value": float(test.pvalue), "median_difference": difference, "native": len(ours), "pooled": len(pooled)})


def h6_used(table: pd.DataFrame, *, minimum: int = MIN_LABELED_POLES) -> Decision:
    """Labeled poles are used: over tested labeled poles, the median of each pole's drop minus its placebos' mean drop
    is above zero with its interval excluding zero. Fewer than `minimum` tested poles fails the rule and is reported."""
    # table: one row per labeled pole (`ablation.run_h6`), with drop and placebo_drops where status is "tested"
    tested = table[table["status"] == "tested"]
    counts = {status: int(count) for status, count in table["status"].value_counts().items()}
    if len(tested) < minimum:
        return Decision("H6", False, {"statuses": counts, "reason": f"fewer than {minimum} tested poles"})
    drops = tested["drop"].to_numpy(dtype=np.float64)  # (a,)
    placebo = np.array([np.mean(values) for values in tested["placebo_drops"]], dtype=np.float64)  # (a,)
    excess = median_interval(drops - placebo)
    return Decision("H6", bool(excess.low > 0), {
        "statuses": counts, "median_excess": _interval(excess), "median_drop": float(np.median(drops)),
        "median_placebo_drop": float(np.median(placebo)),
    })


def h7_scale(by_model: Sequence[tuple[str, pd.DataFrame]]) -> Decision:
    """The median margin rises from each model to the next larger one, each step's interval above zero."""
    details: dict[str, object] = {}
    passed = True
    for (smaller, first), (larger, second) in zip(by_model[:-1], by_model[1:], strict=True):
        difference = median_difference(finite_values(second["margin"]), finite_values(first["margin"]))
        details[f"{larger}_minus_{smaller}"] = _interval(difference)
        passed &= difference.low > 0
    return Decision("H7", passed, details)
