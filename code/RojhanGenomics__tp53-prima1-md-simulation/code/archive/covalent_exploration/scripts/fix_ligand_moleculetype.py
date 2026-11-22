import os, glob

print("=== ۱. یافتن فایل itp لیگاند و نام دقیق moleculetype آن ===")

known_types = ["Protein_chain_A", "Ion_chain_A2", "SOL", "CL", "NA", "TIP3", "OW"]
ligand_itp = None
ligand_name = None

itp_files = glob.glob("*.itp")
for itp in itp_files:
    with open(itp, "r") as f:
        in_mol = False
        for line in f:
            l = line.split(";")[0].strip()
            if l.startswith("[") and "moleculetype" in l:
                in_mol = True
                continue
            if in_mol and l and not l.startswith("["):
                m_name = l.split()[0]
                if m_name not in known_types:
                    ligand_itp = itp
                    ligand_name = m_name
                    break
                in_mol = False

print(f"فایل توپولوژی لیگاند: {ligand_itp}")
print(f"نام moleculetype لیگاند در فایل itp: {ligand_name}")

if not ligand_name:
    print("هشدار: فایل itp جداگانه برای لیگاند یافت نشد. در حال بررسی خود topol.top...")
    # بررسی داخل topol.top
    with open("topol.top", "r") as f:
        in_mol = False
        for line in f:
            l = line.split(";")[0].strip()
            if l.startswith("[") and "moleculetype" in l:
                in_mol = True
                continue
            if in_mol and l and not l.startswith("["):
                m_name = l.split()[0]
                if m_name not in known_types:
                    ligand_name = m_name
                    break
                in_mol = False

print(f"\n=== ۲. اصلاح فایل topol.top ===")
with open("topol.top", "r") as f:
    lines = f.readlines()

# ۱. بررسی وجود #include برای فایل itp لیگاند
has_include = False
if ligand_itp:
    for line in lines:
        if ligand_itp in line and line.strip().startswith("#include"):
            has_include = True
            break

new_lines = []
include_inserted = False

for line in lines:
    # افزودن include لیگاند قبل از بخش system
    if not has_include and ligand_itp and line.strip().startswith("[ system ]") and not include_inserted:
        new_lines.append(f'; Include ligand topology\n#include "{ligand_itp}"\n\n')
        include_inserted = True
    
    # اصلاح بخش molecules
    if line.strip().startswith("PRIMA1") or line.strip().startswith("UNL"):
        parts = line.split()
        if len(parts) >= 2:
            new_lines.append(f"{ligand_name:<15} {parts[1]}\n")
            continue
            
    new_lines.append(line)

with open("topol.top", "w") as f:
    f.writelines(new_lines)

print("فایل topol.top با موفقیت اصلاح گردید.")
