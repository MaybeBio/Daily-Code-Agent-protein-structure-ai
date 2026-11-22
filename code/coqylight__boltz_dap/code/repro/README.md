# Hexamer Reproduction

**Historical workflow:** use the [root README's patched installation](https://github.com/coqylight/boltz_dap/blob/HEAD/README.md#installation)
for the current runtime. The older launcher and 25-prediction recipe below
are retained for reference and have not been revalidated against every current
change. Review its environment paths before use. For the new portable BF16
workflow, use [the full60 guide](https://github.com/coqylight/boltz_dap/blob/HEAD/docs/full60_bf16.md) instead.

This directory contains a **single-job reproduction** for the hexamer setting used to demonstrate Boltz-DAP on a large complex that is difficult to run on a single GPU.

## What this reproduces

- **Target class**: hexamer-sized protein complex
- **Launcher**: `torchrun --nproc_per_node=4`
- **Settings**:
  - `recycling_steps=10`
  - `sampling_steps=200`
  - `diffusion_samples=25`
  - `--use_potentials`
  - full PAE/PDE export enabled
- **Outputs**:
  - 25 CIF files
  - 25 confidence JSON files
  - 25 full PAE `.npz` files
  - 25 full PDE `.npz` files
  - chain-pair interaction tables (`iPTM`, mean `PAE`, mean `iPDE`)
  - a compact markdown report: `repro_report.md`

## Prerequisites

- 4 GPUs on one node
- The pinned patched Boltz v2.2.1 installation; adapt the older launcher's
  checkout/virtual-environment paths to that installation.
- An input YAML prepared separately (this repo does not bundle the experiment-specific input YAML)

## Run

Submit from the repository root:

```bash
INPUT_YAML=/absolute/path/to/1LP3_hexamer_from_trimer_fill.yaml \
BOLTZ_DIR=/absolute/path/to/boltz \
sbatch repro/hexamer_repro.sbatch
```

Optional environment variables:

- `REPO_DIR` — defaults to current working directory
- `OUT_DIR` — defaults to `repro/output/hexamer_af3_defaults`
- `CACHE_DIR` — defaults to `~/.boltz`
- `USE_MSA_SERVER=1` — defaults to `1`
- `SEED=42` — optional; only set this if you want stricter run-to-run reproducibility

Example with an explicit seed:

```bash
INPUT_YAML=/absolute/path/to/1LP3_hexamer_from_trimer_fill.yaml \
BOLTZ_DIR=/absolute/path/to/boltz \
SEED=42 \
sbatch repro/hexamer_repro.sbatch
```

## Expected outputs

Under `OUT_DIR`:

- `predictions/<record_id>/*.cif`
- `predictions/<record_id>/confidence_*.json`
- `predictions/<record_id>/pae_*.npz`
- `predictions/<record_id>/pde_*.npz`
- `predictions/<record_id>/chain_pair_metrics_all_models.tsv`
- `predictions/<record_id>/chain_pair_metrics_mean.tsv`
- `predictions/<record_id>/chain_pair_metrics_top_model.tsv`
- `repro_report.md`

See [example_report.md](https://github.com/coqylight/boltz_dap/blob/HEAD/repro/example_report.md) for a concrete example of the generated markdown report.

## Pass criteria

- Job exits with code `0`
- 25 CIF files are generated
- 25 confidence JSON files are generated
- 25 full PAE files are generated
- 25 full PDE files are generated
- Chain-pair summary tables are generated successfully

## Notes

- Seed is **optional** by design. For normal usage, leaving it unset is fine.
- If you only care about standard prediction outputs, you can still run the main entrypoint directly as described in the main README and `docs/GETTING_STARTED.md`.
