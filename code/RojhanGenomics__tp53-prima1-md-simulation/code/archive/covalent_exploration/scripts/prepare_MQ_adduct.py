"""
ساخت محصول واکنش Michael addition بین MQ (متابولیت فعال PRIMA-1)
و متیل‌تیول (CH3-SH، به‌عنوان مدل ساده‌شده‌ی زنجیره‌ی جانبی سیستئین)

مکانیسم: گروه تیول به کربن متیلن اگزوسیکلیک MQ حمله می‌کند و
یک پیوند کووالانت C-S جدید تشکیل می‌شود؛ کربن متیلن به CH2 اشباع
و سولفور به آن متصل تبدیل می‌شود.

اجرا با (بعد از conda activate tp53_md):
python prepare_MQ_adduct.py
"""

from rdkit import Chem
from rdkit.Chem import AllChem, rdMolDescriptors

# SMILES محصول Michael addition:
# MQ (C1CN2CCC1C(=O)C2=C) + CH3-SH -> پیوند C-S جدید روی کربن متیلن
# ساختار محصول: کربن متیلن قبلی حالا CH2-S-CH3 دارد
SMILES_ADDUCT = "C1CN2CCC1C(=O)C2CSC"
ADDUCT_NAME = "MQ_adduct"

mol = Chem.MolFromSmiles(SMILES_ADDUCT)
if mol is None:
    raise ValueError("خطا: SMILES نامعتبر است.")

formula = rdMolDescriptors.CalcMolFormula(mol)
mw = rdMolDescriptors.CalcExactMolWt(mol)
print(f"فرمول مولکولی adduct: {formula}")
print(f"وزن مولکولی دقیق: {mw:.2f}")
print("(مقدار مورد انتظار: MQ [C8H11NO, 137.08] + CH3SH [CH4S, 48.01] = C9H15NOS، ~185.09)")

mol = Chem.AddHs(mol)
params = AllChem.ETKDGv3()
params.randomSeed = 42
embed_result = AllChem.EmbedMolecule(mol, params)
if embed_result == -1:
    raise ValueError("خطا: ساخت conformer سه‌بعدی ناموفق بود.")

AllChem.MMFFOptimizeMolecule(mol, maxIters=2000)

Chem.MolToPDBFile(mol, f"{ADDUCT_NAME}.pdb")
writer = Chem.SDWriter(f"{ADDUCT_NAME}.sdf")
writer.write(mol)
writer.close()

print(f"\nفایل‌های {ADDUCT_NAME}.pdb و {ADDUCT_NAME}.sdf ذخیره شدند.")
print(f"تعداد اتم‌های نهایی (شامل هیدروژن): {mol.GetNumAtoms()}")
