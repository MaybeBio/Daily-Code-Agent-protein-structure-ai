# ProtMind AI: Interactive Intelligence from Mutation to Mechanism to Medicine 🧬

An integrated bioinformatics platform and 3-step prototype designed to bridge genetic mutations, protein structure, biological function, and computational analysis through an interactive Python and Streamlit interface.


# Project Overview & Motivation
Proteins perform essential structural, regulatory, and catalytic functions dependent on their amino acid sequence and 3D structure. However, missense mutations can alter protein properties, stability, and biological activity. 

Traditionally, vital information is scattered across multiple biological databases, making comprehensive mutation analysis time-consuming. **ProtMind AI** integrates these diverse resources into a single, unified workflow with an accessible Streamlit frontend.

# Core Objectives
1. **Integrated Workflow:** Combine key biological databases into a unified platform.
2. **Data Retrieval:** Fetch protein sequences and annotations using **UniProt**.
3. **Structure Access:** View predicted protein structures through **AlphaFold DB**.
4. **Domain & Motif Search:** Identify conserved domains and functional motifs via **Pfam**.
5. **Interaction Networks:** Retrieve protein-protein interaction information using **STRING**.
6. **Interactive Interface:** Develop an easy-to-use frontend using Python and Streamlit.
7. **Extended Analysis:** Support thermodynamic stability ($\Delta\Delta\G$), stereochemical validation, and pathogenicity evaluation.


# Technology Stack
* **Core Language:** Python 3.x  
* **Libraries:** Biopython, Requests  
* **Frontend & UI:** Streamlit Framework  
* **Test Protein:** TP53 (UniProt ID: `P04637`)  


#  3-Step / Extended Methodology Workflow
1. **User Input & Validation:** Input UniProt ID, mutation details (e.g., `R75H`), and protein sequence (FASTA/upload).
2. **Data Retrieval:** Fetch protein annotations and 3D structures from UniProtKB and AlphaFold DB.
3. **Preprocessing & Motif Search:** Extract sequence features and identify conserved domains using Pfam.
4. **Mutation Analysis & Pathways:** Characterize mutation impact and map interactions via STRING.
5. **Structure Prediction & Visualization:** Model and visualize wild-type and mutant 3D structures.
6. **Thermodynamic Stability:** Compute $\Delta\Delta\G$, folding stability, and physicochemical profiles.
7. **Stereochemical Validation:** Assess structural quality using Ramachandran plots.
8. **Explainable AI & Pathogenicity:** Evaluate pathogenicity via machine learning models with explainable evaluation.
9. **Comprehensive Reporting:** Generate integrated analysis reports and summaries.


#  Quick Start & Installation

1. Clone the repository:
   ```bash
   git clone [https://github.com/AAdisriMenon/ProtMind-AI_3step.git](https://github.com/AAdisriMenon/ProtMind-AI_3step.git)
   cd ProtMind-AI_3step
