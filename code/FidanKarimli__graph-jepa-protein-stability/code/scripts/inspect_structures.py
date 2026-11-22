"""Check that the structures and the labels describe the same proteins.

Labels come from the ThermoMPNN repo and structures from Zenodo, so nothing guarantees
they agree. A numbering offset here would send every mutation to the wrong residue
without raising an error.
"""

import glob
import os
import pandas as pd

RAW = "data/raw/thermompnn"
PDB_DIR = "data/raw/megascale_pdbs"
SINGLE = r"^[A-Z]\d+[A-Z]$"

AA3 = {
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


def read_pdb(path):
    """-> (sequence str, n residues missing a backbone atom, set of chain ids)"""
    residues = {}  # (chain, resnum, insertion code) -> info
    for line in open(path):
        if not line.startswith("ATOM"):
            continue
        if line[16] not in (" ", "A"):  # keep only the first alternate location
            continue
        key = (line[21], int(line[22:26]), line[26])
        r = residues.setdefault(key, {"aa": AA3.get(line[17:20], "X"), "atoms": set()})
        r["atoms"].add(line[12:16].strip())
    seq = "".join(r["aa"] for r in residues.values())  # file order
    missing = sum(
        1 for r in residues.values() if not {"N", "CA", "C", "O"} <= r["atoms"]
    )
    chains = {k[0] for k in residues}
    return seq, missing, chains


# ---- labels: single substitutions only
frames = []
for sp in ["train", "val", "test"]:
    x = pd.read_csv(f"{RAW}/mega_{sp}.csv", index_col=0, low_memory=False)
    x = x[x.mut_type.str.match(SINGLE)][["WT_name", "mut_type", "wt_seq"]].copy()
    x["split"] = sp
    frames.append(x)
df = pd.concat(frames, ignore_index=True)
proteins = df.drop_duplicates("WT_name")[["WT_name", "wt_seq", "split"]]

# ---- 1. does every labelled protein have a structure file?
files = {
    os.path.basename(p): p for p in glob.glob(f"{PDB_DIR}/**/*.pdb", recursive=True)
}
no_pdb = [n for n in proteins.WT_name if n not in files]
print(
    "pdb files:",
    len(files),
    "| labelled proteins:",
    len(proteins),
    "| without pdb:",
    len(no_pdb),
)
print("   examples without pdb:", no_pdb[:5])

# ---- 2. does each protein have exactly one wild-type sequence?
print("proteins with >1 wt_seq:", (df.groupby("WT_name").wt_seq.nunique() > 1).sum())

# ---- 3. structure sequence vs wt_seq
rows = []
for name, wt_seq, sp in proteins.itertuples(index=False):
    if name not in files:
        continue
    seq, missing, chains = read_pdb(files[name])
    rows.append(
        dict(
            name=name,
            split=sp,
            len_struct=len(seq),
            len_wt=len(wt_seq),
            equal=(seq == wt_seq),
            wt_inside_struct=(wt_seq in seq),
            missing_backbone=missing,
            chains="".join(sorted(chains)),
        )
    )
r = pd.DataFrame(rows)
print("\nstructure sequence == wt_seq:\n", r.equal.value_counts())
print("mismatches:\n", r[~r.equal].head(10))
print("chains per file:\n", r.chains.value_counts())
print("residues missing N/CA/C/O:", r.missing_backbone.sum())
print("protein length:\n", r.len_struct.describe())

# ---- 4. mutation alignment: is the wt letter at that position in wt_seq?
m = df.mut_type.str.extract(r"^([A-Z])(\d+)([A-Z])$")
df["wt_aa"], df["pos"], df["mut_aa"] = m[0], m[1].astype(int), m[2]
ok = [
    1 <= p <= len(s) and s[p - 1] == a for s, p, a in zip(df.wt_seq, df.pos, df.wt_aa)
]
print("\nmutations whose wt letter matches wt_seq[pos-1]:", sum(ok), "of", len(df))
print("mutations with wt letter == mutant letter:", (df.wt_aa == df.mut_aa).sum())
