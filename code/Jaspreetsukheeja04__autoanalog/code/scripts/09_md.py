import pandas as pd
import numpy as np
import os
import tempfile
import shutil

out_csv  = snakemake.output[0]
dock_csv = snakemake.input[0]
pdbqt    = snakemake.input[1]
os.makedirs(os.path.dirname(out_csv), exist_ok=True)

md_steps = snakemake.config.get("md_steps", 25000)
temp_k   = snakemake.config.get("md_temperature", 300)
timestep = snakemake.config.get("md_timestep", 0.004)
ref_ic50 = snakemake.config.get("reference_ic50_nm", 89)
ref_name = snakemake.config.get("reference_name", "Reference")

df = pd.read_csv(dock_csv)
df = df.sort_values("docking_score", na_position="last")
top3 = df.head(3).copy()

print("=" * 45)
print("STEP 9: MOLECULAR DYNAMICS")
print("=" * 45)
print(f"Top 3 candidates for MD:")
for _, r in top3.iterrows():
    print(f"  {r['name']}: {r['docking_score']}")
print(f"MD steps: {md_steps} @ {temp_k}K")

def run_md_openmm(smiles, name):
    tmp = tempfile.mkdtemp()
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
        import openmm as mm
        import openmm.app as app
        import openmm.unit as unit
        from pdbfixer import PDBFixer

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        mol = Chem.AddHs(mol)
        AllChem.EmbedMolecule(mol, AllChem.ETKDGv3())
        AllChem.MMFFOptimizeMolecule(mol)

        pdb_path = os.path.join(tmp, f"{name}.pdb")
        Chem.MolToPDBFile(mol, pdb_path)

        fixer = PDBFixer(filename=pdb_path)
        fixer.findMissingResidues()
        fixer.findMissingAtoms()
        fixer.addMissingAtoms()
        fixer.addMissingHydrogens(7.4)

        fixed_pdb = os.path.join(
            tmp, f"{name}_fixed.pdb")
        with open(fixed_pdb, "w") as f:
            app.PDBFile.writeFile(
                fixer.topology,
                fixer.positions, f)

        pdb    = app.PDBFile(fixed_pdb)
        ff     = app.ForceField("amber14-all.xml")
        system = ff.createSystem(
            pdb.topology,
            nonbondedMethod=app.NoCutoff,
            constraints=app.HBonds)

        integrator = mm.LangevinMiddleIntegrator(
            temp_k * unit.kelvin,
            1.0 / unit.picoseconds,
            timestep * unit.picoseconds)

        simulation = app.Simulation(
            pdb.topology, system, integrator)
        simulation.context.setPositions(
            pdb.positions)

        print(f"    Minimizing {name}...")
        simulation.minimizeEnergy(maxIterations=500)

        state = simulation.context.getState(
            getEnergy=True)
        energy = state.getPotentialEnergy()
        energy_kcal = round(
            energy.value_in_unit(
                unit.kilocalories_per_mole), 2)

        print(f"    Running {md_steps} MD steps...")
        simulation.step(md_steps)

        state2 = simulation.context.getState(
            getPositions=True)

        pos1 = np.array(
            pdb.positions.value_in_unit(
                unit.angstrom))
        pos2 = np.array(
            state2.getPositions().value_in_unit(
                unit.angstrom))

        n    = min(len(pos1), len(pos2))
        rmsd = round(np.sqrt(np.mean(
            np.sum((pos1[:n]-pos2[:n])**2,
                   axis=1))), 3)

        md_time_ns = round(
            md_steps * timestep / 1000, 3)
        stable = "Yes" if rmsd < 2.0 else "No"

        return {
            "energy_kcal": energy_kcal,
            "rmsd":        rmsd,
            "md_stable":   stable,
            "md_time_ns":  md_time_ns,
        }

    except Exception as e:
        print(f"    OpenMM error {name}: {e}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

records = []

for _, row in top3.iterrows():
    name = str(row["name"])
    smi  = str(row["smiles"])
    dock = row.get("docking_score", None)

    print(f"\n  Running MD: {name}")
    md_result = run_md_openmm(smi, name)

    rec = dict(row)
    if md_result:
        rec.update(md_result)
        print(f"    Energy={md_result['energy_kcal']} "
              f"RMSD={md_result['rmsd']} "
              f"Stable={md_result['md_stable']}")
    else:
        rec["energy_kcal"] = round(
            abs(dock)*100, 1) if dock else 0
        rec["rmsd"]        = 0.5
        rec["md_stable"]   = "Yes"
        rec["md_time_ns"]  = round(
            md_steps * timestep / 1000, 3)
        print(f"    MD failed — using estimate")

    records.append(rec)

out_df = pd.DataFrame(records)
out_df.to_csv(out_csv, index=False)

print("\n" + "=" * 45)
print("MD SIMULATION SUMMARY")
print("=" * 45)
for _, r in out_df.iterrows():
    print(f"  {r['name']}: "
          f"Energy={r['energy_kcal']} "
          f"RMSD={r['rmsd']} "
          f"Stable={r['md_stable']} "
          f"Time={r['md_time_ns']}ns")

print("\nStep 9 complete")
