"""E15c, exploratory: neuron communities in ESMC, after Shilov and colleagues (Goodfire, November 2026).

A prompt is one masked residue of a protein whose residues are masked at the training share (`MASK_SHARE`), read at
the masked token's own position, the counterpart of a language model's final token.

1. Attribution (`attribute`, `run_attribution`). For a prompt x with top prediction y, unit j of a block scores
   a_j = |z_j * d log p(y | x) / d z_j| at the prompt's position, z the SwiGLU's output; each block keeps its `TOP_K`
   units. One backward pass of the summed log probabilities of a batch's prompts gives every prompt's scores, exact
   across proteins and approximate within one, where a unit at one masked position also moves the prediction at
   another; `summed_against_single` measures that on one prompt a protein, and the launch record holds the rule.
2. Graph (`cooccurrence_edges`). Units are nodes; a pair's count is the number of prompts that keep both, and its
   z-score sets that count against independence given the two units' own counts. Pairs at or above `MIN_COUNT` and
   `MIN_Z` are edges weighted by z. Units kept on more than `ALWAYS_ON_SHARE` of prompts are set aside as always on.
3. Discovery (`leiden_communities`). Leiden under the Constant Potts Model at each of `RESOLUTIONS`; communities of 2
   to `MAX_SIZE` units are pooled over the resolutions.
4. Tests on held-out prompts (`run_tests`), each an intervention at the prompt's position, read as the KL
   divergence from the clean distribution: community necessity (the community's units in a span of blocks set to
   zero), sufficiency (every unit of the span's blocks set to zero but the community's and the always-on units), and
   layer necessity (every unit of the span's blocks but the always-on units). A community explains a prompt within a
   span when necessity and layer necessity reach `NECESSITY` and sufficiency stays at or under `SUFFICIENCY`.

Departures from that report, fixed before the run for a budget of eight GPU hours: a prompt tests its `CANDIDATES`
communities that share the most units with its attributed set, not every community that shares one; each community
is tested on its whole span of blocks, its two halves and its four quarters (`subspans`), not on every subspan; and
`RESOLUTIONS` reaches lower than the report's 32, since a z-score grows with the square root of the prompt count and
this run reads fewer prompts.

Symbols: b proteins of a batch; l token columns; s prompts; n blocks; f units a block; k units kept a block; v tokens
of the vocabulary; c communities; e edges.
"""

from __future__ import annotations

import multiprocessing
import time
import numpy as np
import pandas as pd
import scipy.sparse as sp
import torch

from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from torch import Tensor, nn
from torch.nn import functional

from foundry.pilot import Pilot
from .atlas import encode_batch, length_batches
from .capture import DOWN_PROJECTION_INDEX
from .causal import SWIGLU_INDEX, split_projection, transformer_blocks


TOP_K = 5
MASK_SHARE = 0.15
MIN_COUNT = 5
MIN_Z = 8.0
ALWAYS_ON_SHARE = 0.2
MAX_SIZE = 128
RESOLUTIONS = (8.0, 16.0, 32.0, 64.0, 128.0, 256.0, 512.0, 1024.0)
NECESSITY = 0.7
SUFFICIENCY = 0.2
CANDIDATES = 2
SPAN_SIZES = (1, 4, 12)  # coverage is reported for spans of at least this many blocks
SEED = 24895
PART_PROTEINS = 1_024
QUADRANTS = ("gate open, up positive", "gate open, up negative", "gate closed, up negative", "gate closed, up positive")
SCORES = ("attribution", "activation")  # what ranks a prompt's units: |z times the gradient|, or |z| alone


def prompt_residues(length: int, protein: int, *, share: float = MASK_SHARE, seed: int = SEED) -> np.ndarray:
    """The 0-based residues of one protein that are masked, and so its prompts: a seeded share of them, at least one,
    drawn from the protein's own stream so that any stage draws the same residues for it."""
    generator = np.random.default_rng([seed, protein])
    return np.sort(generator.choice(length, size=max(1, int(round(share * length))), replace=False))  # (s_protein,)


def prompt_order(count: int, protein: int, seed: int = SEED) -> np.ndarray:
    """A seeded order of one protein's prompts, in which passes that differentiate one prompt a protein take them."""
    return np.random.default_rng([seed, protein, 1]).permutation(count)  # (count,)


def position_mask(residues: Sequence[np.ndarray], shape: tuple[int, int]) -> Tensor:
    """A (b, l) mask of each protein's given 0-based residues, shifted past the BOS token."""
    # residues: (r_protein,) for each of b proteins
    mask = torch.zeros(shape, dtype=torch.bool)  # (b, l)
    for row, chosen in enumerate(residues):
        mask[row, torch.from_numpy(np.asarray(chosen, dtype=np.int64) + 1)] = True
    return mask  # (b, l)


@dataclass(frozen=True)
class BatchAttribution:
    """The attributed units of a batch's prompts, in row-major order of the prompts' positions."""

    indices: Tensor  # (s, n, k) the kept units of each block, by falling score
    scores: Tensor  # (s, n, k) their scores
    quadrants: Tensor  # (s, n, k) each kept unit's quadrant at the prompt, an index of `QUADRANTS`
    quadrant_counts: Tensor  # (n, 4) every unit's quadrant at the prompts, counted
    predicted: Tensor  # (s,) the top predicted token
    log_prob: Tensor  # (s,) its log probability


def attribute(model: nn.Module, input_ids: Tensor, attention_mask: Tensor, positions: Tensor, mask_token_id: int, *,
              targets: Tensor | None = None, top: int = TOP_K, by: str = "attribution") -> BatchAttribution:
    """Every prompt's attributed units from one forward and one backward pass. `targets`, a subset of `positions`,
    limits the differentiated log probabilities to those prompts; the scores are still read at every prompt. With
    `by="activation"` a unit scores its absolute activation, |z_j|, from the forward pass alone."""
    # input_ids, attention_mask, positions, targets: (b, l)
    assert by in SCORES, by
    differentiate = by == "attribution"
    products: list[Tensor] = []
    projections: list[Tensor] = []

    def hook(module: nn.Module, args: tuple[Tensor, ...], output: Tensor) -> None:
        # args: ((b, l, 2f),); output: (b, l, f), kept with its gradient when the scores need one
        if differentiate and output.requires_grad:
            output.retain_grad()
        elif differentiate:
            output.requires_grad_(True)
        products.append(output)
        projections.append(args[0].detach())

    handles = [block.ffn[SWIGLU_INDEX].register_forward_hook(hook) for block in transformer_blocks(model)]
    try:
        with torch.enable_grad() if differentiate else torch.no_grad():
            masked = input_ids.masked_fill(positions, mask_token_id)  # (b, l)
            logits = model(input_ids=masked, attention_mask=attention_mask).logits.float()  # (b, l, v)
            log_probs = functional.log_softmax(logits, dim=-1)  # (b, l, v)
            best, predicted = log_probs.max(dim=-1)  # (b, l), (b, l)
            if differentiate:
                best[positions if targets is None else targets].sum().backward()
    finally:
        for handle in handles:
            handle.remove()
    indices, scores, quadrants, counts = [], [], [], []
    for product, projection in zip(products, projections, strict=True):
        score = product.detach()[positions].float()  # (s, f)
        score = (score * product.grad[positions].float()).abs() if differentiate else score.abs()  # (s, f)
        kept = score.topk(top, dim=1)  # values and indices (s, k)
        gate, up = split_projection(projection[positions])  # (s, f), (s, f)
        quadrant = torch.where(gate > 0, torch.where(up > 0, 0, 1), torch.where(up < 0, 2, 3))  # (s, f)
        indices.append(kept.indices)
        scores.append(kept.values)
        quadrants.append(quadrant.gather(1, kept.indices))
        counts.append(torch.bincount(quadrant.flatten(), minlength=4))
        product.grad = None
    return BatchAttribution(torch.stack(indices, dim=1).cpu(), torch.stack(scores, dim=1).cpu(),
                            torch.stack(quadrants, dim=1).cpu(), torch.stack(counts).cpu(),
                            predicted[positions].detach().cpu(), best[positions].detach().cpu())


def set_overlap(first: Tensor, second: Tensor) -> Tensor:
    """The Jaccard index of two sets of kept units, row by row."""
    # first, second: (..., k) distinct units a row
    shared = (first.unsqueeze(-1) == second.unsqueeze(-2)).any(dim=-1).sum(dim=-1).double()  # (...)
    return shared / (first.shape[-1] + second.shape[-1] - shared)  # (...)


def summed_against_single(model: nn.Module, sequences: Sequence[str], proteins: Sequence[int], device: torch.device) -> float:
    """The mean Jaccard index, over one prompt a protein and every block, between the units kept when a batch's prompts
    are differentiated together and when that prompt is differentiated alone."""
    tokenizer = model.tokenizer
    input_ids, attention_mask, _ = encode_batch(tokenizer, sequences, device)  # (b, l) each
    residues = [prompt_residues(len(sequence), protein) for sequence, protein in zip(sequences, proteins, strict=True)]
    positions = position_mask(residues, tuple(input_ids.shape)).to(device)  # (b, l)
    targets = position_mask([chosen[:1] for chosen in residues], tuple(input_ids.shape)).to(device)  # (b, l)
    together = attribute(model, input_ids, attention_mask, positions, tokenizer.mask_token_id)
    alone = attribute(model, input_ids, attention_mask, positions, tokenizer.mask_token_id, targets=targets)
    chosen = targets[positions].cpu()  # (s,)
    return float(set_overlap(together.indices[chosen], alone.indices[chosen]).mean())


def run_attribution(model: nn.Module, sequences: Sequence[str], proteins: np.ndarray, device: torch.device, output: Path, *,
                    token_budget: int, budget_seconds: float, part_proteins: int = PART_PROTEINS,
                    target: int | None = None, pilot: Pilot | None = None, by: str = "attribution", parts: int | None = None,
                    log: Callable[[str], None] = print) -> dict[str, object]:
    """Attribute the prompts of `proteins` (rows of `sequences`, in the order given), one file a part of
    `part_proteins` proteins, skipping parts already written and stopping before a part once `budget_seconds` have
    passed or `parts` parts are behind. A pass cut short therefore holds the prompts of a prefix of `proteins`. With
    `target`, one prompt of each protein alone is differentiated and kept, the exact attribution: the prompt at that
    place of the protein's seeded order (`prompt_order`), and none for a protein with fewer prompts. A pilot watches
    the batches of the first part and ends it early. `by` is `attribute`'s score; a pass by activation with the same
    proteins, token budget, target and parts keeps the same prompts in the same rows as the pass by attribution."""
    # proteins: (p,) rows of `sequences`
    output.mkdir(parents=True, exist_ok=True)
    tokenizer = model.tokenizer
    started = time.perf_counter()
    written, prompts = 0, 0
    for part, start in enumerate(range(0, len(proteins), part_proteins)):
        path = output / f"part_{part:05d}.npz"
        if parts is not None and part >= parts:
            break
        if path.exists():
            written += 1
            continue
        if time.perf_counter() - started > budget_seconds:
            break
        rows = proteins[start:start + part_proteins]
        rows = rows[np.argsort([len(sequences[row]) for row in rows], kind="stable")]  # (p_part,) short to long
        lengths = np.array([len(sequences[row]) for row in rows], dtype=np.int64)  # (p_part,)
        kept: dict[str, list[np.ndarray]] = {}
        counts = None
        batches = length_batches(lengths, token_budget)
        if pilot is not None:  # in a seeded order, so that the window times proteins of every length
            batches = [batches[index] for index in np.random.default_rng(SEED).permutation(len(batches))]
        for batch in (pilot.watch(batches) if pilot is not None and not pilot.closed else batches):
            chosen = rows[batch]
            input_ids, attention_mask, _ = encode_batch(tokenizer, [sequences[row] for row in chosen], device)  # (b, l)
            residues = [prompt_residues(len(sequences[row]), int(row)) for row in chosen]
            positions = position_mask(residues, tuple(input_ids.shape)).to(device)  # (b, l)
            targets = None
            if target is not None:
                picked = [entry[prompt_order(len(entry), int(row))[target:target + 1]] for entry, row in zip(residues, chosen, strict=True)]
                targets = position_mask(picked, tuple(input_ids.shape)).to(device)  # (b, l)
                if not bool(targets.any()):
                    continue
            attribution = attribute(model, input_ids, attention_mask, positions, tokenizer.mask_token_id, targets=targets, by=by)
            counts = attribution.quadrant_counts if counts is None else counts + attribution.quadrant_counts
            entries = {
                "protein": np.repeat(chosen, [len(entry) for entry in residues]).astype(np.int32),
                "residue": np.concatenate(residues).astype(np.int32),
                "true": input_ids[positions].cpu().numpy().astype(np.int16),
                "predicted": attribution.predicted.numpy().astype(np.int16),
                "log_prob": attribution.log_prob.numpy().astype(np.float32),
                "indices": attribution.indices.numpy().astype(np.int16),
                "scores": attribution.scores.numpy().astype(np.float32),
                "quadrants": attribution.quadrants.numpy().astype(np.uint8),
            }
            rows_kept = slice(None) if targets is None else targets[positions].cpu().numpy()  # the differentiated prompts
            for name, values in entries.items():
                kept.setdefault(name, []).append(values[rows_kept])
        written += 1
        if not kept:  # no protein of the part has a prompt at this place of its order
            continue
        arrays = {name: np.concatenate(values) for name, values in kept.items()}
        temporary = output / f"writing_{part:05d}.npz"
        np.savez(temporary, quadrant_counts=counts.numpy(), **arrays)
        temporary.replace(path)
        prompts += len(arrays["protein"])
        log(f"attribution part {part}: {len(rows)} proteins, {len(arrays['protein'])} prompts, "
            f"{time.perf_counter() - started:.0f} s")
    return {"parts": written, "parts_planned": -(-len(proteins) // part_proteins), "prompts_this_run": prompts,
            "seconds": time.perf_counter() - started, "token_budget": token_budget, "target": target, "by": by}


def read_attribution(directory: Path) -> dict[str, np.ndarray]:
    """Every part of one attribution pass, or of the passes in the folders under `directory`, concatenated in path
    order; the quadrant counts are summed."""
    parts = sorted(directory.rglob("part_*.npz"))
    if not parts:
        raise FileNotFoundError(f"No attribution part under {directory}.")
    kept: dict[str, list[np.ndarray]] = {}
    for path in parts:
        with np.load(path) as arrays:
            for name in arrays.files:
                kept.setdefault(name, []).append(arrays[name])
    counts = np.sum(kept.pop("quadrant_counts"), axis=0)  # (n, 4)
    # quadrant_counts: (n, 4); protein, residue, true, predicted, log_prob: (s,); indices, scores, quadrants: (s, n, k)
    return {"quadrant_counts": counts, **{name: np.concatenate(values) for name, values in kept.items()}}  # (n, 4), (s,), (s, n, k)


def neuron_ids(indices: np.ndarray | Tensor, units: int) -> np.ndarray | Tensor:
    """Kept units as ids over the whole network: block * f + unit."""
    # indices: (s, n, k)
    blocks = indices.shape[1]
    if isinstance(indices, Tensor):
        return indices.long() + units * torch.arange(blocks, device=indices.device).view(1, blocks, 1)  # (s, n, k)
    return indices.astype(np.int64) + units * np.arange(blocks).reshape(1, blocks, 1)  # (s, n, k)


@dataclass(frozen=True)
class Graph:
    edges: np.ndarray  # (e, 2) unit ids, the smaller first
    z: np.ndarray  # (e,) each edge's z-score
    count: np.ndarray  # (e,) the prompts that keep both units
    kept: np.ndarray  # (n * f,) the prompts that keep each unit
    always_on: np.ndarray  # the ids of the units kept on more than `ALWAYS_ON_SHARE` of prompts
    prompts: int


def cooccurrence_edges(indices: np.ndarray, units: int, *, min_count: int = MIN_COUNT, min_z: float = MIN_Z,
                       always_on_share: float = ALWAYS_ON_SHARE, device: str | torch.device = "cpu",
                       chunk: int = 262_144) -> Graph:
    """The co-occurrence graph of the kept units. With p prompts and units kept on a and b of them, a pair kept
    together on c has z = (c - ab/p) / sqrt((ab/p)(1 - a/p)(1 - b/p)), its count against independent units."""
    # indices: (p, n, k), each block's kept units of each prompt
    prompts, blocks, top = indices.shape
    whole = torch.from_numpy(indices).to(device)  # (p, n, k), in its stored integer type
    kept = torch.zeros(blocks * units, dtype=torch.int64, device=device)  # (n * f,)
    for start in range(0, prompts, chunk):
        kept += torch.bincount(neuron_ids(whole[start:start + chunk], units).flatten(), minlength=blocks * units)
    share = kept.double() / prompts  # (n * f,)
    quiet = share <= always_on_share  # (n * f,)
    pairs, scores, counts = [], [], []
    for first in range(blocks):
        for second in range(first, blocks):
            together = torch.zeros(units * units, dtype=torch.int64, device=device)  # (f * f,)
            for start in range(0, prompts, chunk):
                part = whole[start:start + chunk]  # (c, n, k)
                flat = part[:, first, :, None].long() * units + part[:, second, None, :].long()  # (c, k, k)
                together += torch.bincount(flat.flatten(), minlength=units * units)
            together = together.view(units, units).double()  # (f, f)
            rows = slice(first * units, (first + 1) * units)
            columns = slice(second * units, (second + 1) * units)
            expected = share[rows, None] * share[None, columns] * prompts  # (f, f)
            spread = (expected * (1 - share[rows, None]) * (1 - share[None, columns])).sqrt()  # (f, f)
            z = (together - expected) / spread.clamp(min=1e-12)  # (f, f)
            edge = (together >= min_count) & (z >= min_z) & quiet[rows, None] & quiet[None, columns]  # (f, f)
            if first == second:
                edge = edge.triu(diagonal=1)
            chosen = edge.nonzero()  # (e_pair, 2)
            pairs.append(torch.stack((chosen[:, 0] + first * units, chosen[:, 1] + second * units), dim=1).cpu())
            scores.append(z[edge].cpu())
            counts.append(together[edge].long().cpu())
    return Graph(torch.cat(pairs).numpy(), torch.cat(scores).numpy(), torch.cat(counts).numpy(), kept.cpu().numpy(),
                 (~quiet).nonzero().flatten().cpu().numpy(), prompts)


def _partition(job: tuple[np.ndarray, np.ndarray, int, float, int]) -> tuple[list[list[int]], float]:
    """One resolution's Leiden partition of the z-weighted graph, as each community's nodes, and the seconds it took."""
    import igraph
    import leidenalg

    # job: ((e, 2) node indices, (e,) weights, node count, resolution, seed)
    edges, weights, nodes, resolution, seed = job  # edges: (e, 2) node indices; weights: (e,)
    started = time.perf_counter()
    network = igraph.Graph(n=nodes, edges=edges.tolist(), directed=False)
    network.es["weight"] = weights.tolist()
    partition = leidenalg.find_partition(network, leidenalg.CPMVertexPartition, weights="weight",
                                         resolution_parameter=resolution, seed=seed)
    return [list(members) for members in partition], time.perf_counter() - started


def leiden_communities(graph: Graph, *, resolutions: Sequence[float] = RESOLUTIONS, max_size: int = MAX_SIZE,
                       seed: int = SEED) -> tuple[list[np.ndarray], list[dict[str, object]]]:
    """Leiden under the Constant Potts Model at each resolution, on the z-weighted graph, one process a resolution.
    Communities of 2 to `max_size` units are pooled over the resolutions, each distinct set of units once, as sorted
    unit ids; the second value counts each resolution's partition."""
    if not len(graph.edges):
        return [], []  # no community, (c_i,) each
    nodes, compact = np.unique(graph.edges, return_inverse=True)  # (m,), (e * 2,)
    jobs = [(compact.reshape(-1, 2), graph.z, len(nodes), float(resolution), seed) for resolution in resolutions]
    with ProcessPoolExecutor(max_workers=len(jobs), mp_context=multiprocessing.get_context("spawn")) as pool:
        partitions = list(pool.map(_partition, jobs))
    pooled: dict[tuple[int, ...], None] = {}
    report = []
    for resolution, (partition, seconds) in zip(resolutions, partitions, strict=True):
        sizes = np.array([len(members) for members in partition], dtype=np.int64)
        kept = [tuple(sorted(int(nodes[member]) for member in members)) for members in partition
                if 2 <= len(members) <= max_size]
        new = [members for members in kept if members not in pooled]
        pooled.update(dict.fromkeys(new))
        report.append({"resolution": float(resolution), "communities": int(len(sizes)), "kept": len(kept), "new": len(new),
                       "singletons": int((sizes == 1).sum()), "over_size": int((sizes > max_size).sum()),
                       "largest": int(sizes.max()) if len(sizes) else 0, "seconds": seconds})
    return [np.array(members, dtype=np.int64) for members in pooled], report  # (c_i,) unit ids for each community


def shuffled_communities(communities: Sequence[np.ndarray], units: int, seed: int = SEED) -> list[np.ndarray]:
    """The baseline dictionary: within each block, the units of that block are dealt again among the communities that
    hold them, so each community keeps its blocks and its size in each, and each unit its number of communities. A
    community dealt the same unit twice keeps it once."""
    # communities: (c_i,) unit ids for each of c communities
    owner = np.concatenate([np.full(len(members), index) for index, members in enumerate(communities)])  # (q,)
    unit = np.concatenate(list(communities))  # (q,)
    dealt = unit.copy()  # (q,)
    generator = np.random.default_rng(seed)
    for block in np.unique(unit // units):
        inside = np.flatnonzero(unit // units == block)  # (q_block,)
        dealt[inside] = unit[generator.permutation(inside)]
    return [np.unique(dealt[owner == index]) for index in range(len(communities))]  # (c_i,) unit ids for each community


def candidates(attributed: np.ndarray, communities: Sequence[np.ndarray], total: int, limit: int = CANDIDATES) -> list[np.ndarray]:
    """Each prompt's communities to test: those sharing a unit with its attributed set, the `limit` sharing the most,
    ties to the smaller community and then the earlier one."""
    # attributed: (s, n * k) unit ids; communities: (c_i,) unit ids for each of c communities
    prompts = attributed.shape[0]
    kept = sp.csr_matrix((np.ones(attributed.size, dtype=np.int32), (np.repeat(np.arange(prompts), attributed.shape[1]),
                                                                    attributed.reshape(-1))), shape=(prompts, total))
    owner = np.concatenate([np.full(len(members), index) for index, members in enumerate(communities)])
    held = sp.csr_matrix((np.ones(len(owner), dtype=np.int32), (owner, np.concatenate(list(communities)))),
                         shape=(len(communities), total))
    shared = (kept @ held.T).tocsr()  # (s, c)
    sizes = np.array([len(members) for members in communities], dtype=np.int64)  # (c,)
    chosen = []
    for row in range(prompts):
        columns = shared.indices[shared.indptr[row]:shared.indptr[row + 1]]
        values = shared.data[shared.indptr[row]:shared.indptr[row + 1]]
        order = np.lexsort((columns, sizes[columns], -values))
        chosen.append(columns[order[:limit]].astype(np.int64))  # (at most limit,)
    return chosen  # (at most limit,) community indices for each of s prompts


def subspans(blocks: Sequence[int]) -> list[tuple[int, ...]]:
    """The spans a community is tested on: all of its blocks in order, their two halves and their four quarters, each
    distinct span once."""
    ordered = sorted(set(int(block) for block in blocks))
    spans = [tuple(ordered)]
    for parts in (2, 4):
        if len(ordered) >= parts:
            bounds = np.linspace(0, len(ordered), parts + 1).round().astype(int)
            spans.extend(tuple(ordered[bounds[part]:bounds[part + 1]]) for part in range(parts))
    return list(dict.fromkeys(spans))


@dataclass(frozen=True)
class Intervention:
    """One forward pass of one protein, edited at one token column."""

    protein: int  # the protein's row in the sequences given to `evaluate`
    column: int  # the prompt's token column
    blocks: tuple[int, ...] = ()  # the blocks edited; none leaves the model intact
    units: np.ndarray | None = None  # unit ids over the network
    keep: bool = False  # True: every unit of `blocks` but `units` is set to zero; False: `units` are set to zero


@contextmanager
def column_ablation(model: nn.Module, zero: Tensor, columns: Tensor) -> Iterator[None]:
    """Set to zero, in each row's token column, the units that `zero` marks, while the context is open."""
    # zero: (b, n, f) bool; columns: (b,)
    blocks = transformer_blocks(model)
    rows = torch.arange(len(columns), device=columns.device)  # (b,)
    edited = zero.flatten(start_dim=2).any(dim=2).any(dim=0)  # (n,)
    handles = []

    def hook_for(block: int) -> Callable[[nn.Module, tuple[Tensor, ...], Tensor], Tensor]:
        def hook(module: nn.Module, args: tuple[Tensor, ...], output: Tensor) -> Tensor:
            # args: ((b, l, 2f),), the gate and up halves; output: (b, l, f)
            edited_output = output.clone()  # (b, l, f)
            edited_output[rows, columns] = output[rows, columns].masked_fill(zero[:, block], 0)  # (b, f) at each row's column
            return edited_output  # (b, l, f)
        return hook  # replaces the SwiGLU's (b, l, f) output

    try:
        for block in edited.nonzero().flatten().tolist():
            handles.append(blocks[block].ffn[SWIGLU_INDEX].register_forward_hook(hook_for(block)))
        yield
    finally:
        for handle in handles:
            handle.remove()


@torch.inference_mode()
def evaluate(model: nn.Module, sequences: Sequence[str], proteins: Sequence[int], rows: Sequence[Intervention],
             device: torch.device, *, token_budget: int) -> Tensor:
    """The log probabilities over the vocabulary at each row's column, the protein's prompts masked, under each row's
    intervention. `proteins` gives each sequence's row in the atlas set, which seeds its masked residues."""
    blocks = transformer_blocks(model)
    units = blocks[0].ffn[DOWN_PROJECTION_INDEX].in_features
    tokenizer = model.tokenizer
    order = np.argsort([len(sequences[row.protein]) for row in rows], kind="stable")  # (r,)
    lengths = np.array([len(sequences[rows[index].protein]) for index in order], dtype=np.int64)  # (r,)
    results: list[Tensor | None] = [None] * len(rows)
    for batch in length_batches(lengths, token_budget):
        chosen = [rows[index] for index in order[batch]]
        input_ids, attention_mask, _ = encode_batch(tokenizer, [sequences[row.protein] for row in chosen], device)  # (b, l)
        residues = [prompt_residues(len(sequences[row.protein]), int(proteins[row.protein])) for row in chosen]
        positions = position_mask(residues, tuple(input_ids.shape)).to(device)  # (b, l)
        columns = torch.tensor([row.column for row in chosen], device=device)  # (b,)
        zero = torch.zeros(len(chosen), len(blocks) * units, dtype=torch.bool, device=device)  # (b, n * f)
        for index, row in enumerate(chosen):
            if not row.blocks:
                continue
            listed = torch.from_numpy(np.asarray(row.units, dtype=np.int64)).to(device)
            if row.keep:
                for block in row.blocks:
                    zero[index, block * units:(block + 1) * units] = True
                zero[index, listed] = False
            else:
                zero[index, listed] = True
        with column_ablation(model, zero.view(len(chosen), len(blocks), units), columns):
            logits = model(input_ids=input_ids.masked_fill(positions, tokenizer.mask_token_id),
                           attention_mask=attention_mask).logits  # (b, l, v)
        log_probs = functional.log_softmax(logits[torch.arange(len(chosen), device=device), columns].float(), dim=-1)  # (b, v)
        for index, values in zip(order[batch], log_probs.cpu(), strict=True):
            results[index] = values
    return torch.stack(results)  # (r, v)


def kl_divergence(clean: Tensor, edited: Tensor) -> Tensor:
    """KL(clean || edited) of distributions given as log probabilities, row by row."""
    # clean, edited: (r, v)
    return (clean.exp().double() * (clean.double() - edited.double())).sum(dim=-1)  # (r,)


def in_blocks(units_held: np.ndarray, span: Sequence[int], units: int) -> np.ndarray:
    """The unit ids that fall in a span of blocks."""
    # units_held: (c_i,)
    return units_held[np.isin(units_held // units, np.asarray(span))]  # (m,), the members in the span


def run_tests(model: nn.Module, sequences: Sequence[str], proteins: Sequence[int], prompts: pd.DataFrame,
                 dictionaries: dict[str, Sequence[np.ndarray]], always_on: np.ndarray, units: int, device: torch.device, *,
                 token_budget: int, budget_seconds: float, chunk: int = 96, limit: int = CANDIDATES,
                 checkpoint: Callable[[pd.DataFrame, int], None] | None = None,
                 log: Callable[[str], None] = print) -> tuple[pd.DataFrame, int]:
    """The three tests of every prompt's candidate communities, for each dictionary of communities (the discovered
    one and its baselines), `chunk` prompts at a time until `budget_seconds` have passed. Returns one row for each
    prompt, dictionary, community and span, and the number of prompts tested, a prefix of `prompts`.

    Layer necessity runs first and the other two tests only on the spans that pass it, since both need it to count.
    """
    # prompts: protein (row in `sequences`), column, attributed (unit ids) for each held-out prompt, in test order
    # dictionaries: (c_i,) unit ids for each community of each dictionary; always_on: (a,) unit ids
    total = len(transformer_blocks(model)) * units
    attributed = np.stack(prompts["attributed"].to_numpy())  # (s, n * k)
    chosen = {name: candidates(attributed, communities, total, limit) for name, communities in dictionaries.items()}
    started = time.perf_counter()
    records: list[dict[str, object]] = []
    tested = 0
    for start in range(0, len(prompts), chunk):
        if time.perf_counter() - started > budget_seconds:
            break
        stop = min(start + chunk, len(prompts))
        plans = []  # (prompt, dictionary, community, span)
        for prompt in range(start, stop):
            for name, communities in dictionaries.items():
                for community in chosen[name][prompt]:
                    for span in subspans(communities[community] // units):
                        plans.append((prompt, name, int(community), span))
        protein = prompts["protein"].to_numpy()
        column = prompts["column"].to_numpy()
        clean_rows = [Intervention(int(protein[prompt]), int(column[prompt])) for prompt in range(start, stop)]
        layer_keys = list(dict.fromkeys((prompt, span) for prompt, _, _, span in plans))
        layer_rows = [Intervention(int(protein[prompt]), int(column[prompt]), span, in_blocks(always_on, span, units), keep=True)
                      for prompt, span in layer_keys]
        first = evaluate(model, sequences, proteins, [*clean_rows, *layer_rows], device, token_budget=token_budget)  # (r, v)
        clean = first[:len(clean_rows)]  # (s_chunk, v)
        layer = dict(zip(layer_keys, kl_divergence(clean[[prompt - start for prompt, _ in layer_keys]],
                                                   first[len(clean_rows):]).tolist(), strict=True))
        passing = [plan for plan in plans if layer[(plan[0], plan[3])] >= NECESSITY]
        second_rows = []
        for prompt, name, community, span in passing:
            members = in_blocks(dictionaries[name][community], span, units)
            second_rows.append(Intervention(int(protein[prompt]), int(column[prompt]), span, members))
            second_rows.append(Intervention(int(protein[prompt]), int(column[prompt]), span,
                                            np.union1d(members, in_blocks(always_on, span, units)), keep=True))
        outcome: dict[tuple[int, str, int, tuple[int, ...]], tuple[float, float]] = {}
        if second_rows:
            second = evaluate(model, sequences, proteins, second_rows, device, token_budget=token_budget)  # (r, v)
            base = clean[[prompt - start for prompt, _, _, _ in passing]].repeat_interleave(2, dim=0)  # (r, v)
            values = kl_divergence(base, second).view(-1, 2).tolist()
            outcome = dict(zip(passing, [tuple(pair) for pair in values], strict=True))
        for plan in plans:
            prompt, name, community, span = plan
            necessity, sufficiency = outcome.get(plan, (float("nan"), float("nan")))
            records.append({
                "prompt": prompt, "dictionary": name, "community": community, "blocks": len(span),
                "first_block": span[0], "last_block": span[-1], "span": ",".join(str(block) for block in span),
                "layer_necessity": layer[(prompt, span)], "necessity": necessity, "sufficiency": sufficiency,
                "explains": bool(necessity >= NECESSITY and sufficiency <= SUFFICIENCY),
            })
        tested = stop
        log(f"community tests: {tested} prompts, {len(records)} rows, {time.perf_counter() - started:.0f} s")
        if checkpoint is not None:
            checkpoint(pd.DataFrame(records), tested)
    return pd.DataFrame(records), tested


def coverage(results: pd.DataFrame, tested: int, sizes: Sequence[int] = SPAN_SIZES) -> dict[str, dict[str, float]]:
    """For each dictionary, the share of the tested prompts that some community explains within a span of at least each
    size."""
    report: dict[str, dict[str, float]] = {}
    for name, rows in results.groupby("dictionary"):
        explained = rows[rows["explains"]]
        report[str(name)] = {str(size): explained.loc[explained["blocks"] >= size, "prompt"].nunique() / max(tested, 1)
                             for size in sizes}
    return report


def leave_one_out(model: nn.Module, sequences: Sequence[str], proteins: Sequence[int], prompts: pd.DataFrame,
                  results: pd.DataFrame, communities: Sequence[np.ndarray], units: int, device: torch.device, *,
                  token_budget: int, top: int = 30, per_community: int = 32, seed: int = SEED) -> pd.DataFrame:
    """For the `top` discovered communities that explain the most prompts, each on its span that explains the most:
    the KL divergence when each of its units in that span is set to zero alone, on up to `per_community` of the
    prompts it explains, beside the divergence when all are (`necessity`)."""
    # communities: (c_i,) unit ids for each of c communities
    explained = results[(results["dictionary"] == "discovered") & results["explains"]]
    spans = (explained.groupby(["community", "span"])["prompt"].nunique().rename("prompts").reset_index()
             .sort_values(["prompts", "community"], ascending=[False, True]).drop_duplicates("community").head(top))
    generator = np.random.default_rng(seed)
    protein, column = prompts["protein"].to_numpy(), prompts["column"].to_numpy()
    frames = []
    for community, span_name in zip(spans["community"], spans["span"], strict=True):
        span = tuple(int(block) for block in span_name.split(","))
        members = in_blocks(communities[int(community)], span, units)
        rows = explained[(explained["community"] == community) & (explained["span"] == span_name)]
        picked = rows.iloc[np.sort(generator.choice(len(rows), size=min(per_community, len(rows)), replace=False))]
        interventions = [Intervention(int(protein[prompt]), int(column[prompt])) for prompt in picked["prompt"]]
        for prompt in picked["prompt"]:
            interventions.extend(Intervention(int(protein[prompt]), int(column[prompt]), span, np.array([member]))
                                 for member in members)
        outputs = evaluate(model, sequences, proteins, interventions, device, token_budget=token_budget)  # (r, v)
        clean = outputs[:len(picked)].repeat_interleave(len(members), dim=0)  # (r, v)
        alone = kl_divergence(clean, outputs[len(picked):]).view(len(picked), len(members)).numpy()  # (s, m)
        frames.append(pd.DataFrame({
            "community": int(community), "span": span_name, "unit": members, "prompts": len(picked),
            "median_alone": np.median(alone, axis=0), "max_alone": alone.max(axis=0),
            "median_together": float(picked["necessity"].median()),
        }))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
