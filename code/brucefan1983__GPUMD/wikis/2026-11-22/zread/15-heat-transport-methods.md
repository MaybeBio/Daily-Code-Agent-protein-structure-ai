

GPUMD implements a comprehensive suite of heat transport simulation methods spanning equilibrium, homogeneous nonequilibrium, and direct nonequilibrium approaches — all GPU-accelerated. These methods enable thermal conductivity calculation for bulk 3D materials, 2D layered systems, and multicomponent alloys, with additional capabilities for spectral decomposition and mode-resolved analysis. The unifying computational primitive across all equilibrium and HNEMD methods is the **per-atom heat current**, calculated from virial and velocity data on the GPU.

Sources: [compute_heat.cuh](/src/measure/compute_heat.cuh#L1-L30), [measure directory](/src/measure)

## Architectural Overview

The heat transport system is organized as a set of `Property` subclasses within the measurement pipeline, each implementing the `preprocess → process → postprocess` lifecycle. A shared `compute_heat` GPU kernel produces per-atom heat current data that feeds into the HAC (Green-Kubo), HNEMD, HNEMDEC, and SHC computations. Separately, the `MODAL_ANALYSIS` class implements GKMA and HNEMA, while the integrator layer provides direct nonequilibrium heat bath and two-temperature-model (TTM) ensembles.

```mermaid
graph TD
    subgraph "Heat Current Computation"
        CH[compute_heat GPU kernel] --> PAH[Per-atom heat current<br/>J_x^in, J_x^out, J_y^in, J_y^out, J_z]
    end

    subgraph "Equilibrium Methods (EMD)"
        PAH --> HAC[HAC class<br/>Heat Auto-Correlation]
        HAC --> RTC[Running Thermal Conductivity<br/>hac.out]
    end

    subgraph "Homogeneous NEMD Methods"
        PAH --> HNEMD[HNEMD class<br/>Driving force F_e]
        PAH --> HNEMDEC[HNEMDEC class<br/>Evans-Cummings algorithm]
        HNEMD --> KOUT[kappa.out]
        HNEMDEC --> OOUT[onsager.out]
    end

    subgraph "Spectral Decomposition"
        PAH --> SHC[SHC class<br/>Spectral Heat Current]
        SHC --> SHOUT[shc.out<br/>K(t) and J_q(omega)]
    end

    subgraph "Modal Analysis"
        MA[MODAL_ANALYSIS class] --> GKMA[GKMA method<br/>Green-Kubo Modal]
        MA --> HNEMA[HNEMA method<br/>HNEMD Modal]
        GKMA --> HMOUT[heatmode.out]
        HNEMA --> KMOUT[kappamode.out]
    end

    subgraph "Direct NEMD (Integrator Layer)"
        EH[ensemble heat_nhc/heat_bdp/heat_lan] --> DIRECT[Direct heat bath method]
        TTM[ensemble ttm/heat_ttm] --> TTMOUT[Two-Temperature Model]
    end

    VPA[Virial per atom] --> CH
    VEL[Velocity per atom] --> CH
```

Sources: [hac.cuh](/src/measure/hac.cuh#L1-L66), [hnemd_kappa.cuh](/src/measure/hnemd_kappa.cuh#L1-L68), [hnemdec_kappa.cuh](/src/measure/hnemdec_kappa.cuh#L1-L76), [shc.cuh](/src/measure/shc.cuh#L1-L81), [modal_analysis.cuh](/src/measure/modal_analysis.cuh#L1-L155)

## Per-Atom Heat Current Kernel

The `compute_heat` function is the foundational GPU kernel shared by the HAC, HNEMD, HNEMDEC, and SHC methods. It computes the **potential part** of the per-atom heat current from the per-atom virial tensor and velocity, following the formalism established in [Fan et al., Phys. Rev. B 92, 094301 (2015)]. Two overloads exist: one using only virial and velocity (producing the 5-component in-plane/out-of-plane decomposition used by HAC, HNEMD, and SHC), and one that additionally includes mass and per-atom potential energy (producing the full 3-component heat current used by HNEMDEC).

The 5-component variant decomposes each Cartesian heat current into in-plane and out-of-plane contributions — critical for 2D materials where basal-plane and cross-plane transport differ fundamentally. The virial tensor is stored in a compact 9-element layout per atom (`xx, yy, zz, xy, xz, yz, yx, zx, zy` mapped to indices `0,1,2,3,4,5,6,7,8`), and the kernel maps these to the heat current components:

| Heat Component | Formula | Physical Meaning |
|---|---|---|
| J_x^in | S_xx·v_x + S_xy·v_y | In-plane x heat current |
| J_x^out | S_xz·v_z | Out-of-plane x heat current |
| J_y^in | S_yx·v_x + S_yy·v_y | In-plane y heat current |
| J_y^out | S_yz·v_z | Out-of-plane y heat current |
| J_z | S_zx·v_x + S_zy·v_y + S_zz·v_z | Total z heat current |

The 3-component overload computes `J_α = (E_i + S_αα)·v_α + Σ_{β≠α} S_αβ·v_β` where `E_i = ½m_i|v_i|² + φ_i` is the total energy per atom, yielding the full heat current including convective contributions for multicomponent systems.

> [!TIP]
> For 3D isotropic systems, sum the in-plane and out-of-plane columns: κ_x^tot = κ_x^in + κ_x^out. The decomposition is only meaningful for 2D/layered materials where the basal plane is in the xy directions.

Sources: [compute_heat.cu](/src/measure/compute_heat.cu#L1-L167)

## Green-Kubo Method (EMD): `compute_hac`

The **Heat Auto-Correlation (HAC)** method computes thermal conductivity via the Green-Kubo linear response formalism in equilibrium molecular dynamics. The thermal conductivity is obtained from the time integral of the heat current autocorrelation function: `κ = (1/Vk_BT) ∫₀^∞ ⟨J(0)·J(t)⟩ dt`. In practice, GPUMD computes the **Running Thermal Conductivity (RTC)** — the cumulative integral as a function of upper limit — which should converge to the true κ at sufficiently long correlation time.

**Syntax:** `compute_hac <sampling_interval> <correlation_steps> <output_interval>`

| Parameter | Description | Constraints |
|---|---|---|
| `sampling_interval` | Steps between heat current samples | ≥ 1 |
| `correlation_steps` | Maximum correlation steps (Nc) | Typically ~10% of total samples |
| `output_interval` | Averaging window before writing output | 1 = no averaging |

The implementation follows a three-phase pipeline: (1) **preprocess** allocates GPU memory for `5 × N_frames` heat current components; (2) **process** computes per-atom heat current via `compute_heat`, then reduces across atoms using a `gpu_sum_heat` kernel with shared-memory reduction (launching 5 blocks of 1024 threads); (3) **postprocess** computes the autocorrelation via `gpu_find_hac` (launching Nc blocks of 128 threads with shared-memory accumulation), then integrates via the trapezoidal rule in `find_rtc` on the CPU. The HAC kernel computes cross-terms between in-plane and out-of-plane components and attributes them equally, as justified in [Fan2019].

**Output** (`hac.out`): 11 columns — correlation time (ps), 5 HAC components (eV³/amu), 5 RTC components (W/mK). The in/out decomposition allows extracting total conductivity for 3D systems by simple column summation.

Sources: [hac.cu](/src/measure/hac.cu#L1-L200), [compute_hac.rst](/doc/gpumd/input_parameters/compute_hac.rst#L1-L52), [hac_out.rst](/doc/gpumd/output_files/hac_out.rst#L1-L49)

## Homogeneous NEMD: `compute_hnemd`

The **HNEMD** method applies a fictitious external driving force **F**_e to all atoms, creating a homogeneous heat current without spatial temperature gradients. This avoids the finite-size effects inherent in direct NEMD. The thermal conductivity is extracted from the steady-state heat current: `κ_μα = ⟨J_α⟩ / (V·T·F_e,μ)`. The method is described in [Fan et al., Phys. Rev. B 99, 064308 (2019)].

**Syntax:** `compute_hnemd <output_interval> <Fe_x> <Fe_y> <Fe_z>`

| Parameter | Description | Units |
|---|---|---|
| `output_interval` | Steps between averaged outputs | steps |
| `Fe_x, Fe_y, Fe_z` | Driving force components | Å⁻¹ |

The driving force direction determines which conductivity tensor components are measured. A nonzero F_e,x yields κ_xx, κ_yx, κ_zx; F_e,y yields κ_xy, κ_yy, κ_zy; F_e,z yields κ_xz, κ_yz, κ_zz. The magnitude |**F**_e| must be small enough for linear response (typically 10⁻⁵ Å⁻¹) but large enough for sufficient signal-to-noise.

The HNEMD class calls `force.set_hnemd_parameters(fe_x, fe_y, fe_z)` during construction, which modifies the force computation to include the driving force. The **process** method samples heat current every step (not at a configurable interval — unlike HAC), accumulates over `output_interval` steps, then computes `κ = KAPPA_UNIT_CONVERSION / (output_interval × V × T × |F_e|) × ΣJ` and appends to `kappa.out`. A Nose-Hoover chain thermostat must be used to control temperature; Langevin thermostats are incompatible because they alter dynamical correlations.

Sources: [hnemd_kappa.cu](/src/measure/hnemd_kappa.cu#L1-L185), [compute_hnemd.rst](/doc/gpumd/input_parameters/compute_hnemd.rst#L1-L60)

## HNEMD for Multicomponent Systems: `compute_hnemdec`

The **HNEMDEC** method extends HNEMD to multicomponent (alloy) systems using the **Evans-Cummings algorithm**, which accounts for the coupling between heat and mass diffusion. In multicomponent systems, the Onsager transport coefficients form a matrix relating heat flux and mass flux to thermodynamic driving forces. HNEMDEC computes these cross-coupling Onsager coefficients by applying either a thermal driving force (producing heat flux) or a diffusive driving force (producing momentum flux for a specific element).

**Syntax:** `compute_hnemdec <driving_force> <output_interval> <Fe_x> <Fe_y> <Fe_z>`

| Parameter | Description | Values |
|---|---|---|
| `driving_force` | Type of driving force | 0 = thermal; i > 0 = diffusive for element (i-1) |
| `output_interval` | Steps between output | steps |
| `Fe_x, Fe_y, Fe_z` | Driving force components | Å⁻¹ (thermal) or eV/Å (diffusive) |

When `driving_force = 0`, heat flux is the dissipative flux and F_e is in Å⁻¹. When `driving_force = i` (positive integer), a momentum flux of the (i-1)th element is produced as dissipative flux, and F_e is in eV/Å. The implementation uses the 3-component `compute_heat` overload (with mass and per-atom potential) to compute the full heat current including convective terms. It simultaneously accumulates diffusion currents (mass-weighted velocity sums per atom type) via the `gpu_sum_heat_and_diffusion` kernel. The `FACTOR` variable corrects for reduced-mass effects in the color conductivity formulation.

**Output** (`onsager.out`): Onsager coefficient matrix elements relating heat and mass transport — essential for predicting alloy thermal conductivity including the mass-diffusion contribution.

Sources: [hnemdec_kappa.cu](/src/measure/hnemdec_kappa.cu#L1-L200), [compute_hnemdec.rst](/doc/gpumd/input_parameters/compute_hnemdec.rst#L1-L61)

## Spectral Heat Current: `compute_shc`

The **Spectral Heat Current (SHC)** method decomposes the total thermal conductivity into frequency-resolved contributions, yielding the spectral thermal conductivity κ(ω). This reveals which phonon frequencies carry the most heat — invaluable for understanding scattering mechanisms and designing materials. The method computes the non-equilibrium virial-velocity correlation function K(t) and its Fourier transform to obtain J_q(ω), following Eq. (18) and Eq. (20) of [Fan2019].

**Syntax:** `compute_shc <sample_interval> <Nc> <transport_direction> <num_omega> <max_omega> [group <grouping_method> <group_id>]`

| Parameter | Description | Constraints |
|---|---|---|
| `sample_interval` | Steps between correlation samples | 1–10 |
| `Nc` | Total correlation steps | 100–1000 |
| `transport_direction` | Heat transport direction | 0=x, 1=y, 2=z |
| `num_omega` | Number of frequency points | ≥ 1 |
| `max_omega` | Maximum angular frequency | THz |
| `group` (optional) | Restrict to atom group | grouping_method + group_id |

The implementation stores Nc frames of velocity (vx, vy, vz) and virial (sx, sy, sz) data per atom in the group, consuming `6 × group_size × Nc` doubles of GPU memory. The correlation kernel `gpu_find_k` computes the in-plane and out-of-plane virial-velocity correlations using shared-memory reduction. The `find_shc` function performs the discrete Fourier transform to obtain the spectral heat current. Setting `group_id = -1` computes SHC for all groups except group 0, allowing selective analysis while reducing memory by assigning unneeded atoms to group 0.

**Output** (`shc.out`): Angular frequency (THz), in-plane SHC, out-of-plane SHC — providing the spectral decomposition of thermal conductivity.

Sources: [shc.cu](/src/measure/shc.cu#L1-L200), [compute_shc.rst](/doc/gpumd/input_parameters/compute_shc.rst#L1-L100)

## Modal Analysis: `compute_gkma` and `compute_hnema`

Modal analysis methods resolve thermal transport to individual phonon modes or frequency bins, requiring eigenvector data from a separate phonon calculation. The `MODAL_ANALYSIS` class implements both **Green-Kubo Modal Analysis (GKMA)** [Lv2016] and **Homogeneous NEMD Modal Analysis (HNEMA)** [Gabourie2021], selected by the keyword used.

### GKMA: `compute_gkma`

Computes modal heat currents in equilibrium using the Green-Kubo formalism projected onto phonon modes.

**Syntax:** `compute_gkma <sample_interval> <first_mode> <last_mode> <bin_option> <size>`

| Parameter | Description |
|---|---|
| `sample_interval` | Steps between modal heat current samples |
| `first_mode`, `last_mode` | Mode range from eigenvector.in |
| `bin_option` | `bin_size` (count) or `f_bin_size` (frequency in THz) |
| `size` | Modes per bin or bin width in THz |

**Output** (`heatmode.out`): Modal heat current data per bin per sample — can be very large (many GB).

### HNEMA: `compute_hnema`

Computes modal thermal conductivity using a driving force, analogous to HNEMD but mode-resolved.

**Syntax:** `compute_hnema <sample_interval> <output_interval> <Fe_x> <Fe_y> <Fe_z> <first_mode> <last_mode> <bin_option> <size>`

| Parameter | Description | Units |
|---|---|---|
| `sample_interval` | Must divide `output_interval` | steps |
| `output_interval` | Output averaging window | steps |
| `Fe_x, Fe_y, Fe_z` | Driving force components | Å⁻¹ |
| Remaining | Same as GKMA | — |

**Output** (`kappamode.out`): Mode-resolved thermal conductivity per bin.

Both methods use cuBLAS (or hipBLAS for AMD GPUs) for eigenvector-matrix multiplications. The eigenvectors are loaded from `eigenvector.in` as single-precision floats. Memory requirements scale with the eigenvector file size. GKMA and HNEMA are **mutually exclusive** within a single run — the last keyword parsed takes precedence.

Sources: [modal_analysis.cuh](/src/measure/modal_analysis.cuh#L1-L155), [compute_gkma.rst](/doc/gpumd/input_parameters/compute_gkma.rst#L1-L76), [compute_hnema.rst](/doc/gpumd/input_parameters/compute_hnema.rst#L1-L83)

## Direct NEMD: Heat Bath Ensembles

Beyond the homogeneous methods, GPUMD provides direct nonequilibrium simulation via localized heat source/sink thermostats. These create an explicit temperature gradient across the simulation domain, and thermal conductivity is extracted from the steady-state heat flux and temperature profile via Fourier's law.

| Ensemble | Thermostat | Command |
|---|---|---|
| `heat_nhc` | Nose-Hoover chain | `ensemble heat_nhc <T> <T_coup> <delta_T> <source> <sink>` |
| `heat_bdp` | Bussi-Donadio-Parrinello | `ensemble heat_bdp <T> <T_coup> <delta_T> <source> <sink>` |
| `heat_lan` | Langevin | `ensemble heat_lan <T> <T_coup> <delta_T> <source> <sink>` |

The source region is thermostatted at T + δT and the sink at T − δT, producing a temperature difference of 2δT. Both `source` and `sink` labels reference grouping method 0. The `T_coup` parameter controls thermostat coupling strength (same meaning as in NVT ensembles). The integrator implementation lives in `ensemble_heat_hybrid.cu`, which combines the velocity Verlet integration with local thermostat application only to atoms in the source/sink groups.

Sources: [ensemble_heat.rst](/doc/gpumd/input_parameters/ensemble_heat.rst#L1-L59), [ensemble_heat_hybrid.cuh](/src/integrate/ensemble_heat_hybrid.cuh#L1-L1)

## Two-Temperature Model: `ensemble ttm` and `ensemble heat_ttm`

The **Two-Temperature Model (TTM)** couples the ionic system to an electron temperature grid, enabling simulation of electron-phonon coupling effects critical in metals and laser-heated systems. The electron temperature evolves on a separate grid according to a diffusion equation with source terms from electron-phonon energy exchange.

**TTM syntax:** `ensemble ttm <grouping_method> <group_id> <Ce> <rho_e> <kappa_e> <gamma_p> <gamma_s> <v_0> <nx> <ny> <nz> <T_e_init> [options]`

**Heat+TTM syntax:** `ensemble heat_ttm <T> <T_coup> <delta_T> <source> <sink> <grouping_method> <group_id> <Ce> <rho_e> <kappa_e> <gamma_p> <gamma_s> <v_0> <nx> <ny> <nz> <T_e_init> [options]`

| Parameter | Description | Units |
|---|---|---|
| `Ce` | Electron specific heat per electron | eV/K |
| `rho_e` | Electron number density | Å⁻³ |
| `kappa_e` | Electron thermal conductivity | eV/(ps·K·Å) |
| `gamma_p`, `gamma_s` | Friction coefficients | amu/ps |
| `v_0` | Threshold velocity | Å/ps |
| `nx, ny, nz` | Electron grid dimensions | cells |
| `T_e_init` | Initial electron temperature | K |

Optional arguments include: `ttm_out_interval` (output frequency), `ttm_infile` (initial electron temperature profile), `ttm_properties_file` (per-cell properties overriding uniform values), `ttm_source` (volumetric heat source in eV/(ps·Å³)), and `ttm_active_x/y/z` (active grid ranges). The `ensemble_ttm.cu` integrator handles both pure TTM and combined heat-bath+TTM simulations.

**Output** (`ttm_electron_temperature.out`): Electron temperature per grid cell over time.

Sources: [ensemble_ttm.rst](/doc/gpumd/input_parameters/ensemble_ttm.rst#L1-L136), [ensemble_ttm.cuh](/src/integrate/ensemble_ttm.cuh#L1-L1)

## Method Selection Guide

| Method | Type | κ Components | Spectral Info | System Type | Finite-Size Issues | Key Output |
|---|---|---|---|---|---|---|
| **HAC** (Green-Kubo) | EMD | All (via in/out decomp.) | No | Bulk 3D, 2D | Minimal | `hac.out` |
| **HNEMD** | Homogeneous NEMD | 3 per run (via F_e direction) | No | Bulk 3D, 2D | Minimal | `kappa.out` |
| **HNEMDEC** | Homogeneous NEMD | Onsager matrix | No | Multicomponent alloys | Minimal | `onsager.out` |
| **SHC** | EMD correlation | One direction per run | Yes: κ(ω) | Bulk, interfaces | Minimal | `shc.out` |
| **GKMA** | EMD modal | Mode-resolved | Yes: per-mode | Crystalline | Minimal | `heatmode.out` |
| **HNEMA** | HNEMD modal | Mode-resolved | Yes: per-mode | Crystalline | Minimal | `kappamode.out` |
| **heat_nhc/bdp/lan** | Direct NEMD | One direction per run | No | Any | **Significant** | Temperature profile |
| **TTM / heat_ttm** | Direct NEMD + e-ph | Electron + phonon | No | Metals | **Significant** | `ttm_electron_temperature.out` |

> [!TIP]
> For bulk crystalline or amorphous systems, start with HNEMD — it converges faster than Green-Kubo HAC and avoids finite-size effects. Use HAC to validate. For alloys, use HNEMDEC. For 2D materials, leverage the in/out decomposition by orienting the basal plane in xy. For spectral analysis, SHC is more general (no eigenvectors needed); GKMA/HNEMA provide mode-resolved detail but require phonon eigenvectors.

Sources: [hac.cuh](/src/measure/hac.cuh#L1-L66), [hnemd_kappa.cuh](/src/measure/hnemd_kappa.cuh#L1-L68), [hnemdec_kappa.cuh](/src/measure/hnemdec_kappa.cuh#L1-L76), [shc.cuh](/src/measure/shc.cuh#L1-L81), [modal_analysis.cuh](/src/measure/modal_analysis.cuh#L1-L155)

## Inter-Method Dependencies and Constraints

Several constraints govern which heat transport computations can coexist in a single run. The HNEMD driving force modifies the force computation globally via `force.set_hnemd_parameters()`, meaning HNEMD-based methods (HNEMD, HNEMDEC, HNEMA) are mutually exclusive with equilibrium methods that assume unmodified dynamics (HAC, GKMA). GKMA and HNEMA are explicitly mutually exclusive. The direct NEMD ensembles (heat_nhc/bdp/lan) operate at the integrator level and are compatible with output computations that don't assume equilibrium, but the thermal conductivity extraction requires post-processing of temperature profiles rather than built-in κ calculation.

The `compute_heat` kernel is invoked within the `process()` method of HAC, HNEMD, HNEMDEC, and SHC, meaning these measurements occur on-line during the MD loop. In contrast, the direct NEMD methods require separate post-processing of dumped temperature data. The modal analysis methods load eigenvectors during `preprocess()` and use cuBLAS for on-line modal heat current computation during `process()`.

For deeper understanding of the force computation that feeds into heat current calculations, see [Force and Potential System](5-force-and-potential-system). For the integration schemes used with heat transport (NHC, BDP, Langevin), see [Integration and Ensemble Methods](6-integration-and-ensemble-methods). For the GPU kernel patterns used in correlation and reduction computations, see [CUDA Kernel Design](13-cuda-kernel-design).
