

Lepton is OpenMM's embedded mathematical expression parser and compiler — a self-contained library at [`libraries/lepton/`](/openmm/openmm/tree/master/libraries/lepton) that transforms human-readable mathematical strings into highly optimized, JIT-compiled evaluation kernels. Every custom force, custom integrator, and tabulated function in OpenMM passes through Lepton at some point, making it the computational backbone of OpenMM's extensibility model. This page dissects Lepton's architecture from parse to machine code, revealing how a string like `"5*k*x^2 - sigma/sqrt(r)"` becomes native assembly executing at nanosecond latency.

## Architecture Overview

Lepton implements a multi-stage compilation pipeline: **lexing → parsing → AST construction → optimization → code generation**. Each stage produces a progressively more specialized representation, culminating in either a stack-based virtual machine (`ExpressionProgram`), a JIT-compiled function pointer (`CompiledExpression`), or a SIMD-vectorized kernel (`CompiledVectorExpression`). All representations originate from a single entry point — the `Parser` — and share a common abstract syntax tree (AST) defined by `ExpressionTreeNode`.

```mermaid
flowchart LR
    A["String Expression\n\"5*k*x^2 - sigma/sqrt(r)\""] --> B["Parser\nTokenize + Recursive Descent"]
    B --> C["ParsedExpression\nAbstract Syntax Tree"]
    C --> D["optimize()\nConstant Folding + Algebraic Simplification"]
    D --> E["ExpressionProgram\nStack-Based VM"]
    D --> F["CompiledExpression\nJIT-Compiled (asmjit)"]
    D --> G["CompiledVectorExpression\nSIMD Vectorized (AVX/NEON)"]
    
    C --> H["differentiate(x)\nSymbolic Derivative AST"]
    
    style A fill:#4a5568,color:#fff
    style F fill:#e53e3e,color:#fff
    style G fill:#e53e3e,color:#fff
```

The pipeline is strictly linear in the forward direction, but the AST representation at center is fully introspectable — it supports symbolic differentiation, variable renaming, and subexpression substitution, making it as useful for code analysis as for evaluation.

Sources: [Lepton.h](/openmm/openmm/blob/master/libraries/lepton/include/Lepton.h), [ParsedExpression.h](/openmm/openmm/blob/master/libraries/lepton/include/lepton/ParsedExpression.h#L47-L141)

## Module Structure

Lepton's implementation is compact and intentionally header-oriented, with all public API surfaces in `include/lepton/` and corresponding implementations in `src/`.

```
libraries/lepton/
├── include/
│   ├── Lepton.h                          # Aggregate include (single entry point)
│   └── lepton/
│       ├── Parser.h                      # Expression parser (static methods)
│       ├── ParsedExpression.h            # AST wrapper + optimization API
│       ├── ExpressionTreeNode.h          # AST node (Operation + children)
│       ├── Operation.h                   # Operation base class + 40+ subclasses
│       ├── ExpressionProgram.h           # Stack-based VM representation
│       ├── CompiledExpression.h          # JIT-compiled scalar evaluator
│       ├── CompiledVectorExpression.h    # SIMD-vectorized evaluator (float32)
│       ├── CustomFunction.h              # User-defined function interface
│       └── Exception.h                   # Lepton exception type
└── src/
    ├── Parser.cpp                        # Recursive descent + precedence climbing
    ├── ParsedExpression.cpp              # Optimization & symbolic differentiation
    ├── ExpressionTreeNode.cpp            # Node management + tree tag assignment
    ├── Operation.cpp                     # Operation implementations + derivatives
    ├── ExpressionProgram.cpp             # AST → stack program compilation
    ├── CompiledExpression.cpp            # AST → JIT compilation (x86/ARM)
    └── CompiledVectorExpression.cpp      # AST → SIMD JIT compilation
```

Sources: [Lepton.h](/openmm/openmm/blob/master/libraries/lepton/include/Lepton.h#L1-L42), [Operation.h](/openmm/openmm/blob/master/libraries/lepton/include/lepton/Operation.h#L1-L150)

## The Operation Taxonomy

Every node in a Lepton AST is an `Operation` — a polymorphic base class with 41 concrete subclasses enumerated in `Operation::Id`. Operations are the atomic units of computation, and each carries full responsibility for evaluation, cloning, and symbolic differentiation. This design means adding a new function requires implementing exactly one class.

The full operation set, organized by semantic category:

| Category | Operations | Arity |
|----------|-----------|-------|
| **Literals** | `CONSTANT`, `VARIABLE` | 0 |
| **Arithmetic** | `ADD`, `SUBTRACT`, `MULTIPLY`, `DIVIDE`, `POWER`, `NEGATE` | 2, 2, 2, 2, 2, 1 |
| **Specialized Arithmetic** | `ADD_CONSTANT`, `MULTIPLY_CONSTANT`, `POWER_CONSTANT`, `SQUARE`, `CUBE`, `RECIPROCAL` | 1, 1, 1, 1, 1, 1 |
| **Transcendental** | `SQRT`, `EXP`, `LOG` | 1 each |
| **Trigonometric** | `SIN`, `COS`, `TAN`, `SEC`, `CSC`, `COT`, `ASIN`, `ACOS`, `ATAN`, `ATAN2` | 1 each (ATAN2: 2) |
| **Hyperbolic** | `SINH`, `COSH`, `TANH` | 1 each |
| **Special Functions** | `ERF`, `ERFC`, `STEP`, `DELTA` | 1 each |
| **Rounding/Selection** | `FLOOR`, `CEIL`, `MIN`, `MAX`, `ABS`, `SELECT` | 1, 1, 2, 2, 1, 3 |
| **Extensibility** | `CUSTOM` | Variable |

The "specialized arithmetic" operations — `ADD_CONSTANT`, `MULTIPLY_CONSTANT`, and `POWER_CONSTANT` — are **not parseable directly**. They are generated exclusively by the optimizer as replacements for binary operations where one operand is a known constant. This distinction is critical: it allows the JIT backend to emit a single `addsd` instruction instead of loading a constant from memory and adding, eliminating an entire memory access per evaluation.

Sources: [Operation.h](/openmm/openmm/blob/master/libraries/lepton/include/lepton/Operation.h#L78-L101)

## Parsing: Recursive Descent with Precedence Climbing

The `Parser` class exposes two static overloads of `parse()` — one accepting an expression string alone, and another accepting a map of `CustomFunction*` for user-defined extensions. Internally, parsing proceeds in three phases.

**Phase 1: Subexpression extraction.** Lepton supports inline subexpression definitions via semicolons. The parser splits the input on `;` characters from right to left, extracting named subexpressions (e.g., `temp=x^2`) that become available as variables in subsequent expressions. The final segment (before the last `;`, or the entire string if no `;` exists) is the primary expression.

**Phase 2: Tokenization.** The tokenizer walks the string character-by-character, classifying each span into one of seven token types: `Number`, `Operator`, `Variable`, `Function`, `LeftParen`, `RightParen`, `Comma`, or `Whitespace`. Numbers support decimal points and scientific notation (`3.14e-2`). The key disambiguation is between variables and functions: a function is any identifier immediately followed by `(`, stripped of its trailing parenthesis before lookup.

**Phase 3: Recursive descent with precedence climbing.** `parsePrecedence()` implements a Pratt parser. The precedence table is minimal — four levels for `+`/`-` (0), `*`/`/` (1), `^` (3), with unary `-` at level 2. Power is **right-associative** (`2^3^4 = 2^(3^4)`), while all other binary operators are left-associative. This matches standard mathematical convention.

```cpp
static const int Precedence[] = {0, 0, 1, 1, 3};  // +, -, *, /, ^
static const bool LeftAssociative[] = {true, true, true, true, false};
```

The parser constructs `ExpressionTreeNode` objects bottom-up. Each node owns an `Operation*` (heap-allocated, cloned on copy) and a vector of child nodes. Variables are resolved against the subexpression definitions first, falling back to `Operation::Variable` if not found, which means user-defined subexpressions shadow built-in variable names.

Sources: [Parser.h](/openmm/openmm/blob/master/libraries/lepton/include/lepton/Parser.h#L47-L76), [Parser.cpp](/openmm/openmm/blob/master/libraries/lepton/src/Parser.cpp#L48-L53)

## ParsedExpression: The AST Gateway

`ParsedExpression` wraps an `ExpressionTreeNode` root and provides the complete surface for analysis and transformation. It is the central hub of Lepton's API — every compilation target and every symbolic operation is a method on this class.

### Evaluation

Two overloads of `evaluate()` exist: a parameterless version that requires the expression to be constant-free, and a version accepting `std::map<std::string, double>` for variable binding. Evaluation is recursive — each node evaluates its children, then invokes `Operation::evaluate()`. This is correct but slow for repeated evaluation, which is why `CompiledExpression` exists.

### Optimization

The `optimize()` method applies a multi-pass transformation pipeline:

1. **Tag assignment** — `assignTags()` assigns unique integer tags to structurally identical subtrees, enabling memoization via `nodeCache` (a `map<int, ExpressionTreeNode>` keyed by tag).
2. **Constant subexpression folding** — `precalculateConstantSubexpressions()` walks the tree bottom-up. Any subtree whose children are all `CONSTANT` operations is evaluated at compile time and replaced with a single `CONSTANT` node.
3. **Algebraic simplification** — `substituteSimplerExpression()` applies pattern-matching rewrites in a loop until convergence (fixed-point). The rewrite rules are extensive and include identity elimination (`x+0=x`, `x*1=x`), strength reduction (`x/const → x*(1/const)` via `MULTIPLY_CONSTANT`), double negation cancellation, reciprocal normalization (`a*(1/b) → a/b`), power specialization (`x^2 → SQUARE`, `x^0.5 → SQRT`, `x^-1 → RECIPROCAL`), and duplicate elimination (`x*x → SQUARE`, `x*x*x → CUBE`, `x-x → 0`).

An overloaded `optimize(map<string, double>)` variant pre-evaluates specific variables to constants before running the optimization pipeline, enabling partial evaluation when some parameters are known at setup time.

Sources: [ParsedExpression.cpp](/openmm/openmm/blob/master/libraries/lepton/src/ParsedExpression.cpp#L62-L429)

### Symbolic Differentiation

The `differentiate(variable)` method constructs a new AST representing the analytical derivative with respect to a named variable. Each `Operation` subclass implements its own chain-rule logic via the `differentiate()` virtual method, receiving both the child nodes and their already-computed derivatives. The recursion is memoized via `nodeCache` (keyed by tag), so common subexpressions are differentiated exactly once. The resulting AST can itself be optimized, creating derivative expressions suitable for JIT compilation.

This facility is how OpenMM computes forces from energy expressions in `CustomForce` subclasses — the energy expression is parsed once, differentiated symbolically with respect to each particle coordinate, and the resulting derivative expressions are compiled for inner-loop evaluation.

Sources: [ParsedExpression.cpp](/openmm/openmm/blob/master/libraries/lepton/src/ParsedExpression.cpp#L387-L408)

### Additional Transformations

- **`renameVariables(map<string, string>)`** — performs a global find-and-replace of variable names throughout the AST, used by OpenMM when mapping generic expression variables to specific particle properties.
- **`createProgram()`** — compiles the AST to a stack-based `ExpressionProgram` (see below).
- **`createCompiledExpression()`** — compiles to a `CompiledExpression` with optional JIT.
- **`createCompiledVectorExpression(width)`** — compiles to a `CompiledVectorExpression` for SIMD batch evaluation.

Sources: [ParsedExpression.h](/openmm/openmm/blob/master/libraries/lepton/include/lepton/ParsedExpression.h#L100-L131)

## ExpressionProgram: Stack-Based Virtual Machine

`ExpressionProgram` linearizes the AST into a flat sequence of `Operation*` objects executed against a stack. Each operation pops its arguments, evaluates, and pushes the result. The class tracks `maxArgs` (the maximum argument count of any operation) and `stackSize` (the maximum stack depth encountered during compilation) for pre-allocation.

This representation is portable — it works on any platform without JIT support — but introduces per-operation dispatch overhead and prevents the compiler from eliminating intermediate temporaries. In practice, `ExpressionProgram` serves as a fallback and as a debugging aid (you can inspect individual operations via `getOperation(index)`). Performance-critical paths use `CompiledExpression` instead.

Sources: [ExpressionProgram.h](/openmm/openmm/blob/master/libraries/lepton/include/lepton/ExpressionProgram.h#L36-L102)

## CompiledExpression: JIT-Compiled Scalar Evaluator

`CompiledExpression` is Lepton's primary performance target. It compiles the AST into a flat operation array with pre-assigned workspace slots, then optionally generates native machine code via the **asmjit** dynamic compiler (conditionally enabled via `LEPTON_USE_JIT`).

### Workspace Model

Unlike the stack-based `ExpressionProgram`, `CompiledExpression` allocates a contiguous `workspace` vector where each intermediate result has a fixed slot index. Variables map to dedicated workspace indices (settable by the caller via `getVariableReference()`), and every operation writes its result to a pre-determined `target` slot. This eliminates stack management overhead and allows sequential argument optimization — when arguments occupy contiguous workspace slots, the JIT emits a pointer to the first slot rather than gathering scattered values.

### Variable Binding

Two binding mechanisms exist:

- **`getVariableReference(name)`** — returns a `double&` referencing the variable's slot in the internal workspace. Setting this reference before `evaluate()` provides the variable's value.
- **`setVariableLocations(map<string, double*>)`** — redirects variable reads to external memory addresses. This is critical when multiple compiled expressions share variables (e.g., a force expression and its derivative both reading particle coordinates). On JIT builds, changing variable locations triggers `generateJitCode()` to regenerate the machine code with updated memory references.

The `variablesToCopy` vector tracks which external pointers need to be copied into the workspace before evaluation, populating a simple pre-evaluation loop.

Sources: [CompiledExpression.h](/openmm/openmm/blob/master/libraries/lepton/include/lepton/CompiledExpression.h#L63-L95)

### JIT Compilation via asmjit

When `LEPTON_USE_JIT` is defined at build time, the constructor invokes `generateJitCode()` after workspace allocation. The JIT backend is **architecture-aware**, using `asmjit::x86::Compiler` for Intel/AMD and `asmjit::a64::Compiler` for ARM64. The generated code follows a consistent pattern:

1. **Variable loading** — emit `mov`/`ldr` instructions to load variable values from their bound addresses into hardware registers.
2. **Constant loading** — pre-compute all constant values used by operations (`CONSTANT`, `ADD_CONSTANT`, `MULTIPLY_CONSTANT`, `POWER_CONSTANT`, `RECIPROCAL`, `STEP`, `DELTA`) into a `constants` vector, then load them into registers. Deduplication ensures each unique constant is loaded exactly once.
3. **Power grouping** — `findPowerGroups()` identifies clusters of `SQUARE`, `CUBE`, and `POWER_CONSTANT` operations that share the same base argument and have powers with the same sign. These are evaluated together using an exponentiation-by-squaring algorithm, reducing the number of multiplications. For example, computing x², x³, and x⁵ simultaneously requires only 3 multiplications instead of 6.
4. **Operation emission** — each remaining operation is translated to native instructions. Transcendental functions (`sin`, `cos`, `exp`, `log`, etc.) use `generateSingleArgCall()` / `generateTwoArgCall()`, which emit a sequence to move arguments to the calling convention registers, execute a `call` to the libc function, and retrieve the result.

The generated function pointer is stored as `double (*jitCode)()`, and `evaluate()` simply calls `jitCode()` when available, falling back to the interpreted loop otherwise.

> [!TIP]
> **Thread safety constraint**: `CompiledExpression` is explicitly NOT thread-safe. Each instance maintains mutable workspace state (`mutable std::vector<double> workspace`). In multi-threaded contexts (which is the norm in OpenMM's force evaluation loops), each thread must have its own `CompiledExpression` instance, or external synchronization must be applied.

Sources: [CompiledExpression.cpp](/openmm/openmm/blob/master/libraries/lepton/src/CompiledExpression.cpp#L19-L80), [CompiledExpression.cpp](/openmm/openmm/blob/master/libraries/lepton/src/CompiledExpression.cpp#L201-L350)

## CompiledVectorExpression: SIMD-Vectorized Evaluator

`CompiledVectorExpression` extends the compilation model to evaluate the same expression across **multiple data points simultaneously** using the CPU's vector unit (AVX on x86, NEON on ARM). This is designed for batch scenarios such as evaluating a bonded force across many bonds in a single vector pass.

### Key Design Differences from CompiledExpression

| Aspect | CompiledExpression | CompiledVectorExpression |
|--------|-------------------|--------------------------|
| **Precision** | `double` (64-bit) | `float` (32-bit) |
| **Vector width** | Scalar (1) | Configurable: 4 (always), 8 (AVX) |
| **Variable access** | `double& getVariableReference()` | `float* getVariablePointer()` → pointer to N floats |
| **JIT backend** | `asmjit::x86::Xmm` / `arm::Vec` | `asmjit::x86::Ymm` / `arm::Vec` |
| **Output** | `double evaluate()` | `const float* evaluate()` → pointer to N results |
| **Width query** | N/A | `static getAllowedWidths()` |

The workspace uses `std::vector<float>` instead of `double`, and variables are accessed as arrays of `width` floats. The `getAllowedWidths()` static method probes CPU features at runtime via CPUID (x86) or equivalent (ARM) to determine supported vector widths.

> [!TIP]
> **Precision trade-off**: The switch to single-precision (`float`) in `CompiledVectorExpression` is deliberate — AVX2 256-bit registers hold 8 × `float` but only 4 × `double`, so the throughput advantage is 2× for single-precision vectorized evaluation. OpenMM uses `CompiledVectorExpression` primarily in nonbonded force kernels where single precision is scientifically acceptable due to the use of mixed-precision force accumulation strategies.

Sources: [CompiledVectorExpression.h](/openmm/openmm/blob/master/libraries/lepton/include/lepton/CompiledVectorExpression.h#L38-L100)

## CustomFunction: Extending the Operation Set

`CustomFunction` is an abstract interface that allows users to inject arbitrary functions into expressions. To define a custom function, you implement four methods:

```cpp
class LEPTON_EXPORT CustomFunction {
    virtual int getNumArguments() const = 0;
    virtual double evaluate(const double* arguments) const = 0;
    virtual double evaluateDerivative(const double* arguments, const int* derivOrder) const = 0;
    virtual CustomFunction* clone() const = 0;
};
```

The `evaluateDerivative()` method accepts a `derivOrder` array where `derivOrder[i]` specifies how many times the function has been differentiated with respect to argument `i`. For example, `{0, 2}` means ∂²f/∂x₂². This multi-index scheme supports mixed partial derivatives, which is essential for expressions like `custom(r, dr/dx)` where nested differentiation is needed.

Custom functions are registered with the parser via a `map<string, CustomFunction*>` passed to `Parser::parse()`. At parse time, if a function name matches a custom function key, an `Operation::Custom` node is created that wraps a cloned copy of the `CustomFunction`. This ensures each AST node owns its function instance, making the tree safe to copy and persist.

The `PlaceholderFunction` subclass is a convenience for analysis-only scenarios — it returns 0.0 for all evaluations and derivatives while correctly reporting the expected argument count, allowing parsers to accept expressions containing unknown custom functions without attempting numerical evaluation.

Sources: [CustomFunction.h](/openmm/openmm/blob/master/libraries/lepton/include/lepton/CustomFunction.h#L36-L108)

## Optimization Rules Catalog

The `substituteSimplerExpression()` method in [`ParsedExpression.cpp`](/openmm/openmm/blob/master/libraries/lepton/src/ParsedExpression.cpp#L130-L384) implements a comprehensive algebraic simplification engine. Below is the complete rule set, organized by operation:

| Source Pattern | Result | Operation |
|---------------|--------|-----------|
| `ADD(x, 0)` | `x` | Identity |
| `ADD(x, -y)` | `SUBTRACT(x, y)` | Sign normalization |
| `SUBTRACT(x, x)` | `CONSTANT(0)` | Self-cancellation |
| `MULTIPLY(x, 0)` | `CONSTANT(0)` | Zero absorption |
| `MULTIPLY(x, 1)` | `x` | Identity |
| `MULTIPLY(x, -y)` | `NEGATE(MULTIPLY(x, y))` | Sign extraction |
| `MULTIPLY(x, RECIP(y))` | `DIVIDE(x, y)` | Reciprocal normalization |
| `MULTIPLY(x, x)` | `SQUARE(x)` | Squaring detection |
| `MULTIPLY(SQUARE(x), x)` | `CUBE(x)` | Cubing detection |
| `DIVIDE(x, x)` | `CONSTANT(1)` | Self-cancellation |
| `DIVIDE(0, x)` | `CONSTANT(0)` | Zero numerator |
| `DIVIDE(1, x)` | `RECIPROCAL(x)` | Unit numerator |
| `DIVIDE(x, 1)` | `x` | Identity |
| `DIVIDE(x, RECIP(y))` | `MULTIPLY(x, y)` | Reciprocal cancellation |
| `POWER(0, n)` | `CONSTANT(0)` | Zero base |
| `POWER(1, n)` | `CONSTANT(1)` | Unit base |
| `POWER(x, 0)` | `CONSTANT(1)` | Zero exponent |
| `POWER(x, 1)` | `x` | Identity |
| `POWER(x, -1)` | `RECIPROCAL(x)` | Negative identity |
| `POWER(x, 2)` | `SQUARE(x)` | Squaring specialization |
| `POWER(x, 3)` | `CUBE(x)` | Cubing specialization |
| `POWER(x, 0.5)` | `SQRT(x)` | Square root specialization |
| `NEGATE(NEGATE(x))` | `x` | Double negation |
| `MULTIPLY_CONST(a, MULTIPLY_CONST(b, x))` | `MULTIPLY_CONST(a*b, x)` | Constant folding |
| `SQRT(SQUARE(x))` | `ABS(x)` | Inverse relationship |
| `SQUARE(SQRT(x))` | `x` | Inverse relationship |
| `SELECT(x, y, y)` | `y` | Trivial selection |

Constant-argument operations with non-specialized constants are reduced to the corresponding `*_CONSTANT` operation variants (`ADD_CONSTANT`, `MULTIPLY_CONSTANT`, `POWER_CONSTANT`), which the JIT backend handles as immediate operands rather than memory loads.

Sources: [ParsedExpression.cpp](/openmm/openmm/blob/master/libraries/lepton/src/ParsedExpression.cpp#L130-L384)

## Integration with OpenMM's Custom Forces

Lepton's design is inseparable from its role in OpenMM. The [Custom Forces and Integrators](18-lepton-expression-engine) system uses Lepton at three critical points:

1. **Expression parsing at construction time** — when a `CustomBondForce`, `CustomNonbondedForce`, or `CustomIntegrator` receives an energy/per-particle update expression, it immediately calls `Parser::parse()` to validate syntax and produce an AST.
2. **Symbolic differentiation for force computation** — the energy expression is differentiated with respect to each degree of freedom using `ParsedExpression::differentiate()`. The resulting derivative expressions are optimized and compiled.
3. **JIT compilation for inner-loop evaluation** — the compiled expressions are evaluated millions of times per simulation step (once per bond, per particle pair, per particle, depending on the force type). The combination of constant folding (per-particle parameters like charges and masses become constants), specialized constant operations, and power grouping makes this feasible.

The variable sharing mechanism (`setVariableLocations()`) is particularly important here — multiple force expressions and their derivatives can all read from the same coordinate array, avoiding data duplication and ensuring consistency without explicit synchronization.

Sources: [CompiledExpression.h](/openmm/openmm/blob/master/libraries/lepton/include/lepton/CompiledExpression.h#L63-L80)

## API Quick Reference

| Class | Key Method | Purpose |
|-------|-----------|---------|
| `Parser` | `parse(string)` / `parse(string, customFunctions)` | Entry point: string → `ParsedExpression` |
| `ParsedExpression` | `evaluate()` / `evaluate(variables)` | Direct recursive evaluation |
| `ParsedExpression` | `optimize()` / `optimize(variables)` | Constant folding + algebraic simplification |
| `ParsedExpression` | `differentiate(variable)` | Symbolic differentiation → new `ParsedExpression` |
| `ParsedExpression` | `renameVariables(replacements)` | Global variable renaming |
| `ParsedExpression` | `createProgram()` | Compile to stack VM |
| `ParsedExpression` | `createCompiledExpression()` | Compile to JIT (scalar, double) |
| `ParsedExpression` | `createCompiledVectorExpression(width)` | Compile to JIT (SIMD, float) |
| `CompiledExpression` | `getVariableReference(name)` | Bind variable → `double&` |
| `CompiledExpression` | `setVariableLocations(map)` | Redirect variables to external memory |
| `CompiledExpression` | `evaluate()` | Execute compiled expression |
| `CompiledVectorExpression` | `getVariablePointer(name)` | Bind variable → `float*` |
| `CompiledVectorExpression` | `evaluate()` | Execute vectorized expression → `float*` |
| `CompiledVectorExpression` | `getAllowedWidths()` | Query CPU SIMD capabilities |
| `CustomFunction` | `evaluate()`, `evaluateDerivative()` | Define user functions with derivative support |
| `PlaceholderFunction` | Constructor `(numArgs)` | Stub function for analysis-only parsing |
