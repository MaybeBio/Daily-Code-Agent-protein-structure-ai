import os

with open("index.ndx", "r") as f:
    content = f.read()

# استخراج گروه‌ها
groups = {}
current_group = None
lines = content.splitlines()

for line in lines:
    line_s = line.strip()
    if line_s.startswith("[") and line_s.endswith("]"):
        current_group = line_s[1:-1].strip()
        groups[current_group] = []
    elif current_group and line_s:
        groups[current_group].extend(line_s.split())

# جمع‌آوری اتم‌های SOL و CL (بدون یون روی ZN)
sol_atoms = set(groups.get("SOL", []) or groups.get("Water", []))
cl_atoms = set(groups.get("CL", []) or groups.get("Ion", []))
zn_atoms = set(groups.get("ZN", []))

sol_cl_atoms = (sol_atoms | cl_atoms) - zn_atoms
combined = sorted(list(sol_cl_atoms), key=lambda x: int(x))

# پاکسازی بخش قدیمی در صورت وجود
if "[ SOL_CL ]" in content:
    content = content.split("[ SOL_CL ]")[0]

# ساخت بخش جدید
new_section = "\n[ SOL_CL ]\n"
for i in range(0, len(combined), 15):
    new_section += " ".join(combined[i:i+15]) + "\n"

with open("index.ndx", "w") as f:
    f.write(content.rstrip() + "\n" + new_section)

print(f"گروه SOL_CL شامل {len(combined)} اتم به فایل index.ndx اضافه شد.")
