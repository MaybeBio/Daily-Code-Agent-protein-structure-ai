from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from . import structures
from .config import get, tool_env
from .structures import AtomArray


# --------------------------------------------------------------------------- #
# Prediction output discovery
# --------------------------------------------------------------------------- #

@dataclass
class ModelArtifact:
    predictor: str
    structure: Path
    confidence_jsons: list[Path] = field(default_factory=list)
    pae_files: list[Path] = field(default_factory=list)
    plddt_files: list[Path] = field(default_factory=list)
    rank: int = 0
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def stem(self) -> str:
        return self.structure.stem


def _numeric_suffix(path: Path) -> int:
    import re

    matches = re.findall(r"(?:model|sample|seed)[_-]?(\d+)", path.stem)
    return int(matches[-1]) if matches else 0


def discover_models(
    predictor: str, outdir: Path, *, design: str | None = None,
    batch_summary: dict[str, dict[str, Any]] | None = None,
) -> list[ModelArtifact]:
    if predictor == "esmfold2_overlay":
        if design is not None:
            structure = outdir / "structures" / f"{design}_model.cif"
            structures = [structure] if structure.is_file() else []
        else:
            structures = sorted(outdir.glob("structures/*.cif"))
        if not structures:
            return []
        artifacts: list[ModelArtifact] = []
        for index, structure in enumerate(structures):
            name = structure.stem.removesuffix("_model")
            confidence = outdir / "confidences" / f"{name}_confidences.npz"
            npzs = [confidence] if confidence.is_file() else []
            if not npzs:
                continue
            row = (batch_summary or {}).get(name, {})
            summary = {key: row[key] for key in ("ptm", "iptm") if key in row}
            artifacts.append(
                ModelArtifact(
                    predictor=predictor,
                    structure=structure,
                    pae_files=npzs,
                    plddt_files=npzs,
                    rank=index,
                    summary=summary,
                )
            )
        return artifacts

    structures = sorted(
        [
            path
            for path in Path(outdir).rglob("*")
            if path.is_file() and path.suffix.lower() in {".cif", ".pdb"}
        ]
    )
    # AF3 also writes a top-level <job>_model.cif next to seed-*/sample-* dirs.
    # Keep the per-sample files so each diffusion sample is scored separately.
    import re

    sample_files = [
        path
        for path in structures
        if re.search(r"seed[_-]?\d+.*sample[_-]?\d+", path.parent.name)
    ]
    if sample_files:
        structures = sorted(sample_files)
    if not structures:
        return []
    all_jsons = sorted(Path(outdir).rglob("*.json"))
    all_npz = sorted(Path(outdir).rglob("*.npz"))
    artifacts: list[ModelArtifact] = []
    for structure in structures:
        stem = structure.stem
        candidates = [
            path
            for path in all_jsons
            if path.parent == structure.parent
            and (stem in path.stem or path.stem in stem)
        ]
        if not candidates:
            candidates = [path for path in all_jsons if path.parent == structure.parent]
        npz = [
            path
            for path in all_npz
            if path.parent == structure.parent
            and (stem in path.stem or path.stem in stem)
        ]
        if not npz:
            npz = [path for path in all_npz if path.parent == structure.parent]
        pae_files = [path for path in npz if "pae" in path.stem.lower()]
        plddt_files = [path for path in npz if "plddt" in path.stem.lower()]
        artifacts.append(
            ModelArtifact(
                predictor=predictor,
                structure=structure,
                confidence_jsons=candidates,
                pae_files=pae_files,
                plddt_files=plddt_files,
                rank=_numeric_suffix(structure),
            )
        )
    artifacts.sort(key=lambda item: (item.rank, str(item.structure)))
    for index, artifact in enumerate(artifacts):
        artifact.rank = index
    return artifacts


# --------------------------------------------------------------------------- #
# Confidence parsing (predictor-agnostic, with explicit AF3/Boltz/Protenix keys)
# --------------------------------------------------------------------------- #

def _iter_dicts(value: Any) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _iter_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_dicts(item)


def _load_json_docs(paths: list[Path]) -> list[Any]:
    docs: list[Any] = []
    for path in paths:
        try:
            docs.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return docs


def _find_scalar(docs: list[Any], names: set[str]) -> float | None:
    for doc in docs:
        for node in _iter_dicts(doc):
            for key, value in node.items():
                if key.lower() in names and isinstance(value, (int, float)):
                    return float(value)
    return None


def _as_matrix(value: Any) -> np.ndarray | None:
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    if array.ndim == 2 and array.shape[0] == array.shape[1] and array.shape[0] > 1:
        return array
    return None


def _find_matrix(
    docs: list[Any], key_hint: str = "pae", allow_fallback: bool = False
) -> np.ndarray | None:
    best: np.ndarray | None = None
    for doc in docs:
        for node in _iter_dicts(doc):
            for key, value in node.items():
                if key_hint in key.lower():
                    matrix = _as_matrix(value)
                    if matrix is not None:
                        return matrix
    if not allow_fallback:
        return None
    for doc in docs:
        for node in _iter_dicts(doc):
            for value in node.values():
                matrix = _as_matrix(value)
                if matrix is not None and (best is None or matrix.shape[0] > best.shape[0]):
                    best = matrix
    return best


def _find_vector(docs: list[Any], names: set[str]) -> np.ndarray | None:
    for doc in docs:
        for node in _iter_dicts(doc):
            for key, value in node.items():
                if key.lower() in names:
                    try:
                        array = np.asarray(value, dtype=float)
                    except (TypeError, ValueError):
                        continue
                    if array.ndim == 1 and array.size > 1:
                        return array
    return None


def _load_npz_value(paths: list[Path], key_hint: str) -> np.ndarray | None:
    for path in paths:
        try:
            with np.load(path, allow_pickle=True) as data:
                keys = list(data.keys())
                for key in keys:
                    if key_hint in key.lower():
                        return np.asarray(data[key], dtype=float)
                if key_hint == "pae":
                    for key in keys:
                        array = np.asarray(data[key], dtype=float)
                        if array.ndim >= 2:
                            return array
                for key in keys:
                    array = np.asarray(data[key], dtype=float)
                    if array.ndim == 1 and array.size > 1:
                        return array
        except (OSError, ValueError):
            continue
    return None


def _normalise_plddt(values: np.ndarray | None) -> np.ndarray | None:
    if values is None:
        return None
    finite = values[np.isfinite(values)]
    if finite.size and float(np.nanmax(finite)) <= 1.5:
        return values * 100.0
    return values


def _tokens_from_json(docs: list[Any]) -> tuple[list[str], list[int]] | None:
    chain_ids: list[str] | None = None
    res_ids: list[int] | None = None
    for doc in docs:
        for node in _iter_dicts(doc):
            for key, value in node.items():
                lower = key.lower()
                if lower in {"token_chain_ids", "chain_ids"} and isinstance(value, list):
                    candidate = [str(item) for item in value]
                    if chain_ids is None or len(candidate) > len(chain_ids):
                        chain_ids = candidate
                if lower in {"token_res_ids", "residue_ids"} and isinstance(value, list):
                    try:
                        candidate_int = [int(item) for item in value]
                    except (TypeError, ValueError):
                        continue
                    if res_ids is None or len(candidate_int) > len(res_ids):
                        res_ids = candidate_int
    if chain_ids and res_ids and len(chain_ids) == len(res_ids):
        return chain_ids, res_ids
    return None


def _tokens_from_structure(array: AtomArray, size: int) -> tuple[list[str], list[int]] | None:
    polymers = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS",
                "ILE", "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP",
                "TYR", "VAL", "MSE", "DA", "DC", "DG", "DT", "A", "C", "G", "U"}
    residues = [
        (str(chain), int(res_id))
        for chain, res_id, res_name in zip(
            array.chain_id.tolist(), array.res_id.tolist(), array.res_name.tolist()
        )
        if str(res_name).upper() in polymers
    ]
    residues = list(dict.fromkeys(residues))
    if len(residues) == size:
        return [item[0] for item in residues], [item[1] for item in residues]
    atoms = [(str(chain), index) for index, chain in enumerate(array.chain_id.tolist())]
    if len(atoms) == size:
        return [item[0] for item in atoms], [item[1] for item in atoms]
    return None


def _chain_groups(tokens: tuple[list[str], list[int]]) -> dict[str, list[int]]:
    chains, _res = tokens
    groups: dict[str, list[int]] = {}
    for index, chain in enumerate(chains):
        groups.setdefault(chain, []).append(index)
    return groups


def _mean(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    return float(finite.mean()) if finite.size else float("nan")


def _pair_key(a: str, b: str) -> str:
    return f"{a}|{b}"


def _chain_pair_matrix(docs: list[Any], chains: list[str]) -> np.ndarray | None:
    for doc in docs:
        for node in _iter_dicts(doc):
            for key, value in node.items():
                lower = key.lower()
                if "chain_pair_iptm" in lower or "pair_chains_iptm" in lower:
                    matrix = _as_matrix(value)
                    if matrix is not None and matrix.shape[0] == len(chains):
                        return matrix
    return None


def _parse_usalign_output(text: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("TM-score=") and "tm_score" not in metrics:
            try:
                metrics["tm_score"] = float(stripped.split("=")[1].split()[0])
            except (IndexError, ValueError):
                pass
        if "RMSD=" in stripped and "rmsd" not in metrics:
            try:
                metrics["rmsd"] = float(stripped.split("RMSD=")[1].split(",")[0].strip())
            except (IndexError, ValueError):
                pass
    return metrics


class USalign:
    def __init__(self, cfg: dict[str, Any]):
        self.binary = get(cfg, "usalign.binary")
        self.clean_ld = bool(get(cfg, "usalign.clean_ld_library_path", True))

    def run(self, mobile: Path, target: Path) -> dict[str, float]:
        if not self.binary or not Path(self.binary).is_file():
            return {"error": "usalign binary missing"}
        env = tool_env({}, clean_ld=self.clean_ld)
        result = subprocess.run(
            [str(self.binary), str(mobile), str(target)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=300,
            check=False,
        )
        return _parse_usalign_output(result.stdout)

    def run_chains(
        self, mobile: AtomArray, target: AtomArray, chain_pairs: list[tuple[str, str]]
    ) -> dict[str, dict[str, float]]:
        results: dict[str, dict[str, float]] = {}
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            for pred_chain, ref_chain in chain_pairs:
                pred = structures.extract_chain(mobile, pred_chain)
                ref = structures.extract_chain(target, ref_chain)
                if pred.array_length() == 0 or ref.array_length() == 0:
                    results[_pair_key(pred_chain, ref_chain)] = {
                        "error": "missing chain"
                    }
                    continue
                pred_path = structures.save_structure_file(
                    tmpdir / f"pred_{pred_chain}.pdb", pred
                )
                ref_path = structures.save_structure_file(
                    tmpdir / f"ref_{ref_chain}.pdb", ref
                )
                results[_pair_key(pred_chain, ref_chain)] = self.run(pred_path, ref_path)
        return results


# --------------------------------------------------------------------------- #
# Interface / geometry metrics
# --------------------------------------------------------------------------- #

def _token_index_lookup(tokens: tuple[list[str], list[int]] | None) -> dict[tuple[str, int], list[int]]:
    if tokens is None:
        return {}
    lookup: dict[tuple[str, int], list[int]] = {}
    for index, (chain, res_id) in enumerate(zip(*tokens)):
        lookup.setdefault((chain, res_id), []).append(index)
    return lookup


def _interface_metrics(
    array: AtomArray,
    pae: np.ndarray | None,
    tokens: tuple[list[str], list[int]] | None,
    chain_a: str,
    chain_b: str,
    contact_cutoff: float,
    pae_cutoff: float,
) -> dict[str, float]:
    pairs = structures.interface_residue_pairs(array, chain_a, chain_b, contact_cutoff)
    result: dict[str, float] = {
        "n_interface_residues_a": float(len({pair[0] for pair in pairs})),
        "n_interface_residues_b": float(len({pair[1] for pair in pairs})),
        "delta_sasa": float("nan"),
        "sc_approx": float("nan"),
        "sc_fraction": float("nan"),
        "ipae": float("nan"),
        "ipsae_ref": float("nan"),
    }
    if not pairs:
        return result

    complex_sasa = structures.total_sasa(array)
    a_sasa = structures.total_sasa(structures.extract_chain(array, chain_a))
    b_sasa = structures.total_sasa(structures.extract_chain(array, chain_b))
    result["delta_sasa"] = float(a_sasa + b_sasa - complex_sasa)

    pair_distances = np.asarray([pair[2] for pair in pairs], dtype=float)
    lookup = _token_index_lookup(tokens)
    if pae is not None and lookup:
        pae_values: list[float] = []
        weighted: list[float] = []
        n_interface = max(len(pairs), 1)
        d0 = max(1.24 * (n_interface - 15) ** (1 / 3) - 1.8, 1.0) if n_interface > 15 else 1.0
        for key_a, key_b, distance in pairs:
            indices_a = lookup.get((chain_a, int(key_a.split(":")[1])), [])
            indices_b = lookup.get((chain_b, int(key_b.split(":")[1])), [])
            if not indices_a or not indices_b:
                continue
            block = pae[np.ix_(indices_a, indices_b)]
            block_reverse = pae[np.ix_(indices_b, indices_a)]
            value = float(np.nanmean(np.concatenate([block.ravel(), block_reverse.ravel()])))
            pae_values.append(value)
            weight = 1.0 / max(d0, 1e-6) ** 2 * 1.0 / (1.0 + (distance / d0) ** 2)
            weighted.append((1.0 / max(value, 1e-6)) * weight)
        if pae_values:
            result["ipae"] = float(np.mean(pae_values))
            result["ipsae_ref"] = float(np.mean(weighted) * 100.0)

    sc, fraction = _shape_complementarity(array, chain_a, chain_b, contact_cutoff)
    result["sc_approx"] = sc
    result["sc_fraction"] = fraction
    return result


def _shape_complementarity(
    array: AtomArray, chain_a: str, chain_b: str, cutoff: float
) -> tuple[float, float]:
    """Approximate shape complementarity from local surface normals.

    This is not the Lawrence-Colman statistic. Surface normals are estimated
    from the local centre of mass of atoms within 10 A; complementary contacts
    have opposing normals, so ``dot(n_a, -n_b)`` is averaged over close pairs.
    Values in [-1, 1]; 1 means perfectly complementary.
    """
    a = structures.heavy_atoms(structures.extract_chain(array, chain_a))
    b = structures.heavy_atoms(structures.extract_chain(array, chain_b))
    if a.array_length() < 10 or b.array_length() < 10:
        return float("nan"), float("nan")
    from scipy.spatial import cKDTree

    def normals(atoms: AtomArray) -> np.ndarray:
        tree = cKDTree(atoms.coord)
        neighbours = tree.query_ball_point(atoms.coord, r=10.0)
        result = np.zeros_like(atoms.coord)
        for index, hits in enumerate(neighbours):
            if len(hits) < 3:
                continue
            local_centroid = atoms.coord[hits].mean(axis=0)
            vector = atoms.coord[index] - local_centroid
            norm = np.linalg.norm(vector)
            if norm > 1e-6:
                result[index] = vector / norm
        return result

    normals_a = normals(a)
    normals_b = normals(b)
    tree = cKDTree(b.coord)
    dots: list[float] = []
    neighbours = tree.query_ball_point(a.coord, r=cutoff)
    for index, hits in enumerate(neighbours):
        if not hits:
            continue
        for hit in hits:
            dots.append(float(np.dot(normals_a[index], -normals_b[hit])))
    if not dots:
        return float("nan"), float("nan")
    values = np.asarray(dots, dtype=float)
    return float(values.mean()), float((values > 0).mean())


# --------------------------------------------------------------------------- #
# Physicochemical properties
# --------------------------------------------------------------------------- #

def physchem(sequence: str) -> dict[str, float]:
    from Bio.SeqUtils.ProtParam import ProteinAnalysis

    if not sequence:
        return {}
    analysis = ProteinAnalysis(sequence)
    hydrophobic = set("AVILMFWY")
    longest = current = 0
    for residue in sequence:
        current = current + 1 if residue in hydrophobic else 0
        longest = max(longest, current)
    return {
        "length": float(len(sequence)),
        "molecular_weight_kda": float(analysis.molecular_weight() / 1000.0),
        "gravy": float(analysis.gravy()),
        "isoelectric_point": float(analysis.isoelectric_point()),
        "charge_ph7_4": float(analysis.charge_at_pH(7.4)),
        "aromaticity": float(analysis.aromaticity()),
        "instability_index": float(analysis.instability_index()),
        "helix_fraction": float(analysis.secondary_structure_fraction()[0]),
        "turn_fraction": float(analysis.secondary_structure_fraction()[1]),
        "sheet_fraction": float(analysis.secondary_structure_fraction()[2]),
        "cysteine_count": float(sequence.count("C")),
        "n_glycosylation_sequons": float(
            sum(1 for index in range(len(sequence) - 2)
                if sequence[index] == "N" and sequence[index + 1] != "P"
                and sequence[index + 2] in "ST")
        ),
        "hydrophobic_fraction": float(sum(residue in hydrophobic for residue in sequence) / len(sequence)),
        "longest_hydrophobic_stretch": float(longest),
        "low_complexity_fraction": float(_low_complexity_fraction(sequence)),
    }


def _low_complexity_fraction(sequence: str, window: int = 12) -> float:
    if len(sequence) < window:
        return 0.0
    low = 0
    for start in range(len(sequence) - window + 1):
        chunk = sequence[start : start + window]
        if len(set(chunk)) <= 5:
            low += 1
    return low / (len(sequence) - window + 1)


# --------------------------------------------------------------------------- #
# Per-model scoring
# --------------------------------------------------------------------------- #

def score_model(
    artifact: ModelArtifact,
    cfg: dict[str, Any],
    backbone: Path | None,
    align_chain_pairs: list[tuple[str, str]],
    motif: list[dict] | None = None,
) -> dict[str, Any]:
    nonfinite = structures.count_nonfinite_atoms(artifact.structure)
    if nonfinite:
        return {
            "predictor": artifact.predictor,
            "model_rank": artifact.rank,
            "structure": str(artifact.structure),
            "error": f"{nonfinite} atoms with non-finite coordinates",
            "ranking_score": -1.0,
        }
    array = structures.load_structure_file(artifact.structure)
    docs = _load_json_docs(artifact.confidence_jsons)
    if artifact.summary:
        docs.append(artifact.summary)
    pae = _find_matrix(docs, "pae")
    if pae is None:
        pae = _load_npz_value(artifact.pae_files, "pae")
        if pae is not None and pae.ndim > 2:
            pae = pae.reshape(pae.shape[-2], pae.shape[-1])
    plddt = _find_vector(
        docs, {"atom_plddts", "atom_plddt", "plddt", "token_plddt"}
    )
    if plddt is None:
        plddt = _load_npz_value(artifact.plddt_files, "plddt")
    if plddt is None:
        # ESMFold writes pLDDT into the PDB B-factor column and no JSON.
        b_factor = structures.pdb_b_factors(artifact.structure)
        if (
            b_factor is not None
            and b_factor.size == array.array_length()
            and np.nanmax(b_factor) <= 100.0
            and np.nanmin(b_factor) >= 0.0
        ):
            plddt = b_factor
    plddt = _normalise_plddt(plddt)
    scalar_plddt = _find_scalar(docs, {"plddt", "mean_plddt", "complex_plddt"})
    if scalar_plddt is not None:
        scalar_plddt = float(scalar_plddt * 100.0 if scalar_plddt <= 1.5 else scalar_plddt)

    tokens = _tokens_from_json(docs)
    if tokens is None and pae is not None:
        tokens = _tokens_from_structure(array, pae.shape[0])

    chains = structures.chain_ids(array)
    groups = _chain_groups(tokens) if tokens else {}
    mean_pae = _mean(pae) if pae is not None else float("nan")
    mean_plddt = _mean(plddt) if plddt is not None else (
        scalar_plddt if scalar_plddt is not None else float("nan")
    )
    ptm = _find_scalar(docs, {"ptm"})
    iptm = _find_scalar(docs, {"iptm"})
    if iptm is None:
        pair_matrix = _chain_pair_matrix(docs, chains)
        if pair_matrix is not None and pair_matrix.shape[0] > 1:
            off_diagonal = pair_matrix[~np.eye(pair_matrix.shape[0], dtype=bool)]
            iptm = _mean(off_diagonal)
    if ptm is None and mean_pae == mean_pae:
        ptm = float("nan")

    per_chain: dict[str, dict[str, float]] = {}
    chain_ptm = _find_vector(docs, {"chain_ptm", "chains_ptm"}) if docs else None
    chain_plddt = _find_vector(docs, {"chain_plddt"}) if docs else None
    for index, chain in enumerate(chains):
        entry: dict[str, float] = {}
        if chain_ptm is not None and index < len(chain_ptm):
            entry["ptm"] = float(chain_ptm[index])
        if plddt is not None:
            if plddt.size == array.array_length():
                mask = array.chain_id == chain
                entry["plddt"] = _mean(plddt[mask])
            elif tokens is not None and chain in groups:
                entry["plddt"] = _mean(plddt[groups[chain]])
            elif plddt.size > index:
                entry["plddt"] = float(plddt[index])
        elif chain_plddt is not None and index < len(chain_plddt):
            entry["plddt"] = float(chain_plddt[index])
        elif scalar_plddt is not None:
            entry["plddt"] = scalar_plddt
        if pae is not None and chain in groups:
            indices = groups[chain]
            entry["mean_pae"] = _mean(pae[np.ix_(indices, indices)])
        per_chain[chain] = entry

    chain_pairs: dict[str, dict[str, float]] = {}
    pair_matrix = _chain_pair_matrix(docs, chains)
    contact_cutoff = float(get(cfg, "metrics.contact_cutoff", 5.0))
    pae_cutoff = float(get(cfg, "metrics.pae_interface_cutoff", 10.0))
    for i, chain_a in enumerate(chains):
        for j, chain_b in enumerate(chains):
            if j <= i:
                continue
            entry = _interface_metrics(
                array, pae, tokens, chain_a, chain_b, contact_cutoff, pae_cutoff
            )
            if pair_matrix is not None and pair_matrix.shape[0] == len(chains):
                entry["iptm"] = float(pair_matrix[i, j])
                entry["iptm_reverse"] = float(pair_matrix[j, i])
            chain_pairs[_pair_key(chain_a, chain_b)] = entry

    usalign_result: dict[str, Any] = {}
    if backbone is not None and Path(backbone).is_file():
        usalign = USalign(cfg)
        usalign_result["global"] = usalign.run(artifact.structure, Path(backbone))
        present = set(chains)
        safe_pairs = [
            (pred if pred in present else chains[0], ref)
            for pred, ref in align_chain_pairs
        ] if chains else []
        usalign_result["per_chain"] = usalign.run_chains(
            array, structures.load_structure_file(backbone), safe_pairs
        )
        if motif:
            usalign_result["motif"] = _motif_rmsd(array, backbone, motif)

    # Best-effort docking-style interface score: ipTM and interface PAE.
    score = _ranking_score(iptm, ptm, mean_plddt, mean_pae, cfg)

    return {
        "predictor": artifact.predictor,
        "model_rank": artifact.rank,
        "structure": str(artifact.structure),
        "ptm": ptm,
        "iptm": iptm,
        "mean_pae": mean_pae,
        "mean_plddt": mean_plddt,
        "per_chain": per_chain,
        "chain_pairs": chain_pairs,
        "usalign": usalign_result,
        "physchem": physchem(structures.chain_sequence(array, chains[0])) if chains else {},
        "ranking_score": score,
    }


def _ranking_score(
    iptm: float | None,
    ptm: float | None,
    mean_plddt: float,
    mean_pae: float,
    cfg: dict[str, Any],
) -> float:
    weights = get(cfg, "metrics.weights", {}) or {}
    pae_score = max(0.0, 1.0 - mean_pae / 31.75) if mean_pae == mean_pae else 0.0
    return float(
        weights.get("iptm", 0.45) * (iptm if iptm is not None and iptm == iptm else 0.0)
        + weights.get("ptm", 0.20) * (ptm if ptm is not None and ptm == ptm else 0.0)
        + weights.get("plddt", 0.20) * (mean_plddt / 100.0 if mean_plddt == mean_plddt else 0.0)
        + weights.get("pae", 0.15) * pae_score
    )


def _motif_rmsd(
    predicted: AtomArray, backbone: Path, motif: list[dict]
) -> dict[str, Any]:
    reference = structures.load_structure_file(backbone)
    results: dict[str, Any] = {}
    for spec in motif:
        chain = str(spec["chain"])
        residue_ids = [int(item) for item in spec.get("res_ids", [])]
        if not residue_ids:
            continue
        pred = structures.ca_coordinates(predicted, chain, residue_ids)
        ref = structures.ca_coordinates(reference, chain, residue_ids)
        shared = sorted(set(pred) & set(ref))
        if not shared:
            results[chain] = {"rmsd": float("nan"), "n_residues": 0}
            continue
        mobile = np.stack([pred[item] for item in shared])
        target = np.stack([ref[item] for item in shared])
        results[chain] = {
            "rmsd": structures.kabsch_rmsd(mobile, target),
            "n_residues": len(shared),
        }
    return results
