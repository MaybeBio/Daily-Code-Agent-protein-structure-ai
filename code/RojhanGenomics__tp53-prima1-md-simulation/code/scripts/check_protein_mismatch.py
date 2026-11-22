import os

print("=== ۱. بررسی فایل‌های itp و top پروتئین ===")
top_file = "topol.top"
protein_itp = None

if os.path.exists("topol_Protein_chain_A.itp"):
    protein_itp = "topol_Protein_chain_A.itp"
else:
    for f in os.listdir("."):
        if f.startswith("topol_Protein") and f.endswith(".itp"):
            protein_itp = f
            break

target_file = protein_itp if protein_itp else top_file
print(f"فایل توپولوژی پروتئین مورد بررسی: {target_file}")

top_atoms = []
in_protein = False
in_atoms = False

with open(target_file, "r") as f:
    for line in f:
        l = line.split(";")[0].strip()
        if not l:
            continue
        if l.startswith("["):
            h = l.replace("[","").replace("]","").strip()
            if h == "moleculetype":
                in_protein = False
            elif h == "atoms":
                if in_protein or protein_itp:
                    in_atoms = True
            else:
                in_atoms = False
            continue
        
        parts = l.split()
        if not in_protein and not in_atoms and len(parts) >= 1:
            if parts[0] == "Protein_chain_A":
                in_protein = True
        elif in_atoms and len(parts) >= 5:
            res_nr = parts[2]
            res_name = parts[3]
            atom_name = parts[4]
            top_atoms.append((res_nr, res_name, atom_name))

print(f"تعداد اتم‌های Protein_chain_A در توپولوژی: {len(top_atoms)}")
if top_atoms:
    print(f"  اولین اتم توپولوژی: Residue {top_atoms[0][0]} {top_atoms[0][1]}, Atom {top_atoms[0][2]}")
    print(f"  آخرین اتم توپولوژی: Residue {top_atoms[-1][0]} {top_atoms[-1][1]}, Atom {top_atoms[-1][2]}")

gro_protein_atoms = []
with open("npt.gro", "r") as f:
    lines = f.readlines()

total_gro = int(lines[1].strip())
for line in lines[2:total_gro+2]:
    res_id = line[0:5].strip()
    res_name = line[5:10].strip()
    atom_name = line[10:15].strip()
    if res_name not in ["SOL", "TIP3", "WAT", "HOH", "CL", "CLA", "CL-", "NA", "SOD", "NA+", "ZN", "UNL", "CYQ", "PRIMA1"]:
        gro_protein_atoms.append((res_id, res_name, atom_name))

print(f"\nتعداد اتم‌های پروتئین در npt.gro: {len(gro_protein_atoms)}")
if gro_protein_atoms:
    print(f"  اولین اتم npt.gro: Residue {gro_protein_atoms[0][0]} {gro_protein_atoms[0][1]}, Atom {gro_protein_atoms[0][2]}")
    print(f"  آخرین اتم npt.gro: Residue {gro_protein_atoms[-1][0]} {gro_protein_atoms[-1][1]}, Atom {gro_protein_atoms[-1][2]}")

top_res_set = set((r[0], r[1]) for r in top_atoms)
gro_res_set = set((r[0], r[1]) for r in gro_protein_atoms)

diff_in_gro = gro_res_set - top_res_set
diff_in_top = top_res_set - gro_res_set

if diff_in_gro:
    print(f"\nباقی‌مانده‌هایی که در npt.gro هست اما در توپولوژی نیست: {sorted(list(diff_in_gro), key=lambda x: int(x[0]))}")
if diff_in_top:
    print(f"\nباقی‌مانده‌هایی که در توپولوژی هست اما در npt.gro نیست: {sorted(list(diff_in_top), key=lambda x: int(x[0]))}")

