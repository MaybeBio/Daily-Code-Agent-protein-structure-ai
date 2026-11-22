"""Local sequence folding, blind pocket prediction, and Vina docking."""
import hashlib
import logging
import tempfile
import csv
import json
import math
import os
import shutil
import subprocess
import threading
from pathlib import Path

from cpi_data import ROOT
from cpi_docking import dock_generated


MODEL_ID = "facebook/esmfold_v1"
MAX_SEQUENCE_LENGTH = 1022
MAX_DOCKED_POCKETS = 8
_fold_lock = threading.Lock()


def select_folding_window(sequence: str, max_length: int = MAX_SEQUENCE_LENGTH) -> tuple[str, int, int, str]:
    """Select the most biologically relevant window of up to max_length residues.

    Returns (window_sequence, start_index_0_based, end_index_0_based, reason).
    """
    seq_len = len(sequence)
    if seq_len <= max_length:
        return sequence, 0, seq_len, "full_sequence"

    # Step 1: Detect protein kinase catalytic domain signatures
    # Look for DFG motif (activation loop) and HRD motif (catalytic loop)
    import re

    dfg_matches = [m.start() for m in re.finditer(r"(?:[LIVMF]DFG|DFG)", sequence)]
    hrd_matches = [m.start() for m in re.finditer(r"(?:H[RKG]D[LIVMF]K|HRD)", sequence)]

    candidate_scores = []
    for d_idx in dfg_matches:
        # Check if there is an upstream HRD motif (canonical distance is 15-45 residues)
        paired_hrd = [h for h in hrd_matches if 15 <= (d_idx - h) <= 45]
        score = 10.0
        if paired_hrd:
            score += 20.0
        # In multi-domain kinases (e.g. JAK1, TYK2), active catalytic domain is downstream of pseudokinase
        score += (d_idx / seq_len) * 5.0
        candidate_scores.append((score, d_idx, "DFG activation loop"))

    for h_idx in hrd_matches:
        score = 8.0 + (h_idx / seq_len) * 5.0
        candidate_scores.append((score, h_idx, "HRD catalytic loop"))

    # Walker A / ATP-binding P-loop: GxGxxG
    for p_match in re.finditer(r"G[A-Z]G[A-Z]{2}G", sequence):
        candidate_scores.append((5.0, p_match.start(), "ATP-binding P-loop"))

    if candidate_scores:
        candidate_scores.sort(key=lambda x: x[0], reverse=True)
        best_score, target_idx, motif_name = candidate_scores[0]
        # Center the window of max_length around target_idx
        start = max(0, min(target_idx - max_length // 2, seq_len - max_length))
        end = start + max_length
        reason = f"Centered on {motif_name} at residue {target_idx + 1} (residues {start + 1}-{end} of {seq_len})"
        return sequence[start:end], start, end, reason

    # Step 2: Default to C-terminal domain (standard for multidomain receptors/kinases)
    start = seq_len - max_length
    end = seq_len
    reason = f"C-terminal functional domain (residues {start + 1}-{end} of {seq_len})"
    return sequence[start:end], start, end, reason


def structure_home():
    configured = os.environ.get("CPI_STRUCTURE_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "cpi-fold-gpu"
    return Path.home() / ".cache" / "cpi-fold-gpu"


def _run_logged(command, log_path, label, timeout, cwd=None, env=None):
    try:
        with log_path.open("w", encoding="utf-8") as log:
            result = subprocess.run(
                [str(part) for part in command],
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    except subprocess.TimeoutExpired as exc:
        with log_path.open("a", encoding="utf-8") as log:
            log.write("\nTimed out.\n")
        raise RuntimeError(f"{label} timed out. See {log_path.name} for details.") from exc
    if result.returncode:
        detail = log_path.read_text(encoding="utf-8")[-1200:].strip()
        raise RuntimeError(f"{label} failed. See {log_path.name}. {detail}")
    return ""


def _run_fold_logged(command, log_path, timeout, cwd, env):
    with _fold_lock:
        return _run_logged(command, log_path, "ESMFold sequence prediction", timeout, cwd=cwd, env=env)


def _read_pockets(path):
    pockets = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            row = {key.strip(): (value or "").strip() for key, value in raw.items() if key}
            try:
                pocket = {
                    "rank": int(row["rank"]),
                    "score": float(row["score"]),
                    "probability": float(row["probability"]),
                    "center": [float(row["center_x"]), float(row["center_y"]), float(row["center_z"])],
                    "residue_ids": row.get("residue_ids", ""),
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"P2Rank produced an invalid pocket row in {path.name}.") from exc
            if not all(math.isfinite(value) for value in pocket["center"] + [pocket["score"], pocket["probability"]]):
                continue
            if not 0 <= pocket["probability"] <= 1:
                continue
            pockets.append(pocket)
    pockets.sort(key=lambda pocket: pocket["rank"])
    return pockets


def fold_and_rank(sequence, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if not sequence:
        raise ValueError("Sequence cannot be empty.")

    fold_sequence, win_start, win_end, win_reason = select_folding_window(sequence, MAX_SEQUENCE_LENGTH)

    home = structure_home()
    python = Path(os.environ.get(
        "CPI_STRUCTURE_PYTHON",
        str(home / ("Scripts/python.exe" if os.name == "nt" else "bin/python")),
    )).expanduser()
    if not python.is_file():
        raise RuntimeError("The local CUDA folding environment is missing. Run scripts/setup_structure_models.ps1.")

    p2rank_home = Path(os.environ.get("CPI_P2RANK_HOME", str(home / "p2rank_2.5.1"))).expanduser()
    p2rank_jar = p2rank_home / "bin" / "p2rank.jar"
    if not p2rank_jar.is_file():
        raise RuntimeError("P2Rank is missing. Run scripts/setup_structure_models.ps1.")
    java = shutil.which("java")
    if not java:
        raise RuntimeError("Java 17 or newer is required for local P2Rank pocket prediction.")

    request_path = folder / "fold_request.json"
    protein_path = folder / "protein.pdb"
    fold_metadata_path = folder / "fold_metadata.json"
    request_payload = {
        "sequence": fold_sequence,
        "full_sequence": sequence,
        "window_start": win_start + 1,
        "window_end": win_end,
        "window_reason": win_reason,
    }
    request_path.write_text(json.dumps(request_payload), encoding="utf-8")
    env = os.environ.copy()
    env["CPI_STRUCTURE_HOME"] = str(home)
    env["HF_HOME"] = str(home / "huggingface")
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    _run_fold_logged(
        [
            python,
            ROOT / "scripts" / "predict_esmfold.py",
            "--request",
            request_path,
            "--output",
            protein_path,
            "--metadata",
            fold_metadata_path,
            "--offload",
            home / "offload" / folder.name,
        ],
        folder / "fold.log",
        timeout=6 * 60 * 60,
        cwd=ROOT,
        env=env,
    )
    fold_metadata = json.loads(fold_metadata_path.read_text(encoding="utf-8"))

    p2rank_out = folder / "p2rank"
    p2rank_out.mkdir(exist_ok=True)
    classpath = f"{p2rank_home / 'bin' / 'p2rank.jar'};{p2rank_home / 'bin' / 'lib' / '*'}"
    _run_logged(
        [
            java,
            "-Xmx2048m",
            "-cp",
            classpath,
            "cz.siret.prank.program.Main",
            "predict",
            "-f",
            protein_path,
            "-o",
            p2rank_out,
            "-threads",
            "2",
            "-visualizations",
            "0",
        ],
        folder / "p2rank.log",
        "P2Rank blind pocket prediction",
        timeout=20 * 60,
        cwd=p2rank_home,
    )
    predictions_path = p2rank_out / "protein.pdb_predictions.csv"
    pockets = _read_pockets(predictions_path)
    if not pockets:
        raise RuntimeError("P2Rank did not identify a usable pocket in the folded structure.")

    return pockets, dict(protein_source=MODEL_ID, pocket_source="P2Rank predicted pockets",
                         fold=fold_metadata, sequence_window=dict(original_sequence_length=len(sequence),
                         folded_length=len(fold_sequence), window_start=win_start+1, window_end=win_end,
                         window_reason=win_reason, is_windowed=len(sequence)!=len(fold_sequence)))


_cache_guard = threading.Lock()
_cache_locks = {}


def predict_and_dock(smiles, sequence, folder, force_rebuild=False):
    from cpi_experimental import lookup, candidate_sites
    from cpi_docking import run
    import sys
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    import time
    started=time.perf_counter()
    found = lookup(smiles, sequence)
    key = hashlib.sha256(sequence.encode()).hexdigest()
    # Different experimental templates for a sequence must keep distinct pockets.
    variant = hashlib.sha256(json.dumps(found.get("pdb_ids", []) if found else ["fold"],
                                       separators=(",", ":")).encode()).hexdigest()
    parent = ROOT / "processed" / "docking_receptor_cache" / key
    parent.mkdir(parents=True, exist_ok=True)
    with _cache_guard:
        lock = _cache_locks.setdefault(key, threading.Lock())
    with lock:
        pointer = parent / (variant+".json")
        record = json.loads(pointer.read_text()) if pointer.exists() and not force_rebuild else None
        cache_hit = bool(record)
        if not cache_hit:
            build = Path(tempfile.mkdtemp(prefix="build-", dir=parent))
            prep_started=time.perf_counter()
            rejected=[]
            solved=False
            for protein,center,info in candidate_sites(found or {},sequence):
                (build/"protein.pdb").write_text(protein)
                try:
                    run([sys.executable,"-m","meeko.cli.mk_prepare_receptor","--read_pdb",build/"protein.pdb",
                         "-o",build/"receptor","-p"],build,"receptor_preparation")
                except RuntimeError as exc:
                    logpath=build/"receptor_preparation.log"
                    reason=logpath.read_text(encoding="utf-8",errors="replace")
                    import re
                    residues=sorted(set(re.findall("No template matched for residue_key='([^']+)'",reason)))
                    rejected.append(info["pdb_id"]+" ("+(", ".join(residues) or str(exc))+")")
                    logpath.replace(build/(info["pdb_id"]+"_prep.log"))
                    continue
                solved=True
                pockets=[dict(rank=1,center=center,score=None,probability=None)]
                metadata=dict(protein_source="RCSB PDB "+info["pdb_id"],pocket_source="Experimental ligand coordinates",
                              experimental_site=info,rejected_templates=rejected)
                break
            if not solved:
                if rejected:
                    raise ValueError("Receptor preparation failed for experimental templates: "+"; ".join(rejected))
                pockets,metadata=fold_and_rank(sequence,build)
                prep_started=time.perf_counter()
                run([sys.executable,"-m","meeko.cli.mk_prepare_receptor","--read_pdb",build/"protein.pdb",
                     "-o",build/"receptor","-p","--delete_bad_res"],build,"receptor_preparation")
            if not any(line.startswith(("ATOM","HETATM")) for line in (build/"receptor.pdbqt").read_text().splitlines()):
                raise ValueError("Receptor preparation produced an empty PDBQT.")
            record = dict(directory=build.name,pockets=pockets,metadata=metadata,prep_seconds=time.perf_counter()-prep_started)
            pending = build / "pointer.tmp"
            pending.write_text(json.dumps(record))
            if solved or not found:
                os.replace(pending,pointer)
            else:
                pending.unlink()
        build = parent / record["directory"]
        logging.getLogger("uvicorn.error").info("Receptor cache %s for %s","hit" if cache_hit else "miss",key)
        for name in ("protein.pdb","receptor.pdbqt","receptor_preparation.log","fold_metadata.json","fold_request.json","fold.log","p2rank.log"):
            if (build/name).is_file():
                shutil.copy2(build/name,folder/name)
        if (build/"p2rank").is_dir():
            shutil.copytree(build/"p2rank",folder/"p2rank",dirs_exist_ok=True)
    docking_started=time.perf_counter()
    docking = dock_generated(smiles,folder/"protein.pdb",record["pockets"][:MAX_DOCKED_POCKETS],folder)
    docking.update(record["metadata"],receptor_cache_hit=cache_hit,seconds_before_vina=docking_started-started,
                   receptor_prep_seconds=0 if cache_hit else record.get("prep_seconds"),
                   docking_seconds=time.perf_counter()-docking_started)
    if docking.get("experimental_site"):
        docking.update(preparation="Single contacting chain; blank/A alternate locations; strict Meeko templates; solvent and cofactors excluded.",
                       confidence="Experimental receptor coordinates; binding pose and contacts are computational predictions.")
    meta_path=folder/"metadata.json"
    meta=json.loads(meta_path.read_text())
    meta.update(record["metadata"],display_name=docking["protein_source"],pose_source="AutoDock Vina predicted pose")
    if docking.get("experimental_site"):
        meta.update(pdb_id=docking["experimental_site"]["pdb_id"],exclusion_reasons=["PREDICTED_POSE"])
    meta_path.write_text(json.dumps(meta,indent=2))
    (folder/"docking.json").write_text(json.dumps(docking,indent=2))
    return docking
