with open("protein.gro", "r") as f:
    prot_lines = f.readlines()

with open("cyq.gro", "r") as f:
    cyq_lines = f.readlines()

title = "p53 with CYQ covalent adduct\n"
prot_atoms = prot_lines[2:-1]
cyq_atoms = cyq_lines[2:-1]
box = prot_lines[-1]

total_atoms = len(prot_atoms) + len(cyq_atoms)

with open("complex.gro", "w") as f:
    f.write(title)
    f.write(f"{total_atoms:5d}\n")
    f.writelines(prot_atoms)
    f.writelines(cyq_atoms)
    f.write(box)

print(f"فایل complex.gro با مجموع {total_atoms} اتم ساخته شد.")
