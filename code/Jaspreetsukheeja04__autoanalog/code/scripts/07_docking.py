from rdkit import Chem
from rdkit.Chem import AllChem
import pandas as pd
import subprocess
import json
import os
import shutil
import tempfile

out_csv    = snakemake.output[0]
pdbqt_path = snakemake.input[0]
grid_path  = snakemake.input[1]
screen_csv = snakemake.input[2]
os.makedirs(os.path.dirname(out_csv), exist_ok=True)

exh      = snakemake.config.get(
    "docking_exhaustiveness", 8)
ref_name = snakemake.config.get(
    "reference_name", "Reference")
ref_ic50 = snakemake.config.get(
    "reference_ic50_nm", 89)

df = pd.read_csv(screen_csv)

print("=" * 45)
print("STEP 7: MOLECULAR DOCKING")
print("=" * 45)
print(f"Compounds to dock: {len(df)}")
print(f"Exhaustiveness: {exh}")

with open(grid_path) as f:
    grid = json.load(f)

cx = grid["center_x"]
cy = grid["center_y"]
cz = grid["center_z"]
sx = grid.get("size_x", 25)
sy = grid.get("size_y", 25)
sz = grid.get("size_z", 25)

print(f"Grid center: ({cx}, {cy}, {cz})")
print(f"Grid size:   ({sx}, {sy}, {sz})")

vina_path = shutil.which("vina") or \
            shutil.which("autodock_vina") or \
            "/usr/local/bin/vina"
gnina_path = "/usr/local/bin/gnina"
gnina_ok = False

print(f"Vina path: {vina_path}")
print(f"GNINA available: {gnina_ok}")

def smiles_to_pdbqt(smiles, name, tmp_dir):
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        mol = Chem.AddHs(mol)
        AllChem.EmbedMolecule(
            mol, AllChem.ETKDGv3())
        AllChem.MMFFOptimizeMolecule(mol)

        pdb_path = os.path.join(
            tmp_dir, f"{name}.pdb")
        pdbqt_out = os.path.join(
            tmp_dir, f"{name}.pdbqt")

        Chem.MolToPDBFile(mol, pdb_path)

        result = subprocess.run([
            "obabel", pdb_path,
            "-O", pdbqt_out,
            "--gen3d", "-h"
        ], capture_output=True, text=True,
           timeout=60)

        if os.path.exists(pdbqt_out):
            return pdbqt_out
        return None
    except Exception as e:
        print(f"    PDBQT error {name}: {e}")
        return None

def run_vina(lig_pdbqt, name, tmp_dir):
    try:
        out_pdbqt = os.path.join(
            tmp_dir, f"{name}_out.pdbqt")
        cmd = [
            vina_path,
            "--receptor",    pdbqt_path,
            "--ligand",      lig_pdbqt,
            "--out",         out_pdbqt,
            "--center_x",    str(cx),
            "--center_y",    str(cy),
            "--center_z",    str(cz),
            "--size_x",      str(sx),
            "--size_y",      str(sy),
            "--size_z",      str(sz),
            "--exhaustiveness", str(exh),
            "--num_modes",   "5",
        ]
        result = subprocess.run(
            cmd, capture_output=True,
            text=True, timeout=300)

        score = None
        for line in result.stdout.split("\n"):
            if line.strip().startswith("1 "):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        score = float(parts[1])
                        break
                    except:
                        pass

        if score is None:
            for line in result.stdout.split("\n"):
                if "REMARK VINA RESULT" in line:
                    try:
                        score = float(
                            line.split()[3])
                        break
                    except:
                        pass

        return score
    except subprocess.TimeoutExpired:
        print(f"    Vina timeout: {name}")
        return None
    except Exception as e:
        print(f"    Vina error {name}: {e}")
        return None

def run_gnina(lig_pdbqt, name, tmp_dir):
    try:
        out_pdbqt = os.path.join(
            tmp_dir, f"{name}_gnina.pdbqt")
        cmd = [
            gnina_path,
            "--receptor",    pdbqt_path,
            "--ligand",      lig_pdbqt,
            "--out",         out_pdbqt,
            "--center_x",    str(cx),
            "--center_y",    str(cy),
            "--center_z",    str(cz),
            "--size_x",      str(sx),
            "--size_y",      str(sy),
            "--size_z",      str(sz),
            "--exhaustiveness", str(exh),
            "--num_modes",   "5",
            "--cnn_scoring", "rescore",
        ]
        result = subprocess.run(
            cmd, capture_output=True,
            text=True, timeout=300)

        score = None
        for line in result.stdout.split("\n"):
            if line.strip().startswith("1 "):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        score = float(parts[1])
                        break
                    except:
                        pass
        return score
    except Exception as e:
        print(f"    GNINA error {name}: {e}")
        return None

# ── DOCK ALL COMPOUNDS ────────────────────
records = []
tmp_dir = tempfile.mkdtemp()

ref_vina_score = None

try:
    for i, row in df.iterrows():
        smi  = str(row["smiles"])
        name = str(row["name"])
        print(f"\n  [{i+1}/{len(df)}] Docking {name}...")

        lig_pdbqt = smiles_to_pdbqt(
            smi, name, tmp_dir)
        if lig_pdbqt is None:
            print(f"    SKIP: could not make PDBQT")
            continue

        vina_score  = run_vina(
            lig_pdbqt, name, tmp_dir)
        gnina_score = run_gnina(
            lig_pdbqt, name, tmp_dir) \
            if gnina_ok else None

        if vina_score and gnina_score:
            dock_score = round(
                0.5*vina_score +
                0.5*gnina_score, 3)
            tools = "Vina+GNINA"
        elif vina_score:
            dock_score = vina_score
            tools = "Vina"
        elif gnina_score:
            dock_score = gnina_score
            tools = "GNINA"
        else:
            dock_score = None
            tools = "Failed"

        if "ref" in name.lower():
            ref_vina_score = dock_score

        vs_ref = ""
        if dock_score and ref_vina_score:
            vs_ref = "Better" \
                if dock_score < ref_vina_score \
                else "Worse"

        rec = dict(row)
        rec["vina_score"]    = vina_score
        rec["gnina_score"]   = gnina_score
        rec["docking_score"] = dock_score
        rec["tools_used"]    = tools
        rec["vs_ref_dock"]   = vs_ref

        records.append(rec)
        print(f"    Vina={vina_score} "
              f"GNINA={gnina_score} "
              f"Final={dock_score} "
              f"({tools})")

finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)

out_df = pd.DataFrame(records)
out_df = out_df.sort_values(
    "docking_score", na_position="last")
out_df.to_csv(out_csv, index=False)

# ── IC50 COMPARISON ───────────────────────
print("\n" + "=" * 45)
print("DOCKING RESULTS SUMMARY")
print("=" * 45)
print(f"Total docked: {len(out_df)}")
print(f"Reference {ref_name} IC50: {ref_ic50} nM")

if ref_vina_score:
    print(f"Reference docking score: "
          f"{ref_vina_score} kcal/mol")
    better = out_df[
        (out_df["docking_score"] <
         ref_vina_score) &
        (~out_df["name"].str.contains(
            "ref", case=False, na=False))
    ]
    print(f"Analogues better than reference: "
          f"{len(better)}")

print("\nTop 5 docking scores:")
for _, r in out_df.head(5).iterrows():
    print(f"  {r['name']}: "
          f"{r['docking_score']} kcal/mol "
          f"({r['tools_used']})")

print("\nStep 7 complete")
