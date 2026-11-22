# modules/utils.py
# This file contains helper functions used
# across multiple scripts.
# Used by: scripts/03_clean.py, 06_design.py,
#          08_admet.py, 09_ranking.py

from rdkit import Chem
from rdkit.Chem import Descriptors, QED
import os

def validate_smiles(smi):
    # Checks if a SMILES string represents
    # a real valid molecule.
    # Returns True or False.
    try:
        mol = Chem.MolFromSmiles(str(smi))
        return mol is not None
    except:
        return False

def get_properties(smi):
    # Calculates all important drug-like
    # properties of a molecule from its SMILES.
    # Returns a dictionary of property values.
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return {}
    mw   = round(Descriptors.MolWt(mol), 1)
    logp = round(Descriptors.MolLogP(mol), 2)
    hbd  = Descriptors.NumHDonors(mol)
    hba  = Descriptors.NumHAcceptors(mol)
    tpsa = round(Descriptors.TPSA(mol), 1)
    rotb = Descriptors.NumRotatableBonds(mol)
    qed  = round(QED.qed(mol), 3)
    ro5  = (mw<=500 and logp<=5
            and hbd<=5 and hba<=10)
    return {
        'MW':       mw,
        'logP':     logp,
        'HBD':      hbd,
        'HBA':      hba,
        'TPSA':     tpsa,
        'RotBonds': rotb,
        'QED':      qed,
        'Lipinski': 'PASS' if ro5 else 'FAIL'
    }

def make_dir(path):
    # Creates a folder if it does not exist.
    # Does nothing if it already exists.
    os.makedirs(path, exist_ok=True)
