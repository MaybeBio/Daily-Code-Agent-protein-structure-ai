import pandas as pd
import numpy as np
import pickle
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

out_csv  = snakemake.output[0]
out_plot = snakemake.output[1]
os.makedirs(os.path.dirname(out_csv), exist_ok=True)

dock_csv  = snakemake.input[0]
admet2_csv= snakemake.input[1]
md_csv    = snakemake.input[2]
ml_pkl    = snakemake.input[3]
admet1_csv= snakemake.input[4]
ml_csv    = snakemake.input[5]

ref_ic50  = snakemake.config.get("reference_ic50_nm", 89)
ref_name  = snakemake.config.get("reference_name", "Reference")
ref_src   = snakemake.config.get("reference_source", "")

print("=" * 45)
print("STEP 10: FINAL RANKING")
print("=" * 45)

dock_df   = pd.read_csv(dock_csv)
admet2_df = pd.read_csv(admet2_csv)
admet1_df = pd.read_csv(admet1_csv)
md_df     = pd.read_csv(md_csv)

# Fix docking None
dock_df['docking_score'] = pd.to_numeric(
    dock_df['docking_score'], errors='coerce'
).fillna(-6.0)

try:
    ml_scores = pickle.load(open(ml_pkl, "rb"))
    if isinstance(ml_scores, pd.DataFrame):
        ml_map  = dict(zip(ml_scores["name"], ml_scores["ml_score"]))
        ic50_map= dict(zip(ml_scores["name"], ml_scores.get("predicted_ic50_nm", pd.Series([None]*len(ml_scores)))))
    else:
        ml_map, ic50_map = {}, {}
except Exception as e:
    print(f"ML load error: {e}")
    ml_map, ic50_map = {}, {}

try:
    ml_df = pd.read_csv(ml_csv)
    for _, r in ml_df.iterrows():
        ml_map[r["name"]]   = r.get("ml_score", 0.5)
        ic50_map[r["name"]] = r.get("predicted_ic50_nm", None)
except Exception as e:
    print(f"ML CSV error: {e}")

df = dock_df.copy()

for col in ["BBB","Bleeding_risk","CNS_ready","QED","Overall_ADMET","hERG","PAINS"]:
    if col in admet1_df.columns:
        df = df.merge(admet1_df[["name", col]], on="name", how="left", suffixes=("","_a1"))

for col in ["LigandEfficiency","LipophilicEfficiency","Binding_stability","BBB_complex","Bleeding_risk"]:
    if col in admet2_df.columns:
        df = df.merge(admet2_df[["name", col]], on="name", how="left", suffixes=("","_a2"))

md_cols = [c for c in ["name","energy_kcal","rmsd","md_stable","md_time_ns"] if c in md_df.columns]
df = df.merge(md_df[md_cols], on="name", how="left")

# Add RMSD column if missing
if 'rmsd' not in df.columns:
    df['rmsd'] = 'N/A'

df["ml_score"]           = df["name"].map(ml_map).fillna(0.5)
df["predicted_ic50_nm"]  = df["name"].map(ic50_map)
df["qed_score"]          = df["name"].map(dict(zip(admet1_df["name"], admet1_df.get("QED", pd.Series([0.5]*len(admet1_df)))))).fillna(0.5)

dmin = df["docking_score"].min()
dmax = df["docking_score"].max()
df["dock_norm"] = (dmin - df["docking_score"]) / (dmin - dmax + 1e-9)

df["bbb_score"]   = df.get("BBB_complex", df.get("BBB","")).apply(lambda x: 1.0 if x=="High" else 0.5 if x=="Medium" else 0.0)
bleed_col         = "Bleeding_risk_a2" if "Bleeding_risk_a2" in df.columns else "Bleeding_risk"
df["bleed_score"] = df[bleed_col].apply(lambda x: 1.0 if x=="LOW" else 0.5 if x=="MEDIUM" else 0.0)
df["md_score"]    = df["md_stable"].apply(lambda x: 1.0 if x=="Yes" else 0.5 if pd.isna(x) else 0.0)

df["composite"] = (
    0.25 * df["ml_score"]    +
    0.25 * df["dock_norm"]   +
    0.15 * df["bbb_score"]   +
    0.15 * df["bleed_score"] +
    0.10 * df["md_score"]    +
    0.10 * df["qed_score"]
).clip(0, 1)

df.loc[df[bleed_col]=="HIGH", "composite"] -= 0.2
df = df.sort_values("composite", ascending=False)
df["rank"] = range(1, len(df)+1)

ref_row  = df[df["name"].str.contains("ref", case=False, na=False)]
ref_dock = ref_row["docking_score"].values[0] if len(ref_row) > 0 else None
ref_ml   = ref_row["ml_score"].values[0]      if len(ref_row) > 0 else None
ref_comp = ref_row["composite"].values[0]     if len(ref_row) > 0 else None

df["better_than_ref_dock"]  = df["docking_score"].apply(lambda x: "Yes" if ref_dock and x < ref_dock else "No")
df["better_than_ref_ml"]    = df["ml_score"].apply(lambda x: "Yes" if ref_ml and x > ref_ml else "No")
df["better_than_ref_ic50"]  = df["predicted_ic50_nm"].apply(lambda x: "Yes" if x and ref_ic50 > 0 and x < ref_ic50 else "No" if x and ref_ic50 > 0 else "Unknown")
df["reference_ic50_nm"]     = ref_ic50
df["reference_name"]        = ref_name

df.to_csv(out_csv, index=False)

print("\nFINAL RANKING:")
for _, r in df.iterrows():
    rmsd_str = f" RMSD={r['rmsd']}" if pd.notna(r.get("rmsd")) and r.get("rmsd") != "N/A" else ""
    print(f"  Rank {int(r['rank'])}: {r['name']} Score={round(r['composite'],3)} Dock={r['docking_score']}{rmsd_str}")

fig, axes = plt.subplots(2, 2, figsize=(14,10))
top = df.head(10)
axes[0,0].barh(top["name"], top["ml_score"], color="steelblue")
if ref_ml: axes[0,0].axvline(x=ref_ml, color="red", linestyle="--", label=f"{ref_name} ref")
axes[0,0].set_title("ML Activity Score"); axes[0,0].legend()

axes[0,1].barh(top["name"], top["docking_score"], color="coral")
if ref_dock: axes[0,1].axvline(x=ref_dock, color="red", linestyle="--", label=f"{ref_name} ref")
axes[0,1].set_title("Docking Score (kcal/mol)"); axes[0,1].legend()

axes[1,0].barh(top["name"], top["predicted_ic50_nm"].fillna(0), color="purple")
axes[1,0].axvline(x=ref_ic50, color="red", linestyle="--", label=f"{ref_name} {ref_ic50}nM")
axes[1,0].set_title("Predicted IC50 (nM) — lower=better"); axes[1,0].legend()

axes[1,1].barh(top["name"], top["composite"], color="green")
if ref_comp: axes[1,1].axvline(x=ref_comp, color="red", linestyle="--", label=f"{ref_name} ref")
axes[1,1].set_title("Final Composite Score"); axes[1,1].legend()

plt.suptitle(f"AutoAnalog v2.0 — Final Ranking\nReference: {ref_name} IC50={ref_ic50}nM ({ref_src})", fontsize=11)
plt.tight_layout()
plt.savefig(out_plot, dpi=150, bbox_inches="tight")
plt.close()
print("Step 10 complete")
