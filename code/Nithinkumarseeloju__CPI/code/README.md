# Bindsight CPI

Bindsight accepts a compound SMILES string and a protein amino-acid sequence,
then returns a Perceiver CPI binding-affinity prediction and a 3D binding pose.
The local 3D workflow uses an experimental receptor when a compatible structure
is available. Otherwise it uses ESMFold and P2Rank before docking with AutoDock
Vina. PLIP assigns the displayed protein-ligand interactions.

The application lives in [`perceiver-cpi-main`](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/perceiver-cpi-main). The
[`gfihm`](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/gfihm) folder is the retained 3D reference and data workspace.

## Run locally

Use Windows PowerShell with Python 3.12, then follow
[`perceiver-cpi-main/docs/LOCAL_SETUP.md`](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/perceiver-cpi-main/docs/LOCAL_SETUP.md).

```powershell
Set-Location .\perceiver-cpi-main
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_local.ps1
```

The five trained affinity checkpoints are included under
`perceiver-cpi-main/models`. Virtual environments, runtime job data, cached
structures and generated training outputs are excluded. GitHub's per-file limit
also prevents committing `gfihm/P-L.zip`, which is approximately 3.7 GB.

Measured end-to-end results are in
[`perceiver-cpi-main/E2E.md`](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/perceiver-cpi-main/E2E.md).
