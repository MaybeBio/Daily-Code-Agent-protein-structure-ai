"""Amino-acid sequence text shared by the projects that read sequences from the outside.

A sequence that arrives from a file, an API, or a model's output may hold lowercase letters, the
ambiguity codes B, J, O, U, and Z, gaps, or stop symbols. Aligners, tokenizers, and folding models
accept only the 20 canonical residues plus X, so every reader of outside sequences narrows to that
alphabet first. `sanitize_sequence` is that one narrowing.

The suite keys its datasets, feature caches, and served requests on a different text, the one
`protein_ascii_v1` names, which never rewrites a residue: `normalize_protein_ascii` reads a sequence
that way, or refuses it.

`complexity_flags` is the one low-complexity rule for designed sequences (the Adaptyv campaigns,
2026-10-22): entropy against a uniform sequence of the same length, the longest single-residue run,
and the share of 12-residue windows with four residue types or fewer. `liabilities` is the
sequence half of a developability screen: the motif liabilities antibody engineering counts
(N-glycosylation sequons, deamidation and isomerization motifs, oxidation sites, cysteines) and the
net charge at pH 7.4, the isoelectric point and the mean hydropathy.
"""

from __future__ import annotations

import math
import re


CANONICAL_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
PROTEIN_ASCII_POLICY = "protein_ascii_v1"
# The letters a sequence database writes for a residue, ambiguity codes and the rare amino acids included. A gap, a stop,
# a digit, and every non-letter are not residues.
IDENTITY_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWYBXZJUO")
ASCII_WHITESPACE = " \t\n\r\v\f"

__all__ = [
    "ASCII_WHITESPACE",
    "CANONICAL_AMINO_ACIDS",
    "ENTROPY_DEFICIT_BITS",
    "complexity_flags",
    "IDENTITY_AMINO_ACIDS",
    "PROTEIN_ASCII_POLICY",
    "ProteinTextError",
    "normalize_protein_ascii",
    "sanitize_sequence",
]


class ProteinTextError(ValueError):
    """A sequence cannot keep its meaning under `protein_ascii_v1`."""


def sanitize_sequence(sequence: str) -> str:
    """Uppercase `sequence` and replace every non-canonical residue with X.

    The result holds only the 20 canonical amino acids and X, and has the same length as the
    input, so residue positions are preserved. Gaps and stop symbols become X like any other
    non-canonical character; strip them before calling this if a position shift is what you want.
    """
    return "".join(
        residue if residue in CANONICAL_AMINO_ACIDS else "X"
        for residue in sequence.upper()
    )


def normalize_protein_ascii(sequence: str) -> str:
    """`sequence` under `protein_ascii_v1`: ASCII whitespace removed and letters uppercased, every residue kept.

    Unlike `sanitize_sequence` this never rewrites a residue, because the text is an identity: the same protein must
    normalize to the same text when a dataset is built and when a request is served, and a changed residue would score a
    different protein than the caller sent. A non-string, non-ASCII text, an empty sequence, and one holding a gap, stop,
    digit, or any other symbol raise `ProteinTextError`.
    """
    if not isinstance(sequence, str) or not sequence.isascii():
        raise ProteinTextError("protein sequence must be ASCII text")
    normalized = sequence.translate(str.maketrans("", "", ASCII_WHITESPACE)).upper()
    if not normalized or not set(normalized) <= IDENTITY_AMINO_ACIDS:
        raise ProteinTextError("protein sequence is empty or contains gaps, stops, or invalid residue symbols")
    return normalized


ENTROPY_DEFICIT_BITS = 0.6  # 3.6 bits at a hundred residues, the rule's origin
LOW_COMPLEXITY_RUN = 6
LOW_COMPLEXITY_WINDOW = 12
LOW_COMPLEXITY_WINDOW_TYPES = 4
LOW_COMPLEXITY_WINDOW_SHARE = 0.05


def complexity_flags(sequence: str) -> dict[str, float | int | bool]:
    """Entropy, longest single-residue run, the share of 12-residue windows with at most four residue types, and the verdict.

    A sequence is low complexity when its entropy falls `ENTROPY_DEFICIT_BITS` under that of a uniform random sequence of
    its length (log2(20) less the Miller-Madow term 19 / (2 L ln 2)), when a residue repeats six times in a row, or when
    more than 5 percent of its windows hold four residue types or fewer. A fixed bar of 3.6 bits flagged every 39-residue
    GLP1R peptide design at 3.2 to 3.5 bits while natural 29- to 42-residue peptides (GLP-1, exendin-4, glucagon, GIP, PTH)
    sit at 3.70 to 3.94; the length-aware bar is 3.37 bits at 39 residues and 3.58 at 100 (2026-10-22).
    """
    if not sequence:
        raise ValueError("complexity_flags needs a sequence")
    length = len(sequence)
    counts: dict[str, int] = {}
    for residue in sequence:
        counts[residue] = counts.get(residue, 0) + 1
    entropy = -sum(n / length * math.log2(n / length) for n in counts.values())
    expected = math.log2(20) - 19 / (2 * length * math.log(2))
    longest = run = 1
    for previous, current in zip(sequence, sequence[1:], strict=False):
        run = run + 1 if current == previous else 1
        longest = max(longest, run)
    windows = [len(set(sequence[i:i + LOW_COMPLEXITY_WINDOW])) <= LOW_COMPLEXITY_WINDOW_TYPES for i in range(max(1, length - LOW_COMPLEXITY_WINDOW + 1))]
    share = sum(windows) / len(windows)
    return {"entropy_bits": round(entropy, 3), "entropy_bar_bits": round(expected - ENTROPY_DEFICIT_BITS, 3), "longest_run": longest,
            "low_complexity_window_share": round(share, 3),
            "low_complexity": entropy < expected - ENTROPY_DEFICIT_BITS or longest >= LOW_COMPLEXITY_RUN or share > LOW_COMPLEXITY_WINDOW_SHARE}


# Overlapping matches count each, so NNST holds two sequons. The motifs are the ones developability screens count on
# antibodies (Jain et al. 2017, PNAS 114:944; Sharma et al. 2014, PNAS 111:18601); a de novo binder has no clinical range
# to be judged against, so the counts are recorded beside the design scores, not gated.
LIABILITY_MOTIFS = {
    "n_glycosylation_motifs": re.compile(r"(?=N[^P][ST])"),  # the N-X-S/T sequon, X not proline
    "deamidation_motifs": re.compile(r"(?=N[GS])"),
    "isomerization_motifs": re.compile(r"(?=D[GS])"),
}
OXIDATION_RESIDUES = frozenset("MW")
LIABILITY_PH = 7.4


def liabilities(sequence: str) -> dict[str, float | int]:
    """Motif liabilities, oxidation sites, cysteines, and the charge and hydropathy of a designed sequence at pH 7.4."""
    if not sequence or set(sequence) - CANONICAL_AMINO_ACIDS:
        raise ValueError("liabilities needs a nonempty canonical amino-acid sequence")
    from Bio.SeqUtils.ProtParam import ProteinAnalysis  # Biopython only here, so readers of sequence text do not load it

    analysis = ProteinAnalysis(sequence)
    counts = {name: len(pattern.findall(sequence)) for name, pattern in LIABILITY_MOTIFS.items()}
    return {**counts, "oxidation_sites": sum(residue in OXIDATION_RESIDUES for residue in sequence), "cysteines": sequence.count("C"),
            "net_charge_ph7": round(float(analysis.charge_at_pH(LIABILITY_PH)), 2), "isoelectric_point": round(float(analysis.isoelectric_point()), 2),
            "gravy": round(float(analysis.gravy()), 3)}
