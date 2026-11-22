"""Fine-tune on MegaScale ddG.

Usage:
    python -m pobj.train.finetune --config configs/arm_a.yaml [--seed 0]

The test split is read once, at the checkpoint with the best validation Spearman.
"""
import argparse
import copy
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch_geometric.loader import DataLoader

from ..data.dataset import batch_protein_names, load_all, protein_items
from ..eval.metrics import evaluate
from ..models.encoder import Encoder
from ..models.heads import DDGHead, DDGModel
from ..utils import append_row, get_device, git_commit, load_config, set_seed


def build_model(cfg: dict, pretrained: Path | str | None = None,
                freeze: bool = False) -> DDGModel:
    enc = Encoder(dim=cfg["encoder"]["dim"],
                  layers=cfg["encoder"]["layers"],
                  dropout=cfg["encoder"]["dropout"])
    if pretrained:
        enc.load_state_dict(torch.load(pretrained, map_location="cpu"))
    head = DDGHead(dim=cfg["encoder"]["dim"],
                   hidden=cfg["ddg_head"]["hidden"],
                   layers=cfg["ddg_head"]["layers"],
                   aa_dim=cfg["ddg_head"]["aa_dim"],
                   dropout=cfg["encoder"]["dropout"])
    return DDGModel(enc, head, freeze_encoder=freeze)


@torch.no_grad()
def predict(model: nn.Module, loader: DataLoader,
            device: torch.device) -> tuple[np.ndarray, np.ndarray, list[str]]:
    model.eval()
    pred, true, proteins = [], [], []
    for batch in loader:
        proteins += batch_protein_names(batch)
        batch = batch.to(device)
        pred.append(model(batch).cpu().numpy())
        true.append(batch.ddg.cpu().numpy())
    return np.concatenate(pred), np.concatenate(true), proteins


def train_epoch(model: nn.Module, loader: DataLoader, optimizer: torch.optim.Optimizer,
                loss_fn: nn.Module, device: torch.device) -> float:
    model.train()
    total, n = 0.0, 0
    for batch in loader:
        batch = batch.to(device)
        optimizer.zero_grad()
        loss = loss_fn(model(batch), batch.ddg)
        loss.backward()
        optimizer.step()
        total += loss.item() * batch.ddg.numel()
        n += batch.ddg.numel()
    return total / n


def run(cfg: dict, device: torch.device | None = None, verbose: bool = True) -> dict:
    seed = cfg["seed"]
    set_seed(seed)
    device = device or get_device()

    labels, graphs = load_all(raw_dir=cfg["data"]["raw_dir"],
                              pdb_dir=cfg["data"]["pdb_dir"],
                              k=cfg["graph"]["k_neighbours"],
                              cache_dir=cfg["data"]["processed_dir"])

    ft = cfg["finetune"]
    loaders = {}
    for split in ("train", "val", "test"):
        items = protein_items(labels, graphs, split)
        loaders[split] = DataLoader(items, batch_size=ft["batch_proteins"],
                                    shuffle=(split == "train"))

    target = cfg.get("pretrain", {}).get("target")       # unset for arm A
    corpus = cfg.get("pretrain", {}).get("corpus")
    pretrained = ft.get("pretrained")
    if pretrained is None and target:
        pretrained = (Path(cfg["pretrain"]["checkpoint_dir"])
                      / f"encoder_{cfg['arm']}_{corpus}_seed{seed}.pt")
    if pretrained and not Path(pretrained).exists():
        raise FileNotFoundError(f"no pretrained encoder at {pretrained}; "
                                f"run pobj.train.pretrain for arm {cfg['arm']} first")

    model = build_model(cfg, pretrained=pretrained,
                        freeze=ft["mode"] == "frozen").to(device)
    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=ft["lr"], weight_decay=ft["weight_decay"])
    loss_fn = nn.MSELoss()

    best = {"spearman": -np.inf, "epoch": -1, "state": None}
    start = time.time()

    for epoch in range(ft["max_epochs"]):
        loss = train_epoch(model, loaders["train"], optimizer, loss_fn, device)
        pred, true, proteins = predict(model, loaders["val"], device)
        val = evaluate(pred, true, proteins, cfg["eval"]["min_mutations_per_protein"])

        if verbose:
            print(f"epoch {epoch:3d}  train mse {loss:.4f}  "
                  f"val spearman {val['pooled_spearman']:.4f}  "
                  f"val rmse {val['rmse']:.4f}")

        if val["pooled_spearman"] > best["spearman"]:
            best = {"spearman": val["pooled_spearman"], "epoch": epoch,
                    "state": copy.deepcopy(model.state_dict())}
        elif epoch - best["epoch"] >= ft["patience"]:
            if verbose:
                print(f"no improvement for {ft['patience']} epochs, stopping")
            break

    model.load_state_dict(best["state"])
    elapsed = time.time() - start

    pred, true, proteins = predict(model, loaders["test"], device)
    test = evaluate(pred, true, proteins, cfg["eval"]["min_mutations_per_protein"])
    if verbose:
        print(f"\nbest epoch {best['epoch']} (val spearman {best['spearman']:.4f})")
        print(f"test  pooled spearman {test['pooled_spearman']:.4f}  "
              f"per-protein median {test['per_protein_median_spearman']:.4f} "
              f"over {test['n_proteins_scored']} proteins  rmse {test['rmse']:.4f}")

    return {
        "arm": cfg.get("arm"),
        "seed": seed,
        "pretrain": target or "none",
        "corpus": corpus if target else "none",
        "pretrained_from": str(pretrained or ""),
        "finetune_mode": ft["mode"],
        "best_epoch": best["epoch"],
        "val_spearman": best["spearman"],
        "test_pooled_spearman": test["pooled_spearman"],
        "test_per_protein_median_spearman": test["per_protein_median_spearman"],
        "test_rmse": test["rmse"],
        "n_proteins_scored": test["n_proteins_scored"],
        "finetune_time_s": round(elapsed, 1),
        "device": str(device),
        "git_commit": git_commit(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--base", default="configs/base.yaml")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--corpus", choices=["scope", "alphafold"])
    parser.add_argument("--mode", choices=["frozen", "full"],
                        help="override finetune.mode, to separate the effect of "
                             "pretraining from the effect of freezing")
    args = parser.parse_args()

    cfg = load_config(args.base, args.config)
    if args.seed is not None:
        cfg["seed"] = args.seed
    if args.mode is not None:
        cfg["finetune"]["mode"] = args.mode
    if args.corpus is not None:
        cfg["pretrain"]["corpus"] = args.corpus
    cfg["config_path"] = args.config

    row = run(cfg)
    row["config_path"] = args.config
    append_row(cfg["results_csv"], row)
    print(f"appended to {cfg['results_csv']}")


if __name__ == "__main__":
    main()
