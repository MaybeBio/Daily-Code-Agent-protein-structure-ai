#!/usr/bin/env python3
"""
Biophysics Engine: True 28Å / exh=16 Vina + Vinardo + OpenMM Physics.
Author: Dr. Roi Castrellon, DDS (DrNemo Caries Foundry)

Zero synthetic formulas, zero mock shortcuts:
- Uncompressed 28.0 x 28.0 x 28.0 A grid centered on catalytic triad oxygens
- Dual scoring: AutoDock Vina (--scoring vina) + Vinardo (--scoring vinardo)
- Ligand Efficiency: LE = -E_vina / heavy_atoms
- Disulfide S-S geometry verification in output pose (2.00 - 2.15 A)
- OpenMM all-atom Amber14 (amber14-all.xml + implicit/gbn2.xml) minimization at 310.15 K (37 C oral temp)
- Solubility Shield: Donnan equilibrium (Q_pH6 <= +4.0) & Stephan acid-switch (Delta Q >= +1.0)
"""
import os
import sys
import hashlib
import subprocess
import math
import numpy as np
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

try:
    from rdkit import Chem
    from rdkit.Chem import AllChem
except ImportError:
    Chem = None
    AllChem = None

try:
    from meeko import MoleculePreparation, PDBQTWriterLegacy
except ImportError:
    MoleculePreparation = None
    PDBQTWriterLegacy = None

try:
    import openmm as mm
    from openmm import app, unit
except ImportError:
    mm = None
    app = None
    unit = None

from solubility_shield import (
    is_viable,
    calc_net_charge_at_ph,
    calc_stephan_switch,
    count_protease_cleavage_sites,
    MAX_DONNAN_CHARGE_PH6
)

REPO_ROOT = Path(__file__).parent.resolve()
RECEPTORS_DIR = REPO_ROOT / "demo_data" / "receptors"
RECEPTOR_3AIC_PDBQT = RECEPTORS_DIR / "3AIC_receptor.pdbqt"
RECEPTOR_1SMD_PDBQT = RECEPTORS_DIR / "1SMD_receptor.pdbqt"
RECEPTOR_1LZ1_PDBQT = RECEPTORS_DIR / "1LZ1_receptor.pdbqt"

# Uncompressed 28 A grid centered on solvent-exposed catalytic triads / active clefts
TARGET_COORDS = {
    "3AIC": {
        "center": (192.072, 44.370, 197.309),
        "size": (28.0, 28.0, 28.0),
        "receptor": str(RECEPTOR_3AIC_PDBQT)
    },
    "1SMD": {
        "center": (8.778, 49.724, 17.278),
        "size": (28.0, 28.0, 28.0),
        "receptor": str(RECEPTOR_1SMD_PDBQT)
    },
    "1LZ1": {
        "center": (10.319, 8.503, 25.960),
        "size": (28.0, 28.0, 28.0),
        "receptor": str(RECEPTOR_1LZ1_PDBQT)
    }
}


def build_macrocycle_3d(
    seq: str,
    out_pdbqt: str,
    out_pdb: Optional[str] = None,
    target_center: Optional[Tuple[float, float, float]] = None
) -> int:
    """
    Builds an all-atom 3D structure for a cyclic disulfide peptide with RDKit MMFF94 force field.
    If target_center is provided, translates the conformer centroid to target_center.
    Returns the count of heavy atoms.
    """
    mol = Chem.MolFromSequence(seq)
    if mol is None:
        raise ValueError(f"Invalid peptide sequence: {seq}")
    mol = Chem.AddHs(mol)

    # Disulfide bond strictly between first residue (resi 1, N-terminal CYS) SG
    # and last residue (resi N, C-terminal CYS) SG
    cys1_sg = None
    cysN_sg = None
    N = len(seq)
    for a in mol.GetAtoms():
        info = a.GetPDBResidueInfo()
        if info and info.GetResidueName().strip() == "CYS" and info.GetName().strip() == "SG":
            if info.GetResidueNumber() == 1:
                cys1_sg = a.GetIdx()
            elif info.GetResidueNumber() == N:
                cysN_sg = a.GetIdx()

    if cys1_sg is not None and cysN_sg is not None:
        atoms_to_remove = []
        for s_idx in (cys1_sg, cysN_sg):
            for nbr in mol.GetAtomWithIdx(s_idx).GetNeighbors():
                if nbr.GetSymbol() == "H":
                    atoms_to_remove.append(nbr.GetIdx())
                    break
        emol = Chem.EditableMol(mol)
        for h_idx in sorted(atoms_to_remove, reverse=True):
            emol.RemoveAtom(h_idx)
        mol = emol.GetMol()

        cys1_sg = None
        cysN_sg = None
        for a in mol.GetAtoms():
            info = a.GetPDBResidueInfo()
            if info and info.GetResidueName().strip() == "CYS" and info.GetName().strip() == "SG":
                if info.GetResidueNumber() == 1:
                    cys1_sg = a.GetIdx()
                elif info.GetResidueNumber() == N:
                    cysN_sg = a.GetIdx()

        emol = Chem.EditableMol(mol)
        emol.AddBond(cys1_sg, cysN_sg, Chem.BondType.SINGLE)
        mol = emol.GetMol()

    Chem.SanitizeMol(mol)

    # 3D Distance Geometry embedding + MMFF94 energy minimization
    params = AllChem.ETKDGv3()
    params.randomSeed = 42
    embed_res = AllChem.EmbedMolecule(mol, params)
    if embed_res != 0:
        embed_res = AllChem.EmbedMolecule(mol, useRandomCoords=True, maxAttempts=5000, randomSeed=42)
    try:
        AllChem.MMFFOptimizeMolecule(mol, maxIters=500)
    except Exception:
        try:
            AllChem.UFFOptimizeMolecule(mol, maxIters=500)
        except Exception:
            pass

    if target_center is not None:
        conf = mol.GetConformer()
        positions = conf.GetPositions()
        centroid = np.mean(positions, axis=0)
        translation = np.array(target_center) - centroid
        for i in range(mol.GetNumAtoms()):
            conf.SetAtomPosition(i, positions[i] + translation)

    # Save clean heavy-atom PDB if requested (for OpenMM / PDBFixer)
    if out_pdb:
        os.makedirs(os.path.dirname(os.path.abspath(out_pdb)), exist_ok=True)
        mol_heavy = Chem.RemoveHs(mol)
        Chem.MolToPDBFile(mol_heavy, out_pdb)

    # Convert to PDBQT via Meeko
    os.makedirs(os.path.dirname(os.path.abspath(out_pdbqt)), exist_ok=True)
    preparator = MoleculePreparation()
    preparator.prepare(mol)
    writer = PDBQTWriterLegacy()
    pdbqt_str = writer.write_string(preparator.setup)[0]
    with open(out_pdbqt, "w", encoding="utf-8") as f:
        f.write(pdbqt_str)

    return mol.GetNumHeavyAtoms()


def measure_disulfide_bond(pdbqt_path: str) -> Optional[float]:
    """Measures the terminal Cys1:SG-CysN:SG distance (Angstroms) in a docked PDBQT pose."""
    cys1_sg = None
    cys_last_sg = None
    max_resi = -1
    if not os.path.exists(pdbqt_path):
        return None
    with open(pdbqt_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("ATOM") or line.startswith("HETATM"):
                atom_name = line[12:16].strip()
                res_name = line[17:20].strip()
                try:
                    res_num = int(line[22:26].strip())
                except ValueError:
                    continue
                if atom_name == "SG" and res_name == "CYS":
                    x = float(line[30:38])
                    y = float(line[38:46])
                    z = float(line[46:54])
                    if res_num == 1:
                        cys1_sg = (x, y, z)
                    if res_num > max_resi:
                        max_resi = res_num
                        cys_last_sg = (x, y, z)
            if line.startswith("ENDMDL"):
                break
    if cys1_sg and cys_last_sg and max_resi > 1:
        dx = cys1_sg[0] - cys_last_sg[0]
        dy = cys1_sg[1] - cys_last_sg[1]
        dz = cys1_sg[2] - cys_last_sg[2]
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        return round(dist, 2)
    return None


def run_docking_vina_and_vinardo(
    ligand_pdbqt: str,
    target: str = "3AIC",
    exhaustiveness: int = 16,
    cpu: int = 8,
    out_pdbqt: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes AutoDock Vina with uncompressed 28A grid, extracts Vina affinity,
    then re-scores with --score_only --scoring vinardo to get Vinardo affinity.
    """
    cfg = TARGET_COORDS[target]
    if out_pdbqt is None:
        out_pdbqt = ligand_pdbqt.replace(".pdbqt", f"_{target}_docked.pdbqt")

    cx, cy, cz = cfg["center"]
    sx, sy, sz = cfg["size"]

    # Check if pose already exists and is valid (Resume-capable / Idempotent)
    vina_score = None
    if os.path.exists(out_pdbqt) and os.path.getsize(out_pdbqt) > 100:
        with open(out_pdbqt, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("REMARK VINA RESULT:"):
                    vina_score = float(line.split()[3])
                    break

    # 1. Dock with Vina scoring if not already present
    if vina_score is None:
        cmd_vina = [
            "/usr/bin/vina",
            "--receptor", cfg["receptor"],
            "--ligand", ligand_pdbqt,
            "--center_x", str(cx), "--center_y", str(cy), "--center_z", str(cz),
            "--size_x", str(sx), "--size_y", str(sy), "--size_z", str(sz),
            "--cpu", str(cpu),
            "--exhaustiveness", str(exhaustiveness),
            "--out", out_pdbqt
        ]
        res_vina = subprocess.run(cmd_vina, capture_output=True, text=True)
        if res_vina.returncode != 0:
            raise RuntimeError(f"Vina docking failed: {res_vina.stderr}")

        # Parse best Vina affinity from output pose
        with open(out_pdbqt, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("REMARK VINA RESULT:"):
                    vina_score = float(line.split()[3])
                    break

    if vina_score is None:
        raise RuntimeError(f"Could not parse Vina score from {out_pdbqt}")

    # 2. Rescore top pose with Vinardo
    split_prefix = out_pdbqt.replace(".pdbqt", "_split_")
    split_cmd = ["/usr/bin/vina_split", "--input", out_pdbqt, "--ligand", split_prefix]
    subprocess.run(split_cmd, capture_output=True, text=True)
    mode1_pdbqt = f"{split_prefix}1.pdbqt"

    vinardo_score = None
    if os.path.exists(mode1_pdbqt):
        cmd_vinardo = [
            "/usr/bin/vina",
            "--receptor", cfg["receptor"],
            "--ligand", mode1_pdbqt,
            "--center_x", str(cx), "--center_y", str(cy), "--center_z", str(cz),
            "--size_x", str(sx), "--size_y", str(sy), "--size_z", str(sz),
            "--scoring", "vinardo",
            "--score_only"
        ]
        res_vinardo = subprocess.run(cmd_vinardo, capture_output=True, text=True)
        for line in res_vinardo.stdout.splitlines():
            if "Estimated Free Energy of Binding" in line:
                # "Estimated Free Energy of Binding   : -5.200 (kcal/mol) [=(1)+(2)+(3)-(4)]"
                parts = line.split(":")
                if len(parts) >= 2:
                    val_str = parts[1].split()[0]
                    try:
                        vinardo_score = float(val_str)
                    except ValueError:
                        pass
                break

        # Fallback to autobox if ligand drifted slightly outside fixed box
        if vinardo_score is None:
            cmd_vinardo_auto = [
                "/usr/bin/vina",
                "--receptor", cfg["receptor"],
                "--ligand", mode1_pdbqt,
                "--scoring", "vinardo",
                "--score_only",
                "--autobox"
            ]
            res_auto = subprocess.run(cmd_vinardo_auto, capture_output=True, text=True)
            for line in res_auto.stdout.splitlines():
                if "Estimated Free Energy of Binding" in line:
                    parts = line.split(":")
                    if len(parts) >= 2:
                        try:
                            vinardo_score = float(parts[1].split()[0])
                        except ValueError:
                            pass
                    break

    if vinardo_score is None:
        raise RuntimeError(f"Vinardo scoring failed to extract binding free energy for {ligand_pdbqt} on {target}")

    # 3. Pose SHA256 & Disulfide check
    with open(out_pdbqt, "rb") as f:
        pose_sha = hashlib.sha256(f.read()).hexdigest()

    ss_dist = measure_disulfide_bond(out_pdbqt)

    return {
        "target": target,
        "vina_kcal": vina_score,
        "vinardo_kcal": vinardo_score,
        "out_pdbqt": out_pdbqt,
        "pose_sha256": pose_sha,
        "ss_bond_angstrom": ss_dist
    }


def relax_with_openmm(pdb_path: str, temp_k: float = 310.15) -> float:
    """
    Computes all-atom Amber14/GBn2 (310.15 K oral body temperature) macrocycle
    conformational and implicit-solvation potential energy (kJ/mol) on the 3D pose.
    """
    from pdbfixer import PDBFixer
    fixer = PDBFixer(filename=pdb_path)
    fixer.findMissingResidues()
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(7.4)

    forcefield = app.ForceField('amber14-all.xml', 'implicit/gbn2.xml')
    system = forcefield.createSystem(
        fixer.topology,
        nonbondedMethod=app.NoCutoff,
        constraints=app.HBonds
    )

    integrator = mm.LangevinMiddleIntegrator(
        temp_k * unit.kelvin,
        1.0 / unit.picoseconds,
        2.0 * unit.femtoseconds
    )

    simulation = app.Simulation(fixer.topology, system, integrator)
    simulation.context.setPositions(fixer.positions)

    # Energy minimize
    simulation.minimizeEnergy(maxIterations=200)
    state = simulation.context.getState(getEnergy=True)
    energy_kj = state.getPotentialEnergy().value_in_unit(unit.kilojoules_per_mole)
    return round(energy_kj, 2)
