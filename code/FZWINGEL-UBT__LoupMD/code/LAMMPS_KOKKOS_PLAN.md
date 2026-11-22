# LoupMD in LAMMPS (Kokkos): integration plan

Status (S145, 19 November 2026, branch `develop`, 5060 Ti under WSL 2 only): stages A and B are built, with a run
style in addition; stage C is built in part. The section "Built and measured" below records what exists and where it
differs from the plan that follows it. Figures marked *estimate* are not measurements.

## Built and measured (S145)

**What exists** (`lammps/`, user guide in `lammps/README.md`):

| piece | state |
|---|---|
| `pair_style loupmd` (stage A; host arrays) | built |
| `loup_compute_device`, `loup_cutoff`, `loup_species` (stage B engine API) | built; `python/loupmd.py` binds them (`LoupEngine.compute_device`) |
| `pair_style loupmd/kk` (stage B) | built |
| `run_style loupmd nve` / `langevin` (not in the plan's stages; the plan's fallback, as a run style) | built |
| `loup_evaluate` as one captured graph per call (found necessary for the plain style) | built |
| installer, CMake module, examples, `tests/test_lammps.py`, `tests/test_device_io.py` | built |
| strain-aware neighbour list for changing cells (stage B item) | not built: `fix npt` rebuilds the list every step |
| per-atom energies, `loupmd lammps` CLI on the release package, docs-site page, CI compile job (stage C) | not built |
| stages D-F | not built |

**Accuracy** (`run 0` against the Python engine on the same structure, both pair styles):

- Five cases:
  - OFF23-S water216;
  - OMAT-0 medium SrTiO3 with 320 atoms (sheared cell) and with 5,000 atoms;
  - MH-1 NaCl216;
  - POLAR-1-M NaCl216 (sheared cell).
- Energy, forces and all six pressure components agree within the spread of two engine runs: forces to
  2e-7 - 5e-6 eV/Å, pressure to 6e-4 - 0.08 bar on up to 7.8e4 bar.
- That settles the virial's sign and component order, the box-to-cell mapping (triclinic included) and the ID
  mapping.

**MD** (OFF23-S water216, 2,000 steps of 0.5 fs from 300 K):

| integrator | total-energy drift, meV/atom |
|---|---|
| engine (`run_style loupmd nve`) | +0.092 |
| LAMMPS `fix nve`, `loupmd` | +0.099 |
| LAMMPS `fix nve/kk`, `loupmd/kk` | +0.080 |

- The spread is 0.18 meV/atom in all three, while the kinetic energy moves by 44 - 46 meV/atom.
- After 100 steps from the same start, the engine's integrator and `fix nve` give the same potential energy at the
  log's resolution (1.5e-7 eV/atom) and kinetic energies 5e-9 eV/atom apart.
- Sorting the atoms every step changes nothing at the log's resolution, in both styles.
- `fix npt` runs in both styles.

**Speed** (ms per MD step; Langevin 300 K, 1 fs):

| system (MACE-OMAT-0 medium unless noted) | engine's own loop | `run_style loupmd` | `loupmd` | `loupmd/kk` | Symmetrix foundation float32/kk |
|---|---|---|---|---|---|
| SrTiO3, 5,000 atoms | 7.71 - 7.74 | 7.81 - 7.86 | 8.20 | 8.38 - 8.45 | 13.47 - 13.54 |
| SrTiO3, 320 atoms | 0.59 - 0.61 | 0.61 - 0.64 | 0.86 - 0.90 | 1.29 - 1.38 | 1.55 - 1.59 |
| NaCl, 216 atoms | 0.29 - 0.30 | not run | 0.52 - 0.54 | 1.60 | not run |
| OFF23-S water, 648 atoms | 0.34 - 0.36 | 0.376 (NVE, output every 100 steps) | 0.57 - 0.59 | 2.2 - 2.9 | – |

- The SrTiO3 rows use the benchmark environment's inputs and protocol (`in.sym_md`: from rest, damp 0.5 ps, 100 + 256
  steps), each code twice in one job. Symmetrix is the benchmark environment's build of 16 November, on the same
  LAMMPS release.
- The engine's own loop on the SrTiO3 rows is `LoupEngine.run_langevin` on the same data files with the same
  protocol, in one job with the run style (`a b b a`): the run style is 1 - 1.5% slower at 5,000 atoms and 2 - 7%
  at 320 (single runs 3% apart), the cost of handing the state back and evaluating energy and pressure at each
  output step. It is the same loop, so it cannot be faster; both end at the same temperature (158 K, 149 - 150 K).
  The 16 November five-engine run had the engine at 8.45 ms/step on the 5,000-atom case, with that day's library.
- After S145, `loupmd/kk` requests an occasional neighbour list, so that LAMMPS-Kokkos keeps its own per-step work
  on the GPU: the `loupmd/kk` column's SrTiO3 rows became 8.14 - 8.19 and 0.97 - 1.03 ms/step (a later job, same
  protocol). It also fixes an abort of rigid bodies in bonded systems under Kokkos.
- With `pair_style loupmd`, 26 LAMMPS setups (integrators, thermostats, barostats, constraints, minimisers) were
  run: table in `LAMMPS_SYMMETRIX_PARITY_PLAN.md`, Part 1.
- Symmetrix-XL on the NaCl case was 3.55 - 3.61 ms/step on 5 November (not rerun).

**What the measurements changed:**

- **LAMMPS-Kokkos has its own per-step cost under WSL 2.**
  - With a zero-strength Lennard-Jones potential on the 648 water atoms it takes 2.43 ms per step
    (`neigh_modify check no`: 0.52); plain LAMMPS takes 0.115.
  - Each blocking exchange between host and GPU costs 0.1 - 0.2 ms there, and LAMMPS-Kokkos makes several per step.
  - So on this machine `loupmd/kk` cannot reach the plain style on small systems, whatever the pair style does.
  - Native Linux is not measured.
- **`loup_evaluate` was the plain style's bottleneck, and is now one graph launch.**
  - Before: positions and forces through pageable memory, a stream synchronisation, and about eight separate
    submissions per call.
  - Now: page-locked staging; the upload, the skin check, the guarded force pass or on-device rebuild and the
    downloads in one captured graph; the host polls two publications.
  - OFF23-S water216: 0.95 - 1.14 → 0.41 - 0.51 ms per call (Python, same job); the plain style 0.87 → 0.57 - 0.59
    ms/step.
  - Every `loup_evaluate` user gains this, not only LAMMPS.
- **The engine's speed needs the engine's integrator.** With LAMMPS integrating on the host, each step still waits
  for the forces and pays the next launch's latency (0.2 ms on water216). `run_style loupmd` removes that. It reaches
  the engine's own step time, at the price that no fix may act during the steps.
- **Run calls with unchanged parameters reuse their captured graphs** (before, every `loup_run_*` call re-captured
  them), so a run in blocks costs one extra force pass per block and no re-capture.
- **`ghost no`** removes LAMMPS's ghost atoms for this pair style. It did not change the Kokkos style's step time
  (the cost above is not ghost traffic), so it stays an option, default off.

**Open after S145:**

- the strain-aware list (NPT at 1.7 - 1.9× the NVE step on water216);
- the rest of stage C;
- a native-Linux measurement of `loupmd/kk`;
- the release branch (`release/v1` has its own variable-cell step and kernel plugins: the engine API of this branch
  has to be ported there, not copied).

---

The plan as written before the build follows.

## Goal

A LAMMPS user with a GPU writes

```
units          metal
atom_style     atomic
pair_style     loupmd/kk                          # or plain `loupmd` in a LAMMPS build without Kokkos
pair_coeff     * * mace-omat-0-medium_8_22_38.loup O Ti Sr
```

and runs `lmp -k on g 1 -sf kk -in in.lammps`. LAMMPS keeps doing what it already does: integrators, thermostats
and barostats, computes, dumps, fixes and `hybrid/overlay` with other pair styles. LoupMD supplies the MACE energy,
forces and virial, from data that stays on the GPU.

"Easily" means three things:

- one `pip install loupmd` provides the library, the header and the LAMMPS sources;
- one command patches a LAMMPS checkout;
- one command writes the bundle.

No `nvcc` beyond what a Kokkos CUDA build of LAMMPS already needs.

## What LoupMD offers today, and what that means for LAMMPS

From `include/loupmd.h` and `src/engine.cu`:

| property today | consequence for a LAMMPS pair style |
|---|---|
| C API with host arrays (`loup_evaluate`: positions in, energy / forces / stress out, all `double`, in the caller's atom order fixed at `loup_set_system`) | a plain pair style works now, with no engine change (stage A) |
| `loup_evaluate` copies positions and forces through host memory (host-side permutation loops) and synchronises twice (the skin check reads a flag, then forces come back) | under WSL2 a host round trip costs 100-200 µs (`AGENTS.md`). Water216 runs 0.35 ms/step, so these copies and syncs would cost a large fraction of the step on small systems: the Kokkos style needs a device-resident call (stage B) |
| the engine builds its own periodic neighbour list (cell lists, sorted rows, `PRELOC` slabs, species-grouped atoms) and is fully periodic only (singular cells are refused) | a single process can ignore LAMMPS's neighbour list and ghost atoms: the gates certify the engine's own list. Non-periodic boundaries and domain decomposition need engine work (stages D, E) |
| the cell enters as a 3×3 row-major matrix; a changed cell forces a neighbour-list rebuild and re-records graphs (`upload_positions`: `cell_changed`, `gen->set_cell`) | `fix npt` changes the box every step, so it would rebuild every step: a strain-aware list is a stage-B item |
| the virial accumulates as `v_grad` [xx, xy, xz, yy, yz, zz] (stress = `v_grad / V`) | LAMMPS wants `virial[6]` = [xx, yy, zz, xy, xz, yz] with the sign of Σ r·f; map the indices and sign, then confirm by finite differences of the energy |
| no per-atom energies or virials | `compute pe/atom` needs per-atom energies (stage C); per-atom virials stay unsupported (as in `symmetrix/mace/kk`) |
| POLAR-1's k-space needs the whole periodic system | POLAR runs in single-process mode only, until stage F |
| a step on device: graph-captured force pass; the MD loop's SWITCH node rebuilds on the GPU, and the host only polls a flag in mapped memory | the device call can reuse the same machinery without the integrator, so no host sync on most steps |

Reference design, for structure only (no code is copied; it is GPLv2): Symmetrix's
`pair_symmetrix/pair_symmetrix_mace_kokkos.cpp`. That single-process mode takes LAMMPS's full neighbour list and maps
ghosts back to owned atoms by tag (`atom->map`), and its `mpi_message_passing` mode communicates the hidden features
between layers (`comm_forward = comm_reverse = num_LM * num_channels`). LoupMD differs in one respect: its neighbour
list is part of what is tuned and gated, so the single-process styles keep it.

## Architecture

```
LAMMPS (Kokkos, CUDA)                          libloupmd.so (C ABI, MIT)
-----------------------                        --------------------------
PairLoupMDKokkos::compute()
  sync X, TYPE, TAG, IMAGE on device
  kernel: unwrap x with image flags  ──────►   loup_compute_device(h, io, cell, stream, ...)
          (x + image · h), tag - 1 -> id          wait on the caller's stream (event)
                                                  gather rows -> engine order (inverse perm)
                                                  skin / strain check -> guard -> SWITCH
                                                     force graph | on-device rebuild + rest
                                                  scatter forces: f[row] += F[engine atom]
                                                  record event, caller's stream waits on it
  eng_vdwl, virial  ◄── host copies only on eflag / vflag steps
```

- **Atom identity.** LAMMPS reorders local atoms when it sorts and reneighbours, and LoupMD fixes the order at
  `loup_set_system`. The bridge is the atom ID: engine atom = `tag - 1`. The pair style therefore requires
  consecutive IDs (`atom->map_tag_max == atom->natoms`; otherwise an error that suggests `reset_atoms id`) and calls
  `loup_set_system` again only when `natoms` or any atom's type changes. The type check is a device reduction over
  `type`, folded into the unwrap kernel. Neither sorting nor reneighbouring touches the engine.
- **Unwrapped positions.** At reneighbouring LAMMPS wraps atoms back into the box, so a raw position jumps by a box
  vector, which the engine's skin check would read as motion and answer with a rebuild. The unwrap kernel adds the
  image flags back (`x + h0·xbox + h5·ybox + h4·zbox`, `y + h1·ybox + h3·zbox`, `z + h2·zbox`, as `Domain::unmap`)
  and keeps the engine's positions continuous. The engine wraps internally.
- **Cell.** From `domain->h`: rows a = (h0, 0, 0), b = (h5, h1, 0), c = (h4, h3, h2). This matches LoupMD's
  row-major lattice vectors, triclinic included.
- **Streams.** The Kokkos CUDA execution space's stream (`Kokkos::DefaultExecutionSpace().cuda_stream()`) is passed
  in. LoupMD orders itself after it with an event, runs its graphs on its own streams (the captured graphs and side
  lanes are unchanged), and makes the caller's stream wait on a completion event. There is no host sync unless energy
  or virial is requested, or a rebuild outgrows the captured sizes (the MD loop's host fallback).
- **Energy and virial.** Copied to host only when LAMMPS asks for them (`eflag_global` / `vflag_global`: thermo
  steps, `fix npt` / `box/relax` every step). `no_virial_fdotr_compute = 1`, since the engine returns no pair
  forces.
- **Ghosts.** In the single-process styles, ghost atoms exist (LAMMPS builds them from the pair cutoff) but are
  unused. Forces go only to owned atoms, so `newton on` and `off` both work and the reverse communication adds zeros.
- **Neighbour list.** None requested: LoupMD builds its own. `init_one` returns the bundle's `r_max`, so LAMMPS's
  communication cutoff stays sane. If a LAMMPS version insists on a request, ask for a half list at `r_max` and ignore
  it (to check against the target LAMMPS version).

## Stages

| stage | scope | done when |
|---|---|---|
| A | `pair_style loupmd` (host arrays, any LAMMPS build) on today's `loup_evaluate`, with the tag mapping, unwrap, cell, virial mapping and `units metal` check; installer; examples | `run 0` energy / forces / virial equal a Python `LoupEngine` call on the same structure (at the cross-process level); NVE drift and `fix npt` sanity on three families |
| B | engine: `loup_compute_device` (device-resident I/O, the caller's stream, forces added, no host sync on ordinary steps) and a strain-aware neighbour list for changing cells; `pair_style loupmd/kk` on it | same accuracy checks as A with `-sf kk`; LAMMPS step time within the targets below of `loupmd md` on the same system |
| C | per-atom energies (`eflag_atom`, `compute pe/atom`); optional skin and device keywords; `loupmd lammps` CLI; docs page; CI job | `compute pe/atom` sums to `pe`; docs build; one-command install from the wheel works on a clean LAMMPS checkout |
| D | engine: open (non-periodic) and mixed boundaries (`boundary p p f`, `s s s`) | molecules in vacuum match a large padded periodic box |
| E | several GPUs: domain decomposition, first with a ghost shell of `n_layers · r_max` (each process evaluates owned + ghost atoms, the energy only of owned atoms, ghost forces reverse-communicated), later per-layer feature exchange | two processes on one or two GPUs equal one process; scaling measured |
| F | POLAR-1 under decomposition: the structure factors summed over processes (`MPI_Allreduce` per SCF iteration) | POLAR-1-M NaCl, two processes equal one |

Stages A-C are what "users can easily use LoupMD in LAMMPS" needs for one GPU. D-F are separate decisions (below).

### Stage A: plain pair style (no engine change)

- `lammps/ML-LOUPMD/pair_loupmd.{h,cpp}`:
  - `PairLoupMD : Pair`, settings `pair_style loupmd [device N] [skin S]`, and `pair_coeff * * file.loup El1 El2 ...`.
  - Each element maps to Z. The bundle's species must include them all; otherwise list the bundle's species.
  - Flags: `manybody_flag = 1`, `single_enable = 0`, `one_coeff = 1`, `restartinfo = 0`,
    `no_virial_fdotr_compute = 1`, `centroidstressflag = CENTROID_NOTAVAIL`.
  - `init_style`:
    - requires `units metal`, atom IDs and `atom_modify map`, consecutive IDs and one MPI process (multi-process
      waits for stage E: error with the reason);
    - creates the handle once (`loup_create`);
    - calls `loup_set_system(natoms, Z[tag - 1], masses, skin)`.
  - `compute`:
    - gathers the unwrapped positions into ID order (host);
    - calls `loup_evaluate` with stress when `vflag_global`;
    - adds the forces back by `atom->map`;
    - tallies `eng_vdwl` and `virial`.
  - On any `-1` return: `error->one` with the engine's stderr line.
- `lammps/install.sh` (patch mode, like most external LAMMPS packages):
  - copies the sources into `lammps/src/ML-LOUPMD` and `lammps/src/KOKKOS`;
  - adds `cmake/Modules/Packages/ML-LOUPMD.cmake`, which finds `loupmd.h` and `libloupmd.so` through `LOUPMD_ROOT`
    or `python -m loupmd --prefix`, links the shared CUDA runtime and sets an rpath;
  - registers `PKG_ML-LOUPMD` in `cmake/CMakeLists.txt` and the docs' package list.
- Checks:
  - The engine's `v_grad` → LAMMPS `virial`: index map [0, 3, 5, 1, 2, 4], sign = −1 (expected from
    stress = v_grad / V and LAMMPS's W = Σ r·f). This is to be confirmed, not assumed. Check `pxx…pyz` from
    `compute pressure NULL virial` against −dE/dε by central differences (`change_box … remap`) on an orthogonal and
    a triclinic cell.
  - Forces and energy against `python/loupmd.py`'s `LoupEngine` on each gate system: OFF23-S water216, OMAT-0 medium
    SrTiO3, MH-1 NaCl216, POLAR-1-M NaCl216. Compare with `LOUP_CONV_TUNE=0` against a second engine run, as in
    `JIT_DESIGN.md`, since the order of the atomics differs between processes.
- Cost: the host copies and the two syncs per step. This is acceptable only for large systems, which is why the
  Kokkos style follows.

### Stage B: device-resident call and the Kokkos style

**Engine API** (C ABI, no Kokkos types; `loupmd.h` interface version + 1):

```c
typedef struct {
    int n_rows;               // rows to read (LAMMPS: nlocal); equal to n_atoms of loup_set_system
    const double* positions;  // device [n_rows][pos_stride], unwrapped, A
    int pos_stride;           // 3 for LAMMPS's t_x_array
    const int* ids;           // device [n_rows]: engine atom of each row (0 .. n_atoms-1); NULL = identity
    double* forces;           // device [n_rows][f_stride]: ADDED to (pair styles accumulate)
    int f_stride;
    double* atom_energy;      // device [n_rows] or NULL (stage C): added to
    int flags;                // LOUP_IO_ENERGY | LOUP_IO_VIRIAL | LOUP_IO_ATOM_ENERGY
} LoupDeviceIO;

// Enqueue one force evaluation after the work already on `stream` (a cudaStream_t); returns after enqueueing.
// Blocks only for what the flags ask the host to receive (energy, virial), or when a neighbour rebuild outgrows the
// captured sizes. out_virial is in LAMMPS order (xx yy zz xy xz yz) and sign.
int loup_compute_device(LoupHandle* h, const LoupDeviceIO* io, const double* cell, void* stream,
                        double* out_energy_ev, double* out_virial);
```

Inside the engine:

- Gather and scatter are separate kernels before and after the force graph, because LAMMPS reallocates `x` / `f`
  when `nmax` grows, and that must not invalidate the captured graphs.
- The skin decision reuses the MD loop's device-side machinery: `check_skin_kernel`, then `guard_step_kernel`, then
  the SWITCH node (force pass | rebuild + checked rest). The host polls the mapped flag, which lands before the force
  pass starts, so ordinary steps return without waiting for forces. This is the `run_md_loop` design without the
  integrator kernels, and must keep its rules: no host sync in the step, no extra conditional nodes, the rebuild
  paths capturable.
- The atomics of the force assembly write the engine's float64 force buffer as now. The scatter adds it into the
  caller's rows, so `hybrid/overlay` (for example with LAMMPS's own `dispersion/d3` or `zbl`) accumulates correctly.
- **Changing cells** (`fix npt`, `box/relax`, `deform`):
  - keep each edge's integer image shift;
  - on a cell change, recompute the Cartesian shifts in one kernel and widen the skin test by the strain since the
    last build (bound per pair: |Δh| · |s|), instead of rebuilding and re-recording;
  - rebuild only when that bound exceeds skin / 2;
  - POLAR-1's k-vectors depend on the cell: recompute them per step under NPT. Measure that cost on its own.

**`lammps/KOKKOS/pair_loupmd_kokkos.{h,cpp}`:**

- Template and data masks:
  - `PairLoupMDKokkos<DeviceType> : PairLoupMD`, styles `loupmd/kk`, `loupmd/kk/device` (and `/kk/host`, refused
    with a message: the engine is CUDA only);
  - `datamask_read = X_MASK | TYPE_MASK | TAG_MASK | IMAGE_MASK | F_MASK`, `datamask_modify = F_MASK`;
  - `atomKK->sync(execution_space, datamask_read)` and `atomKK->modified(execution_space, F_MASK)`.
- One `parallel_for` per step over `nlocal`:
  - decodes the image flags (`IMGMASK`, `IMGBITS`, `IMG2BITS`; `imageint` may be 64-bit);
  - writes the unwrapped positions and `tag - 1` into two persistent Views;
  - ORs a "type changed" bit against the previous step's types.
  It then calls `loup_compute_device` with the View pointers, `k_f.view<DeviceType>().data()` and the Kokkos stream.
- Device: check that the engine's `device_id` equals Kokkos's device (`Kokkos::device_id()`); one context per
  process.
- Build: the Kokkos CUDA build already uses `nvcc_wrapper`; the pair style itself has no CUDA code beyond the Kokkos
  lambda. Link the shared CUDA runtime on both sides (`-D CMAKE_CUDA_RUNTIME_LIBRARY=Shared`) to avoid two runtimes
  in one process. Check what Kokkos does by default in the target LAMMPS.

**Performance targets for stage B (*estimates*, to be measured).** These are LAMMPS step times with `fix nve/kk` (or
`fix langevin/kk` + `nve/kk`) against `loupmd md` / `loup_run_langevin` on the same structure, library and plans:

- ≤ 3% slower at 5,000 atoms (OMAT-0 medium SrTiO3, 7.7 ms/step);
- ≤ 10% slower at 648 atoms (OFF23-S water216, 0.35 ms/step), where launches and LAMMPS's own per-step work (a few
  Kokkos kernels, its thermo and neighbour bookkeeping) weigh most.

If the small-system gap is larger, the fallback is a `fix loupmd/md` that hands N steps of NVE / Langevin to the
engine's own loop between LAMMPS output steps. It trades LAMMPS's per-step features for speed, so it is a separate
style and not the default.

### Stage C: usability

- Per-atom energies: the readout's per-atom terms (plus E0) written to `atom_energy` on request. `compute pe/atom`
  must sum to `pe`.
- Keywords: `device N` (default: Kokkos's device or 0), `skin S` (default: LAMMPS's `neighbor skin`, which also
  drives LoupMD's list), `jit on|off` (sets `LOUP_JIT` before `loup_create`), `plans DIR` (`LOUP_CACHE_DIR`).
- Log at `init_style`:
  - the bundle (model hash, species, head, charge / spin);
  - the per-system tuning time at the first compute (`tune_ms`);
  - JIT compiles;
  - which GEMM cubin is loaded.
- CLI on the release package (`loupmd/cli/lammps.py`):
  - `loupmd lammps bundle MODEL --elements O,Ti,Sr [--head H] [--charge Q --spin M] -o x.loup` (the existing export,
    named for LAMMPS's element order);
  - `loupmd lammps install /path/to/lammps`, which runs `install.sh` and prints the CMake line;
  - `loupmd lammps paths` (include directory, library, rpath) for hand-written builds;
  - `loupmd doctor`: a LAMMPS section.
- Docs: a "LAMMPS" page with the build recipe (CMake, `-D PKG_KOKKOS=on -D Kokkos_ENABLE_CUDA=on
  -D Kokkos_ARCH_<GPU>=on -D PKG_ML-LOUPMD=on`), three input decks (water NVT, SrTiO3 NPT, NaCl POLAR) and the
  limitations (below).
- Tests: `tests/lammps/` driven by pytest through the `lammps` Python module or `lmp` subprocesses. Skipped when no
  LAMMPS build is found, so the main suite is unaffected. CI: a CPU-only compile check of the pair style against
  LAMMPS headers; GPU runs stay local.

### Stages D-F (decisions for the owner)

- **D, open boundaries.** The engine's list builder gains per-axis periodicity, and cells may be degenerate along
  open axes. Until then the stage A-C styles refuse `boundary f` / `s`; the documented workaround is a padded box
  (> 2 (r_max + skin) of vacuum).
- **E, several GPUs.** Two designs:
  - (1) *Ghost shell.* Each process evaluates owned + ghost atoms as an open cluster. Its energy is the owned atoms'
    sum, with the backward seeded by an owned mask; forces come back on ghosts as well, and LAMMPS reverse
    communication adds them.
    - Needs stage D and a variable atom count per reneighbour without `loup_set_system`: capacity buckets for the
      species-grouped GEMMs, so the graphs re-record rarely.
    - Communication cutoff `n_layers · r_max + skin` (12.5 Å for the 6 Å two-layer models): about 4× the owned atoms
      for a 40 Å subdomain (*estimate*), so it pays only at tens of thousands of atoms per GPU.
  - (2) *Per-layer feature exchange* (Symmetrix's `mpi_message_passing`). The ghost cutoff is `r_max`; the force graph
    splits at each interaction layer, with forward communication of the hidden features and reverse communication of
    their gradients through Kokkos `pack/unpack_*_comm_kokkos`. It scales best and touches the most engine code.
  - Recommendation: (1) first, since it reuses a stage-D engine nearly unchanged; (2) only if scaling to many GPUs
    matters.
- **F, POLAR-1 decomposed.** The k-space structure factors are sums over atoms, so an `MPI_Allreduce` of K × channels
  complex values per SCF iteration closes it. The rest of the long-range part stays per atom.
- **Considered and not chosen for stages A-C: LAMMPS ML-IAP `unified` (Python) as used by MACE's own LAMMPS
  route.** It would bring LAMMPS's ghost communication for free. It feeds edges from LAMMPS's list, though, which
  bypasses the engine's own sorted / preallocated list (part of what the gates certify and the speed depends on), and
  it adds a Python call per step. Revisit for stage E if design (2) is chosen.

## Validation matrix (stages A-C)

| check | systems | criterion |
|---|---|---|
| energy, forces, virial vs Python `LoupEngine` | OFF23-S water216, OMAT-0 medium SrTiO3, MP-0b3 oxide, MH-1 NaCl216, POLAR-1-M NaCl216, OMOL-0 water (charge 0) | within two Python engine runs' spread (cross-process atomics), `LOUP_CONV_TUNE=0` on both sides |
| virial sign and order | SrTiO3 orthogonal and a triclinic cell | LAMMPS pressure tensor = −(1/V) dE/dε by central differences, all six components |
| reordering | `atom_modify sort 1 2.0` (sort every step), `reset_atoms id`, `delete_atoms` + new `pair_coeff` | identical trajectories to the unsorted run over 200 steps (to the atomics' order) |
| NVE | water216 0.5 fs, SrTiO3 1 fs, 10,000 steps | drift no worse than `loupmd md` NVE on the same start |
| NPT | SrTiO3 `fix npt/kk` 300 K, 1 bar | stable volume, rebuild count ≈ the skin's (stage B's strain-aware list), pressure vs stage A |
| hybrid | `hybrid/overlay loupmd/kk dispersion/d3 …` | forces = sum of the two styles run alone |
| minimisation | `minimize` + `fix box/relax` on SrTiO3 | converges to the Python `loupmd relax` result |
| speed | water216, NaCl216, SrTiO3, NbCl5 | the stage-B targets above; recorded in the ledger as MEASUREMENT rows |

The accuracy gate (`test_gate.py`) does not need LAMMPS. The pair style adds no arithmetic, only gathers and
scatters, which the first two rows cover.

## Repository layout and licences

```
lammps/                      (LoupMD repo; shipped in the wheel under loupmd/lammps/)
  README.md
  LICENSE                    GPL-2.0: LAMMPS's licence, required for files built into LAMMPS (owner decision)
  install.sh
  cmake/ML-LOUPMD.cmake
  ML-LOUPMD/pair_loupmd.{h,cpp}
  KOKKOS/pair_loupmd_kokkos.{h,cpp}
  examples/{in.water216_nvt, in.srtio3_npt, in.nacl_polar}
tests/lammps/                pytest, skipped without a LAMMPS build
```

`libloupmd.so` stays MIT and is linked through its C ABI. The glue files are GPL-2.0, as LAMMPS's own packages are.
Upstreaming into LAMMPS (a `ML-LOUPMD` package with an external library, like `ML-PACE`) is a later, optional step.

## Open points for the owner

1. **Scope.** One GPU (stages A-C) now, and D-F later or never?
2. **Licence of `lammps/`.** GPL-2.0 (needed to build into LAMMPS) next to the MIT library. Confirmed by the owner
   on 19 November 2026; the text is `lammps/LICENSE`.
3. **Where it ships.** `develop` first, then the release package (`release/v1`, a new minor version). Upstream to
   LAMMPS later?
4. **Target LAMMPS version.** Kokkos must know the GPU's architecture (`sm_120`: a Kokkos release with Blackwell
   support; check which LAMMPS release bundles it). Pick one LAMMPS release to support and test against.
5. **Hardware.** The plan can be built and checked on the 5060 Ti. The `sm_89` workstations and the A100 are needed
   for the usual adoption bar on the speed targets.

## Effort (*estimates*)

| stage | work |
|---|---|
| A | 3-5 days (pair style, installer, CMake module, accuracy and virial checks) |
| B | 1.5-2.5 weeks (device API, stream handoff, guard/SWITCH reuse, strain-aware list, Kokkos style, speed runs) |
| C | 1 week (per-atom energies, CLI, docs, tests) |
| D | 1-2 weeks |
| E | 3-5 weeks for design (1); another 4-8 for design (2) |
| F | 1-2 weeks after E |
