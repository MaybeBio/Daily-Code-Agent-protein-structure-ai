import os

print("=== ۱. آنالیز ترتیب دقیق بلوک‌ها در npt.gro ===")
with open("npt.gro", "r") as f:
    lines = [l for l in f.readlines() if l.strip()]

total_gro_atoms = int(lines[1].strip())

res_blocks = []
curr_res_id = None
curr_res_name = None
curr_count = 0

for line in lines[2:-1]:
    if len(line) < 20:
        continue
    res_id = line[0:5].strip()
    res_name = line[5:10].strip()
    
    if res_id != curr_res_id:
        if curr_res_name is not None:
            res_blocks.append((curr_res_id, curr_res_name, curr_count))
        curr_res_id = res_id
        curr_res_name = res_name
        curr_count = 1
    else:
        curr_count += 1

if curr_res_name is not None:
    res_blocks.append((curr_res_id, curr_res_name, curr_count))

print("بلوک‌های شناسایی‌شده در npt.gro:")
for b in res_blocks:
    if b[1] not in ["SOL", "TIP3", "WAT", "HOH"]:
        print(f"  Residue ID: {b[0]:<5} Name: {b[1]:<8} Atoms: {b[2]}")

print("\n=== ۲. شناسه moleculetypeهای تعریف شده در توپولوژی ===")
mol_atom_counts = {}

def parse_top_itp(fname):
    if not os.path.exists(fname):
        return
    curr_mol = None
    in_atoms = False
    count = 0
    with open(fname) as f:
        for line in f:
            line = line.split(";")[0].strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("["):
                h = line.replace("[","").replace("]","").strip()
                if h == "moleculetype":
                    if curr_mol and count > 0:
                        mol_atom_counts[curr_mol] = count
                    curr_mol = None
                    in_atoms = False
                elif h == "atoms":
                    in_atoms = True
                    count = 0
                else:
                    in_atoms = False
                continue
            if curr_mol is None and not in_atoms:
                parts = line.split()
                if parts:
                    curr_mol = parts[0]
            elif in_atoms:
                parts = line.split()
                if len(parts) >= 4 and parts[0].isdigit():
                    count += 1
        if curr_mol and count > 0:
            mol_atom_counts[curr_mol] = count

parse_top_itp("topol.top")
for fn in os.listdir("."):
    if fn.endswith(".itp"):
        parse_top_itp(fn)

mol_atom_counts.setdefault("SOL", 3)
mol_atom_counts.setdefault("CL", 1)
mol_atom_counts.setdefault("NA", 1)

for k, v in mol_atom_counts.items():
    print(f"  moleculetype: {k:<18} -> {v} اتم")

# ۳. تنظیم دقیق بخش [ molecules ]
sol_mols = sum(1 for b in res_blocks if b[1] in ["SOL", "TIP3", "WAT", "HOH"])
cl_mols = sum(1 for b in res_blocks if b[1] in ["CL", "CLA", "CL-"])

with open("topol.top", "r") as f:
    top_lines = f.readlines()

new_top = []
for line in top_lines:
    if line.strip().startswith("[ molecules ]"):
        break
    new_top.append(line)

new_top.append("[ molecules ]\n")
new_top.append("; Compound        #mols\n")

# اضافه کردن moleculetypeها بر اساس آنچه در mol_atom_counts و npt.gro وجود دارد
added_mols = []
if "Protein_chain_A" in mol_atom_counts:
    new_top.append(f"{'Protein_chain_A':<15} 1\n")
    added_mols.append(("Protein_chain_A", mol_atom_counts["Protein_chain_A"]))

if "CYQ" in mol_atom_counts:
    new_top.append(f"{'CYQ':<15} 1\n")
    added_mols.append(("CYQ", mol_atom_counts["CYQ"]))
elif "PRIMA1" in mol_atom_counts:
    new_top.append(f"{'PRIMA1':<15} 1\n")
    added_mols.append(("PRIMA1", mol_atom_counts["PRIMA1"]))
elif "UNL" in mol_atom_counts:
    new_top.append(f"{'UNL':<15} 1\n")
    added_mols.append(("UNL", mol_atom_counts["UNL"]))

if "Ion_chain_A2" in mol_atom_counts:
    new_top.append(f"{'Ion_chain_A2':<15} 1\n")
    added_mols.append(("Ion_chain_A2", mol_atom_counts["Ion_chain_A2"]))

new_top.append(f"{'SOL':<15} {sol_mols}\n")
added_mols.append(("SOL", sol_mols * 3))

if cl_mols > 0:
    new_top.append(f"{'CL':<15} {cl_mols}\n")
    added_mols.append(("CL", cl_mols))

with open("topol.top", "w") as f:
    f.writelines(new_top)

total_calculated = sum(count for _, count in added_mols)
print("\n=== ۳. نتیجه به‌روزرسانی topol.top ===")
print(f"تعداد اتم‌های فایل npt.gro: {total_gro_atoms}")
print(f"تعداد اتم‌های فایل topol.top: {total_calculated}")

