"""
استخراج بهترین pose (mode 1) از نتایج داکینگ و شناسایی residueهای پروتئین
که در تماس نزدیک با لیگاند هستند (تشکیل‌دهنده‌ی binding pocket)

اجرا با: pymol -cq analyze_pocket.py
"""

from pymol import cmd

RECEPTOR_PDB = "2OCJ_chainA_clean.pdb"
DOCKING_RESULTS = "docking_results.pdbqt"
CONTACT_CUTOFF = 4.5  # آنگستروم - فاصله‌ی معمول برای تعریف "تماس نزدیک"

# بارگذاری پروتئین اصلی (فایل PDB تمیز، نه PDBQT، برای دقت بیشتر در نمایش)
cmd.load(RECEPTOR_PDB, "receptor")

# بارگذاری تمام poseهای داکینگ (PDBQT شامل چند مدل/state است)
cmd.load(DOCKING_RESULTS, "docking_poses")

# جدا کردن فقط بهترین pose (state 1 = mode 1، بهترین امتیاز affinity)
cmd.create("best_pose", "docking_poses", 1, 1)

# انتخاب residueهای پروتئین که در فاصله‌ی نزدیک به بهترین pose هستند
cmd.select("pocket_residues", f"(receptor within {CONTACT_CUTOFF} of best_pose) and polymer")

# استخراج لیست یکتای residueها (شماره + نام اسیدآمینه)
model = cmd.get_model("pocket_residues and name CA")
# چون ممکن است CA برخی residueهای نزدیک در شعاع cutoff نباشد، دوباره با هر اتم residue بررسی می‌کنیم
model_all = cmd.get_model("pocket_residues")
residue_set = sorted(set((int(atom.resi), atom.resn) for atom in model_all.atom), key=lambda x: x[0])

print(f"=== Residueهای تشکیل‌دهنده‌ی binding pocket (در شعاع {CONTACT_CUTOFF} آنگستروم از بهترین pose) ===")
for resi, resn in residue_set:
    print(f"  {resn}{resi}")

print(f"\nتعداد کل residueهای درگیر: {len(residue_set)}")

# ذخیره‌ی pocket برای بررسی بصری بعدی
cmd.save("best_pose.pdb", "best_pose")
cmd.save("pocket_residues.pdb", "pocket_residues")
print("\nفایل‌های best_pose.pdb و pocket_residues.pdb ذخیره شدند.")

