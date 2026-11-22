# LoupMD in LAMMPS

MACE models in LAMMPS through the LoupMD engine, on one CUDA GPU. The package `ML-LOUPMD` adds:

| style | what it does | when to use it |
|---|---|---|
| `pair_style loupmd` | LAMMPS integrates; positions and forces pass through host memory once per step | the default: any LAMMPS build, any fix |
| `pair_style loupmd/kk` | LAMMPS-Kokkos integrates; positions and forces stay on the GPU | Kokkos CUDA builds that also run other Kokkos styles |
| `run_style loupmd` | the engine integrates between LAMMPS's output steps, in the ensemble of the input's `fix nve`, `nvt`, `npt`, `langevin`, ... | the engine's own step time for NVE, NVT and NPT; a fix the engine has no integrator for is refused by name |

All three run cells larger than the GPU in tiles, as the engine does (see Cells larger than the GPU).

Design and measurements: `LAMMPS_KOKKOS_PLAN.md` in the repository root. The plan for the options of Symmetrix's
pair styles (run modes, several processes, per-atom energies, open boundaries): `LAMMPS_SYMMETRIX_PARITY_PLAN.md`.

## Quick start

```
# 1. the engine library and a model bundle (.loup) for your elements
make -j4 CUDA_ARCH=sm_120                      # in the LoupMD checkout: libloupmd.so
pip install "loupmd[export]"                  # the exporter (or pip install -e ".[export]" in the checkout)
python -m loupmd.export --model mace-omat-0-medium.model --elements 8,22,38 --output omat_O_Ti_Sr.loup

# 2. LAMMPS with the package
lammps/install.sh /path/to/lammps
cmake -S /path/to/lammps/cmake -B build -D PKG_ML-LOUPMD=ON -D LOUPMD_ROOT=/path/to/LoupMD
cmake --build build -j 8
```

```
# 3. an input deck
units           metal
atom_style      atomic
atom_modify     map yes
boundary        p p p
read_data       srtio3.data

pair_style      loupmd
pair_coeff      * * omat_O_Ti_Sr.loup Sr Ti O        # one element per atom type, in type order

timestep        0.001
fix             1 all nvt temp 300.0 300.0 0.1
run_style       loupmd                               # the engine integrates fix nvt's ensemble
thermo          100
run             10000
```

Without the `run_style` line LAMMPS integrates itself, with any of its fixes, at a slower step (see Speed).

For `loupmd/kk`, build LAMMPS with `-D PKG_KOKKOS=ON -D Kokkos_ENABLE_CUDA=ON -D Kokkos_ARCH_<GPU>=ON` as well and run
`lmp -k on g 1 -sf kk -in in.lammps`.

## Syntax

```
pair_style loupmd [device N] [skin S] [ghost yes|no] [ahead yes|no]
                  [capacity auto|whole|tiled|wavefront] [receivers N] [memory F]
pair_coeff * * model.loup El1 El2 ...
```

- `device N`: the CUDA device (default 0; `loupmd/kk`: the device Kokkos uses).
- `capacity`: how the engine evaluates the cell (see Cells larger than the GPU). `auto` (default): the whole cell
  when it fits the card, else in tiles. `whole`: always the whole cell, with no plan. `tiled`: always in tiles.
  `wavefront`: in tiles with the wavefront schedule (models of two layers).
- `receivers N`: at most N atoms per tile (default 0: the plan's choice).
- `memory F`: the share of the card's free memory the plan may use, above 0 and at most 1 (default 0.9).
- `skin S`: the skin of the engine's own neighbour list in Å (default: LAMMPS's `neighbor` skin).
- `ghost no`: tells LAMMPS a pair cutoff of zero, so it creates no ghost atoms. The engine does not need them; LAMMPS
  then warns that the communication cutoff is 0 and switches atom sorting off. Default `yes` (the model's cutoff).
- `ahead yes`: the engine queues each next force pass ahead of the call that needs it. Measured: 2 - 7% off the step
  on cells of a few hundred atoms, nothing at 5,000 atoms. Default `no`, because between two steps the engine's GPU
  stream then holds work that cannot run, and any other GPU library in the same process could wait for it forever.
  Use it only when LoupMD is the process's one GPU user. It is ignored with the KOKKOS or GPU package active, and
  has no meaning for `loupmd/kk`, `run_style loupmd` and the tiled mode.
- `pair_coeff`: the bundle and one element symbol per atom type. Every element must be in the bundle. `NULL` is not
  supported, since the engine evaluates every atom.

```
run_style loupmd
run_style loupmd nve
run_style loupmd langevin T damp seed
```

`run_style loupmd` reads the input's fixes and runs the engine's integrator of that ensemble in their place:

| in the input | the engine runs | limits |
|---|---|---|
| `fix nve` | velocity Verlet | |
| `fix nve` + `fix langevin Tstart Tstop damp seed` | Langevin (the scheme of Vanden-Eijnden and Ciccotti), friction 1 / `damp` | `zero yes` keeps the centre of mass at rest; no `omega`, `angmom` or `scale` |
| `fix nve` + `fix temp/csvr Tstart Tstop Tdamp seed` | velocity rescaling of Bussi, Donadio and Parrinello | the noise is seeded from the fix's generator (package EXTRA-FIX) |
| `fix nve` + `fix temp/berendsen Tstart Tstop Tdamp` | Berendsen thermostat | |
| the same + `fix press/berendsen iso P P Pdamp modulus M` | Berendsen thermostat and barostat, compressibility 1 / `M` | orthogonal box (the fix's own rule); `iso`, or `aniso` / single directions with one pressure and one `Pdamp`; no ramp |
| `fix nvt temp Tstart Tstop Tdamp` | Nosé-Hoover chain (`tchain`, `tloop`) | no `drag` |
| `fix npt temp Tstart Tstop Tdamp iso P P Pdamp` | Martyna-Tobias-Klein, isotropic (`tchain`, `pchain`, `tloop`, `ploop`) | `iso` only (orthogonal or triclinic box, the shape is kept); no pressure ramp, `drag`, `mtk no` or `dilate` |
| `fix setforce 0.0 0.0 0.0` on a group at rest; atoms outside the group of `fix nve` / `nvt` | those atoms are held in place | not with a barostat |
| `fix momentum N linear 1 1 1` on `all` | the centre of mass is kept at rest | in every step |

- The log names what runs (`Ensemble : fix 1 (nvt 300 -> 300 K, Tdamp 0.1 ps, tchain 3): Nose-Hoover chain`).
- Any other fix that acts during the steps stops the run with its name and the reason (`fix nph`, `fix npt aniso`,
  `fix addforce`, `fix shake`, `fix ave/time`, a thermostat with `fix_modify temp`, a temperature given as a
  variable, ...). Nothing is dropped silently. Use LAMMPS's default run style with the pair style for such inputs.
  Fixes that do not act during the steps are untouched.
- The settings carry over as written: temperatures in K with their ramp over the run, `Tdamp` and `Pdamp` in ps,
  pressures in bar, the chain lengths. The integrators are the engine's own (those of ASE 3.27): they sample the
  same ensembles as LAMMPS's fixes with the same parameters, but a trajectory is not LAMMPS's step for step.
- Degrees of freedom. LAMMPS's thermostats count 3N - 3. The engine counts the same when it keeps the centre of mass
  at rest: with `fix momentum` or `zero yes`, and for `nvt`, `npt`, `temp/berendsen` and `temp/csvr` whenever the
  starting velocities have no total momentum (`velocity ... mom yes`) and no atom is held. Otherwise it counts
  three per moving atom.
- The engine runs blocks of steps up to the next step with thermo, dump or restart output. There LAMMPS gets
  positions, velocities and the box back and the pair style evaluates energy, forces and pressure for the output.
  Each output costs about two force evaluations: measured on 320 atoms, +2% on the step with output every 100
  steps and +26 to 34% with output every 10.
- From one `run` command to the next the engine keeps its state, with the thermostat's and the barostat's variables,
  when nothing changed in between (positions, velocities, box, masses, the fixes' settings). After a change those
  variables start from zero, as under a newly defined fix. The noise of `langevin` and `temp/csvr` never repeats
  from run to run.
- The fixes themselves do not run, so their own outputs (`f_ID`, and with them `ecouple` and `econserve`) stay as
  they were. `temp`, `pe`, `ke`, `press` and the box in the thermo output are LAMMPS's own, computed on the state
  the engine returned. The forces LAMMPS writes for atoms under `fix setforce 0 0 0` are zero.
- `run_style loupmd nve` and `run_style loupmd langevin T damp seed` name the ensemble on the line itself; then no
  fix may act during the steps.
- Run it without `-k on` / `-sf kk`.

## Cells larger than the GPU (tiled mode)

A cell whose whole evaluation does not fit the card runs in tiles, as in the Python package (`capacity="auto"`).
The engine cuts the cell into tiles of at most `receivers` atoms, evaluates them one after another, each with the
atoms around it, and sums energy, forces and stress. The results are those of the whole cell to float32 rounding:
on 5,760 atoms of SrTiO3 with MACE-OMAT-0 medium in 12 tiles of 600 atoms, the energy was within 1e-8 eV/atom and
the forces within 3.2e-6 eV/Å of the whole call over the test runs (both without the hybrid GEMMs).

- **When it is decided.** At each send of the system to the engine: a run's setup after a change in the atom
  count, a type, a mass, the skin or the capacity keywords. Under `capacity auto` the engine plans: the whole cell if
  it fits in `memory` of the card's free memory, else tiles of the largest size that fits. A cell that fits in no
  tile size is refused with the sizes.
- **The log says what runs.** At the first step, and at the end of each run. MACE-MH-1 on 50,820 atoms of SrTiO3
  under `run_style loupmd`, a run of 100 steps:
  ```
  LoupMD: 50820 atoms run tiled: 8 tiles of at most 12288 atoms, tile lists on the device; the whole cell would need 24.74 GiB, 12.16 GiB free
  LoupMD: tiled mode in this run: 2 tiled force calls, 100 tiled MD steps, tile lists built 1 times; 8 tiles of at most 12288 atoms
  ```
  The force calls are the setup's and the output's; the steps between them are the engine's tiled MD. With the
  pair style alone every step is a force call. A cell that fits:
  `LoupMD: 5000 atoms run whole: the cell needs ... GiB, ... GiB free`.
- **Host memory and the wavefront.** Where the tiles' neighbour lists, or also the layer state, do not fit on the
  card, the plan puts them in pinned host memory (the log says "tile lists in host memory" or "tile lists and layer
  state in host memory"). From 2^20 atoms (about a million), with 12 or more layers of tiles along the cell's first
  axis, models of two layers run the wavefront schedule. The input does not choose among these; `capacity wavefront`
  forces the schedule.
- **The three styles.**
  - `pair_style loupmd`: each step is one tiled call. The stress is formed only on steps that need the virial.
  - `pair_style loupmd/kk`: in tiled mode it works on LAMMPS's host arrays. The transfers take milliseconds, a tiled
    step hundreds of milliseconds on cells that need tiles.
  - `run_style loupmd` runs the engine's tiled MD between the output steps: `fix nve`, `fix nve` with `fix langevin`,
    `fix temp/csvr` or `fix temp/berendsen`, `fix nvt`, `fix npt ... iso`, and `fix nve` + `fix temp/berendsen` +
    `fix press/berendsen`, with `fix setforce 0 0 0` and `fix momentum`, as in the table above. The tile lists stay
    across output steps and from one `run` command to the next.
- **Barostats.** Under `run_style loupmd` the engine moves the cell in tiled MD as it does whole, and LAMMPS's box
  follows it at each output step. With the pair style and LAMMPS's own `fix npt`, `fix deform` or `fix box/relax`
  the box changes in every step, and the tile lists stay across those changes (next item).
- **Kept lists.** The tile lists are kept from step to step until an atom has moved half the skin. In a box that
  changes, the strain since the lists were built takes part of the skin: they are kept while no atom has moved,
  beyond what the strain and a uniform shift explain (`fix npt` dilates about the box centre), more than
  (r_list (1 - |F - I|) - r_max) / 2, with F the box's deformation since the build and r_list = r_max + skin.
  LAMMPS's sorting and re-wrapping do not break them: the pair style passes unwrapped positions by atom ID.
- **Speed.** Measured on an RTX 5060 Ti under WSL 2 (20 November 2026): MACE-MH-1 on SrTiO3 from rest, 100 warm-up
  and 200 measured NVE steps, `capacity auto`, milliseconds per step. Whole, the two cells need 24.7 and 47.8 GiB;
  under LAMMPS they used to run out of memory.

  | atoms | tiles | Python package | `pair_style loupmd` | `run_style loupmd` | `pair_style loupmd/kk` |
  |---:|---|---:|---:|---:|---:|
  | 50,820 | 8 of at most 12,288 | 420 | 418 | 423 | 425 |
  | 98,415 | 27 of at most 8,192 | 836 | 830 | 838 | 845 |

  (`loupmd/kk` with `-pk kokkos newton on neigh half`: LAMMPS-Kokkos's default full lists refuse `newton on`.)

  MACE-OMAT-0 medium on 320,000 atoms (8 tiles of 65,536) took 537 ms per step under the run style and 513 in the
  Python package, over 40 measured steps. The difference is the block's two output steps: in a tiled run an output
  step costs about one tiled force call (0.39 s on the 50,820 atoms above), so thermo every 10 steps made the run
  style 8% slower than every 200. Under `fix npt` through the pair style the tile lists stay across the box's
  changes: 412 and 413 ms per step on the 50,820 atoms, against 410 and 413 at a fixed cell with the virial in every
  step (before the lists were kept: 491 against 424). `run_style loupmd` with `fix npt ... iso` runs the engine's
  tiled MTK, which took 411 and 412 ms per step in the Python package; under the run style its output steps come on
  top, as above.
- **`ghost no`** is recommended for tiled cells: LAMMPS's ghost atoms of a 100,000-atom cell are host work the
  engine never reads.
- **Not tiled:** MACE-POLAR-1 (long range). `capacity tiled` is refused for it, and under `auto` a cell too large to
  run whole is refused with that reason.

## Requirements and limits

- `units metal`, three periodic dimensions (orthogonal or triclinic box), one MPI process, one GPU.
- Atom IDs must be consecutive (1 … N): the engine keeps atoms by ID, so LAMMPS may sort and reorder them freely.
  Use `reset_atoms id` after deleting atoms.
- Energy, forces and the global virial (pressure, `fix npt`, `fix box/relax`). No per-atom energies or virials
  (`compute pe/atom`, `compute stress/atom`).
- LAMMPS's fixes work with the pair styles as with any pair style. Run on 19 November 2026: `nve`, `nvt`, `npt`,
  `nph`, `langevin`, `temp/csvr`, `temp/berendsen`, `press/berendsen`, `setforce`, `spring/self`, `momentum`,
  `recenter`, `addforce`, `deform`, `nve/limit`, `viscous`, `shake`, `rattle`, `rigid/nve/small`,
  `rigid/nvt/small`, `box/relax` with `minimize`, `hybrid/overlay`. `fix press/berendsen` needs the material's
  `modulus`: LAMMPS's default of 10 bar makes a solid's box explode.
- With LAMMPS's own integrator a changing box (`fix npt`) rebuilds the engine's neighbour list in every step of a
  whole cell (a tiled cell keeps its tile lists, above). `run_style loupmd` runs `fix npt ... iso` at the engine's
  step time instead (see Speed), whole or in tiles.
- An isolated molecule needs a periodic box with more than 2 (cutoff + skin) of vacuum.
- MACE-POLAR-1 models run as in the engine: neutral, singlet, zero field.
- `hybrid/overlay` with other pair styles works with the pair styles (forces are added), not with `run_style loupmd`.

## Speed (RTX 5060 Ti under WSL 2, MACE-OMAT-0 medium, Langevin 300 K, 19 November 2026)

SrTiO3 from the benchmark inputs, 100 warm-up and 256 measured steps, two runs each:

| | 5,000 atoms, ms/step | 320 atoms, ms/step |
|---|---|---|
| `run_style loupmd` | 7.84 - 7.86 | 0.61 - 0.63 |
| `pair_style loupmd` | 8.20 | 0.86 - 0.90 |
| `pair_style loupmd/kk` | 8.14 - 8.19 | 0.97 - 1.03 |
| Symmetrix `symmetrix/mace/foundation/float32/kk` (same LAMMPS version, same job) | 13.47 - 13.54 | 1.55 - 1.59 |

With `pair_style loupmd` a step is the engine's force pass plus about 0.2 ms: the start of the engine's step on an
idle GPU, which the engine's own loop hides by queueing ahead, and LAMMPS's own CPU work (another 0.2 ms at 5,000
atoms). `run_style loupmd` avoids both.

The ensembles of the fixes (rattled SrTiO3 cells, 300 K, 1 fs, 2,000 steps after 200, thermo every 1,000, two runs
each with fresh GEMM plans; ms/step):

| atoms | input | the Python package's own loop | `run_style loupmd` | LAMMPS integrates (`pair_style loupmd`) |
|---|---|---|---|---|
| 320 | `fix nvt` | 0.647, 0.647 | 0.651, 0.647 | 0.810, 0.837 |
| 320 | `fix npt iso` | 0.795, 0.780 | 0.783, 0.792 | 1.309, 1.287 |
| 320 | `fix nve` + `fix langevin` | 0.580, 0.573 | 0.594, 0.578 | 0.795, 0.801 |
| 1,080 | `fix nvt` | 1.748, 1.751 | 1.775, 1.761 | 1.969, 2.007 |
| 1,080 | `fix npt iso` | 1.847, 1.863 | 1.844, 1.847 | 2.630, 2.643 |
| 1,080 | `fix nve` + `fix langevin` | 1.718, 1.711 | 1.718, 1.716 | 1.986, 2.032 |
| 5,000 | `fix nvt` | 7.689, 7.678 | 7.743, 7.729 | 8.069, 8.083 |
| 5,000 | `fix npt iso` | 7.687, 7.666 | 7.674, 7.663 | 8.891, 8.861 |
| 5,000 | `fix nve` + `fix langevin` | 7.659, 7.676 | 7.663, 7.677 | 8.192, 8.166 |

The run style is within 1% of the package's own loop in every row. LAMMPS integrating itself takes 1.04 to 1.27
times as long with `fix nvt` and 1.16 to 1.65 times with `fix npt`.

Under WSL 2 every blocking exchange between host and GPU costs 0.1 - 0.2 ms, and LAMMPS-Kokkos makes several per step:
with a zero-strength Lennard-Jones potential on 648 atoms it takes 2.4 ms per step by itself. That is why
`loupmd/kk` trails the plain style there. On native Linux the Kokkos style has not been measured.

## Files

```
lammps/install.sh                          copies the sources into a LAMMPS tree and registers the package
lammps/cmake/ML-LOUPMD.cmake               finds loupmd.h and libloupmd.so (LOUPMD_ROOT)
lammps/ML-LOUPMD/pair_loupmd.{h,cpp}       pair_style loupmd
lammps/ML-LOUPMD/integrate_loupmd.{h,cpp}  run_style loupmd
lammps/KOKKOS/pair_loupmd_kokkos.{h,cpp}   pair_style loupmd/kk
lammps/examples/                           input decks
```

The files in `lammps/` are built into LAMMPS and are distributed under the GNU General Public License version 2,
as LAMMPS is (`lammps/LICENSE`; the owner's decision of 19 November 2026). `libloupmd.so` keeps LoupMD's licence and
is linked through its C interface (`include/loupmd.h`).

Written against LAMMPS `stable_30Sep2026_update1` (Kokkos 5.2.1).
