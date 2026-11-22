"""Pure-Python + NumPy RFD4 token vocabulary and condition metadata.

Vendors RFD4's static 147-token Atom37 vocabulary, token-type groups,
autoencoder local-latent residue set, and 19-entry condition registry without
importing ``rfproteina`` or ``torch``.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Sequence

import numpy as np

if TYPE_CHECKING:
    from atomworks.ml.encoding_definitions import TokenEncoding

    UNIFIED_ATOM37_ENCODING: TokenEncoding

TOKEN_TYPE_IDS: dict[str, int] = {
    "aa": 0,
    "rna": 1,
    "dna": 2,
    "atomized": 3,
    "unknown": 4,
    "glycan": 5,
    "ncaa": 6,
    "mask": 4,
}

# Ordered 37-slot layouts in exact RFD4 checkpoint class order (147 tokens).
# Tokens 0..33 match AtomWorks' unified vocabulary order (with RFD4's UNK
# backbone slots), followed by the 113 RFD4 NCAA (34..133) and glycan (134..146)
# tokens.
_VOCABULARY_LAYOUTS: dict[str, dict[str, str]] = {
    "mask": {
        "<M>": "- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -",
    },
    "aa": {
        "ALA": "N CA C CB O - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - OXT",
        "ARG": "N CA C CB O CG - - - - - CD - - - - - - - - - - - NE - - - - - NH1 NH2 - CZ - - - OXT",
        "ASN": "N CA C CB O CG - - - - - - - - - ND2 OD1 - - - - - - - - - - - - - - - - - - - OXT",
        "ASP": "N CA C CB O CG - - - - - - - - - - OD1 OD2 - - - - - - - - - - - - - - - - - - OXT",
        "CYS": "N CA C CB O - - - - - SG - - - - - - - - - - - - - - - - - - - - - - - - - OXT",
        "GLN": "N CA C CB O CG - - - - - CD - - - - - - - - - - - - - NE2 OE1 - - - - - - - - - OXT",
        "GLU": "N CA C CB O CG - - - - - CD - - - - - - - - - - - - - - OE1 OE2 - - - - - - - - OXT",
        "GLY": "N CA C - O - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - OXT",
        "HIS": "N CA C CB O CG - - - - - - - CD2 ND1 - - - - - CE1 - - - - NE2 - - - - - - - - - - OXT",
        "ILE": "N CA C CB O - CG1 CG2 - - - - CD1 - - - - - - - - - - - - - - - - - - - - - - - OXT",
        "LEU": "N CA C CB O CG - - - - - - CD1 CD2 - - - - - - - - - - - - - - - - - - - - - - OXT",
        "LYS": "N CA C CB O CG - - - - - CD - - - - - - - CE - - - - - - - - - - - - - - - NZ OXT",
        "MET": "N CA C CB O CG - - - - - - - - - - - - SD CE - - - - - - - - - - - - - - - - OXT",
        "PHE": "N CA C CB O CG - - - - - - CD1 CD2 - - - - - - CE1 CE2 - - - - - - - - - - CZ - - - OXT",
        "PRO": "N CA C CB O CG - - - - - CD - - - - - - - - - - - - - - - - - - - - - - - - OXT",
        "SER": "N CA C CB O - - - OG - - - - - - - - - - - - - - - - - - - - - - - - - - - OXT",
        "THR": "N CA C CB O - - CG2 - OG1 - - - - - - - - - - - - - - - - - - - - - - - - - - OXT",
        "TRP": "N CA C CB O CG - - - - - - CD1 CD2 - - - - - - - CE2 CE3 - NE1 - - - CH2 - - - - CZ2 CZ3 - OXT",
        "TYR": "N CA C CB O CG - - - - - - CD1 CD2 - - - - - - CE1 CE2 - - - - - - - - - OH CZ - - - OXT",
        "VAL": "N CA C CB O - CG1 CG2 - - - - - - - - - - - - - - - - - - - - - - - - - - - - OXT",
        "UNK": "N CA C - O - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -",
    },
    "rna": {
        "A": "P C1' C2' O2' C3' O3' C4' O4' C5' O5' OP1 OP2 N9 C8 N7 C5 C4 N3 C2 N1 C6 N6 - - - - - - - - - - - - - - OP3",
        "C": "P C1' C2' O2' C3' O3' C4' O4' C5' O5' OP1 OP2 - - - - - - - - - - - - N1 C2 O2 N3 C4 C5 C6 N4 - - - - OP3",
        "G": "P C1' C2' O2' C3' O3' C4' O4' C5' O5' OP1 OP2 N9 C8 N7 C5 C4 N3 C2 N1 C6 - N2 O6 - - - - - - - - - - - - OP3",
        "U": "P C1' C2' O2' C3' O3' C4' O4' C5' O5' OP1 OP2 - - - - - - - - - - - - N1 C2 O2 N3 C4 C5 C6 - O4 - - - OP3",
        "N": "P C1' C2' O2' C3' O3' C4' O4' C5' O5' OP1 OP2 - - - - - - - - - - - - - - - - - - - - - - - - -",
    },
    "dna": {
        "DA": "P C1' C2' - C3' O3' C4' O4' C5' O5' OP1 OP2 N9 C8 N7 C5 C4 N3 C2 N1 C6 N6 - - - - - - - - - - - - - - OP3",
        "DC": "P C1' C2' - C3' O3' C4' O4' C5' O5' OP1 OP2 - - - - - - - - - - - - N1 C2 O2 N3 C4 C5 C6 N4 - - - - OP3",
        "DG": "P C1' C2' - C3' O3' C4' O4' C5' O5' OP1 OP2 N9 C8 N7 C5 C4 N3 C2 N1 C6 - N2 O6 - - - - - - - - - - - - OP3",
        "DT": "P C1' C2' - C3' O3' C4' O4' C5' O5' OP1 OP2 - - - - - - - - - - - - N1 C2 O2 N3 C4 C5 C6 - O4 C7 - - OP3",
        "DN": "P C1' C2' - C3' O3' C4' O4' C5' O5' OP1 OP2 - - - - - - - - - - - - - - - - - - - - - - - - -",
    },
    "atomized": {
        "<A>": "- X - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -",
    },
    "unknown": {
        "<G>": "- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -",
    },
    "ncaa": {
        "SEP": "N CA C CB O - - O1P OG - - - - - - - - - - - - - - - O2P - - - O3P P - - - - - - OXT",
        "TPO": "N CA C CB O - - CG2 - OG1 - - - - - O1P - - - - - - - - - - O2P - - O3P - - - - P - OXT",
        "CSO": "N CA C CB O - - - - - SG - - - - - - - - - - - - - - - - - - - - - - - - OD OXT",
        "PTR": "N CA C CB O CG - - - - - - CD1 CD2 O1P O2P - - O3P - CE1 CE2 - - - - - - - - P OH CZ - - - OXT",
        "CME": "N CA C CB O - - - - - SG - - - - - - - SD CE - - - - - - - - - - - OH CZ - - - OXT",
        "KCX": "N CA C CB O CG - - - - - CD - - CX - - - - CE - - - - - - - - - OQ1 OQ2 - - - - NZ OXT",
        "LLP": "N CA C CB O CG C2 - C2' C3 C4 CD - - C4' - - C5 C5' CE - - - - C6 N1 O3 OP1 OP2 OP3 - OP4 - P - NZ OXT",
        "CSD": "N CA C CB O - - - - - SG - - - - - OD1 OD2 - - - - - - - - - - - - - - - - - - OXT",
        "HIC": "N CA C CB O CG - - - - - - - CD2 ND1 - - - - - CE1 - - - - NE2 - - - - - - CZ - - - OXT",
        "ALY": "N CA C CB O CG CH - - - - CD - - - - - - - CE - - - - - - CH3 - - - - OH - - - NZ OXT",
        "HYP": "N CA C CB O CG - - - - - CD - - - - OD1 - - - - - - - - - - - - - - - - - - - OXT",
        "MLY": "N CA C CB O CG - - - - - CD - - - - - - - CE - - - - - - - - CH2 - - - - - CH1 NZ OXT",
        "TYS": "N CA C CB O CG - - - - - - CD1 CD2 - - - - - - CE1 CE2 - O1 O2 O3 - - - - - OH CZ - S - OXT",
        "M3L": "N CA C CB O CG CM1 - - - - CD - - - - - - - CE - - - - - - CM2 CM3 - - - - - - - NZ OXT",
        "OCS": "N CA C CB O - - - - - SG - - - - - OD1 OD2 - - - - - - OD3 - - - - - - - - - - - OXT",
        "CSS": "N CA C CB O - - - - - SG - - - - - - - SD - - - - - - - - - - - - - - - - - OXT",
        "CSX": "N CA C CB O - - - - - SG - - - - - - - - - - - - - - - - - - - OD - - - - - OXT",
        "CAS": "N CA C CB O - AS - - - SG - - - - - - - - - CE1 CE2 - - - - - - - - - - - - - - OXT",
        "AIB": "N CA C - O - - - - - - - - - - - - - - - - - - - - - CB1 - - CB2 - - - - - - OXT",
        "0TD": "N CA C CB O CG - - - CSB - - - - - - OD1 OD2 - - - - - - - SB - - - - - - - - - - OXT",
        "MLZ": "N CA C CB O CG - - - - - CD - - - - - - - CE - - - - - - - - CM - - - - - - NZ OXT",
        "NLE": "N CA C CB O CG - - - - - CD - - - - - - - CE - - - - - - - - - - - - - - - - OXT",
        "MEQ": "N CA C CB O CG - - - - - CD - - - - - - - CE - - - - - NE2 OE1 - - - - - - - - - OXT",
        "2MR": "N CA C CB O CG - - - - - CD - - - - - - CQ1 - - - - NE CQ2 - - - - NH1 NH2 - CZ - - - OXT",
        "4D4": "N CA C CB O CG - - OB - - CD - - - - - - - - - - - NE - - - - - NH1 NH2 - CZ - - - OXT",
        "D2T": "N CA C CB O CG - - CB1 - - - - - - - OD1 OD2 - - - - - - - - - - - - SB - - - - - OXT",
        "ABA": "N CA C CB O CG - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - OXT",
        "YCM": "N CA C CB O - - - - - SG CD - - - - - - - CE - - - - - - - - - NZ2 - - - - OZ1 - OXT",
        "ORN": "N CA C CB O CG - - - - - CD - - - - - - - - - - - NE - - - - - - - - - - - - OXT",
        "SEC": "N CA C CB O - - - - - - - - - - SE - - - - - - - - - - - - - - - - - - - - OXT",
        "MEN": "N CA C CB O CG - - - - - - - - - ND2 OD1 - - - - CE2 - - - - - - - - - - - - - - OXT",
        "CGU": "N CA C CB O CG - - - - - - CD1 CD2 OE11 - - - - - - - OE12 OE21 - - - - - - - - - - OE22 - OXT",
        "KPI": "N CA C CB O CG - - C1 - - CD - - - CX1 - - - CE - - CX2 - - - - - O1 - - - - O2 - NZ OXT",
        "PHD": "N CA C CB O CG OP1 - - - - - - - - - OD1 OD2 - - - - - - - OP2 - - - - - - - OP3 P - OXT",
        "SMC": "N CA C CB O - - - CS - SG - - - - - - - - - - - - - - - - - - - - - - - - - OXT",
        "MHS": "N CA C CB O CG - - - - - - - CD2 ND1 - - CM - - CE1 - - - - NE2 - - - - - - - - - - OXT",
        "TPQ": "N CA C CB O - - - C1 - - - - - - - C2 C3 - - - - C4 - - - - C5 C6 - O2 - - O4 - O5 OXT",
        "NEP": "N CA C CB O CG - - - O1P - - - CD2 ND1 O2P - - - - CE1 - - O3P - NE2 - - - - - P - - - - OXT",
        "MK8": "N CA C CB O CG - - - - - CD - - - CB1 - - - CE - - - - - - - - - - - - - - - - OXT",
        "DPP": "N CA C CB O - - - - - - - - - NG - - - - - - - - - - - - - - - - - - - - - OXT",
        "ALC": "N CA C CB O CG - - - - - - CD1 CD2 - - - - - - CE1 CE2 - - - - - - - - - - CZ - - - OXT",
        "CAF": "N CA C CB O - - - - - SG - - - - - - - - - CE1 CE2 - AS - - - O1 - - - - - - - - OXT",
        "DDE": "N CA C CB O CG - CAA CAB - - - - CD2 ND1 - - - CAC - CE1 - CAT CAU - NE2 CBI - - CBW - - - NAD NCB OAG OXT",
        "CIR": "N CA C - O - - C3 C4 - - - - - - C5 - - C7 - - - - - - - N6 N8 - - - - - O7 - - OXT",
        "PHI": "N CA C CB O CG - - - - - - CD1 CD2 - - - - - - CE1 CE2 - I - - - - - - - - CZ - - - OXT",
        "SCH": "N CA C CB O - - - - - SG - - - - - - - SD CE - - - - - - - - - - - - - - - - OXT",
        "DAB": "N CA C CB O CG - - ND - - - - - - - - - - - - - - - - - - - - - - - - - - - OXT",
        "SCY": "N CA C CB O - - - - - SG CD - - - - - - - CE - - - - - - OCD - - - - - - - - - OXT",
        "LYR": "N CA C CB O CG C1 C10 C11 C12 C13 CD - - C14 C15 C16 - C17 CE - - C18 C19 C2 C3 C4 C5 C6 - C7 C8 - C80 C9 NZ OXT",
        "NMM": "N CA C CB O CG - - - - - CD - - - - - - CAA - - - - NE - - - - - NH1 NH2 - CZ - - - OXT",
        "SNC": "N CA C CB O - - - - - SG - - - - - - - - - - - - - - - - ND OE - - - - - - - OXT",
        "SME": "N CA C CB O CG OE - - - - - - - - - - - - CE - - - - - - - - - - S - - - - - OXT",
        "TYQ": "N CA C CB O CG - - - - - - CD1 CD2 - N5 - - - - CE1 CE2 - - - - - - - OZ - OH CZ - - - OXT",
        "MHO": "N CA C CB O CG - - - - - - - - - - OD1 - SD CE - - - - - - - - - - - - - - - - OXT",
        "FTR": "N CA C CB O CG - - - - - - CD1 CD2 - - - - - - - CE2 CE3 - NE1 - - F CH2 - - - - CZ2 CZ3 - OXT",
        "TRQ": "N CA C CB O CG - O6 - - - - CD1 CD2 - - - - - - - CE2 CE3 - NE1 - O7 - CH2 - - - - CZ2 CZ3 - OXT",
        "EEP": "N CA C CB O CG - - - O1 - - CD1 CD2 - - - - - - - - - - O2 - - - - - - - - - - - OXT",
        "4HH": "N CA C CB O - CJ CK OG CL1 - - - - CL2 CL3 CM CO CP - - - CQ CS CT NN NR O1P O2P O3P OM ON - OR P SU OXT",
        "3FG": "N CA C CB O - CG1 CG2 - - - - CD1 CD2 - - OD1 OD2 - - - - - - - - - - - - - - CZ - - - OXT",
        "TOX": "N CA C CB O CG - - - - - - CD1 CD2 - O1 - - - - - CE2 CE3 - NE1 - O2 - CH2 - - - - CZ2 CZ3 - OXT",
        "AGM": "N CA C CB O CG - - - - - CD - - - - - - - - - CE2 - - NE1 - - - - NH1 NH2 - CZ - - - OXT",
        "CCS": "N CA C CB O - - - - OZ1 SG CD - - - - - - - CE - - OZ2 - - - - - - - - - - - - - OXT",
        "NIY": "N CA C CB O CG - - - - - - CD1 CD2 - - - - - - CE1 CE2 - NN - - O1 - - - O2 OH CZ - - - OXT",
        "V5N": "N CA C CB O CG - - - - - - - CD2 ND1 - - - O2 - CE1 - - - - NE2 - - - - - - - - - - OXT",
        "HY3": "N CA C - O - - - - - - - - - - C3 - - - - - - - C4 - - - C5 - - - O2 - - - - OXT",
        "OMY": "N CA C CB O CG - CL - - - - CD1 CD2 - - - - - - CE1 CE2 - - - - - - - OCZ - - CZ - - ODE OXT",
        "P1L": "N CA C CB O - C10 - - C11 SG - - - C12 C13 C14 - C15 - - - C16 C17 C18 C19 C20 C21 - C22 C7 C8 - C9 - O7 OXT",
        "4BF": "N CA C CB O CG - - - - - - CD1 CD2 - BR - - - - CE1 CE2 - - - - - - - - - - CZ - - - OXT",
        "MGN": "N CA C - O CG - - - - - CD - - CB1 - - - - - - - - CB2 - NE2 OE1 - - - - - - - - - OXT",
        "MP8": "N CA C CB O CG - - - - - CD - - - - - - - CE - - - - - - - - - - - - - - - - OXT",
        "004": "N CA C CB O - CG1 CG2 - - - - CD1 CD2 - - - - - CE - - - - - - - - - - - - - - - - OXT",
        "0AF": "N CA C CB O CG - - - O1 - - CD1 CD2 - - - - - - - CE2 CE3 - NE1 - - - CH2 - - - - CZ2 CZ3 - OXT",
        "5CT": "N CA C CB O CG C1 - C2 - - CD - - C3 - C4 - - CE - - - - N1 - - - - - - - - O1 - NZ OXT",
        "ASA": "N CA C CB O CG - - - - - - - - - - OD1 OD2",
        "IYR": "N CA C CB O CG - CC - - - CD - - - - - - - CE - - - - CF CH - - IE - - OF - - - - OXT",
        "TRX": "N CA C CB O CG - - - - - - CD1 CD2 - - - - - - - CE2 CE3 - NE1 OH2 - - CH2 - - - - CZ2 CZ3 - OXT",
        "5OH": "N CA C CB O - - - - CQ - - - - CR CS - NP - - - - - - NQ - - - NR - OS - - - - - OXT",
        "SEB": "N CA C CB O - - - OG - - - - - - CH1 OD1 OD2 SD CE - - CI1 - - - - CI2 CH2 - - - CZ CJ - - OXT",
        "DAH": "N CA C CB O CG - - - - - - CD1 CD2 - - - - - - CE1 CE2 - - - - - OE2 - - - OH CZ - - - OXT",
        "TBG": "N CA C CB O - CG1 CG2 - - - - - - - - - - - - - - - - - - - - CG3 - - - - - - - OXT",
        "ALO": "N CA C CB O - - CG2 - OG1 - - - - - - - - - - - - - - - - - - - - - - - - - - OXT",
        "DDZ": "N CA C CB O - - - - OG1 - - - - - - - - - - - - - - - - - - - OG2 - - - - - - OXT",
        "KCR": "N CA C CB O CG - - CH - - CD - - - - - CH3 - CE - - - - - - - CX - - - OH - - CY NZ OXT",
        "GLZ": "N CA C - O",
        "IIL": "N CA C CB O - CG1 CG2 - - - - CD1 - - - - - - - - - - - - - - - - - - - - - - - OXT",
        "ML3": "N CA C CB O - - - - CM1 SG CD - - - - - - CM2 CE - - - - - - - CM3 - - - - - - - NZ OXT",
        "PPN": "N CA C CB O CG - - - N1 - - CD1 CD2 - - - O1 - - CE1 CE2 - - - - - - - - - - CZ - O2 - OXT",
        "SLL": "N CA C CB O CG - - - - - CD - - CK - - CL - CE - - - - - - CP - - CX OP1 OP2 - - OX NZ OXT",
        "TYI": "N CA C CB O CG I1 - - - - - CD1 CD2 - - - - - - CE1 CE2 - - - - - I2 - - - OH CZ - - - OXT",
        "CSU": "N CA C CB O - - - - - SG - - - - - OD1 OD2 - - - - - - - - - - OD3 S - - - - - - OXT",
        "CYG": "N CA C CB O - CG1 - C1 CA1 SG - CD1 - - CB1 - - N1 - - - - - - - - OE2 - - - - - O1 O2 - OXT",
        "ILX": "N CA C CB O - CG1 CG2 - OG1 - - CD1 - - - OD1 - - - - - - - - - - - - - - - - - - - OXT",
        "OAS": "N CA C CB O - - - OG - - - - - - - - - - - - - - - - - C1A C2A - - OAC - - - - - OXT",
        "HRG": "N CA C CB O CG - - - - - CD - - - - - - - - - - - NE - - - - - NH1 NH2 - CZ - - CG' OXT",
        "OMT": "N CA C CB O CG - - - - - - - - - - OD1 OD2 SD CE - - - - - - - - - - - - - - - - OXT",
        "PBF": "N CA C CB O CG CI1 CI2 CK1 - - - CD1 CD2 - - - - - - CE1 CE2 CK2 CL - CN1 CT - - - - ON2 CZ - - - OXT",
        "API": "N CA C - O - - C3 - C4 - - - - C5 - C6 - C7 - - - N6 - - - - - - - - O3 - - O4 - OXT",
        "HIP": "N CA C CB O CG - O1P - - - - - CD2 ND1 - - O2P - - CE1 - O3P P - NE2 - - - - - - - - - - OXT",
        "MIS": "N CA C CB O - - - OG - - - - - - - - - - - - - C1 - C2 C3 - O1P - - O2P O3P - P - - OXT",
        "ALN": "N CA C CB O - CG1 CG2 - CD3 - - CD1 CD2 - CZ1 - - - - CE1 CE2 CE3 - - - - - - - - - - CZ2 - - OXT",
    },
    "glycan": {
        "NAG": "C2 C1 C3 C4 C5 C6 O1 - O3 O4 O5 O6 C7 C8 N2 O7",
        "BMA": "C2 C1 C3 C4 C5 C6 O1 O2 O3 O4 O5 O6",
        "MAN": "C2 C1 C3 C4 C5 C6 O1 O2 O3 O4 O5 O6",
        "FUC": "C2 C1 C3 C4 C5 C6 O1 O2 O3 O4 O5",
        "GLC": "C2 C1 C3 C4 C5 C6 O1 O2 O3 O4 O5 O6",
        "GAL": "C2 C1 C3 C4 C5 C6 O1 O2 O3 O4 O5 O6",
        "BGC": "C2 C1 C3 C4 C5 C6 O1 O2 O3 O4 O5 O6",
        "SIA": "C1 C2 C3 C4 C5 C6 - O2 - O4 - O6 C7 C8 - O7 C9 C10 C11 N5 O1A O1B O8 O9 O10",
        "NDG": "C2 C1 C3 C4 C5 C6 O1 - O3 O4 O5 O6 C7 C8 N2 O7",
        "XYP": "C2 C1 C3 C4 C5 - O1 O2 O3 O4 O5",
        "GLA": "C2 C1 C3 C4 C5 C6 O1 O2 O3 O4 O5 O6",
        "A2G": "C2 C1 C3 C4 C5 C6 O1 - O3 O4 O5 O6 C7 C8 N2 O7",
        "NGA": "C2 C1 C3 C4 C5 C6 O1 - O3 O4 O5 O6 C7 C8 N2 O7",
    },
}


def _build_raw_vocabulary() -> tuple[dict[str, np.ndarray], dict[str, tuple[str, ...]]]:
    """Construct RFD4's static 147-token Atom37 slot layouts without importing atomworks."""
    token_atoms: dict[str, np.ndarray] = {}
    for group, residues in _VOCABULARY_LAYOUTS.items():
        if group not in TOKEN_TYPE_IDS:
            raise ValueError(f"Unknown vocabulary token type: {group}")
        for name, layout in residues.items():
            atoms = [atom if atom != "-" else "" for atom in layout.split()]
            occupied = [atom for atom in atoms if atom]
            if not 1 <= len(atoms) <= 37 or len(set(occupied)) != len(occupied):
                raise ValueError(f"Invalid 37-slot atom layout for {name!r}")
            token_atoms[name] = np.array(atoms + [""] * (37 - len(atoms)))
    return token_atoms, {group: tuple(residues) for group, residues in _VOCABULARY_LAYOUTS.items()}


TOKEN_ATOM_LAYOUTS, RESIDUES_BY_TOKEN_TYPE = _build_raw_vocabulary()
NCAA_NAMES: tuple[str, ...] = RESIDUES_BY_TOKEN_TYPE["ncaa"]
GLYCAN_NAMES: tuple[str, ...] = RESIDUES_BY_TOKEN_TYPE["glycan"]
LOCAL_LATENT_RESIDUES: tuple[str, ...] = tuple(
    name for name in TOKEN_ATOM_LAYOUTS if name not in ("<A>", "<G>")
)


@functools.lru_cache(maxsize=1)
def _build_unified_encoding() -> Any:
    """Lazily build ``TokenEncoding`` so module import never pulls in atomworks/torch."""
    from atomworks.constants import AA_LIKE_CHEM_TYPES, DNA_LIKE_CHEM_TYPES, RNA_LIKE_CHEM_TYPES
    from atomworks.ml.encoding_definitions import TokenEncoding

    return TokenEncoding(
        token_atoms=TOKEN_ATOM_LAYOUTS,
        chemcomp_type_to_unknown=(
            dict.fromkeys(AA_LIKE_CHEM_TYPES, "UNK")
            | dict.fromkeys(DNA_LIKE_CHEM_TYPES, "DN")
            | dict.fromkeys(RNA_LIKE_CHEM_TYPES, "N")
        ),
    )


def __getattr__(name: str) -> Any:
    if name == "UNIFIED_ATOM37_ENCODING":
        encoding = _build_unified_encoding()
        globals()["UNIFIED_ATOM37_ENCODING"] = encoding
        return encoding
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), "UNIFIED_ATOM37_ENCODING"})


_MISSING_DEFAULT = object()


@dataclass(frozen=True)
class ConditionDefinition:
    """Static metadata for one RFD4 / AtomWorks condition."""

    full_name: str
    aliases: tuple[str, ...]
    _default_value: Any

    @property
    def default_value(self) -> Any:
        """Return the condition's default value, resolving MISSING lazily."""
        if self._default_value is _MISSING_DEFAULT:
            from atomworks.io.utils.standard_annotations.base import _DefaultValue

            return _DefaultValue.MISSING
        return self._default_value


_CONDITION_DEFINITIONS: tuple[ConditionDefinition, ...] = (
    ConditionDefinition("condition_hotspot_1_atom", ("C_HOT", "mask_hotspot_1_atom"), False),
    ConditionDefinition("condition_rasa-binned_1_atom", ("C_RAS",), 0),
    ConditionDefinition("condition_secondary-structure_1_residue", ("C_SEC",), 0),
    ConditionDefinition("condition_hbond_1_atom", ("C_HB",), 0),
    ConditionDefinition("condition_pistack_1_atom", ("C_PISTACK", "mask_pistack_1_atom"), False),
    ConditionDefinition("condition_pication_1_atom", ("C_PICATION",), 0),
    ConditionDefinition("condition_saltbridge_1_atom", ("C_SALT",), 0),
    ConditionDefinition("condition_hydrophobic_1_atom", ("C_HPHOB", "mask_hydrophobic_1_atom"), False),
    ConditionDefinition("condition_metal-coord_1_atom", ("C_MCOORD",), 0),
    ConditionDefinition("condition_index-group_1_token", ("C_IDXGRP",), _MISSING_DEFAULT),
    ConditionDefinition("condition_cath-label_1_residue", ("C_CATH",), "x.x.x.x"),
    ConditionDefinition("condition_InternalCoordinate_1_atom", ("C_INTCRD",), np.nan),
    ConditionDefinition("condition_CoordinateGroup_1_atom", ("C_CRDGRP",), _MISSING_DEFAULT),
    ConditionDefinition("condition_ChainCentroid_1_atom", ("C_CENTROID",), np.nan),
    ConditionDefinition("condition_basepair_2_residue", ("C_BP",), _MISSING_DEFAULT),
    ConditionDefinition("condition_na-ss-state_1_residue", ("C_NA_SS_STATE",), 0),
    ConditionDefinition("condition_coordinate_1_atom", ("C_CRD",), np.nan),
    ConditionDefinition("condition_sequence_1_residue", ("C_SEQ",), "<M>"),
    ConditionDefinition("condition_index_1_residue", ("C_IDX",), True),
)

RFD4_CONDITION_REGISTRY: dict[str, ConditionDefinition] = {
    cond.full_name: cond for cond in _CONDITION_DEFINITIONS
}

_CONDITION_ALIAS_TO_FULL: dict[str, str] = {}
for _cond in _CONDITION_DEFINITIONS:
    _CONDITION_ALIAS_TO_FULL[_cond.full_name] = _cond.full_name
    for _alias in _cond.aliases:
        _CONDITION_ALIAS_TO_FULL[_alias] = _cond.full_name


def resolve_condition_name(name: str) -> str:
    """Map a condition full name or alias to its canonical full name."""
    full_name = _CONDITION_ALIAS_TO_FULL.get(name)
    if full_name is not None:
        return full_name
    raise KeyError(
        f"unknown condition {name!r}; known: {sorted(RFD4_CONDITION_REGISTRY)} + aliases"
    )


def get_condition_default(full_name: str, fallback: Any = 0) -> Any:
    """Return the default value for a condition full name, or ``fallback``."""
    cond = RFD4_CONDITION_REGISTRY.get(full_name)
    return cond.default_value if cond is not None else fallback


CANONICAL_AA3_TO_1: dict[str, str] = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}
CANONICAL_AA1_TO_3: dict[str, str] = {v: k for k, v in CANONICAL_AA3_TO_1.items()}
CANONICAL_NON_GLY_AAS: frozenset[str] = frozenset(
    aa for aa in CANONICAL_AA3_TO_1 if aa != "GLY"
)


@functools.lru_cache(maxsize=1)
def encoding_tables() -> tuple[
    dict[int, str],
    dict[str, int],
    dict[str, tuple[str, ...]],
    dict[str, dict[str, int]],
]:
    """Return cached atom37 vocabulary tables built from ``TOKEN_ATOM_LAYOUTS``."""
    idx_to_token = {idx: str(tok) for idx, tok in enumerate(TOKEN_ATOM_LAYOUTS)}
    token_to_idx = {tok: idx for idx, tok in idx_to_token.items()}
    token_atoms: dict[str, tuple[str, ...]] = {}
    atom_slot_map: dict[str, dict[str, int]] = {}
    for res_name in CANONICAL_AA3_TO_1:
        raw_atoms = TOKEN_ATOM_LAYOUTS.get(res_name)
        if raw_atoms is None:
            continue
        slots = tuple(str(a).strip() for a in raw_atoms)
        token_atoms[res_name] = slots
        atom_slot_map[res_name] = {an: s for s, an in enumerate(slots) if an}
    return idx_to_token, token_to_idx, token_atoms, atom_slot_map


@functools.lru_cache(maxsize=1)
def canonical_aa_token_indices() -> tuple[np.ndarray, tuple[str, ...]]:
    """Return ``(token_idx_array, aa3_tuple)`` for the 20 canonical amino acids."""
    _, token_to_idx, _, _ = encoding_tables()
    aa3_names = tuple(CANONICAL_AA3_TO_1.keys())
    idx_arr = np.array([token_to_idx[aa3] for aa3 in aa3_names], dtype=np.int32)
    return idx_arr, aa3_names


def aa_idx_from_logits(
    seq_logits: np.ndarray, *, canonical_only: bool = False
) -> np.ndarray:
    """Convert ``(..., V)`` sequence logits into ``np.int32`` token indices."""
    logits = np.asarray(seq_logits)
    if logits.ndim < 1 or logits.shape[-1] == 0:
        raise ValueError(
            f"seq_logits must have ndim >= 1 and non-empty vocab axis, got {logits.shape}"
        )
    if not canonical_only:
        return np.argmax(logits, axis=-1).astype(np.int32)
    canon_idx, _ = canonical_aa_token_indices()
    if int(canon_idx.max()) >= logits.shape[-1]:
        raise ValueError(
            f"seq_logits vocab size {logits.shape[-1]} is smaller than canonical "
            f"token index {int(canon_idx.max())}"
        )
    best_pos = np.argmax(logits[..., canon_idx], axis=-1)
    return canon_idx[best_pos].astype(np.int32)


def decode_sequence(aa_pred_idx: Sequence[int] | np.ndarray) -> str:
    """Decode integer atom37 token indices into a 1-letter amino acid string."""
    idx_to_token, _, _, _ = encoding_tables()
    return "".join(
        CANONICAL_AA3_TO_1.get(idx_to_token.get(int(idx), ""), "X")
        for idx in aa_pred_idx
    )
