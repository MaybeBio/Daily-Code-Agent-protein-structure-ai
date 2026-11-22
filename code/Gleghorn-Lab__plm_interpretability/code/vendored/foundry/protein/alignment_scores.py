"""The three alignment scores alignment_atlas's vectors reproduce and alignment_search reports, computed exactly on the GPU
through `foundry.protein.gpu_alignment`.

| Label | Problem | Gaps | Value |
|---|---|---|---|
| `sw` | local, BLOSUM62 | BLAST's existence 11, extension 1 (first residue 12) | the raw score BLASTp's bitscore is a linear map of |
| `nw` | global, BLOSUM62 doubled (Biopython -10 / -0.5, the NW transformer's label) | first residue 20, then 1 | NW(a, b) / sqrt(NW(a, a) NW(b, b)) |
| `foldseek` | local, 3Di x 2.1 plus AA x 1.4 in MMseqs integer units (Foldseek's 3Di+AA default) | Foldseek's 10 / 1 | SW(a, b) - SW(reversed a, b), Foldseek's reported raw score with its composition-bias correction off |
| `foldseek_cbc` | the same, plus Foldseek's composition-bias correction on a's positions in both scans | Foldseek's 10 / 1 | Foldseek's default reported raw score |

Foldseek subtracts the score of the reversed query to suppress compositional false positives. Reversing both
sequences preserves a local score and the tables are symmetric, so SW(reversed a, b) = SW(reversed b, a) and
`foldseek` is symmetric. Composition-bias correction depends on which sequence is the query, so `foldseek_cbc` is not:
a is the query, and its terms (`foundry.protein.composition_bias`) come with each pair. Its E-value network passes the
reversed-database null that the uncorrected score fails (alignment_atlas's amendment A13). The integer tables are
rebuilt exactly as MMseqs's `SubstitutionMatrix` builds them from the `.out` files in `matrices/`, Foldseek
10-941cd33's own (`data/mat3di.out`, `lib/mmseqs/data/blosum62.out`).
"""

from __future__ import annotations

import math
import numpy as np
import torch

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from foundry.protein.gpu_alignment import (TOKEN_IDS, TOKENS, align_profile_reference, align_profile_triton,
                                           align_reference, align_triton, blosum62_table, reverse_within_length)


MATRICES = Path(__file__).resolve().parent / "matrices"
ANY_BACK = 1e-5  # MMseqs's background of X, BaseMatrix::ANY_BACK
LabelName = Literal["sw", "nw", "foldseek", "foldseek_cbc"]
LABELS: tuple[LabelName, ...] = ("sw", "nw", "foldseek")
FOLDSEEK_GAP_OPEN = 10  # the first gap residue's cost, which the parity check against the foldseek binary confirms
FOLDSEEK_GAP_EXTEND = 1
MMSEQS_ALIASES = {"B": "D", "Z": "E", "J": "L", "U": "X", "O": "X"}  # `SubstitutionMatrix::setupLetterMapping`'s reading of the letters past its alphabet
SIGNIFICANT = 1e-3  # the E-value under which an exact hit counts as a homolog
EULER = 0.5772156649015329


@dataclass(frozen=True)
class LabelSpec:
    """One label's alignment problem."""

    name: LabelName
    local: bool
    open: int
    extend: int
    channels: int  # 1: amino acids; 2: 3Di then amino acids
    normalized: bool  # divide by the geometric mean of the two self-scores
    reverse_corrected: bool  # subtract the score of the first sequence reversed
    composition_bias: bool = False  # Foldseek's correction: a per-position term on the first sequence, given per pair


# `foldseek` is Foldseek's score with its composition-bias correction off, equal to the foldseek binary's on every pair
# checked; `foldseek_cbc` is Foldseek's default score, the correction on (`foundry.protein.composition_bias`), whose
# E-value network passes the reversed-database null where the uncorrected score's fails (alignment_atlas's A13).
SPECS: dict[LabelName, LabelSpec] = {
    "sw": LabelSpec("sw", local=True, open=12, extend=1, channels=1, normalized=False, reverse_corrected=False),
    "nw": LabelSpec("nw", local=False, open=20, extend=1, channels=1, normalized=True, reverse_corrected=False),
    "foldseek": LabelSpec("foldseek", local=True, open=FOLDSEEK_GAP_OPEN, extend=FOLDSEEK_GAP_EXTEND, channels=2,
                          normalized=False, reverse_corrected=True),
    "foldseek_cbc": LabelSpec("foldseek_cbc", local=True, open=FOLDSEEK_GAP_OPEN, extend=FOLDSEEK_GAP_EXTEND, channels=2,
                              normalized=False, reverse_corrected=True, composition_bias=True),
}


def read_mmseqs_matrix(path: Path) -> tuple[str, np.ndarray, np.ndarray, float]:
    """An MMseqs `.out` matrix: its alphabet (X last), scores (a, a), the file's background (a) and lambda."""
    alphabet = ""
    rows: list[list[float]] = []
    background = np.zeros(0)
    scale = math.nan
    for line in path.read_text().splitlines():
        if line.startswith("# Background (precomputed optional):"):
            background = np.array([float(x) for x in line.split(":", 1)[1].split()])
        elif line.startswith("# Lambda     (precomputed optional):"):
            scale = float(line.split(":", 1)[1].split()[0])
        elif line.startswith("#") or not line.strip():
            continue
        elif not alphabet:
            alphabet = "".join(line.split())
        else:
            rows.append([float(x) for x in line.split()[1:]])
    scores = np.array(rows)  # (a, a)
    if alphabet[-1] != "X" or scores.shape != (len(alphabet), len(alphabet)) or background.shape != (len(alphabet),) or math.isnan(scale):
        raise ValueError(f"{path} is not a complete MMseqs matrix with background and lambda.")
    return alphabet, scores, background, scale  # str, (a, a), (a), float


@cache
def mmseqs_matrix(path: Path, bit_factor: float, score_bias: float = 0.0) -> tuple[str, np.ndarray, np.ndarray]:
    """MMseqs's integer matrix for `path` at `bit_factor` over the file's own alphabet, X included, and
    `SubstitutionMatrix::pBack` as `readProbMatrix` leaves it: the alphabet, (a, a) int32 and (a).

    SubstitutionMatrix::readProbMatrix rebuilds pair probabilities P = exp(lambda s) p_i p_j from the file's
    background (X's share taken out when X never scores positive), which is pBack; BaseMatrix::generateSubMatrix
    recomputes the background as P's row sums (X fixed at ANY_BACK) and rounds bit_factor log2(P / p_i p_j) + bias half
    away from zero. `bit_factor` is cast to float32, as Foldseek passes a C++ float. Arrays are shared between calls;
    copy before changing them."""
    alphabet, scores, background, scale = read_mmseqs_matrix(path)
    x = alphabet.index("X")
    member = background.copy()
    if not (scores[x] > 0).any() and not (scores[:, x] > 0).any():
        member[np.arange(len(alphabet)) != x] *= 1.0 - background[x]
    probability = np.exp(scale * scores) * member[:, None] * member[None, :]  # (a, a)
    marginal = probability.sum(axis=1)  # (a)
    marginal[x] = ANY_BACK
    bits = np.log2(probability / (marginal[:, None] * marginal[None, :]))  # (a, a)
    scaled = float(np.float32(bit_factor)) * bits + score_bias  # (a, a)
    rounded = np.trunc(np.where(scaled < 0.0, scaled - 0.5, scaled + 0.5)).astype(np.int32)  # (a, a)
    return alphabet, rounded, member  # (a, a), (a)


def mmseqs_integer_matrix(path: Path, bit_factor: float, score_bias: float = 0.0) -> torch.Tensor:
    """`mmseqs_matrix` over `RESIDUES` then `AMBIGUOUS`, each read as `MMSEQS_ALIASES` maps it, with a zero padding row
    and column at `PAD`: (27, 27) int32."""
    alphabet, rounded, _ = mmseqs_matrix(path, bit_factor, score_bias)
    tokens = sorted(TOKEN_IDS.values())
    order = [alphabet.index(MMSEQS_ALIASES.get(letter, letter)) for letter in sorted(TOKEN_IDS, key=TOKEN_IDS.get)]
    table = torch.zeros(TOKENS, TOKENS, dtype=torch.int32)  # (27, 27)
    table[np.ix_(tokens, tokens)] = torch.from_numpy(rounded[np.ix_(order, order)])
    return table  # (27, 27)


def tables(name: LabelName, device: torch.device | str = "cpu") -> torch.Tensor:
    """The label's substitution tables: (27, 27) for one channel, (2, 27, 27) for Foldseek's 3Di then AA."""
    if name == "sw":
        return blosum62_table(1, device)  # (27, 27)
    if name == "nw":
        return blosum62_table(2, device)  # (27, 27)
    three_di = mmseqs_integer_matrix(MATRICES / "mat3di.out", 2.1)  # (27, 27)
    amino = mmseqs_integer_matrix(MATRICES / "blosum62.out", 1.4)  # (27, 27)
    return torch.stack([three_di, amino]).to(device)  # (2, 27, 27)


def raw_scores(spec: LabelSpec, a: torch.Tensor, b: torch.Tensor, len_a: torch.Tensor, len_b: torch.Tensor,
               table: torch.Tensor, *, engine: Literal["triton", "reference"],
               bias: tuple[torch.Tensor, torch.Tensor] | None = None) -> torch.Tensor:
    """The integer score of each pair before normalization: tokens (n, l_a[, c]) and (n, l_b[, c]); returns (n) int32.

    A label with `composition_bias` takes `bias`: each first sequence's terms (n, l_a) int32 on its positions, then
    those of its reversed strings for the reverse score (`composition_bias.foldseek_query_bias` on each), and refuses
    to score without them; any other label refuses them."""
    # a: (n, l_a[, c]); b: (n, l_b[, c]); len_a, len_b: (n); table: (27, 27) or (2, 27, 27); bias: (n, l_a) twice
    if spec.composition_bias != (bias is not None):
        raise ValueError(f"The {spec.name} label {'needs' if spec.composition_bias else 'takes no'} composition bias.")
    if bias is None:
        align = align_triton if engine == "triton" else align_reference
        scores = align(a, b, len_a, len_b, table, open=spec.open, extend=spec.extend, local=spec.local)  # (n)
        if spec.reverse_corrected:
            reverse = align(reverse_within_length(a, len_a), b, len_a, len_b, table, open=spec.open, extend=spec.extend,
                            local=spec.local)  # (n)
            scores = scores - reverse  # (n)
        return scores  # (n)
    forward, backward = bias
    profile = align_profile_triton if engine == "triton" else align_profile_reference
    scores = profile(a, b, len_a, len_b, table, forward, open=spec.open, extend=spec.extend, local=spec.local)  # (n)
    if spec.reverse_corrected:
        scores = scores - profile(reverse_within_length(a, len_a), b, len_a, len_b, table, backward, open=spec.open,
                                  extend=spec.extend, local=spec.local)  # (n)
    return scores  # (n)


def label_scores(spec: LabelSpec, a: torch.Tensor, b: torch.Tensor, len_a: torch.Tensor, len_b: torch.Tensor,
                 table: torch.Tensor, *, self_a: torch.Tensor | None = None, self_b: torch.Tensor | None = None,
                 engine: Literal["triton", "reference"] = "triton",
                 bias: tuple[torch.Tensor, torch.Tensor] | None = None) -> torch.Tensor:
    """The label of each pair as float32: raw for `sw` and the Foldseek labels, self-normalized for `nw`; returns (n).

    `self_a` and `self_b` are the sequences' own raw scores (`self_scores`), required for a normalized label; `bias`
    is `raw_scores`'.
    """
    # a: (n, l_a[, c]); b: (n, l_b[, c]); len_a, len_b, self_a, self_b: (n); table: (27, 27) or (2, 27, 27); bias: (n, l_a) twice
    scores = raw_scores(spec, a, b, len_a, len_b, table, engine=engine, bias=bias).double()  # (n)
    if not spec.normalized:
        return scores.float()  # (n)
    if self_a is None or self_b is None:
        raise ValueError(f"The {spec.name} label divides by self-scores; pass self_a and self_b.")
    return (scores / torch.sqrt(self_a.double() * self_b.double())).float()  # (n)


def self_scores(spec: LabelSpec, tokens: torch.Tensor, lengths: torch.Tensor, table: torch.Tensor, *,
                engine: Literal["triton", "reference"] = "triton") -> torch.Tensor:
    """Each sequence's raw score against itself: tokens (n, l[, c]), lengths (n); returns (n) int32."""
    # tokens: (n, l[, c]); lengths: (n); table: (27, 27) or (2, 27, 27)
    return raw_scores(spec, tokens, tokens, lengths, lengths, table, engine=engine)  # (n)


def null_threshold(moments: np.ndarray, database: int, evalue: float = SIGNIFICANT) -> np.ndarray:
    """The label at which a query's hit has E-value `evalue` against `database` sequences: (q).

    A Gumbel null is fitted by moments to the query's labels against the whole database, which are nearly all unrelated
    (the few homologs barely move the mean and spread); E(s) = database x P(S >= s), as BLAST's statistics but measured,
    so one rule serves every label.
    """
    # moments: (q, 2) or wider, mean and standard deviation first
    beta = moments[:, 1] * np.sqrt(6.0) / np.pi  # (q)
    mu = moments[:, 0] - EULER * beta  # (q)
    return mu - beta * np.log(-np.log1p(-evalue / database))  # (q)


def robust_null_threshold(quartiles: np.ndarray, database: int, evalue: float = SIGNIFICANT) -> np.ndarray:
    """As `null_threshold`, with the Gumbel fitted to the quartiles of the query's labels instead of their moments: (q).

    The mean and spread include the query's homologs, and a family of hundreds, or a small database, lifts the
    threshold toward its own hits; the quartiles of hundreds of thousands of scores do not move for them. A Gumbel's
    p quantile is mu - beta ln(-ln p), so the interquartile range is beta (ln(-ln 0.25) - ln(-ln 0.75)) and the median
    mu - beta ln(ln 2).
    """
    # quartiles: (q, 3), the 25th, 50th and 75th percentiles
    beta = (quartiles[:, 2] - quartiles[:, 0]) / (np.log(-np.log(0.25)) - np.log(-np.log(0.75)))  # (q)
    mu = quartiles[:, 1] + beta * np.log(np.log(2.0))  # (q)
    return mu - beta * np.log(-np.log1p(-evalue / database))  # (q)
