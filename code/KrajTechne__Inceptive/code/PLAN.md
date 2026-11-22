# Inceptive: BindCraft2 → Optimus Design/Validation Pipeline on Modal

Status (2026-10-15): the pipeline works end to end on PD-L1. Design (BindCraft2) → validation (Optimus) → merged report all run on Modal from one config file. Next: parallel design, more targets. See `README.md` for how to use it; this file records how it is built, why, and what is left.

## 1. Goal

One command takes a config and produces ranked binders that have been independently re-predicted by other structure models. All persistent state lives on Modal Volumes.

```
inputs/configs_pipeline/<run>.yaml
   │
   ├─ run_design.py       BindCraft2 on a Modal GPU
   │     └─► inceptive-runs:/<run>/design/3_Ranked/{*.cif, !_Ranked.csv}
   │
   ├─ run_validation.py
   │     ├─ build_designs_csv (Modal, CPU): top N designs → Optimus CSV (chain B = binder)
   │     └─ launches optimus/modal_run_validation.py with OPTIMUS_OUTPUTS_VOLUME=inceptive-runs
   │           └─► inceptive-runs:/<run>/validation/{validation_summary.csv, ...}
   │
   └─ report.py (local)   joins both → results/<run>/final_report.csv (+ copy on the Volume)

run_pipeline.py chains the three and waits for validation to finish.
```

## 2. Decisions

- **Tools as git submodules**: `bindcraft2/` and `optimus/`, pinned to commits (pointer only in our repo). Clone with `--recurse-submodules`.
- **Flat repo**: scripts at the top level; `inputs/` (with `configs/` and `targets/`) is the only structured folder, reorganized by the user on 2026-10-16.
- **One YAML per run** with sections `design`, `selection`, `validate`, `report` and a shared `run_name`. Each step reads only its own section. Tool-specific settings pass straight through (`design.bindcraft` → BindCraft2 settings JSON; `validate` → Optimus `--config`), so we do not re-model their schemas.
- **Volumes**: `inceptive-runs` (everything per run) and `alphafold2-weights` (AF2 parameters, downloaded once).
- **Validation models**: OpenFold3 (`of3`) + ESMFold2. AF3 weights are not used (licensing).
- **Optimus is used unmodified except one upstream change**: the outputs Volume name is configurable via `OPTIMUS_OUTPUTS_VOLUME` (merged in Optimus PR #7). We call its CLI as a subprocess rather than importing it.
- **Code principles**: short single-purpose files, plain functions, Modal lines commented, all tunables in `inputs/configs_pipeline/` and `inputs/configs_bc2/`, `--dry-run` on every step, copy-paste to add a step.
- **Skipped for now**: automated tests (decided to defer).

## 3. As-built layout

| File | Purpose |
|---|---|
| `modal_app.py` | App, the two Volumes, `bindcraft_image` (ported from BindCraft2's Dockerfile), `bridge_image` (CPU) |
| `run_design.py` | Step 1. Compute (`gpu`, `timeout_hours`, optional `cpu`, `memory_gb`) comes from config via `with_options` |
| `run_validation.py` | Step 2. Bridge function + launches Optimus |
| `report.py` | Step 3. Merge + pass/fail against `report:` thresholds |
| `run_pipeline.py` | Runs steps in order; waits by counting finished jobs (results + failures rows) vs expected |
| `config_loader.py`, `volume_utils.py` | YAML loading; `modal volume get/put` helpers |
| `inputs/configs_pipeline/`, `inputs/configs_bc2/` | Run YAMLs (`configs_pipeline`) (`pdl1_denovo_test.yaml` smoke test, `il4_apo_run.yaml`, `il4_apo_run_mixed.yaml`, `ifng_heterodimer_cold_run.yaml`, `ifng_heterodimer_no_cold_run.yaml`, `ifng_heterodimer_cold_old_commit_run.yaml`) and BindCraft2 settings JSONs (`configs_bc2`: `IL4_apo.json`, `IL4_apo_mixed.json`, `interferon_gamma_heterodimer_sc.json`, `interferon_gamma_heterodimer_sc_no_cold.json`) |
| `inputs/targets/` | Target `.cif`/`.pdb` files; mounted into the design container at start-up (no image rebuild) |

## 4. Facts learned along the way

**BindCraft2**
- Needs a GPU (no CPU mode). Python ≥ 3.12, JAX 0.11 with the `cuda13` extra. Installed **editable** because `settings/` is found relative to the source tree. The image also needs the `ldconfig` step for the pip-installed CUDA libraries, or JAX silently runs on CPU.
- AlphaFold params (5.3 GB) download on first use into `BINDCRAFT_WEIGHTS` (we point it at the weights Volume).
- Built-in targets (e.g. `hPDL1`) need no target file. Output: `1_Trajectories/`, `2_Refolded/`, `3_Ranked/` with `!_Ranked.csv`, plus `.cif` complexes. **Binder = chain B, target = chain A** (verified). Campaigns resume when re-run with the same project folder.
- Parallelism is built in: it uses every visible GPU, starts workers per GPU (auto-packs several per card by GPU memory), and each worker logs to `design/workers/`. Overrides: `workers_per_gpu`, `max_workers_per_gpu`, `design_workers`, `gpu_ids`. Its host-RAM cap reads the **node's** memory, not the container limit, so for multi-GPU runs set `cpu` and `memory_gb` explicitly.

**Optimus**
- Local entrypoint checks the input CSV on your machine (needs `biotite`, `gemmi`, `pandas`, `numpy` locally) and then `.spawn()`s a remote driver, so it returns immediately. Results are flushed every 10 finished jobs and again at the end, so "summary exists" does not mean "done"; we count rows instead.
- Images list local modules by hand and need `LigandMPNN/` in the build context. Several dependencies are unpinned or taken from `main` branches, so a rebuild could change behavior.
- `designs_from_structures.py` has no special handling for cyclic peptides or VHH (read as ordinary chains).

**Environment gotchas** (also in README troubleshooting)
- Windows: Modal's CLI needs `PYTHONUTF8=1`. Git's CRLF conversion breaks Optimus's `get_model_params.sh` inside the Linux image (fix: `core.autocrlf=false` in the submodule, or a `.gitattributes` in Optimus).
- Modal ships only the entrypoint file to containers; helper modules need `.add_local_python_source(...)` on the image.
- The repo sits in OneDrive, which can corrupt `.git`; move it if git errors appear.

## 5. Milestones

| # | Milestone | Status |
|---|---|---|
| 1 | Recon of both repos | Done |
| 2 | BindCraft2 on Modal (PD-L1, 1×A100) | Done: 2 designs from 8 trajectories |
| 3 | Optimus validation launched from our repo | Done: 4 jobs (2 designs × of3/esmfold2), 0 failures |
| 4 | Bridge (BindCraft2 `.cif` → Optimus CSV) | Done: chain B verified |
| 5 | End to end + report | Done: a fresh PD-L1 run (`pdl1_e2e_test`, config since removed as a duplicate of `pdl1_denovo_test.yaml`) ran unattended; both designs passed |
| 6 | Hardening | README done. Tests deferred. Resume/retry not yet exercised |
| 7 | Parallel design | Config support added (`gpu: "A100:4"`, `cpu`, `memory_gb`); not yet run. See §6 |
| 8 | More targets / modalities | Wiring done and dry-run OK for IL-4 apo and IFN-γ heterodimer (JSON + structures from the user); no GPU run yet |

## 6. Next steps

1. ~~Parallel design test~~ Done 2026-10-16/17: IL4 and IFN-γ ran on 4×A100 (8 and 4 BindCraft2 workers; IL4 accepted 4 designs after 21 trajectories, IFN-γ accepted 0 of 60). `pdl1_parallel_test.yaml` was removed; `il4_apo_run.yaml` is the 4-GPU example.
2. **New targets (IL-4 apo, IFN-γ heterodimer)**: wiring done (2026-10-16): `design.bindcraft_json` loads the user's JSON, structures are found by file name in `inputs/targets/`, run YAML keys override JSON keys. Open items before the first real runs: (a) IFN-γ JSON targets chain A only of a two-chain file (A 243 res, B 242 res, numbering starts at 0): confirm that is intended and that the coldspot numbers match BindCraft2's numbering; (b) Colab leftovers `workers_per_gpu: 1` / `auto_multi_gpu: false` keep design on one GPU, so override them for parallel runs; (c) confirm the binder chain letter in the output (`selection.binder_chain`) for the two-chain target.
3. **Other modalities** (VHH, cyclic peptide, scFv): confirm the bridge's chain assignment and sequence extraction on real output, since Optimus's script does not special-case them. Multi-chain binders (e.g. oligomers) would need the same check.
4. **Optimus follow-ups (user's repo)**: add `.gitattributes` with `*.sh text eol=lf`; pin the unpinned dependencies; optionally let `run_validation` read its CSV from a Volume so our wrapper no longer needs a local round trip.
5. **Hardening**: retries on preemption for the design function (BindCraft2 resumes, so retrying is safe); a cost estimate in `--dry-run`; per-run cleanup of large intermediate folders (`compile_cache`, `1_Trajectories`) if Volume size becomes an issue.
6. **Later**: parameter sweeps (one config per sweep point), several targets in one run, a results viewer.

## 7. Risks and cautions

- **Validation is a filter, not proof of binding.** The validation models are related to the design model, and best-of-N sampling biases scores upward (Optimus's own caveat). Pass thresholds (`report:`) default to Optimus's gates (ipTM ≥ 0.8, ipSAE ≥ 0.61).
- **Small test runs prove the plumbing only.** The PD-L1 runs used 2 designs, 1 seed; every design passing is not informative. Real campaigns need more designs and seeds.
- **Reproducibility** depends on pinned submodule commits and on Optimus's unpinned image dependencies (see §4).
- **Cost**: GPUs are billed. Multi-GPU design multiplies the hourly rate; check throughput before scaling. H100 is Optimus's default for validation; a cheaper `gpu_type` may do for exploration.
