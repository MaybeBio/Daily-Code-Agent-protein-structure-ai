"""Association sums for dense units, a batch of proteins at a time, in the atlas study's exact form.

The atlas study's `annotation_vocabulary.study.association.local_statistics` walks proteins one by one over sparse
TopK slots on the CPU. Units sparsified to the SAE's firing rates have as many active entries per residue as an SAE,
but no fixed slots and hundreds of thousands of columns across a model, so this module computes the same sums for a
whole batch with matrix products on the GPU. `local_metrics` of the same study then turns them into its statistics,
unchanged. `tests/test_units_accumulate.py` checks the sums against `local_statistics` itself.

A local term is scored within its scope: the whole chain, or for a modification site the residues of its amino acid. Its
positive residues are inside; its masked residues (a tier the protein's split neither scores nor counts as a negative) are
left out; the rest of its scope is outside. A protein is informative for the term when both inside and outside hold a
residue. For each informative (protein, term) pair and each unit, the paired contrast is the share of inside residues where
the unit fires minus the share of outside residues where it fires; proteins where the unit never fires in the scope
contribute a zero contrast and still count, as in the study, which this reduces to for a chain-scoped term without masked
residues.

Symbols: n proteins in a batch; r residues of the batch, concatenated; p poles; c poles in one chunk; t local terms; q
informative (protein, term) pairs; e inside entries of the pairs; m masked entries of the pairs; k = 20 amino acids.
"""

from __future__ import annotations

import numpy as np
import torch

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from annotation_vocabulary.study.association import merge_intervals
from torch import Tensor

from .intrinsic import AMINO_ACIDS


SUM_KEYS = ("sum_difference", "sum_squared_difference", "sum_inside", "sum_outside", "inside_hits", "outside_hits", "n_active")
CHAIN = -1  # the scope of a term whose outside is the rest of the chain (`compendium.CHAIN`)
KINDS = len(AMINO_ACIDS)
KIND_OF = {letter: index for index, letter in enumerate(AMINO_ACIDS)}


@dataclass(frozen=True)
class LocalRuns:
    """One protein's local annotations: positive runs and masked runs of local tokens, 1-based and inclusive."""

    tokens: np.ndarray  # (a,)
    starts: np.ndarray  # (a,)
    ends: np.ndarray  # (a,)
    masked_tokens: np.ndarray  # (b,)
    masked_starts: np.ndarray  # (b,)
    masked_ends: np.ndarray  # (b,)

    def __post_init__(self) -> None:
        if not len(self.tokens) == len(self.starts) == len(self.ends):
            raise ValueError("Positive tokens, starts and ends differ in length.")
        if not len(self.masked_tokens) == len(self.masked_starts) == len(self.masked_ends):
            raise ValueError("Masked tokens, starts and ends differ in length.")

    @classmethod
    def positives(cls, tokens: Sequence[int], starts: Sequence[int], ends: Sequence[int]) -> LocalRuns:
        """Runs with no masked residue."""
        empty = np.zeros(0, dtype=np.int64)
        return cls(*(np.asarray(values, dtype=np.int64) for values in (tokens, starts, ends)), empty, empty, empty)


@dataclass(frozen=True)
class TermResidues:
    """One term's residues in one protein, 0-based: inside, masked within the scope, and the scope's size."""

    inside: np.ndarray  # (i,)
    masked: np.ndarray  # (j,)
    scope_size: int

    @property
    def outside_size(self) -> int:
        return self.scope_size - len(self.inside) - len(self.masked)

    @property
    def informative(self) -> bool:
        return len(self.inside) > 0 and self.outside_size > 0


def _positions(starts: Sequence[int], ends: Sequence[int], length: int) -> np.ndarray:
    spans = merge_intervals(list(starts), list(ends), length)
    return np.concatenate([np.arange(start, stop) for start, stop in spans]) if spans else np.zeros(0, dtype=np.int64)  # (i,)


def residue_kinds(sequence: str) -> np.ndarray:
    """Each residue's amino acid as an index into `AMINO_ACIDS`, -1 for any other letter."""
    return np.fromiter((KIND_OF.get(letter, -1) for letter in sequence), dtype=np.int64, count=len(sequence))  # (l,)


def term_residues(sequence: str, runs: LocalRuns, kept: Collection[int], scopes: Mapping[int, int]) -> dict[int, TermResidues]:
    """Each kept term the protein holds a positive of, with its inside, masked and scope residues; a term absent from
    `scopes` is scored on the chain. A positive residue off its scope's amino acid raises: the release places every site
    on its class's residue."""
    length = len(sequence)
    kinds = residue_kinds(sequence) if any(scope != CHAIN for scope in scopes.values()) else None  # (l,)
    grouped: dict[int, tuple[list[int], list[int]]] = {}
    for token, start, end in zip(runs.tokens, runs.starts, runs.ends, strict=True):
        if int(token) in kept:
            left, right = grouped.setdefault(int(token), ([], []))
            left.append(int(start))
            right.append(int(end))
    hidden: dict[int, tuple[list[int], list[int]]] = {}
    for token, start, end in zip(runs.masked_tokens, runs.masked_starts, runs.masked_ends, strict=True):
        if int(token) in grouped:
            left, right = hidden.setdefault(int(token), ([], []))
            left.append(int(start))
            right.append(int(end))
    found: dict[int, TermResidues] = {}
    for token, (starts, ends) in grouped.items():
        inside = _positions(starts, ends, length)  # (i,)
        masked = np.setdiff1d(_positions(*hidden.get(token, ([], [])), length), inside)  # (j,)
        scope = scopes.get(token, CHAIN)
        if scope == CHAIN:
            found[token] = TermResidues(inside, masked, length)
            continue
        if (kinds[inside] != scope).any():
            raise ValueError(f"Term {token} has a positive residue off its amino acid {AMINO_ACIDS[scope]}.")
        found[token] = TermResidues(inside, masked[kinds[masked] == scope], int((kinds == scope).sum()))
    return found


@dataclass(frozen=True)
class LocalPairs:
    """The informative (protein, term) pairs of one batch, where their inside and masked residues sit, and their scopes."""

    protein: Tensor  # (q,) protein index within the batch
    term: Tensor  # (q,) column of the term in the accumulator
    scope: Tensor  # (q,) CHAIN, or the amino acid whose residues the pair is scored on
    inside_pair: Tensor  # (e,) pair index of each inside residue
    inside_residue: Tensor  # (e,) batch residue index of each inside residue
    masked_pair: Tensor  # (m,) pair index of each masked residue
    masked_residue: Tensor  # (m,) batch residue index of each masked residue
    inside_length: Tensor  # (q,) inside residues per pair
    outside_length: Tensor  # (q,) outside residues per pair
    residue_kind: Tensor  # (r,) each batch residue's amino acid, -1 for another letter

    @property
    def size(self) -> int:
        return int(self.protein.numel())


def _entries(groups: Sequence[np.ndarray]) -> tuple[Tensor, Tensor]:
    # groups: (e_i,) the residue rows of each pair
    if not groups:
        return torch.zeros(0, dtype=torch.long), torch.zeros(0, dtype=torch.long)  # (0,), (0,)
    pairs = np.concatenate([np.full(len(positions), pair) for pair, positions in enumerate(groups)])  # (e,)
    return torch.from_numpy(pairs).long(), torch.from_numpy(np.concatenate(groups)).long()  # (e,), (e,)


def local_pairs(
    sequences: Sequence[str],
    annotations: Sequence[LocalRuns],
    term_columns: Mapping[int, int],
    scopes: Mapping[int, int] | None = None,
) -> LocalPairs:
    """The informative pairs of a batch from each protein's local runs (`LocalRuns`), in batch order.

    The proteins' residues follow one another in the batch's activation matrix. Terms outside `term_columns` are ignored,
    as the study ignores tokens outside its endpoint list; `scopes` gives a term scored on one amino acid its index.
    """
    if len(sequences) != len(annotations):
        raise ValueError("Every protein in the batch needs its sequence and its annotations.")
    scopes = {} if scopes is None else scopes
    proteins: list[int] = []
    terms: list[int] = []
    pair_scopes: list[int] = []
    inside_groups: list[np.ndarray] = []
    masked_groups: list[np.ndarray] = []
    inside_lengths: list[int] = []
    outside_lengths: list[int] = []
    offset = 0
    for protein, (sequence, runs) in enumerate(zip(sequences, annotations, strict=True)):
        for token, residues in term_residues(sequence, runs, term_columns, scopes).items():
            if not residues.informative:
                continue
            proteins.append(protein)
            terms.append(term_columns[token])
            pair_scopes.append(scopes.get(token, CHAIN))
            inside_groups.append(residues.inside + offset)
            masked_groups.append(residues.masked + offset)
            inside_lengths.append(len(residues.inside))
            outside_lengths.append(residues.outside_size)
        offset += len(sequence)
    inside_pair, inside_residue = _entries(inside_groups)  # (e,), (e,)
    masked_pair, masked_residue = _entries(masked_groups)  # (m,), (m,)
    long = torch.long
    return LocalPairs(
        protein=torch.tensor(proteins, dtype=long),  # (q,)
        term=torch.tensor(terms, dtype=long),  # (q,)
        scope=torch.tensor(pair_scopes, dtype=long),  # (q,)
        inside_pair=inside_pair, inside_residue=inside_residue, masked_pair=masked_pair, masked_residue=masked_residue,
        inside_length=torch.tensor(inside_lengths, dtype=torch.float64),  # (q,)
        outside_length=torch.tensor(outside_lengths, dtype=torch.float64),  # (q,)
        residue_kind=torch.from_numpy(np.concatenate([residue_kinds(sequence) for sequence in sequences]) if sequences
                                      else np.zeros(0, dtype=np.int64)),  # (r,)
    )


def protein_index(lengths: Sequence[int], device: str | torch.device = "cpu") -> Tensor:
    """The protein each of a batch's concatenated residues belongs to."""
    counts = torch.as_tensor(list(lengths), dtype=torch.long, device=device)  # (n,)
    return torch.repeat_interleave(torch.arange(counts.numel(), device=device), counts)  # (r,)


def protein_maxima(activations: Tensor, owner: Tensor, n_proteins: int) -> Tensor:
    """Each protein's maximum activation per unit, the atlas study's global score."""
    # activations: (r, p), nonnegative; owner: (r,)
    maxima = activations.new_zeros((n_proteins, activations.shape[1]))  # (n, p)
    index = owner.unsqueeze(1).expand_as(activations)  # (r, p)
    return maxima.scatter_reduce(0, index, activations, reduce="amax", include_self=True)  # (n, p)


class LocalAccumulator:
    """Running sums of paired occupancy contrasts for every (unit, term), over every batch it is given.

    Sums are (units, terms), the study's layout, on `device` in `dtype` (float64 by default, as in the study). `keys`
    names the sums kept: all seven feed the study's `local_metrics`, while the dominant-term rule reads only
    `sum_difference` and the enrichment check `sum_inside` and `sum_outside`. A batch's units are taken `chunk` columns at
    a time, so it never holds more than (r, chunk) indicators; residue counts are summed in float32, exact below 2^24.
    """

    def __init__(
        self,
        n_terms: int,
        n_poles: int,
        device: str | torch.device = "cpu",
        dtype: torch.dtype = torch.float64,
        *,
        keys: Sequence[str] = SUM_KEYS,
        chunk: int = 4096,
    ) -> None:
        unknown = sorted(set(keys) - set(SUM_KEYS))
        if unknown or not keys:
            raise ValueError(f"Keys must be a nonempty subset of {SUM_KEYS}; got unknown {unknown}.")
        if chunk < 1:
            raise ValueError("The unit chunk must be positive.")
        self.n_terms, self.n_poles, self.chunk = n_terms, n_poles, chunk
        self.keys = tuple(key for key in SUM_KEYS if key in keys)
        self.device, self.dtype = torch.device(device), dtype
        self.sums = {key: torch.zeros((n_poles, n_terms), dtype=dtype, device=self.device) for key in self.keys}  # each (p, t)
        self.n_informative = torch.zeros(n_terms, dtype=torch.long, device=self.device)  # (t,)
        self.inside_exposure = torch.zeros(n_terms, dtype=torch.long, device=self.device)  # (t,)
        self.outside_exposure = torch.zeros(n_terms, dtype=torch.long, device=self.device)  # (t,)

    def update(self, activations: Tensor, owner: Tensor, pairs: LocalPairs, n_proteins: int | None = None) -> None:
        """Add one batch: its sparsified activations, each residue's protein, and its informative pairs."""
        # activations: (r, p); owner: (r,)
        if activations.shape[1] != self.n_poles:
            raise ValueError(f"Expected {self.n_poles} poles, got {activations.shape[1]}.")
        if pairs.size == 0:
            return
        work = activations.device
        n_proteins = int(owner.max()) + 1 if n_proteins is None else n_proteins
        def entries(pair: Tensor, residue: Tensor) -> Tensor:
            # pair, residue: (e,)
            return torch.sparse_coo_tensor(
                torch.stack((pair, residue)).to(work), torch.ones(pair.numel(), dtype=torch.float32, device=work),
                size=(pairs.size, activations.shape[0]),
                check_invariants=False,  # indices come from `local_pairs`, in range by construction
            )  # (q, r), sparse

        inside_entries = entries(pairs.inside_pair, pairs.inside_residue)  # (q, r)
        masked_entries = entries(pairs.masked_pair, pairs.masked_residue) if pairs.masked_pair.numel() else None  # (q, r)
        protein = pairs.protein.to(work)  # (q,)
        scope = pairs.scope.to(work)  # (q,)
        scoped = scope != CHAIN  # (q,)
        kind = pairs.residue_kind.to(work)  # (r,)
        with_kind = kind >= 0  # (r,)
        kind_row = owner[with_kind] * KINDS + kind[with_kind]  # (r_kind,)
        scope_row = protein[scoped] * KINDS + scope[scoped]  # (q_scoped,)
        inside_length = pairs.inside_length.to(work).unsqueeze(1)  # (q, 1)
        outside_length = pairs.outside_length.to(work).unsqueeze(1)  # (q, 1)
        term = pairs.term.to(self.device)  # (q,)
        for start in range(0, self.n_poles, self.chunk):
            stop = min(start + self.chunk, self.n_poles)
            active = (activations[:, start:stop] > 0).to(torch.float32)  # (r, c)
            totals = active.new_zeros((n_proteins, stop - start)).index_add_(0, owner, active)[protein]  # (q, c), in scope
            if bool(scoped.any()):
                by_kind = active.new_zeros((n_proteins * KINDS, stop - start)).index_add_(0, kind_row, active[with_kind])  # (n k, c)
                totals[scoped] = by_kind[scope_row]
            totals = totals.double()  # (q, c)
            inside = torch.sparse.mm(inside_entries, active).double()  # (q, c)
            outside = totals - inside  # (q, c)
            if masked_entries is not None:
                outside = outside - torch.sparse.mm(masked_entries, active).double()  # (q, c)
            inside_fraction = inside / inside_length  # (q, c)
            outside_fraction = outside / outside_length  # (q, c)
            difference = inside_fraction - outside_fraction  # (q, c)
            increments = {
                "sum_difference": difference, "sum_squared_difference": difference**2,
                "sum_inside": inside_fraction, "sum_outside": outside_fraction,
                "inside_hits": inside, "outside_hits": outside, "n_active": (totals > 0).double(),
            }  # each (q, c)
            for key in self.keys:
                self.sums[key][start:stop].index_add_(1, term, increments[key].T.to(self.device, self.dtype))  # (c, t)
        self.n_informative.index_add_(0, term, torch.ones_like(term))  # (t,)
        self.inside_exposure.index_add_(0, term, pairs.inside_length.to(self.device).long())  # (t,)
        self.outside_exposure.index_add_(0, term, pairs.outside_length.to(self.device).long())  # (t,)

    def study_sums(self) -> dict[str, np.ndarray]:
        """The kept sums in the study's layout, (units, terms) and (terms,), ready for its `local_metrics`."""
        arrays = {key: values.cpu().double().numpy() for key, values in self.sums.items()}  # each (p, t)
        arrays["n_informative"] = self.n_informative.cpu().numpy()  # (t,)
        arrays["inside_exposure"] = self.inside_exposure.cpu().numpy()  # (t,)
        arrays["outside_exposure"] = self.outside_exposure.cpu().numpy()  # (t,)
        return arrays  # (p, t) and (t,) arrays by key

    def state_dict(self) -> dict[str, Tensor]:
        """Everything a resumed run needs, on the CPU."""
        state = {f"sum.{key}": values.cpu() for key, values in self.sums.items()}
        state.update(n_informative=self.n_informative.cpu(), inside_exposure=self.inside_exposure.cpu(),
                     outside_exposure=self.outside_exposure.cpu())
        return state  # (p, t) sums and (t,) counts

    def load_state_dict(self, state: dict[str, Tensor]) -> None:
        """Restore the sums of an interrupted run; shapes and keys must match this accumulator's."""
        # state: (p, t) sums and (t,) counts by key
        expected = {f"sum.{key}" for key in self.keys} | {"n_informative", "inside_exposure", "outside_exposure"}
        if set(state) != expected:
            raise ValueError(f"Saved accumulator keys {sorted(state)} differ from {sorted(expected)}.")
        for key in self.keys:
            if tuple(state[f"sum.{key}"].shape) != (self.n_poles, self.n_terms):
                raise ValueError(f"Saved {key} has shape {tuple(state[f'sum.{key}'].shape)}.")
            self.sums[key].copy_(state[f"sum.{key}"])
        self.n_informative.copy_(state["n_informative"])
        self.inside_exposure.copy_(state["inside_exposure"])
        self.outside_exposure.copy_(state["outside_exposure"])
