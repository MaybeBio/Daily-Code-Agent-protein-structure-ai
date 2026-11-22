#!/usr/bin/env python
"""Write loupmd/data/d3_tables.npz, the D3 reference tables LoupMD ships (plan task S6-D04), from torch-dftd 0.5.1's
dftd3_params.npz (MIT; the values are Grimme's D3 reference data). Run once in an environment with torch-dftd:

    python tools/dev/make_d3_tables.py

Arrays, index = atomic number 0..94: nref [95] (reference systems with a C6), cnref [95, 5] (their coordination
numbers), rcov [95] (bohr, the 4/3 factor included), r2r4 [95], c6ref [95, 95, 5, 5] (hartree bohr^6, -1 where no
reference exists), r0ab [95, 95] (bohr).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "loupmd" / "data" / "d3_tables.npz"
MAXREF = 5


def main():
    import torch_dftd

    src = Path(torch_dftd.__file__).parent / "nn" / "params" / "dftd3_params.npz"
    d = np.load(src)
    c6ab, r0ab, rcov, r2r4 = d["c6ab"], d["r0ab"], d["rcov"], d["r2r4"]
    nel = c6ab.shape[0]
    nref = np.array([int((c6ab[z, z, :, :, 0].diagonal() > 0).sum()) for z in range(nel)], dtype=np.int32)
    cnref = np.zeros((nel, MAXREF))
    for z in range(nel):
        cnref[z, : nref[z]] = c6ab[z, z, : nref[z], 0, 1]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT, nref=nref, cnref=cnref, rcov=rcov.astype(np.float64), r2r4=r2r4.astype(np.float64),
                        c6ref=np.ascontiguousarray(c6ab[..., 0], dtype=np.float64),
                        r0ab=np.ascontiguousarray(r0ab, dtype=np.float64),
                        source=np.array(f"torch-dftd {torch_dftd.__version__} dftd3_params.npz (MIT)"))
    print(f"{OUT}: {OUT.stat().st_size / 1e6:.2f} MB, elements with references: {int((nref > 0).sum())}")


if __name__ == "__main__":
    main()
