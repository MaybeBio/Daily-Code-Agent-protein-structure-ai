"""
Align کردن ساختار all-atom اصلی لیگاند (PRIMA1.pdb، از RDKit)
با موقعیت مکانی بهترین pose داکینگ (best_pose_model1.pdbqt)
با استفاده از الگوریتم Kabsch روی اتم‌های سنگین مشترک.

اجرا با (بعد از conda activate tp53_md):
python align_ligand_pose.py
"""

import numpy as np

def parse_pdb_heavy_atoms(filename, is_pdbqt=False):
    """خواندن مختصات اتم‌های سنگین (غیر H) از فایل PDB یا PDBQT"""
    coords = []
    names = []
    with open(filename, "r") as f:
        for line in f:
            if line.startswith("ATOM") or line.startswith("HETATM"):
                atom_name = line[12:16].strip()
                element = line[76:78].strip() if len(line) > 77 else atom_name[0]
                if element.upper() == "H" or atom_name.startswith("H"):
                    continue
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
                coords.append((x, y, z))
                names.append(atom_name)
    return np.array(coords), names

def kabsch_align(P, Q):
    """
    محاسبه‌ی چرخش و انتقال بهینه که P (متحرک) را به Q (مرجع) می‌چسباند.
    برمی‌گرداند: R (ماتریس چرخش 3x3)، t (بردار انتقال)
    """
    P_centroid = P.mean(axis=0)
    Q_centroid = Q.mean(axis=0)
    P_centered = P - P_centroid
    Q_centered = Q - Q_centroid

    H = P_centered.T @ Q_centered
    U, S, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    D = np.diag([1, 1, d])
    R = Vt.T @ D @ U.T

    t = Q_centroid - R @ P_centroid
    return R, t

# --- بارگذاری مختصات ---
mobile_coords, mobile_names = parse_pdb_heavy_atoms("PRIMA1.pdb")
target_coords, target_names = parse_pdb_heavy_atoms("best_pose_model1.pdbqt", is_pdbqt=True)

print(f"تعداد اتم سنگین در PRIMA1.pdb (all-atom اصلی): {len(mobile_coords)}")
print(f"تعداد اتم سنگین در best_pose_model1.pdbqt (داکینگ‌شده): {len(target_coords)}")

print(f"\nنام اتم‌ها در PRIMA1.pdb: {mobile_names}")
print(f"نام اتم‌ها در best_pose_model1.pdbqt: {target_names}")

if len(mobile_coords) != len(target_coords):
    raise ValueError(
        "تعداد اتم‌های سنگین مطابقت ندارد! باید ترتیب اتم‌ها را دستی بررسی کنید."
    )

# --- محاسبه‌ی چرخش/انتقال بهینه ---
R, t = kabsch_align(mobile_coords, target_coords)

rmsd_before = np.sqrt(np.mean(np.sum((mobile_coords - target_coords) ** 2, axis=1)))
aligned_mobile = (R @ mobile_coords.T).T + t
rmsd_after = np.sqrt(np.mean(np.sum((aligned_mobile - target_coords) ** 2, axis=1)))

print(f"\nRMSD قبل از align: {rmsd_before:.3f} Å")
print(f"RMSD بعد از align: {rmsd_after:.3f} Å")

# --- اعمال تبدیل به تمام اتم‌های PRIMA1.pdb (شامل هیدروژن‌ها) و نوشتن فایل جدید ---
with open("PRIMA1.pdb", "r") as f_in, open("PRIMA1_docked.pdb", "w") as f_out:
    for line in f_in:
        if line.startswith("ATOM") or line.startswith("HETATM"):
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
            new_xyz = R @ np.array([x, y, z]) + t
            new_line = (
                line[:30]
                + f"{new_xyz[0]:8.3f}{new_xyz[1]:8.3f}{new_xyz[2]:8.3f}"
                + line[54:]
            )
            f_out.write(new_line)
        else:
            f_out.write(line)

print("\nفایل PRIMA1_docked.pdb ذخیره شد (لیگاند all-atom در موقعیت داکینگ‌شده).")
