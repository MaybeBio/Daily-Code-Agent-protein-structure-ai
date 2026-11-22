import warnings
warnings.filterwarnings("ignore")

from rdkit import Chem, DataStructs
from rdkit.Chem import (AllChem, Descriptors, QED,
    Draw, rdMolDescriptors, rdFingerprintGenerator)
from rdkit.Chem.inchi import MolToInchiKey
import pandas as pd
import numpy as np
import os

out_csv = snakemake.output[0]
out_png = snakemake.output[1]
os.makedirs(os.path.dirname(out_csv), exist_ok=True)

known_inh = snakemake.config.get("known_inhibitor","")
ref_name  = snakemake.config.get("reference_name","Reference")
ref_ic50  = snakemake.config.get("reference_ic50_nm", 0)

mfpgen = rdFingerprintGenerator.GetMorganGenerator(
    radius=2, fpSize=2048)

# 15 substituents — Topliss + Hansch-Craig + Bioisostere
SUB_SMILES = [
    ("F",        "Fluorine"),
    ("Cl",       "Chlorine"),
    ("Br",       "Bromine"),
    ("C",        "Methyl"),
    ("CC",       "Ethyl"),
    ("CCC",      "Propyl"),
    ("OC",       "Methoxy"),
    ("OCC",      "Ethoxy"),
    ("N",        "Amino"),
    ("NC",       "Methylamino"),
    ("C(F)(F)F", "CF3"),
    ("C#N",      "Cyano"),
    ("O",        "Hydroxy"),
    ("S",        "Thiol"),
    ("C1CC1",    "Cyclopropyl"),
]

RING_SWAPS = {
    "pyridine_to_thiazole":   ("c1ccncc1","c1cscn1"),
    "pyridine_to_pyrimidine": ("c1ccncc1","c1cncnc1"),
    "benzene_to_pyridine":    ("c1ccccc1","c1ccncc1"),
    "benzene_to_thiophene":   ("c1ccccc1","c1ccsc1"),
}

BIOISOSTERES = {
    "sulfonamide_to_urea":      ("NS(=O)(=O)","NC(=O)N"),
    "sulfonamide_to_amide":     ("NS(=O)(=O)","NC(=O)"),
    "sulfonamide_to_carbamate": ("NS(=O)(=O)","NC(=O)O"),
}

KNOWN = [
    ("F_tolyl",   "Cc1ccc(S(=O)(=O)Nc2ncc(-c3ccccn3)cn2)cc1F",        "F on tolyl"),
    ("CF3_tolyl", "Cc1ccc(S(=O)(=O)Nc2ncc(-c3ccccn3)cn2)cc1C(F)(F)F", "CF3 on tolyl"),
    ("Cl_tolyl",  "Cc1ccc(S(=O)(=O)Nc2ncc(-c3ccccn3)cn2)cc1Cl",       "Cl on tolyl"),
    ("Methoxy",   "COc1ccc(S(=O)(=O)Nc2ncc(-c3ccccn3)cn2)cc1",        "Methoxy on tolyl"),
    ("F_pyridine","Cc1ccc(S(=O)(=O)Nc2ncc(-c3ccccnc3F)cn2)cc1",       "F on pyridine"),
    ("Urea",      "Cc1ccc(NC(=O)Nc2ncc(-c3ccccn3)cn2)cc1",            "Sulfonamide to urea"),
    ("Amide",     "Cc1ccc(C(=O)Nc2ncc(-c3ccccn3)cn2)cc1",             "Sulfonamide to amide"),
    ("Nitro",     "Cc1ccc(S(=O)(=O)Nc2ncc(-c3ccccn3)cn2)cc1[N+](=O)[O-]","Nitro on tolyl"),
    ("CN_tolyl",  "Cc1ccc(S(=O)(=O)Nc2ncc(-c3ccccn3)cn2)cc1C#N",     "Cyano on tolyl"),
]

def sanitize(smi):
    try:
        mol = Chem.MolFromSmiles(smi)
        if mol is None: return None
        Chem.SanitizeMol(mol)
        return mol
    except: return None

def get_inchikey(mol):
    """InChIKey for isomer filtering"""
    try:
        key = MolToInchiKey(mol)
        return key if key else Chem.MolToSmiles(
            mol, canonical=True)
    except:
        return Chem.MolToSmiles(mol, canonical=True)

def lipinski_pass(mol):
    if mol is None: return False
    return (Descriptors.MolWt(mol)<=500 and
            Descriptors.MolLogP(mol)<=5 and
            rdMolDescriptors.CalcNumHBD(mol)<=5 and
            rdMolDescriptors.CalcNumHBA(mol)<=10)

def get_tanimoto(mol, ref_mol):
    try:
        fp1 = mfpgen.GetFingerprint(mol)
        fp2 = mfpgen.GetFingerprint(ref_mol)
        return round(DataStructs.TanimotoSimilarity(fp1,fp2),3)
    except: return 0.0

def get_descriptors(mol, name, mod, ref_mol):
    try:
        tan = get_tanimoto(mol, ref_mol)
        pred_ic50 = None
        vs_ref = "Unknown"
        if ref_ic50 > 0 and tan > 0:
            pred_ic50 = round(ref_ic50/max(tan,0.01),1)
            vs_ref = "Better" if pred_ic50 < ref_ic50 else "Worse"
        return {
            "name":             name,
            "smiles":           Chem.MolToSmiles(mol),
            "modification":     mod,
            "MW":               round(Descriptors.MolWt(mol),1),
            "logP":             round(Descriptors.MolLogP(mol),2),
            "QED":              round(QED.qed(mol),3),
            "HBD":              rdMolDescriptors.CalcNumHBD(mol),
            "HBA":              rdMolDescriptors.CalcNumHBA(mol),
            "TPSA":             round(Descriptors.TPSA(mol),1),
            "RotBonds":         rdMolDescriptors.CalcNumRotatableBonds(mol),
            "Lipinski":         "PASS" if lipinski_pass(mol) else "FAIL",
            "Tanimoto":         tan,
            "predicted_ic50_nm":pred_ic50,
            "vs_ref_ic50":      vs_ref,
            "ref_ic50_nm":      ref_ic50,
        }
    except Exception as e:
        print(f"  Error {name}: {e}")
        return None

def get_aromatic_positions(mol):
    return [a.GetIdx() for a in mol.GetAtoms()
            if a.GetIsAromatic() and
            a.GetSymbol()=="C" and
            a.GetTotalNumHs()>0]

def add_sub_to_position(mol, atom_idx, sub_smi):
    try:
        sub = Chem.MolFromSmiles(sub_smi)
        if sub is None: return None
        atom = mol.GetAtomWithIdx(atom_idx)
        if not atom.GetIsAromatic(): return None
        if atom.GetTotalNumHs()==0: return None
        combined = Chem.RWMol(Chem.CombineMols(mol,sub))
        new_idx = mol.GetNumAtoms()
        combined.AddBond(atom_idx, new_idx,
            Chem.rdchem.BondType.SINGLE)
        combined.GetAtomWithIdx(atom_idx).SetNumExplicitHs(
            max(0, atom.GetTotalNumHs()-1))
        Chem.SanitizeMol(combined)
        return combined.GetMol()
    except: return None

print("="*45)
print("STEP 3: ANALOGUE DESIGN")
print("="*45)

if not known_inh:
    raise ValueError("known_inhibitor blank in config")

ref_mol = sanitize(known_inh)
if ref_mol is None:
    raise ValueError("Invalid reference SMILES")

ref_smi = Chem.MolToSmiles(ref_mol)
print(f"Reference: {ref_name} IC50={ref_ic50}nM")

analogues      = []
existing_keys  = set()  # InChIKey based
existing_names = set()

# Reference
ref_desc = get_descriptors(ref_mol,
    f"{ref_name}_ref", "Reference", ref_mol)
if ref_desc:
    analogues.append(ref_desc)
    existing_keys.add(get_inchikey(ref_mol))
    existing_names.add(f"{ref_name}_ref")

# Ring swaps
print("\nRing swaps...")
for name,(old,new) in RING_SWAPS.items():
    try:
        old_mol = Chem.MolFromSmarts(old)
        if old_mol and ref_mol.HasSubstructMatch(old_mol):
            new_mol = sanitize(ref_smi.replace(old,new))
            if new_mol and lipinski_pass(new_mol):
                key = get_inchikey(new_mol)
                if key not in existing_keys:
                    short = name.split("_to_")[1].capitalize()
                    desc = get_descriptors(new_mol,short,name,ref_mol)
                    if desc:
                        analogues.append(desc)
                        existing_keys.add(key)
                        existing_names.add(short)
                        print(f"  + {short}")
    except: pass

# Bioisosteres
print("\nBioisosteres...")
for name,(old,new) in BIOISOSTERES.items():
    try:
        if old in ref_smi:
            new_mol = sanitize(ref_smi.replace(old,new,1))
            if new_mol and lipinski_pass(new_mol):
                key = get_inchikey(new_mol)
                if key not in existing_keys:
                    short = name.split("_to_")[1].capitalize()
                    desc = get_descriptors(new_mol,short,name,ref_mol)
                    if desc:
                        analogues.append(desc)
                        existing_keys.add(key)
                        existing_names.add(short)
                        print(f"  + {short}")
    except: pass

# Known analogues
print("\nKnown analogues...")
for name,smi,mod in KNOWN:
    if name in existing_names: continue
    mol = sanitize(smi)
    if mol and lipinski_pass(mol):
        key = get_inchikey(mol)
        if key not in existing_keys:
            desc = get_descriptors(mol,name,mod,ref_mol)
            if desc:
                analogues.append(desc)
                existing_keys.add(key)
                existing_names.add(name)
                print(f"  + {name}")

# R-group permutation with InChIKey isomer filter
print("\nR-group permutation...")
positions = get_aromatic_positions(ref_mol)
print(f"  Positions: {len(positions)}")
print(f"  Substituents: {len(SUB_SMILES)}")

perm_count = 0
for pos in positions:
    for sub_smi, sub_name in SUB_SMILES:
        try:
            new_mol = add_sub_to_position(
                ref_mol, pos, sub_smi)
            if new_mol is None: continue

            # InChIKey isomer filter
            key = get_inchikey(new_mol)
            if key in existing_keys: continue
            if not lipinski_pass(new_mol): continue

            existing_keys.add(key)
            name = f"p{pos}_{sub_smi.replace('(','').replace(')','').replace('#','n')}"
            if name in existing_names:
                name = f"{name}_{perm_count}"

            desc = get_descriptors(new_mol, name,
                f"{sub_name} at pos {pos}", ref_mol)
            if desc:
                analogues.append(desc)
                existing_names.add(name)
                perm_count += 1
        except: continue

print(f"  Permutation analogues: {perm_count}")

# Save
df = pd.DataFrame([a for a in analogues if a])
df = df.drop_duplicates(subset=["smiles"])
df = df[df["Lipinski"]=="PASS"]
df = df.sort_values("Tanimoto", ascending=False)
df = df.reset_index(drop=True)

print(f"\nTotal analogues: {len(df)}")
if ref_ic50 > 0:
    better = (df["predicted_ic50_nm"] < ref_ic50).sum()
    print(f"Better IC50: {better}/{len(df)}")

df.to_csv(out_csv, index=False)

# Image
try:
    mols, legends = [], []
    for _, row in df.iterrows():
        mol = sanitize(row["smiles"])
        if mol:
            AllChem.Compute2DCoords(mol)
            mols.append(mol)
            legends.append(
                f"{row['name']}\nMW:{row['MW']}\nIC50~{row['predicted_ic50_nm']}nM")
    img = Draw.MolsToGridImage(
        mols, molsPerRow=3,
        subImgSize=(400,300),
        legends=legends)
    img.save(out_png)
except Exception as e:
    print(f"Image error: {e}")
    from PIL import Image
    Image.new("RGB",(800,600),(255,255,255)).save(out_png)

print("Step 3 complete")
