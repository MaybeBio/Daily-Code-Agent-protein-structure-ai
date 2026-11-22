# Claude-Accelerated Blackwell Protein Kit

Community-maintained, unofficial acceleration kit for protein-design workloads on NVIDIA Blackwell GPUs. This project is not affiliated with or endorsed by Anthropic.

Reproducible sm120 inference wrappers and kernel overlays for protein design
and structure prediction on NVIDIA RTX 50-series GPUs.

The project name is hardware-focused: RTX 50-series cards are Blackwell GPUs
with compute capability 12.0. This repository is a release bundle, not a
replacement for the upstream model projects. It carries optimization
overlays, pinned stock snapshots, small examples, and local launchers. Model
weights and large databases are never committed.

## Included kits

| Kit | Default route | Qualification result |
|---|---|---|
| AlphaFold 3 Torch / OF3 | `fast` | strict sm120 model gate passed |
| Boltz-2 | `fast` | warm and 480-token probe passed |
| BoltzGen | `fast` | design and inverse-folding warm passed |
| OpenDDE | `fast` | warm sm120 path passed |
| Protenix-v2 | `fast` | 693-token model gate passed |
| RFdiffusion3 | `fast` | warm sm120 path passed |
| [ESMFold2](https://github.com/LiuSantu123/claude-blackwell-protein-accel-kit/blob/HEAD/kits/esmfold2/README.md) | `blackwell` | tested on RTX 5090 32 GB: 13.09× over the tiled reference on one complex |

The original kits were qualified on an RTX 5070 Ti 16 GB (driver 616.92);
ESMFold2 was tested separately on an RTX 5090. RTX 50-series cards vary in
available memory. Run the relevant check on your own card before production use.

## Quick start

Use the Python environment that matches the selected kit's `STOCK.md`. Install
one kit into one environment; the upstream packages have different pins.

```bash
cd claude-blackwell-protein-accel-kit
bash scripts/check.sh af3
bash scripts/af3_50.sh
```

The other one-command examples are:

```bash
bash scripts/boltz2_50.sh
bash scripts/boltzgen_50.sh
bash scripts/opendde_50.sh
bash scripts/protenix2_50.sh
bash scripts/rfd3_50.sh
```

Each script accepts an input path and output directory as its first two
arguments. Extra arguments are passed to the selected runner.

ESMFold2 reuses an upstream environment and local checkpoints. Set
`ESMFOLD2_WEIGHTS` and `ESMFOLD2_ESMC` as described in its [kit guide](https://github.com/LiuSantu123/claude-blackwell-protein-accel-kit/blob/HEAD/kits/esmfold2/README.md):

```bash
bash scripts/check.sh esmfold2
bash scripts/esmfold2_50.sh examples/esmfold2 outputs/esmfold2-bw
```

## Installation pattern

After activating the matching environment, install the overlay and local
shared core:

```bash
bash scripts/install.sh af3
bash scripts/check.sh af3
```

Weights remain outside Git. Exact weight variables are documented in the
selected kit's `README.md` and `STOCK.md`; common examples include
`AF3_TORCH_PARAMS_DIR`, `BOLTZ_CACHE`, `BOLTZGEN_CACHE`, `OPENDDE_ROOT_DIR`,
`PROTENIX_ROOT_DIR`, and `RFD3_CKPT`.

For a persistent compile cache:

```bash
export MODEL_OPT_JIT_ROOT="$PWD/.jit"
```

## Reproducibility

- `kits/*/stock/PINS.json` records upstream releases and digests.
- `kits/common/opt_core` is the shared pinned runtime.
- `kits/*/configs/sm120.env` is the deployment profile used by the wrappers.
- `docs/SM120.md` records tile, warp, shared-memory, numerical, and model-gate
  evidence.
- `scripts/verify_tree.sh` checks the release tree for accidental weights,
  caches, Python bytecode, and large build artifacts.

The first run compiles Triton/CUDA kernels. Cold-start time is not a stable
inference benchmark; retain the cache before comparing throughput.

## Scope and limitations

This release targets Linux x86-64 with an NVIDIA driver and a CUDA-enabled
Python stack. It does not provide model weights, MSA databases, templates, or
an installer that guesses a Conda environment. AF3's converted OF3 weights are
not interchangeable with the official AF3 `af3.bin` weights. Some upstream
branches retain measured stock or inherited rows for unsupported shapes; the
runtime reports these explicitly instead of silently calling them native
sm120.

See `THIRD_PARTY_NOTICES.md` before redistributing a fork or binary build.
