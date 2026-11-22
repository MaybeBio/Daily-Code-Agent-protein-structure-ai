# Type System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [LICENSE](LICENSE)
- [chai_lab/__init__.py](chai_lab/__init__.py)
- [chai_lab/utils/typing.py](chai_lab/utils/typing.py)

</details>



This page documents the type checking infrastructure and validation utilities used throughout the Chai Lab codebase. The system ensures code correctness by validating data types both during development and at runtime, specifically focusing on the complex tensor shapes and multidimensional array operations used in the Chai-1 molecular structure prediction pipeline.

## Overview

Chai Lab employs a hybrid type checking approach that combines static type annotations with runtime type checking. This system is particularly valuable for catching errors in tensor shapes, dimensions, and data types which are critical in scientific computing applications like molecular modeling.

The type system is built on two specialized libraries:
- **beartype**: A high-performance runtime type checker for Python.
- **jaxtyping**: A type annotation system for JAX (and by extension, compatible tensor) arrays that provides shape and dtype checking.

## Type System Architecture

The following diagram illustrates how the type system is structured within the Chai Lab codebase, specifically focusing on the `typecheck` decorator logic.

**Diagram: Type System Validation Flow**
```mermaid
graph TD
    subgraph "Natural Language Requirements"
        Req["Need 3D coordinates for atoms [N, 3]"]
    end

    subgraph "Code Entity Space: chai_lab.utils.typing"
        TypeDec["typecheck decorator"]
        Flag["should_typecheck flag"]
        JaxTyped["jaxtyped"]
        BearType["beartype"]
        JaxCheck["jaxtyping checks"]
    end

    Req -->|"Implemented as"| FuncSig["Function Signature with jaxtyping annotations"]
    FuncSig --> TypeDec
    TypeDec -->|"Checks"| Flag
    
    Flag -->|"True"| JaxTyped
    Flag -->|"False"| NoOp["Return original function"]
    
    JaxTyped -->|"Uses"| BearType
    JaxTyped -->|"Uses"| JaxCheck
    
    BearType -->|"Validates"| ScalarArgs["Scalar & Object Types"]
    JaxCheck -->|"Validates"| TensorShapes["Tensor Shapes & Dtypes"]
```
Sources: [chai_lab/utils/typing.py:23-33](), [chai_lab/utils/typing.py:7-19]()

## Core Components

### The `typecheck` Decorator
The primary entry point for the type system is the `typecheck` decorator defined in `chai_lab/utils/typing.py`. It serves as a wrapper that conditionally enables runtime validation.

- **Implementation**: If `should_typecheck` is `True`, it returns the function or class wrapped by `jaxtyped(typechecker=beartype)`. Otherwise, it returns the original object with no runtime overhead [chai_lab/utils/typing.py:29-33]().
- **Scope**: It can be applied to both functions and classes [chai_lab/utils/typing.py:29-29]().

### Configuration: `should_typecheck`
The global flag `should_typecheck` controls the enforcement of types. 
- **Persistence**: Because modules are only loaded once, the value of `should_typecheck` remains constant over the lifetime of the program [chai_lab/utils/typing.py:21-23]().
- **Default**: It is currently set to `True` [chai_lab/utils/typing.py:23-23]().

### Re-exported Tensor Type Aliases
To provide a unified interface, `chai_lab.utils.typing` re-exports several key types from `jaxtyping`. These are used to annotate tensors (typically JAX or PyTorch arrays) throughout the model trunk and feature generation pipelines.

| Alias | Underlying jaxtyping Type | Description |
| :--- | :--- | :--- |
| `Bool` | `jaxtyping.Bool` | Boolean array/tensor |
| `Float` | `jaxtyping.Float` | Generic floating-point array |
| `Float32` | `jaxtyping.Float32` | 32-bit floating-point array |
| `Int` | `jaxtyping.Int` | Generic integer array |
| `Int32` | `jaxtyping.Int32` | 32-bit integer array |
| `UInt8` | `jaxtyping.UInt8` | 8-bit unsigned integer array |
| `Num` | `jaxtyping.Num` | Any numeric array (int or float) |
| `Shaped` | `jaxtyping.Shaped` | Array with a specific shape but any dtype |

Sources: [chai_lab/utils/typing.py:8-19](), [chai_lab/utils/typing.py:36-48]()

## Data Flow and Validation

The following diagram bridges the gap between the internal `typing` utilities and their application in the broader system (e.g., in the Inference Engine or Feature Assembly).

**Diagram: Application of Types in Model Pipeline**
```mermaid
graph LR
    subgraph "Natural Language Domain"
        ResidueData["Residue-level features"]
        AtomCoords["3D Atom Coordinates"]
    end

    subgraph "Code Entity Domain"
        direction TB
        Annot1["Int[N_residues]"]
        Annot2["Float[N_atoms, 3]"]
        Func["@typecheck<br/>def process_features(...)"]
        Err["TypeCheckError"]
    end

    ResidueData -.-> Annot1
    AtomCoords -.-> Annot2
    
    Annot1 --> Func
    Annot2 --> Func
    
    Func -->|"Invalid Shape/Type"| Err
    Func -->|"Valid"| Output["Result Tensor"]
```
Sources: [chai_lab/utils/typing.py:16-16](), [chai_lab/utils/typing.py:29-31]()

## Usage Patterns

### Function Decoration
Functions requiring strict shape validation are decorated with `@typecheck`. This is standard for functions handling MSA (Multiple Sequence Alignment) data, structural templates, or diffusion coordinates where dimensions like `[batch, atoms, 3]` must be strictly maintained.

```python
from chai_lab.utils.typing import typecheck, Float, Int32

@typecheck
def compute_loss(
    predictions: Float[..., "atoms", 3], 
    targets: Float[..., "atoms", 3],
    mask: Int32[..., "atoms"]
) -> Float[()]:
    ...
```

### Error Handling
When a type or shape mismatch occurs at runtime, the system raises a `TypeCheckError` [chai_lab/utils/typing.py:16-16](). This exception is re-exported in the `__all__` list of the typing utility for easy catching during testing or debugging [chai_lab/utils/typing.py:38-38]().

## Implementation Details

The core implementation in `chai_lab/utils/typing.py` is concise, leveraging the interoperability between `beartype` (for standard Python types) and `jaxtyping` (for array-specific logic).

```python
def typecheck(cls_or_func: Func) -> Func:
    if should_typecheck:
        return jaxtyped(typechecker=beartype)(cls_or_func)  # type: ignore
    else:
        return cls_or_func
```
Sources: [chai_lab/utils/typing.py:29-33]()

The use of `typing.TypeVar("Func")` ensures that the decorator maintains the type signature of the wrapped function or class for static analysis tools like `mypy` [chai_lab/utils/typing.py:26-29]().

Sources: [chai_lab/utils/typing.py:1-49]()

---