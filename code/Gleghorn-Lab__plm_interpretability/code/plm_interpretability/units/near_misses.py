"""E7c: Swiss-Prot's mutagenesis as near misses for the poles E2 labels.

Swiss-Prot's mutagenesis entries record what a substitution did to its protein. A pole labeled with an annotated local
term (one of the release's, not an intrinsic one) should lose more of its activity at the site when a substitution
inside the term abolishes function than when one leaves function unchanged, the near miss: the same kind of edit at the
same kind of residue, without the loss. A pole that reads only the residue's identity loses the same either way.
Explanations that survive near misses are the test Cammarata (Goodfire, 2026) asks of a unit's label.

The proteins are every reviewed protein of the compendium's validation and test splits, sampled into the atlas set or
not, so no label was selected on them; their terms are the release's experimental and signature ones, a curated term
masked. A substitution counts when it changes one residue, its note states only a loss of function or only no effect,
and it is not reported in combination with another substitution. Each is read at ESMC-600's block 26 in the wild type
and the mutant: the relative drop at the site of each labeled pole whose term covers the site and which fires there
in the wild type, averaged per substitution, and the same for placebo poles, those firing at the site whose wild-type
activation is closest to each labeled pole's on a log scale. Loss and no-effect substitutions are compared within
substitution types (the same wild-type and substituted residue) by a stratified AUROC, for labeled poles and for
placebos, with a bootstrap over clusters.

Symbols: m substitutions; s sequences of a batch; p poles, 2f.
"""

from __future__ import annotations

import re
import numpy as np
import pandas as pd
import torch

from collections.abc import Sequence
from dataclasses import dataclass
from torch import Tensor, nn

from .ablation import column_mask, matched_placebos, term_intervals
from .atlas import TOKEN_BUDGET, encode_batch, length_batches
from .capture import BlockReader, BlockStates
from .poles import swiglu_poles


UNIPROT_FIELDS = "accession,sequence,ft_mutagen"
UNIPROT_STREAM = ("https://rest.uniprot.org/uniprotkb/stream?compressed=true&format=tsv"
                  "&query=%28reviewed%3Atrue%29%20AND%20%28ft_mutagen%3A%2A%29&fields=" + UNIPROT_FIELDS.replace(",", "%2C"))
HELD_OUT = ("validation", "test")
PLACEBOS = 10
SEED = 24895
DRAWS = 1000
FEATURE = re.compile(r'MUTAGEN (\d+); /note="([A-Z])->([A-Z](?:,[A-Z])*): ([^"]*)"')
LOSS = re.compile(r"\b(?:loss of|lost|lacks?|lack of|abolish\w*|abrogat\w*|eliminat\w*|inactive|inactivat\w*|"
                  r"complete(?:ly)? (?:block\w*|inhibit\w*))", re.IGNORECASE)
NO_EFFECT = re.compile(r"\b(?:no (?:significant |obvious |apparent |detectable |measurable )?(?:effect|change|difference|"
                       r"alteration)|(?:does|did) not (?:affect|alter|change)|not affect\w*|unaffected|normal|"
                       r"(?:like|as|similar to) wild[- ]type|wild[- ]type[- ]like)", re.IGNORECASE)
GRADED = re.compile(r"\b(?:partial\w*|reduc\w*|decreas\w*|impair\w*|weak\w*|diminish\w*|lower\w*|increas\w*|enhanc\w*|"
                    r"higher|stronger|slight\w*|moderate\w*)", re.IGNORECASE)
COMBINED = "associated with"


@dataclass(frozen=True)
class Substitution:
    position: int  # 1-based, as UniProt numbers residues
    wild: str
    mutant: str
    effect: str  # "loss" or "none"
    note: str


def effect_class(description: str) -> str | None:
    """'loss' for a note that states only a loss of function, 'none' for one that states only no effect, None for a
    graded, increased, mixed or combined effect."""
    if COMBINED in description.lower() or GRADED.search(description):
        return None
    loss, none = bool(LOSS.search(description)), bool(NO_EFFECT.search(description))
    if loss == none:
        return None
    return "loss" if loss else "none"


def parse_mutagenesis(field: object) -> list[Substitution]:
    """The single-residue substitutions of one entry's mutagenesis field whose effect is one class; ranges, deletions
    and multi-residue edits do not match the feature pattern."""
    if not isinstance(field, str):
        return []
    found = []
    for position, wild, mutants, description in FEATURE.findall(field):
        effect = effect_class(description)
        if effect is not None:
            found.extend(Substitution(int(position), wild, mutant, effect, description)
                         for mutant in mutants.split(",") if mutant != wild)
    return found


def held_out_substitutions(entries: pd.DataFrame, proteins: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Every classified substitution of a reviewed entry whose protein the compendium holds out, at a site the pooled
    sequence holds with the stated wild-type residue, with counts of what each filter dropped.

    `entries` holds UniProt's TSV columns Entry and Mutagenesis; `proteins` the compendium's proteins (`accessions`, each
    entry's accessions; `split`, the release's; `cluster`; `sequence`; local runs). An accession two proteins share raises.
    """
    row_of: dict[str, int] = {}
    for row, accessions in enumerate(proteins["accessions"]):
        for accession in accessions:
            if row_of.setdefault(str(accession), row) != row:
                raise ValueError(f"Accession {accession} belongs to two proteins.")
    counts = {"classified": 0, "not_pooled": 0, "training_split": 0, "beyond_sequence": 0, "wild_mismatch": 0}
    rows = []
    for accession, field in zip(entries["Entry"], entries["Mutagenesis"], strict=True):
        found = parse_mutagenesis(field)
        counts["classified"] += len(found)
        if not found:
            continue
        if accession not in row_of:
            counts["not_pooled"] += len(found)
            continue
        row = row_of[accession]
        cluster = str(proteins["cluster"].iloc[row])
        if proteins["split"].iloc[row] not in HELD_OUT:
            counts["training_split"] += len(found)
            continue
        sequence = proteins["sequence"].iloc[row]
        for substitution in found:
            if substitution.position > len(sequence):
                counts["beyond_sequence"] += 1
            elif sequence[substitution.position - 1] != substitution.wild:
                counts["wild_mismatch"] += 1
            else:
                rows.append({"accession": accession, "row": row, "cluster": cluster, "site": substitution.position - 1,
                             "wild": substitution.wild, "mutant": substitution.mutant, "effect": substitution.effect,
                             "note": substitution.note})
    table = pd.DataFrame(rows, columns=["accession", "row", "cluster", "site", "wild", "mutant", "effect", "note"])
    counts["kept"] = len(table)
    return table, counts


def covering_poles(substitutions: pd.DataFrame, proteins: pd.DataFrame, poles: pd.DataFrame) -> list[np.ndarray]:
    """For each substitution, the labeled poles whose term has an interval covering its site in its protein."""
    # poles: pole, term
    by_term = poles.groupby("term")["pole"].apply(lambda values: np.sort(values.to_numpy())).to_dict()
    covering = []
    for row, site in zip(substitutions["row"], substitutions["site"], strict=True):
        protein = proteins.iloc[int(row)]
        terms = set(int(token) for token in protein["local_term_ids"]) & set(by_term)
        hits = [by_term[term] for term in sorted(terms)
                if any(start <= site <= end for start, end in term_intervals(protein, term))]
        covering.append(np.unique(np.concatenate(hits)) if hits else np.zeros(0, dtype=np.int64))  # (c_i,)
    return covering  # (c_i,) for each of m substitutions


@torch.no_grad()
def site_poles(model: nn.Module, block: int, sequences: Sequence[str], sites: Sequence[int], device: torch.device, *,
               token_budget: int = TOKEN_BUDGET) -> Tensor:
    """Every pole's activation at one 0-based site of each sequence, read at `block`'s SwiGLU, in input order."""
    lengths = np.array([len(sequence) for sequence in sequences], dtype=np.int64)  # (m,)
    order = np.argsort(-lengths, kind="stable")  # (m,)
    read: list[Tensor] = []
    with BlockReader(model, [block], lambda states: read.append(_main_poles(states))) as reader:
        for batch in length_batches(lengths[order], token_budget):
            chosen = order[batch]  # (s,)
            input_ids, attention_mask, _ = encode_batch(model.tokenizer, [sequences[index] for index in chosen], device)
            at_site = column_mask([np.array([sites[index]]) for index in chosen], tuple(input_ids.shape)).to(device)  # (s, l)
            reader.run(input_ids, attention_mask, at_site)
    values = torch.cat(read)  # (m, p), in sorted order
    restored = torch.empty_like(values)  # (m, p)
    restored[torch.from_numpy(order)] = values
    return restored  # (m, p)


def _main_poles(states: BlockStates) -> Tensor:
    """The labeled units' layout of one block's poles, moved to the CPU."""
    return swiglu_poles(states.gate, states.up).main().cpu()  # (s, p)


def near_miss_table(substitutions: pd.DataFrame, covering: Sequence[np.ndarray], wild: Tensor, mutant: Tensor, *,
                    placebos: int = PLACEBOS, seed: int = SEED) -> pd.DataFrame:
    """Per substitution, the labeled poles that cover the site and fire there in the wild type, their mean relative
    drop at the site, and the mean relative drop of their placebos; a substitution no covering pole fires at is
    `silent`."""
    # covering: (c_i,) for each of m substitutions; wild, mutant: (m, p), every pole at each substitution's site
    if len(substitutions) != wild.shape[0] or wild.shape != mutant.shape or len(covering) != len(substitutions):
        raise ValueError("Every substitution needs its covering poles and its wild-type and mutant activations.")
    rows = []
    for index in range(len(substitutions)):
        before, after = wild[index].double(), mutant[index].double()  # (p,), (p,)
        labeled = [int(pole) for pole in covering[index] if float(before[pole]) > 0]
        entry = {"covering": len(covering[index]), "poles": len(labeled), "placebos": 0,
                 "labeled_drop": float("nan"), "placebo_drop": float("nan")}
        if not labeled:
            rows.append({**entry, "status": "silent"})
            continue
        chosen = sorted({placebo for pole in labeled
                         for placebo in matched_placebos(before, pole, covering[index].tolist(), count=placebos,
                                                         seed=seed + index)})
        if not chosen:
            rows.append({**entry, "status": "no_placebo"})
            continue
        relative = (before - after) / before.clamp(min=1e-30)  # (p,)
        rows.append({**entry, "status": "tested", "placebos": len(chosen),
                     "labeled_drop": float(relative[labeled].mean()), "placebo_drop": float(relative[chosen].mean())})
    return pd.concat([substitutions.reset_index(drop=True), pd.DataFrame(rows, index=range(len(rows)))], axis=1)


def stratified_auroc(drops: np.ndarray, loss: np.ndarray, strata: np.ndarray, weights: np.ndarray | None = None) -> float:
    """The weighted share of (loss, no-effect) pairs of one stratum in which the loss substitution's drop is larger,
    ties counting half, over every stratum holding both; NaN when none does."""
    # drops, loss, strata, weights: (m,)
    weights = np.ones(len(drops)) if weights is None else np.asarray(weights, dtype=np.float64)  # (m,)
    wins = pairs = 0.0
    for stratum in np.unique(strata):
        inside = strata == stratum  # (m,)
        positive, negative = inside & loss, inside & ~loss  # (m,), (m,)
        positive_weight, negative_weight = weights[positive].sum(), weights[negative].sum()
        if positive_weight == 0 or negative_weight == 0:
            continue
        values, inverse = np.unique(drops[negative], return_inverse=True)  # (u,), (n_negative,)
        mass = np.bincount(inverse, weights=weights[negative], minlength=len(values))  # (u,)
        below = np.concatenate(([0.0], np.cumsum(mass)))  # (u + 1,)
        lower = np.searchsorted(values, drops[positive], side="left")  # (n_positive,)
        upper = np.searchsorted(values, drops[positive], side="right")  # (n_positive,)
        credit = below[lower] + 0.5 * (below[upper] - below[lower])  # (n_positive,)
        wins += float((weights[positive] * credit).sum())
        pairs += float(positive_weight * negative_weight)
    return wins / pairs if pairs > 0 else float("nan")


def near_miss_summary(table: pd.DataFrame, *, draws: int = DRAWS, seed: int = SEED, level: float = 0.95) -> dict[str, object]:
    """Counts, and the stratified AUROC of loss against no-effect drops for labeled poles, for placebos and their
    difference, each with a percentile interval from resampling clusters."""
    tested = table[table["status"] == "tested"].reset_index(drop=True)
    strata = (tested["wild"] + ">" + tested["mutant"]).to_numpy()  # (m,)
    loss = (tested["effect"] == "loss").to_numpy()  # (m,)
    labeled, placebo = tested["labeled_drop"].to_numpy(), tested["placebo_drop"].to_numpy()  # (m,), (m,)
    both = [stratum for stratum in np.unique(strata) if loss[strata == stratum].any() and (~loss[strata == stratum]).any()]
    clusters, cluster_index = np.unique(tested["cluster"].to_numpy(), return_inverse=True)  # (k,), (m,)
    generator = np.random.default_rng(seed)
    draws_labeled, draws_placebo = [], []
    for _ in range(draws):
        counts = np.bincount(generator.integers(0, len(clusters), len(clusters)), minlength=len(clusters))  # (k,)
        weights = counts[cluster_index].astype(np.float64)  # (m,)
        draws_labeled.append(stratified_auroc(labeled, loss, strata, weights))
        draws_placebo.append(stratified_auroc(placebo, loss, strata, weights))
    tail = (1 - level) / 2 * 100

    def interval(estimate: float, values: np.ndarray) -> dict[str, float]:
        # values: (draws,)
        low, high = np.nanpercentile(values, [tail, 100 - tail])
        return {"estimate": estimate, "low": float(low), "high": float(high)}

    first, second = np.array(draws_labeled), np.array(draws_placebo)  # (draws,), (draws,)
    estimate_labeled, estimate_placebo = stratified_auroc(labeled, loss, strata), stratified_auroc(placebo, loss, strata)
    return {"statuses": {str(key): int(value) for key, value in table["status"].value_counts().items()},
            "tested": {"loss": int(loss.sum()), "none": int((~loss).sum())}, "clusters": int(len(clusters)),
            "strata_with_both": len(both),
            "labeled_auroc": interval(estimate_labeled, first), "placebo_auroc": interval(estimate_placebo, second),
            "difference": interval(estimate_labeled - estimate_placebo, first - second)}
