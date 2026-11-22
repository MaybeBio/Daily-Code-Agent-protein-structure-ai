import os
import json
import requests
import subprocess
import shutil
import numpy as np

out_pdbqt  = snakemake.output[0]
out_grid   = snakemake.output[1]
os.makedirs(os.path.dirname(out_pdbqt), exist_ok=True)

pdb_id   = snakemake.config.get("pdb_id","").strip()
sequence = snakemake.config.get("sequence","").strip()
receptor = snakemake.config["receptor"]
disease  = snakemake.config["disease"]

print("=" * 45)
print("STEP 1: PROTEIN STRUCTURE PREPARATION")
print("=" * 45)

tmp_dir = "results/structure/tmp"
os.makedirs(tmp_dir, exist_ok=True)

pdb_path = os.path.join(tmp_dir, "protein.pdb")

# ── SOURCE 1: PDB DOWNLOAD ────────────────
def download_pdb(pdb_id):
    print(f"Downloading PDB {pdb_id}...")
    url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
    r   = requests.get(url, timeout=60)
    if r.status_code == 200:
        with open(pdb_path, "w") as f:
            f.write(r.text)
        print(f"  Downloaded: {pdb_path}")
        return True
    print(f"  PDB download failed: {r.status_code}")
    return False

# ── SOURCE 2: ALPHAFOLD2 ──────────────────
def predict_alphafold(sequence):
    print("Predicting structure with AlphaFold2...")
    try:
        af_url = "https://api.esmatlas.com/foldSequence/v1/pdb/"
        r = requests.post(
            af_url,
            data=sequence,
            headers={"Content-Type": "text/plain"},
            timeout=120)
        if r.status_code == 200:
            with open(pdb_path, "w") as f:
                f.write(r.text)
            print("  ESMFold prediction done")
            return True
    except Exception as e:
        print(f"  ESMFold error: {e}")
    return False

# ── GET STRUCTURE ─────────────────────────
got_structure = False

if pdb_id:
    got_structure = download_pdb(pdb_id)

if not got_structure and sequence:
    got_structure = predict_alphafold(sequence)

if not got_structure:
    raise ValueError(
        "Could not get structure — "
        "check pdb_id or sequence in config")

# ── PDBFIXER ──────────────────────────────
print("\nFixing structure with PDBFixer...")
try:
    from pdbfixer import PDBFixer
    import openmm.app as app

    fixer = PDBFixer(filename=pdb_path)
    fixer.findMissingResidues()
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    fixer.removeHeterogens(False)
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(7.4)

    fixed_path = os.path.join(
        tmp_dir, "protein_fixed.pdb")
    with open(fixed_path, "w") as f:
        app.PDBFile.writeFile(
            fixer.topology,
            fixer.positions, f)
    pdb_path = fixed_path
    print("  PDBFixer done")
except Exception as e:
    print(f"  PDBFixer error: {e}")
    print("  Using original PDB")

# ── OPENBABEL PDB → PDBQT ─────────────────
print("\nConverting to PDBQT...")
result = subprocess.run([
    "obabel", pdb_path,
    "-O", out_pdbqt,
    "-xr"
], capture_output=True, text=True, timeout=120)

if not os.path.exists(out_pdbqt):
    raise FileNotFoundError(
        f"PDBQT not created: {result.stderr}")
print(f"  Saved: {out_pdbqt}")

# ── GRID CONFIG ───────────────────────────
print("\nExtracting grid coordinates...")

hetatm_coords = []
with open(pdb_path) as f:
    for line in f:
        if line.startswith("HETATM"):
            try:
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
                hetatm_coords.append([x,y,z])
            except Exception:
                continue

if hetatm_coords:
    coords = np.array(hetatm_coords)
    cx = round(float(np.mean(coords[:,0])), 2)
    cy = round(float(np.mean(coords[:,1])), 2)
    cz = round(float(np.mean(coords[:,2])), 2)
    print(f"  Grid from HETATM ligand: "
          f"({cx}, {cy}, {cz})")
else:
    ca_coords = []
    with open(pdb_path) as f:
        for line in f:
            if line.startswith("ATOM") and \
               " CA " in line:
                try:
                    x = float(line[30:38])
                    y = float(line[38:46])
                    z = float(line[46:54])
                    ca_coords.append([x,y,z])
                except Exception:
                    continue
    if ca_coords:
        coords = np.array(ca_coords)
        cx = round(float(np.mean(coords[:,0])), 2)
        cy = round(float(np.mean(coords[:,1])), 2)
        cz = round(float(np.mean(coords[:,2])), 2)
        print(f"  Grid from CA atoms: "
              f"({cx}, {cy}, {cz})")
    else:
        cx, cy, cz = 0.0, 0.0, 0.0
        print("  WARNING: using origin (0,0,0)")

grid = {
    "center_x": cx,
    "center_y": cy,
    "center_z": cz,
    "size_x":   25,
    "size_y":   25,
    "size_z":   25,
}
with open(out_grid, "w") as f:
    json.dump(grid, f, indent=2)

print(f"  Grid saved: {out_grid}")
print(f"  Center: ({cx}, {cy}, {cz})")
print(f"  Size: 25 x 25 x 25")
print("\nStep 1 complete")
