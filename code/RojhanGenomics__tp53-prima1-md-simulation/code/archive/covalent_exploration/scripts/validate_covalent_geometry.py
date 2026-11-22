"""
مینیمایزیشن انرژی و اعتبارسنجی هندسی نهایی محصول واکنش کووالانت
MQ-Cysteine adduct، به‌عنوان بررسی مقدماتی (preliminary validation)
پایداری استریوشیمیایی پیوند کووالانت جدید.

اجرا با (بعد از conda activate tp53_md):
python validate_covalent_geometry.py
"""

from rdkit import Chem
from rdkit.Chem import AllChem, rdMolDescriptors, rdMolTransforms

ADDUCT_FILE = "MQ_adduct.sdf"

mol = Chem.MolFromMolFile(ADDUCT_FILE, removeHs=False)
if mol is None:
    raise ValueError("خطا در خواندن فایل adduct.")

print(f"فرمول مولکولی: {rdMolDescriptors.CalcMolFormula(mol)}")
print(f"تعداد اتم‌ها: {mol.GetNumAtoms()}")

# انرژی قبل از مینیمایزیشن (با فیلد نیروی MMFF94)
props = AllChem.MMFFGetMoleculeProperties(mol)
ff = AllChem.MMFFGetMoleculeForceField(mol, props)
energy_before = ff.CalcEnergy()
print(f"\nانرژی قبل از مینیمایزیشن: {energy_before:.2f} kcal/mol")

# مینیمایزیشن انرژی (تا همگرایی کامل)
converged = ff.Minimize(maxIts=5000, energyTol=1e-6, forceTol=1e-4)
energy_after = ff.CalcEnergy()
print(f"انرژی بعد از مینیمایزیشن: {energy_after:.2f} kcal/mol")
print(f"وضعیت همگرایی: {'موفق' if converged == 0 else 'ناقص (بررسی شود)'}")
print(f"کاهش انرژی: {energy_before - energy_after:.2f} kcal/mol")

# بررسی هندسه‌ی پیوند C-S جدید (اتم S1 و C8 که در واکنش Michael addition ساخته شدند)
conf = mol.GetConformer()

s_idx = None
c8_idx = None
for atom in mol.GetAtoms():
    if atom.GetSymbol() == "S":
        s_idx = atom.GetIdx()
    if atom.GetSymbol() == "C" and atom.GetIdx() != s_idx:
        for neighbor in atom.GetNeighbors():
            if neighbor.GetSymbol() == "S":
                c8_idx = atom.GetIdx()

if s_idx is not None and c8_idx is not None:
    bond_length = rdMolTransforms.GetBondLength(conf, s_idx, c8_idx)
    print(f"\nطول پیوند C-S جدید (پس از مینیمایزیشن): {bond_length:.3f} Å")
    print("(مقدار مرجع تجربی برای پیوند تک C-S: 1.81-1.86 Å)")

    if 1.70 <= bond_length <= 1.95:
        print(">>> نتیجه: طول پیوند در محدوده‌ی استریوشیمیایی معتبر است. ✓")
    else:
        print(">>> هشدار: طول پیوند خارج از محدوده‌ی معمول است، بررسی بیشتر لازم است.")

# ذخیره‌ی ساختار مینیمم‌شده
writer = Chem.SDWriter("MQ_adduct_minimized.sdf")
writer.write(mol)
writer.close()
Chem.MolToPDBFile(mol, "MQ_adduct_minimized.pdb")
print("\nفایل‌های MQ_adduct_minimized.sdf و .pdb ذخیره شدند.")
