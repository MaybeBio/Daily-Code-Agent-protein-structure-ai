"""Composition features of a sequence for a baseline that reads no order past neighbours: the twenty amino-acid fractions,
the log length and the 400 dipeptide fractions, (n, 421). Letters outside the canonical twenty are dropped before counting,
so a sequence of none is a zero row. Promoted 2026-11-01 from the attribute audits of pli_experimental_v2 and
solubility_binary_v2, which read the same features.
"""

from __future__ import annotations

import numpy as np


AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"
FEATURES = 20 + 1 + 400
CODE = np.full(256, -1, dtype=np.int64)  # (256) byte value to residue index; nonstandard letters stay -1
for index, letter in enumerate(AMINO_ACIDS):
    CODE[ord(letter)] = index


def composition(sequences: list[str]) -> np.ndarray:
    """Amino-acid fractions, log length and dipeptide fractions, (n, 421)."""
    n = len(sequences)
    X = np.zeros((n, FEATURES), dtype=np.float32)  # (n, 421)
    for i, sequence in enumerate(sequences):
        codes = CODE[np.frombuffer(sequence.encode("ascii", "replace"), dtype=np.uint8)]  # (l)
        codes = codes[codes >= 0]  # (l')
        if len(codes) == 0:
            continue
        X[i, :20] = np.bincount(codes, minlength=20) / len(codes)
        X[i, 20] = np.log(len(codes))
        if len(codes) > 1:
            pairs = codes[:-1] * 20 + codes[1:]  # (l' - 1)
            X[i, 21:] = np.bincount(pairs, minlength=400) / len(pairs)
    return X  # (n, 421)
