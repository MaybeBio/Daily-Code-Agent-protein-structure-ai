# Architecture

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [docs/src/references/changelog.rst](docs/src/references/changelog.rst)
- [src/torchpme/calculators/calculator.py](src/torchpme/calculators/calculator.py)
- [src/torchpme/calculators/ewald.py](src/torchpme/calculators/ewald.py)
- [src/torchpme/calculators/p3m.py](src/torchpme/calculators/p3m.py)
- [src/torchpme/calculators/pme.py](src/torchpme/calculators/pme.py)
- [src/torchpme/potentials/combined.py](src/torchpme/potentials/combined.py)
- [src/torchpme/potentials/coulomb.py](src/torchpme/potentials/coulomb.py)
- [src/torchpme/potentials/inversepowerlaw.py](src/torchpme/potentials/inversepowerlaw.py)
- [src/torchpme/potentials/potential.py](src/torchpme/potentials/potential.py)
- [src/torchpme/potentials/spline.py](src/torchpme/potentials/spline.py)
- [tests/calculators/test_calculator.py](tests/calculators/test_calculator.py)
- [tests/test_potentials.py](tests/test_potentials.py)

</details>



This page provides a high-level overview of the torch-pme architecture, explaining the main components and their relationships. For implementation details of specific components, see the respective child pages.

The torch-pme library is designed to efficiently compute long-range potentials in molecular simulations, with a primary focus on electrostatic interactions. It provides a flexible, modular framework that enables different calculation strategies with varying trade-offs between computational efficiency and accuracy.

## Core Architecture Components

The architecture of torch-pme is built around several key abstractions that work together to provide an efficient implementation of various potential calculation methods:

```mermaid
graph TD
    subgraph "Core Components"
        A["Calculator Framework"] --> B["Potential System"]
        A --> C["K-Space Methods"]
        A --> D["Library Functions"]
    end

    subgraph "Implementation Layer"
        E["Calculator Implementations"] --> A
        F["Potential Implementations"] --> B
        G["Mesh Interpolation"] --> C
        H["K-Space Filtering"] --> C
    end

    I["Automatic Tuning"] --> E
    I --> F

    style A fill:#f5f5f5,stroke:#333,stroke-width:2px
    style B fill:#f5f5f5,stroke:#333,stroke-width:2px
    style C fill:#f5f5f5,stroke:#333,stroke-width:2px
    style D fill:#f5f5f5,stroke:#333,stroke-width:2px
```

The architecture follows a modular design where:

1. The **Calculator Framework** provides the base functionality for computing potentials, and serves as the primary interface for users.
2. The **Potential System** defines the mathematical forms of interactions through a set of interchangeable potential classes.
3. **K-Space Methods** handle the computation of long-range interactions in reciprocal space.
4. **Library Functions** provide utility functions, mathematical operations, and specialized algorithms used throughout the system.

Sources: [src/torchpme/calculators/calculator.py](), [src/torchpme/potentials/potential.py](), [src/torchpme/calculators/pme.py]()

## Computational Pipeline

The following diagram illustrates the computational pipeline in torch-pme:

```mermaid
flowchart TD
    subgraph "Input Data"
        A["Atomic Positions"] 
        B["Charges"]
        C["Unit Cell"]
        D["Neighbor List"]
    end

    subgraph "Calculator" 
        E["Calculator.forward()"] --> F["Real Space Calculation"]
        E --> G["K-Space Calculation"]
        
        F --> H["_compute_rspace()"]
        G --> I["_compute_kspace()"]
        
        H --> J["Short-Range Potential"]
        I --> K["Long-Range Potential"]
        
        J --> L["Real Space Sum"]
        K --> M["Self-Energy Correction"]
        K --> N["Background Correction"]
    end

    subgraph "Output"
        O["Potential Energy"]
    end

    A & B & C & D --> E
    L & M & N --> O
```

The computational process follows these steps:
1. Input data includes atomic positions, charges, unit cell parameters, and a neighbor list
2. The `Calculator.forward()` method splits the computation into real space and k-space components
3. Real space calculations handle short-range interactions using the neighbor list
4. K-space calculations handle long-range interactions using FFT-based methods
5. Self-energy and background corrections are applied as needed
6. The components are combined to produce the final potential energy

Sources: [src/torchpme/calculators/calculator.py:97-163](), [src/torchpme/calculators/pme.py:95-147](), [src/torchpme/calculators/ewald.py:76-134]()

## Calculator and Potential Class Hierarchies

The library is structured around two primary class hierarchies: Calculators and Potentials.

### Calculator Hierarchy

```mermaid
classDiagram
    class Calculator {
        +potential: Potential
        +full_neighbor_list: bool
        +prefactor: float
        +forward(charges, cell, positions, neighbor_indices, neighbor_distances)
        +_compute_rspace(charges, neighbor_indices, neighbor_distances)
        +_compute_kspace(charges, cell, positions)* abstract
    }
    
    class EwaldCalculator {
        +lr_wavelength: float
        +_compute_kspace(charges, cell, positions)
    }
    
    class PMECalculator {
        +mesh_spacing: float
        +interpolation_nodes: int
        +mesh_interpolator: MeshInterpolator
        +kspace_filter: KSpaceFilter
        +_compute_kspace(charges, cell, positions)
    }
    
    class P3MCalculator {
        +mesh_interpolator: MeshInterpolator
        +kspace_filter: P3MKSpaceFilter
    }
    
    Calculator <|-- EwaldCalculator
    Calculator <|-- PMECalculator
    PMECalculator <|-- P3MCalculator
```

The `Calculator` class serves as the base abstraction for all potential calculators. It implements the common logic for real-space calculations while leaving k-space calculations to be implemented by subclasses through the abstract `_compute_kspace` method.

Sources: [src/torchpme/calculators/calculator.py:8-163](), [src/torchpme/calculators/ewald.py:8-134](), [src/torchpme/calculators/pme.py:11-147](), [src/torchpme/calculators/p3m.py:9-96]()

### Potential Hierarchy

```mermaid
classDiagram
    class Potential {
        +smearing: Optional[float]
        +exclusion_radius: Optional[float]
        +exclusion_degree: int
        +from_dist(dist)
        +sr_from_dist(dist)
        +lr_from_dist(dist)
        +lr_from_k_sq(k_sq)
        +kernel_from_k_sq(k_sq)
        +self_contribution()
        +background_correction()
        +f_cutoff(dist)
    }
    
    class CoulombPotential {
        +from_dist(dist)
        +lr_from_dist(dist)
        +lr_from_k_sq(k_sq)
        +self_contribution()
        +background_correction()
    }
    
    class InversePowerLawPotential {
        +exponent: int
        +from_dist(dist)
        +lr_from_dist(dist)
        +lr_from_k_sq(k_sq)
        +self_contribution()
        +background_correction()
    }
    
    class SplinePotential {
        +r_grid: Tensor
        +y_grid: Tensor
        +k_grid: Tensor
        +yhat_grid: Tensor
        +from_dist(dist)
        +sr_from_dist(dist)
        +lr_from_dist(dist)
        +lr_from_k_sq(k_sq)
        +self_contribution()
        +background_correction()
    }
    
    class CombinedPotential {
        +potentials: List[Potential]
        +weights: Tensor
        +from_dist(dist)
        +sr_from_dist(dist)
        +lr_from_dist(dist)
        +lr_from_k_sq(k_sq)
        +self_contribution()
        +background_correction()
    }
    
    Potential <|-- CoulombPotential
    Potential <|-- InversePowerLawPotential
    Potential <|-- SplinePotential
    Potential <|-- CombinedPotential
```

The `Potential` class defines the interface for all potential functions used in torch-pme. It provides methods for calculating potentials in both real space and reciprocal space, as well as methods for computing self-energy and background corrections.

Sources: [src/torchpme/potentials/potential.py:6-173](), [src/torchpme/potentials/coulomb.py:8-107](), [src/torchpme/potentials/inversepowerlaw.py:11-145](), [src/torchpme/potentials/spline.py:14-159](), [src/torchpme/potentials/combined.py:8-120]()

## Calculation Methods and Space Complexity

torch-pme implements several methods for computing long-range potentials, each with different computational characteristics:

| Method | Implementation | Space Complexity | Main Features |
|--------|---------------|------------------|---------------|
| Ewald | `EwaldCalculator` | O(N²) | Direct k-space summation, accurate but computationally expensive |
| PME | `PMECalculator` | O(N·log(N)) | Fast Fourier Transform-based with mesh interpolation |
| P3M | `P3MCalculator` | O(N·log(N)) | Optimized PME with improved accuracy through modified influence functions |

Where N is the number of particles in the system.

Sources: [src/torchpme/calculators/ewald.py:8-15](), [src/torchpme/calculators/pme.py:11-17](), [src/torchpme/calculators/p3m.py:9-21]()

## Data Flow for Long-Range Potential Calculation

The following diagram illustrates how data flows through the system when calculating a long-range potential:

```mermaid
flowchart LR
    subgraph "Input"
        A["Atomic Positions"]
        B["Charges"]
        C["Cell Parameters"]
        D["Neighbor List"]
    end
    
    subgraph "Real Space Calculation"
        E["Short-Range Potential Evaluation"]
        F["Neighbor Pair Summation"]
    end
    
    subgraph "K-Space Calculation"
        G["Mesh Interpolation"]
        H["Fast Fourier Transform"]
        I["K-Space Filtering"]
        J["Inverse FFT"]
        K["Back-Interpolation"]
    end
    
    subgraph "Corrections"
        L["Self-Energy Correction"]
        M["Background Correction"]
    end
    
    subgraph "Output"
        N["Total Potential Energy"]
    end
    
    A & B & D --> E --> F
    A & B & C --> G --> H --> I --> J --> K
    B --> L
    B & C --> M
    
    F & K & L & M --> N
```

This detailed flow shows how:
1. The real space calculation evaluates the short-range part of the potential directly from the neighbor list
2. The k-space calculation uses mesh interpolation and Fourier transforms to efficiently compute the long-range part
3. Correction terms account for self-interaction and background charge
4. All components contribute to the final potential energy

Sources: [src/torchpme/calculators/calculator.py:97-163](), [src/torchpme/calculators/pme.py:95-147]()

## Integration with PyTorch and Automatic Differentiation

torch-pme is built on top of PyTorch, allowing it to leverage automatic differentiation for computing forces:

```mermaid
flowchart LR
    subgraph "torch-pme Components"
        A["Calculator"] --> B["Potential Energy"]
    end
    
    subgraph "PyTorch Features"
        C["Tensor Operations"]
        D["Automatic Differentiation"]
        E["TorchScript"]
    end
    
    B -- "requires_grad=True" --> D --> F["Forces = -∇Energy"]
    A -- "inherits from" --> G["torch.nn.Module"]
    G --> E
    C --> A
```

By implementing calculators and potentials as PyTorch modules and using PyTorch tensors for all calculations, torch-pme enables:
1. Automatic computation of forces through gradient backpropagation
2. GPU acceleration of calculations
3. Integration with PyTorch-based machine learning models
4. Just-in-time compilation through TorchScript for improved performance

Sources: [src/torchpme/calculators/calculator.py:8](), [src/torchpme/potentials/potential.py:6]()

## Summary and Component Relationships

The overall architecture of torch-pme follows a modular design that separates concerns:
- `Calculator` classes handle the overall computation strategy and implementation details
- `Potential` classes define the mathematical form of the interaction
- Supporting components like `MeshInterpolator` and `KSpaceFilter` provide specialized functionality

This architecture allows for flexible combination of different calculators and potentials, enabling efficient calculation of a wide range of interaction types.

For more detailed information on specific components, see the following pages:
- [Calculator Framework](#2.1)
- [Potential System](#2.2)
- [K-Space Methods](#2.3)
- [Library Functions](#2.4)

---