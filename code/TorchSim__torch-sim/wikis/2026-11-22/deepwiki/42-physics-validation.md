# Physics Validation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [tests/test_integrators.py](tests/test_integrators.py)

</details>



## Purpose and Scope

This document describes the physics-based validation infrastructure used to verify the correctness of molecular dynamics integrators and thermostats in torch-sim. Physics validation ensures that integrators correctly implement the fundamental laws of statistical mechanics and thermodynamics, including energy conservation, temperature control, and pressure maintenance.

For information about the general testing framework, fixtures, and test organization, see [Testing Framework](#10.1). For information about the integrators themselves, see sections [NVE Ensemble](#4.2), [NVT Ensemble](#4.3), and [NPT Ensemble](#4.4).

## Overview

Physics validation in torch-sim employs a comprehensive strategy to verify that molecular dynamics simulations obey fundamental physical principles:

- **Energy Conservation**: Verifying that NVE integrators preserve total energy
- **Temperature Control**: Validating that NVT thermostats maintain target temperatures
- **Pressure Control**: Ensuring NPT barostats maintain target pressures
- **Invariant Conservation**: Checking that extended system variables remain stable
- **Reproducibility**: Confirming deterministic behavior with seeded random number generation
- **Batching Consistency**: Verifying identical results between single and batched simulations

```mermaid
graph TB
    subgraph "Physics Validation Tests"
        NVE["test_nve<br/>Energy Conservation"]
        NVT_L["test_nvt_langevin<br/>Temperature Control"]
        NVT_NH["test_nvt_nose_hoover<br/>Temperature + Invariant"]
        NVT_VR["test_nvt_vrescale<br/>Temperature Control"]
        NPT_L["test_npt_langevin<br/>Pressure + Temperature"]
        NPT_NH["test_npt_nose_hoover<br/>Pressure + Temperature + Invariant"]
        NPT_CR["test_npt_crescale<br/>Pressure Control"]
    end
    
    subgraph "Validation Metrics"
        ENERGY["Energy Conservation<br/>torch.allclose(E_t, E_0)"]
        TEMP["Temperature Maintenance<br/>mean(kT) ≈ target_kT"]
        PRESS["Pressure Maintenance<br/>mean(P) ≈ target_P"]
        INVAR["Invariant Stability<br/>std(H) / mean(H) < threshold"]
    end
    
    subgraph "Supporting Tests"
        REPRO["test_nvt_langevin_reproducibility<br/>test_npt_langevin_reproducibility"]
        BATCH["test_compare_single_vs_batched_integrators"]
        MULTI["test_nvt_langevin_multi_kt<br/>test_npt_nose_hoover_multi_kt"]
        MOMENTA["test_initialize_momenta_basic<br/>test_initialize_momenta_single_atoms"]
    end
    
    NVE --> ENERGY
    NVT_L --> TEMP
    NVT_NH --> TEMP
    NVT_NH --> INVAR
    NVT_VR --> TEMP
    NPT_L --> TEMP
    NPT_L --> PRESS
    NPT_NH --> TEMP
    NPT_NH --> PRESS
    NPT_NH --> INVAR
    NPT_CR --> TEMP
    NPT_CR --> PRESS
    
    REPRO -.-> NVT_L
    REPRO -.-> NPT_L
    BATCH -.-> NVE
    MULTI -.-> NVT_L
    MULTI -.-> NPT_NH
    MOMENTA -.-> NVT_L
```

**Sources:** [tests/test_integrators.py:1-1118]()

## Energy Conservation Testing

Energy conservation is the fundamental test for microcanonical (NVE) ensemble simulations. The `test_nve` function verifies that the total energy (kinetic + potential) remains constant throughout the simulation to within numerical precision.

### NVE Energy Conservation Test

The NVE test initializes a system with random velocities and verifies that energy is conserved over 100 integration steps:

```mermaid
graph LR
    INIT["ts.nve_init<br/>Initialize momenta<br/>Compute forces"]
    LOOP["Loop n_steps times"]
    STEP["ts.nve_step<br/>Velocity Verlet"]
    COLLECT["Collect energies"]
    VALIDATE["torch.allclose<br/>E_i ≈ E_0<br/>atol=1e-4"]
    
    INIT --> LOOP
    LOOP --> STEP
    STEP --> COLLECT
    COLLECT --> LOOP
    LOOP --> VALIDATE
```

The implementation uses the velocity Verlet algorithm with small timesteps (0.001 in metal units) to ensure numerical stability. Energy conservation is checked independently for each system in batched simulations:

| Test Component | Implementation | Validation Criteria |
|---------------|----------------|---------------------|
| Initialization | `ts.nve_init(state, model, kT)` | Initialize momenta from temperature |
| Integration | `ts.nve_step(state, model, dt)` | Velocity Verlet algorithm |
| Energy Collection | `state.energy` per step | Store energy for each system |
| Validation | `torch.allclose(energies[:, i], energies[0, i])` | Energy constant within 1e-4 tolerance |

**Sources:** [tests/test_integrators.py:929-950]()

### Batching Consistency for NVE

The `test_compare_single_vs_batched_integrators` function verifies that running a single system produces identical results to extracting that system from a batched simulation. This is critical for ensuring that batching optimizations do not introduce numerical artifacts:

```mermaid
graph TB
    SINGLE["Single System<br/>ts.nve_init(state)<br/>ts.nve_step(...)"]
    BATCHED["Batched System<br/>ts.concatenate_states([state, state])<br/>ts.nve_init(batched)<br/>ts.nve_step(...)"]
    EXTRACT["Extract Components<br/>batched[0], batched[1]"]
    COMPARE["torch.testing.assert_close<br/>positions, momenta, forces<br/>masses, cell, energy"]
    
    SINGLE --> COMPARE
    BATCHED --> EXTRACT
    EXTRACT --> COMPARE
```

The test runs 100 steps starting from zero momentum and verifies that all state components match exactly between single and batched execution paths. This test uses both orthorhombic and triclinic cell geometries to verify proper periodic boundary condition handling.

**Sources:** [tests/test_integrators.py:952-1006]()

## Temperature Control Validation

Temperature control is validated for all NVT ensemble integrators by monitoring the instantaneous temperature calculated from kinetic energy and comparing it to the target temperature over the course of a simulation.

### Temperature Calculation

Temperature is computed using the `ts.calc_kT` function, which converts kinetic energy to temperature:

```mermaid
graph LR
    KE["Kinetic Energy<br/>KE = ½mv²<br/>= p²/(2m)"]
    KT["ts.calc_kT<br/>kT from momenta<br/>per system"]
    TEMP["Temperature<br/>T = kT / k_B"]
    
    KE --> KT
    KT --> TEMP
```

### NVT Langevin Thermostat

The Langevin thermostat test validates stochastic temperature control using friction and random forces:

| Test Parameter | Value | Purpose |
|---------------|-------|---------|
| Steps | 100-200 | Equilibration time |
| Timestep | 0.001 (metal units) | Numerical stability |
| Target Temperature | 300 K or multi-kT | Test temperature control |
| Validation Tolerance | ±100-150 K | Allow thermal fluctuations |

The test collects instantaneous temperatures at each step and validates that the mean temperature matches the target:

```mermaid
graph TB
    INIT["ts.nvt_langevin_init<br/>state.rng = 42<br/>Initialize momenta"]
    STEP["ts.nvt_langevin_step<br/>BAOAB splitting<br/>dt, kT parameters"]
    CALC["ts.calc_kT<br/>Compute instantaneous T"]
    COLLECT["temperatures.append(temp)"]
    VALIDATE["mean_temps ≈ target_kT<br/>Allow thermal fluctuations"]
    
    INIT --> STEP
    STEP --> CALC
    CALC --> COLLECT
    COLLECT --> STEP
    STEP --> VALIDATE
```

**Sources:** [tests/test_integrators.py:216-267](), [tests/test_integrators.py:269-305]()

### NVT Nose-Hoover Thermostat

The Nose-Hoover thermostat is a deterministic extended system method that requires validation of both temperature control and invariant conservation:

```mermaid
graph TB
    INIT["ts.nvt_nose_hoover_init<br/>Initialize thermostat chain<br/>NVTNoseHooverState"]
    STEP["ts.nvt_nose_hoover_step<br/>Evolve extended system"]
    TEMP_CHECK["Temperature Check<br/>mean(T) ≈ target_T<br/>tolerance ±100 K"]
    INVAR_CHECK["Invariant Check<br/>ts.nvt_nose_hoover_invariant<br/>std(H)/mean(H) < 0.1"]
    
    INIT --> STEP
    STEP --> TEMP_CHECK
    STEP --> INVAR_CHECK
    STEP --> STEP
```

The Nose-Hoover invariant is computed using `ts.nvt_nose_hoover_invariant(state, kT)`, which returns the conserved quantity for the extended system. The test verifies that this invariant has less than 10% relative variation, indicating proper energy exchange between the physical system and thermostat.

**Sources:** [tests/test_integrators.py:307-382]()

### NVT Velocity Rescaling

The velocity rescaling thermostat test follows a similar pattern but uses stochastic rescaling of velocities:

```mermaid
graph LR
    INIT["ts.nvt_vrescale_init"]
    STEP["ts.nvt_vrescale_step<br/>Stochastic rescaling"]
    VALIDATE["Temperature validation<br/>Same criteria as Langevin"]
    
    INIT --> STEP
    STEP --> VALIDATE
```

**Sources:** [tests/test_integrators.py:491-542]()

### Multi-Temperature Testing

Multi-temperature tests verify that different systems in a batch can maintain different target temperatures simultaneously:

```mermaid
graph TB
    SETUP["Setup Multiple Systems<br/>kT = [300, 10000] K<br/>ar_double_sim_state"]
    INIT["Initialize with per-system kT<br/>ts.nvt_langevin_init(kT=tensor)"]
    RUN["Run simulation<br/>Each system evolves at its target T"]
    CHECK["Validate per-system<br/>mean_temps[i] ≈ kT[i]<br/>rtol=0.5"]
    
    SETUP --> INIT
    INIT --> RUN
    RUN --> CHECK
```

This capability is essential for high-throughput screening where multiple chemical compositions or thermodynamic states are simulated simultaneously.

**Sources:** [tests/test_integrators.py:269-305](), [tests/test_integrators.py:438-489]()

## Pressure Control Validation

Pressure control validation ensures that NPT ensemble integrators maintain the target pressure while also controlling temperature. This requires monitoring the stress tensor and validating pressure equilibration.

### NPT Langevin Barostat

The NPT Langevin test validates stochastic pressure control combined with temperature control:

```mermaid
graph TB
    INIT["ts.npt_langevin_init<br/>NPTLangevinState<br/>cell dynamics variables"]
    PARAMS["Parameters<br/>dt, kT, external_pressure<br/>alpha, cell_alpha, b_tau"]
    STEP["ts.npt_langevin_step<br/>Update cell + positions<br/>Apply barostat"]
    TEMP_VAL["Temperature Validation<br/>mean(T) ≈ kT<br/>±150 K tolerance"]
    ENERGY_VAL["Energy Stability<br/>std(E) < 1.0"]
    
    INIT --> PARAMS
    PARAMS --> STEP
    STEP --> TEMP_VAL
    STEP --> ENERGY_VAL
    STEP --> STEP
```

The NPT Langevin test uses several coupling parameters:
- `alpha`: Friction coefficient for atomic motion
- `cell_alpha`: Friction coefficient for cell dynamics
- `b_tau`: Barostat coupling timescale

The test validates that both temperature and energy remain stable, acknowledging that NPT simulations allow energy fluctuations due to volume changes.

**Sources:** [tests/test_integrators.py:83-156](), [tests/test_integrators.py:158-214]()

### NPT Nose-Hoover Barostat

The NPT Nose-Hoover integrator is a deterministic extended system method that controls both temperature and pressure:

```mermaid
graph TB
    INIT["ts.npt_nose_hoover_init<br/>NPTNoseHooverState<br/>Thermostat + barostat chains"]
    STEP["ts.npt_nose_hoover_step<br/>Evolve extended system<br/>external_pressure parameter"]
    TEMP["Temperature Check<br/>mean(T) ≈ target_T<br/>±100 K tolerance"]
    ENERGY["Energy Fluctuations<br/>std(E) < 2.0<br/>Higher than NVT due to PV work"]
    INVAR["Invariant Check<br/>ts.npt_nose_hoover_invariant<br/>std(H)/mean(H) < 0.15"]
    
    INIT --> STEP
    STEP --> TEMP
    STEP --> ENERGY
    STEP --> INVAR
```

The NPT Nose-Hoover invariant includes contributions from the barostat variables and is computed using `ts.npt_nose_hoover_invariant(state, kT, external_pressure)`. The test allows for slightly higher invariant variation (15%) compared to NVT (10%) due to the additional barostat degrees of freedom.

**Sources:** [tests/test_integrators.py:690-771](), [tests/test_integrators.py:865-927]()

### NPT C-Rescale Methods

The C-Rescale barostats provide both isotropic and anisotropic pressure control through stochastic cell rescaling:

| Method | Function | Cell Update Mode |
|--------|----------|------------------|
| Isotropic | `ts.npt_crescale_isotropic_step` | Uniform scaling in all directions |
| Anisotropic | `ts.npt_crescale_anisotropic_step` | Independent scaling per axis |

Both methods share the same initialization function `ts.npt_crescale_init` and use the same validation criteria as NPT Langevin.

**Sources:** [tests/test_integrators.py:544-615](), [tests/test_integrators.py:617-688]()

### Cell Force Scaling

A critical validation test ensures that cell forces scale correctly with the number of atoms per system. The `test_compute_cell_force_atoms_per_system` verifies that systems with different numbers of atoms experience proportional cell forces:

```mermaid
graph LR
    SETUP["Create two systems<br/>8 atoms vs 64 atoms"]
    COMPUTE["_compute_cell_force<br/>From stress tensor"]
    RATIO["Compute force ratio<br/>F_64 / F_8"]
    VALIDATE["Assert ratio ≈ 8.0<br/>within 10% tolerance"]
    
    SETUP --> COMPUTE
    COMPUTE --> RATIO
    RATIO --> VALIDATE
```

This test catches a common error where cell forces are not properly normalized by system size, which would cause incorrect pressure control in batched simulations.

**Sources:** [tests/test_integrators.py:1008-1042]()

## Thermodynamic Invariants

For extended system methods (Nose-Hoover chains), the conservation of thermodynamic invariants provides a rigorous test of implementation correctness. The invariant represents the total conserved quantity of the extended system.

### Invariant Functions

| Ensemble | Function | Invariant Components |
|----------|----------|----------------------|
| NVT | `ts.nvt_nose_hoover_invariant(state, kT)` | H + KE_thermostat + PE_thermostat |
| NPT | `ts.npt_nose_hoover_invariant(state, kT, P_ext)` | H + KE_thermostat + PE_thermostat + KE_barostat + PE_barostat |

### Invariant Validation Criteria

```mermaid
graph TB
    COLLECT["Collect invariant at each step<br/>invariants.append(invariant)"]
    STACK["Stack into tensor<br/>invariants_tensor = torch.stack(invariants)"]
    PER_SYS["For each system trajectory<br/>invariant_traj = invariants_tensor[:, sys_idx]"]
    CALC_STD["Calculate statistics<br/>std = invariant_traj.std()<br/>mean = invariant_traj.mean()"]
    CHECK["Validate stability<br/>std / mean < threshold"]
    
    COLLECT --> STACK
    STACK --> PER_SYS
    PER_SYS --> CALC_STD
    CALC_STD --> CHECK
```

The acceptance criteria for invariant conservation are:
- **NVT**: Relative variation < 10% (`std(H) / mean(H) < 0.1`)
- **NPT**: Relative variation < 15% (`std(H) / mean(H) < 0.15`)

NPT ensembles allow slightly higher variation due to the additional complexity of the barostat dynamics.

**Sources:** [tests/test_integrators.py:366-373](), [tests/test_integrators.py:755-761]()

## Reproducibility Testing

Reproducibility tests ensure that molecular dynamics simulations produce identical results when initialized with the same random seed. This is essential for debugging and for verifying that GPU operations are deterministic.

### Reproducibility Test Pattern

```mermaid
graph TB
    RUN1["Run 1: seed=123<br/>state.rng = 123<br/>ts.nvt_langevin_init<br/>Run n_steps"]
    RUN2["Run 2: seed=123<br/>state.rng = 123<br/>Same initialization<br/>Same n_steps"]
    RUN3["Run 3: seed=456<br/>Different seed"]
    
    COMPARE_SAME["torch.testing.assert_close<br/>positions, momenta<br/>Run 1 vs Run 2"]
    COMPARE_DIFF["assert not torch.allclose<br/>Run 1 vs Run 3"]
    
    RUN1 --> COMPARE_SAME
    RUN2 --> COMPARE_SAME
    RUN1 --> COMPARE_DIFF
    RUN3 --> COMPARE_DIFF
```

### Tested Integrators

| Integrator | Test Function | Validated State Components |
|------------|---------------|----------------------------|
| NVT Langevin | `test_nvt_langevin_reproducibility` | positions, momenta |
| NPT Langevin | `test_npt_langevin_reproducibility` | positions, momenta, cell |

The reproducibility tests verify:
1. **Same seed → identical trajectories**: Two runs with seed=123 produce bit-exact results
2. **Different seeds → divergent trajectories**: Runs with different seeds produce different results

NPT tests additionally verify cell reproducibility since the simulation box evolves under pressure control.

**Sources:** [tests/test_integrators.py:1044-1069](), [tests/test_integrators.py:1071-1118]()

## Momenta Initialization Testing

Proper initialization of momenta is critical for all MD simulations. The momenta initialization tests verify that velocities are correctly sampled from the Maxwell-Boltzmann distribution and that center-of-mass motion is properly removed.

### Momenta Initialization Validation

```mermaid
graph TB
    GENERATE["initialize_momenta<br/>Sample from Normal(0, sqrt(m*kT))"]
    REMOVE_COM["Remove COM momentum<br/>Per system"]
    CHECK_SHAPE["Verify shapes<br/>momenta.shape == positions.shape"]
    CHECK_COM["Verify COM removal<br/>mean(p_sys) ≈ 0"]
    CHECK_SINGLE["Single-atom systems<br/>Preserve original momentum"]
    
    GENERATE --> REMOVE_COM
    REMOVE_COM --> CHECK_SHAPE
    REMOVE_COM --> CHECK_COM
    REMOVE_COM --> CHECK_SINGLE
```

### Test Coverage

| Test | Validation | Constraint |
|------|------------|------------|
| `test_initialize_momenta_basic` | COM momentum = 0 per system | `torch.allclose(com_momentum, 0, atol=1e-10)` |
| `test_initialize_momenta_single_atoms` | Single-atom systems unchanged | Raw momenta preserved |

The tests ensure that:
1. Each system has zero center-of-mass momentum
2. Single-atom systems retain their initial momentum (COM removal would be meaningless)
3. The momenta distribution is correctly scaled by mass and temperature

**Sources:** [tests/test_integrators.py:13-81]()

## Multi-System Validation

Multi-system validation ensures that batched simulations correctly handle multiple systems with different parameters (temperatures, pressures) and that systems remain independent throughout the simulation.

### System Independence Test Pattern

```mermaid
graph TB
    CONCAT["ts.concatenate_states<br/>Combine multiple systems<br/>system_idx assignment"]
    MULTI_KT["Different kT per system<br/>kT = tensor([300, 10000])"]
    SIMULATE["Run integrator<br/>Each system evolves independently"]
    VALIDATE_T["Validate per-system temperature<br/>mean_temps[i] ≈ kT[i]"]
    VALIDATE_POS["Validate system separation<br/>Systems remain distinct"]
    
    CONCAT --> MULTI_KT
    MULTI_KT --> SIMULATE
    SIMULATE --> VALIDATE_T
    SIMULATE --> VALIDATE_POS
```

### Equivalence Tests

The "multi-equivalent-to-single" tests verify that a multi-system simulation with identical parameters produces the same results as running individual simulations:

| Test Function | Verification |
|---------------|-------------|
| `test_nvt_nose_hoover_multi_equivalent_to_single` | Split systems → run separately → compare to batched |
| `test_npt_nose_hoover_multi_equivalent_to_single` | Same verification for NPT ensemble |

These tests:
1. Run each system individually with same seed
2. Concatenate systems and run batched with same seed
3. Verify final temperatures match exactly: `torch.allclose(final_temps_separate, final_temps_batched)`

**Sources:** [tests/test_integrators.py:384-436](), [tests/test_integrators.py:796-863]()

### System Separation Validation

All batched tests include a check that systems remain spatially separated:

```python
pos_diff = torch.norm(
    state.positions[:n_atoms].mean(0) - state.positions[n_atoms:].mean(0)
)
assert pos_diff > 0.0001  # Systems should remain separated
```

This verifies that the periodic boundary conditions and neighbor lists correctly respect system boundaries.

**Sources:** [tests/test_integrators.py:152-156](), [tests/test_integrators.py:262-266](), [tests/test_integrators.py:377-381]()

## Validation Metrics Summary

The following table summarizes the validation metrics used across different integrator tests:

| Property | Metric | Threshold | Ensembles |
|----------|--------|-----------|-----------|
| Energy Conservation | `torch.allclose(E_t, E_0)` | atol=1e-4 | NVE |
| Temperature | `abs(mean(T) - target_T)` | < 100-150 K | NVT, NPT |
| Multi-Temperature | `torch.allclose(mean(T), target_T)` | rtol=0.5 | NVT, NPT |
| Energy Stability | `std(E)` | < 1.0 (NVT), < 2.0 (NPT) | NVT, NPT |
| Invariant Conservation | `std(H) / mean(H)` | < 0.1 (NVT), < 0.15 (NPT) | Nose-Hoover |
| Reproducibility | `torch.testing.assert_close` | Bit-exact | All stochastic |
| System Separation | `norm(pos_diff)` | > 0.0001 | All batched |
| Cell Force Scaling | `abs(ratio - expected) / expected` | < 0.1 | NPT |

## Code Entity Reference

### Key Functions Under Test

```mermaid
graph TB
    subgraph "Initialization Functions"
        NVE_INIT["ts.nve_init"]
        NVT_L_INIT["ts.nvt_langevin_init"]
        NVT_NH_INIT["ts.nvt_nose_hoover_init"]
        NVT_VR_INIT["ts.nvt_vrescale_init"]
        NPT_L_INIT["ts.npt_langevin_init"]
        NPT_NH_INIT["ts.npt_nose_hoover_init"]
        NPT_CR_INIT["ts.npt_crescale_init"]
    end
    
    subgraph "Step Functions"
        NVE_STEP["ts.nve_step"]
        NVT_L_STEP["ts.nvt_langevin_step"]
        NVT_NH_STEP["ts.nvt_nose_hoover_step"]
        NVT_VR_STEP["ts.nvt_vrescale_step"]
        NPT_L_STEP["ts.npt_langevin_step"]
        NPT_NH_STEP["ts.npt_nose_hoover_step"]
        NPT_CR_ISO["ts.npt_crescale_isotropic_step"]
        NPT_CR_ANI["ts.npt_crescale_anisotropic_step"]
    end
    
    subgraph "Utility Functions"
        CALC_KT["ts.calc_kT"]
        NVT_INV["ts.nvt_nose_hoover_invariant"]
        NPT_INV["ts.npt_nose_hoover_invariant"]
        INIT_MOM["initialize_momenta"]
        CONCAT["ts.concatenate_states"]
    end
    
    NVE_INIT --> NVE_STEP
    NVT_L_INIT --> NVT_L_STEP
    NVT_NH_INIT --> NVT_NH_STEP
    NVT_VR_INIT --> NVT_VR_STEP
    NPT_L_INIT --> NPT_L_STEP
    NPT_NH_INIT --> NPT_NH_STEP
    NPT_CR_INIT --> NPT_CR_ISO
    NPT_CR_INIT --> NPT_CR_ANI
    
    NVT_L_STEP --> CALC_KT
    NVT_NH_STEP --> CALC_KT
    NVT_NH_STEP --> NVT_INV
    NPT_NH_STEP --> NPT_INV
```

**Sources:** [tests/test_integrators.py:1-11]()

---