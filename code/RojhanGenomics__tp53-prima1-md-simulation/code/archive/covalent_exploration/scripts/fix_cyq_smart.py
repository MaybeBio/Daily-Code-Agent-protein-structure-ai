from pymol import cmd

cmd.reinitialize()
cmd.load("CYQ_clean.pdb", "cyq")

# ۱. حذف تمامی هیدروژن‌های موجود
cmd.remove("elem H")

# ۲. پاک‌سازی کامل تمام پیوندهای اتم SG
cmd.unbond("name SG", "all")

# ۳. اتصال مجدد گوگرد به CB
cmd.bond("name SG", "name CB")

# ۴. یافتن دقیق نزدیک‌ترین اتم کربن لیگاند به SG برای پیوند کووالانت
atoms = cmd.get_model("cyq and not name SG+CB").atom
sg_atom = cmd.get_model("cyq and name SG").atom[0]

min_dist = 999.0
closest_atom_name = None

for a in atoms:
    dist = ((a.coord[0]-sg_atom.coord[0])**2 + (a.coord[1]-sg_atom.coord[1])**2 + (a.coord[2]-sg_atom.coord[2])**2)**0.5
    if dist < min_dist:
        min_dist = dist
        closest_atom_name = a.name

print(f"اتم SG به CB و اتم {closest_atom_name} (فاصله: {min_dist:.2f} آنگستروم) متصل شد.")
cmd.bond("name SG", f"name {closest_atom_name}")

# ۵. اضافه کردن هیدروژن‌های استاندارد به سایر اتم‌ها
cmd.h_add("cyq")

# ۶. اطمینان از عدم وجود هیدروژن روی گوگرد
cmd.remove("elem H and neighbor name SG")

# ۷. ذخیره ساختار
cmd.save("CYQ_correct.mol2", "cyq")
print("فایل CYQ_correct.mol2 با موفقیت ساخته شد.")
