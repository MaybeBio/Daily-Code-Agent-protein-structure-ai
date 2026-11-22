with open("cyq_gmx.top", "r") as f:
    lines = f.readlines()

atomtypes = []
itp_content = []
in_atomtypes = False

for line in lines:
    if line.strip().startswith("[ atomtypes ]"):
        in_atomtypes = True
        atomtypes.append(line)
        continue
    elif line.strip().startswith("[") and in_atomtypes:
        in_atomtypes = False

    if in_atomtypes:
        atomtypes.append(line)
    else:
        if not line.startswith("#include") and not "system" in line.lower():
            itp_content.append(line)

with open("cyq_atomtypes.itp", "w") as f:
    f.writelines(atomtypes)

with open("cyq.itp", "w") as f:
    f.writelines(itp_content)

print("فایل‌های cyq_atomtypes.itp و cyq.itp با موفقیت ساخته شدند.")
