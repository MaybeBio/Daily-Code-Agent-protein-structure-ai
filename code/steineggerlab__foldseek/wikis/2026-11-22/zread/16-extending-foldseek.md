

Foldseek is designed with extensibility in mind, allowing developers to add new functionality, algorithms, and workflows to enhance its protein structure comparison capabilities. Whether you want to implement a new structural alignment algorithm, add support for additional file formats, or create specialized workflows, Foldseek's modular architecture makes it possible. This guide will walk you through the key components and extension points in the codebase.

## Understanding Foldseek's Architecture

Foldseek is built on a modular architecture that separates concerns into distinct components. At its core, the application follows a command-based pattern where each major functionality is implemented as a separate command that can be invoked through the CLI.

The main entry point is in `src/foldseek.cpp`, which initializes the application and registers all available commands. The application uses a base framework inherited from MMseqs2, providing robust database handling, threading, and workflow management capabilities.

```cpp
const char* binary_name = "foldseek";
const char* tool_name = "foldseek";
const char* tool_introduction = "Foldseek enables fast and sensitive comparisons of large structure sets...";

void init() {
    registerCommands(&baseCommands);
    registerCommands(&foldseekCommands);
}
```

Sources: [src/foldseek.cpp#L5-L21](src/foldseek.cpp#L5-L21)

## Command System and Registration

Foldseek's functionality is organized around a command system where each operation (like `createdb`, `structuresearch`, etc.) is implemented as a separate command. Commands are declared in `src/LocalCommandDeclarations.h` and defined in `src/FoldseekBase.cpp`.

To add a new command to Foldseek, you need to:

1. **Declare your command function** in `LocalCommandDeclarations.h`:
```cpp
extern int mynewcommand(int argc, const char **argv, const Command& command);
```

2. **Implement your command** in a new or existing source file.

3. **Register your command** in the `foldseekCommands` vector in `FoldseekBase.cpp`:
```cpp
std::vector<Command> foldseekCommands = {
    {"mynewcommand", mynewcommand, &localPar.mynewcommand, COMMAND_MAIN,
     "Description of my new command",
     "Example usage:\nfoldseek mynewcommand input.db output.db\n",
     "Your Name <email@example.com>",
     "<i:inputDB> <o:outputDB>",
     CITATION_FOLDSEEK, {{"inputDB", DbType::ACCESS_MODE_INPUT, DbType::NEED_DATA, &DbValidator::flatfile},
                         {"outputDB", DbType::ACCESS_MODE_OUTPUT, DbType::NEED_DATA, &DbValidator::flatfile}}}
};
```

Sources: [src/LocalCommandDeclarations.h#L6-L35](src/LocalCommandDeclarations.h#L6-L35), [src/FoldseekBase.cpp#L17-L41](src/FoldseekBase.cpp#L17-L41)

## Parameter System

Foldseek uses a hierarchical parameter system inherited from MMseqs2. The `LocalParameters` class in `src/commons/LocalParameters.h` extends the base `Parameters` class to add Foldseek-specific parameters.

To add new parameters:

1. **Define your parameters** in `LocalParameters.h`:
```cpp
class LocalParameters : public Parameters {
public:
    // Existing parameters...
    int myNewParameter;
    static const int MY_NEW_MODE_AUTO = 0;
    static const int MY_NEW_MODE_CUSTOM = 1;
};
```

2. **Initialize your parameters** in `LocalParameters.cpp` (not shown in viewed files but follows the pattern).

3. **Create a parameter group** for your command in `FoldseekBase.cpp`:
```cpp
PARAM_STRUCT(MYNEWCOMMAND, mynewcommand, "My New Command Parameters")
PARAM(STRUCTURE, myNewParameter, "my-new-param", "My new parameter", "Description of my new parameter", "auto", "auto|custom")
END_STRUCT()
```

Sources: [src/commons/LocalParameters.h#L18-L50](src/commons/LocalParameters.h#L18-L50)

## Workflow Implementation

Foldseek implements complex operations as workflows that chain together multiple simpler commands. Workflows are located in the `src/workflow/` directory and follow a consistent pattern.

A typical workflow implementation looks like this:

```cpp
int structuresearch(int argc, const char **argv, const Command &command) {
    LocalParameters &par = LocalParameters::getLocalInstance();
    
    // Set default values for this workflow
    setStructureSearchWorkflowDefaults(&par);
    
    // Parse command line parameters
    par.parseParameters(argc, argv, command, true, Parameters::PARSE_VARIADIC, 0);
    
    // Set parameters that must be passed to sub-commands
    setStructureSearchMustPassAlong(&par);
    
    // Determine which databases and files are needed
    bool needBacktrace = false;
    bool needTaxonomy = false;
    bool needLookup = false;
    // ... more need flags
    
    // Build and execute the workflow
    CommandCaller cmd;
    // ... set up workflow steps
    cmd.addVariable("NEED_BACKTRACE", needBacktrace ? "TRUE" : NULL);
    // ... more variables
    cmd.execProgram("structuresearch.sh", argc, argv, par);
    
    return 0;
}
```

Sources: [src/workflow/StructureSearch.cpp#L30-L50](src/workflow/StructureSearch.cpp#L30-L50)

## Utility Functions

The `src/strucclustutils/` directory contains utility functions that implement specific algorithms and data processing tasks. These utilities can be called from workflows or used as standalone commands.

For example, the structure alignment utility demonstrates how to implement core algorithms:

```cpp
int alignStructure(StructureSmithWaterman & structureSmithWaterman,
                   StructureSmithWaterman & reverseStructureSmithWaterman,
                   Sequence & tSeqAA, Sequence & tSeq3Di,
                   unsigned int querySeqLen, unsigned int targetSeqLen,
                   EvalueNeuralNet & evaluer, std::pair<double, double> muLambda,
                   Matcher::result_t & res, std::string & backtrace,
                   Parameters & par) {
    
    // Set default parameters
    float seqId = 0.0;
    backtrace.clear();
    
    // Perform the alignment
    StructureSmithWaterman::s_align align = structureSmithWaterman.alignScoreEndPos<StructureSmithWaterman::PROFILE>(
        tSeqAA.numSequence, tSeq3Di.numSequence, targetSeqLen, 
        par.gapOpen.values.aminoacid(), par.gapExtend.values.aminoacid(), 
        querySeqLen / 2);
    
    // Check coverage criteria
    bool hasLowerCoverage = !(Util::hasCoverage(par.covThr, par.covMode, align.qCov, align.tCov));
    
    // ... rest of the implementation
}
```

Sources: [src/strucclustutils/structurealign.cpp#L37-L50](src/strucclustutils/structurealign.cpp#L37-L50)

## Library Dependencies

Foldseek integrates several specialized libraries for different aspects of protein structure analysis:

- **3Di**: Converts protein structures to 3Di descriptors for fast comparison
- **block-aligner**: Provides efficient sequence alignment algorithms
- **foldcomp**: Compresses protein structure data
- **gemmi**: Handles PDB and mmCIF file parsing
- **tmalign**: Implements the TM-align structural alignment algorithm
- **prostt5**: Provides protein language model capabilities
- **pulchra**: Reconstructs protein structures from C-alpha traces

These libraries are located in the `lib/` directory and can be extended or replaced to add new functionality.

Sources: [lib/](lib/)

## Build System and Integration

Foldseek uses CMake as its build system. The main `CMakeLists.txt` file in the root directory configures the build and manages dependencies.

Key build configuration options include:

```cmake
set(ENABLE_PROSTT5 1 CACHE BOOL "Enable ProstT5")
set(ENABLE_CUDA 0 CACHE BOOL "Enable CUDA")
set(IGNORE_RUST_VERSION 0 CACHE BOOL "Ignore Rust version check")
set(FORCE_STATIC_DEPS 0 CACHE BOOL "Force static linking of deps")
```

To add a new library dependency:

1. **Add your library** to the `lib/` directory
2. **Include it** in the main CMakeLists.txt:
```cmake
add_subdirectory(lib/mynewlib)
include_directories(lib/mynewlib)
```
3. **Link against it** in the appropriate CMakeLists.txt file

Sources: [CMakeLists.txt#L9-L12](CMakeLists.txt#L9-L12), [CMakeLists.txt#L39-L44](CMakeLists.txt#L39-L44)

## Extension Points and Best Practices

When extending Foldseek, consider these key extension points:

### 1. New Structural Alignment Algorithms
Implement your algorithm in the `strucclustutils/` directory, following the pattern of existing alignment utilities. Your implementation should integrate with the existing parameter system and database handling.

### 2. New File Format Support
Add format support by extending the file parsing capabilities in the `commons/` directory or by integrating with the `gemmi` library.

### 3. New Workflows
Create new workflows in the `workflow/` directory that chain together existing commands to solve specific problems.

### 4. New Database Types
Extend the `LocalParameters` class to define new database types and add validation logic in the `FoldSeekDbValidator` class.

> [!TIP]
> When adding new functionality, always consider performance implications. Foldseek is designed for large-scale analyses, so your extensions should maintain the tool's efficiency. Use the existing threading and parallelization patterns to ensure good performance.

## Testing Your Extensions

Before contributing your extensions, ensure they:

1. **Follow the existing code style** and patterns
2. **Include appropriate documentation** and examples
3. **Handle edge cases** gracefully
4. **Integrate properly** with the parameter system
5. **Maintain backward compatibility** where possible

The Foldseek team welcomes contributions that extend the tool's capabilities while maintaining its performance and usability. By following the patterns outlined in this guide, you can create robust extensions that integrate seamlessly with the existing codebase.
