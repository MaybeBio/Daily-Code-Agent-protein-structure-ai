from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate,
    Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, HRFlowable)
import pandas as pd
import os
from datetime import datetime

out_pdf    = snakemake.output[0]
os.makedirs(os.path.dirname(out_pdf), exist_ok=True)

disease    = snakemake.config["disease"]
receptor   = snakemake.config["receptor"]
pdb_id     = snakemake.config.get("pdb_id","N/A")
ref_ic50   = snakemake.config.get("reference_ic50_nm", 89)
ref_name   = snakemake.config.get("reference_name","AZD1283")
ref_src    = snakemake.config.get("reference_source","")

lit_csv    = snakemake.input[0]
ana_png    = snakemake.input[1]
dock_csv   = snakemake.input[2]
admet1_csv = snakemake.input[3]
admet2_csv = snakemake.input[4]
md_csv     = snakemake.input[5]
rank_csv   = snakemake.input[6]
plot_png   = snakemake.input[7]

doc = SimpleDocTemplate(
    out_pdf, pagesize=A4,
    rightMargin=0.6*inch,
    leftMargin=0.6*inch,
    topMargin=0.6*inch,
    bottomMargin=0.6*inch)

styles = getSampleStyleSheet()
DARK  = colors.HexColor('#003366')
MID   = colors.HexColor('#0066CC')
LIGHT = colors.HexColor('#E8F4FD')
GOLD  = colors.HexColor('#FFD700')
GREEN = colors.HexColor('#E8F4E8')

title_s = ParagraphStyle('T',
    parent=styles['Title'],
    fontSize=18, textColor=DARK,
    spaceAfter=6)
h1_s = ParagraphStyle('H1',
    parent=styles['Heading1'],
    fontSize=13, textColor=DARK,
    spaceAfter=4, spaceBefore=8)
h2_s = ParagraphStyle('H2',
    parent=styles['Heading2'],
    fontSize=11, textColor=MID,
    spaceAfter=3, spaceBefore=5)
body_s = ParagraphStyle('B',
    parent=styles['Normal'],
    fontSize=9, spaceAfter=3, leading=12)
small_s = ParagraphStyle('S',
    parent=styles['Normal'],
    fontSize=8, spaceAfter=2,
    textColor=colors.grey)

def divider():
    return HRFlowable(
        width='100%', thickness=0.5,
        color=MID, spaceAfter=4)

def make_table(data, col_widths):
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,0), DARK),
        ('TEXTCOLOR',     (0,0),(-1,0), colors.white),
        ('FONTSIZE',      (0,0),(-1,-1), 7.5),
        ('FONTNAME',      (0,0),(-1,0), 'Helvetica-Bold'),
        ('GRID',          (0,0),(-1,-1), 0.3, colors.grey),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),
         [colors.white, LIGHT]),
        ('VALIGN',        (0,0),(-1,-1), 'TOP'),
        ('TOPPADDING',    (0,0),(-1,-1), 3),
        ('BOTTOMPADDING', (0,0),(-1,-1), 3),
    ]))
    return t

story = []

# ── COVER ────────────────────────────────
story.append(Spacer(1, 0.3*inch))
story.append(Paragraph(
    "AutoAnalog v2.0 — Computational Drug Discovery",
    title_s))
story.append(Paragraph(
    "Small Molecule Analogue Lead Compound Report",
    h1_s))
story.append(divider())

meta = [
    ['Target Receptor',    receptor],
    ['Disease Context',    disease.capitalize()],
    ['Reference PDB',      pdb_id],
    ['Reference Compound', ref_name],
    ['Published IC50',     f'{ref_ic50} nM ({ref_src})'],
    ['Generated On',
     datetime.now().strftime('%B %d, %Y %H:%M')],
    ['Pipeline', 'AutoAnalog v2.0 — Snakemake'],
]
t = Table(meta, colWidths=[2*inch, 4.5*inch])
t.setStyle(TableStyle([
    ('FONTSIZE',      (0,0),(-1,-1), 9),
    ('FONTNAME',      (0,0),(0,-1), 'Helvetica-Bold'),
    ('TEXTCOLOR',     (0,0),(0,-1), DARK),
    ('BOTTOMPADDING', (0,0),(-1,-1), 4),
    ('LINEBELOW',     (0,0),(-1,-1),
     0.3, colors.lightgrey),
]))
story.append(t)
story.append(Spacer(1, 0.2*inch))
story.append(Paragraph(
    "DISCLAIMER: All results are computational "
    "predictions only. Experimental validation "
    "required before any biological claim.",
    small_s))
story.append(PageBreak())

# ── SECTION 1: OVERVIEW ──────────────────
story.append(Paragraph(
    "1. Project Overview", h1_s))
story.append(divider())
story.append(Paragraph(
    f"AutoAnalog v2.0 targets the {receptor} "
    f"receptor for {disease}. Starting from "
    f"{ref_name} (IC50={ref_ic50} nM, {ref_src}), "
    f"the pipeline designs improved analogue lead "
    f"compounds via ML, two-stage ADMET, docking, "
    f"and MD simulation. IC50 predicted for all "
    f"analogues vs published reference.",
    body_s))

pipeline_data = [
    ['Step','Task','Tools'],
    ['1','Structure prep',
     'PDB/AlphaFold, PDBFixer, OpenBabel'],
    ['2','Literature mining',
     'PubMed, SemanticScholar, OpenAlex'],
    ['3','Analogue design',
     'RDKit BRICS + R-group permutation'],
    ['4','ML + IC50 prediction',
     'ChemBERTa + Tanimoto'],
    ['5','ADMET Stage 1',
     'RDKit, pkCSM, PAINS filter'],
    ['6','Virtual screening',
     'Tanimoto + Pharmacophore'],
    ['7','Docking',
     'AutoDock Vina + GNINA (GPU)'],
    ['8','ADMET Stage 2',
     'Complex ADMET, LE, LipE'],
    ['9','MD Simulation',
     'OpenMM 0.1ns @ 300K'],
    ['10','Final Ranking',
     'Composite + IC50 comparison'],
]
story.append(make_table(pipeline_data,
    [0.4*inch, 1.8*inch, 3.5*inch]))

# ── SECTION 2: REFERENCE ─────────────────
story.append(Spacer(1, 0.1*inch))
story.append(Paragraph(
    f"2. Reference Compound — {ref_name}", h1_s))
story.append(divider())
ref_data = [
    ['Property','Value','Source'],
    ['IC50 (P2Y12)', f'{ref_ic50} nM', ref_src],
    ['Selectivity','P2Y12 selective','Published'],
    ['Mechanism',
     'Competitive antagonist','Published'],
    ['PDB Structure', pdb_id,'RCSB PDB'],
    ['Key residues',
     'Lys174, Phe251, Tyr105',
     'Crystal structure'],
]
story.append(make_table(ref_data,
    [1.5*inch, 2.5*inch, 2.0*inch]))

# ── SECTION 3: LITERATURE ────────────────
story.append(Spacer(1, 0.1*inch))
story.append(Paragraph(
    "3. Scientific Literature Evidence", h1_s))
story.append(divider())
if os.path.exists(lit_csv):
    lit_df = pd.read_csv(lit_csv)
    story.append(Paragraph(
        f"Total papers: {len(lit_df)} from "
        f"PubMed, Semantic Scholar, "
        f"Europe PMC and OpenAlex.", body_s))
    lit_data = [['Title','Year',
                 'Journal','Citations']]
    for _, r in lit_df.head(6).iterrows():
        title = str(r.get('title',''))
        if len(title) > 55:
            title = title[:55]+'...'
        lit_data.append([
            title,
            str(r.get('year','')),
            str(r.get('journal',''))[:22],
            str(int(r.get('citations',0)))])
    story.append(make_table(lit_data,
        [3.3*inch, 0.5*inch,
         1.5*inch, 0.5*inch]))
story.append(PageBreak())

# ── SECTION 4: ANALOGUES ─────────────────
story.append(Paragraph(
    "4. Designed Analogues", h1_s))
story.append(divider())
ana_csv = lit_csv.replace(
    'literature/papers.csv',
    'analogues/descriptors.csv')
if os.path.exists(ana_csv):
    ana_df = pd.read_csv(ana_csv)
    story.append(Paragraph(
        f"{len(ana_df)} analogues designed from "
        f"{ref_name} scaffold using bioisosteric "
        f"replacement, fluorination, ring "
        f"substitution, and R-group permutation. "
        f"IC50 predicted for all candidates.",
        body_s))
    ana_data = [['Name','Modification',
                 'MW','logP','QED',
                 'Pred.IC50(nM)','Ro5']]
    for _, r in ana_df.iterrows():
        ic50_str = str(
            r.get('predicted_ic50_nm',''))
        ana_data.append([
            r['name'],
            str(r.get('modification',''))[:25],
            str(r.get('MW','')),
            str(r.get('logP','')),
            str(r.get('QED','')),
            ic50_str,
            str(r.get('Lipinski',''))])
    story.append(make_table(ana_data,
        [1.0*inch, 1.7*inch, 0.55*inch,
         0.55*inch, 0.55*inch,
         0.9*inch, 0.5*inch]))
if os.path.exists(ana_png):
    story.append(Spacer(1, 0.1*inch))
    story.append(Image(ana_png,
        width=6*inch, height=3.5*inch))

# ── SECTION 5: ML + IC50 ─────────────────
story.append(Spacer(1, 0.1*inch))
story.append(Paragraph(
    "5. ML Activity Prediction + IC50",
    h1_s))
story.append(divider())
story.append(Paragraph(
    f"ChemBERTa transformer + Tanimoto. "
    f"IC50 estimated as: "
    f"{ref_ic50} / ML_score. "
    f"Reference {ref_name} = {ref_ic50} nM.",
    body_s))
ml_csv_path = lit_csv.replace(
    'literature/papers.csv',
    'models/activity_scores.csv')
if os.path.exists(ml_csv_path):
    ml_df = pd.read_csv(ml_csv_path)
    ml_data = [['Name','Tanimoto',
                'ChemBERTa','ML Score',
                'Pred.IC50(nM)','vs Ref']]
    for _, r in ml_df.head(12).iterrows():
        ml_data.append([
            r['name'],
            str(r.get('tanimoto','')),
            str(r.get('chemberta','')),
            str(r.get('ml_score','')),
            str(r.get('predicted_ic50_nm','')),
            str(r.get('vs_ref_ic50',''))])
    story.append(make_table(ml_data,
        [1.1*inch, 0.9*inch, 0.9*inch,
         0.9*inch, 1.0*inch, 0.9*inch]))
story.append(PageBreak())

# ── SECTION 6: DOCKING ───────────────────
story.append(Paragraph(
    "6. Molecular Docking Results", h1_s))
story.append(divider())
if os.path.exists(dock_csv):
    d_df = pd.read_csv(dock_csv)
    ref_dock = d_df[
        d_df['name'].str.contains(
            'ref', case=False, na=False)][
        'docking_score'].values
    ref_dock_val = ref_dock[0] \
        if len(ref_dock) > 0 else None
    story.append(Paragraph(
        f"AutoDock Vina v1.2.5. "
        f"{ref_name} reference: "
        f"IC50={ref_ic50}nM, "
        f"Docking={ref_dock_val} kcal/mol.",
        body_s))
    dock_data = [['Rank','Compound',
                  'Score(kcal/mol)',
                  'vs Reference',
                  'Pred.IC50(nM)']]
    for i,(_, r) in enumerate(
            d_df.sort_values(
            'docking_score').iterrows(), 1):
        vs = ''
        if ref_dock_val and r['docking_score']:
            diff = r['docking_score'] - \
                   ref_dock_val
            vs = f"{diff:+.3f}"
        dock_data.append([
            str(i), r['name'],
            str(r['docking_score']), vs,
            str(r.get('predicted_ic50_nm',''))])
    story.append(make_table(dock_data,
        [0.4*inch, 1.5*inch, 1.4*inch,
         1.2*inch, 1.2*inch]))

# ── SECTION 7: ADMET ─────────────────────
story.append(Spacer(1, 0.1*inch))
story.append(Paragraph(
    "7. Two-Stage ADMET Assessment", h1_s))
story.append(divider())
story.append(Paragraph(
    "Stage 1 on free molecule. Stage 2 on "
    "complex. Includes BBB, bleeding risk, "
    "hERG, PAINS, LE and LipE.", body_s))
if os.path.exists(admet1_csv):
    a_df = pd.read_csv(admet1_csv)
    admet_data = [['Name','MW','logP',
                   'BBB','Bleed',
                   'hERG','PAINS','Overall']]
    for _, r in a_df.head(12).iterrows():
        admet_data.append([
            r['name'],
            str(r.get('MW','')),
            str(r.get('logP','')),
            str(r.get('BBB','')),
            str(r.get('Bleeding_risk','')),
            str(r.get('hERG','')),
            str(r.get('PAINS','')),
            str(r.get('Overall_ADMET',''))])
    story.append(make_table(admet_data,
        [1.0*inch, 0.6*inch, 0.6*inch,
         0.7*inch, 0.6*inch, 0.6*inch,
         0.6*inch, 0.7*inch]))
story.append(PageBreak())

# ── SECTION 8: MD ────────────────────────
story.append(Paragraph(
    "8. Molecular Dynamics Simulation", h1_s))
story.append(divider())
if os.path.exists(md_csv):
    md_df = pd.read_csv(md_csv)
    ns = md_df.iloc[0].get(
        'md_time_ns', 0.1) \
        if len(md_df) > 0 else 0.1
    story.append(Paragraph(
        f"OpenMM + AMBER14. {ns}ns @ 300K. "
        f"RMSD ~0.1-0.13nm = stable. "
        f"Top 3 candidates simulated.",
        body_s))
    md_data = [['Name','Docking',
                'Energy(kcal/mol)',
                'RMSD','Stable','Time(ns)']]
    for _, r in md_df.iterrows():
        md_data.append([
            r['name'],
            str(r.get('docking_score','')),
            str(r.get('energy_kcal','')),
            str(r.get('rmsd','')),
            str(r.get('md_stable','')),
            str(r.get('md_time_ns',''))])
    story.append(make_table(md_data,
        [1.1*inch, 0.8*inch, 1.3*inch,
         0.7*inch, 0.7*inch, 0.8*inch]))

# ── SECTION 9: FINAL RANKING ─────────────
story.append(Spacer(1, 0.1*inch))
story.append(Paragraph(
    "9. Final Candidate Shortlist", h1_s))
story.append(divider())
story.append(Paragraph(
    f"Composite: ML(25%) + Dock(25%) + "
    f"BBB(15%) + Bleed(15%) + "
    f"MD(10%) + QED(10%). "
    f"IC50 vs {ref_name} ({ref_ic50}nM).",
    body_s))

if os.path.exists(rank_csv):
    r_df = pd.read_csv(rank_csv)
    ref_row = r_df[r_df['name'].str.contains(
        'ref', case=False, na=False)]
    if len(ref_row) > 0:
        ref = ref_row.iloc[0]
        story.append(Paragraph(
            f"{ref_name}: "
            f"IC50={ref_ic50}nM (published) | "
            f"Dock={ref.get('docking_score','N/A')}"
            f" | Score="
            f"{round(ref.get('composite',0),3)}",
            body_s))

    rank_data = [['Rank','Name','ML',
                  'Dock','BBB','Bleed',
                  'Score','IC50(nM)','Better?']]
    for _, r in r_df.head(10).iterrows():
        better = ''
        if 'ref' not in str(
                r['name']).lower():
            better = str(r.get(
                'better_than_ref_ic50',''))
        bbb = str(r.get(
            'BBB_complex_a2',
            r.get('BBB_a1',
            r.get('BBB',''))))
        bleed = str(r.get(
            'Bleeding_risk_a2',
            r.get('Bleeding_risk_a1',
            r.get('Bleeding_risk',''))))
        rank_data.append([
            str(int(r['rank'])),
            r['name'],
            str(round(r.get('ml_score',0),2)),
            str(r.get('docking_score','')),
            bbb, bleed,
            str(round(r['composite'],3)),
            str(r.get('predicted_ic50_nm','')),
            better])

    t = Table(rank_data,
        colWidths=[0.4*inch, 1.0*inch,
                   0.5*inch, 0.6*inch,
                   0.5*inch, 0.5*inch,
                   0.6*inch, 0.8*inch,
                   0.6*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0), DARK),
        ('TEXTCOLOR', (0,0),(-1,0), colors.white),
        ('FONTSIZE',  (0,0),(-1,-1), 7),
        ('GRID',      (0,0),(-1,-1),
         0.3, colors.grey),
        ('BACKGROUND',(0,1),(-1,1), GOLD),
        ('BACKGROUND',(0,2),(-1,2), LIGHT),
        ('BACKGROUND',(0,3),(-1,3), GREEN),
    ]))
    story.append(t)

    if os.path.exists(plot_png):
        story.append(Spacer(1, 0.1*inch))
        story.append(Image(plot_png,
            width=6.5*inch, height=4*inch))
story.append(PageBreak())

# ── SECTION 10: METHODS ──────────────────
story.append(Paragraph(
    "10. Methods Summary", h1_s))
story.append(divider())
methods = [
    ("Analogue Design",
     "AZD1283 scaffold modified using "
     "bioisosteric replacement, fluorination, "
     "ring substitution, and auto R-group "
     "permutation via RDKit BRICS."),
    ("IC50 Prediction",
     f"Predicted IC50 = {ref_ic50} / ML_score. "
     f"Based on ChemBERTa + Tanimoto vs "
     f"{ref_name} published IC50."),
    ("ML Activity",
     "ChemBERTa + Tanimoto to known P2Y12 "
     "actives. Combined score 0-1."),
    ("Docking",
     "AutoDock Vina v1.2.5. Grid from "
     "crystal structure. Exhaustiveness=8."),
    ("Two-Stage ADMET",
     "Stage 1: free molecule. "
     "Stage 2: complex. "
     "BBB, hERG, PAINS, LE, LipE."),
    ("MD Simulation",
     "OpenMM AMBER14. 500 steps minimize "
     "+ 0.1ns MD at 300K. Top 3."),
    ("Final Ranking",
     "Composite: ML(25%) + Dock(25%) + "
     "BBB(15%) + Bleed(15%) + "
     "MD(10%) + QED(10%)."),
]
for title, desc in methods:
    story.append(Paragraph(title, h2_s))
    story.append(Paragraph(desc, body_s))

# ── SECTION 11: DISCLAIMER ───────────────
story.append(Spacer(1, 0.1*inch))
story.append(Paragraph(
    "11. Disclaimer", h1_s))
story.append(divider())
story.append(Paragraph(
    "All results are computational predictions. "
    "Docking scores, ML predictions, IC50 "
    "estimates, and ADMET properties are ranking "
    "signals only. Experimental validation through "
    "in vitro P2Y12 binding assays required "
    "before any biological claim.",
    body_s))
story.append(Spacer(1, 0.2*inch))
story.append(Paragraph(
    f"Generated: "
    f"{datetime.now().strftime('%Y-%m-%d %H:%M')}"
    f" | AutoAnalog v2.0 | Snakemake",
    small_s))

doc.build(story)
print(f"Report saved: {out_pdf}")
print("Step 11 complete")
