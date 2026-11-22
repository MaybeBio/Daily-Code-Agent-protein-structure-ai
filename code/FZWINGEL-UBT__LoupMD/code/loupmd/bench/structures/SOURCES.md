# Sources of the shipped structures

The benchmark (`loupmd bench`) and the accuracy gate (`loupmd validate`) read their structures from this folder
first and then from the folders of `$LOUPMD_BENCH_STRUCTURES`. `SrTiO3` and rocksalt NaCl are generated in code.
Each file here is byte for byte the file named as its source.

| File | What | Source and licence | SHA-256 |
| --- | --- | --- | --- |
| `water_216.extxyz` | Liquid-water starting box: 216 H2O, cubic 18.644 A, 0.997 g/cm3, 648 atoms. A lattice start with random orientations (seed 20261016), not an equilibrated liquid | Built by the authors' own script (`build_water_box.py`, 16 October 2026) from `ase.build.molecule("H2O")`; released with LoupMD under its MIT licence | `fb1dec83bfff0568a11d174c7785465be5cdff4361d96de7e314c07e331acc3a` |
| `urea_cod1008787.cif` | Urea, P-42_1m, neutron diffraction at 60 K, 16 atoms per cell | Crystallography Open Database entry 1008787 (Guth, Heger, Klein, Treutmann, Scheringer, Z. Kristallogr. 153, 237 (1980)); the COD's data are in the public domain (CC0), as the file's header states | `f95db254423e06ed6da2d013991b4967b1c78913bcaec85b7d1d2826fc92382f` |
| `naphthalene_cod2311090.cif` | Naphthalene, P2_1/c, X-ray diffraction at 80 K, 36 atoms per cell | Crystallography Open Database entry 2311090 (Hoser and Madsen, Acta Cryst. A 73, 102 (2017), doi:10.1107/S2053273316018994); public domain (CC0) | `fcfa0cc14c0ed167664be484bc38618f76a9b2a24084e63535821a635d377c85` |
| `paracetamol_cod2104364.cif` | Paracetamol form I, P2_1/n, X-ray diffraction at 100 K, 80 atoms per cell | Crystallography Open Database entry 2104364 (Bouhmaida, Bonhomme, Guillot, Jelsch, Ghermani, Acta Cryst. B 65, 363 (2009), doi:10.1107/S0108768109008271); public domain (CC0) | `3db1149c5f9d35d794f5cda8608b463cc7924f9c4d793eaf67d1cada5756d41a` |

The three COD files were downloaded from `https://www.crystallography.net/cod/<id>.cif` on 16 October 2026 and
renamed; their content is unchanged.

## Not shipped

`NbCl5_R2SCAN.cif` (the standard benchmark's second cell and the gate's default set) and the `NaCl` and `NaNbO3`
cells of the gate's `crystals` set are r2SCAN structures of the Materials Project (mp-23307, mp-22862, mp-3671).
They are not in the package until the Materials Project's terms of use have been checked for redistribution
(PLAN.md, decision O11). Put them into a folder named by `$LOUPMD_BENCH_STRUCTURES`; `loupmd bench --suite quick`
and the `families` suite for the models that run on `SrTiO3` or NaCl need no file.
