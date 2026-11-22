from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors, QED
import pandas as pd
import numpy as np
import os

out_csv  = snakemake.output[0]
in_csv   = snakemake.input[0]
os.makedirs(os.path.dirname(out_csv), exist_ok=True)

ref_ic50 = snakemake.config.get("reference_ic50_nm", 89)
ref_name = snakemake.config.get("reference_name", "Reference")

df = pd.read_csv(in_csv)

print("=" * 45)
print("STEP 5: ADMET STAGE 1 — FREE MOLECULE")
print("=" * 45)
print(f"Input analogues: {len(df)}")

records = []

for _, row in df.iterrows():
    smi  = str(row["smiles"])
    name = str(row["name"])
    mol  = Chem.MolFromSmiles(smi)

    if mol is None:
        print(f"  SKIP {name}: invalid SMILES")
        continue

    # ── BASIC DESCRIPTORS ─────────────────
    mw   = round(Descriptors.MolWt(mol), 1)
    logp = round(Descriptors.MolLogP(mol), 2)
    hbd  = rdMolDescriptors.CalcNumHBD(mol)
    hba  = rdMolDescriptors.CalcNumHBA(mol)
    tpsa = round(Descriptors.TPSA(mol), 1)
    rot  = rdMolDescriptors.CalcNumRotatableBonds(mol)
    arom = rdMolDescriptors.CalcNumAromaticRings(mol)
    qed  = round(QED.qed(mol), 3)
    mw_exact = round(Descriptors.ExactMolWt(mol), 4)

    # ── LIPINSKI Ro5 ──────────────────────
    lip_pass = (mw <= 500 and logp <= 5
                and hbd <= 5 and hba <= 10)
    lipinski = "PASS" if lip_pass else "FAIL"

    # ── VEBER RULE ────────────────────────
    veber = "PASS" if (tpsa <= 140
                       and rot <= 10) else "FAIL"

    # ── BBB PENETRATION ───────────────────
    bbb_score = 0
    if 1.0 <= logp <= 3.5:   bbb_score += 2
    elif logp < 5:            bbb_score += 1
    if tpsa < 60:             bbb_score += 2
    elif tpsa < 90:           bbb_score += 1
    if mw < 400:              bbb_score += 2
    elif mw < 450:            bbb_score += 1
    if hbd <= 2:              bbb_score += 1
    if hba <= 5:              bbb_score += 1

    if bbb_score >= 6:        bbb = "High"
    elif bbb_score >= 3:      bbb = "Medium"
    else:                     bbb = "Low"

    # ── GI ABSORPTION ─────────────────────
    gi = "High" if tpsa <= 140 else "Low"

    # ── CNS READINESS ─────────────────────
    cns_ready = (bbb == "High" and
                 mw <= 450 and
                 logp <= 4 and
                 hbd <= 3)
    cns = "YES" if cns_ready else "NO"

    # ── BLEEDING RISK (P2Y12 specific) ────
    bleed_flags = 0
    if logp > 3.5:    bleed_flags += 1
    if tpsa < 75:     bleed_flags += 1
    if hba < 4:       bleed_flags += 1
    if mw < 350:      bleed_flags += 1

    if bleed_flags <= 1:   bleeding = "LOW"
    elif bleed_flags == 2: bleeding = "MEDIUM"
    else:                  bleeding = "HIGH"

    # ── SOLUBILITY (ESOL) ─────────────────
    esol = round(0.16 - 0.63 * logp
                 - 0.0062 * mw
                 + 0.066 * hba
                 - 0.74, 2)
    if esol >= -2:        solubility = "High"
    elif esol >= -4:      solubility = "Medium"
    else:                 solubility = "Low"

    # ── HEPATOTOXICITY FLAG ───────────────
    hepatotox = "Flag" if (logp > 4.5
                           and mw > 400) else "OK"

    # ── hERG FLAG ─────────────────────────
    herg = "Flag" if (logp > 3.0
                      and arom >= 2) else "OK"

    # ── PAINS FILTER ─────────────────────
    from rdkit.Chem.FilterCatalog import (
        FilterCatalog, FilterCatalogParams)
    params = FilterCatalogParams()
    params.AddCatalog(
        FilterCatalogParams.FilterCatalogs.PAINS)
    catalog = FilterCatalog(params)
    pains = "Flag" if catalog.HasMatch(mol) else "OK"

    # ── OVERALL PASS/FAIL ─────────────────
    overall = ("PASS" if
               lip_pass and
               veber == "PASS" and
               solubility != "Low" and
               hepatotox == "OK"
               else "FAIL")

    rec = {
        "name":           name,
        "smiles":         smi,
        "MW":             mw,
        "ExactMW":        mw_exact,
        "logP":           logp,
        "HBD":            hbd,
        "HBA":            hba,
        "TPSA":           tpsa,
        "RotBonds":       rot,
        "AromaticRings":  arom,
        "QED":            qed,
        "Lipinski":       lipinski,
        "Veber":          veber,
        "BBB":            bbb,
        "BBB_score":      bbb_score,
        "GI_absorption":  gi,
        "CNS_ready":      cns,
        "Bleeding_risk":  bleeding,
        "Solubility":     solubility,
        "ESOL_logS":      esol,
        "Hepatotox":      hepatotox,
        "hERG":           herg,
        "PAINS":          pains,
        "Overall_ADMET":  overall,
    }

    # carry over IC50 prediction if available
    for col in ["predicted_ic50_nm",
                "vs_ref_ic50",
                "ref_ic50_nm"]:
        if col in row:
            rec[col] = row[col]

    records.append(rec)
    status = "✓" if overall == "PASS" else "✗"
    print(f"  {status} {name}: BBB={bbb} "
          f"Bleed={bleeding} QED={qed} "
          f"Overall={overall}")

out_df = pd.DataFrame(records)
out_df.to_csv(out_csv, index=False)

# ── SUMMARY ───────────────────────────────
print("\n" + "=" * 45)
print("ADMET STAGE 1 SUMMARY")
print("=" * 45)
print(f"Total:          {len(out_df)}")
print(f"Overall PASS:   {(out_df['Overall_ADMET']=='PASS').sum()}")
print(f"BBB High:       {(out_df['BBB']=='High').sum()}")
print(f"BBB Medium:     {(out_df['BBB']=='Medium').sum()}")
print(f"Bleeding LOW:   {(out_df['Bleeding_risk']=='LOW').sum()}")
print(f"Bleeding HIGH:  {(out_df['Bleeding_risk']=='HIGH').sum()}")
print(f"CNS Ready:      {(out_df['CNS_ready']=='YES').sum()}")
print(f"hERG Flag:      {(out_df['hERG']=='Flag').sum()}")
print(f"PAINS Flag:     {(out_df['PAINS']=='Flag').sum()}")
print("\nStep 5 complete")
