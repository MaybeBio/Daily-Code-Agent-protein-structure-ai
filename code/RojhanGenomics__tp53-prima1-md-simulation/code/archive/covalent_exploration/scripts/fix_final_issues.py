import os

# ۱. رفع هشدارهای atomtypes تکراری در PRIMA1.itp
if os.path.exists("PRIMA1.itp"):
    with open("PRIMA1.itp", "r") as f:
        lines = f.readlines()
    
    new_itp = []
    in_atomtypes = False
    for line in lines:
        clean = line.strip()
        if clean.startswith("[") and "atomtypes" in clean:
            in_atomtypes = True
            new_itp.append("; " + line)
            continue
        elif clean.startswith("["):
            in_atomtypes = False
        
        if in_atomtypes and clean and not clean.startswith(";"):
            new_itp.append("; " + line)
        else:
            new_itp.append(line)
            
    with open("PRIMA1.itp", "w") as f:
        f.writelines(new_itp)
    print("بخش atomtypes تکراری از PRIMA1.itp غیرفعال شد.")

# ۲. اصلاح و استانداردسازی فرمت ستون‌های npt.gro
with open("npt.gro", "r") as f:
    gro_lines = f.readlines()

header = gro_lines[0]
count_line = gro_lines[1]
box_line = gro_lines[-1]
atom_lines = gro_lines[2:-1]

formatted_atoms = []
for idx, line in enumerate(atom_lines, start=1):
    if len(line) < 44:
        continue
    
    resnr_str = line[0:5].strip()
    resname = line[5:10].strip()
    atomname = line[10:15].strip()
    
    try:
        resnr = int(resnr_str)
    except ValueError:
        resnr = 1
        
    try:
        x = float(line[20:28])
        y = float(line[28:36])
        z = float(line[36:44])
    except ValueError:
        parts = line[20:].split()
        x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
        
    vel_str = ""
    if len(line) >= 68:
        try:
            vx = float(line[44:52])
            vy = float(line[52:60])
            vz = float(line[60:68])
            vel_str = f"{vx:8.4f}{vy:8.4f}{vz:8.4f}"
        except ValueError:
            pass

    # فرمت استاندارد گرومکس: %5d%-5s%5s%5d%8.3f%8.3f%8.3f
    new_line = f"{resnr % 100000:5d}{resname:<5s}{atomname:>5s}{idx % 100000:5d}{x:8.3f}{y:8.3f}{z:8.3f}{vel_str}\n"
    formatted_atoms.append(new_line)

with open("npt.gro", "w") as f:
    f.write(header)
    f.write(f"{len(formatted_atoms):>12}\n")
    f.writelines(formatted_atoms)
    f.write(box_line)

print("فرمت ستون‌های npt.gro با موفقیت استانداردسازی شد.")
