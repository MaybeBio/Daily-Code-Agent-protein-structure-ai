configfile: "config/config.yaml"

def get_mode(config):
    has_pdb = bool(config.get("pdb_id","").strip())
    has_seq = bool(config.get("sequence","").strip())
    has_inh = bool(config.get("known_inhibitor","").strip())
    if not has_pdb and not has_seq:
        raise ValueError("pdb_id ya sequence dono blank hain!")
    struct = "known" if has_pdb else "unknown"
    inhib  = "known" if has_inh else "unknown"
    return f"{struct}__{inhib}"

PIPELINE_MODE   = get_mode(config)
KNOWN_PROTEIN   = PIPELINE_MODE.startswith("known")
KNOWN_INHIBITOR = PIPELINE_MODE.endswith("known")

rule all:
    input:
        "results/report/final_report.pdf"

rule structure:
    output:
        "results/structure/protein.pdbqt",
        "results/structure/grid_config.json"
    log:
        "logs/structure.log"
    script:
        "scripts/01_structure.py"

rule literature:
    output:
        "results/literature/papers.csv"
    log:
        "logs/literature.log"
    script:
        "scripts/02_literature.py"

rule analogues:
    input:
        "results/structure/protein.pdbqt",
        "results/structure/grid_config.json"
    output:
        "results/analogues/descriptors.csv",
        "results/analogues/all_analogues.png"
    log:
        "logs/analogues.log"
    script:
        "scripts/03_analogues.py"

rule ml:
    input:
        "results/analogues/descriptors.csv"
    output:
        "results/models/best_model.pkl",
        "results/models/activity_scores.csv"
    log:
        "logs/ml.log"
    script:
        "scripts/04_ml.py"

rule admet_stage1:
    input:
        "results/analogues/descriptors.csv"
    output:
        "results/admet/stage1.csv"
    log:
        "logs/admet1.log"
    script:
        "scripts/05_admet_stage1.py"

rule virtual_screening:
    input:
        "results/admet/stage1.csv"
    output:
        "results/screening/screened.csv"
    log:
        "logs/screening.log"
    script:
        "scripts/06_virtual_screening.py"

rule docking:
    input:
        "results/structure/protein.pdbqt",
        "results/structure/grid_config.json",
        "results/screening/screened.csv"
    output:
        "results/docking/scores.csv"
    log:
        "logs/docking.log"
    script:
        "scripts/07_docking.py"

rule admet_stage2:
    input:
        "results/docking/scores.csv"
    output:
        "results/admet/stage2.csv"
    log:
        "logs/admet2.log"
    script:
        "scripts/08_admet_stage2.py"

rule md_simulation:
    input:
        "results/docking/scores.csv",
        "results/structure/protein.pdbqt"
    output:
        "results/md/md_results.csv"
    log:
        "logs/md.log"
    script:
        "scripts/09_md.py"

rule ranking:
    input:
        "results/docking/scores.csv",
        "results/admet/stage2.csv",
        "results/md/md_results.csv",
        "results/models/best_model.pkl",
        "results/admet/stage1.csv",
        "results/models/activity_scores.csv"
    output:
        "results/ranking/final_ranking.csv",
        "results/ranking/pareto_plot.png"
    log:
        "logs/ranking.log"
    script:
        "scripts/10_ranking.py"

rule report:
    input:
        "results/literature/papers.csv",
        "results/analogues/all_analogues.png",
        "results/docking/scores.csv",
        "results/admet/stage1.csv",
        "results/admet/stage2.csv",
        "results/md/md_results.csv",
        "results/ranking/final_ranking.csv",
        "results/ranking/pareto_plot.png"
    output:
        "results/report/final_report.pdf"
    log:
        "logs/report.log"
    script:
        "scripts/11_report.py"
