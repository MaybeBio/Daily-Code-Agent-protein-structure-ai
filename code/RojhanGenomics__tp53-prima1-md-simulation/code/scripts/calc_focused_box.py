"""
محاسبه‌ی مرکز و ابعاد جعبه‌ی جست‌وجوی متمرکز (focused docking)
حول دو سیستئین کلیدی Cys124 و Cys277 که طبق مطالعات تجربی
محل واقعی اتصال کووالانت PRIMA-1/APR-246 هستند.

اجرا با (بعد از conda activate tp53_md):
python calc_focused_box.py
"""

import numpy as np

PDB_FILE = "2OCJ_chainA_clean.pdb"
TARGET_RESIDUES = [124, 277]
PADDING = 8.0  # آنگستروم - حاشیه‌ی بزرگ‌تر چون دو residue از هم فاصله دارند

residue_coords = {resi: [] for resi in TARGET_RESIDUES}
all_target_coords = []

with open(PDB_FILE, "r") as f:
    for line in f:
        if line.startswith("ATOM"):
            resi = int(line[22:26])
            if resi in TARGET_RESIDUES:
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
                residue_coords[resi].append((x, y, z))
                all_target_coords.append((x, y, z))

# بررسی اینکه هر دو residue واقعاً پیدا شدند
for resi in TARGET_RESIDUES:
    count = len(residue_coords[resi])
    print(f"Residue {resi}: {count} atom پیدا شد")
    if count == 0:
        print(f"  هشدار: residue {resi} در فایل پیدا نشد! (شماره‌گذاری را بررسی کنید)")

if not all_target_coords:
    raise ValueError("هیچ‌کدام از residueهای هدف پیدا نشدند.")

all_target_coords = np.array(all_target_coords)

# فاصله‌ی بین دو سیستئین (برای اطمینان از این‌که جعبه واقعاً هر دو را پوشش می‌دهد)
if len(residue_coords[124]) > 0 and len(residue_coords[277]) > 0:
    ca_124 = np.mean(residue_coords[124], axis=0)
    ca_277 = np.mean(residue_coords[277], axis=0)
    dist = np.linalg.norm(ca_124 - ca_277)
    print(f"\nفاصله‌ی تقریبی بین Cys124 و Cys277: {dist:.2f} آنگستروم")

min_xyz = all_target_coords.min(axis=0)
max_xyz = all_target_coords.max(axis=0)

center = (min_xyz + max_xyz) / 2.0
size = (max_xyz - min_xyz) + 2 * PADDING

print("\n=== مرکز جعبه‌ی جست‌وجوی متمرکز (center) ===")
print(f"center_x = {center[0]:.3f}")
print(f"center_y = {center[1]:.3f}")
print(f"center_z = {center[2]:.3f}")

print("\n=== ابعاد جعبه‌ی جست‌وجو (size) ===")
print(f"size_x = {size[0]:.3f}")
print(f"size_y = {size[1]:.3f}")
print(f"size_z = {size[2]:.3f}")

with open("vina_config_focused.txt", "w") as f:
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
    f.write(f"out = docking_results_focused.pdbqt\n")

print("\nفایل کانفیگ Vina (focused) ذخیره شد: vina_config_focused.txt")
