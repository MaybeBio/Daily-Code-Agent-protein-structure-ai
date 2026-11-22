# ESM Embeddings

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [chai_lab/data/dataset/embeddings/embedding_context.py](chai_lab/data/dataset/embeddings/embedding_context.py)
- [chai_lab/data/dataset/embeddings/esm.py](chai_lab/data/dataset/embeddings/esm.py)
- [chai_lab/data/features/generators/esm_generator.py](chai_lab/data/features/generators/esm_generator.py)
- [chai_lab/utils/paths.py](chai_lab/utils/paths.py)

</details>



## Purpose and Scope

This document details the ESM (Evolutionary Scale Modeling) embeddings component in the Chai Lab system. ESM embeddings provide rich, contextual representations of protein sequences based on evolutionary information. These embeddings serve as a critical input feature for the structure prediction pipeline, particularly for protein sequences.

For information about other feature generation components like Multiple Sequence Alignments, see [Multiple Sequence Alignments](#5.1), or for template-based features, see [Structural Templates](#5.2).

## Overview

ESM embeddings in Chai Lab are generated using a pre-trained ESM2 model, specifically the ESM2-3B model with 36 transformer layers. These embeddings capture evolutionary information from protein sequences that helps the diffusion model make accurate structural predictions.

```mermaid
graph TD
    subgraph "ESM Embedding Generation System"
        ProteinSeq["Protein Sequences"] --> Tokenizer["DumbTokenizer"]
        Tokenizer --> ESMModel["ESM2 Model<br>3B parameters"]
        ESMModel --> Embeddings["Per-residue Embeddings"]
        Embeddings --> EmbeddingContext["EmbeddingContext"]
    end
    
    subgraph "Feature Context Integration"
        EmbeddingContext --> AllAtomFeatureContext["AllAtomFeatureContext"]
        MSAContext["MSAContext"] --> AllAtomFeatureContext
        TemplateContext["TemplateContext"] --> AllAtomFeatureContext
        RestraintContext["RestraintContext"] --> AllAtomFeatureContext
    end
    
    AllAtomFeatureContext --> ModelInference["Structure Prediction Model"]
```

Sources: [chai_lab/data/dataset/embeddings/esm.py:140-180]()

## ESM Model Management

The ESM model is efficiently managed through a global container `_esm_model` and context manager `esm_model()` to minimize memory usage and optimize performance.

### Model Loading and Caching Strategy

The system uses a persistent in-process container `_esm_model` (list) to cache the loaded model and avoid repeated loading: [chai_lab/data/dataset/embeddings/esm.py:16-16]().

```mermaid
graph TD
    subgraph "Model Management Components"
        global_container["_esm_model: list<br/>Global model container"] --> context_manager["esm_model(device)<br/>Context manager"]
        url_constant["ESM_URL<br/>Model download URL"] --> download_func["download_if_not_exists()"]
        cache_folder["esm_cache_folder<br/>downloads_path/esm"] --> local_path["local_esm_path<br/>traced_sdpa_esm2_t36_3B_UR50D_fp16.pt"]
        download_func --> local_path
        local_path --> context_manager
    end
    
    subgraph "Process Management"
        fork_handler["os.register_at_fork()<br/>after_in_child callback"] --> clear_cache["_esm_model.clear()"]
    end
    
    context_manager --> model_inference["Model Inference"]
```

### Device Management Process

The `esm_model` context manager [chai_lab/data/dataset/embeddings/esm.py:28-52]() handles the lifecycle of the model on the GPU/CPU.

```mermaid
sequenceDiagram
    participant Client as "Client Code"
    participant ContextMgr as "esm_model(device)"
    participant GlobalContainer as "_esm_model"
    participant Download as "download_if_not_exists"
    participant TorchJIT as "torch.jit.load"
    
    Client->>ContextMgr: with esm_model(device="cuda:0")
    ContextMgr->>Download: Check/download model
    Download->>ContextMgr: Model file ready
    
    alt len(_esm_model) == 0
        ContextMgr->>TorchJIT: Load model from file
        alt device != "cuda:0"
            TorchJIT->>ContextMgr: Load on CPU first
            ContextMgr->>ContextMgr: Move to target device
        else
            TorchJIT->>ContextMgr: Load directly on GPU
        end
        ContextMgr->>GlobalContainer: Append model to _esm_model
    else
        ContextMgr->>GlobalContainer: Get cached model
    end
    
    ContextMgr->>ContextMgr: model.to(device)
    ContextMgr->>ContextMgr: model.eval()
    ContextMgr->>Client: yield model
    Client->>Client: Use model for inference
    Client->>ContextMgr: Exit context
    ContextMgr->>ContextMgr: model.to("cpu")
```

The system also registers a fork handler using `os.register_at_fork(after_in_child=lambda: _esm_model.clear())` to prevent model sharing issues in multi-process environments [chai_lab/data/dataset/embeddings/esm.py:18-18]().

Sources: [chai_lab/data/dataset/embeddings/esm.py:16-52](), [chai_lab/utils/paths.py:29-48]()

## Tokenization Process

Before a protein sequence can be processed by the ESM model, it needs to be tokenized. Chai Lab implements a `DumbTokenizer` that converts amino acid sequences to token IDs [chai_lab/data/dataset/embeddings/esm.py:91-109]().

### Token Mapping and DumbTokenizer Implementation

The system defines a comprehensive `token_map` dictionary that maps amino acids and special tokens to integer IDs [chai_lab/data/dataset/embeddings/esm.py:54-88]().

```mermaid
graph TD
    subgraph "Token Mapping Components"
        token_map["token_map<br/>Dict[str, int]"] --> special_tokens["Special Tokens<br/>&lt;cls&gt;:0, &lt;pad&gt;:1, &lt;eos&gt;:2, &lt;unk&gt;:3<br/>&lt;mask&gt;:32"]
        token_map --> amino_acids["Amino Acids<br/>L:4, A:5, G:6, V:7, S:8, E:9<br/>R:10, T:11, I:12, D:13, P:14<br/>K:15, Q:16, N:17, F:18, Y:19<br/>M:20, H:21, W:22, C:23"]
        token_map --> extended_aa["Extended AA<br/>X:24, B:25, U:26, Z:27, O:28"]
        token_map --> gap_tokens["Gap Tokens<br/>.:29, -:30"]
    end
    
    subgraph "DumbTokenizer Class"
        tokenizer_init["DumbTokenizer.__init__<br/>(token_map)"] --> tokenize_method["DumbTokenizer.tokenize<br/>(text: str) -> list[int]"]
        tokenize_method --> greedy_match["Greedy Token Matching<br/>text.startswith(token, i)"]
    end
    
    subgraph "ESM Processing Pipeline"
        raw_seq["Raw Protein Sequence<br/>'MKTLVLGAVILGSTLLAG...'"] --> add_special["Add BOS/EOS<br/>f'&lt;cls&gt;{seq}&lt;eos&gt;'"]
        add_special --> tokenize_call["esm_tokenizer.tokenize()"]
        tokenize_call --> tensor_convert["torch.asarray()<br/>token_ids.to(device)"]
        tensor_convert --> model_input["ESM Model Input<br/>tokens=[0, 20, 15, 11, 4, 7, 4, 6...]"]
    end
```

Sources: [chai_lab/data/dataset/embeddings/esm.py:54-109]()

## Embedding Generation Process

The main function for generating embeddings is `get_esm_embedding_context`, which processes a list of `Chain` objects to generate embeddings [chai_lab/data/dataset/embeddings/esm.py:141-180]().

### Core Function Flow

```mermaid
flowchart TD
    subgraph "get_esm_embedding_context Function"
        input_chains["Input: list[Chain]<br/>chains parameter"] --> extract_seqs["Extract Unique Protein Sequences<br/>chain.entity_data.entity_type == EntityType.PROTEIN"]
        extract_seqs --> call_helper["_get_esm_contexts_for_sequences<br/>(prot_sequences: set[str], device)"]
        
        subgraph "_get_esm_contexts_for_sequences Implementation"
            empty_check{"len(prot_sequences) == 0"} -->|Yes| return_empty["return {}"]
            empty_check -->|No| init_dict["seq2embedding_context = {}"]
            init_dict --> torch_no_grad["torch.no_grad()"]
            torch_no_grad --> esm_context["with esm_model(device=device)"]
            esm_context --> seq_loop["for seq in prot_sequences"]
            seq_loop --> tokenize_seq["esm_tokenizer.tokenize<br/>(f'&lt;cls&gt;{seq}&lt;eos&gt;')"]
            tokenize_seq --> model_call["model(tokens=token_ids)"]
            model_call --> extract_hidden["last_hidden_state[0, 1:-1]<br/>Remove BOS/EOS, move to CPU"]
            extract_hidden --> create_emb_ctx["EmbeddingContext<br/>(esm_embeddings=esm_embeddings)"]
            create_emb_ctx --> store_result["seq2embedding_context[seq] = context"]
        end
        
        call_helper --> process_chains["Process Each Chain<br/>for chain in chains"]
        
        subgraph "Chain Processing Logic"
            entity_check{"chain.entity_data.entity_type<br/>== EntityType.PROTEIN"} 
            entity_check -->|True| get_protein_emb["chain_embs.append<br/>(protein_seq2emb_context[sequence])"]
            entity_check -->|False| get_zero_emb["chain_embs.append<br/>(EmbeddingContext.empty(n_tokens))"]
        end
        
        process_chains --> explode_embs["Map to Structure Tokens<br/>embedding.esm_embeddings[chain.structure_context.token_residue_index, :]"]
        explode_embs --> merge_embs["torch.cat(cropped_embs, dim=0)<br/>Merge along tokens dimension"]
        merge_embs --> final_output["Return EmbeddingContext<br/>(esm_embeddings=merged_embs)"]
    end
```

### Entity Type Handling

The system handles different molecular entity types by checking `chain.entity_data.entity_type` [chai_lab/data/dataset/embeddings/esm.py:155-161]():

| Entity Type | Embedding Strategy | Implementation |
|-------------|-------------------|----------------|
| `EntityType.PROTEIN` | ESM model embeddings | `protein_seq2emb_context[chain.entity_data.sequence]` |
| Non-protein entities | Zero embeddings | `EmbeddingContext.empty(n_tokens=chain.structure_context.num_tokens)` |

Sources: [chai_lab/data/dataset/embeddings/esm.py:112-180](), [chai_lab/data/dataset/embeddings/embedding_context.py:48-52]()

## Key Data Structures

The primary data structure is the `EmbeddingContext`, which contains the ESM embeddings for all tokens in a structure.

### EmbeddingContext
Defined in [chai_lab/data/dataset/embeddings/embedding_context.py:15-52](), this dataclass stores the `esm_embeddings` tensor with shape `[num_tokens, d_emb]`. It provides utility methods like `pad` [chai_lab/data/dataset/embeddings/embedding_context.py:28-42]() and `empty` [chai_lab/data/dataset/embeddings/embedding_context.py:48-52]().

### ESMEmbeddings Feature Generator
The `ESMEmbeddings` class [chai_lab/data/features/generators/esm_generator.py:12-35]() is a `FeatureGenerator` that extracts embeddings from a batch and prepares them for the model trunk.

```mermaid
classDiagram
    class EmbeddingContext {
        +Tensor esm_embeddings
        +num_tokens int
        +pad(max_tokens) EmbeddingContext
        +empty(n_tokens, d_emb) static
    }
    
    class ESMEmbeddings {
        +FeatureType ty
        +get_input_kwargs_from_batch(batch)
        +_generate(esm_embeddings)
    }
    
    ESMEmbeddings ..> EmbeddingContext : processes
```

Sources: [chai_lab/data/dataset/embeddings/embedding_context.py:15-52](), [chai_lab/data/features/generators/esm_generator.py:12-35]()

## Implementation Details

### Model Loading and Device Strategy
The system implements optimized loading based on target device [chai_lab/data/dataset/embeddings/esm.py:38-43]():

```mermaid
graph TD
    subgraph "Model Loading Strategy"
        check_device{"device != torch.device('cuda:0')"}
        check_device -->|True| load_cpu["torch.jit.load(local_esm_path,<br/>map_location='cpu')<br/>.to(device)"]
        check_device -->|False| load_gpu["torch.jit.load(local_esm_path)<br/>.to(device)"]
        load_cpu --> append_model["_esm_model.append(model)"]
        load_gpu --> append_model
    end
```

The model is moved back to CPU using `model.to("cpu")` after the context manager yields to prevent GPU memory bloat [chai_lab/data/dataset/embeddings/esm.py:51-51]().

### Embedding Dimensionality
By default, the `EmbeddingContext.empty` method uses a dimension of `2560` [chai_lab/data/dataset/embeddings/embedding_context.py:48-48](), which corresponds to the ESM2-3B output dimension.

Sources: [chai_lab/data/dataset/embeddings/esm.py:28-52](), [chai_lab/data/dataset/embeddings/embedding_context.py:48-52]()

## Technical Specifications

The ESM model used in Chai Lab is:

| Specification | Value |
|---------------|--------|
| Model | ESM2-t36-3B |
| Size | 3 billion parameters |
| Architecture | 36-layer transformer |
| Format | Traced model (PyTorch JIT) |
| Precision | FP16 (half precision) |
| Download URL | `ESM_URL` [chai_lab/data/dataset/embeddings/esm.py:21]() |
| Local Path | `downloads_path / "esm/traced_sdpa_esm2_t36_3B_UR50D_fp16.pt"` |

### File Path Management

```mermaid
graph TD
    subgraph "ESM Model Path Management"
        esm_url["ESM_URL<br/>'https://chaiassets.com/chai1-inference-depencencies/esm2/traced_sdpa_esm2_t36_3B_UR50D_fp16.pt'"]
        cache_folder["esm_cache_folder<br/>downloads_path.joinpath('esm')"]
        local_path["local_esm_path<br/>downloads_path.joinpath('esm/traced_sdpa_esm2_t36_3B_UR50D_fp16.pt')"]
        
        esm_url --> download_func["download_if_not_exists()<br/>Download if missing"]
        cache_folder --> local_path
        download_func --> local_path
    end
```

Sources: [chai_lab/data/dataset/embeddings/esm.py:21-34](), [chai_lab/utils/paths.py:19-22]()

---