# Testing Framework

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/electro.cpp](src/electro.cpp)
- [src/electro.h](src/electro.h)
- [tests/generate_test_values.py](tests/generate_test_values.py)
- [tests/templates/input.mdin.jinja](tests/templates/input.mdin.jinja)
- [tests/test_amber_integration.py](tests/test_amber_integration.py)
- [tests/test_values_cpu_1ccx_ensemble.txt](tests/test_values_cpu_1ccx_ensemble.txt)
- [tests/test_values_cpu_1x_ensemble.txt](tests/test_values_cpu_1x_ensemble.txt)
- [tests/test_values_cpu_2x_ensemble.txt](tests/test_values_cpu_2x_ensemble.txt)
- [tests/test_values_cpu_dr_ensemble.txt](tests/test_values_cpu_dr_ensemble.txt)
- [tests/test_values_cpu_mbis_ensemble.txt](tests/test_values_cpu_mbis_ensemble.txt)
- [tests/test_values_cuda_1ccx_ensemble.txt](tests/test_values_cuda_1ccx_ensemble.txt)
- [tests/test_values_cuda_1x_ensemble.txt](tests/test_values_cuda_1x_ensemble.txt)
- [tests/test_values_cuda_2x_ensemble.txt](tests/test_values_cuda_2x_ensemble.txt)
- [tests/test_values_cuda_dr_ensemble.txt](tests/test_values_cuda_dr_ensemble.txt)
- [tests/test_values_cuda_mbis_ensemble.txt](tests/test_values_cuda_mbis_ensemble.txt)

</details>



## Overview

The TorchANI-Amber testing framework provides comprehensive integration testing for the entire system, validating the correctness of neural network potential calculations, Amber MD engine integration, and ML/MM coupling mechanisms. The framework systematically tests combinations of computational backends (CPU/CUDA), precision levels, molecular environments, and coupling protocols to ensure robust operation across diverse simulation scenarios.

For information about the build system that compiles the test executables, see [6.1](#6.1). For performance testing and benchmarking tools, see [5.2](#5.2).

## Test Configuration System

The testing framework uses a sophisticated configuration system based on dataclasses to systematically generate test scenarios across multiple dimensions of variability.

### Configuration Classes

The `RunConfig` class in [tests/test_amber_integration.py:44-75]() serves as the primary configuration container, composed of:

- `CudaConfig`: Controls GPU execution and CUAEV acceleration
- `MlmmConfig`: Defines ML/MM coupling protocols (`me` or `mbispol`)  
- Boolean flags for shake constraints, vacuum/explicit solvent, precision, and neighborlist options

```mermaid
graph TB
    subgraph "Configuration Generation"
        A["RunConfig"] --> B["CudaConfig"]
        A --> C["MlmmConfig"] 
        A --> D["Boolean Flags"]
        
        B --> B1["cuaev: bool"]
        C --> C1["protocol: me|mbispol"]
        C --> C2["use_torch_coupling: bool"]
        D --> D1["shake: bool"]
        D --> D2["vacuum: bool"]
        D --> D3["float64: bool"]
        D --> D4["use_amber_neighborlist: bool"]
    end
    
    subgraph "Test Matrix Generation"
        E["itertools.product()"] --> F["288 Base Combinations"]
        F --> G["Filter Logic"]
        G --> H["Final Test Configs"]
        
        G --> G1["Float64 Restrictions"]
        G --> G2["Neighborlist Compatibility"]
        G --> G3["Legacy Mode Filtering"]
    end
    
    A --> E
```

**Test Matrix Generation**

The framework generates test configurations using `itertools.product()` across all parameter combinations in [tests/test_amber_integration.py:87-110](), then applies filtering logic to remove invalid or unsupported combinations:

| Filter Type | Condition | Rationale |
|-------------|-----------|-----------|
| Float64 Restriction | Only MLMM + CUDA + CUAEV + Vacuum | Performance optimization |
| Neighborlist Incompatibility | No MLMM with Amber neighborlist | Not implemented |
| Vacuum FullML | No FullML + Vacuum + Amber neighborlist | Not applicable |

Sources: [tests/test_amber_integration.py:32-110]()

## Integration Test Suite

The test suite is organized into parameterized test methods that systematically validate different execution engines and coupling modes.

### Test Method Organization

```mermaid
graph TB
    subgraph "AmberIntegration Test Class"
        A["testPmemd()"] --> A1["Full ML Tests"]
        A --> A2["No Amber Neighborlist"]
        
        B["testPmemdFromNeighbors()"] --> B1["Full ML Tests"]
        B --> B2["With Amber Neighborlist"]
        
        C["testSander()"] --> C1["Standard Configurations"]
        C --> C2["No Torch Coupling"]
        
        D["testSanderFromNeighbors()"] --> D1["Full ML Tests"]
        D --> D2["With Amber Neighborlist"]
        
        E["testSanderTorchCoupledMLMM()"] --> E1["ML/MM Tests"]
        E --> E2["Torch Coupling Enabled"]
        
        F["testNetCDFWorks()"] --> F1["NetCDF Output Format"]
        F --> F2["Both pmemd and sander"]
    end
    
    subgraph "Test Execution Flow"
        G["_testPmemd()/_testSander()"] --> H["Generate Input Files"]
        H --> I["_run_engine()"]
        I --> J["Parse Output"]
        J --> K["Compare vs Expected"]
    end
    
    A --> G
    B --> G
    C --> G
    D --> G
    E --> G
```

### Input File Generation

Each test generates Amber input files using Jinja2 templates. The `input.mdin.jinja` template in [tests/templates/input.mdin.jinja:1-98]() supports both legacy and modern configuration formats:

**Template Structure:**
- Control namelist (`&cntrl`) with dynamics parameters
- QM/MM namelist (`&qmmm`) for ML/MM simulations  
- External potential namelist (`&extpot`) for full ML simulations
- TorchANI-specific namelist (`&ani`) with model and device configuration

Sources: [tests/test_amber_integration.py:127-243](), [tests/templates/input.mdin.jinja:1-98]()

## Test Execution Workflow

The test execution follows a standardized workflow that isolates each test case and validates outputs against expected results.

### Execution Pipeline

```mermaid
flowchart TD
    A["Test Method Entry"] --> B["Setup Temporary Directory"]
    B --> C["Render Jinja Template"]
    C --> D["Write input.mdin"]
    D --> E["Copy System Files"]
    E --> F["Execute Amber Engine"]
    F --> G["Parse Output Files"]
    G --> H["Load Expected Values"]
    H --> I["Numerical Comparison"]
    I --> J["Cleanup"]
    
    subgraph "File Operations"
        E --> E1["system.prmtop"]
        E --> E2["system.inpcrd"]
        F --> F1["system.mdout"]
        F --> F2["system.mdcrd"]
        F --> F3["*.dat files"]
        F --> F4["*.xyz files"]
    end
    
    subgraph "Validation Logic"
        I --> I1["assert_allclose()"]
        I --> I2["Tolerance Configuration"]
        I --> I3["Error Reporting"]
    end
```

### Engine Execution

The `_run_engine()` method in [tests/test_amber_integration.py:344-379]() handles subprocess execution of both `pmemd` and `sander` with standardized command-line arguments:

```
engine -i input.mdin -p system.prmtop -c system.inpcrd 
       -o system.mdout -r system.restart -x system.mdcrd 
       -inf system.mdinfo -O
```

Sources: [tests/test_amber_integration.py:151-379]()

## Test Data Generation and Validation

### Reference Data Generation

The `generate_test_values.py` script creates reference datasets by executing JIT-compiled neural network models directly through PyTorch:

```mermaid
graph LR
    subgraph "Model Execution"
        A["JIT Model Files"] --> B["torch.jit.load()"]
        B --> C["Test Coordinates"]
        C --> D["Forward Pass"]
        D --> E["Energy Calculation"]
        E --> F["Force Derivatives"]
    end
    
    subgraph "Output Generation"
        F --> G["Energy Values"]
        F --> H["Force Components"]
        F --> I["Atomic Charges"]
        F --> J["Charge Derivatives"]
    end
    
    subgraph "File Output"
        G --> K["test_values_cpu_*.txt"]
        H --> K
        I --> K
        J --> K
        
        G --> L["test_values_cuda_*.txt"]
        H --> L
        I --> L
        J --> L
    end
```

**Test Value Files Structure:**
Each `.txt` file contains numerical values in sequence:
1. Energy (kcal/mol)
2. Force components (3 × num_atoms)
3. QBC values (for ensemble models)
4. QBC derivatives (for ensemble models)  
5. Atomic charges (for charge-predicting models)
6. Charge derivatives (for charge-predicting models)

### Tolerance Configuration

The validation system applies different numerical tolerances based on computational context:

| Configuration | rtol | atol | Rationale |
|---------------|------|------|-----------|
| CPU Standard | 1e-7 | 1e-5 | High precision baseline |
| CUDA Standard | 0.0 | 1.0002e-3 | GPU numerical differences |
| Amber Neighborlist | 0.0005 | 1.5e-3 | Mapping approximations |

Sources: [tests/test_amber_integration.py:183-194](), [tests/test_amber_integration.py:301-312](), [tests/generate_test_values.py:13-119]()

## Environment Variables and Controls

The testing framework provides several environment variables for debugging and development workflows:

### Control Variables

| Variable | Effect | Use Case |
|----------|--------|----------|
| `TORCHANI_AMBER_KEEP_TEST_DIRS=1` | Preserve test directories | Debugging failed tests |
| `TORCHANI_AMBER_OVERWRITE_EXPECTED=1` | Update expected output files | Creating new baselines |
| `TORCHANI_AMBER_LEGACY_TEST=1` | Enable legacy compatibility mode | Testing older branches |

### Output Parsing and Comparison

The `parse_amber_output()` method in [tests/test_amber_integration.py:334-342]() handles different output formats:

- **XYZ format**: Filters out comment lines containing "TORCHANI"
- **MDCRD format**: Removes header line with filename
- **DAT format**: Direct numerical parsing

Sources: [tests/test_amber_integration.py:1-10](), [tests/test_amber_integration.py:152-157](), [tests/test_amber_integration.py:195-202]()

## Test Coverage Matrix

The parameterized testing approach ensures comprehensive coverage across the configuration space:

```mermaid
graph TB
    subgraph "Execution Engines"
        A["pmemd"] --> A1["Full ML"]
        A --> A2["From Neighbors"]
        B["sander"] --> B1["Standard"]
        B --> B2["From Neighbors"] 
        B --> B3["Torch Coupled MLMM"]
    end
    
    subgraph "Configuration Dimensions"
        C["Hardware"] --> C1["CPU"]
        C --> C2["CUDA"]
        C --> C3["CUAEV"]
        
        D["Precision"] --> D1["Float32"]
        D --> D2["Float64"]
        
        E["Environment"] --> E1["Vacuum"]
        E --> E2["Explicit Solvent"]
        
        F["Constraints"] --> F1["SHAKE"]
        F --> F2["No SHAKE"]
        
        G["Coupling"] --> G1["Full ML"]
        G --> G2["ME Protocol"]
        G --> G3["MBISPOL Protocol"]
    end
    
    subgraph "Output Validation"
        H["Numerical Comparison"] --> H1["Energy Values"]
        H --> H2["Force Components"]
        H --> H3["Atomic Charges"]
        H --> H4["Charge Derivatives"]
    end
```

Sources: [tests/test_amber_integration.py:77-110](), [tests/test_amber_integration.py:135-266]()

---