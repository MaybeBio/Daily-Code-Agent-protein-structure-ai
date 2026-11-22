"""
# DEPRECATED in v2.0.1: distances were computed without the minimum-image convention  (see legacy/README.md)
شناسایی residueهای پروتئین که در تماس نزدیک با لیگاند هستند،
هم در ابتدای شبیه‌سازی (فریم 0) و هم در انتهای آن (آخرین فریم)

این به ما می‌گوید آیا لیگاند در همان pocket اولیه مانده یا به موقعیت
دیگری روی سطح پروتئین جابه‌جا شده است.

اجرا با (بعد از conda activate tp53_md):
python analyze_ligand_location.py
"""

import MDAnalysis as mda
import pandas as pd

runs = {
    "Run 1": {"traj": "run1_20ns/md_fixed.xtc", "tpr": "run1_20ns/md.tpr"},
    "Run 2": {"traj": "run2_20ns/md_run2_fixed.xtc", "tpr": "run2_20ns/md_run2.tpr"},
    "Run 3": {"traj": "run3_20ns/md_run3_fixed.xtc", "tpr": "run3_20ns/md_run3.tpr"},
}

CONTACT_CUTOFF = 4.5  # آنگستروم

for run_name, paths in runs.items():
    print(f"\n{'='*60}")
    print(f"=== {run_name} ===")
    print(f"{'='*60}")

    u = mda.Universe(paths["tpr"], paths["traj"])
    ligand = u.select_atoms("resname UNL")

    # فریم اول
    u.trajectory[0]
    contacts_start = u.select_atoms(
        f"protein and around {CONTACT_CUTOFF} group ligand", ligand=ligand
    )
    residues_start = sorted(set(contacts_start.resids))
    print(f"Residueهای تماس در ابتدا (t=0 ns): {residues_start}")

    # آخرین فریم
    u.trajectory[-1]
    last_time = u.trajectory.time / 1000.0
    contacts_end = u.select_atoms(
        f"protein and around {CONTACT_CUTOFF} group ligand", ligand=ligand
    )
    residues_end = sorted(set(contacts_end.resids))
    print(f"Residueهای تماس در انتها (t={last_time:.1f} ns): {residues_end}")

    # مقایسه
    common = set(residues_start) & set(residues_end)
    print(f"Residueهای مشترک بین ابتدا و انتها: {sorted(common)}")
    if len(common) == 0:
        print(">>> لیگاند کاملاً به یک موقعیت جدید جابه‌جا شده (هیچ همپوشانی با pocket اولیه)")
    elif len(common) < min(len(residues_start), len(residues_end)) / 2:
        print(">>> لیگاند تا حد زیادی جابه‌جا شده (همپوشانی جزئی با pocket اولیه)")
    else:
        print(">>> لیگاند عمدتاً در همان ناحیه‌ی اولیه باقی مانده")
