from pathlib import Path
import math

INPUT = Path("protein_plus_adduct_raw.pdb")
OUTPUT = Path("protein_MQ_CYS124_bonded.pdb")

# Protein Cys124 sulfur
CYS_SG_SERIAL = 218

# MQ adduct carbon that is covalently attached to Cys-SG
MQ_C8_SERIAL = 1535

# ---------------------------------------------------------------------
# Read PDB
# ---------------------------------------------------------------------

lines = INPUT.read_text().splitlines()

# Make sure both atoms exist
atom_records = {}

for i, line in enumerate(lines):
    if line.startswith(("ATOM", "HETATM")):
        serial = int(line[6:11])
        atom_records[serial] = {
            "line_index": i,
            "name": line[12:16].strip(),
            "resname": line[17:20].strip(),
            "chain": line[21].strip(),
            "resid": line[22:26].strip(),
            "x": float(line[30:38]),
            "y": float(line[38:46]),
            "z": float(line[46:54]),
        }

if CYS_SG_SERIAL not in atom_records:
    raise RuntimeError(f"Cys SG atom {CYS_SG_SERIAL} not found.")

if MQ_C8_SERIAL not in atom_records:
    raise RuntimeError(f"MQ C8 atom {MQ_C8_SERIAL} not found.")

sg = atom_records[CYS_SG_SERIAL]
c8 = atom_records[MQ_C8_SERIAL]

# ---------------------------------------------------------------------
# Calculate current SG-C8 distance
# ---------------------------------------------------------------------

dx = c8["x"] - sg["x"]
dy = c8["y"] - sg["y"]
dz = c8["z"] - sg["z"]

distance = math.sqrt(dx*dx + dy*dy + dz*dz)

print("==============================================")
print("COVALENT COMPLEX CHECK")
print("==============================================")
print(f"Cys124 SG : serial {CYS_SG_SERIAL}")
print(
    f"  coordinates = "
    f"({sg['x']:.3f}, {sg['y']:.3f}, {sg['z']:.3f})"
)

print(f"MQ C8      : serial {MQ_C8_SERIAL}")
print(
    f"  coordinates = "
    f"({c8['x']:.3f}, {c8['y']:.3f}, {c8['z']:.3f})"
)

print(f"Current SG-C8 distance = {distance:.3f} Å")

if not (1.6 <= distance <= 2.1):
    raise RuntimeError(
        "SG-C8 distance is outside the expected covalent-bond range. "
        "Do not create the bonded complex yet."
    )

# ---------------------------------------------------------------------
# Check existing CONECT records
# ---------------------------------------------------------------------

conect_pairs = set()

for line in lines:
    if line.startswith("CONECT"):
        nums = []
        for start in range(6, len(line), 5):
            field = line[start:start+5].strip()
            if field:
                try:
                    nums.append(int(field))
                except ValueError:
                    pass

        if len(nums) >= 2:
            first = nums[0]
            for other in nums[1:]:
                conect_pairs.add(tuple(sorted((first, other))))

existing_pair = tuple(sorted((CYS_SG_SERIAL, MQ_C8_SERIAL)))

print()
print("Existing SG-C8 CONECT:", existing_pair in conect_pairs)

# ---------------------------------------------------------------------
# Add explicit covalent CONECT records
# ---------------------------------------------------------------------

new_lines = list(lines)

# Remove END if present, so new CONECT records can be inserted before END
end_line = None
if new_lines and new_lines[-1].strip() == "END":
    end_line = new_lines.pop()

# Avoid duplicate CONECT entries
if existing_pair not in conect_pairs:

    # PDB CONECT records use the first serial as the central atom.
    # Add the bond in both directions for compatibility.
    new_lines.append(
        f"CONECT{CYS_SG_SERIAL:5d}{MQ_C8_SERIAL:5d}"
    )
    new_lines.append(
        f"CONECT{MQ_C8_SERIAL:5d}{CYS_SG_SERIAL:5d}"
    )

if end_line is not None:
    new_lines.append(end_line)

OUTPUT.write_text("\n".join(new_lines) + "\n")

print()
print("==============================================")
print("OUTPUT CREATED")
print("==============================================")
print(OUTPUT)

print()
print("Added covalent connection:")
print(f"  CYS124 SG ({CYS_SG_SERIAL})")
print("        ||")
print("        C-S")
print("        ||")
print(f"  MQ C8 ({MQ_C8_SERIAL})")

print()
print("Original file was NOT modified.")
