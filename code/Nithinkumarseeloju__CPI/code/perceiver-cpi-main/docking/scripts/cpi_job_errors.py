"""Stage and user guidance for docking job failures."""
import re


def classify_failure(error):
    messages = re.findall(r"^[\w.]+(?:Error|Exception):\s*(.*)$", error or "", re.M)
    message = messages[-1].lower() if messages else ""
    stages = {
        "receptor_preparation": ("receptor_preparation", "receptor preparation", "no usable amino-acid atoms"),
        "pose_validation": ("no chemically valid pose", "failed chemistry", "no readable poses", "stereocenter", "pose_export"),
        "folding": ("esmfold", "bfloat16", "local cuda folding environment"),
        "pocket_prediction": ("p2rank", "java 17"),
        "contacts": ("plip contact analysis failed",),
        "docking": ("vina failed",),
        "ligand_preparation": ("compound", "smiles", "ligand"),
    }
    return next((stage for stage, terms in stages.items() if any(term in message for term in terms)), "unknown")


def failure_detail(stage):
    guidance = {
        "folding": "Check fold.log or use a verified experimental protein structure.",
        "receptor_preparation": "Check receptor_preparation.log for rejected residues or try a different verified structure.",
        "pose_validation": "No pose passed the checks. Review the pocket and receptor before retrying.",
        "pocket_prediction": "Check the P2Rank log or use a verified known pocket.",
        "contacts": "Check the PLIP error and the prepared complex geometry.",
        "docking": "Check vina.log before retrying.",
        "ligand_preparation": "Check the compound SMILES and whether it contains separate fragments.",
    }
    return f"3D job failed at {stage.replace('_', ' ')}. " + guidance.get(stage, "Open the technical error before retrying.")
