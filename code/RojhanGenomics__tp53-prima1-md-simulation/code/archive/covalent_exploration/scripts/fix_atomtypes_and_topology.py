import os

# ۱. بازگردانی PRIMA1.itp از بک‌آ‌پ یا فعال‌سازی مجدد آن
if os.path.exists("backup_today/PRIMA1.itp"):
    with open("backup_today/PRIMA1.itp", "r") as f:
        prima1_raw = f.read()
else:
    with open("PRIMA1.itp", "r") as f:
        prima1_raw = f.read()
    lines = prima1_raw.splitlines()
    uncommented = []
    for line in lines:
        if line.strip().startswith("; [ atomtypes") or line.strip().startswith("; [atomtypes"):
            uncommented.append(line.replace("; ", "", 1))
        elif line.strip().startswith(";") and len(line.split()) >= 6 and not line.strip().startswith("; Include"):
            uncommented.append(line.replace(";", "", 1))
        else:
            uncommented.append(line)
    prima1_raw = "\n".join(uncommented)

# ۲. جداسازی بخش [ atomtypes ] از بدنه PRIMA1.itp
lines = prima1_raw.splitlines()
atomtypes_lines = []
molecule_lines = []
in_atomtypes = False

for line in lines:
    clean = line.strip()
    if clean.startswith("[") and "atomtypes" in clean:
        in_atomtypes = True
        atomtypes_lines.append("[ atomtypes ]\n")
        continue
    elif clean.startswith("[") and "atomtypes" not in clean:
        in_atomtypes = False

    if in_atomtypes:
        if clean:
            atomtypes_lines.append(line + "\n")
    else:
        molecule_lines.append(line + "\n")

# ذخیره فایل مجزای atomtypes
if atomtypes_lines:
    with open("PRIMA1_atomtypes.itp", "w") as f:
        f.writelines(atomtypes_lines)
    print("فایل PRIMA1_atomtypes.itp با موفقیت ساخته شد.")

# به‌روزرسانی PRIMA1.itp بدون بخش atomtypes
with open("PRIMA1.itp", "w") as f:
    f.writelines(molecule_lines)
print("فایل PRIMA1.itp با موفقیت اصلاح شد.")

# ۳. تنظیم و مرتب‌سازی فایل topol.top
with open("topol.top", "r") as f:
    topol_lines = f.readlines()

cleaned_topol = [l for l in topol_lines if not any(k in l for k in ["PRIMA1_atomtypes.itp", "PRIMA1.itp", "cyq_atomtypes.itp"])]

new_topol = []
inserted_atomtypes = False
inserted_molecule = False

for line in cleaned_topol:
    new_topol.append(line)
    
    # اضافه کردن تمام atomtypesها بلافاصله پس از forcefield
    if "forcefield.itp" in line and not inserted_atomtypes:
        new_topol.append('\n; Extra atomtypes (must be included before any moleculetype)\n')
        if os.path.exists("cyq_atomtypes.itp"):
            new_topol.append('#include "cyq_atomtypes.itp"\n')
        if os.path.exists("PRIMA1_atomtypes.itp"):
            new_topol.append('#include "PRIMA1_atomtypes.itp"\n')
        new_topol.append('\n')
        inserted_atomtypes = True

    # اضافه کردن توپولوژی PRIMA1.itp قبل از بخش system
    if ("[ system ]" in line or "[ molecules ]" in line) and not inserted_molecule:
        last_line = new_topol.pop()
        new_topol.append('; Include PRIMA1 topology\n#include "PRIMA1.itp"\n\n')
        new_topol.append(last_line)
        inserted_molecule = True

with open("topol.top", "w") as f:
    f.writelines(new_topol)

print("فایل topol.top کاملاً مرتب و آماده گردید.")
