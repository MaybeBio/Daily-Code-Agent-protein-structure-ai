"""Constants, alphabets, and Enzyme Commission (EC) nomenclature."""

from __future__ import annotations

import numpy as np

AMINO_ACIDS: str = "ACDEFGHIKLMNPQRSTVWY"
AA_TO_IDX: dict[str, int] = {a: i for i, a in enumerate(AMINO_ACIDS)}

# Top-level EC Classes (Level 1)
EC_TOP_CLASSES: list[str] = [
    "EC 1: Oxidoreductases",
    "EC 2: Transferases",
    "EC 3: Hydrolases",
    "EC 4: Lyases",
    "EC 5: Isomerases",
    "EC 6: Ligases",
    "EC 7: Translocases",
]

# Top-25 populated fine-grained EC subclasses (>=97 chains each) verified across RCSB PDB + CATH 4.2
EC_CLASSES: list[str] = [
    "1.1.1",   # Oxidoreductases acting on CH-OH group of donors (NAD+/NADP+)
    "2.1.1",   # Methyltransferases
    "2.3.1",   # Acyltransferases
    "2.3.2",   # Aminoacyltransferases
    "2.4.2",   # Pentosyltransferases
    "2.5.1",   # Alkyl/aryltransferases
    "2.6.1",   # Transaminases
    "2.7.1",   # Phosphotransferases (alcohol acceptor)
    "2.7.7",   # Nucleotidyltransferases
    "2.7.10",  # Protein-tyrosine kinases
    "2.7.11",  # Protein-serine/threonine kinases
    "2.7.13",  # Protein-histidine kinases
    "3.1.1",   # Carboxylic-ester hydrolases
    "3.1.3",   # Phosphoric-monoester hydrolases (Phosphatases)
    "3.2.1",   # Glycosidases
    "3.2.2",   # Hydrolyzing N-glycosyl compounds
    "3.4.21",  # Serine endopeptidases
    "3.4.22",  # Cysteine endopeptidases
    "3.5.1",   # Linear amide hydrolases
    "3.6.1",   # Phosphorus-containing anhydride hydrolases (GTPases/ATPases)
    "3.6.4",   # Acid anhydride hydrolases (Helicases/motor ATPases)
    "4.1.1",   # Carboxy-lyases (Decarboxylases)
    "4.2.1",   # Hydro-lyases (Dehydratases)
    "6.1.1",   # Aminoacyl-tRNA ligases
    "6.3.2",   # Acid-amino-acid ligases (Ubiquitin/peptide ligases)
]

EC_DESCRIPTIONS: dict[str, str] = {
    "1.1.1": "CH-OH Oxidoreductases (NAD/NADP)",
    "2.1.1": "Methyltransferases",
    "2.3.1": "Acyltransferases",
    "2.3.2": "Aminoacyltransferases",
    "2.4.2": "Pentosyltransferases",
    "2.5.1": "Alkyl/Aryltransferases",
    "2.6.1": "Transaminases (Aminotransferases)",
    "2.7.1": "Phosphotransferases (Kinases)",
    "2.7.7": "Nucleotidyltransferases (Polymerases)",
    "2.7.10": "Protein-Tyr Kinases",
    "2.7.11": "Protein-Ser/Thr Kinases",
    "2.7.13": "Protein-His Kinases",
    "3.1.1": "Carboxylic-ester hydrolases",
    "3.1.3": "Phosphatases",
    "3.2.1": "Glycoside hydrolases",
    "3.2.2": "N-glycosylases",
    "3.4.21": "Serine endopeptidases",
    "3.4.22": "Cysteine endopeptidases",
    "3.5.1": "Linear amide hydrolases",
    "3.6.1": "NTP/Anhydride hydrolases",
    "3.6.4": "Helicases / Motor ATPases",
    "4.1.1": "Decarboxylases",
    "4.2.1": "Hydro-lyases",
    "6.1.1": "Aminoacyl-tRNA ligases",
    "6.3.2": "Acid-amino-acid ligases",
}

EC_TO_IDX: dict[str, int] = {ec: i for i, ec in enumerate(EC_CLASSES)}
IDX_TO_EC: dict[int, str] = {i: ec for i, ec in enumerate(EC_CLASSES)}

# Primary EC class (1 to 7) color palette (Okabe-Ito themed)
EC_PRIMARY_COLORS: dict[int, str] = {
    1: "#0072B2",  # Oxidoreductases (Blue)
    2: "#E69F00",  # Transferases (Orange)
    3: "#009E73",  # Hydrolases (Green)
    4: "#D55E00",  # Lyases (Vermillion)
    5: "#CC79A7",  # Isomerases (Pink)
    6: "#56B4E9",  # Ligases (Sky Blue)
    7: "#F0E442",  # Translocases (Yellow)
}
