# Third-party notices

LoupMD is distributed under the MIT licence (`LICENSE`), with the exceptions this file lists. The code that
follows ASE is under LGPL-2.1-or-later (owner decisions O6 of 15 November 2026 and O35 of 18 November 2026,
`PLAN.md` §1.1), and because the engine's integrators are part of it, the compiled library `libloupmd.so` is
distributed under LGPL-2.1-or-later as a whole. The compiled GEMM kernels are BSD-3-Clause. The LAMMPS package in
`lammps/` is GPL-2.0, as LAMMPS is (`lammps/LICENSE`, the owner's decision of 19 November 2026): it is built into
LAMMPS, reaches the engine only through `include/loupmd.h`, and is not in the wheel. The files below are binaries or generated sources; each
is listed with what it was made from. `tests/test_notice.py` checks that every tracked binary and generated file
appears here.

## Compiled GEMM kernels (`cubins/`)

Tensor-core GEMM kernels that the engine loads at run time as autotune candidates (`src/engine.cu`; never used
for models with long-range terms). They are compiled from NVIDIA CUTLASS headers (BSD-3-Clause, © 2017-2026
NVIDIA CORPORATION & AFFILIATES, <https://github.com/NVIDIA/cutlass>; licence text in `cubins/LICENSE.cutlass`).

Two sets are tracked. The `tf32x3_hyb_*` cubins are the ones the engine loads by default on every GPU but those
of compute capability 8.0; they were built from FastMACE's sources `fastmace/kernels/cutlass/tf32x3_sm80.cu` and
`hybrid_f16.h` (MIT, © 2026 Fabian Zwingel) with `-DFM_HYBRID_F16`. The `gemm_tc_*` cubins are LoupMD's own
builds from `cubins/src/gemm_tc.cu` and `cubins/src/hybrid_f16.h` (derived from the same FastMACE sources), with
their recipe in `cubins/src/build_gemm_tc.sh` and its record in `cubins/src/gemm_tc.build.txt`.
`gemm_tc_hyb_sm80.cubin` is the default on compute capability 8.0 (the A100); the engine loads the others only
when `LOUP_HYBRID_CUBIN` names them (testing, until they are gated and adopted). `cubins/src/fastf32_rn.h`
(a 3xTF32 variant that rounds the split to nearest; it derives a class from CUTLASS's `MmaTensorOpFastF32`) is
compiled into none of the tracked cubins: the recipe does not set `LOUP_TC_SPLIT_RN`.

| File | SHA-256 | Origin | Build record |
| --- | --- | --- | --- |
| `cubins/tf32x3_hyb_sm80.cubin` | `c5dd8728d23987ad8ae3883f5968956f665cd7a9ecabe7b8de27499a865e4d14` | byte-identical to FastMACE's `fastmace/kernels/cutlass/tf32x3_hyb_sm80.cubin` | FastMACE `tf32x3_sm80.build.txt`: CUTLASS v4.8.1, commit `2c85f497547eb441f0fe80bfb0fb2e6f9add1719`; nvcc 13.3 (V13.3.33); 11 November 2026 |
| `cubins/tf32x3_hyb_sm90.cubin` | `c4f97a4002dc53a4e2f7fc6c3afa7ac42edc04ff5b9e5b471f1d2d6e4cac7cd7` | byte-identical to FastMACE's `tf32x3_hyb_sm90.cubin` | as above |
| `cubins/tf32x3_hyb_sm120.cubin` | `9a949b7065906f5284e1190a0994576d1d186e3f723592488b54f81d59396f1f` | the same sources compiled for `sm_120`; not in FastMACE | **none.** `gemm_tc_hyb_sm120.cubin` below is its recorded rebuild; the default switches to it once it is gated (`PLAN.md` §1.3, D6) |
| `cubins/gemm_tc_hyb_sm80.cubin` | `065d1a89b39fd6b60236f0dd6b120443ce0b484f74270862a2578e3f6a45892e` | `cubins/src/gemm_tc.cu`: TF32 + FP16 hybrid, 6 tiles, with beta | `cubins/src/gemm_tc.build.txt`: CUTLASS commit `2c85f497547eb441f0fe80bfb0fb2e6f9add1719` (v4.8.1); nvcc 13.3 (V13.3.33) |
| `cubins/gemm_tc_3x_sm80.cubin` | `d816cb2a75dc8f1f9c3713e253f33633d03f89cc5b246135da76471b850aec08` | `cubins/src/gemm_tc.cu`: 3xTF32, 6 tiles, with beta | as above |
| `cubins/gemm_tc_hyb_sm90.cubin` | `c244a049203e158230a261c4467521cd3041140812f22036959684c9acf38668` | `cubins/src/gemm_tc.cu`: TF32 + FP16 hybrid, 3 tiles | as above |
| `cubins/gemm_tc_hyb_sm120.cubin` | `c40b86ddacf3da3252e6d4594888c0fc01a1de9b41cdc2eb21f8a0d4e1ff46b5` | `cubins/src/gemm_tc.cu`: TF32 + FP16 hybrid, 3 tiles | as above |

What the hybrid kernels compute: the product of two float32 matrices, each element split into an 11-bit high
part and a low part. The high-by-high products run on TF32 tensor cores and the two cross products in one FP16
tensor-core instruction on parts that fit float16 exactly (`hybrid_f16.h`). Elements must stay below 32752 in
magnitude; the engine drops the hybrid for a handle whose result turns non-finite and evaluates again without it.
The `3x` cubin is CUTLASS's 3xTF32 without the FP16 instruction.

## Generated sources (`src/generated_*`)

Written by the generators in `codegen/`; not edited by hand. They hold kernel source specialised to model
architectures (channel counts, irreps, tensor-product paths, coupling coefficients). They hold no model weights:
those are read from a `.loup` bundle at run time. A bundle also carries the source text of its model's product
kernels, as `loupmd/export/gen_product.py` emits it (the text of `src/generated_generic.cu` for that model), which
the library compiles at load when it was not built with them (JIT_DESIGN.md stage 3).

The kernels specialised to MACE-OMAT-0 medium (`src/generated_kernels.cuh`, `codegen/gen_kernels.py`, with a
streaming schedule adapted from OpenEquivariance pull request 223) were retired with JIT_DESIGN.md stage 5 and are
no longer in the tree; version 0.0.1 shipped them.

| File | Generator | Made with |
| --- | --- | --- |
| `src/generated_generic.cu` | `codegen/gen_generic.py` with `loupmd/export/gen_product.py`, from the architectures of the model files found at generation time | the product kernels: FastMACE's factored symmetric contraction (`fastmace/kernels/cuda/sc_factored.py`, `sc_generated.py`; MIT, © 2026 Fabian Zwingel), with MACE's `convert_e3nn_cueq` (MIT, © 2022 ACEsuit/mace) supplying the contraction's polynomial; the kernels' launchers |
| `src/generated_generic.cuh` | `codegen/gen_generic.py` | the declarations of the above; no third-party content |
| `src/generated_conv.cuh` | `codegen/gen_generic.py` | the conv (tensor-product) kernels: e3nn's Wigner 3j coefficients (MIT). Device code only: the library also compiles it at run time (NVRTC, `src/jit.cu`) |
| `src/generated_sh16.cuh` | `codegen/gen_generic.py` | the spherical harmonics' gradient, derived with sympy (BSD-3-Clause; only its output is here). Device code only, also compiled at run time |
| `src/generated_generic_manifest.json` | `codegen/gen_generic.py` | the signatures of the product kernels in `src/generated_generic.cu` and the model files each came from; no third-party content |

## Vendored from FastMACE (`loupmd/export/_vendor/`)

The exporters (`loupmd/export/`) and `codegen/gen_generic.py` use parts of seven FastMACE modules (MIT, © 2026
Fabian Zwingel): the factored symmetric contraction (`kernels/cuda/sc_factored.py`, `sc_generated.py`), the skip
composition (`kernels/triton/compose_skip.py`), the certified radial tables and splines (`rewrites/radial/`), and
the weight extraction of the generic and linear rewrites (`rewrites/generic/modules.py`,
`rewrites/linear/modules.py`). `tools/release/vendor_fastmace.py` writes the tree from the FastMACE commit named
in `loupmd/export/_vendor/VERSION`, keeping of each module the definitions the exporters use with their original
text; it is not edited by hand. `tools/release/export_identity.sh` exports the same bundles with the vendored tree
and with a FastMACE checkout and compares them byte for byte.

## Code and data ported from FastMACE

FastMACE is MIT, © 2026 Fabian Zwingel, the same owner as LoupMD.

| File | Ported from (FastMACE commit `9b801229`) | Changes |
| --- | --- | --- |
| `loupmd/models.py` | `fastmace/model/labels.py` (the label table: release URLs, SHA-256, licences, heads and training functionals with their sources) and the checkpoint lookup, download and trust functions of `fastmace/model/loading.py` | errors are LoupMD's; the model folder variable is `LOUPMD_MODELS`; nothing is unpickled in this module |
| `loupmd/errors.py` | the message shape of `fastmace/errors.py` (`what`, `Why:`, `Next:`) | LoupMD's own classes |
| `loupmd/protocols.py` | `fastmace/protocols/schedule.py` and `profiles.py`: segments, `Schedule`, whole-step resolution (half up), the end-point target, `ScheduleState`, the profiles `slow`, `fast`, `ultrafast`, `anneal` | errors are `InputError`; profile files are TOML only; NPT, `pressure_GPa` and dispersion in a profile are refused; optimiser names are kept as data |
| `loupmd/quench.py` | `fastmace/protocols/quench.py`: the frame selection per target-temperature bin, the quench's settings, files and CSV columns | each frame is relaxed with `lm.optimize` on the host; the run's schedule and cadence are read from `metadata.json` |
| `loupmd/output.py` | the chunk scheme, file names and thermo header of `fastmace/io/output.py` and `io/trajectory.py`, and the durable-write helpers of `io/durable.py` | rows and frames come from the engine (device thermo buffer, `get_state`), not from torch tensors; a background thread writes them |
| `loupmd/quick.py`, `loupmd/integrators.py`, `loupmd/config.py` (`Output`) | the signature, argument rules and defaults of `fastmace/quick.py` (`md`, `RunResult`, initial velocities, default friction and output directory), the record names of `fastmace/integrators/__init__.py`, the `Output` record of `fastmace/io/output.py` | only what LoupMD's engine has (NVE, Langevin); FastMACE's planner arguments are refused by name |

The model files themselves are not part of LoupMD. Each label's licence (MIT or the Academic Software License) is
in the table and is shown by `loupmd models`.

## Modules ported from ASE (LGPL-2.1-or-later)

By owner decisions O6 (15 November 2026) and O35 (18 November 2026) the files below, which port or follow classes
of ASE 3.27 (LGPL-2.1-or-later, © the ASE developers, <https://gitlab.com/ase/ase>) so that they agree with ASE to
rounding, are distributed under **LGPL-2.1-or-later**, not MIT. Each starts with an
`SPDX-License-Identifier: LGPL-2.1-or-later` line and a provenance line. The licence text is
`LICENSES/LGPL-2.1-or-later.txt`.

| LGPL file | Ported from (ASE 3.27) |
| --- | --- |
| `loupmd/optimize/lbfgs.py` | `ase/optimize/lbfgs.py` (`LBFGS` without line search) |
| `loupmd/optimize/fire.py` | `ase/optimize/fire.py` (`FIRE` without the downhill check) |
| `loupmd/optimize/cell.py` | `ase/filters.py` (`UnitCellFilter`'s cell mapping and `FrechetCellFilter`) |
| `src/integrator.cu` | the thermostats and barostats of `ase/md`, as CUDA kernels; the section "Integrators that follow ASE's conventions" lists each |
| `src/cell.cu` | `ase/md/nptberendsen.py` (the Berendsen barostat; the file's other kernels are the engine's variable cell) |
| `src/minimize.cu` | `ase/optimize/lbfgs.py`: the device part of `loupmd/optimize/lbfgs.py` |

The records of `loupmd/optimize/__init__.py` and `loupmd/integrators.py` and the classes of `loupmd/ase/` take
ASE's argument names and defaults (an interface, not ported code) and are MIT.

**The compiled library.** `libloupmd.so` (in the wheel: `loupmd/_lib/libloupmd.so`) is linked from these kernels
and the rest of the engine, and is distributed under LGPL-2.1-or-later as a whole; the other source files it is
built from stay MIT. The complete source of a release's library is this repository at the tag of that version
(`v<version>`, <https://github.com/FZWINGEL-UBT/LoupMD>), and `tools/release/` holds the build. The package loads
the library at run time; `LOUP_LIB` names another build to load in its place.

## Blocks that follow ASE inside MIT files (LGPL-2.1-or-later)

Three blocks in two files that are otherwise MIT follow the same ASE classes. Each lies between an
`SPDX-SnippetBegin` and an `SPDX-SnippetEnd` comment and is under LGPL-2.1-or-later (O35).

| File | Block | Follows (ASE 3.27) |
| --- | --- | --- |
| `src/engine.cu` | two blocks: the integrators' coefficients and masses in the set-up of an MD call (`run_md_loop`), and the barostats' constants in the set-up of a tiled MD call (`tiled_run_impl`) | the classes of `ase/md` named in "Integrators that follow ASE's conventions" |
| `loupmd/tiled_engine.py` | the Langevin and velocity-Verlet steps of the tiled mode's host loop | `ase/md/langevin.py`, `ase/md/verlet.py` |

## Structure files

`loupmd/bench/structures/` holds the structures of the benchmark and the accuracy gate that ship with the package;
`loupmd/bench/structures/SOURCES.md` names the source, licence and SHA-256 of each. The water box was built by the
authors (MIT, as LoupMD); the urea, naphthalene and paracetamol cells are entries of the Crystallography Open
Database, whose data are in the public domain (CC0). The Materials Project cells of the benchmark (`NbCl5`) and
of the gate's `crystals` set are not in the package (PLAN.md, decision O11).

## D3 reference data (`loupmd/data/d3_tables.npz`)

The D3 reference tables (reference C6 coefficients with their coordination numbers, covalent radii, the r2r4
factors and the zero-damping cutoff radii) are Grimme's DFT-D3 reference data (S. Grimme, J. Antony, S. Ehrlich,
H. Krieg, J. Chem. Phys. 132, 154104 (2010)), taken as torch-dftd 0.5.1 distributes them in
`torch_dftd/nn/params/dftd3_params.npz` (MIT, © 2020 Preferred Networks, Inc.); `tools/dev/make_d3_tables.py`
rewrites them into LoupMD's layout without changing a value. The damping parameter sets in
`loupmd/dispersion.py` are numbers from the papers each entry cites. The kernels of `src/dispersion/` are
LoupMD's own; simple-dftd3 (LGPL-3.0-or-later) is used only as an external reference in the tests and the
bake-off, never copied or linked.

## Integrators that follow ASE's conventions (`src/integrator.cu`, `src/cell.cu`)

The thermostats and barostats below are CUDA kernels written for the engine. Each implements a published algorithm
and follows ASE 3.27's class of the same name in its argument meanings, its coefficients and its order of
operations, so that a LoupMD run agrees with ASE's to rounding (the tests compare them). No ASE source file was
copied; the comments name the ASE class each one follows. Because they were written from ASE's implementation,
the owner decided on 18 November 2026 (O35, `PLAN.md` D81) to distribute them under ASE's licence,
LGPL-2.1-or-later, as decision O6 did for the optimisers. The commits before that decision marked them MIT.

| Kernel section | Algorithm | Follows (ASE 3.27) |
| --- | --- | --- |
| `src/integrator.cu`: Langevin and velocity Verlet steps, `fix_com` | Langevin dynamics, velocity Verlet | `Langevin`, `VelocityVerlet` |
| `src/integrator.cu`: CSVR | Bussi, Donadio, Parrinello, J. Chem. Phys. 126, 014101 (2007) | `Bussi` |
| `src/integrator.cu`: Nose-Hoover chain | Martyna, Klein, Tuckerman (1992); Tuckerman et al. (2006); Suzuki-Yoshida coefficients | `NoseHooverChainNVT` |
| `src/integrator.cu`: Berendsen thermostat | Berendsen et al., J. Chem. Phys. 81, 3684 (1984) | `NVTBerendsen` |
| `src/integrator.cu`: Langevin BAOAB NPT | Leimkuhler and Matthews' BAOAB with a barostat | `LangevinBAOAB` |
| `src/integrator.cu`: Martyna-Tobias-Klein NPT | Martyna, Tobias, Klein, J. Chem. Phys. 101, 4177 (1994) | `IsotropicMTKNPT` |
| `src/cell.cu`: Berendsen barostat | Berendsen et al. (1984) | `NPTBerendsen` (isotropic and per axis) |

## Run-time libraries that are not shipped

The wheel ships `libloupmd.so` and depends on NVIDIA's CUDA run-time libraries through the `cuda-toolkit` package
(cuBLAS, cuBLASLt, the CUDA runtime and, for the split dispersion sum, cuFFT, which the library opens with
`dlopen`). They are installed by pip under NVIDIA's licence and are not part of LoupMD's distribution.

## Licences of the run-time dependencies

`docs/validation/dependency-licences.md` lists every distribution `pip install loupmd` brings in, with its version
and licence as its metadata states it, written by `tools/release/dependency_licences.py` (the listing `pip-licenses`
gives, from installed metadata; `--extra export` adds the export extra). In short: ASE is LGPL-2.1-or-later and
NumPy, SciPy and matplotlib's dependencies are permissive (BSD, MIT, PSF, Apache-2.0, MIT-CMU); the NVIDIA wheels
(`nvidia-cuda-runtime`, `nvidia-cublas`, `nvidia-cufft`, `nvidia-cuda-nvrtc`, `nvidia-nvjitlink`) are under NVIDIA's
proprietary licence, and the `cuda-toolkit` meta-package states none. None of them is copied into the wheel.

## Not in the package

The Materials Project structures of the benchmark set stay out of the package (decisions O11 and O25):
`LOUPMD_BENCH_STRUCTURES` names a folder that holds them.
