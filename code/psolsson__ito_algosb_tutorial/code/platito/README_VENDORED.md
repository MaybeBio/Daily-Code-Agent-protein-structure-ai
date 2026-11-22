# Vendored copy of PLaTITO (inference only)

This directory is an unmodified subset (`platito/models`, `platito/utils/amino_acid_vocab.py`)
of https://github.com/PanosAntoniadis/platito at commit
82f753507064bc056013b6a89da7973c35fdf87a (MIT License, see LICENSE in this folder).

Only the code needed to load a checkpoint and generate trajectories is included, so the
course environment does not need hydra, wandb, h5py or the ESM SDK.
For training, embeddings and the full pipeline, use the original repository.
