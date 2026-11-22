"""A canonical base's depth-layer hidden state and structural stream for a batch of proteins, computed on the GPU in use.

A model that reads per-residue ESMC features for proteins outside the canonical token store (which holds Atlas's proteins
only, Logan, 2026-10-19) runs the frozen base beside itself. It runs the store's own computation:
`canonical.build_runtime` loads the pinned, digest-checked base and structural projection, and FastPLMs' `TokenTapExecutor`
applies the canonical `layer_hidden` and `structural` taps (and `final_hidden`, for a baseline arm) over CLS, the residues
and EOS of the canonical crop (2,046 residues). It runs in BF16 without the embedding profile's fixed batch geometry, so a
row matches the store's to BF16 rounding, not bit for bit; `parity` measures that. A base whose canonical streams hold no
`structural` (the random-init control) gives batches without it.

Symbols: b proteins, m token columns of the padded batch, n packed token rows (sum of l_i + 2), a hidden width,
s structural width (256).
"""

from __future__ import annotations

import hashlib
import numpy as np
import torch

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from torch import Tensor

from .canonical import FINAL_HIDDEN, LAYER_HIDDEN, STRUCTURAL, build_runtime, canonical_base
from .contracts import CANONICAL_MAX_RESIDUES


@dataclass(frozen=True)
class StreamBatch:
    """Padded token rows of one batch, on the device."""

    hidden: Tensor  # (b, m, a) bfloat16, the depth layer
    structural: Tensor | None  # (b, m, s); None for a base without the structural stream
    mask: Tensor  # (b, m) bool, CLS, retained residues and EOS
    residues: list[int]  # retained residues of each protein after the crop
    final: Tensor | None = None  # (b, m, a) bfloat16, the final hidden state after its norm, when asked for


class EsmcStreams:
    """A frozen canonical base and the canonical taps a token model reads: `layer_hidden`, `structural`, optionally `final_hidden`."""

    def __init__(self, cache: Path, device: str = "cuda", base: str = "esmc_small", with_final: bool = False) -> None:
        from fastplms.embeddings import ResidueVocabulary, TokenTapExecutor
        from fastplms.embeddings.taps import plan_taps

        runtime = build_runtime(canonical_base(base), cache, device=device, fetch=True)
        self.structured = STRUCTURAL in canonical_base(base).streams
        wanted = (LAYER_HIDDEN, *((STRUCTURAL,) if self.structured else ()), *((FINAL_HIDDEN,) if with_final else ()))
        by_name = {tap.name: tap for tap in runtime.taps}
        missing = [name for name in wanted if name not in by_name]
        if missing:
            raise ValueError(f"the canonical {base} runtime lacks the taps {missing}")
        model = runtime.model
        plan = plan_taps([by_name[name] for name in wanted], int(model.embedding_tap_state_count))
        self.vocabulary = ResidueVocabulary(model.tokenizer)
        self.executor = TokenTapExecutor(model, plan, vocabulary=self.vocabulary,
                                         max_residues=CANONICAL_MAX_RESIDUES, dtype=None)
        self.base = base
        self.with_final = with_final
        self.device = torch.device(device)
        self.evidence = runtime.evidence
        self.hidden_width = canonical_base(base).hidden_width

    def crop(self, sequence: str) -> str:
        return self.executor.crop(sequence)

    def sanitize(self, sequence: str) -> tuple[str, int]:
        """The canonical text of a raw sequence and how many residues were replaced.

        Whitespace goes, letters are uppercased, and a letter the base's tokenizer has no residue token for (ESMC lacks J,
        for one) becomes X, which the tokenizer reads as unknown. Anything but ASCII letters is refused. The canonical
        stores refuse such proteins instead (`--skip-unrepresentable`); a model trained on a legacy benchmark keeps them.
        """
        text = "".join(sequence.split()).upper()
        if not text or not text.isascii() or not text.isalpha():
            raise ValueError(f"Not a protein sequence: {sequence[:30]!r}")
        letters = np.frombuffer(text.encode("ascii"), dtype=np.uint8)  # (l,)
        unknown = self.vocabulary.table[letters] < 0  # (l,)
        replaced = int(unknown.sum())
        if replaced == 0:
            return text, 0
        return "".join("X" if bad else letter for letter, bad in zip(text, unknown, strict=True)), replaced

    def _pad(self, packed_values: Tensor, owner: Tensor, within: Tensor, b: int, m: int) -> Tensor:
        # packed_values: (n, w); owner and within: (n,); the padded rows stay zero.
        # owner: (n,)
        padded = packed_values.new_zeros((b, m, packed_values.shape[1]))  # (b, m, w)
        padded[owner, within] = packed_values
        return padded  # (b, m, w)

    @torch.no_grad()
    def batch(self, sequences: Sequence[str]) -> StreamBatch:
        digests = [hashlib.sha256(sequence.encode()).hexdigest() for sequence in sequences]
        # The base keeps its own BF16 arithmetic, the one `parity` checks, whatever autocast the caller trains under.
        with torch.autocast(self.device.type, enabled=False):
            packed = self.executor.run_batch(sequences, digests)
            packed.wait()
        rows = torch.tensor(packed.rows, dtype=torch.int64, device=self.device)  # (b,) l_i + 2
        b, m = len(sequences), int(rows.max())
        owner = torch.repeat_interleave(torch.arange(b, device=self.device), rows)  # (n,)
        starts = torch.cumsum(rows, 0) - rows  # (b,)
        within = torch.arange(int(rows.sum()), device=self.device) - torch.repeat_interleave(starts, rows)  # (n,)
        names = (LAYER_HIDDEN, *((STRUCTURAL,) if self.structured else ()), *((FINAL_HIDDEN,) if self.with_final else ()))
        values = {name: packed.streams[name]["values"].to(self.device, non_blocking=True) for name in names}  # each (n, w)
        mask = torch.arange(m, device=self.device)[None, :] < rows[:, None]  # (b, m)
        return StreamBatch(
            hidden=self._pad(values[LAYER_HIDDEN], owner, within, b, m),  # (b, m, a)
            structural=self._pad(values[STRUCTURAL], owner, within, b, m) if self.structured else None,  # (b, m, s)
            mask=mask,
            residues=[count - 2 for count in packed.rows],
            final=self._pad(values[FINAL_HIDDEN], owner, within, b, m) if self.with_final else None,  # (b, m, a)
        )


def fuse(batch: StreamBatch) -> Tensor:
    """The token fusion's input: the depth-layer state and the structure stream joined row for row, padding zero.

    `(b, m, a)` and `(b, m, s)` give `(b, m, a + s)` in float32, the width the model's first Linear projects from.
    """
    if batch.structural is None:
        raise ValueError("the fusion needs the structural stream, which this base does not have")
    joined = torch.cat((batch.hidden.float(), batch.structural.float()), dim=-1)  # (b, m, a + s)
    return joined.masked_fill(~batch.mask[..., None], 0)  # (b, m, a + s)


def parity(streams: EsmcStreams, sequences: Sequence[str], revision: str) -> dict[str, float]:
    """Relative L2 distance of this computation's rows from the canonical token store's, per stream.

    `sequences` must be in the store (Atlas's proteins). A misaligned layer or row gives distances near 1; BF16
    rounding without the profile's fixed geometry gives about 1e-2.
    """
    from .hub import read_rows

    directory = f"{canonical_base(streams.base).store_model}/token"
    names = [LAYER_HIDDEN, *([STRUCTURAL] if streams.structured else [])]
    stored = read_rows("Synthyra/esmc_embeddings", directory, sequences, revision=revision, streams=names)
    computed = streams.batch(sequences)
    tensors = {LAYER_HIDDEN: computed.hidden, STRUCTURAL: computed.structural}
    distances: dict[str, list[float]] = {name: [] for name in names}
    for index, sequence in enumerate(sequences):
        rows = computed.residues[index] + 2
        for name in names:
            values = tensors[name]  # (b, m, w)
            reference = stored[sequence][name].to(torch.float32)  # (l + 2, w)
            mine = values[index, :rows].float().cpu()  # (l + 2, w)
            if mine.shape != reference.shape:
                raise ValueError(f"{name} rows differ in shape: {tuple(mine.shape)} against {tuple(reference.shape)}")
            distances[name].append(float((mine - reference).norm() / reference.norm()))
    return {name: max(values) for name, values in distances.items()}
