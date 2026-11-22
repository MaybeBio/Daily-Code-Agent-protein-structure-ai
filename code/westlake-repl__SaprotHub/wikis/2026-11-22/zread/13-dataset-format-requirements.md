

This page outlines the comprehensive dataset format requirements for SaprotHub, covering various protein analysis tasks and input formats. Understanding these requirements is essential for preparing data that works seamlessly with the Saprot model architecture.

## Core Data Architecture

SaprotHub uses LMDB (Lightning Memory-Mapped Database) as its primary data storage format, providing efficient access to large-scale protein datasets. All dataset classes inherit from the abstract `LMDBDataset` class [saprot/dataset/lmdb_dataset.py](saprot/dataset/lmdb_dataset.py#L14-L17), which provides the foundation for data loading and management.

### Dataset Loading Interface

The `DataInterface` class [saprot/dataset/data_interface.py](saprot/dataset/data_interface.py#L88-L99) provides dynamic dataset loading capabilities:

```python
@classmethod
def init_dataset(cls, dataset_py_path: str, **kwargs):
    """
    Args:
       dataset_py_path: Path to dataset file
       **kwargs: Kwargs for model initialization
    Returns: Corresponding model
    """
```

## Input Format Categories

### 1. Amino Acid Sequences

For standard amino acid sequence analysis, datasets should follow this CSV format:

**Structure:**
```csv
sequence,label,stage
MEETMKLATMEDTVEYCLFLIPDESRDSDKHKEILQKYIERIITRFAPMLVPYIWQNQPFNLKYKPGKGGVPAHMFGVTKFGDNIEDEWFIVYVIKQITKEFPELVARIEDNDGEFLLIEAADFLPKWLDPENSTNRVFFCHGELCIIPAPRKSGAESWLPTTPPTIPQALNIITAHSEKILASESIRAAVNRRIRGYPEKIQASLHRAHCFLPAGIVAVLKQRPRLVAAAVQAFYLRDPIDLRACRVFKTFLPETRIMTSVTFTKCLYAQLVQQRFVPDRRSGYRLPPPSDPQYRAHEL,0,train
MAVMAPRTLLLLLSGALALTQTWAGSHSMRYFFTSVSRPGRGEPRFIAVGYVDDTQFVRFDSDAASQRMEPRAPWIEQEGPEYWDQETRNVKAQSQTDRVDLGTLRGYYNQSEAGSHTIQIMYGCDVGSDGRFLRGYRQDAYDGKDYIALNEDLRSWTAADMAAQITKRKWEAAHEAEQLRAYLDGTCVEWLRRYLENGKETLQRTDPPKTHMTHHPISDHEATLRCWALGFYPAEITLTWQRDGEDQTQDTELVETRPAGDGTFQKWAAVVVPSGEEQRYTCHVQHEGLPKPLTLRWEL,1,test
```

**Fields:**
- `sequence`: Raw amino acid sequence string
- `label`: Target value (classification or regression)
- `stage`: Data split (train/test/valid)

### 2. Structure-Aware Sequences

For structure-aware protein representation, use the enhanced format with structural information:

**Structure:**
```csv
sequence,label,stage
MdEvEvTvMpKpLpApTaMpEaDqTkVkEkYkCwLkFdLfIpPpDpEpSdRpDpSqDvKvHvKqEvIvLqQvKvYlIqElRlIlIcTlRlFcAcPlMqLqVlPvYfIqWqQlNfQaPgFaNfLwKdYwKdPpGdKdGdGlVrPhAtHtMiFmGtVmTdKrFrGdDpNdIcEvDrEvWlFvIvVvYvVsIqKlQvIsTlKqEvFpPqErLmVkAmRdImEaDhNpDlGgErFcLlLcIvElAlAvDvFpLdPdKpWvLdDdPpEqNaSqTaNlRqVwFiFrCgHnGsEaLiCfIgIqPdAa,0,train
```

**Key Features:**
- Each amino acid is paired with structural annotation
- Format: `AminoAcid(1 letter) + StructuralState(1 letter)`
- Structural states indicate 3D conformation information

### 3. PDB Structure Files

For direct structure-based analysis using PDB or AlphaFold2 files:

**Structure:**
```csv
sequence,type,chain,label,stage
1qsf.pdb,PDB,A,1,valid
1szh.pdb,PDB,A,0,train
2br2.pdb,PDB,A,1,test
O95905.pdb,AF2,A,1,train
P04439.pdb,AF2,A,0,train
```

**Fields:**
- `sequence`: PDB filename or UniProt ID
- `type`: PDB (experimental) or AF2 (AlphaFold2 predicted)
- `chain`: Protein chain identifier
- `label`: Target value
- `stage`: Data split

## Task-Specific Dataset Formats

### Classification Tasks

**Dataset Class:** `SaprotClassificationDataset` [saprot/dataset/saprot/saprot_classification_dataset.py](saprot/dataset/saprot/saprot_classification_dataset.py#L11-L99)

**Input Requirements:**
- Tokenizer path for sequence encoding
- Optional structure masking capabilities
- pLDDT threshold support for confidence filtering
- Maximum sequence length (default: 1024)

**Key Parameters:**
```python
mask_struc_ratio: float = None  # Ratio of masked structure tokens
plddt_threshold: float = None   # Mask structure tokens with pLDDT < threshold
use_bias_feature: bool = False   # Include structural coordinates
```

### Regression Tasks

**Dataset Class:** `SaprotRegressionDataset` [saprot/dataset/saprot/saprot_regression_dataset.py](saprot/dataset/saprot/saprot_regression_dataset.py#L13-L108)

**Additional Features:**
```python
min_clip: [float, float] = None      # [given_value, clip_value]
mix_max_norm: [float, float] = None  # [min_norm, max_norm] for normalization
```

### Pair Classification Tasks

**Dataset Class:** `SaprotPairClassificationDataset` [saprot/dataset/saprot/saprot_pair_classification_dataset.py](saprot/dataset/saprot/saprot_pair_classification_dataset.py#L10-L82)

**Input Format:**
```csv
seq_1,seq_2,label
MEETMKLATMEDTVEYCLFLIPDESRDSDKHKEILQKYIERIITRFAPMLVPYIWQNQPFNLKYKPGKGGVPAHMFGVTKFGDNIEDEWFIVYVIKQITKEFPELVARIEDNDGEFLLIEAADFLPKWLDPENSTNRVFFCHGELCIIPAPRKSGAESWLPTTPPTIPQALNIITAHSEKILASESIRAAVNRRIRGYPEKIQASLHRAHCFLPAGIVAVLKQRPRLVAAAVQAFYLRDPIDLRACRVFKTFLPETRIMTSVTFTKCLYAQLVQQRFVPDRRSGYRLPPPSDPQYRAHEL,MAVMAPRTLLLLLSGALALTQTWAGSHSMRYFFTSVSRPGRGEPRFIAVGYVDDTQFVRFDSDAASQRMEPRAPWIEQEGPEYWDQETRNVKAQSQTDRVDLGTLRGYYNQSEAGSHTIQIMYGCDVGSDGRFLRGYRQDAYDGKDYIALNEDLRSWTAADMAAQITKRKWEAAHEAEQLRAYLDGTCVEWLRRYLENGKETLQRTDPPKTHMTHHPISDHEATLRCWALGFYPAEITLTWQRDGEDQTQDTELVETRPAGDGTFQKWAAVVVPSGEEQRYTCHVQHEGLPKPLTLRWEL,1
```

## Data Processing Pipeline

### LMDB Entry Structure

Each LMDB entry contains JSON-formatted data with the following common fields:

```json
{
  "seq": "structure_aware_sequence",
  "label": "target_value",
  "coords": {
    "N": [x1, y1, z1, ...],
    "CA": [x2, y2, z2, ...],
    "C": [x3, y3, z3, ...],
    "O": [x4, y4, z4, ...]
  },
  "plddt": [confidence_scores]
}
```

### Quality Control Features

**Structure Masking:**
- Random structure token masking based on `mask_struc_ratio`
- Confidence-based masking using `plddt_threshold`
- Seed-based reproducible masking

**Sequence Length Management:**
- Automatic truncation to `max_length`
- Token-based length calculation
- Preserves structural information integrity

## Advanced Dataset Types

SaprotHub supports specialized dataset classes for various protein analysis tasks:

- **Annotation Tasks:** `saprot_annotation_dataset.py`
- **Contact Prediction:** `saprot_contact_dataset.py`  
- **Foldseek Integration:** `saprot_foldseek_dataset.py`
- **Language Modeling:** `saprot_lm_dataset.py`
- **PPI Prediction:** `saprot_ppi_dataset.py`
- **Sequence Design:** `saprot_seq_design_dataset.py`
- **Token Classification:** `saprot_token_classification_dataset.py`

## Implementation Guidelines

### Dataset Registration

Use the `@register_dataset` decorator to make custom datasets available:

```python
@register_dataset
class CustomDataset(LMDBDataset):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Custom initialization
    
    def __getitem__(self, index):
        # Custom data loading logic
        pass
    
    def __len__(self):
        # Custom length calculation
        pass
    
    def collate_fn(self, batch):
        # Custom batch processing
        pass
```

### Data Validation

Ensure data quality by implementing:
- Sequence format validation
- Structure coordinate verification
- Label range checking
- Missing data handling

> [!TIP]
> Always validate input sequences and structures before LMDB conversion to prevent runtime errors during training.

> [!TIP]
> Use the provided example datasets in `upload_files/example_csv_dataset/` as templates for understanding the expected format for different task types.

## Next Steps

For detailed information on processing protein structures with Foldseek integration, refer to [Protein Structure Processing with Foldseek](14-protein-structure-processing-with-foldseek). To understand how structure-aware sequences are generated, see [Structure-Aware Sequence Generation](12-structure-aware-sequence-generation).