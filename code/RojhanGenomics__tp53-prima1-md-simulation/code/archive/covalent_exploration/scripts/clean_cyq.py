from pymol import cmd

cmd.load("CYQ_residue_v2.pdb", "cyq")
# حذف مولکول‌های آب و یون‌های احتمالی
cmd.remove("resn SOL or resn HOH or resn WAT or name OW+HW1+HW2")
cmd.save("CYQ_clean.pdb", "cyq")
n_atoms = cmd.count_atoms("cyq")
print(f"فایل تمیز ساخته شد. تعداد اتم‌های CYQ: {n_atoms}")
