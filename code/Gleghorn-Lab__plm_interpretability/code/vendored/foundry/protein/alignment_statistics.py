"""Bit scores, E-values and probabilities of an exact alignment score, by each tool's own formulas.

| Label | Bit score | E-value | Source |
|---|---|---|---|
| `sw` | (lambda S - ln K) / ln 2 with lambda 0.267, K 0.041 (BLOSUM62, gaps 11/1) | Spouge's finite-size correction from the query and subject lengths, as BLASTp computes it by default; the classic effective search space x 2^-bits is kept for the report | BLAST+ `blast_stat.c`: the `blosum62_values` row for 11/1, `BLAST_SpougeStoE`, `BLAST_ComputeLengthAdjustment`, `BLAST_CalcEffLengths` |
| `foldseek` | the reverse-corrected raw score itself, which Foldseek prints in its `bits` column | (database residues x P)^0.32, P the upper tail of a Gumbel whose lambda and mu a small network predicts from the query's 3Di counts and length | Foldseek 10-941cd33: `EvalueNeuralNet.h`, `data/evalue_nn.kerasify`, `structureconvertalis.cpp` |
| `nw` | none | none | the label is a normalized global score with no null model |

`prob` is Foldseek's `CalcProbTP`: a two-gamma mixture fit of true and false positives' bit scores. The E-value
network's weights are `matrices/evalue_nn.kerasify`, Foldseek 10-941cd33's `data/evalue_nn.kerasify` unmodified
(GPL-3.0, as Foldseek).

Composition-based statistics as BLAST's mode 1 (Schaffer et al. 2001) are `composition_scale`, applied to the raw score
after the alignment; BLASTp's default, mode 2, refits the matrix per pair and realigns, which these formulas do not
reproduce (alignment_search's parity table). For SW, alignment_atlas's scorecard version 4 (its amendment A11) defines a
hit by the Spouge E-value after mode 1 (`sw_composition_threshold`), plus a guard: each query's scores against a fixed
shuffled guard set (`guard_set`) flag it (`sw_guard`), and a flagged query also needs its guard tail's threshold
(`tail_threshold`, or `tail_evalue` for its E-value). The raw score stays the label; the adjustment decides significance
only.

A null's chance-hit count at one E-value is judged by `chance_level`: its exact 95 percent Poisson interval against
half to twice the expectation, as alignment_atlas's ship condition S7 reads a decoy database.
"""

from __future__ import annotations

import math
import struct
import numpy as np
import torch

from dataclasses import dataclass
from pathlib import Path

from foundry.protein.gpu_alignment import RESIDUES, blosum62_table


FOLDSEEK_WEIGHTS = Path(__file__).resolve().parent / "matrices" / "evalue_nn.kerasify"


@dataclass(frozen=True)
class KarlinAltschul:
    """BLAST's gapped Karlin-Altschul parameters for one matrix and gap cost (a row of `blast_stat.c`)."""

    scale: float  # lambda
    k: float
    entropy: float  # H
    alpha: float
    beta: float

    def bits(self, raw: np.ndarray) -> np.ndarray:
        """Bit scores of raw scores: (lambda S - ln K) / ln 2, elementwise over any shape."""
        # raw: (...) any shape
        return (self.scale * raw.astype(np.float64) - math.log(self.k)) / math.log(2.0)  # (...) as given

    def length_adjustment(self, query_length: int, database_residues: int, database_sequences: int) -> int:
        """BLAST's length adjustment, `BLAST_ComputeLengthAdjustment` transcribed: the integer ell solving
        ell = alpha / lambda (ln K + ln((m - ell)(n - N ell))) + beta, bracketed and iterated at most 20 times."""
        m, n, count = float(query_length), float(database_residues), float(database_sequences)
        alpha_over_lambda = self.alpha / self.scale
        log_k = math.log(self.k)
        a, minus_b, c = count, m * count + n, n * m - max(m, n) / self.k
        if c < 0:
            return 0
        upper = 2 * c / (minus_b + math.sqrt(minus_b * minus_b - 4 * a * c))
        lower, following, converged = 0.0, 0.0, False
        for iteration in range(1, 21):
            current = following
            space = (m - current) * (n - count * current)
            proposed = alpha_over_lambda * (log_k + math.log(space)) + self.beta
            if proposed >= current:
                lower = current
                if proposed - lower <= 1.0:
                    converged = True
                    break
                if lower == upper:
                    break
            else:
                upper = current
            if lower <= proposed <= upper:
                following = proposed
            else:
                following = upper if iteration == 1 else (lower + upper) / 2
        adjustment = int(lower)
        if converged:
            ceiling = math.ceil(lower)
            if ceiling <= upper:
                space = (m - ceiling) * (n - count * ceiling)
                if alpha_over_lambda * (log_k + math.log(space)) + self.beta >= ceiling:
                    adjustment = int(ceiling)
        return adjustment

    def search_space(self, query_length: int, database_residues: int, database_sequences: int) -> float:
        """BLAST's effective search space, `BLAST_CalcEffLengths`: (m - ell) (n - N ell), each factor at least 1."""
        adjustment = self.length_adjustment(query_length, database_residues, database_sequences)
        database = max(database_residues - database_sequences * adjustment, 1)
        return float(max(query_length - adjustment, 1)) * float(database)

    def evalue(self, raw: np.ndarray, search_space: float) -> np.ndarray:
        """E-values of raw scores against one effective search space: m'n' K exp(-lambda S), elementwise."""
        # raw, score: (...) any shape
        return search_space * self.k * np.exp(-self.scale * raw.astype(np.float64))  # (...) as given


@dataclass(frozen=True)
class SpougeGumbel:
    """The finite-size correction BLASTp applies by default since BLAST+ 2.2.28 (`BLAST_SpougeStoE`, unless the
    `OLD_FSC` environment variable is set): each pair's E-value from its own query and subject lengths, scaled to the
    database by residues over subject length, with no length adjustment or effective search space.

    Fields are `Blast_GumbelBlkLoadFromTables`' inputs: the gapped row's columns 6, 9 and 10 (a, Alpha, Sigma), the
    ungapped row's columns 6 and 9, and G = gap existence + extension.
    """

    karlin: KarlinAltschul
    a: float
    alpha: float
    sigma: float
    ungapped_a: float
    ungapped_alpha: float
    gap: int

    def evalue(self, raw: np.ndarray, query_length: int | np.ndarray, subject_lengths: np.ndarray,
               database_residues: int) -> np.ndarray:
        """E-values of raw scores (k) for pairs of the given query lengths (one, or k) and subject lengths (k)."""
        # raw, subject_lengths: (k); query_length: () or (k)
        y = raw.astype(np.float64)  # (k)
        n = subject_lengths.astype(np.float64)  # (k)
        lam, k = self.karlin.scale, self.karlin.k
        b = 2.0 * self.gap * (self.ungapped_a - self.a)
        beta = 2.0 * self.gap * (self.ungapped_alpha - self.alpha)
        tau = 2.0 * self.gap * (self.ungapped_alpha - self.sigma)
        variance = np.maximum(2.0 * self.alpha / lam, self.alpha * y + beta)  # (k)
        root = np.sqrt(variance)  # (k)

        def side(length: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            # length: () or (k)
            shortened = length - (self.a * y + b)  # (k)
            f = shortened / root  # (k)
            tail = torch.special.erfc(torch.from_numpy(-f / math.sqrt(2.0))).numpy() / 2.0  # (k)
            return shortened * tail + root * np.exp(-0.5 * f * f) / math.sqrt(2.0 * math.pi), tail  # (k), (k)

        p1, tail_m = side(np.asarray(query_length, dtype=np.float64))
        p2, tail_n = side(n)
        crossing = np.maximum(2.0 * self.sigma / lam, self.sigma * y + tau)  # (k)
        area = p1 * p2 + crossing * tail_m * tail_n  # (k)
        return area * k * np.exp(-lam * y) * (database_residues / n)  # (k)

    def score_at(self, evalue: float, query_lengths: np.ndarray, subject_lengths: np.ndarray, database_residues: int,
                 steps: int = 48) -> np.ndarray:
        """The raw score at which each pair's E-value is `evalue`, by bisection, since the E-value falls as the score
        rises; a pair's exact score reaches it exactly when its E-value is at most `evalue`. Shape of the broadcast
        lengths."""
        # query_lengths: (...); subject_lengths: (...), any shapes that broadcast
        m, n = np.broadcast_arrays(np.asarray(query_lengths, dtype=np.float64), np.asarray(subject_lengths, dtype=np.float64))
        shape, m, n = m.shape, m.ravel(), n.ravel()  # (k), (k)
        low, high = np.zeros_like(n), np.full_like(n, 64.0)  # (k)
        while (grown := self.evalue(high, m, n, database_residues) > evalue).any():
            high = np.where(grown, high * 2, high)
        for _ in range(steps):  # to well under a raw-score unit
            middle = (low + high) / 2
            above = self.evalue(middle, m, n, database_residues) > evalue  # (k)
            low, high = np.where(above, middle, low), np.where(above, high, middle)
        return high.reshape(shape)  # (...), the broadcast shape


# BLOSUM62 with gap existence 11 and extension 1, BLASTp's default.
BLOSUM62_11_1 = KarlinAltschul(scale=0.267, k=0.041, entropy=0.14, alpha=1.9, beta=-30.0)
# `blosum62_values` in `blast_stat.c`: the 11/1 row {.., 1.9, -30, 0.669720, 42.602800, 43.636200} and the ungapped
# row {.., 0.7916, -3.2, 0.623757, 4.964660, 4.964660}.
BLOSUM62_11_1_SPOUGE = SpougeGumbel(BLOSUM62_11_1, a=1.9, alpha=42.6028, sigma=43.6362, ungapped_a=0.7916,
                                    ungapped_alpha=4.96466, gap=12)

# Robinson and Robinson's amino acid frequencies (PNAS 1991), per thousand: BLAST's background for its matrices' lambda
# and the standard composition of composition-based statistics (`Robinson_prob` in `blast_stat.c`).
ROBINSON = {"A": 78.05, "R": 51.29, "N": 44.87, "D": 53.64, "C": 19.25, "Q": 42.64, "E": 62.95, "G": 73.77, "H": 21.99,
            "I": 51.42, "L": 90.19, "K": 57.44, "M": 22.43, "F": 38.56, "P": 52.03, "S": 71.20, "T": 58.41, "W": 13.30,
            "Y": 32.16, "V": 64.41}


def residue_counts(sequences: list[str] | np.ndarray, alphabet: str) -> np.ndarray:
    """How often each letter of `alphabet` occurs in each sequence, other letters ignored: (n, a) int64."""
    # sequences: (n) strings
    lookup = np.full(256, len(alphabet), dtype=np.int64)  # (256), any other byte to the extra column
    lookup[np.frombuffer(alphabet.encode(), dtype=np.uint8)] = np.arange(len(alphabet))
    return np.stack([np.bincount(lookup[np.frombuffer(sequence.encode(), dtype=np.uint8)],
                                 minlength=len(alphabet) + 1)[:len(alphabet)] for sequence in sequences])  # (n, a)


def ungapped_lambda(matrix: np.ndarray, left: np.ndarray, right: np.ndarray, steps: int = 60) -> np.ndarray:
    """Karlin and Altschul's ungapped lambda of an integer substitution matrix (a, a) for each pair of residue
    frequencies, left (n, a) and right (n, a): the positive root of sum_ij left_i right_j exp(lambda s_ij) = 1, by
    bisection over the score's distribution. NaN where the expected score is not negative, which has no such root."""
    # matrix: (a, a); left, right: (n, a), rows summing to 1
    values = np.unique(matrix)  # (v)
    probability = np.stack([((left @ (matrix == value)) * right).sum(-1) for value in values], -1)  # (n, v)
    expected = probability @ values  # (n)
    rooted = (expected < 0) & (probability[:, values > 0].sum(-1) > 0)  # (n), a negative mean and a positive score

    def excess(lam: np.ndarray) -> np.ndarray:
        # lam: (n)
        return (probability * np.exp(lam[:, None] * values[None, :])).sum(-1) - 1.0  # (n)

    low, high = np.zeros(len(left)), np.full(len(left), 0.5)  # (n)
    while (short := rooted & (excess(high) <= 0)).any():
        high = np.where(short, high * 2, high)
    for _ in range(steps):
        middle = (low + high) / 2
        below = excess(middle) <= 0  # (n), still left of the root
        low, high = np.where(below, middle, low), np.where(below, high, middle)
    return np.where(rooted, high, np.nan)  # (n)


COMPOSITION_CLAMP = (0.5, 1.0)  # BLAST's bounds on the lambda ratio (`Blast_CompositionBasedStats`, blast_kappa.c)


def composition_scale(matrix: np.ndarray, alphabet: str, left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Composition-based statistics (Schaffer et al., NAR 2001, BLAST's mode 1): each pair's ungapped lambda for its
    own two compositions over the lambda for Robinson's background, so that the pair's raw score times this factor is
    judged by the standard statistics. Below 1 for pairs that share a bias, which score high by composition alone.

    Clamped as BLAST clamps it, to `COMPOSITION_CLAMP`: a score is only ever scaled down, and at most halved, a pair
    whose compositions give no lambda (a non-negative expected score) included, which takes the floor. Applied after
    the alignment, to the whole score with its gaps; BLAST rescales the matrix alone and realigns, so its scores differ
    slightly. matrix (a, a) in `alphabet` order; left, right: (n, a) residue counts or frequencies; returns (n)."""
    # matrix: (a, a); left, right: (n, a)
    background = np.array([ROBINSON[residue] for residue in alphabet])  # (a)
    background = background / background.sum()
    standard = ungapped_lambda(matrix, background[None], background[None])[0]
    left = left / left.sum(-1, keepdims=True)  # (n, a)
    right = right / right.sum(-1, keepdims=True)  # (n, a)
    ratio = np.nan_to_num(ungapped_lambda(matrix, left, right) / standard, nan=COMPOSITION_CLAMP[0])  # (n)
    return np.clip(ratio, *COMPOSITION_CLAMP)  # (n)


def tail_fit(top: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Each query's exponential tail from its top null scores against shuffled sequences, top (q, k), each row
    descending: the floor u (the lowest listed score), the count c of exceedances above it and their mean mean(y), each
    (q), fitted by maximum likelihood so that P(S >= u + y) = (c / sampled) exp(-y / mean(y)).

    A shuffled database holds no homolog, so the upper tail of a query's scores against it is the null's own. A local
    score's tail is asymptotically exponential, so the fit needs no family-free moments and follows a query whose
    composition makes chance scores run high. `tail_threshold` and `tail_evalue` read it in the two directions."""
    # top: (q, k), each row descending
    floor = top[:, -1:]  # (q, 1)
    above = top > floor  # (q, k)
    count = above.sum(axis=1)  # (q)
    if (count == 0).any():
        raise ValueError("A query's listed null scores are all equal; list more of them to fit its tail.")
    return floor[:, 0], count, np.where(above, top - floor, 0.0).sum(axis=1) / count  # (q) each


def tail_threshold(top: np.ndarray, sampled: int, database: int, evalue: float) -> np.ndarray:
    """Each query's score at E-value `evalue` against `database` sequences, from its top null scores against `sampled`
    shuffled sequences (`tail_fit`), extrapolated to where `database` x P = `evalue`: (q)."""
    # top: (q, k), each row descending
    floor, count, excess = tail_fit(top)  # (q) each
    return floor + excess * np.log(database * count / (sampled * evalue))  # (q)


def tail_evalue(score: np.ndarray, top: np.ndarray, sampled: int, database: int) -> np.ndarray:
    """The inverse of `tail_threshold`: each score's E-value against `database` sequences under its query's tail
    (`tail_fit` of top (q, k) against `sampled` shuffled sequences), database x (c / sampled) x exp(-(score - u) /
    mean(y)). score (q) or (q, ...), a row per query. Below the floor u the same exponential is extrapolated; there the
    E-value exceeds database x c / sampled, far above any cutoff."""
    # score: (q) or (q, ...); top: (q, k), each row descending
    floor, count, excess = tail_fit(top)  # (q) each
    shape = (-1,) + (1,) * (np.ndim(score) - 1)
    rate = database * count / sampled  # (q), the chance hits at the floor
    return rate.reshape(shape) * np.exp(-(score - floor.reshape(shape)) / excess.reshape(shape))  # (q) or (q, ...), score's shape


# The SW significance guard (alignment_atlas's amendment A11): each query is aligned to a fixed set of GUARD_SIZE
# shuffled sequences of the database; GUARD_SEED draws and permutes them, so a database's guard, and every E-value it
# touches, is the same at every deploy. The parameters were set on one shuffled database and checked on another.
GUARD_SIZE, GUARD_TOP, GUARD_FACTOR, GUARD_EVALUE, GUARD_SEED = 20_000, 20, 10.0, 1.0, 20261019
# The reversed guard (amendment A15): GUARD_SIZE of the database's rows drawn by its own seed, each reversed, which keeps
# the periodic segments and low-complexity runs a shuffle destroys. Its tail is fitted to a query's top
# REVERSED_GUARD_TOP scores and flags at REVERSED_GUARD_FACTOR; both were chosen on the 446k set's Q1 queries with this
# seed (the pair keeping the most real hits of those whose reversed-database counts at E 0.01 and 1e-3 stay at or under
# blastp's while the shuffled databases stay calibrated) and checked with another seed's guard (20261023).
REVERSED_GUARD_SEED, REVERSED_GUARD_TOP, REVERSED_GUARD_FACTOR = 20261022, 50, 30.0


def guard_flags(top: np.ndarray, adjusted: np.ndarray, database: int, size: int = GUARD_SIZE,
                factor: float = GUARD_FACTOR) -> np.ndarray:
    """The queries whose chance scores run heavier than their statistics say: each query's top scores against the
    guard set (`GUARD_TOP` of them for the shuffled guard), top (q, t), imply `factor` times the chance hits E-value
    `GUARD_EVALUE` allows at the median of its composition-adjusted thresholds at that E-value for those same guard
    subjects, adjusted (q, t). Such a query is judged by the stricter of the adjusted threshold and its guard tail's
    (`tail_threshold`) at every E-value; judged once, where the guard's sample sees the tail almost directly: (q) bool."""
    # top: (q, t); adjusted: (q, t)
    heavy = tail_threshold(top, size, database, GUARD_EVALUE * factor)  # (q)
    return heavy > np.nanmedian(np.where(np.isfinite(adjusted), adjusted, np.nan), axis=1)  # (q)


def chance_level(count: int, expected: float) -> dict[str, object]:
    """A chance-hit count at one E-value with its exact 95 percent Poisson interval; S7 passes the level when the
    interval overlaps [expected / 2, 2 x expected]."""
    from scipy.stats import chi2

    low = chi2.ppf(0.025, 2 * count) / 2 if count else 0.0
    high = chi2.ppf(0.975, 2 * count + 2) / 2
    return {"count": int(count), "expected": expected, "interval": [float(low), float(high)],
            "passes": bool(high >= expected / 2 and low <= 2 * expected)}


def guard_set(sequences: list[str] | np.ndarray, size: int = GUARD_SIZE, seed: int = GUARD_SEED,
              states: list[str] | np.ndarray | None = None,
              reverse: bool = False) -> tuple[np.ndarray, list[str], list[str] | None]:
    """A database's guard set: `size` of its rows drawn without replacement by `seed` and sorted, then each row's
    residues permuted by the same stream in row order, and its 3Di (`states`, when given) by the same permutation. The
    draw reads the database alone, so the set is the same whatever the queries and at every deploy. With `reverse` each
    drawn row is reversed instead (amendment A15's reversed guard), which keeps the periodic segments and low-complexity
    runs a shuffle destroys. Returns the rows (g), the shuffled or reversed sequences, and their states or None."""
    # sequences: (n) strings; states: (n) strings or None
    rng = np.random.default_rng(seed)
    rows = np.sort(rng.choice(len(sequences), size, replace=False))  # (g)
    shuffled: list[str] = []
    shuffled_states: list[str] | None = None if states is None else []
    for row in rows:
        order = np.arange(len(sequences[row]))[::-1] if reverse else rng.permutation(len(sequences[row]))  # (l)
        shuffled.append(np.frombuffer(sequences[row].encode(), dtype=np.uint8)[order].tobytes().decode())
        if shuffled_states is not None:
            if len(states[row]) != len(order):
                raise ValueError(f"Row {row}'s 3Di has {len(states[row])} states for {len(order)} residues.")
            shuffled_states.append(np.frombuffer(states[row].encode(), dtype=np.uint8)[order].tobytes().decode())
    return rows, shuffled, shuffled_states  # (g), g strings, g strings or None


def sw_composition_threshold(threshold: np.ndarray, query_counts: np.ndarray, subject_counts: np.ndarray) -> np.ndarray:
    """SW thresholds on the raw score (q, k) under composition-based statistics: a pair is significant when its raw score
    times its `composition_scale` (BLOSUM62 over `RESIDUES`, clamped as BLAST clamps it) reaches the standard threshold,
    so the threshold is divided by that scale, at most doubling it. query_counts (q, 20) and subject_counts (q, k, 20)
    are residue counts (`residue_counts`)."""
    # threshold: (q, k); query_counts: (q, 20); subject_counts: (q, k, 20)
    q, k = threshold.shape
    scale = composition_scale(blosum62_table(1)[:20, :20].numpy(), RESIDUES, np.repeat(query_counts, k, axis=0),
                              subject_counts.reshape(q * k, -1)).reshape(q, k)  # (q, k)
    return np.divide(threshold, scale, out=np.full((q, k), np.inf), where=scale > 0)  # (q, k)


def sw_guard(top: np.ndarray, top_lengths: np.ndarray, top_counts: np.ndarray, query_lengths: np.ndarray,
             query_counts: np.ndarray, residues: int, database: int, size: int = GUARD_SIZE,
             factor: float = GUARD_FACTOR) -> np.ndarray:
    """`guard_flags` for SW: each query's top exact scores against a guard set, top (q, t), descending, with those guard
    subjects' lengths (q, t) and residue counts (q, t, 20) (a shuffle or a reversal keeps both), against the Spouge
    thresholds at E-value `GUARD_EVALUE` after composition-based statistics (`sw_composition_threshold`) for the queries'
    lengths (q) and counts (q, 20), in a database of `residues` residues and `database` sequences: (q) bool."""
    # top: (q, t); top_lengths: (q, t); top_counts: (q, t, 20); query_lengths: (q); query_counts: (q, 20)
    spouge = BLOSUM62_11_1_SPOUGE.score_at(GUARD_EVALUE, query_lengths[:, None], top_lengths, residues)  # (q, t)
    return guard_flags(top, sw_composition_threshold(spouge, query_counts, top_counts), database, size, factor)  # (q)


class FoldseekEvalue:
    """Foldseek's E-value: a four-layer network maps the query's 3Di counts and length to an extreme value distribution.

    `EvalueNeuralNet::predictMuLambda` feeds the counts of each 3Di state (the matrix alphabet, X last) and the length,
    rescales the two outputs to lambda and mu, and `computeEvalueCorr` raises the database-wide E-value to 0.32.
    """

    def __init__(self, weights: Path, alphabet: str) -> None:
        self.alphabet = alphabet
        self.layers = read_kerasify_dense(weights)
        if self.layers[0][0].shape[0] != len(alphabet) + 1:
            raise ValueError(f"{weights} reads {self.layers[0][0].shape[0]} inputs; the 3Di alphabet gives {len(alphabet) + 1}.")
        self.lookup = {letter: index for index, letter in enumerate(alphabet)}

    def scale_location(self, three_di: str) -> tuple[float, float]:
        """Lambda and mu of the query's null, as `predictMuLambda` returns them (its first output is lambda)."""
        counts = np.zeros(len(self.alphabet) + 1, dtype=np.float32)  # (a + 1)
        for letter in three_di:
            counts[self.lookup.get(letter, len(self.alphabet) - 1)] += 1
        counts[-1] = len(three_di)
        scale, location = self.forward(counts)
        return float(scale), float(location)

    def scale_locations(self, states: list[str]) -> np.ndarray:
        """`scale_location` of many 3Di strings at once, the counts gathered by array lookup: (q, 2), lambda then mu."""
        lookup = np.full(256, len(self.alphabet) - 1, dtype=np.int64)  # (256), an unknown letter counts as X
        for letter, index in self.lookup.items():
            lookup[ord(letter)] = index
        counts = np.zeros((len(states), len(self.alphabet) + 1), dtype=np.float32)  # (q, a + 1)
        for row, three_di in enumerate(states):
            counts[row, :len(self.alphabet)] = np.bincount(lookup[np.frombuffer(three_di.encode(), dtype=np.uint8)],
                                                           minlength=len(self.alphabet))
            counts[row, -1] = len(three_di)
        return np.stack(self.forward(counts), axis=-1)  # (q, 2)

    def forward(self, counts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """The network on state counts and length, (a + 1) or (q, a + 1), rescaled to lambda and mu: each () or (q)."""
        # counts: (a + 1) or (q, a + 1)
        hidden = counts  # (..., a + 1)
        for weight, bias, relu in self.layers:
            hidden = hidden @ weight + bias  # (..., w)
            if relu:
                hidden = np.maximum(hidden, 0.0)  # (..., w)
        hidden = hidden.astype(np.float64)  # the rescale in double precision, as Foldseek's
        return hidden[..., 0] * 0.03260331312698818 + 0.17518475184751847, hidden[..., 1] * 0.4353169278257701 - 2.5569312493124934  # () or (q) each

    @staticmethod
    def evalue(score: np.ndarray, scale: float, location: float, database_residues: int) -> np.ndarray:
        """`computeEvalueCorr`: (residues x P(S >= score))^0.32 under the Gumbel (lambda, mu), elementwise."""
        # raw, score: (...) any shape
        h = scale * (score.astype(np.float64) - location)
        with np.errstate(over="ignore", divide="ignore"):  # np.where evaluates the branches it does not pick
            log_tail = np.where(h > 10, -h, np.where(h < -2.5, -np.exp(-np.exp(-h)), np.log1p(-np.exp(-np.exp(-h)))))
        return np.exp((log_tail + math.log(database_residues)) * 0.32)  # (...) as given

    @staticmethod
    def score_at(evalue: float, scale: np.ndarray, location: np.ndarray, database_residues: int) -> np.ndarray:
        """The score at which `evalue` falls, inverting `evalue`: (residues x P)^0.32 = evalue gives the tail P, and the
        Gumbel's upper tail P = 1 - exp(-exp(-lambda (s - mu))) gives s. Shape of the broadcast parameters."""
        # scale: (...); location: (...), any shapes that broadcast
        tail = evalue ** (1 / 0.32) / database_residues
        return np.asarray(location, dtype=np.float64) - np.log(-np.log1p(-tail)) / np.asarray(scale, dtype=np.float64)  # (...), the broadcast shape


def read_kerasify_dense(path: Path) -> list[tuple[np.ndarray, np.ndarray, bool]]:
    """The dense layers of a kerasify file as (weight (i, o), bias (o), ReLU after): only dense layers with linear or
    ReLU activations occur in Foldseek's E-value network, and anything else is refused."""
    weights_file = path.read_bytes()
    offset = 0

    def unsigned() -> int:
        nonlocal offset
        (value,) = struct.unpack_from("<I", weights_file, offset)
        offset += 4
        return value

    layers = []
    for _ in range(unsigned()):
        if unsigned() != 1:
            raise ValueError(f"{path} holds a layer other than dense.")
        rows, columns, width = unsigned(), unsigned(), unsigned()
        weight = np.frombuffer(weights_file, dtype="<f4", count=rows * columns, offset=offset).reshape(rows, columns)  # (i, o)
        offset += 4 * rows * columns
        bias = np.frombuffer(weights_file, dtype="<f4", count=width, offset=offset)  # (o)
        offset += 4 * width
        activation = unsigned()
        if activation not in (1, 2):
            raise ValueError(f"{path} uses activation {activation}; only linear (1) and ReLU (2) are read.")
        layers.append((weight.copy(), bias.copy(), activation == 2))
    if offset != len(weights_file):
        raise ValueError(f"{path} has {len(weights_file) - offset} trailing bytes.")
    return layers  # each (i, o), (o), ReLU flag


def foldseek_probability(bits: np.ndarray) -> np.ndarray:
    """Foldseek's `CalcProbTP`: P(true positive | bits) from two gamma mixtures, 0 at 10 bits or less, 1 at 100 or more."""
    # bits: (...) any shape
    x = np.clip(bits.astype(np.float64), 10.0 + 1e-9, 100.0)

    def gamma(shape: float, rate: float) -> np.ndarray:
        return np.exp(shape * math.log(rate) + (shape - 1) * np.log(x) - rate * x - math.lgamma(shape))  # (...) as given

    true = (0.8279 * gamma(1.8123, 1 / 46.0042) + 0.1721 * gamma(1.0057, 1 / 563.5014)) * 0.1023
    false = (0.34 * gamma(4.9259, 1 / 4.745) + 0.66 * gamma(9.4834, 1 / 1.3136)) * 0.8977
    probability = 1 / (1 + false / true)
    return np.where(bits <= 10, 0.0, np.where(bits >= 100, 1.0, probability))  # (...) as given
