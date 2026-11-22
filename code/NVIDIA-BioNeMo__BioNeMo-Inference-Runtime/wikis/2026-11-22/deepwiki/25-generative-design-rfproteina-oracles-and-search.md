# Generative Design: RFProteina, Oracles, and Search

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [bionemo_ir/_torch/layers/random_augmentation.py](bionemo_ir/_torch/layers/random_augmentation.py)
- [bionemo_ir/_torch/sampling/edm.py](bionemo_ir/_torch/sampling/edm.py)
- [bionemo_ir/_torch/sampling/frame_reuse.py](bionemo_ir/_torch/sampling/frame_reuse.py)
- [bionemo_ir/models/rfproteina/__init__.py](bionemo_ir/models/rfproteina/__init__.py)
- [bionemo_ir/models/rfproteina/convert.py](bionemo_ir/models/rfproteina/convert.py)
- [bionemo_ir/models/rfproteina/modeling.py](bionemo_ir/models/rfproteina/modeling.py)
- [docs/ref/oracles.md](docs/ref/oracles.md)
- [docs/ref/sampling.md](docs/ref/sampling.md)
- [scripts/fetch_weights.sh](scripts/fetch_weights.sh)
- [tests/_torch/test_frame_reuse.py](tests/_torch/test_frame_reuse.py)
- [tests/_torch/test_rfd4_beam_search.py](tests/_torch/test_rfd4_beam_search.py)
- [tests/_torch/test_rfd4_modules.py](tests/_torch/test_rfd4_modules.py)

</details>



This page provides a high-level overview of the generative (non-folding) capabilities within the BioNeMo Inference Runtime (BioIR). This includes the RFProteina product-space flow-matching design model, pluggable structure oracle scoring providers, and metric-weighted beam search over rollout trajectories. 

For deep technical details, weight conversion internals, and advanced sampling configurations, refer to the child pages:
- [RFProteina Model and Product-Space Flow Matching](#6.1)
- [Oracles and Beam Search](#6.2)

---

## 6.1. RFProteina Model and Product-Space Flow Matching

RFProteina is a generative flow-matching model designed for protein backbones, local latents, and multimodal sequence-structure co-design. The model integrates structural representation builders (`RFProteinaRepresentationBuilder`), unified encoders, and velocity prediction networks (`RFProteina`) to perform unconditional design, partial redesign, sequence redesign, and inverse folding [bionemo_ir/models/rfproteina/modeling.py:32-77]().

Runtime workflows support flexible generation tasks through entrypoints such as `sample`, `sample_partial`, `redesign`, and `inverse_fold` [tests/_torch/test_rfd4_modules.py:51-83](). Checkpoint loading routines automatically infer autoencoder and trunk configurations from stored weight shapes, while weight conversion utilities (`convert.py`) handle OSS-checkpoint mapping and LoRA weight merging [bionemo_ir/models/rfproteina/convert.py:15-42]().

```mermaid
graph TD
    subcode ["Code Entity Space: bionemo_ir.models.rfproteina"]
        RF[RFProteina] --> RB[RFProteinaRepresentationBuilder]
        RB --> LLT[LocalLatentsTransformer]
        LLT --> VEL[velocity]
        MODEL[modeling.py] --> CONV[convert.py]
    end

    subnl ["Natural Language Space"]
        NL1["Generative Flow Matching"] --> RF
        NL2["Representation Builder"] --> RB
        NL3["Velocity Network"] --> VEL
        NL4["Checkpoint Conversion & LoRA Merging"] --> CONV
    end
```

Sources:
- `bionemo_ir/models/rfproteina/modeling.py:32-77`
- `bionemo_ir/models/rfproteina/convert.py:15-42`
- `tests/_torch/test_rfd4_modules.py:51-83`

For details, see [RFProteina Model and Product-Space Flow Matching](#6.1).

---

## 6.2. Oracles and Beam Search

BioIR provides a dependency-light abstraction for evaluating generated structures via custom structure oracles (`bionemo_ir/oracles`) [docs/ref/oracles.md:7-18](). Oracle providers decouple reward calculation from sampling trajectories, allowing the same scoring mechanism to serve beam search, best-of-N selection, and benchmarking.

Beam search (`_torch/search` and `run_rfproteina_beam_search`) coordinates metric-weighted rollouts across checkpoint branching steps [bionemo_ir/models/rfproteina/modeling.py:77-80](). Residue and atom resolvers map model-specific integer vocabularies into canonical schemas (`bionemo_ir.data.schemas`), ensuring reproducible candidate scoring and robust search heuristics [docs/ref/oracles.md:22-30]().

```mermaid
graph TD
    subcode ["Code Entity Space: bionemo_ir.oracles & _torch/search"]
        PROV[OracleProvider / CallableOracleProvider] --> ADAPT[RFProteinaOracleRequestAdapter]
        ADAPT --> RES[ResidueTypeResolver / AtomTypeResolver]
        SEARCH[run_rfproteina_beam_search] --> COMP[CompositeMetricEvaluator]
        SEARCH --> REWARD[RFProteinaSearchRewardConfig]
    end

    subnl ["Natural Language Space"]
        NL1["Pluggable Structure Oracle"] --> PROV
        NL2["Request & Adapter Translation"] --> ADAPT
        NL3["Canonical Vocabulary Resolvers"] --> RES
        NL4["Metric-Weighted Beam Search"] --> SEARCH
    end
```

Sources:
- `docs/ref/oracles.md:7-30`
- `bionemo_ir/models/rfproteina/modeling.py:77-80`
- `tests/_torch/test_rfd4_beam_search.py:23-60`

For details, see [Oracles and Beam Search](#6.2).

---