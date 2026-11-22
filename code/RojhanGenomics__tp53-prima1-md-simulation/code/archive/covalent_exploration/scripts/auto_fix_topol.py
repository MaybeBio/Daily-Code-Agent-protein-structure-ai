import os

# خواندن فایل nvt.gro
with open("nvt.gro", "r") as f:
    gro_lines = f.readlines()

total_gro_atoms = int(gro_lines[1].strip())
print(f"تعداد کل اتم‌ها در nvt.gro: {total_gro_atoms}")

# استخراج ترتیب و تعداد دقیق تمام مولکول‌های آب و یون‌ها
ordered_mols = []
prev_res_id = None

for line in gro_lines[2:-1]:
    if len(line) < 20:
        continue
    res_id = line[:5].strip()
    res_name = line[5:10].strip().upper()
    
    if res_id != prev_res_id:
        prev_res_id = res_id
        if res_name in ["SOL", "WAT", "H2O", "TIP3", "OW"]:
            mtype = "SOL"
        elif res_name in ["NA", "NA+", "SOD"]:
            mtype = "NA"
        elif res_name in ["CL", "CL-", "CLA"]:
            mtype = "CL"
        else:
            continue
        
        if not ordered_mols or ordered_mols[-1][0] != mtype:
            ordered_mols.append([mtype, 1])
        else:
            ordered_mols[-1][1] += 1

print("ترتیب و تعداد استخراج‌شده برای آب و یون‌ها:", ordered_mols)

# بازنویسی بخش [ molecules ] در topol.top
with open("topol.top", "r") as f:
    top_lines = f.readlines()

clean_lines = []
for line in top_lines:
    if line.strip().startswith("[ molecules ]"):
        clean_lines.append("[ molecules ]\n; Compound        #mols\n")
        break
    clean_lines.append(line)

# تعریف ساختارهای اصلی پروتئین و لیگاند
clean_lines.append("Protein_chain_A 1\n")
clean_lines.append("Ion_chain_A2    1\n")
clean_lines.append("CYQ             1\n")

# اضافه کردن آب و یون‌ها به همان ترتیبی که در gro وجود دارند
for mtype, count in ordered_mols:
    clean_lines.append(f"{mtype:<15} {count}\n")

with open("topol.top", "w") as f:
    f.writelines(clean_lines)

print("فایل topol.top با موفقیت به روزرسانی شد.")
