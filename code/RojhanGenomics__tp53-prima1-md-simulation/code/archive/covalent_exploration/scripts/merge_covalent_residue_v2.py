"""
نسخه‌ی اصلاح‌شده: ساخت residue ترکیبی CYQ (Cys124 + adduct) با استفاده از
ساختار equilibrated (npt_protein.pdb) که هیدروژن‌های backbone را به‌درستی
از GROMACS/AMBER99SB-ILDN دارد - به این ترتیب دیگر نیازی به اضافه کردن
دستی هیدروژن نیست.

توجه: در npt_protein.pdb، شماره‌گذاری residueها بر اساس شماره‌گذاری داخلی
GROMACS است (از 1 شروع می‌شود)، نه شماره‌گذاری اصلی PDB.
residue 124 در PDB اصلی = residue (124-95)=29 در GROMACS.

اجرا با: pymol -cq merge_covalent_residue_v2.py
"""

from pymol import cmd

CYS_RESI_GROMACS = 124  # معادل residue 124 در شماره‌گذاری اصلی PDB

cmd.load("npt_protein.pdb", "protein")
cmd.load("MQ_adduct.pdb", "adduct")

# بررسی که residue 29 واقعاً سیستئین است
cmd.select("cys_check", f"protein and resi {CYS_RESI_GROMACS} and resn CYS")
n_check = cmd.count_atoms("cys_check")
print(f"تعداد اتم‌های residue {CYS_RESI_GROMACS} (باید Cys124 باشد): {n_check}")
if n_check == 0:
    raise ValueError("residue مورد انتظار به عنوان CYS پیدا نشد!")

# مختصات SG از ساختار equilibrated
sg_coord = cmd.get_atom_coords(f"protein and resi {CYS_RESI_GROMACS} and name SG")
s1_coord = cmd.get_atom_coords("adduct and name S1")
translation = [sg_coord[i] - s1_coord[i] for i in range(3)]
cmd.translate(translation, "adduct", camera=0)

dist_check = cmd.get_distance(
    f"protein and resi {CYS_RESI_GROMACS} and name SG", "adduct and name S1"
)
print(f"فاصله‌ی SG تا S1 پس از انتقال (باید ~0 باشد): {dist_check:.4f} Å")

# حذف HG (هیدروژن تیول) و S1 (گوگرد تکراری adduct)
cmd.remove(f"protein and resi {CYS_RESI_GROMACS} and name HG")
cmd.remove("adduct and name S1")
print("اتم HG (از Cys) و S1 (از adduct) حذف شدند.")

# بررسی فاصله‌ی پیوند جدید C8(adduct)-SG(Cys)
dist_bond = cmd.get_distance(
    f"protein and resi {CYS_RESI_GROMACS} and name SG", "adduct and name C8"
)
print(f"طول پیوند جدید SG-C8: {dist_bond:.3f} Å (مرجع: ~1.8 Å)")

# استخراج و ادغام residue نهایی
cmd.create("cys_final", f"protein and resi {CYS_RESI_GROMACS}")
cmd.create("adduct_final", "adduct")

cmd.alter("cys_final", "resn='CYQ'")
cmd.alter("adduct_final", "resn='CYQ'")
cmd.alter("cys_final", f"resi='{CYS_RESI_GROMACS}'")
cmd.alter("adduct_final", f"resi='{CYS_RESI_GROMACS}'")
cmd.alter("cys_final", "chain='A'")
cmd.alter("adduct_final", "chain='A'")

# تغییر نام اتم‌های adduct با پیشوند L برای جلوگیری از تداخل نام
space = {"names": []}
cmd.iterate("adduct_final", "names.append(ID)", space=space)
for atom_id in space["names"]:
    cmd.alter(f"adduct_final and id {atom_id}", "name='L'+name if not name.startswith('L') else name")

cmd.rebuild()
cmd.save("CYQ_residue_v2.pdb", "cys_final or adduct_final")

n_total = cmd.count_atoms("cys_final or adduct_final")
print(f"\nتعداد اتم‌های residue ترکیبی نهایی (شامل هیدروژن‌های صحیح): {n_total}")
print("فایل ذخیره شد: CYQ_residue_v2.pdb")
