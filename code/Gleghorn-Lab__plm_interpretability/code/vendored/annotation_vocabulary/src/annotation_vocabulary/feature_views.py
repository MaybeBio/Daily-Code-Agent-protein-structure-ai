"""Array-like views of an extraction's stored features, and the function that opens them.

Study and analysis code was written against memory-mapped arrays: `pooled[rows, columns]` for a
block of features, `pooled[start:stop]` for a block of proteins, and `residues[offset:offset + n]`
for one protein's TopK track. `open_extraction` gives those same expressions over the feature
store, so a consumer changes where its arrays come from and nothing else.

Two things differ from a memory map, and both are visible in the API.

- Stored rows are whole proteins, so a block of columns costs a pass over the rows. `PooledColumns`
  reads a window of columns for every protein once, under a memory budget, and serves later column
  requests from that window. A caller that knows its column plan passes it to `hint_columns`.
- Residue rows have no global array. `ResidueTracks` maps a global residue row to its protein by
  the index's `residue_offset` and `n_residues`, reads that protein's row, and refuses any request
  that does not land inside one protein's span, or a stored row whose length differs from the
  index. The views present the old dtypes: counts as uint16 and residue indices as uint16 whenever
  the codebook fits, so downstream arithmetic is unchanged.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastplms.features import FeatureReader, TopKRow
from .feature_cache import (
    POOLED_COUNT,
    POOLED_MAX,
    POOLED_MEAN,
    POOLED_ROLES,
    RESIDUE_TOPK,
    ROLES,
    check_sequence_alignment,
    default_store_root,
    discover_features,
    read_sequences,
)


DEFAULT_COLUMN_BUDGET_BYTES = 4 * 1024**3
READ_CHUNK = 2048
CACHED_PROTEINS = 8
_POOLING_ROLES = {"max": POOLED_MAX, "mean": POOLED_MEAN, "count": POOLED_COUNT}
_NUMPY_DTYPES = {torch.float32: np.float32, torch.float16: np.float16}


def _axis(key: Any, length: int) -> tuple[np.ndarray, bool]:
    """Positions along one axis for an int, slice, boolean mask, or integer array key."""
    if isinstance(key, (int, np.integer)):
        position = int(key) + (length if int(key) < 0 else 0)
        if not 0 <= position < length:
            raise IndexError(f"index {int(key)} is out of bounds for an axis of length {length}")
        return np.array([position], dtype=np.int64), True  # (1,)
    if isinstance(key, slice):
        return np.arange(length, dtype=np.int64)[key], False  # (m,)
    array = np.asarray(key)
    if array.dtype == bool:
        if array.shape != (length,):
            raise IndexError("a boolean mask must match the axis length")
        return np.flatnonzero(array).astype(np.int64), False  # (m,)
    if array.ndim != 1 or (array.size and not np.issubdtype(array.dtype, np.integer)):
        raise TypeError("only integer, slice, boolean, and np.ix_ indexing is supported")
    positions = array.astype(np.int64)
    positions = np.where(positions < 0, positions + length, positions)
    if positions.size and (positions.min() < 0 or positions.max() >= length):
        raise IndexError(f"an index is out of bounds for an axis of length {length}")
    return positions, False  # (m,)


class PooledColumns:
    """A `(n, c)` pooled feature over `n` proteins, indexed like the array it replaces.

    Row `i` is the stored row of `sequences[i]`, so repeated sequences read one stored row.
    Supported keys are an int, slice, boolean mask, or integer array for either axis, and the
    `np.ix_` pair. Two bare integer arrays (pairwise indexing) are refused rather than guessed.
    """

    ndim = 2

    def __init__(
        self, reader: FeatureReader, sequences: Sequence[str], *, dtype: Any,
        budget_bytes: int = DEFAULT_COLUMN_BUDGET_BYTES, location: dict[str, Any] | None = None,
    ) -> None:
        self._reader = reader
        self._sequences = tuple(sequences)
        self.dtype = np.dtype(dtype)
        self.width = int(reader.spec.width)
        self.shape = (len(self._sequences), self.width)
        self.location = location
        self._budget = int(budget_bytes)
        self._window: tuple[np.ndarray, np.ndarray] | None = None  # (columns, (n, w) values)
        self._hint: np.ndarray | None = None

    def __len__(self) -> int:
        return self.shape[0]

    @property
    def budget_bytes(self) -> int:
        """The memory one column window may use."""
        return self._budget

    def hint_columns(self, columns: Sequence[int] | np.ndarray) -> None:
        """Tell the view which columns will be requested, so windows fill with those and no others."""
        # columns: (f,)
        self._hint = np.unique(np.asarray(columns, dtype=np.int64))

    def __array__(self, dtype: Any = None, copy: Any = None) -> np.ndarray:
        block = self._read_rows(np.arange(len(self), dtype=np.int64))  # (n, c)
        return block if dtype is None else block.astype(dtype, copy=False)  # (n, c)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, tuple):
            if len(key) != 2:
                raise IndexError("a pooled view has two axes")
            row_key, column_key = key
        else:
            row_key, column_key = key, slice(None)
        both_arrays = all(isinstance(part, (np.ndarray, list)) for part in (row_key, column_key))
        if both_arrays and np.ndim(row_key) == 2 and np.ndim(column_key) == 2:
            if np.shape(row_key)[1] != 1 or np.shape(column_key)[0] != 1:
                raise IndexError("np.ix_ indexing needs a column of rows and a row of columns")
            row_key, column_key = np.asarray(row_key)[:, 0], np.asarray(column_key)[0]
        elif both_arrays:
            raise TypeError("pairwise integer-array indexing is not supported; use np.ix_")
        rows, row_scalar = _axis(row_key, self.shape[0])
        columns, column_scalar = _axis(column_key, self.width)
        block = self._gather(rows, columns)  # (m, f)
        if row_scalar and column_scalar:
            return block[0, 0]
        if row_scalar:
            return block[0]
        if column_scalar:
            return block[:, 0]
        return block

    def _gather(self, rows: np.ndarray, columns: np.ndarray) -> np.ndarray:
        # rows: (m,); columns: (f,)
        if rows.size == 0 or columns.size == 0:
            return np.empty((rows.size, columns.size), dtype=self.dtype)  # (m, f)
        if columns.size == self.width and np.array_equal(columns, np.arange(self.width)):
            return self._read_rows(rows)  # (m, c)
        wanted = np.unique(columns)  # (f,) sorted
        if self._window is None or not np.isin(wanted, self._window[0], assume_unique=True).all():
            self._window = None  # release the old window before allocating the next
            chosen = self._choose_window(wanted)
            self._window = (chosen, self._read_columns(chosen))
        offsets = np.searchsorted(self._window[0], columns)  # (f,) positions inside the window
        return self._window[1][np.ix_(rows, offsets)]  # (m, f)

    def _choose_window(self, wanted: np.ndarray) -> np.ndarray:
        """The columns to hold next: everything wanted, then as many neighbours as the budget allows."""
        # wanted: (f,)
        room = max(1, self._budget // max(1, self.shape[0] * self.dtype.itemsize))
        if self._hint is not None:
            later = self._hint[self._hint >= wanted[0]]
            extra = later[~np.isin(later, wanted)][: max(0, room - wanted.size)]
            return np.union1d(wanted, extra)  # (w,)
        if wanted[-1] - wanted[0] + 1 <= room:
            return np.arange(wanted[0], min(self.width, wanted[0] + room), dtype=np.int64)  # (w,)
        return wanted  # (f,)

    def _rows(self, positions: np.ndarray) -> Any:
        # positions: (m,)
        for start in range(0, positions.size, READ_CHUNK):
            chunk = positions[start:start + READ_CHUNK]
            stored = self._reader.read([self._sequences[int(position)] for position in chunk])
            yield start, torch.stack(stored).numpy()  # (m, c) in the stored dtype

    def _read_rows(self, positions: np.ndarray) -> np.ndarray:
        # positions: (m,)
        block = np.empty((positions.size, self.width), dtype=self.dtype)  # (m, c)
        for start, rows in self._rows(positions):
            block[start:start + len(rows)] = rows.astype(self.dtype, copy=False)
        return block  # (m, c)

    def _read_columns(self, columns: np.ndarray) -> np.ndarray:
        # columns: (w,)
        block = np.empty((self.shape[0], columns.size), dtype=self.dtype)  # (n, w)
        contiguous = columns[-1] - columns[0] + 1 == columns.size
        for start, rows in self._rows(np.arange(self.shape[0], dtype=np.int64)):
            part = rows[:, columns[0]:columns[-1] + 1] if contiguous else rows[:, columns]  # (m, w)
            block[start:start + len(rows)] = part.astype(self.dtype, copy=False)
        return block  # (n, w)


class TrackSource:
    """Per-protein TopK rows of `residue_topk`, addressed by the index's residue coordinates.

    `offsets` and `lengths` are the index columns `residue_offset` and `n_residues`. Offsets may
    be in any order, as an old cache's were, but spans must not overlap. Reading a protein checks
    that the stored row has exactly the length the index promises.
    """

    def __init__(
        self, reader: FeatureReader, sequences: Sequence[str], offsets: np.ndarray, lengths: np.ndarray,
    ) -> None:
        # offsets: (n,); lengths: (n,)
        self._reader = reader
        self._sequences = tuple(sequences)
        self._lengths = np.asarray(lengths, dtype=np.int64)  # (n,)
        offsets = np.asarray(offsets, dtype=np.int64)  # (n,)
        if not len(offsets) == len(self._lengths) == len(self._sequences):
            raise ValueError("Residue offsets, lengths, and sequences must align protein by protein")
        present = np.flatnonzero(self._lengths > 0)  # proteins that own residue rows
        order = present[np.argsort(offsets[present], kind="stable")]
        self._order = order  # (p,) protein positions by residue offset
        self._starts = offsets[order]  # (p,)
        self._stops = self._starts + self._lengths[order]  # (p,)
        if np.any(self._stops[:-1] > self._starts[1:]) or np.any(self._starts < 0):
            raise ValueError("Residue spans overlap or start below zero")
        self.rows = int(self._stops[-1]) if len(order) else 0
        self.k = int(reader.spec.sparse_count)
        self.index_dtype = np.dtype(np.uint16 if reader.spec.width <= np.iinfo(np.uint16).max + 1 else np.int32)
        self.value_dtype = np.dtype(_NUMPY_DTYPES[reader.spec.dtype])
        self._cache: OrderedDict[int, tuple[np.ndarray, np.ndarray]] = OrderedDict()

    def protein(self, position: int) -> tuple[np.ndarray, np.ndarray]:
        """Indices and values `(l, k)` of one protein, read-only, from a small least-recently-used cache."""
        cached = self._cache.get(position)
        if cached is not None:
            self._cache.move_to_end(position)
            return cached  # ((l, k), (l, k)) indices and values
        entry = self._entry(position, self._reader.read_topk([self._sequences[position]])[0])
        self._cache[position] = entry
        if len(self._cache) > CACHED_PROTEINS:
            self._cache.popitem(last=False)
        return entry  # ((l, k), (l, k)) indices and values

    def proteins(self, positions: Sequence[int]) -> list[tuple[np.ndarray, np.ndarray]]:
        """Indices and values of several proteins in the order asked, with one store lookup.

        The rows go straight to the caller: reading a block of proteins once must not push the
        proteins a slice consumer is walking out of the small cache.
        """
        wanted = [int(position) for position in positions]
        absent = [position for position in dict.fromkeys(wanted) if position not in self._cache]
        stored = self._reader.read_topk([self._sequences[position] for position in absent]) if absent else []
        fresh = {position: self._entry(position, row) for position, row in zip(absent, stored, strict=True)}
        return [fresh[position] if position in fresh else self._cache[position] for position in wanted]  # ((l, k), (l, k)) indices and values per position

    def _entry(self, position: int, stored: TopKRow) -> tuple[np.ndarray, np.ndarray]:
        indices = stored.indices.numpy()  # (l, k) int32
        values = stored.values.numpy()  # (l, k)
        if indices.shape[0] != int(self._lengths[position]):
            raise ValueError(
                f"Protein {position} stores {indices.shape[0]} residues; the index promises "
                f"{int(self._lengths[position])}"
            )
        entry = (indices.astype(self.index_dtype), values.astype(self.value_dtype, copy=False))
        for array in entry:
            array.flags.writeable = False
        return entry  # ((l, k), (l, k)) indices and values

    def locate(self, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Protein positions and local residue rows of global residue `rows`, or IndexError."""
        # rows: (m,)
        slot = np.searchsorted(self._starts, rows, side="right") - 1  # (m,)
        inside = (slot >= 0) & (rows < self._stops[np.maximum(slot, 0)])
        if not inside.all():
            bad = int(rows[~inside][0])
            raise IndexError(f"residue row {bad} lies outside every protein's span")
        return self._order[slot], rows - self._starts[slot]  # ((m,), (m,)) protein positions, local residue rows


class ResidueTracks:
    """One component of the `(r, k)` TopK arrays, `indices` or `values`, over global residue rows."""

    ndim = 2

    def __init__(self, source: TrackSource, component: str) -> None:
        if component not in ("indices", "values"):
            raise ValueError("component must be 'indices' or 'values'")
        self._source = source
        self._which = 0 if component == "indices" else 1
        self.dtype = source.index_dtype if component == "indices" else source.value_dtype
        self.shape = (source.rows, source.k)

    def __len__(self) -> int:
        return self.shape[0]

    def __getitem__(self, key: Any) -> np.ndarray:
        if isinstance(key, tuple):
            if len(key) != 2:
                raise IndexError("a residue view has two axes")
            row_key, column_key = key
            block = self[row_key]
            if isinstance(row_key, (int, np.integer)):
                return block[column_key]  # (w,) for a slice or array column_key, () for an int
            if isinstance(row_key, (np.ndarray, list)) and isinstance(column_key, (np.ndarray, list)):
                return block[np.arange(len(block)), column_key]  # (m,)
            return block[:, column_key]  # (m, w), or (m,) for an int column_key
        if isinstance(key, (int, np.integer)):
            rows, _ = _axis(key, self.shape[0])
            return self._gather(rows)[0]  # (k,)
        if isinstance(key, slice):
            start, stop, step = key.indices(self.shape[0])
            if step == 1:
                return self._span(start, stop)  # (m, k)
        rows, _ = _axis(key, self.shape[0])
        return self._gather(rows)  # (m, k)

    def _span(self, start: int, stop: int) -> np.ndarray:
        """Rows `[start, stop)` read protein by protein; the range must be covered without gaps."""
        if stop <= start:
            return np.empty((0, self.shape[1]), dtype=self.dtype)  # (0, k)
        pieces = []
        row = start
        while row < stop:
            proteins, local = self._source.locate(np.array([row], dtype=np.int64))
            position, first = int(proteins[0]), int(local[0])
            block = self._source.protein(position)[self._which]  # (l, k)
            take = min(stop - row, block.shape[0] - first)
            pieces.append(block[first:first + take])
            row += take
        return pieces[0] if len(pieces) == 1 else np.concatenate(pieces)  # (m, k), m = stop - start

    def _gather(self, rows: np.ndarray) -> np.ndarray:
        # rows: (m,)
        gathered = np.empty((rows.size, self.shape[1]), dtype=self.dtype)  # (m, k)
        if rows.size == 0:
            return gathered  # (0, k)
        proteins, local = self._source.locate(rows)  # (m,), (m,)
        order = np.argsort(proteins, kind="stable")  # (m,)
        boundaries = np.flatnonzero(np.diff(proteins[order])) + 1
        for group in np.split(order, boundaries):
            block = self._source.protein(int(proteins[group[0]]))[self._which]  # (l, k)
            gathered[group] = block[local[group]]
        return gathered  # (m, k)


class ExtractionArrays:
    """The views of one opened extraction, with its index and the sequences that key its rows."""

    def __init__(
        self, directory: Path, root: Path, index: pd.DataFrame, sequences: tuple[str, ...],
        readers: dict[str, FeatureReader], budget_bytes: int,
    ) -> None:
        self.directory = directory
        self.root = root
        self.index = index
        self.sequences = sequences
        self.readers = readers
        self._pooled: dict[str, PooledColumns] = {}
        for role in POOLED_ROLES:
            if role in readers:
                dtype = np.uint16 if role == POOLED_COUNT else _NUMPY_DTYPES[readers[role].spec.dtype]
                self._pooled[role] = PooledColumns(
                    readers[role], sequences, dtype=dtype, budget_bytes=budget_bytes,
                    location={"directory": str(directory), "store_root": str(root), "role": role},
                )
        self._tracks: TrackSource | None = None
        if RESIDUE_TOPK in readers:
            self._tracks = TrackSource(
                readers[RESIDUE_TOPK], sequences, index["residue_offset"].to_numpy(dtype=np.int64),
                index["n_residues"].to_numpy(dtype=np.int64),
            )

    def __enter__(self) -> ExtractionArrays:
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()

    def close(self) -> None:
        """Release every reader. Views obtained earlier refuse further reads."""
        for reader in self.readers.values():
            reader.close()

    def pooled(self, name: str) -> PooledColumns:
        """One pooled view by pooling mode (`max`, `mean`, `count`) or role name."""
        role = _POOLING_ROLES.get(name, name)
        if role not in self._pooled:
            raise ValueError(f"This extraction stores no {role} feature under {self.root}")
        return self._pooled[role]

    @property
    def pooled_max(self) -> PooledColumns:
        return self.pooled(POOLED_MAX)

    @property
    def pooled_mean(self) -> PooledColumns:
        return self.pooled(POOLED_MEAN)

    @property
    def pooled_count(self) -> PooledColumns:
        return self.pooled(POOLED_COUNT)

    @property
    def residue_features(self) -> ResidueTracks:
        return ResidueTracks(self._need_tracks(), "indices")

    @property
    def residue_values(self) -> ResidueTracks:
        return ResidueTracks(self._need_tracks(), "values")

    @property
    def roles(self) -> tuple[str, ...]:
        """The roles this extraction stores, in canonical order."""
        return tuple(role for role in ROLES if role in self.readers)

    def batch(self, positions: Sequence[int] | np.ndarray) -> dict[str, np.ndarray]:
        """The stored arrays of index rows `positions`, as `ExtractionWriter.append` takes them.

        Pooled roles are `(b, c)` in the view dtype, and `residue_features` and `residue_values` are
        `(sum of the proteins' residue counts, k)` with proteins concatenated in the order asked.
        """
        # positions: (b,)
        rows = np.asarray(positions, dtype=np.int64)  # (b,)
        arrays: dict[str, np.ndarray] = {role: view[rows] for role, view in self._pooled.items()}
        if self._tracks is not None:
            tracks = self._tracks
            pieces = tracks.proteins(rows)
            arrays["residue_features"] = np.concatenate(
                [indices for indices, _ in pieces] or [np.empty((0, tracks.k), dtype=tracks.index_dtype)],
            )  # (r, k)
            arrays["residue_values"] = np.concatenate(
                [values for _, values in pieces] or [np.empty((0, tracks.k), dtype=tracks.value_dtype)],
            )  # (r, k)
        return arrays  # dict of (b, c) pooled roles and (r, k) residue roles

    @property
    def n_features(self) -> int:
        """The codebook size, read from a stored feature's declared width."""
        return int(next(iter(self.readers.values())).spec.width)

    @property
    def k(self) -> int:
        """The retained TopK width per residue."""
        return int(self._need_tracks().k)

    def _need_tracks(self) -> TrackSource:
        if self._tracks is None:
            raise ValueError(f"This extraction stores no {RESIDUE_TOPK} feature under {self.root}")
        return self._tracks


def open_extraction(
    directory: str | Path, *, store_root: str | Path | None = None, roles: Sequence[str] | None = None,
    column_budget_bytes: int = DEFAULT_COLUMN_BUDGET_BYTES,
) -> ExtractionArrays:
    """Open the stored features of an extraction directory as array-like views.

    Reads `protein_index.parquet` and the sequence sidecar, requires them to agree accession by
    accession and length by length (and by digest when the index records one), finds each role's
    store by its descriptor, and requires every indexed sequence to have a row. Bytes are verified
    lazily as parts are first read; `study.association.verify_extraction` verifies all of them.
    """
    directory = Path(directory)
    root = Path(store_root) if store_root is not None else default_store_root(directory)
    index = pd.read_parquet(directory / "protein_index.parquet")
    sidecar = read_sequences(root)
    check_sequence_alignment(index, sidecar)
    sequences = tuple(sidecar["sequence"].tolist())
    found = discover_features(root)
    wanted = tuple(roles) if roles is not None else tuple(role for role in ROLES if role in found)
    unknown = [role for role in wanted if role not in found]
    if unknown:
        raise ValueError(f"The extraction stores no {unknown} feature under {root}")
    if not wanted:
        raise ValueError(f"No extraction feature is stored under {root}")
    readers = {role: FeatureReader.open(found[role]) for role in wanted}
    unique = list(dict.fromkeys(sequences))
    for role, reader in readers.items():
        absent = reader.missing(unique)
        if absent:
            for opened in readers.values():
                opened.close()
            raise ValueError(f"{len(absent)} indexed proteins have no {role} row under {root}")
    return ExtractionArrays(directory, root, index, sequences, readers, column_budget_bytes)


__all__ = [
    "DEFAULT_COLUMN_BUDGET_BYTES",
    "ExtractionArrays",
    "PooledColumns",
    "ResidueTracks",
    "TrackSource",
    "open_extraction",
]
