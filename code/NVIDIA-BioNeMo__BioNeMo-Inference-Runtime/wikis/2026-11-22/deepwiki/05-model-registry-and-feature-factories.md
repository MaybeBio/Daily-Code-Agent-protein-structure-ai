# Model Registry and Feature Factories

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [bionemo_ir/models/protenix/config.py](bionemo_ir/models/protenix/config.py)
- [bionemo_ir/models/protenix/modeling.py](bionemo_ir/models/protenix/modeling.py)
- [bionemo_ir/pipeline/engine.py](bionemo_ir/pipeline/engine.py)
- [bionemo_ir/pipeline/models/boltz2/feature_factory.py](bionemo_ir/pipeline/models/boltz2/feature_factory.py)
- [bionemo_ir/pipeline/stages/feature_generator_stage.py](bionemo_ir/pipeline/stages/feature_generator_stage.py)
- [bionemo_ir/pipeline/stages/tokenizer_stage.py](bionemo_ir/pipeline/stages/tokenizer_stage.py)
- [bionemo_ir/pipeline/utils/__init__.py](bionemo_ir/pipeline/utils/__init__.py)
- [bionemo_ir/registry.py](bionemo_ir/registry.py)
- [docs/ray.md](docs/ray.md)
- [docs/ref/architecture.md](docs/ref/architecture.md)
- [tests/_torch/test_protenix_contracts.py](tests/_torch/test_protenix_contracts.py)
- [tests/pipeline/feature_generator/test_feature_generator_udf.py](tests/pipeline/feature_generator/test_feature_generator_udf.py)
- [tests/pipeline/test_request_rng.py](tests/pipeline/test_request_rng.py)

</details>



## Purpose and Scope

This page covers the architectural routing mechanism via `ModelRegistry` and `ModelComponentsFactory`, the foundational base classes for feature extraction and transformation (`ContextGeneratorBase`, `FeatureGeneratorBase`, `FeatureCollatorBase`, and `TransformBase`), and the two primary data flow patterns (**Pattern A** and **Pattern B**) used across model pipelines.

For implementation-specific details, see the child pages:
- [OpenFold2/OpenFold3 Feature Pipelines](#2.2.1)
- [Boltz-1/Boltz-2 Feature Pipelines](#2.2.2)

Sources: [bionemo_ir/registry.py:30-118](), [bionemo_ir/pipeline/stages/tokenizer_stage.py:26-83]()

---

## 1. Model Registry and Components Factory

The BioNeMo Inference Runtime decouples model execution and featurization from concrete implementations through `ModelRegistry` and `ModelComponentsFactory` [bionemo_ir/registry.py:30-58](). 

Each supported model family implements `ModelComponentsFactory`, exposing class methods that return the PyTorch model class, tokenizer, feature factory, post-processor, default runtime arguments, and supported model name strings [bionemo_ir/registry.py:30-77](). The `ModelRegistry` maintains a global registry mapping model identifiers to their respective factories, allowing dynamic component resolution at runtime [bionemo_ir/registry.py:79-118]().

Title: Model Registry Routing Architecture
```mermaid
graph TD
    A["ModelRegistry"] -->|"get_factory(model_name)"| B["ModelComponentsFactory"]
    B -->|"get_model_class()"| C["nn.Module"]
    B -->|"get_tokenizer()"| D["TokenizerBase"]
    B -->|"get_feature_factory()"| E["FeatureFactoryBase"]
    B -->|"get_postprocessor()"| F["PostProcessorBase"]
    B -->|"get_default_runtime_args()"| G["dict[str, Any]"]
```
Sources: [bionemo_ir/registry.py:30-118]()

---

## 2. Pipeline Base Classes

Feature generation and tokenization rely on standardized abstract base classes implemented across tokenizer and feature generator stages [bionemo_ir/pipeline/stages/tokenizer_stage.py:26-83](), [bionemo_ir/pipeline/stages/feature_generator_stage.py:29-102]().

| Base Class | Role | Output Type |
| :--- | :--- | :--- |
| `ContextGeneratorBase` | Converts parsed input into initial tensors or row context [bionemo_ir/pipeline/stages/tokenizer_stage.py:63-71]() | `dict[str, torch.Tensor]` or `dict[str, Any]` |
| `TransformBase` | Applies non-ensembled modifications to the tensor dict in-place during tokenization [bionemo_ir/pipeline/stages/tokenizer_stage.py:72-74]() | `dict[str, torch.Tensor]` |
| `FeatureGeneratorBase` | Produces new feature tensors from existing batch and context [bionemo_ir/pipeline/stages/feature_generator_stage.py:81-89]() | `dict[str, torch.Tensor]` (new keys) |
| `FeatureCollatorBase` | Inherits from `FeatureGeneratorBase`; handles ensembled, stochastic, or deterministic feature collation [bionemo_ir/pipeline/stages/feature_generator_stage.py:94-96]() | `dict[str, torch.Tensor]` |

Sources: [bionemo_ir/pipeline/stages/tokenizer_stage.py:26-83](), [bionemo_ir/pipeline/stages/feature_generator_stage.py:29-102]()

---

## 3. Data Flow Patterns: Pattern A vs Pattern B

BioIR supports two distinct data flow architectures depending on whether upstream data handling maintains flat tensors or mixed-type intermediate structures [bionemo_ir/pipeline/stages/feature_generator_stage.py:66-101](), [bionemo_ir/pipeline/models/boltz2/feature_factory.py:15-107]():

- **Pattern A (OpenFold-style)**: The context generator produces a complete, flat tensor dictionary. All downstream tokenizers and feature generators operate exclusively on `dict[str, torch.Tensor]`. Examples: `openfold2/`, `boltz1/` [bionemo_ir/registry.py:134-178]().
- **Pattern B (Boltz2-style)**: The context generator returns a mixed context row (`context["_row"]`) containing non-tensor objects such as physical structures, molecule dictionaries, and per-chain MSAs. Feature generators read from `_row` incrementally to yield tensors [bionemo_ir/pipeline/stages/feature_generator_stage.py:66-74](). Examples: `boltz2/` [bionemo_ir/pipeline/models/boltz2/feature_factory.py:76-107]().

Title: Pattern A vs Pattern B Data Flow Comparison
```mermaid
graph TD
    subgraph "Pattern A (OpenFold-style)"
        A1["InputRequest"] --> A2["ParserStage"]
        A2 --> A3["TokenizerStage: ContextGenerator -> dict[str, torch.Tensor]"]
        A3 --> A4["FeatureGeneratorStage: FeatureCollators & Generators"]
        A4 --> A5["FoldingEngineStage"]
    end
    subgraph "Pattern B (Boltz2-style)"
        B1["InputRequest"] --> B2["ParserStage"]
        B2 --> B3["TokenizerStage: ContextGenerator -> row dict"]
        B3 --> B4["FeatureGeneratorStage: Reads context['_row'] -> new tensors"]
        B4 --> B5["FoldingEngineStage"]
    end
```
Sources: [bionemo_ir/pipeline/stages/tokenizer_stage.py:26-83](), [bionemo_ir/pipeline/stages/feature_generator_stage.py:66-101](), [bionemo_ir/pipeline/models/boltz2/feature_factory.py:15-107]()

---

## 4. Child Page References

For granular details on feature pipelines, transformations, and postprocessing per model family, proceed to:
- [OpenFold2/OpenFold3 Feature Pipelines](#2.2.1)
- [Boltz-1/Boltz-2 Feature Pipelines](#2.2.2)

Sources: [bionemo_ir/registry.py:30-118]()

---