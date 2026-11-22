import os
import parmed as pmd

# ۱. ساخت اسکریپت tleap جهت ترکیب mol2 و frcmod
tleap_script = """
source leaprc.gaff2
CYQ = loadmol2 cyq.mol2
loadamberparams cyq.frcmod
saveamberparm CYQ cyq.prmtop cyq.inpcrd
quit
"""
with open("tleap.in", "w") as f:
    f.write(tleap_script)

# ۲. اجرای tleap
os.system("tleap -f tleap.in")

# ۳. تبدیل توپولوژی AMBER به GROMACS با ParmEd
mol = pmd.load_file("cyq.prmtop", "cyq.inpcrd")
mol.save("cyq_gmx.top", format="gromacs")
mol.save("cyq.gro", overwrite=True)

print("فایل‌های cyq_gmx.top و cyq.gro ساخته شدند.")
