# Dr. Nemo: 24/7 Autonomous Research Laboratory
**Project Goal:** Complete eradication of dental caries via high-throughput discovery of targeted adhesion blockers against *Streptococcus mutans*.

---

## 🏆 Project Vision
The primary mechanism of cavity formation is the physical adhesion of *S. mutans* to the tooth enamel biofilm, allowing it to aggregate, secrete acid, and degrade the crystal lattice. 
To cure caries, we must design a custom **peptide blocker** that physically plugs into the active site of the *S. mutans* surface adhesion proteins.

To do this at a Nobel-level scale, we have built an **Autonomous In-Silico Lab** that writes novel molecular sequences, folds them mathematically in the cloud, analyzes their binding affinity locally using a Medical AI, and compiles institutional pitch reports—running entirely automatically, 24 hours a day.

---

## 🗺️ Architectural Concept Map
This laboratory operates via distinct "software workstations" that function together automatically. You can find all these files inside the `~/drnemo_research/` server directory.

### 1. The Generation Tools (The "Biologists")
Instead of manually typing molecules to test, you use these scripts to generate batches of targets.

*   **`mutation_scanner.py`**: Takes a baseline "okay" peptide (like `LKKLLKLL`), mathematically randomizes one or two of its amino acids (letters), and queues up 10 brand new variant candidates to test.
*   **`directed_evolution.py`**: A highly advanced Darwinian algorithm. It automatically finds the Top 3 highest-scoring peptides you've ever found, structurally mutates *those specific winners*, and generates a new breed of superior variants. Using this allows the AI to "learn" and climb the gradient towards a cure without random guessing.

*(Both scripts create tiny `.json` files representing the molecule and drop them into the `jobs/pending/` folder).*

---

### 2. The Engine (The "Lab Manager")
*   **`orchestrator.py`**: This is the heart of the 24/7 autonomous lab. It runs infinitely in the background, constantly watching the `pending/` folder. When a json drops in, the Orchestrator picks it up, hands it to the Folding Pipeline, waits for the result, hands it to the Clinical Analyzer, logs the result, and loops. It has built-in crash-recovery (backoff looping) so your computer never stops researching.

---

### 3. The Folding Pipeline (The "Crystallographer")
*   **`biophysics_engine.py`**: This script runs 28 Å uncompressed grid docking using **AutoDock Vina v1.2.7** and **Vinardo** alongside all-atom OpenMM Amber14/GBn2 minimization. 
    *   It tests the physical folding of the proteins to see if your sequence successfully plugs the target. 
    *   It pulls down a 3D structural model (`.pdb` file) and logs two vital scores:
        *   **pLDDT:** Confidence that the 3D shape itself is correct (Aim for >70).
        *   **iPTM:** Confidence in the *interaction* (binding affinity) between the pathogen and your blocker (Aim for >0.8 for a major hit).
    *   *Note: This script has multi-key load balancing built-in. If NVIDIA rate-limits a key, it seamlessly passes to the next free-tier key.*

---

### 4. The Clinical Synthesis (The "Medical Diagnostician")
*   **`analyzer.py`**: Relying solely on raw math values (`iPTM`) is not enough for an IRB or FDA pitch. This script loads a miniaturized Medical Brain (**MedGemma 1.5 4B**) directly onto your local RTX 4060 graphics card. 
*   It feeds the 3D physics scores to the language model, which writes a highly professional, literature-grade clinical justification analyzing the molecule's potential logic as a pharmaceutical therapy.

---

### 5. The Visualization & Export (The "Publisher")
*   **`dashboard.py`**: The Streamlit user interface you open in your Windows browser. 
*   **The Log:** Sorts all your results so you can see your highest `iPTM` hits at the top.
*   **Sequence Display:** Extracts strings out of the job names to explicitly show you the Amino Acid sequence (`LKHLLKLL`, etc.) so you know what the molecule is.
*   **Publication 3D Render:** Custom visualizes the molecules. Colors the pathogen in standard Red-White-Blue confidence mapping, and highlights your newly designed blocker clearly in solid spheres.
*   **Pitch Exporter:** Compiles the entire pipeline's work (The sequence + the MedGemma Clinical text) into a downloadable Markdown protocol you can email straight to an institution for laboratory wet-lab validation.

---

## 🎯 Getting Started Checklist
1. You have already built the core structure.
2. Ensure the **Orchestrator** is running.
3. Open the **Dashboard**.
4. Double click `RUN_MUTATION_SCANNER.bat` or `EVOLVE_MUTATIONS.bat` on your Desktop to fill the pipeline with data.
5. Watch the dashboard to find a peptide scoring `iPTM > 0.8`.
6. Export the Pitch Deck.
7. Change Dental History!
