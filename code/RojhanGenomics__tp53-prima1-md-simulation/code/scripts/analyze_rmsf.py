"""
محاسبه‌ی RMSF (Root Mean Square Fluctuation) به ازای هر residue پروتئین
برای هر سه تکرار مستقل MD

RMSF نشان می‌دهد کدام نواحی پروتئین در طول شبیه‌سازی منعطف‌تر (نوسان بیشتر)
و کدام نواحی سفت‌تر (نوسان کمتر) بوده‌اند.

اجرا با (بعد از conda activate tp53_md):
python analyze_rmsf.py
"""

import MDAnalysis as mda
from MDAnalysis.analysis import align, rms
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

    protein_ca = u.select_atoms("protein and name CA")
    print(f"تعداد اتم‌های CA: {len(protein_ca)}")

    # مهم: قبل از محاسبه‌ی RMSF، باید تراژکتوری را نسبت به یک ساختار مرجع
    # (معمولاً فریم میانگین یا فریم اول) align کنیم، وگرنه حرکت کلی
    # (translation/rotation) کل مولکول باعث RMSF کاذب بزرگ می‌شود
    average = align.AverageStructure(
        u, u, select="protein and name CA", ref_frame=0
    ).run()
    ref = average.results.universe

    aligner = align.AlignTraj(
        u, ref, select="protein and name CA", in_memory=True
    ).run()

    R = rms.RMSF(protein_ca).run()

    resids = protein_ca.resids
    rmsf_values = R.results.rmsf

    df = pd.DataFrame({
        "resid": resids,
        "rmsf_nm": rmsf_values / 10.0,  # Å به nm
    })
    csv_name = f"rmsf_{run_name.replace(' ', '_').lower()}.csv"
    df.to_csv(csv_name, index=False)
    print(f"فایل ذخیره شد: {csv_name}")

    results[run_name] = df

# --- رسم نمودار ترکیبی ---
fig, ax = plt.subplots(figsize=(12, 5))
colors = {"Run 1": "#1f77b4", "Run 2": "#ff7f0e", "Run 3": "#2ca02c"}

for run_name, df in results.items():
    ax.plot(df["resid"], df["rmsf_nm"], label=run_name, color=colors[run_name], linewidth=1.0, alpha=0.8)

# هایلایت residueهای pocket که در داکینگ blind شناسایی شده بودند
pocket_residues = [7, 9, 15, 16, 31, 36, 173, 174, 175]
for resi in pocket_residues:
    ax.axvline(x=resi, color="gray", linestyle="--", alpha=0.3, linewidth=0.7)

ax.set_xlabel("Residue number")
ax.set_ylabel("RMSF (nm)")
ax.set_title("RMSF هر residue در سه تکرار مستقل\n(خطوط نقطه‌چین: residueهای binding pocket شناسایی‌شده در داکینگ)")
ax.legend()
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig("rmsf_combined_plot.png", dpi=300)
print("\nنمودار ترکیبی ذخیره شد: rmsf_combined_plot.png")

# --- آمار خلاصه برای residueهای pocket به‌طور خاص ---
print("\n=== RMSF residueهای binding pocket (شناسایی‌شده در داکینگ blind) ===")
summary_rows = []
for run_name, df in results.items():
    for resi in pocket_residues:
        match = df[df["resid"] == resi]
        if not match.empty:
            rmsf_val = match["rmsf_nm"].values[0]
            summary_rows.append({"Run": run_name, "Residue": resi, "RMSF (nm)": round(rmsf_val, 3)})

pocket_df = pd.DataFrame(summary_rows)
pocket_pivot = pocket_df.pivot(index="Residue", columns="Run", values="RMSF (nm)")
print(pocket_pivot)
pocket_pivot.to_csv("rmsf_pocket_residues_table.csv")
print("\nجدول ذخیره شد: rmsf_pocket_residues_table.csv")
