from pymol import cmd

cmd.reinitialize()
cmd.load("CYQ_clean.pdb", "cyq")

# ۱. قطع پیوند کاذب SG با CC9 / LC9 / C9
cmd.unbond("name SG", "name CC9+LC9+C9")

# ۲. حصول اطمینان از وجود پیوند صحیح SG با CB و CC8 / LC8 / C8
cmd.bond("name SG", "name CB")
cmd.bond("name SG", "name CC8+LC8+C8")

# ۳. حذف تمامی هیدروژن‌های قبلی
cmd.remove("elem H")

# ۴. اضافه کردن مجدد هیدروژن‌ها (اکنون PyMOL برای CC9 هیدروژن لازم را می‌سازد)
cmd.h_add("cyq")

# ۵. حذف هیدروژن احتمالی اضافه شده به گوگرد (SG)
cmd.remove("elem H and neighbor name SG")

# ۶. ذخیره ساختار با ظرفیت‌های کامل و دقیق
cmd.save("CYQ_correct.mol2", "cyq")
print("فایل CYQ_correct.mol2 با ظرفیت‌های استاندارد ساخته شد.")
