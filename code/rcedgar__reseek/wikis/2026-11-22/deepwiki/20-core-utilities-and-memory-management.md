# Core Utilities and Memory Management

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
- [src/xdpmem.h](src/xdpmem.h)

</details>



## Purpose and Scope

This document covers the fundamental infrastructure components of the reseek codebase, including the application entry point, core utility functions, custom memory management system, and specialized memory classes. These components provide the foundation for all other systems in the codebase.

For information about command-line interface and option parsing, see [Commands and Options](#6.1). For build system configuration, see [Build System and CI/CD](#8.1).

## Application Entry Point

The application entry point is implemented in `reseek_main.cpp` and provides the central dispatcher for all reseek commands.

```mermaid
graph TD
    subgraph "Application Lifecycle"
        A[main] --> B[MyCmdLine]
        B --> C[LogProgramInfoAndCmdLine]
        C --> D[InitTiming]
        D --> E[Command Validation]
        E --> F[Command Dispatch]
        F --> G[Memory Cleanup]
        G --> H[LogElapsedTimeAndRAM]
        H --> I[MyutilsExit]
    end
    
    subgraph "Command Processing"
        E --> J["CmdCount Check"]
        J --> K["Single Command Validation"]
        K --> L["cmd_* Function Call"]
    end
    
    subgraph "Memory Management Integration"
        B --> M["mymalloc Configuration"]
        M --> N["opt_myalloc_summary_secs"]
        M --> O["opt_myalloc_dump_secs"]
        M --> P["opt_myalloc_trace"]
        G --> Q["mymalloc_write_state"]
        G --> R["mymalloc_print_summary"]
    end
```

The main function coordinates initialization, command execution, and cleanup through these key phases:

| Phase | Function | Purpose |
|-------|----------|---------|
| Initialization | `MyCmdLine()` | Parse command line arguments |
| Logging Setup | `LogProgramInfoAndCmdLine()` | Initialize logging system |
| Timing | `InitTiming()` | Setup performance monitoring |
| Command Dispatch | Dynamic `cmd_*()` calls | Execute user-specified command |
| Cleanup | `LogElapsedTimeAndRAM()` | Report resource usage |

Sources: [src/reseek_main.cpp:10-65]()

## Core Utility Functions

The `myutils` module provides essential utility functions organized into several categories:

### File I/O Operations

```mermaid
graph LR
    subgraph "File Operations"
        A["OpenStdioFile"] --> B["FILE* Handle"]
        C["CreateStdioFile"] --> B
        D["ReadStdioFile"] --> E["Buffer Management"]
        F["WriteStdioFile"] --> E
        G["CloseStdioFile"] --> H["Buffer Cleanup"]
    end
    
    subgraph "Position Management"
        I["SetStdioFilePos"] --> J["fseeko"]
        K["GetStdioFilePos64"] --> L["ftello"]
        M["GetStdioFileSize64"] --> N["File Size Calculation"]
    end
    
    subgraph "Buffer Management"
        O["AllocBuffer"] --> P["MY_IO_BUFSIZ"]
        Q["FreeBuffer"] --> R["g_IOBuffers"]
        P --> S["setvbuf"]
    end
```

Key file I/O functions include:

- `OpenStdioFile()` - Opens files with custom buffering
- `ReadAllStdioFile64()` - Reads entire files into memory with chunked reading for large files
- `WriteStdioFile()` - Writes data with error checking
- Custom buffering system using `MY_IO_BUFSIZ` (32,000 bytes)

Sources: [src/myutils.cpp:146-636](), [src/myutils.h:145-205]()

### Memory and Resource Tracking

```mermaid
graph TD
    subgraph "Memory Tracking"
        A["GetMemUseBytes"] --> B["Platform Detection"]
        B --> C["Windows: GetProcessMemoryInfo"]
        B --> D["Linux: /proc/PID/statm"]
        B --> E["macOS: task_info"]
        C --> F["g_PeakMemUseBytes"]
        D --> F
        E --> F
    end
    
    subgraph "Resource Reporting"
        G["LogElapsedTimeAndRAM"] --> H["GetElapsedSecs"]
        G --> I["MemBytesToStr"]
        G --> J["Progress Output"]
        K["GetPhysMemBytes"] --> L["Total System RAM"]
        M["GetUsableMemBytes"] --> N["Available for Process"]
    end
```

Platform-specific memory tracking implementations:

| Platform | Method | Implementation |
|----------|---------|----------------|
| Windows | `GetProcessMemoryInfo()` | Uses Windows API |
| Linux | `/proc/PID/statm` | Reads process memory statistics |
| macOS | `task_info()` | Uses Mach API |

Sources: [src/myutils.cpp:704-960](), [src/myutils.h:271-274]()

### Progress Tracking and Logging

The progress system provides real-time feedback with memory usage and timing information:

```mermaid
graph LR
    subgraph "Progress System"
        A["Progress"] --> B["GetProgressPrefixStr"]
        B --> C["Elapsed Time"]
        B --> D["Memory Usage"]
        C --> E["SecsToHHMMSS"]
        D --> F["MemBytesToStr"]
        E --> G["Output Formatting"]
        F --> G
    end
    
    subgraph "Logging Integration"
        H["ProgressLog"] --> I["Log File"]
        H --> J["stderr Output"]
        K["Die_"] --> L["Error Logging"]
        K --> M["Stack Trace"]
        L --> N["g_fLog"]
    end
```

Sources: [src/myutils.cpp:1265-1556](), [src/myutils.h:246-259]()

## Memory Management System

The reseek codebase implements a custom memory management system with optional debug tracking:

### Production Memory Management

```mermaid
graph TD
    subgraph "Production Mode"
        A["myalloc"] --> B["mymalloc"]
        B --> C["malloc"]
        C --> D["User Pointer"]
        E["myfree"] --> F["free"]
    end
    
    subgraph "Debug Mode"
        G["myalloc"] --> H["mymalloc_lo"]
        H --> I["mem_data Header"]
        I --> J["malloc + metadata"]
        J --> K["InsertBlock"]
        K --> L["s_BlockList"]
        M["myfree"] --> N["DeleteBlock"]
        N --> O["Magic Check"]
        O --> P["free"]
    end
```

The system supports two compilation modes:

| Mode | Features | Performance |
|------|----------|-------------|
| Production | Direct malloc/free | High performance |
| Debug | Leak tracking, magic numbers | Development debugging |

Sources: [src/mymalloc.h:1-36](), [src/mymalloc_dbg.cpp:1-377]()

### Debug Memory Tracking

When `MYMALLOC_DBG` is enabled, the system provides comprehensive memory tracking:

```mermaid
graph LR
    subgraph "Memory Block Tracking"
        A["mem_data"] --> B["magic: 0x3e3e3e3e"]
        A --> C["fn: source file"]
        A --> D["linenr: line number"]
        A --> E["bytes: allocation size"]
        A --> F["idx: allocation index"]
        A --> G["secs: timestamp"]
    end
    
    subgraph "Linked List Management"
        H["s_BlockList"] --> I["fwd pointer"]
        I --> J["bwd pointer"]
        J --> K["InsertBlock"]
        K --> L["DeleteBlock"]
    end
    
    subgraph "Reporting"
        M["mymalloc_print_summary"] --> N["Memory Statistics"]
        O["mymalloc_write_state"] --> P["Block Dump"]
        Q["mymalloc_trace"] --> R["Allocation Log"]
    end
```

Debug features include:

- **Magic Number Validation**: Detects memory corruption
- **Source Location Tracking**: Records file and line of allocation
- **Leak Detection**: Maintains active allocation list
- **Memory Maps**: Dumps process memory layout (Linux)
- **Periodic Reporting**: Automatic memory usage summaries

Sources: [src/mymalloc_dbg.cpp:12-377]()

## Specialized Memory Classes

### Matrix Template Class

The `Mx<T>` template provides efficient 2D array management:

```mermaid
graph TD
    subgraph "Mx Template Structure"
        A["Mx<T>"] --> B["m_RowCount"]
        A --> C["m_ColCount"]
        A --> D["m_Data: T**"]
        A --> E["m_Buffer: T*"]
    end
    
    subgraph "Memory Layout"
        F["ONE_BUFFER Mode"] --> G["Single Allocation"]
        G --> H["Contiguous Memory"]
        H --> I["Row Pointers"]
        I --> J["Column Access"]
    end
    
    subgraph "Operations"
        K["Alloc"] --> L["FreeData"]
        L --> M["myalloc"]
        M --> N["Pointer Setup"]
        O["Get/Put"] --> P["Bounds Checking"]
    end
```

Key design features:

- **Single Buffer Mode**: Allocates contiguous memory for better cache performance
- **Type Safety**: Template-based with compile-time type checking
- **Automatic Cleanup**: RAII-style memory management
- **Bounds Checking**: Debug-mode range validation

Sources: [src/mx.h:8-138](), [src/mx.cpp:1-16]()

### XDPMem Class

The `XDPMem` class provides specialized memory management for dynamic programming algorithms:

```mermaid
graph LR
    subgraph "XDPMem Components"
        A["XDPMem"] --> B["m_LA: sequence length A"]
        A --> C["m_LB: sequence length B"]
        A --> D["m_TBBit: traceback matrix"]
        A --> E["m_RevA: reversed sequence A"]
        A --> F["m_RevB: reversed sequence B"]
        A --> G["m_Buffer1: DP row buffer"]
        A --> H["m_Buffer2: DP row buffer"]
        A --> I["m_Buffer1_Int: integer buffer"]
    end
    
    subgraph "Buffer Management"
        J["Alloc"] --> K["Clear existing"]
        K --> L["Allocate all buffers"]
        L --> M["Set dimensions"]
        N["Clear"] --> O["myfree all"]
        O --> P["Reset pointers"]
    end
```

The XDPMem class supports:

- **Sequence Alignment**: Buffers for forward and reverse sequences
- **Traceback Matrix**: 2D array for alignment path reconstruction
- **Double Buffering**: Alternating row buffers for space efficiency
- **Mixed Types**: Both float and integer buffers for different algorithms

Sources: [src/xdpmem.h:15-132]()

## Platform Support

The utilities module provides comprehensive cross-platform support:

```mermaid
graph TD
    subgraph "Platform Detection"
        A["GetPlatform"] --> B["BITS: 32/64"]
        B --> C["Compiler Check"]
        C --> D["win32/win64"]
        C --> E["i86osx32/i86osx64"]
        C --> F["i86linux32/i86linux64"]
    end
    
    subgraph "Platform-Specific Features"
        G["Windows"] --> H["_MSC_VER"]
        H --> I["Windows API"]
        I --> J["GetProcessMemoryInfo"]
        K["Linux"] --> L["__GNUC__"]
        L --> M["/proc filesystem"]
        M --> N["Process statistics"]
        O["macOS"] --> P["__MACH__"]
        P --> Q["Mach API"]
        Q --> R["task_info"]
    end
```

Platform-specific implementations:

| Feature | Windows | Linux | macOS |
|---------|---------|--------|-------|
| Memory Usage | `GetProcessMemoryInfo()` | `/proc/PID/statm` | `task_info()` |
| Physical Memory | `GlobalMemoryStatusEx()` | `/proc/meminfo` | `sysctlbyname()` |
| File Operations | Win32 API | POSIX | POSIX |
| Sleep Function | `Sleep()` | `usleep()` | `usleep()` |

Sources: [src/myutils.cpp:77-104](), [src/myutils.cpp:831-960]()

---