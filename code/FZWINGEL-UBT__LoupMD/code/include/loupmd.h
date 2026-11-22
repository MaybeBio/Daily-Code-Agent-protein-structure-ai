#pragma once

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct LoupHandle LoupHandle;

// The version of this C interface. It changes when a call or a struct of this header changes incompatibly; a
// caller built against another value must not use the library (loupmd/_core.py refuses it).
#define LOUP_ABI_VERSION 1
// The release this source belongs to (the same string as loupmd.__version__).
#define LOUP_VERSION "0.0.2"

int loup_abi_version(void);     // LOUP_ABI_VERSION of the loaded library
const char* loup_version(void); // LOUP_VERSION "+" 16 hex digits: a hash of the library file (the one in the
                                // GEMM plan cache's file names)

typedef struct {
    double step_ms;                    // GPU time per step, excluding tune_ms
    int rebuilds;
    double final_potential_energy_ev;
    double final_kinetic_energy_ev;
    double final_temperature_k;
    int dangerous_builds;              // steps whose force pass ran on a list an atom had left by more than skin/2:
                                       // always 0 (every step checks its list before its force pass); kept for the
                                       // layout of LOUP_ABI_VERSION 1
    double tune_ms;                    // one-time per-system kernel-variant timing at the first rebuild, or after 50
                                       // force passes without one (not in step_ms)
    int pipelined_steps;               // steps of this call the GPU ran without waiting for the host: all but those
                                       // whose neighbour rebuild the host finished
} LoupMDStats;

// All int-returning calls return 0 on success and -1 on failure (no C++ exception escapes); loup_last_error gives
// the reason. After a failure caused by a CUDA error the device context may be unusable: destroy the handle.

// The reason of the last failure, as "<entry point>: <message>".
//   h != NULL: the last call on `h`; "" if that call succeeded. Valid until the next call on `h`.
//   h == NULL: this thread's last loup_create, or call with a NULL handle; "" if the last loup_create on this
//              thread succeeded. Valid until this thread's next loup_create or failing call without a handle.
// The library prints nothing on a failure. LOUP_DEBUG_ERRORS (set to anything) also prints each message to stderr.
const char* loup_last_error(const LoupHandle* h);

// Create engine from a .loup bundle (python -m loupmd.export; loupmd.bundles caches them) on CUDA
// device `device_id`. One path for every family (MACE-OMAT-0 / MP-0 / MPA-0 / MatPES, MACE-OMOL-0, MACE-OFF23/23b/24,
// MACE-MH-1 with one head per bundle, MACE-POLAR-1 S/M/L); bundles of the retired specialised OMAT-0-medium path
// (arch omat0_medium_spec, before JIT_DESIGN.md stage 5) are refused: re-export them. MACE-POLAR-1 is
// evaluated for neutral singlet systems in zero external field; its stress includes the k-space terms' cell
// dependence (MACE PR 1718), which the PolarMACE releases up to 0.3.16 leave out.
LoupHandle* loup_create(const char* loup_path, int device_id);
void loup_destroy(LoupHandle* h);

// What a handle runs: the model as loaded and the GPU it is on.
typedef struct {
    int abi;                    // LOUP_ABI_VERSION of the library
    int compute_capability;     // of the handle's GPU, major * 10 + minor (120 for sm_120)
    int n_layers;               // interaction layers of the model
    int has_long_range;         // 1 for MACE-POLAR-1 (k-space electrostatics), else 0
    int specialised;            // always 0: the kernels specialised to MACE-OMAT-0 medium were retired (the field
                                // keeps the struct's layout)
    int n_species;              // elements the bundle was exported for
    double r_max;               // cutoff in A
    char gpu_name[64];
    char kernel_signature[160]; // the compiled kernels the bundle needs; ends in "..." if it did not fit
} LoupInfo;
int loup_get_info(const LoupHandle* h, LoupInfo* out);

// Facts of the loaded model: the cutoff radius in A (0 on a null handle), and the atomic numbers of the bundle's
// species (returns their count and writes at most `max` of them to out_atomic_numbers, which may be NULL).
double loup_cutoff(const LoupHandle* h);
int loup_species(const LoupHandle* h, int* out_atomic_numbers, int max);

// Set system topology (species as atomic numbers Z[0..n_atoms-1], masses in amu).
// Internally groups atoms by species for contiguous GEMMs; for systems whose per-atom working set exceeds L2, atoms
// inside each species group are also reordered spatially at every neighbour-list rebuild. All inputs and outputs
// use the caller's atom order.
int loup_set_system(LoupHandle* h, int n_atoms, const int* atomic_numbers, const double* masses_amu, double skin);

// Single-point evaluation (positions [n_atoms, 3] in A, cell [3, 3] row-major in A). Replaces the positions, keeps
// MD velocities; the neighbour list is rebuilt only if the cell changed or an atom moved more than skin/2.
// Forces written to out_forces [n_atoms, 3] in eV/A (caller atom order).
// Stress [3, 3] in eV/A^3 (optional, pass nullptr to skip virial/stress accumulation).
int loup_evaluate(
    LoupHandle* h,
    const double* positions,
    const double* cell,
    int compute_stress,
    double* out_energy_ev,
    double* out_forces,
    double* out_stress
);

// loup_evaluate with flags.
//   LOUP_EVAL_STRESS       also the stress (out_stress [3, 3]); without it out_stress is not written.
//   LOUP_EVAL_ENERGY_ONLY  the energy alone, from a pass without gradients: for Monte Carlo move energies. Forces
//                          and stress are not computed and out_forces is not written; the forces loup_get_state
//                          returns are then not those of these positions, and a run that follows starts with a
//                          force pass of its own. Excludes LOUP_EVAL_STRESS.
//   LOUP_EVAL_PER_ATOM     also per-atom energies (eV) into out_atom_energies [n_atoms], in the caller's order:
//                          each atom's MACE node energy (the readouts of every layer and its share of the ZBL
//                          pair energies) plus its E0 (0 for ghost atoms). out_energy_ev is then their sum; it
//                          differs from a plain call's energy in float32 rounding (the per-atom energies come from
//                          one more energy-only pass; measured up to 6e-7 relative), while forces and stress are
//                          the plain call's. The device forces are stale afterwards.
//                          Not for long-range models: refused there.
#define LOUP_EVAL_STRESS 1
#define LOUP_EVAL_ENERGY_ONLY 2
#define LOUP_EVAL_PER_ATOM 4
int loup_evaluate2(
    LoupHandle* h,
    const double* positions,
    const double* cell,
    int flags,
    double* out_energy_ev,
    double* out_forces,
    double* out_stress,
    double* out_atom_energies
);

// Evaluate ahead (0 off, the default; 1 on): after a loup_evaluate call the engine queues the next call's force pass
// on its GPU stream, held back until that call has written its positions, so the call itself launches nothing. It
// is for a caller that integrates on the host and calls loup_evaluate every step, such as the LAMMPS pair style:
// measured on an RTX 5060 Ti under WSL 2, it took 2-7% off a LAMMPS step on cells of a few hundred atoms and nothing
// measurable off a 5,000-atom step. It starts after two calls in a row with one stress flag and
// an unchanged cell; a call that does not fit the queued pass, and every other call on the handle, lets the queued
// pass run first (its result is discarded), so results never depend on the setting.
// WARNING: between two loup_evaluate calls the handle's stream then holds work that cannot run. Other GPU work of
// the process in that time may wait for it forever: anything on CUDA's default stream (another handle being set up,
// another library such as PyTorch) and any device-wide synchronisation. Switch it on only when this handle's
// loup_evaluate calls are the process's only GPU work between them. Without driver support for a stream wait on host
// memory the setting has no effect. LOUP_EVAL_ARM=0 keeps it off for every handle; =1 switches it on for every handle.
int loup_set_evaluate_ahead(LoupHandle* h, int on);

// Initialize MD state (positions [n_atoms, 3] in A, velocities [n_atoms, 3] in ASE units, i.e. A per ASE time unit
// as returned by ase.Atoms.get_velocities(); cell [3, 3] in A). Velocities are zero after loup_set_system until
// this call sets them (a run after only loup_evaluate starts from rest).
int loup_set_state(LoupHandle* h, const double* positions, const double* velocities, const double* cell);

// Holds atoms in place (ASE's FixAtoms). `fixed` [n_atoms] in caller order, nonzero = fixed; NULL frees all. A
// fixed atom keeps its position in every integrator, has zero velocity and gets no thermostat noise; the
// temperatures the engine reports count 3 (N - n_fixed) degrees of freedom. Energies and forces are unchanged
// (the caller ignores the forces on fixed atoms). Fixing every atom is refused. loup_set_system frees all.
int loup_set_fixed_atoms(LoupHandle* h, const int* fixed);

// The run and profile calls return -1 unless positions and a neighbour list exist (loup_set_state or loup_evaluate
// after loup_set_system, with the last rebuild completed).
// A run may be split into calls of any length at no extra cost: the captured step graphs are kept while the
// timestep, thermostat settings and seed stay the same, and a call that follows a run or an evaluation at the same
// positions starts from the forces already on the device.
// Run NVE Velocity-Verlet steps (`dt_fs` in fs). Every step checks the skin list against its new positions before
// its force pass and rebuilds it only when an atom has moved more than skin/2.
int loup_run_nve(LoupHandle* h, int n_steps, double dt_fs, LoupMDStats* out_stats);

// Run Langevin steps (ASE's Vanden-Eijnden-Ciccotti scheme; `dt_fs` in fs, `temp_k` in K, `friction_per_fs` in 1/fs,
// same as ASE's friction=f/units.fs). The noise stream continues across calls; it restarts only in loup_set_system.
int loup_run_langevin(
    LoupHandle* h,
    int n_steps,
    double dt_fs,
    double temp_k,
    double friction_per_fs,
    unsigned long long seed,
    LoupMDStats* out_stats
);

// One run call for every integrator. The caller sets `size` to sizeof(LoupIntegrator), so a library can tell which
// fields a caller built against another header knows; zero every field it does not use.
enum {
    LOUP_NVE = 0,            // velocity Verlet
    LOUP_LANGEVIN = 1,       // ASE's Vanden-Eijnden-Ciccotti Langevin scheme
    LOUP_CSVR = 2,           // canonical sampling through velocity rescaling (Bussi), as ASE's Bussi
    LOUP_NHC = 3,            // Nose-Hoover chain, as ASE's NoseHooverChainNVT
    LOUP_BERENDSEN_NVT = 4,  // Berendsen thermostat, as ASE's NVTBerendsen (not canonical: for equilibration)
    LOUP_BERENDSEN_NPT = 5,  // with Berendsen's barostat: ASE's NPTBerendsen (LOUP_CELL_HYDROSTATIC) or its
                             // Inhomogeneous_NPTBerendsen (LOUP_CELL_FULL with cell_mask), with one force call
                             // per step: the first kick uses the forces of the cell before its scaling, where
                             // ASE's classes evaluate again. Experimental. Not with fixed atoms
    LOUP_BAOAB_NPT = 6,      // Langevin BAOAB with the Langevin-Hoover barostat, as ASE's LangevinBAOAB with
                             // externalstress: T_tau = 1 / friction_per_fs, P_tau = tau_p_fs (0: 20 T_tau), the
                             // barostat's mass from ASE's heuristic, external stress -pressure_gpa,
                             // LOUP_CELL_HYDROSTATIC or LOUP_CELL_FULL. In the full-cell mode the barostat's drag
                             // on the velocities is Quigley and Probert's (p + Tr(p) / Ndof 1) / W; ASE 3.27
                             // adds the trace to all nine elements. Experimental. Not with fixed atoms or fix_com
    LOUP_MTK_NPT = 7         // Martyna-Tobias-Klein: Nose-Hoover chains on the atoms and on the cell, as ASE's
                             // IsotropicMTKNPT (LOUP_CELL_HYDROSTATIC) and MTKNPT (LOUP_CELL_FULL): tdamp =
                             // tau_t_fs, pdamp = tau_p_fs, chain_length and p_chain_length (0: 3, at most 8),
                             // the masses made for mass_temp_k (0: temp_k). Experimental. Not with fixed atoms
};
enum { LOUP_CELL_HYDROSTATIC = 0, LOUP_CELL_FULL = 1 };

typedef struct {
    unsigned size;                 // sizeof(LoupIntegrator) of the caller
    int kind;                      // LOUP_NVE ...
    double dt_fs;                  // timestep in fs
    double temp_k;                 // thermostat temperature in K
    double temp_rate_k_per_step;   // thermostats: step i of the call (1 .. n_steps) runs at temp_k + i * this (a
                                   // ramp; 0 = constant). The target lives on the device, so calls that differ
                                   // only in temperature reuse the captured step
    double friction_per_fs;        // Langevin friction in 1/fs
    double tau_t_fs;               // thermostat time constant in fs (CSVR, Nose-Hoover chain, Berendsen)
    double mass_temp_k;            // Nose-Hoover chain: the temperature its thermostat masses are made for (ASE: the
                                   // temperature the object was made with); 0 takes temp_k. A ramp moves the
                                   // target, not the masses
    double pressure_gpa;           // barostat pressure in GPa
    double tau_p_fs;               // barostat time constant in fs
    double compressibility_per_gpa;// Berendsen NPT: the material's compressibility in 1/GPa
    int chain_length;              // Nose-Hoover chain: thermostats in the chain (ASE's tchain), 1 to 16
    int chain_loops;               // Nose-Hoover chain: sub-steps of the chain per half step (ASE's tloop); 0 is 1
    int p_chain_length;            // MTK NPT: links of the barostat's chain (ASE's pchain), 1 to 8; 0 is 3
    int p_chain_loops;             // MTK NPT: sub-steps of the barostat's chain per half step (ASE's ploop); 0 is 1
    int cell_mode;                 // LOUP_CELL_HYDROSTATIC (the shape is kept) or LOUP_CELL_FULL
    int cell_mask[3];              // LOUP_CELL_FULL, Berendsen: 1 for a cell vector the barostat may scale, 0 for
                                   // one it leaves alone (ASE's mask); the angles stay
    int fix_com;                   // keep the centre of mass at rest. Langevin: both noise terms lose their
                                   // mass-weighted mean every step, so the thermostat puts no momentum into the
                                   // centre of mass (FastMACE's "mass_weighted" projection). NVE and CSVR: the
                                   // total momentum is removed at the start of the call. Temperatures then count
                                   // three degrees of freedom fewer. Refused together with fixed atoms
    int thermo_every;              // write a thermo row every so many steps (loup_read_thermo); 0 = none
    unsigned long long seed;       // noise stream of the stochastic integrators
} LoupIntegrator;

// Runs `n_steps` steps of `it`. NVE reads dt_fs; Langevin reads dt_fs, temp_k, temp_rate_k_per_step, friction_per_fs
// and seed; CSVR reads dt_fs, temp_k, temp_rate_k_per_step, tau_t_fs and seed. All read fix_com and thermo_every.
// The rules of loup_run_nve and loup_run_langevin apply: those two calls are this one with the struct filled in.
// CSVR scales the velocities at the start of every step by the factor of Bussi, Donadio and Parrinello's equation
// A7 (one normal and one chi-square variate per step, from the seed and the step counter), then steps as NVE. Its
// degrees of freedom are those of the reported temperature. A system at rest is not scaled until the forces have
// set it in motion.
// The Nose-Hoover chain reads dt_fs, temp_k, temp_rate_k_per_step, tau_t_fs (ASE's tdamp), mass_temp_k,
// chain_length and chain_loops: the chain for half a step, a velocity-Verlet step, the chain for half a step, with
// ASE's fourth-order sub-steps. The chain's variables travel in the state block; the degrees of freedom of the
// reported temperature stand where ASE has 3 N.
// The Berendsen thermostat reads dt_fs, temp_k, temp_rate_k_per_step and tau_t_fs (ASE's taut, at least dt_fs):
// the velocities are scaled by sqrt(1 + (T0 / T - 1) dt / taut) within [0.9, 1.1] at the start of every step.
int loup_run(LoupHandle* h, const LoupIntegrator* it, int n_steps, LoupMDStats* out_stats);

// Structure relaxation at fixed cell on the device. LOUP_MIN_LBFGS is ASE 3.27's LBFGS without line search: the
// same steps to rounding (the history's sums are taken in another order). Fixed atoms (loup_set_fixed_atoms) do
// not move and their forces do not count.
enum { LOUP_MIN_LBFGS = 0 };

typedef struct {
    unsigned size;        // sizeof(LoupMinimizer) of the caller
    int kind;             // LOUP_MIN_LBFGS
    double fmax_ev_a;     // converged when the largest force on a free atom is below this, in eV/A
    double maxstep_a;     // the longest step of an atom in A (ASE: 0.2)
    int memory;           // history pairs kept (ASE: 100)
    int reserved;
    double damping;       // step factor (ASE: 1.0)
    double alpha;         // initial inverse-Hessian guess is 1 / alpha, in eV/A^2 (ASE: 70.0)
} LoupMinimizer;

typedef struct {
    int steps;                     // optimiser steps taken in this call
    int converged;                 // 1 if the largest force is below fmax_ev_a
    int total_steps;               // steps of this relaxation so far (it continues across calls, see below)
    int rebuilds;                  // neighbour rebuilds of this call
    int force_passes;              // force passes of this call, the repeated ones included
    int repeated_passes;           // force passes run again because the step before had outdated the neighbour
                                   // list (the list check of a small step comes with the next step's results)
    double max_force_ev_a;         // the largest force on a free atom at the positions the call ends with
    double potential_energy_ev;    // at those positions
    double force_ms;               // this call's force evaluations: force passes, list checks and rebuilds
    double optimizer_ms;           // the optimiser's own kernels and its host arithmetic
} LoupMinStats;

// Takes up to `max_steps` optimiser steps from the positions on the handle (loup_set_state, or where a run or an
// earlier call left them) and stops as soon as the largest force is below fmax_ev_a. max_steps = 0 only evaluates
// (energy and largest force). Velocities are not touched. A call with the same settings as the one before goes on
// with that relaxation and its history (so a caller may step one at a time), unless positions were set, a run or
// an evaluation moved them, the fixed atoms changed or the handle's atom order was renewed: then the history
// starts empty. loup_get_state reads the result.
int loup_minimize(LoupHandle* h, const LoupMinimizer* minimizer, int max_steps, LoupMinStats* out_stats);

// Thermodynamic output without a host round trip per row: with LoupIntegrator.thermo_every = k, every k-th step
// appends a row to a buffer on the device, inside the captured step.
typedef struct {
    long long step;       // MD steps completed since the last loup_set_state or loup_import_state on this handle
    double e_pot;         // eV, as loup_get_state's energy at that step
    double e_kin;         // eV
    double temp_k;        // 2 e_kin / (3 N k_B)
    double pressure_gpa;  // variable-cell steps: minus a third of the stress's trace plus 2 e_kin / (3 V) (ASE's
                          // stress with the ideal-gas part); 0 in a fixed-cell step, which carries no stress
    double volume_a3;     // variable-cell steps: the cell's volume; 0 in a fixed-cell step
    double conserved;     // e_pot + e_kin (NVE's conserved quantity); for CSVR minus the energy its thermostat has
                          // transferred since the last loup_set_state (it travels in the state block); for the
                          // Nose-Hoover chain plus the chain's energy (ASE's get_conserved_energy)
} LoupThermoRow;
// Copies up to `max_rows` of the oldest unread rows to `rows`, removes them from the buffer and sets *n_rows to
// their number. loup_read_thermo(h, NULL, 0, &n) only counts the unread rows. The buffer holds 4096 rows: a run
// call that would write more than its free part is refused before its first step. loup_set_state and
// loup_import_state discard unread rows.
int loup_read_thermo(LoupHandle* h, LoupThermoRow* rows, int max_rows, int* n_rows);

// The largest distance in A any atom moved in one MD step, over the current and the previous window of the
// displacement tracker (a window holds 32 to 512 steps; a neighbour rebuild ends one); 0 before the first step.
// The run loop compares four times this with half the skin: below it, steps run in the pipelined loop. A caller
// that picks the skin (loup_set_system) can measure with this what the skin has to cover.
int loup_get_step_displacement(LoupHandle* h, double* out_max_a);

// The cell of the positions on the handle (row-major, rows are the cell vectors, in A): the one last given, or
// where a variable-cell run has taken it.
int loup_get_cell(LoupHandle* h, double* out_cell);

// The volume V0 the cell limits of a variable-cell run refer to (it stops outside [V0 / 20, 20 V0]).
// loup_set_state sets it to the volume it is given; a run that goes on in another process from a state block
// passes the first run's here. On a handle with tiled MD state (loup_tiled_set_state) it sets that state's V0.
int loup_set_reference_volume(LoupHandle* h, double volume_a3);

// A new cell for the positions on the handle. scale_atoms != 0: the atoms keep their fractional coordinates
// (ASE's set_cell(scale_atoms=True)); 0: they stay where they are. Velocities are kept, the neighbour list is
// rebuilt, and forces are those of the old cell until the next evaluation or run.
int loup_set_cell(LoupHandle* h, const double* cell, int scale_atoms);

// Read back state in caller's original atom order (velocities in ASE units, as for loup_set_state).
int loup_get_state(LoupHandle* h, double* out_positions, double* out_velocities, double* out_forces, double* out_energy_ev);

// The state a restart needs, as one versioned block of bytes: positions, velocities and cell as the caller gave
// them (caller atom order), the step counter (the offset of the noise streams, so a resumed Langevin or CSVR run
// continues its noise), the integrator's scalars (CSVR's transferred energy) and the displacement tracker. Forces
// and the neighbour list are not in it.
//   loup_export_state(h, NULL, 0, &n) sets n to the size in bytes. With a buffer it writes the block; a buffer
//   smaller than that is refused, and n still holds the size.
//   loup_import_state needs the same system on the handle (loup_set_system with the same atomic numbers in the
//   same order) and refuses a block of another atom count, species list, version or length, or a damaged one. It
//   rebuilds the neighbour list; the next run starts with a force pass.
int loup_export_state(LoupHandle* h, void* buffer, size_t capacity, size_t* written);
int loup_import_state(LoupHandle* h, const void* buffer, size_t size);

// How a force call is executed. LOUP_EXEC_WAVEFRONT is the tiled call with the wavefront schedule forced (S5-T08).
enum { LOUP_EXEC_AUTO = 0, LOUP_EXEC_WHOLE = 1, LOUP_EXEC_TILED = 2, LOUP_EXEC_WAVEFRONT = 3 };

// The device memory a system of `n_atoms` with `edges_per_atom` neighbours per atom inside cutoff + skin would
// take, scaled from the buffers of the handle's current system, which must have a neighbour list (any size: a
// small cell of the same material will do). edges_per_atom <= 0 takes the current system's value.
typedef struct {
    size_t whole_bytes;          // every buffer of the whole-system call that scales with atoms or edges
    size_t tiled_global_bytes;   // 0 until the tiled mode is built
    size_t tile_workspace_bytes; // 0 until the tiled mode is built
    size_t free_bytes;           // free device memory now (cudaMemGetInfo), the current system's buffers included
                                 // in what is used
    int receivers;               // receiver cap of the tiled mode; 0 until it is built
    int mode;                    // LOUP_EXEC_WHOLE if the whole-system call fits with 10% headroom once the current
                                 // system is released, else LOUP_EXEC_TILED (the size needs the capacity mode)
    int host_lists;              // 1: the tiled plan keeps the tiles' edge lists in pinned host memory (O31, S5-T07)
    size_t host_bytes;           // the pinned host memory that plan takes (lists and layer state); 0 without either
    int host_state;              // 1: the tiled plan keeps the layer outputs and their gradients in pinned host
                                 // memory too (O32; the plain order's whole system, or the wavefront's row pool)
} LoupMemoryPlan;
// Not counted: MACE-POLAR-1's long-range buffers, captured graphs and cuBLAS's own allocations.
int loup_plan_memory(LoupHandle* h, int n_atoms, double edges_per_atom, LoupMemoryPlan* out);

// The execution of the capacity mode (plan task S5-T05). loup_set_execution sets the mode (LOUP_EXEC_AUTO,
// LOUP_EXEC_WHOLE, LOUP_EXEC_TILED or LOUP_EXEC_WAVEFRONT), a receiver cap (0: the plan's) and the fraction of free device memory a
// plan may use (above 0, at most 1; default 0.9); loup_set_system keeps them. loup_plan_execution plans the
// periodic system `positions` in `cell` under them: with AUTO or TILED on a bundle that can tile (generic path,
// no long range, two or more layers) one probe tile of at most 4,096 receivers is set up on the handle and its
// buffers measured per row and per edge; whole_bytes is then the whole-system call's estimate, and receivers the
// largest cap of 4,096, 6,144, 8,192, ... 65,536 whose workspace and whole-system state (tiled_global_bytes,
// tile_workspace_bytes) fit, or the cap set. mode: WHOLE when asked, when the bundle cannot tile, or (AUTO) when
// the whole-system call fits; else TILED. When no cap fits with the tile lists on the device, the plan moves the
// lists' edge arrays (36 B per edge) to pinned host memory (host_lists, host_bytes; at most half of the available
// host memory), which the active-edge compaction reads over the bus once per tile and call (PLAN.md O31); the
// environment variable LOUP_TILE_HOST_LISTS=1|0 forces that on or off (tests). When no cap fits with the lists in
// host memory either, the plan also moves the whole system's layer outputs and their gradients there (host_state;
// O32, as FastMACE's host state: each atom's row in its tile's block, a tile's own rows copied as one block, ghost
// rows gathered and gradient rows added on host threads, the copies overlapped with the sweeps on two copy
// streams), within 60% of the available host memory with the lists. Where the wavefront applies and the plain
// order's state does not fit there (or the wavefront is forced), the wavefront's row pool goes to host memory
// instead, as blocks of a tile's locals held from its first sweep to its last, its sweeps one after another;
// LOUP_TILE_HOST_STATE=1|0 forces it on or off, LOUP_TILE_HOST_PIPE=0 runs its copies and host work without the
// overlap (tests). A system that does not fit at 4,096 receivers any way is refused. The handle
// afterwards holds the probe tile: call loup_set_system before other calls.
// The wavefront (S5-T08; two-layer models): the tiled call runs its three sweeps in loup_wavefront_schedule's order
// and keeps the layer outputs and their gradients in a row pool instead of whole-system arrays. LOUP_EXEC_WAVEFRONT
// forces it (refused for models of other layer counts); under AUTO or TILED it is on from 2^20 atoms when the plan
// has 12 or more layers of tiles along the first cell axis. The plan's tiled_global_bytes then counts the pool, and
// its mode stays TILED. The environment variable LOUP_TILE_WAVEFRONT=1|0 overrides both (tests).
// loup_get_execution: how the last tiled call (loup_evaluate_tiled or loup_tiled_run) ran; mode is LOUP_EXEC_WAVEFRONT when it
// ran the wavefront, else LOUP_EXEC_TILED. budget_bytes is the device memory
// free when it began plus the handle's own buffers; peak_bytes that budget less the least memory free during it.
// A tiled call keeps the plan, the tile lists and the whole-system state of the previous one while the atomic
// numbers, the cell, the skin and the cap are the same (receivers 0 takes the kept cap) and no atom has moved more
// than skin/2 since the lists were built; loup_set_system and loup_plan_execution drop them (plan task S5-T06).
typedef struct {
    int mode;
    int receivers;
    long long tiles;
    size_t budget_bytes;
    size_t peak_bytes;
    int lists_kept;          // 1: the call kept the tile lists of an earlier call and refreshed their positions
    long long list_builds;   // tiled calls of this handle that built their tile lists
    int host_lists;          // 1: the call's tile edge lists were in pinned host memory
    int host_state;          // 1: the call's layer outputs and gradients were in pinned host memory (O32)
} LoupExecution;
int loup_set_execution(LoupHandle* h, int mode, int receivers, double memory_fraction);
int loup_plan_execution(LoupHandle* h, int n_atoms, const int* atomic_numbers, const double* positions,
                        const double* cell, double skin, LoupMemoryPlan* out);
int loup_get_execution(LoupHandle* h, LoupExecution* out);

// The tiled call (the capacity mode's force call; LAMMPS_TILED_PLAN.md LD2): energy (eV), forces [n_atoms, 3]
// (eV/A) and stress [3, 3] (eV/A^3, the virial over the cell's volume, sign as loup_evaluate's) of the periodic
// system `positions` [n_atoms, 3] (A) in `cell` (rows are the lattice vectors), evaluated tile by tile with the
// per-layer sweeps, at most `receivers` local atoms per tile. out_stress NULL skips the virial (the cheaper call);
// out_tiles (optional) receives the tile count. Bundles of the generic path without long range and without a
// dispersion term, of two or more layers (LOUP_EXEC_WAVEFRONT: exactly two).
// receivers: pass the cap of loup_plan_execution (LoupMemoryPlan.receivers) or a cap of the caller's. With 0 or less
// the call keeps the cap of the previous tiled call on the same system while it keeps the lists (below); when the
// system changed (another skin, atom count or atomic numbers) or its cell changed beyond what the kept lists allow,
// it plans again, which sets up a probe tile and drops the kept tile lists and state.
// What stays between calls: the tile plan, the tile lists and the whole-system layer state are kept while the
// atomic numbers, the skin and the cap are the same and no atom has moved more than skin/2 since the lists were built,
// measured as the plain Cartesian difference of the positions passed (no minimum image: pass unwrapped positions, or
// atoms that cross a face count as moved by a cell vector and the lists are built again). In a cell other than the
// one the lists were built in (a barostat's), the test is that of the variable-cell step: with F = h0^-1 h (h0 that
// cell), the lists stay while r_list (1 - |F - 1|) > r_max (|.| the Frobenius norm, r_list = cutoff + skin) and every
// atom lies within (r_list (1 - |F - 1|) - r_max) / 2 of x0 F + t, x0 its position then and t the atoms' mean
// displacement, so a common translation does not count. The tiled MD calls below share that state, so an
// evaluation between two blocks of loup_tiled_run on the same positions builds no lists. loup_get_execution
// afterwards: the cap, tiles, lists kept and list builds.
// The handle then holds the last tile's domain: loup_evaluate, loup_run and the other whole-system calls refuse
// until loup_set_system. loup_set_system drops the kept tiled state.
int loup_evaluate_tiled(LoupHandle* h, int n_atoms, const int* atomic_numbers, const double* positions,
                        const double* cell, int receivers, double skin, double* out_energy_ev, double* out_forces,
                        double* out_stress, long long* out_tiles);

// The tile planner of the tiled mode, on the host: no handle and no GPU. loup_tile_plan divides `n_atoms` atoms at
// `positions` [n_atoms, 3] in `cell` (rows are the lattice vectors) into tiles of at most `receivers` local atoms
// and keeps the plan for the calling thread; loup_tile_plan_copy copies it out (an output that is NULL is left
// out). `degree` with `edges` > 0 also caps a tile's edges (degree: each atom's edge count); NULL and 0: no edge
// cap. `reach` > 0 (cutoff plus skin, Angstrom) lists each tile's ghost candidates: every image of an atom that
// can lie within `reach` of one of the tile's locals. `shape`: the blocks per cell axis, or NULL for the planner's
// choice. Outputs: local_ptr and ghost_ptr [n_tiles + 1], local [n_atoms] (every atom once, tile by tile),
// local_shift [n_atoms, 3] and ghost_shift [n_ghosts, 3]: the whole cell vectors to add to an atom's position for
// the place it has in its tile, ghost [n_ghosts] the candidates' atoms. Both return 0, or -1 with the reason in
// loup_tile_plan_error().
int loup_tile_plan(const double* positions, long long n_atoms, const double* cell, int receivers, long long edges,
                   const int* degree, double reach, const int* shape, long long* n_tiles, long long* n_ghosts,
                   int* grid);
int loup_tile_plan_copy(long long* local_ptr, int* local, int* local_shift, long long* ghost_ptr, int* ghost,
                        int* ghost_shift);
const char* loup_tile_plan_error(void);
// The wavefront's plan and schedule (plan task S5-T08; testing and the front end, no handle). loup_tile_plan_wavefront
// is loup_tile_plan without an edge cap and with `boundary_skin` (Angstrom; 0: none): the first and last layer of
// blocks along the first cell axis split into the atoms within boundary_skin of the cell's faces and the rest.
// loup_tile_dependencies, for the thread's plan: needs_ptr [n_tiles + 1] and needs [*n_needs] (each tile's tiles
// that own one of its locals or candidates, ascending), ready [n_tiles] (the last tile that holds one of a tile's
// locals); NULL outputs are left out, so a first call with needs NULL gives the size. loup_wavefront_schedule: the
// 3 * tiles steps (out_sweep 1, 2 or 3; out_tile) of the schedule, `group` sweep-2 tiles at a time, and in *out_peak
// the most `counts` between a tile's sweeps 1 and 3. All return 0, or -1 with the reason in loup_tile_plan_error().
int loup_tile_plan_wavefront(const double* positions, long long n_atoms, const double* cell, int receivers,
                             double reach, double boundary_skin, const int* shape, long long* n_tiles,
                             long long* n_ghosts, int* grid);
int loup_tile_dependencies(long long* needs_ptr, long long* needs, long long* ready, long long* n_needs);
int loup_wavefront_schedule(long long tiles, const long long* needs_ptr, const long long* needs,
                            const long long* ready, const long long* counts, int group, int* out_sweep,
                            long long* out_tile, long long* out_peak);

// Testing only; not part of the interface a caller may rely on. A handle as an open domain (the unit a tiled run
// evaluates): the first n_local atoms are local and receive, the n_ghost atoms after them only send. Bundles of the
// generic path without long range. loup_debug_evaluate_domain runs the per-layer sweeps on it for a domain whose
// ghosts are images of its own locals: ghost_of[g] names the local atom ghost g is an image of, positions holds
// locals then ghosts, and cell is a box around them all with room for cutoff plus skin on every side. Energy and
// forces [n_local, 3] are those of the locals with the ghosts' share folded back; stress is the virial over the
// box's volume. With n_ghost = 0 the cell is periodic as usual and the sweeps run on the whole system.
int loup_debug_set_domain(LoupHandle* h, int n_local, int n_ghost, const int* atomic_numbers, double skin);
int loup_debug_evaluate_domain(LoupHandle* h, const double* positions, const double* cell, const int* ghost_of,
                               double* out_energy_ev, double* out_forces, double* out_stress);
// Testing only (plan task S5-T02): the neighbour list of cutoff plus skin the handle builds for `positions` and
// `cell`, on a periodic system or an open domain whose ghosts are a tile's ghost candidates. *out_count is the edge
// count; with capacity >= it, receivers (local atoms), senders (n_local + g for ghost g) and shifts [count, 3]
// (Cartesian, edge vector = receiver - sender + shift) are written in the caller's atom order, each optional.
// out_ghost_used [n_ghost] (optional) marks the ghosts that send along some edge; a tile drops the others.
int loup_debug_domain_edges(LoupHandle* h, const double* positions, const double* cell, long long capacity,
                            int* out_receivers, int* out_senders, double* out_shifts, long long* out_count,
                            unsigned char* out_ghost_used);
// The earlier name of loup_evaluate_tiled (plan task S5-T03), kept for callers of 0.0.1: the same call.
int loup_debug_evaluate_tiled(LoupHandle* h, int n_atoms, const int* atomic_numbers, const double* positions,
                              const double* cell, int receivers, double skin, double* out_energy_ev, double* out_forces,
                              double* out_stress, long long* out_tiles);

// Tiled MD on the device (PLAN.md O31): the trajectory of a system in the tiled mode, with positions, velocities and
// forces kept on the GPU between steps, so a step costs one tiled force call and a few small kernels. The barostats
// move the cell (LAMMPS_TILED_PLAN.md LT6 (a)): each step's tiled call then carries the stress, and the tile lists
// stay across the cell's changes as loup_evaluate_tiled says.
// loup_tiled_set_state: the system (n_atoms, atomic_numbers, masses in amu, positions and velocities in A and
// A/(ASE time unit) [n_atoms, 3], cell rows), optional `fixed` flags [n_atoms] (velocities of fixed atoms are
// zeroed), the receiver cap (pass the plan's; 0 as loup_evaluate_tiled takes it) and skin, the noise step counter
// of the stochastic integrators, and optionally the integrator state block [64] with its kind (a restart; NULL: zero).
// With positions and velocities both NULL on a handle that holds n_atoms atoms, the state stays and only the step
// count of the thermo rows starts anew.
// loup_tiled_run: n_steps steps of `integrator`: any kind of loup_run, with its rules (fix_com refused with fixed
// atoms; the barostats LOUP_BERENDSEN_NPT, LOUP_BAOAB_NPT and LOUP_MTK_NPT not with fixed atoms, and their
// variables carried in the integrator state block as loup_run carries them). The barostats stop the run with an
// error when the cell's volume leaves [V0 / 20, 20 V0]; V0 is the volume of loup_tiled_set_state's cell, or
// loup_set_reference_volume's after it. With integrator->thermo_every > 0 and `rows`, up to max_rows thermo rows are
// written and *out_rows counts them (pressure and volume of the cell under a barostat, else pressure 0).
// out_stats: step_ms the wall time per step, rebuilds the tiled calls that built their lists; dangerous_builds,
// tune_ms and pipelined_steps are 0. *out_max_step_a (optional): the longest distance an atom moved in one step of the
// call, in A. A tiled call that fails in a cell other than the one its cap was planned or set for plans once more.
// loup_tiled_get_state: any of positions, velocities, forces [n_atoms, 3], the energy of the last force call (eV),
// the noise step counter and the integrator state block [64] with its kind (-1: none); NULL skips an output.
// loup_tiled_get_cell: the tiled MD's cell [3, 3] (rows), as a barostat left it.
int loup_tiled_set_state(LoupHandle* h, int n_atoms, const int* atomic_numbers, const double* masses_amu,
                         const double* positions, const double* velocities, const double* cell,
                         const unsigned char* fixed, int receivers, double skin, unsigned long long noise_step,
                         const double* int_state, int int_state_kind);
int loup_tiled_run(LoupHandle* h, const LoupIntegrator* integrator, int n_steps, LoupMDStats* out_stats,
                   LoupThermoRow* rows, int max_rows, int* out_rows, double* out_max_step_a);
int loup_tiled_get_state(LoupHandle* h, double* positions, double* velocities, double* forces, double* out_energy_ev,
                         unsigned long long* noise_step, double* int_state, int* int_state_kind);
int loup_tiled_get_cell(LoupHandle* h, double* out_cell);
// Testing only: the noise CSVR draws in steps first_step .. first_step + n_steps - 1 (counted by the handle's step
// counter, which loup_set_system zeroes) with `seed` for `ndof` degrees of freedom: the standard normal R1 and the
// chi-square variate of ndof - 1 degrees of freedom of each step.
int loup_debug_csvr_noise(LoupHandle* h, unsigned long long seed, unsigned long long first_step, int n_steps,
                          int ndof, double* out_normal, double* out_chi2);

// Timing breakdown across components for diagnostics (averages over `n_calls` force evaluations).
int loup_profile_force(LoupHandle* h, int warmup, int n_calls, double* out_total_us);

// ---- Dispersion: the real-space two-body D3 term on its own (S6-D04; src/dispersion/d3_pair.cu) --------------
// Settings in bohr and hartree units as the literature gives them. damping: 0 BJ, 1 zero, 2 modified BJ, 3 modified
// zero. smoothing_bohr: 0, or the width of a quintic switch that takes each pair energy to 0 at the pair cutoff
// (and each side of a three-body triangle to 0 at the three-body cutoff). three_body: nonzero adds the
// Axilrod-Teller-Muto term (S6-D08) with s9 = 1 over triangles whose sides lie within three_body_cutoff_bohr.
// long_range 2: the split sum (S6-D06): the pair term minus its smooth long-range part to pair_cutoff_bohr, the rest
// as a sum over reciprocal space of the exact C6 / C8 channels (an Ewald sum for 1/r^6 and 1/r^8).
typedef struct {
    int damping;
    double s6, s8, a1, a2, rs6, rs8, alpha, beta;
    double pair_cutoff_bohr, cn_cutoff_bohr, smoothing_bohr;
    int three_body;
    double three_body_cutoff_bohr;
    int long_range;             // 0 the plain sum, 2 the split sum (S6-D06; 1 tail and 3 mesh not built)
    double mesh_spacing_A;      // 0: the method's default
} LoupD3Settings;
// The reference tables, index = atomic number 0..94 (loupmd/data/d3_tables.npz): nref [95], cnref [95, 5], rcov
// [95] (bohr, 4/3 included), r2r4 [95], c6ref [95, 95, 5, 5] (hartree bohr^6; < 0: no reference), r0ab [95, 95] (bohr).
typedef struct {
    const int* nref;
    const double *cnref, *rcov, *r2r4, *c6ref, *r0ab;
} LoupD3Tables;
// One evaluation of a periodic cell on the GPU, captured in a CUDA graph and replayed. positions [n, 3] and cell [9]
// (rows) in A. Outputs: energy eV; forces [n, 3] eV/A, virial [6] (xx xy xz yy yz zz, dE/d strain, eV; stress =
// virial / V) and per-atom energies [n] eV, each optional (NULL: not computed; neither forces nor virial: the
// energy-only path). repeat > 0 with out_ms: the mean time of that many further replays. 0 on success; else
// loup_d3_last_error() says why.
int loup_d3_evaluate(const LoupD3Settings* settings, const LoupD3Tables* tables, int n_atoms,
                     const int* atomic_numbers, const double* positions, const double* cell, int repeat,
                     double* out_energy_ev, double* out_forces, double* out_virial, double* out_atom_energies,
                     double* out_ms);
const char* loup_d3_last_error(void);
// The same term inside a handle's force passes (energy, forces, stress, per-atom energies, the MD step, the
// variable-cell step): added to every whole-system evaluation from the next positions on. settings NULL removes it.
// Needs a periodic cell; refused for open domains and the tiled call (PLAN.md S6-D09). The tables are copied.
int loup_set_dispersion(LoupHandle* h, const LoupD3Settings* settings, const LoupD3Tables* tables);
// A D3 term kept across calls, outside a handle (the tiled execution, S6-D09): made for the atomic numbers and the
// cell (the cell may change later; the grid's bin counts are fixed here), then computed at each call as
// loup_d3_evaluate does but without a graph (outputs as there; NULL: not computed). NULL / nonzero on failure, with
// loup_d3_last_error() saying why. loup_d3_device_bytes: what the term holds on the GPU.
typedef struct LoupD3 LoupD3;
LoupD3* loup_d3_create(const LoupD3Settings* settings, const LoupD3Tables* tables, int n_atoms,
                       const int* atomic_numbers, const double* cell);
int loup_d3_compute(LoupD3* term, const double* positions, const double* cell, double* out_energy_ev,
                    double* out_forces, double* out_virial, double* out_atom_energies);
size_t loup_d3_device_bytes(const LoupD3* term);
void loup_d3_destroy(LoupD3* term);

// Device-resident evaluation, for host codes that keep their atoms on the GPU and integrate themselves (the LAMMPS
// Kokkos pair style `loupmd/kk`, lammps/ in this repository). All pointers in LoupDeviceIO are device pointers on the
// engine's CUDA device.
#define LOUP_IO_ENERGY 1       /* out_energy_ev is filled (the call then waits for the force pass) */
#define LOUP_IO_VIRIAL 2       /* out_virial is filled (the call then waits for the force pass) */
#define LOUP_IO_ATOM_ENERGY 4  /* reserved: per-atom energies are not available yet (the call is refused) */
typedef struct {
    int n_rows;               // rows of the caller's arrays; must equal n_atoms of loup_set_system
    // Component c (0 = x, 1 = y, 2 = z) of row r is at base[r * row_stride + c * comp_stride], in doubles: a row-major
    // [n][3] array has strides (3, 1), a column-major [n_alloc][3] array (Kokkos::LayoutLeft) (1, n_alloc).
    const double* positions;  // A. Rows may be unwrapped (any periodic image); they must be continuous from call to
                              // call, since the skin check compares them with the positions of the last list build.
    long long pos_row_stride, pos_comp_stride;
    const int* ids;           // [n_rows]: the engine atom (index in loup_set_system's order, 0 .. n_atoms-1) each row
                              // holds; every atom exactly once. NULL: row r is atom r.
    double* forces;           // eV/A: the forces are ADDED to the rows (NULL: no forces written)
    long long f_row_stride, f_comp_stride;
    double* atom_energy;      // reserved, must be NULL
    int flags;                // LOUP_IO_* bits
} LoupDeviceIO;

// Queues one force evaluation behind the work already on `stream` (a cudaStream_t of the same device; NULL is the
// default stream) and makes `stream` wait for the forces, so work the caller queues on it afterwards sees them. `cell`
// is a host [3, 3] row-major matrix in A, as for loup_evaluate; a changed cell rebuilds the neighbour list.
// The call returns as soon as the step is queued and its neighbour-list decision is known; it waits for the result
// only when energy or virial is asked for. out_energy_ev (with LOUP_IO_ENERGY) is the potential energy in eV.
// out_virial (with LOUP_IO_VIRIAL) is the virial tensor -dE/d(strain) in eV, as [xx, yy, zz, xy, xz, yz] (the layout
// and sign of LAMMPS's `virial`; the stress of loup_evaluate is -virial / volume).
// loup_evaluate, loup_set_state and the run calls may be mixed with it on one handle; MD velocities are untouched.
// A whole system only (not an open domain, not the tiled call); a dispersion term set on the handle is included.
// The per-atom energies of loup_evaluate2 are not available here.
int loup_compute_device(LoupHandle* h, const LoupDeviceIO* io, const double* cell, void* stream,
                        double* out_energy_ev, double* out_virial);

// Environment:
//   LOUP_CACHE_DIR  directory for the per-GPU GEMM plan cache (default $HOME/.cache/loupmd). Files are keyed by GPU
//                   name, compute capability, cuBLASLt version and a hash of this library; plans whose winner leads
//                   the runner-up by less than 3% are not persisted.
//   LOUP_RETUNE     if set, ignore the plan cache and re-time every GEMM shape (results are still saved).
//   LOUP_EVAL_ARM=0|1  loup_set_evaluate_ahead for every handle: 0 keeps it off, 1 switches it on (testing; see the
//                   warning at loup_set_evaluate_ahead).
//   LOUP_DEBUG_EVAL_TIMES=1  when a handle is destroyed, print where its loup_evaluate calls spent their time: to
//                   the launch, to the guard's publication, to the results, to the return, and between calls.
//   LOUP_REORDER=0|1  the spatial atom reorder off or on (testing).
//   LOUP_CONV_FWD_VARIANT, LOUP_CONV_TUNE  force or untune the conv forward variants (testing; tools/dev/test_gate.py).
//   LOUP_JIT=0|1    the run-time compiler (JIT_DESIGN.md): 0 off (built-in kernels only; a bundle whose product the
//                   library lacks is then refused), unset the kernels the library has no instance for (conv widths,
//                   products), 1 also layer 0's kernels. LOUP_NVRTC names the NVRTC library, LOUP_DEBUG_JIT=1 prints
//                   what is compiled or read from <LOUP_CACHE_DIR>/jit/, LOUP_JIT_PRODUCTS=1 compiles every product
//                   from the bundle (testing).
//   LOUP_ROW_SORT=global  sort every neighbour row in global scratch, the path of rows over 4,096 edges (testing).
//   LOUP_MD_REBUILD=host|fallback  MD neighbour rebuilds host-driven, or counted on the GPU and always finished on the
//                   host, instead of inside the step graph (testing).
//   LOUP_POLAR_FOLD=0|1  POLAR long range without (0) the load-time dot^T weight fold, testing the path other GPUs take,
//                   or with it (1) on any GPU (sm_120 and cc 8.0 fold by default).
//   LOUP_POLAR_ZBLK=0  POLAR long range: run the GEMMs of weight blocks certified exactly zero at load (POLAR-1-L's
//                   l = 2 SCF, electron-energy and source blocks), which are skipped by default (testing).
//   LOUP_POLAR_HFOLD=0|1|2|3  POLAR models: the degrees (bit l - 1 = degree l) whose hidden chain is folded at load into
//                   the long-range mixer and source and the next layers' weights; 0 forms every layer's output, the
//                   path other GPUs take (testing; sm_120 folds degrees 1 and 2 by default).
//   LOUP_CHAIN_FOLD=0|1  generic models (OMOL-0, MH-1, the OMAT-0 / MP-0 / MPtrj / OFF families on the generic path):
//                   0 skips the load-time skip-chain fold (the path other GPUs take), 1 folds on any GPU (testing;
//                   sm_120 and cc 8.0 fold by default).
//   LOUP_SPECIES_TABLES=0|1  generic models (OMOL-0, MH-1): 0 keeps layer 0's species-only GEMMs instead of per-species
//                   tables, 1 builds the tables on any GPU (testing; sm_120 and cc 8.0 build them by default).
//   LOUP_CONV_TUNE=0|1  generic models: 0 keeps the default conv forward variant (no per-system timing at the first
//                   rebuild, or after 50 force passes without one); 1 times the variants on any GPU (testing; sm_120
//                   times them by default).
//   LOUP_CONV_FWD_VARIANT=0|1|2  force a generic conv forward variant (testing; see tools/dev/test_gate.py).
//   LOUP_CONV_PRUNE=0  generic models: keep every conv path of a layer whose l >= 1 projections are exactly zero
//                   (MP-0 medium's second interaction), which by default runs only its output-degree-0 paths and a
//                   scalar-only product (testing).
//   LOUP_LIN_COMPACT=0  generic models: the dense projections and product kernels of kind-1 layers (MPtrj-2022.9, MP-0
//                   medium's layer 0) instead of their live channels, certified from exact zeros at load (testing).
//   LOUP_SENDER_BWD=0  generic models: the receiver-owned backward of a pruned conv layer (MP-0 medium's second
//                   interaction) instead of the sender-owned one (testing).
//   LOUP_NO_HYBRID=1  no tensor-core GEMM cubin (float32 SIMT GEMMs only).
//   LOUP_HYBRID_CUBIN=path  load this GEMM cubin instead of the default (cubins/gemm_tc_hyb_sm80.cubin, LoupMD's own
//                   cubins/src/gemm_tc.cu build with more tiles and beta support, on cc 8.0; FastMACE's
//                   cubins/tf32x3_hyb_sm<arch>.cubin elsewhere) (testing). GEMM plans are keyed by the cubin file.
//   LOUP_LR_HYBRID=1  load the GEMM cubin for long-range models too (testing; they run float32 SIMT GEMMs by default).
//   LOUP_OWN_EXT=0|1  force the own-SGEMM extensions (sgemm64 / sgemm32 candidates, N-fastest rasterisation; testing;
//                   on by default for sm_120, and for cc 8.0 when no GEMM cubin is loaded, e.g. long-range models).
//   LOUP_NB_GROUPS=0|1  force the lane-group neighbour-list kernels (testing; on for sm_120 and compute capability 8.0
//                   by default).
//   LOUP_FORCE_TC=1  every GEMM the tensor-core cubin can take runs on it (testing the cubin's accuracy on every
//                   eligible shape; no GEMM plans are loaded or saved).
//   LOUP_GATE_FUSE=0, LOUP_GATE_FUSE_FWD=0  generic models with gated (kind 4) layers (MH-1, OMOL-0, POLAR-1): keep the
//                   gate kernels instead of the gate backward in the W_2^T GEMMs' epilogue / layer 0's gated store in
//                   its projections' epilogue (testing; both run where a GEMM's plan is the own N-fastest sgemm128,
//                   i.e. on sm_120).
//   LOUP_DEBUG_SPLINE, LOUP_DEBUG_GEMM, LOUP_DEBUG_COMPACT  print the variant / GEMM tuning decisions and the compacted
//                   generic layers to stderr.
//   LOUP_DEBUG_ERRORS  print every failure's message (loup_last_error) to stderr as well.
//   LOUP_DEBUG_GRAPHS  print a line to stderr for every capture of an MD step graph and for every force pass a run
//                      call makes before its first step (tests/test_md_graph_reuse.py).
//   LOUP_DEBUG_ALLOC_FREE=<MiB>  the allocations of a system's buffers count at most this much device memory as free
//                   and are refused above it, as when the card is full (tests/gpu/test_engine.py). Without it, a
//                   request of 4 MiB or more beyond the card's free memory (NVML's figure) fails with "out of
//                   memory", also under WSL 2, where the driver would page it out to system memory instead.

#ifdef __cplusplus
}
#endif
