"""Sequence families at an identity threshold: greedy clusters over a global BLOSUM62 alignment, identity over the shorter sequence.

The competition packages and the Protein Design Environment's pool table group designs into families at 70 percent
identity (BLOSUM62, gap open -10, extend -0.5), so a submission's diversity and a pool's family count read one
definition. `identity` is the share of the shorter sequence's residues aligned to an identical residue.
"""

from __future__ import annotations

from Bio import Align
from Bio.Align import substitution_matrices


FAMILY_IDENTITY = 0.70
_ALIGNER = Align.PairwiseAligner(mode="global", substitution_matrix=substitution_matrices.load("BLOSUM62"), open_gap_score=-10, extend_gap_score=-0.5)


def identity(first: str, second: str) -> float:
    """Identical aligned positions over the shorter sequence's length."""
    alignment = _ALIGNER.align(first, second)[0]
    same = 0
    for (start_a, end_a), (start_b, _) in zip(*alignment.aligned, strict=True):
        same += sum(first[start_a + offset] == second[start_b + offset] for offset in range(int(end_a) - int(start_a)))
    return same / min(len(first), len(second))


def families(sequences: list[str], threshold: float = FAMILY_IDENTITY) -> list[int]:
    """Greedy family index per sequence, in the given order: a sequence joins the first family whose founder it matches."""
    founders: list[str] = []
    labels = []
    for sequence in sequences:
        for index, founder in enumerate(founders):
            if identity(sequence, founder) >= threshold:
                labels.append(index)
                break
        else:
            founders.append(sequence)
            labels.append(len(founders) - 1)
    return labels


def shared_kmers(sequence: str, references: dict[str, str], k: int = 6) -> list[str]:
    """Names of references that share an exact k-mer with the sequence."""
    kmers = {sequence[i:i + k] for i in range(len(sequence) - k + 1)}
    return [name for name, reference in references.items() if any(reference[i:i + k] in kmers for i in range(len(reference) - k + 1))]
