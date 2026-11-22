> Historical preprocessing-stage report. The original model source was subsequently recovered and inference/docking were implemented. See the root README for current capabilities and limitations.

# Dataset preprocessing and 3D viewer

Completed on 15 November 2026 using local files in `H:\gfihm`.

## Results

| Dataset | Input examples | Accepted for prepared training pool | Other examples | Train | Validation | Test |
|---|---:|---:|---|---:|---:|---:|
| PDBbind | 19,037 | 17,479 | 1,556 view only; 2 failed | 13,983 | 1,748 | 1,748 |
| Davis | 30,056 | 25,226 | 4,830 removed or set aside | 20,071 | 2,553 | 2,602 |
| Kiba | 118,254 | 117,369 | 885 removed or set aside | 93,688 | 11,758 | 11,923 |
| Metz | 35,259 | 35,259 | 0 removed or set aside | 28,223 | 3,487 | 3,549 |

Accepted means passed the documented preprocessing filters, not proven free of all biological or experimental problems. No model was trained or validated scientifically in this task.

## What was done

1. Matched all 19,037 structure IDs to the protein-ligand index. There are zero unmatched IDs. The tar archive contains the index; the ZIP contains structures. The package README describes the 2020R1 overlap set reprocessed with the v2024 workflow, with index updates in August 2025. It is not the entire v2024 dataset.
2. Read all four structure files per ID (protein PDB, pocket PDB, ligand SDF and ligand MOL2), checking ZIP checksums. Validated finite protein coordinates and ligand chemistry with RDKit. Used the first protein model and highest-occupancy alternate atom location.
3. Preserved the common experimental coordinate frame. Used heavy atoms, ligand chemical bonds, formal charges, estimated ligand partial charges, and masks for unavailable features. No new ligand conformation or docking pose was generated.
4. Recomputed pockets as complete amino-acid residues with an atom within 6 angstroms of a ligand atom. Waters and separate cofactors/ions are omitted from pocket graphs. Original structures remain intact.
5. Saved NPZ graphs with directed distance connections up to 4.5 angstroms, separate ligand chemical bonds, and geometric protein-ligand contacts up to 4 angstroms. A distance contact is not automatically a hydrogen bond.
6. Made train/validation/test splits and checked overlap. CSV datasets are split by unique compound-protein pair; PDBbind groups complexes sharing any exact observed protein chain sequence.
7. Saved every accepted/view-only graph, pocket PDB, ligand SDF, metadata and row-level manifests. Built and browser-tested a local 3D viewer.

## Affinity labels

`p_affinity = -log10(affinity in mol/L)`. For example, 10gs has Ki=0.4uM, so its pKi is approximately 6.398. Kd, Ki and IC50 retain their types and must not silently be treated as the same assay. Smaller concentration corresponds to a larger p-value. Inequality signs reverse after this conversion. The 270 non-exact labels are retained as bounds but excluded from ordinary exact-label regression.

The prepared pool contains 6,453 Kd, 4,475 Ki and 6,551 IC50 examples. Separate assay-specific split files are in `processed/pdbbind/by_affinity_type/<Kd|Ki|IC50>/`. Use these for a single-assay target or explicitly include assay type in a suitable model.

The three original CSV score scales are not declared in their headers. Their numeric values were preserved without re-logging or rescaling. KIBA scores must not be treated as molar concentration merely because they are numbers. Confirm Davis and Metz score definitions from the data source before scientific interpretation. No scores were pooled across the three datasets.

The archive also contains only 387 old processed CSV rows (309/39/39), without PDB IDs. These were audited and not used to label structures; the complete ID-based index was used instead.

## Overlap and limitations

- PDBbind: zero PDB-ID overlap and zero exact observed protein-chain sequence overlap across the three splits.
- Identical ligand structures still overlap: 342 train/validation, 329 train/test, 112 validation/test. Similar protein sequences and similar chemical scaffolds were not clustered. These are not strict homology- or scaffold-disjoint benchmark splits.
- CSV datasets: zero exact compound-protein pair overlap across their new splits, but individual compounds and proteins can appear on both sides. These are pair splits, not cold-target or cold-compound splits.
- Exact pair overlaps between datasets: Davis/KIBA 1,001; Davis/Metz 406; KIBA/Metz 19,307. A shared pair is assigned to the same split across all three datasets. Do not count it as an independent external test example.
- Cross-dataset overlap with PDBbind is not established: the CSVs lack PDB IDs and their sequences may differ from crystallized fragments. Cross-dataset 3D generalization claims require additional mapping and overlap checks.
- New splits do not reproduce the splits used to train the supplied saved checkpoints. Evaluation of those checkpoints on these new test rows may include examples those models already saw.
- Missing protein atoms, protonation states, stereochemistry relative to experiment, metal coordination, sequence homology leakage and force-field readiness are not fully validated by this pipeline.

## How many datasets are needed?

**For the 3D viewer, one structural dataset is sufficient: the supplied PDBbind structure-plus-index package.** One valid complex is enough for a demonstration; 19,035 can be opened here. You do not need three additional datasets to show a pocket.

**For an affinity model, use a suitable labelled training collection and separate training, validation and test subsets.** These are three splits of a dataset, not a requirement to download three different datasets. The needed sample count depends on the model and the scientific goal; these counts do not guarantee accuracy.

**For all four datasets to support true 3D inputs, Davis, KIBA and Metz also need verified matched protein-ligand complex structures or a documented structure-prediction and docking workflow.** A predicted protein plus an independently generated compound shape does not establish the correct bound pose.

**For physical motion, an additional kind of data is required: a simulation trajectory.** Starting structures, protonation/force-field preparation, ligand parameters, solvent/ions, equilibration and simulation are required. Starting from a bound structure does not guarantee that ordinary simulation will capture the binding event itself.

## Tools

| Tool | Purpose | Status |
|---|---|---|
| Python 3.12 | Read archives, parse labels, create splits and serve viewer | Used |
| RDKit | Validate ligand/SMILES chemistry, ligand bonds, formal and estimated partial charges | Used |
| NumPy + SciPy | Store atom arrays, build pockets and distance connections | Used |
| 3Dmol.js | Local interactive protein/compound rendering and illustrative animation | Used; downloaded library kept locally |
| Playwright + installed Chrome | Browser tests, screenshots and animation checks | Used for verification |
| PLIP | Classify protein-ligand interactions such as hydrogen bonds with geometric/chemical rules | Optional; not run |
| GROMACS or another MD engine | Generate physical simulation trajectories after proper system preparation | Not run |

Documentation: [RDKit](https://www.rdkit.org/docs/RDKit_Book.html), [3Dmol.js](https://www.3dmol.org/doc/GLModel.html), [PLIP](https://plip-tool.biotec.tu-dresden.de/plip-web/plip/index), [GROMACS](https://manual.gromacs.org/current/user-guide/system-preparation.html), [PDBbind downloads](https://www.pdbbind-plus.org.cn/download).

## Open the viewer

From PowerShell:

```powershell
cd H:\gfihm
.\start_viewer.ps1
```

Open **http://127.0.0.1:8765/**. Stop the server with Ctrl+C. If PowerShell blocks scripts, run `.\.venv\Scripts\python.exe scripts\serve_viewer.py --port 8765` directly. The viewer reads local processed files and the source archive. It needs no internet after dependencies and the bundled library are installed.

Type a PDB ID such as `10gs`, rotate/zoom, show the full protein or pocket surface, inspect nearby residues, and play the approach illustration. Contact lines disappear during movement because their distances describe the original bound pose.

The animation is an artificial straight-line translation with a fixed protein. It is neither molecular dynamics nor a predicted binding pathway.

## Files and model integration

- `processed/pdbbind/manifest.csv`: all 19,037 results, labels, warnings, exclusion reasons and split membership.
- `processed/pdbbind/excluded.csv`: view-only and failed complexes, with reasons.
- `processed/pdbbind/complexes/<pdb_id>/`: `graph.npz`, `metadata.json`, `pocket.pdb`, `ligand.sdf`.
- `processed/<davis|kiba|metz>/`: cleaned `train.csv`, `val.csv`, `test.csv`, `summary.json`, and `excluded_rows.csv`.
- `reports/schema.json`: array names, feature meanings, masks, cutoffs and label conventions.
- `reports/ERRORS_SIMPLE.md`: errors in school-level language.
- `reports/data_validation.json`: independent checks on every emitted graph and the splits.
- `reports/viewer_validation.json`, `viewer_desktop.png`, `viewer_mobile.png`: browser verification.
- `reports/input_provenance.json`: source file sizes and SHA256 checksums.
- `scripts/preprocess.py`: reproducible preprocessing; run with `.\.venv\Scripts\python.exe scripts\preprocess.py --workers 6`.

The model source is absent. These are documented generic NumPy graph files, not a claim of compatibility with the supplied checkpoints. Use `scripts/load_graph_example.py` to inspect them. Integration requires the model forward method and data-loader code. The viewer works independently of the checkpoints.

Original input files were preserved. No checkpoint pickle was executed.

## Compound features for the three CSV datasets

Also saved 2,676 distinct ligand chemical graphs shared across the cleaned CSV datasets: Davis has 68 compounds, KIBA 2,061, and Metz 1,423 (some compounds appear in multiple datasets). These include atom types, formal charges, estimated partial charges, aromaticity, hybridization and chemical bonds. All partial-charge calculations succeeded for these compounds.

Join each split CSV to `processed/<dataset>/ligand_lookup.csv` using canonical `smiles`. Graph files are in `processed/ligands2d/`, with their schema in `reports/ligand2d_summary.json`. These graphs intentionally contain no XYZ coordinates, protein pockets or implied binding poses. Rebuild them with `.\.venv\Scripts\python.exe scripts\prepare_2d_ligands.py`.

To regenerate the written reports and assay-specific split files after preprocessing, run `.\.venv\Scripts\python.exe scripts\finalize_reports.py`. To verify outputs, run `scripts\verify_data.py` using the same interpreter; start the viewer before running `scripts\verify_viewer.py`.

## Verification results

- `data_validation.json`: PASS.

- `additional_validation.json`: PASS.

- `viewer_validation.json`: PASS.

The data validation checks every emitted 3D graph, recomputes every saved edge distance, verifies labels and split membership, and checks that missing charges are masked. The additional check validates all 2D compound graphs and assay-specific split files. Browser checks exercise rendering, surfaces, full-protein loading, animation, invalid-ID messages and the mobile layout. These are software/data consistency tests, not evidence of model accuracy or a physical binding pathway.
