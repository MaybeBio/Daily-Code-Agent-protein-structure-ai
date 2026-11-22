with open("npt.gro", "r") as f:
    gro_lines = [l for l in f.readlines() if l.strip()]

total_gro_atoms = int(gro_lines[1].strip())
print(f"تعداد کل اتم‌ها در npt.gro: {total_gro_atoms}")

print("\n۱۰ خط آخر فایل npt.gro جهت بررسی یون‌ها:")
for l in gro_lines[-11:-1]:
    print(l.strip())

with open("topol.top", "r") as f:
    top_lines = f.readlines()

clean_top = []
for line in top_lines:
    if line.strip().startswith("[ molecules ]"):
        clean_top.append("[ molecules ]\n; Compound        #mols\n")
        break
    clean_top.append(line)

clean_top.append("Protein_chain_A 1\n")
clean_top.append("Ion_chain_A2    1\n")
clean_top.append("CYQ             1\n")
clean_top.append("SOL             14346\n")
clean_top.append("NA              5\n")
clean_top.append("CL              5\n")

with open("topol.top", "w") as f:
    f.writelines(clean_top)

print("\nفایل topol.top با ترکیب (SOL: 14346, NA: 5, CL: 5) به ۴۶۰۸۲ اتم تنظیم شد.")
