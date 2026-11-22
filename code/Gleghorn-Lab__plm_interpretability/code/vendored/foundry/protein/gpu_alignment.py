"""Exact batched pairwise alignment scores on the GPU: global (Needleman-Wunsch) or local (Smith-Waterman), affine gaps.

Every function scores integer substitution tables, so every value is an exact int32. A gap of n residues costs
`open + (n - 1) * extend`: `open` is the cost of a gap's first residue (BLAST's "existence 11, extension 1" is
`open=12, extend=1`; Biopython's global -10 / -0.5 doubled is `open=20, extend=1`). Global alignment charges end gaps.

Tokens index the substitution tables. A table is `(k, k)` int32; a protein table is (27, 27): the 20 residues, padding
(`PAD`, a zero row and column) and the six letters of `AMBIGUOUS`. Padded positions never feed a score, so any id
pads. A two-channel problem (Foldseek's 3Di plus amino acid) passes tokens `(n, l, 2)` and tables `(2, k, k)`, and a
cell scores the sum of the two channels' entries.

Two implementations compute the same numbers:

- `align_reference` (any device) computes rows one at a time, each vectorized over the batch and the columns, by the
  scan form of Gotoh's recursion (Farrar's and parasail's "scan" kernels): the vertical gap state is elementwise from
  the previous row, and the horizontal gap state is a prefix maximum along the row, which `torch.cummax` computes.
  Opening a horizontal gap from a cell whose best path already ends in a horizontal gap never beats extending it
  (open >= extend), so the prefix maximum may read the row before horizontal gaps are folded in.
- `align_triton` (CUDA) runs the same recursion with one Triton program per pair, the whole row in registers and the
  prefix maximum an in-register associative scan, so a launch scores every pair of a length bucket at once.

`align_profile_reference` and `align_profile_triton` are the same two with a per-position term on the first sequence:
cell (i, j) also scores `bias[i]`, an int32 (n, l_a), as Foldseek's composition-bias correction adds to its query
profile. The table entry points do not take it, so their kernels compile without it.

`local_spans` places each pair's best local alignment (its start and end in both sequences) by two reference scans,
without walking a path.

`nw_doubled` is the NW transformer's original labeler (BLOSUM62 doubled, open 20, extend 1, global), kept because its
grokking models read its constants.

Padded positions past a sequence's length never feed the cell (l_a, l_b) or a local maximum, so pairs of different
lengths share one padded grid.
"""

from __future__ import annotations

import numpy as np
import torch

from Bio.Align import substitution_matrices


RESIDUES = "ACDEFGHIKLMNPQRSTVWY"
PAD = 20  # token id of padding, outside the 20 residues
AMBIGUOUS = "XBZJUO"  # the other letters a protein may hold, token ids PAD + 1 to PAD + 6
TOKENS = PAD + 1 + len(AMBIGUOUS)  # 27, the side of a protein table
TOKEN_IDS = {residue: index for index, residue in enumerate(RESIDUES)} | {letter: PAD + 1 + index for index, letter in enumerate(AMBIGUOUS)}
TOKEN_INDEX = np.full(256, -1, dtype=np.int64)  # (256), each ASCII byte's token id, -1 for a letter no protein holds
TOKEN_INDEX[np.frombuffer("".join(TOKEN_IDS).encode("ascii"), dtype=np.uint8)] = list(TOKEN_IDS.values())
OPEN = 20  # doubled gap open: the first residue of a gap
EXTEND = 1  # doubled gap extend: every further residue
NEG = -(2 ** 28)  # minus infinity that survives adding a few thousand without overflow
BLOCKS = (64, 128, 256, 512, 1024, 2048)  # Triton row widths; a pair's shorter sequence plus one must fit
# BLASTp 2.17.0's scores for B, Z and J against RESIDUES then X, B, Z and J (`parity.residue_tool_scores`, 2026-10-19).
# X scores -1 against every letter, U scores as C and O as X; Biopython's BLOSUM62 differs for B, Z and J.
BLASTP_ROWS = {
    "B": (-2, -3, 4, 1, -3, -1, 0, -3, 0, -4, -3, 4, -2, 0, -1, 0, -1, -3, -4, -3, -1, 4, 0, -3),
    "Z": (-1, -3, 1, 4, -3, -2, 0, -3, 1, -3, -1, 0, -1, 4, 0, 0, -1, -2, -2, -2, -1, 0, 4, -3),
    "J": (-1, -1, -3, -3, 0, -4, -3, 3, -3, 3, 2, -3, -3, -2, -2, -2, -1, 2, -2, -1, -1, -3, -3, 3),
}
BLASTP_ALIASES = {"U": "C", "O": "X"}


def blosum62_table(scale: int, device: torch.device | str = "cpu") -> torch.Tensor:
    """`scale` x BLOSUM62 as BLASTp scores it, over `RESIDUES` then `AMBIGUOUS` (ids 21 to 26), with a zero padding row
    and column at `PAD`: (27, 27) int32."""
    blosum = substitution_matrices.load("BLOSUM62")
    named = RESIDUES + "XBZJ"
    scores = {(x, y): int(blosum[x][y]) for x in RESIDUES for y in RESIDUES}
    scores |= {(x, y): -1 for x in named for y in named if "X" in (x, y)}
    scores |= {(x, y): value for x, row in BLASTP_ROWS.items() for y, value in zip(named, row, strict=True)}
    scores |= {(y, x): value for (x, y), value in list(scores.items())}
    letter = {token: residue for residue, token in TOKEN_IDS.items()}
    table = torch.zeros(TOKENS, TOKENS, dtype=torch.int32)  # (27, 27)
    for i in letter:
        for j in letter:
            x, y = (BLASTP_ALIASES.get(letter[token], letter[token]) for token in (i, j))
            table[i, j] = scale * scores[x, y]
    return table.to(device)  # (27, 27)


def doubled_blosum62(device: torch.device) -> torch.Tensor:
    """2 x BLOSUM62 over the 20 residues in `RESIDUES` order, with a zero padding row and column: (21, 21) int32, the
    NW transformer's vocabulary."""
    return blosum62_table(2, device)[:PAD + 1, :PAD + 1]  # (21, 21)


def encode(sequences: list[str], length: int | None = None, alphabet: str = RESIDUES) -> tuple[torch.Tensor, torch.Tensor]:
    """Token ids of each sequence in `alphabet` order, padded with `len(alphabet)`, and the lengths: (n, l), (n).
    Proteins (`RESIDUES`, the default) may also hold `AMBIGUOUS`, as ids 21 to 26."""
    lengths = torch.tensor([len(sequence) for sequence in sequences], dtype=torch.int32)  # (n)
    width = int(lengths.max()) if length is None else length
    lookup = TOKEN_IDS if alphabet == RESIDUES else {residue: index for index, residue in enumerate(alphabet)}
    tokens = torch.full((len(sequences), width), len(alphabet), dtype=torch.int32)  # (n, l)
    for row, sequence in enumerate(sequences):
        tokens[row, : len(sequence)] = torch.tensor([lookup[residue] for residue in sequence], dtype=torch.int32)
    return tokens, lengths  # (n, l), (n)


def reverse_within_length(tokens: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
    """Each row's first `length` tokens in reverse order, padding left in place: (n, l) or (n, l, c) as given."""
    # tokens: (n, l) or (n, l, c); lengths: (n)
    n, l = tokens.shape[:2]
    positions = torch.arange(l, device=tokens.device)[None, :]  # (1, l)
    source = torch.where(positions < lengths[:, None], lengths[:, None] - 1 - positions, positions)  # (n, l)
    if tokens.ndim == 3:
        return torch.gather(tokens, 1, source[:, :, None].expand(-1, -1, tokens.shape[2]).long())  # (n, l, c)
    return torch.gather(tokens, 1, source.long())  # (n, l)


def _substitution(a: torch.Tensor, b: torch.Tensor, tables: torch.Tensor) -> torch.Tensor:
    """Cell scores of every pair: tokens (n, l_a[, c]) and (n, l_b[, c]), tables (k, k) or (c, k, k); returns (n, l_a, l_b)."""
    # a: (n, l_a[, c]); b: (n, l_b[, c]); tables: (k, k) or (c, k, k)
    if tables.ndim == 2:
        return tables[a.long()[:, :, None], b.long()[:, None, :]]  # (n, l_a, l_b)
    channels = [tables[c][a[..., c].long()[:, :, None], b[..., c].long()[:, None, :]] for c in range(tables.shape[0])]
    return torch.stack(channels).sum(dim=0, dtype=torch.int32)  # (n, l_a, l_b)


def _check(a: torch.Tensor, b: torch.Tensor, len_a: torch.Tensor, len_b: torch.Tensor, tables: torch.Tensor,
           open: int, extend: int) -> None:
    # a: (n, l_a[, c]); b: (n, l_b[, c]); len_a, len_b: (n); tables: (k, k) or (c, k, k)
    if tables.dtype != torch.int32 or tables.ndim not in (2, 3) or tables.shape[-1] != tables.shape[-2]:
        raise ValueError("Tables are int32, (k, k) or (c, k, k).")
    channels = 1 if tables.ndim == 2 else tables.shape[0]
    if a.ndim != (2 if channels == 1 else 3) or b.ndim != a.ndim or (channels > 1 and (a.shape[2], b.shape[2]) != (channels, channels)):
        raise ValueError("Tokens are (n, l) for one table and (n, l, c) for c tables.")
    if a.shape[0] != b.shape[0] or len_a.shape != (a.shape[0],) or len_b.shape != (a.shape[0],):
        raise ValueError("Both token batches and both length vectors must hold the same pairs.")
    if not open >= extend >= 0:
        raise ValueError("The scan recursion needs open >= extend >= 0.")
    if bool((len_a < 1).any()) or bool((len_b < 1).any()) or bool((len_a > a.shape[1]).any()) or bool((len_b > b.shape[1]).any()):
        raise ValueError("Every length is at least 1 and within its padded width.")


def align_reference(a: torch.Tensor, b: torch.Tensor, len_a: torch.Tensor, len_b: torch.Tensor, tables: torch.Tensor, *,
                    open: int, extend: int, local: bool,
                    ends: bool = False) -> torch.Tensor | tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Exact affine alignment score of each pair by the row scan: tokens (n, l_a[, c]), (n, l_b[, c]); returns (n) int32.

    With `ends` (local only), also the cell where each pair's best alignment ends, 1-based in a and in b (n) each: the
    first row reaching the best score, and its first column reaching it; (0, 0) for a pair whose best score is 0."""
    # a: (n, l_a[, c]); b: (n, l_b[, c]); len_a, len_b: (n); tables: (k, k) or (c, k, k)
    _check(a, b, len_a, len_b, tables, open, extend)
    if ends and not local:
        raise ValueError("Ends belong to a local alignment; a global one ends at both lengths.")
    return _scan(_substitution(a, b, tables), len_a, len_b, open=open, extend=extend, local=local, ends=ends)  # (n)


def align_profile_reference(a: torch.Tensor, b: torch.Tensor, len_a: torch.Tensor, len_b: torch.Tensor,
                            tables: torch.Tensor, bias: torch.Tensor, *, open: int, extend: int, local: bool) -> torch.Tensor:
    """`align_reference` with `bias[:, i]` added to every cell of a's position i: bias (n, l_a) int32; returns (n) int32."""
    # a: (n, l_a[, c]); b: (n, l_b[, c]); len_a, len_b: (n); tables: (k, k) or (c, k, k); bias: (n, l_a)
    _check(a, b, len_a, len_b, tables, open, extend)
    _check_bias(a, bias)
    return _scan(_substitution(a, b, tables) + bias[:, :, None], len_a, len_b, open=open, extend=extend, local=local)  # (n)


def _check_bias(a: torch.Tensor, bias: torch.Tensor) -> None:
    # a: (n, l_a[, c]); bias: (n, l_a)
    if bias.dtype != torch.int32 or bias.shape != a.shape[:2] or bias.device != a.device:
        raise ValueError("The bias is int32 (n, l_a), one entry per position of the first sequence, on its device.")


def _scan(substitution: torch.Tensor, len_a: torch.Tensor, len_b: torch.Tensor, *, open: int, extend: int, local: bool,
          ends: bool = False) -> torch.Tensor | tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """The row scan over given cell scores (n, l_a, l_b): `align_reference`'s recursion and returns."""
    # substitution: (n, l_a, l_b); len_a, len_b: (n)
    n, l_a, l_b = substitution.shape
    device = substitution.device
    columns = torch.arange(l_b + 1, device=device, dtype=torch.int32)  # (l_b + 1)
    inside = (columns[None, :] >= 1) & (columns[None, :] <= len_b[:, None])  # (n, l_b + 1)
    if local:
        h = torch.zeros(n, l_b + 1, device=device, dtype=torch.int32)  # (n, l_b + 1)
    else:
        h = torch.where(columns == 0, 0, -(open + (columns - 1) * extend)).expand(n, -1).contiguous()  # (n, l_b + 1)
    f = torch.full((n, l_b + 1), NEG, device=device, dtype=torch.int32)  # (n, l_b + 1), vertical gap state
    best = torch.zeros(n, device=device, dtype=torch.int32)  # (n)
    end_a = torch.zeros(n, device=device, dtype=torch.int64)  # (n)
    end_b = torch.zeros(n, device=device, dtype=torch.int64)  # (n)
    rows = torch.arange(n, device=device)  # (n)
    for i in range(1, l_a + 1):
        f = torch.maximum(f - extend, h - open)  # (n, l_b + 1)
        boundary = torch.full((n, 1), 0 if local else -(open + (i - 1) * extend), device=device, dtype=torch.int32)  # (n, 1)
        diagonal = h[:, :-1] + substitution[:, i - 1]  # (n, l_b)
        before_gaps = torch.cat([boundary, torch.maximum(diagonal, f[:, 1:])], dim=1)  # (n, l_b + 1)
        if local:
            before_gaps = before_gaps.clamp_min(0)  # (n, l_b + 1)
        # Horizontal gap into column j from any k < j: max_k (H[k] + k e) - open - (j - 1) e.
        carried = torch.cummax(before_gaps + columns[None, :] * extend, dim=1).values  # (n, l_b + 1)
        e = torch.cat([torch.full((n, 1), NEG, device=device, dtype=torch.int32),
                       carried[:, :-1] - open - (columns[None, 1:] - 1) * extend], dim=1)  # (n, l_b + 1)
        h = torch.maximum(before_gaps, e)  # (n, l_b + 1)
        live = i <= len_a  # (n)
        if local:
            within = torch.where(inside, h, 0)  # (n, l_b + 1)
            row_best = within.amax(dim=1)  # (n)
            if ends:
                better = live & (row_best > best)  # (n)
                end_a = torch.where(better, i, end_a)  # (n)
                end_b = torch.where(better, within.argmax(dim=1), end_b)  # (n), the first column reaching the row's best
            best = torch.where(live, torch.maximum(best, row_best), best)  # (n)
        else:
            best = torch.where(len_a == i, h[rows, len_b.long()], best)  # (n)
    if ends:
        return best, end_a, end_b  # (n) each
    return best  # (n)


def local_spans(a: torch.Tensor, b: torch.Tensor, len_a: torch.Tensor, len_b: torch.Tensor, tables: torch.Tensor, *,
                open: int, extend: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Where each pair's best local alignment lies, without walking its path: the score and the 1-based inclusive start
    and end in a and in b, (n) each. The end is `align_reference`'s; the start is where the best alignment of the two
    prefixes read backward ends, since the best alignment read backward from its end is the best over those prefixes.
    Between equal-scoring alignments the start may come from another of them. A pair scoring 0 gets zeros."""
    # a: (n, l_a[, c]); b: (n, l_b[, c]); len_a, len_b: (n); tables: (k, k) or (c, k, k)
    score, end_a, end_b = align_reference(a, b, len_a, len_b, tables, open=open, extend=extend, local=True, ends=True)
    prefix_a, prefix_b = end_a.clamp_min(1).to(len_a.dtype), end_b.clamp_min(1).to(len_b.dtype)  # (n) each
    back, back_a, back_b = align_reference(reverse_within_length(a, prefix_a), reverse_within_length(b, prefix_b), prefix_a,
                                           prefix_b, tables, open=open, extend=extend, local=True, ends=True)  # (n) each
    scored = score > 0  # (n)
    if not torch.equal(back[scored], score[scored]):
        raise RuntimeError("The prefixes read backward score other than the pair; the scan disagrees with itself.")
    start_a = torch.where(scored, end_a - back_a + 1, 0)  # (n)
    start_b = torch.where(scored, end_b - back_b + 1, 0)  # (n)
    return score, start_a, end_a, start_b, end_b  # (n) each


def nw_doubled(a: torch.Tensor, b: torch.Tensor, len_a: torch.Tensor, len_b: torch.Tensor, table: torch.Tensor,
               return_grid: bool = False) -> torch.Tensor | tuple[torch.Tensor, torch.Tensor]:
    """Doubled NW scores of each pair: tokens a (n, l_a) and b (n, l_b), lengths (n), table (21, 21); returns (n) int32.

    With `return_grid`, also the whole score matrix (n, l_a + 1, l_b + 1): cell (i, j) is the doubled NW score of the
    prefixes a[:i] and b[:j], every one of them an exactly labeled pair in its own right.
    """
    # a: (n, l_a); b: (n, l_b); len_a, len_b: (n); table: (21, 21)
    n, l_a = a.shape
    l_b = b.shape[1]
    device = a.device
    columns = torch.arange(l_b + 1, device=device, dtype=torch.int32)  # (l_b + 1)
    # Row 0: a leading gap of j residues in A.
    h = torch.where(columns == 0, 0, -(OPEN + (columns - 1) * EXTEND)).expand(n, -1).contiguous()  # (n, l_b + 1)
    f = torch.full((n, l_b + 1), NEG, device=device, dtype=torch.int32)  # (n, l_b + 1), vertical gap state
    substitution = table[a.long()[:, :, None], b.long()[:, None, :]]  # (n, l_a, l_b)
    offset = columns[None, :]  # (1, l_b + 1), adds k so a prefix maximum can carry the extension cost
    corner = torch.zeros(n, device=device, dtype=torch.int32)  # (n)
    rows = torch.arange(n, device=device)  # (n)
    grid = [h] if return_grid else []
    for i in range(1, l_a + 1):
        f = torch.maximum(f - EXTEND, h - OPEN)  # (n, l_b + 1)
        boundary = torch.full((n, 1), -(OPEN + (i - 1) * EXTEND), device=device, dtype=torch.int32)  # (n, 1), column 0
        diagonal = h[:, :-1] + substitution[:, i - 1]  # (n, l_b)
        before_gaps = torch.cat([boundary, torch.maximum(diagonal, f[:, 1:])], dim=1)  # (n, l_b + 1)
        # Horizontal gap into column j from any k < j: max_k (H[k] + k) - OPEN - (j - 1 - k) * EXTEND, with EXTEND = 1.
        carried = torch.cummax(before_gaps + offset * EXTEND, dim=1).values  # (n, l_b + 1)
        e = torch.cat([torch.full((n, 1), NEG, device=device, dtype=torch.int32),
                       carried[:, :-1] - OPEN - (offset[:, 1:] - 1) * EXTEND], dim=1)  # (n, l_b + 1)
        h = torch.maximum(before_gaps, e)  # (n, l_b + 1)
        if return_grid:
            grid.append(h)
        done = len_a == i  # (n)
        corner = torch.where(done, h[rows, len_b.long()], corner)  # (n)
    if return_grid:
        return corner, torch.stack(grid, dim=1)  # (n), (n, l_a + 1, l_b + 1)
    return corner  # (n)


try:
    import triton
    import triton.language as tl
except ImportError:  # CPU machines: align_triton refuses, align_reference still works
    triton = None


if triton is not None:
    # Triton reads a kernel's annotations as its argument types (an `int` annotation becomes a malformed type), so the
    # runtime arguments stay unannotated and the compile-time ones keep Triton's upper-case constexpr names.

    @triton.jit
    def _maximum(x, y):  # noqa: missing-annotation
        return tl.maximum(x, y)

    @triton.jit
    def _align_kernel(a_ptr, b_ptr, len_a_ptr, len_b_ptr, table_ptr, out_ptr, scratch_ptr, stride_a, stride_b,  # noqa: missing-annotation
                      row_bias_ptr, col_bias_ptr, stride_bias, open, extend, K: tl.constexpr, CHANNELS: tl.constexpr,  # noqa: missing-annotation, naming
                      LOCAL: tl.constexpr, BLOCK: tl.constexpr, BIAS: tl.constexpr, UNGAPPED: tl.constexpr = False):  # noqa: missing-annotation, naming
        # One program scores one pair; columns j = 0..BLOCK-1 hold the row, j = 0 the boundary column. With BIAS a
        # cell (i, j) also scores row_bias[i] + col_bias[j]; the caller zeroes the side that is not the profile's.
        # UNGAPPED (local only) drops both gap states: the best diagonal segment, a cascade's cheap second stage.
        pair = tl.program_id(0)
        len_a = tl.load(len_a_ptr + pair)
        len_b = tl.load(len_b_ptr + pair)
        columns = tl.arange(0, BLOCK)  # (BLOCK)
        inside = (columns >= 1) & (columns <= len_b)  # (BLOCK)
        b_row = b_ptr + pair.to(tl.int64) * stride_b
        b0 = tl.load(b_row + (columns - 1) * CHANNELS, mask=inside, other=K - 1)  # (BLOCK)
        if CHANNELS == 2:
            b1 = tl.load(b_row + (columns - 1) * CHANNELS + 1, mask=inside, other=K - 1)  # (BLOCK)
        if BIAS:
            row_bias = row_bias_ptr + pair.to(tl.int64) * stride_bias
            col_bias = tl.load(col_bias_ptr + pair.to(tl.int64) * stride_bias + (columns - 1), mask=inside, other=0)  # (BLOCK)
        if LOCAL:
            h = tl.zeros([BLOCK], dtype=tl.int32)  # (BLOCK)
        else:
            h = tl.where(columns == 0, 0, -(open + (columns - 1) * extend))  # (BLOCK)
        f = tl.full([BLOCK], -(2 ** 28), dtype=tl.int32)  # (BLOCK), vertical gap state
        best = tl.zeros([1], dtype=tl.int32).sum()  # ()
        a_row = a_ptr + pair.to(tl.int64) * stride_a
        scratch = scratch_ptr + pair.to(tl.int64) * (BLOCK + 1)
        tl.store(scratch, 0)
        for i in range(1, len_a + 1):
            a0 = tl.load(a_row + (i - 1) * CHANNELS)
            substitution = tl.load(table_ptr + a0 * K + b0)  # (BLOCK)
            if CHANNELS == 2:
                a1 = tl.load(a_row + (i - 1) * CHANNELS + 1)
                substitution += tl.load(table_ptr + K * K + a1 * K + b1)  # (BLOCK)
            if BIAS:
                substitution += col_bias + tl.load(row_bias + (i - 1))  # (BLOCK)
            # The diagonal reads the previous row one column to the left: shift it through this pair's scratch row.
            tl.store(scratch + 1 + columns, h)
            tl.debug_barrier()
            shifted = tl.load(scratch + columns)  # (BLOCK)
            tl.debug_barrier()
            if UNGAPPED:
                h = tl.where(columns == 0, 0, tl.maximum(shifted + substitution, 0))  # (BLOCK)
            else:
                f = tl.maximum(f - extend, h - open)  # (BLOCK)
                before = tl.maximum(shifted + substitution, f)  # (BLOCK)
                if LOCAL:
                    before = tl.maximum(before, 0)
                    before = tl.where(columns == 0, 0, before)  # (BLOCK)
                else:
                    before = tl.where(columns == 0, -(open + (i - 1) * extend), before)  # (BLOCK)
                # Including k = j in the prefix maximum adds before[j] - open + extend <= before[j], which changes nothing.
                carried = tl.associative_scan(before + columns * extend, 0, _maximum)  # (BLOCK)
                h = tl.maximum(before, carried - open - (columns - 1) * extend)  # (BLOCK)
            h = tl.where(columns <= len_b, h, -(2 ** 28))  # (BLOCK)
            if LOCAL:
                best = tl.maximum(best, tl.max(tl.where(inside, h, 0), axis=0))
        if LOCAL:
            tl.store(out_ptr + pair, best)
        else:
            tl.store(out_ptr + pair, tl.sum(tl.where(columns == len_b, h, 0), axis=0))


def align_triton(a: torch.Tensor, b: torch.Tensor, len_a: torch.Tensor, len_b: torch.Tensor, tables: torch.Tensor, *,
                 open: int, extend: int, local: bool, num_warps: int | None = None) -> torch.Tensor:
    """`align_reference`'s numbers from one Triton program per pair, bucketed by the shorter length; returns (n) int32.

    The tables must be symmetric (each channel's), so a pair may be scored with either sequence along the row; the
    shorter one is, which keeps the row narrow. Tokens and lengths live on one CUDA device.
    """
    # a: (n, l_a[, c]); b: (n, l_b[, c]); len_a, len_b: (n); tables: (k, k) or (c, k, k)
    return _triton_scores(a, b, len_a, len_b, tables, None, open=open, extend=extend, local=local, num_warps=num_warps)  # (n)


def align_ungapped_triton(a: torch.Tensor, b: torch.Tensor, len_a: torch.Tensor, len_b: torch.Tensor, tables: torch.Tensor,
                          *, num_warps: int | None = None) -> torch.Tensor:
    """Each pair's best ungapped local segment (the best diagonal's maximum subarray) from `align_triton`'s kernel
    with both gap states dropped; returns (n) int32. `align_reference` with gaps priced out (`open = extend` above
    any score) gives the same numbers."""
    # a: (n, l_a[, c]); b: (n, l_b[, c]); len_a, len_b: (n); tables: (k, k) or (c, k, k)
    return _triton_scores(a, b, len_a, len_b, tables, None, open=0, extend=0, local=True, num_warps=num_warps, ungapped=True)  # (n)


def align_profile_triton(a: torch.Tensor, b: torch.Tensor, len_a: torch.Tensor, len_b: torch.Tensor, tables: torch.Tensor,
                         bias: torch.Tensor, *, open: int, extend: int, local: bool, num_warps: int | None = None) -> torch.Tensor:
    """`align_profile_reference`'s numbers from `align_triton`'s kernel: bias (n, l_a) int32 on a's positions, which
    moves to the columns of a pair scored with a along them; returns (n) int32."""
    # a: (n, l_a[, c]); b: (n, l_b[, c]); len_a, len_b: (n); tables: (k, k) or (c, k, k); bias: (n, l_a)
    _check_bias(a, bias)
    return _triton_scores(a, b, len_a, len_b, tables, bias, open=open, extend=extend, local=local, num_warps=num_warps)  # (n)


def _triton_scores(a: torch.Tensor, b: torch.Tensor, len_a: torch.Tensor, len_b: torch.Tensor, tables: torch.Tensor,
                   bias: torch.Tensor | None, *, open: int, extend: int, local: bool, num_warps: int | None,
                   ungapped: bool = False) -> torch.Tensor:
    # a: (n, l_a[, c]); b: (n, l_b[, c]); len_a, len_b: (n); tables: (k, k) or (c, k, k); bias: (n, l_a) or None
    if triton is None or a.device.type != "cuda":
        raise RuntimeError("align_triton needs Triton and CUDA tensors; align_reference runs anywhere.")
    _check(a, b, len_a, len_b, tables, open, extend)
    if not torch.equal(tables, tables.transpose(-1, -2)):
        raise ValueError("align_triton orients each pair by length, so every table must be symmetric.")
    channels = 1 if tables.ndim == 2 else tables.shape[0]
    if channels > 2:
        raise ValueError("align_triton scores one or two channels.")
    k = tables.shape[-1]
    width = max(a.shape[1], b.shape[1])
    a = torch.nn.functional.pad(a, (0, 0, 0, width - a.shape[1]) if channels == 2 else (0, width - a.shape[1]), value=k - 1)  # (n, w[, c])
    b = torch.nn.functional.pad(b, (0, 0, 0, width - b.shape[1]) if channels == 2 else (0, width - b.shape[1]), value=k - 1)  # (n, w[, c])
    swap = len_b > len_a  # (n)
    view = (-1, 1, 1) if channels == 2 else (-1, 1)
    rows = torch.where(swap.view(view), b, a).to(torch.int32).contiguous()  # (n, w[, c]), the longer sequence
    cols = torch.where(swap.view(view), a, b).to(torch.int32).contiguous()  # (n, w[, c]), the shorter sequence
    len_rows = torch.where(swap, len_b, len_a).to(torch.int32).contiguous()  # (n)
    len_cols = torch.where(swap, len_a, len_b).to(torch.int32).contiguous()  # (n)
    if bias is not None:  # the profile follows a: along the rows unless the pair is swapped
        padded = torch.nn.functional.pad(bias, (0, width - bias.shape[1]))  # (n, w)
        row_bias = torch.where(swap[:, None], 0, padded).to(torch.int32)  # (n, w)
        col_bias = torch.where(swap[:, None], padded, 0).to(torch.int32)  # (n, w)
    flat_tables = tables.to(torch.int32).contiguous()  # (k, k) or (c, k, k)
    scores = torch.empty(a.shape[0], device=a.device, dtype=torch.int32)  # (n)
    need = len_cols + 1  # (n)
    if int(need.max()) > BLOCKS[-1]:
        raise ValueError(f"align_triton scores pairs whose shorter sequence is under {BLOCKS[-1]} residues.")
    lower = 0
    for block in BLOCKS:
        members = torch.nonzero((need > lower) & (need <= block)).flatten()  # (m)
        lower = block
        if members.numel() == 0:
            continue
        scratch = torch.empty(members.numel() * (block + 1), device=a.device, dtype=torch.int32)  # (m * (block + 1))
        out = torch.empty(members.numel(), device=a.device, dtype=torch.int32)  # (m)
        bucket_rows, bucket_cols = rows[members].contiguous(), cols[members].contiguous()  # (m, w[, c]) each
        # Two warps measured fastest on a GH200 (2026-10-16): 4.3M pairs a second at mean length 238 (243 GCUPS),
        # against 4.0M at four warps and 2.8M at eight.
        warps = num_warps or (2 if block <= 1024 else 4)
        # Without a profile the bias pointers are never read (BIAS compiles them out); `out` stands in for them.
        bucket_row_bias = row_bias[members].contiguous() if bias is not None else out  # (m, w)
        bucket_col_bias = col_bias[members].contiguous() if bias is not None else out  # (m, w)
        _align_kernel[(members.numel(),)](
            bucket_rows, bucket_cols, len_rows[members].contiguous(), len_cols[members].contiguous(), flat_tables, out,
            scratch, bucket_rows.stride(0), bucket_cols.stride(0), bucket_row_bias, bucket_col_bias,
            bucket_row_bias.stride(0) if bias is not None else 0, open, extend,
            K=k, CHANNELS=channels, LOCAL=local, BLOCK=block, BIAS=bias is not None, UNGAPPED=ungapped, num_warps=warps,
        )
        scores[members] = out
    return scores  # (n)
