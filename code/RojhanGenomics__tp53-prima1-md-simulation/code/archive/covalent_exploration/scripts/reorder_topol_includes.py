import os, re

def file_has_atomtypes(filepath):
    if not os.path.exists(filepath):
        return False
    try:
        with open(filepath, 'r') as f:
            for line in f:
                clean = line.split(';')[0].strip()
                if '[ atomtypes ]' in clean or '[atomtypes]' in clean:
                    return True
    except Exception:
        pass
    return False

with open("topol.top", "r") as f:
    lines = f.readlines()

atomtype_includes = []
other_lines = []

for line in lines:
    match = re.search(r'^\s*#include\s+["\']([^"\']+)["\']', line)
    if match:
        inc_file = match.group(1)
        if "forcefield.itp" in inc_file:
            other_lines.append(line)
        elif file_has_atomtypes(inc_file):
            if line not in atomtype_includes:
                atomtype_includes.append(line)
        else:
            other_lines.append(line)
    else:
        other_lines.append(line)

final_lines = []
inserted = False

for line in other_lines:
    final_lines.append(line)
    if "forcefield.itp" in line and not inserted:
        if atomtype_includes:
            final_lines.append("\n; Atomtypes definitions (must be placed before moleculetypes)\n")
            final_lines.extend(atomtype_includes)
            final_lines.append("\n")
        inserted = True

if not inserted and atomtype_includes:
    final_lines = atomtype_includes + ["\n"] + final_lines

with open("topol.top", "w") as f:
    f.writelines(final_lines)

print("فایل topol.top با موفقیت بر اساس قوانین ترتیب گرومکس مرتب‌سازی شد.")
