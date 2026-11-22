"""The features of each control: what a head sees when it is shown no information about the protein's function.

- `random_features`: `SyntheticControlView(RANDOM_VECTOR)` pooled rows, (n, 1920), seeded by each protein's SHA-256.
- `one_hot_sequence`: `SyntheticControlView(ONE_HOT)` pooled rows, (n, 56): the residue composition and its variance.
- `random_backbone`: the pooled `final_mean_var` rows of the ESMC-300 network with random weights, read from the
  public store `Synthyra/esmc_embeddings` at `esmc_300_random/pooled` by byte range, (n, 1920).
- `metadata_only`: no sequence at all. Log length and its square, and one-hot columns of the training split's source
  namespace, organism, genus and the first EC number at four depths, as a sparse matrix.

Every feature matrix is float32 with one row per split row, in the split's order. Symbols: n rows, d feature columns,
w a store's hidden width, c categorical levels.
"""

from __future__ import annotations

import numpy as np

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias

from .release import NO_EC, Release, Split


if TYPE_CHECKING:
    from scipy.sparse import csr_matrix

    Matrix: TypeAlias = np.ndarray | csr_matrix
else:
    Matrix = Any

RANDOM_FEATURES = "random_features"
ONE_HOT_SEQUENCE = "one_hot_sequence"
RANDOM_BACKBONE = "random_backbone"
METADATA_ONLY = "metadata_only"
CONTROLS = (RANDOM_FEATURES, ONE_HOT_SEQUENCE, RANDOM_BACKBONE, METADATA_ONLY)

BACKBONE_REPOSITORY = "Synthyra/esmc_embeddings"
BACKBONE_FOLDER = "esmc_300_random/pooled"
BACKBONE_STREAM = "final_mean_var"
MIN_LEVEL_ROWS = 2  # a categorical level needs this many training rows to get a column
MAX_LEVELS = 500  # the most frequent levels of one field that get columns
EC_DEPTHS = 4  # class, subclass, sub-subclass, serial number
POOL_BATCH_ROWS = 64  # a control view's default read budget allows this many rows per call
BackboneReader = Callable[[Sequence[str]], Mapping[str, Mapping[str, Any]]]


@dataclass(frozen=True)
class Features:
    """A control's feature matrices for the three splits, and the arithmetic that made them."""

    control: str
    matrices: dict[str, Matrix]  # split name -> (n, d)
    identity: dict[str, Any]

    @property
    def width(self) -> int:
        return int(next(iter(self.matrices.values())).shape[1])


def synthetic_features(control: str, release: Release) -> Features:
    """The pooled rows of the random-vector or one-hot control for every split, made from the sequences alone."""
    from foundry.embedding import ONE_HOT, RANDOM_VECTOR, SyntheticControlView, sequence_inventory

    from tqdm import tqdm

    kind = {RANDOM_FEATURES: RANDOM_VECTOR, ONE_HOT_SEQUENCE: ONE_HOT}[control]
    matrices: dict[str, Matrix] = {}
    identity: dict[str, Any] = {}
    for name, split in release.splits.items():
        texts = [str(sequence) for sequence in split.sequences.tolist()]
        view = SyntheticControlView(kind, sequence_inventory(texts))
        batches = range(0, len(texts), POOL_BATCH_ROWS)
        pooled = [view.pooled(texts[start:start + POOL_BATCH_ROWS]).numpy()  # (b, 2w)
                  for start in tqdm(batches, desc=f"{control} {name}", unit="batch", disable=len(batches) < 8)]
        matrices[name] = (np.concatenate(pooled) if pooled else np.empty((0, 2 * view.width))).astype(np.float32)  # (n, 2w)
        identity = dict(view.identity)
    return Features(control, matrices, {"source": "foundry.embedding.SyntheticControlView", **identity})


def hub_backbone_reader(revision: str) -> BackboneReader:
    """Reads the random-weight ESMC-300 pooled rows of the given sequences from the Hub store at `revision`."""
    from foundry.embedding.hub import read_rows

    def read(sequences: Sequence[str]) -> Mapping[str, Mapping[str, Any]]:
        return read_rows(BACKBONE_REPOSITORY, BACKBONE_FOLDER, sequences, revision=revision, streams=[BACKBONE_STREAM])

    return read


def backbone_features(release: Release, *, revision: str, reader: BackboneReader | None = None) -> Features:
    """The random-weight backbone's pooled rows for every split, read through `reader` (the Hub store by default).

    The store keys rows by the normalized protein text, so a split's raw spelling is normalized before the lookup.
    """
    from foundry.embedding.contracts import normalize_sequence

    read = hub_backbone_reader(revision) if reader is None else reader
    matrices: dict[str, Matrix] = {}
    for name, split in release.splits.items():
        texts = [normalize_sequence(str(sequence)) for sequence in split.sequences.tolist()]
        rows = read(texts)
        matrix = np.stack([np.asarray(rows[text][BACKBONE_STREAM], dtype=np.float32) for text in texts])  # (n, 2w)
        if matrix.ndim != 2:
            raise ValueError(f"the backbone store returned rows of shape {matrix.shape[1:]}; a pooled row is one vector.")
        matrices[name] = matrix
    return Features(RANDOM_BACKBONE, matrices, {"source": "foundry.embedding.hub.read_rows", "repository": BACKBONE_REPOSITORY,
                                                "folder": BACKBONE_FOLDER, "stream": BACKBONE_STREAM, "revision": revision})


def ec_keys(ec: Sequence[str], depth: int) -> list[str]:
    """Each EC number cut to `depth` fields; NO_EC stays as it is."""
    return [NO_EC if number == NO_EC else ".".join(number.split(".")[:depth]) for number in ec]


def categorical_fields(split: Split) -> dict[str, list[str]]:
    """The categorical metadata of a split's rows, by field name, each a list of n keys."""
    ec = [str(number) for number in split.ec.tolist()]
    fields = {"source": [str(key) for key in split.source.tolist()], "species": [str(key) for key in split.species.tolist()],
              "genus": [str(key) for key in split.genus.tolist()]}
    for depth in range(1, EC_DEPTHS + 1):
        fields[f"ec_{depth}"] = ec_keys(ec, depth)
    return fields


def level_columns(train_fields: Mapping[str, Sequence[str]], *, min_rows: int = MIN_LEVEL_ROWS,
                  max_levels: int = MAX_LEVELS) -> dict[str, dict[str, int]]:
    """The column of each categorical level that at least `min_rows` training rows carry, the `max_levels` most frequent
    per field, numbered after the two length columns."""
    columns: dict[str, dict[str, int]] = {}
    next_column = 2
    for field, keys in train_fields.items():
        levels, counts = np.unique(np.array(keys, dtype=object), return_counts=True)  # (c,), (c,)
        order = np.lexsort((levels.astype(str), -counts))  # (c,) most frequent first, ties by name
        kept = [str(levels[index]) for index in order if counts[index] >= min_rows][:max_levels]
        columns[field] = {level: next_column + position for position, level in enumerate(kept)}
        next_column += len(kept)
    return columns


def metadata_matrix(split: Split, columns: Mapping[str, Mapping[str, int]], width: int) -> Matrix:
    """The sparse (n, d) metadata matrix of a split: log length, its square, then the one-hot level columns."""
    from scipy import sparse

    lengths = np.array([len(str(sequence)) for sequence in split.sequences.tolist()], dtype=np.float64)  # (n,)
    log_length = np.log(np.maximum(lengths, 1.0))  # (n,)
    rows: list[int] = list(range(split.rows)) * 2
    cols: list[int] = [0] * split.rows + [1] * split.rows
    values: list[float] = log_length.tolist() + (log_length ** 2).tolist()
    for field, keys in categorical_fields(split).items():
        field_columns = columns[field]
        for row, key in enumerate(keys):
            column = field_columns.get(key)
            if column is not None:
                rows.append(row)
                cols.append(column)
                values.append(1.0)
    return sparse.csr_matrix((np.array(values, dtype=np.float32), (np.array(rows), np.array(cols))), shape=(split.rows, width))


def metadata_features(release: Release, *, min_rows: int = MIN_LEVEL_ROWS, max_levels: int = MAX_LEVELS) -> Features:
    """The metadata-only control's matrices: lengths and the training split's categorical levels, nothing of the residues."""
    columns = level_columns(categorical_fields(release.splits["train"]), min_rows=min_rows, max_levels=max_levels)
    width = 2 + sum(len(levels) for levels in columns.values())  # d
    matrices = {name: metadata_matrix(split, columns, width) for name, split in release.splits.items()}
    return Features(METADATA_ONLY, matrices, {
        "source": "foundry.controls.features.metadata_features", "length": "log length and its square",
        "fields": {field: len(levels) for field, levels in columns.items()}, "min_level_rows": min_rows,
        "max_levels_per_field": max_levels, "width": width,
    })
