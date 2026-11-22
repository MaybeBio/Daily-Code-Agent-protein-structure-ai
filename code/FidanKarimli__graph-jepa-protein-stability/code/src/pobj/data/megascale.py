"""Load the MegaScale ddG labels and the matching wild-type structures.

Facts verified on 2026-11-20 (scripts/inspect_megascale.py, inspect_structures.py):
  * 271,231 single substitutions over 298 proteins (train 239 / val 31 / test 28),
    plus 1,481 `wt` reference rows which we drop. 271,231 + 1,481 = 272,712, the
    number quoted by the ThermoMPNN paper.
  * Splits are protein-disjoint.
  * ddG_ML sign: POSITIVE = stabilizing. Kept as-is, never flipped.
  * Every structure's sequence equals the csv's wt_seq, so `pos` is 1-based into both
    and node index = pos - 1. All single chain A, no missing backbone atoms.
"""
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

AA = "ACDEFGHIKLMNPQRSTVWY"
AA_IDX = {a: i for i, a in enumerate(AA)}

AA3 = {"ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q", "GLU": "E",
       "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F",
       "PRO": "P", "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V"}

SINGLE = r"^([A-Z])(\d+)([A-Z])$"
SPLITS = ("train", "val", "test")

RAW_DIR = Path("data/raw/thermompnn")
PDB_DIR = Path("data/raw/megascale_pdbs/AlphaFold_model_PDBs")

BACKBONE = ("N", "CA", "C", "O")


def load_labels(raw_dir: Path | str = RAW_DIR,
                splits: Sequence[str] = SPLITS) -> pd.DataFrame:
    """-> DataFrame[WT_name, mut_type, wt_aa, pos, mut_aa, ddG, wt_seq, split].

    `pos` is 1-based. Node index into the structure is pos - 1.
    """
    frames = []
    for sp in splits:
        x = pd.read_csv(Path(raw_dir) / f"mega_{sp}.csv", index_col=0, low_memory=False)
        x = x[x.mut_type.str.match(SINGLE)]                       # drops the 'wt' rows
        x = x[["WT_name", "mut_type", "ddG_ML", "wt_seq"]].copy()
        x["split"] = sp
        frames.append(x)
    df = pd.concat(frames, ignore_index=True)

    m = df.mut_type.str.extract(SINGLE)
    df["wt_aa"], df["pos"], df["mut_aa"] = m[0], m[1].astype(int), m[2]
    df["ddG"] = df.ddG_ML.astype(float)                           # positive = stabilizing
    return df.drop(columns=["ddG_ML"])


def read_pdb(path: Path | str) -> tuple[str, np.ndarray]:
    """Backbone parse of one pdb file.

    -> (seq: str of length N, coords: float32 [N, 4, 3] for N/CA/C/O)

    Residues that are not one of the 20 standard amino acids, or that are missing a
    backbone atom, are dropped. None of the MegaScale structures lose anything this way
    (checked), but experimental structures such as SCOPe regularly do.
    """
    residues = {}
    for line in Path(path).read_text().splitlines():
        if not line.startswith("ATOM") or line[16] not in (" ", "A"):
            continue
        atom = line[12:16].strip()
        if atom not in BACKBONE:
            continue
        key = (line[21], int(line[22:26]), line[26])              # chain, resnum, icode
        r = residues.setdefault(key, {"aa": AA3.get(line[17:20], "X"), "xyz": {}})
        r["xyz"].setdefault(atom, (float(line[30:38]), float(line[38:46]), float(line[46:54])))

    kept = [r for r in residues.values()
            if r["aa"] in AA_IDX and len(r["xyz"]) == len(BACKBONE)]
    seq = "".join(r["aa"] for r in kept)                          # file order == sequence order
    coords = np.array([[r["xyz"][a] for a in BACKBONE] for r in kept],
                      dtype=np.float32).reshape(len(kept), len(BACKBONE), 3)
    return seq, coords


def load_structures(names: Iterable[str],
                    pdb_dir: Path | str = PDB_DIR) -> dict[str, tuple[str, np.ndarray]]:
    """-> {WT_name: (seq, coords[N, 4, 3])} for the given names."""
    out = {}
    for name in sorted(set(names)):
        out[name] = read_pdb(Path(pdb_dir) / name)
    return out
