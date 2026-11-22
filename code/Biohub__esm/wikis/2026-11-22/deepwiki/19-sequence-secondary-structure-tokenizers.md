# Sequence & Secondary Structure Tokenizers

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [esm/tokenization/residue_tokenizer.py](esm/tokenization/residue_tokenizer.py)
- [esm/tokenization/sasa_tokenizer.py](esm/tokenization/sasa_tokenizer.py)
- [esm/tokenization/sequence_tokenizer.py](esm/tokenization/sequence_tokenizer.py)
- [esm/tokenization/ss_tokenizer.py](esm/tokenization/ss_tokenizer.py)
- [esm/tokenization/structure_tokenizer.py](esm/tokenization/structure_tokenizer.py)

</details>



This page documents the tokenization system for sequence and structural tracks in ESM. The system is built around a common protocol, `EsmTokenizerBase`, which ensures consistency across different data modalities including amino acid sequences, secondary structure classifications, and discretized surface accessibility values.

## Tokenization Architecture

The ESM tokenization system uses a multimodal approach where different tracks (sequence, structure, SASA, etc.) are tokenized independently before being processed by the transformer.

### EsmTokenizerBase Protocol
All tokenizers in the ESM ecosystem implement the `EsmTokenizerBase` protocol. This ensures that every tokenizer provides a consistent interface for special tokens and basic operations like encoding and decoding.

**Interface Overview:**
*   **Special Tokens**: Every tokenizer must provide `mask`, `bos`, `eos`, `pad`, and `chain_break` tokens and their corresponding integer IDs [esm/tokenization/tokenizer_base.py:5-15]().
*   **Methods**: Implementations must provide `encode()` and `decode()` methods [esm/tokenization/tokenizer_base.py:17-19]().
*   **Properties**: `all_token_ids` and `special_token_ids` are required for sampling and masking logic [esm/tokenization/tokenizer_base.py:21-25]().

### Sequence & Structure Tokenization Flow
The following diagram illustrates how raw protein data is transformed into tokens by the various tokenizer classes.

**Data to Token Entity Mapping**
```mermaid
graph TD
    subgraph "Natural Language & Biological Space"
        AA_SEQ["Amino Acid Sequence 'MKT...'"]
        SS_STR["SS8 String 'GHH...'"]
        SASA_VALS["SASA Floats [12.5, 0.0, ...]"]
    end

    subgraph "Code Entity Space"
        EST["EsmSequenceTokenizer"]
        SST["SecondaryStructureTokenizer"]
        SDT["SASADiscretizingTokenizer"]
        
        SEQ_TOK["sequence_tokens (Tensor)"]
        SS_TOK["secondary_structure_tokens (Tensor)"]
        SASA_TOK["sasa_tokens (Tensor)"]
    end

    AA_SEQ -->|encode| EST
    SS_STR -->|encode| SST
    SASA_VALS -->|encode| SDT

    EST --> SEQ_TOK
    SST --> SS_TOK
    SDT --> SASA_TOK

    style EST stroke-dasharray: 5 5
    style SST stroke-dasharray: 5 5
    style SDT stroke-dasharray: 5 5
```
Sources: [esm/tokenization/sequence_tokenizer.py:10-15](), [esm/tokenization/ss_tokenizer.py:10-13](), [esm/tokenization/sasa_tokenizer.py:9-12]()

---

## EsmSequenceTokenizer

The `EsmSequenceTokenizer` is the primary tokenizer for amino acid sequences. It inherits from `PreTrainedTokenizerFast` (HuggingFace) and uses a character-level Byte Pair Encoding (BPE) model with no merges [esm/tokenization/sequence_tokenizer.py:10-31]().

### Configuration and Vocab
*   **Vocabulary**: Based on `C.SEQUENCE_VOCAB` [esm/tokenization/sequence_tokenizer.py:27-28]().
*   **Special Tokens**: Includes `<unk>`, `<cls>`, `<pad>`, `<mask>`, `<eos>`, and the chain break token `|` [esm/tokenization/sequence_tokenizer.py:18-24]().
*   **Post-Processing**: Automatically wraps single sequences in `<cls>` and `<eos>` tokens using `TemplateProcessing` [esm/tokenization/sequence_tokenizer.py:48-54]().

### Chain Breaks
The tokenizer handles multi-chain proteins using the `|` character. This is mapped to a specific `chain_break_token_id` to inform the model of discontinuities in the polypeptide backbone [esm/tokenization/sequence_tokenizer.py:24-41]().

Sources: [esm/tokenization/sequence_tokenizer.py:10-64]()

---

## SecondaryStructureTokenizer

The `SecondaryStructureTokenizer` handles the discretization of protein secondary structure into either 8-class (SS8) or 3-class (SS3) representations [esm/tokenization/ss_tokenizer.py:13-15]().

### Supported Vocabularies
| Kind | Vocabulary Source | Tokens |
| :--- | :--- | :--- |
| **SS8** | `C.SSE_8CLASS_VOCAB` | G, H, I, T, E, B, S, C [esm/tokenization/ss_tokenizer.py:26]() |
| **SS3** | `C.SSE_3CLASS_VOCAB` | H, E, C [esm/tokenization/ss_tokenizer.py:28]() |

### Implementation Details
*   **Special Tokens**: Uses `<pad>`, `<motif>`, and `<unk>`. Notably, for secondary structure, `<pad>` is used for BOS, EOS, and Chainbreak roles [esm/tokenization/ss_tokenizer.py:80-117]().
*   **Encoding**: Maps characters directly to indices in the concatenated list of special and non-special tokens [esm/tokenization/ss_tokenizer.py:33-67]().

Sources: [esm/tokenization/ss_tokenizer.py:10-126]()

---

## SASADiscretizingTokenizer

The `SASADiscretizingTokenizer` converts continuous Solvent Accessible Surface Area (SASA) values into discrete bins.

### Discretization Logic
*   **Bins**: Uses 15 discretization boundaries defined in `C.SASA_DISCRETIZATION_BOUNDARIES` [esm/tokenization/sasa_tokenizer.py:12]().
*   **Bucketing**: Uses `torch.bucketize` to map float values into discrete ranges [esm/tokenization/sasa_tokenizer.py:79-80]().
*   **Midpoints**: For decoding, the tokenizer maintains a `midpoints_tensor` to map discrete tokens back to a representative float value (the center of the bin) [esm/tokenization/sasa_tokenizer.py:34-42]().

### Vocabulary Structure
The vocabulary consists of special tokens followed by range tokens formatted as `<low-high>` (e.g., `<0-2.5>`) [esm/tokenization/sasa_tokenizer.py:26-31]().

Sources: [esm/tokenization/sasa_tokenizer.py:9-106]()

---

## StructureTokenizer (VQ-VAE Wrapper)

The `StructureTokenizer` is a convenience class designed to provide access to special token IDs used by the `StructureTokenEncoder` and `StructureTokenDecoder` (the VQ-VAE system) [esm/tokenization/structure_tokenizer.py:5-7]().

### VQ-VAE Special Tokens
Because structure tokens represent latent codes from a VQ-VAE codebook, they do not have string representations. The tokenizer defines special IDs starting after the codebook size [esm/tokenization/structure_tokenizer.py:9-16]().

| Token Name | ID Calculation |
| :--- | :--- |
| **MASK** | `codebook_size` |
| **EOS** | `codebook_size + 1` |
| **BOS** | `codebook_size + 2` |
| **PAD** | `codebook_size + 3` |
| **CHAINBREAK** | `codebook_size + 4` |

**Note**: Calling `encode()` or `decode()` on this class will raise a `NotImplementedError`, as structure encoding requires 3D coordinates and the VQ-VAE model [esm/tokenization/structure_tokenizer.py:71-83]().

Sources: [esm/tokenization/structure_tokenizer.py:5-83]()

---

## Class Relationship Diagram

The following diagram shows how the tokenizer classes relate to the base protocol and the underlying utilities.

**Tokenizer Class Hierarchy**
```mermaid
classDiagram
    class EsmTokenizerBase {
        <<Protocol>>
        +mask_token_id: int
        +bos_token_id: int
        +encode()
        +decode()
    }

    class EsmSequenceTokenizer {
        +cb_token: str
        +model_input_names: list
        +encode(text)
    }

    class SecondaryStructureTokenizer {
        +kind: str
        +vocab: list
        +encode(sequence)
    }

    class SASADiscretizingTokenizer {
        -_boundaries: list
        +midpoints_tensor: Tensor
        +encode(values)
    }

    class StructureTokenizer {
        +vq_vae_special_tokens: dict
    }

    EsmTokenizerBase <|.. EsmSequenceTokenizer : implements
    EsmTokenizerBase <|.. SecondaryStructureTokenizer : implements
    EsmTokenizerBase <|.. SASADiscretizingTokenizer : implements
    EsmTokenizerBase <|.. StructureTokenizer : implements

    EsmSequenceTokenizer --|> PreTrainedTokenizerFast : inherits
```
Sources: [esm/tokenization/tokenizer_base.py:4-26](), [esm/tokenization/sequence_tokenizer.py:10](), [esm/tokenization/ss_tokenizer.py:10](), [esm/tokenization/sasa_tokenizer.py:9](), [esm/tokenization/structure_tokenizer.py:5]()

---