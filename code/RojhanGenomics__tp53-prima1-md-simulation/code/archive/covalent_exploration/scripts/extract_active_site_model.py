"""
استخراج مدل موضعی سایت فعال - نسخه‌ی اصلاح‌شده با فیلتر صریح اسیدآمینه‌ها
"""

from pymol import cmd

CYS_RESI = 124
CUTOFF = 10.0

# لیست صریح نام‌های استاندارد اسیدآمینه (برای جلوگیری از خطای طبقه‌بندی PyMOL)
AA_LIST = "ALA+ARG+ASN+ASP+CYS+GLU+GLN+GLY+HIS+HSE+HSD+HSP+HIE+HID+HIP+ILE+LEU+LYS+MET+PHE+PRO+SER+THR+TRP+TYR+VAL"

cmd.load("npt_protein.pdb", "protein")
cmd.load("CYQ_residue_v2.pdb", "cyq")

cmd.select("real_protein", f"resn {AA_LIST}")
n_prot = cmd.count_atoms("real_protein")
print(f"تعداد اتم‌های واقعی پروتئین (با فیلتر صریح): {n_prot}")

cmd.select("nearby", f"(real_protein and byres (real_protein within {CUTOFF} of cyq)) and not resi {CYS_RESI}")
nearby_resis = set()
cmd.iterate("nearby", "nearby_resis.add(resi)", space={"nearby_resis": nearby_resis})
nearby_resis = sorted(nearby_resis, key=int)
print(f"تعداد residueهای پروتئین در شعاع {CUTOFF} Å اطراف Cys124: {len(nearby_resis)}")
print(f"شماره‌های residue: {nearby_resis}")

cmd.create("active_site_model", "nearby or cyq")
n_atoms = cmd.count_atoms("active_site_model")
print(f"\nتعداد کل اتم‌های مدل موضعی (قبل از کلاهک‌گذاری): {n_atoms}")

cmd.save("active_site_raw.pdb", "active_site_model")
print("فایل ذخیره شد: active_site_raw.pdb")
