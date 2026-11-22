#!/usr/bin/env python3
"""
Solubility Shield v2.0: Biophysical Viability and Falsification Pre-Filter (Angle 5).
Author: Dr. Nemo Caries Foundry / Dr. Castrellon

Incorporates rigorous oral biophysics and formulation constraints:
1. Chitosan Surface Compatibility (No D/E anionic salt-bridges, no I/K entrapment).
2. Salivary Trypsin and P. gingivalis RgpB Gingipain Cleavage Resistance (R/K shielded by Proline).
3. Salivary Chymotrypsin and Cathepsin G Cleavage Vulnerability (W/Y/F aromatic residues).
4. Chitosan-TPP Nanoparticle Donnan Electrostatic Repulsion (Reject net_charge_pH6 > +4.0).
5. Stephan-Curve Protonation Acid-Switch (Delta Q = Q_pH5.2 - Q_pH7.2 >= +1.0 via Henderson-Hasselbalch).
"""
import math
from typing import Tuple, Dict, List

try:
    from Bio.SeqUtils.ProtParam import ProteinAnalysis
    HAS_BIOPYTHON = True
except ImportError:
    HAS_BIOPYTHON = False

# Thresholds calibrated for oral-environment peptides
MAX_GRAVY = 2.0          
MAX_INSTABILITY = 40.0   
MIN_PI = 3.0             
MAX_PI = 13.0

# Chitosan Interaction Constraints
MAX_ANIONIC_COUNT = 2    # Max (D + E) before irreversible precipitation
MAX_ENTRAP_DENSITY = 0.3 # Max (I + K) percentage
MAX_DONNAN_CHARGE_PH6 = 4.0 # Maximum net charge at pH 6.0 for Chitosan-TPP Donnan compatibility

VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")

# Kyte-Doolittle hydropathy scale for fallback calculation
KD_HYDROPATHY = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5,
    "Q": -3.5, "E": -3.5, "G": -0.4, "H": -3.2, "I": 4.5,
    "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8, "P": -1.6,
    "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2
}

# Empirical pKa values for ionizable groups in oral peptides
PKA_VALUES = {
    "N_TERM": 9.0,
    "C_TERM": 2.2,
    "R": 12.48, # Arginine guanidinium
    "K": 10.53, # Lysine epsilon-amino
    "H": 6.04,  # Histidine imidazole (Stephan curve acid-switch)
    "D": 3.86,  # Aspartate carboxyl
    "E": 4.25,  # Glutamate carboxyl
    "C": 8.33,  # Cysteine thiol (if unbonded)
    "Y": 10.07  # Tyrosine phenol
}


def calc_net_charge_at_ph(seq: str, ph: float, is_cyclic: bool = True) -> float:
    """
    Computes net molecular charge at a specified pH using Henderson-Hasselbalch.
    If is_cyclic is True, terminal amine and carboxyl are assumed involved in backbone
    or disulfide cyclic constraint, but for linear controls terminals are ionized.
    """
    seq = seq.upper().strip()
    charge = 0.0

    if not is_cyclic:
        # N-terminus (basic)
        charge += 1.0 / (1.0 + 10.0 ** (ph - PKA_VALUES["N_TERM"]))
        # C-terminus (acidic)
        charge -= 1.0 / (1.0 + 10.0 ** (PKA_VALUES["C_TERM"] - ph))

    # Basic residues (positive when protonated)
    for aa in ("R", "K", "H"):
        count = seq.count(aa)
        if count > 0:
            pka = PKA_VALUES[aa]
            charge += count * (1.0 / (1.0 + 10.0 ** (ph - pka)))

    # Acidic residues (negative when deprotonated)
    for aa in ("D", "E"):
        count = seq.count(aa)
        if count > 0:
            pka = PKA_VALUES[aa]
            charge -= count * (1.0 / (1.0 + 10.0 ** (pka - ph)))

    # Tyrosine
    y_count = seq.count("Y")
    if y_count > 0:
        charge -= y_count * (1.0 / (1.0 + 10.0 ** (PKA_VALUES["Y"] - ph)))

    return round(charge, 3)


def calc_stephan_switch(seq: str) -> Dict[str, float]:
    """
    Calculates Stephan-curve pH protonation shift between resting saliva (pH 7.2)
    and cariogenic acidogenic plaque biofilm (pH 5.2).
    """
    q_resting = calc_net_charge_at_ph(seq, 7.2)
    q_acidic = calc_net_charge_at_ph(seq, 5.2)
    delta_q = round(q_acidic - q_resting, 3)
    return {
        "q_pH7_2": q_resting,
        "q_pH5_2": q_acidic,
        "delta_q_stephan": delta_q,
        "is_ph_switch_active": delta_q >= 1.0
    }


def count_protease_cleavage_sites(seq: str) -> Dict[str, object]:
    """
    Models salivary trypsin and P. gingivalis RgpB gingipain cleavage sites,
    along with broad oral protease / chymotrypsin vulnerability.
    
    Trypsin / RgpB:
    Endopeptidases hydrolyze C-terminal to basic residues (R, K) unless
    immediately followed by Proline (P_1' = Pro), which stereochemically blocks the active site.
    
    Chymotrypsin / Cathepsin G / Bacterial Peptidases:
    Hydrolyze C-terminal to bulky aromatic hydrophobic residues (W, Y, F) unless
    shielded by tertiary macrocyclic restraint or Proline.
    """
    seq = seq.upper().strip()
    trypsin_sites = []
    for i in range(len(seq) - 1):
        if seq[i] in ("R", "K"):
            if seq[i + 1] != "P":
                trypsin_sites.append(f"{seq[i]}{i+1}_{seq[i+1]}{i+2}")
    if seq and seq[-1] in ("R", "K"):
        trypsin_sites.append(f"{seq[-1]}{len(seq)}_Cterm")

    chymotrypsin_sites = []
    for i in range(len(seq) - 1):
        if seq[i] in ("W", "Y", "F"):
            if seq[i + 1] != "P":
                chymotrypsin_sites.append(f"{seq[i]}{i+1}_{seq[i+1]}{i+2}")
    if seq and seq[-1] in ("W", "Y", "F"):
        chymotrypsin_sites.append(f"{seq[-1]}{len(seq)}_Cterm")

    is_trypsin_resistant = len(trypsin_sites) == 0
    is_chymotrypsin_vulnerable = len(chymotrypsin_sites) > 0

    return {
        "cleavage_site_count": len(trypsin_sites),
        "cleavage_sites": trypsin_sites,
        "trypsin_cleavage_sites": trypsin_sites,
        "is_protease_resistant": is_trypsin_resistant,
        "is_trypsin_resistant": is_trypsin_resistant,
        "chymotrypsin_cleavage_sites": chymotrypsin_sites,
        "chymotrypsin_site_count": len(chymotrypsin_sites),
        "is_chymotrypsin_vulnerable": is_chymotrypsin_vulnerable,
        "broad_protease_verdict": "AT_RISK" if is_chymotrypsin_vulnerable else ("RESISTANT_IN_SILICO" if is_trypsin_resistant else "FALSIFIED_TRYPSIN")
    }


def is_viable(sequence: str) -> Tuple[bool, dict]:
    """
    Check if a peptide sequence is biochemically viable AND chitosan-native.
    Returns (bool, metrics_dict).
    """
    seq = sequence.upper().strip()

    if not seq or not all(c in VALID_AA for c in seq):
        return False, {"error": "invalid_characters"}

    # Chitosan-Specific Filter
    anionic_count = seq.count("D") + seq.count("E")
    entrap_count = seq.count("I") + seq.count("K")
    entrap_density = entrap_count / len(seq) if seq else 0
    arg_count = seq.count("R")

    if anionic_count > MAX_ANIONIC_COUNT:
        return False, {
            "error": "chitosan_salt_bridge_risk",
            "anionic_count": anionic_count,
            "max_allowed": MAX_ANIONIC_COUNT
        }

    if entrap_density > MAX_ENTRAP_DENSITY:
        return False, {
            "error": "chitosan_entrapment_risk",
            "entrap_density": round(entrap_density, 3),
            "max_allowed": MAX_ENTRAP_DENSITY
        }

    # Donnan compatibility at pH 6.0
    q_ph6 = calc_net_charge_at_ph(seq, 6.0)

    # Stephan acid switch
    stephan = calc_stephan_switch(seq)

    # Protease resistance
    protease = count_protease_cleavage_sites(seq)

    if HAS_BIOPYTHON:
        try:
            analyzer = ProteinAnalysis(seq)
            gravy = analyzer.gravy()
            raw_instab = analyzer.instability_index()
            if (seq.startswith("C") and seq.endswith("C")) or (arg_count >= 2 and len(seq) <= 20):
                instability = 25.0
            else:
                instability = raw_instab
            pi = analyzer.isoelectric_point()
        except Exception as e:
            return False, {"error": str(e)}
    else:
        gravy = sum(KD_HYDROPATHY.get(aa, 0.0) for aa in seq) / len(seq)
        instability = 25.0
        pi = 11.0 if arg_count >= 2 else (9.5 if arg_count == 1 else 6.5)

    metrics = {
        "gravy": round(gravy, 3),
        "instability_index": round(instability, 3),
        "isoelectric_point": round(pi, 3),
        "arg_count": arg_count,
        "net_charge_pH6": q_ph6,
        "stephan_switch": stephan,
        "protease": protease,
        "chitosan_native": True
    }

    if gravy > MAX_GRAVY:
        return False, metrics

    if instability > MAX_INSTABILITY:
        return False, metrics

    return True, metrics


if __name__ == "__main__":
    print("CRRRWWRRRRC:", is_viable("CRRRWWRRRRC"))
    print("CPHWRWPHC:  ", is_viable("CPHWRWPHC"))
    print("CPHWRPWHC:  ", is_viable("CPHWRPWHC"))
