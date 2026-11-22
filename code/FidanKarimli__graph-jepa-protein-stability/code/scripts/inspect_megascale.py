"""A first look at the ThermoMPNN MegaScale csv files: counts, splits, ddG sign.

Run before writing any loader, so the loader is built against what the files
actually contain rather than what a paper says they contain.
"""

import pandas as pd

RAW = "data/raw/thermompnn"
SINGLE = r"^[A-Z]\d+[A-Z]$"  # single substitution, e.g. E12Q

d = {
    sp: pd.read_csv(f"{RAW}/mega_{sp}.csv", index_col=0, low_memory=False)
    for sp in ["train", "val", "test"]
}

# 1. counts per split
for sp, x in d.items():
    s = x[x.mut_type.str.match(SINGLE)]
    print(
        sp,
        "rows:",
        len(x),
        "| single subs:",
        len(s),
        "| unique (protein, mutation):",
        len(s.drop_duplicates(["WT_name", "mut_type"])),
        "| proteins:",
        s.WT_name.nunique(),
    )
    print(
        "   other mut_type examples:",
        x.mut_type[~x.mut_type.str.match(SINGLE)].unique()[:8],
    )

# 2. splits must share no proteins
n = {sp: set(x.WT_name) for sp, x in d.items()}
print(
    "overlaps train/val, train/test, val/test:",
    len(n["train"] & n["val"]),
    len(n["train"] & n["test"]),
    len(n["val"] & n["test"]),
)

# 3. sign check, using the lab's own Stabilizing_mut label in val
v = d["val"][d["val"].mut_type.str.match(SINGLE)]
print(v.groupby("Stabilizing_mut").ddG_ML.describe())
print("fraction ddG_ML < 0:", (v.ddG_ML < 0).mean())
