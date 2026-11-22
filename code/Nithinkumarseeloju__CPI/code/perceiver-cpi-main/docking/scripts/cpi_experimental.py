"""Optional solved-structure lookup and deterministic receptor selection."""
from collections import defaultdict
from pathlib import Path
import json
import logging
import os
import re
import tempfile
from cpi_data import ROOT
from docking_stages import Stage
from http.client import HTTPException
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np
from scipy.spatial import cKDTree
from Bio.SeqUtils import seq1

log = logging.getLogger("uvicorn.error")
ADDITIVES = set("HOH DOD SO4 PO4 GOL EDO PEG PGE PG4 MPD ACT ACE MES TRS HEP DMS BME NAG MAN NA CL CA MG ZN K MN FE CU CO NI WAT BMA FUC GAL NDG SIA IOD BR NO3 ACY FMT".split())


def lookup(smiles, sequence):
    base = os.getenv("PERCEIVER_APP_URL", os.getenv("CPI_STRUCTURE_LOOKUP_URL", "http://127.0.0.1:8000")).strip()
    if not base:
        return None
    try:
        request = Request(base.rstrip("/") + "/structure", data=json.dumps(dict(smiles=smiles, sequence=sequence)).encode(),
                      headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            result = json.load(response)
    except (HTTPException, URLError, TimeoutError, ValueError, OSError) as exc:
        log.warning("Structure lookup unavailable: %s. Falling back to folding.", exc)
        return None
    if not isinstance(result, dict) or not isinstance(result.get("pdb_ids"), list):
        log.warning("Invalid structure lookup reply. Falling back to folding.")
        return None
    if result.get("level") in ("same_target", "exact_complex"):
        return result
    return None


def experimental_pocket(pdb_text, query):
    chains, ligands = defaultdict(list), defaultdict(list)
    for line in pdb_text.splitlines():
        if line.startswith("ENDMDL"):
            break
        if line[16:17] not in (" ", "A") or line[76:78].strip() in ("H", "D"):
            continue
        if line.startswith("ATOM  "):
            chains[line[21]].append(line)
        elif line.startswith("HETATM") and line[17:20].strip() not in ADDITIVES:
            ligands[line[17:27]].append(line)
    def xyz(lines):
        return np.array([[float(row[i:i+8]) for i in (30, 38, 46)] for row in lines])
    # Identify the largest organic ligand instance with a contacting target chain.
    for key, ligand in sorted(ligands.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(ligand) < 6 or not any(row[76:78].strip()=="C" for row in ligand):
            continue
        tree = cKDTree(xyz(ligand))
        matches = []
        for chain, atoms in chains.items():
            residues = {row[22:27]:seq1(row[17:20]) for row in atoms}
            seq = "".join(residues.values())
            if len(seq)<20:
                continue
            from Bio.Align import PairwiseAligner
            aligner = PairwiseAligner(mode="local",match_score=2,mismatch_score=-2,open_gap_score=-5,extend_gap_score=-1)
            alignment=next(iter(aligner.align(query,seq)),None)
            if alignment is None:
                continue
            if alignment.counts().identities / len(seq) < 0.9:
                continue
            count = int((tree.query(xyz(atoms))[0] <= 6).sum())
            if count:
                matches.append((count,chain,atoms))
        if matches:
            _, chain, atoms = max(matches,key=lambda item:(item[0],item[1]))
            cleaned = "\n".join(row[:16]+" "+row[17:] for row in atoms)+"\nTER\nEND\n"
            return cleaned, xyz(ligand).mean(axis=0).tolist(), dict(chain=chain,ligand_instance=key.strip())
    raise ValueError("No suitable bound ligand contacts a sequence-matched receptor chain.")


def pdb_file(pdb):
    if not isinstance(pdb, str) or not re.fullmatch(r"[0-9][A-Za-z0-9]{3}", pdb):
        raise ValueError(f"Invalid PDB identifier {pdb!r}")
    directory = ROOT / "processed" / "experimental"
    directory.mkdir(exist_ok=True, parents=True)
    path = directory / (pdb.lower() + ".pdb")
    if path.is_file():
        return path
    with urlopen(f"https://files.rcsb.org/download/{pdb.upper()}.pdb", timeout=10) as response:
        data = response.read()
    if not any(line.startswith(b"ATOM  ") for line in data.splitlines()):
        raise ValueError(f"PDB {pdb} contains no protein coordinates")
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
        handle.write(data)
        staging = Path(handle.name)
    staging.replace(path)
    return path


def find(smiles, sequence, *, with_candidates=False):
    found = lookup(smiles, sequence)
    if not found or not found["pdb_ids"]:
        return None
    pdb = found["pdb_ids"][0]
    try:
        result = dict(pdb_id=pdb, pdb_path=str(pdb_file(pdb)), ligand_code=found.get("ligand_code"))
        if with_candidates:
            result.update(pdb_ids=found["pdb_ids"], level=found["level"])
        return result
    except (HTTPException, OSError, ValueError) as exc:
        log.warning("Cannot fetch PDB %s: %s", pdb, exc)
        return None


def candidate_sites(found, sequence):
    for pdb in found.get("pdb_ids", [])[:8]:
        try:
            with Stage("experimental_site"):
                protein, center, details = experimental_pocket(pdb_file(pdb).read_text(encoding="ascii"), sequence)
            details.update(pdb_id=pdb.lower(), lookup_level=found["level"])
            yield protein, center, details
        except (HTTPException, OSError, ValueError) as exc:
            log.warning("Cannot use PDB %s: %s", pdb, exc)
