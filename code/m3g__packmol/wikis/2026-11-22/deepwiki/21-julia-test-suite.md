# Julia Test Suite

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

</details>



## Purpose and Scope

The Julia Test Suite is Packmol's primary validation layer that performs deep structural analysis of generated molecular packings. It executes Packmol, parses the output PDB files, and validates that inter-molecular minimum distances meet specified tolerance requirements within numerical precision bounds. This test suite uses the PDBTools.jl library for PDB parsing and CellListMap.jl for efficient O(N) distance calculations with periodic boundary condition support.

For information about shell-based CLI and error handling tests, see [Shell Test Scripts](#5.2). For the overall CI/CD orchestration, see [Continuous Integration](#5.3).

## Architecture Overview

The Julia test infrastructure consists of three main components: a test orchestrator script, a minimum distance validation function, and a collection of input test cases spanning basic scenarios to complex biological systems.

```mermaid
graph TB
    subgraph "Test Orchestration"
        test_sh["test.sh<br/>Shell orchestrator"]
        install_julia["install_julia.sh<br/>Julia setup"]
        julia_exe["~/.juliaup/bin/julia<br/>Julia executable"]
    end
    
    subgraph "runtests.jl [Core Test Runner]"
        main_loop["Main loop: for input_test in ARGS"]
        run_packmol["run(pipeline(`packmol`;<br/>stdin=input_test, stdout=log))"]
        success_check["occursin('Success!', String(take!(log)))"]
        check_mind_call["check_mind(input_test)"]
    end
    
    subgraph "check_mind Function [Validator]"
        parse_input["Parse input file:<br/>- tolerance keyword<br/>- output keyword<br/>- pbc keyword<br/>- precision keyword"]
        read_pdb["readPDB(output_name)<br/>PDBTools.jl"]
        create_sys["ParticleSystem(<br/>positions, unitcell,<br/>cutoff, output)"]
        map_pairwise["map_pairwise(<br/>update_mind, sys)"]
        validate["mind.d >= (1-precision)*tolerance"]
    end
    
    subgraph "MinimumDistance [Data Structure]"
        mind_struct["struct MinimumDistance<br/>i: Int (atom index)<br/>j: Int (atom index)<br/>d: Float64 (distance)"]
        update_mind["update_mind(i, j, d2, pdb, md)<br/>Skip same residue<br/>Update if d < md.d"]
        reducer["CellListMap.reducer<br/>Select minimum"]
    end
    
    subgraph "Test Input Files"
        basic["water_box.inp<br/>mixture.inp<br/>spherical.inp"]
        pbc["water_box_pbc*.inp<br/>bilayer_pbc.inp<br/>solvprotein_pbc.inp"]
        complex["bilayer.inp<br/>solvprotein.inp<br/>toy_with_fixed.inp"]
        edge["ieee_signaling.inp<br/>only_one_fixed.inp"]
    end
    
    test_sh --> install_julia
    install_julia --> julia_exe
    test_sh --> main_loop
    julia_exe --> main_loop
    
    main_loop --> run_packmol
    run_packmol --> success_check
    success_check -->|"Success!"| check_mind_call
    success_check -->|No success| error["error('Failed packing')"]
    
    check_mind_call --> parse_input
    parse_input --> read_pdb
    read_pdb --> create_sys
    create_sys --> map_pairwise
    map_pairwise --> update_mind
    update_mind --> reducer
    reducer --> mind_struct
    mind_struct --> validate
    validate -->|Pass| ok["printstyled(' OK.', color=:green)"]
    validate -->|Fail| error_mind["error('minimum distance not correct')"]
    
    basic --> main_loop
    pbc --> main_loop
    complex --> main_loop
    edge --> main_loop
    
    style main_loop fill:#f9f9f9
    style check_mind_call fill:#f9f9f9
    style map_pairwise fill:#f9f9f9
    style validate fill:#f9f9f9
```

**Sources:** [testing/test.sh:1-35](), [testing/runtests.jl:1-109](), [testing/install_julia.sh:1-9]()

## Test Execution Flow

### Test Orchestration

The test suite is launched by `test.sh`, which sets up the Julia environment and invokes `runtests.jl` with a list of input files to test.

```mermaid
sequenceDiagram
    participant CI as GitHub Actions
    participant test_sh as test.sh
    participant install as install_julia.sh
    participant juliaup as juliaup
    participant runtests as runtests.jl
    participant packmol as packmol binary
    
    CI->>test_sh: Execute ./test.sh
    test_sh->>install: ./install_julia.sh
    install->>juliaup: Check if juliaup exists
    alt juliaup not found
        install->>juliaup: curl install.julialang.org
        install->>juliaup: ./juliaup.sh -y
    end
    
    test_sh->>runtests: $julia_exe runtests.jl [input files...]
    Note over runtests: Parse -packmol argument<br/>Default: ../packmol
    
    loop For each input file
        runtests->>packmol: run(pipeline(`packmol`; stdin=input_file))
        packmol-->>runtests: stdout log
        runtests->>runtests: Check for "Success!" in log
        alt Success found
            runtests->>runtests: check_mind(input_file)
        else No success
            runtests->>runtests: error("Failed packing")
        end
    end
    
    runtests-->>test_sh: Exit status
    test_sh-->>CI: Test results
```

The test script accepts an optional `-packmol` argument to specify the path to the Packmol executable. If not provided, it defaults to `../packmol` relative to the testing directory.

**Sources:** [testing/test.sh:5-24](), [testing/runtests.jl:81-106]()

### Input File Coverage

The test suite covers 17 distinct input files representing various molecular packing scenarios:

| Category | Input Files | Purpose |
|----------|-------------|---------|
| Basic Systems | `water_box.inp`, `mixture.inp`, `spherical.inp` | Simple packings without PBC |
| Periodic Boundary | `water_box_pbc.inp`, `water_box_pbc2.inp`, `mixture_pbc.inp` | Standard PBC configurations |
| PBC Edge Cases | `water_box_pbc_negative_coordinates.inp`, `water_box_pbc_outside_box.inp`, `water_box_pbc_slab.inp` | Negative coords, outside box, slab geometry |
| Complex Biological | `bilayer.inp`, `bilayer_pbc.inp`, `solvprotein.inp`, `solvprotein_pbc.inp` | Lipid bilayers, solvated proteins |
| Fixed Molecules | `toy_with_fixed.inp`, `only_one_fixed.inp` | Systems with fixed molecular positions |
| Numerical Edge Cases | `ieee_signaling.inp`, `spherical_pbc.inp` | IEEE floating-point handling, spherical constraints with PBC |

**Sources:** [testing/test.sh:8-24]()

## Minimum Distance Validation

### The `check_mind` Function

The core validation logic is implemented in the `check_mind` function, which performs a multi-step validation process:

```mermaid
graph TB
    start["check_mind(input_file)"] --> init["Initialize:<br/>tolerance = nothing<br/>output_name = nothing<br/>unitcell = nothing<br/>precision = 0.01"]
    
    init --> parse_loop["Parse input file line by line"]
    
    parse_loop --> extract_tol["Extract 'tolerance' value"]
    parse_loop --> extract_out["Extract 'output' filename"]
    parse_loop --> extract_prec["Extract 'precision' value<br/>(default: 0.01)"]
    parse_loop --> extract_pbc["Extract 'pbc' parameters"]
    
    extract_pbc --> pbc_3["3 values → pbc 0 0 0 lx ly lz<br/>unitcell = [lx, ly, lz]"]
    extract_pbc --> pbc_6["6 values → pbc x0 y0 z0 x1 y1 z1<br/>unitcell = [x1-x0, y1-y0, z1-z0]"]
    
    extract_tol --> validate_parsed["Validate tolerance and<br/>output_name exist"]
    extract_out --> validate_parsed
    extract_prec --> validate_parsed
    pbc_3 --> validate_parsed
    pbc_6 --> validate_parsed
    
    validate_parsed -->|Missing| error_parse["error('tolerance or output not found')"]
    validate_parsed -->|Valid| read["readPDB(output_name)<br/>PDBTools.jl"]
    
    read --> create_sys["ParticleSystem(<br/>positions = coor.(pdb),<br/>unitcell = unitcell,<br/>cutoff = tolerance * 1.5,<br/>output = MinimumDistance(0,0,+Inf))"]
    
    create_sys --> map["mind = map_pairwise(<br/>(x,y,i,j,d2,md) → update_mind(i,j,d2,pdb,md),<br/>sys)"]
    
    map --> check["mind.d >= (1-precision)*tolerance"]
    
    check -->|Fail| error_dist["error('minimum distance not correct<br/>Obtained: mind.d<br/>Expected: >= (1-precision)*tolerance<br/>Atoms: mind.i and mind.j')"]
    
    check -->|Pass| success["printstyled(' OK.', color=:green, bold=true)"]
    
    style create_sys fill:#f9f9f9
    style map fill:#f9f9f9
    style check fill:#f9f9f9
```

**Sources:** [testing/runtests.jl:34-78]()

### Input File Parsing

The function parses the input file to extract key parameters:

- **`tolerance`**: The minimum allowed inter-molecular distance
- **`output`**: The output PDB filename to validate
- **`precision`**: Tolerance precision factor (default: 0.01 if not specified)
- **`pbc`**: Periodic boundary condition box dimensions

The PBC parameter can be specified in two formats:
- 3 values: `pbc lx ly lz` (box from origin)
- 6 values: `pbc x0 y0 z0 x1 y1 z1` (explicit box bounds)

**Sources:** [testing/runtests.jl:39-55]()

### Distance Calculation with CellListMap

The minimum distance calculation leverages the CellListMap.jl library, which provides O(N) scaling through cell list spatial partitioning. The system is configured with:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `positions` | `coor.(pdb)` | Cartesian coordinates from PDB file |
| `unitcell` | Parsed from `pbc` keyword | Box dimensions for PBC wrapping |
| `cutoff` | `tolerance * 1.5` | Interaction cutoff radius |
| `output` | `MinimumDistance(0, 0, +Inf)` | Initial output structure |

The `map_pairwise` function efficiently computes pairwise interactions by only evaluating atom pairs within the cutoff distance, automatically handling periodic boundary conditions when `unitcell` is specified.

**Sources:** [testing/runtests.jl:59-66]()

## MinimumDistance Data Structure

### Custom Type Definition

The validation uses a custom `MinimumDistance` struct to track the closest inter-molecular approach:

```mermaid
classDiagram
    class MinimumDistance {
        +Int i
        +Int j
        +Float64 d
    }
    
    class CellListMapIntegration {
        <<interface>>
        +update_mind(i, j, d2, pdb, md)
        +reducer(md1, md2)
        +copy_output(md)
        +reset_output(md)
    }
    
    MinimumDistance ..|> CellListMapIntegration : implements
    
    note for MinimumDistance "i, j: Atom indices (1-based)\nd: Distance in Angstroms"
    note for CellListMapIntegration "CellListMap.jl requires these functions\nto support custom reduction operations"
```

**Sources:** [testing/runtests.jl:20-32]()

### Custom Reduction Operations

The `MinimumDistance` type integrates with CellListMap through four required functions:

#### `update_mind`

This function is called for each atom pair within the cutoff distance:

```
function update_mind(i, j, d2, pdb, md::MinimumDistance)
    residue(pdb[i]) == residue(pdb[j]) && return md  # Skip intra-molecular
    d = sqrt(d2)
    return d < md.d ? MinimumDistance(i, j, d) : md  # Keep minimum
end
```

The function skips atom pairs from the same residue (intra-molecular distances) since the validation only concerns inter-molecular spacing. This relies on the PDB structure having distinct residue identifiers for each molecule, which is ensured by the `resnumbers` option in Packmol input files.

**Sources:** [testing/runtests.jl:25-29](), [testing/runtests.jl:6-12]()

#### Reducer Functions

The remaining three functions enable CellListMap's parallel reduction:

| Function | Purpose | Implementation |
|----------|---------|----------------|
| `reducer(md1, md2)` | Combine results from parallel threads | Return `md1.d < md2.d ? md1 : md2` |
| `copy_output(md)` | Create independent copy for thread safety | Return `md` (immutable struct) |
| `reset_output(md)` | Initialize accumulator for each thread | Return `MinimumDistance(0, 0, +Inf)` |

**Sources:** [testing/runtests.jl:30-32]()

## Validation Criteria

### Precision-Based Tolerance

The validation checks that the computed minimum distance meets the tolerance with a precision allowance:

```
mind.d >= (1 - precision) * tolerance
```

| Parameter | Typical Value | Source |
|-----------|---------------|--------|
| `tolerance` | 2.0 Å | Input file `tolerance` keyword |
| `precision` | 0.01 (1%) | Input file `precision` keyword or default |
| Threshold | 1.98 Å | `(1 - 0.01) * 2.0` |

This precision allowance accounts for numerical artifacts in the optimization and floating-point arithmetic. If the minimum distance falls below the threshold, the test fails with a detailed error message including:

- The input file name
- Obtained minimum distance
- Expected threshold
- Atom indices (both 1-based Julia indexing and 0-based VMD indexing)

**Sources:** [testing/runtests.jl:67-75]()

### Success Message Verification

Before running minimum distance validation, the test suite verifies that Packmol reported successful completion by searching for the string `"Success!"` in the execution log. If this message is not found, the test fails immediately without attempting validation.

**Sources:** [testing/runtests.jl:96-100]()

## Dependency Management

### Julia Package Environment

The test suite uses a local Julia environment defined by `Project.toml`:

```mermaid
graph LR
    Project["Project.toml<br/>testing/Project.toml"]
    PDBTools["PDBTools.jl<br/>e29189f1-7114-4dbd-93d0-c5673a921a58"]
    CellListMap["CellListMap.jl<br/>69e1c6dd-3888-40e6-b3c8-31ac5f578864"]
    
    Project --> PDBTools
    Project --> CellListMap
    
    PDBTools -.->|Parse PDB files| readPDB["readPDB()<br/>coor()<br/>residue()"]
    CellListMap -.->|Distance calc| ParticleSystem["ParticleSystem<br/>map_pairwise"]
    
    style Project fill:#f9f9f9
    style readPDB fill:#f9f9f9
    style ParticleSystem fill:#f9f9f9
```

The environment is activated and instantiated at the beginning of `runtests.jl`:

```julia
import Pkg; Pkg.activate(@__DIR__); Pkg.instantiate()
```

This ensures all dependencies are available before running tests.

**Sources:** [testing/runtests.jl:1-4](), [testing/Project.toml:1-4]()

## Integration with Test Suite

### Invocation Pattern

The Julia test suite is invoked from `test.sh` after the Packmol binary is compiled:

```bash
julia_exe=~/.juliaup/bin/julia
$julia_exe runtests.jl ./input_files/water_box.inp \
                      ./input_files/mixture.inp \
                      # ... (17 total input files)
```

Each input file path is passed as a command-line argument, and `runtests.jl` processes them sequentially.

**Sources:** [testing/test.sh:5-24]()

### CI/CD Integration

The GitHub Actions workflow compiles Packmol using both `make` and `cmake`, then runs the test suite on both Ubuntu and macOS:

```mermaid
sequenceDiagram
    participant GH as GitHub Actions
    participant Compile as Compile Step
    participant CD as cd testing
    participant Install as install_julia.sh
    participant Test as test.sh
    participant Julia as runtests.jl
    
    GH->>Compile: make or cmake
    Compile->>CD: cd testing
    CD->>Install: ./install_julia.sh
    Install-->>CD: Julia ready
    CD->>Test: ./test.sh
    Test->>Julia: Run 17 test cases
    Julia-->>Test: All tests pass/fail
    Test-->>GH: Exit status
```

The workflow tests on multiple platforms and compilers to ensure cross-platform compatibility.

**Sources:** [.github/workflows/actions.yml:1-46]()

## Periodic Boundary Condition Handling

### PBC Parameter Extraction

When the input file contains a `pbc` keyword, the validator extracts box dimensions and passes them to CellListMap:

```mermaid
graph TD
    pbc_line["pbc keyword in input file"]
    
    pbc_line --> check_length{"Length of values"}
    
    check_length -->|3 values| format1["pbc lx ly lz<br/>(box from origin)"]
    check_length -->|6 values| format2["pbc x0 y0 z0 x1 y1 z1<br/>(explicit bounds)"]
    check_length -->|Other| error["error('pbc not properly set')"]
    
    format1 --> calc1["unitcell = [lx, ly, lz]"]
    format2 --> calc2["unitcell = [x1-x0, y1-y0, z1-z0]"]
    
    calc1 --> pass_to_sys["ParticleSystem(<br/>unitcell = unitcell)"]
    calc2 --> pass_to_sys
    
    pass_to_sys --> celllist["CellListMap handles<br/>PBC distance wrapping"]
    
    style pass_to_sys fill:#f9f9f9
    style celllist fill:#f9f9f9
```

When `unitcell` is provided to `ParticleSystem`, CellListMap automatically applies minimum image convention for distance calculations, ensuring correct validation for periodic systems.

**Sources:** [testing/runtests.jl:46-54]()

## Error Reporting

### Failure Message Format

When validation fails, the error message provides comprehensive debugging information:

```
Packing reported success, but minimum distance is not correct for $input_file
Obtained minimum-distance = $(mind.d) for tolerance $tolerance and precision $precision.
Atoms: $(mind.i) and $(mind.j) - VMD: index $(mind.i-1) $(mind.j-1)
```

The message includes both 1-based Julia indexing and 0-based VMD indexing to facilitate visualization and debugging in molecular visualization tools.

**Sources:** [testing/runtests.jl:68-74]()

### Test Isolation

Each test case runs independently. If one test fails, the error is immediately reported and the test suite terminates due to the `set -e` flag in `test.sh`. This fail-fast behavior ensures that test failures are noticed and addressed promptly.

**Sources:** [testing/test.sh:3-4]()

---