# Command-Line Interface

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/cli_parser.f90](src/cli_parser.f90)
- [src/setsizes.f90](src/setsizes.f90)
- [testing/test_cli.sh](testing/test_cli.sh)

</details>



This page documents Packmol's command-line interface, including supported invocation methods, argument parsing implementation, and error handling. The CLI provides three distinct ways to execute Packmol, all of which are validated for consistency through automated testing.

For information about the input file format that the CLI accepts, see [Input File Format](#3.1). For details about output file generation, see [Output File Formats](#3.4). For the overall program execution flow, see [Program Execution Flow](#4.2).

## Purpose and Scope

Packmol's command-line interface serves as the primary entry point for executing the molecular packing program. It handles argument parsing, file path validation, and initialization of input/output streams. The implementation supports both traditional Unix-style input redirection and explicit file specification via command-line flags.

## Supported Invocation Methods

Packmol supports three invocation methods, all of which produce identical results for the same input:

| Method | Syntax | Description |
|--------|--------|-------------|
| Standard Input Redirection | `packmol < input.inp` | Traditional Unix approach; reads from stdin |
| Input File Flag | `packmol -i input.inp` | Explicit input file specification |
| Input and Output Flags | `packmol -i input.inp -o output.pdb` | Explicit specification of both files |

The output file is normally specified within the input file using the `output` keyword. The `-o` flag overrides this specification.

**Sources:** [src/cli_parser.f90:18-26](), [testing/test_cli.sh:1-240]()

## Command-Line Argument Parsing Flow

The following diagram illustrates how command-line arguments are processed from program invocation to input/output stream initialization:

```mermaid
flowchart TD
    START["Program Entry<br/>(app/packmol.f90)"] --> PARSE["parse_command_line_args()<br/>(cli_parser.f90)"]
    
    PARSE --> ARGC{"command_argument_count()"}
    
    ARGC -->|"argc = 0"| STDIN_MODE["Standard Input Mode"]
    ARGC -->|"argc = 2"| INPUT_MODE["Input File Mode"]
    ARGC -->|"argc = 4"| BOTH_MODE["Input + Output Mode"]
    ARGC -->|"other"| ERROR_EXIT["Error: Invalid Arguments"]
    
    STDIN_MODE --> SET_EMPTY["Set input_file_name = ''<br/>Set output_file_name = ''"]
    
    INPUT_MODE --> PARSE_I1["parse_command(cmd)"]
    PARSE_I1 --> CHECK_I1{"cmd = '-i'?"}
    CHECK_I1 -->|"Yes"| GET_INPUT1["get_filename(cmdno, input_file_name)"]
    CHECK_I1 -->|"No"| ERROR_EXIT
    
    BOTH_MODE --> PARSE_I2["parse_command(cmd1)"]
    PARSE_I2 --> FIRST_FLAG{"First flag?"}
    FIRST_FLAG -->|"'-i'"| GET_INPUT2["get_filename(1, input_file_name)"]
    FIRST_FLAG -->|"'-o'"| GET_OUTPUT1["get_filename(1, output_file_name)"]
    GET_INPUT2 --> PARSE_O2["parse_command(cmd2)"]
    GET_OUTPUT1 --> PARSE_I3["parse_command(cmd2)"]
    PARSE_O2 --> GET_OUTPUT2["get_filename(3, output_file_name)"]
    PARSE_I3 --> GET_INPUT3["get_filename(3, input_file_name)"]
    
    GET_OUTPUT2 --> VALIDATE["Validate Filenames"]
    GET_INPUT3 --> VALIDATE
    GET_INPUT1 --> VALIDATE
    SET_EMPTY --> SETSIZES
    
    VALIDATE --> CHECK_SAME{"input = output?"}
    CHECK_SAME -->|"Yes"| ERROR_EXIT
    CHECK_SAME -->|"No"| SETSIZES["setsizes()<br/>(setsizes.f90)"]
    
    SETSIZES --> FILE_CHECK{"input_file_name empty?"}
    FILE_CHECK -->|"Yes"| UNIT5["Open unit 5 (stdin)"]
    FILE_CHECK -->|"No"| UNIT100["Open unit 100 (file)"]
    
    UNIT5 --> READ_INPUT["Read Input Data"]
    UNIT100 --> READ_INPUT
    
    ERROR_EXIT --> EXIT["stop exit_code_command_line_error"]
    
    READ_INPUT --> CONTINUE["Continue Execution"]
```

**Sources:** [src/cli_parser.f90:80-239](), [src/setsizes.f90:37-46]()

## CLI Parser Module Architecture

The `cli_parser` module provides the core command-line parsing functionality through a hierarchical function structure:

```mermaid
graph TB
    subgraph "cli_parser Module (cli_parser.f90)"
        PARSE_CMD_ARGS["parse_command_line_args()<br/>Main entry point<br/>(lines 80-239)"]
        PARSE_CMD["parse_command(cmd)<br/>Identifies flag type<br/>(lines 33-69)"]
        GET_FNAME["get_filename(cmdno, filename)<br/>Extracts filename argument<br/>(lines 71-78)"]
    end
    
    subgraph "Module Variables"
        INPUT_FLAG["INPUT_FLAG = 0<br/>Constant"]
        OUTPUT_FLAG["OUTPUT_FLAG = 1<br/>Constant"]
        ERRMSG["errmsg<br/>Error message template"]
    end
    
    subgraph "External Dependencies"
        SIZES["sizes module<br/>Provides strl constant"]
        EXIT_CODES["exit_codes module<br/>Provides exit_code_command_line_error"]
        INPUT_MOD["input module<br/>Provides input_file_name, output_file_name"]
    end
    
    subgraph "Fortran Intrinsics"
        CMD_ARG_COUNT["command_argument_count()<br/>Returns argc"]
        GET_CMD_ARG["get_command_argument()<br/>Retrieves individual arguments"]
    end
    
    PARSE_CMD_ARGS --> CMD_ARG_COUNT
    PARSE_CMD_ARGS --> GET_CMD_ARG
    PARSE_CMD_ARGS --> PARSE_CMD
    PARSE_CMD_ARGS --> GET_FNAME
    
    PARSE_CMD --> INPUT_FLAG
    PARSE_CMD --> OUTPUT_FLAG
    
    GET_FNAME --> GET_CMD_ARG
    
    PARSE_CMD_ARGS --> INPUT_MOD
    PARSE_CMD --> EXIT_CODES
    PARSE_CMD --> ERRMSG
    
    INPUT_MOD --> SIZES
```

**Sources:** [src/cli_parser.f90:1-242]()

## Argument Parsing Logic

### Zero Arguments (Standard Input Mode)

When no command-line arguments are provided, Packmol expects input via standard input redirection:

```mermaid
sequenceDiagram
    participant User
    participant Shell
    participant CLI as cli_parser
    participant Setsizes as setsizes
    
    User->>Shell: packmol < input.inp
    Shell->>CLI: argc = 0
    CLI->>CLI: Verify no implementation errors
    CLI->>CLI: Set input_file_name = ""
    CLI->>CLI: Set output_file_name = ""
    CLI->>Setsizes: Continue initialization
    Setsizes->>Setsizes: Check len(trim(input_file_name)) == 0
    Setsizes->>Setsizes: Open unit 5 (stdin)
    Setsizes->>Setsizes: Read from stdin
```

The implementation validates that both `input_file_name` and `output_file_name` are empty strings to detect implementation errors [src/cli_parser.f90:119-127]().

**Sources:** [src/cli_parser.f90:99-128](), [src/setsizes.f90:37-46]()

### Two Arguments (Input File Flag)

When two arguments are provided, the first must be `-i` and the second is the input filename:

```mermaid
sequenceDiagram
    participant User
    participant CLI as cli_parser
    participant Parse as parse_command
    participant Get as get_filename
    
    User->>CLI: packmol -i input.inp
    CLI->>CLI: argc = 2
    CLI->>CLI: get_command_argument(1, cmd)
    CLI->>Parse: parse_command(cmd)
    Parse->>Parse: index(cmd, "-i")
    Parse->>Parse: Verify len(trim(cmd)) == 2
    Parse-->>CLI: INPUT_FLAG (0)
    CLI->>Get: get_filename(1, input_file_name)
    Get->>Get: get_command_argument(2, filename)
    Get-->>CLI: input_file_name set
    CLI->>CLI: Validate filename not empty
    CLI->>CLI: Continue execution
```

The parser ensures the flag is exactly `-i` (no additional characters) and extracts the filename from the subsequent argument [src/cli_parser.f90:129-162]().

**Sources:** [src/cli_parser.f90:129-162](), [src/cli_parser.f90:33-69](), [src/cli_parser.f90:71-78]()

### Four Arguments (Input and Output Flags)

When four arguments are provided, they must be `-i` and `-o` in any order with their respective filenames:

```mermaid
flowchart TD
    START["argc = 4"] --> GET1["get_command_argument(1, cmd)"]
    GET1 --> PARSE1["parse_command(cmd)"]
    
    PARSE1 --> FIRST{"First flag?"}
    FIRST -->|"INPUT_FLAG"| INPUT1["Set input_file_name<br/>specified_input_file = true"]
    FIRST -->|"OUTPUT_FLAG"| OUTPUT1["Set output_file_name<br/>specified_output_file = true"]
    
    INPUT1 --> GET3["get_command_argument(3, cmd)"]
    OUTPUT1 --> GET3
    
    GET3 --> PARSE3["parse_command(cmd)"]
    
    PARSE3 --> SECOND{"Second flag?"}
    SECOND -->|"OUTPUT_FLAG<br/>(if first was INPUT)"| OUTPUT2["Set output_file_name<br/>specified_output_file = true"]
    SECOND -->|"INPUT_FLAG<br/>(if first was OUTPUT)"| INPUT2["Set input_file_name<br/>specified_input_file = true"]
    
    OUTPUT2 --> ASSERT["Assert both flags specified"]
    INPUT2 --> ASSERT
    
    ASSERT --> VALIDATE["Validate filenames not empty"]
    VALIDATE --> COMPARE{"input = output?"}
    
    COMPARE -->|"Yes"| ERROR["Error: Same filename"]
    COMPARE -->|"No"| SUCCESS["Continue execution"]
```

The implementation supports both `-i input.inp -o output.pdb` and `-o output.pdb -i input.inp` orderings [src/cli_parser.f90:163-236]().

**Sources:** [src/cli_parser.f90:163-236]()

## Flag Parsing Implementation

The `parse_command` function identifies and validates command-line flags:

| Check | Description | Error Condition |
|-------|-------------|-----------------|
| Flag presence | Uses `index(cmd, "-i")` and `index(cmd, "-o")` | No match with either flag |
| Exact length | Verifies `len(trim(cmd)) == 2` | Extra characters in flag |
| Flag type | Returns `INPUT_FLAG` or `OUTPUT_FLAG` | Invalid flag characters |

The function returns integer constants `INPUT_FLAG = 0` or `OUTPUT_FLAG = 1` to indicate the flag type [src/cli_parser.f90:16-17]().

**Sources:** [src/cli_parser.f90:33-69]()

## Error Handling and Validation

The CLI parser implements comprehensive error handling:

```mermaid
graph TB
    subgraph "Validation Checks"
        V1["Argument count validation<br/>(0, 2, or 4 only)"]
        V2["Flag format validation<br/>(-i or -o exactly)"]
        V3["Filename presence validation<br/>(not empty string)"]
        V4["Distinct filenames validation<br/>(input ≠ output)"]
        V5["get_command_argument status<br/>(stat == 0)"]
    end
    
    subgraph "Error Messages"
        E1["errmsg<br/>Usage examples"]
        E2["'ERROR: unrecognized command-line argument'"]
        E3["'ERROR: invalid input filename'"]
        E4["'ERROR: invalid output filename'"]
        E5["'ERROR: packmol expects different<br/>for the input and output files'"]
        E6["'ERROR: truncation error'"]
        E7["'ERROR: command-line retrieval error'"]
    end
    
    subgraph "Exit Behavior"
        EXIT["stop exit_code_command_line_error"]
    end
    
    V1 -->|"Fail"| E1
    V2 -->|"Fail"| E2
    V3 -->|"Fail"| E3
    V3 -->|"Fail"| E4
    V4 -->|"Fail"| E5
    V5 -->|"stat = -1"| E6
    V5 -->|"stat > 0"| E7
    
    E1 --> EXIT
    E2 --> EXIT
    E3 --> EXIT
    E4 --> EXIT
    E5 --> EXIT
    E6 --> EXIT
    E7 --> EXIT
```

All errors terminate the program with `exit_code_command_line_error` from the `exit_codes` module [src/cli_parser.f90:10]().

**Sources:** [src/cli_parser.f90:18-26](), [src/cli_parser.f90:89-90](), [src/cli_parser.f90:227-230]()

## Integration with Input System

The CLI parser sets module variables in the `input` module that are later consumed by `setsizes`:

```mermaid
graph LR
    subgraph "cli_parser Module"
        PARSE["parse_command_line_args()"]
    end
    
    subgraph "input Module (Shared State)"
        INPUT_NAME["input_file_name<br/>(character string)"]
        OUTPUT_NAME["output_file_name<br/>(character string)"]
    end
    
    subgraph "setsizes.f90"
        SETSIZES["setsizes()"]
        CHECK["len(trim(input_file_name)) == 0"]
        UNIT_STDIN["un = 5"]
        UNIT_FILE["un = 100<br/>open(unit=100, file=input_file_name)"]
        READ["read(un, ...)"]
    end
    
    PARSE -->|"Sets"| INPUT_NAME
    PARSE -->|"Sets"| OUTPUT_NAME
    
    INPUT_NAME --> CHECK
    OUTPUT_NAME --> SETSIZES
    
    CHECK -->|"True"| UNIT_STDIN
    CHECK -->|"False"| UNIT_FILE
    
    UNIT_STDIN --> READ
    UNIT_FILE --> READ
```

The key decision point is at [src/setsizes.f90:37-46](), where an empty `input_file_name` indicates standard input mode (unit 5), while a non-empty string indicates file mode (unit 100).

**Sources:** [src/cli_parser.f90:11-12](), [src/setsizes.f90:27-46]()

## CLI Testing and Validation

The CLI behavior is validated through `test_cli.sh`, which ensures all three invocation methods produce identical output:

```mermaid
flowchart TD
    START["test_cli.sh<br/>Script Start"] --> ITERATE["For each *.inp in input_files/"]
    
    ITERATE --> FILTER{"Skip if filename<br/>contains 'error'<br/>or 'fail'"}
    FILTER -->|"Skip"| ITERATE
    FILTER -->|"Process"| PATCH["Patch input file:<br/>• Replace 'seed -1' with 'seed 1024'<br/>• Create .txt and .tmp versions"]
    
    PATCH --> RUN1["Run: packmol < input.txt<br/>Produces: output.pdb"]
    RUN1 --> RUN2["Run: packmol -i input.tmp<br/>Produces: output.tmp"]
    RUN2 --> RUN3["Run: packmol -i input.txt -o output.txt<br/>Produces: output.txt"]
    
    RUN3 --> DIFF1["diff output.pdb output.txt"]
    DIFF1 --> DIFF2["diff output.pdb output.tmp"]
    
    DIFF2 --> CHECK{"wc -c = 0<br/>for both diffs?"}
    CHECK -->|"Yes"| PASS["Test PASS<br/>Clean up temp files"]
    CHECK -->|"No"| FAIL["Test FAIL<br/>Exit with error"]
    
    PASS --> ITERATE
    FAIL --> END["Exit 1"]
```

### Test Methodology

The testing script implements several key strategies:

| Strategy | Implementation | Purpose |
|----------|----------------|---------|
| Seed normalization | Replace `seed -1` with `seed 1024` | Ensure deterministic results |
| File extension variants | Create `.txt` and `.tmp` copies | Test different output specifications |
| Binary diff comparison | Use GNU `diff` with `wc -c` | Verify byte-identical outputs |
| Input file filtering | Skip files with "error" or "fail" | Exclude intentional failure cases |

**Sources:** [testing/test_cli.sh:119-237]()

## Platform Considerations

The CLI implementation includes platform-specific considerations:

### macOS Compatibility

The test script detects macOS and uses `awk` instead of `gawk`:

```bash
os=$("$uname")
if [ "Darwin" == "$os" ] ; then
    gawk=$(which awk)
else
    gawk=$(which gawk)
fi
```

This accommodates macOS not shipping with GNU awk by default [testing/test_cli.sh:103-109]().

### Fortran Intrinsic Portability

The CLI parser uses standard Fortran intrinsics that are portable across compilers:

- `command_argument_count()` - Returns number of command-line arguments
- `get_command_argument(number, value, length, status)` - Retrieves specific arguments
- `index(string, substring)` - Finds substring position

**Sources:** [testing/test_cli.sh:103-114](), [src/cli_parser.f90:98-175]()

## Usage Examples

### Standard Input Redirection

```bash
packmol < water_box.inp
```

The input file `water_box.inp` contains the `output` directive specifying where to write results.

### Explicit Input File

```bash
packmol -i water_box.inp
```

Functionally identical to standard input redirection, but more explicit. The output file is still determined from the input file's `output` directive.

### Override Output File

```bash
packmol -i water_box.inp -o custom_output.pdb
```

The `-o` flag overrides any `output` directive in the input file, forcing output to `custom_output.pdb`.

### Invalid Invocations

The following commands produce errors:

```bash
packmol input.inp              # Error: expects 0, 2, or 4 args
packmol -i                     # Error: missing filename
packmol -i input.inp output.pdb # Error: missing -o flag
packmol -i same.txt -o same.txt # Error: input = output
```

**Sources:** [src/cli_parser.f90:18-26](), [testing/test_cli.sh:175-213]()

## Error Message Template

When the CLI parser encounters an error, it displays a standardized error message with usage examples:

```
ERROR: packmol command-line error

Command-line execution examples (you may use any): 

packmol < inputfile.inp

packmol -i inputfile.inp

packmol -i inputfile.inp -o output.pdb
```

This message is defined as a module constant `errmsg` in [src/cli_parser.f90:18-26]() and is displayed for all command-line parsing errors.

**Sources:** [src/cli_parser.f90:18-26]()

---