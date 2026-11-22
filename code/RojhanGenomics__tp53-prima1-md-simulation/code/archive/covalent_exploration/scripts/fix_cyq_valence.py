from pymol import cmd

cmd.reinitialize()
cmd.load("CYQ_clean.pdb", "cyq")

# ۱. حذف تمامی هیدروژن‌های موجود
cmd.remove("elem H")

# ۲. اضافه کردن هیدروژن‌های استاندارد
cmd.h_add("cyq")

# ۳. حذف هیدروژن اضافی اضافه شده به گوگرد (SG)
cmd.remove("elem H and neighbor name SG")

# ۴. ذخیره فایل اصلاح‌شده
cmd.save("CYQ_fixed.mol2", "cyq")
print("ساختار CYQ با حذف هیدروژن اضافی SG در CYQ_fixed.mol2 ذخیره شد.")
