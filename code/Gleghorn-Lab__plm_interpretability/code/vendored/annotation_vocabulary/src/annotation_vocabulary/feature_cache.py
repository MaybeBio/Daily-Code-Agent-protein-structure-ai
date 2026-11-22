"""Extraction caches in the workspace feature store.

An extraction holds four things for every protein it embedded: the per-residue TopK slots of the
sparse autoencoder (`residue_topk`), and three pooled summaries over residues (`pooled_max`,
`pooled_mean`, `pooled_count`). Each is one feature of `fastplms.features`, addressed by the
SHA-256 of the exact processed sequence text, so a protein embedded twice is one row and a
protein embedded by another run is found without knowing which run.

The store keeps digests and residue counts but no sequence text, and its API reads by text. An
extraction therefore keeps one sidecar beside its stores, `sequences.parquet`, listing each index
row's accession and processed sequence in index order. `annotation_vocabulary.feature_views`
binds the sidecar to the index and turns the stores into array-like views, so a consumer still
asks for `pooled[rows, columns]` and `residues[offset:offset + length]`.

Layout under one extraction directory (the store root defaults to its `features` subdirectory)::

    <extraction>/manifest.json, protein_index.parquet    unchanged in meaning
    <extraction>/features/sequences.parquet              accession, processed sequence
    <extraction>/features/<key>/...                      one directory per role

Each key is `foundry.embedding.plain_feature` with owner `annotation_vocabulary`. The digest
covers the descriptor and nothing else, so the descriptor states layout, width, dtype, and every
fact that changes the stored numbers: model and SAE identity where a run recorded them, layer,
pooling, residue policy, TopK width, normalization, and the pooled dtype. A fact an old cache never
recorded is None, never a guess. Two generations of cache exist and differ in what their numbers
mean (float16 against float32 pooling, TopK membership against positive-slot counts), so each has
its own descriptors and therefore its own keys.

Counts are uint16 in the old caches. The store holds float dtypes only, so counts are stored as
float32, which holds every uint16 exactly, and the views cast them back on read.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import numpy as np
import pandas as pd
import torch

from collections.abc import Iterable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from torch import Tensor

from fastplms.features import (
    DENSE,
    RAGGED_TOPK,
    FeatureReader,
    FeatureStore,
    SegmentWriter,
    StoredFeature,
    TopKRow,
    describe_file,
    features_in,
    sequence_digest,
)
from foundry.embedding import plain_feature


OWNER = "annotation_vocabulary"
STORE_DIRECTORY = "features"
SEQUENCES_FILE = "sequences.parquet"
STUDY = "study"
ANALYSIS = "analysis"
GENERATIONS = (STUDY, ANALYSIS)
RESIDUE_TOPK = "residue_topk"
POOLED_MAX = "pooled_max"
POOLED_MEAN = "pooled_mean"
POOLED_COUNT = "pooled_count"
POOLED_ROLES = (POOLED_MAX, POOLED_MEAN, POOLED_COUNT)
ROLES = (RESIDUE_TOPK, *POOLED_ROLES)
COUNT_LIMIT = 65_535
STUDY_DEFAULT_MAX_RESIDUES = 2048  # what `study.extract.load_sequences` applies when a run sets none
DEFAULT_ROWS_PER_SEGMENT = 50_000
DEFAULT_MAX_TENSOR_BYTES = 256 * 1024**2

_TORCH_DTYPES = {"float32": torch.float32, "float16": torch.float16}
_NUMPY_DTYPES = {torch.float32: np.float32, torch.float16: np.float16}

# What the numbers of each generation mean. These sentences go into descriptors, so each states
# only what the extraction code does.
_GENERATION_MEANING: dict[str, dict[str, str]] = {
    STUDY: {
        "pooled_dtype": "float32",
        "layer_input": "hidden state entering transformer block sae_layer, early exit, no final layer norm",
        "activation": (
            "Biohub SAE encoder: per-residue sample-standard-deviation standardization with epsilon "
            "1e-5, decoder-bias subtraction, projection, ReLU, raw TopK magnitudes, no idf rescaling"
        ),
        "residue_policy": "biological residues only, BOS and EOS positions dropped, prefix of max_residues",
        "count_rule": "residues whose retained slot for the feature has a positive value",
    },
    ANALYSIS: {
        "pooled_dtype": "float16",
        "layer_input": "SAE head attached at sae_layer by the esm package, tap point defined by that package",
        "activation": "sparse TopK output of the SAE head as emitted, k retained entries per position",
        "residue_policy": "residues only, CLS and EOS positions dropped, prefix of max_residues",
        "count_rule": (
            "residues whose retained entries include the feature, zero-valued entries included, "
            "clamped to 65535"
        ),
    },
}
_QUANTITY = {
    RESIDUE_TOPK: (
        "per residue, the k retained SAE entries as codebook indices and activation values, entry "
        "order kept and zero-valued entries kept"
    ),
    POOLED_MAX: "per feature, the maximum retained activation over the protein's residues, zero if never retained",
    POOLED_MEAN: "per feature, the sum of retained activations over the protein's residues divided by its residue count",
}


@dataclass(frozen=True, slots=True)
class ExtractionFacts:
    """Every fact about one extraction that changes the stored numbers.

    `None` marks a fact the run never recorded. `residue_value_dtype` is the dtype the run stored
    residue activations in, which changes the numbers when it is float16.
    """

    generation: str
    sae_layer: int | None
    codebook_size: int
    k: int
    residue_value_dtype: str
    max_residues: int | None = None
    base_repo: str | None = None
    base_revision: str | None = None
    original_base_repo: str | None = None
    original_base_revision: str | None = None
    sae_repo: str | None = None
    sae_revision: str | None = None
    backbone_dtype: str | None = None
    sae_dtype: str | None = None
    precision: str | None = None
    attention_backend: str | None = None
    runtime_revision: str | None = None

    def __post_init__(self) -> None:
        if self.generation not in GENERATIONS:
            raise ValueError(f"generation must be one of {GENERATIONS}; received {self.generation!r}.")
        if self.residue_value_dtype not in _TORCH_DTYPES:
            raise ValueError(f"residue_value_dtype must be float32 or float16; received {self.residue_value_dtype!r}.")
        if not 1 <= self.k <= self.codebook_size:
            raise ValueError("k must lie between 1 and the codebook size.")

    @property
    def pooled_dtype(self) -> str:
        return _GENERATION_MEANING[self.generation]["pooled_dtype"]

    def descriptor(self, role: str) -> dict[str, Any]:
        """The plain data one role's key is computed from."""
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}; received {role!r}.")
        meaning = _GENERATION_MEANING[self.generation]
        layout, dtype, sparse_count = self._shape(role)
        quantity = meaning["count_rule"] if role == POOLED_COUNT else _QUANTITY[role]
        descriptor: dict[str, Any] = {
            "schema": f"{OWNER}_{role}_v1",
            "role": role,
            "generation": self.generation,
            "layout": layout,
            "width": self.codebook_size,
            "dtype": dtype,
            "sparse_count": sparse_count,
            "quantity": quantity,
            "row_identity": "sha256 of the processed sequence text, the residues that were embedded",
            "base_repo": self.base_repo,
            "base_revision": self.base_revision,
            "original_base_repo": self.original_base_repo,
            "original_base_revision": self.original_base_revision,
            "sae_repo": self.sae_repo,
            "sae_revision": self.sae_revision,
            "sae_layer": self.sae_layer,
            "codebook_size": self.codebook_size,
            "k": self.k,
            "layer_input": meaning["layer_input"],
            "activation": meaning["activation"],
            "residue_policy": meaning["residue_policy"],
            "max_residues": self.max_residues,
            "backbone_dtype": self.backbone_dtype,
            "sae_dtype": self.sae_dtype,
            "precision": self.precision,
            "attention_backend": self.attention_backend,
            "runtime_revision": self.runtime_revision,
        }
        if role == POOLED_COUNT:
            descriptor["count_storage"] = "uint16 counts held exactly as float32"
        return descriptor

    def _shape(self, role: str) -> tuple[str, str, int | None]:
        if role == RESIDUE_TOPK:
            return RAGGED_TOPK, self.residue_value_dtype, self.k
        if role == POOLED_COUNT:
            return DENSE, "float32", None
        return DENSE, self.pooled_dtype, None


def study_facts(settings: Mapping[str, Any], *, residue_value_dtype: str | None = None) -> ExtractionFacts:
    """Facts of a study-format extraction from its configuration or recorded settings.

    `residue_value_dtype` overrides the setting when the caller has read the stored array, which
    is authoritative over a setting that may have been defaulted.
    """
    precision = settings.get("precision", "bf16")
    backbone = settings.get("backbone_dtype", "float32" if precision == "fp32" else "bfloat16")
    return ExtractionFacts(
        generation=STUDY,
        sae_layer=None if settings.get("sae_layer") is None else int(settings["sae_layer"]),
        codebook_size=int(settings["feature_dim"]),
        k=int(settings["k"]),
        residue_value_dtype=residue_value_dtype or str(settings.get("residue_dtype", "float32")),
        max_residues=int(settings.get("max_residues", STUDY_DEFAULT_MAX_RESIDUES)),
        base_repo=settings.get("base_repo"),
        base_revision=settings.get("base_revision"),
        original_base_repo=settings.get("original_base_repo"),
        original_base_revision=settings.get("original_base_revision"),
        sae_repo=settings.get("sae_repo"),
        sae_revision=settings.get("sae_revision"),
        backbone_dtype=backbone,
        # FastPLMSAE loads the SAE encoder in float32 whatever the backbone runs in.
        sae_dtype="float32",
        precision=precision,
        attention_backend=settings.get("attention_backend", "sdpa"),
        runtime_revision=settings.get("fastplms_revision"),
    )


def analysis_facts(
    config: Mapping[str, Any], *, codebook_size: int, k: int, sae_dtype: str | None = None,
) -> ExtractionFacts:
    """Facts of an analysis-format extraction from its `ExtractionConfig` fields.

    The old writer recorded repositories but no revisions and no SAE dtype, so a converted cache
    leaves those None, which is the default here. A new run states the revisions its config pins
    (an empty string means it pinned none) and the SAE dtype it observed after loading. The
    backbone was loaded in bfloat16 and residue activations were stored in float16.
    """
    return ExtractionFacts(
        generation=ANALYSIS,
        sae_layer=int(config["sae_layer"]),
        codebook_size=int(codebook_size),
        k=int(k),
        residue_value_dtype="float16",
        max_residues=None if config.get("max_length") is None else int(config["max_length"]),
        base_repo=config.get("base_repo"),
        base_revision=config.get("base_revision") or None,
        sae_repo=config.get("sae_repo"),
        sae_revision=config.get("sae_revision") or None,
        backbone_dtype="bfloat16",
        sae_dtype=sae_dtype,
    )


def extraction_features(facts: ExtractionFacts, *, residues: bool = True) -> dict[str, StoredFeature]:
    """The stored features of an extraction, by role. `residues=False` omits `residue_topk`."""
    roles = ROLES if residues else POOLED_ROLES
    return {role: _feature(facts, role) for role in roles}


def _feature(facts: ExtractionFacts, role: str) -> StoredFeature:
    descriptor = facts.descriptor(role)
    # A short slug keeps the deepest store path under the 260 characters Windows allows without
    # long-path support; the model, layer, dtype, and every other fact are in the descriptor and
    # its digest, which alone decides identity.
    slug = [facts.generation, role]
    return plain_feature(
        OWNER, descriptor, layout=descriptor["layout"], width=facts.codebook_size,
        dtype=_TORCH_DTYPES[descriptor["dtype"]], sparse_count=descriptor["sparse_count"], slug=slug,
    )


def default_store_root(extraction_dir: str | Path) -> Path:
    """Where an extraction directory keeps its stores when the caller names no root."""
    return Path(extraction_dir) / STORE_DIRECTORY


def discover_features(root: str | Path) -> dict[str, Path]:
    """The feature directory of each role under `root`, found by its descriptor.

    A role held by two stores is ambiguous and raises: a reader must never guess between two sets
    of numbers.
    """
    found: dict[str, list[Path]] = {}
    for store in features_in(root):
        descriptor = store.spec.descriptor
        role = descriptor.get("role")
        if str(descriptor.get("schema", "")).startswith(f"{OWNER}_") and role in ROLES:
            found.setdefault(role, []).append(store.directory)
    ambiguous = {role: [path.name for path in paths] for role, paths in found.items() if len(paths) > 1}
    if ambiguous:
        raise ValueError(f"More than one stored feature claims a role under {root}: {ambiguous}")
    return {role: paths[0] for role, paths in found.items()}


# Sequence sidecar -----------------------------------------------------------------------------


def write_sequences(root: str | Path, accessions: Sequence[str], sequences: Sequence[str]) -> dict[str, Any]:
    """Write `sequences.parquet` atomically and return its `describe_file` record.

    Rows follow the extraction index. An existing sidecar with the same content is left in place,
    so a resumed run does not change bytes that a manifest already names.
    """
    if len(accessions) != len(sequences):
        raise ValueError("One processed sequence is needed for every accession.")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame({"accession": list(accessions), "sequence": list(sequences)})
    target = root / SEQUENCES_FILE
    if target.exists() and read_sequences(root).equals(frame):
        return describe_file(target)
    temporary = target.with_suffix(".parquet.writing")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, target)
    return describe_file(target)


def read_sequences(root: str | Path) -> pd.DataFrame:
    """The sidecar's `accession` and `sequence` columns."""
    path = Path(root) / SEQUENCES_FILE
    if not path.is_file():
        raise FileNotFoundError(
            f"The extraction has no sequence sidecar: {path}. An extraction still held as .npy arrays "
            "converts with `python -m annotation_vocabulary.legacy_extraction_cache EXTRACTION_DIR "
            "--sequences TABLE.parquet`."
        )
    return pd.read_parquet(path, columns=["accession", "sequence"])


def aligned_sequences_digest(accessions: Iterable[str], sequences: Iterable[str]) -> str:
    """SHA-256 of the accession and sequence pairs, independent of any file encoding."""
    digest = hashlib.sha256()
    for accession, sequence in zip(accessions, sequences, strict=True):
        digest.update(f"{accession}\t{sequence}\n".encode())
    return digest.hexdigest()


def check_sequence_alignment(index: pd.DataFrame, sequences: pd.DataFrame) -> None:
    """Require the sidecar to follow the index accession by accession, length by length.

    An index that records `processed_sequence_sha256` also binds every sequence by digest, which is
    the store's own row identity, so a passing check means each row is read by the residues the
    extraction embedded.
    """
    if len(sequences) != len(index) or not np.array_equal(
        sequences["accession"].to_numpy(dtype=object), index["accession"].to_numpy(dtype=object),
    ):
        raise ValueError("The stored sequences do not follow the extraction index accession by accession")
    lengths = sequences["sequence"].str.len().to_numpy(dtype=np.int64)  # (n,)
    if not np.array_equal(lengths, index["n_residues"].to_numpy(dtype=np.int64)):
        raise ValueError("Stored sequence lengths differ from the extraction index residue counts")
    if "processed_sequence_sha256" in index:
        digests = [sequence_digest(sequence) for sequence in sequences["sequence"]]
        if digests != index["processed_sequence_sha256"].tolist():
            raise ValueError("Stored sequences differ from the index processed_sequence_sha256 values")


# Writing --------------------------------------------------------------------------------------


class ExtractionWriter:
    """Append batches of proteins to the role stores, committing one window at a time.

    A window is a set of parts that commit together in every role store once it holds
    `rows_per_segment` proteins. A run that dies loses at most the open window: committed windows
    stay, and `missing` names the proteins a restart still owes. Every commit re-verifies the
    committed parts of its store, so windows are large and few.

    `append` writes to each role only the rows that role lacks, so a batch that a crash left in
    some roles is recomputed once and completed. Rows are never rounded silently: a value the
    store dtype cannot hold exactly raises.
    """

    def __init__(
        self, root: str | Path, features: Mapping[str, StoredFeature], *, run: str,
        metadata: Mapping[str, Any] | None = None,
        rows_per_segment: int = DEFAULT_ROWS_PER_SEGMENT,
        max_tensor_bytes: int = DEFAULT_MAX_TENSOR_BYTES,
    ) -> None:
        if rows_per_segment < 1:
            raise ValueError("rows_per_segment must be positive.")
        self.root = Path(root)
        self.features = dict(features)
        self.run = run
        self.metadata = dict(metadata or {})
        self.rows_per_segment = rows_per_segment
        self.max_tensor_bytes = max_tensor_bytes
        self.stores: dict[str, FeatureStore] = {}
        self._stack: ExitStack | None = None
        self._writers: dict[str, SegmentWriter] = {}
        self._staged: dict[str, set[str]] = {}
        self._window_rows = 0

    def __enter__(self) -> ExtractionWriter:
        self.root.mkdir(parents=True, exist_ok=True)
        for role, spec in self.features.items():
            store = FeatureStore.open(self.root, spec)
            store.sweep()
            self.stores[role] = store
        return self

    def __exit__(self, exception_type: Any, exception: Any, traceback: Any) -> None:
        if self._stack is None:
            return
        if exception_type is None:
            self.commit()
        else:
            stack, self._stack = self._stack, None
            stack.__exit__(exception_type, exception, traceback)

    def missing(self, sequences: Sequence[str]) -> tuple[str, ...]:
        """The sequences at least one role store still lacks, in order, without repeats."""
        absent: set[str] = set()
        for store in self.stores.values():
            absent.update(store.missing(sequences))
        return tuple(sequence for sequence in dict.fromkeys(sequences) if sequence in absent)

    def append(self, sequences: Sequence[str], arrays: Mapping[str, np.ndarray], lengths: Sequence[int]) -> int:
        """Stage one batch and return how many role rows were written.

        `arrays` holds what the engine returned for the batch: `pooled_max`, `pooled_mean`,
        `pooled_count` as `(b, c)`, and `residue_features`, `residue_values` as `(sum(lengths), k)`
        with proteins concatenated in batch order. `lengths` are the residue counts.
        """
        # arrays: (b, c) for each pooled role, (r, k) for each residue role, r = sum(lengths)
        lengths_array = np.asarray(lengths, dtype=np.int64)  # (b,)
        if len(sequences) != len(lengths_array) or len(set(sequences)) != len(sequences):
            raise ValueError("A batch needs one length per sequence and no repeated sequence.")
        if any(len(sequence) != length for sequence, length in zip(sequences, lengths_array, strict=True)):
            raise ValueError("A residue count differs from the length of its processed sequence.")
        if RESIDUE_TOPK in self.features:
            expected = int(lengths_array.sum())
            for name in ("residue_features", "residue_values"):
                if len(arrays[name]) != expected:
                    raise ValueError(f"{name} holds {len(arrays[name])} rows for {expected} residues.")
        if self._stack is None:
            self._open_window()
        starts = np.concatenate([[0], np.cumsum(lengths_array)])  # (b + 1,)
        written = 0
        for role, writer in self._writers.items():
            staged = self._staged[role]
            absent = {
                sequence for sequence in self.stores[role].missing(sequences)
                if sequence_digest(sequence) not in staged
            }
            chosen = [position for position, sequence in enumerate(sequences) if sequence in absent]
            if not chosen:
                continue
            rows = [self._row(role, arrays, position, starts) for position in chosen]
            chosen_sequences = [sequences[position] for position in chosen]
            writer.append_bounded(chosen_sequences, rows, max_tensor_bytes=self.max_tensor_bytes)
            staged.update(sequence_digest(sequence) for sequence in chosen_sequences)
            written += len(chosen)
        self._window_rows += len(sequences)
        if self._window_rows >= self.rows_per_segment:
            self.commit()
        return written

    def commit(self, **window_metadata: Any) -> None:
        """Commit the open window in every role, adding `window_metadata` to each commit marker."""
        if self._stack is None:
            return
        for writer in self._writers.values():
            writer.metadata.update(json.loads(json.dumps(window_metadata)))
            writer.metadata["window_rows"] = self._window_rows
        stack, self._stack = self._stack, None
        self._writers, self._staged, self._window_rows = {}, {}, 0
        stack.close()

    def _open_window(self) -> None:
        stack = ExitStack()
        try:
            for role, store in self.stores.items():
                name = f"{self.run}-{_committed_windows(store, self.run):05d}"
                self._writers[role] = stack.enter_context(store.segment(name, self.metadata))
                self._staged[role] = set()
        except BaseException:
            stack.close()
            self._writers, self._staged = {}, {}
            raise
        self._stack = stack

    def _row(self, role: str, arrays: Mapping[str, np.ndarray], position: int, starts: np.ndarray) -> Tensor | TopKRow:
        # arrays: (b, c) for each pooled role, (r, k) for each residue role; starts: (b + 1,)
        spec = self.features[role]
        if role == RESIDUE_TOPK:
            start, stop = int(starts[position]), int(starts[position + 1])
            indices = exact_tensor(arrays["residue_features"][start:stop], torch.int32)  # (r_i, k)
            values = exact_tensor(arrays["residue_values"][start:stop], spec.dtype)  # (r_i, k)
            return TopKRow(indices, values)  # (r_i, k) indices and values
        source = arrays[role][position]  # (c,)
        if role == POOLED_COUNT and (source.min(initial=0) < 0 or source.max(initial=0) > COUNT_LIMIT):
            raise ValueError("A pooled count lies outside the uint16 range the extraction promises.")
        return exact_tensor(source, spec.dtype)  # (c,)


def _committed_windows(store: FeatureStore, run: str) -> int:
    """The next window number of `run`: one past its highest committed window, so a gap never collides."""
    directory = store.directory / "segments"
    numbers = [
        int(marker.parent.name.rsplit("-", 1)[1])
        for marker in directory.glob(f"{run}-[0-9]*/run.json") if marker.is_file()
    ]
    return max(numbers, default=-1) + 1


def exact_tensor(values: np.ndarray, dtype: torch.dtype) -> Tensor:
    """`values` as a tensor of `dtype`, raising if the cast would change any value.

    Unsigned integers are widened through numpy first, because a uint16 tensor is not a storable
    or reliably supported dtype.
    """
    # values: (...), any shape; the tensor keeps it
    array = np.ascontiguousarray(values)
    if dtype in _NUMPY_DTYPES:
        target = _NUMPY_DTYPES[dtype]
    elif dtype == torch.int32:
        target = np.int32
    else:
        raise ValueError(f"exact_tensor casts to float32, float16, or int32; received {dtype}.")
    converted = array.astype(target)
    if array.dtype != target and not np.array_equal(converted.astype(array.dtype), array):
        raise ValueError(f"Casting {array.dtype} values to {np.dtype(target)} would change them.")
    return torch.from_numpy(converted)  # (...) same shape as values


def measure_write(
    root: str | Path, features: Mapping[str, StoredFeature], sequences: Sequence[str],
    arrays: Mapping[str, np.ndarray], lengths: Sequence[int],
) -> dict[str, Any]:
    """Write one batch into throwaway stores under `root` and report time and bytes.

    A benchmark uses this to price persistence with the same writer a real run uses. Repeated
    sequences in the batch are written once.
    """
    # arrays: (b, c) for each pooled role, (r, k) for each residue role, over the whole batch
    lengths_array = np.asarray(lengths, dtype=np.int64)  # (b,)
    starts = np.concatenate([[0], np.cumsum(lengths_array)])  # (b + 1,)
    seen: dict[str, int] = {}
    for position, sequence in enumerate(sequences):
        seen.setdefault(sequence, position)
    first = sorted(seen.values())  # batch positions of each distinct sequence
    kept_sequences = [sequences[position] for position in first]
    kept_lengths = lengths_array[first]
    started = time.perf_counter()
    residue_arrays: dict[str, np.ndarray] = {}
    if RESIDUE_TOPK in features:
        for name in ("residue_features", "residue_values"):
            residue_arrays[name] = np.concatenate(
                [arrays[name][int(starts[position]):int(starts[position + 1])] for position in first]
            )  # (sum kept residues, k)
    kept = {**{name: arrays[name][first] for name in POOLED_ROLES}, **residue_arrays}
    with ExtractionWriter(root, features, run="io") as writer:
        writer.append(kept_sequences, kept, kept_lengths)
    seconds = time.perf_counter() - started
    total = sum(path.stat().st_size for path in Path(root).rglob("*") if path.is_file())
    return {"seconds": seconds, "proteins": len(kept_sequences), "bytes": total}


# Identity and verification --------------------------------------------------------------------


def store_content(directory: str | Path, sequences: Sequence[str]) -> dict[str, str]:
    """The SHA-256 of every immutable file that holds these sequences' rows, verified on the way.

    The store's own `content_pins` recomputes each digest and refuses a part that differs from its
    commit marker, so a returned mapping certifies the bytes, not only names them.
    """
    return FeatureStore.read_only(directory).content_pins(list(dict.fromkeys(sequences)))


def feature_identity(directory: str | Path, sequences: Sequence[str]) -> dict[str, Any]:
    """`{path, bytes, sha256}` for one stored feature, the shape analysis provenance binds inputs by.

    `bytes` is the total size of the pinned files and `sha256` the digest of their pinned digests,
    so the identity changes exactly when a committed byte changes.
    """
    directory = Path(directory)
    pins = store_content(directory, sequences)
    encoded = json.dumps(pins, sort_keys=True, separators=(",", ":")).encode()
    return {
        "path": str(directory.resolve()),
        "bytes": sum((directory / relative).stat().st_size for relative in pins),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def role_identity(extraction_dir: str | Path, role: str, *, store_root: str | Path | None = None) -> dict[str, Any]:
    """`feature_identity` of one role of an extraction directory, read through its sidecar."""
    root = Path(store_root) if store_root is not None else default_store_root(extraction_dir)
    features = discover_features(root)
    if role not in features:
        raise ValueError(f"The extraction stores no {role} feature under {root}.")
    return feature_identity(features[role], read_sequences(root)["sequence"].tolist())


def describe_store(
    extraction_dir: str | Path, root: str | Path, features: Mapping[str, StoredFeature],
    sequences: Sequence[str],
) -> dict[str, Any]:
    """The `feature_store` block of an extraction manifest, binding every stored byte.

    `content` maps each immutable file of a feature (relative to its directory) to its SHA-256, so
    a manifest digest bound by a later stage covers the stored numbers too.
    """
    extraction_dir, root = Path(extraction_dir), Path(root)
    unique = list(dict.fromkeys(sequences))
    try:
        recorded_root = root.resolve().relative_to(extraction_dir.resolve()).as_posix()
    except ValueError:
        recorded_root = str(root.resolve())
    block: dict[str, Any] = {
        "root": recorded_root, "sequences": describe_file(root / SEQUENCES_FILE), "features": {},
    }
    for role, spec in features.items():
        block["features"][role] = {
            "key": spec.key, "layout": spec.layout, "width": spec.width,
            "dtype": str(spec.dtype).removeprefix("torch."), "sparse_count": spec.sparse_count,
            "rows": len(unique), "content": store_content(root / spec.key, unique),
        }
    return block


def recorded_root(extraction_dir: str | Path, block: Mapping[str, Any]) -> Path:
    """The store root a manifest's `feature_store` block names."""
    root = Path(str(block["root"]))
    return root if root.is_absolute() else Path(extraction_dir) / root


def stored_files(extraction_dir: str | Path, block: Mapping[str, Any]) -> dict[Path, dict[str, Any]]:
    """Every file a manifest's `feature_store` block binds, resolved, with its recorded size and SHA-256.

    These are the sequence sidecar and, for each stored feature, the descriptor, the commit markers,
    and the parts that hold the indexed rows. The digests are the manifest's own record, so a caller
    compares them with a receipt and leaves the hashing to `verify_recorded_store`. A listed file
    that is missing raises, because a record of absent bytes binds nothing.
    """
    root = recorded_root(extraction_dir, block).resolve()
    files: dict[Path, dict[str, Any]] = {
        root / SEQUENCES_FILE: {"size": int(block["sequences"]["bytes"]), "sha256": block["sequences"]["sha256"]},
    }
    for entry in block["features"].values():
        for relative, sha256 in entry["content"].items():
            path = (root / entry["key"] / relative).resolve()
            files[path] = {"size": path.stat().st_size, "sha256": sha256}
    return files


def verify_recorded_store(
    extraction_dir: str | Path, block: Mapping[str, Any], index: pd.DataFrame, *, include_local: bool,
) -> None:
    """Fail unless every stored byte, row, and residue count matches the manifest and the index.

    The pooled maximum is always required, and `residue_topk` when `include_local` is true, as
    the old checksum inventory required the same arrays.
    """
    extraction_dir = Path(extraction_dir)
    root = recorded_root(extraction_dir, block)
    entries = block.get("features", {})
    required = (POOLED_MAX, *((RESIDUE_TOPK,) if include_local else ()))
    absent = [role for role in required if role not in entries]
    if absent:
        raise ValueError(f"Extraction manifest lacks required stored features: {absent}")
    sidecar = root / SEQUENCES_FILE
    recorded = block["sequences"]
    if not sidecar.is_file() or describe_file(sidecar) != recorded:
        raise ValueError("The extraction sequence sidecar differs from its manifest record")
    sequences = read_sequences(root)
    check_sequence_alignment(index, sequences)
    listed = sequences["sequence"].tolist()
    for role, entry in entries.items():
        verify_role(root, role, listed, index, key=entry["key"], content=entry["content"])


def verify_role(
    root: Path, role: str, sequences: Sequence[str], index: pd.DataFrame, *,
    key: str | None = None, content: Mapping[str, str] | None = None,
) -> None:
    """Verify one role's store against the index, and against recorded `content` when given."""
    found = discover_features(root)
    directory = root / key if key is not None else found.get(role)
    if directory is None or not (Path(directory) / "feature.json").is_file():
        raise ValueError(f"The extraction stores no {role} feature under {root}")
    store = FeatureStore.read_only(directory)
    if store.spec.descriptor.get("role") != role:
        raise ValueError(f"{directory} does not hold the {role} feature")
    unique = list(dict.fromkeys(sequences))
    absent = store.missing(unique)
    if absent:
        raise ValueError(f"{len(absent)} proteins of the index have no {role} row")
    pins = store.content_pins(unique)
    if content is not None and dict(content) != pins:
        raise ValueError(f"Stored bytes of {role} differ from the manifest record")
    if role == RESIDUE_TOPK:
        counts = np.asarray(store.residue_counts(list(sequences)), dtype=np.int64)  # (n,)
        if not np.array_equal(counts, index["n_residues"].to_numpy(dtype=np.int64)):
            raise ValueError("Stored residue counts differ from the extraction index")


def open_reader(root: str | Path, role: str) -> FeatureReader:
    """A reader over one role of the stores under `root`."""
    found = discover_features(root)
    if role not in found:
        raise ValueError(f"The extraction stores no {role} feature under {root}.")
    return FeatureReader.open(found[role])


__all__ = [
    "ANALYSIS",
    "COUNT_LIMIT",
    "GENERATIONS",
    "OWNER",
    "POOLED_COUNT",
    "POOLED_MAX",
    "POOLED_MEAN",
    "POOLED_ROLES",
    "RESIDUE_TOPK",
    "ROLES",
    "SEQUENCES_FILE",
    "STORE_DIRECTORY",
    "STUDY",
    "ExtractionFacts",
    "ExtractionWriter",
    "aligned_sequences_digest",
    "analysis_facts",
    "check_sequence_alignment",
    "default_store_root",
    "describe_store",
    "discover_features",
    "exact_tensor",
    "extraction_features",
    "feature_identity",
    "measure_write",
    "open_reader",
    "read_sequences",
    "recorded_root",
    "role_identity",
    "store_content",
    "stored_files",
    "study_facts",
    "verify_recorded_store",
    "verify_role",
    "write_sequences",
]
