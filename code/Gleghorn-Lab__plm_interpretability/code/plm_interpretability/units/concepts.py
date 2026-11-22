"""The concept extraction behind E6, E9, E10 and E11: version one's concept datasets, pooled per protein at fixed blocks.

Version one's concept datasets (`GleghornLab/protein_concept_probing`, pinned in the preregistration) hold, per task,
train, validation and test parquet files of id, sequence and label, with the task's level and type in `metadata.json`.
These experiments read the protein-level tasks; residue-level concepts are the atlas's local terms (E2, E3). Each distinct
sequence, cut at the models' residue cap, runs once through the model up to its deepest needed block. At each depth
block the units' products z are pooled over the protein's residues (mean, maximum and minimum), beside the mean gate, the
mean of each native pole and the mean output stream. Mean pooling commutes with a rotation, so rotated means need no
pass; maxima and minima do not, so at the rotation block they are also kept for z under each rotation seed. An SAE's
latents are max-pooled at its block, and with `all_blocks` every block up to the deepest keeps its mean z, which E9's
exact decomposition of a stream probe reads. Features go to float32 memory-mapped arrays, one per (block, feature), with
rows in the order of `ConceptProteins.sequences`; an interrupted extraction resumes at its last saved batch.

Symbols: n proteins; b proteins of a batch; r residues; f units; d model width; c SAE codebook.
"""

from __future__ import annotations

import json
import time
import numpy as np
import pandas as pd
import torch

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from torch import Tensor, nn

from foundry.embedding import encode_topk
from foundry.pilot import Pilot
from .accumulate import protein_index
from .atlas import TOKEN_BUDGET, encode_batch, length_batches, transformer_units
from .capture import BlockReader, BlockStates
from .poles import swiglu_poles
from .rotations import haar_rotation, rotate


SPLITS = ("train", "validation", "test")
MAX_RESIDUES = 2046
DEPTHS = {"esmc_600": (8, 17, 26, 35), "esmc_6b": (19, 39, 59, 79)}  # a quarter, half, three quarters and all of each model
UNIT_FEATURES = ("z_mean", "z_max", "z_min", "gate_mean")
SAVE_SECONDS = 900.0


@dataclass(frozen=True)
class ConceptTask:
    name: str
    level: str  # "protein" or "residue"
    kind: str  # "regression", "binary", "multiclass" or "multilabel"
    label_names: tuple[str, ...]
    frames: dict[str, pd.DataFrame]  # split -> id, sequence, label


def load_tasks(root: Path, *, level: str = "protein") -> dict[str, ConceptTask]:
    """Every task at `level` in a downloaded copy of the concept datasets, by name."""
    tasks = {}
    for path in sorted(root.glob("*/metadata.json")):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata["task_level"] != level:
            continue
        frames = {split: pd.read_parquet(path.parent / f"{split}.parquet") for split in SPLITS}
        tasks[metadata["config"]] = ConceptTask(metadata["config"], metadata["task_level"], metadata["task_type"],
                                                tuple(metadata["label_names"]), frames)
    if not tasks:
        raise ValueError(f"No {level}-level task was found under {root}.")
    return tasks


@dataclass(frozen=True)
class ConceptProteins:
    sequences: list[str]  # the distinct sequences, cut at the residue cap, sorted
    rows: dict[str, dict[str, np.ndarray]]  # task -> split -> each example's row in `sequences`


def concept_proteins(tasks: Mapping[str, ConceptTask], *, max_residues: int = MAX_RESIDUES) -> ConceptProteins:
    """Each distinct (cut) sequence of the tasks once, and where each example's sequence sits among them."""
    cut = {name: {split: frame["sequence"].str.slice(0, max_residues) for split, frame in task.frames.items()}
           for name, task in tasks.items()}
    sequences = sorted({sequence for splits in cut.values() for column in splits.values() for sequence in column})
    position = {sequence: row for row, sequence in enumerate(sequences)}
    rows = {name: {split: column.map(position).to_numpy(dtype=np.int64) for split, column in splits.items()}
            for name, splits in cut.items()}
    return ConceptProteins(sequences, rows)


@dataclass(frozen=True)
class ExtractionPlan:
    depths: tuple[int, ...]
    rotation_block: int | None = None  # the depth block whose rotated maxima and minima are kept
    rotation_seeds: tuple[int, ...] = ()
    sae: str | None = None  # the SAE whose latents are max-pooled
    sae_block: int | None = None  # the block whose output stream it reads
    all_blocks: bool = False  # every block's mean z up to the deepest depth, for E9

    def __post_init__(self) -> None:
        if (self.sae is None) != (self.sae_block is None):
            raise ValueError("An SAE needs its block, and a block needs its SAE.")
        if self.sae_block is not None and self.sae_block not in self.depths:
            raise ValueError("The SAE must read the output stream of a depth block, where it is captured.")
        if (self.rotation_block is None) != (not self.rotation_seeds):
            raise ValueError("Rotated extremes need both a block and seeds.")
        if self.rotation_block is not None and self.rotation_block not in self.depths:
            raise ValueError("The rotation block must be a depth block.")

    @property
    def blocks(self) -> tuple[int, ...]:
        return tuple(range(max(self.depths) + 1)) if self.all_blocks else tuple(sorted(self.depths))


def feature_widths(plan: ExtractionPlan, units: int, width: int, codebook: int | None = None) -> dict[tuple[int, str], int]:
    """Every stored array of a plan, by (block, feature), with its number of columns."""
    widths: dict[tuple[int, str], int] = {}
    for block in plan.depths:
        widths.update({(block, name): units for name in UNIT_FEATURES})
        widths[(block, "poles_mean")] = 2 * units
        widths[(block, "stream_mean")] = width
    for seed in plan.rotation_seeds:
        widths.update({(plan.rotation_block, f"rotation{seed}_{statistic}"): units for statistic in ("max", "min")})
    if plan.all_blocks:
        for block in plan.blocks:
            widths.setdefault((block, "z_mean"), units)
    if plan.sae_block is not None:
        if codebook is None:
            raise ValueError("Max-pooled SAE latents need the codebook size.")
        widths[(plan.sae_block, "sae_max")] = codebook
    return widths


def pooled(values: Tensor, owner: Tensor, n_proteins: int, statistics: tuple[str, ...] = ("mean", "max", "min")) -> dict[str, Tensor]:
    """Each protein's mean, maximum or minimum (those in `statistics`) of every column over its residues."""
    # values: (r, w); owner: (r,), every protein owning at least one residue
    values = values.float()  # (r, w)
    empty = values.new_zeros((n_proteins, values.shape[1]))  # (n, w)
    per_protein = {}
    if "mean" in statistics:
        counts = torch.bincount(owner, minlength=n_proteins).unsqueeze(1).float()  # (n, 1)
        per_protein["mean"] = empty.index_add(0, owner, values) / counts  # (n, w)
    for statistic in ("max", "min"):
        if statistic in statistics:
            index = owner.unsqueeze(1).expand_as(values)  # (r, w)
            per_protein[statistic] = empty.scatter_reduce(0, index, values, reduce=f"a{statistic}", include_self=False)  # (n, w)
    return per_protein  # (n, w) each


def max_pooled_codes(indices: Tensor, values: Tensor, owner: Tensor, n_proteins: int, codebook: int) -> Tensor:
    """Each protein's maximum of every SAE latent over its residues, from TopK codes (absent latents count as zero)."""
    # indices, values: (r, k); owner: (r,)
    flat = (owner.unsqueeze(1) * codebook + indices).reshape(-1)  # (r k,)
    maxima = values.new_zeros(n_proteins * codebook, dtype=torch.float32)  # (n c,)
    maxima.scatter_reduce_(0, flat, values.reshape(-1).float(), reduce="amax", include_self=True)
    return maxima.view(n_proteins, codebook)  # (n, c)


class ConceptExtraction:
    """One model's pooled features over the concept proteins, written batch by batch to memory-mapped arrays."""

    def __init__(
        self,
        model: nn.Module,
        plan: ExtractionPlan,
        sequences: list[str],
        output: Path,
        device: torch.device,
        *,
        sae: nn.Module | None = None,
        token_budget: int = TOKEN_BUDGET,
        save_seconds: float = SAVE_SECONDS,
        log: Callable[[str], None] = print,
    ) -> None:
        if (sae is None) != (plan.sae is None):
            raise ValueError("Pass the SAE layer exactly when the plan names one.")
        self.model, self.plan, self.output, self.device, self.sae, self.log = model, plan, output, device, sae, log
        self.save_seconds = save_seconds
        self.units, self.width = transformer_units(model), model.config.hidden_size
        self.codebook = int(sae.params.codebook_dim) if sae is not None else None
        self.rotations = {seed: haar_rotation(self.units, seed, dtype=torch.float32, device=device)  # (f, f) each
                          for seed in plan.rotation_seeds}
        self.sequences = sequences
        order = sorted(range(len(sequences)), key=lambda row: (-len(sequences[row]), sequences[row]))
        self.order = np.array(order, dtype=np.int64)  # (n,), batch order: longest first
        self.batches = length_batches(np.array([len(sequences[row]) for row in order], dtype=np.int64), token_budget)
        self.widths = feature_widths(plan, self.units, self.width, self.codebook)
        (output / "features").mkdir(parents=True, exist_ok=True)
        self.arrays = {key: self._array(key, columns) for key, columns in self.widths.items()}
        self.done = 0
        progress = output / "progress.json"
        if progress.exists():
            saved = json.loads(progress.read_text(encoding="utf-8"))
            if saved["proteins"] != len(sequences) or saved["batches"] != len(self.batches):
                raise ValueError(f"{progress} belongs to a different extraction.")
            self.done = int(saved["done"])
        self._rows: np.ndarray | None = None
        self._owner: Tensor | None = None

    def _array(self, key: tuple[int, str], columns: int) -> np.memmap:
        path = self.output / "features" / f"block{key[0]}_{key[1]}.npy"
        if path.exists():
            array = np.load(path, mmap_mode="r+")
            if array.shape != (len(self.sequences), columns):
                raise ValueError(f"{path} has shape {array.shape}, not {(len(self.sequences), columns)}.")
            return array
        return np.lib.format.open_memmap(path, mode="w+", dtype=np.float32, shape=(len(self.sequences), columns))

    def _write(self, block: int, name: str, values: Tensor) -> None:
        # values: (b, w)
        self.arrays[(block, name)][self._rows] = values.cpu().numpy()

    def _consume(self, states: BlockStates) -> None:
        owner, count = self._owner, len(self._rows)
        product = states.product()  # (r, f)
        if states.block not in self.plan.depths:
            self._write(states.block, "z_mean", pooled(product, owner, count, ("mean",))["mean"])
            return
        for statistic, per_protein in pooled(product, owner, count).items():  # (b, f) each
            self._write(states.block, f"z_{statistic}", per_protein)
        means = {"gate_mean": states.gate, "poles_mean": swiglu_poles(states.gate, states.up).main(),
                 "stream_mean": states.stream}  # (r, f), (r, 2f), (r, d)
        for name, values in means.items():
            self._write(states.block, name, pooled(values, owner, count, ("mean",))["mean"])
        if states.block == self.plan.rotation_block:
            for seed, rotation in self.rotations.items():
                extremes = pooled(rotate(product, rotation), owner, count, ("max", "min"))  # (b, f) each
                for statistic, per_protein in extremes.items():
                    self._write(states.block, f"rotation{seed}_{statistic}", per_protein)
        if states.block == self.plan.sae_block:
            codes = encode_topk(states.stream, self.sae)  # (r, k) each
            self._write(states.block, "sae_max", max_pooled_codes(codes.indices, codes.values, owner, count, self.codebook))

    def save(self) -> None:
        for array in self.arrays.values():
            array.flush()
        progress = {"proteins": len(self.sequences), "batches": len(self.batches), "done": self.done}
        (self.output / "progress.json").write_text(json.dumps(progress), encoding="utf-8")

    def run(self, pilot: Pilot | None = None) -> dict[str, object]:
        """Stream every remaining batch, or under a pilot only its window; returns timing and throughput."""
        started = last_save = time.time()
        residues_done = 0
        tokenizer = self.model.tokenizer
        with BlockReader(self.model, self.plan.blocks, self._consume, stream_blocks=self.plan.depths) as reader:
            indices = range(self.done, len(self.batches))
            for index in pilot.watch(indices) if pilot is not None else indices:
                self._rows = self.order[self.batches[index]]  # (b,)
                sequences = [self.sequences[row] for row in self._rows]
                lengths = [len(sequence) for sequence in sequences]
                self._owner = protein_index(lengths, self.device)  # (r,)
                input_ids, attention_mask, residues = encode_batch(tokenizer, sequences, self.device)  # (b, l) each
                reader.run(input_ids, attention_mask, residues)
                residues_done += sum(lengths)
                self.done = index + 1
                if time.time() - last_save >= self.save_seconds:
                    self.save()
                    last_save = time.time()
                    self.log(f"batch {self.done}/{len(self.batches)}, {residues_done / (last_save - started):,.0f} residues/s")
        self.save()
        elapsed = time.time() - started
        return {"batches": len(self.batches), "done": self.done, "complete": self.done == len(self.batches),
                "seconds": elapsed, "residues": residues_done, "residues_per_second": residues_done / max(elapsed, 1e-9)}


def read_feature(output: Path, block: int, name: str) -> np.ndarray:
    """One stored feature array, (n, w), memory-mapped read-only."""
    return np.load(output / "features" / f"block{block}_{name}.npy", mmap_mode="r")  # (n, w)
