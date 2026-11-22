"""Exemplar units for Figure 4, drawn by a rule fixed before any residue track is seen, and their residue tracks.

The pool is H6's: block 26's native poles whose dominant local term is also one of their selected labels and a curated
term (`ablation.labeled_poles`). `PER_KIND` poles are drawn from each local concept kind of `KINDS`, uniformly with
`SEED`, so no exemplar is chosen by looking at it. Each exemplar's test carriers of its term then give the `TOP` with
the highest maximum of the pole, one a cluster, and one more drawn with the seed from the remaining carriers, so a
typical carrier stands beside the strongest. A track holds, per residue, the four poles of the exemplar's neuron (both
main poles and both leaks), whether the residue lies in the term, and the pole's rate-matched threshold.

Symbols: e exemplars; n proteins; p poles; f units; l residues of one protein; c carriers.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from collections.abc import Mapping, Sequence
from torch import nn

from .ablation import term_intervals
from .atlas import encode_batch
from .capture import BlockReader, BlockStates
from .poles import swiglu_poles


KINDS = ("site", "structure", "domain")  # the local concept kinds of the preregistration's H4 kinds, composition aside
PER_KIND = 2
TOP = 3
SEED = 24895
POLE_NAMES = ("positive", "negative", "leak_positive", "leak_negative")


def draw_exemplars(labeled: pd.DataFrame, kinds: Mapping[int, str], *, per_kind: int = PER_KIND,
                   seed: int = SEED) -> pd.DataFrame:
    """`per_kind` labeled poles of each kind in `KINDS`, drawn uniformly without replacement by one generator in kind
    order; a kind with fewer candidates gives all it has."""
    # labeled: pole, term (`ablation.labeled_poles`); kinds: term token -> concept kind
    generator = np.random.default_rng(seed)
    drawn = []
    for kind in KINDS:
        candidates = labeled[labeled["term"].map(kinds) == kind].sort_values("pole", kind="stable")
        count = min(per_kind, len(candidates))
        rows = np.sort(generator.choice(len(candidates), size=count, replace=False)) if count else np.zeros(0, dtype=np.int64)
        drawn.append(candidates.iloc[rows].assign(kind=kind))
    table = pd.concat(drawn, ignore_index=True)
    return table.assign(exemplar=np.arange(len(table)))[["exemplar", "kind", "pole", "term"]]


def exemplar_carriers(exemplars: pd.DataFrame, proteins: pd.DataFrame, maxima: np.ndarray, *, top: int = TOP,
                      seed: int = SEED) -> pd.DataFrame:
    """Per exemplar, the test carriers of its term with the `top` highest maxima of its pole, one a cluster, then one
    more drawn from the remaining carriers with `seed` plus the exemplar's index; `row` indexes `proteins`."""
    # proteins: the pass's proteins in pass order (cluster, split, local_term_ids); maxima: (n, p) in the same order
    test = np.flatnonzero(proteins["split"].to_numpy() == "test")  # (n_test,)
    tokens = [frozenset(int(token) for token in proteins["local_term_ids"].iloc[row]) for row in test]
    clusters = proteins["cluster"].to_numpy()  # (n,)
    rows = []
    for exemplar in exemplars.itertuples():
        carriers = np.array([row for row, held in zip(test, tokens, strict=True) if int(exemplar.term) in held],
                            dtype=np.int64)  # (c,)
        if carriers.size == 0:
            continue
        values = np.asarray(maxima[carriers, int(exemplar.pole)], dtype=np.float64)  # (c,)
        ranked = carriers[np.argsort(-values, kind="stable")]  # (c,)
        chosen: list[int] = []
        seen: set[object] = set()
        for row in ranked:
            if clusters[row] not in seen:
                chosen.append(int(row))
                seen.add(clusters[row])
            if len(chosen) == top:
                break
        roles = [f"top{rank + 1}" for rank in range(len(chosen))]
        rest = np.setdiff1d(carriers, chosen)  # (c_rest,)
        if rest.size:
            chosen.append(int(rest[np.random.default_rng(seed + int(exemplar.exemplar)).integers(rest.size)]))
            roles.append("drawn")
        rows.extend({"exemplar": int(exemplar.exemplar), "row": row, "role": role,
                     "maximum": float(maxima[row, int(exemplar.pole)])} for row, role in zip(chosen, roles, strict=True))
    return pd.DataFrame(rows, columns=["exemplar", "row", "role", "maximum"])


def residue_tracks(model: nn.Module, block: int, sequences: Sequence[str], units: Sequence[int],
                   device: torch.device) -> list[np.ndarray]:
    """The four poles of one unit at every residue of each sequence, read at `block` one sequence a pass; `units`
    names each sequence's unit."""
    if len(sequences) != len(units):
        raise ValueError("Every sequence needs its unit.")
    tracks: list[np.ndarray] = []
    for sequence, unit in zip(sequences, units, strict=True):
        def keep(states: BlockStates, unit: int = int(unit)) -> None:
            poles = swiglu_poles(states.gate, states.up)  # (l, f) each
            tracks.append(torch.stack([getattr(poles, name)[:, unit] for name in POLE_NAMES], dim=1).float().cpu().numpy())

        input_ids, attention_mask, residues = encode_batch(model.tokenizer, [sequence], device)
        with BlockReader(model, [block], keep) as reader:
            reader.run(input_ids, attention_mask, residues)
    return tracks  # (l, 4) each


def track_table(pairs: pd.DataFrame, proteins: pd.DataFrame, tracks: Sequence[np.ndarray],
                thresholds: np.ndarray, units: int) -> pd.DataFrame:
    """One row per residue of each chosen carrier: its exemplar and role, which of the neuron's main poles is the
    exemplar's (`own`), the position (1-based) and residue, the neuron's four poles, whether the residue lies in the
    exemplar's term, and the pole's threshold."""
    # pairs: exemplar_carriers' rows joined to their exemplar (kind, pole, term); proteins: in pass order
    # tracks: (l, 4) per pair; thresholds: (p,) the basis's rate-matched thresholds, positive poles first
    frames = []
    for pair, track in zip(pairs.itertuples(), tracks, strict=True):
        protein = proteins.iloc[int(pair.row)]
        sequence = protein["sequence"]
        if track.shape != (len(sequence), len(POLE_NAMES)):
            raise ValueError(f"The track of {protein['accession']} does not cover its {len(sequence)} residues.")
        inside = np.zeros(len(sequence), dtype=bool)  # (l,)
        for start, end in term_intervals(protein, int(pair.term)):
            inside[start:end + 1] = True
        frames.append(pd.DataFrame({
            "exemplar": int(pair.exemplar), "kind": pair.kind, "pole": int(pair.pole), "term": int(pair.term),
            "own": POLE_NAMES[int(pair.pole) // units], "accession": protein["accession"], "role": pair.role,
            "position": np.arange(1, len(sequence) + 1),
            "residue": list(sequence), **{name: track[:, column] for column, name in enumerate(POLE_NAMES)},
            "in_term": inside, "threshold": float(thresholds[int(pair.pole)]),
        }))
    return pd.concat(frames, ignore_index=True)
