# Embedded Cubin Packs and the Kernel Registry

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [bionemo_ir/_torch/modules/openfold3/utils/confidence.py](bionemo_ir/_torch/modules/openfold3/utils/confidence.py)
- [cpp/cmake/materialize_cubin_payloads.py](cpp/cmake/materialize_cubin_payloads.py)
- [cpp/kernels/cutedsl_adaln_layernorm_sigmoid/cubins/index.json](cpp/kernels/cutedsl_adaln_layernorm_sigmoid/cubins/index.json)
- [cpp/kernels/cutedsl_attn_epilogue/cubins/index.json](cpp/kernels/cutedsl_attn_epilogue/cubins/index.json)
- [cpp/kernels/cutedsl_dual_gemm_x0_x1/cubins/index.json](cpp/kernels/cutedsl_dual_gemm_x0_x1/cubins/index.json)
- [cpp/kernels/cutedsl_dual_gemm_x_x/cubins/index.json](cpp/kernels/cutedsl_dual_gemm_x_x/cubins/index.json)
- [cpp/kernels/cutedsl_gated_sigmoid/cubins/index.json](cpp/kernels/cutedsl_gated_sigmoid/cubins/index.json)
- [cpp/kernels/cutedsl_outer_product_mean/cubins/index.json](cpp/kernels/cutedsl_outer_product_mean/cubins/index.json)
- [cpp/kernels/cutedsl_pair_weighted_averaging/cubins/index.json](cpp/kernels/cutedsl_pair_weighted_averaging/cubins/index.json)
- [cpp/kernels/cutedsl_pairwise_attention/cubins/index.json](cpp/kernels/cutedsl_pairwise_attention/cubins/index.json)
- [cpp/kernels/cutedsl_transition_mlp/cubins/index.json](cpp/kernels/cutedsl_transition_mlp/cubins/index.json)
- [cpp/kernels/cutedsl_triangle_attention/cubins/index.json](cpp/kernels/cutedsl_triangle_attention/cubins/index.json)
- [cpp/kernels/cutedsl_trimul_kf_k1/cubins/index.json](cpp/kernels/cutedsl_trimul_kf_k1/cubins/index.json)
- [cpp/kernels/cutedsl_trimul_kf_k2/cubins/index.json](cpp/kernels/cutedsl_trimul_kf_k2/cubins/index.json)
- [cpp/kernels/cutedsl_trimul_kf_k3/cubins/index.json](cpp/kernels/cutedsl_trimul_kf_k3/cubins/index.json)
- [tests/_torch/__init__.py](tests/_torch/__init__.py)
- [tests/_torch/test_attn_epilogue.py](tests/_torch/test_attn_epilogue.py)
- [tests/_torch/test_pair_averaging.py](tests/_torch/test_pair_averaging.py)
- [tests/_torch/test_token_padding.py](tests/_torch/test_token_padding.py)
- [tests/cubin/test_materialize_cubin_payloads.py](tests/cubin/test_materialize_cubin_payloads.py)
- [tests/ops/test_cutedsl_oob.py](tests/ops/test_cutedsl_oob.py)
- [tests/ops/test_dual_gemm_cute.py](tests/ops/test_dual_gemm_cute.py)
- [tests/ops/test_dual_gemm_x0_x1_cutedsl.py](tests/ops/test_dual_gemm_x0_x1_cutedsl.py)
- [tests/pipeline/test_pipelined_processor.py](tests/pipeline/test_pipelined_processor.py)

</details>



## Purpose and Scope

The BioNeMo Inference Runtime (BioIR) relies on high-performance custom CUDA kernels written using CUTLASS DSL (CuTeDSL). Because compiling these complex templates at runtime introduces unacceptable latency, BioIR uses precompiled CUDA binary (cubin) archives packed into structured directories and indexed via JSON manifests (`index.json`). 

This page details the architecture of embedded cubin packs under the `bioir-cubin-pack-v2` format, the layout of the `index.json` registry schema including architecture packs and shards, the build-time materialization process (`materialize_cubin_payloads.py`), and how C++ launchers and runtime bindings preload and resolve these binaries for different NVIDIA Streaming Multiprocessor (SM) architectures (`sm_80`, `sm_86`, `sm_89`, `sm_90a`, `sm_100a`, `sm_103a`, `sm_120a`).

---

## 1. Cubin Pack Anatomy and Index Schema (`index.json`)

Each custom kernel family (e.g., `cutedsl_dual_gemm_x0_x1`, `cutedsl_triangle_attention`, `cutedsl_pairwise_attention`, `cutedsl_adaln_layernorm_sigmoid`) houses a `cubins/` directory containing an `index.json` manifest that indexes precompiled binaries and shards.

The `index.json` file uses the format specifier `"bioir-cubin-pack-v2"` and is structured around a top-level compile fingerprint, kernel family identifier, registry version, architecture pack checksums, shard dictionaries, and toolchain metadata.

```json
{
  "compile_fingerprint": "6c10c8c96b3559da0dd3a659ebe4302a47fa5be84699a94cece11c7b6830a150",
  "family": "dual_gemm_x0_x1",
  "format": "bioir-cubin-pack-v2",
  "packs": {
    "sm_100a": {
      "sha256": "6facf32e90dded97df8bd03045040adca050196cf05596c23e8ea2d86787674c",
      "size": 83100
    },
    "sm_80": {
      "sha256": "a914427014f46547b29af31c26d05fa3240d7a4df335dc758e83a654849a920d",
      "size": 113588
    }
  },
  "registry_version": 2,
  "shards": {
    "0": {
      "sha256": "76e8ca5134dfd3c622db2398aa7edbdb3e3b58aaa18bdc0f3d458079845c4f89",
      "size": 76629
    }
  },
  "toolchain": {
    "compile_environment": "sha256:222d8b18e671be5c3ef91cb41727a2572a0b23f59ded6c39f373a96946f6f2ba",
    "nvidia-cutlass-dsl": "4.5.2"
  }
}
```
*Sources: `cpp/kernels/cutedsl_dual_gemm_x0_x1/cubins/index.json:1-102`*

### Packs and Shards

- **Packs (`packs`)**: Catalogs hardware architecture targets (`sm_80`, `sm_86`, `sm_89`, `sm_90a`, `sm_100a`, `sm_103a`, `sm_120a`), recording the expected SHA-256 checksum and size in bytes for each architecture payload.
- **Shards (`shards`)**: Maps individual binary shards (hexadecimal indices `"0"` through `"f"`) to their respective SHA-256 hashes and sizes, enabling granular parallel extraction and lazy loading.

```mermaid
graph TD
    sub531_NaturalLanguageSpace ["Natural Language Space: Kernel Registry Manifest"] --> sub531_CodeEntitySpace["Code Entity Space: index.json & Shards"]
    
    sub531_CodeEntitySpace --> IndexJSON["cpp/kernels/*/cubins/index.json"]
    IndexJSON --> Format["bioir-cubin-pack-v2"]
    Format --> Packs["Packs Dictionary (sm_80, sm_90a, sm_100a, etc.)"]
    Format --> Shards["Shards Dictionary (0 through f)"]
    
    Packs --> PackChecksum["Architecture SHA-256 & Size Validation"]
    Shards --> ShardChecksum["Shard Payload Hash & Size Verification"]
```
*Diagram 1: Mapping from manifest concepts to file entities in version 2 cubin packs.*

Sources: 
- `cpp/kernels/cutedsl_dual_gemm_x0_x1/cubins/index.json:1-102`
- `cpp/kernels/cutedsl_triangle_attention/cubins/index.json:1-102`
- `cpp/kernels/cutedsl_adaln_layernorm_sigmoid/cubins/index.json:1-110`

---

## 2. Build-Time Materialization Pipeline

Precompiled cubin payloads and shards are verified and assembled into the final build artifact tree during the CMake build and Python package staging steps.

This is coordinated by `cpp/cmake/materialize_cubin_payloads.py` and validated via `tests/cubin/test_materialize_cubin_payloads.py`.

```mermaid
graph TD
    sub531_NL_Build ["Natural Language Space: Build-Time Materialization"] --> sub531_CE_Build["Code Entity Space: CMake & Materializer"]

    sub531_CE_Build --> CMake["CMakeLists.txt / Build System"]
    CMake --> Script["cpp/cmake/materialize_cubin_payloads.py"]
    Script --> ReadIndex["Read index.json Manifest"]
    ReadIndex --> VerifySha["Validate SHA-256 Checksums of Packs and Shards"]
    VerifySha --> Extract["Materialize Payload into Build Directory Tree"]
    Extract --> RuntimeLoad["Preload Binaries into C++ Launcher Registry"]
```
*Diagram 2: Build-time materialization pipeline flow.*

Sources:
- `cpp/cmake/materialize_cubin_payloads.py`
- `tests/cubin/test_materialize_cubin_payloads.py`

### Materialization Steps

1. **Manifest Parsing**: The utility loads `index.json` to inspect the declared `registry_version` (v2) and enumerate all target architecture packs and shards.
2. **Integrity Verification**: Computes SHA-256 hashes for the unpacked or archived shards/packs and verifies them against the entries in `index.json`.
3. **Payload Materialization**: Prepares the binary layout in the build tree so that C++ CuTeDSL launchers can resolve individual kernel symbols at runtime.

Sources:
- `cpp/cmake/materialize_cubin_payloads.py`
- `cpp/kernels/cutedsl_dual_gemm_x0_x1/cubins/index.json:1-102`

---

## 3. Runtime Preloading and Registry Resolution

Once materialized, the C++ CuTeDSL launchers (`cpp/kernels/`) consult the registry metadata at startup or upon first kernel execution. 

- **Target Architecture Dispatch**: Depending on the active device SM capability (`sm_80`, `sm_86`, `sm_89`, `sm_90a`, `sm_100a`, `sm_103a`, `sm_120a`), the appropriate launch bindings locate and load the corresponding compiled binary images.
- **Validation and Caching**: Compile fingerprints ensure version parity between the loaded binaries and the active CUTLASS DSL toolchain environment (`nvidia-cutlass-dsl`).

Sources:
- `cpp/kernels/cutedsl_dual_gemm_x0_x1/cubins/index.json:1-102`
- `cpp/kernels/cutedsl_triangle_attention/cubins/index.json:1-102`
- `cpp/kernels/cutedsl_adaln_layernorm_sigmoid/cubins/index.json:1-110`

---