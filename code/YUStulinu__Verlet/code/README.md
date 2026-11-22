# Verlet

Molecular dynamics from scratch:
- an engine in C++ with a CUDA plugin (nonbonded forces and particle-mesh Ewald with an own FFT);
- bonded terms in modern Fortran;
- system preparation from PDB files in Python;
- analysis in Julia (structure, density, diffusion, free energy);
- a WebGL molecule viewer in TypeScript.

Everything is compared with OpenMM on the same systems and with experiment.

## What is in it

| part | language | what it does |
|---|---|---|
| `engine/src`, `engine/include` | C++20 | system reader; Lennard-Jones and real-space Ewald with a Verlet list; smooth PME (B-splines of order 5, mixed-radix Stockham FFT written here); exclusion and self corrections; long-range dispersion correction; SETTLE and SHAKE/RATTLE; the Langevin-middle integrator (leapfrog Verlet at zero friction); Monte Carlo barostat; minimizer; alchemical decoupling of a water (charge scaling + Beutler soft core) with energies at every state |
| `engine/fortran/bonded.f90` | Fortran 2018 | bonds, angles, proper and improper periodic torsions, scaled 1-4 pairs, through `bind(C)` |
| `engine/cuda/plugin.cu` | CUDA | the nonbonded and PME work on the GPU: atoms sorted by cell, neighbor list, 8 threads per atom, PME spread / FFT / convolution / gather in float with double energy sums. It is a separate library with a C interface, loaded at run time, because on Windows nvcc needs MSVC while the engine is built with g++/gfortran |
| `prep/verlet_prep` | Python | PDB reader and writer; Amber ff14SB + TIP3P parameters read from OpenMM's ffxml files (data only); template matching; bonded terms with OpenMM's torsion and improper rules; water boxes, solvation, ions |
| `analysis/` | Julia | RDF, block averages, MSD and diffusion with the Yeh-Hummer correction, RMSD after Kabsch superposition, MBAR and TI |
| `viewer/` | TypeScript, WebGL2 | sphere impostors and bonds, trajectory playback, water on or off |
| `eval/` | Python, sh | comparison with OpenMM, OpenMM runs of the same systems, benchmark, free-energy windows, export for the viewer, figures |

The proteins are NMR models with hydrogens (1L2Y Trp-cage, 1UAO chignolin), so no hydrogens are built.

## Results

All runs use TIP3P (and Amber ff14SB for the protein), rigid water, X-H constraints, 2 fs, PME with tolerance 5e-4 and a 0.9 nm cutoff with the dispersion correction, Langevin middle at 1/ps, Monte Carlo barostat at 1 bar, and an RTX 2060.

### The same energies and forces as OpenMM

Our parameters are loaded into OpenMM (Reference platform, double precision), with the same positions, PME grid and alpha (`eval/compare_openmm.py`):

| system | atoms | engine | total energy (kJ/mol) | energy difference | force RMS difference (RMS force) |
|---|---|---|---|---|---|
| 216 waters | 648 | CPU (double) | -493.19 | 1e-8 | 7.5e-6 (638) |
| Trp-cage in 2495 waters + Cl- | 7790 | CPU (double) | -3776.27 | 4.5e-6 | 7.7e-6 (656) |
| 216 waters | 648 | GPU (float) | -493.19 | 1.7e-3 | 1.4e-3 (638) |
| Trp-cage in water | 7790 | GPU (float) | -3776.27 | -8.7e-3 | 2.8e-3 (656) |

Our ff14SB assignment against OpenMM's own `ForceField.createSystem` for chignolin: every term agrees within 1e-5 kJ/mol. A few aromatic impropers list their atoms in another order, because OpenMM reuses the atom order of the first improper with the same type signature. The energy is the same, and the forces differ by at most 1.2e-3.

### Energy conservation (NVE, GPU)

2180 waters, 20 ps after 10 ps of NVT:

| time step | drift | fluctuation of the total energy |
|---|---|---|
| 2 fs | -1.4e-3 kT/ns per degree of freedom | 2.7 kJ/mol |
| 1 fs | +3.2e-4 kT/ns per degree of freedom | 2.0 kJ/mol |

### Water: density and structure against experiment

2180 waters, NPT at 298.15 K and 1 bar, 100 ps of equilibration, then 400 ps. Errors are block-average standard errors. Computed by `analysis/water.jl`:

| | Verlet | OpenMM | experiment |
|---|---|---|---|
| density (g/cm³) | 0.9853 ± 0.0005 | 0.9854 ± 0.0005 | 0.99705 |
| potential energy per molecule (kJ/mol) | -40.07 | -40.09 | -41.5 (from the heat of vaporization) |
| first O-O peak | 0.278 nm, height 2.70 | 0.278 nm, height 2.71 | 0.280 nm, height 2.57 (X-ray) |
| self-diffusion, finite-size corrected (cm²/s) | 5.2e-5 | 5.1e-5 | 2.3e-5 |

![RDF](https://github.com/YUStulinu/Verlet/raw/HEAD/results/rdf.png)

The two programs agree within their error bars. The differences from experiment are those known for TIP3P, which is 1.2% too light, slightly over-structured and more than twice as mobile. The temperature Verlet reports is 297.0 ± 0.6 K, against 298.4 ± 0.6 K for OpenMM. Since density, energy and structure agree, this most likely comes from the kinetic-energy estimate at the half step, not from the dynamics.

### Free energy of hydration of a water

One TIP3P water decoupled from 499 others: 5 windows switch its charges off, then 10 windows switch its Lennard-Jones off with a soft core. Each window runs 20 ps of equilibration and 200 ps of production, NPT, sampled every 1 ps. Computed by `eval/fep_water.sh` and `analysis/fep.jl`:

| method | ΔG of hydration (kJ/mol) |
|---|---|
| MBAR, 15 states | -25.6 ± 0.6 |
| TI, trapezoid rule (charges -35.2, Lennard-Jones +9.0) | -26.2 ± 0.5 |
| experiment (Ben-Naim and Marcus) | -26.5 |

### Trp-cage

1 ns NPT from the NMR structure, two independent runs per program. Backbone (N, CA, C) RMSD against the NMR model over the second half, from `analysis/protein.jl`:

| run | Verlet | OpenMM |
|---|---|---|
| seed 1 | 0.156 ± 0.033 nm (max 0.263) | 0.080 ± 0.013 nm (max 0.119) |
| seed 2 | 0.116 ± 0.023 nm (max 0.163) | 0.092 ± 0.024 nm (max 0.140) |

The fold is kept in every run. Verlet's backbone moves somewhat more in both of its runs. Two nanosecond-long runs per program cannot tell whether this is systematic.

### Speed

Same system and settings for both programs (`eval/benchmark.sh`; the long runs above give the same numbers):

| system | atoms | Verlet | OpenMM 8.6.1 (CUDA, mixed) |
|---|---|---|---|
| 2180 waters | 6540 | 130 ns/day | 535 ns/day |
| Trp-cage in water | 7790 | 102 ns/day | 417 ns/day |
| 500 waters, alchemical | 1500 | 193 ns/day | |

Verlet is about four times slower. The GPU kernels take about 0.6 ms per step. The rest is on the CPU: the integrator and the constraints, kernel launches (expensive under Windows' WDDM), and copying positions and forces every step. This comes from the design, which keeps the bonded terms in Fortran on the CPU. Moving the integration onto the GPU is the next step for speed.

## Building and running

```bash
engine/build.sh          # C++ + Fortran (MSYS2 UCRT64 on Windows: its bin must come first on PATH)
ctest --test-dir engine/build/cm
cmake -S engine/cuda -B engine/build/cuda && cmake --build engine/build/cuda --config Release   # GPU plugin
python -m venv .venv && .venv/Scripts/pip install openmm numpy matplotlib pytest
PYTHONPATH=prep python -m verlet_prep water 2180 --out data/systems/water2180.vsys
PYTHONPATH=prep python -m verlet_prep protein data/pdb/1L2Y.pdb --out data/systems/trpcage.vsys
engine/build/cm/verlet run data/systems/water2180.vsys --minimize 500 --temperature 298.15 --pressure 1 \
    --equilibrate 50000 --steps 200000 --log run/w.csv --traj run/w.vtrj
julia --project=analysis analysis/water.jl data/systems/water2180.vsys verlet run/w.csv run/w.vtrj
eval/fep_water.sh && julia --project=analysis analysis/fep.jl run/fep 15
python eval/export_viewer.py data/systems/water2180.vsys run/w.vtrj water "Water" && (cd viewer && npm ci && npm run build && npm run serve)
```

OpenMM is used only as the comparison, and its force-field XML files as parameter data.

## Tests and CI

- Engine: 61 checks.
  - FFT against a direct DFT;
  - PME against the plain Ewald sum;
  - every force term against finite differences;
  - SETTLE against SHAKE, and the velocity constraints;
  - NVE conservation;
  - the alchemical forces and energies;
  - input checks.
- Preparation: 3 tests, including the parameter comparison with OpenMM.
- Analysis: 11 tests (ideal-gas RDF, random-walk diffusion, MBAR on harmonic states, Kabsch RMSD).
- Viewer: 4 tests.
- GitHub Actions runs all of them, on the CPU. The CUDA plugin is not built there (no GPU).

## License

MIT
