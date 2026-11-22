"""
ادغام residue Cys124 (بدون HG) و adduct در یک residue واحد جدید
با نام CYQ (Cysteine-Quinuclidinone adduct)، آماده برای پارامترسازی
با antechamber در فرمت prepi (فرمت استاندارد AMBER برای اسیدآمینه‌های
غیراستاندارد با اتم‌های head/tail مشخص)

اجرا با: pymol -cq merge_covalent_residue.py
"""

from pymol import cmd

cmd.load("cys124_no_HG.pdb", "cys_part")
cmd.load("adduct_positioned.pdb", "adduct_part")

# حذف اتم S1 تکراری از adduct (چون SG سیستئین همان نقش را ایفا می‌کند)
# در واقع در ساختار نهایی، فقط یک اتم گوگرد باید وجود داشته باشد: SG از سیستئین
# پس اتم S1 از adduct را حذف کرده و باقی adduct را مستقیماً به SG متصل می‌کنیم
cmd.remove("adduct_part and name S1")
print("اتم S1 (تکراری) از adduct حذف شد؛ SG سیستئین به‌عنوان گوگرد مشترک باقی می‌ماند.")

# تغییر نام residue هر دو بخش به یک نام و شماره‌ی یکسان تا PyMOL آن‌ها را یک residue واحد بداند
cmd.alter("cys_part", "resn='CYQ'")
cmd.alter("adduct_part", "resn='CYQ'")
cmd.alter("cys_part", "resi='124'")
cmd.alter("adduct_part", "resi='124'")
cmd.alter("cys_part", "chain='A'")
cmd.alter("adduct_part", "chain='A'")

# تغییر نام اتم‌های adduct تا با اتم‌های موجود در Cys تداخل نداشته باشند (پیشوند X)
# به جز C8 که مستقیماً به SG متصل است و باید نامی منحصربه‌فرد و قابل شناسایی داشته باشد
space = {"renamed": []}
cmd.iterate("adduct_part", "renamed.append((ID, name))", space=space)
for atom_id, name in space["renamed"]:
    new_name = f"L{name}" if not name.startswith("L") else name
    cmd.alter(f"adduct_part and id {atom_id}", f"name='{new_name[:4]}'")

cmd.rebuild()

# ذخیره‌ی residue ترکیبی نهایی
cmd.save("CYQ_residue.pdb", "cys_part or adduct_part")
print("فایل CYQ_residue.pdb (residue ترکیبی Cys124+adduct) ذخیره شد.")

# گزارش تعداد اتم‌های نهایی
n_total = cmd.count_atoms("cys_part or adduct_part")
print(f"تعداد کل اتم‌های residue ترکیبی CYQ: {n_total}")
