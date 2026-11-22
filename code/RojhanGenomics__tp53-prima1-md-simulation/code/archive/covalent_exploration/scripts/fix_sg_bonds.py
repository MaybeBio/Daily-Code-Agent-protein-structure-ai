import os

mol2_file = "CYQ_fixed.mol2"
output_file = "CYQ_ready.mol2"

with open(mol2_file, "r") as f:
    lines = f.readlines()

# ۱. یافتن کد اتم‌های SG و CC9
sg_id = None
cc9_id = None

in_atoms = False
for line in lines:
    if "@<TRIPOS>ATOM" in line:
        in_atoms = True
        continue
    elif line.startswith("@<TRIPOS>"):
        in_atoms = False

    if in_atoms and line.strip():
        parts = line.split()
        atom_id, atom_name = parts[0], parts[1]
        if atom_name == "SG":
            sg_id = atom_id
        elif atom_name in ["CC9", "C9", "LC9"]:
            cc9_id = atom_id

print(f"شناسه اتم SG: {sg_id} | شناسه اتم CC9: {cc9_id}")

# ۲. بازنویسی بخش BONDها و حذف پیوند کاذب SG-CC9
new_lines = []
in_bonds = False
bond_count = 1

for line in lines:
    if "@<TRIPOS>BOND" in line:
        in_bonds = True
        new_lines.append(line)
        continue
    elif line.startswith("@<TRIPOS>") and in_bonds:
        in_bonds = False

    if in_bonds:
        if not line.strip():
            continue
        parts = line.split()
        a1, a2 = parts[1], parts[2]
        
        # حذف پیوند بین SG و CC9
        if (a1 == sg_id and a2 == cc9_id) or (a1 == cc9_id and a2 == sg_id):
            print(f"پیوند کاذب حذف شد: اتم {a1} به اتم {a2}")
            continue
        
        # بازنویسی شماره پیوندها
        bond_type = parts[3] if len(parts) > 3 else "1"
        new_lines.append(f"{bond_count:6d}{int(a1):6d}{int(a2):6d} {bond_type}\n")
        bond_count += 1
    else:
        new_lines.append(line)

with open(output_file, "w") as f:
    f.writelines(new_lines)

print(f"فایل اصلاح‌شده در {output_file} ذخیره شد.")
