"""
محاسبه‌ی Radius of Gyration (Rg) برای پروتئین در هر سه تکرار مستقل MD
Rg نشان‌دهنده‌ی میزان فشردگی (compactness) کلی پروتئین است.
افزایش ناگهانی یا پیوسته‌ی Rg می‌تواند نشانه‌ی باز شدن جزئی یا کامل fold باشد.

اجرا با (بعد از conda activate tp53_md):
python analyze_rg.py
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

results = {}

for run_name, paths in runs.items():
    print(f"\n=== در حال پردازش {run_name} ===")
    u = mda.Universe(paths["tpr"], paths["traj"])
    protein = u.select_atoms("protein")

    time_list = []
    rg_list = []

    for ts in u.trajectory:
        time_list.append(ts.time / 1000.0)  # ps به ns
        rg_list.append(protein.radius_of_gyration() / 10.0)  # Å به nm

    df = pd.DataFrame({"time_ns": time_list, "rg_nm": rg_list})
    csv_name = f"rg_{run_name.replace(' ', '_').lower()}.csv"
    df.to_csv(csv_name, index=False)
    print(f"فایل ذخیره شد: {csv_name}")
    print(f"Rg میانگین (کل تراژکتوری): {df['rg_nm'].mean():.3f} ± {df['rg_nm'].std():.3f} nm")

    results[run_name] = df

# --- رسم نمودار ترکیبی ---
fig, ax = plt.subplots(figsize=(10, 5))
colors = {"Run 1": "#1f77b4", "Run 2": "#ff7f0e", "Run 3": "#2ca02c"}

for run_name, df in results.items():
    ax.plot(df["time_ns"], df["rg_nm"], label=run_name, color=colors[run_name], linewidth=1.0, alpha=0.8)

ax.set_xlabel("Time (ns)")
ax.set_ylabel("Radius of Gyration (nm)")
ax.set_title("شعاع ژیراسیون پروتئین در سه تکرار مستقل")
ax.legend()
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig("rg_combined_plot.png", dpi=300)
print("\nنمودار ترکیبی ذخیره شد: rg_combined_plot.png")

# --- آمار خلاصه (نیمه‌ی دوم هر تراژکتوری) ---
print("\n=== آمار خلاصه (نیمه‌ی دوم هر تراژکتوری) ===")
summary_rows = []
for run_name, df in results.items():
    half = df[df["time_ns"] >= df["time_ns"].max() / 2]
    mean_rg = half["rg_nm"].mean()
    std_rg = half["rg_nm"].std()
    summary_rows.append({"Run": run_name, "Rg mean (nm)": round(mean_rg, 3), "Rg std (nm)": round(std_rg, 3)})
    print(f"{run_name}: Rg = {mean_rg:.3f} ± {std_rg:.3f} nm")

summary_df = pd.DataFrame(summary_rows)
summary_df.to_csv("rg_summary_table.csv", index=False)
print("\nجدول خلاصه ذخیره شد: rg_summary_table.csv")
