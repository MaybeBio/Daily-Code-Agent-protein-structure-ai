"""Read-only decoders of the two pre-store extraction cache formats, and the converter.

Two writers stored an extraction as `.npy` arrays beside a `protein_index.parquet` and a
`manifest.json`. Both writers are retired (the originals are in `C:/ws-staging/_removed/`), and
this module is the only code that still reads their format. It has no writer.

- `analysis`: `analysis/extraction.py`. Manifest `{"config", "metrics"}`. Pooled maximum and mean
  as float16, counts and residue indices as uint16, residue values as float16, all keyed by row
  order of the accession-sorted sequence table. Residue rows sit at `residue_offset`, assigned in
  batch processing order. Model and SAE revisions were never recorded, and neither was the SAE
  dtype. The index carries `accession`, `length`, `n_residues`, `residue_offset`.
- `study`: `study/extract.py`. Manifest with a `files` inventory (`sha256`, `size`), `settings`,
  `sae_identity`, and a `fingerprint`. Pooled arrays in float32, positive-slot counts as uint16,
  residue indices as uint16, residue values as float32 or float16. The index adds
  `original_sequence_sha256` and `processed_sequence_sha256`, which bind each row to its residues.

`convert_extraction` reads one such directory and writes a feature store under its `features`
subdirectory with `fastplms.features.convert_rows`, which compares every stored row bit for bit
with a second decode of the old arrays. The old files are never modified, and every file a role was
decoded from is recorded, with its SHA-256, in the origin of each commit marker. That record is what
lets `verify_converted_manifest` keep checking a receipt's checksum inventory after the old arrays
are gone: a checksummed array is accepted if the store was converted from exactly those bytes.

Run it where the old cache lives:

    python -m annotation_vocabulary.legacy_extraction_cache EXTRACTION_DIR --sequences TABLE.parquet

`TABLE.parquet` supplies the sequence text, which the old caches never stored: the prepared
`proteins.parquet` for a study cache, the sequence table the extraction read for an analysis cache.
Accession and length are checked for every protein, and so is the processed-sequence digest for a
study cache. An analysis cache records no digests, so its alignment evidence is accession and
length only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import numpy as np
import pandas as pd
import torch

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any
from torch import Tensor

from fastplms.features import ConversionReceipt, FeatureStore, TopKRow, convert_rows, describe_file
from .feature_cache import (
    ANALYSIS,
    POOLED_COUNT,
    POOLED_MAX,
    POOLED_MEAN,
    POOLED_ROLES,
    RESIDUE_TOPK,
    SEQUENCES_FILE,
    STUDY,
    ExtractionFacts,
    aligned_sequences_digest,
    analysis_facts,
    check_sequence_alignment,
    default_store_root,
    discover_features,
    extraction_features,
    read_sequences,
    study_facts,
    verify_role,
    write_sequences,
)


ARRAY_FILES: dict[str, tuple[str, ...]] = {
    POOLED_MAX: ("pooled_max.npy",),
    POOLED_MEAN: ("pooled_mean.npy",),
    POOLED_COUNT: ("pooled_count.npy",),
    RESIDUE_TOPK: ("residue_features.npy", "residue_values.npy"),
}
FILE_ROLES = {name: role for role, names in ARRAY_FILES.items() for name in names}
CONTEXT_FILES = ("manifest.json", "protein_index.parquet", "extraction_identity.json")
FORMAT = "annotation_vocabulary_extraction_cache"
DUPLICATE_POLICIES = ("strict", "first")
_POOLED_DTYPES = {STUDY: np.dtype(np.float32), ANALYSIS: np.dtype(np.float16)}


@dataclass(slots=True)
class LegacyCache:
    """One old-format extraction directory, read but never written."""

    directory: Path
    generation: str
    manifest: dict[str, Any]
    index: pd.DataFrame
    facts: ExtractionFacts
    arrays: dict[str, Path]


def read_legacy_cache(directory: str | Path, *, overrides: Mapping[str, Any] | None = None) -> LegacyCache:
    """Read the manifest, index, and array headers of an old-format extraction.

    `overrides` fills configuration fields a merged analysis run's manifest lacks (`base_repo`,
    `sae_repo`, `sae_layer`, `max_length`); a value the manifest does record wins over an override.
    """
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    index = pd.read_parquet(directory / "protein_index.parquet")
    arrays = {name: directory / name for name in FILE_ROLES if (directory / name).is_file()}
    if "settings" in manifest and "files" in manifest:
        generation = STUDY
    elif "config" in manifest and "metrics" in manifest:
        generation = ANALYSIS
    else:
        raise ValueError(f"{directory / 'manifest.json'} is neither an analysis nor a study extraction manifest")
    if not arrays:
        raise ValueError(f"{directory} holds no extraction array to convert")
    headers = {name: np.load(path, mmap_mode="r", allow_pickle=False) for name, path in arrays.items()}
    residue_dtype = headers.get("residue_values.npy")
    if generation == STUDY:
        facts = study_facts(
            manifest["settings"],
            residue_value_dtype=None if residue_dtype is None else str(residue_dtype.dtype),
        )
    else:
        config = _analysis_config(directory, manifest, overrides or {})
        metrics = manifest["metrics"]
        facts = analysis_facts(config, codebook_size=int(metrics["codebook_dim"]), k=int(metrics["k"]))
    _check_headers(headers, index, facts)
    return LegacyCache(directory, generation, manifest, index, facts, arrays)


def _analysis_config(directory: Path, manifest: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    """The extraction configuration of an analysis cache, following `merged_from` when needed."""
    config = dict(manifest["config"])
    if "sae_layer" not in config and isinstance(config.get("merged_from"), list):
        sources = []
        for source in config["merged_from"]:
            source_manifest = Path(source)
            source_manifest = source_manifest if source_manifest.is_absolute() else directory / source_manifest
            if (source_manifest / "manifest.json").is_file():
                sources.append(json.loads((source_manifest / "manifest.json").read_text(encoding="utf-8"))["config"])
        wanted = ("base_repo", "sae_repo", "sae_layer", "max_length")
        if sources and len({tuple(item.get(key) for key in wanted) for item in sources}) == 1:
            config = {**sources[0], **config}
    for key, value in overrides.items():
        config.setdefault(key, value)
    if "sae_layer" not in config:
        raise ValueError(
            "The manifest does not record sae_layer (a merged run); pass it, and base_repo, sae_repo, "
            "and max_length, with --set NAME=VALUE."
        )
    return config


def _check_headers(headers: Mapping[str, np.ndarray], index: pd.DataFrame, facts: ExtractionFacts) -> None:
    """Require each array to have the shape and dtype its generation wrote."""
    # headers: (n, f) for pooled roles, (r, k) for residue roles
    pooled_dtype = _POOLED_DTYPES[facts.generation]
    for name, array in headers.items():
        role = FILE_ROLES[name]
        if role in POOLED_ROLES:
            expected_dtype = np.dtype(np.uint16) if role == POOLED_COUNT else pooled_dtype
            if array.shape != (len(index), facts.codebook_size) or array.dtype != expected_dtype:
                raise ValueError(
                    f"{name} is {array.dtype}{array.shape}; expected {expected_dtype}"
                    f"{(len(index), facts.codebook_size)}"
                )
        elif name == "residue_features.npy":
            residues = int(index["n_residues"].sum())
            if array.shape != (residues, facts.k) or array.dtype != np.uint16:
                raise ValueError(f"{name} is {array.dtype}{array.shape}; expected uint16{(residues, facts.k)}")
        elif array.shape != (int(index["n_residues"].sum()), facts.k) or str(array.dtype) != facts.residue_value_dtype:
            raise ValueError(f"{name} is {array.dtype}{array.shape}, unlike the residue indices or the recorded dtype")


def processed_sequences(cache: LegacyCache, table: str | Path) -> list[str]:
    """The processed text of every index row, from a table of accession and sequence.

    The processed text is the prefix the extraction embedded: `sequence[:n_residues]`. Every index
    accession must be in the table exactly once, and the table's lengths must agree with the
    index. A study cache also checks each processed digest against the index, and the full-sequence
    digest when the table holds the full sequence.
    """
    frame = pd.read_parquet(table, columns=["accession", "sequence"])
    if frame["accession"].duplicated().any():
        raise ValueError("The sequence table repeats an accession")
    text = pd.Series(frame["sequence"].to_numpy(dtype=object), index=frame["accession"])
    index = cache.index
    absent = ~index["accession"].isin(text.index)
    if absent.any():
        raise ValueError(f"{int(absent.sum())} indexed accessions are absent from the sequence table")
    full = text.loc[index["accession"]].tolist()
    lengths = index["n_residues"].to_numpy(dtype=np.int64)  # (n,)
    processed = [sequence[:length] for sequence, length in zip(full, lengths, strict=True)]
    if any(len(sequence) != length for sequence, length in zip(processed, lengths, strict=True)):
        raise ValueError("A sequence is shorter than its recorded residue count")
    if cache.generation == ANALYSIS:
        if "length" in index and any(
            len(sequence) != int(length) for sequence, length in zip(full, index["length"], strict=True)
        ):
            raise ValueError("A sequence length differs from the recorded original length")
        return processed
    if [_sha256(sequence) for sequence in processed] != index["processed_sequence_sha256"].tolist():
        raise ValueError("Processed sequences differ from the index processed_sequence_sha256 values")
    complete = np.array(
        [len(sequence) == int(length) for sequence, length in zip(full, index["full_length"], strict=True)]
    )
    if complete.any():
        digests = index["original_sequence_sha256"].to_numpy(dtype=object)
        if any(_sha256(full[row]) != digests[row] for row in np.flatnonzero(complete)):
            raise ValueError("Full sequences differ from the index original_sequence_sha256 values")
    return processed


def _sha256(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def _first_occurrences(sequences: Sequence[str]) -> set[int]:
    seen: dict[str, int] = {}
    for row, sequence in enumerate(sequences):
        seen.setdefault(sequence, row)
    return set(seen.values())


def decode_pooled(cache: LegacyCache, role: str, sequences: Sequence[str], *, policy: str = "strict") -> Iterator[tuple[str, Tensor]]:
    """Yield `(sequence, (c,) tensor)` for a pooled role, in index order.

    Counts are widened from uint16 to float32, which is exact. With policy `first` a repeated
    sequence is yielded once, at its first row; `strict` yields every row and leaves repeats with
    differing rows to `convert_rows`, which refuses them.
    """
    (name,) = ARRAY_FILES[role]
    array = np.load(cache.arrays[name], mmap_mode="r", allow_pickle=False)  # (n, c)
    keep = _first_occurrences(sequences) if policy == "first" else None
    for row, sequence in enumerate(sequences):
        if keep is not None and row not in keep:
            continue
        vector = np.array(array[row], dtype=np.float32 if role == POOLED_COUNT else array.dtype)  # (c,)
        yield sequence, torch.from_numpy(vector)


def decode_residues(cache: LegacyCache, sequences: Sequence[str], *, policy: str = "strict") -> Iterator[tuple[str, TopKRow]]:
    """Yield `(sequence, TopKRow)` with `(l, k)` indices and values, in index order."""
    indices_array = np.load(cache.arrays["residue_features.npy"], mmap_mode="r", allow_pickle=False)  # (r, k)
    values_array = np.load(cache.arrays["residue_values.npy"], mmap_mode="r", allow_pickle=False)  # (r, k)
    offsets = cache.index["residue_offset"].to_numpy(dtype=np.int64)  # (n,)
    lengths = cache.index["n_residues"].to_numpy(dtype=np.int64)  # (n,)
    keep = _first_occurrences(sequences) if policy == "first" else None
    for row, sequence in enumerate(sequences):
        if keep is not None and row not in keep:
            continue
        start, stop = int(offsets[row]), int(offsets[row] + lengths[row])
        indices = torch.from_numpy(np.array(indices_array[start:stop], dtype=np.int32))  # (l, k)
        values = torch.from_numpy(np.array(values_array[start:stop]))  # (l, k)
        yield sequence, TopKRow(indices, values)


def convert_extraction(
    directory: str | Path, sequences_table: str | Path, *, store_root: str | Path | None = None,
    duplicate_policy: str = "strict", roles: Sequence[str] | None = None,
    rows_per_segment: int = 100_000, window_rows: int = 1_024, overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert one old-format extraction directory into a feature store beside it.

    Returns a summary with the store root, the sidecar, and for each converted role its key, the
    conversion receipt counts, and any collapsed duplicates. Calling it again resumes: committed
    segments stay and only the comparison of every row is repeated.

    `duplicate_policy` decides what happens when two accessions share a processed sequence. The
    store holds one row per sequence, so `strict` requires the old rows to be identical and
    otherwise raises; `first` keeps the first accession's row and records how many rows were
    collapsed. The collapse changes the numbers of the later accessions and says so in the origin.
    """
    if duplicate_policy not in DUPLICATE_POLICIES:
        raise ValueError(f"duplicate_policy must be one of {DUPLICATE_POLICIES}")
    directory = Path(directory)
    cache = read_legacy_cache(directory, overrides=overrides)
    sequences = processed_sequences(cache, sequences_table)
    available = [role for role in ARRAY_FILES if all(name in cache.arrays for name in ARRAY_FILES[role])]
    chosen = list(roles) if roles is not None else available
    unavailable = [role for role in chosen if role not in available]
    if unavailable or not chosen:
        raise ValueError(f"Cannot convert roles {unavailable or chosen}; the directory holds {available}")
    root = Path(store_root) if store_root is not None else default_store_root(directory)
    accessions = cache.index["accession"].tolist()
    sidecar = write_sequences(root, accessions, sequences)
    kept = _first_occurrences(sequences)
    collapsed = [accessions[row] for row in range(len(sequences)) if row not in kept]
    context = [describe_file(directory / name) for name in CONTEXT_FILES if (directory / name).is_file()]
    described: dict[str, dict[str, Any]] = {}
    features = extraction_features(cache.facts, residues=RESIDUE_TOPK in chosen)
    summary: dict[str, Any] = {
        "root": str(root), "generation": cache.generation, "sequences": sidecar,
        "duplicates": {"policy": duplicate_policy, "repeated_rows": len(collapsed)}, "roles": {},
    }
    for role in chosen:
        files = []
        for name in ARRAY_FILES[role]:
            described.setdefault(name, describe_file(cache.arrays[name]))
            files.append(described[name])
        origin = {
            "format": FORMAT,
            "generation": cache.generation,
            "role": role,
            "decoder": f"{__name__}.{'decode_residues' if role == RESIDUE_TOPK else 'decode_pooled'}",
            "files": [*context, *files],
            "sequence_table": describe_file(sequences_table),
            "aligned_sequences_sha256": aligned_sequences_digest(accessions, sequences),
            "duplicate_policy": duplicate_policy,
            "repeated_rows": len(collapsed),
            "collapsed_accessions_sha256": hashlib.sha256("\n".join(collapsed).encode()).hexdigest(),
        }
        if role == RESIDUE_TOPK:
            decoder = partial(decode_residues, cache, sequences, policy=duplicate_policy)
        else:
            decoder = partial(decode_pooled, cache, role, sequences, policy=duplicate_policy)
        store = FeatureStore.open(root, features[role])
        receipt = convert_rows(
            store, decoder, origin=origin, rows_per_segment=rows_per_segment, window_rows=window_rows,
        )
        summary["roles"][role] = {"key": features[role].key, **_receipt_summary(receipt)}
    return summary


def _receipt_summary(receipt: ConversionReceipt) -> dict[str, Any]:
    return {
        "segments": list(receipt.segments), "source_rows": receipt.source_rows,
        "written": receipt.written, "skipped": receipt.skipped, "verified": receipt.verified,
    }


def conversion_origin(feature_directory: str | Path) -> dict[str, Any]:
    """The single conversion origin recorded in every commit marker of one converted feature."""
    origins = []
    for receipt in FeatureStore.read_only(feature_directory).segments():
        conversion = receipt.metadata.get("conversion")
        if conversion is None:
            raise ValueError(f"{feature_directory} holds a segment that was not converted from an old cache")
        origins.append(conversion["origin"])
    if not origins or any(origin != origins[0] for origin in origins):
        raise ValueError(f"{feature_directory} mixes conversions of different old caches")
    return origins[0]


def verify_converted_manifest(
    directory: str | Path, manifest: Mapping[str, Any], index: pd.DataFrame, *, include_local: bool,
) -> None:
    """Check an old study manifest's checksum inventory through the store converted from it.

    The manifest's array entries name bytes that may no longer exist. The store keeps, in each
    commit marker, the digest and size of every file it was decoded from, so an array is accepted
    when the store's origin records exactly the manifest's `sha256` and `size`. Files that are not
    arrays are checked on disk as before. Every stored byte is re-verified too.
    """
    directory = Path(directory).resolve()
    inventory = manifest.get("files", {})
    required = {"protein_index.parquet", "pooled_max.npy"}
    if include_local:
        required |= {"residue_features.npy", "residue_values.npy"}
    if not required.issubset(inventory):
        raise ValueError("Extraction manifest lacks required array checksums")
    for name, expected in inventory.items():
        if name in FILE_ROLES:
            continue
        path = (directory / name).resolve()
        if path.parent != directory:
            raise ValueError("Extraction manifest contains a nonlocal array path")
        if not path.is_file() or path.stat().st_size != expected["size"] or _file_sha256(path) != expected["sha256"]:
            raise ValueError(f"Extraction checksum or size mismatch: {name}")
    root = default_store_root(directory)
    if not (root / SEQUENCES_FILE).is_file():
        raise ValueError(
            f"{directory} still holds its extraction only as .npy arrays; convert it with "
            f"python -m annotation_vocabulary.legacy_extraction_cache {directory} --sequences TABLE"
        )
    found = discover_features(root)
    sequences = read_sequences(root)
    check_sequence_alignment(index, sequences)
    listed = sequences["sequence"].tolist()
    needed = {FILE_ROLES[name] for name in required if name in FILE_ROLES}
    for role, names in ARRAY_FILES.items():
        if not all(name in inventory for name in names):
            continue
        if role not in found:
            if role in needed:
                raise ValueError(
                    f"The {role} cache has not been converted; run python -m "
                    f"annotation_vocabulary.legacy_extraction_cache {directory} --sequences TABLE"
                )
            continue
        recorded = {entry["name"]: entry for entry in conversion_origin(found[role])["files"]}
        for name in (*names, "protein_index.parquet"):
            entry, expected = recorded.get(name), inventory[name]
            if entry is None or entry["bytes"] != expected["size"] or entry["sha256"] != expected["sha256"]:
                raise ValueError(f"Stored {role} was not converted from the checksummed {name}")
        verify_role(root, role, listed, index)


def is_converted_array(path: str | Path) -> bool:
    """True for a retired `.npy` array that is gone because its extraction was converted to the store.

    A manifest's inventory and a receipt's binding still name such an array by digest and size. Its
    bytes are checked through the store's conversion origin (`verify_converted_manifest`) instead of
    on disk, so a receipt written before the conversion keeps verifying after the array is removed.
    """
    path = Path(path)
    return path.name in FILE_ROLES and not path.exists() and (default_store_root(path.parent) / SEQUENCES_FILE).is_file()


def _file_sha256(path: Path) -> str:
    return describe_file(path)["sha256"]


def _parse_overrides(pairs: Sequence[str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for pair in pairs:
        name, separator, value = pair.partition("=")
        if not separator or not name:
            raise ValueError(f"--set expects NAME=VALUE; received {pair!r}")
        overrides[name] = int(value) if name in {"sae_layer", "max_length"} else value
    return overrides


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("extraction_dir")
    parser.add_argument("--sequences", required=True, help="parquet with accession and sequence columns")
    parser.add_argument("--store-root", default=None, help="default: EXTRACTION_DIR/features")
    parser.add_argument("--duplicate-policy", choices=DUPLICATE_POLICIES, default="strict")
    parser.add_argument("--roles", nargs="+", default=None, choices=tuple(ARRAY_FILES))
    parser.add_argument("--rows-per-segment", type=int, default=100_000)
    parser.add_argument("--set", dest="overrides", nargs="*", default=[], metavar="NAME=VALUE")
    arguments = parser.parse_args(argv)
    summary = convert_extraction(
        arguments.extraction_dir, arguments.sequences, store_root=arguments.store_root,
        duplicate_policy=arguments.duplicate_policy, roles=arguments.roles,
        rows_per_segment=arguments.rows_per_segment, overrides=_parse_overrides(arguments.overrides),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
