"""
ساخت ساختار سه‌بعدی لیگاند PRIMA-1 از روی SMILES با RDKit
منبع SMILES: PubChem CID 322968

اجرا با (بعد از conda activate tp53_md):
python prepare_ligand.py
"""

from rdkit import Chem
from rdkit.Chem import AllChem

# SMILES رسمی PRIMA-1 از PubChem (CID 322968)
SMILES = "C1CN2CCC1C(=O)C2(CO)CO"
LIGAND_NAME = "PRIMA1"

# ساخت مولکول از SMILES
mol = Chem.MolFromSmiles(SMILES)
if mol is None:
    raise ValueError("خطا: SMILES نامعتبر است.")

print(f"فرمول مولکولی: {Chem.rdMolDescriptors.CalcMolFormula(mol)}")

# اضافه کردن هیدروژن‌های صریح (ضروری برای ساخت مختصات سه‌بعدی دقیق)
mol = Chem.AddHs(mol)

# ساخت conformer سه‌بعدی اولیه (embedding)
# از الگوریتم ETKDG استفاده می‌شود که نسبت به روش‌های قدیمی‌تر دقیق‌تر است
params = AllChem.ETKDGv3()
params.randomSeed = 42  # برای تکرارپذیری نتیجه
embed_result = AllChem.EmbedMolecule(mol, params)

if embed_result == -1:
    raise ValueError("خطا: ساخت conformer سه‌بعدی ناموفق بود.")

# بهینه‌سازی هندسه با فیلد نیروی MMFF94 (مینیمم کردن انرژی ساختار)
optimize_result = AllChem.MMFFOptimizeMolecule(mol, maxIters=2000)
if optimize_result != 0:
    print("هشدار: بهینه‌سازی MMFF ممکن است کامل نشده باشد (نتیجه غیرصفر).")
else:
    print("بهینه‌سازی هندسه با موفقیت انجام شد.")

# ذخیره به فرمت PDB (برای بررسی بصری در PyMOL)
pdb_path = f"{LIGAND_NAME}.pdb"
Chem.MolToPDBFile(mol, pdb_path)
print(f"فایل PDB ذخیره شد: {pdb_path}")

# ذخیره به فرمت SDF (برای مراحل بعدی آماده‌سازی داکینگ با Meeko)
sdf_path = f"{LIGAND_NAME}.sdf"
writer = Chem.SDWriter(sdf_path)
writer.write(mol)
writer.close()
print(f"فایل SDF ذخیره شد: {sdf_path}")

print(f"\nتعداد اتم‌های نهایی (شامل هیدروژن): {mol.GetNumAtoms()}")
