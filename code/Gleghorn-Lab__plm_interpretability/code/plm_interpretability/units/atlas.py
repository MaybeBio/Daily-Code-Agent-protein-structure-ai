"""The atlas pass: every planned basis of every planned block, sparsified to a reference SAE's firing rates, streamed
once over the atlas set (preregistration, `firing_rate_matching` and `specificity`).

Calibration comes first, over the calibration proteins. A seeded sample of their residues keeps the states the
reference SAEs read, whose codes give each reference's latent rates, then each basis block's states (block groups at a
time, within a memory budget), from which every planned (basis, reference) pair gets thresholds that put its poles at
that reference's rates (`firing_rates.match_firing_rates`). One basis can be planned under several references, as
native poles are at ESMC-600's block 26: under its size-matched SAE for the comparison with it, and under the
16,384-latent SAE every model shares for the comparison across scale.

The pass then streams the train, validation and test proteins once, longest first. For each planned pair it writes each
protein's maximum per pole (the global score) to a memory-mapped array, adds the local sums of training proteins and the
contrast sums of test proteins to its accumulators, and counts each pole's firings on validation residues for the
acceptance check. A checkpoint every `checkpoint_seconds` lets an interrupted pass resume at its last saved batch.

Profiles say which local sums a pair keeps. `selection` keeps the seven sums of the atlas study's frozen selection, in
float64, over terms with at least 10 informative training proteins; `contrast` keeps the paired contrast and the two
occupancy sums, in float32, over terms with at least 50, which the dominant-term rule and its enrichment check read.

Symbols: n proteins of the pass; b proteins of a batch; r residues; w poles of a basis; t local terms; m SAE latents;
f units.
"""

from __future__ import annotations

import hashlib
import json
import time
import numpy as np
import torch

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from torch import Tensor, nn

from foundry.pilot import Pilot
from .accumulate import SUM_KEYS, LocalAccumulator, LocalPairs, LocalRuns, local_pairs, protein_index, protein_maxima
from .bases import Basis, basis_activations, sae_firing_rates
from .capture import DOWN_PROJECTION_INDEX, BlockReader, BlockStates, residue_mask
from .causal import transformer_blocks
from .firing_rates import RateMatch, match_firing_rates, sparsify


CALIBRATION_RESIDUES = 262_144
CALIBRATION_SEED = 24895
TOKEN_BUDGET = 32_768
CHECKPOINT_SECONDS = 900.0
HELD_OUT_KEYS = ("sum_difference",)


@dataclass(frozen=True)
class LocalProfile:
    keys: tuple[str, ...]
    dtype: torch.dtype
    min_informative: int


PROFILES = {
    "selection": LocalProfile(SUM_KEYS, torch.float64, 10),
    "contrast": LocalProfile(("sum_difference", "sum_inside", "sum_outside"), torch.float32, 50),
}
HELD_OUT_MINIMUM = PROFILES["contrast"].min_informative


@dataclass(frozen=True)
class PlannedBasis:
    """A basis, the local sums it keeps, and the SAE whose rates sparsify it (none for an SAE, read as it fires)."""

    basis: Basis
    profile: str
    reference: str | None = None

    def __post_init__(self) -> None:
        if self.profile not in PROFILES:
            raise ValueError(f"Profile {self.profile!r} is not one of {sorted(PROFILES)}.")
        if (self.basis.kind == "sae") != (self.reference is None):
            raise ValueError("Every basis but an SAE is sparsified to a reference SAE's rates; an SAE takes none.")

    @property
    def key(self) -> str:
        return self.basis.name if self.reference is None else f"{self.basis.name}@{self.reference}"

    @property
    def stem(self) -> str:
        """The key as a file name."""
        return self.key.replace("/", "__").replace(":", "-").replace("@", "--")


@dataclass
class PassProteins:
    """The proteins of one pass in pass order, with their split and local runs (1-based inclusive)."""

    accession: list[str]
    sequence: list[str]
    split: np.ndarray  # (n,)
    local: list[LocalRuns]

    def __post_init__(self) -> None:
        if not len(self.accession) == len(self.sequence) == len(self.split) == len(self.local):
            raise ValueError("Every protein of a pass needs its accession, sequence, split and annotations.")

    @property
    def lengths(self) -> np.ndarray:
        return np.array([len(sequence) for sequence in self.sequence], dtype=np.int64)  # (n,)

    def ordered(self) -> PassProteins:
        """Longest first, ties by accession, the order batches and stored rows follow."""
        order = sorted(range(len(self.accession)), key=lambda index: (-len(self.sequence[index]), self.accession[index]))
        return PassProteins([self.accession[i] for i in order], [self.sequence[i] for i in order], self.split[order],
                            [self.local[i] for i in order])


def length_batches(lengths: np.ndarray, token_budget: int = TOKEN_BUDGET) -> list[slice]:
    """Consecutive proteins whose padded batch, each padded to the longest plus BOS and EOS, fits the token budget."""
    # lengths: (n,), in pass order
    batches: list[slice] = []
    start = 0
    while start < len(lengths):
        stop, longest = start, 0
        while stop < len(lengths):
            longest = max(longest, int(lengths[stop]) + 2)
            if (stop - start + 1) * longest > token_budget and stop > start:
                break
            stop += 1
        batches.append(slice(start, stop))
        start = stop
    return batches


def encode_batch(tokenizer: object, sequences: Sequence[str], device: torch.device) -> tuple[Tensor, Tensor, Tensor]:
    """Token ids, attention mask and biological-residue mask of one right-padded batch."""
    encoded = tokenizer(list(sequences), return_tensors="pt", padding=True)  # input_ids, attention_mask: (b, l)
    input_ids = encoded["input_ids"].to(device)  # (b, l)
    attention_mask = encoded["attention_mask"].to(device)  # (b, l)
    lengths = torch.tensor([len(sequence) for sequence in sequences], device=device)  # (b,)
    return input_ids, attention_mask, residue_mask(attention_mask, lengths)  # (b, l) each


def _block_groups(blocks: Sequence[int], bytes_per_block: int, budget: int) -> list[list[int]]:
    per_group = max(1, budget // max(bytes_per_block, 1))
    ordered = sorted(set(blocks))
    return [ordered[start:start + per_group] for start in range(0, len(ordered), per_group)]


def calibration_states(
    model: nn.Module,
    tokenizer: object,
    sequences: Sequence[str],
    blocks: Sequence[int],
    keep: np.ndarray,
    *,
    stream_blocks: Sequence[int] = (),
    write_blocks: Sequence[int] = (),
    token_budget: int = TOKEN_BUDGET,
    device: torch.device,
) -> dict[int, BlockStates]:
    """Each block's states at the kept residues of `sequences`, on the CPU in the model's dtype."""
    # keep: (r_total,) bool over the residues of `sequences`, concatenated in order
    lengths = np.array([len(sequence) for sequence in sequences], dtype=np.int64)  # (n,)
    offsets = np.concatenate(([0], np.cumsum(lengths)))  # (n + 1,)
    if len(keep) != offsets[-1]:
        raise ValueError(f"The residue sample covers {len(keep)} residues, the sequences {offsets[-1]}.")
    parts: dict[int, dict[str, list[Tensor]]] = {}
    current: dict[str, Tensor] = {}

    def keep_states(states: BlockStates) -> None:
        entry = parts.setdefault(states.block, {})
        for name in ("gate", "up", "write", "stream"):
            value = getattr(states, name)
            if value is not None:
                entry.setdefault(name, []).append(value[current["kept"]].cpu())

    with BlockReader(model, blocks, keep_states, write_blocks=write_blocks, stream_blocks=stream_blocks) as reader:
        for batch in length_batches(lengths, token_budget):
            input_ids, attention_mask, residues = encode_batch(tokenizer, sequences[batch], device)
            current["kept"] = torch.from_numpy(keep[offsets[batch.start]:offsets[batch.stop]]).to(device)  # (r,)
            reader.run(input_ids, attention_mask, residues)
    return {block: BlockStates(block=block, **{name: torch.cat(values) for name, values in entry.items()})
            for block, entry in parts.items()}


def residue_sample(total: int, size: int = CALIBRATION_RESIDUES, seed: int = CALIBRATION_SEED) -> np.ndarray:
    """A seeded uniform sample of residue positions, as a mask over all of them."""
    keep = np.zeros(total, dtype=bool)  # (r_total,)
    keep[np.random.default_rng(seed).choice(total, size=min(size, total), replace=False)] = True
    return keep  # (r_total,)


def _reads(bases: Sequence[Basis], group: Sequence[int]) -> dict[str, list[int]]:
    return {"stream_blocks": sorted({basis.block for basis in bases if basis.needs_stream and basis.block in group}),
            "write_blocks": sorted({basis.block for basis in bases if basis.needs_write and basis.block in group})}


def calibrate(
    model: nn.Module,
    tokenizer: object,
    sequences: Sequence[str],
    plan: Sequence[PlannedBasis],
    references: Mapping[str, Basis],
    *,
    rotations: Mapping[int, Tensor],
    saes: Mapping[str, nn.Module],
    device: torch.device,
    memory_budget: int = 64 * 2**30,
    sample_size: int = CALIBRATION_RESIDUES,
    token_budget: int = TOKEN_BUDGET,
    rates: Mapping[str, Tensor] | None = None,
) -> tuple[dict[str, RateMatch], dict[str, Tensor]]:
    """Thresholds for every planned (basis, reference) pair, by key, and each reference SAE's latent rates.

    The references' blocks are read first, in a pass that stops at the deepest of them, unless `rates` gives them (a
    randomly initialized model is matched to the trained model's reference rates); the bases' blocks follow in groups
    whose states fit `memory_budget` bytes on the CPU. Each basis's activations are computed once and matched to every
    reference it is planned under.
    """
    # rotations: (f, f) by seed; rates: (m,) by reference name
    for name, reference in references.items():
        if reference.kind != "sae" or reference.sae != name or (rates is None and name not in saes):
            raise ValueError(f"Reference {name!r} must be an SAE basis of that name whose layer is given.")
    missing = {planned.reference for planned in plan} - set(references) - {None}
    if missing:
        raise ValueError(f"The plan names references {sorted(missing)} that were not given.")
    total = sum(len(sequence) for sequence in sequences)
    keep = residue_sample(total, sample_size)  # (r_total,)
    if rates is None:
        reference_blocks = sorted({reference.block for reference in references.values()})
        states = calibration_states(model, tokenizer, sequences, reference_blocks, keep, token_budget=token_budget,
                                    device=device, **_reads(list(references.values()), reference_blocks))
        measured = {name: sae_firing_rates(reference, _to(states[reference.block], device), saes[name])
                    for name, reference in references.items()}  # each (m,)
        del states
        rates = measured
    elif set(rates) != set(references):
        raise ValueError(f"Given rates for {sorted(rates)}, but the references are {sorted(references)}.")
    rates = {name: values.to(device) for name, values in rates.items()}  # each (m,)
    bytes_per_block = int(keep.sum()) * (4 * transformer_units(model) + 4 * model.config.hidden_size)  # BF16 states
    planned_by_basis: dict[Basis, list[PlannedBasis]] = {}
    for planned in plan:
        if planned.reference is not None:
            planned_by_basis.setdefault(planned.basis, []).append(planned)
    bases = list(planned_by_basis)
    matches: dict[str, RateMatch] = {}
    for group in _block_groups(sorted({basis.block for basis in bases}), bytes_per_block, memory_budget):
        states = calibration_states(model, tokenizer, sequences, group, keep, token_budget=token_budget, device=device,
                                    **_reads(bases, group))
        for block in group:
            block_states = _to(states.pop(block), device)
            for basis in (basis for basis in bases if basis.block == block):
                activations = basis_activations(basis, block_states, rotation=_rotation(basis, rotations))  # (r, w)
                for planned in planned_by_basis[basis]:
                    matches[planned.key] = match_firing_rates(activations, rates[planned.reference])
                del activations
            del block_states
    return matches, {name: values.cpu() for name, values in rates.items()}  # key -> match; name -> (m,)


def _rotation(basis: Basis, rotations: Mapping[int, Tensor]) -> Tensor | None:
    # rotations: (f, f) by seed
    if basis.kind != "rotation":
        return None  # (f, f) only for rotation bases
    if basis.seed not in rotations:
        raise ValueError(f"{basis.name} needs the rotation of seed {basis.seed}.")
    return rotations[basis.seed]  # (f, f)


def transformer_units(model: nn.Module) -> int:
    """SwiGLU width f of an ESM++ model."""
    return int(transformer_blocks(model)[0].ffn[DOWN_PROJECTION_INDEX].in_features)


def _to(states: BlockStates, device: torch.device) -> BlockStates:
    def move(value: Tensor | None) -> Tensor | None:
        # value: (r, w) or absent
        return None if value is None else value.to(device)  # (r, w)
    return BlockStates(block=states.block, gate=move(states.gate), up=move(states.up), write=move(states.write),
                       stream=move(states.stream))


def plan_digest(plan: Sequence[PlannedBasis], proteins: PassProteins, token_budget: int) -> str:
    """Identity of a pass: its planned pairs, protein order and batching; a resumed pass must match it exactly."""
    hashed = hashlib.sha256()
    for planned in plan:
        hashed.update(f"{planned.basis!r}|{planned.profile}|{planned.reference}\n".encode())
    for accession, split in zip(proteins.accession, proteins.split, strict=True):
        hashed.update(f"{accession}\t{split}\n".encode())
    hashed.update(f"budget={token_budget}".encode())
    return hashed.hexdigest()


@dataclass
class AtlasPass:
    """One streamed pass of the atlas set through a model, writing each planned pair's scores under `output`."""

    model: nn.Module
    tokenizer: object
    plan: Sequence[PlannedBasis]
    proteins: PassProteins  # in pass order
    term_columns: Mapping[int, Mapping[int, int]]  # minimum informative count -> token -> column
    thresholds: Mapping[str, Tensor]  # planned key -> (w,)
    widths: Mapping[str, int]  # basis name -> w
    output: Path
    device: torch.device
    rotations: Mapping[int, Tensor] = field(default_factory=dict)
    saes: Mapping[str, nn.Module] = field(default_factory=dict)
    scopes: Mapping[int, int] = field(default_factory=dict)  # local token -> the amino acid it is scored on
    token_budget: int = TOKEN_BUDGET
    checkpoint_seconds: float = CHECKPOINT_SECONDS
    log: Callable[[str], None] = print

    def __post_init__(self) -> None:
        keys = [planned.key for planned in self.plan]
        if len(set(keys)) != len(keys):
            raise ValueError("A basis appears twice under one reference in the plan.")
        for planned in self.plan:
            if planned.reference is not None and planned.key not in self.thresholds:
                raise ValueError(f"{planned.key} has no calibrated thresholds.")
        self.thresholds = {key: values.to(self.device) for key, values in self.thresholds.items()}  # each (w,)
        self.batches = length_batches(self.proteins.lengths, self.token_budget)
        self.digest = plan_digest(self.plan, self.proteins, self.token_budget)
        self.by_block: dict[int, dict[Basis, list[PlannedBasis]]] = {}
        for planned in self.plan:
            self.by_block.setdefault(planned.basis.block, {}).setdefault(planned.basis, []).append(planned)
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / "maxima").mkdir(exist_ok=True)
        n = len(self.proteins.accession)
        self.maxima: dict[str, np.memmap] = {}
        self.train: dict[str, LocalAccumulator] = {}
        self.test: dict[str, LocalAccumulator] = {}
        self.validation_counts: dict[str, Tensor] = {}
        mode = "r+" if (self.output / "progress.json").exists() else "w+"
        for planned in self.plan:
            profile, width = PROFILES[planned.profile], int(self.widths[planned.basis.name])
            path = self.output / "maxima" / f"{planned.stem}.npy"
            self.maxima[planned.key] = np.lib.format.open_memmap(path, mode=mode, dtype=np.float32, shape=(n, width))
            self.train[planned.key] = LocalAccumulator(len(self.term_columns[profile.min_informative]), width, self.device,
                                                       profile.dtype, keys=profile.keys)
            self.test[planned.key] = LocalAccumulator(len(self.term_columns[HELD_OUT_MINIMUM]), width, self.device,
                                                      torch.float32, keys=HELD_OUT_KEYS)
            self.validation_counts[planned.key] = torch.zeros(width, dtype=torch.long, device=self.device)  # (w,)
        self.validation_residues = 0
        self.done = 0
        self._current: dict[object, object] = {}

    def _pairs(self, rows: slice, split: str, minimum: int) -> LocalPairs:
        empty = LocalRuns.positives([], [], [])
        annotations = [local if label == split else empty
                       for local, label in zip(self.proteins.local[rows], self.proteins.split[rows], strict=True)]
        return local_pairs(self.proteins.sequence[rows], annotations, self.term_columns[minimum], self.scopes)

    def _consume(self, states: BlockStates) -> None:
        rows, owner, validation = self._current["rows"], self._current["owner"], self._current["validation"]
        n_batch = rows.stop - rows.start
        for basis, entries in self.by_block.get(states.block, {}).items():
            activations = basis_activations(basis, states, rotation=_rotation(basis, self.rotations),
                                            sae=self.saes.get(basis.sae or ""))  # (r, w)
            for planned in entries:
                key = planned.key
                sparse = activations if planned.reference is None else sparsify(activations, self.thresholds[key])  # (r, w)
                self.maxima[key][rows] = protein_maxima(sparse, owner, n_batch).cpu().numpy()  # (b, w)
                minimum = PROFILES[planned.profile].min_informative
                self.train[key].update(sparse, owner, self._current[("train", minimum)], n_batch)
                self.test[key].update(sparse, owner, self._current[("test", HELD_OUT_MINIMUM)], n_batch)
                self.validation_counts[key] += ((sparse > 0) & validation.unsqueeze(1)).sum(dim=0)  # (w,)
                del sparse
            del activations

    def save(self) -> None:
        """Flush the maxima and write the accumulators and counts, then the progress record, atomically."""
        state_dir = self.output / "state"
        state_dir.mkdir(exist_ok=True)
        for array in self.maxima.values():
            array.flush()
        for planned in self.plan:
            key, path = planned.key, state_dir / f"{planned.stem}.pt"
            torch.save({"train": self.train[key].state_dict(), "test": self.test[key].state_dict(),
                        "validation_counts": self.validation_counts[key].cpu()}, path.with_suffix(".tmp"))
            path.with_suffix(".tmp").replace(path)
        progress = {"digest": self.digest, "batches_done": self.done, "batches": len(self.batches),
                    "validation_residues": self.validation_residues}
        (self.output / "progress.json.tmp").write_text(json.dumps(progress, indent=2), encoding="utf-8")
        (self.output / "progress.json.tmp").replace(self.output / "progress.json")

    def resume(self) -> None:
        """Load a saved pass of the same plan; refuses one of another plan."""
        progress = json.loads((self.output / "progress.json").read_text(encoding="utf-8"))
        if progress["digest"] != self.digest:
            raise ValueError("The saved pass belongs to another plan, protein order or batching.")
        for planned in self.plan:
            saved = torch.load(self.output / "state" / f"{planned.stem}.pt", weights_only=True)
            self.train[planned.key].load_state_dict(saved["train"])
            self.test[planned.key].load_state_dict(saved["test"])
            self.validation_counts[planned.key].copy_(saved["validation_counts"])
        self.done, self.validation_residues = int(progress["batches_done"]), int(progress["validation_residues"])
        self.log(f"resumed at batch {self.done} of {len(self.batches)}")

    def run(self, pilot: Pilot | None = None) -> dict[str, object]:
        """Stream every remaining batch, or under a `foundry.pilot.Pilot` only its window; returns timing and throughput.

        A pilot's batches are the pass's own, longest first, so its projection errs long.
        """
        if (self.output / "progress.json").exists():
            self.resume()
        started = last_save = time.time()
        residues_done = 0
        bases = [planned.basis for planned in self.plan]
        minima = sorted({PROFILES[planned.profile].min_informative for planned in self.plan})
        # TODO(atlas_pass_overlap): the e2 pilot (2026-11-06) ran kernels 86% of the time at 2.59 s a step with 1.2 of 64
        # cores busy; the next batch's local pairs are built, and each pair's maxima copied to its memmap, while the GPU waits.
        with BlockReader(self.model, sorted(self.by_block), self._consume, **_reads(bases, sorted(self.by_block))) as reader:
            indices = range(self.done, len(self.batches))
            for index in pilot.watch(indices) if pilot is not None else indices:
                rows = self.batches[index]
                sequences = self.proteins.sequence[rows]
                lengths = [len(sequence) for sequence in sequences]
                input_ids, attention_mask, residues = encode_batch(self.tokenizer, sequences, self.device)
                is_validation = np.repeat(self.proteins.split[rows] == "validation", lengths)  # (r,)
                self._current = {"rows": rows, "owner": protein_index(lengths, self.device),
                                 "validation": torch.from_numpy(is_validation).to(self.device)}
                for minimum in minima:
                    self._current[("train", minimum)] = self._pairs(rows, "train", minimum)
                self._current[("test", HELD_OUT_MINIMUM)] = self._pairs(rows, "test", HELD_OUT_MINIMUM)
                reader.run(input_ids, attention_mask, residues)
                self.validation_residues += int(is_validation.sum())
                residues_done += sum(lengths)
                self.done = index + 1
                if time.time() - last_save >= self.checkpoint_seconds:
                    self.save()
                    last_save = time.time()
                    self.log(f"batch {self.done}/{len(self.batches)}, {residues_done / (last_save - started):,.0f} residues/s")
        self.save()
        elapsed = time.time() - started
        return {"batches": len(self.batches), "seconds": elapsed, "residues": residues_done,
                "residues_per_second": residues_done / max(elapsed, 1e-9)}

    def validation_rates(self) -> dict[str, Tensor]:
        """Each planned pair's firing rates over validation residues, by key, the acceptance check's input."""
        if self.validation_residues == 0:
            raise ValueError("The pass held no validation residues.")
        return {key: counts.double().cpu() / self.validation_residues for key, counts in self.validation_counts.items()}  # (w,)
