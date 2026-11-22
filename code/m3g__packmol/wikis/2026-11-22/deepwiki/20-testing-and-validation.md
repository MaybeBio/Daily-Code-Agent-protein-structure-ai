# Testing and Validation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/actions.yml](.github/workflows/actions.yml)
- [testing/Project.toml](testing/Project.toml)
- [testing/input_files/bilayer_pbc.inp](testing/input_files/bilayer_pbc.inp)
- [testing/input_files/mixture_pbc.inp](testing/input_files/mixture_pbc.inp)
- [testing/input_files/protein_outside_pbc_error.inp](testing/input_files/protein_outside_pbc_error.inp)
- [testing/input_files/toy_with_fixed.inp](testing/input_files/toy_with_fixed.inp)
- [testing/input_files/water_box_pbc2.inp](testing/input_files/water_box_pbc2.inp)
- [testing/input_files/water_box_pbc_outside_box.inp](testing/input_files/water_box_pbc_outside_box.inp)
- [testing/install_julia.sh](testing/install_julia.sh)
- [testing/runtests.jl](testing/runtests.jl)
- [testing/test.sh](testing/test.sh)
- [testing/test_cli.sh](testing/test_cli.sh)

</details>



## Purpose and Scope

This document provides an overview of Packmol's comprehensive testing infrastructure, which validates both the correctness of molecular packing results and the robustness of the software interface. The testing system employs a multi-layered validation strategy combining Julia-based physical validation, shell-based interface testing, and continuous integration orchestration.

For detailed information about specific test components, see:
- Julia-based minimum distance validation: [5.1](#5.1)
- Shell-based interface and error handling tests: [5.2](#5.2)
- CI/CD pipeline configuration: [5.3](#5.3)

## Testing Architecture Overview

Packmol's testing system is organized as a hierarchical test orchestration framework with three primary validation layers:

```mermaid
graph TB
    subgraph "Test Orchestration Layer"
        TEST_SH["test.sh<br/>Main Test Orchestrator"]
        CI["GitHub Actions<br/>.github/workflows/actions.yml"]
    end
    
    subgraph "Physical Validation Layer"
        RUNTESTS["runtests.jl<br/>Julia Test Runner"]
        CHECK_MIND["check_mind()<br/>Distance Validator"]
        PDBTOOLS["PDBTools.jl<br/>PDB Parser"]
        CELLLIST["CellListMap.jl<br/>Distance Calculator"]
    end
    
    subgraph "Interface Validation Layer"
        TEST_CLI["test_cli.sh<br/>CLI Consistency Tests"]
        TEST_FAILED["test_failed.sh<br/>Error Handling Tests"]
        TEST_CONNECT["test_connectivity.sh<br/>Connectivity Tests"]
    end
    
    subgraph "Test Inputs"
        BASIC_INP["Basic Inputs<br/>water_box.inp<br/>mixture.inp"]
        PBC_INP["PBC Inputs<br/>water_box_pbc*.inp<br/>bilayer_pbc.inp"]
        ERROR_INP["Error Cases<br/>*_failed.inp<br/>*_error.inp"]
    end
    
    subgraph "Validation Criteria"
        MIN_DIST["Minimum Distance<br/>mind >= tolerance * (1-precision)"]
        SUCCESS_MSG["Success Message<br/>Search for 'Success!'"]
        OUTPUT_CONSISTENCY["Output Consistency<br/>diff between invocations"]
        ERROR_HANDLING["Error Detection<br/>Expected failure patterns"]
    end
    
    subgraph "Build Systems Tested"
        MAKE_BUILD["make compiler"]
        CMAKE_BUILD["cmake compiler"]
    end
    
    CI --> TEST_SH
    TEST_SH --> RUNTESTS
    TEST_SH --> TEST_CLI
    TEST_SH --> TEST_FAILED
    TEST_SH --> TEST_CONNECT
    
    RUNTESTS --> CHECK_MIND
    CHECK_MIND --> PDBTOOLS
    CHECK_MIND --> CELLLIST
    
    BASIC_INP --> RUNTESTS
    PBC_INP --> RUNTESTS
    BASIC_INP --> TEST_CLI
    ERROR_INP --> TEST_FAILED
    
    CHECK_MIND --> MIN_DIST
    RUNTESTS --> SUCCESS_MSG
    TEST_CLI --> OUTPUT_CONSISTENCY
    TEST_FAILED --> ERROR_HANDLING
    
    CI --> MAKE_BUILD
    CI --> CMAKE_BUILD
    MAKE_BUILD --> TEST_SH
    CMAKE_BUILD --> TEST_SH
```

**Test Execution Flow**

The testing system follows a staged execution model where each stage validates different aspects of functionality.

Sources: [testing/test.sh:1-35](), [.github/workflows/actions.yml:1-46]()

## Test Orchestration

The main test orchestration is handled by `test.sh`, which executes tests in a specific sequence designed to validate progressively complex scenarios:

```mermaid
flowchart TD
    START["CI Triggers Test Suite"] --> SETUP["install_julia.sh<br/>Setup Julia Environment"]
    SETUP --> TEST_SH["test.sh Entry Point"]
    
    TEST_SH --> JULIA_TESTS["Julia Test Suite<br/>Lines 8-24"]
    
    subgraph "Julia Tests - runtests.jl"
        JULIA_TESTS --> BASIC["Basic Tests<br/>water_box.inp<br/>ieee_signaling.inp<br/>mixture.inp"]
        JULIA_TESTS --> FIXED["Fixed Molecule Tests<br/>toy_with_fixed.inp<br/>only_one_fixed.inp"]
        JULIA_TESTS --> SPATIAL["Spatial Constraint Tests<br/>spherical.inp<br/>bilayer.inp<br/>solvprotein.inp"]
        JULIA_TESTS --> PBC["PBC Test Suite<br/>8 PBC input files"]
    end
    
    BASIC --> VALIDATE_BASIC["Validate: mind >= tolerance"]
    FIXED --> VALIDATE_FIXED["Validate: mind >= tolerance"]
    SPATIAL --> VALIDATE_SPATIAL["Validate: mind >= tolerance"]
    PBC --> VALIDATE_PBC["Validate: mind >= tolerance<br/>with unitcell wrapping"]
    
    VALIDATE_BASIC --> FAILED_TESTS
    VALIDATE_FIXED --> FAILED_TESTS
    VALIDATE_SPATIAL --> FAILED_TESTS
    VALIDATE_PBC --> FAILED_TESTS
    
    FAILED_TESTS["Error Handling Tests<br/>Lines 26-28"] --> FAILED1["test_failed.sh<br/>water_box_failed.inp<br/>Check for 'FORCED' in log"]
    FAILED_TESTS --> FAILED2["test_failed.sh<br/>protein_outside_pbc_error.inp<br/>Check for 'outside' in log"]
    
    FAILED1 --> CONNECTIVITY
    FAILED2 --> CONNECTIVITY
    
    CONNECTIVITY["Connectivity Test<br/>Line 31<br/>test_connectivity.sh"] --> CLI_TESTS
    
    CLI_TESTS["CLI Validation<br/>Line 34<br/>test_cli.sh ../packmol"] --> CLI_METHOD1["stdin redirection<br/>packmol < input.txt"]
    CLI_TESTS --> CLI_METHOD2["-i flag<br/>packmol -i input.tmp"]
    CLI_TESTS --> CLI_METHOD3["-i and -o flags<br/>packmol -i input.txt -o output.txt"]
    
    CLI_METHOD1 --> DIFF["diff Output Files<br/>Verify Identical Results"]
    CLI_METHOD2 --> DIFF
    CLI_METHOD3 --> DIFF
    
    DIFF --> SUCCESS["All Tests Pass<br/>exit 0"]
    
    DIFF -->|"Differences Found"| FAIL["Test Failure<br/>exit 1"]
    VALIDATE_BASIC -->|"mind < threshold"| FAIL
    FAILED1 -->|"Pattern Not Found"| FAIL
```

**Execution Stages**

Sources: [testing/test.sh:1-35]()

## Test Categories and Input Files

The test suite includes 17+ input files organized into functional categories:

| Category | Input Files | Purpose |
|----------|-------------|---------|
| **Basic Functionality** | `water_box.inp`<br/>`mixture.inp`<br/>`ieee_signaling.inp` | Validate core packing without PBC or special constraints |
| **Fixed Molecules** | `toy_with_fixed.inp`<br/>`only_one_fixed.inp` | Test molecules with `fixed` keyword holding positions constant |
| **Spatial Constraints** | `spherical.inp`<br/>`bilayer.inp`<br/>`solvprotein.inp` | Test geometric constraints (inside/outside regions) |
| **Periodic Boundaries** | `water_box_pbc.inp`<br/>`water_box_pbc2.inp`<br/>`water_box_pbc_negative_coordinates.inp`<br/>`water_box_pbc_slab.inp`<br/>`water_box_pbc_outside_box.inp` | Validate PBC with various coordinate configurations |
| **Complex PBC Systems** | `mixture_pbc.inp`<br/>`bilayer_pbc.inp`<br/>`solvprotein_pbc.inp`<br/>`spherical_pbc.inp` | Test PBC combined with constraints |
| **Error Handling** | `water_box_failed.inp`<br/>`protein_outside_pbc_error.inp` | Validate error detection and reporting |

Sources: [testing/test.sh:8-24](), [testing/input_files/water_box_pbc_outside_box.inp:1-20](), [testing/input_files/mixture_pbc.inp:1-22]()

## Validation Criteria and Mechanisms

The testing system validates multiple dimensions of correctness:

```mermaid
graph TB
    subgraph "Physical Correctness Validation"
        PARSE_INPUT["Parse Input File<br/>runtests.jl:39-55"]
        EXTRACT_TOL["Extract tolerance value<br/>Line 43"]
        EXTRACT_OUTPUT["Extract output filename<br/>Line 44"]
        EXTRACT_PBC["Extract PBC parameters<br/>Lines 46-53"]
        EXTRACT_PRECISION["Extract precision<br/>Line 45"]
        
        READ_PDB["Read Output PDB<br/>PDBTools.readPDB<br/>Line 59"]
        BUILD_SYSTEM["Build ParticleSystem<br/>CellListMap<br/>Lines 60-65"]
        
        CALC_MIND["Calculate Minimum Distance<br/>map_pairwise + update_mind<br/>Line 66"]
        UPDATE_MIND["update_mind Function<br/>Lines 25-29<br/>Skip same residue<br/>Track minimum"]
        
        CHECK_THRESHOLD["Verify Threshold<br/>mind >= tolerance * (1-precision)<br/>Lines 67-74"]
    end
    
    subgraph "Interface Consistency Validation"
        PATCH_INPUT["Patch Input Files<br/>test_cli.sh:149-154<br/>Fix seed to 1024<br/>Change output filename"]
        
        RUN_STDIN["Run: packmol < input<br/>Line 178"]
        RUN_I_FLAG["Run: packmol -i input<br/>Line 193"]
        RUN_IO_FLAGS["Run: packmol -i input -o output<br/>Line 204"]
        
        DIFF_CHECK["diff Utility Comparison<br/>Lines 217-218<br/>Count bytes in diff output"]
        VERIFY_ZERO["Verify 0 bytes difference<br/>Line 219"]
    end
    
    subgraph "Error Handling Validation"
        RUN_FAILED["Execute Expected-to-Fail Input<br/>test_failed.sh"]
        CAPTURE_LOG["Capture packmol.log<br/>Redirect output"]
        SEARCH_PATTERN["Search for Error Pattern<br/>grep for expected message"]
        VERIFY_PATTERN["Verify Pattern Found<br/>Confirm proper error reporting"]
    end
    
    PARSE_INPUT --> EXTRACT_TOL
    PARSE_INPUT --> EXTRACT_OUTPUT
    PARSE_INPUT --> EXTRACT_PBC
    PARSE_INPUT --> EXTRACT_PRECISION
    
    EXTRACT_OUTPUT --> READ_PDB
    READ_PDB --> BUILD_SYSTEM
    EXTRACT_PBC --> BUILD_SYSTEM
    EXTRACT_TOL --> BUILD_SYSTEM
    
    BUILD_SYSTEM --> CALC_MIND
    CALC_MIND --> UPDATE_MIND
    UPDATE_MIND --> CALC_MIND
    
    CALC_MIND --> CHECK_THRESHOLD
    EXTRACT_TOL --> CHECK_THRESHOLD
    EXTRACT_PRECISION --> CHECK_THRESHOLD
    
    CHECK_THRESHOLD -->|"Pass"| SUCCESS_PHYS["Print OK<br/>Line 76"]
    CHECK_THRESHOLD -->|"Fail"| ERROR_PHYS["Throw Error<br/>Lines 68-74"]
    
    PATCH_INPUT --> RUN_STDIN
    PATCH_INPUT --> RUN_I_FLAG
    PATCH_INPUT --> RUN_IO_FLAGS
    
    RUN_STDIN --> DIFF_CHECK
    RUN_I_FLAG --> DIFF_CHECK
    RUN_IO_FLAGS --> DIFF_CHECK
    
    DIFF_CHECK --> VERIFY_ZERO
    VERIFY_ZERO -->|"Pass"| SUCCESS_CLI["Print OK<br/>Line 220"]
    VERIFY_ZERO -->|"Fail"| ERROR_CLI["Exit with Error<br/>Lines 222-228"]
    
    RUN_FAILED --> CAPTURE_LOG
    CAPTURE_LOG --> SEARCH_PATTERN
    SEARCH_PATTERN --> VERIFY_PATTERN
```

**Distance Validation Algorithm**

The `check_mind()` function implements a sophisticated validation algorithm:

1. **Parse Input**: Extract `tolerance`, `output`, `pbc`, and `precision` keywords from input file [testing/runtests.jl:39-55]()
2. **Read Structure**: Parse generated PDB using PDBTools [testing/runtests.jl:59]()
3. **Build Cell System**: Create `ParticleSystem` with cutoff = `tolerance * 1.5` for efficient neighbor search [testing/runtests.jl:60-65]()
4. **Calculate Minimum Distance**: Use `map_pairwise()` with custom reducer to find minimum inter-molecular distance [testing/runtests.jl:66]()
5. **Validate Threshold**: Ensure `mind >= tolerance * (1 - precision)` [testing/runtests.jl:67-74]()

The `update_mind()` function ensures molecules are identified by residue number, skipping intra-molecular atom pairs [testing/runtests.jl:25-29]().

Sources: [testing/runtests.jl:34-78]()

## Minimum Distance Calculation Subsystem

The validation system leverages Julia's CellListMap package for O(N) complexity distance calculations:

```mermaid
graph LR
    subgraph "MinimumDistance Type"
        MIND_STRUCT["struct MinimumDistance<br/>i: atom index<br/>j: atom index<br/>d: distance<br/>Lines 20-24"]
    end
    
    subgraph "CellListMap Integration"
        PARTICLE_SYS["ParticleSystem<br/>positions: from PDB<br/>unitcell: PBC box<br/>cutoff: tolerance*1.5<br/>output: MinimumDistance"]
        
        MAP_PAIRWISE["map_pairwise()<br/>Parallel cell-based search"]
        
        UPDATE_MIND_FUNC["update_mind(i,j,d2,pdb,md)<br/>Skip same residue<br/>Track minimum<br/>Lines 25-29"]
        
        REDUCER["reducer(md1,md2)<br/>Return minimum<br/>Line 30"]
        
        COPY_OUT["copy_output(md)<br/>Line 31"]
        RESET_OUT["reset_output()<br/>Initialize to +Inf<br/>Line 32"]
    end
    
    subgraph "Validation Logic"
        THRESHOLD["Threshold Check<br/>mind.d >= (1-precision)*tolerance<br/>Line 67"]
        ERROR_REPORT["Error Report<br/>Include atom indices<br/>VMD-compatible indices<br/>Lines 68-74"]
    end
    
    MIND_STRUCT --> PARTICLE_SYS
    PARTICLE_SYS --> MAP_PAIRWISE
    MAP_PAIRWISE --> UPDATE_MIND_FUNC
    UPDATE_MIND_FUNC --> REDUCER
    REDUCER --> MAP_PAIRWISE
    COPY_OUT --> MAP_PAIRWISE
    RESET_OUT --> MAP_PAIRWISE
    
    MAP_PAIRWISE --> THRESHOLD
    THRESHOLD -->|"Fail"| ERROR_REPORT
```

Sources: [testing/runtests.jl:20-32](), [testing/runtests.jl:60-74]()

## CLI Consistency Testing Mechanism

The `test_cli.sh` script validates that all three command-line interface methods produce identical output:

| Invocation Method | Command Syntax | Output File Source |
|-------------------|----------------|-------------------|
| **Standard Input** | `packmol < input.txt` | Specified in `output` keyword in input file |
| **Input Flag** | `packmol -i input.tmp` | Specified in `output` keyword in input file |
| **Input and Output Flags** | `packmol -i input.txt -o output.txt` | Overridden by `-o` flag |

**Test Procedure**:
1. Filter input files to exclude `*_error.inp` and `*_fail*.inp` patterns [testing/test_cli.sh:124]()
2. Patch input files: replace `seed -1` with `seed 1024` for reproducibility [testing/test_cli.sh:150]()
3. Create three variants with different output filenames [testing/test_cli.sh:152]()
4. Execute packmol using each invocation method [testing/test_cli.sh:178,193,204]()
5. Use GNU `diff` to compare output files byte-by-byte [testing/test_cli.sh:217-218]()
6. Verify zero byte difference (identical files) [testing/test_cli.sh:219]()

Sources: [testing/test_cli.sh:1-241]()

## Error Handling Test Pattern

The `test_failed.sh` script validates that Packmol correctly detects and reports specific error conditions:

```mermaid
sequenceDiagram
    participant TEST as test.sh
    participant FAILED as test_failed.sh
    participant PACKMOL as packmol binary
    participant LOG as packmol.log
    
    TEST->>FAILED: Execute with input file and pattern
    Note over TEST,FAILED: test_failed.sh input.inp log "PATTERN"
    
    FAILED->>PACKMOL: Run with failing input
    PACKMOL->>LOG: Write error messages
    PACKMOL->>FAILED: Exit with error code
    
    FAILED->>LOG: grep for expected pattern
    alt Pattern Found
        LOG->>FAILED: Pattern match
        FAILED->>TEST: Return success (error properly detected)
    else Pattern Not Found
        LOG->>FAILED: No match
        FAILED->>TEST: Return failure (error not detected)
    end
```

**Test Cases**:
1. `water_box_failed.inp` → Expect "FORCED" in log [testing/test.sh:27]()
2. `protein_outside_pbc_error.inp` → Expect "outside" in log [testing/test.sh:28]()

Sources: [testing/test.sh:26-28]()

## Continuous Integration Configuration

The GitHub Actions workflow orchestrates testing across multiple platforms and compiler configurations:

| Matrix Dimension | Values | Purpose |
|------------------|--------|---------|
| **Operating System** | `ubuntu-latest`, `macOS-latest` | Cross-platform validation |
| **GCC Version** | `13` | Consistent compiler version |
| **Build System** | `make`, `cmake` | Validate both build systems |

**Pipeline Stages**:
1. **Checkout**: Retrieve code from repository [.github/workflows/actions.yml:20]()
2. **Setup Fortran**: Install GCC 13 using `fortran-lang/setup-fortran` [.github/workflows/actions.yml:21-25]()
3. **Compile (make)**: Run `./configure && make` [.github/workflows/actions.yml:27-32]()
4. **Compile (cmake)**: Run `cmake ./ && cmake --build ./` [.github/workflows/actions.yml:34-38]()
5. **Test**: Execute `install_julia.sh` followed by `test.sh` [.github/workflows/actions.yml:40-45]()

This creates 4 test jobs per push: (ubuntu×make, ubuntu×cmake, macOS×make, macOS×cmake), with failure isolation via `fail-fast: false` [.github/workflows/actions.yml:11]().

Sources: [.github/workflows/actions.yml:1-46]()

## Test Input File Requirements

For Julia validation tests to function correctly, PDB files must adhere to specific structural requirements:

**Structural Constraints**:
- Each molecule must be identified as a single residue [testing/runtests.jl:7-11]()
- Proteins must have one residue name for all atoms
- Residue numbers can be overwritten using the `resnumbers` option in input files
- The `update_mind()` function uses `residue(pdb[i]) == residue(pdb[j])` to skip intra-molecular pairs [testing/runtests.jl:26]()

**Input File Parameters Parsed**:
- `tolerance`: Required minimum distance between molecules [testing/runtests.jl:43]()
- `output`: Required output filename [testing/runtests.jl:44]()
- `precision`: Optional, defaults to 0.01 [testing/runtests.jl:45]()
- `pbc`: Optional, can specify 3 values (box size) or 6 values (min/max bounds) [testing/runtests.jl:46-53]()

Sources: [testing/runtests.jl:6-56](), [testing/input_files/toy_with_fixed.inp:1-27]()

## Test Execution Environment Setup

The test environment requires Julia with specific package dependencies:

```mermaid
graph TD
    INSTALL_SH["install_julia.sh<br/>Lines 1-9"] --> CHECK_JULIAUP{"juliaup exists?"}
    CHECK_JULIAUP -->|Yes| SKIP["Use existing Julia"]
    CHECK_JULIAUP -->|No| DOWNLOAD["curl install.julialang.org<br/>Download juliaup.sh"]
    DOWNLOAD --> CHMOD["chmod +x juliaup.sh"]
    CHMOD --> INSTALL["./juliaup.sh -y<br/>Install Julia"]
    
    SKIP --> RUNTESTS_INIT
    INSTALL --> RUNTESTS_INIT
    
    RUNTESTS_INIT["runtests.jl Initialization<br/>Lines 1-2"] --> PKG_ACTIVATE["Pkg.activate(@__DIR__)<br/>Activate test environment"]
    PKG_ACTIVATE --> PKG_INSTALL["Pkg.instantiate()<br/>Install dependencies"]
    
    PKG_INSTALL --> DEPS["Project.toml Dependencies<br/>PDBTools.jl<br/>CellListMap.jl"]
```

**Dependencies** [testing/Project.toml:1-4]():
- `PDBTools`: Parse and manipulate PDB files
- `CellListMap`: Efficient O(N) distance calculations with cell lists

Sources: [testing/install_julia.sh:1-9](), [testing/runtests.jl:1-4](), [testing/Project.toml:1-4]()

---