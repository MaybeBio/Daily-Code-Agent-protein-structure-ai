import re
import numpy as np

src_pdb = 'demo_data/results/3AIC_docked_complex_CAHWRPWHC.pdb'

with open(src_pdb, 'r') as f:
    lines = f.readlines()

header_lines = []
chain_a_lines = []
chain_b_lines = []

for line in lines:
    if line.startswith(('COMPND', 'REMARK', 'HEADER', 'TITLE')):
        header_lines.append(line)
    elif line.startswith('ATOM') or line.startswith('HETATM'):
        ch = line[21]
        if ch == 'A':
            chain_a_lines.append(line)
        elif ch == 'B':
            chain_b_lines.append(line)

print(f'Original Chain A atoms: {len(chain_a_lines)}')
print(f'Original Chain B atoms: {len(chain_b_lines)}')

# Clean Chain B
# Sequence: C(1) A(2) H(3) W(4) R(5) P(6) W(7) H(8) C(9)
# Map any UNL hydrogen to the last active residue in Chain B
cleaned_b_lines = []
last_resn = 'CYS'
last_resi = 1

for line in chain_b_lines:
    atom_num = int(line[6:11].strip())
    atom_name = line[12:16]
    resn = line[17:20].strip()
    chain = line[21]
    resi_str = line[22:26].strip()
    resi = int(resi_str) if resi_str.isdigit() else 1
    
    if resn == 'UNL':
        # Assign to last_resn and last_resi
        resn = last_resn
        resi = last_resi
    else:
        last_resn = resn
        last_resi = resi
        
    x = float(line[30:38])
    y = float(line[38:46])
    z = float(line[46:54])
    occ = float(line[54:60]) if len(line) >= 60 and line[54:60].strip() else 1.00
    bfac = float(line[60:66]) if len(line) >= 66 and line[60:66].strip() else 0.00
    elem = line[76:78] if len(line) >= 78 else atom_name.strip()[:1].rjust(2)

    new_line = f"ATOM  {atom_num:5d} {atom_name:4s} {resn:3s} B{resi:4d}    {x:8.3f}{y:8.3f}{z:8.3f}{occ:6.2f}{bfac:6.2f}          {elem:>2s}\n"
    cleaned_b_lines.append(new_line)

print(f'Cleaned Chain B atoms: {len(cleaned_b_lines)}')

# Chain B coordinates for distance calculation
b_coords = np.array([[float(l[30:38]), float(l[38:46]), float(l[46:54])] for l in cleaned_b_lines])

# Catalytic triad center
triad_center = np.array([194.732, 46.367, 192.617])

# Group Chain A by residue
a_res_map = {}
for line in chain_a_lines:
    resi = int(line[22:26].strip())
    a_res_map.setdefault(resi, []).append(line)

cropped_a_lines = []
kept_resi = []

for resi in sorted(a_res_map.keys()):
    atom_lines = a_res_map[resi]
    coords = np.array([[float(l[30:38]), float(l[38:46]), float(l[46:54])] for l in atom_lines])
    
    # Distance to catalytic triad center
    dist_triad = np.linalg.norm(coords - triad_center, axis=1).min()
    # Distance to Chain B
    dist_b = min(np.linalg.norm(coords - b_coord, axis=1).min() for b_coord in b_coords)
    
    # Include if triad residue or within 18.0A of triad center or within 15.0A of ligand
    if resi in (477, 515, 588) or dist_triad <= 18.0 or dist_b <= 15.0:
        cropped_a_lines.extend(atom_lines)
        kept_resi.append(resi)

print(f'Cropped Chain A residues: {len(kept_resi)} (atoms: {len(cropped_a_lines)})')
print(f'Triad present: {all(r in kept_resi for r in (477, 515, 588))}')

# Re-number atom serials cleanly
final_lines = []
# Keep header
for hl in header_lines:
    final_lines.append(hl)

atom_idx = 1
for line in cropped_a_lines:
    new_line = f"{line[:6]}{atom_idx:5d}{line[11:]}"
    final_lines.append(new_line)
    atom_idx += 1

final_lines.append("TER\n")

for line in cleaned_b_lines:
    new_line = f"{line[:6]}{atom_idx:5d}{line[11:]}"
    final_lines.append(new_line)
    atom_idx += 1

final_lines.append("TER\nEND\n")

with open(src_pdb, 'w') as f:
    f.writelines(final_lines)

print(f'Wrote {len(final_lines)} lines to {src_pdb}')
