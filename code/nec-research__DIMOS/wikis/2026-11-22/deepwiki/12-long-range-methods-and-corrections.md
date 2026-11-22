# Long-Range Methods and Corrections

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [benchmark/proteins/benchmark_proteins.py](benchmark/proteins/benchmark_proteins.py)
- [dimos/energy.py](dimos/energy.py)

</details>



## Purpose and Scope

This document describes the implementation of long-range electrostatic methods and analytical dispersion corrections in DIMOS. These methods are essential for accurately modeling systems with periodic boundary conditions, where interactions extend beyond the cutoff distance used for direct calculations.

For information about nonbonded interactions within the cutoff distance, see [Nonbonded Interactions](#3.1.2). For bonded interaction terms, see [Bonded Interactions](#3.1.1).

---

## Overview of Long-Range Corrections

Long-range corrections address two distinct problems in molecular dynamics simulations:

1. **Electrostatic Long-Range Effects**: Coulombic interactions decay slowly (1/r) and require special treatment to properly account for interactions beyond the cutoff in periodic systems
2. **Dispersion Corrections**: Lennard-Jones interactions are typically truncated at a cutoff, leading to systematic errors in energy and pressure that can be corrected analytically

DIMOS implements three approaches for handling long-range electrostatics and one method for dispersion corrections:

| Method | Type | Use Case | Class |
|--------|------|----------|-------|
| Reaction Field Approximation (RFA) | Electrostatics | Fast approximation for explicit solvent | `ElectrostaticsCutoff` |
| Ewald Summation | Electrostatics | Accurate periodic electrostatics | `Ewald` |
| Particle Mesh Ewald (PME) | Electrostatics | Efficient Ewald for large systems | `PME` |
| Analytical Dispersion | Lennard-Jones | Corrects for cutoff truncation | `DispersionCorrection` |

**Sources:** [dimos/energy.py:374-398](), [dimos/energy.py:812-943]()

---

## Electrostatic Long-Range Methods

### Method Selection Architecture

```mermaid
graph TD
    NB["NonbondedCutoffCommon<br/>Base Class"]
    
    NB_CUT["NonbondedInteractionsCutoff<br/>Simple cutoff method"]
    NB_EWALD["NonbondedInteractionsEwald<br/>Ewald-based methods"]
    
    ELEC_CUT["ElectrostaticsCutoff<br/>Reaction Field"]
    EWALD_CLASS["Ewald<br/>Standard Ewald summation"]
    PME_CLASS["PME<br/>Particle Mesh Ewald"]
    
    NB --> NB_CUT
    NB --> NB_EWALD
    
    NB_CUT --> ELEC_CUT
    NB_EWALD --> EWALD_CLASS
    NB_EWALD --> PME_CLASS
    
    USER["User Configuration"]
    USER -->|"nonbonded_type='cutoff'<br/>solvent_dielectric"| NB_CUT
    USER -->|"nonbonded_type='Ewald'<br/>method='Ewald'"| EWALD_CLASS
    USER -->|"nonbonded_type='PME'<br/>method='PME'"| PME_CLASS
```

**Sources:** [dimos/energy.py:550-810](), [dimos/energy.py:812-943]()

---

### Reaction Field Approximation (RFA)

The Reaction Field Approximation treats the region beyond the cutoff as a dielectric continuum with a specified dielectric constant. This provides a computationally efficient approximation for systems with explicit solvent.

#### Theory

The reaction field potential takes the form:

```
E = (q₁q₂/4πε₀) * (1/r + k_rf*r² - c_rf)
```

where the reaction field parameters are:

```
k_rf = (1/r_c³) * (ε_rf - 1) / (2*ε_rf + 1)
c_rf = (1/r_c) * (3*ε_rf) / (2*ε_rf + 1)
```

with `ε_rf` being the solvent dielectric constant and `r_c` the cutoff distance.

#### Implementation: ElectrostaticsCutoff Class

```mermaid
graph LR
    subgraph "ElectrostaticsCutoff Implementation"
        INIT["__init__()<br/>Initialize parameters"]
        CALC_REG["electrostatic_energy_contribution()<br/>Regular pairs"]
        CALC_14["electrostatic_energy_contribution_one_four()<br/>1-4 pairs"]
        CALC_TOTAL["calc_energy()<br/>Total energy"]
    end
    
    PARAMS["Parameters<br/>charges, cutoff,<br/>solvent_dielectric,<br/>scee, exclusions"]
    
    PRECOMP["Precomputed Values<br/>krf, crf,<br/>one_four_charges"]
    
    PARAMS --> INIT
    INIT --> PRECOMP
    
    PRECOMP --> CALC_REG
    PRECOMP --> CALC_14
    
    CALC_REG --> CALC_TOTAL
    CALC_14 --> CALC_TOTAL
```

**Key Implementation Details:**

- **Initialization**: [dimos/energy.py:1478-1521]()
  - Precomputes `krf` and `crf` parameters based on cutoff and dielectric constant
  - Stores scaled charge products for 1-4 interactions (divided by `scee` factor)
  
- **Regular Interactions**: [dimos/energy.py:1533-1560]()
  - Applies reaction field formula: `pot = q[i]*q[j] * (1/r + krf*r² - crf)`
  - Multiplies by Coulomb constant `constants.ONE_BY_4_PI_EPSILON_0`
  
- **1-4 Interactions**: [dimos/energy.py:1562-1582]()
  - Uses simple Coulomb interaction with pre-scaled charges
  - No reaction field correction applied to 1-4 pairs

**Sources:** [dimos/energy.py:1421-1619]()

---

### Ewald Summation

Ewald summation splits the slowly-converging electrostatic sum into two rapidly-converging parts: a real-space sum and a reciprocal-space sum. This method is exact (within numerical precision) for periodic systems.

#### Method Overview

The total electrostatic energy is decomposed as:

```
E_total = E_real + E_reciprocal + E_self + E_14
```

where:
- **E_real**: Short-range direct-space contribution (complementary error function screened)
- **E_reciprocal**: Long-range reciprocal-space contribution (Fourier space)
- **E_self**: Correction for self-interaction of Gaussian charge distributions
- **E_14**: Scaled 1-4 interactions

#### Implementation: Ewald and PME Classes

```mermaid
graph TD
    subgraph "Ewald/PME Configuration"
        INIT_EWALD["Ewald.__init__() / PME.__init__()"]
        ALPHA["Determine alpha parameter<br/>from tolerance"]
        KMAX["Determine k-space cutoff<br/>(Ewald only)"]
        GRID["Set up PME grid<br/>(PME only)"]
    end
    
    subgraph "Energy Calculation"
        REAL["calc_real_space()<br/>Direct space interactions"]
        RECIP_E["calc_reciprocal_ewald()<br/>(Ewald)"]
        RECIP_P["calc_reciprocal_pme()<br/>(PME)"]
        SELF["calc_self_energy()<br/>Self-interaction correction"]
        ONEFOUR["calc_one_four()<br/>1-4 interactions"]
    end
    
    INIT_EWALD --> ALPHA
    ALPHA --> KMAX
    ALPHA --> GRID
    
    KMAX --> REAL
    GRID --> REAL
    
    REAL --> RECIP_E
    REAL --> RECIP_P
    
    RECIP_E --> SELF
    RECIP_P --> SELF
    
    SELF --> ONEFOUR
```

**Key Parameters:**

| Parameter | Description | Determined By |
|-----------|-------------|---------------|
| `alpha` (α) | Gaussian width parameter | `tolerance` via error function |
| `cutoff` | Real-space cutoff | User-specified |
| `tolerance` | Target accuracy | User-specified (default: 1e-5) |
| `kmax` | Reciprocal space cutoff (Ewald) | Calculated from `alpha` and `tolerance` |
| `grid_size` | PME grid dimensions | Calculated from box size |

**Sources:** [dimos/energy.py:812-943](), [dimos/ewald.py:1-392]()

---

### Particle Mesh Ewald (PME)

PME is an optimized implementation of Ewald summation that uses fast Fourier transforms (FFT) on a grid to compute reciprocal space contributions. This reduces the computational complexity from O(N²) to O(N log N).

#### PME Workflow

```mermaid
graph LR
    subgraph "PME Reciprocal Space Calculation"
        CHARGE_GRID["1. Charge Assignment<br/>Interpolate charges to grid<br/>B-spline interpolation"]
        FFT_FORWARD["2. Forward FFT<br/>Transform to k-space"]
        CONVOLVE["3. Convolution<br/>Apply Ewald operator<br/>in k-space"]
        FFT_BACK["4. Inverse FFT<br/>Transform back to real space"]
        FORCES["5. Force Extraction<br/>Interpolate forces from grid"]
    end
    
    CHARGE_GRID --> FFT_FORWARD
    FFT_FORWARD --> CONVOLVE
    CONVOLVE --> FFT_BACK
    FFT_BACK --> FORCES
```

**PME-Specific Implementation:**

- Grid size is automatically determined to provide sufficient resolution
- B-spline interpolation (typically 4th order) maps charges to grid points
- FFT operations are performed using PyTorch's FFT capabilities
- Supports both `float32` and `float64` precision

**Sources:** [dimos/ewald.py:1-392]()

---

### Comparison of Electrostatic Methods

```mermaid
graph TD
    subgraph "Computational Complexity"
        RFA["Reaction Field<br/>O(N) with neighbor list"]
        EWALD["Ewald<br/>O(N²) + O(N k_max³)"]
        PME_COMP["PME<br/>O(N log N)"]
    end
    
    subgraph "Accuracy"
        RFA_ACC["Reaction Field<br/>Approximate<br/>Dielectric continuum"]
        EWALD_ACC["Ewald<br/>Exact (within tolerance)<br/>Periodic systems"]
        PME_ACC["PME<br/>Exact (within tolerance)<br/>Periodic systems"]
    end
    
    subgraph "Best Use Cases"
        RFA_USE["Reaction Field<br/>• Explicit solvent<br/>• Spherical cutoff OK<br/>• Speed critical"]
        EWALD_USE["Ewald<br/>• Small systems<br/>• High accuracy needed<br/>• Simple implementation"]
        PME_USE["PME<br/>• Large systems<br/>• Standard choice<br/>• Best performance"]
    end
```

**Sources:** [dimos/energy.py:695-810](), [dimos/energy.py:812-943]()

---

## Dispersion Corrections

### Purpose

Lennard-Jones interactions are typically truncated at a cutoff distance for computational efficiency. However, this truncation introduces systematic errors in both energy and pressure. Analytical dispersion corrections account for the missing tail of the LJ potential beyond the cutoff.

### Theory

The dispersion correction assumes a uniform particle distribution beyond the cutoff and integrates the Lennard-Jones potential analytically:

```
E_disp = (8π/V) * Σᵢⱼ εᵢⱼσᵢⱼ⁶ * [σᵢⱼ⁶/(9r_c⁹) - 1/(3r_c³)]
```

where:
- V is the system volume
- r_c is the cutoff distance
- εᵢⱼ, σᵢⱼ are the combined Lennard-Jones parameters

For switched potentials, an additional integral accounts for the switching region.

### Implementation: DispersionCorrection Class

```mermaid
graph TD
    subgraph "DispersionCorrection Workflow"
        INIT["__init__()<br/>sigmas, epsilons,<br/>cutoff, switch_distance"]
        
        COMBINE["Combine LJ Parameters<br/>ε_ij = sqrt(ε_i * ε_j)<br/>σ_ij = (σ_i + σ_j)/2"]
        
        INTEGRAL_DIRECT["Direct Cutoff Integral<br/>sum_1 = Σ ε_ij*σ_ij¹²/(9*r_c⁹)<br/>sum_2 = Σ ε_ij*σ_ij⁶/(3*r_c³)"]
        
        INTEGRAL_SWITCH["Switching Integral<br/>_eval_switch_integral()<br/>Analytical integration<br/>of switching function"]
        
        PRECOMP["Precompute Total<br/>dispersion_energy<br/>= 8π * (sum_1 - sum_2 + sum_3)"]
        
        CALC["calc_energy()<br/>Return dispersion_energy / V"]
    end
    
    INIT --> COMBINE
    COMBINE --> INTEGRAL_DIRECT
    COMBINE --> INTEGRAL_SWITCH
    INTEGRAL_DIRECT --> PRECOMP
    INTEGRAL_SWITCH --> PRECOMP
    PRECOMP --> CALC
    
    BOX["Box dimensions V<br/>Updated dynamically<br/>for NPT simulations"]
    BOX --> CALC
```

**Key Implementation Features:**

1. **Initialization** [dimos/energy.py:2566-2600]():
   - Computes pairwise LJ parameter combinations
   - Calculates direct cutoff integral contributions
   - Adds switching region correction if applicable
   - Stores precomputed energy term (independent of volume)

2. **Switching Function Integral** [dimos/energy.py:2612-2677]():
   - Analytical integration of 5th-order polynomial switch
   - Switch function: `S(r) = 1 + t³(-10 + t(15 - 6t))` where `t = (r-r_s)/(r_c-r_s)`
   - Complex polynomial expressions for both r⁶ and r¹² terms

3. **Energy Calculation** [dimos/energy.py:2679-2697]():
   - Simply divides precomputed value by current box volume
   - Very efficient: O(1) operation per energy evaluation
   - Volume-dependent for proper NPT ensemble behavior

**Sources:** [dimos/energy.py:2539-2698]()

---

## Integration with Nonbonded System

### System Configuration

Different long-range methods are selected through the nonbonded system configuration:

```mermaid
graph TD
    FF_INIT["ForceField Initialization<br/>AmberForceField or<br/>GromacsForceField"]
    
    CONFIG["Configuration Parameters<br/>• cutoff<br/>• switch_distance<br/>• nonbonded_type<br/>• solvent_dielectric<br/>• tolerance"]
    
    SELECT{"nonbonded_type?"}
    
    CUTOFF_SYS["NonbondedInteractionsCutoff<br/>+ ElectrostaticsCutoff<br/>+ LennardJones"]
    
    EWALD_SYS["NonbondedInteractionsEwald<br/>+ Ewald/PME<br/>+ LennardJones"]
    
    NOCUT_SYS["NonbondedInteractionsNoCutoff<br/>+ ElectrostaticsNoCutoff<br/>+ LennardJonesNoCutoff"]
    
    DISP["DispersionCorrection<br/>Always added if periodic"]
    
    FF_INIT --> CONFIG
    CONFIG --> SELECT
    
    SELECT -->|"'cutoff' or 'RFA'"| CUTOFF_SYS
    SELECT -->|"'Ewald' or 'PME'"| EWALD_SYS
    SELECT -->|"None"| NOCUT_SYS
    
    CUTOFF_SYS --> DISP
    EWALD_SYS --> DISP
```

**Configuration Examples:**

```python
# Reaction Field with 10 Å cutoff, 7.5 Å switch
system = dimos.AmberForceField(
    topology_file,
    coordinate_file,
    cutoff=10.0,
    switch_distance=7.5,
    nonbonded_type="cutoff",
    solvent_dielectric=78.5  # Water dielectric
)

# PME with 10 Å cutoff, 1e-5 tolerance
system = dimos.GromacsForceField(
    topology_file,
    coordinate_file,
    cutoff=10.0,
    nonbonded_type="PME",
    tolerance=1e-5
)
```

**Sources:** [benchmark/proteins/benchmark_proteins.py:31](), [dimos/energy.py:695-943]()

---

## Box Updates for NPT Simulations

All long-range methods support dynamic box dimension updates for NPT ensemble simulations through the `update_box()` method:

```mermaid
graph LR
    BAROSTAT["Barostat<br/>MC volume move"]
    
    NB_UPDATE["NonbondedSystem.update_box()"]
    
    LJ_UPDATE["LennardJones.update_box()"]
    ELEC_UPDATE["Electrostatics.update_box()<br/>RFA/Ewald/PME"]
    DISP_UPDATE["DispersionCorrection.update_box()"]
    
    BAROSTAT --> NB_UPDATE
    NB_UPDATE --> LJ_UPDATE
    NB_UPDATE --> ELEC_UPDATE
    NB_UPDATE --> DISP_UPDATE
    
    DISP_UPDATE -->|"Updates V<br/>in correction term"| DISP_CALC["calc_energy() uses<br/>new volume"]
```

The `update_box()` method propagates box dimension changes through the hierarchy of energy calculators, ensuring that:
- Periodic minimum image conventions use updated box vectors
- Dispersion corrections use the current volume
- PME grid spacing remains appropriate (may trigger reinitialization)

**Sources:** [dimos/energy.py:405-414](), [dimos/energy.py:683-693](), [dimos/energy.py:798-809](), [dimos/energy.py:931-942]()

---

## Performance Considerations

| Method | Initialization Cost | Per-Step Cost | Memory | Best For |
|--------|-------------------|---------------|--------|----------|
| **RFA** | Low | O(N) | Low | Small-medium systems, speed priority |
| **Ewald** | Medium | O(N²) + O(Nk³) | Medium | Small systems (<1000 atoms) |
| **PME** | Medium-High | O(N log N) | Medium-High | Large systems (>1000 atoms) |
| **Dispersion** | Low | O(1) | Very Low | All periodic systems |

**Optimization Notes:**

1. **PME Grid Size**: Automatically determined but can impact performance
   - Larger grids: More accurate, slower FFT
   - Smaller grids: Faster but may require larger cutoff

2. **Ewald Alpha Parameter**: Balances real vs reciprocal space work
   - Larger α: More reciprocal space work, less real space
   - Smaller α: More real space work, less reciprocal space

3. **Dispersion Correction**: Always recommended for cutoff-based methods
   - Nearly zero computational cost
   - Significant improvement in thermodynamic properties

**Sources:** [dimos/energy.py:374-398](), [benchmark/proteins/benchmark_proteins.py:1-73]()

---