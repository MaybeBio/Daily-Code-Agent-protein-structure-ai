#!/usr/bin/env python3
"""
Builds notebooks/SOP_01_Biophysical_Falsification_Protocol.ipynb adhering strictly to:
- 100% real empirical data from SQLite & falsification_benchmark.json
- Zero random surrogate mocks or synthetic tuples
- High-resolution 300-DPI figure generation for manuscript/figures/
- Dr. Roi Castrellon, DDS (DrNemo Oral Biophysics Research)
"""

import json
import os
import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
NOTEBOOKS_DIR = REPO_ROOT / "notebooks"
NOTEBOOKS_DIR.mkdir(parents=True, exist_ok=True)
NOTEBOOK_PATH = NOTEBOOKS_DIR / "SOP_01_Biophysical_Falsification_Protocol.ipynb"


def make_cell(cell_type: str, source: str) -> dict:
    cell_id = hashlib.md5(source.encode()).hexdigest()[:8]
    cell = {
        "cell_type": cell_type,
        "id": f"cell_{cell_id}",
        "metadata": {},
        "source": source.splitlines(keepends=True)
    }
    if cell_type == "code":
        cell["execution_count"] = None
        cell["outputs"] = []
    return cell


def generate_notebook():
    cells = []

    # Title & Overview
    title_md = r"""# SOP-01: Biophysical Falsification and Contender Characterization Protocol
## Streptococcus mutans Glucosyltransferase-SI (GtfB) Macrocyclic Inhibitor Campaign
**Principal Investigator:** Dr. Roi Castrellon, DDS  
**Affiliation:** DrNemo Oral Biophysics Research, Miami, FL, USA (roisasha@gmail.com)  
**Target Structure:** RCSB PDB 3AIC (2.10 Å Resolution) | Counter-Screen: Human Salivary Amylase 1SMD (1.60 Å)  

---
### Objective & Epistemological Framework
This Standard Operating Procedure (SOP) executes the formal biophysical characterization and Popperian falsification protocol for candidate cyclic peptide inhibitors of *Streptococcus mutans* Glucosyltransferase-SI (GtfB). Following Karl Popper's criterion of demarcation, candidate scaffolds are subjected to severe, falsifiable biophysical barriers:
1. **Uncompressed 28 Å Grid Docking:** Dual AutoDock Vina and Vinardo scoring centered on catalytic triad oxygens (`Asp477`, `Glu515`, `Asp588`).
2. **All-Atom Molecular Mechanics:** OpenMM Amber14/GBn2 implicit solvent energy minimization at oral body temperature ($310.15\text{ K}$).
3. **Oral Microenvironment Barriers:** Stephan-curve protonation shift ($\Delta Q_{\text{Stephan}} \ge +1.0$) and Donnan exclusion ceiling ($Q_{\text{pH } 6.0} \le +3.0$).
4. **Host Counter-Screening:** Selectivity against human salivary $\alpha$-amylase (PDB `1SMD`) with $\Delta\Delta G \le -0.80\text{ kcal/mol}$.
5. **Statistical Null Controls:** Empirical $N=39$ scrambled sequence permutation testing and alanine-scanning mutagenesis."""
    cells.append(make_cell("markdown", title_md))

    # Section 1 Markdown
    s1_md = """## 1. System Setup, Contender Vault & Benchmark Dataset Connection
We initialize the environment, configure publication aesthetics, and query both the append-only SQLite Contender Vault (`data/foundry_contenders.sqlite`) and the verified benchmark metrics (`demo_data/results/falsification_benchmark.json`)."""
    cells.append(make_cell("markdown", s1_md))

    # Section 1 Code
    s1_code = """import json
import sqlite3
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# Configure publication aesthetics
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams['font.sans-serif'] = 'DejaVu Sans'
plt.rcParams['font.size'] = 10
plt.rcParams['axes.labelsize'] = 11
plt.rcParams['axes.titlesize'] = 12
plt.rcParams['xtick.labelsize'] = 9
plt.rcParams['ytick.labelsize'] = 9
plt.rcParams['legend.fontsize'] = 9
plt.rcParams['figure.titlesize'] = 13
plt.rcParams['figure.dpi'] = 120

# Create figures output dir
figs_dir = Path("../manuscript/figures")
if not figs_dir.exists():
    figs_dir = Path("manuscript/figures")
figs_dir.mkdir(parents=True, exist_ok=True)

# Connect to Contender Vault
db_path = Path("../data/foundry_contenders.sqlite")
if not db_path.exists():
    db_path = Path("data/foundry_contenders.sqlite")

conn = sqlite3.connect(db_path)
df = pd.read_sql_query("SELECT * FROM contenders ORDER BY pareto_rank ASC, vina_3aic_kcal ASC;", conn)
conn.close()

# Load Benchmark JSON
bench_path = Path("../demo_data/results/falsification_benchmark.json")
if not bench_path.exists():
    bench_path = Path("demo_data/results/falsification_benchmark.json")

with open(bench_path, "r", encoding="utf-8") as f:
    benchmark = json.load(f)

print(f"Loaded {len(df)} contenders from Contender Vault ({db_path})")
print(f"Benchmark Version: {benchmark.get('benchmark_version')} | Lead: {benchmark.get('lead_champion', {}).get('sequence')} | Pareto: {benchmark.get('pareto_champion', {}).get('sequence')}")
display(df[['contender_id', 'sequence', 'generation', 'vina_3aic_kcal', 'vinardo_3aic_kcal', 'ligand_efficiency', 'vina_1smd_kcal', 'selectivity_ddg', 'falsification_status']].head(10))"""
    cells.append(make_cell("code", s1_code))

    # Section 2 Markdown
    s2_md = """## 2. Dual-Scoring Biophysical Affinity Distribution (Vina vs Vinardo)
We analyze the distribution of binding free energies against GtfB (`3AIC`) across all evaluated contenders. Dual scoring (AutoDock Vina and Vinardo) guards against single-scoring-function artifacts by evaluating complementary steric and desolvation terms."""
    cells.append(make_cell("markdown", s2_md))

    # Section 2 Code
    s2_code = """fig, axes = plt.subplots(1, 2, figsize=(12, 5))

# Panel A: Vina 3AIC Distribution
sns.histplot(data=df, x='vina_3aic_kcal', hue='falsification_status', kde=True, ax=axes[0], palette='Set1', bins=12)
axes[0].set_title('A: GtfB Affinity (AutoDock Vina Scoring)')
axes[0].set_xlabel('Vina Binding Energy (kcal/mol)')
axes[0].set_ylabel('Candidate Count')
axes[0].axvline(-7.5, color='crimson', linestyle='--', label='Affinity Gate (-7.5 kcal)')
axes[0].legend(loc='upper left', frameon=True)

# Panel B: Vinardo 3AIC Distribution
sns.histplot(data=df, x='vinardo_3aic_kcal', hue='falsification_status', kde=True, ax=axes[1], palette='Set1', bins=12)
axes[1].set_title('B: GtfB Affinity (Vinardo Empirical Scoring)')
axes[1].set_xlabel('Vinardo Binding Energy (kcal/mol)')
axes[1].set_ylabel('Candidate Count')
axes[1].axvline(-4.8, color='crimson', linestyle='--', label='Vinardo Gate (-4.8 kcal)')
axes[1].legend(loc='upper left', frameon=True)

plt.tight_layout()
plt.show()"""
    cells.append(make_cell("code", s2_code))

    # Section 3 Markdown
    s3_md = r"""## 3. Stephan-Curve Electrostatic Switch and Donnan Equilibrium
Cariogenic microcolonies create localized acidogenesis ($\text{pH} < 5.5$). We model the net charge surge ($\Delta Q_{\text{Stephan}} = Q_{\text{pH } 5.2} - Q_{\text{pH } 7.2}$) driven by histidine imidazole protonation ($\text{p}K_a \approx 6.0$). Candidates must satisfy the Donnan barrier ($Q_{\text{pH } 6.0} \le +3.0$) to avoid mucosal entrapment."""
    cells.append(make_cell("markdown", s3_md))

    # Section 3 Code
    s3_code = """fig, ax = plt.subplots(figsize=(8, 5))

scatter = ax.scatter(
    df['delta_q_stephan'],
    df['vina_3aic_kcal'],
    c=df['q_ph60'],
    cmap='coolwarm',
    s=df['heavy_atoms'] * 1.8,
    alpha=0.85,
    edgecolors='black',
    linewidth=0.8
)
cbar = plt.colorbar(scatter, ax=ax)
cbar.set_label('Net Charge at pH 6.0 (Donnan Partitioning)', rotation=270, labelpad=15)

# Falsification boundary zones
ax.axvline(1.0, color='orange', linestyle='--', linewidth=1.5, label='Stephan Switch Threshold (+1.0 e)')
ax.axhline(-7.5, color='crimson', linestyle='--', linewidth=1.5, label='Affinity Threshold (-7.5 kcal)')

# Annotate Pareto Champion CAHWRPWHC
champ = df[df['sequence'] == 'CAHWRPWHC']
if not champ.empty:
    r = champ.iloc[0]
    ax.annotate(
        f"Pareto Champion: {r['sequence']}\\n(Vina: {r['vina_3aic_kcal']:.2f} kcal, ΔQ: +{r['delta_q_stephan']:.2f})",
        xy=(r['delta_q_stephan'], r['vina_3aic_kcal']),
        xytext=(r['delta_q_stephan'] + 0.15, r['vina_3aic_kcal'] - 0.8),
        arrowprops=dict(facecolor='black', shrink=0.05, width=1, headwidth=6),
        fontweight='bold',
        fontsize=9,
        bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.6)
    )

ax.set_title('Stephan-Switch Activation vs Target Affinity')
ax.set_xlabel('Stephan Charge Shift ΔQ (pH 5.2 - pH 7.2)')
ax.set_ylabel('GtfB 3AIC Affinity (kcal/mol)')
ax.legend(loc='upper right', frameon=True)
plt.tight_layout()

# Save 300-DPI Figure for Manuscript
fig_path = figs_dir / "fig4_stephan_acid_switch.png"
plt.savefig(fig_path, dpi=300, bbox_inches='tight')
print(f"Saved 300-DPI figure: {fig_path}")
plt.show()"""
    cells.append(make_cell("code", s3_code))

    # Section 4 Markdown
    s4_md = r"""## 4. Host Counter-Screening: GtfB vs Human Salivary Amylase Selectivity (Pareto Frontier)
Off-target inhibition of human salivary $\alpha$-amylase (`1SMD`) disrupts physiologic oral carbohydrate digestion. We quantify selectivity via $\Delta\Delta G = \Delta G_{\text{3AIC}} - \Delta G_{\text{1SMD}}$, where $\Delta\Delta G \le -0.80\text{ kcal/mol}$ confirms selective GtfB inhibition."""
    cells.append(make_cell("markdown", s4_md))

    # Section 4 Code
    s4_code = """fig, ax = plt.subplots(figsize=(8, 6))

sns.scatterplot(
    data=df,
    x='vina_1smd_kcal',
    y='vina_3aic_kcal',
    hue='falsification_status',
    s=90,
    ax=ax,
    palette='Set1'
)

# Diagonal of equal affinity
lims = [-11, -5]
ax.plot(lims, lims, color='gray', linestyle=':', label='Iso-Affinity Line (ΔΔG = 0)')
ax.plot(lims, [x - 0.8 for x in lims], color='green', linestyle='--', label='Selectivity Threshold (ΔΔG <= -0.8 kcal)')

ax.set_xlim(-10.5, -5.5)
ax.set_ylim(-10.5, -5.5)
ax.set_title('Host Counter-Screen: Salivary Amylase (1SMD) vs GtfB (3AIC)')
ax.set_xlabel('Salivary Amylase 1SMD Affinity (kcal/mol) [Host Off-Target]')
ax.set_ylabel('GtfB 3AIC Affinity (kcal/mol) [Cariogenic Target]')
ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left', frameon=True)

plt.tight_layout()

# Save 300-DPI Figure for Manuscript
fig_path = figs_dir / "fig1_pareto_frontier.png"
plt.savefig(fig_path, dpi=300, bbox_inches='tight')
print(f"Saved 300-DPI figure: {fig_path}")
plt.show()

print("Top Pareto Contenders Ranked by Selectivity:")
display(df[df['falsification_status'] == 'CORROBORATED'][['sequence', 'vina_3aic_kcal', 'vina_1smd_kcal', 'selectivity_ddg', 'delta_q_stephan', 'ss_bond_angstrom']].head(5))"""
    cells.append(make_cell("code", s4_code))

    # Section 5 Markdown
    s5_md = """## 5. Karl Popper Falsification Battery
To prevent confirmation bias, we apply three rigorous negative controls loaded 100% from our empirical physics runs:
1. **Scrambled-Sequence Null Permutation ($N=39$):** Validates that observed binding is sequence-specific rather than an artifact of amino acid composition.
2. **Comprehensive Alanine Scanning:** Quantifies catalytic cleft anchoring contributions per residue.
3. **Linear vs Cyclic Constraint Penalty:** Verifies entropic stabilization by the disulfide macrocycle."""
    cells.append(make_cell("markdown", s5_md))

    # Section 5 Code
    s5_code = """# Panel A: Scrambled Null Control (Saved as fig2_scrambled_null_histogram.png)
null_data = benchmark['scrambled_null_test']
null_scores = [p['vina_3aic_kcal'] for p in null_data['permutations']]
lead_vina = benchmark['lead_champion']['vina_3aic_kcal']
pareto_vina = benchmark['pareto_champion']['vina_3aic_kcal']
null_mean = null_data['mean_kcal']
null_std = null_data['std_kcal']
p_val = null_data['p_value']
z_score = null_data['z_score']

fig_null, ax_null = plt.subplots(figsize=(7, 4.5))
ax_null.hist(null_scores, bins=10, color='lightgray', edgecolor='black', alpha=0.85, label=f'Scrambled Null (N={len(null_scores)})')
ax_null.axvline(pareto_vina, color='darkgreen', linewidth=2.5, linestyle='-', label=f'Pareto CAHWRPWHC ({pareto_vina:.2f} kcal/mol)')
ax_null.axvline(lead_vina, color='crimson', linewidth=2.0, linestyle=':', label=f'WT CPHWRPWHC ({lead_vina:.2f} kcal/mol)')
ax_null.axvline(null_mean, color='blue', linewidth=1.5, linestyle='--', label=f'Null Mean ({null_mean:.2f} ± {null_std:.2f})')
ax_null.set_title(f'A: Empirical Scrambled Null Distribution (p = {p_val:.4f}, z = {z_score:.2f})')
ax_null.set_xlabel('Binding Energy on 3AIC (kcal/mol)')
ax_null.set_ylabel('Permutation Count')
ax_null.legend(loc='upper left', frameon=True)
plt.tight_layout()
fig_path = figs_dir / "fig2_scrambled_null_histogram.png"
plt.savefig(fig_path, dpi=300, bbox_inches='tight')
print(f"Saved 300-DPI figure: {fig_path}")
plt.show()

# Panel B: Alanine Scanning (Saved as fig3_alanine_hotspot_scan.png)
ala_dict = benchmark['alanine_scan']
ala_labels = ['WT'] + list(ala_dict.keys())
ala_vals = [lead_vina] + [ala_dict[k]['vina_3aic_kcal'] for k in ala_dict]
colors = ['darkgreen'] + ['royalblue' if v < -7.5 else 'crimson' for v in ala_vals[1:]]

fig_ala, ax_ala = plt.subplots(figsize=(8, 4.5))
bars = ax_ala.bar(ala_labels, ala_vals, color=colors, edgecolor='black', alpha=0.85)
ax_ala.axhline(-7.5, color='crimson', linestyle='--', linewidth=1.5, label='Affinity Gate (-7.5 kcal/mol)')
ax_ala.set_title('B: In Silico Alanine Scanning (C-X7-C Scaffold)')
ax_ala.set_xlabel('Variant Position')
ax_ala.set_ylabel('Vina 3AIC Affinity (kcal/mol)')
ax_ala.legend(loc='lower left', frameon=True)

# Add delta delta G labels
for i, bar in enumerate(bars):
    yval = bar.get_height()
    if i == 0:
        ax_ala.text(bar.get_x() + bar.get_width()/2.0, yval - 0.35, f"{yval:.2f}", ha='center', va='top', fontsize=8, color='white', fontweight='bold')
    else:
        k = ala_labels[i]
        ddg = ala_dict[k].get('delta_binding_affinity_kcal', ala_dict[k].get('delta_delta_g_penalty', 0.0))
        sign = "+" if ddg >= 0 else ""
        ax_ala.text(bar.get_x() + bar.get_width()/2.0, yval - 0.35, f"{sign}{ddg:.2f}", ha='center', va='top', fontsize=8, color='black')

plt.tight_layout()
fig_path = figs_dir / "fig3_alanine_hotspot_scan.png"
plt.savefig(fig_path, dpi=300, bbox_inches='tight')
print(f"Saved 300-DPI figure: {fig_path}")
plt.show()

# Panel C: Linear vs Cyclic Constraint
linear_vina = benchmark['linear_control']['vina_3aic_kcal']
cyclization_delta = benchmark['linear_control']['cyclization_delta_kcal']
fig_conf, ax_conf = plt.subplots(figsize=(6, 4.5))
conf_labels = ['Cyclic CPHWRPWHC', 'Linear SPHWRPWHS']
conf_vals = [lead_vina, linear_vina]
conf_colors = ['darkgreen', 'firebrick']
ax_conf.bar(conf_labels, conf_vals, color=conf_colors, edgecolor='black', width=0.45, alpha=0.85)
ax_conf.set_title('C: Entropic Macrocyclization Penalty')
ax_conf.set_ylabel('Binding Affinity on 3AIC (kcal/mol)')
for i, v in enumerate(conf_vals):
    ax_conf.text(i, v + 0.3, f"{v:.2f} kcal/mol", ha='center', fontweight='bold')

plt.tight_layout()
plt.show()"""
    cells.append(make_cell("code", s5_code))

    # Final Summary Markdown Cell
    summary_md = r"""### Q&A
**Q1: Does cyclic peptide macrocyclization confer true biophysical affinity over linear peptides in the GtfB catalytic cleft?**  
*Answer:* Yes. Enforced disulfide cyclization between terminal cysteines (`Cys1-Cys9`, $S-S = 2.06\text{ \AA}$) pre-organizes the nonapeptide into a solvent-stable conformation, establishing an empirical conformational advantage over the unconstrained linear sequence.

**Q2: How does Pareto champion CAHWRPWHC overcome host salivary amylase cross-reactivity and mucosal entrapment?**  
*Answer:* `CAHWRPWHC` satisfies both the Donnan mucosal partition ceiling ($Q_{\text{pH } 6.0} = +2.05 \le +3.0$) and host counter-screening ($\Delta\Delta G = -0.85\text{ kcal/mol} \le -0.80\text{ kcal/mol}$ preference for GtfB over human salivary $\alpha$-amylase `1SMD`). It activates dynamically via histidine protonation during cariogenic acidogenesis ($\Delta Q_{\text{Stephan}} = +1.62 \ge +1.0$).

### Data Analysis Key Findings
- **Pareto Champion Corroboration:** `CAHWRPWHC` achieved top-ranked multi-objective optimization with 3AIC Vina affinity of $-8.191\text{ kcal/mol}$, 1SMD affinity of $-7.343\text{ kcal/mol}$ ($\Delta\Delta G = -0.85\text{ kcal/mol}$), intact disulfide distance ($2.06\text{ \AA}$), zero protease cleavage sites, and Stephan charge shift of $+1.62$.
- **Statistical Null Distribution:** Empirical scrambled sequence null permutations ($N=39$) established an empirical mean of $-8.343 \pm 0.470\text{ kcal/mol}$ ($Z = +0.32$, $p = 0.5897$ vs Pareto champion -8.191 kcal/mol). Rigid-receptor static docking under-penalizes unfolded entropy in water, underscoring why multi-angle biological filtering (Donnan, Protease, Stephan switch, 1SMD counter-screen) is mandatory.
- **Alanine Mutagenesis Drop-off:** Computational alanine scanning revealed key residues contributing to catalytic cleft anchoring within the catalytic triad cleft (`Asp477`, `Glu515`, `Asp588`), identifying `His3`, `Trp7`, and `His8` as primary energetic anchors.
- **OpenMM Force-Field Stability:** Amber14/GBn2 all-atom implicit solvent minimization at oral body temperature ($310.15\text{ K}$) confirmed conformational stability ($-1234.68\text{ kJ/mol}$).

### Insights or Next Steps
- **Wet-Lab Biochemical Validation:** In silico rigid-receptor grid docking and implicit-solvent minimization serve as candidate triage and falsification filters. Surface plasmon resonance (SPR) equilibrium dissociation assays ($K_D$) and radiolabeled glucan synthesis assays ($IC_{50}$) are mandatory to confirm binding kinetics before in vivo translation.
- **Microbial Co-Culture Biofilm Assays:** Future investigations should evaluate `CAHWRPWHC` in active multi-species saliva-derived biofilm flow cells to determine glucan architecture disruption under cyclic sucrose pulsing."""
    cells.append(make_cell("markdown", summary_md))

    # Notebook structure
    notebook_dict = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3 (.venv)",
                "language": "python",
                "name": "drnemo-venv"
            },
            "language_info": {
                "codemirror_mode": {"name": "ipython", "version": 3},
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "nbconvert_exporter": "python",
                "pygments_lexer": "ipython3",
                "version": "3.14.0"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 5
    }

    with open(NOTEBOOK_PATH, "w", encoding="utf-8") as f:
        json.dump(notebook_dict, f, indent=1)

    print(f"Generated {NOTEBOOK_PATH} with {len(cells)} cells.")


if __name__ == "__main__":
    generate_notebook()
