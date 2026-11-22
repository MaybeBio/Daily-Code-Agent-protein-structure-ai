"""E9: does a dense probe on the pooled stream read its concept through the neurons the atlas labels with it?

An ESMC block adds its attention and feed-forward outputs to the stream, each divided by the block's residual scale s,
and the feed-forward output is the bias-free down projection of the units' products, sum_j z_j w_j. So the mean-pooled
stream after block b is the mean embedding, plus every earlier block's mean attention output, plus
sum_{i <= b} sum_j mean(z_ij) w_ij / s. A linear probe's score on the standardized pooled stream is v . mean(x) plus a
constant, with v the probe's weights divided by the training standard deviations, so neuron (i, j) contributes
mean(z_ij) (v . w_ij) / s to every protein's score, exactly. The probe separates a concept's test positives from its
negatives by delta, the difference of their mean scores; neuron (i, j)'s part of delta is (v . w_ij) / s times the
difference of its pooled product's means, and the rest belongs to attention and the embedding.

For a concept whose label names a Gene Ontology or InterPro accession, its labeled neurons are those with a pole whose
best global term in the atlas (E2's score tables, one per block) is the concept's term or a descendant of it, at a
best-term AUROC of at least 0.6, the atlas study's threshold. Their share of delta is set against null sets that replace
each labeled neuron by one of the 20 unlabeled neurons of its block with the closest mean absolute pooled product over
the task's training proteins (preregistration, `probe_attribution`).

Symbols: n proteins; d model width; f units; t targets; b the probe's block.
"""

from __future__ import annotations

import re
import numpy as np
import pandas as pd
import scipy.sparse as sp
import torch

from collections.abc import Callable, Mapping
from pathlib import Path
from torch import Tensor

from .concepts import ConceptProteins, ConceptTask, read_feature
from .sparse_probes import fit_dense_logistic, standardized, task_targets


MIN_AUROC = 0.60
NEIGHBOURS = 20
NULL_SETS = 100
SEED = 24895
ACCESSION = re.compile(r"\[(GO:\d{7})\]$|^(IPR\d{6})__")


def concept_accession(label: str) -> str | None:
    """The Gene Ontology or InterPro accession a concept label names, if any."""
    match = ACCESSION.search(label)
    return None if match is None else match.group(1) or match.group(2)


def concept_tokens(terms: pd.DataFrame, ancestors: sp.csr_matrix, accession: str) -> np.ndarray:
    """The vocabulary tokens of a term named by its accession and of every descendant of it; empty if absent."""
    # ancestors: (t, t), row i marks the ancestors of term i
    matches = terms.loc[terms["term_id"].str.split("::").str[-1] == accession, "token"].to_numpy(dtype=np.int64)  # (m,)
    if not len(matches):
        return matches  # (0,)
    descendants = np.flatnonzero(np.asarray(ancestors[:, matches].sum(axis=1)).ravel() > 0)  # (u,)
    return np.union1d(matches, descendants)  # (m + u,)


def labeled_neurons(scores: pd.DataFrame, tokens: np.ndarray, units: int, *, min_auroc: float = MIN_AUROC) -> np.ndarray:
    """The neurons of one block with a pole whose best global term is among `tokens` at the AUROC threshold."""
    # scores: one row per pole of the native layout (positive poles 0..f-1, negative f..2f-1); tokens: (m,)
    chosen = scores.loc[scores["best_term"].isin(tokens) & (scores["best_auroc"] >= min_auroc), "pole"].to_numpy()  # (c,)
    return np.unique(chosen % units)  # (u,)


def neuron_effects(z_means: Mapping[int, np.ndarray], readout: Mapping[int, np.ndarray], positives: np.ndarray, negatives: np.ndarray) -> dict[int, np.ndarray]:
    """Each neuron's part of the probe's separation, (v . w_ij) / s times its pooled product's positive-minus-negative
    mean, by block."""
    # z_means: (n, f) by block; readout: (f,) by block, (v . w_ij) / s; positives: (n_positive,); negatives: (n_negative,)
    effects = {}
    for block, pooled in z_means.items():
        gap = np.asarray(pooled[positives], dtype=np.float64).mean(axis=0) - np.asarray(pooled[negatives], dtype=np.float64).mean(axis=0)  # (f,)
        effects[block] = readout[block] * gap  # (f,)
    return effects  # (f,) by block


def matched_nulls(activity: Mapping[int, np.ndarray], labeled: Mapping[int, np.ndarray], *, sets: int = NULL_SETS,
                  neighbours: int = NEIGHBOURS, seed: int = SEED) -> list[dict[int, np.ndarray]]:
    """Null neuron sets: each labeled neuron replaced by one of the `neighbours` unlabeled neurons of its block whose
    activity is closest to its own, drawn with `seed`."""
    # activity: (f,) by block, the mean absolute pooled product over training proteins; labeled: (u,) by block
    generator = np.random.default_rng(seed)
    candidates = {}
    for block, neurons in labeled.items():
        free = np.setdiff1d(np.arange(len(activity[block])), neurons)  # (c,)
        nearest = np.argsort(np.abs(activity[block][free][None, :] - activity[block][neurons][:, None]), axis=1, kind="stable")  # (u, c)
        candidates[block] = free[nearest[:, :neighbours]]  # (u, neighbours)
    return [{block: options[np.arange(len(options)), generator.integers(0, options.shape[1], len(options))]
             for block, options in candidates.items()} for _ in range(sets)]  # (u,) by block, in each set


def run_e9(
    extraction: Path,
    proteins: ConceptProteins,
    tasks: Mapping[str, ConceptTask],
    block: int,
    scores: Mapping[int, pd.DataFrame],
    down: Mapping[int, Tensor],
    scale: float,
    terms: pd.DataFrame,
    ancestors: sp.csr_matrix,
    *,
    log: Callable[[str], None] = print,
) -> pd.DataFrame:
    """E9 for every mappable binary target of every task: the probe on block `block`'s mean stream, its test separation,
    the share carried by all neurons and by the labeled ones, and the null shares' mean and 95% interval."""
    # down: (d, f) by block, the down projections of blocks 0..block; scores: E2's per-pole table by block
    z_means = {index: read_feature(extraction, index, "z_mean") for index in range(block + 1)}  # (n, f) each
    stream = np.asarray(read_feature(extraction, block, "stream_mean"), dtype=np.float64)  # (n, d)
    units = next(iter(z_means.values())).shape[1]
    rows = []
    for name, task in tasks.items():
        targets = task_targets(task)
        if targets.kind != "binary":
            continue
        train_rows, test_rows = proteins.rows[name]["train"], proteins.rows[name]["test"]
        train, _ = standardized(stream[train_rows], stream[test_rows])  # (n_train, d)
        scale_by = stream[train_rows].std(axis=0)  # (d,), the standardization's scale
        scale_by = np.where(scale_by > 0, scale_by, 1.0)  # (d,)
        weights = fit_dense_logistic(train, torch.from_numpy(targets.values["train"]))  # (d + 1, t)
        activity = {index: np.abs(np.asarray(pooled[train_rows], dtype=np.float64)).mean(axis=0) for index, pooled in z_means.items()}  # (f,) each
        for column, label in enumerate(targets.names):
            accession = concept_accession(label)
            tokens = concept_tokens(terms, ancestors, accession) if accession else np.array([], dtype=np.int64)
            if not len(tokens):
                continue
            positive = targets.values["test"][:, column]  # (n_test,)
            v = weights[:-1, column].numpy() / scale_by  # (d,), the raw-space readout
            score = stream[test_rows] @ v  # (n_test,)
            delta = float(score[positive].mean() - score[~positive].mean())
            readout = {index: (v @ down[index].double().numpy()) / scale for index in z_means}  # (f,) each
            effects = neuron_effects(z_means, readout, test_rows[positive], test_rows[~positive])  # (f,) each
            labeled = {index: labeled_neurons(scores[index], tokens, units) for index in z_means}
            labeled = {index: neurons for index, neurons in labeled.items() if len(neurons)}
            share = sum(float(effects[index][neurons].sum()) for index, neurons in labeled.items()) / delta
            nulls = [sum(float(effects[index][neurons].sum()) for index, neurons in null.items()) / delta
                     for null in matched_nulls(activity, labeled)] if labeled else []
            rows.append({
                "task": name, "target": label, "accession": accession, "delta": delta,
                "neuron_share": sum(float(values.sum()) for values in effects.values()) / delta,
                "labeled_neurons": sum(len(neurons) for neurons in labeled.values()), "labeled_share": share if labeled else np.nan,
                "null_mean": float(np.mean(nulls)) if nulls else np.nan,
                "null_low": float(np.percentile(nulls, 2.5)) if nulls else np.nan,
                "null_high": float(np.percentile(nulls, 97.5)) if nulls else np.nan,
                "null_rank": float(np.mean(np.array(nulls) >= share)) if nulls else np.nan,
            })
        log(f"E9 {name}: {sum(row['task'] == name for row in rows)} mappable targets")
    return pd.DataFrame(rows)
