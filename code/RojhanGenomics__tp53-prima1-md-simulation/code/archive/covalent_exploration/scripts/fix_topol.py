import re

# 1. خواندن تعداد اتم‌ها و مولکول‌ها از nvt.gro
with open("nvt.gro", "r") as f:
    gro_lines = f.readlines()

total_gro_atoms = int(gro_lines[1].strip())

# شمارش دقیق مولکول‌های آب (SOL) و یون‌ها در GRO
sol_count = 0
na_count = 0
cl_count = 0

prev_res = None
for line in gro_lines[2:-1]:
    if len(line) < 20:
        continue
    res_num = line[:5].strip()
    res_name = line[5:10].strip()
    
    if res_num != prev_res:
        if res_name in ["SOL", "OW", "TIP3"]:
            sol_count += 1
        elif res_name == "NA":
            na_count += 1
        elif res_name == "CL":
            cl_count += 1
        prev_res = res_num

print(f"تعداد واقعی در nvt.gro -> آب (SOL): {sol_count} | سدیم (NA): {na_count} | کلر (CL): {cl_count}")

# 2. اصلاح فایل topol.top
with open("topol.top", "r") as f:
    top_lines = f.readlines()

new_top = []
in_molecules = False
seen_mols = set()

for line in top_lines:
    if line.strip().startswith("[ molecules ]"):
        in_molecules = True
        new_top.append(line)
        continue
    
    if in_molecules:
        if line.strip().startswith(";") or not line.strip():
            new_top.append(line)
            continue
        
        parts = line.split()
        if len(parts) >= 2:
            mol_name = parts[0]
            
            # جلوگیری از تکرار بخش‌های پروتئین و لیگاند
            if mol_name in ["Protein_chain_A", "Ion_chain_A2", "CYQ"]:
                if mol_name not in seen_mols:
                    new_top.append(f"{mol_name:<15} 1\n")
                    seen_mols.add(mol_name)
            elif mol_name == "SOL":
                if "SOL" not in seen_mols and sol_count > 0:
                    new_top.append(f"{'SOL':<15} {sol_count}\n")
                    seen_mols.add("SOL")
            elif mol_name == "NA":
                if "NA" not in seen_mols and na_count > 0:
                    new_top.append(f"{'NA':<15} {na_count}\n")
                    seen_mols.add("NA")
            elif mol_name == "CL":
                if "CL" not in seen_mols and cl_count > 0:
                    new_top.append(f"{'CL':<15} {cl_count}\n")
                    seen_mols.add("CL")
    else:
        new_top.append(line)

with open("topol.top", "w") as f:
    f.writelines(new_top)

print("فایل topol.top با موفقیت اصلاح و به‌روزرسانی شد.")
