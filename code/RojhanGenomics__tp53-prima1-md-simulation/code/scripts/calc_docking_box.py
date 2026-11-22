"""
محاسبه‌ی مرکز و ابعاد جعبه‌ی جست‌وجو (search box) برای blind docking
بر اساس بازه‌ی مختصات کل اتم‌های پروتئین، به‌همراه یک حاشیه‌ی اطمینان (padding)

اجرا با (بعد از conda activate tp53_md):
python calc_docking_box.py
"""

import numpy as np

PDB_FILE = "2OCJ_chainA_clean.pdb"
PADDING = 5.0  # آنگستروم - حاشیه‌ی اطمینان اطراف پروتئین

coords = []
with open(PDB_FILE, "r") as f:
    for line in f:
        if line.startswith("ATOM") or line.startswith("HETATM"):
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
            coords.append((x, y, z))

coords = np.array(coords)

min_xyz = coords.min(axis=0)
max_xyz = coords.max(axis=0)

center = (min_xyz + max_xyz) / 2.0
size = (max_xyz - min_xyz) + 2 * PADDING

print("=== مرکز جعبه‌ی جست‌وجو (center) ===")
print(f"center_x = {center[0]:.3f}")
print(f"center_y = {center[1]:.3f}")
print(f"center_z = {center[2]:.3f}")

print("\n=== ابعاد جعبه‌ی جست‌وجو (size) ===")
print(f"size_x = {size[0]:.3f}")
print(f"size_y = {size[1]:.3f}")
print(f"size_z = {size[2]:.3f}")

# نوشتن فایل کانفیگ آماده برای Vina
with open("vina_config.txt", "w") as f:
    f.write(f"receptor = receptor.pdbqt\n")
    f.write(f"ligand = PRIMA1.pdbqt\n\n")
    f.write(f"center_x = {center[0]:.3f}\n")
    f.write(f"center_y = {center[1]:.3f}\n")
    f.write(f"center_z = {center[2]:.3f}\n\n")
    f.write(f"size_x = {size[0]:.3f}\n")
    f.write(f"size_y = {size[1]:.3f}\n")
    f.write(f"size_z = {size[2]:.3f}\n\n")
    f.write(f"exhaustiveness = 32\n")
    f.write(f"num_modes = 20\n")
    f.write(f"out = docking_results.pdbqt\n")

print("\nفایل کانفیگ Vina ذخیره شد: vina_config.txt")
