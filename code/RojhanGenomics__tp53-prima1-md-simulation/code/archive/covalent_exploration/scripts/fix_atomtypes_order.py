import os, glob

# ۱. حذف فراخوانی‌های احتمالی cyq_atomtypes از داخل سایر فایل‌های itp
for itp in glob.glob("*.itp"):
    if "atomtypes" in itp:
        continue
    with open(itp, 'r') as f:
        content = f.read()
    if "cyq_atomtypes.itp" in content:
        lines = content.splitlines()
        new_lines = [l for l in lines if "cyq_atomtypes.itp" not in l]
        with open(itp, 'w') as f:
            f.write("\n".join(new_lines) + "\n")
        print(f"فراخوانی cyq_atomtypes از داخل {itp} حذف شد.")

# ۲. بازسازی مرتب topol.top
with open("topol.top", "r") as f:
    lines = f.readlines()

lines = [l for l in lines if "cyq_atomtypes.itp" not in l]

new_lines = []
inserted = False

for line in lines:
    new_lines.append(line)
    if "forcefield.itp" in line and not inserted:
        new_lines.append('; Include ligand atomtypes BEFORE any moleculetype\n#include "cyq_atomtypes.itp"\n')
        inserted = True

with open("topol.top", "w") as f:
    f.writelines(new_lines)

print("فایل topol.top با موفقیت اصلاح شد.")
