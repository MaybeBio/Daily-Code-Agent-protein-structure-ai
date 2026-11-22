with open("cyq.itp", "r") as f:
    lines = f.readlines()

new_lines = []
skip = False

for line in lines:
    if line.strip().startswith("[ defaults ]"):
        skip = True
        continue
    if skip and line.strip().startswith("["):
        skip = False
    
    if not skip:
        new_lines.append(line)

with open("cyq.itp", "w") as f:
    f.writelines(new_lines)

print("بخش [ defaults ] با موفقیت از cyq.itp حذف شد.")
