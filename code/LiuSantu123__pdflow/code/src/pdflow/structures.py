from __future__ import annotations

from pathlib import Path

import numpy as np
from biotite.structure import AtomArray, sasa
from biotite.structure.io import load_structure, save_structure

WATER = {"HOH", "WAT", "DOD"}
HYDROGEN = {"H", "D", "T"}

THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "MSE": "M", "SEC": "U", "PYL": "O", "HSD": "H", "HSE": "H",
    "HSP": "H", "HID": "H", "HIE": "H", "HIP": "H", "CYX": "C",
    "ASH": "D", "GLH": "E", "LYN": "K",
    "DA": "A", "DC": "C", "DG": "G", "DT": "T", "DI": "I",
    "A": "A", "C": "C", "G": "G", "U": "U", "I": "I",
}

PROTEIN_RESIDUES = {
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS",
    "ILE", "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP",
    "TYR", "VAL", "MSE", "SEC", "PYL", "HSD", "HSE", "HSP", "HID",
    "HIE", "HIP", "CYX", "ASH", "GLH", "LYN",
}
DNA_RESIDUES = {"DA", "DC", "DG", "DT", "DI"}
RNA_RESIDUES = {"A", "C", "G", "U", "I"}


def load_structure_file(path: str | Path, drop_nonfinite: bool = True) -> AtomArray:
    array = load_structure(str(path))
    if array is None:
        raise ValueError(f"could not read structure: {path}")
    if array.array_length() == 0:
        raise ValueError(f"empty structure: {path}")
    if drop_nonfinite:
        finite = np.isfinite(array.coord).all(axis=1)
        if not finite.all():
            array = array[finite]
    return array


def count_nonfinite_atoms(path: str | Path) -> int:
    array = load_structure(str(path))
    if array is None or array.array_length() == 0:
        return 0
    finite = np.isfinite(array.coord).all(axis=1)
    return int((~finite).sum())


def pdb_b_factors(path: str | Path) -> np.ndarray | None:
    """B-factor column of a PDB file (ESMFold stores pLDDT there)."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    values: list[float] = []
    for line in lines:
        if line.startswith(("ATOM  ", "HETATM")):
            try:
                values.append(float(line[60:66]))
            except ValueError:
                values.append(0.0)
    return np.asarray(values, dtype=float) if values else None


def save_structure_file(path: str | Path, array: AtomArray) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_structure(str(path), array)
    return path


def heavy_atoms(array: AtomArray) -> AtomArray:
    elements = np.char.upper(array.element.astype(str))
    keep = ~np.isin(elements, list(HYDROGEN))
    keep &= ~np.isin(array.res_name, list(WATER))
    return array[keep]


def chain_ids(array: AtomArray) -> list[str]:
    return [str(item) for item in dict.fromkeys(array.chain_id.tolist())]


def chain_kind(array: AtomArray, chain: str) -> str:
    names = {
        str(name).upper() for name in array.res_name[array.chain_id == chain].tolist()
    }
    if names & PROTEIN_RESIDUES:
        return "protein"
    if names & DNA_RESIDUES:
        return "dna"
    if names & RNA_RESIDUES:
        return "rna"
    return "ligand"


def extract_chains(array: AtomArray, chains: list[str]) -> AtomArray:
    return array[np.isin(array.chain_id, chains)]


def extract_chain(array: AtomArray, chain: str) -> AtomArray:
    return array[array.chain_id == chain]


def chain_sequence(array: AtomArray, chain: str) -> str:
    sub = array[array.chain_id == chain]
    residues: list[str] = []
    seen: set[tuple[int, str]] = set()
    for res_id, res_name in zip(sub.res_id.tolist(), sub.res_name.tolist()):
        key = (int(res_id), str(res_name))
        if key in seen:
            continue
        seen.add(key)
        residues.append(THREE_TO_ONE.get(str(res_name).upper(), "X"))
    return "".join(residues)


def chain_sequences(array: AtomArray) -> dict[str, str]:
    return {chain: chain_sequence(array, chain) for chain in chain_ids(array)}


def chain_residues(array: AtomArray, chain: str) -> list[tuple[int, str, str]]:
    """[(res_id, res_name, one_letter), ...] in file order."""
    sub = array[array.chain_id == chain]
    residues: list[tuple[int, str, str]] = []
    seen: set[tuple[int, str]] = set()
    for res_id, res_name in zip(sub.res_id.tolist(), sub.res_name.tolist()):
        key = (int(res_id), str(res_name))
        if key in seen:
            continue
        seen.add(key)
        residues.append(
            (int(res_id), str(res_name), THREE_TO_ONE.get(str(res_name).upper(), "X"))
        )
    return residues


def residue_key_array(array: AtomArray) -> np.ndarray:
    return np.asarray(
        [f"{chain}:{int(res_id)}" for chain, res_id in zip(array.chain_id, array.res_id)]
    )


def interface_residue_pairs(
    array: AtomArray,
    chain_a: str,
    chain_b: str,
    cutoff: float = 5.0,
) -> list[tuple[str, str, float]]:
    """Heavy-atom residue pairs closer than ``cutoff``.

    Returns [(residue_key_a, residue_key_b, min_distance), ...].
    """
    from scipy.spatial import cKDTree

    a = heavy_atoms(extract_chain(array, chain_a))
    b = heavy_atoms(extract_chain(array, chain_b))
    if a.array_length() == 0 or b.array_length() == 0:
        return []
    tree = cKDTree(b.coord)
    pairs: dict[tuple[str, str], float] = {}
    neighbours = tree.query_ball_point(a.coord, r=cutoff)
    for atom_index, hits in enumerate(neighbours):
        if not hits:
            continue
        key_a = f"{chain_a}:{int(a.res_id[atom_index])}"
        for hit in hits:
            distance = float(np.linalg.norm(a.coord[atom_index] - b.coord[hit]))
            key_b = f"{chain_b}:{int(b.res_id[hit])}"
            previous = pairs.get((key_a, key_b))
            if previous is None or distance < previous:
                pairs[(key_a, key_b)] = distance
    return [(key_a, key_b, dist) for (key_a, key_b), dist in sorted(pairs.items())]


def total_sasa(array: AtomArray, probe: float = 1.4) -> float:
    if array.array_length() == 0:
        return 0.0
    values = sasa(heavy_atoms(array), probe_radius=probe)
    return float(np.nansum(values))


def per_chain_sasa(array: AtomArray, probe: float = 1.4) -> dict[str, float]:
    return {
        chain: total_sasa(extract_chain(array, chain), probe=probe)
        for chain in chain_ids(array)
    }


def kabsch_rmsd(mobile: np.ndarray, target: np.ndarray) -> float:
    """RMSD after optimal superposition (no reflection)."""
    mobile = np.asarray(mobile, dtype=float)
    target = np.asarray(target, dtype=float)
    if mobile.shape != target.shape or mobile.shape[0] == 0:
        return float("nan")
    mobile_centroid = mobile.mean(axis=0)
    target_centroid = target.mean(axis=0)
    mobile_centered = mobile - mobile_centroid
    target_centered = target - target_centroid
    covariance = mobile_centered.T @ target_centered
    v, _s, wt = np.linalg.svd(covariance)
    determinant = np.linalg.det(v @ wt)
    correction = np.eye(3)
    correction[2, 2] = 1.0 if determinant > 0 else -1.0
    rotation = v @ correction @ wt
    aligned = mobile_centered @ rotation
    return float(np.sqrt(((aligned - target_centered) ** 2).sum(axis=1).mean()))


def ca_coordinates(
    array: AtomArray, chain: str, residue_ids: list[int] | None = None
) -> dict[int, np.ndarray]:
    sub = array[(array.chain_id == chain) & (array.atom_name == "CA")]
    wanted = set(residue_ids) if residue_ids is not None else None
    result: dict[int, np.ndarray] = {}
    for res_id, coord in zip(sub.res_id.tolist(), sub.coord):
        res_id = int(res_id)
        if wanted is None or res_id in wanted:
            result[res_id] = np.asarray(coord, dtype=float)
    return result


def shared_residue_rmsd(
    predicted: AtomArray,
    reference: AtomArray,
    pred_chain: str,
    ref_chain: str,
    residue_ids: list[int] | None = None,
) -> tuple[float, int]:
    pred = ca_coordinates(predicted, pred_chain, residue_ids)
    ref = ca_coordinates(reference, ref_chain, residue_ids)
    shared = sorted(set(pred) & set(ref))
    if not shared:
        return float("nan"), 0
    mobile = np.stack([pred[res_id] for res_id in shared])
    target = np.stack([ref[res_id] for res_id in shared])
    return kabsch_rmsd(mobile, target), len(shared)
