with open("em.gro", "r") as f:
    lines = f.readlines()[2:-1]

prot_cyq_atoms = []
water_ions_atoms = []

for i, line in enumerate(lines, 1):
    res_name = line[5:10].strip()
    if res_name in ["SOL", "NA", "CL"]:
        water_ions_atoms.append(i)
    else:
        prot_cyq_atoms.append(i)

def write_group(f, name, atoms):
    f.write(f"[ {name} ]\n")
    for idx, atom in enumerate(atoms, 1):
        f.write(f"{atom:6d}")
        if idx % 15 == 0:
            f.write("\n")
    f.write("\n\n")

with open("index.ndx", "w") as f:
    write_group(f, "Protein_CYQ", prot_cyq_atoms)
    write_group(f, "Water_and_ions", water_ions_atoms)

print("فایل index.ndx با موفقیت ساخته شد.")
