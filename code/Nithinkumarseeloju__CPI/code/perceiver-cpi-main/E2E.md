# Local score and pose checks

Measured in the C-drive checkout on 19 November 2026. The test client called the same score and job endpoints as the browser. For every successful job it downloaded the SDF, receptor PDB and metadata, checked the ligand connectivity and finite 3D coordinates, and checked the PLIP contacts against the result. All affinity scores below use the Davis model.

| Input | Receptor | Receptor cache | Score (pKd) | Vina (kcal/mol) | Pose | PLIP contacts | Wall (s) | Failure |
|---|---|---|---:|---:|---|---:|---:|---|
| Erlotinib / EGFR | RCSB PDB 1m17 | miss | 6.739 | -7.128 | yes | 7 | 45.58 | — |
| Benzoic acid / FKBP12 (FASTA) | RCSB PDB 1fkl | miss | 5.166 | -5.626 | yes | 10 | 10.14 | — |
| Aspirin / FKBP12 (lowercase and line break) | RCSB PDB 1fkl | hit | 5.172 | -5.8 | yes | 8 | 8.95 | — |
| Gefitinib / EGFR (1210 residues) | RCSB PDB 4i22 | miss | 8.401 | -9.086 | yes | 7 | 48.67 | — |
| Ethanol / FKBP12 | RCSB PDB 1fkl | hit | 5.161 | -2.237 | yes | 3 | 5.15 | — |
| Adenine / ubiquitin | facebook/esmfold_v1 | miss | 5.150 | -3.431 | yes | 4 | 354.35 | — |
| Erlotinib / supplied 645-residue fragment | facebook/esmfold_v1 | hit | 6.739 | -6.354 | yes | 5 | 150.11 | — |

## Stage timings in seconds

Stage times are summed across candidate structures and pockets. A dash means that the stage was skipped or included in its parent. Pose generation includes ligand preparation, Vina, export and validation. Wall time also includes the score request, queueing, polling and artifact verification. Timings reflect other work running on the laptop.

| Input | Score | Input validation | Lookup | Template selection | ESMFold | P2Rank | Receptor preparation | Ligand preparation | Vina | Export | Pose generation | PLIP | Motion |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Erlotinib / EGFR | 8.775 | 0.001 | 0.097 | 0.036 | — | — | 3.401 | 0.106 | 28.699 | 1.607 | 31.089 | 0.695 | 0.013 |
| Benzoic acid / FKBP12 (FASTA) | 0.567 | 0.001 | 0.025 | 0.008 | — | — | 2.305 | 0.018 | 2.994 | 2.468 | 5.578 | 0.434 | 0.017 |
| Aspirin / FKBP12 (lowercase and line break) | 0.635 | 0.001 | 0.023 | — | — | — | — | 0.013 | 5.816 | 1.580 | 7.463 | 0.142 | — |
| Gefitinib / EGFR (1210 residues) | 0.786 | 0.001 | 0.009 | 0.143 | — | — | 16.071 | 0.086 | 28.285 | 1.777 | 30.257 | 0.391 | 0.368 |
| Ethanol / FKBP12 | 0.630 | 0.001 | 0.004 | — | — | — | — | 0.007 | 1.696 | 1.700 | 3.460 | 0.115 | — |
| Adenine / ubiquitin | 0.751 | 0.001 | 0.150 | — | 333.822 | 5.001 | 2.249 | 0.050 | 2.797 | 1.788 | 5.334 | 0.600 | 0.005 |
| Erlotinib / supplied 645-residue fragment | 9.378 | 0.001 | 0.094 | 0.831 | — | — | — | 0.108 | 130.994 | 6.222 | 138.008 | 0.979 | 0.018 |

## Input and browser checks

The five valid input cases produced poses. The FASTA header and multiline lowercase forms were cleaned before both scoring and docking. The 1,210-residue EGFR used an experimental kinase domain for docking. The Davis affinity model reports its 499-residue input limit.
- Invalid SMILES — PASS. The score endpoint returned 422 and the docking service returned 400 for an unparseable compound.
- Invalid sequence — PASS. Both endpoints returned 422 and identified X and Z after stripping the digits.

The browser example submitted full-length EGFR, displayed 6.74 pKd, rendered 29 ligand atoms and listed seven PLIP contacts. The other trained models returned 11.816 on the KIBA scale and 6.562 pKi on Metz for that pair.

## Cache check

Two direct runs used full-length EGFR. Erlotinib forced receptor preparation. Aspirin reused the same verified 1M17 chain and ligand pocket after checking the candidates returned for the new compound. Both compounds were docked afresh.
- Erlotinib — 34.2 s across measured stages, cache miss, 7 PLIP contacts. [Full log](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/perceiver-cpi-main/.runtime/cache-first.log)
- Aspirin — 14.2 s across measured stages, cache hit, 10 PLIP contacts. [Full log](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/perceiver-cpi-main/.runtime/cache-second.log)

## PLIP on the solved 1M17 coordinates

Independently of redocking, the crystallographic ligand was selected by atom count and contacting chain. Its chemistry was assigned from erlotinib and its original coordinates were retained for PLIP. Distances below are in angstroms and residue numbers follow the PDB chain.

| Chain | Residue | Interaction | Distance (Å) |
|---|---|---|---:|
| A | LEU694 | hydrophobic contact | 3.60 |
| A | LEU764 | hydrophobic contact | 3.43 |
| A | THR766 | hydrophobic contact | 3.53 |
| A | LEU768 | hydrophobic contact | 3.99 |
| A | LYS721 | hydrophobic contact | 3.81 |
| A | LYS721 | hydrophobic contact | 3.74 |
| A | MET769 | hydrogen bond | 2.70 |

## Supplied 645-residue fragment

The example originally supplied ends at YGCTGPGLEGCPTNGPKIPS. The index suggested four PDB entries by sequence prefix. None had a bound ligand on a chain matching this fragment. The local pipeline therefore took the folding route.

[Full direct run log](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/perceiver-cpi-main/try_one.log)
Generated a Vina pose on facebook/esmfold_v1, with 7 PLIP contacts and a Vina score of -6.345 kcal/mol.

| Stage | Seconds |
|---|---:|
| input_validation | 0.01 |
| structure_lookup | 0.17 |
| experimental_site | 4.24 |
| folding | 1457.67 |
| pocket_prediction | 5.97 |
| receptor_preparation | 4.54 |
| ligand_preparation | 0.10 |
| vina | 128.96 |
| pose_export | 6.96 |
| pose_generation | 136.85 |
| contacts | 1.15 |

The first diagnostic used the inherited folded-receptor preparation. Inspection found eight residues involved in four spurious covalent links inferred from close ESMFold coordinates. The final preparation retained all 645 residues, used standard peptide/disulfide connectivity and excluded four search boxes overlapping the clashes. Each run below docked a new ligand against the prepared receptor. These remain computational hypotheses for the supplied fragment. The model returned 6.739 pKd for erlotinib and this fragment. Its first 499 residues match the full-length example.

| Ligand | Source | Receptor cache | Vina (kcal/mol) | PLIP contacts | Timed stages (s) |
|---|---|---|---:|---:|---:|
| [Erlotinib](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/perceiver-cpi-main/.runtime/fragment-final.log) | facebook/esmfold_v1 | hit | -6.354 | 5 | 189.0 |
| [Aspirin](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/perceiver-cpi-main/.runtime/fragment-aspirin.log) | facebook/esmfold_v1 | hit | -5.955 | 11 | 33.6 |

## Reproduce

Run these PowerShell commands from the project root. The first command prints the local URL.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_local.ps1
.\.venv\Scripts\python.exe test_inputs.py --no-cache
.\.venv\Scripts\python.exe try_one.py
```

Raw per-case results and timings are under .runtime/case-*.json. The 9 min 47 s baseline in the brief is historical. The cold full-length EGFR test in the table includes receptor preparation and fresh Vina docking. A new experimental PDB download requires access to RCSB.

## Server correction

The stale server on port 8000 failed while reading the optional data/davis.csv measurement table. It was replaced by the updated C-drive project using its own virtual environment. The current app is http://127.0.0.1:8000/ and docking is on port 8010. Browser verification returned 6.74 pKd, 29 displayed ligand atoms and seven PLIP contacts. All five checkpoint paths were verified under this project models folder. The page now reports non-JSON HTTP errors clearly.
