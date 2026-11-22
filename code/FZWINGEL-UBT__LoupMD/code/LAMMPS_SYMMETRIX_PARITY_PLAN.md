# LoupMD in LAMMPS: LAMMPS's own features, and the options of Symmetrix's pair styles

Status: plan (19 November 2026). Part 1's table of what works today is measured, and stage L1 is built and
measured (S146); nothing else in this file is built.
Effort figures and speed targets are *estimates*. Measured figures are from the 5060 Ti under WSL 2.

Goal (owner, 19 November): the LoupMD package for LAMMPS should offer what Symmetrix's does, ideally without losing
speed. The owner's clarification of the same day: what matters most is **LAMMPS's own features, its other integrators,
thermostats, barostats and constraints**. Part 1 is about those. Part 2 keeps the list of Symmetrix's pair-style
options, with the owner's decisions applied.

## Decisions (owner, 19 November)

| question | decision |
|---|---|
| base for the engine-dependent stages | the release engine (`release/v1`), not `develop` |
| style names | `pair_style loupmd` stays the fast default; add `/float32` and `/float32-mixed` |
| double precision | not for now |
| CPU styles, NequIP styles | out of scope |
| POLAR `float32-mixed` | offered only where it passes the accuracy gate |
| licence of `lammps/` | GPL-2.0 (`lammps/LICENSE`) |
| the engine's own thermostats and barostats (ASE's schemes) for the fast route | acceptable; LAMMPS's exact fixes stay available through the pair styles |

## Part 1. LAMMPS's integrators, thermostats, barostats and constraints

### How a LAMMPS feature reaches LoupMD

Symmetrix has no integrator. Its users get every ensemble and constraint from LAMMPS fixes, because its pair styles
are ordinary pair styles. LoupMD's pair styles are ordinary pair styles too, so the same fixes apply. There are
three routes, and they differ only in speed:

| route | who integrates | which LAMMPS features | step time against the engine's own loop (OMAT-0 medium SrTiO3) |
|---|---|---|---|
| A. `pair_style loupmd`, plain LAMMPS | LAMMPS on the CPU | every fix LAMMPS has for one process | +6% at 5,000 atoms (8.20 against 7.71 - 7.74 ms), +45% at 320 (0.86 - 0.90 against 0.59 - 0.61) |
| B. `pair_style loupmd/kk`, LAMMPS-Kokkos | LAMMPS on the GPU | every fix with a `/kk` version, on the GPU; the others through host copies | +6% at 5,000 atoms (8.14 - 8.19), +65% at 320 (0.97 - 1.03); LAMMPS-Kokkos's own per-step cost under WSL 2 |
| C. `run_style loupmd` | the engine | none during the steps; NVE and Langevin only | +1 to 1.5% at 5,000 atoms, +2 to 7% at 320 |

So the features are there today through routes A and B. What is missing is their speed on small systems, and the
engine-speed route for anything beyond NVE and Langevin.

### What works today (measured)

Twenty-eight LAMMPS setups, each run for 200 steps of 0.5 fs with `pair_style loupmd` and, in Kokkos mode
(`-sf kk`), with `pair_style loupmd/kk`. The LAMMPS test build has the packages RIGID, MOLECULE and EXTRA-FIX for
this. Times are single short runs, good to about 10%.

SrTiO3, 320 atoms, MACE-OMAT-0 medium (the engine's own loop on this system: 0.59 - 0.61 ms/step):

| LAMMPS feature | `loupmd`, ms/step | `loupmd/kk`, ms/step |
|---|---|---|
| `fix nve` | 0.83 | 0.97 |
| `fix nvt` (Nosé-Hoover) | 0.78 | 1.07 |
| `fix npt iso` | 1.02 | 2.14 |
| `fix npt aniso` | 1.14 | 2.75 |
| `fix nph iso` | 1.33 | 2.53 |
| `fix nve` + `fix langevin` | 0.84 | 1.15 |
| `fix nve` + `fix temp/csvr` | 0.91 | 1.34 |
| `fix nve` + `fix temp/berendsen` | 0.84 | 1.40 |
| `fix nve` + `fix press/berendsen` | runs (not timed) | runs (not timed) |
| `fix setforce 0 0 0` on a group (frozen atoms) | 0.85 | 1.33 |
| `fix spring/self` | 0.82 | 1.05 |
| `fix momentum` | 0.81 | 1.17 |
| `fix recenter` | 0.81 | 1.27 |
| `fix addforce` | 0.91 | 1.26 |
| `fix deform` | 1.36 | 1.65 |
| `fix nve/limit` | 0.87 | 1.59 |
| `fix viscous` | 0.85 | 0.88 |
| `compute msd` + `fix ave/time` | 0.81 | 1.21 |
| `compute rdf` + `fix ave/time` | 0.87 | 1.17 |
| `pair_style hybrid/overlay loupmd lj/cut` | 0.80 | 1.10 |
| `minimize` (cg) | 4.0 per iteration (several force calls each) | 8.6 |
| `minimize` (fire) | 0.89 | 2.75 |
| `fix box/relax` + `minimize` | 1.45 | 11.9 |
| `compute pe/atom` | refused: no per-atom energies (P2) | refused |

216 water molecules with bonds and angles in the data file, MACE-OFF23 small (the engine's own loop: 0.34 - 0.36):

| LAMMPS feature | `loupmd`, ms/step | `loupmd/kk`, ms/step |
|---|---|---|
| `fix shake` (rigid water) | 0.54 | 6.1 |
| `fix rattle` | 0.58 | 5.6 |
| `fix rigid/nve/small molecule` | 0.62 | 6.8 |
| `fix rigid/nvt/small molecule` | 0.68 | 7.1 |

What the matrix shows:

- **Every integrator, thermostat, barostat and constraint tried runs with the plain style.** Only `compute pe/atom`
  is refused, as documented.
- **The plain style's cost is a fixed 0.2 - 0.3 ms per step** over the engine's loop, whatever the fix. A changing
  box (`npt`, `nph`, `deform`, `box/relax`) adds the engine's list rebuild in every step.
- **Kokkos mode is slower than the plain style for every setup at this size**, and several times slower for fixes
  without a `/kk` version or with bonded systems: LAMMPS then copies atom data between the GPU and the CPU in
  every step.
- **`fix press/berendsen` needs a material modulus.** With LAMMPS's default (`modulus 10`, in bar) the box of a solid
  explodes in the first step and the engine reports non-finite forces. With `modulus 1.8e6` it runs in both styles
  (checked separately).
- **One defect found and fixed:** in Kokkos mode, rigid bodies in a bonded system aborted inside LAMMPS-Kokkos's
  bond-list handling. The cause was that `loupmd/kk` requested no neighbour list, so LAMMPS-Kokkos kept its own
  per-step work on the CPU. The style now requests an occasional list, which LAMMPS never builds.
  - Rigid bodies run.
  - The Kokkos style's step dropped from 1.29 - 1.38 to 0.97 - 1.03 ms at 320 atoms, and from 8.38 - 8.45 to
    8.14 - 8.19 ms at 5,000 atoms (the benchmark protocol; separate jobs).
- **Not tried:**
  - fixes that add or remove atoms (`deposit`, `evaporate`, `gcmc`): their packages are not in the test build;
  - anything that needs several processes (`neb`, replica exchange with more than one process per replica).

### Where route A loses its time (measured, S146)

Timing probes inside `loup_evaluate` (`LOUP_DEBUG_EVAL_TIMES=1`), LAMMPS with `pair_style loupmd`, `fix nve` +
`fix langevin`, means over about 1,080 steps without a neighbour rebuild:

| part of a step, µs | 320 atoms | 5,000 atoms |
|---|---|---|
| entry to the launch of the step graph (staging the positions) | 20 | 51 |
| launch to the guard's publication (upload, skin check, guard) | 208 | 225 |
| guard to the results having landed (force pass, result copy) | 571 | 7,588 |
| results to the return | 1 | 29 |
| between two calls (LAMMPS's own work on the CPU) | 17 | 200 |
| LAMMPS step | 826 | 8,134 |
| the engine's own loop, for comparison | 580 - 590 | 7,680 - 7,720 |

- **The force pass itself costs what it costs in the engine's loop.** The gap is everything around it.
- **A fixed delay of about 0.2 ms sits between a launch and the start of the force pass**, at both sizes. It is not
  the host copies: a lab build without the upload and the download still showed 107 - 181 µs (water216). It is the
  start of the engine's large step graph on an idle GPU. The engine's own loop hides it by queueing each step while
  the previous force pass runs. A caller that integrates on the CPU cannot, because the next positions depend on the
  forces.
- **At 5,000 atoms LAMMPS's own CPU work is as large again** (0.2 ms per step for `fix nve` and `fix langevin`).

Two further costs appear only with certain fixes:

- **A changing box** (`fix npt`, `nph`, `deform`, `box/relax`): the engine rebuilds its neighbour list in every
  step. NPT measured 1.7 - 1.9× the NVE step on water216.
- **Atoms added or removed** (`fix deposit`, `fix evaporate`, `delete_atoms`): the engine keeps atoms by ID and needs
  IDs 1 … N. It is given the system again when the count changes.

### Stages

**L1. Pre-armed force pass for route A** (engine). Built in S146 as `loup_set_evaluate_ahead` and
`pair_style loupmd ahead yes`; off by default.
- What it does: after a call, the next call's step graph is queued behind a wait on a host-mapped word
  (`cuStreamWaitValue32`). The next call writes its positions into the staging and stores the word, so no launch sits
  on its path. The guarded step graph with its SWITCH node (S75) handles a neighbour rebuild inside the queued
  graph, which is what S37 lacked.
- Measured (5060 Ti, WSL 2, LAMMPS `a b b a` on one build):

  | system | `ahead no`, ms/step | `ahead yes`, ms/step |
  |---|---|---|
  | SrTiO3, 320 atoms | 0.838, 0.826 | 0.752, 0.783 |
  | OFF23-S water216 | 0.553, 0.567 and 0.581, 0.547 | 0.528, 0.533 and 0.548, 0.561 |
  | SrTiO3, 5,000 atoms | 8.189, 8.232 | 8.146, 8.269 |

  About 7% at 320 atoms, 2 - 5% on water216, a tie at 5,000 atoms. By the probes it removes the launch call
  (20 → 3 µs) and about 35 µs of the delay to the guard (208 → 174 µs), and adds 18 µs for queueing the next
  pass. The delay it was meant to remove is mostly not the launch (see the table above).
- Why off by default: between two calls the engine's stream holds work that cannot run. The stream is an ordinary
  (blocking) one, so anything on CUDA's default stream elsewhere in the process, and any device-wide synchronisation,
  waits for it forever. The first build hung in the tests for this reason (a second engine was being set up). In plain
  LAMMPS the engine is normally the only GPU user, so `ahead yes` is safe there; it is never switched on with the
  KOKKOS or GPU package active.
- Target missed: the plan asked for route A within about 0.1 ms of the engine's step. It is at about 0.2 ms.
  What is left is the fixed start of the step graph, which only an integrator inside the engine avoids. That makes
  L3 the stage that matters for speed.

**L2. Changing boxes without a rebuild per step** (engine; with P0).
- The release engine's variable-cell step forms the Cartesian shifts in every step and keeps the list. Through P0
  that serves `fix npt`, `nph`, `deform` and `box/relax` in routes A and B.
- Target: an NPT step within 10% of the NVT step (now 1.7 - 1.9×).

**L3. LAMMPS's common fixes at the engine's speed** (run style; with P0). **Built on `release/v1`, 19 November
2026** (local, not pushed); status and measurements after the plan's text.
- `run_style loupmd` reads the input's fix commands and takes over the ones the engine has an integrator for. The
  user keeps writing LAMMPS syntax:

  | LAMMPS input | engine integrator (release engine) |
  |---|---|
  | `fix nve` | velocity Verlet |
  | `fix nve` + `fix langevin` | Langevin |
  | `fix nve` + `fix temp/csvr` | CSVR (Bussi) |
  | `fix nvt` | Nosé-Hoover chain |
  | `fix nve` + `fix temp/berendsen` (+ `fix press/berendsen`) | Berendsen NVT / NPT |
  | `fix npt` (`iso`; `aniso` / `tri` as far as the engine's full-cell mode covers them) | MTK NPT |
  | `fix setforce 0 0 0` on a group | fixed atoms |
  | `fix momentum` (linear) | centre of mass kept at rest |

- If any other fix acts during the steps, the run style names it and the run uses route A. Nothing is silently
  dropped.
- The engine's integrators follow ASE's schemes. They sample the same ensembles as LAMMPS's fixes but are not the
  same equations step for step (for example LAMMPS's `fix langevin` against the Vanden-Eijnden and Ciccotti scheme).
  The log says which integrator runs. Parameters map directly (`Tdamp` → the thermostat time, `Pdamp` → the barostat
  time, `tchain`); options without an engine counterpart (`drag`, `mtk no`, per-direction couplings) send the run to
  route A.
- Target: the engine's step time for these ensembles, as measured for NVE and Langevin in route C.
- **Status.** `run_style loupmd` without an ensemble does this (`lammps/ML-LOUPMD/integrate_loupmd.cpp`,
  `read_fixes`; the user's table is in `lammps/README.md`). Taken over: `fix nve`, `nve` + `langevin`, `nve` +
  `temp/csvr`, `nve` + `temp/berendsen` (+ `press/berendsen`: `iso`, or per direction in an orthogonal box),
  `nvt`, `npt iso`, `setforce 0 0 0` and atoms outside the integrating fix's group (held atoms), `momentum linear`.
  Refused by name, with the reason: every other fix that acts during the steps, and the options without an engine
  counterpart (`npt aniso` / `tri`, pressure ramps, `drag`, `mtk no`, `dilate`, `fix_modify temp` / `press`,
  variable temperatures, `nph`).
- **Measured** (RTX 5060 Ti under WSL 2 only; MACE-OMAT-0 medium, rattled SrTiO3, 300 K, 1 fs, 2,000 steps after
  200, thermo every 1,000, two runs each with fresh GEMM plans; ms/step):

  | atoms | input | package's own loop | run style | route A (LAMMPS integrates) |
  |---|---|---|---|---|
  | 320 | `fix nvt` | 0.647, 0.647 | 0.651, 0.647 | 0.810, 0.837 |
  | 320 | `fix npt iso` | 0.795, 0.780 | 0.783, 0.792 | 1.309, 1.287 |
  | 320 | `nve` + `langevin` | 0.580, 0.573 | 0.594, 0.578 | 0.795, 0.801 |
  | 1,080 | `fix nvt` | 1.748, 1.751 | 1.775, 1.761 | 1.969, 2.007 |
  | 1,080 | `fix npt iso` | 1.847, 1.863 | 1.844, 1.847 | 2.630, 2.643 |
  | 1,080 | `nve` + `langevin` | 1.718, 1.711 | 1.718, 1.716 | 1.986, 2.032 |
  | 5,000 | `fix nvt` | 7.689, 7.678 | 7.743, 7.729 | 8.069, 8.083 |
  | 5,000 | `fix npt iso` | 7.687, 7.666 | 7.674, 7.663 | 8.891, 8.861 |
  | 5,000 | `nve` + `langevin` | 7.659, 7.676 | 7.663, 7.677 | 8.192, 8.166 |

  The target is met: the run style is within 1% of the package's own loop in every row. Route A takes 1.04 to
  1.27 times as long with `fix nvt` and 1.16 to 1.65 times with `fix npt`.
- **Three things the stage needed besides the mapping.**
  1. An evaluation between two blocks of a run kept capturing the host step over the integrator's step graphs, and
     the integrator's again at the next block: four captures per output. `loup_evaluate` now takes the force
     graph while the MD graphs hold an integrator's step (`evaluate_once`, `keep_md`). Langevin on 320 atoms,
     before and after: thermo every 1,000 steps 0.600 → 0.580 ms/step, every 100 0.617 → 0.594, every 10
     0.920 → 0.734; graph captures of the job 20 / 92 / 884 → 6 / 6 / 6.
  2. The pair style gave the engine the system again at every `run` command (the masses might be new), which
     dropped the list, the tuned plans and the thermostat's state. It now compares the masses too and sends the
     system only when it changed. This serves route A as well.
  3. The fixes the engine stands in for must not run their own `setup()`: `fix langevin`'s adds its forces and
     assumes `run_style verlet` or `respa` (a crash under any other run style). The run style calls
     `Modify::setup()`'s parts itself and leaves those fixes out.
- **Left open.**
  - `fix npt aniso` and `tri`: the engine's full-cell MTK mode moves all nine components of the box, which is
    neither. An engine mode with a diagonal or a triangular cell matrix would be needed.
  - Fixes that only read the state every N steps (`fix ave/time`, `fix print`, `fix ave/atom`) are refused like
    every fix with an `end_of_step`. They could be served as output is: a block boundary at their steps.
  - Each output costs about two force evaluations (the output's own, and the first of the next block, which
    evaluates the same positions again). Reusing the first would halve that: +26 to 34% on the step with output
    every 10 steps today, +2% with output every 100.
  - Degrees of freedom with held atoms or a total momentum: the engine counts 3 per moving atom, LAMMPS 3 fewer.

**L4. Constraints.**
- Through LAMMPS (routes A and B): everything in the table above, including SHAKE, RATTLE and rigid bodies.
- At the engine's speed (L3): fixed atoms and the centre of mass.
- An engine-side SHAKE (a device constraint solver inside the step graph) is possible but is its own project. It
  would matter only for long constrained-water runs on small cells. Not planned unless asked for.

**L5. Route B (Kokkos) where it can win.**
- Measure `loupmd/kk` on native Linux. LAMMPS-Kokkos's own step was 2.43 ms on a 648-atom cell under WSL 2 and is not
  measured elsewhere.
- Settings that cut LAMMPS's own per-step work when LoupMD is the only pair style: `ghost no` and
  `neigh_modify every 20 delay 0 check no` took water216 from 2.5 to 0.90 ms per step (LAMMPS's reneighbouring then
  only wraps and sorts atoms; the engine keeps its own list). To be documented with their limits.
- The gather and scatter kernels of `loup_compute_device` can join the step graph (two launches fewer per step).
- Done already: the occasional list request (see the matrix above), which keeps LAMMPS-Kokkos's own per-step work
  on the GPU.

**L6. Atom counts and IDs.**
- IDs that are not 1 … N (after `delete_atoms`, `fix evaporate`): map them through their rank instead of asking for
  `reset_atoms id`.
- A changed atom count re-sends the system (a full `loup_set_system`). For frequent insertion (`fix deposit`,
  `fix gcmc`) the capacity-bucket system of P4 would avoid re-capturing the graphs.

**Order.** L1 is done. L5's settings can be done on `develop` now. L2 and L3 come with P0, and L3 is the one that
brings LAMMPS's ensembles to the engine's step time. L6 as needed.

## Part 2. Symmetrix's pair-style options

Reference: Symmetrix `main` at `b907f04` (10 November 2026, v0.3.0), `pair_symmetrix/`, as checked out in the
benchmark environment. The list is read from the `settings()`, `coeff()` and `init_style()` of each style and from
its README.

### The speed rule

The default stays what it is today: one process, a periodic cell, the engine's own neighbour list. In Symmetrix's
terms that is `no_domain_decomposition`.

1. Every new option is a mode chosen once in `init_style`, with its own captured graphs. No option may add a
   kernel, a conditional node or a host exchange to a step of the default mode.
2. After every stage the three default configurations (`run_style loupmd`, `loupmd`, `loupmd/kk`) are timed
   `a b b a` against the stage's parent on OFF23-S water216, SrTiO3 with 320 atoms and SrTiO3 with 5,000 atoms. A
   stage is accepted only with b/a inside the run-to-run spread.
3. The Symmetrix side-by-side job (`in.sym_md` protocol) stays as the reference number:

   | ms/step, OMAT-0 medium SrTiO3 | 5,000 atoms | 320 atoms |
   |---|---|---|
   | `run_style loupmd` | 7.81 - 7.86 | 0.61 - 0.64 |
   | `pair_style loupmd` | 8.20 | 0.86 - 0.90 |
   | `pair_style loupmd/kk` | 8.14 - 8.19 | 0.97 - 1.03 |
   | Symmetrix `symmetrix/mace/foundation/float32/kk` | 13.47 - 13.54 | 1.55 - 1.59 |

### Symmetrix's options, one by one

| Symmetrix option | what it does there | LoupMD today (`develop`, S145) | plan |
|---|---|---|---|
| `pair_style … no_domain_decomposition` (default on one process) | one process; LAMMPS's full list, ghosts mapped back to owners | this is LoupMD's only mode, with the engine's own list | P1: accept the keyword |
| `pair_style … mpi_message_passing` (default on several processes) | hidden features exchanged between layers through LAMMPS's forward / reverse communication; ghost cutoff = model cutoff | refused (one process only) | P4b |
| `pair_style … no_mpi_message_passing` (general `symmetrix/mace` styles only) | each process evaluates owned + ghost atoms; communication cutoff raised to 2 × cutoff + skin | refused | P4a |
| several processes and GPUs (`mpirun -np 4 lmp -k on g 4 -sf kk`) | through the two modes above | one process, one GPU | P4 |
| precision: plain name = float64, `/float32`, `/float32-mixed` (GPU foundation styles) | three arithmetic variants | one arithmetic: float32 kernels, tensor-core GEMMs, float64 accumulation (`LOUP_NO_HYBRID=1`: float32 GEMMs) | P5: the two float32 names; no float64 (decided) |
| CPU execution (styles without `/kk`, OpenMP; `/kk/host`) | runs without a GPU | needs a CUDA GPU; the non-Kokkos style still computes on the GPU | out of scope (decided) |
| per-atom energies (`compute pe/atom`) | yes | no | P2 |
| per-atom virials (`compute stress/atom`) | no (refused) | no (refused) | same already |
| boundaries | any (`p`, `f`, `s`, `m`), through LAMMPS's lists and ghosts; POLAR: periodic only | three periodic dimensions only | P3 |
| every LAMMPS fix | yes (ordinary pair styles) | yes, on one process (Part 1) | Part 1 for their speed |
| `newton on` required | yes | either | same or better already |
| `atom_modify map yes` required | yes | yes | same already |
| `pair_coeff * * model.json El1 El2 …` | one element per type | `pair_coeff * * model.loup El1 El2 …` | same already |
| model file from `symmetrix_extract_mace -m MODEL -s H O` / `-Z 1 8`, `--head`, `--r-min`, `--num-spline-points`, `-o` | JSON with splines | `python/export.py --model … --elements 1,8 --output …`, `--head`, `--charge`, `--spin-multiplicity` | P1: one command with the same flags |
| `symmetrix/mace/foundation*` (fixed shapes of the foundation models) | faster kernels for listed architectures | every supported family runs LoupMD's one path | nothing to do |
| `symmetrix/mace/polar`: `charge Q`, `spin S` | total charge and spin multiplicity of the cell | POLAR-1 neutral singlet only | P6a |
| … `mesh h`, `order P` | smooth particle-mesh Ewald grid for the electrostatics | direct sums over the model's k-vectors | P6b |
| … `direct` | direct k-sums (one process) | what LoupMD does | P1: accept the keyword |
| … `grid lammps\|local` (`/cuda`) | the mesh whole on one GPU (cuFFT), or LAMMPS's distributed grid | – | P6b (`local`), P6c (`lammps`, with P4) |
| … `float32-mixed` (`/cuda`) | tensor-core GEMMs for POLAR | tensor-core GEMMs are off for long-range models: they failed POLAR accuracy gates (ledger `gemm-tc-rounded-polar`) | P6d: only where it passes the gate (decided) |
| `symmetrix/nequip*`, `direct_exchange [fp16_wire]` | NequIP models; direct GPU-to-GPU feature exchange exists only for these | not a MACE option | out of scope (decided) |

### What the release engine already has

Read from `include/loupmd.h` on `release/v1` (`ae347d4`); none of it is on `develop`:

- **Per-atom energies:** `loup_evaluate2` with `LOUP_EVAL_PER_ATOM` (one more energy-only pass; refused for
  long-range models).
- **Open domains with ghost atoms, evaluated layer by layer:** `loup_debug_set_domain` /
  `loup_debug_evaluate_domain`. The first `n_local` atoms receive, the ghosts only send, and the ghosts' share of the
  forces is folded back. Its tiled runs evaluate a large system as such domains, one sweep per layer. That looks like
  the scheme of `mpi_message_passing` with tiles in place of processes; to be confirmed in the code before P4.
  Marked "testing only" there.
- **Eight integrators and a minimiser:** `loup_run` (NVE, Langevin, CSVR, Nosé-Hoover chain, Berendsen NVT / NPT,
  BAOAB NPT, MTK NPT), `loup_minimize`, `loup_set_fixed_atoms`, `loup_set_cell`, and a variable-cell step that forms
  the Cartesian shifts in every step.
- **A B-spline mesh with FFT** for the reciprocal part of its D3 term (`LOUP_D3_PME_ORDER`).
- **Errors as text** (`loup_last_error`), `loup_get_info`, an ABI version.

`develop` has what the LAMMPS styles need and release lacks: `loup_compute_device`, `loup_evaluate` as one graph
launch, run-graph reuse, and the optimisations 0.0.2 is waiting for.

### Stages

**P0. One engine (prerequisite; decided: the release engine).**
- Bring the S145 engine work and `lammps/` onto the release engine, with or after the merge of the `develop`
  optimisations that 0.0.2 is waiting for.
- Port, not copy: release's `engine.cu` has its own step graphs (variable cell, tiled runs), so `loup_compute_device`
  and the one-graph `loup_evaluate` have to be fitted to them.
- Done when: the 101 tests of S145 pass on the merged library, and the speed rule's three configurations are within
  spread of `develop`'s.

**P1. Same words (no engine work).**
- `pair_style loupmd [no_domain_decomposition | mpi_message_passing | no_mpi_message_passing] [device N] [skin S]
  [ghost yes|no]`, with Symmetrix's defaults by process count. Until P4 exists, the two multi-process modes stop with
  a message naming this plan.
- POLAR keywords on the same style when the bundle is a POLAR model: `direct` accepted now; `charge`, `spin`, `mesh`,
  `order`, `grid`, `float32-mixed` parsed and refused with the stage that will add them.
- One bundle command with Symmetrix's flags: `loupmd lammps bundle -m MODEL (-s H O | -Z 1 8) [--head H] -o x.loup`.
  `--r-min` and `--num-spline-points` are accepted and reported as not needed: LoupMD builds and certifies its own
  radial tables (`kPackedTableMaxRelErr`).

**P2. Per-atom energies.**
- Engine: release's `LOUP_EVAL_PER_ATOM` through `loup_evaluate`'s LAMMPS path and through `loup_compute_device`
  (the reserved `atom_energy` field). Add it for long-range models, which release refuses.
- Pair styles: `eflag_atom` fills `eatom`. `compute pe/atom` sums to `pe` (to the 6e-7 relative that release
  documents).
- Speed: only the steps that ask for per-atom energies pay the extra energy pass.

**P3. Any boundary.**
- Open axes (`f`, `s`, `m`) as a padded periodic cell: along each non-periodic axis the pair style gives the engine a
  cell that spans the atoms plus more than cutoff + skin of vacuum on both sides.
- The padded length grows in fixed steps (for example 2 Å) and only when atoms come within the margin, so the cell
  does not change from step to step and the list is not rebuilt for it.
- POLAR stays periodic-only, as in Symmetrix. Periodic runs are untouched.
- Tests: a molecule in `boundary f f f` against the same molecule in a large periodic box; a slab with `p p f`.

**P4. Several processes and GPUs.** Both modes build on release's open domain as a supported interface, and on an
engine system whose atom count changes at every reneighbouring without a full `loup_set_system` (capacity buckets
for the species-grouped GEMM shapes, so the captured graphs are re-recorded rarely).
- **P4a, `no_mpi_message_passing` (ghost shell).** LAMMPS supplies owned atoms and ghosts within
  `n_layers × cutoff + skin`. The engine evaluates one open domain: owned atoms and the ghosts within one cutoff of
  them receive, the outer ghosts only send. The energy is the owned atoms' sum, with the backward pass seeded by the
  owned mask. Forces come back on every atom and LAMMPS's reverse communication adds the ghosts' share.
- **P4b, `mpi_message_passing` (features exchanged between layers).** The ghost cutoff is the model's cutoff. The
  force pass splits at every interaction layer: the layer's sweep on the owned atoms, then LAMMPS's forward
  communication of the hidden features into the ghost rows; backward mirrored with reverse communication of the
  feature gradients. `comm_forward` = `comm_reverse` = the feature row width, as in Symmetrix.
- **Speed.** One process is untouched. For the modes themselves the yardstick is Symmetrix in the same mode with the
  same process count. This machine has one GPU: scaling needs the workstations or A100 nodes.

**P5. Precision names (decided).**

| name | arithmetic | work |
|---|---|---|
| `loupmd` | LoupMD's default (tensor-core GEMMs where the model allows; float32 GEMMs for long-range models); printed at start-up | none |
| `loupmd/float32-mixed` | tensor-core GEMMs | a style name |
| `loupmd/float32` | float32 GEMMs only: today `LOUP_NO_HYBRID=1` for the whole process | a per-handle setting, and the style name |

No double precision for now. LoupMD's accuracy statement stays the gate: within 3× of MACE's own
float32-against-float64 error.

**P6. MACE-POLAR options.**
- **P6a, `charge Q`, `spin S`.** The engine evaluates POLAR-1 for neutral singlets only. Work: the total charge and
  spin inputs of PolarMACE through the export and the SCF, checked against PolarMACE float64 references for charged
  cells. First step: read how PolarMACE applies them, before estimating.
- **P6b, `mesh h`, `order P`, `grid local`.** A smooth particle-mesh Ewald path on one GPU (cuFFT), reusing the mesh
  code release has for D3. Also a speed item: the direct sums grow with atoms × k-vectors, the mesh with atoms plus
  grid points. To lose no speed, the default stays whichever is faster for the system, timed at the first rebuild;
  `direct` and `mesh` force one.
- **P6c, `grid lammps`.** LAMMPS's distributed grid and FFTs for several processes. With P4.
- **P6d, `float32-mixed`.** Offered only for the model / GPU combinations that pass the gate; otherwise it stops with
  the reason.

## Order and effort (*estimates*)

| stage | work | depends on |
|---|---|---|
| L1 pre-armed force pass | done (S146): 2 - 7% on small systems, opt-in | – |
| L5 Kokkos settings, documented and tested | 2 days (the native-Linux measurement needs a Linux machine) | – |
| P1 same words | 2 - 3 days | – |
| P3 any boundary | 3 - 5 days | – |
| P5 `float32` / `float32-mixed` names | 2 days | – |
| P0 one engine | 1 - 2 weeks | the 0.0.2 merge |
| L2 changing boxes | with P0, plus 2 - 3 days of tests | P0 |
| L3 LAMMPS's common fixes through the run style | 1 - 2 weeks (**built, 19 November**) | P0 |
| P2 per-atom energies | 3 - 4 days | P0 |
| L6 atom IDs and counts | 2 - 3 days | – |
| P4a ghost-shell mode | 2 - 3 weeks | P0, P2 |
| P4b feature-exchange mode | 3 - 5 weeks | P4a |
| P6a POLAR charge and spin | 1 - 2 weeks after a first look | – |
| P6b POLAR mesh, one GPU | 2 - 3 weeks | P0 |
| P6c POLAR distributed grid | 1 - 2 weeks | P4b, P6b |

Suggested order: P1 / P3 / P5 (all on `develop`, no engine dependency), P0, then L3 and L2 (the two that bring
LAMMPS's ensembles to the engine's speed), P2, and the several-process and POLAR stages after that.

## Open points for the owner

1. **Hardware for P4 and L5.** Two GPUs for scaling, and a native-Linux machine for the Kokkos route: the
   workstations or A100 nodes, when available.
