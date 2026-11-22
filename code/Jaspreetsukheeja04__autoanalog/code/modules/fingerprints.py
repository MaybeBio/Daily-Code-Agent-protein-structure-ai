# modules/fingerprints.py
# This file converts molecule SMILES strings into
# numbers that machine learning can understand.
# Used by: scripts/04_ml.py and scripts/09_ranking.py

from rdkit import Chem
from rdkit.Chem import AllChem, MACCSkeys

def to_morgan(smi, radius=2, nbits=2048):
    # Morgan fingerprint — looks at each atom and
    # its neighbors going outward 2 bonds in every
    # direction. Produces 2048 zeros and ones.
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return None
    return list(AllChem.GetMorganFingerprintAsBitVect(
        mol, radius, nbits))

def to_maccs(smi):
    # MACCS keys — 166 yes/no questions about
    # whether specific chemical patterns exist
    # in the molecule.
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return None
    return list(MACCSkeys.GenMACCSKeys(mol))

def to_combined(smi):
    # Combined fingerprint — Morgan + MACCS
    # together. More information for the model.
    morgan = to_morgan(smi)
    maccs  = to_maccs(smi)
    if morgan is None or maccs is None:
        return None
    return morgan + maccs

def get_fingerprint(smi, fp_type='Morgan'):
    # Single function to get any fingerprint type.
    # fp_type can be Morgan, MACCS, or Combined.
    if fp_type == 'Morgan':
        return to_morgan(smi)
    elif fp_type == 'MACCS':
        return to_maccs(smi)
    elif fp_type == 'Combined':
        return to_combined(smi)
    return None
