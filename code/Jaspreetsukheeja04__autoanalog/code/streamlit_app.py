import streamlit as st
import subprocess
import os
import yaml
import pandas as pd

st.set_page_config(
    page_title="AutoAnalog v2.0",
    page_icon="🧬",
    layout="wide")

st.title("🧬 AutoAnalog v2.0")
st.subheader(
    "Automated Drug Discovery Pipeline — "
    "Disease → Ranked Lead Compounds")

st.sidebar.header("Pipeline Configuration")

disease = st.sidebar.text_input("Disease", "endometriosis")
receptor = st.sidebar.text_input("Receptor", "P2Y12")
pdb_id = st.sidebar.text_input("PDB ID", "4NTJ")
sequence = st.sidebar.text_area("OR Protein Sequence (if no PDB)", "")
inhibitor = st.sidebar.text_area(
    "Known Inhibitor SMILES",
    "CC1=CC=C(C=C1)S(=O)(=O)NC2=NC=C(C=N2)C3=CC=CC=N3")
ref_ic50 = st.sidebar.number_input("Reference IC50 (nM)", 1, 10000, 89)
ref_name = st.sidebar.text_input("Reference Name", "AZD1283")
ref_source = st.sidebar.text_input(
    "Reference Source", "Springthorpe et al. 2007")
exhaustiveness = st.sidebar.slider("Docking Exhaustiveness", 1, 16, 8)
n_analogues = st.sidebar.slider("Max Analogues", 10, 200, 50)

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Disease", disease)
with col2:
    st.metric("Receptor", receptor)
with col3:
    st.metric("Reference IC50", f"{ref_ic50} nM")

st.divider()

if st.button("🚀 Run Pipeline",
             type="primary",
             use_container_width=True):

    config = {
        "disease":            disease,
        "receptor":           receptor,
        "pdb_id":             pdb_id,
        "sequence":           sequence,
        "known_inhibitor":    inhibitor,
        "reference_ic50_nm":  ref_ic50,
        "reference_name":     ref_name,
        "reference_source":   ref_source,
        "chembl_id":          "CHEMBL2563",
        "n_analogues":        n_analogues,
        "max_permutation_analogues": 999,
        "docking_exhaustiveness": exhaustiveness,
        "ml_cv_folds":        5,
        "md_steps":           25000,
        "md_temperature":     300,
        "md_timestep":        0.004,
        "active_threshold_nm": 1000,
        "inactive_threshold_nm": 10000,
        "use_admet_ai":       True,
        "admet_herg_threshold": 0.5,
        "admet_hepatotox_threshold": 0.5,
        "chembl_screen_n":    1000,
        "tanimoto_vs_threshold": 0.4,
        "top_hits_for_analogues": 5,
    }

    os.makedirs("config", exist_ok=True)
    with open("config/config.yaml", "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    st.success("Config saved!")

    # Unlock snakemake first
    subprocess.run(
        ["snakemake", "--unlock"],
        cwd=os.getcwd(),
        capture_output=True)

    steps = [
        "Structure preparation",
        "Literature mining",
        "Analogue design",
        "ML activity + IC50",
        "ADMET Stage 1",
        "Virtual screening",
        "Molecular docking",
        "ADMET Stage 2",
        "MD simulation",
        "Final ranking",
        "PDF report generation",
    ]

    progress = st.progress(0)
    status   = st.empty()
    log_box  = st.empty()

    with st.spinner("Pipeline running..."):
        process = subprocess.Popen(
            ["snakemake", "--forceall",
             "--cores", "2"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=os.getcwd())

        output_lines = []
        step_num = 0

        for line in process.stdout:
            output_lines.append(line.strip())
            if len(output_lines) > 25:
                output_lines.pop(0)
            log_box.code(
                "\n".join(output_lines),
                language="bash")
            for i, step in enumerate(steps):
                kw = step.split()[0].lower()
                if kw in line.lower():
                    step_num = i + 1
                    progress.progress(
                        step_num / len(steps))
                    status.info(f"Running: {step}")

        process.wait()

        if process.returncode == 0:
            progress.progress(1.0)
            status.success("Pipeline complete!")
            st.balloons()
        else:
            status.error("Pipeline failed — check logs")

st.divider()

rank_path  = "results/ranking/final_ranking.csv"
dock_path  = "results/docking/scores.csv"
plot_path  = "results/ranking/pareto_plot.png"
ana_png    = "results/analogues/all_analogues.png"
report     = "results/report/final_report.pdf"
admet_path = "results/admet/stage1.csv"
lit_path   = "results/literature/papers.csv"
ana_csv    = "results/analogues/descriptors.csv"

col1, col2 = st.columns(2)
with col1:
    if os.path.exists(report):
        with open(report, "rb") as f:
            st.download_button(
                "📄 Download PDF Report",
                f,
                file_name=
                f"AutoAnalog_{receptor}_{disease}.pdf",
                mime="application/pdf",
                use_container_width=True)
    else:
        st.info("Run pipeline to generate report")

with col2:
    if os.path.exists(rank_path):
        r_df = pd.read_csv(rank_path)
        st.download_button(
            "📊 Download Rankings CSV",
            r_df.to_csv(index=False),
            file_name=f"Rankings_{receptor}.csv",
            mime="text/csv",
            use_container_width=True)

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🏆 Final Rankings",
    "⚗️ Analogues",
    "🔬 Docking",
    "🧪 ADMET",
    "📄 Report"])

with tab1:
    st.subheader("Final Candidate Shortlist")
    st.caption(
        "Composite: ML(25%) + Dock(25%) + "
        "BBB(15%) + Bleed(15%) + MD(10%) + QED(10%)")
    if os.path.exists(rank_path):
        r_df = pd.read_csv(rank_path)
        ref_row = r_df[
            r_df['name'].str.contains(
                'ref', case=False, na=False)]
        if len(ref_row) > 0:
            ref = ref_row.iloc[0]
            st.info(
                f"Reference AZD1283: IC50=89nM | "
                f"Dock={ref.get('docking_score','N/A')} | "
                f"Score={round(ref.get('composite',0),3)}")
        cols = [c for c in [
            "rank","name","ml_score",
            "docking_score","composite",
            "predicted_ic50_nm",
            "better_than_ref_ic50",
            "better_than_ref_dock"]
            if c in r_df.columns]
        st.dataframe(r_df[cols], use_container_width=True)
        if os.path.exists(plot_path):
            st.image(plot_path,
                caption="Ranking Plot",
                use_container_width=True)
    else:
        st.warning("Run pipeline to see results")

with tab2:
    st.subheader("Designed Analogues")
    if os.path.exists(ana_csv):
        ana_df = pd.read_csv(ana_csv)
        c1,c2,c3,c4 = st.columns(4)
        with c1: st.metric("Total", len(ana_df))
        with c2: st.metric("Lipinski PASS",
            int((ana_df['Lipinski']=='PASS').sum()))
        with c3: st.metric("Positions", "7")
        with c4: st.metric("Substituents", "15")
        st.dataframe(
            ana_df[[c for c in [
                "name","modification",
                "MW","logP","QED","Tanimoto",
                "predicted_ic50_nm",
                "vs_ref_ic50","Lipinski"]
                if c in ana_df.columns]],
            use_container_width=True)
    if os.path.exists(ana_png):
        st.image(ana_png,
            caption="Analogue Structures",
            use_container_width=True)

with tab3:
    st.subheader("Molecular Docking Results")
    st.caption("AutoDock Vina v1.2.5 | Grid from 4NTJ crystal structure")
    if os.path.exists(dock_path):
        d_df = pd.read_csv(dock_path)
        ref_dock = d_df[
            d_df['name'].str.contains(
                'ref', case=False, na=False)][
            'docking_score'].values
        ref_val = ref_dock[0] if len(ref_dock) > 0 else None
        c1,c2,c3 = st.columns(3)
        with c1: st.metric("Total Docked", len(d_df))
        with c2: st.metric("AZD1283 Ref",
            f"{ref_val} kcal/mol" if ref_val else "N/A")
        with c3:
            if ref_val:
                better = len(d_df[
                    (d_df['docking_score'] < ref_val) &
                    (~d_df['name'].str.contains(
                        'ref', case=False, na=False))])
                st.metric("Better than Ref", better)
        st.dataframe(
            d_df.sort_values('docking_score')[[
                c for c in [
                    "name","docking_score",
                    "predicted_ic50_nm","vs_ref_dock"]
                if c in d_df.columns]],
            use_container_width=True)

with tab4:
    st.subheader("ADMET Assessment")
    st.caption("Two-stage ADMET | RDKit descriptors | P2Y12-specific filters")
    if os.path.exists(admet_path):
        a_df = pd.read_csv(admet_path)
        c1,c2,c3,c4 = st.columns(4)
        with c1: st.metric("Total", len(a_df))
        with c2:
            bbb_col = next(
                (c for c in a_df.columns if 'BBB' in c), None)
            if bbb_col:
                st.metric("BBB High",
                    int((a_df[bbb_col]=='High').sum()))
        with c3:
            if 'Bleeding_risk' in a_df.columns:
                st.metric("Bleeding LOW",
                    int((a_df['Bleeding_risk']=='LOW').sum()))
        with c4:
            if 'PAINS' in a_df.columns:
                st.metric("PAINS OK",
                    int((a_df['PAINS']=='OK').sum()))
        st.dataframe(
            a_df[[c for c in [
                "name","MW","logP",
                "BBB","Bleeding_risk",
                "hERG","PAINS","Overall_ADMET"]
                if c in a_df.columns]],
            use_container_width=True)

with tab5:
    st.subheader("Pipeline Report")
    if os.path.exists(report):
        with open(report, "rb") as f:
            st.download_button(
                "📄 Download Full PDF Report",
                f,
                file_name="AutoAnalog_P2Y12_Report.pdf",
                mime="application/pdf",
                use_container_width=True)
        st.success("11-page report ready!")
    else:
        st.warning("Report not found — run pipeline first")
    if os.path.exists(lit_path):
        lit_df = pd.read_csv(lit_path)
        st.subheader("Literature Evidence")
        st.metric("Papers Retrieved", len(lit_df))
        st.dataframe(
            lit_df[[c for c in [
                "title","year","journal","citations"]
                if c in lit_df.columns]].head(20),
            use_container_width=True)

st.divider()
st.caption(
    "AutoAnalog v2.0 | Snakemake | "
    "ChemBERTa + AutoDock Vina + OpenMM | "
    "Computational predictions only | "
    "P2Y12 × Endometriosis")
