import os

print("=== ۱. بررسی گروه های مورد نیاز در md.mdp ===")
mdp_groups = set()
if os.path.exists("md.mdp"):
    with open("md.mdp", "r") as f:
        for line in f:
            line = line.split(";")[0].strip()
            if "=" in line:
                key, val = line.split("=", 1)
                if key.strip().lower() in ["tc-grps", "energygrps", "compressed-x-grps", "xtc-grps"]:
                    for g in val.split():
                        mdp_groups.add(g.strip())
print(f"گروه‌های مورد نیاز md.mdp: {mdp_groups}")

print("\n=== ۲. آنالیز ساختار npt.gro ===")
with open("npt.gro", "r") as f:
    lines = [l for l in f.readlines() if l.strip()]

total_gro_atoms = int(lines[1].strip())
atom_lines = lines[2:-1]

residues = []
current_res_num = None
current_res_name = None
current_res_atoms = []

for line in atom_lines:
    if len(line) < 20:
        continue
    res_num = line[:5].strip()
    res_name = line[5:10].strip()
    atom_id = int(line[15:20].strip())
    
    if res_num != current_res_num or res_name != current_res_name:
        if current_res_name is not None:
            residues.append((current_res_num, current_res_name, current_res_atoms))
        current_res_num = res_num
        current_res_name = res_name
        current_res_atoms = [atom_id]
    else:
        current_res_atoms.append(atom_id)

if current_res_name is not None:
    residues.append((current_res_num, current_res_name, current_res_atoms))

blocks = []
curr_block_name = None
curr_block_atoms = []
curr_block_count = 0

for rnum, rname, ratoms in residues:
    m_type = rname
    if rname in ["SOL", "WAT", "TIP3", "H2O"]:
        m_type = "SOL"
    elif rname in ["CL", "CLA", "CL-"]:
        m_type = "CL"
    elif rname in ["NA", "SOD", "NA+"]:
        m_type = "NA"
    elif rname == "ZN":
        m_type = "Ion_chain_A2"
    
    if curr_block_name is None:
        curr_block_name = m_type
        curr_block_atoms = list(ratoms)
        curr_block_count = 1
    elif m_type == curr_block_name:
        curr_block_atoms.extend(ratoms)
        curr_block_count += 1
    else:
        blocks.append((curr_block_name, curr_block_count, len(curr_block_atoms), curr_block_atoms[0], curr_block_atoms[-1]))
        curr_block_name = m_type
        curr_block_atoms = list(ratoms)
        curr_block_count = 1

if curr_block_name is not None:
    blocks.append((curr_block_name, curr_block_count, len(curr_block_atoms), curr_block_atoms[0], curr_block_atoms[-1]))

print("بلاک‌های شناسایی‌شده در npt.gro:")
for bname, bcount, batoms, bstart, bend in blocks:
    print(f"  مولکول/گروه: {bname:<15} | تعداد: {bcount:<6} | اتم‌ها: {batoms:<6} (از {bstart} تا {bend})")

print("\n=== ۳. شمارش دقیق اتم‌ها در topol.top و itp ها ===")
mol_atom_counts = {}

def parse_itp(filename):
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

parse_itp("topol.top")
for fname in os.listdir("."):
    if fname.endswith(".itp"):
        parse_itp(fname)

mol_atom_counts.setdefault("SOL", 3)
mol_atom_counts.setdefault("CL", 1)
mol_atom_counts.setdefault("NA", 1)

print(f"تعداد اتم هر moleculetype: {mol_atom_counts}")

print("\n=== ۴. اصلاح بخش [ molecules ] در topol.top ===")
with open("topol.top", "r") as f:
    top_lines = f.readlines()

clean_top = []
for line in top_lines:
    if line.strip().startswith("[ molecules ]"):
        clean_top.append("[ molecules ]\n; Compound        #mols\n")
        break
    clean_top.append(line)

defined_mols = list(mol_atom_counts.keys())
total_top_atoms = 0

for bname, bcount, batoms, bstart, bend in blocks:
    target_mol = None
    if bname in mol_atom_counts:
        target_mol = bname
    else:
        for dm in defined_mols:
            if dm.lower() in bname.lower() or bname.lower() in dm.lower():
                target_mol = dm
                break
            if "protein" in dm.lower() and bname not in ["SOL", "CL", "NA", "Ion_chain_A2", "CYQ", "UNL"]:
                target_mol = dm
                break
    
    if target_mol is None:
        target_mol = bname

    atoms_per_mol = mol_atom_counts.get(target_mol, 1)
    actual_mols = batoms // atoms_per_mol if atoms_per_mol > 0 else bcount
    clean_top.append(f"{target_mol:<15} {actual_mols}\n")
    total_top_atoms += actual_mols * atoms_per_mol

with open("topol.top", "w") as f:
    f.writelines(clean_top)

print(f"فایل topol.top به روزرسانی شد. کل اتم‌های توپولوژی: {total_top_atoms} (مطابق با npt.gro: {total_gro_atoms})")

print("\n=== ۵. به روزرسانی index.ndx ===")
existing_groups = set()
if os.path.exists("index.ndx"):
    with open("index.ndx", "r") as f:
        for line in f:
            line_str = line.strip()
            if line_str.startswith("[") and line_str.endswith("]"):
                existing_groups.add(line_str.replace("[", "").replace("]", "").strip())

non_water_atoms = []
water_and_ion_atoms = []

for bname, bcount, batoms, bstart, bend in blocks:
    if bname in ["SOL", "CL", "NA"]:
        water_and_ion_atoms.extend(range(bstart, bend + 1))
    else:
        non_water_atoms.extend(range(bstart, bend + 1))

def make_ndx_block(gname, atom_list):
    res = f"\n[ {gname} ]\n"
    for i in range(0, len(atom_list), 15):
        res += " ".join(f"{a:5d}" for a in atom_list[i:i+15]) + "\n"
    return res

new_ndx_content = ""
for req_grp in mdp_groups:
    if req_grp not in existing_groups:
        print(f"ایجاد گروه مفقودشده برای index.ndx: '{req_grp}'")
        if req_grp in ["Water_and_ions", "SOL_CL", "Water_Ions"]:
            new_ndx_content += make_ndx_block(req_grp, water_and_ion_atoms)
        else:
            new_ndx_content += make_ndx_block(req_grp, non_water_atoms)

if new_ndx_content:
    with open("index.ndx", "a") as f:
        f.write(new_ndx_content)
    print("گروه‌های جدید با موفقیت به index.ndx اضافه شدند.")
else:
    print("تمام گروه‌های مورد نیاز در index.ndx موجود هستند.")

print("\n=== اصلاحات با موفقیت پایان یافت ===")
