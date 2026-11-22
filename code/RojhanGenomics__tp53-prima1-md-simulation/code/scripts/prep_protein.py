with open("2OCJ_chainA_clean.pdb", "r") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.startswith(("ATOM", "HETATM")):
        res_num = line[22:26].strip()
        if res_num == "124":
            continue
    new_lines.append(line)

with open("protein_no_cys124.pdb", "w") as f:
    f.writelines(new_lines)

print("فایل protein_no_cys124.pdb (بدون CYS124) با موفقیت ساخته شد.")
