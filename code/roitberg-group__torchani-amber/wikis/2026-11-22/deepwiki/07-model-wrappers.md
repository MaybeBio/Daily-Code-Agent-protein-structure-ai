# Model Wrappers

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [jit/aimnet2_wrapper.py](jit/aimnet2_wrapper.py)
- [jit/nutmeg_wrapper.py](jit/nutmeg_wrapper.py)

</details>



This document covers the model wrapper system that enables integration of external neural network potentials into TorchANI-Amber. Model wrappers provide a standardized interface for different neural network architectures, handling coordinate transformations, neighbor list calculations, and unit conversions.

For information about the core C++ integration layer, see [C++ Engine and JIT System](#3.1). For simulation configuration details, see [Simulation Configuration](#4.1).

## Purpose and Architecture

Model wrappers serve as adaptation layers that allow external neural network potentials to interface with the TorchANI-Amber system. They handle the differences in input formats, coordinate systems, and output structures between various neural network implementations.

### Wrapper System Architecture

```mermaid
graph TB
    subgraph "External Models"
        AIMNET["AimNet2 Models<br/>.pt files"]
        NUTMEG["Nutmeg Models<br/>.pt files"]
        OTHER["Other NN Models"]
    end
    
    subgraph "Wrapper Layer"
        AIM_WRAP["AimNet2Wrapper<br/>torchani.nn.Module"]
        AIM_MBIS["AimNet2Mbis<br/>torchani.nn.Module"]
        NUT_WRAP["NutmegWrapper<br/>torchani.nn.Module"]
    end
    
    subgraph "TorchANI Interface"
        COMMON["Common Interface<br/>forward(species_coords)"]
        NLIST["Neighbor Lists<br/>AdaptiveList"]
        UNITS["Unit Conversion<br/>Hartree/eV/kJ·mol⁻¹"]
    end
    
    subgraph "Output"
        SPECIES["Species Tensors"]
        ENERGIES["Energy Values"]
        CHARGES["Atomic Charges"]
    end
    
    AIMNET --> AIM_WRAP
    AIMNET --> AIM_MBIS
    NUTMEG --> NUT_WRAP
    OTHER --> NUT_WRAP
    
    AIM_WRAP --> COMMON
    AIM_MBIS --> COMMON
    NUT_WRAP --> COMMON
    
    COMMON --> NLIST
    COMMON --> UNITS
    
    NLIST --> SPECIES
    UNITS --> ENERGIES
    COMMON --> CHARGES
    
    style AIM_WRAP fill:#e1f5fe
    style COMMON fill:#e8f5e8
    style NLIST fill:#fff3e0
```

**Sources:** [jit/aimnet2_wrapper.py:54-338](), [jit/nutmeg_wrapper.py:18-152]()

### Data Flow Through Wrappers

```mermaid
flowchart LR
    subgraph "Input Processing"
        COORDS["Coordinates<br/>Tensor[batch, atoms, 3]"]
        SPECIES["Species<br/>Tensor[batch, atoms]"]
        CELL["Cell Parameters<br/>Optional[Tensor]"]
        PBC["Periodic Boundary<br/>Optional[Tensor]"]
    end
    
    subgraph "Wrapper Processing"
        NLIST_CALC["Neighbor List<br/>AdaptiveList._nlist()"]
        COORD_TRANS["Coordinate Transform<br/>Units & Format"]
        FEAT_BUILD["Feature Building<br/>Atom Types & Charges"]
    end
    
    subgraph "Model Execution"
        EXTERNAL["External Model<br/>model.forward()"]
        POST_PROC["Post Processing<br/>Unit Conversion"]
    end
    
    subgraph "Output"
        OUT_SPECIES["Species"]
        OUT_ENERGY["Energies"]
        OUT_CHARGES["Atomic Charges"]
    end
    
    COORDS --> NLIST_CALC
    SPECIES --> NLIST_CALC
    CELL --> NLIST_CALC
    PBC --> NLIST_CALC
    
    NLIST_CALC --> COORD_TRANS
    COORD_TRANS --> FEAT_BUILD
    FEAT_BUILD --> EXTERNAL
    
    EXTERNAL --> POST_PROC
    POST_PROC --> OUT_SPECIES
    POST_PROC --> OUT_ENERGY
    POST_PROC --> OUT_CHARGES
    
    style NLIST_CALC fill:#fff3e0
    style EXTERNAL fill:#e1f5fe
    style POST_PROC fill:#e8f5e8
```

**Sources:** [jit/aimnet2_wrapper.py:120-195](), [jit/nutmeg_wrapper.py:106-151]()

## AimNet2 Wrapper System

The AimNet2 wrapper system provides integration for AimNet2 neural network potentials, supporting multiple long-range electrostatic treatment methods and charge prediction schemes.

### AimNet2Wrapper Class

The `AimNet2Wrapper` class provides the primary interface for AimNet2 models:

| Component | Description | Configuration |
|-----------|-------------|---------------|
| `method_lr` | Long-range method | `"simple"`, `"dsf"`, `"ewald"` |
| `cutoff_lr` | Long-range cutoff | `None` (auto), or float value |
| `dsf_alpha` | DSF damping parameter | `None` (auto), or float value |
| `output_hartree` | Energy units | `True` (Hartree), `False` (eV) |

**Core Methods:**

- `from_jit_file(path, device, **kwargs)` - Load model from JIT file
- `forward(species_coords, cell, pbc, charge, atomic, ensemble_values)` - Main inference
- `_calc_neighbors(species, coords, cell, pbc)` - Neighbor list calculation

### Long-Range Electrostatic Methods

```mermaid
graph TB
    subgraph "Method Types"
        SIMPLE["method_lr='simple'<br/>No cutoff (inf)"]
        DSF["method_lr='dsf'<br/>Damped Shifted Force"]
        EWALD["method_lr='ewald'<br/>Ewald summation"]
    end
    
    subgraph "Configuration"
        CUTOFF["cutoff_lr parameter<br/>Default: 15.0 Å"]
        ALPHA["dsf_alpha parameter<br/>Default: 0.2"]
        VALIDATION["Parameter Validation<br/>_validate_lr_params()"]
    end
    
    subgraph "Model Application"
        MODULE_FIND["Find .lrcoulomb modules<br/>model.named_modules()"]
        METHOD_SET["Set module.method<br/>Set module.dsf_alpha"]
        CUTOFF_CHECK["Validate cutoff_lr < model.cutoff"]
    end
    
    SIMPLE --> CUTOFF
    DSF --> CUTOFF
    DSF --> ALPHA
    EWALD --> CUTOFF
    
    CUTOFF --> VALIDATION
    ALPHA --> VALIDATION
    VALIDATION --> MODULE_FIND
    
    MODULE_FIND --> METHOD_SET
    METHOD_SET --> CUTOFF_CHECK
    
    style DSF fill:#e1f5fe
    style VALIDATION fill:#fff3e0
    style METHOD_SET fill:#e8f5e8
```

**Sources:** [jit/aimnet2_wrapper.py:74-95](), [jit/aimnet2_wrapper.py:100-104]()

### AimNet2Mbis Charge Prediction

The `AimNet2Mbis` class extends `AimNet2Wrapper` to use MBIS (Minimal Basis Iterative Stockholder) charge prediction instead of Hirshfeld charges:

```mermaid
graph LR
    subgraph "AimNet2Mbis Components"
        BASE["AimNet2Wrapper<br/>Base functionality"]
        ASSEMBLER["Assembler<br/>ANIq model builder"]
        CHARGE_NET["Charge Networks<br/>_ANINetworksDiscardFirstScalar"]
        NORMALIZER["ChargeNormalizer<br/>electronegativity_and_hardness"]
    end
    
    subgraph "State Dict Loading"
        ANI2X["ani2x_state_dict.pt<br/>AEV parameters"]
        CHARGE_DICT["charge_nn_state_dict.pt<br/>Charge network weights"]
    end
    
    subgraph "Execution Flow"
        AIMNET_FORWARD["_run_aimnet_forward()<br/>Energy calculation"]
        CHARGE_FORWARD["_charge_model.compute_from_neighbors()<br/>MBIS charges"]
        COMBINE["Combine results<br/>SpeciesEnergiesAtomicCharges"]
    end
    
    BASE --> ASSEMBLER
    ASSEMBLER --> CHARGE_NET
    CHARGE_NET --> NORMALIZER
    
    ANI2X --> CHARGE_NET
    CHARGE_DICT --> CHARGE_NET
    
    AIMNET_FORWARD --> CHARGE_FORWARD
    CHARGE_FORWARD --> COMBINE
    
    style CHARGE_NET fill:#e1f5fe
    style COMBINE fill:#e8f5e8
```

**Sources:** [jit/aimnet2_wrapper.py:257-338](), [jit/aimnet2_wrapper.py:268-298]()

## Nutmeg Wrapper System

The `NutmegWrapper` class provides integration for Nutmeg neural network potentials, which use different atomic representations and units.

### Atomic Number Mapping

Nutmeg models use a specific mapping from atomic numbers to internal indices:

| Atomic Number | Element | Internal Index |
|---------------|---------|----------------|
| 1 | H | 0 |
| 6 | C | 3 |
| 7 | N | 4 |
| 8 | O | 5 |
| 9 | F | 6 |
| 16 | S | 11 |
| 17 | Cl | 12 |
| 35 | Br | 15 |
| 53 | I | 16 |

### Feature Engineering

```mermaid
graph TB
    subgraph "Input Processing"
        SPECIES_IN["Species Tensor<br/>Atomic numbers"]
        COORDS_IN["Coordinates<br/>Angstroms"]
        CHARGES_IN["Atomic Charges<br/>Gasteiger charges"]
    end
    
    subgraph "Feature Creation"
        TYPE_MAP["_types_map<br/>Z_NUM_IDX_MAP lookup"]
        ONE_HOT["One-hot encoding<br/>17 element types"]
        CHARGE_FEAT["Charge features<br/>_atomic_charges"]
    end
    
    subgraph "Model Input"
        NODE_ATTRS["node_attrs<br/>Concatenated features"]
        EDGE_INDEX["edge_index<br/>Neighbor pairs"]
        COORDINATES["coordinates<br/>Nanometers"]
        CELL_SHIFT["cell_shift_vector<br/>PBC shifts"]
    end
    
    SPECIES_IN --> TYPE_MAP
    TYPE_MAP --> ONE_HOT
    CHARGES_IN --> CHARGE_FEAT
    
    ONE_HOT --> NODE_ATTRS
    CHARGE_FEAT --> NODE_ATTRS
    COORDS_IN --> COORDINATES
    
    NODE_ATTRS --> MODEL_INPUT["Nutmeg Model"]
    EDGE_INDEX --> MODEL_INPUT
    COORDINATES --> MODEL_INPUT
    CELL_SHIFT --> MODEL_INPUT
    
    style TYPE_MAP fill:#fff3e0
    style NODE_ATTRS fill:#e1f5fe
    style MODEL_INPUT fill:#e8f5e8
```

**Sources:** [jit/nutmeg_wrapper.py:19-37](), [jit/nutmeg_wrapper.py:70-81](), [jit/nutmeg_wrapper.py:134-149]()

### Unit Conversion System

The Nutmeg wrapper handles multiple unit conversions:

| Conversion | Factor | Purpose |
|------------|--------|---------|
| kJ/mol → Hartree | `1 / HARTREE_TO_KJOULEMOL` | Energy units |
| Angstrom → Nanometer | `0.1` | Distance units |
| Cutoff scaling | `/self._angstrom_to_nm` | Neighbor list cutoff |

**Sources:** [jit/nutmeg_wrapper.py:54-56]()

## Common Interface Patterns

All model wrappers implement a consistent interface for integration with the TorchANI-Amber system.

### Standard Forward Method Signature

```python
def forward(
    self,
    species_coords: Tuple[Tensor, Tensor],
    cell: Optional[Tensor] = None,
    pbc: Optional[Tensor] = None,
    charge: int = 0,
    atomic: bool = False,
    ensemble_values: bool = False,
    _molecule_idxs: Optional[Tensor] = None,
) -> Union[SpeciesEnergiesAtomicCharges, Tuple[Tensor, Tensor]]
```

### Neighbor List Management

All wrappers use the `AdaptiveList` neighbor list implementation:

```mermaid
graph LR
    subgraph "Neighbor List Workflow"
        INIT["AdaptiveList()<br/>Initialize neighbor list"]
        COMPUTE["_nlist(cutoff, species, coords, cell, pbc)<br/>Compute neighbors"]
        FILTER["discard_inter_molecule_pairs()<br/>Optional molecule filtering"]
        PROCESS["Wrapper-specific processing<br/>Format conversion"]
    end
    
    INIT --> COMPUTE
    COMPUTE --> FILTER
    FILTER --> PROCESS
    
    style COMPUTE fill:#e1f5fe
    style FILTER fill:#fff3e0
    style PROCESS fill:#e8f5e8
```

**Sources:** [jit/aimnet2_wrapper.py:99](), [jit/aimnet2_wrapper.py:232-254](), [jit/nutmeg_wrapper.py:60](), [jit/nutmeg_wrapper.py:82-104]()

### JIT Compilation Support

Model wrappers support TorchScript compilation for deployment:

```python
# Example compilation pattern
model = AimNet2Wrapper.from_jit_file("model.pt")
scripted_model = torch.jit.script(model)
torch.jit.save(scripted_model, "compiled_model.pt")
```

**Sources:** [jit/aimnet2_wrapper.py:481-487](), [jit/nutmeg_wrapper.py:156-159]()

---