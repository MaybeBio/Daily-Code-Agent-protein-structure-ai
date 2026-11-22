"""ipSAE, ipTM, pDockQ, pDockQ2, and LIS for a predicted complex: the workspace's one ipSAE.

ipSAE (Dunbrack, 2025, https://www.biorxiv.org/content/10.1101/2025.02.10.637595v1) scores a
predicted interface from its predicted aligned errors (PAE). Aligned on one residue of a chain,
each error to the other chain's residues below a cutoff becomes a TM-score term, whose distance
scale d0 is set by how many errors there are. A direction's score is its best residue's mean term,
and a pair's ipSAE_min is the weaker of its two directions.

Two forms live here:

- From the PAE matrix alone, given where each chain's rows are: `ipsae_asym_from_pae` and
  `ipsae_min_fields`, with `tm_d0` and `tm_from_pae`.
- The Dunbrack lab's full table, from the PAE matrix and the structure: `interface_scores` over
  residue arrays, `read_structure` and `read_prediction` for AlphaFold2, AlphaFold3, and Boltz
  outputs, the script's three output files from `write_outputs`, and its command line,
  `python -m foundry.protein.ipsae <pae file> <structure file> <pae cutoff> <dist cutoff>`.

The full table is the Dunbrack lab's ipsae.py, version 3, at DunbrackLab/IPSAE commit
441b2a479be3, refactored. Its notice, which its license asks to reproduce:

    Roland Dunbrack
    Fox Chase Cancer Center
    version 3
    April 6, 2025
    MIT license: script can be modified and redistributed for non-commercial and commercial use,
    as long as this information is reproduced.

It also calculates pDockQ (Bryant, Pozzati, and Elofsson,
https://www.nature.com/articles/s41467-022-28865-w), pDockQ2 (Zhu, Shenoy, Kundrotas, and
Elofsson, https://academic.oup.com/bioinformatics/article/39/7/btad424/7219714), and LIS (Kim, Hu,
Comjean, Rodiger, Mohr, and Perrimon, https://www.biorxiv.org/content/10.1101/2024.02.19.580970v1).
foundry.protein's README lists where this differs from the script.
"""

from __future__ import annotations

import json
import math
import sys
import warnings
import numpy as np

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict


__all__ = [
    "InterfaceScores",
    "Prediction",
    "ResidueArrays",
    "chain_pair_iptm_from_matrix",
    "empty_ipsae_min_summary",
    "format_chain_pair_table",
    "format_pymol_script",
    "format_residue_table",
    "interface_scores",
    "ipsae_asym_from_pae",
    "ipsae_min_fields",
    "main",
    "protein_chain_spans_from_entities",
    "read_prediction",
    "read_structure",
    "score_prediction",
    "tm_d0",
    "tm_from_pae",
    "write_outputs",
]


# ---------------------------------------------------------------------------------------------
# From the PAE matrix alone
# ---------------------------------------------------------------------------------------------


class ChainSpan(TypedDict):
    """One protein chain's rows of the PAE matrix: `start` is its first row, `end` one past its last."""

    id: str
    start: int
    end: int
    length: int


class AsymmetricScore(TypedDict):
    """One direction's ipSAE, with the error count and d0 of the aligned residue that set it."""

    score: float
    n0res: int
    d0res: float


class PairMetrics(TypedDict):
    """Both directions of one pair of chains, as `ipsae_pair_metrics_json` lists them."""

    chain_a: str
    chain_b: str
    ipsae_min: float
    ipsae_max: float
    ipsae_a_to_b: float
    ipsae_b_to_a: float
    n0res_a_to_b: int
    n0res_b_to_a: int
    d0res_a_to_b: float
    d0res_b_to_a: float


class IpsaeMinFields(TypedDict, total=False):
    """`ipsae_min_fields`' result: every key for two or more spans, none for fewer."""

    ipsae: float
    ipsae_min: float
    ipsae_max: float
    ipsae_a_to_b: float
    ipsae_b_to_a: float
    ipsae_chain_pair: str
    ipsae_pair_metrics_json: str
    binder_likely: bool


def protein_chain_spans_from_entities(entities: list[dict[str, Any]]) -> list[ChainSpan]:
    """Each protein chain's rows of the PAE matrix, from a fold request's entities in order.

    A protein, DNA, or RNA entity takes one row per residue, and a SMILES or CCD ligand one row.
    Each span is `{"id": chain_id, "start": first row, "end": one past the last, "length": residues}`.
    """
    spans: list[ChainSpan] = []
    cursor = 0
    for entity in entities:
        entity_type = str(entity["type"])
        if entity_type in {"protein", "dna", "rna"}:
            value = str(entity["value"])
            length = len(value)
            if entity_type == "protein":
                spans.append(
                    {
                        "id": str(entity["chain_id"]),
                        "start": cursor,
                        "end": cursor + length,
                        "length": length,
                    }
                )
            cursor += length
        elif entity_type in {"smiles", "ccd"}:
            cursor += 1
        else:
            raise ValueError(f"Unsupported entity type for ipSAE spans: {entity_type!r}")
    return spans


def tm_d0(length: int | float) -> float:
    """TM-score's distance scale d0, in angstroms, for `length` residues.

    It is 1.24 (L - 15)^(1/3) - 1.8 with L counted as at least 27, as the Dunbrack script counts it,
    so never under about 1.039 (decision 2026-09-24_ipsae_min_d0).
    """
    return _d0(float(length), "protein")


def tm_from_pae(pae_value: float, d0: float) -> float:
    """One predicted aligned error as a TM-score term: 1 / (1 + (pae / d0)^2)."""
    return 1.0 / (1.0 + (float(pae_value) / float(d0)) ** 2.0)


def ipsae_asym_from_pae(
    pae_matrix: Sequence[Sequence[float]] | np.ndarray,
    align_span: ChainSpan,
    scored_span: ChainSpan,
    pae_cutoff: float,
) -> AsymmetricScore:
    """One direction's ipSAE, aligned on each residue of `align_span` and scored over `scored_span`.

    `pae_matrix` is `(l, l)`, rows aligned on and columns scored, as a list of rows or an array.
    Returns `score`, the best aligned residue's mean TM-score term over its errors below
    `pae_cutoff`; `n0res`, how many errors that residue kept; and `d0res`, the d0 they set. When
    no error is below the cutoff the score is 0.0 and `n0res` is 0.
    """
    # pae_matrix: (l, l), l tokens in the complex
    best_score = 0.0
    best_n0res = 0
    best_d0res = tm_d0(0)
    for row_index in range(int(align_span["start"]), int(align_span["end"])):
        pae_row = pae_matrix[row_index]  # (l,)
        valid_pae: list[float] = []  # (n0res,)
        for col_index in range(int(scored_span["start"]), int(scored_span["end"])):
            pae = float(pae_row[col_index])
            if pae < pae_cutoff:
                valid_pae.append(pae)

        n0res = len(valid_pae)
        if n0res == 0:
            continue

        d0res = tm_d0(n0res)
        score = float(sum(tm_from_pae(pae, d0res) for pae in valid_pae) / n0res)
        if score > best_score:
            best_score = score
            best_n0res = n0res
            best_d0res = d0res

    return {
        "score": best_score,
        "n0res": best_n0res,
        "d0res": best_d0res,
    }


def ipsae_min_fields(
    pae_matrix: Sequence[Sequence[float]] | np.ndarray,
    chain_spans: list[ChainSpan],
    *,
    pae_cutoff: float,
    binder_threshold: float,
) -> IpsaeMinFields:
    """Score each pair of chains both ways, and return the fields of the pair whose weaker direction is strongest.

    `pae_matrix` is `(l, l)` and holds every row the spans name. `ipsae` and `ipsae_min` are that
    pair's weaker direction and `ipsae_max` its stronger, `ipsae_a_to_b` and `ipsae_b_to_a` are
    each direction, and `ipsae_chain_pair` names the pair as `"A:B"`. `ipsae_pair_metrics_json`
    holds every pair's scores as compact JSON, and `binder_likely` is whether `ipsae_min` exceeds
    `binder_threshold`. The first pair wins a tie. With fewer than two spans there is no pair,
    and the result is empty.
    """
    # pae_matrix: (l, l), l tokens in the complex
    pair_metrics: list[PairMetrics] = []
    best_pair: PairMetrics | None = None
    best_score = -1.0
    for index_a in range(len(chain_spans)):
        for index_b in range(index_a + 1, len(chain_spans)):
            span_a = chain_spans[index_a]
            span_b = chain_spans[index_b]
            a_to_b = ipsae_asym_from_pae(pae_matrix, span_a, span_b, pae_cutoff)
            b_to_a = ipsae_asym_from_pae(pae_matrix, span_b, span_a, pae_cutoff)
            pair_min = min(float(a_to_b["score"]), float(b_to_a["score"]))
            pair_max = max(float(a_to_b["score"]), float(b_to_a["score"]))
            pair_payload: PairMetrics = {
                "chain_a": str(span_a["id"]),
                "chain_b": str(span_b["id"]),
                "ipsae_min": pair_min,
                "ipsae_max": pair_max,
                "ipsae_a_to_b": float(a_to_b["score"]),
                "ipsae_b_to_a": float(b_to_a["score"]),
                "n0res_a_to_b": int(a_to_b["n0res"]),
                "n0res_b_to_a": int(b_to_a["n0res"]),
                "d0res_a_to_b": float(a_to_b["d0res"]),
                "d0res_b_to_a": float(b_to_a["d0res"]),
            }
            pair_metrics.append(pair_payload)
            if pair_min > best_score:
                best_score = pair_min
                best_pair = pair_payload

    if best_pair is None:
        return {}

    return {
        "ipsae": float(best_pair["ipsae_min"]),
        "ipsae_min": float(best_pair["ipsae_min"]),
        "ipsae_max": float(best_pair["ipsae_max"]),
        "ipsae_a_to_b": float(best_pair["ipsae_a_to_b"]),
        "ipsae_b_to_a": float(best_pair["ipsae_b_to_a"]),
        "ipsae_chain_pair": f"{best_pair['chain_a']}:{best_pair['chain_b']}",
        "ipsae_pair_metrics_json": json.dumps(pair_metrics, separators=(",", ":")),
        "binder_likely": float(best_pair["ipsae_min"]) > float(binder_threshold),
    }


def empty_ipsae_min_summary(pae_cutoff: float, binder_threshold: float | None = None) -> dict[str, Any]:
    """The summary of an interface that cannot be scored: every `ipsae_min_fields` key blank and `binder_likely` False.

    Callers `update` it with `ipsae_min_fields` when a pair can be scored. Given `binder_threshold`, the summary
    also records it as `binder_ipsae_threshold`, after the cutoff.
    """
    summary: dict[str, Any] = {
        "ipsae": "",
        "ipsae_min": "",
        "ipsae_max": "",
        "ipsae_a_to_b": "",
        "ipsae_b_to_a": "",
        "ipsae_chain_pair": "",
        "ipsae_pae_cutoff": float(pae_cutoff),
    }
    if binder_threshold is not None:
        summary["binder_ipsae_threshold"] = float(binder_threshold)
    summary |= {"ipsae_pair_metrics_json": "", "binder_likely": False}
    return summary


# ---------------------------------------------------------------------------------------------
# The full table: ipSAE with three d0 choices, ipTM, pDockQ, pDockQ2, and LIS
# ---------------------------------------------------------------------------------------------

NUCLEIC_ACID_RESIDUES = frozenset({"DA", "DC", "DT", "DG", "A", "C", "U", "G"})
TOKEN_RESIDUES = frozenset({
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
}) | NUCLEIC_ACID_RESIDUES
PDOCKQ_DISTANCE = 8.0  # angstroms between CB-equivalent atoms that count as a contact
LIS_PAE_CUTOFF = 12.0

_CHAIN_COLORS = {
    "A": "magenta", "B": "marine", "C": "lime", "D": "orange", "E": "yellow", "F": "cyan",
    "G": "lightorange", "H": "pink", "I": "deepteal", "J": "forest", "K": "lightblue",
    "L": "slate", "M": "violet", "N": "arsenic", "O": "iodine", "P": "silver", "Q": "red",
    "R": "sulfur", "S": "purple", "T": "olive", "U": "palegreen", "V": "green", "W": "blue",
    "X": "palecyan", "Y": "limon", "Z": "chocolate",
}


def _ptm(pae: np.ndarray | float, d0: float) -> np.ndarray | float:
    """Each predicted aligned error as a TM-score term, 1 / (1 + (pae / d0)^2)."""
    # pae: (...) errors in angstroms, or one float
    return 1.0 / (1.0 + (pae / d0) ** 2.0)  # (...), as pae


def _d0(length: float, pair_type: str) -> float:
    """The script's d0: at least 27 residues counted, and at least 1.0, or 2.0 with nucleic acid."""
    length = max(27.0, float(length))
    minimum = 2.0 if pair_type == "nucleic_acid" else 1.0
    return max(minimum, 1.24 * (length - 15.0) ** (1.0 / 3.0) - 1.8)


def _d0_array(lengths: np.ndarray, pair_type: str) -> np.ndarray:
    """`_d0` of each length."""
    # lengths: (...)
    lengths = np.maximum(27.0, np.asarray(lengths, dtype=float))  # (...)
    minimum = 2.0 if pair_type == "nucleic_acid" else 1.0
    return np.maximum(minimum, 1.24 * (lengths - 15.0) ** (1.0 / 3.0) - 1.8)  # (...)


def _cutoff_text(cutoff: float) -> str:
    """A cutoff as the script names it in files: its integer part, two digits below 10."""
    value = int(cutoff)
    return f"0{value}" if cutoff < 10 else str(value)


def _chain_index(label: str) -> int:
    """A chain label's index in a predictor's chain-pair matrices: A is 0, Z 25, AA 26."""
    total = 0
    for char in label.upper():
        if not "A" <= char <= "Z":
            raise ValueError(f"Chain label {label!r} is not letters")
        total = total * 26 + (ord(char) - ord("A") + 1)
    return total - 1


def chain_pair_iptm_from_matrix(
    matrix: Sequence[Sequence[float]] | Mapping[str, Mapping[str, float]] | np.ndarray,
    chains: Sequence[str],
) -> dict[str, dict[str, float]] | None:
    """Each ordered chain pair's ipTM from a predictor's chain-pair matrix, keyed by chain label.

    `matrix` is indexed by each chain's position in the alphabet (A 0, B 1), as AlphaFold3's
    `chain_pair_iptm` list of rows or Boltz's `pair_chains_iptm` mapping of string indices.
    Returns None when the matrix does not reach every chain.
    """
    # matrix: (m, m) by alphabet position, m at least one past the last chain's, or a mapping of the same
    iptm: dict[str, dict[str, float]] = {chain: {} for chain in chains}
    for chain1 in chains:
        for chain2 in chains:
            if chain1 == chain2:
                continue
            i, j = _chain_index(chain1), _chain_index(chain2)
            try:
                if isinstance(matrix, Mapping):
                    value = matrix[str(i)][str(j)]
                else:
                    if i >= len(matrix) or j >= len(matrix[i]):
                        return None
                    value = matrix[i][j]
            except (KeyError, IndexError):
                return None
            iptm[chain1][chain2] = float(value)
    return iptm


@dataclass(frozen=True)
class ResidueArrays:
    """One entry per residue token of a structure, in file order.

    `coordinates` are each residue's CB-equivalent atom (CB, C3' for a nucleotide, CA for
    glycine, and the token atom when none of those is present). `token_atom_indices` and
    `cb_atom_indices` are those atoms' 0-based positions among the file's atoms, which index
    AlphaFold3's per-atom pLDDT. `token_mask` has one entry per token of the predictor's PAE
    matrix, `n_tokens` of them, true where the token is one of these `n` residues.
    """

    chains: np.ndarray  # (n,) str
    residue_types: np.ndarray  # (n,) str
    residue_numbers: np.ndarray  # (n,) int
    coordinates: np.ndarray  # (n, 3) angstroms
    token_atom_indices: np.ndarray  # (n,) int
    cb_atom_indices: np.ndarray  # (n,) int
    token_mask: np.ndarray  # (n_tokens,) bool, n true


@dataclass(frozen=True, slots=True)
class _Atom:
    """One ATOM or HETATM record of a structure file."""

    atom_num: int  # the file's 1-based serial number
    atom_name: str
    residue_name: str
    chain_id: str
    residue_seq_num: int
    coord: tuple[float, float, float]  # angstroms


def _pdb_atom(line: str) -> _Atom:
    """A PDB file's ATOM or HETATM line, read by its fixed columns."""
    return _Atom(
        atom_num=int(line[6:11].strip()),
        atom_name=line[12:16].strip(),
        residue_name=line[17:20].strip(),
        chain_id=line[21].strip(),
        residue_seq_num=int(line[22:26].strip()),
        coord=(float(line[30:38].strip()), float(line[38:46].strip()), float(line[46:54].strip())),
    )


def _cif_atom(line: str, fields: dict[str, int]) -> _Atom | None:
    """An mmCIF `_atom_site` row, read by the column positions in `fields`; None for a ligand atom."""
    parts = line.split()
    residue_seq_num = parts[fields["label_seq_id"]]
    if residue_seq_num == ".":
        return None  # a ligand atom
    return _Atom(
        atom_num=int(parts[fields["id"]]),
        atom_name=parts[fields["label_atom_id"]],
        residue_name=parts[fields["label_comp_id"]],
        chain_id=parts[fields["label_asym_id"]],
        residue_seq_num=int(residue_seq_num),
        coord=(
            float(parts[fields["Cartn_x"]]),
            float(parts[fields["Cartn_y"]]),
            float(parts[fields["Cartn_z"]]),
        ),
    )


def read_structure(path: str | Path) -> ResidueArrays:
    """The residue tokens of a PDB file (AlphaFold2) or an mmCIF file (AlphaFold3, Boltz).

    A residue's token is its CA atom, or C1' for a nucleotide. An mmCIF atom with no residue
    number is a ligand and takes a token of its own that is not a residue, as does each atom of a
    modified residue other than its CA, as the predictors tokenize them.
    """
    path = Path(path)
    if path.suffix.lower() == ".pdb":
        is_cif = False
    elif path.suffix.lower() == ".cif":
        is_cif = True
    else:
        raise ValueError(f"Structure file must be .pdb or .cif: {path}")

    fields: dict[str, int] = {}
    token_atoms: list[_Atom] = []
    cb_atoms: dict[tuple[str, int], _Atom] = {}
    token_mask: list[bool] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("_atom_site."):
                fields[line.strip().split(".")[1]] = len(fields)
            if not (line.startswith("ATOM") or line.startswith("HETATM")):
                continue
            atom = _cif_atom(line, fields) if is_cif else _pdb_atom(line)
            if atom is None:
                token_mask.append(False)
                continue
            name, residue = atom.atom_name, atom.residue_name
            if name == "CA" or "C1" in name:
                token_mask.append(True)
                token_atoms.append(atom)
            if name == "CB" or "C3" in name or (residue == "GLY" and name == "CA"):
                cb_atoms[(atom.chain_id, atom.residue_seq_num)] = atom
            if name != "CA" and "C1" not in name and residue not in TOKEN_RESIDUES:
                token_mask.append(False)

    if not token_atoms:
        raise ValueError(f"No residue tokens (CA or C1' atoms) in {path}")
    # Each residue takes the CB-equivalent atom of its own chain and number, so a residue with
    # none of them cannot shift every later residue's coordinates onto its neighbor's.
    cb_for_token = [cb_atoms.get((atom.chain_id, atom.residue_seq_num), atom) for atom in token_atoms]
    return ResidueArrays(
        chains=np.array([atom.chain_id for atom in token_atoms]),  # (n,)
        residue_types=np.array([atom.residue_name for atom in token_atoms]),  # (n,)
        residue_numbers=np.array([atom.residue_seq_num for atom in token_atoms], dtype=int),  # (n,)
        coordinates=np.array([atom.coord for atom in cb_for_token], dtype=float),  # (n, 3)
        token_atom_indices=np.array([atom.atom_num - 1 for atom in token_atoms], dtype=int),  # (n,)
        cb_atom_indices=np.array([atom.atom_num - 1 for atom in cb_for_token], dtype=int),  # (n,)
        token_mask=np.array(token_mask, dtype=bool),  # (n_tokens,)
    )


class ChainPairRow(TypedDict):
    """One row of the chain-pair table, under the script's column names.

    `PAE` and `Dist` are the cutoffs as the script writes them, `Type` is `asym` or `max`, and
    `Model` names the structure.
    """

    Chn1: str
    Chn2: str
    PAE: str
    Dist: str
    Type: str
    ipSAE: float
    ipSAE_d0chn: float
    ipSAE_d0dom: float
    ipTM_af: float
    ipTM_d0chn: float
    pDockQ: float
    pDockQ2: float
    LIS: float
    n0res: int
    n0chn: int
    n0dom: int
    d0res: float
    d0chn: float
    d0dom: float
    nres1: int
    nres2: int
    dist1: int
    dist2: int
    Model: str


class ResidueRow(TypedDict):
    """One row of the by-residue table, under the script's column names; `i` counts from 1."""

    i: int
    AlignChn: str
    ScoredChain: str
    AlignResNum: int
    AlignResType: str
    AlignRespLDDT: float
    n0chn: int
    n0dom: int
    n0res: int
    d0chn: float
    d0dom: float
    d0res: float
    ipTM_pae: float
    ipSAE_d0chn: float
    ipSAE_d0dom: float
    ipSAE: float


@dataclass(frozen=True)
class InterfaceScores:
    """The script's tables for one predicted complex.

    `rows` is the chain-pair table: for each unordered pair in chain order, its two `asym` rows
    (each direction) and its `max` row, with the script's column names as keys. `residue_rows` is
    the by-residue table. `interface_residues` holds, for each ordered pair, the residue numbers
    of each chain with an error below the PAE cutoff, which the PyMOL script colors.
    """

    rows: list[ChainPairRow]
    residue_rows: list[ResidueRow]
    interface_residues: dict[tuple[str, str], tuple[frozenset[int], frozenset[int]]]
    chains: list[str]


def _mask_to_min_length(label: str, arrays: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Cut residue-indexed arrays to their common length, warning when they disagree.

    A predictor's PAE matrix or pLDDT can hold a different number of tokens than the structure it
    wrote; the script then raised or read a neighbor's values. Cutting keeps the residues all
    arrays cover, as property_oracles' copy of the script did.
    """
    # arrays: (n_k, ...) each, with pae_matrix (n_k, n_k); n_c is the smallest n_k
    lengths = {name: int(array.shape[0]) for name, array in arrays.items()}
    common = min(lengths.values())  # n_c
    if common == 0:
        raise ValueError(f"{label}: empty residue arrays: {lengths}")
    if common == max(lengths.values()):
        return arrays  # (n_c, ...) each, already one length
    warnings.warn(f"{label}: residue arrays disagree in length, cut to {common}: {lengths}", stacklevel=3)
    return {  # (n_c, ...) each, with pae_matrix (n_c, n_c)
        name: array[:common, :common] if name == "pae_matrix" else array[:common]
        for name, array in arrays.items()
    }


def interface_scores(
    pae_matrix: np.ndarray | Sequence[Sequence[float]],  # (n, n)
    chains: Sequence[str] | np.ndarray,  # (n,)
    residue_types: Sequence[str] | np.ndarray,  # (n,)
    residue_numbers: Sequence[int] | np.ndarray,  # (n,)
    coordinates: np.ndarray | Sequence[Sequence[float]],  # (n, 3)
    cb_plddt: np.ndarray | Sequence[float],  # (n,)
    *,
    plddt: np.ndarray | Sequence[float] | None = None,  # (n,)
    iptm: float | Mapping[str, Mapping[str, float]] | None = None,
    pae_cutoff: float = 10.0,
    dist_cutoff: float = 10.0,
    model_label: str = "model",
) -> InterfaceScores:
    """ipSAE, ipTM, pDockQ, pDockQ2, and LIS for every pair of chains, as the script computes them.

    Every array has one entry per residue token, in the same order: `pae_matrix` is `(n, n)`,
    aligned on rows and scored on columns; `coordinates` are the CB-equivalent atoms `(n, 3)`;
    `cb_plddt` is their pLDDT on the 0 to 100 scale, which the pDockQ constants assume. `plddt`,
    each token atom's pLDDT, only fills the by-residue table and defaults to `cb_plddt`.

    `iptm` fills the `ipTM_af` column: the predictor's own ipTM, one value for the whole complex
    (AlphaFold2) or one per ordered chain pair (AlphaFold3, Boltz). A pair's `max` row takes the
    larger of its two directions. With None, `ipTM_af` repeats `ipTM_d0chn`, the ipTM computed
    here from the PAE matrix.
    """
    pae_matrix = np.asarray(pae_matrix, dtype=float)  # (n, n)
    chains = np.asarray(chains)  # (n,)
    residue_types = np.asarray(residue_types)  # (n,)
    residue_numbers = np.asarray(residue_numbers, dtype=int)  # (n,)
    coordinates = np.asarray(coordinates, dtype=float)  # (n, 3)
    cb_plddt = np.asarray(cb_plddt, dtype=float)  # (n,)
    plddt = cb_plddt if plddt is None else np.asarray(plddt, dtype=float)  # (n,)
    if pae_matrix.ndim != 2 or pae_matrix.shape[0] != pae_matrix.shape[1]:
        raise ValueError(f"PAE matrix must be square, got {pae_matrix.shape}")
    numres = int(pae_matrix.shape[0])  # n
    for name, array in (("chains", chains), ("residue_types", residue_types), ("residue_numbers", residue_numbers),
                        ("coordinates", coordinates), ("cb_plddt", cb_plddt), ("plddt", plddt)):
        if array.shape[0] != numres:
            raise ValueError(f"{name} has {array.shape[0]} entries for a {numres}-residue PAE matrix")

    unique_chains = [str(chain) for chain in np.unique(chains)]
    distances = np.sqrt(((coordinates[:, None, :] - coordinates[None, :, :]) ** 2).sum(axis=2))  # (n, n) angstroms
    nucleic = {
        chain: any(residue in NUCLEIC_ACID_RESIDUES for residue in residue_types[chains == chain])
        for chain in unique_chains
    }
    ordered_pairs = [(c1, c2) for c1 in unique_chains for c2 in unique_chains if c1 != c2]
    pair_type = {
        (c1, c2): "nucleic_acid" if nucleic[c1] or nucleic[c2] else "protein" for c1, c2 in ordered_pairs
    }
    in_chain = {chain: chains == chain for chain in unique_chains}  # (n,) each

    pdockq: dict[tuple[str, str], float] = {}
    pdockq2: dict[tuple[str, str], float] = {}
    lis: dict[tuple[str, str], float] = {}
    for c1, c2 in ordered_pairs:
        npairs = 0
        ptm_sum = 0.0
        contact_residues: set[int] = set()
        for i in np.where(in_chain[c1])[0]:
            contacts = in_chain[c2] & (distances[i] <= PDOCKQ_DISTANCE)  # (n,)
            if contacts.any():
                npairs += int(np.sum(contacts))
                contact_residues.add(int(i))
                contact_residues.update(int(j) for j in np.where(contacts)[0])
                ptm_sum += float(_ptm(pae_matrix[i][contacts], 10.0).sum())
        if npairs > 0:
            mean_plddt = cb_plddt[list(contact_residues)].mean()
            pdockq[(c1, c2)] = 0.724 / (1 + math.exp(-0.052 * (mean_plddt * math.log10(npairs) - 152.611))) + 0.018
            pdockq2[(c1, c2)] = 1.31 / (1 + math.exp(-0.075 * (mean_plddt * (ptm_sum / npairs) - 84.733))) + 0.005
        else:
            pdockq[(c1, c2)] = 0.0
            pdockq2[(c1, c2)] = 0.0

        # Every error from a residue of c1 to one of c2, n_1 * n_2 of them, and those within LIS's cutoff.
        selected = pae_matrix[in_chain[c1][:, None] & in_chain[c2][None, :]]  # (n_1 * n_2,)
        valid = selected[selected <= LIS_PAE_CUTOFF]  # (n_lis,)
        lis[(c1, c2)] = float(np.mean((LIS_PAE_CUTOFF - valid) / LIS_PAE_CUTOFF)) if valid.size > 0 else 0.0

    # Per aligned residue, for each ordered pair: (n,) each, zero outside the aligned chain.
    iptm_d0chn_byres = {pair: np.zeros(numres) for pair in ordered_pairs}
    ipsae_d0chn_byres = {pair: np.zeros(numres) for pair in ordered_pairs}
    ipsae_d0dom_byres = {pair: np.zeros(numres) for pair in ordered_pairs}
    ipsae_d0res_byres = {pair: np.zeros(numres) for pair in ordered_pairs}
    n0chn: dict[tuple[str, str], int] = {}
    d0chn: dict[tuple[str, str], float] = {}
    n0dom: dict[tuple[str, str], int] = {}
    d0dom: dict[tuple[str, str], float] = {}
    n0res_byres: dict[tuple[str, str], np.ndarray] = {}  # (n,) each
    d0res_byres: dict[tuple[str, str], np.ndarray] = {}  # (n,) each
    aligned_residues: dict[tuple[str, str], set[int]] = {pair: set() for pair in ordered_pairs}
    scored_residues: dict[tuple[str, str], set[int]] = {pair: set() for pair in ordered_pairs}
    close_aligned: dict[tuple[str, str], set[int]] = {pair: set() for pair in ordered_pairs}
    close_scored: dict[tuple[str, str], set[int]] = {pair: set() for pair in ordered_pairs}

    for pair in ordered_pairs:
        c1, c2 = pair
        n0chn[pair] = int(np.sum(in_chain[c1]) + np.sum(in_chain[c2]))
        d0chn[pair] = _d0(n0chn[pair], pair_type[pair])
        ptm_d0chn = _ptm(pae_matrix, d0chn[pair])  # (n, n)
        below_cutoff = in_chain[c2] & (pae_matrix < pae_cutoff)  # (n, n)
        for i in np.where(in_chain[c1])[0]:
            iptm_d0chn_byres[pair][i] = ptm_d0chn[i, in_chain[c2]].mean() if in_chain[c2].any() else 0.0
            kept = below_cutoff[i]  # (n,)
            ipsae_d0chn_byres[pair][i] = ptm_d0chn[i, kept].mean() if kept.any() else 0.0
            if kept.any():
                aligned_residues[pair].add(int(residue_numbers[i]))
                scored_residues[pair].update(int(residue_numbers[j]) for j in np.where(kept)[0])
            close = kept & (distances[i] < dist_cutoff)  # (n,)
            if close.any():
                close_aligned[pair].add(int(residue_numbers[i]))
                close_scored[pair].update(int(residue_numbers[j]) for j in np.where(close)[0])

    residue_rows: list[ResidueRow] = []
    for pair in ordered_pairs:
        c1, c2 = pair
        n0dom[pair] = len(aligned_residues[pair]) + len(scored_residues[pair])
        d0dom[pair] = _d0(n0dom[pair], pair_type[pair])
        ptm_d0dom = _ptm(pae_matrix, d0dom[pair])  # (n, n)
        below_cutoff = in_chain[c2] & (pae_matrix < pae_cutoff)  # (n, n)
        n0res_byres[pair] = np.sum(below_cutoff, axis=1)  # (n,)
        d0res_byres[pair] = _d0_array(n0res_byres[pair], pair_type[pair])  # (n,)
        for i in np.where(in_chain[c1])[0]:
            kept = below_cutoff[i]  # (n,)
            if kept.any():
                ipsae_d0dom_byres[pair][i] = ptm_d0dom[i, kept].mean()
                ipsae_d0res_byres[pair][i] = _ptm(pae_matrix[i], d0res_byres[pair][i])[kept].mean()
            residue_rows.append({
                "i": int(i) + 1,
                "AlignChn": c1,
                "ScoredChain": c2,
                "AlignResNum": int(residue_numbers[i]),
                "AlignResType": str(residue_types[i]),
                "AlignRespLDDT": float(plddt[i]),
                "n0chn": n0chn[pair],
                "n0dom": n0dom[pair],
                "n0res": int(n0res_byres[pair][i]),
                "d0chn": d0chn[pair],
                "d0dom": d0dom[pair],
                "d0res": float(d0res_byres[pair][i]),
                "ipTM_pae": float(iptm_d0chn_byres[pair][i]),
                "ipSAE_d0chn": float(ipsae_d0chn_byres[pair][i]),
                "ipSAE_d0dom": float(ipsae_d0dom_byres[pair][i]),
                "ipSAE": float(ipsae_d0res_byres[pair][i]),
            })

    # Each direction's value is its best aligned residue's; ipSAE's n0res and d0res are that residue's.
    iptm_d0chn = {pair: float(np.max(values)) for pair, values in iptm_d0chn_byres.items()}
    ipsae_d0chn = {pair: float(np.max(values)) for pair, values in ipsae_d0chn_byres.items()}
    ipsae_d0dom = {pair: float(np.max(values)) for pair, values in ipsae_d0dom_byres.items()}
    ipsae_d0res: dict[tuple[str, str], float] = {}
    n0res: dict[tuple[str, str], int] = {}
    d0res: dict[tuple[str, str], float] = {}
    for pair, values in ipsae_d0res_byres.items():
        best = int(np.argmax(values))
        ipsae_d0res[pair] = float(values[best])
        n0res[pair] = int(n0res_byres[pair][best])
        d0res[pair] = float(d0res_byres[pair][best])

    def af_iptm(pair: tuple[str, str]) -> float:
        if iptm is None:
            return iptm_d0chn[pair]
        if isinstance(iptm, Mapping):
            return float(iptm[pair[0]][pair[1]])
        return float(iptm)

    pae_text, dist_text = _cutoff_text(pae_cutoff), _cutoff_text(dist_cutoff)
    rows: list[ChainPairRow] = []
    for index_a, chain_a in enumerate(unique_chains):
        for chain_b in unique_chains[index_a + 1:]:
            for pair in ((chain_a, chain_b), (chain_b, chain_a)):
                rows.append({
                    "Chn1": pair[0], "Chn2": pair[1], "PAE": pae_text, "Dist": dist_text, "Type": "asym",
                    "ipSAE": ipsae_d0res[pair], "ipSAE_d0chn": ipsae_d0chn[pair],
                    "ipSAE_d0dom": ipsae_d0dom[pair], "ipTM_af": af_iptm(pair),
                    "ipTM_d0chn": iptm_d0chn[pair], "pDockQ": pdockq[pair], "pDockQ2": pdockq2[pair],
                    "LIS": lis[pair], "n0res": n0res[pair], "n0chn": n0chn[pair], "n0dom": n0dom[pair],
                    "d0res": d0res[pair], "d0chn": d0chn[pair], "d0dom": d0dom[pair],
                    "nres1": len(aligned_residues[pair]), "nres2": len(scored_residues[pair]),
                    "dist1": len(close_aligned[pair]), "dist2": len(close_scored[pair]),
                    "Model": model_label,
                })
            # The max row takes each score's stronger direction; on a tie, the later chain's, as the script does.
            forward, backward = (chain_a, chain_b), (chain_b, chain_a)
            dom_pair = backward if ipsae_d0dom[backward] >= ipsae_d0dom[forward] else forward
            res_pair = backward if ipsae_d0res[backward] >= ipsae_d0res[forward] else forward
            rows.append({
                "Chn1": chain_a, "Chn2": chain_b, "PAE": pae_text, "Dist": dist_text, "Type": "max",
                "ipSAE": ipsae_d0res[res_pair], "ipSAE_d0chn": max(ipsae_d0chn[forward], ipsae_d0chn[backward]),
                "ipSAE_d0dom": ipsae_d0dom[dom_pair],
                "ipTM_af": max(af_iptm(forward), af_iptm(backward)),
                "ipTM_d0chn": max(iptm_d0chn[forward], iptm_d0chn[backward]),
                "pDockQ": pdockq[backward], "pDockQ2": max(pdockq2[forward], pdockq2[backward]),
                "LIS": (lis[backward] + lis[forward]) / 2.0,
                "n0res": n0res[res_pair], "n0chn": n0chn[backward], "n0dom": n0dom[dom_pair],
                "d0res": d0res[res_pair], "d0chn": d0chn[backward], "d0dom": d0dom[dom_pair],
                "nres1": max(len(scored_residues[backward]), len(aligned_residues[forward])),
                "nres2": max(len(aligned_residues[backward]), len(scored_residues[forward])),
                "dist1": max(len(close_scored[backward]), len(close_aligned[forward])),
                "dist2": max(len(close_aligned[backward]), len(close_scored[forward])),
                "Model": model_label,
            })

    interface_residues = {
        pair: (frozenset(aligned_residues[pair]), frozenset(scored_residues[pair])) for pair in ordered_pairs
    }
    return InterfaceScores(rows, residue_rows, interface_residues, unique_chains)


# ---------------------------------------------------------------------------------------------
# Predictor outputs on disk
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Prediction:
    """One predicted complex, read from a predictor's files, ready for `score_prediction`."""

    residues: ResidueArrays
    pae_matrix: np.ndarray  # (n, n)
    plddt: np.ndarray  # (n,) token atoms, 0 to 100
    cb_plddt: np.ndarray  # (n,) CB-equivalent atoms, 0 to 100
    iptm: float | dict[str, dict[str, float]]
    predictor: str  # "alphafold2", "alphafold3", or "boltz"


def _sibling(path: Path, old: str, new: str, suffix: str | None = None) -> Path:
    name = path.name.replace(old, new)
    if suffix is not None:
        name = str(Path(name).with_suffix(suffix))
    return path.with_name(name)


def _masked(values: np.ndarray, mask: np.ndarray, label: str, *, square: bool) -> np.ndarray:
    """Keep the residue tokens of a per-token vector or matrix, cutting both to the shorter."""
    # values: (n_p,), or (n_p, n_p) when square, n_p the predictor's tokens; mask: (n_tokens,)
    length = min(len(mask), values.shape[0])
    if length != len(mask) or length != values.shape[0]:
        warnings.warn(
            f"{label}: {values.shape[0]} tokens against {len(mask)} in the structure, cut to {length}",
            stacklevel=3,
        )
    keep = mask[:length]  # (length,), n_kept true
    if square:
        return values[:length, :length][np.ix_(keep, keep)]  # (n_kept, n_kept)
    return values[:length][keep]  # (n_kept,)


def read_prediction(pae_path: str | Path, structure_path: str | Path) -> Prediction:
    """Read a predicted complex, as the script does, from the files its predictor wrote.

    - AlphaFold2: a `.pdb` structure and a scores `.json` (or `.pkl`) holding `pae` or
      `predicted_aligned_error`, `plddt`, and `iptm`. A missing ipTM is -1.0, as the script prints.
    - AlphaFold3: a `.cif` structure and its `full_data` or `confidences` `.json`, holding `pae`
      per token and `atom_plddts`. ipTM per chain pair comes from the `summary_confidences` file
      beside it, named by replacing `full_data` or `confidences`, and is 0.0 without one.
    - Boltz: a `.cif` structure and its `pae_*.npz`, with `plddt_*.npz` and `confidence_*.json`
      beside it, named by replacing `pae` in the file name. pLDDT is 0.0 without the first and
      ipTM 0.0 without the second.
    """
    pae_path, structure_path = Path(pae_path), Path(structure_path)
    # The structure holds n residue tokens among n_tokens predictor tokens. A predictor's own
    # arrays hold n_p entries, n when its files agree with the structure, and the arrays that
    # disagree in length are cut to the shortest, n_c.
    residues = read_structure(structure_path)
    chains = [str(chain) for chain in np.unique(residues.chains)]
    numres = residues.chains.shape[0]  # n
    zero_iptm = {c1: {c2: 0.0 for c2 in chains if c2 != c1} for c1 in chains}

    if structure_path.suffix.lower() == ".pdb":
        if pae_path.suffix == ".pkl":
            scores_file = np.load(pae_path, allow_pickle=True)
        else:
            scores_file = json.loads(pae_path.read_text(encoding="utf-8"))
        iptm: float | dict[str, dict[str, float]] = float(scores_file["iptm"]) if "iptm" in scores_file else -1.0
        plddt = np.array(scores_file["plddt"], dtype=float) if "plddt" in scores_file else np.zeros(numres)  # (n_p,) or (n,)
        cb_plddt = plddt  # (n_p,) or (n,)
        if "pae" in scores_file:
            pae_matrix = np.array(scores_file["pae"], dtype=float)  # (n_p, n_p)
        elif "predicted_aligned_error" in scores_file:
            pae_matrix = np.array(scores_file["predicted_aligned_error"], dtype=float)  # (n_p, n_p)
        else:
            raise ValueError(f"No PAE in AlphaFold2 scores file {pae_path}")
        predictor = "alphafold2"
    elif pae_path.suffix == ".json":
        full_data = json.loads(pae_path.read_text(encoding="utf-8"))
        if "pae" not in full_data:
            raise ValueError(f"No PAE in AlphaFold3 file {pae_path}")
        atom_plddts = np.array(full_data["atom_plddts"], dtype=float)  # (n_atoms,)
        plddt = atom_plddts[residues.token_atom_indices]  # (n,)
        cb_plddt = atom_plddts[residues.cb_atom_indices]  # (n,)
        # (n_kept, n_kept), n_kept = n when the PAE covers every token.
        pae_matrix = _masked(np.array(full_data["pae"], dtype=float), residues.token_mask, "AlphaFold3 PAE", square=True)
        iptm = zero_iptm
        summary_path = None
        if "confidences" in pae_path.name:
            summary_path = _sibling(pae_path, "confidences", "summary_confidences")
        elif "full_data" in pae_path.name:
            summary_path = _sibling(pae_path, "full_data", "summary_confidences")
        if summary_path is not None and summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            iptm = chain_pair_iptm_from_matrix(summary["chain_pair_iptm"], chains) or zero_iptm
        else:
            warnings.warn(f"No AlphaFold3 summary_confidences beside {pae_path}; ipTM_af is 0", stacklevel=2)
        predictor = "alphafold3"
    elif pae_path.suffix == ".npz":
        plddt_path = _sibling(pae_path, "pae", "plddt")
        if plddt_path.exists():
            token_plddt = 100.0 * np.array(np.load(plddt_path)["plddt"], dtype=float)  # (n_p,), 0 to 100
            plddt = _masked(token_plddt, residues.token_mask, "Boltz pLDDT", square=False)  # (n_kept,)
        else:
            plddt = np.zeros(int(residues.token_mask.sum()))  # (n,)
        cb_plddt = plddt  # (n_kept,) or (n,)
        # (n_kept, n_kept), n_kept = n when the PAE covers every token.
        pae_matrix = _masked(np.array(np.load(pae_path)["pae"], dtype=float), residues.token_mask, "Boltz PAE", square=True)
        confidence_path = _sibling(pae_path, "pae", "confidence", suffix=".json")
        iptm = zero_iptm
        if confidence_path.exists():
            confidence = json.loads(confidence_path.read_text(encoding="utf-8"))
            iptm = chain_pair_iptm_from_matrix(confidence["pair_chains_iptm"], chains) or zero_iptm
        else:
            warnings.warn(f"No Boltz confidence file beside {pae_path}; ipTM_af is 0", stacklevel=2)
        predictor = "boltz"
    else:
        raise ValueError(f"Cannot tell the predictor from {pae_path} and {structure_path}")

    arrays = _mask_to_min_length(predictor, {  # (n_c, ...) each, with pae_matrix (n_c, n_c)
        "chains": residues.chains,
        "residue_types": residues.residue_types,
        "residue_numbers": residues.residue_numbers,
        "coordinates": residues.coordinates,
        "token_atom_indices": residues.token_atom_indices,
        "cb_atom_indices": residues.cb_atom_indices,
        "plddt": np.asarray(plddt, dtype=float),
        "cb_plddt": np.asarray(cb_plddt, dtype=float),
        "pae_matrix": pae_matrix,
    })
    residues = ResidueArrays(
        chains=arrays["chains"],
        residue_types=arrays["residue_types"],
        residue_numbers=arrays["residue_numbers"],
        coordinates=arrays["coordinates"],
        token_atom_indices=arrays["token_atom_indices"],
        cb_atom_indices=arrays["cb_atom_indices"],
        token_mask=residues.token_mask,
    )
    return Prediction(residues, arrays["pae_matrix"], arrays["plddt"], arrays["cb_plddt"], iptm, predictor)


def score_prediction(
    prediction: Prediction,
    *,
    pae_cutoff: float = 10.0,
    dist_cutoff: float = 10.0,
    model_label: str = "model",
) -> InterfaceScores:
    """`interface_scores` for a `read_prediction` result."""
    residues = prediction.residues
    return interface_scores(
        prediction.pae_matrix,
        residues.chains,
        residues.residue_types,
        residues.residue_numbers,
        residues.coordinates,
        prediction.cb_plddt,
        plddt=prediction.plddt,
        iptm=prediction.iptm,
        pae_cutoff=pae_cutoff,
        dist_cutoff=dist_cutoff,
        model_label=model_label,
    )


# ---------------------------------------------------------------------------------------------
# The script's output files
# ---------------------------------------------------------------------------------------------

_TABLE_COLUMNS = (
    "Chn1", "Chn2", "PAE", "Dist", "Type", "ipSAE", "ipSAE_d0chn", "ipSAE_d0dom", "ipTM_af", "ipTM_d0chn",
    "pDockQ", "pDockQ2", "LIS", "n0res", "n0chn", "n0dom", "d0res", "d0chn", "d0dom", "nres1", "nres2",
    "dist1", "dist2", "Model",
)
_TABLE_HEADER = (
    "Chn1 Chn2  PAE Dist  Type   ipSAE    ipSAE_d0chn ipSAE_d0dom  ipTM_af  ipTM_d0chn     pDockQ     "
    "pDockQ2    LIS       n0res  n0chn  n0dom   d0res   d0chn   d0dom  nres1   nres2   dist1   dist2  Model"
)
_PYMOL_HEADER = (
    "# Chn1 Chn2  PAE Dist  Type   ipSAE    ipSAE_d0chn ipSAE_d0dom  ipTM_af  ipTM_d0chn     pDockQ     "
    "pDockQ2    LIS      n0res  n0chn  n0dom   d0res   d0chn   d0dom  nres1   nres2   dist1   dist2  Model"
)
_RESIDUE_HEADER = (
    "i   AlignChn ScoredChain  AlignResNum  AlignResType  AlignRespLDDT      n0chn  n0dom  n0res    "
    "d0chn     d0dom     d0res   ipTM_pae  ipSAE_d0chn ipSAE_d0dom    ipSAE "
)


def _text_row(row: ChainPairRow) -> str:
    """One chain-pair row as the script's fixed-width text."""
    return (
        f"{row['Chn1']}    {row['Chn2']}     {row['PAE']:3}  {row['Dist']:3}  {row['Type']:5} "
        f"{row['ipSAE']:8.6f}    {row['ipSAE_d0chn']:8.6f}    {row['ipSAE_d0dom']:8.6f}    "
        f"{row['ipTM_af']:5.3f}    {row['ipTM_d0chn']:8.6f}    {row['pDockQ']:8.4f}   "
        f"{row['pDockQ2']:8.4f}   {row['LIS']:8.4f}   {int(row['n0res']):5d}  {int(row['n0chn']):5d}  "
        f"{int(row['n0dom']):5d}  {row['d0res']:6.2f}  {row['d0chn']:6.2f}  {row['d0dom']:6.2f}  "
        f"{row['nres1']:5d}   {row['nres2']:5d}   {row['dist1']:5d}   {row['dist2']:5d}   {row['Model']}\n"
    )


def _csv_row(row: ChainPairRow) -> str:
    """One chain-pair row as comma-separated values, at the text's precision."""
    return (
        f"{row['Chn1']},{row['Chn2']},{row['PAE']},{row['Dist']},{row['Type']},"
        f"{row['ipSAE']:.6f},{row['ipSAE_d0chn']:.6f},{row['ipSAE_d0dom']:.6f},{row['ipTM_af']:5.3f},"
        f"{row['ipTM_d0chn']:.6f},{row['pDockQ']:.4f},{row['pDockQ2']:.4f},{row['LIS']:.4f},"
        f"{int(row['n0res'])},{int(row['n0chn'])},{int(row['n0dom'])},{row['d0res']:.2f},"
        f"{row['d0chn']:.2f},{row['d0dom']:.2f},{row['nres1']},{row['nres2']},{row['dist1']},"
        f"{row['dist2']},{row['Model']}\n"
    )


def _pair_groups(rows: Sequence[ChainPairRow]) -> list[list[ChainPairRow]]:
    """The chain-pair rows three at a time: each unordered pair's two asym rows and its max row."""
    if len(rows) % 3 != 0:
        raise ValueError("Chain-pair rows come three to a pair of chains")
    return [list(rows[index:index + 3]) for index in range(0, len(rows), 3)]


def format_chain_pair_table(rows: Sequence[ChainPairRow], *, style: str = "text") -> str:
    """The chain-pair table as the script writes it (`style="text"`), or as comma-separated values.

    The text is the script's `<stem>.txt` byte for byte. The CSV is property_oracles' form of it,
    which pandas reads: the same rows and precision, without padding.
    """
    if style == "text":
        header, render = _TABLE_HEADER, _text_row
    elif style == "csv":
        header, render = ",".join(_TABLE_COLUMNS), _csv_row
    else:
        raise ValueError(f"style must be 'text' or 'csv', not {style!r}")
    lines = ["\n", header + "\n"]
    for group in _pair_groups(rows):
        lines.extend(render(row) for row in group)
        lines.append("\n")
    return "".join(lines)


def format_residue_table(residue_rows: Sequence[ResidueRow]) -> str:
    """The by-residue table as the script writes it to `<stem>_byres.txt`."""
    lines = [_RESIDUE_HEADER + "\n"]
    for row in residue_rows:
        lines.append(
            f"{row['i']:<4d}    {row['AlignChn']:4}      {row['ScoredChain']:4}      {row['AlignResNum']:4d}           "
            f"{row['AlignResType']:3}        {row['AlignRespLDDT']:8.2f}         {row['n0chn']:5d}  "
            f"{row['n0dom']:5d}  {row['n0res']:5d}  {row['d0chn']:8.3f}  {row['d0dom']:8.3f}  "
            f"{row['d0res']:8.3f}   {row['ipTM_pae']:8.4f}    {row['ipSAE_d0chn']:8.4f}    "
            f"{row['ipSAE_d0dom']:8.4f}    {row['ipSAE']:8.4f}\n"
        )
    return "".join(lines)


def _contiguous_ranges(numbers: frozenset[int]) -> str | None:
    """Residue numbers as PyMOL ranges joined by '+', such as '3-7+9'; None when there are none."""
    if not numbers:
        return None
    ordered = sorted(numbers)
    ranges: list[str] = []
    start = end = ordered[0]
    for number in ordered[1:]:
        if number == end + 1:
            end = number
            continue
        ranges.append(f"{start}" if start == end else f"{start}-{end}")
        start = end = number
    ranges.append(f"{start}" if start == end else f"{start}-{end}")
    return "+".join(ranges)


def format_pymol_script(scores: InterfaceScores) -> str:
    """The PyMOL script the script writes to `<stem>.pml`: the table as comments, and one alias
    per ordered chain pair that colors the residues with an error below the PAE cutoff."""
    lines = [_PYMOL_HEADER + "\n"]
    for group in _pair_groups(scores.rows):
        asym_forward, asym_backward, max_row = group
        for row in (asym_forward, asym_backward):
            chain1, chain2 = row["Chn1"], row["Chn2"]
            lines.append("# " + _text_row(row))
            if chain1 > chain2:
                lines.append("# " + _text_row(max_row))
            aligned, scored = scores.interface_residues[(chain1, chain2)]
            color1 = _CHAIN_COLORS.get(chain1, "magenta")
            color2 = _CHAIN_COLORS.get(chain2, "marine")
            lines.append(
                f"alias color_{chain1}_{chain2}, color gray80, all; "
                f"color {color1}, chain  {chain1} and resi {_contiguous_ranges(aligned)}; "
                f"color {color2}, chain  {chain2} and resi {_contiguous_ranges(scored)}\n\n"
            )
    return "".join(lines)


def write_outputs(scores: InterfaceScores, stem: str | Path) -> dict[str, Path]:
    """Write the script's three files, `<stem>.txt`, `<stem>_byres.txt`, and `<stem>.pml`."""
    stem = str(stem)
    paths = {
        "table": Path(stem + ".txt"),
        "by_residue": Path(stem + "_byres.txt"),
        "pymol": Path(stem + ".pml"),
    }
    paths["table"].write_text(format_chain_pair_table(scores.rows), encoding="utf-8", newline="\n")
    paths["by_residue"].write_text(format_residue_table(scores.residue_rows), encoding="utf-8", newline="\n")
    paths["pymol"].write_text(format_pymol_script(scores), encoding="utf-8", newline="\n")
    return paths


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m foundry.protein.ipsae <pae file> <structure file> <pae cutoff> <dist cutoff>`.

    Writes the script's three files beside the structure, named for it and the two cutoffs, such
    as `model_0_10_10.txt`.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 4:
        print(
            "Usage: python -m foundry.protein.ipsae <pae file> <structure file> <pae cutoff> <dist cutoff>\n"
            "  AlphaFold2: scores .json and .pdb; AlphaFold3: full_data .json and .cif; Boltz: pae .npz and .cif",
            file=sys.stderr,
        )
        return 1
    pae_path, structure_path = args[0], args[1]
    pae_cutoff, dist_cutoff = float(args[2]), float(args[3])
    # The script names the model by the structure path as given, without its extension.
    suffix = Path(structure_path).suffix
    model_label = structure_path[: -len(suffix)] if suffix else structure_path
    scores = score_prediction(
        read_prediction(pae_path, structure_path),
        pae_cutoff=pae_cutoff,
        dist_cutoff=dist_cutoff,
        model_label=model_label,
    )
    write_outputs(scores, f"{model_label}_{_cutoff_text(pae_cutoff)}_{_cutoff_text(dist_cutoff)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
