"""
# DEPRECATED in v2.0.1: not the source of the reported cluster numbers (gmx cluster, all heavy atoms); superseded by analysis_v2/audit_cluster_hbond.py  (see legacy/README.md)
Clustering ساختاری (بر پایه‌ی RMSD) برای پیدا کردن conformationهای غالب
پروتئین در هر تکرار، و استخراج representative structure هر خوشه

اجرا با (بعد از conda activate tp53_md):
python analyze_clustering.py
"""

import MDAnalysis as mda
from MDAnalysis.analysis import align, encore
import numpy as np
import warnings
warnings.filterwarnings("ignore")

runs = {
    "Run 1": {"traj": "run1_20ns/md_fixed.xtc", "tpr": "run1_20ns/md.tpr"},
    "Run 2": {"traj": "run2_20ns/md_run2_fixed.xtc", "tpr": "run2_20ns/md_run2.tpr"},
    "Run 3": {"traj": "run3_20ns/md_run3_fixed.xtc", "tpr": "run3_20ns/md_run3.tpr"},
}

for run_name, paths in runs.items():
    print(f"\n=== در حال پردازش {run_name} ===")
    u = mda.Universe(paths["tpr"], paths["traj"])

    # align کردن تراژکتوری قبل از clustering (ضروری برای RMSD-based clustering)
    protein_ca = u.select_atoms("protein and name CA")
    ref = u.copy()

    aligner = align.AlignTraj(
        u, u, select="protein and name CA", in_memory=True, ref_frame=0
    ).run()

    # استفاده از الگوریتم clustering ساده (k-means روی فضای RMSD) از ماژول encore
    clusters = encore.cluster(
        u,
        select="protein and name CA",
    )

    print(f"تعداد خوشه‌های پیدا‌شده: {len(clusters)}")

    cluster_sizes = [(c.id, c.size) for c in clusters]
    cluster_sizes.sort(key=lambda x: -x[1])

    for cid, size in cluster_sizes[:5]:
        percentage = size / len(u.trajectory) * 100
        print(f"  خوشه {cid}: {size} فریم ({percentage:.1f}%)")

    # استخراج representative frame از بزرگ‌ترین خوشه
    largest_cluster = max(clusters, key=lambda c: c.size)
    rep_frame_idx = largest_cluster.centroid
    print(f"Representative frame بزرگ‌ترین خوشه: فریم شماره {rep_frame_idx}")

    u.trajectory[rep_frame_idx]
    output_name = f"representative_{run_name.replace(' ', '_').lower()}.pdb"
    u.atoms.write(output_name)
    print(f"ساختار representative ذخیره شد: {output_name}")
