

SaProt introduces a revolutionary approach to protein representation by integrating three-dimensional structural information directly into the language model's embedding space. Unlike traditional protein language models that process sequences independently of their spatial context, SaProt's structure-aware representation captures the intricate relationship between amino acid sequence and protein folding, enabling more accurate predictions across diverse biological tasks.

## Core Architecture: Structure-Sequence Integration

The foundation of SaProt's structure-aware representation lies in its dual-input processing pipeline, which seamlessly combines sequence and structural information through specialized encoding mechanisms.

### Structure Encoding Pipeline

The structural encoding process begins with extracting geometric features from protein coordinates using a sophisticated feature extraction pipeline:

```python
def coords2feature(coords: dict, device: str = 'cpu'):
    pair_feature = make_rbf(coords, device=device)
    pair_feature = torch.cat([pair_feature, make_orientations(coords, device)], dim=-1)
    return pair_feature
```

This pipeline generates **407-dimensional feature vectors** that capture both distance-based and orientation-based structural relationships between amino acid pairs [saprot/data/pdb2feature.py#L19-L23](saprot/data/pdb2feature.py#L19-L23).

### Radial Basis Function (RBF) Distance Features

The distance encoding employs **Radial Basis Functions (RBFs)** to discretize continuous distance measurements into learnable representations:

```python
def make_rbf(coord_dict, num_rbf=16, device='cpu'):
    coords = torch.stack([torch.tensor(coord_dict[k]) for k in ["N", "CA", "C", "O"]], dim=1)
    coords_dist = make_dist_map(coords)
    RBFs = torch.cat([rbf(coords_dist[..., i], 2., 22., num_rbf) for i in range(coords_dist.shape[-1])], dim=-1)
    return RBFs
```

The RBF transformation maps pairwise distances between backbone atoms (N, CA, C, O) into a **16-dimensional embedding space** spanning distances from 2Å to 22Å [saprot/data/data_transform.py#L95-L115](saprot/data/data_transform.py#L95-L115). This approach preserves continuous spatial information while making it amenable to neural network processing.

### Orientation Encoding with Quaternions

SaProt captures relative orientation between amino acids through a sophisticated quaternion-based representation:

```python
def make_orientations(coord_dict, device='cuda'):
    X_N, X_CA, X_C, _ = [atom_coords for atom_coords in coord_dict.values()]
    vec_CAtoC = F.normalize(X_C - X_CA, dim=-1)
    vec_CAtoN = F.normalize(X_N - X_CA, dim=-1)
    vec_cross_product = F.normalize(torch.cross(vec_CAtoN, vec_CAtoC), dim=-1)
    
    O = torch.stack((vec_CAtoN, vec_cross_product, torch.cross(vec_CAtoN, vec_cross_product)), -2)
    dX = X_CA[..., None, :] - X_CA[..., None, :, :]
    dU = torch.matmul(O[..., None, :, :].transpose(-1, -2), dX.unsqueeze(-1)).squeeze(-1)
    dU = F.normalize(dU, dim=-1)
    
    rots = torch.matmul(O.unsqueeze(-3).transpose(-1, -2), O.unsqueeze(-4))
    quats = rot2quat(rots)
    O_features = torch.cat((dU, quats), dim=-1)
    return O_features
```

This process creates **local reference frames** for each amino acid using the backbone geometry (N-CA-C atoms) and computes relative orientations between all residue pairs using **quaternion representations** [saprot/data/data_transform.py#L118-L152](saprot/data/data_transform.py#L118-L152). The resulting orientation features capture both directional relationships and rotational alignments between amino acids.

## Foldseek Integration: Efficient Structure-to-Sequence Mapping

SaProt leverages **Foldseek**, a structure alignment tool, to convert complex 3D protein structures into sequences that preserve structural information:

```python
def get_struc_seq(foldseek, path, chains: list = None, process_id: int = 0, 
                  plddt_mask: bool = True, plddt_threshold: float = 70.,
                  foldseek_verbose: bool = False) -> dict:
```

This function processes PDB files through Foldseek's `structureto3didescriptor` operation, generating **structural sequences** that encode geometric relationships in a sequence-like format [saprot/utils/foldseek_util.py#L12-L38](saprot/utils/foldseek_util.py#L12-L38). The integration enables:

- **Efficient storage**: Structural information compressed into sequence format
- **Fast processing**: Leverages existing protein language model infrastructure
- **Quality filtering**: Incorporates pLDDT confidence scores from AlphaFold2 predictions

> [!TIP]
> The Foldseek integration is crucial for scalability—it converts high-dimensional structural data into a format that can be processed by existing transformer architectures without requiring specialized 3D convolution operations.

## Model Architecture: Unified Sequence-Structure Processing

### Base Model Framework

The `SaprotBaseModel` serves as the foundation for all structure-aware tasks, providing a unified interface for different downstream applications:

```python
class SaprotBaseModel(AbstractModel):
    def __init__(self, task: str, config_path: str, extra_config: dict = None,
                 load_pretrained: bool = False, freeze_backbone: bool = False,
                 gradient_checkpointing: bool = False, lora_kwargs: dict = None, **kwargs):
```

This architecture supports **multiple task types** including classification, regression, token classification, and language modeling [saprot/model/saprot/base.py#L21-L34](saprot/model/saprot/base.py#L21-L34).

### Structure-Enhanced Tokenization

SaProt employs a specialized tokenizer that processes both sequence and structural information simultaneously:

```python
def __getitem__(self, index):
    entry = json.loads(self._get(index))
    seq = entry['seq']
    tokens = self.tokenizer.tokenize(seq)[:self.max_length]
    masked_tokens, labels = self._apply_bert_mask(tokens)
    return masked_seq, labels
```

The dataset implementation supports **masked language modeling** with structure-aware tokens, enabling the model to learn joint sequence-structure representations during pre-training [saprot/dataset/saprot/saprot_foldseek_dataset.py#L59-L74](saprot/dataset/saprot/saprot_foldseek_dataset.py#L59-L74).

## Training Configuration and Optimization

### Pre-training Strategy

The pre-training configuration emphasizes structure-aware learning through carefully designed hyperparameters:

```yaml
dataset:
  dataset_py_path: saprot/saprot_foldseek_dataset
  kwargs:
    tokenizer: westlake-repl/SaProt_35M_AF2
    max_length: 1024
    mask_ratio: 0.15
```

The model uses a **15% masking ratio** for structure-aware tokens during pre-training, following established BERT-style training protocols while incorporating structural context [saprot/config/pretrain/saprot.yaml#L47-L52](saprot/config/pretrain/saprot.yaml#L47-L52).

### Learning Rate Scheduling

The training employs a sophisticated learning rate schedule with warmup and decay phases:

```yaml
lr_scheduler_kwargs:
  last_epoch: -1
  init_lr: 0
  max_lr: 4.0e-4
  final_lr: 4.0e-5
  warmup_steps: 2000
  start_decay_after_n_steps: 150000
  end_decay_after_n_steps: 1500000
```

This schedule enables **stable convergence** during the initial training phase and gradual learning rate decay to fine-tune the structure-aware representations [saprot/config/pretrain/saprot.yaml#L17-L25](saprot/config/pretrain/saprot.yaml#L17-L25).

## Feature Engineering Pipeline

### Multi-scale Structural Features

SaRot's representation captures structural information at multiple scales:

1. **Local geometry**: Backbone dihedral angles and bond lengths
2. **Pairwise relationships**: Distance and orientation between amino acid pairs
3. **Global topology**: Overall fold architecture through Foldseek encoding

### Feature Integration Strategy

The final representation combines multiple feature streams:

```python
pair_feature = make_rbf(coords, 16, device=device)
pair_feature = torch.cat([pair_feature, make_orientations(coords, device)], dim=-1)
```

This concatenation creates a **comprehensive 407-dimensional feature vector** that captures both distance-based and orientation-based structural relationships [saprot/data/pdb2feature.py#L12-L13](saprot/data/pdb2feature.py#L12-L13).

> [!TIP]
> The multi-modal feature integration enables the model to learn complementary representations—RBF features capture spatial proximity while orientation features preserve directional relationships critical for understanding protein folding patterns.

## Advantages Over Sequence-Only Models

### Enhanced Biological Realism

Structure-aware representations provide several key advantages:

- **Contextual understanding**: Amino acid function depends on structural context
- **Long-range dependencies**: Captures interactions between distant residues
- **Conformational sensitivity**: Accounts for structural changes affecting function

### Performance Benefits

The integration of structural information leads to improved performance across diverse tasks:

- **Mutation effect prediction**: Structural context crucial for understanding impacts
- **Protein-protein interactions**: Interface geometry captured in representations
- **Function prediction**: Structure correlates strongly with biological function

## Implementation Considerations

### Computational Efficiency

Despite the complexity of structural encoding, SaProt maintains computational efficiency through:

- **Pre-computed features**: Structural features calculated offline
- **Batch processing**: Optimized for GPU acceleration
- **Memory management**: Efficient tensor operations for large proteins

### Scalability

The architecture supports proteins of varying lengths through:

- **Dynamic padding**: Handles variable sequence lengths
- **Gradient checkpointing**: Reduces memory usage for large proteins
- **Distributed training**: Scales across multiple GPUs

## Next Steps

To understand how these structure-aware representations are utilized in specific applications, continue with **[Transformer-Based Model Architecture](7-transformer-based-model-architecture)** which details the transformer modifications that enable effective processing of structure-aware tokens. For practical implementation guidance, see **[Structure-Aware Sequence Generation](12-structure-aware-sequence-generation)** which covers the data processing pipeline for preparing structure-aware datasets.