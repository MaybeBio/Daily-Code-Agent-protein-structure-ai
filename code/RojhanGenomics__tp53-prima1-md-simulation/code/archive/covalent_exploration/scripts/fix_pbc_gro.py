with open("npt.gro", "r") as f:
    lines = f.readlines()

header = lines[:2]
atom_lines = lines[2:-1]
box_line = lines[-1]

box_parts = box_line.strip().split()
box_x, box_y, box_z = float(box_parts[0]), float(box_parts[1]), float(box_parts[2])

current_res_num = None
ref_x, ref_y, ref_z = 0.0, 0.0, 0.0
new_atom_lines = []

for line in atom_lines:
    res_num = line[:5].strip()
    x = float(line[20:28])
    y = float(line[28:36])
    z = float(line[36:44])

    if res_num != current_res_num:
        current_res_num = res_num
        ref_x, ref_y, ref_z = x, y, z

    dx, dy, dz = x - ref_x, y - ref_y, z - ref_z

    if dx > box_x / 2: x -= box_x
    elif dx < -box_x / 2: x += box_x

    if dy > box_y / 2: y -= box_y
    elif dy < -box_y / 2: y += box_y

    if dz > box_z / 2: z -= box_z
    elif dz < -box_z / 2: z += box_z

    v_part = line[44:].rstrip('\n') if len(line) > 44 else ""
    new_atom_lines.append(f"{line[:20]}{x:8.3f}{y:8.3f}{z:8.3f}{v_part}\n")

with open("npt_fixed.gro", "w") as f:
    f.writelines(header + new_atom_lines + [box_line])

print("فایل npt_fixed.gro با موفقیت اصلاح شد.")
