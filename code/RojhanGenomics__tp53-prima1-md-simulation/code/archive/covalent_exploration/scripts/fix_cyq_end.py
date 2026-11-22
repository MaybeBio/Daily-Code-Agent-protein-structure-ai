with open("cyq.itp", "r") as f:
    lines = f.readlines()

cleaned_lines = []
skip = False

for line in lines:
    stripped = line.strip()
    if stripped.startswith("[ molecules ]") or stripped.startswith("[ system ]") or stripped.startswith("[ defaults ]"):
        skip = True
        continue
    if skip and stripped.startswith("[") and not (stripped.startswith("[ molecules ]") or stripped.startswith("[ system ]") or stripped.startswith("[ defaults ]")):
        skip = False
        
    if not skip:
        cleaned_lines.append(line)

with open("cyq.itp", "w") as f:
    f.writelines(cleaned_lines)

print("دستورات اضافی [ molecules ] و [ system ] از cyq.itp حذف شدند.")
