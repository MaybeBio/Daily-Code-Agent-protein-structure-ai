# Shared Perceiver CPI frontend

This is the Perceiver visual design from `H:\siddu\frontend`, connected to the score, structure, docking and BioEmu workflows in this project. The runtime is self-contained under `H:\gfihm`; it does not call port 5173 or read frontend assets from the other folder.

## Run the whole application

From `H:\gfihm`, run:

```powershell
.\start_cpi.ps1
```

Open http://127.0.0.1:8765/. One server serves the frontend and model APIs. The existing compiled frontend is included; Node is needed only when editing the landing page/theme.

## Edit and rebuild the frontend

```powershell
cd H:\gfihm\frontend
npm ci
npm run build
```

`npm run watch` rebuilds JS/CSS changes while you work; refresh the browser after a rebuild. Run `npm run build` after editing `index.html`. The build writes only `viewer/experience/` and the generated `viewer/cpi.html`. Edit the source `frontend/index.html`, not the generated copy.

## Shared frontend, separate model responsibilities

| Interface | Existing implementation | Output |
|---|---|---|
| Pair search and dataset selection | `scripts/cpi_data.py`, `/api/pairs` | Real Davis/KIBA/Metz source pairs |
| Affinity prediction | `scripts/cpi_inference.py`, `/api/predict` | Current dataset checkpoint score |
| Experimental structures / docking | `/api/jobs`, `/api/complex`, `/api/pose` | Verified structure matches or labelled predicted docking poses |
| 3D pocket viewer | `viewer/app.js`, `viewer/cpi.js` | Atom coordinates, pocket contacts, exports and illustrative approach |
| BioEmu-2 | `/api/bioemu2`, `viewer/bioemu2.js` | Exact-pair GPU input export and imported predicted motion |
| Landing page and navigation | `frontend/src/main.js`, `style.css`, `scene.js` | Shared Perceiver experience |

The hero uses the original procedural Three.js illustration. One shared SMILES and protein sequence feed the score model and 3D workflow from the same **Predict score and 3D** button. The two 3D choices are an exact-pair experimental structure, or sequence-based docking: ESMFold predicts the protein structure, P2Rank ranks up to five candidate pockets, and AutoDock Vina docks the compound at those sites. The folding runtime is isolated from the affinity-scoring environment and configured for CUDA with disk offload. On Windows, run `scripts\setup_structure_models.ps1` once to install the local runtime and P2Rank; Java 17+ and a working NVIDIA CUDA driver are required. The first docking request downloads about 16.9 GB of ESMFold weights. A 4 GB GPU may not fit the model even with offload, and disk-offloaded inference can be very slow. Results label predicted coordinates, P2Rank probabilities and Vina scores clearly; none is experimental evidence or measured affinity. After both jobs finish, **Download combined report** exports the score, inputs, ranked pocket results and (when available) protein, ligand, pocket and PyMOL scene files in one ZIP. BioEmu output is clearly distinguished from the illustrative approach.

The existing project `models/`, `model_source/`, `processed/` and `training_runs/` folders keep their current contents. No second affinity architecture or checkpoint set has been silently substituted or merged. When another model implementation is added later, give it its own backend route/checkpoint selection and identify its outputs; reuse this same frontend. Different models' scores must not be mixed under one label.

See `../BIOEMU2.md` for the remote Linux GPU steps. No BioEmu inference runs on this Windows server.

## Verification

Run from the project root:

```powershell
.\.venv\Scripts\python.exe scripts\verify_cpi_browser.py
.\.venv\Scripts\python.exe scripts\verify_bioemu2.py
.\.venv\Scripts\python.exe scripts\verify_shared_frontend.py
```

The first and third checks expect the application at port 8765. BioEmu import/playback checks use temporary synthetic fixtures and do not claim GPU inference. Screenshots and the shared-page report are under `reports/shared_frontend/`.
