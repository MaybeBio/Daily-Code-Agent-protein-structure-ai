with open("topol.top", "r") as f:
    lines = f.readlines()

# حذف خطوط قبلی PRIMA1.itp برای جلوگیری از تکرار
clean_lines = [l for l in lines if "PRIMA1.itp" not in l]

new_lines = []
inserted = False
for line in clean_lines:
    new_lines.append(line)
    # قرار دادن include لیگاند دقیقاً زیر forcefield.itp
    if "forcefield.itp" in line and not inserted:
        new_lines.append('; Include ligand topology\n#include "PRIMA1.itp"\n')
        inserted = True

with open("topol.top", "w") as f:
    f.writelines(new_lines)

print("فایل topol.top با موفقیت اصلاح شد.")
