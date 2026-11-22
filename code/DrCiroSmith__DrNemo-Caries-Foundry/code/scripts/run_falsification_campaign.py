#!/usr/bin/env python3
"""
Operation Karl Popper: Falsification Suite Runner
Runs Angle 1, Angle 2, Angle 3, Angle 4, Angle 5 across real Vina + RDKit physics.
"""
import os
import sys
import json
import time
import random
import subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem
import meeko
from scipy import stats

from solubility_shield import (
    is_viable,
    calc_net_charge_at_ph,
    calc_stephan_switch,
    count_protease_cleavage_sites
)

BASE_DIR = Path(__file__).resolve().parent.parent
RECEPTORS_DIR = BASE_DIR / "demo_data" / "receptors"
RESULTS_DIR = BASE_DIR / "demo_data" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

TARGET_3AIC_CENTER = (192.072, 44.370, 197.309)
TARGET_1SMD_CENTER = (8.778, 49.724, 17.278)


def build_peptide_pdbqt(seq: str, target_center: tuple, out_pdbqt: str, is_cyclic: bool = True) -> str:
    """
    Builds 3D conformer using RDKit, cyclizes via disulfide bridge if is_cyclic,
    minimizes with MMFF94, centers at target_center, and prepares PDBQT with Meeko.
    """
    mol = Chem.MolFromSequence(seq)
    if mol is None:
        raise ValueError(f"Could not build molecule for sequence {seq}")

    if is_cyclic:
        sulfurs = [atom.GetIdx() for atom in mol.GetAtoms() if atom.GetSymbol() == "S"]
        if len(sulfurs) >= 2:
            rwmol = Chem.RWMol(mol)
            rwmol.AddBond(sulfurs[0], sulfurs[-1], Chem.BondType.SINGLE)
            mol = rwmol.GetMol()
            for s_idx in [sulfurs[0], sulfurs[-1]]:
                mol.GetAtomWithIdx(s_idx).SetNumExplicitHs(0)
            Chem.SanitizeMol(mol)

    mol = Chem.AddHs(mol)
    AllChem.EmbedMolecule(mol, randomSeed=42)
    if AllChem.MMFFHasAllMoleculeParams(mol):
        AllChem.MMFFOptimizeMolecule(mol, maxIters=300)
    else:
        AllChem.UFFOptimizeMolecule(mol, maxIters=300)

    conf = mol.GetConformer()
    positions = conf.GetPositions()
    centroid = np.mean(positions, axis=0)
    translation = np.array(target_center) - centroid
    for i in range(mol.GetNumAtoms()):
        pos = conf.GetAtomPosition(i)
        conf.SetAtomPosition(i, [pos.x + translation[0], pos.y + translation[1], pos.z + translation[2]])

    preparator = meeko.MoleculePreparation(flexible_amides=False, rigid_macrocycles=is_cyclic)
    mol_setups = preparator.prepare(mol)
    pdbqt_string, _, _ = meeko.PDBQTWriterLegacy.write_string(mol_setups[0])

    Path(out_pdbqt).parent.mkdir(parents=True, exist_ok=True)
    with open(out_pdbqt, "w", encoding="utf-8") as f:
        f.write(pdbqt_string)

    return out_pdbqt


def run_vina_dock(receptor_pdbqt: str, ligand_pdbqt: str, center: tuple, out_pdbqt: str, cpu: int = 4, exh: int = 2, box_size: float = 22.0) -> float:
    """
    Executes AutoDock Vina and parses the top affinity score (kcal/mol).
    """
    cmd = [
        "vina",
        "--receptor", str(receptor_pdbqt),
        "--ligand", str(ligand_pdbqt),
        "--center_x", f"{center[0]:.3f}",
        "--center_y", f"{center[1]:.3f}",
        "--center_z", f"{center[2]:.3f}",
        "--size_x", f"{box_size:.1f}",
        "--size_y", f"{box_size:.1f}",
        "--size_z", f"{box_size:.1f}",
        "--cpu", str(cpu),
        "--exhaustiveness", str(exh),
        "--out", str(out_pdbqt)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Vina failed for {ligand_pdbqt}: {res.stderr}")
        return 999.0

    score = 999.0
    for line in res.stdout.splitlines():
        if line.strip().startswith("1 "):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    score = float(parts[1])
                    break
                except ValueError:
                    pass
    return score


def worker_dock_task(task_args):
    seq, target_name, center, out_prefix, is_cyclic, cpu, exh = task_args
    lig_pdbqt = f"{out_prefix}.pdbqt"
    dock_out = f"{out_prefix}_docked.pdbqt"
    receptor_pdbqt = RECEPTORS_DIR / f"{target_name}_receptor.pdbqt"
    
    build_peptide_pdbqt(seq, center, lig_pdbqt, is_cyclic=is_cyclic)
    score = run_vina_dock(str(receptor_pdbqt), lig_pdbqt, center, dock_out, cpu=cpu, exh=exh)
    return {
        "sequence": seq,
        "target": target_name,
        "is_cyclic": is_cyclic,
        "affinity_kcal": score,
        "dock_out": dock_out
    }


if __name__ == "__main__":
    print("Falsification campaign module ready.")
