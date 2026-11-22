"""Pretrain the encoder on unlabelled structures.

Usage:
    python -m pobj.train.pretrain --config configs/arm_c.yaml [--seed 0] [--limit 1000]

--limit trains on a subset, which is how we timed one epoch before committing to a corpus
size. The encoder weights go to results/checkpoints/, and the per-epoch log, including
effective rank, to results/.

A run saves its full state every save_every epochs and picks up from there if started
again, so an interrupted grid does not have to start over. Pass --fresh to ignore it.
"""
import argparse
import math
import time
from pathlib import Path

import torch
import torch.nn as nn
from torch_geometric.loader import DataLoader

from ..data.masking import apply_mask, sample_mask
from ..data.pretrain_set import load_pretrain_graphs
from ..eval.rank import effective_rank, per_dimension_variance
from ..losses import letter_loss, vector_loss
from ..models.ema import EMATeacher
from ..models.encoder import Encoder
from ..models.heads import LetterHead, Predictor
from ..utils import append_row, get_device, git_commit, load_config, set_seed


def run_tag(cfg: dict) -> str:
    """Names a run by arm, corpus and seed, so two corpora never share a checkpoint."""
    return f"{cfg['arm']}_{cfg['pretrain']['corpus']}_seed{cfg['seed']}"


def split_graphs(graphs: list, val_fraction: float, seed: int) -> tuple[list, list]:
    """A held-out slice of the corpus, so letter accuracy is measured on unseen structures."""
    order = torch.randperm(len(graphs), generator=torch.Generator().manual_seed(seed))
    n_val = max(1, int(len(graphs) * val_fraction))
    val = [graphs[i] for i in order[:n_val]]
    train = [graphs[i] for i in order[n_val:]]
    return train, val


def letter_frequencies(graphs: list) -> torch.Tensor:
    """The most common amino acid, as the baseline any real model has to beat."""
    counts = torch.zeros(20)
    for g in graphs:
        counts += torch.bincount(g.x, minlength=20).float()
    return counts / counts.sum()


def step_losses(encoder: nn.Module, heads: nn.ModuleDict, batch, mask_rate: float,
                generator: torch.Generator | None = None,
                teacher: EMATeacher | None = None,
                lam: float = 0.0) -> tuple[torch.Tensor, dict[str, float], int]:
    """One masked forward pass for whichever arm is being trained.

    -> (loss to backward through, numbers to log, how many residues were masked)
    """
    mask = sample_mask(batch, mask_rate, generator)
    x, targets = apply_mask(batch, mask)
    z = encoder(x, batch.node_feat, batch.edge_index, batch.edge_attr)

    loss, stats = 0.0, {}

    if "letter" in heads:
        logits = heads["letter"](z[mask])
        letter = letter_loss(logits, targets)
        loss = loss + letter
        stats["letter_loss"] = float(letter.detach())
        stats["letter_accuracy"] = float((logits.argmax(-1) == targets).float().mean())

    if "predictor" in heads:
        target_z = teacher(batch)[mask]                  # the unmasked graph, no gradient
        predicted = heads["predictor"](z[mask])
        vector = vector_loss(predicted, target_z)
        loss = loss + (lam if "letter" in heads else 1.0) * vector
        stats["vector_loss"] = float(vector.detach())
        stats["target_cosine_spread"] = float(
            nn.functional.normalize(target_z, dim=-1).std(dim=0).mean())

    stats["loss"] = float(loss.detach())
    return loss, stats, int(mask.sum())


def build_heads(cfg: dict, target: str) -> nn.ModuleDict:
    """The heads each arm needs. The encoder is identical in every case."""
    dim = cfg["encoder"]["dim"]
    heads = {}
    if target in ("letter", "both"):
        heads["letter"] = LetterHead(dim)
    if target in ("vector", "both"):
        heads["predictor"] = Predictor(dim, layers=cfg["pretrain"]["predictor_layers"])
    if not heads:
        raise ValueError(f"unknown pretraining target {target!r}")
    return nn.ModuleDict(heads)


class Running:
    """Averages per-residue quantities over the masked residues seen, not over batches."""

    def __init__(self):
        self.totals, self.n = {}, 0

    def add(self, stats: dict[str, float], weight: int) -> None:
        self.n += weight
        for key, value in stats.items():
            self.totals[key] = self.totals.get(key, 0.0) + value * weight

    def mean(self) -> dict[str, float]:
        return {key: value / self.n for key, value in self.totals.items()}


@torch.no_grad()
def evaluate(encoder, heads, loader, mask_rate, device, seed, teacher=None, lam=0.0,
             rank_sample=None):
    encoder.eval()
    generator = torch.Generator().manual_seed(seed)       # the same masks every epoch
    running, embeddings = Running(), []
    for batch in loader:
        batch = batch.to(device)
        _, stats, weight = step_losses(encoder, heads, batch, mask_rate, generator,
                                       teacher, lam)
        running.add(stats, weight)
        embeddings.append(encoder.encode(batch).cpu())

    out = running.mean()
    z = torch.cat(embeddings)
    out["effective_rank"] = effective_rank(z, sample=rank_sample, seed=seed)
    out["n_residues_for_rank"] = min(rank_sample, z.shape[0]) if rank_sample else z.shape[0]
    out["n_residues_available"] = z.shape[0]
    out.update(per_dimension_variance(z))
    return out


def run(cfg: dict, device: torch.device | None = None, limit: int | None = None,
        verbose: bool = True, resume: bool = True) -> dict:
    seed = cfg["seed"]
    set_seed(seed)
    device = device or get_device()
    pt = cfg["pretrain"]

    graphs = load_pretrain_graphs(corpus=pt["corpus"],
                                  k=cfg["graph"]["k_neighbours"],
                                  cache_dir=cfg["data"]["processed_dir"],
                                  limit=limit)
    train, val = split_graphs(graphs, pt["val_fraction"], seed)
    baseline = float(letter_frequencies(train).max())
    if verbose:
        print(f"{len(train):,} structures to train on, {len(val):,} held out")
        print(f"most common amino acid: {baseline:.3f} of residues, the accuracy to beat")

    encoder = Encoder(dim=cfg["encoder"]["dim"], layers=cfg["encoder"]["layers"],
                      dropout=cfg["encoder"]["dropout"]).to(device)
    heads = build_heads(cfg, pt["target"]).to(device)

    loaders = {
        "train": DataLoader(train, batch_size=pt["batch_proteins"], shuffle=True),
        "val": DataLoader(val, batch_size=pt["batch_proteins"]),
    }
    steps = pt["epochs"] * len(loaders["train"])
    lam = pt.get("lambda", 0.0)

    teacher = None
    if "predictor" in heads:
        teacher = EMATeacher(encoder, pt["ema_start"], pt["ema_end"], steps).to(device)

    optimizer = torch.optim.AdamW(list(encoder.parameters()) + list(heads.parameters()),
                                  lr=pt["lr"], weight_decay=pt["weight_decay"])
    warmup = max(1, int(pt["warmup_frac"] * steps))
    schedule = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda s: (s + 1) / warmup if s < warmup
        else 0.5 * (1 + math.cos(math.pi * (s - warmup) / max(1, steps - warmup))))

    tag = run_tag(cfg)
    log_path = Path(cfg["results_dir"]) / f"pretrain_{tag}.csv"
    generator = torch.Generator().manual_seed(seed)
    state_path = Path(pt["checkpoint_dir"]) / f"state_{tag}.pt"

    first_epoch = 0
    if resume and state_path.exists():
        state = torch.load(state_path, map_location=device, weights_only=False)
        encoder.load_state_dict(state["encoder"])
        heads.load_state_dict(state["heads"])
        optimizer.load_state_dict(state["optimizer"])
        schedule.load_state_dict(state["schedule"])
        generator.set_state(state["generator"])
        if teacher is not None and state.get("teacher"):
            teacher.load_state_dict(state["teacher"])
            teacher.steps = state["teacher_steps"]
        first_epoch = state["epoch"] + 1
        if verbose:
            print(f"resuming from {state_path} at epoch {first_epoch}")

    def save_state(epoch):
        torch.save({"epoch": epoch, "encoder": encoder.state_dict(),
                    "heads": heads.state_dict(), "optimizer": optimizer.state_dict(),
                    "schedule": schedule.state_dict(), "generator": generator.get_state(),
                    "teacher": teacher.state_dict() if teacher else None,
                    "teacher_steps": teacher.steps if teacher else 0},
                   state_path)

    Path(pt["checkpoint_dir"]).mkdir(parents=True, exist_ok=True)
    start = time.time()

    for epoch in range(first_epoch, pt["epochs"]):
        encoder.train()
        epoch_start = time.time()
        running = Running()
        for batch in loaders["train"]:
            batch = batch.to(device)
            optimizer.zero_grad()
            loss, stats, weight = step_losses(encoder, heads, batch, pt["mask_rate"],
                                              generator, teacher, lam)
            loss.backward()
            optimizer.step()
            schedule.step()
            if teacher is not None:
                teacher.update(encoder)
            running.add(stats, weight)

        train_log = running.mean()
        val_log = evaluate(encoder, heads, loaders["val"], pt["mask_rate"], device, seed,
                           teacher, lam, pt.get("rank_sample"))
        seconds = time.time() - epoch_start

        if verbose:
            extra = ""
            if "letter_accuracy" in val_log:
                extra += f"  letter acc {val_log['letter_accuracy']:.3f}"
            if "vector_loss" in val_log:
                extra += f"  vector {val_log['vector_loss']:.4f}"
            print(f"epoch {epoch:3d}  {seconds:5.1f}s  "
                  f"train loss {train_log['loss']:.4f}  "
                  f"val loss {val_log['loss']:.4f}{extra}  "
                  f"rank {val_log['effective_rank']:.1f}")

        if (epoch + 1) % pt["save_every"] == 0 or epoch == pt["epochs"] - 1:
            save_state(epoch)

        append_row(log_path, {"arm": cfg["arm"], "seed": seed, "epoch": epoch,
                              "seconds": round(seconds, 2),
                              "structures_per_s": round(len(train) / seconds, 1),
                              "baseline_letter_accuracy": baseline,
                              "ema_momentum": teacher.momentum() if teacher else "",
                              **{f"train_{k}": v for k, v in train_log.items()},
                              **{f"val_{k}": v for k, v in val_log.items()}})

    path = Path(pt["checkpoint_dir"]) / f"encoder_{tag}.pt"
    torch.save(encoder.state_dict(), path)

    elapsed = time.time() - start
    epochs_run = max(1, pt["epochs"] - first_epoch)
    if verbose:
        print(f"\n{elapsed / 60:.1f} min for {epochs_run} epochs, "
              f"{elapsed / epochs_run:.1f}s per epoch on {len(train):,} structures "
              f"({len(train) / (elapsed / epochs_run):.0f}/s)")
        print(f"encoder saved to {path}")
        print(f"log written to {log_path}")
    return {"checkpoint": str(path), "pretrain_time_s": round(elapsed, 1),
            "n_pretrain_structures": len(train), "git_commit": git_commit()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--base", default="configs/base.yaml")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--limit", type=int, help="use only this many structures")
    parser.add_argument("--epochs", type=int, help="override the configured epoch count")
    parser.add_argument("--corpus", choices=["scope", "alphafold"])
    parser.add_argument("--fresh", action="store_true",
                        help="ignore any saved state and start from epoch 0")
    args = parser.parse_args()

    cfg = load_config(args.base, args.config)
    if args.seed is not None:
        cfg["seed"] = args.seed
    if args.epochs is not None:
        cfg["pretrain"]["epochs"] = args.epochs
    if args.corpus is not None:
        cfg["pretrain"]["corpus"] = args.corpus
    run(cfg, limit=args.limit, resume=not args.fresh)


if __name__ == "__main__":
    main()
