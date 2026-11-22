# LoupMD

LoupMD runs molecular dynamics with pretrained [MACE](https://github.com/ACEsuit/mace) potentials on NVIDIA GPUs.
The model, the neighbour list and the integrator run in one C++/CUDA engine, and a whole MD step is replayed as a
CUDA graph. The Python package loads a model by label, exports it to the engine's format, checks it against
PyTorch MACE, and writes the trajectory and a report. The runtime needs no PyTorch and no CUDA compiler.

```python
import loupmd as lm

result = lm.md("structure.cif", model="omat0-medium", temperature_K=300, steps=10_000, output="run")
print(result.summary)
```

The same run from the command line:

```bash
loupmd md structure.cif --model omat0-medium --temperature 300 --steps 10000
```

## What it does

- NVT, NVE and NPT molecular dynamics with the thermostats and barostats of ASE, on the GPU.
- Relaxation of positions and of the cell (ASE's LBFGS and FIRE, and its `FrechetCellFilter`).
- Monte Carlo swaps, transmutations and displacements between MD steps.
- Cells too large for the GPU, split into tiles.
- The D3 dispersion correction, with a choice of damping, three-body term and long-range sum.
- An ASE calculator and drop-in ASE MD and optimiser classes.
- LAMMPS: `pair_style loupmd`, `pair_style loupmd/kk` and `run_style loupmd`, in the package ML-LOUPMD of the
  repository's `lammps/` folder (GPL-2.0, built into LAMMPS, not in the wheel;
  [its guide](https://github.com/FZWINGEL-UBT/LoupMD/blob/release/v1/lammps/README.md)).

Every model runs in float32 on the engine. Before a run LoupMD can compare energies, forces and stress with PyTorch
MACE in float64 on rattled copies of your structure (`check="gate"`, `loupmd validate`): the gate allows three
times the error of float32 MACE.

## Install

```bash
pip install "loupmd[export]"    # the engine, and PyTorch and MACE to export a model the first time it runs
loupmd doctor                   # checks the GPU, the driver, the libraries and the model files
```

`pip install loupmd` alone installs the engine without PyTorch; it runs models that are already exported.

It needs Linux x86_64 (glibc 2.28 or newer) or WSL2, an NVIDIA GPU of compute capability 8.0 or newer with a
driver for CUDA 13, and Python 3.10 or newer. The
[install guide](https://fzwingel-ubt.github.io/LoupMD/install/) has the details.

This release (0.0.2) has been verified from its wheel on an RTX 5060 Ti (compute capability 12.0) only. The wheel
also holds code for compute capability 8.0, 8.6, 8.9, 9.0 and 10.0, which is untested from the wheel in this
release (`docs/validation/release-0.0.2.md` in the repository).

## Documentation

The documentation is at <https://fzwingel-ubt.github.io/LoupMD/>: install, quickstart, guides, the command-line
and Python reference, and "Coming from FastMACE". Its sources are in `docs/` of the
[repository](https://github.com/FZWINGEL-UBT/LoupMD) and build with `mkdocs build --strict`
(`pip install -e ".[docs]"`). The runnable examples are in `examples/`.

## Licence

LoupMD's own code is MIT-licensed (`LICENSE`). The code that follows ASE is LGPL-2.1-or-later, as ASE is: the
optimisers, and in the engine the thermostats, the barostats and the minimiser. The compiled engine library
(`libloupmd.so`) contains them and is distributed under LGPL-2.1-or-later as a whole; its source is the repository
at the release's tag. The tensor-core GEMM kernels compiled from CUTLASS headers are BSD-3-Clause. `NOTICE.md`
lists every file of each, the origins of the data, and the licences of the run-time dependencies. Each MACE model
keeps its own licence, which `loupmd models` prints. The LAMMPS package in `lammps/` is GPL-2.0, as LAMMPS is
(`lammps/LICENSE`); it is not part of the wheel.
