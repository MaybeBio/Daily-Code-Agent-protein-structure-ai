import os

# ۱. خواندن و تحلیل ساختار npt.gro
with open("npt.gro", "r") as f:
    gro_lines = [l for l in f.readlines() if l.strip()]

total_atoms = int(gro_lines[1].strip())

sol_mols = set()
cl_mols = set()
na_mols = set()
non_sol_atoms = []

for line in gro_lines[2:-1]:
    if len(line) < 20:
        continue
    atom_id = int(line[15:20].strip())
    res_num = line[:5].strip()
    res_name = line[5:10].strip().upper()

    if res_name in ["SOL", "WAT", "H2O", "TIP3", "OW", "HW1", "HW2"]:
        sol_mols.add(res_num)
    elif res_name in ["CL", "CLA", "CL-"]:
        cl_mols.add(res_num)
    elif res_name in ["NA", "SOD", "NA+"]:
        na_mols.add(res_num)
    else:
        non_sol_atoms.append(atom_id)

num_sol = len(sol_mols)
num_cl = len(cl_mols)
num_na = len(na_mols)
num_non_sol = len(non_sol_atoms)

print(f"تعداد اتم‌های پروتئین/لیگاند/روی: {num_non_sol}")
print(f"تعداد مولکول‌های آب (SOL): {num_sol}")
print(f"تعداد یون‌های کلر (CL): {num_cl}")
print(f"تعداد یون‌های سدیم (NA): {num_na}")

# ۲. بازنویسی انتهای topol.top
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
clean_top.append(f"{'SOL':<15} {num_sol}\n")
if num_na > 0:
    clean_top.append(f"{'NA':<15} {num_na}\n")
if num_cl > 0:
    clean_top.append(f"{'CL':<15} {num_cl}\n")

with open("topol.top", "w") as f:
    f.writelines(clean_top)

print("فایل topol.top با موفقیت به روزرسانی شد.")

# ۳. به‌روزرسانی فایل index.ndx و افزودن گروه‌های مورد نیاز grompp
existing_ndx = ""
if os.path.exists("index.ndx"):
    with open("index.ndx", "r") as f:
        existing_ndx = f.read()

new_groups = ""

def format_ndx_group(name, atom_list):
    res = f"\n[ {name} ]\n"
    for i in range(0, len(atom_list), 15):
        res += " ".join(f"{a:5d}" for a in atom_list[i:i+15]) + "\n"
    return res

if "[ Protein_ZN_UNL ]" not in existing_ndx:
    new_groups += format_ndx_group("Protein_ZN_UNL", list(range(1, num_non_sol + 1)))

if "[ Protein_ZN_CYQ ]" not in existing_ndx:
    new_groups += format_ndx_group("Protein_ZN_CYQ", list(range(1, num_non_sol + 1)))

if "[ Water_and_ions ]" not in existing_ndx:
    new_groups += format_ndx_group("Water_and_ions", list(range(num_non_sol + 1, total_atoms + 1)))

with open("index.ndx", "a") as f:
    f.write(new_groups)

print("گروه‌های Protein_ZN_UNL و Water_and_ions با موفقیت به index.ndx اضافه شدند.")
