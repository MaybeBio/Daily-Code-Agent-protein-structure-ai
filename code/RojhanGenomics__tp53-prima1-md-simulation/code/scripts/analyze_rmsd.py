"""
محاسبه‌ی RMSD (Root Mean Square Deviation) برای backbone پروتئین و لیگاند
در هر سه تکرار مستقل MD، نسبت به ساختار equilibrated اولیه (npt.gro)

خروجی: یک فایل CSV با ستون‌های زمان و RMSD برای هر تکرار
        + یک نمودار ترکیبی (هر سه تکرار روی هم)

اجرا با (بعد از conda activate tp53_md):
python analyze_rmsd.py
"""

import MDAnalysis as mda
from MDAnalysis.analysis import rms
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

# تعریف مسیر فایل‌ها برای هر سه تکرار
runs = {
    "Run 1": {"traj": "run1_20ns/md_fixed.xtc", "tpr": "run1_20ns/md.tpr"},
    "Run 2": {"traj": "run2_20ns/md_run2_fixed.xtc", "tpr": "run2_20ns/md_run2.tpr"},
    "Run 3": {"traj": "run3_20ns/md_run3_fixed.xtc", "tpr": "run3_20ns/md_run3.tpr"},
}

results = {}

for run_name, paths in runs.items():
    print(f"\n=== در حال پردازش {run_name} ===")

    u = mda.Universe(paths["tpr"], paths["traj"])

    # انتخاب اتم‌های backbone پروتئین (N, CA, C) برای RMSD ساختاری استاندارد
    protein_backbone = "protein and backbone"
    # انتخاب اتم‌های لیگاند (residue name UNL که acpype برایش تعیین کرد)
    ligand_heavy = "resname UNL and not name H*"

    # بررسی این‌که هر دو گروه اتم واقعاً در سیستم پیدا می‌شوند
    n_backbone = len(u.select_atoms(protein_backbone))
    n_ligand = len(u.select_atoms(ligand_heavy))
    print(f"تعداد اتم‌های backbone پروتئین: {n_backbone}")
    print(f"تعداد اتم‌های سنگین لیگاند: {n_ligand}")

    if n_backbone == 0 or n_ligand == 0:
        print(f"هشدار: یکی از گروه‌های اتمی خالی است! این تکرار را بررسی کنید.")
        continue

    # محاسبه‌ی RMSD با کلاس RMSD از MDAnalysis
    # select برای alignment (معمولاً بر پایه‌ی backbone پروتئین)
    # groupselections برای محاسبه‌ی RMSD گروه‌های اضافی (اینجا لیگاند) پس از همان alignment
    R = rms.RMSD(
        u,
        u,
        select=protein_backbone,
        groupselections=[ligand_heavy],
        ref_frame=0,
    )
    R.run()

    # ستون‌های خروجی: [frame, time, rmsd_backbone(fit-group), rmsd_ligand]
    time_ps = R.results.rmsd[:, 1]
    rmsd_protein = R.results.rmsd[:, 2]
    rmsd_ligand = R.results.rmsd[:, 3]

    df = pd.DataFrame({
        "time_ns": time_ps / 1000.0,
        "rmsd_protein_nm": rmsd_protein / 10.0,   # Å به nm
        "rmsd_ligand_nm": rmsd_ligand / 10.0,
    })
    csv_name = f"rmsd_{run_name.replace(' ', '_').lower()}.csv"
    df.to_csv(csv_name, index=False)
    print(f"فایل ذخیره شد: {csv_name}")

    results[run_name] = df

# --- رسم نمودار ترکیبی ---
fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

colors = {"Run 1": "#1f77b4", "Run 2": "#ff7f0e", "Run 3": "#2ca02c"}

for run_name, df in results.items():
    axes[0].plot(df["time_ns"], df["rmsd_protein_nm"], label=run_name, color=colors[run_name], linewidth=1.2)
    axes[1].plot(df["time_ns"], df["rmsd_ligand_nm"], label=run_name, color=colors[run_name], linewidth=1.2)

axes[0].set_ylabel("Protein backbone RMSD (nm)")
axes[0].set_title("RMSD پروتئین (backbone) در سه تکرار مستقل")
axes[0].legend()
axes[0].grid(alpha=0.3)

axes[1].set_ylabel("Ligand RMSD (nm)")
axes[1].set_xlabel("Time (ns)")
axes[1].set_title("RMSD لیگاند (PRIMA1) در سه تکرار مستقل")
axes[1].legend()
axes[1].grid(alpha=0.3)

plt.tight_layout()
plt.savefig("rmsd_combined_plot.png", dpi=300)
print("\nنمودار ترکیبی ذخیره شد: rmsd_combined_plot.png")

# --- آمار خلاصه (میانگین و انحراف معیار روی نیمه‌ی دوم تراژکتوری، یعنی بخش تعادل‌یافته) ---
print("\n=== آمار خلاصه (روی نیمه‌ی دوم هر تراژکتوری، یعنی بعد از ~10ns) ===")
summary_rows = []
for run_name, df in results.items():
    half = df[df["time_ns"] >= df["time_ns"].max() / 2]
    mean_prot = half["rmsd_protein_nm"].mean()
    std_prot = half["rmsd_protein_nm"].std()
    mean_lig = half["rmsd_ligand_nm"].mean()
    std_lig = half["rmsd_ligand_nm"].std()
    summary_rows.append({
        "Run": run_name,
        "Protein RMSD mean (nm)": round(mean_prot, 3),
        "Protein RMSD std (nm)": round(std_prot, 3),
        "Ligand RMSD mean (nm)": round(mean_lig, 3),
        "Ligand RMSD std (nm)": round(std_lig, 3),
    })
    print(f"{run_name}: Protein = {mean_prot:.3f} ± {std_prot:.3f} nm | Ligand = {mean_lig:.3f} ± {std_lig:.3f} nm")

summary_df = pd.DataFrame(summary_rows)
summary_df.to_csv("rmsd_summary_table.csv", index=False)
print("\nجدول خلاصه ذخیره شد: rmsd_summary_table.csv")

