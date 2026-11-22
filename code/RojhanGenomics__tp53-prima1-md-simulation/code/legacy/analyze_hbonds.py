"""
# DEPRECATED in v2.0.1: counted any bond with the ligand as donor or acceptor, including ligand-water and intramolecular bonds  (see legacy/README.md)
تحلیل پیوندهای هیدروژنی (Hydrogen Bonds) بین لیگاند (PRIMA1) و پروتئین
در هر سه تکرار مستقل MD

هدف: بررسی این‌که آیا لیگاند در طول شبیه‌سازی پیوند هیدروژنی پایدار با
residueهای pocket حفظ کرده، یا این پیوندها در یک لحظه‌ی خاص قطع شده‌اند
(که باید با جهش بزرگ در RMSD لیگاند هم‌زمان باشد)

اجرا با (بعد از conda activate tp53_md):
python analyze_hbonds.py
"""

import MDAnalysis as mda
from MDAnalysis.analysis.hydrogenbonds import HydrogenBondAnalysis
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

    # تعریف تحلیل پیوند هیدروژنی بین لیگاند (donor/acceptor) و پروتئین (donor/acceptor)
    hbonds = HydrogenBondAnalysis(
        universe=u,
        donors_sel=None,
        hydrogens_sel=None,
        acceptors_sel=None,
        d_a_cutoff=3.5,       # فاصله‌ی استاندارد donor-acceptor (آنگستروم)
        d_h_a_angle_cutoff=150,  # زاویه‌ی استاندارد (درجه)
    )

    # محدود کردن به پیوندهایی که حداقل یک طرفشان لیگاند (resname UNL) باشد
    hbonds.hydrogens_sel = hbonds.guess_hydrogens("protein or resname UNL")
    hbonds.acceptors_sel = hbonds.guess_acceptors("protein or resname UNL")

    hbonds.run()

    # فیلتر کردن فقط پیوندهایی که یک طرفشان لیگاند است
    # ستون‌های hbonds.results.hbonds: [frame, donor_ix, hydrogen_ix, acceptor_ix, distance, angle]
    u_check = mda.Universe(paths["tpr"], paths["traj"])
    ligand_atom_indices = set(u_check.select_atoms("resname UNL").indices)

    frames = hbonds.results.hbonds[:, 0]
    donor_ix = hbonds.results.hbonds[:, 1].astype(int)
    acceptor_ix = hbonds.results.hbonds[:, 3].astype(int)

    is_ligand_hbond = np.array([
        (d in ligand_atom_indices) or (a in ligand_atom_indices)
        for d, a in zip(donor_ix, acceptor_ix)
    ])

    ligand_hbond_frames = frames[is_ligand_hbond]

    # شمارش تعداد پیوند هیدروژنی لیگاند-پروتئین در هر فریم
    n_frames_total = len(u.trajectory)
    counts_per_frame = np.zeros(n_frames_total)
    unique_frames, counts = np.unique(ligand_hbond_frames.astype(int), return_counts=True)
    for f, c in zip(unique_frames, counts):
        if f < n_frames_total:
            counts_per_frame[f] = c

    time_ns = np.array([u.trajectory[i].time / 1000.0 for i in range(n_frames_total)])

    df = pd.DataFrame({"time_ns": time_ns, "n_hbonds_ligand": counts_per_frame})
    csv_name = f"hbonds_{run_name.replace(' ', '_').lower()}.csv"
    df.to_csv(csv_name, index=False)
    print(f"فایل ذخیره شد: {csv_name}")
    print(f"میانگین تعداد پیوند هیدروژنی لیگاند-پروتئین: {df['n_hbonds_ligand'].mean():.2f}")
    print(f"درصد فریم‌هایی با حداقل ۱ پیوند هیدروژنی: {(df['n_hbonds_ligand'] > 0).mean() * 100:.1f}%")

    results[run_name] = df

# --- رسم نمودار ترکیبی ---
fig, ax = plt.subplots(figsize=(10, 5))
colors = {"Run 1": "#1f77b4", "Run 2": "#ff7f0e", "Run 3": "#2ca02c"}

for run_name, df in results.items():
    ax.plot(df["time_ns"], df["n_hbonds_ligand"], label=run_name, color=colors[run_name], linewidth=1.0, alpha=0.7)

ax.set_xlabel("Time (ns)")
ax.set_ylabel("Number of ligand-protein H-bonds")
ax.set_title("تعداد پیوندهای هیدروژنی لیگاند-پروتئین در طول زمان")
ax.legend()
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig("hbonds_combined_plot.png", dpi=300)
print("\nنمودار ترکیبی ذخیره شد: hbonds_combined_plot.png")
