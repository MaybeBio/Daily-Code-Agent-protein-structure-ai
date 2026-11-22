"""E7d: steering a continuous concept along its fitted manifold against a straight line, read through ESMC's own
masked-token prediction (Wurgaft et al., Goodfire, 2026).

The concept, fixed before any steering result, is the hydropathy around a masked residue: the mean Kyte-Doolittle value
of the 18 residues within nine of it, the window of the intrinsic hydrophobic-stretch term without its center. The
model cannot see the masked residue, and its prediction for it should move toward hydrophobic residues as the
surroundings do, so the head reads the concept without a probe. Calibration proteins are masked every 20 residues from a
seeded offset, so no flank holds another mask, and their masked residues are binned at the deciles of the concept. Per
bin, the mean stream entering ESMC-600's block 26 at the masked residue is the activation centroid, and the mean
predicted distribution over the 20 amino acids and one class for every other token the behavior centroid. Natural
cubic splines through the centroids, against each bin's median concept value, give the activation manifold and, in
Hellinger coordinates, the behavior manifold, as the paper fits them.

Steering from bin a to bin b adds to a masked test residue's own stream an offset that grows from zero to the
difference of the two centroids: along the activation spline (manifold), along the straight line between the centroids
(linear), or along a seeded random direction for the straight line's length (random), at 11 evenly spaced steps. This
is the paper's interpolation between centroids applied as an offset, so the first step leaves the model unchanged and
the manifold and linear arms end at the same point. A path's energy is the mean over its steps of the Bhattacharyya
distance from the predicted distribution to the nearest point of the behavior manifold, the paper's measure of how far
steered outputs leave the model's natural ones.

Symbols: n residues; d model width; B bins; K steps; c the 21 output classes; q points along the behavior manifold.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from collections.abc import Callable, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from numpy.lib.stride_tricks import sliding_window_view
from scipy.interpolate import CubicSpline
from scipy.stats import pearsonr, spearmanr
from torch import Tensor, nn

from foundry.pilot import Pilot
from .ablation import column_mask
from .atlas import TOKEN_BUDGET, encode_batch, length_batches
from .causal import stream_reading, stream_shift, transformer_blocks
from .intrinsic import AMINO_ACIDS, KYTE_DOOLITTLE


BLOCK = 26  # the stream entering ESMC-600's block 26, the causal site
FLANK = 9
SPACING = 20
BINS = 10
STEPS = 11
RESIDUES_PER_BIN = 64
MAX_LENGTH = 510  # steering proteins, so a bin's 64 with their start and end tokens fit one batch of the token budget
CURVE_SAMPLES = 1000
SEGMENT_SAMPLES = 50
SEED = 24895
DRAWS = 1000
ARMS = ("manifold", "linear", "random")
HYDROPATHY = np.array([KYTE_DOOLITTLE[residue] for residue in AMINO_ACIDS])  # (20,)


def flank_hydropathy(sequence: str, flank: int = FLANK) -> np.ndarray:
    """Each residue's surroundings: the mean Kyte-Doolittle value of the residues within `flank` of it, itself left
    out; NaN where the window leaves the protein or holds a residue outside the twenty."""
    values = np.array([KYTE_DOOLITTLE.get(residue, np.nan) for residue in sequence], dtype=np.float64)  # (l,)
    width = 2 * flank + 1
    surroundings = np.full(len(sequence), np.nan)  # (l,)
    if len(sequence) >= width:
        windows = sliding_window_view(values, width)  # (l - 2 flank, width)
        surroundings[flank:len(sequence) - flank] = (windows.sum(axis=1) - windows[:, flank]) / (width - 1)
    return surroundings  # (l,)


def fit_positions(lengths: Sequence[int], *, flank: int = FLANK, spacing: int = SPACING, seed: int = SEED) -> list[np.ndarray]:
    """Per protein, the residues masked to fit the manifolds: every `spacing`-th from a seeded offset, each with its
    full flank inside the protein, so no flank holds another mask."""
    generator = np.random.default_rng(seed)
    return [np.arange(flank + int(generator.integers(0, spacing)), length - flank, spacing) for length in lengths]  # (s_protein,) each


def amino_acid_ids(tokenizer: object) -> list[int]:
    """The tokenizer's ids of the twenty amino acids, in `AMINO_ACIDS` order."""
    ids = list(tokenizer.convert_tokens_to_ids(list(AMINO_ACIDS)))
    if len(set(ids)) != len(AMINO_ACIDS) or tokenizer.unk_token_id in ids:
        raise ValueError("The tokenizer does not give each amino acid its own token.")
    return ids


def output_classes(logits: Tensor, ids: Sequence[int]) -> Tensor:
    """The predicted distribution over the twenty amino acids and one class for every other token."""
    # logits: (s, v)
    probabilities = torch.softmax(logits.float(), dim=-1)  # (s, v)
    amino = probabilities[:, list(ids)]  # (s, 20)
    return torch.cat((amino, (1 - amino.sum(dim=1, keepdim=True)).clamp(min=0)), dim=1)  # (s, c)


@torch.no_grad()
def masked_pass(model: nn.Module, sequences: Sequence[str], positions: Sequence[np.ndarray], ids: Sequence[int],
                device: torch.device, *, block: int = BLOCK, shifts: Tensor | None = None, read_stream: bool = False,
                token_budget: int = TOKEN_BUDGET) -> tuple[Tensor | None, Tensor]:
    """With each protein's listed residues (0-based, ascending) masked: the stream entering `block` at them when
    `read_stream`, and the predicted distribution there; `shifts`, one row per listed residue in protein order, is added
    to that stream first."""
    # positions: (s_protein,) per protein; shifts: (s, d)
    if any(np.any(np.diff(chosen) <= 0) for chosen in positions):
        raise ValueError("Each protein's masked residues must be distinct and ascending.")
    counts = np.array([len(chosen) for chosen in positions], dtype=np.int64)  # (n_proteins,)
    first = np.concatenate(([0], np.cumsum(counts)))  # (n_proteins + 1,)
    total = int(first[-1])
    if shifts is not None and shifts.shape[0] != total:
        raise ValueError(f"{shifts.shape[0]} shifts for {total} masked residues.")
    lengths = np.array([len(sequence) for sequence in sequences], dtype=np.int64)  # (n_proteins,)
    order = np.argsort(-lengths, kind="stable")  # (n_proteins,)
    width = transformer_width(model)
    streams = torch.empty((total, width)) if read_stream else None  # (s, d)
    distributions = torch.empty((total, len(ids) + 1))  # (s, c)
    kept: list[Tensor] = []
    for batch in length_batches(lengths[order], token_budget):
        chosen = order[batch]  # (b,)
        rows = torch.from_numpy(np.concatenate([np.arange(first[protein], first[protein + 1]) for protein in chosen]))  # (s_b,)
        if len(rows) == 0:
            continue
        input_ids, attention_mask, _ = encode_batch(model.tokenizer, [sequences[protein] for protein in chosen], device)
        mask = column_mask([positions[protein] for protein in chosen], tuple(input_ids.shape)).to(device)  # (b, l)
        masked = input_ids.masked_fill(mask, model.tokenizer.mask_token_id)  # (b, l)
        with (stream_shift(model, block, mask, shifts[rows]) if shifts is not None else nullcontext(),
              stream_reading(model, block, mask, kept) if read_stream else nullcontext()):
            logits = model(input_ids=masked, attention_mask=attention_mask).logits  # (b, l, v)
        distributions[rows] = output_classes(logits[mask], ids).cpu()
        if streams is not None:
            streams[rows] = kept.pop()
    return streams, distributions  # (s, d) or None, (s, c)


def transformer_width(model: nn.Module) -> int:
    """The width of the residual stream the blocks read."""
    return int(transformer_blocks(model)[0].ffn[0].normalized_shape[0])


@dataclass(frozen=True)
class ConceptManifolds:
    edges: np.ndarray  # (B + 1,), bin edges at the calibration deciles of the concept
    knots: np.ndarray  # (B,), each bin's median concept value
    centroids: np.ndarray  # (B, d), the mean stream per bin
    behavior: np.ndarray  # (B, c), the mean predicted distribution per bin

    def activation(self, values: np.ndarray) -> np.ndarray:
        """Points of the activation manifold at concept values."""
        # values: (n,)
        return CubicSpline(self.knots, self.centroids, axis=0, bc_type="natural")(values)  # (n, d)

    def behavior_at(self, values: np.ndarray) -> np.ndarray:
        """Points of the behavior manifold at concept values, in Hellinger coordinates kept on the unit sphere."""
        # values: (n,)
        points = np.clip(CubicSpline(self.knots, np.sqrt(self.behavior), axis=0, bc_type="natural")(values), 0, None)  # (n, c)
        return points / np.linalg.norm(points, axis=1, keepdims=True)  # (n, c)

    def bins(self, values: np.ndarray) -> np.ndarray:
        """Each value's bin; values past the calibration range join the end bins, NaN gets -1."""
        # values: (n,)
        index = np.clip(np.searchsorted(self.edges, values, side="right") - 1, 0, len(self.knots) - 1)  # (n,)
        return np.where(np.isfinite(values), index, -1)  # (n,)


def fit_manifolds(values: np.ndarray, states: np.ndarray, distributions: np.ndarray, *, bins: int = BINS) -> ConceptManifolds:
    """Bin the calibration residues at the concept's quantiles; per bin the median concept value, the mean stream and
    the mean predicted distribution."""
    # values: (n,); states: (n, d); distributions: (n, c)
    if not np.all(np.isfinite(values)):
        raise ValueError("Every calibration residue needs a concept value.")
    edges = np.quantile(values, np.linspace(0, 1, bins + 1))  # (B + 1,)
    index = np.clip(np.searchsorted(edges, values, side="right") - 1, 0, bins - 1)  # (n,)
    if np.bincount(index, minlength=bins).min() == 0:
        raise ValueError("A bin of the concept holds no calibration residue.")
    knots = np.array([np.median(values[index == member]) for member in range(bins)])  # (B,)
    if not np.all(np.diff(knots) > 0):
        raise ValueError("The bins' median concept values do not increase.")
    centroids = np.stack([states[index == member].mean(axis=0) for member in range(bins)])  # (B, d)
    behavior = np.stack([distributions[index == member].mean(axis=0) for member in range(bins)])  # (B, c)
    return ConceptManifolds(edges, knots, centroids, behavior)


def _cumulative(points: np.ndarray) -> np.ndarray:
    """Length along consecutive points."""
    # points: (g, w)
    return np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))))  # (g,)


def isometry(manifolds: ConceptManifolds, *, samples: int = SEGMENT_SAMPLES) -> dict[str, float]:
    """The paper's isometry check over every pair of centroids: Pearson's r of geodesic distances along the activation
    manifold, and of straight-line distances between activation centroids, with geodesic Hellinger distances along the
    behavior manifold."""
    knots = manifolds.knots  # (B,)
    grid = np.concatenate([np.linspace(left, right, samples, endpoint=False) for left, right in zip(knots[:-1], knots[1:], strict=True)]
                          + [knots[-1:]])  # (g,)
    at_knot = np.arange(len(knots)) * samples  # (B,)
    activation = _cumulative(manifolds.activation(grid))[at_knot]  # (B,)
    behavior = _cumulative(manifolds.behavior_at(grid))[at_knot] / np.sqrt(2)  # (B,), Hellinger distance
    first, second = np.triu_indices(len(knots), k=1)  # (pairs,), (pairs,)
    straight = np.linalg.norm(manifolds.centroids[first] - manifolds.centroids[second], axis=1)  # (pairs,)
    geodesic_behavior = np.abs(behavior[first] - behavior[second])  # (pairs,)
    return {"geodesic_r": float(pearsonr(np.abs(activation[first] - activation[second]), geodesic_behavior)[0]),
            "straight_r": float(pearsonr(straight, geodesic_behavior)[0]), "pairs": int(len(first))}


def arm_offsets(manifolds: ConceptManifolds, start: int, end: int, *, steps: int = STEPS, seed: int = SEED) -> dict[str, np.ndarray]:
    """Each arm's offset from the start centroid at each step from bin `start` to bin `end`."""
    t = np.linspace(0.0, 1.0, steps)  # (K,)
    begin, finish = manifolds.centroids[start], manifolds.centroids[end]  # (d,), (d,)
    along = manifolds.activation(manifolds.knots[start] + t * (manifolds.knots[end] - manifolds.knots[start])) - begin  # (K, d)
    direction = np.random.default_rng([seed, start, end]).standard_normal(begin.shape[0])  # (d,)
    direction /= np.linalg.norm(direction)
    return {"manifold": along, "linear": t[:, None] * (finish - begin)[None, :],
            "random": t[:, None] * np.linalg.norm(finish - begin) * direction[None, :]}  # (K, d) each


def manifold_distance(distributions: np.ndarray, curve: np.ndarray) -> np.ndarray:
    """The Bhattacharyya distance from each distribution to the nearest point of the behavior manifold."""
    # distributions: (n, c); curve: (q, c), Hellinger coordinates
    affinity = np.sqrt(np.clip(distributions, 0, None)) @ curve.T  # (n, q)
    return -np.log(np.clip(affinity.max(axis=1), 1e-12, 1.0))  # (n,)


def expected_hydropathy(distributions: np.ndarray) -> np.ndarray:
    """The Kyte-Doolittle value of the predicted residue, over the amino-acid classes."""
    # distributions: (n, c)
    amino = distributions[:, :len(AMINO_ACIDS)]  # (n, 20)
    return amino @ HYDROPATHY / amino.sum(axis=1)  # (n,)


def steering_residues(sequences: Sequence[str], manifolds: ConceptManifolds, *, per_bin: int = RESIDUES_PER_BIN,
                      seed: int = SEED) -> list[list[tuple[int, int]]]:
    """Per bin, up to `per_bin` (protein, residue) pairs from distinct proteins whose surroundings fall in the bin,
    drawn with `seed`."""
    generator = np.random.default_rng(seed)
    bins = [manifolds.bins(flank_hydropathy(sequence)) for sequence in sequences]  # (l,) each
    chosen = []
    for member in range(len(manifolds.knots)):
        picks: list[tuple[int, int]] = []
        for protein in generator.permutation(len(sequences)):
            eligible = np.flatnonzero(bins[protein] == member)  # (e,)
            if len(eligible):
                picks.append((int(protein), int(generator.choice(eligible))))
            if len(picks) == per_bin:
                break
        chosen.append(picks)
    return chosen


@dataclass(frozen=True)
class SteeringRun:
    pairs: pd.DataFrame  # start, end, arm, residues, energy, tracking, end_hydropathy, target_hydropathy
    energies: dict[tuple[int, int, str], np.ndarray]  # each residue's path energy, (n_start,)
    natural: dict[int, np.ndarray]  # each start bin's residues' energy without steering, (n_start,)
    manifolds: ConceptManifolds
    isometry: dict[str, float]


def run_e7d(model: nn.Module, calibration: Sequence[str], test: Sequence[str], device: torch.device, *,
            block: int = BLOCK, bins: int = BINS, steps: int = STEPS, per_bin: int = RESIDUES_PER_BIN,
            pilot: Pilot | None = None, log: Callable[[str], None] = print) -> SteeringRun:
    """E7d: the manifolds from calibration proteins, then every ordered pair of bins steered on test proteins of at
    most `MAX_LENGTH` residues by each arm."""
    ids = amino_acid_ids(model.tokenizer)
    positions = fit_positions([len(sequence) for sequence in calibration])
    fitted = [index for index, chosen in enumerate(positions) if len(chosen)]
    states, distributions = masked_pass(model, [calibration[index] for index in fitted], [positions[index] for index in fitted],
                                        ids, device, block=block, read_stream=True)  # (s, d), (s, c)
    values = np.concatenate([flank_hydropathy(calibration[index])[positions[index]] for index in fitted])  # (s,)
    finite = np.isfinite(values)  # (s,)
    manifolds = fit_manifolds(values[finite], states.numpy()[finite], distributions.numpy()[finite], bins=bins)
    curve = manifolds.behavior_at(np.linspace(manifolds.knots[0], manifolds.knots[-1], CURVE_SAMPLES))  # (q, c)
    shape = isometry(manifolds)
    log(f"E7d manifolds from {int(finite.sum())} calibration residues; isometry r {shape['geodesic_r']:.3f} along the "
        f"manifold, {shape['straight_r']:.3f} straight")
    short = [sequence for sequence in test if len(sequence) <= MAX_LENGTH]
    residues = steering_residues(short, manifolds, per_bin=per_bin)
    rows, energies, natural, unsteered = [], {}, {}, {}
    plan = steering_plan(bins)
    last = {start: end for start, end in plan}  # the plan is start-major, so each start's last end
    for start, end in pilot.watch(plan) if pilot is not None else plan:
        picks = residues[start]
        sequences = [short[protein] for protein, _ in picks]
        sites = [np.array([residue]) for _, residue in picks]
        if start not in natural:
            unsteered[start] = masked_pass(model, sequences, sites, ids, device, block=block)[1].numpy()  # (n, c)
            natural[start] = manifold_distance(unsteered[start], curve)  # (n,)
        target = float(expected_hydropathy(manifolds.behavior[end:end + 1])[0])
        for arm, offsets in arm_offsets(manifolds, start, end, steps=steps).items():
            distances, hydropathy = [natural[start]], [expected_hydropathy(unsteered[start])]  # step 0 leaves the model as it is
            for offset in offsets[1:]:  # (d,)
                shift = torch.as_tensor(offset, dtype=torch.float32).expand(len(picks), -1)  # (n, d)
                steered = masked_pass(model, sequences, sites, ids, device, block=block, shifts=shift)[1].numpy()  # (n, c)
                distances.append(manifold_distance(steered, curve))
                hydropathy.append(expected_hydropathy(steered))
            energies[start, end, arm] = np.mean(distances, axis=0)  # (n,)
            track = np.mean(hydropathy, axis=1)  # (K,)
            rows.append({"start": start, "end": end, "arm": arm, "residues": len(picks),
                         "energy": float(energies[start, end, arm].mean()),
                         "tracking": float(spearmanr(np.arange(len(track)), track)[0] * np.sign(end - start)),
                         "end_hydropathy": float(track[-1]), "target_hydropathy": target})
        if end == last[start]:
            log(f"E7d start bin {start}: {len(picks)} residues steered to every other bin")
    return SteeringRun(pd.DataFrame(rows), energies, natural, manifolds, shape)


def steering_plan(bins: int = BINS) -> list[tuple[int, int]]:
    """Every ordered pair of distinct bins, start-major: the steps a pilot times."""
    return [(start, end) for start in range(bins) for end in range(bins) if end != start]


def steering_summary(run: SteeringRun, *, draws: int = DRAWS, seed: int = SEED, level: float = 0.95) -> dict[str, object]:
    """Each arm's median path energy over bin pairs, and the median paired difference of the linear and random arms
    from the manifold arm, with a percentile interval from resampling each start bin's residues."""
    pairs = sorted({(start, end) for start, end, _ in run.energies})
    sizes = {start: len(values) for start, values in run.natural.items()}

    def medians(index: dict[int, np.ndarray]) -> dict[str, float]:
        # index: (n_start,) residues of each start bin
        energy = {arm: np.array([run.energies[start, end, arm][index[start]].mean() for start, end in pairs])
                  for arm in ARMS}  # (pairs,) each
        return {**{arm: float(np.median(energy[arm])) for arm in ARMS},
                "linear_minus_manifold": float(np.median(energy["linear"] - energy["manifold"])),
                "random_minus_manifold": float(np.median(energy["random"] - energy["manifold"]))}

    generator = np.random.default_rng(seed)
    estimate = medians({start: np.arange(size) for start, size in sizes.items()})
    sampled = [medians({start: generator.integers(0, size, size) for start, size in sizes.items()}) for _ in range(draws)]
    tail = (1 - level) / 2 * 100

    def interval(key: str) -> dict[str, float]:
        low, high = np.percentile([draw[key] for draw in sampled], [tail, 100 - tail])
        return {"estimate": estimate[key], "low": float(low), "high": float(high)}

    return {"isometry": run.isometry, "knots": run.manifolds.knots.tolist(), "pairs": len(pairs),
            "residues": {str(start): size for start, size in sizes.items()},
            "natural_energy": float(np.median(np.concatenate(list(run.natural.values())))),
            "energy": {arm: interval(arm) for arm in ARMS},
            "linear_minus_manifold": interval("linear_minus_manifold"),
            "random_minus_manifold": interval("random_minus_manifold"),
            "tracking": run.pairs.groupby("arm")["tracking"].median().to_dict()}
