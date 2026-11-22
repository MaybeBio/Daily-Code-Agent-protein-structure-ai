# RBMD

Current version: RBMD 2.0

Molecular dynamics software with multi-device support, fully GPU-resident parallelism, and Random Batch algorithms: RBE, RBL, and RBSOG.

RBMD is a GPU-accelerated molecular dynamics package for heterogeneous and high-performance computing systems. It supports NVIDIA CUDA and AMD ROCm/DCU devices, MPI-based multi-GPU execution, and optional NCCL/RCCL collective communication.

## Preprints

For the manuscript of RBMD 2.0, see, [RBMD 2.0: Random batch molecular dynamics package for large-scale simulations on multi-GPU architectures](https://arxiv.org/abs/2609.02694)

## Highlights

- Random Batch Method algorithms for short- and long-range interactions, including RBL, RBE, and RBSOG.
- CUDA and ROCm/DCU backends with explicit wave32 and wave64 configurations.
- Multi-device and multi-node parallelism with simulation data kept on GPUs throughout the main computation path.
- Molecular force fields and interaction models for water, polymers, ionic systems, metals, and three-body materials.
- JSON-based simulation configuration and optional RDF, MSD, and VACF post-processing.

## Build and run

Building RBMD does not require a supercomputer. A Linux workstation or server with a compatible CUDA or ROCm toolchain can build the project and run configurations supported by its available GPU resources. MPI is optional for a single-device build and required for the multi-GPU execution path.

The following example configures a single-GPU CUDA build. Replace the CUDA architecture with the value for your device.

```bash
cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DUSE_CUDA=ON \
  -DUSE_MPI=OFF \
  -DWARP_SIZE_64=OFF \
  -DCMAKE_CUDA_ARCHITECTURES=89
cmake --build build --parallel

./build/rbmd --version
./build/rbmd -j examples/03-metal/Cu/Cu.json
```

For CUDA, ROCm/DCU, MPI, NCCL/RCCL, compiler selection, CMake options, and troubleshooting, see the [Build and Run Guide](https://github.com/JZJZJZ33/polySIM_RBMD/blob/HEAD/docs/build.en.md) or the [中文构建与运行指南](https://github.com/JZJZJZ33/polySIM_RBMD/blob/HEAD/docs/build.zh_CN.md).

Simulation inputs are JSON files. See the [JSON Configuration Reference](https://github.com/JZJZJZ33/polySIM_RBMD/blob/HEAD/docs/json-configuration.en.md) or [JSON 配置参考](https://github.com/JZJZJZ33/polySIM_RBMD/blob/HEAD/docs/json-configuration.zh_CN.md) for supported fields and examples.

## Benchmarks

The `benchmark/` directory contains curated configurations, Slurm submission scripts, shared input data, RDF results, and result workbooks for three systems:

| System | Records | Workbook |
| --- | --- | --- |
| H2O | [`benchmark/h2o`](https://github.com/JZJZJZ33/polySIM_RBMD/blob/HEAD/benchmark/h2o) | `benchmark/h2o/workbook/run_H2O.xlsx` |
| LJ-salt | [`benchmark/lj_salt`](https://github.com/JZJZJZ33/polySIM_RBMD/blob/HEAD/benchmark/lj_salt) | `benchmark/lj_salt/workbook/run_LJ_salt.xlsx` |
| PEO-LiTFSI | [`benchmark/peo_litfsi`](https://github.com/JZJZJZ33/polySIM_RBMD/blob/HEAD/benchmark/peo_litfsi) | `benchmark/peo_litfsi/workbook/run_PEO.xlsx` |

The four publication input systems are distributed as a single
[`rbmd-data-v2.tar.gz`](https://github.com/qizhou1729/rbmd/releases/download/benchmark-data-v2/rbmd-data-v2.tar.gz)
Release asset rather than stored in Git. Download and extract it from the
repository root:

```bash
curl -L https://github.com/qizhou1729/rbmd/releases/download/benchmark-data-v2/rbmd-data-v2.tar.gz \
  -o rbmd-data-v2.tar.gz
tar -xzf rbmd-data-v2.tar.gz
```

The archive installs the three shared benchmark inputs and the equilibrated H2O
RDF seed at the canonical paths used by the retained configurations. See
[`benchmark/data/README.md`](https://github.com/JZJZJZ33/polySIM_RBMD/blob/HEAD/benchmark/data/README.md) for the exact file list,
system definitions, and checksums.

A supercomputer is not needed to read the benchmark configurations or build RBMD. Reproducing the published multi-device scaling runs does require an HPC environment with the corresponding number of GPUs/DCUs, MPI, and a Slurm-compatible scheduler. Partition names, module versions, device requests, and launcher options in the archived submission scripts are site-specific and must be adapted to the target cluster.

## Repository layout

- `src/`: C++ and GPU implementation.
- `cmake/`: CMake modules and backend configuration.
- `tools/`: bundled third-party source archives used during configuration.
- `examples/`: runnable JSON configurations and input data.
- `benchmark/`: curated H2O, LJ-salt, and PEO-LiTFSI benchmark records.
- `docs/`: English and Chinese build and JSON configuration documentation.
- `scripts/`: analysis, diagnostics, and environment helper utilities.
- `LICENSES/`: third-party license notices.

## License

See [`LICENSE`](https://github.com/JZJZJZ33/polySIM_RBMD/blob/HEAD/LICENSE) for the RBMD project license and [`LICENSES/`](https://github.com/JZJZJZ33/polySIM_RBMD/blob/HEAD/LICENSES) for third-party notices.

### Staged single-GPU equilibration

`scripts/run_equilibration.py` runs NVT warm-up, NPT density relaxation, and
NVT production using an existing RBMD executable. The runner uses Python 3.8+
and the standard library, with no network access required. Start with the
bundled PEO box to test the stage handoff. From the repository root on the
GPU server, with your RBMD build environment active:

```bash
python3 scripts/run_equilibration.py \
  --rbmd ./build-h20-cuda121-gcc12/rbmd \
  --data examples/01-peo/peo+Li.data \
  --out runs/peo-handoff-smoke \
  --nvt-steps 100 --npt-steps 100 --production-steps 100 \
  --equil-interval 20 --production-interval 20
```

Each stage writes its config, log, trajectory, density CSV, and final LAMMPS
data file. After NVT warm-up and NPT, the runner transfers the final wrapped
coordinates, box, and velocities, retains the input topology and coefficients,
and reconstructs molecular image flags from bonds. This assumes that each bond
has an unambiguous minimum image and that no bonded cycle winds through the
periodic box. Thermostat, barostat, and random-number states are reinitialized
at stage boundaries. Output intervals must divide the stage lengths so the
final timestep is saved.

The short run exercises the handoff. For a fresh PolySIM box, supply an
orthogonal, periodic, parameterized `REAL` / `atom_style full` data file with
contiguous atom IDs and a matching CVFF JSON template via `--template`.
The runner starts from the supplied box. Severe overlaps can require
minimization before warm-up. Review the NPT density and thermodynamic log
before treating the production trajectory as equilibrated. This runner does
not compute transport properties.

### PolySIM to PEO–LiTFSI transport

Run this from the RBMD checkout with PolySIM installed in the Python
environment and `xtb` on the path. Use `--run-rbmd no` for the existing
PolySIM geometry workflow, `prepare` to export a box on the Mac, or `yes`
to prepare and run all MD stages in an environment that also has the
compiled RBMD executable.

The default MD case follows the 5 ns screening tier of
[Xie et al.](https://doi.org/10.1038/s41467-022-30994-1). For PEO, 150 backbone
atoms means 50 EO units per chain. The default uses 50 LiTFSI pairs and
rounds the number of chains to the nearest integer at the target loading
of 1.5 mol/kg of polymer. This gives 15 chains and 6,080 total atoms, with
EO:Li = 15:1 and a realized molality of about 1.512 mol/kg. The default is
5 ns equilibration followed by 5 ns NVT production at 353 K.

PolySIM's RBMD adaptation splits equilibration into 0.1 ns NVT warm-up
and 4.9 ns NPT at 0.5 fs, then runs production at 1 fs. This uses the
bundled RBMD CVFF-form force field, xTB chain geometry, and RBMD velocity
Verlet. The published workflow used PCFF+, MedeA Monte Carlo packing, and
rRESPA with 0.5 fs inner and 2 fs outer timesteps. Compare forces and
short-run properties before using the RBMD labels alongside the paper's
datasets.

```bash
python scripts/polysim_workflow.py \
  --run-rbmd prepare --monomer '[*]CCO[*]' --out runs/peo-xie-5ns
```

Override the composition explicitly for a small smoke test or another
formulation:

```bash
python scripts/polysim_workflow.py \
  --run-rbmd prepare --monomer '[*]CCO[*]' --repeat-units 8 \
  --chains 16 --ratio 16:1 --out runs/peo-16to1
```

The ratio is **PEO repeat units per LiTFSI pair**, not chains per pair
or a weight ratio. The box above contains 16 chains and 8 salt pairs.
Integer rounding can change the realized ratio. See `species_map.json`
for both requested and realized loadings and the atom ID ranges.
`--run-rbmd no` writes one optimized PEO chain. For other chemistries it
uses the existing PolySIM workflow, defaulting to one chain.

The MD preparation path explicitly builds H-capped head-to-tail PEO, then
uses PolySIM's MMFF and xTB GFN-FF geometry routines. The bundled RBMD PEO
case supplies CVFF-form parameters and salt topology. The exporter balances
the small residual charge introduced by transferring rounded PEO partial
charges and records the correction. Use the prepared cases for validation
until matched-snapshot forces and energies, density equilibration, and
transport convergence have been checked. Other polymer chemistries need
their own parameter sets. Copies of one conformer are packed at the
requested initial density and independently rotated. Use different seeds
for independently packed replicas.

For an offline server without PolySIM or xTB, upload `packed.data`,
`rbmd.json`, `species_map.json`, and `run_plan.json` from the prepared
case. Pass `--plan "$case_dir/run_plan.json"` to the runner for the full
5 ns protocol. The command below overrides the plan with short runs.
Set the following path to the uploaded case. This smoke test checks the handoff
and generates transport curves:

```bash
case_dir=runs/peo-16to1
python3 scripts/run_equilibration.py \
  --rbmd ./build-h20-cuda121-gcc12/rbmd \
  --data "$case_dir/packed.data" --template "$case_dir/rbmd.json" \
  --out "$case_dir/md" --plan "$case_dir/run_plan.json" \
  --nvt-steps 100 --npt-steps 100 \
  --production-steps 100 --equil-interval 10 --production-interval 10

python3 scripts/analyze_transport.py \
  --trajectory "$case_dir/md/03-production/rbmd.trj" \
  --data "$case_dir/md/03-production/final.data" \
  --species "$case_dir/species_map.json" \
  --config "$case_dir/md/03-production/rbmd.json" \
  --out "$case_dir"
```

The transport script needs NumPy. It writes collective displacement curves
in the polymer center-of-mass frame. On a longer production trajectory,
inspect these curves and pass `--fit-ps START END` within the diffusive lag
range to report conductivity and transference estimates. The calculation
uses formal monovalent charges for transport and records the convention.
A single-trajectory fit is provisional and must be checked against longer
runs, fit windows, and independent replicas before screening decisions.
For a one-command smoke test on a GPU machine with PolySIM and xTB, use
`--run-rbmd yes` in the first command, pick a new output path, and add
`--rbmd` and the three step-count and two interval options shown above.

### Server transport analysis and plots

Run these scripts on Linux with Python 3, NumPy and Matplotlib available.
The analysis accepts any neutral polymer chemistry with a binary monovalent salt,
using explicit species metadata. Automated force-field assignment and fresh-box
preparation in `polysim_workflow.py` currently support PEO–LiTFSI only.

An existing `species_map.json` is preserved. Maps may contain `atom_ids` lists
or the older inclusive `first_id`/`last_id` ranges. Supply species definitions
for new chemistries, for example a JSON file containing
`{"polymer":{"role":"polymer","atom_types":[7,8,9]},"Li":{"role":"cation","charge_e":1,"atom_types":[1]},"anion":{"role":"anion","charge_e":-1,"atom_types":[2,3,4,5,6]}}`.
Replace the type lists with those of your force field. Each bonded component
must match exactly one definition. For overlapping type sets, provide an explicit
map from the box builder. Original LAMMPS molecule IDs need not identify components.

```bash
python3 scripts/generate_species_map.py --data runs/my-case/packed.data \
  --definitions species_definitions.json --out runs/my-case/species_map.json
python3 scripts/analyze_run.py --run runs/my-case --fit-ps 1 4
```

For the bundled PEO example only, omit `--definitions` in the map generator.
For integrated cases whose MD stages are under `case/md`, use `--run case/md`
and `--species case/species_map.json`.
Analysis tolerates an incomplete final atom record from an interrupted run with
an explicit warning. Interior corruption remains an error. The source trajectory
is retained. Production must have a fixed orthogonal periodic box and unwrapped
coordinates. Output includes ion self-MSD, polymer-frame ion self-diffusion in
m²/s, collective conductivity in S/cm, cation transference number, and
Nernst–Einstein estimates. Historical Li/TFSI column and result names are retained
for compatibility; species definitions in the JSON give their actual identities.
Three figures with fitted regions are generated as PNG and PDF. Fit windows are
user-selected and estimates are provisional. Replica uncertainties and convergence
are not inferred from one short trajectory. The scripts do not run MD on macOS.
