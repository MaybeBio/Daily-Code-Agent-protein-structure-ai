# Protein Allergen Prediction

This repository contains two research implementations for protein allergen prediction:

1. **PPLM + GNN** — a ProtT5-based protein representation pipeline with graph neural network models.
2. **MLP + CNN & MHSA + Graph Transformer** — a multimodal architecture combining ProtT5 representations, evolutionary descriptors, and graph-transformer-based modeling.

## Repository layout

```text
PPLM + GNN/
  gnn_models.py
  prott5_graph_dataset.py
  train_and_compare_gnns.py

MLP + CNN & MHSA + Graph Transformer/
  graph_transformer_model.py
  evo_hybrid_fusion_model.py
  prott5_gt_dataset.py
  pssm_evo_features.py
  train_and_test_multimodal.py
  eval_5fold_ensemble.py
  benchmark_params_and_latency.py
  descriptors/
```

The second project directory also contains FASTA sequence files and precomputed evolutionary descriptor files used by its pipeline.

## Notes

- Model checkpoints, virtual environments, and cached pretrained-model embeddings are not included in this repository bundle.
- Install dependencies in an isolated Python environment. The projects may have different dependency requirements; consult their source code and configure environments separately if needed.
- Pretrained ProtT5 weights are not bundled. The relevant code may download them from the model provider when run.
- Verify the provenance, license, and redistribution terms of the FASTA sequences and descriptor data before redistributing this public repository.
- Experimental results depend on the data, random seeds, software versions, and hardware configuration. Consult the scripts and experiment logs for implementation details.

## Projects

### PPLM + GNN

See [`PPLM + GNN/`](https://github.com/Almer-FW/protein-allergen-prediction/blob/HEAD/PPLM%20%2B%20GNN) for the graph-neural-network implementation.

### MLP + CNN & MHSA + Graph Transformer

See [`MLP + CNN & MHSA + Graph Transformer/`](https://github.com/Almer-FW/protein-allergen-prediction/blob/HEAD/MLP%20%2B%20CNN%20%26%20MHSA%20%2B%20Graph%20Transformer) for the multimodal implementation and evolutionary descriptor inputs.
