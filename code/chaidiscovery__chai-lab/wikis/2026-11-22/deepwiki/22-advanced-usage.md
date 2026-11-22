# Advanced Usage

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [chai_lab/data/dataset/embeddings/esm.py](chai_lab/data/dataset/embeddings/esm.py)
- [chai_lab/utils/paths.py](chai_lab/utils/paths.py)

</details>



This document covers advanced configuration options and usage patterns for experienced users of `chai-lab`. It focuses on environment customization, performance optimization, and specialized workflows that go beyond basic structure prediction.

For basic inference usage, see [Getting Started](#2). For details on individual feature systems, see [Feature Generation](#5).

## Child Pages
- [Asset Management](#7.1) — Managing model weights, cached data, and download configurations. Documents `CHAI_DOWNLOADS_DIR`, `CHAI_TEMPLATE_CIF_FOLDER`, `paths.py`, and the antipickle-based conformer cache.
- [Custom Restraints](#7.2) — Advanced usage of restraints including file formats and integration examples. Documents contact and pocket restraint file formats, covalent bond specification, and the `predict_with_restraints` example.

## Environment Configuration

The `chai-lab` system provides several environment variables and configuration options for advanced users to customize behavior, particularly around asset management and resource utilization.

### Download Directory Configuration

The system uses a configurable download directory for storing model weights and cached data. By default, assets are stored in the repository's `downloads` directory [chai_lab/utils/paths.py:21](), but this can be customized using the `CHAI_DOWNLOADS_DIR` environment variable [chai_lab/utils/paths.py:22]().

```bash
export CHAI_DOWNLOADS_DIR=/path/to/custom/downloads
```

The download system implements atomic downloads with file locking to prevent corruption during concurrent access, as shown in the `download_if_not_exists` function [chai_lab/utils/paths.py:29-49]().

**Download System Architecture:**

```mermaid
flowchart TD
    EnvVar["CHAI_DOWNLOADS_DIR<br/>Environment Variable"]
    DefaultPath["repo_root/downloads<br/>Default location"]
    DownloadsPath["downloads_path<br/>Final configuration"]
    
    ModelComponents["Model Components<br/>trunk.pt, diffusion.pt, etc."]
    CachedConformers["Cached Conformers<br/>conformers_v1.apkl"]
    ESMWeights["ESM Weights<br/>traced_sdpa_esm2_t36_3B_UR50D_fp16.pt"]
    
    ChaiComponent["chai1_component()<br/>Download function"]
    DownloadIfNotExists["download_if_not_exists()<br/>Atomic download with locking"]
    FileLock["FileLock<br/>Prevents concurrent downloads"]
    
    EnvVar --> DownloadsPath
    DefaultPath --> DownloadsPath
    DownloadsPath --> ChaiComponent
    DownloadsPath --> CachedConformers
    DownloadsPath --> ESMWeights
    
    ChaiComponent --> DownloadIfNotExists
    DownloadIfNotExists --> FileLock
    
    ModelComponents --> ComponentUrl["COMPONENT_URL<br/>https://chaiassets.com/chai1-inference-depencencies/models_v2/{comp_key}"]
```

Sources: [chai_lab/utils/paths.py:19-23](), [chai_lab/utils/paths.py:29-49](), [chai_lab/utils/paths.py:67-82](), [chai_lab/data/dataset/embeddings/esm.py:21-34]()

## Asset Management Overview

The `chai-lab` system implements a sophisticated asset management system for handling model weights, cached conformers, and ESM language model embeddings. This system provides automatic downloading, caching, and version management.

### Downloadable Asset System

The `Downloadable` class provides a lazy-loading mechanism for remote assets [chai_lab/utils/paths.py:51-60](). Assets are downloaded only when first accessed, with automatic caching and integrity checking.

For details, see [Asset Management](#7.1).

**Asset Management Architecture:**

```mermaid
flowchart TD
    DownloadableClass["Downloadable<br/>url, path"]
    GetPath["get_path()<br/>Lazy download trigger"]
    
    ModelComponents["Model Components<br/>chai1_component()"]
    CachedConformers["cached_conformers<br/>Downloadable instance"]
    ESMModel["esm_model()<br/>Context manager"]
    
    ChaiAssets["https://chaiassets.com<br/>Remote asset repository"]
    LocalCache["Local Downloads Cache<br/>CHAI_DOWNLOADS_DIR"]
    
    FileLockMechanism["FileLock<br/>Concurrent access protection"]
    AtomicDownload["Atomic Download<br/>Temporary file + rename"]
    
    DownloadableClass --> GetPath
    GetPath --> DownloadIfNotExists["download_if_not_exists()"]
    
    ModelComponents --> ChaiAssets
    CachedConformers --> ChaiAssets
    ESMModel --> ChaiAssets
    
    DownloadIfNotExists --> FileLockMechanism
    DownloadIfNotExists --> AtomicDownload
    AtomicDownload --> LocalCache
    
    LocalCache --> ModelWeights["Model Weights<br/>trunk.pt, diffusion.pt"]
    LocalCache --> ConformerData["Conformer Data<br/>conformers_v1.apkl"]
    LocalCache --> ESMData["ESM Weights<br/>esm/traced_sdpa_esm2_..."]
```

Sources: [chai_lab/utils/paths.py:51-65](), [chai_lab/utils/paths.py:72-82](), [chai_lab/data/dataset/embeddings/esm.py:21-35]()

## Advanced Restraints and Customization

Chai-1 allows users to guide the folding process using experimental or hypothesized restraints. This is particularly useful for complex assemblies or when specific biochemical knowledge is available.

### Restraint Types
The system supports several advanced restraint configurations:
*   **Contact Restraints**: Distance constraints between specific atom pairs.
*   **Pocket Restraints**: Guidance for ligand binding site placement.
*   **Covalent Bonds**: Explicit specification of chemical bonds, including branched ligands or non-standard linkages.

For detailed file formats and integration examples, see [Custom Restraints](#7.2).

**Restraint Integration Flow:**

```mermaid
flowchart TD
    InputFASTA["Input FASTA"]
    RestraintFile["Restraint File<br/>.csv / .json"]
    
    RunInference["run_inference()"]
    RunFoldingContext["run_folding_on_context()"]
    
    FeatureContext["AllAtomFeatureContext"]
    RestraintCtx["RestraintContext"]
    
    InputFASTA --> RunInference
    RestraintFile --> RunInference
    
    RunInference --> FeatureContext
    RestraintFile --> RestraintCtx
    RestraintCtx --> FeatureContext
    
    FeatureContext --> Model["Chai-1 Model Inference"]
```

Sources: [README.md:91-94](), [README.md:113-118]()

## Performance and Resource Management

### ESM Embedding Management
The ESM language model is used to generate protein sequence embeddings. The system manages the 3B parameter model by transiently loading it onto the GPU and moving it back to the CPU when not in use to save VRAM [chai_lab/data/dataset/embeddings/esm.py:27-52]().

### Concurrent Access
The asset download system uses `FileLock` to safely handle concurrent access, allowing multiple processes to share the same download directory without corruption [chai_lab/utils/paths.py:33-48]().

Sources: [chai_lab/data/dataset/embeddings/esm.py:27-52](), [chai_lab/utils/paths.py:33-48]()

---