# Exception Handling

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.astyle.options](.astyle.options)
- [.ci/install.autoconf](.ci/install.autoconf)
- [.codecov.yml](.codecov.yml)
- [.gitignore](.gitignore)
- [Makefile](Makefile)
- [Makefile.conf.in](Makefile.conf.in)
- [astyle/.gitignore](astyle/.gitignore)
- [astyle/Makefile](astyle/Makefile)
- [configure](configure)
- [configure.ac](configure.ac)
- [developer-doc/InstallationLayout.md](developer-doc/InstallationLayout.md)
- [src/Makefile](src/Makefile)
- [src/README](src/README)
- [src/asmjit/COPYRIGHT](src/asmjit/COPYRIGHT)
- [src/asmjit/Makefile](src/asmjit/Makefile)
- [src/asmjit/arm.h](src/asmjit/arm.h)
- [src/asmjit/asmjit.h](src/asmjit/asmjit.h)
- [src/astyle.sh](src/astyle.sh)
- [src/lib/Makefile](src/lib/Makefile)
- [src/maketools/codecheck](src/maketools/codecheck)
- [src/maketools/make.rules](src/maketools/make.rules)
- [src/maketools/plumedcheck](src/maketools/plumedcheck)
- [src/tools/Exception.cpp](src/tools/Exception.cpp)
- [src/tools/Exception.h](src/tools/Exception.h)

</details>



This page documents the error and exception handling mechanisms within the PLUMED codebase. Exception handling in PLUMED is designed to provide robust, context-rich error reporting for both developers and users, with detailed messages, file/line/function information, and optional stack traces. The system is tightly integrated with the build and quality system, and is enforced by code quality tools.

---

## Exception Class Hierarchy and Code Entities

PLUMED implements a custom exception system based on C++ exceptions. The main class is `PLMD::Exception`, which derives from `std::exception`. Several specialized exception types are provided for different error categories.

**Exception Class Hierarchy Diagram**

```mermaid
classDiagram
    "std::exception" <|-- "PLMD::Exception"
    "PLMD::Exception" <|-- "PLMD::ExceptionError"
    "PLMD::Exception" <|-- "PLMD::ExceptionDebug"
    "PLMD::Exception" <|-- "PLMD::ExceptionTypeError"

    class "PLMD::Exception" {
      - "std::string msg"
      - "std::stringstream stream"
      - "std::array<void*,128> callstack"
      - "int callstack_n"
      - "std::string stackTrace"
      + "what() const"
      + "stack() const"
      + "operator<<(const std::string&)"
      + "operator<<(const Location&)"
      + "operator<<(const Assertion&)"
    }
    class "PLMD::ExceptionError" {
      + "operator<<(const T&)"
    }
    class "PLMD::ExceptionDebug" {
      + "operator<<(const T&)"
    }
    class "PLMD::ExceptionTypeError" {
      + "operator<<(const T&)"
    }
```

**Key code entities:**
- `PLMD::Exception`
- `PLMD::ExceptionError`
- `PLMD::ExceptionDebug`
- `PLMD::ExceptionTypeError`

Sources: [src/tools/Exception.h:155-332]()

## Exception Flow and Propagation

When an error condition is detected, a `PLMD::Exception` (or derived type) is created and thrown. Contextual information (file, line, function) is attached automatically via macros. Exceptions propagate up the call stack and can be caught at any level.

**Exception Propagation Flow**

```mermaid
flowchart TD
    "DetectError"["Code detects error condition"] --> "CreateException"["PLMD::Exception or derived type is created"]
    "CreateException" --> "AddContext"["File, line, function info added (via macros)"]
    "AddContext" --> "ThrowException"["Exception is thrown"]
    "ThrowException" --> "Propagate"["Exception propagates up call stack"]
    "Propagate" --> "Catch?"{"Is exception caught?"}
    "Catch?" -- "Yes" --> "Handle"["Exception is handled (e.g., error message displayed)"]
    "Catch?" -- "No" --> "Terminate"["Program terminates with error message"]
```

Sources: [src/tools/Exception.h:135-146](), [src/cltools/Driver.cpp:640-643]()

## Exception Macros and Context Injection

PLUMED provides macros to simplify exception throwing and ensure that context (file, line, function) is always included. These macros are the standard way to report errors and assertions in the codebase.

| Macro | Description | Typical Usage |
|-------|-------------|--------------|
| `plumed_error()` | Throws a `PLMD::ExceptionError` with file/line/function info | `plumed_error() << "Failed to read file";` |
| `plumed_merror(msg)` | Same as above, but takes a message as argument | `plumed_merror("Failed to read file");` |
| `plumed_assert(test)` | Throws if `test` is false, with context | `plumed_assert(a > 0) << "a must be positive";` |
| `plumed_massert(test, msg)` | Throws if `test` is false, with message | `plumed_massert(a > 0, "a must be positive");` |
| `plumed_dbg_assert(test)` | Like `plumed_assert`, but only in debug builds | `plumed_dbg_assert(expensive_check());` |
| `plumed_dbg_massert(test, msg)` | Like `plumed_massert`, but only in debug builds | `plumed_dbg_massert(expensive_check(), "check failed");` |

All macros automatically inject file, line, and function information using the `plumed_here` macro, which creates a `PLMD::Exception::Location` object.

Sources: [src/tools/Exception.h:350-402]()

## Error Message Construction and Insertion Operator

The `PLMD::Exception` class supports the insertion operator (`<<`) for building detailed error messages. This allows developers to append arbitrary information, including variable values, to the exception message in a type-safe way.

**Error Message Construction Flow**

```mermaid
flowchart TD
    "ErrorDetected"["Error detected"] --> "CreateException"["Create PLMD::Exception"]
    "CreateException" --> "AddContext"["Add file/line/function info (via macro)"]
    "AddContext" --> "AddMessage"["Add custom message via <<"]
    "AddMessage" --> "AddValues"["Add variable values via <<"]
    "AddValues" --> "Throw"["Throw the exception"]
```

**Example Usage:**
- `plumed_error() << "Failed to read file";`
- `plumed_error() << "Invalid value: " << value;`
- `plumed_assert(a > 0) << "a must be positive, got a=" << a;`

Sources: [src/tools/Exception.h:86-111]()

## Stack Traces

PLUMED exceptions can include a stack trace, which is useful for debugging. Stack traces are captured using `backtrace` and `backtrace_symbols` (when available) and are included in the error message if the environment variable `PLUMED_STACK_TRACE` is set to `yes` at runtime.

**How to Enable Stack Traces:**
```sh
export PLUMED_STACK_TRACE=yes
```

When enabled, the stack trace is appended to the exception message.

Sources: [src/tools/Exception.cpp:86-96]()

## Exception Handling in Application and Library Code

Exceptions can be caught and handled at various levels. In command-line tools (e.g., `Driver`), exceptions are caught and error messages are printed to the user. In library usage, external codes can catch PLUMED exceptions as `std::exception`.

**Example:**
```cpp
try {
    plumed.cmd("calc");
} catch (const std::exception& e) {
    std::fprintf(stderr, "Error: %s\n", e.what());
    return 1;
}
```

In some cases (e.g., MPI environments), exceptions may trigger program termination.

Sources: [src/tools/Communicator.cpp:127-135](), [src/cltools/Driver.cpp:640-643]()

## Exception Safety and Resource Management

PLUMED code is written to provide basic exception safety. Resource management is typically handled using RAII (Resource Acquisition Is Initialization) patterns, such as `std::unique_ptr` with custom deleters for file handles and other resources. This ensures that resources are released even if an exception is thrown.

**Example:**
```cpp
std::unique_ptr<FILE, decltype(deleter)> fp_deleter(fp, deleter);
```

Sources: [src/cltools/Driver.cpp:349-356](), [src/cltools/SimpleMD.cpp:78-82]()

## Location and Assertion Information in Exceptions

The `PLMD::Exception` class contains nested classes for storing context:

- `PLMD::Exception::Location`: Stores file, line, and function name.
- `PLMD::Exception::Assertion`: Stores the failed assertion expression.
- `PLMD::Exception::Throw`: Used for nested exception support.

**Location and Assertion Class Diagram**

```mermaid
classDiagram
    "PLMD::Exception" o-- "PLMD::Exception::Location"
    "PLMD::Exception" o-- "PLMD::Exception::Assertion"
    "PLMD::Exception" o-- "PLMD::Exception::Throw"

    class "PLMD::Exception::Location" {
      + "const char* file"
      + "const unsigned line"
      + "const char* pretty"
      + "Location(file, line, pretty)"
    }
    class "PLMD::Exception::Assertion" {
      + "const char* assertion"
      + "Assertion(assertion)"
    }
    class "PLMD::Exception::Throw" {
      + "operator<<=()"
    }
```

The `plumed_here` macro creates a `Location` object with the current file, line, and function name.

Sources: [src/tools/Exception.h:173-195](), [src/tools/Exception.h:350-351]()

## Nested Exceptions

PLUMED supports nested exceptions using the C++11 `std::throw_with_nested` mechanism. This allows error context to be preserved across multiple layers of function calls.

**Nested Exception Propagation**

```mermaid
flowchart TD
    "LowLevelThrow"["Low-level function throws exception"] --> "MidLevelCatch"["Mid-level function catches exception"]
    "MidLevelCatch" --> "MidLevelThrowNested"["Mid-level function throws nested exception"]
    "MidLevelThrowNested" --> "HighLevelCatch"["High-level function catches nested exception"]
    "HighLevelCatch" --> "Report"["Error is reported with full context chain"]
```

The `plumed_error_nested()` macro is used to throw nested exceptions.

Sources: [src/tools/Exception.h:202-214](), [src/tools/Exception.h:364-365]()

## Error vs. Assertion Macros

PLUMED distinguishes between errors and assertions:

- **Errors** (`plumed_error`, `plumed_merror`): Used for conditions that should not occur in correct code, but may happen due to external factors (e.g., invalid input).
- **Assertions** (`plumed_assert`, `plumed_massert`): Used to check programming invariants that should never be violated.

**Decision Flow: Error or Assertion**

```mermaid
flowchart TD
    "IsInvariant"["Is the condition an invariant that should always be true?"] -- "Yes" --> "UseAssert"["Use assertion (plumed_assert)"]
    "IsInvariant" -- "No" --> "IsExpectedError"["Is it an expected error condition?"]
    "IsExpectedError" -- "Yes" --> "HandleNormally"["Handle normally (if/else)"]
    "IsExpectedError" -- "No" --> "UseError"["Use error (plumed_error)"]
```

Sources: [src/tools/Exception.h:95-104]()

## Debug Assertions

Debug assertions (`plumed_dbg_assert`, `plumed_dbg_massert`) are only active in debug builds (when `NDEBUG` is not defined). These are intended for expensive or development-only checks.

**Example:**
```cpp
plumed_dbg_assert(expensive_function(i) > 0) << "Value must be positive";
```

Sources: [src/tools/Exception.h:384-402]()

## Exception Handling in External Code

When PLUMED is used as a library in external code, exceptions can be caught and handled by the external code. This allows for graceful error handling and recovery.

```cpp
try {
    plumed.cmd("setPrecision", n);
} catch (const std::exception & e) {
    std::printf("PLUMED error: %s", e.what());
    exit(1);
}
```

Sources: [src/tools/Exception.h:132-140](src/tools/Exception.h:132-140)

---