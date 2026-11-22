#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path
from Bio.PDB import PDBParser, PDBIO, Select

class ChainASelect(Select):
    def accept_residue(self, residue):
        # Keep standard amino acids in chain A
        return residue.get_parent().id == "A" and residue.id[0] == " "

class LigandSelect(Select):
    def accept_residue(self, residue):
        # Chain I contains GLC 1, GLC 2, AC1 3
        return residue.get_parent().id == "I" and residue.resname in ["GLC", "AC1"]

class SMDChainSelect(Select):
    def accept_residue(self, residue):
        # Keep standard amino acids in chain A of 1SMD
        return residue.get_parent().id == "A" and residue.id[0] == " "

def prepare_targets():
    base_dir = Path(__file__).resolve().parent.parent
    receptors_dir = base_dir / "demo_data" / "receptors"
    receptors_dir.mkdir(parents=True, exist_ok=True)
    
    parser = PDBParser(QUIET=True)
    io = PDBIO()

    # 1. 3AIC Chain A
    print("Extracting 3AIC Chain A...")
    struct_3aic = parser.get_structure("3aic", str(base_dir / "3AIC.pdb"))
    io.set_structure(struct_3aic)
    chain_a_pdb = receptors_dir / "3AIC_receptor.pdb"
    io.save(str(chain_a_pdb), ChainASelect())
    print(f"Saved {chain_a_pdb}")

    # Convert 3AIC receptor to PDBQT with obabel (-xr keeps as rigid receptor, -p 7.4 adds hydrogens)
    chain_a_pdbqt = receptors_dir / "3AIC_receptor.pdbqt"
    cmd = f"obabel -ipdb {chain_a_pdb} -opdbqt -O {chain_a_pdbqt} -xr -p 7.4 --partialcharge gasteiger"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        print("obabel error 3AIC:", res.stderr)
    else:
        print(f"Generated {chain_a_pdbqt} ({chain_a_pdbqt.stat().st_size} bytes)")

    # 2. Extract Native Co-crystal Ligand (Chain I: GLC 1, GLC 2, AC1 3)
    print("Extracting 3AIC Co-crystal Ligand (Chain I)...")
    lig_pdb = receptors_dir / "3AIC_native_ligand.pdb"
    io.save(str(lig_pdb), LigandSelect())
    print(f"Saved {lig_pdb} ({lig_pdb.stat().st_size} bytes)")
    
    # Convert ligand to PDBQT with obabel
    lig_pdbqt = receptors_dir / "3AIC_native_ligand.pdbqt"
    cmd_lig = f"obabel -ipdb {lig_pdb} -opdbqt -O {lig_pdbqt} -p 7.4 --partialcharge gasteiger"
    res_lig = subprocess.run(cmd_lig, shell=True, capture_output=True, text=True)
    if res_lig.returncode != 0:
        print("obabel error native ligand:", res_lig.stderr)
    else:
        print(f"Generated {lig_pdbqt} ({lig_pdbqt.stat().st_size} bytes)")

    # 3. 1SMD Chain A
    print("Extracting 1SMD Chain A...")
    struct_1smd = parser.get_structure("1smd", str(base_dir / "1SMD.pdb"))
    io.set_structure(struct_1smd)
    smd_pdb = receptors_dir / "1SMD_receptor.pdb"
    io.save(str(smd_pdb), SMDChainSelect())
    print(f"Saved {smd_pdb}")

    # Convert 1SMD receptor to PDBQT
    smd_pdbqt = receptors_dir / "1SMD_receptor.pdbqt"
    cmd_smd = f"obabel -ipdb {smd_pdb} -opdbqt -O {smd_pdbqt} -xr -p 7.4 --partialcharge gasteiger"
    res_smd = subprocess.run(cmd_smd, shell=True, capture_output=True, text=True)
    if res_smd.returncode != 0:
        print("obabel error 1SMD:", res_smd.stderr)
    else:
        print(f"Generated {smd_pdbqt} ({smd_pdbqt.stat().st_size} bytes)")

if __name__ == "__main__":
    prepare_targets()
