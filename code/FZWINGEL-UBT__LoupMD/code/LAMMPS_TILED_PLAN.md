# The tiled and wavefront modes in LAMMPS

Plan of 20 November 2026 (PLAN.md O42). The owner's request: "Yes create an in depth plan on how to best do this
after crash fix and benchmark". It is carried out after two other pieces of work, in this order:

1. The destroy-race fix: the fast tier's segmentation fault, STATUS §6.39.
2. The benchmark re-run with 100 warm-up + 200 measured steps (O41 (a)).

Figures marked *estimate* were not measured. Measured figures name the card: all were taken on the RTX 5060 Ti only.

**Status, 20 November 2026:** LT0 to LT5 done (STATUS §6.40). LT6 (a) qualified by its rule (16% per step); the
owner gave the go the same evening ("Start the barostat", D99), and it is done (STATUS §6.41, §4 LT6): the tiled call
keeps its lists across a strained cell, and tiled MD runs the three barostats. LT6 (b) waits for a user case.

## 1. Goal

A cell too large for the card as a whole runs in LAMMPS as it runs in the engine's own loop: tile by tile, in
whichever form the plan picks (device lists, host lists, host state, the wavefront). This covers all three styles:

- `pair_style loupmd`: LAMMPS integrates.
- `pair_style loupmd/kk`: LAMMPS-Kokkos integrates.
- `run_style loupmd`: the engine integrates.

Done means:

- MACE-MH-1 on SrTiO3 at 50,820 and 98,415 atoms runs under each of the three styles. The benchmark's LAMMPS + LoupMD
  rows failed on both cells on 20 November (`~/loup_bench_runs/5060ti-20261120/summary.csv`); the engine's own loop
  ran both tiled.
- Each style's step time is within a few percent of the Python package's tiled loop on the same cell.
- Each style agrees with the whole-system call where both fit, to the bounds `tests/gpu/test_tiled.py` uses.
- A cell that fits whole runs exactly as today: the same calls and the same step time.

Not in scope:

- Several MPI processes or GPUs: Part 2's P4 of `LAMMPS_SYMMETRIX_PARITY_PLAN.md`, a separate design (see §9).
- MACE-POLAR-1 tiled. Long range cannot tile (`sweeps_possible`, `src/generic.hpp:144`), so it stays whole and is
  refused with a reason.
- D3 in tiled mode. The tiled call refuses a dispersion term (`src/engine.cu:6428`, S6-D09). The LAMMPS styles have
  no D3 option today.
- Per-atom energies and virials: refused in every mode, as today.
- Barostats in `run_style loupmd` tiled. Tiled MD had a fixed cell (`src/engine.cu:7941-7946`). LT6 (a) lifted this
  on 20 November (D99).

## 2. What exists today

### LAMMPS side (`lammps/ML-LOUPMD`, `lammps/KOKKOS`)

**`pair_loupmd.cpp`:**
- `settings` (93): keywords `device`, `skin`, `ghost`, `ahead`.
- `init_style` (147):
  - one process, metal units, consecutive IDs;
  - creates the handle (163-164) and sets evaluate-ahead (180).
- `ensure_system` (216):
  - sends z and masses by tag through `loup_set_system` (245);
  - sends only when the atomic numbers, masses or skin change;
  - `serial` counts the sends.
- `compute` (285):
  - `ensure_system` (289);
  - unwrapped positions by tag;
  - `loup_evaluate(..., stress)` (313).
- Per-atom requests are refused (`refuse_per_atom`).

**`pair_loupmd_kokkos.cpp`:**
- `compute` (79): Kokkos views. It unwraps and maps IDs on the device and calls `loup_compute_device`.
- Host execution spaces take the plain style's compute on host arrays (173-176).

**`integrate_loupmd.cpp`:**
- `init` (237): refuses KOKKOS (243).
- `read_fixes` (264): maps fixes to `LoupIntegrator` kinds 0-7.
- `setup` (539) calls `forces()` (the pair style evaluates, which sends the system), then `push_state` (779).
- `push_state`:
  - `loup_set_state` (835) unless nothing changed since the last run (`snap_*`, `ensemble_key`);
  - `loup_set_fixed_atoms` (837).
- `run` (634): `loup_run` blocks up to the next output step (682). At an output step:
  - `pull_state` (879, `loup_get_state` 892);
  - `reneighbor`;
  - `forces()`: the pair style evaluates energy, forces and virial for the output.

### Engine side (`src/engine.cu`, `include/loupmd.h:356-484`)

**The tiled call: `loup_debug_evaluate_tiled` → `evaluate_tiled_impl`, 6420.**

It is "testing only, until S5-T12 makes it a mode of the public calls" (header 454). The Python package uses it anyway, through `TiledEngine`.

Refusals (6427-6446):
- a dispersion term;
- long range;
- fewer than two layers;
- WAVEFRONT on a model that does not have exactly two layers;
- a bad skin.

Outputs:
- Stress is optional. A NULL `out_stress` skips the virial (7062).
- There is no per-atom energy.

Afterwards:
- The handle holds the last tile's open domain.
- `loup_evaluate` and `loup_run` then refuse ("the handle holds an open domain", 2705).
- `loup_set_system` drops all tiled state (2487 → `free_system`, 1090-1103; tiled MD, 8263).

**Kept state (6450-6472).** The plan, the tile lists and the whole-system state are kept when:
- n is the same;
- the skin is the same;
- the cell is the same, bit for bit (`memcmp`);
- the atomic numbers are the same, in order;
- no atom has moved more than skin/2 since the lists were built.

The displacement is a plain Cartesian difference with no minimum image (`max_disp2_kernel`, 5120). A position that
wraps counts as a jump, so callers must pass unwrapped positions. The pair styles already do.

On a cell change or a crossing:
- the kept state is released and a new host tile plan is made (6531);
- neighbour lists are built per tile, and lists and state are allocated anew (6563-6806).

`receivers <= 0` takes the kept cap only while the system is the same. Otherwise `plan_execution_impl` runs again with
its probe tile (6484-6494). Its `set_domain_impl` calls `free_system` and drops what was kept. **A caller that
re-plans by passing 0 loses its lists: pass the plan's cap explicitly.**

**Tiled MD (O31): `loup_tiled_set_state` / `loup_tiled_run` / `loup_tiled_get_state` (7844-8145).**
- Positions, velocities and forces stay on the device.
- Integrators:
  - NVE, Langevin, CSVR, NHC (chain ≤ 16) and Berendsen NVT;
  - temperature ramps are honoured (`temp_rate_k_per_step`, 7951);
  - `fix_com` with fixed atoms is refused (7948).
- Thermo rows carry pressure 0 (8093). The MD's force call passes no stress (`tiled_md_forces`, 7921).
- `set_state` needs positions and velocities both, or both NULL; both NULL keeps the state (7849-7857).
- `set_state` marks the forces stale (7913): the next `run` starts with one extra tiled call (7994).
- `get_state`'s forces and energy belong to the current positions.

The MD calls the same `evaluate_tiled_impl` on the same `h->tiled_state` (7919-7928). A `loup_debug_evaluate_tiled`
between two `loup_tiled_run` blocks therefore keeps the lists and computes stress. Conditions: the same n, z, skin
and cap; a bit-identical cell; positions within skin/2. It leaves `md->forces` alone (a separate buffer).
**No GPU test interleaves the two today.** Only the CPU fake does (`tests/cpu/test_tiled_engine.py`).

`TiledMD`'s own buffers are allocated with a plain `cudaMalloc` (7869-7877), not `loup::device_malloc`. They take
about 144 B per atom, and the plan does not count them.

**The plan: `loup_plan_execution` → `plan_execution_impl`, 5962.**
- It returns WHOLE without a probe when asked, or when the model cannot tile (5984-5990).
- Otherwise it sets up one probe tile of at most 4,096 receivers and measures it (5991-6012). It then takes the
  largest cap from 65,536 down to 4,096 that fits, in passes:
  1. lists on the device;
  2. host lists;
  3. host state;
  4. the wavefront's host pool (6202-6286).
- The mode is `AUTO && whole_fits ? WHOLE : TILED` (6392).
- It leaves `tile_host_lists` and `tile_host_state` on the handle for the next list build. After a probe, the
  handle must get `loup_set_system` before any whole call.
- The wavefront is decided at list build: two layers, forced or ≥ 2^20 atoms, and ≥ 12 layers of tiles along the
  first axis (5834-5839, 6538).
- `LOUP_DEBUG_PLAN_FREE` caps the free memory it counts (6033-6036).

### Python front end (the pattern to follow)

- `capacity="auto"` is the default (`loupmd/quick.py:140`, `simulation.py:109`, `config.py:378`), with receivers
  `None` and memory fraction 0.9.
- `forcefield.py:192-208`:
  - `auto` on a short-range model runs `set_execution` + `plan_execution`; TILED gives a `TiledEngine`.
  - `tiled` and `wavefront` go to `TiledEngine` with no plan.
- `TiledEngine` drives `evaluate_tiled` (`tiled_engine.py:146-166`) or `tiled_run` (284-303).
- It refuses NPT, long range in tiled modes, `set_reference_volume`, and `fix_com` with fixed atoms.
- No front end falls back to tiled when a whole run runs out of memory. `CapacityError` (`errors.py:93`) is
  never raised.

## 3. Design decisions

Each decision gives the recommendation first, then the alternative and why it loses.

### LD1. The mode is chosen in the pair style, once per system send

Settings:

```
pair_style loupmd ... [capacity auto|whole|tiled|wavefront] [receivers N] [memory F]
```

- **`capacity`**, default `auto`, as in Python.
  - `whole` is today's path, with no plan call.
  - `tiled` and `wavefront` force the mode. They are refused when the model cannot tile, with the reason the engine
    gives.
- **`receivers N`** sets a cap; the default 0 takes the plan's.
- **`memory F`** sets the plan's share of the free memory, default 0.9.
- All three go to `loup_set_execution` in `init_style`, after the handle exists.

`ensure_system` makes the decision. When it has to send the system and `capacity` is not `whole`, it calls
`loup_plan_execution`. That needs positions and the cell, so the compute fills `xbuf` before `ensure_system` (today
it fills it after). Then:

- **WHOLE:** `loup_set_system` as today.
- **TILED:** no `loup_set_system`. The pair style keeps `tiled = true` and the cap the plan returned (`plan.receivers`).

The plan runs again only on the next system send: new atomic numbers, masses or skin.

- Why at system send and not per call: the plan's probe drops the kept lists (§2). A re-plan per call would rebuild
  them every step.
- Why `auto` by default:
  - A cell that fits whole takes exactly today's path, after the plan's probe at the send. LT1 measures the probe's
    cost.
  - A cell that does not fit runs instead of failing.
  - Python already behaves this way.
  - If the probe costs more than about 100 ms on a 5,000-atom cell, `auto` first asks `loup_plan_memory` (counts
    only, no probe). It then probes only when the whole estimate exceeds about half the free memory.

**The log** shows the plan line at each send. Example:

`LoupMD: 98415 atoms run tiled: 4 tiles of at most 32768 atoms, lists on the device; the whole cell needs 52.1 GiB,
14.6 GiB free`

The line names host lists, host state and the wavefront when the plan or the call picks them. At the end of each
`run`, it reports the tiled calls and list builds (`loup_get_execution`). Users see what ran, and the tests read it.

### LD2. Engine API: promote the tiled call to a public function

**(A), recommended.** Add `loup_evaluate_tiled(h, n, z, positions, cell, receivers, skin, energy, forces, stress,
tiles)`:
- the same contract as `loup_debug_evaluate_tiled`, under its own name;
- the debug name stays as an alias;
- a purely additive change under interface version 1.

The LAMMPS styles call it, `loup_tiled_*` and `loup_plan_execution`, and dispatch on the pair style's `tiled` flag.

**(B)** makes the tiled mode a mode of `loup_evaluate`, `loup_compute_device` and `loup_run` after
`loup_set_execution`. That was S5-T12's original intent (header 454). It is cleaner for every caller, but it touches
`loup_set_system` (no whole buffers under TILED), `guarded`, the step graphs' preconditions (`has_system`) and the
Python package's dispatch, all in the release branch. (A) does not rule out (B) later. Keep (B) as a post-release
item.

Also in LT0:
- `TiledMD`'s allocations go through `loup::device_malloc`, so an overshoot under WSL 2 fails instead of paging.
- The docs of the three `loup_tiled_*` calls gain one sentence: the tiled call and tiled MD share the kept state.

### LD3. The cap is passed explicitly after the plan

The pair style passes the plan's cap (or the user's) to every tiled call and to `loup_tiled_set_state`, never 0.
That avoids the probe on a changed cell (§2).

If a tiled call fails with out of memory after a cell change, the pair style re-plans once at the new cell and tries
again. A second failure stops the run with the engine's message. A change in density under a barostat can make
tiles denser than the probe measured.

### LD4. `pair_style loupmd` in tiled mode

Each step:
1. Unwrapped positions by tag, as today.
2. `loup_evaluate_tiled(..., stress only when vflag_global)`.
3. Add the forces.
4. The virial from stress × volume, as today.

Notes:
- Kept lists survive LAMMPS's wrapping and sorting: the positions are continuous and in tag order.
- Under `fix npt`, `deform` or `box/relax` the cell changes every step. Until LT6 (a) every step re-planned its tiles
  and built lists, and the log warned once: "the box changes in every step: tiled mode rebuilds its tile lists in
  each". LT5 measured 16% per step. Since LT6 (a) the lists stay while the strain rule allows, and the warning is
  gone.
- `ahead yes` has no tiled counterpart. It is ignored with a log line.
- Transfers are small next to the call. At 98,415 atoms each way carries 2.4 MB, about 1 ms *estimate*. A tiled
  MH-1 step there is about 0.8 s: 8.2 µs/atom measured in the 20 November run.

### LD5. `pair_style loupmd/kk` in tiled mode: through the host

In tiled mode the Kokkos compute takes its existing host branch (`pair_loupmd_kokkos.cpp:173-176`):
- `atomKK->sync(Host, ...)`;
- `PairLoupMD::compute`;
- `atomKK->modified(Host, F_MASK)`.

That branch already exists for host execution spaces. The DualView transfers cost milliseconds against hundreds of
milliseconds per step.

A device-array variant (`loup_evaluate_tiled_device` with `LoupDeviceIO`) would save only those milliseconds, so it
is not planned. It becomes worth doing only if tiles ever run at tens of milliseconds per step.

### LD6. `run_style loupmd` in tiled mode: the engine's tiled MD

| run style step | whole (today) | tiled |
|---|---|---|
| `setup` → `forces()` | `loup_set_system` + `loup_evaluate` | the pair style's plan + `loup_evaluate_tiled` (builds the lists) |
| `push_state` | `loup_set_state` + `loup_set_fixed_atoms` | `loup_tiled_set_state(z, masses, x, v, cell, fixed, cap, skin, noise_step, NULL)` |
| `run` blocks | `loup_run` | `loup_tiled_run` with the same `LoupIntegrator` (temperature ramp, seed, `fix_com`) and `thermo_every` 0 |
| output step | `loup_get_state`, then `forces()` → `loup_evaluate` | `loup_tiled_get_state(x, v)`, then `forces()` → `loup_evaluate_tiled` with stress (kept lists) |

**State continuity.** When nothing changed since the last run, `push_state` skips `loup_tiled_set_state`, as today
(the `snap_*` check). The forces stay current and the thermostat keeps its state. When something changed:
- `noise_step` is the handle's counter from `loup_tiled_get_state`, so the noise never repeats.
- `int_state` is NULL, so the thermostat starts from zero, as under a newly defined fix.
- The seed shift by `system_serial` stays as it is.

**Ensembles.** Tiled MD takes `nve`, `langevin`, `temp/csvr`, `nvt` and `temp/berendsen`, with `setforce 0 0 0`
(fixed atoms) and `momentum` (`fix_com`). Until LT6 (a) it refused by name:
- `fix npt`;
- `press/berendsen`.

Example message: "the cell does not fit the card whole, so it runs tiled, and tiled MD keeps the cell fixed. Use the
default run style with pair_style loupmd, which re-plans the tiles in every step, or a smaller cell".

The mode is known only after the setup's `forces()` call. So the refusal sat in `setup` right after `forces()`,
before `push_state`, and with `capacity tiled` or `wavefront` set `init` refused earlier.

Since LT6 (a) tiled MD takes both (MTK and Berendsen NPT), and the run style sets LAMMPS's box from
`loup_tiled_get_cell` after each block. `check_tiled` still refuses, by kind, an integrator the tiled MD lacks.

**Output steps.**
- Each output costs one tiled call with stress.
- The MD's forces are not touched (a separate buffer), so the next block starts without an extra call.
- LAMMPS's wrap moves the last bits of positions in a sheared box. That is far inside skin/2, so the lists are kept.
- *Estimate:* with thermo every 100 steps, +1% on the step.
- Optional optimisation, only if LT5 shows output costs matter: when `vflag` is 0 (no `press` in the thermo), take
  energy and forces from `loup_tiled_get_state` and skip the call.

### LD7. Wavefront, host lists and host state come through the plan

No LAMMPS code chooses among them.
- `capacity wavefront` maps to `LOUP_EXEC_WAVEFRONT`. It is refused for models without exactly two layers.
- The environment variables (`LOUP_TILE_WAVEFRONT`, `LOUP_TILE_HOST_LISTS`, `LOUP_TILE_HOST_STATE`) work unchanged.
  The tests use them to force each form on a small cell.

Pinned host memory is planned within shares of `MemAvailable` at plan time, after LAMMPS has allocated its arrays.
The guard since `bf595d5` (17 November) refuses a host pool beyond it.

### LD8. Refusals and messages

| case | message source | where |
|---|---|---|
| MACE-POLAR-1 with `capacity tiled` / `wavefront` | the plan returns WHOLE without probing a long-range model: the style says "long-range models cannot tile" | `init_style` / first send |
| MACE-POLAR-1 too large whole under `auto` | `loup::device_malloc`'s refusal, extended by the style: "the cell does not fit the card whole, and long-range models cannot run tiled" | `ensure_system` |
| `capacity wavefront` with another layer count | the engine (6442-6445) | first tiled call |
| a cell no cap fits | the plan (6394-6415) | `ensure_system` |
| per-atom energy or virial | `refuse_per_atom`, unchanged | `compute` |
| barostat under `run_style loupmd` tiled | refused until LT6 (a); accepted since | — |

### LD9. What is not changed

- Atom IDs stay consecutive.
- One MPI process.
- `ghost` keeps its meaning. For tiled cells the README recommends `ghost no`, since LAMMPS's own ghosts of a
  100,000-atom cell are host work the engine never reads.
- The capture-mode and destroy fixes of the crash fix cover the tiled calls through `guarded`. All five tiled
  entry points go through it (8376-8410).

## 4. Stages

Every stage is built and tested on the release worktree, under `local_gpu.py run` reservations of 15 minutes or
less, with no push.

- **The test LAMMPS** (`~/loupmd_lammps`) links `loupmd_root/lib/libloupmd.so`. Replace it only when no `lmp` runs:
  `cp`, then `mv`, as `.tmp_o/lmp_tests_g.sh` does.
- **Tests:** each stage's tests are written before its code.

Effort is in working days, *estimates*.

### LT0. Engine: the public tiled call (0.5-1 day)

1. `loup_evaluate_tiled` in `include/loupmd.h` and `src/engine.cu`, through `guarded`. `loup_debug_evaluate_tiled`
   stays as an alias.
2. `TiledMD` allocations through `loup::device_malloc`.
3. Header documentation:
   - the shared kept state of the tiled call and tiled MD;
   - "pass the cap, not 0, to keep the lists".
4. Python: `_core.LoupEngine.evaluate_tiled` calls the public name and falls back to the debug name, so older
   libraries still load (the package's version checks are unchanged).
5. GPU tests in `tests/gpu/test_tiled_md.py`:
   - (a) A stress evaluation between two `tiled_run` blocks leaves the trajectory as in an unbroken run (dx 1e-6)
     and adds no list build.
   - (b) After `loup_tiled_set_state` with unchanged positions, `run` makes one extra force call and no list build.
   - (c) `receivers` 0 after a cell change re-plans; the cap passed does not.

### LT1. `pair_style loupmd` tiled (1-1.5 days)

1. Settings `capacity`, `receivers`, `memory`; `loup_set_execution` in `init_style`.
2. `ensure_system(x, cell)`: the plan, the mode, the cap, the log line. The compute reorders: positions first.
3. `compute` in tiled mode: `loup_evaluate_tiled`, stress on `vflag_global`. Re-plan once on failure after a cell
   change (LD3).
4. `pair_loupmd.h`: `tiled`, `cap`, `plan` members; `tiled()` and `cap()` accessors for the run style.
5. Run-end line with tiled calls and list builds.
6. Measure the plan's probe cost at 5,000 and 50,820 atoms. If needed, add the `loup_plan_memory` pre-filter of LD1.

### LT2. `pair_style loupmd/kk` tiled (0.5 day)

1. In tiled mode `compute` takes the host branch. `ensure_system` gets host positions through that branch's sync.
2. Test: `kk` equals the plain style in tiled mode.

### LT3. `run_style loupmd` tiled (1-1.5 days)

1. `push_state`, `run`, `pull_state` and the output step dispatch on `pair->tiled()` (LD6).
2. Refusal of `fix npt` and `press/berendsen` in tiled mode, after the setup's `forces()`.
3. `describe()` names the tiled mode and the plan.
4. The `snap_*` continuity and the noise counter as in LD6.

### LT4. Tests and the benchmark (1 day)

1. `tests/gpu/test_lammps_tiled.py` (§5) runs whole, under `LOUPMD_LMP`.
2. The full LAMMPS suites (`test_lammps.py`, `test_lammps_run_style.py`) on the new library: whole cells unchanged.
3. Fast tier, then the full tier (`-m "not acceptance"`). `tests/cpu` on `leto`, per the workstation recipe, when the
   owner's VPN is up; else locally.
4. Benchmark: the LAMMPS + LoupMD rows of MH-1 at 50,820 and 98,415 atoms (pair style and run style) in the local
   `Benchmark_loup` checkout, with the protocol of O41 (a), next to the own loop's tiled rows. OMAT-0 medium at
   larger cells as well: the 320,000-atom cell of S5-T06, which runs tiled with 8 tiles of 65,536 (measured,
   status §6.18).

### LT5. Measurements and documentation (0.5-1 day)

The measurements of §6, then the documentation of §7.

### LT6. Optional, after LT5's numbers

**(a) Variable cell in tiled mode.** Lists kept across small cell changes, as the whole mode's variable-cell step
keeps its list:
- shifts from fractional images;
- a strain margin in the displacement test;
- allocations reused when sizes fit.

That serves `pair_style loupmd` with `fix npt`, and later a barostat in tiled MD (MTK or Berendsen on the tiled
state's arrays, D65's (a)). Engine work, 2-4 days *estimate*. Only if LT5 shows the per-step re-plan costs more than
about 10% of the step.

LT5 measured 16% (`fix npt` through the tiled pair style, 491 ms per step against 424 at a fixed cell, MH-1, 50,820
atoms). The owner's go, 20 November 2026: "Start the barostat" (PLAN.md D99). The design:

*A1. The tiled call keeps its lists across a cell change (engine).*
- A tile is an open domain. Its row r sits at `x_a + S_r h - o`: `S_r` is the row's whole-cell image, `o` the
  tile's origin. Every edge's shift is zero, since the tile's own box images lie beyond the list's reach. So a kept
  tile needs only its rows placed in the new cell: `pos = x_a + offset_r + S_r (h - h0)`. `S_r` is
  `rint((offset_r + o) h0^-1)`, from the kept offset and the tile's origin, so no new array is needed.
- The test is the whole system's variable-cell test (`src/cell.cu`): `F = h0^-1 h`, `thr = (r_list (1 - |F - 1|_F)
  - r_max) / 2`. The lists stay while every atom lies within `thr` of `x0 F + t`, where `t` is the mean of the
  displacements `x - x0 F`. A common translation moves no pair vector: LAMMPS's `fix npt` scales about the box's
  centre, the engine's barostats about the origin.
- A cell bit for bit equal to the build's keeps today's test.
- `receivers` 0 takes the kept cap while the lists are kept. When a changed cell needs new lists, it plans again, as
  today.
- No new device memory, so the memory plan's figures stay.

*A2. Barostats in tiled MD (engine).* `loup_tiled_run` takes `LOUP_BERENDSEN_NPT`, `LOUP_BAOAB_NPT` and
`LOUP_MTK_NPT`. They run the whole system's kernels (`integrator.cu`, `cell.cu`) on the tiled MD's arrays, with
its own `CellDev` and virial.
- The first half runs as `run_md_loop`'s `record_move`, then `cell_derive_kernel`.
- The new cell comes back to the host (72 B), and the tiled call runs with stress at that cell. Its virial goes to
  the device.
- The second half runs as `record_rest`.
- The validation is shared with `loup_run` (one function): no fixed atoms, and BAOAB without `fix_com`, as for the
  whole system.
- Thermo rows carry pressure and volume, as `thermo_row_kernel` writes them.
- `loup_tiled_get_cell` (new) returns the tiled MD's cell.
- `loup_set_reference_volume` on a handle with tiled MD sets its V0. The default V0 is the volume at
  `loup_tiled_set_state`.
- A tiled call that fails after a cell change plans once more at the new cell: LD3's rule, in the engine.

*A3. Python.* `TiledEngine` runs the three barostats on the device loop; the host loop refuses them. `get_cell`
reads the device's cell, and V0 is passed on. `Simulation` accepts its NPT schemes in tiled mode.

*A4. LAMMPS.*
- The pair style's warning about rebuilds in every step goes.
- `run_style loupmd` takes `fix npt` and `press/berendsen` in tiled mode (MTK, Berendsen).
- After each block the run style sets LAMMPS's box from `loup_tiled_get_cell`, as the whole mode does from
  `loup_get_cell`.

*Tests, written first.*
- `tests/gpu/test_tiled_md.py`:
  1. An affine strain plus a translation keeps the lists and gives the whole system's result at the new cell (1e-7
     eV/atom, 1e-5 eV/Å, 1e-8 eV/Å^3). A strain beyond the margin builds new lists, and `receivers` 0 then plans
     again. This replaces `test_a_tiled_call_after_a_cell_change_keeps_a_passed_cap_and_plans_on_zero`.
  2. The three barostats: the tiled device loop against the whole system's loop on 5,000 atoms in 3 tiles, 20 steps,
     compared on positions and cell.
  3. A tiled NPT run, stopped and resumed, ends where the unbroken run ends.
  4. The volume limit stops a tiled run.
- `tests/gpu/test_lammps_tiled.py`:
  - The run style with `fix npt` and with `press/berendsen` in tiled mode, against the engine's tiled run of the same
    ensemble.
  - The pair style with `fix npt`: lists are built about as often as LAMMPS's own neighbour list, and the result
    matches the whole cell's.
- `tests/cpu`: the refusals that move, for NPT in tiled mode.

*Measurement* (MH-1, 50,820 atoms):
- `fix npt` through the pair style;
- the run style with `fix npt` in tiled mode;
- the package's own loop with MTK in tiled mode.

*Effort estimate:* engine 1.5-2 days, Python 0.5, LAMMPS 0.5-1, tests, measurement and docs 1.

*Result, 20 November 2026* (STATUS §6.41; RTX 5060 Ti only). Done as designed, in one evening.
- The barostat test runs 5,000 atoms in 8 tiles of at most 2,000, not 3. Tiled against whole over 20 steps at 2 GPa:
  positions within 1e-7 Å and the cell within 7.3e-8 Å for all three barostats.
- The comparison found a whole-mode fault: MTK's barostat mass counted 3N degrees of freedom with `fixcm` in the first
  call on an engine and 3N - 3 later. It is fixed in the same change.
- A2's re-plan is in `tiled_md_forces`: a tiled MD force call that fails in a cell other than the one its cap was
  planned or set for plans once more at that cell. No test forces that failure.
- `fix npt` through the pair style: 412-413 ms per step against 410-413 at a fixed cell with the virial (MH-1, 50,820
  atoms), where it was 491 against 424. The package's MTK: 411-412 against NVE 410-411.
- 200 steps of `fix npt` through the tiled pair style built tile lists 7 times. LAMMPS's own neighbour list was built
  13 times over the same steps.
- LT6 (b) stays open.

**(b) Out-of-memory fallback.** A whole system whose list outgrows its buffers in a run (density under a barostat)
switches to tiled instead of stopping. Pair style only: the run style's state would have to move between the two
modes. 1 day *estimate*. Only if a user case needs it.

**Total LT0-LT5:** 4.5-6.5 working days *estimate*. LT6 is decided separately.

## 5. Tests (`tests/gpu/test_lammps_tiled.py`)

Cells and models follow `tests/gpu/test_tiled.py`:
- SrTiO3 rods of 5,760 atoms (`srtio3(1).repeat((32, 6, 6))`) with caps of 400-600 receivers, so that several
  layers of tiles form;
- MACE-OMAT-0 medium as the two-layer model;
- MACE-MH-1 as a model of more layers.

Whole-system references:
- run with `LOUP_CHAIN_FOLD=0`, which is what the tiles run (`gpu_support.unfolded`);
- compare with `LOUP_NO_HYBRID=1` on both sides for the tight bounds, otherwise at the default-GEMM bounds of
  `test_tiled.py:85` (dE 2e-6 eV/atom, dF 1e-5 eV/Å, dS 2e-7 eV/Å³).

| test | what it shows | bound |
|---|---|---|
| `test_tiled_pair_style_matches_the_whole_call` (plain, kk) | `capacity tiled receivers 600`: energy, forces, pressure against `capacity whole` on the same cell | dE 1e-7 eV/atom, dF 1e-5, dS 1e-8 without hybrids |
| `test_auto_runs_whole_when_the_cell_fits` | `capacity auto`, the log says whole, no tiled call, same numbers as today's style | identical to `capacity whole` |
| `test_auto_tiles_when_the_card_is_too_small` | `LOUP_DEBUG_PLAN_FREE` set low: `auto` runs tiled and says so | log line, results as above |
| `test_sorting_and_wrapping_keep_the_lists` | `atom_modify sort 1 ...` and atoms crossing the box over 200 NVE steps: the run-end line shows list builds only at skin/2 crossings | builds ≤ the engine's own count for the same trajectory |
| `test_tiled_run_style_follows_the_engines_tiled_md` | `run_style loupmd` with `fix nve` / `nvt` / `langevin` / `temp/csvr` / `temp/berendsen`, tiled, against `TiledEngine` driven from Python with the same mapped integrator, seed and steps | as the whole-mode test (`test_lammps_run_style.py:125-126`): positions 2e-5 Å, velocities 2e-3 Å/ps |
| `test_output_inside_a_tiled_run_leaves_the_trajectory_alone` | thermo every 10 vs every 1,000 | as the whole-mode test |
| `test_two_tiled_runs_continue_one_trajectory` | `run 100` twice vs `run 200` | as the whole-mode test |
| `test_tiled_nve_conserves_energy` | 1,000 steps NVE | drift < 0.05 meV/atom/ps (`test_tiled_md.py:66`) |
| `test_wavefront_and_host_forms` | `capacity wavefront`; `LOUP_TILE_HOST_LISTS=1`; `LOUP_TILE_HOST_STATE=1`: each against plain tiled | `test_tiled.py`'s bounds per form |
| `test_tiled_refusals_say_why` | POLAR-1-S with `capacity tiled`; `fix npt` under `run_style loupmd` tiled; `capacity wavefront` with a model of three layers (OMOL-0 extra large; MH-1 has two, so it runs the wavefront); per-atom compute | message text |
| `test_npt_through_the_pair_style_runs_tiled` | `fix npt iso` with `pair_style loupmd` tiled for 50 steps: runs, and the log warns of the per-step re-plan | runs; pressure finite |

Kept from the fast tier: one plain-style case and one run-style case. The rest go in the full tier (`@pytest.mark.full`).

## 6. Measurements

All on the RTX 5060 Ti under WSL 2, each under its own reservation, with fresh `LOUP_CACHE_DIR` plans per run and
two runs each (memory `ab-across-builds-fresh-plans`). They are recorded with "5060 Ti only" unless the `sm_89`
workstations are free (only with the owner's VPN and go).

1. **The plan's probe** at 5,000, 50,820 and 98,415 atoms (LT1). It decides the pre-filter.
2. **The pair style, the run style and the own loop, tiled.** MH-1 SrTiO3 at 50,820 and 98,415 atoms, and OMAT-0
   medium at 320,000 atoms. 100 warm-up + 200 measured steps (OMAT-0 at 320,000: 10 + 40 at about 1.1 s per step,
   to stay inside 15-minute jobs). Target: the run style within 2% of the own loop, the pair style within 5%.
3. **The cost of an output step** in tiled mode: thermo every 10 and every 100 on MH-1 at 50,820 atoms.
4. **`fix npt` through the pair style, tiled:** the step with the per-step re-plan against the fixed-cell step. It
   decides LT6 (a).
5. **Memory:** NVML peaks of the tiled LAMMPS runs against the plan's figures (`peak_bytes`) and against the own loop.

## 7. Documentation and bookkeeping

- **`lammps/README.md`:**
  - the syntax of `capacity`, `receivers`, `memory`;
  - a "Large cells" section: what tiled mode is, the plan line, which fixes `run_style loupmd` takes over tiled, the
    per-step re-plan under a changing box, `ghost no` for large cells;
  - the speed table of §6;
  - "Requirements and limits" updated.
- **`docs/guide/large-cells.md`:** a LAMMPS section linking the README.
- **`include/loupmd.h`:** `loup_evaluate_tiled` and the shared-state sentences (LT0).
- **`CHANGELOG.md`:** under the unreleased heading. The version stays 0.0.1 until the owner decides (O37).
- **`STATUS_AND_PROFILE.md`:** a section for the work with the measurements.
- **`OPTIMISATION_LEDGER.md`:** only if LT6 (a) or the output-step optimisation is tried. A feature is not an
  optimisation.
- **`AGENTS.md`:** the LAMMPS bullet gains the rules:
  - tiled mode is chosen at system send;
  - pass the cap, never 0, after the plan;
  - the tiled call and tiled MD share kept state;
  - the run style's tiled ensembles.
- **`PLAN.md`:** O42 (this plan), a D entry for LD2's choice of (A), and the stage rows as they finish.

## 8. Risks

| risk | effect | handling |
|---|---|---|
| The probe at each send under `auto` costs more than expected | slower start of every run with a new system | measured in LT1; `loup_plan_memory` pre-filter |
| The whole decision leaves 10% headroom, and LAMMPS-Kokkos allocates views after the plan | out of memory on the first whole call | the style catches the refusal at the first call after a WHOLE plan and re-plans once with the memory now free; test with `LOUP_DEBUG_ALLOC_FREE` |
| A denser cell than the probe saw (barostat) | the workspace or tile lists outgrow the plan | LD3's single re-plan |
| Pinned host memory under WSL 2 next to LAMMPS's own arrays | host memory pressure | the plan's shares of `MemAvailable` at plan time; the guard since `bf595d5`; tests force the host forms only on small cells |
| Bit-identical cell needed to keep lists | a style that rounds the box differently between calls rebuilds every step | `box_to_cell` is deterministic for a fixed box; the run-end line exposes unexpected rebuilds; the test of sorting and wrapping checks it |
| No GPU test interleaves tiled MD and the tiled call today | an untested shared-state path | LT0's tests (a)-(c) before any LAMMPS code |
| The destroy race (the crash fix) | crashes from other threads | the crash fix comes first; LAMMPS calls the engine from one thread |

## 9. Relation to other plans

- **`LAMMPS_SYMMETRIX_PARITY_PLAN.md` P4** (several processes and GPUs) is domain decomposition across ranks, with
  ghost shells and feature exchange. Tiled mode is one rank, one GPU, the cell in pieces over time. The two share
  the engine's open domains (`loup_debug_set_domain`), but neither needs the other. If P4 is built, each rank could
  itself run tiled for a subdomain larger than its card. That is a later question.
- **`PLAN.md` D65 (a)**, the device integrators on the tiled state, is done (O31's `loup_tiled_*`). LD6 uses them.
- **S5-T12 (B)**, the tiled mode as a mode of the public calls, stays open as a post-release item (LD2).

## 10. Points for the owner (answered 20 November 2026)

The owner's answer: "1 yes 2 pl 3 yes" ("pl" read as "ok").

1. **`capacity auto` as the LAMMPS default** (LD1): **yes.** The rejected alternative was `whole` by default with
   tiled opt-in, which keeps today's behaviour byte for byte, including failing on cells that are too large.
2. **LD2 (A) now and (B) after the release:** **yes.** (B) now would touch the release branch's public calls.
3. **LT6 (a), barostats in tiled mode:** **yes**, decided after LT5's measurement.
