# Perceiver CPI shared workbench

Local website for Davis, KIBA and Metz score prediction, verified protein-ligand structures, pocket inspection, illustrative ligand motion and known-pocket docking. Original inputs are preserved. The supplied checkpoints run through the recovered original model source in `model_source/`.

The site now uses the same Perceiver frontend design as `H:\siddu\frontend`: the animated pink hero, research introduction, dataset cards/filters, method section, navigation and footer. This project's real prediction, structure and BioEmu controls share that interface. Source and rebuild instructions are in [frontend/README.md](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/gfihm/frontend/README.md); no running server or frontend files from the other folder are needed. The existing model folders remain in place for the later model integration.

**Training:** see [TRAINING.md](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/gfihm/TRAINING.md) for tested commands, resume instructions and measured CPU time estimates.

## Open the project

From PowerShell in `H:\gfihm`:

```powershell
.\.venv\Scripts\python.exe scripts\cpi_app.py
```

Open **http://127.0.0.1:8765/**. Click **Show Davis result**, **Show KIBA result** or **Show Metz result**, then **Play**. Rotate by dragging; use the wheel to zoom. Playback includes pause, replay, speed and scrubbing. Stop the server with Ctrl+C. `start_cpi.ps1` is an equivalent launcher. Run one server on port 8765 at a time.

The **Browse the processed PDBbind structures** section opens any of the 19,035 available complexes independently of a CSV query. Its motion uses the same checked path planner. The results table reads current database counts.

Choose a dataset pair or enter SMILES and one protein sequence/FASTA record. Scores and structure jobs run independently. The displayed structure must match both inputs. Select docking to try a verified receptor chain/domain contained in the input protein sequence, or redocking to generate a new pose even when an experimental match exists.

### Sequence-based 3D prediction

The **Docking** route is separate from the affinity checkpoints: ESMFold predicts the protein, P2Rank ranks pockets and Vina docks the compound. On Windows, the app reuses a complete cached `pytorch_model.bin` under `%LOCALAPPDATA%\cpi-fold-gpu\huggingface\hub\models--facebook--esmfold_v1` instead of fetching a second checkpoint format. If no complete local checkpoint exists, the first run needs Hugging Face access and downloads the model. ESMFold uses bfloat16 on supported GPUs (otherwise float32), and jobs run one at a time to limit GPU memory use. With a 4 GB GPU, long sequences can take many minutes because model weights are offloaded. Sequences are limited to 1,022 residues; generated poses are predictions, not experimental structures. Specified SMILES stereochemistry is enforced, while unspecified stereocenters remain ambiguous and may be assigned by the generated pose.

## Actual results

| Dataset | Original rows retained | Searchable unique pairs | Scores computed for source pairs | Pairs with a ready pose | Pairs with playback |
|---|---:|---:|---:|---:|---:|
| Davis | 30,056 | 25,772 | 15 | 15 | 2 |
| KIBA | 118,254 | 117,657 | 22 | 22 | 10 |
| Metz | 35,259 | 35,259 | 17 | 17 | 9 |

Counts are the verified handoff snapshot, not a claim that all pairs have 3D results. Some pairs occur in multiple datasets. Remaining scores are available on demand but have not all been computed. Current counts appear on the site and at `/api/coverage`. Every source pair has a readiness row in `processed/<dataset>/pair_readiness.csv`.

PDBbind: **19,037** indexed complexes; **17,479** accepted for the prepared training pool, **1,556** view-only, **2** excluded. All **19,035** emitted graphs were checked. The training split has 13,983/1,748/1,748 examples. Ligand overlap remains across splits; these are not scaffold-disjoint or homology-disjoint benchmarks.

The separate filtered CSV training pools contain 25,226 Davis, 117,369 KIBA and 35,259 Metz pairs. Conflicting measurements are excluded from these training views but retained in the searchable source catalog. The generic XYZ graphs are **not inputs to the supplied 2D checkpoints**. Small training and resume checks were completed on all three CSV datasets. These are code checks, not full retraining or scientific accuracy validation.

## What is verified and what remains limited

- All three checkpoints load strictly and produce fresh scores. Recovered original test ordering was verified. Reproducing three original batches per dataset gave maximum absolute differences of 0.000192 Davis, 0.000334 KIBA and 0.000589 Metz. These **exceed the strict 0.0001 comparison tolerance**; numerical reproduction is not exact. Runtime differences remain unresolved. Live single-pair inference is deterministic, but the original model is sensitive to batch padding and can differ from its original multi-pair batches.
- The original encoder keeps the first 500 tokens, including special tokens. Truncation and the displayed protein-domain range are disclosed separately. Davis/Metz score units remain unverified; values are shown without invented concentration units. KIBA is labelled as a KIBA score.
- Experimental matching uses ligand stereochemistry/connectivity after charge normalization and an exact observed chain/domain sequence that participates in the pocket. Missing matches may reflect construct differences; they do not prove no structure exists.
- AutoDock Vina 1.2.7 with Meeko produced a real 2ITY known-pocket redocking result: **3.33 Angstrom symmetry-aware heavy-atom RMSD, n=1**, in the unchanged receptor frame. This is a limited demonstration, not evidence of general accuracy. Receptor preparation removes waters/metals/cofactors and is unsuitable for sites that require them without further preparation.
- Motion translates the actual final ligand with a fixed protein. Continuous geometric clearance is checked against heavy atoms, including original waters/cofactors. It is an **illustration, not molecular dynamics or a predicted binding pathway**. Buried pockets may allow only the final pose.
- PLIP assigned contacts for 10 of 50 analyzed experimental structures; 40 failed chemical-identity preparation. Those structures show geometric distances, without claiming hydrogen bonds. Errors are retained beside the structures.
- The project score environment is CPU-only; ESMFold uses the separate GPU environment described above. Sequence-based ESMFold/P2Rank/Vina docking is available for unmatched pairs, but it is a predicted static structure/pose, not a molecular-dynamics trajectory or measured affinity. No Boltz weights are installed.

One structural dataset is enough for the 3D demonstration: the supplied PDBbind structures plus their index. Three CSV datasets are not a requirement for displaying a pocket. Training, validation and test are separate subsets, not three additional datasets. General 3D coverage requires verified structures or a tested prediction workflow for the unmatched pairs.

## Reproduce preprocessing and resume jobs

The existing `.venv` is installed and tested. For dependency restoration in an existing Python 3.12 environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-app.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements-contacts.txt
```

These files pin the installed versions; a clean-machine reinstall has not been tested. `tools/vina.exe` is the tested Windows executable. Keep `models/`, `model_source/`, the original archives and CSVs with this project. Tests use the installed Chrome path recorded in their scripts.

```powershell
# Full rebuild; existing processed outputs are regenerated.
.\.venv\Scripts\python.exe scripts\preprocess.py --workers 6
# Continue structure processing after interruption, verifying source SHA256.
.\.venv\Scripts\python.exe scripts\preprocess.py --mode structures --resume --workers 6
# Populate/resume the lossless source catalog and exact structure matching.
.\.venv\Scripts\python.exe scripts\cpi_data.py
.\.venv\Scripts\python.exe scripts\cpi_audit.py
# Small verified batch; repeating it reuses successful results.
.\.venv\Scripts\python.exe scripts\cpi_batch.py --dataset davis --matched-only --limit 1 --scores
# All verified matches for a dataset; repeat with kiba and metz.
.\.venv\Scripts\python.exe scripts\cpi_batch.py --dataset davis --matched-only --scores
# Refresh actual coverage and every source pair's readiness CSV.
.\.venv\Scripts\python.exe scripts\cpi_finalize.py
```

Remove `--matched-only` to submit every valid source pair. Add `--method dock` for known-receptor docking or `--method redock` to force docking; these full batches have **not** been run. Omit `--scores` to run structure jobs only. Stop the web server before using `--recover` to resume interrupted batch jobs. Server startup also recovers queued/running jobs. Use one batch worker process at a time; SQLite persists results, but job deduplication is designed within one process. Protein-only receptor indexing commits each structure separately so website writes can continue.

The protein-only docking index covers 17,479 eligible structures, 21,077 contacting chains and 10,287 unique observed chain sequences. It can find receptors for new compounds independently of previous CSV ligand matches. Rebuild/resume it with `.\.venv\Scripts\python.exe scripts\build_receptor_index.py --workers 6`; candidates are independently verified with Biopython before docking.

## Tests and reports

With the site running:

```powershell
.\.venv\Scripts\python.exe scripts\verify_cpi_browser.py
.\.venv\Scripts\python.exe scripts\verify_cpi_final.py
.\.venv\Scripts\python.exe scripts\verify_cpi_display.py
.\.venv\Scripts\python.exe scripts\verify_completion.py
.\.venv\Scripts\python.exe scripts\verify_receptor_index.py
```

Browser checks cover all three datasets, score/checkpoint routing, ligand movement with a fixed camera/protein, pause/scrub, final-coordinate agreement within 0.0001 Angstrom, contact visibility, stale-response handling, mobile layout, invalid input, real docking and matching exports. Final checks also cover missing weights, duplicate submission and recovery. See `reports/cpi_browser_validation.json` and `reports/cpi_final_validation.json`.

Select **Export PyMOL scene** for the displayed result; unzip the download and run `@scene.pml` from its folder in PyMOL. Exported coordinates match the browser's final pose. PyMOL rendering itself was not tested.

- `reports/ERRORS_SIMPLE.md`: problems explained in everyday language.
- `reports/cpi_coverage.json`: counts and supported routes.
- `reports/cpi_source_audit.json`: every original row checked against its CSV.
- `reports/checkpoint_verification.json`: reference prediction comparisons.
- `reports/data_validation.json`, `additional_validation.json`: graph/split validation.
- `reports/schema.json`: atom features, masks, bonds and distance connections.
- `reports/PREPROCESSING_REPORT.md`: initial preprocessing details; current app behavior and model availability are described here.
- `processed/pdbbind/manifest.csv`, `excluded.csv`: per-complex status and reasons.
- `processed/cpi.sqlite`: measurements, pair identities, matches, scores and persistent jobs.

The app uses FastAPI, SQLite, PyTorch and the recovered model code; RDKit/Biopython/NumPy/SciPy for structures; 3Dmol.js for rendering; Vina/Meeko for docking; optional PLIP/OpenBabel for assigned contacts; Playwright/Chrome for browser verification. Full dependency versions are in `reports/application_versions.json`.


## BioEmu-2 remote structure and motion

The site now includes a separate BioEmu-2 panel for the selected protein/compound pair. Export its GPU input, run the bundled worker on a Linux NVIDIA GPU, then import the result ZIP to inspect the predicted pose, successive motion frames and nearby residues. See [BIOEMU2.md](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/gfihm/BIOEMU2.md) for setup and simple error explanations. Local import and browser checks use temporary synthetic fixtures; real GPU inference has not been run or connected from this Windows workspace.
