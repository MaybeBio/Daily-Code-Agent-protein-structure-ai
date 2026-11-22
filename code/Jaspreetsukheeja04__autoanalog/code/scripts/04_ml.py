from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator
import pandas as pd
import numpy as np
import pickle
import os
import warnings
warnings.filterwarnings("ignore")

out_pkl  = snakemake.output[0]
out_csv  = snakemake.output[1]
os.makedirs(os.path.dirname(out_pkl), exist_ok=True)

known_inh = snakemake.config.get("known_inhibitor","")
ref_ic50  = snakemake.config.get("reference_ic50_nm", 89)
ref_name  = snakemake.config.get("reference_name","Reference")

ana_df = pd.read_csv(snakemake.input[0])

mfpgen = rdFingerprintGenerator.GetMorganGenerator(
    radius=2, fpSize=2048)

print("=" * 45)
print("STEP 4: ML ACTIVITY PREDICTION")
print("=" * 45)

P2Y12_ACTIVES = [
    "CC1=CC=C(C=C1)S(=O)(=O)NC2=NC=C(C=N2)C3=CC=CC=N3",
    "CC1=CC=C(C=C1F)S(=O)(=O)NC2=NC=C(C=N2)C3=CC=CC=N3",
    "c1ccc2c(c1)cc(c(=O)n2)N3CCNCC3",
    "CC(=O)Nc1ccc(cc1)S(=O)(=O)Nc2nccs2",
    "O=C(Nc1ccc(F)cc1)c1ccncc1",
]

def sanitize(smi):
    try:
        mol = Chem.MolFromSmiles(smi)
        if mol:
            Chem.SanitizeMol(mol)
        return mol
    except Exception:
        return None

def get_tanimoto_score(smiles):
    try:
        mol = sanitize(smiles)
        if mol is None:
            return 0.0
        fp = mfpgen.GetFingerprint(mol)
        scores = []
        for ref_smi in P2Y12_ACTIVES:
            ref_mol = sanitize(ref_smi)
            if ref_mol:
                ref_fp = mfpgen.GetFingerprint(ref_mol)
                scores.append(
                    DataStructs.TanimotoSimilarity(
                        fp, ref_fp))
        return round(max(scores), 3) \
            if scores else 0.0
    except Exception:
        return 0.0

def get_chemberta_score(smiles):
    try:
        import logging
        logging.getLogger(
            "transformers").setLevel(
            logging.ERROR)
        from transformers import (
            AutoTokenizer, AutoModel)
        import torch

        tokenizer = AutoTokenizer.from_pretrained(
            "seyonec/ChemBERTa-zinc-base-v1")
        model = AutoModel.from_pretrained(
            "seyonec/ChemBERTa-zinc-base-v1",
            ignore_mismatched_sizes=True)
        model.eval()

        def embed(smi):
            inputs = tokenizer(
                smi,
                return_tensors="pt",
                truncation=True,
                max_length=512,
                padding=True)
            with torch.no_grad():
                out = model(**inputs)
            return out.last_hidden_state[:,0,:]

        ref_emb = embed(known_inh)
        smi_emb = embed(smiles)
        cos = torch.nn.functional\
            .cosine_similarity(ref_emb, smi_emb)
        return round(float((cos.item()+1)/2), 3)
    except Exception as e:
        print(f"  ChemBERTa error: {e}")
        return 0.5

def predict_ic50(ml_score):
    if ml_score <= 0:
        return None
    return round(ref_ic50 / max(ml_score, 0.01), 1)

print(f"Scoring {len(ana_df)} analogues...")
print("Loading ChemBERTa model...")

records = []
for i, row in ana_df.iterrows():
    smi  = str(row["smiles"])
    name = str(row["name"])
    print(f"  [{i+1}/{len(ana_df)}] {name}...")

    tan   = get_tanimoto_score(smi)
    chbrt = get_chemberta_score(smi)
    ml    = round(0.5*chbrt + 0.5*tan, 3)
    ic50  = predict_ic50(ml)

    vs_ref = ""
    if ic50 and ref_ic50 > 0:
        vs_ref = "Better" if ic50 < ref_ic50 \
            else "Equal" if ic50 == ref_ic50 \
            else "Worse"

    records.append({
        "name":              name,
        "smiles":            smi,
        "tanimoto":          tan,
        "chemberta":         chbrt,
        "ml_score":          ml,
        "predicted_ic50_nm": ic50,
        "vs_ref_ic50":       vs_ref,
        "ref_ic50_nm":       ref_ic50,
    })
    print(f"    Tan={tan} ChemBERTa={chbrt} "
          f"ML={ml} IC50~{ic50}nM {vs_ref}")

scores_df = pd.DataFrame(records)
scores_df.to_csv(out_csv, index=False)
pickle.dump(scores_df, open(out_pkl, "wb"))

print("\n" + "=" * 45)
print("ML SCORING SUMMARY")
print("=" * 45)
print(f"Total scored:         {len(scores_df)}")
print(f"ML score > 0.8:       "
      f"{(scores_df['ml_score']>0.8).sum()}")
print(f"ML score 0.5-0.8:     "
      f"{((scores_df['ml_score']>=0.5) & (scores_df['ml_score']<=0.8)).sum()}")

if ref_ic50 > 0:
    better = (scores_df[
        "predicted_ic50_nm"] < ref_ic50).sum()
    print(f"Better IC50 than ref: "
          f"{better}/{len(scores_df)}")
    print(f"Reference IC50:       {ref_ic50} nM")

print("\nTop 5 by ML score:")
for _, r in scores_df.nlargest(5,"ml_score")\
        .iterrows():
    print(f"  {r['name']}: ML={r['ml_score']} "
          f"IC50~{r['predicted_ic50_nm']}nM")

print("\nStep 4 complete")
