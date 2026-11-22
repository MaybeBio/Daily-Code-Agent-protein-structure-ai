"""
اسکریپت پاک‌سازی ساختار p53 core domain (PDB: 2OCJ) با PyMOL
اجرا با: pymol -cq clean_2ocj.py
"""

from pymol import cmd

# مسیر فایل ورودی و خروجی
INPUT_PDB = "2OCJ.pdb"
OUTPUT_PDB = "2OCJ_chainA_clean.pdb"

# بارگذاری ساختار
cmd.load(INPUT_PDB, "p53")

# نگه داشتن فقط chain A (یکی از چهار مولکول موجود در unit cell)
cmd.remove("not chain A")

# حذف آب‌های کریستالی (در سالوِیشن دوباره آب اضافه می‌کنیم)
cmd.remove("resn HOH")

# بررسی وجود یون Zn (برای پایداری ساختاری core domain ضروریه - نباید حذف بشه)
zn_count = cmd.count_atoms("resn ZN")
print(f"تعداد اتم‌های Zn باقی‌مانده: {zn_count}")
if zn_count == 0:
    print("هشدار: هیچ یون روی نگه داشته نشده! ساختار core domain بدون Zn ناپایدار می‌مونه.")

# بررسی تعداد residueها (باید نزدیک به ~219 باشه طبق annotation دامنه)
residue_count = cmd.count_atoms("name CA and polymer")
print(f"تعداد residueهای پروتئین (بر اساس اتم CA): {residue_count}")

# ذخیره‌ی نسخه‌ی پاک‌شده
cmd.save(OUTPUT_PDB, "p53")
print(f"ساختار پاک‌شده ذخیره شد در: {OUTPUT_PDB}")
