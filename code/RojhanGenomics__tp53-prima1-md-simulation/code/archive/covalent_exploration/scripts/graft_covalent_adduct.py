"""
پیوند دادن (grafting) ساختار MQ_adduct به residue واقعی Cys124
در ساختار پروتئین equilibrated (منبع: 2OCJ_chainA_clean.pdb)

روش: مختصات اتم گوگرد (S1) در adduct را روی مختصات اتم SG سیستئین124
منطبق می‌کنیم (align/translate)، سپس باقی‌مانده‌ی زنجیره‌ی جانبی Cys
(اتم HG که هیدروژن تیول است) را حذف می‌کنیم چون دیگر در پیوند کووالانت
جایی ندارد.

توجه: residue شماره‌ی 124 در PDB اصلی برابر است با residue شماره‌ی
29 در شماره‌گذاری داخلی GROMACS (124 - 95 = 29).

اجرا با: pymol -cq graft_covalent_adduct.py
"""

from pymol import cmd

PROTEIN_PDB = "2OCJ_chainA_clean.pdb"
ADDUCT_PDB = "MQ_adduct.pdb"
CYS_RESI_ORIGINAL = 124  # شماره‌ی residue در PDB اصلی

cmd.load(PROTEIN_PDB, "protein")
cmd.load(ADDUCT_PDB, "adduct")

# بررسی که واقعاً residue 124 سیستئین است
cmd.select("cys124", f"protein and resi {CYS_RESI_ORIGINAL} and resn CYS")
n_atoms = cmd.count_atoms("cys124")
print(f"تعداد اتم‌های Cys{CYS_RESI_ORIGINAL} در پروتئین: {n_atoms}")
if n_atoms == 0:
    raise ValueError(f"residue {CYS_RESI_ORIGINAL} به عنوان CYS پیدا نشد! شماره‌گذاری را بررسی کنید.")

# مختصات اتم گوگرد سیستئین (SG) در پروتئین
sg_coord = cmd.get_atom_coords(f"protein and resi {CYS_RESI_ORIGINAL} and name SG")
print(f"مختصات SG سیستئین{CYS_RESI_ORIGINAL}: {sg_coord}")

# مختصات اتم گوگرد در adduct (S1) - این باید روی همان محل SG بنشیند
s1_coord = cmd.get_atom_coords("adduct and name S1")
print(f"مختصات S1 در adduct (قبل از انتقال): {s1_coord}")

# انتقال کل adduct طوری که S1 دقیقا روی مکان SG سیستئین بنشیند
translation = [sg_coord[i] - s1_coord[i] for i in range(3)]
cmd.translate(translation, "adduct", camera=0)

s1_new = cmd.get_atom_coords("adduct and name S1")
print(f"مختصات S1 پس از انتقال: {s1_new}")

# ذخیره‌ی ساختار ترکیبی برای بازرسی بصری (پروتئین + adduct منتقل‌شده)
cmd.save("protein_plus_adduct_raw.pdb", "protein or adduct")
print("\nفایل protein_plus_adduct_raw.pdb ذخیره شد.")
print("این فایل را در PyMOL گرافیکی باز کنید و بررسی کنید که آیا اتم S1")
print("adduct دقیقاً نزدیک به موقعیت SG سیستئین124 نشسته و از نظر هندسی")
print("(بدون برخورد شدید با اتم‌های مجاور) معقول است.")
