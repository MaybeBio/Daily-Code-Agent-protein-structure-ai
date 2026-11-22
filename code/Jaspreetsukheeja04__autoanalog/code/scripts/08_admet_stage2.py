from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors
import pandas as pd
import os

out_csv   = snakemake.output[0]
dock_csv  = snakemake.input[0]
os.makedirs(os.path.dirname(out_csv), exist_ok=True)

ref_ic50 = snakemake.config.get("reference_ic50_nm", 89)
ref_name = snakemake.config.get("reference_name", "Reference")

df = pd.read_csv(dock_csv)

print("=" * 45)
print("STEP 8: ADMET STAGE 2 — COMPLEX ADMET")
print("=" * 45)
print(f"Input compounds: {len(df)}")

records = []

for _, row in df.iterrows():
    smi  = str(row["smiles"])
    name = str(row["name"])
    mol  = Chem.MolFromSmiles(smi)

    if mol is None:
        continue

    dock = row.get("docking_score", None)

    mw   = Descriptors.MolWt(mol)
    logp = Descriptors.MolLogP(mol)
    hbd  = rdMolDescriptors.CalcNumHBD(mol)
    hba  = rdMolDescriptors.CalcNumHBA(mol)
    tpsa = Descriptors.TPSA(mol)
    heavy = mol.GetNumHeavyAtoms()

    # ── LIGAND EFFICIENCY ─────────────────
    le = round(abs(dock) / heavy, 3) \
        if dock and heavy > 0 else None

    # ── LIPOPHILIC EFFICIENCY ─────────────
    lipe = round(abs(dock) - logp, 3) \
        if dock else None

    # ── BINDING EFFICIENCY INDEX ──────────
    bei = round(abs(dock) / (mw/1000), 3) \
        if dock and mw > 0 else None

    # ── BBB RE-CHECK AFTER BINDING ────────
    bbb_score = 0
    if 1.0 <= logp <= 3.5: bbb_score += 2
    elif logp < 5:          bbb_score += 1
    if tpsa < 60:           bbb_score += 2
    elif tpsa < 90:         bbb_score += 1
    if mw < 400:            bbb_score += 2
    elif mw < 450:          bbb_score += 1
    if hbd <= 2:            bbb_score += 1

    bbb = "High" if bbb_score >= 6 else \
          "Medium" if bbb_score >= 3 else "Low"

    # ── BINDING STABILITY ─────────────────
    if dock and dock < -8.0:    stability = "High"
    elif dock and dock < -7.0:  stability = "Medium"
    elif dock and dock < -6.0:  stability = "Low"
    else:                       stability = "Very Low"

    # ── BLEEDING RISK (P2Y12) ─────────────
    bleed_flags = 0
    if logp > 3.5:   bleed_flags += 1
    if tpsa < 75:    bleed_flags += 1
    if hba < 4:      bleed_flags += 1
    if mw < 350:     bleed_flags += 1

    bleeding = "LOW" if bleed_flags <= 1 else \
               "MEDIUM" if bleed_flags == 2 else "HIGH"

    # ── COMPLEX IC50 ESTIMATE ─────────────
    pred_ic50 = row.get("predicted_ic50_nm", None)
    if dock and ref_ic50 > 0:
        ref_row = df[df["name"].str.contains(
            "ref", case=False, na=False)]
        if len(ref_row) > 0:
            ref_dock = ref_row.iloc[0].get(
                "docking_score", None)
            if ref_dock and ref_dock != 0:
                ratio = dock / ref_dock
                pred_ic50 = round(
                    ref_ic50 * ratio, 1)

    vs_ref = ""
    if pred_ic50 and ref_ic50 > 0:
        if "ref" not in name.lower():
            vs_ref = "Better" \
                if pred_ic50 < ref_ic50 \
                else "Worse"

    rec = dict(row)
    rec["LigandEfficiency"]    = le
    rec["LipophilicEfficiency"]= lipe
    rec["BindingEfficiency"]   = bei
    rec["BBB_complex"]         = bbb
    rec["Binding_stability"]   = stability
    rec["Bleeding_risk"]       = bleeding
    rec["predicted_ic50_nm"]   = pred_ic50
    rec["vs_ref_ic50"]         = vs_ref

    records.append(rec)
    print(f"  {name}: LE={le} LipE={lipe} "
          f"BBB={bbb} Stable={stability} "
          f"IC50~{pred_ic50}nM {vs_ref}")

out_df = pd.DataFrame(records)
out_df.to_csv(out_csv, index=False)

print("\n" + "=" * 45)
print("ADMET STAGE 2 SUMMARY")
print("=" * 45)
print(f"Total: {len(out_df)}")
print(f"BBB High:      {(out_df['BBB_complex']=='High').sum()}")
print(f"Stable High:   {(out_df['Binding_stability']=='High').sum()}")
print(f"Bleeding LOW:  {(out_df['Bleeding_risk']=='LOW').sum()}")

if ref_ic50 > 0:
    better = out_df[
        (out_df["predicted_ic50_nm"].notna()) &
        (out_df["predicted_ic50_nm"] < ref_ic50) &
        (~out_df["name"].str.contains(
            "ref", case=False, na=False))
    ]
    print(f"Better IC50 than {ref_name}: {len(better)}")

print("\nStep 8 complete")
