

The Transform Pipeline System in AtomWorks provides a powerful, composable framework for processing biological structure data through a sequence of modular transformations. This system enables both deterministic and stochastic data processing pipelines with built-in validation, error handling, and debugging capabilities.

## Core Architecture

At the heart of the transform system lies the abstract `Transform` class, which serves as the foundation for all data processing operations. Each transform operates on dictionary-based data structures, allowing flexible data flow through the pipeline while maintaining type safety and validation.

### Base Transform Class

The `Transform` abstract class defines the essential contract for all transformations:

- **Validation Framework**: Built-in input validation with configurable error handling
- **Dependency Management**: Transform dependency tracking through `requires_previous_transforms` and `incompatible_previous_transforms` attributes
- **History Tracking**: Optional transform history recording for debugging and reproducibility
- **Processing Time Monitoring**: Automatic timing of transform execution for performance analysis

```python
class Transform(ABC):
    validate_input: bool = True
    raise_if_invalid_input: bool = True
    requires_previous_transforms: ClassVar[list[str]] = []
    incompatible_previous_transforms: ClassVar[list[str]] = []
    previous_transforms_order_matters: bool = False
    _track_transform_history: bool = True
```

### Pipeline Composition

The `Compose` class enables sophisticated pipeline construction by chaining multiple transforms sequentially:

```python
class Compose(Transform):
    def __init__(self, transforms: list[Transform], track_rng_state: bool = True, print_rng_state: bool = False)
```

Key features include:
- **RNG State Tracking**: Essential for debugging stochastic pipelines
- **Flexible Composition**: Support for adding transforms dynamically using the `+` operator
- **Error Propagation**: Comprehensive error reporting with pipeline context

## Transform Categories

### Data Manipulation Transforms

These transforms handle basic dictionary operations:

| Transform | Purpose | Key Features |
|-----------|---------|--------------|
| `RemoveKeys` | Remove specified keys from data dictionary | Configurable key existence validation |
| `SubsetToKeys` | Keep only specified keys | Inverse of RemoveKeys operation |
| `AddData` | Add new data to dictionary | Overwrite protection options |
| `Identity` | Pass-through operation | No-op transform for pipeline structure |

### Conditional Routing

Advanced routing transforms enable dynamic pipeline behavior:

#### RandomRoute
Probabilistic selection between transforms, useful for data augmentation strategies:

```python
RandomRoute(transforms=[Transform1(), Transform2()], probs=[0.7, 0.3])
```

#### ConditionalRoute
Condition-based routing for training/inference mode switching:

```python
ConditionalRoute(
    condition_func=lambda data: data.get("mode", "inference"),
    transform_map={
        "train": TrainingTransform(),
        "inference": Identity()
    }
)
```

> [!TIP]
> RandomRoute automatically tracks RNG state when `track_rng_state=True`, enabling exact reproduction of stochastic pipeline behavior for debugging.

## Specialized Transform Domains

### Atom Array Processing

The atomworks.ml.transforms.atom_array module provides transforms for structural data manipulation:

#### Annotation Management
- `AddGlobalAtomIdAnnotation`: Unique atom identification for tracking
- `AddGlobalTokenIdAnnotation`: Token-level identification for ML models
- `AddProteinTerminiAnnotation`: N- and C-terminus detection and annotation

#### Structural Organization
- `SortLikeRF2AA`: Three-tier sorting (polymers → covalent modifications → free ligands)
- `SortPolyThenNonPoly`: Polymer-first ordering with configurable atomized token handling

### Cropping and Sampling

The crop module implements sophisticated structure cropping strategies:

#### CropContiguousLikeAF3
Contiguous residue selection following AlphaFold 3 methodology:
- Respects chain boundaries
- Maintains biological context
- Configurable crop size and atom limits

#### CropSpatialLikeAF3
Spatial proximity-based cropping:
- Distance-based center selection
- Jitter for stochasticity
- Query-driven cropping around specific regions

### Atomization and Encoding

The atomize and encoding modules handle the critical transformation from biological structures to ML-ready representations:

#### AtomizeByCCDName
Converts residues to individual atoms based on Chemical Component Dictionary:
- Configurable default atomization behavior
- Selective residue targeting
- Validation of atomization consistency

#### EncodeAtomArray
Transforms AtomArray objects to tokenized numerical representations:
- Multiple encoding schemes support
- Coordinate and mask generation
- Annotation preservation

## Pipeline Integration

### AlphaFold 3 Integration

The system provides specialized pipelines for AlphaFold 3 workflows through `build_af3_transform_pipeline()`:

```python
def build_af3_transform_pipeline(
    *,
    is_inference: bool,
    protein_msa_dirs: list[dict],
    rna_msa_dirs: list[dict],
    n_recycles: int = 5,
    crop_size: int = 384,
    # ... extensive configuration options
) -> Transform
```

This pipeline integrates:
- MSA processing and selection
- Template searching and alignment
- Structure cropping and augmentation
- Feature encoding for model input

### Error Handling and Debugging

The transform system includes comprehensive error management:

- **TransformPipelineError**: Custom exception with RNG state capture
- **TransformedDict**: Dictionary wrapper with history tracking
- **LogData**: Debug transform for pipeline inspection
- **PickleToDisk**: Intermediate result saving for analysis

## Best Practices

### Pipeline Design

1. **Dependency Management**: Use `requires_previous_transforms` to ensure proper transform ordering
2. **Validation Strategy**: Enable input validation during development, disable for production performance
3. **History Tracking**: Keep enabled during debugging, disable for memory efficiency
4. **RNG State**: Track in stochastic pipelines, disable in deterministic workflows

### Performance Optimization

- Use `Identity` transforms for conditional pipeline branches
- Leverage `RemoveKeys` to reduce memory footprint
- Implement efficient `check_input` methods for early validation
- Consider `_track_transform_history=False` for long-running pipelines

## Advanced Features

### Custom Transform Development

Create custom transforms by extending the base class:

```python
class CustomTransform(Transform):
    requires_previous_transforms = ["AtomizeByCCDName"]
    
    def check_input(self, data: dict[str, Any]) -> None:
        # Validation logic
        pass
    
    def forward(self, data: dict[str, Any]) -> dict[str, Any]:
        # Transformation logic
        return data
```

### Pipeline Composition Patterns

The system supports multiple composition strategies:
- **Sequential Chaining**: Using `+` operator for linear pipelines
- **Conditional Branching**: Using `ConditionalRoute` for mode-dependent processing
- **Stochastic Selection**: Using `RandomRoute` for data augmentation
- **Nested Composition**: Combining `Compose` instances for modular design

> [!TIP]
> The transform system's dictionary-based approach enables seamless integration with existing ML frameworks while maintaining biological data context throughout the processing pipeline.

## Next Steps

For deeper understanding of transform implementation, explore [Transform System Fundamentals](12-transform-system-fundamentals). To learn about specific encoding schemes, see [Feature Encoding Schemes](14-feature-encoding-schemes). For practical pipeline examples, refer to [Custom Transform Development](16-custom-transform-development).
