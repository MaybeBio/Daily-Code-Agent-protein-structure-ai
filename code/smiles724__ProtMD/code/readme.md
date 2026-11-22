# ProtMD

ProtMD pretrains an equivariant graph neural network on molecular dynamics trajectories and transfers the encoder to ligand binding affinity (LBA) and ligand efficacy prediction (LEP).

[Published paper](https://doi.org/10.1002/advs.202203796) · [arXiv](https://arxiv.org/abs/2204.08663) · [Pretrained checkpoint](https://github.com/smiles724/ProtMD/blob/HEAD/save/model.pt) · [Citation](#citation)

![Overview of the ProtMD pretraining and downstream workflows](https://github.com/smiles724/ProtMD/raw/HEAD/model.png)

## Installation

Use an isolated Python environment. The CPU workflow was tested with Python 3.9 and PyTorch 2.8. The training scripts use the PyTorch 2.4+ AMP API.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install "torch>=2.4" numpy einops scipy scikit-learn
```

Install a [CUDA-enabled PyTorch build](https://pytorch.org/get-started/locally/) for GPU training. Use `--gpu cpu` for CPU runs and `--gpu 0` or `--gpu 0,1` for CUDA runs. The dense EGNN used by these scripts requires `einops`. The separate sparse EGNN requires PyTorch Geometric.

## Quick Start

The repository includes `save/model.pt`. After preparing the [LBA data](#downstream-data), run the following from the repository root. The example freezes the encoder and trains the prediction head for one epoch.

```bash
python main.py --data lba --split 30 --unknown false \
  --pretrain save/model.pt --linear_probe --gpu cpu --epochs 1
```

Omit `--linear_probe` to fine-tune the encoder. Omit `--pretrain` to train from scratch. For LEP, use `--data lep`. Set `--data_dir` to change the processed-data directory and `--save_path` to change the checkpoint and log directory.

## Data

### Downstream data

The [ATOM3D](https://www.atom3d.ai/) LBA and [LEP](https://zenodo.org/record/4914734) datasets are distributed separately. Point each preprocessor at the extracted directory containing the `train`, `val` (or `valid`), and `test` LMDB directories. Install `atom3d` first.

```bash
python -m pip install atom3d
python pdbbind/dataloader_pdb.py --split 30 --input-dir /path/to/lba/data
python lep/dataloader_lep.py --input-dir /path/to/lep/data
```

Both scripts write to `data/pdb/` by default. LBA expects `pdb_{train,val,test}_{30,60}.pt`, with the suffix matching the selected sequence-identity split. LEP expects `lep_{train,val,test}.pt`. LBA files contain `[tokens, indices, coordinates, labels]`. LEP files contain `[tokens, coordinates, labels]`. Token 0 is reserved for padding, and each preprocessor shares one vocabulary across its three splits.

For LBA, `--unknown false` selects the experimental structures for the test split. `--unknown true` selects a separately prepared `docking_test_<split>.pt` file. The original repository links to [EquiBind data](https://zenodo.org/record/6034088) for experiments on predicted structures. When using existing processed tensors, use the same atom-to-token mapping in all splits.

The 60% ATOM3D split and the historical [HoloProt](https://github.com/vsomnath/holoprot) split have different membership. Keep the split source consistent when comparing results.

### Trajectory data

The original pretraining trajectories from MindRank AI are private. The repository includes [format conversion](https://github.com/smiles724/ProtMD/blob/HEAD/data/nc2xtc.ipynb) and [NumPy export](https://github.com/smiles724/ProtMD/blob/HEAD/data/xtc2npy.ipynb) notebooks for users who have trajectory files.

`pretrain.py` reads `.npy` dictionaries from `data/md/` by default. Each file contains `R` with shape `[frames, atoms, 3]` and `z` with the corresponding atom symbols. The dataset loader uses NumPy pickle support for this format, so use files from a trusted source.

## Pretraining

With prepared trajectories in hand, run:

```bash
python pretrain.py --data_dir /path/to/trajectories --gpu 0 --epochs 200
```

`--prompt 1,2` trains on frame offsets of one and two. `--ordering` adds the snapshot-ordering objective. `--noise false` disables coordinate noise. `--split_ratio` controls the chronological train/validation boundary within each trajectory. Each side must have enough frames to form pairs for at least one requested offset.

Pretraining saves the encoder separately from the optional ordering classifier. To use a saved checkpoint in `main.py`, pass its path to `--pretrain` and use the same encoder dimensions and depth.

## Repository layout

- [egnn/](https://github.com/smiles724/ProtMD/blob/HEAD/egnn) contains the dense and sparse EGNN implementations.
- [data/](https://github.com/smiles724/ProtMD/blob/HEAD/data) contains the trajectory dataset loader and conversion notebooks.
- [pdbbind/](https://github.com/smiles724/ProtMD/blob/HEAD/pdbbind), [lep/](https://github.com/smiles724/ProtMD/blob/HEAD/lep), and [unknown_structure/](https://github.com/smiles724/ProtMD/blob/HEAD/unknown_structure) contain downstream data preparation code.
- [utils/](https://github.com/smiles724/ProtMD/blob/HEAD/utils) contains shared CLI and logging code, plotting scripts, and reference baselines.

## Citation

```bibtex
@article{wu2022pre,
  title = {Pre-Training of Equivariant Graph Matching Networks with Conformation Flexibility for Drug Binding},
  author = {Wu, Fang and Jin, Shuting and Jiang, Yinghui and Jin, Xurui and Tang, Bowen and Niu, Zhangming and Liu, Xiangrong and Zhang, Qiang and Zeng, Xiangxiang and Li, Stan Z.},
  journal = {Advanced Science},
  year = {2022},
  volume = {9},
  number = {33},
  pages = {2203796},
  doi = {10.1002/advs.202203796}
}
```

For questions, contact [Fang Wu](mailto:fangwu97@stanford.edu).
