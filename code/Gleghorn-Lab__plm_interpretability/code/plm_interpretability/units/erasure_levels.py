"""E15e, exploratory: what linear erasure leaves behind, read by the monitors of Fel and colleagues (arXiv:2611.07071).

That report erases a concept with LEACE at an intermediate layer and finds the classes' means equal and their
covariances not, so the original linear direction and a refitted linear probe fall to chance at the layer, a
nonlinear probe still reads the concept there, and linear probes recover within two layers. The pooling study's
erasure read ridge probes only, so its recovery after erasure and the low cost of early erasure say nothing of a
second-order remnant. Here, for a protein-level concept and a block of ESMC:

1. LEACE is fitted on the mean-pooled stream leaving the block, over training proteins and the concept's classes
   (`fit_leace`), and applied to every token of that stream (`stream_eraser`). The map is affine, so the mean-pooled
   stream of every protein is erased exactly as fitted.
2. The stream leaving that block and later blocks is pooled over residues as its mean and its variance.
3. Readers are fitted on training proteins and scored on test proteins: the linear probe fitted on the intact model's
   means (`linear_original`, the report's level 1), a linear probe refitted on the erased means (`linear`, level 2), a
   one-hidden-layer MLP refitted on the erased means (`mlp`, level 3), and a linear probe refitted on the erased
   variances (`linear_variance`), the second moment of the tokens that the pooling study's own probes read; the same
   readers at later blocks are the report's level 4.

Symbols: n proteins; b proteins of a batch; l token columns; d stream width; k classes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from torch import Tensor, nn
from torch.nn import functional

from .atlas import encode_batch, length_batches
from .causal import transformer_blocks


ERASED_BLOCKS = (8, 17, 26)  # a quarter, half and three quarters of ESMC-600's stack, the depths of `concepts.DEPTHS`
READ_OFFSETS = (0, 1, 2, 4)  # blocks past the erased one at which the stream is read, with the last block
TRAIN_PROTEINS = 3_000
TEST_PROTEINS = 1_000
KINDS = ("binary", "multiclass")
HIDDEN = 512
STEPS = 300
VALIDATION_SHARE = 0.15
SEED = 24895
READERS = ("linear_original", "linear", "mlp", "linear_variance")


def fit_leace(states: Tensor, classes: Tensor) -> tuple[Tensor, Tensor]:
    """LEACE's eraser for class labels (Belrose and colleagues, 2023): the projection P and mean m of
    x -> x - P (x - m), after which no linear map of x predicts the classes better than a constant."""
    # states: (n, d); classes: (n,) integers
    states = states.double()  # (n, d)
    mean = states.mean(dim=0)  # (d,)
    centered = states - mean  # (n, d)
    targets = functional.one_hot(classes.long()).double()  # (n, k)
    targets = targets - targets.mean(dim=0)  # (n, k)
    covariance = centered.T @ centered / len(states)  # (d, d)
    cross = centered.T @ targets / len(states)  # (d, k)
    values, vectors = torch.linalg.eigh(covariance)  # (d,), (d, d)
    kept = values > values.max() * 1e-10  # (d,)
    whiten = (vectors[:, kept] * values[kept].rsqrt()) @ vectors[:, kept].T  # (d, d)
    unwhiten = (vectors[:, kept] * values[kept].sqrt()) @ vectors[:, kept].T  # (d, d)
    left, singular, _ = torch.linalg.svd(whiten @ cross, full_matrices=False)  # (d, k), (k,)
    left = left[:, singular > singular.max() * 1e-8]  # (d, rank)
    return unwhiten @ left @ left.T @ whiten, mean  # (d, d), (d,)


def erase(states: Tensor, projection: Tensor, mean: Tensor) -> Tensor:
    """x - P (x - m), row by row."""
    # states: (..., d); projection: (d, d); mean: (d,)
    return states - (states - mean) @ projection.T  # (..., d)


@contextmanager
def stream_eraser(model: nn.Module, block: int, projection: Tensor, mean: Tensor) -> Iterator[None]:
    """Erase the stream leaving `block` at every token, as it enters the next block, while the context is open."""
    # projection: (d, d); mean: (d,)
    blocks = transformer_blocks(model)

    def hook(module: nn.Module, args: tuple[Tensor, ...], kwargs: dict[str, object]) -> tuple[tuple[Tensor, ...], dict[str, object]]:
        # args: ((b, l, d), ...) when the stream is passed by position, else kwargs["x"]: (b, l, d)
        stream = kwargs["x"] if "x" in kwargs else args[0]  # (b, l, d)
        edited = erase(stream.float(), projection.to(stream.device).float(), mean.to(stream.device).float()).to(stream.dtype)  # (b, l, d)
        if "x" in kwargs:
            return args, {**kwargs, "x": edited}  # x: (b, l, d)
        return (edited, *args[1:]), kwargs  # ((b, l, d), ...)

    handle = blocks[block + 1].register_forward_pre_hook(hook, with_kwargs=True)
    try:
        yield
    finally:
        handle.remove()


@torch.no_grad()
def pooled_streams(model: nn.Module, sequences: Sequence[str], blocks: Sequence[int], device: torch.device, *,
                   token_budget: int) -> dict[int, tuple[Tensor, Tensor]]:
    """The stream leaving each listed block, pooled over each protein's residues as its mean and its variance, in
    protein order. A block's stream is read as it enters the next block, after any eraser registered before this
    call, and the last block's as it leaves."""
    layers = transformer_blocks(model)
    lengths = np.array([len(sequence) for sequence in sequences], dtype=np.int64)  # (n,)
    order = np.argsort(lengths, kind="stable")  # (n,)
    current: dict[str, Tensor] = {}
    kept: dict[int, list[tuple[Tensor, Tensor]]] = {block: [] for block in blocks}

    def pool(block: int, stream: Tensor) -> None:
        # stream: (b, l, d)
        mask = current["residues"].unsqueeze(-1).float()  # (b, l, 1)
        count = mask.sum(dim=1)  # (b, 1)
        values = stream.float()  # (b, l, d)
        mean = (values * mask).sum(dim=1) / count  # (b, d)
        variance = ((values - mean.unsqueeze(1)).pow(2) * mask).sum(dim=1) / count  # (b, d)
        kept[block].append((mean.cpu(), variance.cpu()))

    def entering(block: int) -> Callable[..., None]:
        def hook(module: nn.Module, args: tuple[Tensor, ...], kwargs: dict[str, object]) -> None:
            # args: ((b, l, d), ...) when the stream is passed by position, else kwargs["x"]: (b, l, d)
            pool(block, kwargs["x"] if "x" in kwargs else args[0])
        return hook

    def leaving(block: int) -> Callable[..., None]:
        def hook(module: nn.Module, args: tuple[Tensor, ...], output: object) -> None:
            # args: ((b, l, d), ...); output: (b, l, d), or a tuple that leads with it
            pool(block, output[0] if isinstance(output, tuple) else output)
        return hook

    handles = []
    for block in blocks:
        if block + 1 < len(layers):
            handles.append(layers[block + 1].register_forward_pre_hook(entering(block), with_kwargs=True))
        else:
            handles.append(layers[block].register_forward_hook(leaving(block)))
    try:
        for batch in length_batches(lengths[order], token_budget):
            input_ids, attention_mask, residues = encode_batch(model.tokenizer, [sequences[row] for row in order[batch]], device)
            current["residues"] = residues
            model(input_ids=input_ids, attention_mask=attention_mask)
    finally:
        for handle in handles:
            handle.remove()
    back = np.argsort(order)  # (n,)
    return {block: (torch.cat([mean for mean, _ in parts])[back], torch.cat([variance for _, variance in parts])[back])
            for block, parts in kept.items()}  # (n, d) means and (n, d) variances for each block


class Probe(nn.Module):
    """A linear probe, or a one-hidden-layer MLP, on features standardized by the training proteins."""

    def __init__(self, width: int, classes: int, hidden: int | None, center: Tensor, scale: Tensor) -> None:
        # center, scale: (w,)
        super().__init__()
        self.register_buffer("center", center)
        self.register_buffer("scale", scale)
        self.head = nn.Linear(width, classes) if hidden is None else nn.Sequential(nn.Linear(width, hidden), nn.GELU(),
                                                                                   nn.Linear(hidden, classes))

    def forward(self, features: Tensor) -> Tensor:
        # features: (n, w)
        return self.head((features - self.center) / self.scale)  # (n, k)


def train_probe(features: Tensor, labels: Tensor, classes: int, *, hidden: int | None = None, steps: int = STEPS,
                seed: int = SEED, device: str | torch.device = "cpu") -> Probe:
    """A probe fitted by full-batch Adam on a seeded share of the training proteins, kept at the step of its best
    accuracy on the rest."""
    # features: (n, w); labels: (n,)
    generator = torch.Generator().manual_seed(seed)
    order = torch.randperm(len(features), generator=generator)  # (n,)
    held = max(1, int(round(VALIDATION_SHARE * len(features))))
    features, labels = features.float().to(device), labels.long().to(device)
    fit, validation = order[held:].to(device), order[:held].to(device)
    center = features[fit].mean(dim=0)  # (w,)
    scale = features[fit].std(dim=0).clamp(min=1e-6)  # (w,)
    torch.manual_seed(seed)
    probe = Probe(features.shape[1], classes, hidden, center, scale).to(device)
    optimizer = torch.optim.AdamW(probe.parameters(), lr=3e-3, weight_decay=1e-2)
    best, best_state = -1.0, None
    for step in range(steps):
        optimizer.zero_grad()
        functional.cross_entropy(probe(features[fit]), labels[fit]).backward()  # noqa: pytorch-cross-entropy - E15e's recorded readings were fitted with it
        optimizer.step()
        if (step + 1) % 20 == 0:
            with torch.no_grad():
                accuracy = float((probe(features[validation]).argmax(dim=1) == labels[validation]).float().mean())
            if accuracy > best:
                best, best_state = accuracy, {name: value.clone() for name, value in probe.state_dict().items()}
    probe.load_state_dict(best_state)
    return probe.eval()


@torch.no_grad()
def score(probe: Probe, features: Tensor, labels: Tensor, classes: int) -> dict[str, float]:
    """Accuracy and balanced accuracy (the mean recall over the classes present) of a probe."""
    # features: (n, w); labels: (n,)
    device = probe.center.device
    predicted = probe(features.float().to(device)).argmax(dim=1).cpu()  # (n,)
    labels = labels.long().cpu()  # (n,)
    recalls = [float((predicted[labels == label] == label).float().mean()) for label in range(classes) if bool((labels == label).any())]
    return {"accuracy": float((predicted == labels).float().mean()), "balanced_accuracy": float(np.mean(recalls))}


@dataclass
class IntactReaders:
    """The readers of the intact model at one block: the linear probe on its means, kept to be applied after an
    erasure, and each reader's score on test proteins."""

    original: Probe
    scores: dict[str, dict[str, float]]


def intact_readers(means: Tensor, variances: Tensor, labels: Tensor, train: Tensor, test: Tensor, classes: int, *,
                   device: str | torch.device = "cpu") -> IntactReaders:
    """Every reader fitted and scored on the intact model's pooled stream at one block."""
    # means, variances: (n, d); labels: (n,); train: (n_train,) and test: (n_test,) row indices
    original = train_probe(means[train], labels[train], classes, device=device)
    linear = score(original, means[test], labels[test], classes)
    mlp = score(train_probe(means[train], labels[train], classes, hidden=HIDDEN, device=device), means[test], labels[test], classes)
    variance = score(train_probe(variances[train], labels[train], classes, device=device), variances[test], labels[test], classes)
    return IntactReaders(original, {"linear_original": linear, "linear": linear, "mlp": mlp, "linear_variance": variance})


def read_levels(intact: dict[int, IntactReaders], erased: dict[int, tuple[Tensor, Tensor]], labels: Tensor, train: Tensor,
                test: Tensor, classes: int, *, device: str | torch.device = "cpu") -> list[dict[str, object]]:
    """Every reader at every block read after one erasure, beside the same reader on the intact model."""
    # erased: ((n, d) means, (n, d) variances) for each block; labels: (n,); train: (n_train,) and test: (n_test,) rows
    rows = []
    for block, (means, variances) in erased.items():
        readers = {
            "linear_original": (intact[block].original, means),
            "linear": (train_probe(means[train], labels[train], classes, device=device), means),
            "mlp": (train_probe(means[train], labels[train], classes, hidden=HIDDEN, device=device), means),
            "linear_variance": (train_probe(variances[train], labels[train], classes, device=device), variances),
        }
        for name, (probe, features) in readers.items():
            rows.append({"read_block": block, "reader": name, **score(probe, features[test], labels[test], classes),
                         **{f"intact_{metric}": value for metric, value in intact[block].scores[name].items()}})
    return rows


def sample_task(frames: dict[str, pd.DataFrame], *, max_residues: int, seed: int = SEED) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray, int]:
    """A task's proteins for this reading: seeded draws of at most `TRAIN_PROTEINS` training and `TEST_PROTEINS` test
    proteins among those within the residue cap, their class indices, and the rows of each split."""
    generator = np.random.default_rng(seed)
    parts = []
    for split, cap in (("train", TRAIN_PROTEINS), ("test", TEST_PROTEINS)):
        frame = frames[split][frames[split]["sequence"].str.len() <= max_residues]
        parts.append(frame.iloc[np.sort(generator.choice(len(frame), size=min(cap, len(frame)), replace=False))])
    names = sorted(set(parts[0]["label"].tolist()))
    index = {name: position for position, name in enumerate(names)}
    parts[1] = parts[1][parts[1]["label"].isin(index)]  # a test class absent from the drawn training proteins is left out
    sequences = [*parts[0]["sequence"], *parts[1]["sequence"]]
    labels = np.array([index[label] for part in parts for label in part["label"]], dtype=np.int64)  # (n,)
    train = np.arange(len(parts[0]))  # (n_train,)
    return sequences, labels, train, np.arange(len(parts[0]), len(sequences)), len(names)  # labels (n,), train (n_train,), test (n_test,)


def run_erasure_levels(model: nn.Module, name: str, frames: dict[str, pd.DataFrame], device: torch.device, *,
                       erased_blocks: Sequence[int] = ERASED_BLOCKS, token_budget: int, max_residues: int,
                       log: Callable[[str], None] = print) -> pd.DataFrame:
    """One concept: every erased block, read at that block, the blocks `READ_OFFSETS` past it and the last."""
    last = len(transformer_blocks(model)) - 1
    sequences, labels, train, test, classes = sample_task(frames, max_residues=max_residues)
    reads = {block: sorted({min(block + offset, last) for offset in READ_OFFSETS} | {last}) for block in erased_blocks}
    every = sorted({block for blocks in reads.values() for block in blocks})
    clean = pooled_streams(model, sequences, every, device, token_budget=token_budget)
    targets = torch.from_numpy(labels)  # (n,)
    train_rows, test_rows = torch.from_numpy(train), torch.from_numpy(test)
    chance = float(np.bincount(labels[test], minlength=classes).max() / len(test))
    intact = {block: intact_readers(*clean[block], targets, train_rows, test_rows, classes, device=device) for block in every}
    rows = []
    for block in erased_blocks:
        projection, mean = fit_leace(clean[block][0][train_rows], targets[train_rows])
        with stream_eraser(model, block, projection, mean):
            erased = pooled_streams(model, sequences, reads[block], device, token_budget=token_budget)
        found = read_levels(intact, erased, targets, train_rows, test_rows, classes, device=device)
        rows.extend({"task": name, "erased_block": block, **row, "classes": classes, "majority_share": chance,
                     "train_proteins": len(train), "test_proteins": len(test),
                     "rank": int(torch.linalg.matrix_rank(projection))} for row in found)
        log(f"erasure levels {name}, erased at block {block}, read there: " + ", ".join(
            f"{row['reader']} {row['accuracy']:.3f} (intact {row['intact_accuracy']:.3f})"
            for row in found if row["read_block"] == block))
    return pd.DataFrame(rows)
