import os

with open("index.ndx", "r") as f:
    content = f.read()

# استخراج گروه‌های موجود
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

# جمع‌آوری اتم‌های پروتئین، یون روی و لیگاند
protein_atoms = set(groups.get("Protein", []))
zn_atoms = set(groups.get("ZN", []))
prima_atoms = set(groups.get("PRIMA", []))

# ترکیب اتم‌ها و مرتب‌سازی بر اساس شماره اتم
combined = sorted(list(protein_atoms | zn_atoms | prima_atoms), key=lambda x: int(x))

# پاکسازی بخش قدیمی در صورت وجود
if "[ Protein_ZN_UNL ]" in content:
    content = content.split("[ Protein_ZN_UNL ]")[0]

# ساخت بخش جدید
new_section = "\n[ Protein_ZN_UNL ]\n"
for i in range(0, len(combined), 15):
    new_section += " ".join(combined[i:i+15]) + "\n"

with open("index.ndx", "w") as f:
    f.write(content.rstrip() + "\n" + new_section)

print(f"گروه Protein_ZN_UNL شامل {len(combined)} اتم به فایل index.ndx اضافه شد.")
