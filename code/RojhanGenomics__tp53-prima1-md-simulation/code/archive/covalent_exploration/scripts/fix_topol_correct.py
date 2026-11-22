import os

print("=== ۱. شناسایی moleculetype ها و تعداد اتم‌های آن‌ها ===")
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

print("تعداد اتم هر moleculetype شناسایی‌شده:")
for k, v in mol_atom_counts.items():
    print(f"  {k}: {v} اتم")

print("\n=== ۲. خواندن فایل npt.gro ===")
with open("npt.gro", "r") as f:
    lines = [l for l in f.readlines() if l.strip()]

total_gro_atoms = int(lines[1].strip())
print(f"کل اتم‌های npt.gro: {total_gro_atoms}")

print("\n=== ۳. بازنویسی صحیح بخش [ molecules ] در topol.top ===")
protein_atoms = mol_atom_counts.get("Protein_chain_A", 2999)
ion_atoms = mol_atom_counts.get("Ion_chain_A2", 1)
unl_atoms = mol_atom_counts.get("CYQ", mol_atom_counts.get("UNL", 36))

remaining_atoms = total_gro_atoms - (protein_atoms + ion_atoms + unl_atoms)

cl_count = 0
for l in reversed(lines[2:-1]):
    if len(l) >= 10 and l[5:10].strip() in ["CL", "CLA", "CL-"]:
        cl_count += 1
    else:
        break

sol_atoms = remaining_atoms - cl_count
sol_count = sol_atoms // 3

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
if "CYQ" in mol_atom_counts:
    new_top.append(f"{'CYQ':<15} 1\n")
elif "UNL" in mol_atom_counts:
    new_top.append(f"{'UNL':<15} 1\n")
new_top.append(f"{'SOL':<15} {sol_count}\n")
if cl_count > 0:
    new_top.append(f"{'CL':<15} {cl_count}\n")

with open("topol.top", "w") as f:
    f.writelines(new_top)

print("فایل topol.top اصلاح شد.")
