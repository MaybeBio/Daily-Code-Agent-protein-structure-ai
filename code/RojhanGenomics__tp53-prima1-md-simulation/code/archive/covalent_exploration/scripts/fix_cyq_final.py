from pymol import cmd

cmd.reinitialize()
cmd.load("CYQ_clean.pdb", "cyq")

# ۱. حذف تمامی هیدروژن‌ها
cmd.remove("elem H")

# ۲. پاک‌سازی کامل تمام پیوندهای گوگرد
cmd.unbond("name SG", "all")

# ۳. اتصال گوگرد به CB زنجیره اصلی
cmd.bond("name SG", "name CB")

# ۴. اتصال صریح گوگرد به اتم CC8 / LC8 / C8 لیگاند
cmd.bond("name SG", "name CC8+LC8+C8")

# ۵. بازسازی هیدروژن‌های استاندارد
cmd.h_add("cyq")

# ۶. حذف هیدروژن احتمالی روی گوگرد
cmd.remove("elem H and neighbor name SG")

# ۷. ذخیره ساختار اصلاح‌شده
cmd.save("CYQ_correct.mol2", "cyq")
print("پیوند کووالانت SG به CC8 با موفقیت ثبت شد و فایل CYQ_correct.mol2 ساخته شد.")
