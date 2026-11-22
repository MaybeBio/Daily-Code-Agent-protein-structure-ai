from rdkit import Chem, DataStructs
from rdkit.Chem import AllChem, rdMolDescriptors, rdFingerprintGenerator
import pandas as pd
import numpy as np
import os

out_csv = snakemake.output[0]
in_csv  = snakemake.input[0]
os.makedirs(os.path.dirname(out_csv), exist_ok=True)

known_inh  = snakemake.config.get("known_inhibitor", "")
threshold  = snakemake.config.get("tanimoto_vs_threshold", 0.4)
ref_name   = snakemake.config.get("reference_name", "Reference")

df = pd.read_csv(in_csv)

print("=" * 45)
print("STEP 6: VIRTUAL SCREENING")
print("=" * 45)
print(f"Input compounds: {len(df)}")
print(f"Tanimoto threshold: {threshold}")

mfpgen = rdFingerprintGenerator.GetMorganGenerator(
    radius=2, fpSize=2048)

def sanitize(smi):
    try:
        mol = Chem.MolFromSmiles(smi)
        if mol:
            Chem.SanitizeMol(mol)
        return mol
    except Exception:
        return None

ref_mol = sanitize(known_inh)
ref_fp  = mfpgen.GetFingerprint(ref_mol) \
          if ref_mol else None

def pharma_score(mol):
    if mol is None:
        return 0
    score = 0
    hbd  = rdMolDescriptors.CalcNumHBD(mol)
    hba  = rdMolDescriptors.CalcNumHBA(mol)
    arom = rdMolDescriptors.CalcNumAromaticRings(mol)
    rot  = rdMolDescriptors.CalcNumRotatableBonds(mol)
    if hbd >= 1:  score += 1
    if hba >= 2:  score += 1
    if arom >= 2: score += 1
    if rot <= 8:  score += 1
    return score

records = []

for _, row in df.iterrows():
    smi  = str(row["smiles"])
    name = str(row["name"])
    mol  = sanitize(smi)

    if mol is None:
        continue

    fp  = mfpgen.GetFingerprint(mol)
    tan = round(
        DataStructs.TanimotoSimilarity(fp, ref_fp),
        3) if ref_fp else 0.0

    pharma   = pharma_score(mol)
    vs_score = round(
        0.6*tan + 0.4*(pharma/4.0), 3)
    passes   = tan >= threshold

    rec = dict(row)
    rec["tanimoto_vs"]  = tan
    rec["pharma_score"] = pharma
    rec["vs_score"]     = vs_score
    rec["vs_pass"]      = "PASS" if passes else "FAIL"
    records.append(rec)

    status = "✓" if passes else "✗"
    print(f"  {status} {name}: "
          f"Tan={tan} Pharma={pharma}/4 "
          f"VS={vs_score} → {rec['vs_pass']}")

out_df = pd.DataFrame(records)

pass_df = out_df[out_df["vs_pass"] == "PASS"]
ref_df  = out_df[out_df["name"].str.contains(
    "ref", case=False, na=False)]
out_df  = pd.concat(
    [pass_df, ref_df]).drop_duplicates(
    subset=["name"])
out_df  = out_df.sort_values(
    "vs_score", ascending=False)
out_df.to_csv(out_csv, index=False)

total  = len(records)
passed = len(out_df)

print("\n" + "=" * 45)
print("VIRTUAL SCREENING SUMMARY")
print("=" * 45)
print(f"Total input:          {total}")
print(f"Passed (Tan>={threshold}):   {passed}")
print(f"Failed:               {total-passed}")
print(f"Pass rate:            "
      f"{round(100*passed/max(total,1),1)}%")

if len(out_df) > 0:
    print("\nTop 5 by VS score:")
    for _, r in out_df.head(5).iterrows():
        print(f"  {r['name']}: "
              f"VS={r['vs_score']} "
              f"Tan={r['tanimoto_vs']}")

print("\nStep 6 complete")
