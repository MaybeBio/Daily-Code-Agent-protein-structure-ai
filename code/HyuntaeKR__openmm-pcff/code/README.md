# openmm-pcff

PCFF, the class II force field, for OpenMM.
`openmm_pcff` types a structure, assigns PCFF parameters, and builds an `openmm.System` whose energies and forces reproduce the EMC + LAMMPS (`class2` styles) workflow.
On 21 reference systems, atom types and parameters are identical to EMC's, and energies match LAMMPS to 1e-5 relative or better (see [Validation](#validation)).

## Installation

Install OpenMM (8.6 or later) and RDKit, preferably from conda-forge for GPU support, then install this package from a clone of the repository:

```
conda install -c conda-forge openmm rdkit numpy scipy
git clone https://github.com/HyuntaeKR/openmm-pcff.git && cd openmm-pcff
pip install .
```

Use `pip install -e .` for a development install; the tests also need `pytest` and are run from the repository root.

## PCFF parameter files

PCFF typing and parameters come from two files that ship with [EMC](https://montecarlo.sourceforge.net/emc/Welcome.html) and are not distributed here: `pcff.frc` and `pcff_templates.dat`, in `field/cff/pcff/` of the EMC installation.
Pass their paths to the functions below.
The tests read them from `$EMC_ROOT/field/cff/pcff/` and are skipped when the environment variable `EMC_ROOT` is not set.

## Quick start

From a PDB file with `CONECT` records for every bond and a `CRYST1` box:

```python
import os
from pathlib import Path

import openmm
import openmm.app
import openmm.unit
from rdkit import Chem
from openmm_pcff import system_from_pdb

pcff_directory = Path(os.environ["EMC_ROOT"]) / "field" / "cff" / "pcff"

system, topology, positions_nm, report = system_from_pdb(
    "mixture.pdb",
    [Chem.AddHs(Chem.MolFromSmiles(smiles)) for smiles in ["CCO", "c1ccccc1"]],
    frc_path=pcff_directory / "pcff.frc",
    templates_path=pcff_directory / "pcff_templates.dat",
    lj_cutoff_angstrom=9.5,
    coulomb_cutoff_angstrom=9.5,
    lj_tail_correction=True,
    periodic=True,
    coulomb_method="pme",
    ewald_error_tolerance=5e-4,
)

integrator = openmm.LangevinMiddleIntegrator(300 * openmm.unit.kelvin, 1 / openmm.unit.picosecond, 0.001 * openmm.unit.picoseconds)
simulation = openmm.app.Simulation(topology, system, integrator)
simulation.context.setPositions(positions_nm)
```

The RDKit molecules (one per distinct molecule, with explicit hydrogens) supply the bond orders and aromaticity that the typing needs and PDB files lack.

## Usage

### Input routes

The routes that assign parameters take the same simulation settings as the quick start; `system_from_emc_lammps_files` takes the cutoffs and tail correction from EMC's `.params` file.

| Function | Structure from | Types and parameters from | Returns |
|---|---|---|---|
| `system_from_pdb(path, molecules, frc_path, templates_path, ...)` | PDB or PDBx/mmCIF file | openmm_pcff | System, `openmm.app.Topology`, positions (nm), report |
| `system_from_openmm_topology(omm_topology, positions, molecules, frc_path, templates_path, ...)` | `openmm.app.Topology` and positions with units (e.g. from `Modeller`) | openmm_pcff | System, positions (nm), report |
| `system_from_lammps_data(data_path, molecules, frc_path, templates_path, ...)` | LAMMPS data file | openmm_pcff | System, positions (nm), report |
| `system_from_emc_lammps_files(data_path, params_path, ...)` | EMC's `.data` | EMC's `.params` (including cutoffs and tail correction) | System, positions (nm) |

`topology_from_openmm_topology` and `topology_from_lammps_data` stop before the OpenMM system and return the parameterized topology (coefficients in LAMMPS real units), e.g. to inspect the assigned parameters.

### Input requirements

- Every bond, including those to hydrogen, must be in the file: `CONECT` records in PDB, `struct_conn` or `chem_comp_bond` in PDBx/mmCIF.
- Every molecule must have the same connectivity as one of the given RDKit molecules.
- The box must be orthorhombic; `periodic=True` needs a box.
- Molecules split across the periodic boundary are made whole (atoms moved by whole box vectors), with a warning, because bonded forces use raw coordinates.
- PDB stores coordinates to 0.001 Angstrom and at most 99999 atoms; use PDBx/mmCIF (`.cif`) for larger systems.

### Simulation settings

None of these has a default, so that no simulation choice is made silently.

| Argument | Meaning | EMC's PCFF default |
|---|---|---|
| `lj_cutoff_angstrom` | 9-6 LJ cutoff (plain truncation) | 9.5 |
| `coulomb_cutoff_angstrom` | real-space Coulomb cutoff (PME, Ewald) | 9.5 |
| `lj_tail_correction` | long-range LJ correction | on |
| `periodic` | periodic boundary conditions | yes |
| `coulomb_method` | `"pme"`, `"ewald"`, `"no_cutoff"` (non-periodic), or `None` | PPPM |
| `ewald_error_tolerance` | OpenMM's Ewald/PME error tolerance (required for PME and Ewald) | |

### Force groups

By default (`merge_bonded=True`) each bonded family is one force, and energies can be split by LAMMPS keyword (`ebond`, `eangle`, `edihed`, `eimp`, `evdwl`, `ecoul+elong`) with the groups in `openmm_pcff.builder.MERGED_FORCE_GROUPS`.
`merge_bonded=False` gives one force per PCFF sub-term (groups in `openmm_pcff.builder.FORCE_GROUPS`) for energy decomposition; it gives the same energies and forces to round-off but runs MD 1.37-1.55 times slower on the GPU (see [Validation](#validation)).
Use the dictionary that matches the layout; the other one silently selects the wrong forces.

### Report

The routes that assign parameters return a report to check before production runs:

- `automatic`: terms that use the lower-quality automatic (`_auto`) parameters because no explicit entry exists;
- `zero_wilson`: impropers whose Wilson term is zero because no explicit entry exists;
- `hybridization_mismatches`: atoms whose type matches only because template hybridization tests are skipped (as in EMC).

## Scope and known differences

- Typing and parameter assignment reproduce EMC v9.4.4, including its choices: template hybridization tests are skipped and automatic Wilson parameters are not used (details in `openmm_pcff/atomtyping.py` and `openmm_pcff/assign.py`).
- One deliberate difference from EMC: the amide nitrogen of N-methylacetamide is typed `n_2` (EMC's greedy matcher gives `na` and then stops with a missing bond increment).
- Charges come from PCFF bond increments; a missing increment raises an error.
- Nonbonded: 9-6 LJ with sixth-power mixing, 1-2 and 1-3 pairs excluded, 1-4 pairs at full strength (`special_bonds 0 0 1`); explicit unlike-pair LJ coefficients are not supported.
- Orthorhombic boxes only; molecules bonded to their own periodic image (infinite networks) are not supported.
- The LJ tail correction differs from LAMMPS's by O(1/N), because the two codes count like-type pairs differently.

## Validation

All comparisons use OpenMM's Reference platform (double precision) and LAMMPS single points of the same configurations.
The 21 reference systems are butane and polyethylene, 13 small molecules, two mixtures of 25 and 39 small molecules covering many atom types, and oligomers of polystyrene, PMMA, PEO, and PDMS.

| Comparison | Systems | Agreement required |
|---|---|---|
| EMC's parameters in OpenMM vs LAMMPS: energy per keyword, per-atom forces | butane, polyethylene; isolated, periodic, and Ewald cases | energy 1e-6 relative; force 1e-4 kcal/mol/Angstrom; Coulomb 1e-5 relative |
| openmm_pcff typing and parameters vs EMC | all 21 | identical types; coefficients within 1e-5 and charges within 6e-5 e (EMC's printed precision) |
| openmm_pcff-parameterized OpenMM vs LAMMPS | all 21 | as above; Coulomb 1e-6 after removing the error of LAMMPS's approximate erfc |
| Merged vs per-sub-term bonded layout | all 21 | energy 1e-12, force 1e-10 relative |
| Forces vs finite differences of the energy | 6 systems | 1e-5 relative |
| PDB, PDBx/mmCIF, and `openmm.app.Topology` input vs LAMMPS data input | 6 reference systems and an RDKit-built mixture | identical types and parameters |

On the GPU (CUDA, mixed precision, PME error tolerance 5e-4), the merged bonded layout runs MD 1.37-1.55 times faster than the per-sub-term layout for 50k-atom polystyrene and PMMA.

All results were produced on one workstation:

| Component | Version |
|---|---|
| OS | Ubuntu 24.04.5 LTS (Linux 7.0.0) |
| CPU | Intel Core i7-13700KF (16 cores, 24 threads), 64 GB RAM |
| GPU | NVIDIA GeForce RTX 4070 SUPER (12 GB), driver 580.178.04 |
| Python packages (conda-forge) | Python 3.13.16, OpenMM 8.6.1 (CUDA 13.0 build), numpy 2.5.4, scipy 1.18.1, RDKit 2026.09.2, pytest 9.2.0 |
| LAMMPS | 22 Jul 2025, Update 4; packages CLASS2, KSPACE, MOLECULE, KOKKOS (CUDA + OpenMP, double precision; Kokkos 4.6.2, CUDA 12.6); GNU C++ 13.3.0, Open MPI 4.1.6 |
| EMC | v9.4.4 |

## Reproducing the validation

The reference data are generated locally; this repository contains no EMC- or PCFF-derived data.
Needed: EMC v9.4.4 with `EMC_ROOT` set to its installation directory, and LAMMPS with the CLASS2, KSPACE, and MOLECULE packages run as `lmp` from `PATH`.

butane and polyethylene were built by hand; in `reference/butane/` and in `reference/polyethylene/` run:

```
perl $EMC_ROOT/scripts/emc.pl input.esh
$EMC_ROOT/bin/emc_linux_x86_64 build.emc
```

Then, from the repository root:

```
python scripts/make_emc_reference.py         # other EMC reference systems (seconds)
python scripts/make_lammps_reference.py      # LAMMPS single points (about 20 s)
pytest                                       # acceptance tests (about 80 s)
python scripts/compare_with_lammps.py        # butane and polyethylene comparison table
python scripts/report_assignment.py          # typing and assignment summary for all systems
python scripts/nve_energy_drift.py butane    # NVE energy drift, OpenMM GPU vs LAMMPS (a few minutes, needs CUDA)
```

The GPU benchmarks need LAMMPS built with KOKKOS for CUDA:
`make_benchmark_systems.py` builds and relaxes the 50k-atom systems in `benchmark/`; `benchmark_openmm.py` and `benchmark_lammps.py` measure speed; `check_gpu_accuracy.py`, `check_merged_layout.py`, and `check_benchmark_nve_drift.py` check precision, the merged layout, and energy conservation on the GPU.

## Repository layout

```
openmm_pcff/    the package (public API in __init__.py)
validation/     reference-system definitions and comparisons used by tests and scripts (not installed)
tests/          pytest tests
scripts/        reference generation, reports, benchmarks
reference/      reference systems (only the EMC inputs input.esh are tracked)
benchmark/      benchmark inputs and results
```

## Citation

If you use openmm-pcff, please cite this repository and the work it builds on:

- PCFF: H. Sun, S. J. Mumby, J. R. Maple, A. T. Hagler, "An ab Initio CFF93 All-Atom Force Field for Polycarbonates", *J. Am. Chem. Soc.* **116**, 2978-2987 (1994). https://doi.org/10.1021/ja00086a030
- EMC: P. J. in 't Veld, G. C. Rutledge, "Temperature-Dependent Elasticity of a Semicrystalline Interphase Composed of Freely Rotating Chains", *Macromolecules* **36**, 7358-7365 (2003). https://doi.org/10.1021/ma0346658
- OpenMM: P. Eastman et al., "OpenMM 8: Molecular Dynamics Simulation with Machine Learning Potentials", *J. Phys. Chem. B* **128**, 109-116 (2024). https://doi.org/10.1021/acs.jpcb.3c06662
- RDKit: RDKit: Open-source cheminformatics, https://www.rdkit.org (cite the release DOI of the version used; all releases: https://doi.org/10.5281/zenodo.591637).
- LAMMPS, if you use the validation workflow: A. P. Thompson et al., "LAMMPS - a flexible simulation tool for particle-based materials modeling at the atomic, meso, and continuum scales", *Comput. Phys. Commun.* **271**, 108171 (2022). https://doi.org/10.1016/j.cpc.2021.108171

## License

MIT (see `LICENSE`).
The PCFF force-field files and any data derived from them or generated by EMC are not part of this repository and not covered by this license.
