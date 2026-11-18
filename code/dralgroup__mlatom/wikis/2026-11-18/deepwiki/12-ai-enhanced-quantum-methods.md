# AI-Enhanced Quantum Methods

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [mlatom/aiqm1.py](mlatom/aiqm1.py)
- [mlatom/aiqm2.py](mlatom/aiqm2.py)
- [mlatom/model_cls.py](mlatom/model_cls.py)

</details>



This document covers MLatom's AI-enhanced quantum mechanical methods, specifically AIQM1 and AIQM2. These hybrid methods combine neural network models with traditional quantum chemistry calculations to provide accurate and efficient molecular property predictions. For neural network models without quantum chemistry components, see [Neural Network Models](#4.2). For general active learning workflows, see [Active Learning](#4.1).

## Overview

AI-Enhanced Quantum Methods in MLatom implement hybrid approaches that combine machine learning models with quantum chemistry calculations. The two main methods are AIQM1 and AIQM2, which use different baseline quantum chemistry methods but share a common architectural approach of hierarchical model composition.

### Method Architecture

```mermaid
graph TD
    subgraph "AIQM1 Architecture"
        A1["aiqm1"] --> B1["ani_nns ensemble"]
        A1 --> C1["atomic_energy_shift"]
        A1 --> D1["ODM2* method"]
        A1 --> E1["D4 dispersion"]
    end
    
    subgraph "AIQM2 Architecture"
        A2["aiqm2"] --> B2["ANI ensemble"]
        A2 --> C2["GFN2-xTB* baseline"]
        A2 --> D2["D4 dispersion"]
    end
    
    subgraph "Model Composition"
        MT["model_tree_node"] --> OP1["sum operator"]
        MT --> OP2["average operator"]
        MT --> OP3["predict operator"]
    end
    
    B1 --> MT
    B2 --> MT
    D1 --> MT
    C2 --> MT
```

**Sources:** [mlatom/aiqm1.py:15-67](), [mlatom/aiqm2.py:5-164](), [mlatom/model_cls.py:953-1135]()

## AIQM1 Method

The `aiqm1` class implements the Artificial Intelligence Quantum Mechanical method 1, which combines ANI neural networks with ODM2* quantum chemistry calculations.

### AIQM1 Components

```mermaid
graph TB
    subgraph "AIQM1 Model Tree"
        ROOT["aiqm1_model (sum)"] --> NN["aiqm1_nn (average)"]
        ROOT --> SHIFT["aiqm1_atomic_energy_shift (predict)"]
        ROOT --> ODM["odm2star (predict)"]
        ROOT --> D4["d4_wb97x (predict)"]
        
        NN --> NN0["aiqm1_nn0 (predict)"]
        NN --> NN1["aiqm1_nn1 (predict)"]
        NN --> NN2["aiqm1_nn2 (predict)"]
        NN --> DOTS["..."]
        NN --> NN7["aiqm1_nn7 (predict)"]
    end
    
    subgraph "Implementation Classes"
        IMPL1["ani_nns_in_aiqm1"]
        IMPL2["atomic_energy_shift"]  
        IMPL3["methods(ODM2*)"]
        IMPL4["methods(D4)"]
    end
    
    NN0 --> IMPL1
    SHIFT --> IMPL2
    ODM --> IMPL3
    D4 --> IMPL4
```

**Sources:** [mlatom/aiqm1.py:48-66](), [mlatom/aiqm1.py:171-318](), [mlatom/aiqm1.py:134-170]()

### AIQM1 Method Variants

The AIQM1 implementation supports three method variants:

| Method | Description | Components |
|--------|-------------|------------|
| `AIQM1` | Standard AIQM1 | ANI NNs + ODM2* + D4 + atomic shifts |
| `AIQM1@DFT` | DFT-trained variant | ANI NNs + ODM2* + D4 + atomic shifts |
| `AIQM1@DFT*` | DFT without D4 | ANI NNs + ODM2* + atomic shifts |

**Sources:** [mlatom/aiqm1.py:43-46](), [mlatom/aiqm1.py:63-65]()

### Neural Network Ensemble

The `ani_nns_in_aiqm1` class implements the neural network component using 8 ANI models for uncertainty quantification:

```mermaid
graph LR
    subgraph "ANI Neural Networks"
        MODEL["ani_nns_in_aiqm1"] --> DEVICE["CUDA/CPU device"]
        MODEL --> AEV["AEV computer"]
        MODEL --> NETS["8 NN models"]
        
        NETS --> H["H_network (160→128→96→1)"]
        NETS --> C["C_network (144→112→96→1)"] 
        NETS --> N["N_network (128→112→96→1)"]
        NETS --> O["O_network (128→112→96→1)"]
    end
```

**Sources:** [mlatom/aiqm1.py:171-318](), [mlatom/aiqm1.py:231-276]()

## AIQM2 Method

The `aiqm2` class implements AIQM2, which uses GFN2-xTB* as the baseline quantum chemistry method with neural network corrections.

### AIQM2 Architecture

```mermaid
graph TB
    subgraph "AIQM2 Model Structure"
        ROOT2["aiqm2_model (sum)"] --> BASE["gfn2xtbstar (predict)"]
        ROOT2 --> NN2["aiqm2_nn (average)"]
        ROOT2 --> D42["d4wb97x (predict)"]
        
        NN2 --> CV0["aiqm2_nn_0"]
        NN2 --> CV1["aiqm2_nn_1"] 
        NN2 --> CV2["aiqm2_nn_2"]
        NN2 --> DOTS2["..."]
        NN2 --> CV7["aiqm2_nn_7"]
    end
    
    subgraph "Backend Methods"
        GFN["GFN2-xTB*"]
        ANI["ANI models"]
        D4M["D4 method"]
    end
    
    BASE --> GFN
    CV0 --> ANI
    CV1 --> ANI
    CV2 --> ANI
    CV7 --> ANI
    D42 --> D4M
```

**Sources:** [mlatom/aiqm2.py:101-164](), [mlatom/aiqm2.py:122-158]()

### AIQM2 Method Variants

| Method | Description | Model Directory |
|--------|-------------|-----------------|
| `AIQM2` | Standard AIQM2 | `aiqm2_model` |
| `AIQM2@DFT` | DFT-trained variant | `aiqm2_dft_model` |
| `AIQM2@DFT*` | Alias for `AIQM2@DFT` | `aiqm2_dft_model` |

**Sources:** [mlatom/aiqm2.py:32](), [mlatom/aiqm2.py:104-115]()

## Model Composition Framework

The AI-enhanced quantum methods leverage MLatom's hierarchical model composition system implemented through the `model_tree_node` class.

### Model Tree Operations

```mermaid
graph TD
    subgraph "Model Tree Operations"
        NODE["model_tree_node"] --> PRED["predict operator"]
        NODE --> SUM["sum operator"]
        NODE --> AVG["average operator"]
        NODE --> WSUM["weighted_sum operator"]
    end
    
    subgraph "Tree Structure"
        PARENT["parent node"] --> CHILD1["child 1"]
        PARENT --> CHILD2["child 2"]
        PARENT --> CHILD3["child N"]
        
        CHILD1 --> LEAF1["leaf model"]
        CHILD2 --> LEAF2["leaf model"]
    end
    
    subgraph "Property Flow"
        PROPS["properties"] --> EN["energy"]
        PROPS --> GRAD["gradients"]
        PROPS --> HESS["hessian"]
    end
```

**Sources:** [mlatom/model_cls.py:953-1135](), [mlatom/model_cls.py:987-1077]()

### Operator Implementation

The model tree supports different combination operators:

| Operator | Function | Usage |
|----------|----------|-------|
| `predict` | Execute leaf model | Individual model components |
| `sum` | Add child predictions | AIQM total energy |
| `average` | Average child predictions | Neural network ensembles |
| `weighted_sum` | Weighted combination | Custom model weighting |

**Sources:** [mlatom/model_cls.py:1043-1075]()

## Implementation Details

### Class Hierarchy

```mermaid
graph TD
    subgraph "Base Classes"
        MODEL["model"] --> METHOD["method_model"]
        MODEL --> TORCH["torch_model"]
        MODEL --> DOWNLOAD["downloadable_model"]
        TORCH --> TORCHANI["torchani_model"]
    end
    
    subgraph "AIQM1 Classes"
        METHOD --> AIQM1["aiqm1"]
        TORCHANI --> AIQM1
        TORCHANI --> ANINNS["ani_nns_in_aiqm1"]
        DOWNLOAD --> ANINNS
        MODEL --> SHIFT["atomic_energy_shift"]
    end
    
    subgraph "AIQM2 Classes"
        METHOD --> AIQM2["aiqm2"]
        DOWNLOAD --> AIQM2
    end
    
    subgraph "Composition"
        MODEL --> TREE["model_tree_node"]
    end
```

**Sources:** [mlatom/model_cls.py:20-200](), [mlatom/aiqm1.py:15](), [mlatom/aiqm2.py:5]()

### Property Calculation Flow

Both AIQM methods support multiple property calculations:

```mermaid
graph LR
    subgraph "Input Properties"
        CALCEN["calculate_energy"]
        CALCGRAD["calculate_energy_gradients"] 
        CALCHESS["calculate_hessian"]
        NSTATES["nstates"]
    end
    
    subgraph "Processing"
        TREE["model_tree_node.predict()"]
        VALIDATE["element validation (CHNO only)"]
        ENSEMBLE["uncertainty quantification"]
    end
    
    subgraph "Output Properties"
        ENERGY["molecule.energy"]
        GRADIENTS["atom.energy_gradients"]
        HESSIAN["molecule.hessian"]
        UNCERTAINTY["standard_deviation"]
    end
    
    CALCEN --> TREE
    CALCGRAD --> TREE
    CALCHESS --> TREE
    NSTATES --> TREE
    
    TREE --> VALIDATE
    VALIDATE --> ENSEMBLE
    ENSEMBLE --> ENERGY
    ENSEMBLE --> GRADIENTS  
    ENSEMBLE --> HESSIAN
    ENSEMBLE --> UNCERTAINTY
```

**Sources:** [mlatom/aiqm1.py:68-132](), [mlatom/aiqm2.py:62-99](), [mlatom/model_cls.py:987-1112]()

### Element Support and Validation

Both AIQM1 and AIQM2 are restricted to CHNO elements (H, C, N, O):

```python
for atom in molecule.atoms:
    if not atom.atomic_number in [1, 6, 7, 8]:
        raise ValueError("Molecule contains elements other than CHNO")
```

**Sources:** [mlatom/aiqm1.py:83-87](), [mlatom/aiqm2.py:88-91]()

## Usage Examples

### Basic AIQM1 Usage

```python
import mlatom as ml

# Initialize molecule
mol = ml.data.molecule()
mol.read_from_xyz_file(filename='ethanol.xyz')

# Run AIQM1 calculation
aiqm1 = ml.methods(method='AIQM1', qm_program='MNDO')
aiqm1.predict(molecule=mol, 
              calculate_energy=True, 
              calculate_energy_gradients=True)

# Access results
energy = mol.energy
gradient = mol.get_energy_gradients()
uncertainty = mol.aiqm1_nn.energy_standard_deviation
```

### Basic AIQM2 Usage

```python
# Run AIQM2 calculation  
aiqm2 = ml.methods(method='AIQM2')
aiqm2.predict(molecule=mol,
              calculate_energy=True,
              calculate_energy_gradients=True,
              calculate_hessian=True)

# Access results
energy = mol.energy
gradients = mol.get_energy_gradients() 
hessian = mol.hessian
uncertainty = mol.aiqm2_model.energy_standard_deviation
```

**Sources:** [mlatom/aiqm1.py:27-38](), [mlatom/aiqm2.py:16-28]()

---