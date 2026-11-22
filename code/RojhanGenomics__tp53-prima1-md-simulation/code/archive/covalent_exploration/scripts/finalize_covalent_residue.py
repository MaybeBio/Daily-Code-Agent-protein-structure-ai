"""
نهایی‌سازی residue ترکیبی کووالانت:
- حذف اتم HG (هیدروژن تیول) از Cys124 در پروتئین
- ادغام مختصات Cys124 (بدون HG) با adduct منتقل‌شده
- ذخیره‌ی این residue ترکیبی به‌صورت جداگانه برای بررسی و آماده‌سازی tleap

اجرا با: pymol -cq finalize_covalent_residue.py
"""

from pymol import cmd

CYS_RESI_ORIGINAL = 124

cmd.load("2OCJ_chainA_clean.pdb", "protein")
cmd.load("MQ_adduct.pdb", "adduct")

# انجام مجدد انتقال (برای اطمینان از سازگاری با اسکریپت قبلی)
sg_coord = cmd.get_atom_coords(f"protein and resi {CYS_RESI_ORIGINAL} and name SG")
s1_coord = cmd.get_atom_coords("adduct and name S1")
translation = [sg_coord[i] - s1_coord[i] for i in range(3)]
cmd.translate(translation, "adduct", camera=0)

# حذف اتم HG از سیستئین (دیگر جایی در پیوند کووالانت ندارد)
cmd.remove(f"protein and resi {CYS_RESI_ORIGINAL} and name HG")
print(f"اتم HG از Cys{CYS_RESI_ORIGINAL} حذف شد.")

# بررسی فاصله‌ی اتم متصل‌شونده‌ی adduct (C8) تا SG - باید نزدیک به طول پیوند C-S باشد (~1.8 Å)
c8_coord = cmd.get_atom_coords("adduct and name C8")
sg_new = cmd.get_atom_coords(f"protein and resi {CYS_RESI_ORIGINAL} and name SG")
dist = sum((c8_coord[i] - sg_new[i])**2 for i in range(3)) ** 0.5
print(f"فاصله‌ی C8(adduct) تا SG(Cys{CYS_RESI_ORIGINAL}): {dist:.3f} Å (مقدار مرجع پیوند C-S: ~1.8 Å)")

# ذخیره‌ی هر بخش جداگانه برای استفاده در گام بعدی (ساخت residue سفارشی در tleap)
cmd.save("cys124_no_HG.pdb", f"protein and resi {CYS_RESI_ORIGINAL}")
cmd.save("adduct_positioned.pdb", "adduct")

# ذخیره‌ی کل پروتئین (با Cys124 بدون HG) برای مرحله‌ی بعدی ساخت توپولوژی کامل
cmd.save("protein_for_covalent.pdb", "protein")

print("\nفایل‌های ذخیره‌شده:")
print("  cys124_no_HG.pdb       - فقط residue Cys124 (بدون HG)")
print("  adduct_positioned.pdb  - adduct در موقعیت نهایی")
print("  protein_for_covalent.pdb - کل پروتئین (با Cys124 اصلاح‌شده)")
