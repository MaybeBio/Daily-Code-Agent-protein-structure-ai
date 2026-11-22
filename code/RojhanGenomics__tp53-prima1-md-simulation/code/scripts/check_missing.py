"""
بررسی residueهای گمشده (missing) در chain A از فایل اصلی 2OCJ.pdb
اجرا با: pymol -cq check_missing.py
"""

from pymol import cmd

cmd.load("2OCJ.pdb", "orig")

# گرفتن لیست شماره‌ی residueهای موجود در chain A
model = cmd.get_model("chain A and polymer and name CA")
resi_list = sorted(set(int(atom.resi) for atom in model.atom))

print(f"تعداد residueهای موجود: {len(resi_list)}")
print(f"کوچک‌ترین شماره residue: {min(resi_list)}")
print(f"بزرگ‌ترین شماره residue: {max(resi_list)}")

# پیدا کردن شکاف‌ها (gaps) در توالی شماره‌ها
gaps = []
for i in range(len(resi_list) - 1):
    if resi_list[i+1] - resi_list[i] > 1:
        gaps.append((resi_list[i], resi_list[i+1]))

if gaps:
    print("\nشکاف‌های موجود در توالی (residueهای گمشده):")
    for start, end in gaps:
        missing_count = end - start - 1
        print(f"  بین residue {start} و {end}: {missing_count} residue گمشده")
else:
    print("\nهیچ شکافی در توالی پیدا نشد.")
