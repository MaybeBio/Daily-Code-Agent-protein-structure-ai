from pymol import cmd
cmd.load("CYQ_clean.pdb", "cyq")
cmd.save("CYQ_clean.mol2", "cyq")
print("فایل CYQ_clean.mol2 با اتصالات کامل ۳بعدی ساخته شد.")
