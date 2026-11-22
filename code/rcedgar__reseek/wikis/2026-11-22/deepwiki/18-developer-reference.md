# Developer Reference

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/mx.cpp](src/mx.cpp)
- [src/mx.h](src/mx.h)
- [src/mymalloc.h](src/mymalloc.h)
- [src/mymalloc_dbg.cpp](src/mymalloc_dbg.cpp)
- [src/myutils.cpp](src/myutils.cpp)
- [src/myutils.h](src/myutils.h)
- [src/reseek_main.cpp](src/reseek_main.cpp)
- [src/timers.h](src/timers.h)
- [src/xdpmem.h](src/xdpmem.h)

</details>



This document covers the internal developer infrastructure supporting the reseek protein search tool, including core utilities, memory management, build system integration, and fundamental data structures. This material is essential for understanding the codebase architecture and for contributing to the project.

For information about the core alignment algorithms, see [Core Alignment Engine](#3). For database search implementation details, see [Database Search System](#4). For build and deployment processes, see [Build System and CI/CD](#8.1).

## Core Application Architecture

The reseek application follows a command-dispatch architecture where the main entry point processes command-line arguments and dispatches to appropriate command implementations.

### Application Entry Point

The application entry point in `reseek_main.cpp` implements a structured initialization and command dispatch system:

```mermaid
graph TB
    subgraph "Application Startup"
        main["main()"] --> cmdline["MyCmdLine()"]
        cmdline --> logging["LogProgramInfoAndCmdLine()"]
        logging --> timing["InitTiming()"]
        timing --> memsetup["Memory Setup"]
    end
    
    subgraph "Command Processing"
        memsetup --> cmdcount["Command Count Validation"]
        cmdcount --> dispatch["Command Dispatch"]
        dispatch --> cmd_convert["cmd_convert()"]
        dispatch --> cmd_search["cmd_search()"]
        dispatch --> cmd_bench["cmd_bench()"]
    end
    
    subgraph "Application Cleanup"
        cmd_convert --> cleanup["Cleanup Phase"]
        cmd_search --> cleanup
        cmd_bench --> cleanup
        cleanup --> logtiming["LogTiming()"]
        logtiming --> logmem["LogElapsedTimeAndRAM()"]
        logmem --> exit["MyutilsExit()"]
    end
```

**Application Entry Point Flow**

The main function [src/reseek_main.cpp:10-65]() follows a strict initialization sequence:

1. **Command-line Processing**: `MyCmdLine()` parses arguments and sets global option variables
2. **Logging Initialization**: `LogProgramInfoAndCmdLine()` sets up logging and records program start
3. **Memory Tracking**: Optional memory allocation tracking based on command-line flags
4. **Command Validation**: Ensures exactly one command is specified using preprocessor macros
5. **Command Dispatch**: Uses preprocessor expansion to call the appropriate `cmd_*()` function
6. **Cleanup**: Logs timing, memory usage, and performs orderly shutdown

Sources: [src/reseek_main.cpp:10-65]()

## Core Utility System

The `myutils` module provides the foundational infrastructure for the entire application, including platform abstraction, memory management, I/O operations, and logging.

### Platform Abstraction Layer

```mermaid
graph TB
    subgraph "Platform Detection"
        platform["GetPlatform()"] --> win64["win64"]
        platform --> win32["win32"]
        platform --> i86linux64["i86linux64"]
        platform --> i86osx64["i86osx64"]
    end
    
    subgraph "File System Operations"
        fileops["File Operations"] --> stdio["Stdio Wrapper Functions"]
        stdio --> OpenStdioFile["OpenStdioFile()"]
        stdio --> ReadStdioFile["ReadStdioFile()"]
        stdio --> WriteStdioFile["WriteStdioFile()"]
        fileops --> pathops["Path Operations"]
        pathops --> GetBaseName["GetBaseName()"]
        pathops --> GetExtFromPathName["GetExtFromPathName()"]
    end
    
    subgraph "Memory Management"
        memops["Memory Operations"] --> GetMemUseBytes["GetMemUseBytes()"]
        memops --> GetPhysMemBytes["GetPhysMemBytes()"]
        memops --> GetUsableMemBytes["GetUsableMemBytes()"]
    end
    
    subgraph "String Utilities"
        strops["String Operations"] --> StrToInt["StrToInt()"]
        strops --> StrToFloat["StrToFloat()"]
        strops --> StrToMemBytes["StrToMemBytes()"]
        strops --> Split["Split()"]
    end
```

**Platform-Specific Implementations**

The utility system provides platform-specific implementations for:

- **Memory Usage Tracking**: Windows (`GetProcessMemoryInfo`), Linux (`/proc/*/statm`), macOS (`task_info`)
- **File I/O**: 64-bit file operations with platform-specific seeks and tells
- **Physical Memory Detection**: Platform-specific methods for determining available RAM
- **Directory Listing**: Windows (`FindFirstFile`/`FindNextFile`) vs Unix (`opendir`/`readdir`)

Sources: [src/myutils.cpp:77-104](), [src/myutils.cpp:832-960](), [src/myutils.cpp:962-1012]()

### I/O Abstraction Layer

The I/O system provides a comprehensive wrapper around standard C file operations with enhanced error handling and 64-bit support:

```mermaid
graph LR
    subgraph "File Management"
        OpenStdioFile["OpenStdioFile()"] --> bufalloc["AllocBuffer()"]
        bufalloc --> tracking["FileToFileName tracking"]
        CreateStdioFile["CreateStdioFile()"] --> bufalloc
        CloseStdioFile["CloseStdioFile()"] --> bufdealloc["FreeBuffer()"]
    end
    
    subgraph "Read Operations"
        ReadStdioFile["ReadStdioFile()"] --> pos32["32-bit positioning"]
        ReadStdioFile64["ReadStdioFile64()"] --> pos64["64-bit positioning"]
        ReadAllStdioFile["ReadAllStdioFile()"] --> chunked["Chunked reading"]
        ReadLineStdioFile["ReadLineStdioFile()"] --> lineproc["Line processing"]
    end
    
    subgraph "Write Operations"
        WriteStdioFile["WriteStdioFile()"] --> WriteStdioFile64["WriteStdioFile64()"]
        WriteStdioFileStr["WriteStdioFileStr()"] --> WriteStdioFile
    end
    
    subgraph "Position Management"
        SetStdioFilePos["SetStdioFilePos()"] --> GetStdioFilePos["GetStdioFilePos()"]
        SetStdioFilePos64["SetStdioFilePos64()"] --> GetStdioFilePos64["GetStdioFilePos64()"]
        GetStdioFileSize32["GetStdioFileSize32()"] --> GetStdioFileSize64["GetStdioFileSize64()"]
    end
```

**I/O Features**

Key I/O system capabilities include:

- **Buffered I/O**: Custom buffer allocation with `MY_IO_BUFSIZ` (32KB) for performance
- **64-bit File Support**: Full 64-bit file positioning and size operations
- **Error Handling**: Comprehensive error reporting with file state logging
- **File Tracking**: Global map tracking file handles to filenames for debugging
- **Memory Mapped Reading**: Large file reading with chunked operations

Sources: [src/myutils.cpp:158-183](), [src/myutils.cpp:248-287](), [src/myutils.cpp:416-462]()

## Memory Management System

The reseek application implements a sophisticated memory management system with optional debugging capabilities, performance tracking, and leak detection.

### Memory Management Architecture

```mermaid
graph TB
    subgraph "Memory Interface"
        myalloc["myalloc(type, count)"] --> mymalloc["mymalloc()"]
        myfree["myfree(ptr)"] --> actualfree["free()"]
        newop["operator new"] --> mymalloc
        deleteop["operator delete"] --> myfree
    end
    
    subgraph "Debug Mode (MYMALLOC_DBG)"
        mymalloc --> memdata["mem_data block"]
        memdata --> magic["magic number"]
        memdata --> tracking["allocation tracking"]
        memdata --> metadata["filename:line info"]
        tracking --> blocklist["s_BlockList"]
        blocklist --> summary["periodic summaries"]
        summary --> statedump["state dumping"]
    end
    
    subgraph "Release Mode"
        mymalloc --> stdlib["standard malloc()"]
        stdlib --> performance["optimized performance"]
    end
    
    subgraph "Statistics"
        g_myalloc_netbytes["g_myalloc_netbytes"] --> netnew["g_mymalloc_netnewbytes"]
        g_mymalloc_netallocount["g_mymalloc_netallocount"] --> netcount["g_mymalloc_netnewcount"]
    end
```

**Memory Management Features**

The system provides two operational modes:

1. **Debug Mode** (`MYMALLOC_DBG=1`): Full allocation tracking with metadata
2. **Release Mode** (`MYMALLOC_DBG=0`): Minimal overhead wrapper

**Debug Mode Capabilities**:
- Per-allocation metadata with source file and line number
- Magic number corruption detection
- Linked list tracking of all active allocations
- Periodic memory usage summaries
- State dumping for leak analysis
- Memory access pattern tracing

Sources: [src/mymalloc.h:1-36](), [src/mymalloc_dbg.cpp:10-377]()

### Memory Debugging Interface

The debug memory system provides comprehensive tracking and analysis tools:

```mermaid
graph LR
    subgraph "Allocation Tracking"
        alloctrack["Allocation"] --> memdata["mem_data structure"]
        memdata --> magic["magic: 0x3e3e3e3e"]
        memdata --> srcinfo["fn:linenr"]
        memdata --> allocinfo["bytes, idx, secs"]
        memdata --> linkage["fwd/bwd pointers"]
    end
    
    subgraph "State Management"
        linkage --> blocklist["s_BlockList"]
        blocklist --> insert["InsertBlock()"]
        blocklist --> delete["DeleteBlock()"]
        insert --> summary["Summary Generation"]
        delete --> summary
    end
    
    subgraph "Reporting"
        summary --> mymalloc_print_summary["mymalloc_print_summary()"]
        summary --> mymalloc_write_state["mymalloc_write_state()"]
        summary --> mymalloc_write_map["mymalloc_write_map()"]
        summary --> tracing["Memory Tracing"]
    end
    
    subgraph "Periodic Operations"
        timer["Timer-based"] --> autosummary["Auto Summary"]
        timer --> autodump["Auto State Dump"]
        autosummary --> fd["File Descriptor I/O"]
        autodump --> fd
    end
```

**Memory Debugging Configuration**

The debug system supports runtime configuration through command-line options:
- `--myalloc_summary_secs`: Interval for periodic memory summaries
- `--myalloc_dump_secs`: One-time state dump after specified seconds
- `--myalloc_trace`: Enable per-allocation tracing
- `--myalloc_exit_state`: Generate state dump on application exit

Sources: [src/mymalloc_dbg.cpp:64-182](), [src/mymalloc_dbg.cpp:238-377]()

## Matrix and Memory Management

The application provides specialized matrix classes and memory management for dynamic programming operations.

### Matrix Class System

```mermaid
graph TB
    subgraph "Matrix Template"
        Mx["Mx<T>"] --> rowcount["m_RowCount"]
        Mx --> colcount["m_ColCount"]
        Mx --> data["m_Data**"]
        Mx --> buffer["m_Buffer*"]
    end
    
    subgraph "Memory Layout"
        buffer --> onebuffer["ONE_BUFFER mode"]
        onebuffer --> contiguous["Contiguous allocation"]
        contiguous --> rowpointers["Row pointer setup"]
        data --> rowpointers
    end
    
    subgraph "Operations"
        ops["Matrix Operations"] --> Alloc["Alloc(rows, cols)"]
        ops --> Get["Get(i, j)"]
        ops --> Put["Put(i, j, val)"]
        ops --> Assign["Assign(val)"]
        ops --> Clear["Clear()"]
    end
    
    subgraph "Specializations"
        XDPMem["XDPMem"] --> TBBit["m_TBBit: Mx<byte>"]
        XDPMem --> RevA["m_RevA: byte*"]
        XDPMem --> RevB["m_RevB: byte*"]
        XDPMem --> Buffer1["m_Buffer1: float*"]
        XDPMem --> Buffer2["m_Buffer2: float*"]
    end
```

**Matrix Implementation Details**

The `Mx<T>` template class provides:

- **Unified Memory Layout**: Single buffer allocation with computed row pointers for cache efficiency
- **Type Safety**: Template-based type checking for different data types
- **Bounds Checking**: Debug mode boundary validation
- **Resource Management**: Automatic cleanup in destructor

The `XDPMem` class extends this for dynamic programming:

- **Specialized Buffers**: Separate float and int buffers for different DP algorithms
- **Reverse Sequence Storage**: Buffers for reversed sequence data
- **Traceback Support**: Byte matrix for alignment path reconstruction
- **Offset Handling**: Buffer pointers adjusted for 1-based indexing

Sources: [src/mx.h:8-135](), [src/xdpmem.h:15-109]()

## Performance Monitoring and Timing

The application includes comprehensive performance monitoring through a timing system and progress reporting infrastructure.

### Timing System Architecture

```mermaid
graph LR
    subgraph "Timer Infrastructure"
        timers["timers.h"] --> timerlist["Timer Definitions"]
        timerlist --> DSS_Align1["DSS_Align1"]
        timerlist --> SWFwd["SWFwd"]
        timerlist --> SWRev["SWRev"]
        timerlist --> SetProfiles["SetProfiles"]
        timerlist --> MuKmerAln["MuKmerAln"]
    end
    
    subgraph "Timing Control"
        InitTiming["InitTiming()"] --> timing["Timing System"]
        timing --> LogTiming["LogTiming()"]
        timing --> GetElapsedSecs["GetElapsedSecs()"]
        timing --> performance["Performance Tracking"]
    end
    
    subgraph "Progress Reporting"
        progress["Progress System"] --> ProgressLog["ProgressLog()"]
        progress --> ProgressStep["ProgressStep()"]
        progress --> ProgressFile["ProgressFile*()"]
        progress --> GetProgressPrefixStr["GetProgressPrefixStr()"]
    end
    
    subgraph "Memory Monitoring"
        memmon["Memory Monitor"] --> GetMemUseBytes["GetMemUseBytes()"]
        memmon --> GetPeakMemUseBytes["GetPeakMemUseBytes()"]
        memmon --> GetUsableMemBytes["GetUsableMemBytes()"]
    end
```

**Performance Monitoring Features**

The timing system provides:

- **Hierarchical Timers**: Named timers for different algorithm phases
- **Automatic Reporting**: Integrated timing output at application exit
- **Memory Integration**: Combined timing and memory usage reporting
- **Progress Tracking**: File-based and step-based progress reporting

**Timer Categories**:
- **Alignment Operations**: `DSS_Align1`, `DSS_Align2`, `DSS_Align3`
- **Smith-Waterman**: `SWFwd`, `SWRev`, `SWFast`, `SWFastGapless`
- **Profile Operations**: `SetProfiles`, `SetMuQP`, `SetKmersVec`
- **Database Operations**: `MuKmerAln`, `GetScorePosPair`

Sources: [src/timers.h:1-61](), [src/myutils.cpp:185-188](), [src/myutils.cpp:1265-1556]()

### Logging and Error Handling

The application provides a comprehensive logging and error handling system:

```mermaid
graph TB
    subgraph "Logging System"
        SetLogFileName["SetLogFileName()"] --> g_fLog["g_fLog"]
        Log["Log()"] --> g_fLog
        ProgressLog["ProgressLog()"] --> dualoutput["Dual Output"]
        dualoutput --> g_fLog
        dualoutput --> stderr["stderr"]
    end
    
    subgraph "Error Handling"
        Die["Die()"] --> g_DieLock["g_DieLock mutex"]
        g_DieLock --> Die_["Die_()"]
        Die_ --> errorlog["Error Logging"]
        errorlog --> cmdline["Command Line Log"]
        cmdline --> timestamp["Timestamp"]
        timestamp --> exit["exit(1)"]
        Warning["Warning()"] --> warninglog["Warning Log"]
    end
    
    subgraph "Progress Display"
        Progress["Progress()"] --> quiet["opt(quiet) check"]
        quiet --> prefix["Progress Prefix"]
        prefix --> formatting["Line Formatting"]
        formatting --> stderr
    end
    
    subgraph "Utility Functions"
        utils["Utility Functions"] --> GetProgressPrefixStr["GetProgressPrefixStr()"]
        utils --> SecsToHHMMSS["SecsToHHMMSS()"]
        utils --> MemBytesToStr["MemBytesToStr()"]
        utils --> IntToStr["IntToStr()"]
    end
```

**Logging Features**

The logging system provides:

- **File and Console Output**: Dual logging to file and stderr
- **Thread Safety**: Mutex-protected error handling
- **Contextual Information**: Automatic timestamp and memory usage reporting
- **Formatted Output**: Specialized formatting for time, memory, and numeric values
- **Progress Integration**: Combined progress and logging with optional prefixes

Sources: [src/myutils.cpp:736-817](), [src/myutils.cpp:1316-1450]()

## Type System and Portability

The codebase implements a comprehensive type system for cross-platform compatibility and performance optimization.

### Type Definitions and Platform Support

```mermaid
graph LR
    subgraph "Base Types"
        basetypes["Base Types"] --> byte["byte (unsigned char)"]
        basetypes --> uint16["uint16"]
        basetypes --> uint32["uint32"]
        basetypes --> uint["uint"]
    end
    
    subgraph "64-bit Types"
        types64["64-bit Types"] --> int64_msvc["int64 (__int64)"]
        types64 --> int64_gcc["int64 (long long)"]
        types64 --> uint64_msvc["uint64 (unsigned __int64)"]
        types64 --> uint64_gcc["uint64 (unsigned long long)"]
    end
    
    subgraph "Platform Macros"
        macros["Platform Macros"] --> BITS["BITS (32/64)"]
        macros --> uintb["uintb (uint32/uint64)"]
        macros --> constants["UINT32_MAX, UINT64_MAX"]
        macros --> platform["Platform detection"]
    end
    
    subgraph "Compatibility"
        compat["Compatibility"] --> _stricmp["_stricmp/strcasecmp"]
        compat --> off_t["off_t (__int64)"]
        compat --> debug["DEBUG/_DEBUG"]
    end
```

**Type System Design**

The type system provides:

- **Consistent Naming**: `uint32`, `uint64`, `byte` for clear intent
- **Platform Abstraction**: Compiler-specific `int64` definitions
- **Architecture Awareness**: `BITS` macro for 32/64-bit builds
- **Standard Compliance**: Proper constants and limits definitions

**Platform-Specific Adaptations**:
- **Windows**: `__int64`, `_stricmp`, `off_t` redefinition
- **GCC**: `long long`, `strcasecmp`, standard `off_t`
- **Debug Builds**: Unified `DEBUG` and `_DEBUG` macros

Sources: [src/myutils.h:4-104](), [src/myutils.h:141-143]()

This developer reference provides the foundation for understanding reseek's internal architecture and contributing to the codebase. The modular design, comprehensive error handling, and performance monitoring systems support the complex protein structure alignment algorithms implemented in higher-level modules.

---