#!/usr/bin/env python3
"""
Prepares human salivary lysozyme (RCSB 1LZ1) receptor for counter-screening.
"""
import subprocess
from pathlib import Path
import numpy as np
from Bio.PDB import PDBParser, PDBIO, Select

REPO_ROOT = Path(__file__).parent.parent.resolve()
RECEPTORS_DIR = REPO_ROOT / "demo_data" / "receptors"
RAW_PDB = RECEPTORS_DIR / "1LZ1.pdb"
CLEAN_PDB = RECEPTORS_DIR / "1LZ1_receptor.pdb"
PDBQT_FILE = RECEPTORS_DIR / "1LZ1_receptor.pdbqt"


class ChainASelect(Select):
    def accept_residue(self, res):
        return res.get_parent().id == "A" and res.id[0] == " "


def prepare_1lz1():
    parser = PDBParser(QUIET=True)
    struct = parser.get_structure("1lz1", str(RAW_PDB))
    io = PDBIO()
    io.set_structure(struct)
    io.save(str(CLEAN_PDB), ChainASelect())

    coords = []
    for model in struct:
        for chain in model:
            if chain.id == "A":
                for res in chain:
                    if res.id[1] in (35, 53):
                        for atom in res:
                            coords.append(atom.coord)

    center = np.mean(coords, axis=0) if coords else np.array([0.0, 0.0, 0.0])
    center_tuple = (round(float(center[0]), 3), round(float(center[1]), 3), round(float(center[2]), 3))
    print(f"1LZ1 Catalytic Groove Centroid (Glu35 / Asp53): {center_tuple}")

    cmd = f"obabel -ipdb {CLEAN_PDB} -opdbqt -O {PDBQT_FILE} -xr -p 7.4 --partialcharge gasteiger"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"obabel failed: {res.stderr}")
    print(f"Generated {PDBQT_FILE} ({PDBQT_FILE.stat().st_size} bytes)")
    return center_tuple


if __name__ == "__main__":
    prepare_1lz1()
