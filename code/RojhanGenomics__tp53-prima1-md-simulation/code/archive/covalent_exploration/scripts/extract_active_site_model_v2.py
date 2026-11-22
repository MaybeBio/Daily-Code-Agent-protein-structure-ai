from pymol import cmd

CYS_RESI = 124
RANGE_START = 115
RANGE_END = 135

AA_LIST = "ALA+ARG+ASN+ASP+CYS+GLU+GLN+GLY+HIS+HSE+HSD+HSP+HIE+HID+HIP+ILE+LEU+LYS+MET+PHE+PRO+SER+THR+TRP+TYR+VAL"

cmd.load("npt_protein.pdb", "protein")
cmd.load("CYQ_residue_v2.pdb", "cyq")

cmd.select("real_protein", f"resn {AA_LIST}")
cmd.select("seg1", f"real_protein and resi {RANGE_START}-{RANGE_END} and not resi {CYS_RESI}")

n_seg = cmd.count_atoms("seg1")
print(f"تعداد اتم‌های قطعه‌ی پیوسته ({RANGE_START}-{RANGE_END}, بدون Cys124): {n_seg}")

cmd.create("active_site_model", "seg1 or cyq")
n_atoms = cmd.count_atoms("active_site_model")
print(f"تعداد کل اتم‌های مدل موضعی نهایی: {n_atoms}")

cmd.save("active_site_raw.pdb", "active_site_model")
print("فایل ذخیره شد: active_site_raw.pdb (یک قطعه‌ی پیوسته، فقط دو نقطه‌ی برش)")
