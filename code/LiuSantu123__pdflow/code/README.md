# pdflow

Reproducible protein-design workflow: **backbone -> sequence -> predicted structure -> metrics -> archive**.

`pdflow` wraps RFdiffusion4 and six structure predictors through their own conda
environments. It never imports predictor packages, so a broken or conflicting
environment cannot break the rest of the pipeline.

```
design / ingest        sequence design        prediction                 scoring                 archive
-----------------      -----------------      --------------------       --------------------    -----------------
RFD4  -----------\                            AF3 (default)              confidence (pTM/iPTM)   best.cif
RFD3  ------------+-->  one FASTA per   --->  Boltz2                --->  PAE, interfaces   ---> full_data.json
BoltzGen ---------/     design, all in         Protenix2                  ipSAE, dSASA, SC        designs.csv
                        sequences/             OpenDDE                    US-align, motif RMSD
                                               Mol-1                      tmol, physchem
                                               ESMFold2
```

Every record carries its provenance:

- backbone: `<campaign>__<designer>__s<seed>__<index>[__<tag>]`
- sequence: `<backbone>__<method><NNN>`
- FASTA header: `><seq_id>|<chain> chain=A backbone=<backbone> designer=<designer> method=<method>`
- prediction: `<seq_id>__<predictor>__m<rank>`

The archive keeps only the best predicted structure per design and one
`full_data.json` with every model's metrics. Sequences and final backbones are
kept; all predictor intermediates can be deleted by `finalize`.

## Install

```bash
# Native profile: every tool runs in its own conda env
bash scripts/bootstrap.sh

# Blackwell acceleration profile: uses the Claude/Blackwell kits
bash scripts/bootstrap.sh -- --profile kit
```

The bootstrap script creates the `pdflow` conda env from `environment.yml`,
installs the package editable, and runs the first-time wizard. Manual equivalent:

```bash
conda env create -f environment.yml
conda activate pdflow
pip install -e .
pdflow setup --profile native      # or: --profile kit
pdflow doctor
```

`pdflow setup` detects the conda base, model root, kit root and US-align path,
then writes a concrete `backends.yaml`. Override any of them with
`--conda-base`, `--model-root`, `--kit-root`, `--af3-root`, `--usalign`.
`pdflow init` is a native-profile alias. `pdflow doctor` checks every binary,
script, checkpoint directory and runs US-align once. See
[docs/AGENT_SETUP.md](https://github.com/LiuSantu123/pdflow/blob/HEAD/docs/AGENT_SETUP.md) for the agent-oriented checklist.

## Backend configuration

All tool paths live in `backends.yaml` (repo root, or
`~/.config/pdflow/backends.yaml`). Two templates are shipped:

- [config/backends.native.example.yaml](https://github.com/LiuSantu123/pdflow/blob/HEAD/config/backends.native.example.yaml) —
  native conda environments, no acceleration kits.
- [config/backends.example.yaml](https://github.com/LiuSantu123/pdflow/blob/HEAD/config/backends.example.yaml) — Blackwell
  acceleration profile with `ptxv2kit` / `boltz2kit` and kit launchers.

Both are tokenized and materialized by `pdflow setup`; do not edit the templates
in place. The generated config contains:

| Backend | Called through | Notes |
|---|---|---|
| RFdiffusion4 | `rfd4-generate` | Hydra overrides; weights must be local or in HF cache |
| AlphaFold 3 | `run_alphafold.py` | MSA + templates; `--run_data_pipeline=false` |
| Boltz-2 | `boltz predict` | dedicated `boltz2kit` venv (`torch 2.12/cu130`); kit fast |
| Protenix 2 | `protenix pred` | dedicated Blackwell venv (`torch 2.13/cu130`, `LAYERNORM_TYPE=torch`); PAE via `--need_atom_confidence True` |
| OpenDDE | `opendde pred` | stock env + kit fast; query-only MSA fallback |
| Mol-1 | `mol pred` | same JSON dialect; set `MOL_ROOT_DIR` |
| ESMFold v1 | `run_esmfold.py` | single-chain only, no MSA; needs `--fp32` on this OpenFold build |
| ESMFold2 | `esmfold2_overlay` via `scripts/esmfold2_50.sh` | batches single-chain protein inputs with the local ESMFold2 and ESMC-6B checkpoints |
| tmol | `tmol` env | score / minimize / relax |
| US-align | standalone binary | used for global and per-chain RMSD/TM-score |

Each predictor block accepts `extra_args`, which are appended verbatim.

## Campaign layout

```
campaign.yaml
inputs/                        # RFD4 condition spec, target structures, MSA, templates
backbones/                     # final backbones only (RFD3 no-seq / RFD4 seq / BoltzGen refold)
sequences/
  all.fasta                    # every designed sequence, provenance in the header
  <seq_id>.fasta               # one file per design (all chains)
predictions/<seq_id>/<predictor>/    # intermediates (deleted by finalize)
final/<seq_id>/
  best.cif                     # best model across all predictors
  full_data.json               # every predictor/model, metrics, provenance
designs.csv                    # one row per design x predictor (best model each)
manifest.jsonl                 # backbone -> source -> sequence provenance
```

`pdflow new --campaign runs/my-campaign` creates the skeleton. Copy
`config/campaign.example.yaml` to `campaign.yaml` and edit it.

## Quickstart (existing backbones)

```bash
pdflow new --campaign runs/demo
# copy final backbones into a directory
pdflow ingest --campaign runs/demo --designer rfd4 --input /path/to/rfd4_samples
pdflow predict --campaign runs/demo --predictors af3,boltz2
pdflow score --campaign runs/demo
pdflow finalize --campaign runs/demo
```

For backbones without sequences (RFD3), `ingest` sets `needs_seqdesign` and
`pdflow seqdesign` runs the configured MPNN command. Fill in
`design.mpnn.command` first.

### Ingest rules

- `--designer rfd4`: keeps every final design and reads sequences from the CIF.
- `--designer rfd3`: keeps the no-sequence backbone; pair it with `seqdesign`.
- `--designer boltzgen`: keeps both the raw design backbone and the refolded
  structure. Point `--input` at the narrow final/refold directory if a run
  contains additional intermediates.

## Design with RFdiffusion4

```yaml
design:
  engine: rfd4
  input: inputs/binder.yaml          # annotated CIF or condition spec
  num_designs: 10
  extra: ["~metrics"]                # keep RFD4's refolding off
```

```bash
pdflow design --campaign runs/demo
```

RFD4 writes `design_runs/rfd4/inference_samples/`; `pdflow` imports only that
directory, copies the final backbones and writes sequences.

## Prediction: trimmed design vs full-length target

Binder campaigns design against a trimmed target but predict against the
full-length target with its MSA:

```yaml
targets:
  T1:
    full: inputs/target_full.cif
    msa: inputs/target.a3m
    templates: []                    # AF3 only
    design_chain: A                  # chain in the RFD4 backbone
    predict_chain: A                 # chain in the prediction job
    kind: protein                    # optional: protein | dna | rna (auto-detected)
```

`build_job` drops the designed target chain and inserts the full-length chain
with `msa` attached. DNA/RNA targets are detected from residue names and written
as `dna`/`rna` (`dnaSequence`/`rnaSequence`) for every backend. AF3 receives
`unpairedMsa` + optional `templates`; Boltz-2 receives an `msa:` path;
Protenix/OpenDDE/Mol-1 receive `precomputed_msa_dir` with `non_pairing.a3m`. If
no MSA is supplied:

- AF3 gets an empty MSA,
- Boltz-2 gets a query-only a3m,
- Protenix/OpenDDE/Mol-1 run their own MSA search when available.

### Blackwell acceleration

Measured on representative complexes: 7r6r (245 tokens) for Protenix and
Boltz-2; a 199-aa two-chain smoke complex for OpenDDE. Conditions: 1 sample,
seed 42, RTX 5070 Ti, warm JIT cache.

| Backend | stock | exact | fast | fast speedup |
|---|---:|---:|---:|---:|
| Protenix 2 | 70.8 s | 47.2 s | 45.8 s | 1.55x |
| Boltz-2 | 53.6 s | 45.8 s | 41.8 s | 1.28x |
| OpenDDE | 108.0 s | — | 67.2 s | 1.61x |

Accuracy checks:

- Protenix `fast` vs stock: RMSD 0.04 A, TM 0.99995.
- Boltz-2 `exact` vs stock: bitwise identical (RMSD 0, TM 1.0).
- Boltz-2 `fast` vs stock on 7r6r: RMSD 0.73 A, TM 0.9849; on a low-confidence
  no-MSA complex it can diverge more, so validate per campaign.
- OpenDDE `fast` vs stock on the smoke complex: RMSD 0.02 A, TM 0.99997.

Setup notes:

- Boltz-2 and Protenix use dedicated pinned venvs (`boltz2kit`, `ptxv2kit`).
  OpenDDE reuses its stock env.
- Boltz-2's `exactln` lever cannot apply on this stack; the kit exits 3 after
  writing a complete prediction. `pdflow` accepts that by
  `accept_returncodes: [0, 3]` and records `partial: true`.
- OpenDDE builds its fast LayerNorm for sm120 only; the host's `10.3` arch list
  is overridden with `TORCH_CUDA_ARCH_LIST=12.0`.
- First run of a mode pays JIT compilation; `MODEL_OPT_JIT_ROOT` keeps caches
  warm.

**ESMFold2:** add `esmfold2_overlay` to the campaign's `score.predictors` and
enable that backend in `backends.yaml`. It uses a separate ESM environment and
loads the model once for all eligible inputs to `pdflow predict`. The existing
`esmfold2` key still selects ESMFold v1 for compatibility with older campaigns.
See [ESMFold2 setup](https://github.com/LiuSantu123/pdflow/blob/HEAD/docs/AGENT_SETUP.md#esmfold2-overlay) for the launcher's
configuration and commands.

## Metrics

For every predictor and every diffusion sample:

**Global / per chain**

- `ptm`, `iptm`, `mean_pae`, `mean_plddt`
- per chain: `ptm` (`chain_ptm` / `chains_ptm`), `plddt`, intra-chain `mean_pae`
- chain-pair: `iptm` from `chain_pair_iptm`; reversed value when available

**Interface** (per chain pair, heavy atoms < 5 A)

- `ipae`: mean PAE over interface residue pairs, both directions
- `ipsae_ref`: reference ipSAE-like score
  `mean(1/pae * 1/(1 + (d/d0)^2)) * 100`, with
  `d0 = max(1.24*(N_iface-15)^(1/3)-1.8, 1.0)`; documented as an approximation
- `delta_sasa = SASA(A) + SASA(B) - SASA(AB)` (Shrake-Rupley, probe 1.4 A)
- `sc_approx`: mean `dot(n_a, -n_b)` over cross-chain atom pairs < 5 A, where
  normals come from the local 10 A centre of mass; `sc_fraction` is the fraction
  of positive (complementary) contacts. This is **not** the Lawrence-Colman
  statistic.

**Against the design backbone**

- US-align global RMSD and TM-score
- US-align per-chain RMSD and TM-score (`score.align_chains`)
- motif RMSD on shared CA atoms (`score.motif`), Kabsch superposition

**Energy and sequence**

- tmol beta_nov2016 total score and per-term breakdown (`score | minimize | relax`)
- molecular weight, GRAVY, pI, charge at pH 7.4, aromaticity, instability index,
  helix/turn/sheet fraction, cysteines, N-glycosylation sequons, hydrophobic
  fraction, longest hydrophobic stretch, low-complexity fraction

The ranking score is a weighted sum of iPTM, pTM, pLDDT/100 and a PAE term; weights
are in `metrics.weights`. Models with non-finite coordinates are recorded with
`error` and `ranking_score = -1`.

## Reproducibility

- One conda environment (`pdflow`) for orchestration and metrics.
- Every predictor runs in its own environment; no shared imports.
- `pdflow doctor` is the single pre-flight check.
- `full_data.json` stores every model's metrics and the original structure path,
  plus the exact predictor/model rank used for `best.cif`.
- `designs.csv` is a flat table for downstream filtering. `final_structure`
  points at the archived `best.cif`; `error` is populated for predictors that
  were skipped or failed, and such rows are never marked `is_best`.
- `finalize` deletes only intermediates (`predictions/`, `design_runs/`), never
  final backbones or sequences.

## Known limitations on the reference machine

- **Protenix 2.0** needs the dedicated Blackwell stack. The stock conda env
  (`torch 2.7.1+cu128`, `cuequivariance-ops-cu12 0.8.0`) produces all-NaN
  coordinates on sm_120. The reference machine uses
  `/home/liusantu/.venvs/ptxv2kit` (`torch 2.13.0+cu130`) with
  `LAYERNORM_TYPE=torch`; the stock fast-LayerNorm extension is not sm_120-safe.
  Protenix writes `token_pair_pae` only when `--need_atom_confidence True` is
  passed; the config already includes it. `kalign` is copied into the venv for
  template realignment.
- **RFD4** works with the local bundle
  `/home/liusantu/hf-bundle` (`default_extra` in `backends.yaml`). Without those
  overrides it tries `nvidia/RFD4-Proteina` on Hugging Face.
- **ESMFold** needs `extra_args: ["--fp32"]` with the installed OpenFold build;
  fp16 hits a NaN in `compute_tm`. It only handles single protein chains.
- **US-align** must run with `LD_LIBRARY_PATH` cleared on hosts that inject an
  older `libstdc++` (`usalign.clean_ld_library_path: true`).
- **tmol** ligand typing is limited; protein complexes score reliably.
- `sc_approx` and `ipsae_ref` are documented approximations, not published
  reference implementations.

## Adding a predictor

1. Add a block under `predictors:` in `backends.yaml`.
2. Add a runner in `src/pdflow/predict.py` (`run_<name>`), register it in
   `RUNNERS`.
3. Make sure the output directory contains at least one `.cif`/`.pdb`; the
   generic discovery in `metrics.discover_models` handles the rest.
4. Add confidence parsing only if the JSON keys differ from the standard
   `ptm / iptm / plddt / pae / chain_ptm / chain_pair_iptm` set.

## Tests

```bash
pip install pytest
pytest -q
```

The tests cover provenance headers, target replacement, input writers, US-align
parsing and physicochemical metrics; they do not require a GPU.
