import os

# ۱. استخراج تعداد اتم‌های هر moleculetype از فایل‌های itp و top
mol_atom_counts = {}

def parse_itp_or_top(filename):
    if not os.path.exists(filename):
        return
    current_mol = None
    in_atoms = False
    atom_count = 0
    with open(filename, "r") as f:
        for line in f:
            line = line.split(";")[0].strip()
            if not line:
                continue
            if line.startswith("["):
                h_name = line.replace("[", "").replace("]", "").strip()
                if h_name == "moleculetype":
                    if current_mol and atom_count > 0:
                        mol_atom_counts[current_mol] = atom_count
                    current_mol = None
                    in_atoms = False
                elif h_name == "atoms":
                    in_atoms = True
                    atom_count = 0
                else:
                    in_atoms = False
                continue
            
            if current_mol is None and not in_atoms:
                parts = line.split()
                if parts:
                    current_mol = parts[0]
            elif in_atoms:
                parts = line.split()
                if len(parts) >= 4 and parts[0].isdigit():
                    atom_count += 1
        if current_mol and atom_count > 0:
            mol_atom_counts[current_mol] = atom_count

parse_itp_or_top("topol.top")
for fname in os.listdir("."):
    if fname.endswith(".itp"):
        parse_itp_or_top(fname)

mol_atom_counts.setdefault("SOL", 3)
mol_atom_counts.setdefault("CL", 1)
mol_atom_counts.setdefault("NA", 1)

print("=== ۱. تعداد اتم‌های تعریف‌شده برای هر moleculetype ===")
for k, v in mol_atom_counts.items():
    print(f"  {k}: {v} اتم")

# ۲. خواندن npt.gro و دسته‌بندی مولکول‌ها بر اساس ساختار واقعی
print("\n=== ۲. آنالیز دقیق فایل npt.gro ===")
with open("npt.gro", "r") as f:
    lines = f.readlines()

header = lines[0].strip()
total_atoms = int(lines[1].strip())
atom_lines = lines[2:total_atoms + 2]

# تفکیک بر اساس Residue
residues = []
current_res_id = None
current_res_name = None
current_count = 0

for line in atom_lines:
    res_id = line[0:5].strip()
    res_name = line[5:10].strip()
    
    if res_id != current_res_id or res_name != current_res_name:
        if current_res_name is not None:
            residues.append((current_res_name, current_count))
        current_res_id = res_id
        current_res_name = res_name
        current_count = 1
    else:
        current_count += 1

if current_res_name is not None:
    residues.append((current_res_name, current_count))

# شمارش مولکول‌ها
molecules_summary = []
protein_atom_sum = 0
sol_atom_sum = 0
cl_count = 0
na_count = 0
other_mols = []

for rname, rcount in residues:
    if rname in ["SOL", "TIP3", "WAT", "HOH"]:
        sol_atom_sum += rcount
    elif rname in ["CL", "CLA", "CL-"]:
        cl_count += 1
    elif rname in ["NA", "SOD", "NA+"]:
        na_count += 1
    elif rname in ["CYQ", "UNL", "PRIMA1", "ZN"]:
        other_mols.append((rname, rcount))
    else:
        protein_atom_sum += rcount

print(f"  کل اتم‌های پروتئین: {protein_atom_sum}")
for om in other_mols:
    print(f"  مولکول/یون غیرپروتئینی: {om[0]} با {om[1]} اتم")
print(f"  کل اتم‌های آب: {sol_atom_sum} (تعداد مولکول: {sol_atom_sum // 3})")
print(f"  تعداد کلر (CL): {cl_count}")

# ۳. بازنویسی بخش [ molecules ]
print("\n=== ۳. اصلاح topol.top ===")
with open("topol.top", "r") as f:
    top_lines = f.readlines()

new_top = []
for line in top_lines:
    if line.strip().startswith("[ molecules ]"):
        break
    new_top.append(line)

new_top.append("[ molecules ]\n")
new_top.append("; Compound        #mols\n")
new_top.append(f"{'Protein_chain_A':<15} 1\n")

if "Ion_chain_A2" in mol_atom_counts:
    new_top.append(f"{'Ion_chain_A2':<15} 1\n")

# اضافه کردن لیگاندها بر اساس آنچه در npt.gro وجود دارد
for om_name, _ in other_mols:
    if om_name == "CYQ" and "CYQ" in mol_atom_counts:
        new_top.append(f"{'CYQ':<15} 1\n")
    elif om_name == "PRIMA1" and "PRIMA1" in mol_atom_counts:
        new_top.append(f"{'PRIMA1':<15} 1\n")

sol_mols = sol_atom_sum // 3
new_top.append(f"{'SOL':<15} {sol_mols}\n")
if cl_count > 0:
    new_top.append(f"{'CL':<15} {cl_count}\n")
if na_count > 0:
    new_top.append(f"{'NA':<15} {na_count}\n")

with open("topol.top", "w") as f:
    f.writelines(new_top)

# محاسبه مجموع اتم‌های جدید توپولوژی برای اطمینان
top_total = mol_atom_counts.get("Protein_chain_A", protein_atom_sum)
if "Ion_chain_A2" in mol_atom_counts:
    top_total += mol_atom_counts["Ion_chain_A2"]
for om_name, _ in other_mols:
    if om_name in mol_atom_counts:
        top_total += mol_atom_counts[om_name]
top_total += sol_mols * 3 + cl_count + na_count

print(f"\nتعداد کل اتم‌ها در npt.gro: {total_atoms}")
print(f"تعداد کل اتم‌ها در topol.top اصلاح‌شده: {top_total}")

