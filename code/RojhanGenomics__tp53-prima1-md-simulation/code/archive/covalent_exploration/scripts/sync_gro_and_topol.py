import os

print("=== ۱. خواندن ساختار اتم‌های پروتئین از توپولوژی ===")
top_file = "topol_Protein_chain_A.itp"
if not os.path.exists(top_file):
    top_file = "topol.top"

top_atoms = []
in_protein = False
in_atoms = False

with open(top_file, "r") as f:
    for line in f:
        l = line.split(";")[0].strip()
        if not l:
            continue
        if l.startswith("["):
            h = l.replace("[","").replace("]","").strip()
            if h == "moleculetype":
                in_protein = False
            elif h == "atoms":
                if in_protein or top_file.endswith(".itp"):
                    in_atoms = True
            else:
                in_atoms = False
            continue
        
        parts = l.split()
        if not in_protein and not in_atoms and len(parts) >= 1:
            if parts[0] == "Protein_chain_A":
                in_protein = True
        elif in_atoms and len(parts) >= 5:
            top_atoms.append({
                'nr': parts[0],
                'type': parts[1],
                'resnr': parts[2],
                'resname': parts[3],
                'atomname': parts[4]
            })

print(f"تعداد اتم‌های Protein_chain_A در توپولوژی: {len(top_atoms)}")

print("\n=== ۲. جداسازی بخش‌های مختلف در فایل npt.gro ===")
with open("npt.gro", "r") as f:
    gro_lines = f.readlines()

header = gro_lines[0]
total_gro_atoms = int(gro_lines[1].strip())
box_line = gro_lines[-1]

atom_lines = gro_lines[2:total_gro_atoms+2]

protein_lines = []
zn_lines = []
ligand_lines = []
sol_lines = []
cl_lines = []
na_lines = []

for line in atom_lines:
    res_name = line[5:10].strip()
    if res_name in ["SOL", "TIP3", "WAT", "HOH"]:
        sol_lines.append(line)
    elif res_name in ["CL", "CLA", "CL-"]:
        cl_lines.append(line)
    elif res_name in ["NA", "SOD", "NA+"]:
        na_lines.append(line)
    elif res_name in ["ZN", "ZN2+"]:
        zn_lines.append(line)
    elif res_name in ["UNL", "PRIMA1", "CYQ"]:
        ligand_lines.append(line)
    else:
        protein_lines.append(line)

print(f"تعداد اتم‌های پروتئین در npt.gro اولیه: {len(protein_lines)}")

print("\n=== ۳. انطباق دقیق اتم‌های پروتئین npt.gro با توپولوژی ===")
matched_protein_lines = []
p_idx = 0

for t_atom in top_atoms:
    t_resnr = t_atom['resnr']
    t_resname = t_atom['resname']
    t_atomname = t_atom['atomname']
    
    found = False
    for search_i in range(p_idx, len(protein_lines)):
        pline = protein_lines[search_i]
        g_resnr = pline[0:5].strip()
        g_resname = pline[5:10].strip()
        g_atomname = pline[10:15].strip()
        
        if g_resnr == t_resnr and (g_atomname == t_atomname or g_resname == t_resname):
            matched_protein_lines.append(pline)
            p_idx = search_i + 1
            found = True
            break
            
    if not found:
        if p_idx < len(protein_lines):
            matched_protein_lines.append(protein_lines[p_idx])
            p_idx += 1

print(f"تعداد اتم‌های پروتئین تطبیق‌یافته: {len(matched_protein_lines)}")

# تغییر نام UNL به PRIMA1 در فایل gro برای یکسانی با توپولوژی
fixed_ligand_lines = []
for line in ligand_lines:
    new_l = line[:5] + f"{'PRIMA1':<5}" + line[10:]
    fixed_ligand_lines.append(new_l)

all_new_atom_lines = matched_protein_lines + zn_lines + fixed_ligand_lines + sol_lines + cl_lines + na_lines

final_gro_lines = [header, f"{len(all_new_atom_lines):>12}\n"]

for idx, line in enumerate(all_new_atom_lines, start=1):
    res_part = line[0:15]
    coord_part = line[20:]
    atom_idx_str = f"{idx % 100000:>5}"
    final_gro_lines.append(f"{res_part}{atom_idx_str}{coord_part}")

final_gro_lines.append(box_line)

with open("npt.gro", "w") as f:
    f.writelines(final_gro_lines)

print(f"فایل npt.gro جدید با {len(all_new_atom_lines)} اتم بازنویسی شد.")

print("\n=== ۴. به‌روزرسانی بخش [ molecules ] در topol.top ===")
sol_mols = len(sol_lines) // 3
cl_mols = len(cl_lines)
na_mols = len(na_lines)

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
if len(zn_lines) > 0:
    new_top.append(f"{'Ion_chain_A2':<15} 1\n")
if len(fixed_ligand_lines) > 0:
    new_top.append(f"{'PRIMA1':<15} 1\n")
new_top.append(f"{'SOL':<15} {sol_mols}\n")
if cl_mols > 0:
    new_top.append(f"{'CL':<15} {cl_mols}\n")
if na_mols > 0:
    new_top.append(f"{'NA':<15} {na_mols}\n")

with open("topol.top", "w") as f:
    f.writelines(new_top)

print("فایل topol.top با موفقیت به روزرسانی شد.")
