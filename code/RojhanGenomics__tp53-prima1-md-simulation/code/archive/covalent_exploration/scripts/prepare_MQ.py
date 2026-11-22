"""
ساخت ساختار سه‌بعدی MQ (2-methylene-3-quinuclidinone)
متابولیت زیستی-فعال PRIMA-1 که واقعاً با سیستئین واکنش کووالانت می‌دهد
(نه خود PRIMA-1، که صرفاً پیش‌دارو است)

اجرا با (بعد از conda activate tp53_md):
python prepare_MQ.py
"""

from rdkit import Chem
from rdkit.Chem import AllChem, rdMolDescriptors

SMILES_MQ = "C1CN2CCC1C(=O)C2=C"
LIGAND_NAME = "MQ"

mol = Chem.MolFromSmiles(SMILES_MQ)
if mol is None:
    raise ValueError("خطا: SMILES نامعتبر است.")

formula = rdMolDescriptors.CalcMolFormula(mol)
mw = rdMolDescriptors.CalcExactMolWt(mol)
print(f"فرمول مولکولی MQ: {formula}")
print(f"وزن مولکولی دقیق: {mw:.2f}")
print("(مقدار مرجع ادبیات علمی: C8H11NO ، MW ≈ 137.18)")

mol = Chem.AddHs(mol)
params = AllChem.ETKDGv3()
params.randomSeed = 42
embed_result = AllChem.EmbedMolecule(mol, params)
if embed_result == -1:
    raise ValueError("خطا: ساخت conformer سه‌بعدی ناموفق بود.")

AllChem.MMFFOptimizeMolecule(mol, maxIters=2000)

Chem.MolToPDBFile(mol, f"{LIGAND_NAME}.pdb")
writer = Chem.SDWriter(f"{LIGAND_NAME}.sdf")
writer.write(mol)
writer.close()

print(f"\nفایل‌های {LIGAND_NAME}.pdb و {LIGAND_NAME}.sdf ذخیره شدند.")
print(f"تعداد اتم‌های نهایی (شامل هیدروژن): {mol.GetNumAtoms()}")
