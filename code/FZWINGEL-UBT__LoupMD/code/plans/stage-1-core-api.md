# Stage 1: core API v1 (step-level plan)

Plan tasks S1-T01 to S1-T11 of `PLAN.md`. Written 15 November 2026 on `release/v1` at `bac354c`. Working rules,
the GPU procedure and the shell variables `PY`, `RUN`, `GPU` are those of `plans/stage-0-ground-rules.md`.

Every task follows the same loop: write the failing test, run it and see it fail for the stated reason, implement,
run the test and the task's neighbours, commit. A task that changes a kernel or the step also runs the funnel of
`AGENTS.md` §4 against the baseline library before its commit, and adds its ledger row and status entry.

No figure in this plan is measured. Line numbers are those of `bac354c`.

## Interim layout (until S0-T03)

- New Python: `loupmd/__init__.py`, `loupmd/errors.py`, `loupmd/_core.py`, `loupmd/_legacy.py`.
- `loupmd._core.LoupEngine` is the ctypes binding of ABI v1. It replaces `python/loupmd.py`'s `LoupEngine` for
  the tests; `python/loupmd.py` itself is not edited.
- Tests stay in `tests/` (flat) until S2-T11. `tests/conftest.py` puts the repository root first on `sys.path`.
- Test command for one file: `$GPU "<task>" -- $RUN $PY -m pytest -q tests/<file>.py`.

## S1-T01: error channel

Files: `src/error.hpp` (new), `src/model.hpp`, `src/engine.cu`, `include/loupmd.h`, `loupmd/errors.py`,
`loupmd/_core.py`, `loupmd/_legacy.py`, `loupmd/__init__.py`, `tests/conftest.py`, `tests/test_engine.py`,
`tests/test_engine_guards.py`, `tests/test_error_channel.py` (new), `tests/test_errors.py` (new, no GPU).

Design.
- `loup::set_error(fmt, ...)` writes a thread-local pending message (`src/error.hpp`, header only: an inline
  function over an inline `thread_local std::string`, so no new translation unit and no `Makefile` change).
- `CUDA_CHECK` and `CUBLAS_CHECK` call `set_error` in place of `fprintf(stderr, ...)`. Every explicit refusal in
  `engine.cu` that returned -1 silently or after a stderr line calls `set_error` with its reason.
- `guarded(h, name, f)` clears the pending message, runs `f`, and on a failure stores `"<name>: <message>"` in
  `h->last_error` (in a thread-local string when `h` is NULL). A failure that set no message stores
  `"<name>: failed without a message"`. A successful call clears `h->last_error`.
- `loup_create` stores its message in the thread-local string and returns NULL as before.
- `const char* loup_last_error(const LoupHandle* h)`: the stored text, `""` if the last call succeeded. The
  pointer is valid until the next call on the handle (NULL: until the next failing call on the thread).
- `LOUP_DEBUG_ERRORS=1` also prints each stored message to stderr. Without it the library prints nothing on an
  error. The `LOUP_DEBUG_*` tuning prints are unchanged.
- Python: `LoupError(what, why=None, next_step=None)` with FastMACE's printed shape; `BackendError(LoupError,
  RuntimeError)` for a failed library call (attribute `call`); `InputError(LoupError, ValueError)` for arguments
  the wrapper refuses before the library reads them. Keeping `RuntimeError` and `ValueError` as bases keeps every
  existing `pytest.raises` valid, including tests that arrive by merge.

Steps.
1. Test first, no GPU: `tests/test_errors.py` checks the printed form of `LoupError` (what / `Why:` / `Next:`),
   the bases of `BackendError` and `InputError`, and pickling. Run: fails on the import. Implement
   `loupmd/errors.py`. Run: passes.
2. Test first, GPU: `tests/test_error_channel.py`
   - `test_refusal_text_reaches_python`: an unknown species raises `BackendError` whose text names the atomic
     number and the bundle's elements; `err.call == "loup_set_system"`.
   - `test_nothing_on_stderr_for_a_handled_error` (`capfd`): after refused `set_system`, `evaluate` and a failed
     create, captured stderr is empty.
   - `test_debug_switch_prints_the_message` (`LOUP_DEBUG_ERRORS=1`, child process): stderr holds the message.
   - `test_message_is_cleared_by_the_next_successful_call`: `loup_last_error` is `""` after a good call.
   - `test_create_error_is_per_thread`: a failed create on a worker thread leaves the main thread's text empty.
   - `test_every_refusal_has_its_own_text`: table of (call, bad argument, expected fragment) over every refusal
     of `engine.cu`: no system, no positions, steps, timestep, temperature, friction, skin, mass, NULL-free
     shapes, singular cell, non-finite cell, position and velocity, warm-up and call counts.
   Run against the baseline library: fails (`loup_last_error` missing).
3. Edit today's refusal tests (`test_engine.py`, `test_engine_guards.py`): each `pytest.raises(RuntimeError)`
   gains `match=` with the reason; the packed-table test reads the exception text instead of `capfd`.
4. Implement the C++ side; build to `libloupmd_cand.so`; implement `loupmd/_core.py`, `_legacy.py`,
   `__init__.py`; switch `tests/conftest.py`.
5. Run `tests/test_error_channel.py`, `tests/test_engine.py`, `tests/test_engine_guards.py`,
   `tests/test_families.py` with `LOUP_LIB` at the candidate; then install the library and run `pytest -q`.
6. Speed: the change touches no kernel and no launch. Check `cmp` of the SASS of two kernels
   (`cuobjdump -sass build/sm_120/engine.o`) is not needed; run one quick `bench_md.py` A/B (baseline library
   against the candidate, both orders) and record it in the task's commit message. No ledger row unless the A/B
   moves.
7. Commit `S1-T01: error channel (loup_last_error, LoupError)`; mark the task in `PLAN.md`.

Acceptance (PLAN): each of today's refusal tests asserts the message text; nothing is printed to stderr on a
handled error.

## S1-T02: ABI version, library version, `loup_get_info`

Files: `include/loupmd.h`, `src/engine.cu`, `loupmd/_core.py`, `loupmd/__init__.py`, `tests/test_abi.py` (new).

1. Tests first: `loup_abi_version() == 1`; `loup_version()` matches `^1\.0\.0\+[0-9a-f]{16}$` and its hash equals
   `library_build_hash`'s (the plan-cache file name carries it); `get_info()` on an OMAT-0 medium bundle gives
   `specialised == 1`, `n_layers == 2`, `n_species == 3`, `r_max == 6.0`, `compute_capability == 120`, the GPU
   name of `nvidia-smi`, `has_long_range == 0`; on OMAT-0 small `specialised == 0` and a non-empty
   `kernel_signature`; on POLAR-1-S `has_long_range == 1`. A stub library built from a ten-line C file with
   `loup_abi_version` returning 2 is refused by `_core` with a `BackendError` naming both versions (no GPU), and
   a library without the symbol (ABI 0) is refused the same way.
2. Implement: `LOUP_ABI_VERSION`, the three functions, `LoupInfo` as in `PLAN.md` §4.3. `kernel_signature` is the
   specialised path's `LOUP_KERNEL_SIGNATURE` or the generic layers' product signatures joined by `;`, truncated
   with a trailing `...` if longer than the field.
3. Run the new tests and `tests/test_engine.py`; commit `S1-T02: ABI and library version, loup_get_info`.

Acceptance (PLAN): Python refuses a library whose ABI differs, naming both versions.

## S1-T03: keep captured MD graphs across run calls

Files: `src/engine.cu` (`run_md_loop`, `invalidate_md_graphs`), `tests/test_md_graph_reuse.py` (new).

Today `run_md_loop` calls `invalidate_md_graphs()` at entry (line 2080) although `note_params` already records
kind, dt, temperature, friction and seed. It also runs a force pass before its first step on every call, which
alone would cost a tenth of a 10-step call: the acceptance needs both removed.

1. Tests first (`LOUP_DEBUG_GRAPHS` makes the library print a line per MD graph capture and per initial force
   pass; `LoupMDStats` is not extended, because `python/loupmd.py` allocates it at its present size):
   - `test_short_calls_reuse_the_graphs_and_the_forces`: after a settling phase, 20 calls of 10 steps print no
     initial force pass and at most 3 captures (one invalidation); the old code printed 40 or more.
   - `test_a_run_after_evaluate_needs_no_force_pass_and_one_after_new_positions_does`.
   - `test_changed_parameters_are_captured_again` for timestep, kind, temperature, friction and seed.
   - `test_a_changed_thermostat_takes_effect_on_reused_handles`: 100 K then 900 K on one handle.
   - `test_chunked_trajectory_matches_one_call`: 20 calls of 10 NVE steps against one call of 200 on `SrTiO3`
     3x3x3: positions within five times the difference of two single-call runs (floor 1e-6 A). The comparison
     with the baseline library's single call is part of step 3, outside pytest.
2. Implement: key = (kind, dt, temperature, friction, seed); graphs are dropped by `invalidate_graphs()` (edge
   bucket growth, scan workspace growth, kernel variant change, cell change of the long-range part,
   `free_system`) and by a key change, not at entry. `forces_current` on the handle is set by a completed
   evaluation or run and cleared by new positions; a run starts with a force pass only when it is clear. The
   stress flag is not part of an MD graph today (the MD pass records `compute_stress = 0`); the key gets the
   field when S4-T06 adds a stress-carrying step.
3. Acceptance run (GPU, quiet): 100 x 10 steps against 1 x 1,000 Langevin steps on `SrTiO3` 5,000 atoms, both
   orders, three repeats; the ratio must be within 2%.
4. Ledger row and status entry (this changes speed for chunked runs); commit `S1-T03: MD graphs kept across run
   calls`.

## S1-T04: `loup_run` with `LoupIntegrator`

Files: `include/loupmd.h`, `src/engine.cu`, `src/integrator.cu`, `loupmd/_core.py`, `tests/test_run_api.py` (new).

1. Tests first: `loup_run` with `LOUP_NVE` and `LOUP_LANGEVIN` against `loup_run_nve` / `loup_run_langevin` from
   the same state and seed: final positions differ by no more than two runs of the old entry point differ; a
   `size` smaller than the first released struct, an unknown `kind` and each integrator kind not yet built
   (`LOUP_CSVR` ... `LOUP_MTK_NPT`) are refused with a text naming the kind; the old entry points still pass
   `tests/test_engine.py`.
2. Implement: `LoupIntegrator` exactly as §4.3; `run_md_loop` takes the struct; `loup_run_nve` and
   `loup_run_langevin` fill it and call `loup_run`'s implementation. `fix_com` and `thermo_every` are accepted at
   0 and refused otherwise until S1-T05 / S4-T01.
3. Kernel list: `nsys profile --cuda-graph-trace=node` of 10 steps before and after; the per-step kernel names
   and counts are identical. Record the two lists' diff (empty) in the commit message.
4. Quick A/B (`AGENTS.md` funnel step 4), then commit `S1-T04: loup_run and LoupIntegrator`.

## S1-T05: thermo buffer on the device

Files: `src/thermo.cu` (new; `Makefile` `SRCS` gains it), `src/engine.cu`, `include/loupmd.h`, `loupmd/_core.py`,
`tests/test_thermo.py` (new).

1. Tests first: with `thermo_every = 20`, 200 NVE steps give 10 rows (steps 20 ... 200); each row's `e_pot` and
   `e_kin` equal `get_state` and `LoupMDStats` of a second engine stopped at the same step to 1e-12 relative;
   `conserved` is `e_pot + e_kin` for NVE; a second read returns 0 rows; a full buffer is reported, not
   overwritten.
2. Implement: a device ring of `LoupThermoRow`; a kernel at the end of the captured step that reduces the kinetic
   energy and writes a row when `step % thermo_every == 0` (the step counter already lives on the device);
   pressure and volume are filled only by a step that carries stress (0 until S4-T06).
3. Step cost at `thermo_every = 20`: A/B in both orders on `SrTiO3` 5,000 atoms; ledger row.
4. Commit `S1-T05: device thermo buffer and loup_read_thermo`.

## S1-T06: state blob

Files: `src/engine.cu`, `include/loupmd.h`, `loupmd/_core.py`, `tests/test_state_blob.py` (new).

1. Tests first: export, destroy, create, `set_system`, import: positions, velocities, cell, step counter and the
   displacement tracker equal the exported ones bitwise (a second export equals the first blob byte for byte);
   100 further Langevin steps end within the spread of two uninterrupted runs (at most 1e-4 A); a blob with
   another atom count, another version, a truncated blob and a blob of another species order are refused with a
   text each; `written` reports the needed size when `capacity` is too small.
2. Implement: header (magic, version, atom count, species hash), then caller-order arrays. The reference positions
   of the neighbour list are not part of the blob: import rebuilds the list.
3. Commit `S1-T06: loup_export_state and loup_import_state`.

## S1-T07: `loup_evaluate2`

Files: `src/engine.cu`, `src/generic.cu`, `include/loupmd.h`, `loupmd/_core.py`, `tests/test_evaluate2.py` (new).

1. Tests first: `LOUP_EVAL_ENERGY_ONLY` equals the full call's energy to 1e-12 relative on OMAT-0 medium, OMAT-0
   small and MH-1, and writes no forces; `LOUP_EVAL_PER_ATOM` energies sum to the total to 1e-9 relative and
   follow the caller's atom order; the default graph's kernel list is unchanged (`nsys`); POLAR-1 per-atom
   energies are refused or defined (decide from `polar.cu` when the task starts and put the choice to the owner
   if it is a refusal).
2. Implement: graph variants keyed by flags; the energy-only variant stops after the readouts.
3. Funnel, ledger note (the default path must be untouched), commit `S1-T07: loup_evaluate2`.

## S1-T08: the per-layer sweeps

Files: `src/domain.hpp` (new), `src/generic.cu`, `src/generic.hpp`, `tests/test_sweeps.py` (new).

Owner, 15 November (O9): no model is refused for its layer count. The sweeps are per layer: L - 1 forward sweeps,
one sweep of the last layer (forward, readouts, backward), L - 1 backward sweeps. Two layers give FastMACE's three
sweeps; OMOL-0 extra large gives five.

Design, from reading `GenericModel::record` (generic.cu 1481-1933) and FastMACE's `docs/design/tiled-backend.md`
§2-§4 on 15 November:

- Atoms couple only through the convolutions' sender gathers (`launch_conv_fwd` reads `x[sender]`,
  `launch_conv_bwd` adds to `dx[sender]`; layer 0 of most families reads the sender's species only). Everything
  else in a layer is per receiver.
- The state at the boundary after layer t is therefore the layer's output `hout_t` (all degrees, width `C_out`)
  for every atom, and its adjoint `dhout_t`; not the post-`linear_up` rows the plan's sketch named. The sweep of
  layer t + 1 gathers `hout_t` for its locals and ghosts and applies `W_up` to both (FastMACE does the same:
  `linear_up` on tile and halo), so the locals also have `h_in` for their skip connections and readout skip.
- The sweep of layer t + 1 scatter-adds `dh_in` for locals and ghosts into `dhout_t`. Layer t's backward sweep
  replays its forward, seeds `dhout_t` with its readout's gradient plus the stored adjoint, and goes on. Energy is
  accumulated by the forward sweeps only: a replay must not add its readout's energy again.
- Forces and virial stay per edge (`d_edge_dvec_`, then `assemble_forces_kernel` or the first layer's edge
  kernel), with ZBL in the layer-0 backward sweep; every edge belongs to its receiver's domain.
- OMOL-0's S57 fold writes later layers' inputs straight from `y_t` and never forms `hout_t`. The whole-system
  call keeps the fold. Domains use the plain path (what `LOUP_CHAIN_FOLD=0` runs today); its whole-system cost is
  on record in the ledger (S57: 0.821), so tiled OMOL-0 is slower per atom by about that factor, an estimate.
- For the whole system nothing moves: `record` becomes preamble, `forward_layer(t)` for each layer, the long
  range, `backward_layer(t)` in reverse, the final assembly; the kernel sequence of today, so the captured graph
  is the same.

1. Tests first: for every generic family (two layers: OMAT-0 small, OFF23 medium, MH-1, MP-0 medium; three:
   OMOL-0 extra large on water), energy, forces and stress of the composed sweeps differ from the unsplit pass by
   no more than two calls of the unsplit pass differ from each other (measured in the test; the unsplit pass stays
   selectable by `LOUP_UNSPLIT=1` until the task's last commit). The long-range models keep `record` unsplit.
2. OMOL-0's S57 skip-chain fold never forms the non-last layers' outputs, so its layer states are not the plain
   `x` rows. Decide at the task's start, from `setup_chain_fold`, whether the sweeps cut the folded path at the
   product outputs or whether tiled runs use `LOUP_CHAIN_FOLD=0`'s plain path; record the choice and its
   whole-system cost in the ledger.
3. Implement in commits that each keep the tests green: (a) `Domain` and `LayerState` structs filled from
   `GenericPassInputs` with `n_ghost == 0`; (b) `record` cut at the layer boundaries into `sweep_forward(t)`,
   `sweep_last`, `sweep_backward(t)` with `keep_activations = true` and `replay_forward = false`; (c) the replay
   path of the backward sweeps, tested by calling the sweeps with `keep_activations = false` on the whole system.
4. Gate for every generic family; full A/B in both orders on `NbCl5` and `SrTiO3` for OMAT-0 small and MH-1, and
   on water216 for OMOL-0 extra large.
5. Ledger row and status entry; commit `S1-T08: generic pass as per-layer sweeps`.

## S1-T09: open domains with ghost atoms

Files: `src/neighbors.cu`, `src/generic.cu`, `src/domain.hpp`, `tests/test_open_domain.py` (new).

Design notes of 15 November, after S1-T08's first part (`11c5205`); nothing of this is built.

- **Rows.** A domain has `n_local` receivers, grouped by species as today, followed by `n_ghost` ghosts in any
  order. Receiver-side arrays and kernels keep the count `N = n_local`. Four things run over
  `Nx = n_local + n_ghost` rows: the embedding gather, each layer's `linear_up` (`x = h_in W_up`), the adjoint
  `dx`, and `dh_in = dx W_up^T`. `GenericPassInputs` gets `n_ghost`; the species-grouped GEMMs stay on the locals.
- **Sweeps.** `record` gets a selector (`all`, `forward(t)`, `last`, `backward(t)`), so the per-layer pieces of
  S1-T08 are reachable one at a time without turning the pass into a class. Each sweep that differentiates
  (`last`, `backward(t)`) zeroes the edge gradients, runs its layer's backward and assembles its own edge forces
  into a domain-local force buffer; ZBL is added by `backward(0)` only. The caller owns what crosses sweeps:
  `hout_t` rows written for locals and gathered for ghosts, `dhout_t` rows scatter-added for both.
- **Neighbour list.** The periodic builder is reused on a non-periodic box around the domain with a margin above
  cutoff plus skin, with a receiver limit so that ghosts get no rows. Edges carry no shifts.
- **Workspace.** The domain needs its own set of per-system buffers sized for (receivers, ghosts, edges): a second
  handle-like object, not the whole-system handle's arrays. Stage 5's tile driver refills one such workspace per
  tile. What a tile keeps between steps is its edge list (senders, pair index: about 10 B per edge), not the
  135 B per edge of the whole-system build.
- **Test entry point.** `loup_debug_evaluate_domain(h, n_local, n_ghost, positions, ghost_of, ...)` runs all
  sweeps on one domain whose ghosts are images of locals (`ghost_of[g]` names the local a ghost copies): after
  each forward sweep the ghost rows are copied from their locals, after each differentiating sweep the ghosts'
  adjoint rows and forces are added to their locals. With the ghosts of a periodic cell this must give the
  periodic call's energy and forces.
- **Order of work.** (1) `n_ghost` and the selector in the generic pass, checked by `LOUP_SWEEP_REPLAY` still
  passing; (2) the workspace object and the open neighbour build; (3) the debug entry point and the test; (4)
  three-layer OMOL-0 on the plain path.

1. Test first: a 135-atom periodic `SrTiO3` cell (and the organic and NaCl cells for OFF23 medium and MH-1)
   evaluated as an open domain whose ghosts are its explicit periodic images within cutoff: energy to 1e-7
   eV/atom and forces to 3e-6 eV/A of the periodic call, for OMAT-0 small, OFF23 medium, MH-1 and OMOL-0 extra
   large (three layers: the ghosts' two layer states are both gathered). The test needs
   an entry point: an internal `loup_debug_evaluate_domain` exported only in test builds, or a hidden symbol
   reached through `ctypes`; decide at the task's start.
2. Implement: neighbour build without shifts where only locals receive; ghost rows of `x` gathered by the caller;
   `dx` accumulated for ghosts.
3. Commit `S1-T09: open domains with ghost atoms`.

## S1-T10: memory plan

Files: `src/engine.cu`, `include/loupmd.h`, `loupmd/_core.py`, `tests/test_memory_plan.py` (new).

1. Test first: predicted whole-system bytes within 10% of the measured peak (`cudaMemGetInfo` before
   `set_system` and after the first evaluate) for 5,000, 20,480 and 40,000 `SrTiO3` atoms on OMAT-0 medium; the
   same for OMAT-0 small on the generic path at 5,000 atoms.
2. Implement from the allocation arithmetic of `set_system_impl` (lines 1789-1809 and the buffers around them),
   `GenericModel::alloc_system` and `ensure_edges`. The tiled fields are 0 until Stage 5.
3. The 40,000-atom case runs only with the guards of the local GPU (expected well under 12 GiB; check the
   prediction before the run).
4. Commit `S1-T10: loup_plan_memory`.

## S1-T11: decaying displacement maximum

Files: `src/engine.cu`, `src/integrator.cu`, `tests/test_pipeline_decay.py` (new).

1. Tests first: water 2x2x2 (OFF23 medium) at 300 K over 5,000 steps reports `pipelined_steps > 0` and
   `dangerous_builds == 0`; one deliberately fast first step (a single hot atom) no longer keeps a later cold run
   unpipelined; the existing pipeline tests of `tests/test_engine.py` pass.
2. Implement: the running maximum is reset at each neighbour rebuild to the maximum seen since the previous one
   (two-window maximum), so it decays within two rebuild intervals and never drops below the current window's
   maximum.
3. Soundness check: `dangerous_builds == 0` on the hot Langevin test (1,200 K) and on water at 500 K.
4. A/B on the standard benchmarks (they already pipeline; no change expected) and on water; ledger row and status
   entry; commit `S1-T11: decaying displacement maximum`.

## Exit of Stage 1

1. Merge `round6-hardening`; rebuild.
2. `pytest -q`, the default gate, the gate for every family of `tests/test_gate_wrapper.py`.
3. Full A/B against the Stage 0 baseline library in both orders on `NbCl5` and `SrTiO3`.
4. Mark the tasks in `PLAN.md` with their commits; record the merged commit under §9.
5. Ask the owner before the tag `v1.0.0a1`.
