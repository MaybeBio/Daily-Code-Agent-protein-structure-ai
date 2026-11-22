"""
# DEPRECATED in v2.0.1: distances were computed without the minimum-image convention  (see legacy/README.md)
محاسبه‌ی فاصله‌ی مرکز جرم (Center of Mass) لیگاند تا مرکز جرم residueهای
binding pocket، در طول زمان، برای هر سه تکرار.

این نمودار لحظه‌ی دقیق جدایی (unbinding) لیگاند از pocket را به‌صورت
بصری نشان می‌دهد.

اجرا با (بعد از conda activate tp53_md):
python analyze_ligand_distance.py
"""

import MDAnalysis as mda
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

runs = {
    "Run 1": {"traj": "run1_20ns/md_fixed.xtc", "tpr": "run1_20ns/md.tpr"},
    "Run 2": {"traj": "run2_20ns/md_run2_fixed.xtc", "tpr": "run2_20ns/md_run2.tpr"},
    "Run 3": {"traj": "run3_20ns/md_run3_fixed.xtc", "tpr": "run3_20ns/md_run3.tpr"},
}

# residueهای pocket با شماره‌گذاری اصلاح‌شده‌ی GROMACS
POCKET_RESIDUES = [7, 9, 15, 16, 31, 36, 173, 174, 175]
pocket_sel = "protein and resid " + " ".join(str(r) for r in POCKET_RESIDUES) + " and name CA"

results = {}

for run_name, paths in runs.items():
    print(f"\n=== در حال پردازش {run_name} ===")
    u = mda.Universe(paths["tpr"], paths["traj"])

    ligand = u.select_atoms("resname UNL")
    pocket = u.select_atoms(pocket_sel)
    print(f"تعداد اتم‌های pocket برای محاسبه‌ی مرکز جرم: {len(pocket)}")

    time_list = []
    distance_list = []

    for ts in u.trajectory:
        lig_com = ligand.center_of_mass()
        pocket_com = pocket.center_of_mass()
        dist = np.linalg.norm(lig_com - pocket_com) / 10.0  # Å به nm
        time_list.append(ts.time / 1000.0)
        distance_list.append(dist)

    df = pd.DataFrame({"time_ns": time_list, "distance_nm": distance_list})
    csv_name = f"ligand_distance_{run_name.replace(' ', '_').lower()}.csv"
    df.to_csv(csv_name, index=False)
    print(f"فایل ذخیره شد: {csv_name}")
    print(f"فاصله در t=0: {df['distance_nm'].iloc[0]:.2f} nm | فاصله در انتها: {df['distance_nm'].iloc[-1]:.2f} nm")

    results[run_name] = df

# --- رسم نمودار ترکیبی ---
fig, ax = plt.subplots(figsize=(10, 5))
colors = {"Run 1": "#1f77b4", "Run 2": "#ff7f0e", "Run 3": "#2ca02c"}

for run_name, df in results.items():
    ax.plot(df["time_ns"], df["distance_nm"], label=run_name, color=colors[run_name], linewidth=1.2)

ax.axhline(y=1.0, color="red", linestyle="--", alpha=0.5, linewidth=1, label="آستانه‌ی تقریبی جدایی (~1 nm)")
ax.set_xlabel("Time (ns)")
ax.set_ylabel("Ligand COM - Pocket COM distance (nm)")
ax.set_title("فاصله‌ی مرکز جرم لیگاند تا مرکز pocket در طول زمان\n(افزایش ناگهانی = لحظه‌ی جدایی لیگاند)")
ax.legend()
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig("ligand_distance_combined_plot.png", dpi=300)
print("\nنمودار ترکیبی ذخیره شد: ligand_distance_combined_plot.png")
