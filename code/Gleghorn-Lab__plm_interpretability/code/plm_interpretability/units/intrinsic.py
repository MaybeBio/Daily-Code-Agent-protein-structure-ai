"""Local terms computed from sequence alone, for patterns the compendium does not annotate.

A unit can track residue chemistry, position or periodicity, which no annotation vocabulary marks; without these terms
it would count as unlabeled. Each term gives 1-based inclusive intervals in the atlas study's local format, is scored
exactly like the release's local terms, and is reported apart (preregistration, `vocabulary`). Thresholds follow the
published defaults of each measure: SEG's trigger window of 12 residues at 2.2 bits (Wootton and Federhen), the
Kyte-Doolittle 19-residue window at a mean of 1.6, and the Eisenberg consensus scale's hydrophobic moment at 100 degrees
over 11 residues at 0.5.

Symbols: l residues of one protein; w a window's length.
"""

from __future__ import annotations

import numpy as np

from numpy.lib.stride_tricks import sliding_window_view


AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"
KYTE_DOOLITTLE = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5, "Q": -3.5, "E": -3.5, "G": -0.4, "H": -3.2, "I": 4.5,
    "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8, "P": -1.6, "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}
EISENBERG = {
    "A": 0.62, "R": -2.53, "N": -0.78, "D": -0.90, "C": 0.29, "Q": -0.85, "E": -0.74, "G": 0.48, "H": -0.40, "I": 1.38,
    "L": 1.06, "K": -1.50, "M": 0.64, "F": 1.19, "P": 0.12, "S": -0.18, "T": -0.05, "W": 0.81, "Y": 0.26, "V": 1.08,
}
TERMINAL = 5
LOW_COMPLEXITY = (12, 2.2)  # window, bits
HYDROPHOBIC_STRETCH = (19, 1.6)  # window, mean Kyte-Doolittle
AMPHIPATHIC = (11, 0.5, 100.0)  # window, mean hydrophobic moment, degrees per residue
CHARGE_RUN = (6, 5)  # window, residues of one charge sign
PROLINE_GLYCINE = (6, 4)  # window, prolines and glycines

TERMS = (
    *(f"residue:{residue}" for residue in AMINO_ACIDS),
    "terminus:n", "terminus:c", "low_complexity", "hydrophobic_stretch", "amphipathic",
    "charge_run:positive", "charge_run:negative", "proline_glycine_rich",
)


def intervals(covered: np.ndarray) -> list[tuple[int, int]]:
    """Runs of covered positions as 1-based inclusive (start, end) pairs."""
    # covered: (l,) bool
    padded = np.concatenate(([False], covered.astype(bool), [False]))  # (l + 2,)
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))  # (2 * runs,)
    return [(int(start) + 1, int(stop)) for start, stop in zip(edges[::2], edges[1::2], strict=True)]


def window_cover(hits: np.ndarray, window: int, length: int) -> np.ndarray:
    """Positions covered by any window that starts at a hit."""
    # hits: (l - w + 1,) bool over window starts
    marks = np.zeros(length + 1, dtype=np.int64)  # (l + 1,)
    starts = np.flatnonzero(hits)  # (h,)
    np.add.at(marks, starts, 1)
    np.add.at(marks, starts + window, -1)
    return np.cumsum(marks[:length]) > 0  # (l,)


def _windows(values: np.ndarray, window: int) -> np.ndarray:
    # values: (l,) or (l, k)
    return sliding_window_view(values, window, axis=0)  # (l - w + 1, w) or (l - w + 1, k, w)


def low_complexity(sequence: str) -> np.ndarray:
    """Positions inside a window whose Shannon entropy over residue types is at most the SEG trigger."""
    window, bits = LOW_COMPLEXITY
    length = len(sequence)
    if length < window:
        return np.zeros(length, dtype=bool)  # (l,)
    codes = np.frombuffer(sequence.encode("ascii"), dtype=np.uint8)  # (l,)
    one_hot = codes[:, None] == np.frombuffer(AMINO_ACIDS.encode("ascii"), dtype=np.uint8)[None, :]  # (l, 20)
    counts = _windows(one_hot.astype(np.int64), window).sum(axis=-1)  # (l - w + 1, 20)
    probability = counts / window  # (l - w + 1, 20)
    with np.errstate(divide="ignore", invalid="ignore"):
        entropy = -np.nansum(np.where(probability > 0, probability * np.log2(probability), 0.0), axis=1)  # (l - w + 1,)
    return window_cover(entropy <= bits, window, length)  # (l,)


def hydrophobic_stretch(sequence: str) -> np.ndarray:
    """Positions inside a 19-residue window of mean Kyte-Doolittle hydropathy of at least 1.6."""
    window, threshold = HYDROPHOBIC_STRETCH
    if len(sequence) < window:
        return np.zeros(len(sequence), dtype=bool)  # (l,)
    scale = np.array([KYTE_DOOLITTLE.get(residue, 0.0) for residue in sequence])  # (l,)
    return window_cover(_windows(scale, window).mean(axis=1) >= threshold, window, len(sequence))  # (l,)


def amphipathic(sequence: str) -> np.ndarray:
    """Positions inside an 11-residue window whose mean hydrophobic moment at 100 degrees is at least 0.5."""
    window, threshold, degrees = AMPHIPATHIC
    if len(sequence) < window:
        return np.zeros(len(sequence), dtype=bool)  # (l,)
    scale = np.array([EISENBERG.get(residue, 0.0) for residue in sequence])  # (l,)
    angle = np.deg2rad(degrees) * np.arange(window)  # (w,)
    windows = _windows(scale, window)  # (l - w + 1, w)
    moment = np.hypot(windows @ np.cos(angle), windows @ np.sin(angle)) / window  # (l - w + 1,)
    return window_cover(moment >= threshold, window, len(sequence))  # (l,)


def _count_runs(sequence: str, residues: str, window: int, minimum: int) -> np.ndarray:
    if len(sequence) < window:
        return np.zeros(len(sequence), dtype=bool)  # (l,)
    marks = np.array([residue in residues for residue in sequence], dtype=np.int64)  # (l,)
    return window_cover(_windows(marks, window).sum(axis=1) >= minimum, window, len(sequence))  # (l,)


def intrinsic_terms(sequence: str) -> dict[str, list[tuple[int, int]]]:
    """Every intrinsic term's 1-based inclusive intervals in one sequence; terms with no interval are left out."""
    length = len(sequence)
    residues = np.frombuffer(sequence.encode("ascii"), dtype=np.uint8)  # (l,)
    covered: dict[str, np.ndarray] = {
        f"residue:{residue}": residues == ord(residue) for residue in AMINO_ACIDS
    }  # each (l,)
    terminal = min(TERMINAL, length)
    covered["terminus:n"] = np.arange(length) < terminal  # (l,)
    covered["terminus:c"] = np.arange(length) >= length - terminal  # (l,)
    covered["low_complexity"] = low_complexity(sequence)
    covered["hydrophobic_stretch"] = hydrophobic_stretch(sequence)
    covered["amphipathic"] = amphipathic(sequence)
    covered["charge_run:positive"] = _count_runs(sequence, "KR", *CHARGE_RUN)
    covered["charge_run:negative"] = _count_runs(sequence, "DE", *CHARGE_RUN)
    covered["proline_glycine_rich"] = _count_runs(sequence, "PG", *PROLINE_GLYCINE)
    return {term: intervals(mask) for term, mask in covered.items() if mask.any()}
