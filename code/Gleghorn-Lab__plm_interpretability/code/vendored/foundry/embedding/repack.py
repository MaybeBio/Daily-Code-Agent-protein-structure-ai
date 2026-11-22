"""Repack a store down to the proteins and streams it should keep, from the parts it already holds.

Logan, 2026-10-01: full residue streams only for interaction data; 2026-10-19: only Atlas (PPI, PLI, CAMP) keeps them, and
no store keeps the SAE streams. `repack_store` rewrites a store into a new root with only the kept rows of the kept
streams: each source part yields one part of its kept rows, with the same descriptors, keys, row identities and values, so
nothing is embedded again. The rows are selected by tensor operations on the packed layout, never row by row. A source may
hold its commit markers alone and fetch each part as it is read (``fetch``), so a store published on the Hub repacks with
a few parts on disk at a time.

Symbols: b rows (proteins) of a part; n = sum(l_i + 2) stored token rows; w stored columns; k SAE codes per token row.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import torch

from collections import deque
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from torch import Tensor
from tqdm.auto import tqdm

from foundry.digests import sha256_file
from .canonical import MANIFEST_FILE, manifest_features, open_canonical_view, read_manifest, sequence_inventory, write_manifest
from .pooled import COMPARE_BUDGET, compare_views


REPACK_FILE = "repack.json"
REPACK_SCHEMA = "canonical_token_repack_v1"
GIB = 1024**3
PROGRESS_SECONDS = 15


@dataclass(frozen=True, slots=True)
class SourcePart:
    """One part of a source stream that holds at least one kept row, with what its commit marker says about it."""

    segment: str
    number: int
    path: Path
    digests: tuple[str, ...]  # b row keys in part order
    residues: tuple[int, ...]  # b stored rows per row key (zero for dense and csr)
    sidecar: Path | None  # the part's row identities, one JSON object per row
    sha256: str  # the part file's digest, as its commit marker states it
    sidecar_sha256: str | None
    tensor_bytes: int  # the part's tensor payload, its size before it is fetched


@dataclass(frozen=True, slots=True)
class PackedPart:
    """Kept rows of one source part, packed in the stream's layout and ready for `SegmentWriter.append_packed`."""

    digests: list[str]
    residues: list[int]
    tensors: dict[str, Tensor]
    identities: list[dict[str, Any]]


def keep_mask(digests: tuple[str, ...], keep: Collection[str]) -> Tensor:
    """Which of the b rows of a part are kept."""
    mask = torch.tensor([digest in keep for digest in digests], dtype=torch.bool)  # (b,)
    return mask  # (b,)


def select_rows(layout: str, tensors: Mapping[str, Tensor], mask: Tensor) -> dict[str, Tensor]:
    """The packed tensors of a part restricted to the rows where ``mask`` is true, in the same layout.

    dense: ``values`` (b, w). csr: ``indptr`` (b + 1,), ``indices`` and ``values`` (nnz,). ragged: ``offsets`` (b + 1,),
    ``values`` (n, w). ragged_topk: ``offsets`` (b + 1,), ``indices`` and ``values`` (n, k).
    """
    # tensors: (b, w) dense; (b + 1,) and (nnz,) csr; (b + 1,) and (n, w) ragged; top-k adds (n, k). mask: (b,) bool.
    # The output has b' = mask.sum() rows.
    if layout == "dense":
        return {"values": tensors["values"][mask]}  # (b', w)
    boundary = "indptr" if layout == "csr" else "offsets"
    bounds = tensors[boundary]  # (b + 1,) int64
    spans = bounds[1:] - bounds[:-1]  # (b,) stored rows (ragged) or entries (csr) per row
    covered = torch.repeat_interleave(mask, spans)  # (n,) bool: the stored rows of kept row i
    selected: dict[str, Tensor] = {name: value[covered] for name, value in tensors.items() if name != boundary}
    selected[boundary] = torch.cat([torch.zeros(1, dtype=bounds.dtype), torch.cumsum(spans[mask], 0)])  # (b' + 1,)
    return selected  # same layout: (b' + 1,) boundaries and (n', w) or (nnz',) values, n' = sum of the kept spans


def part_residues(layout: str, tensors: Mapping[str, Tensor], count: int) -> list[int]:
    """Stored rows per row of packed ``tensors`` holding ``count`` rows: l + 2 for a ragged layout, zero for dense and csr."""
    # tensors: (b' + 1,) offsets and (n', w) values ragged; (b', w) dense; (b' + 1,) and (nnz',) csr
    if layout in {"ragged", "ragged_topk"}:
        offsets = tensors["offsets"]  # (b' + 1,)
        return (offsets[1:] - offsets[:-1]).tolist()
    return [0] * count


def source_parts(directory: Path, keep: Collection[str]) -> Iterator[SourcePart]:
    """The parts of the stream directory ``directory`` that hold a kept row, segment by segment in commit order."""
    markers = sorted((directory / "segments").glob("*/run.json"))
    for marker in markers:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        for part in payload["parts"]:
            digests = tuple(part["digests"])
            if not keep.isdisjoint(digests):
                identity = part.get("row_metadata")
                yield SourcePart(
                    marker.parent.name, int(part["part"]), marker.parent / f"part-{int(part['part']):05d}.safetensors",
                    digests, tuple(part["residues"]), None if identity is None else marker.parent / identity["file"],
                    part["sha256"], None if identity is None else identity["sha256"], int(part["tensor_bytes"]),
                )


def marker_digests(directory: Path) -> set[str]:
    """Every row key the commit markers of the stream directory ``directory`` name."""
    held: set[str] = set()
    for marker in (directory / "segments").glob("*/run.json"):
        for part in json.loads(marker.read_text(encoding="utf-8"))["parts"]:
            held.update(part["digests"])
    return held


def fetched_file(path: Path, sha256: str, fetch: Callable[[Path], None] | None) -> bool:
    """Make sure ``path`` is on disk with digest ``sha256``, fetching it when absent; returns whether it was fetched."""
    if path.is_file():
        return False
    if fetch is None:
        raise FileNotFoundError(f"{path} is not on disk and this repack fetches nothing.")
    fetch(path)
    if sha256_file(path) != sha256:
        path.unlink()
        raise RuntimeError(f"{path} arrived with a digest other than its commit marker's {sha256[:12]}.")
    return True


def load_part(layout: str, source: SourcePart, keep: Collection[str],
              fetch: Callable[[Path], None] | None = None) -> PackedPart:
    """Read a source part and keep the rows in ``keep``; the file leaves the page cache once it is read.

    A part or sidecar absent from disk is fetched, held to its commit marker's digest, and deleted once read.
    """
    import gzip

    from safetensors import safe_open

    fetched = fetched_file(source.path, source.sha256, fetch)
    with safe_open(source.path, framework="pt", device="cpu") as handle:
        tensors = {name: handle.get_tensor(name) for name in handle.keys()}  # noqa: SIM118  # the part's tensors, whole
    drop_from_page_cache(source.path)
    if fetched:
        source.path.unlink()
    mask = keep_mask(source.digests, keep)  # (b,)
    chosen = select_rows(layout, tensors, mask)
    positions = mask.nonzero().flatten().tolist()
    identities: list[dict[str, Any]] = []
    if source.sidecar is not None:
        assert source.sidecar_sha256 is not None
        sidecar_fetched = fetched_file(source.sidecar, source.sidecar_sha256, fetch)
        rows = json.loads(gzip.decompress(source.sidecar.read_bytes()))  # b identities, in part order
        if sidecar_fetched:
            source.sidecar.unlink()
        identities = [rows[position] for position in positions]
    digests = [source.digests[position] for position in positions]
    return PackedPart(digests, part_residues(layout, chosen, len(digests)), chosen, identities)


def drop_from_page_cache(path: Path) -> None:
    """Ask the kernel to drop a file's cached pages, as the store's own writer does for what it writes (a GH200 counts them as HBM)."""
    if hasattr(os, "posix_fadvise"):
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.posix_fadvise(descriptor, 0, 0, os.POSIX_FADV_DONTNEED)
        finally:
            os.close(descriptor)


def prefetched(parts: list[SourcePart], load: Callable[[SourcePart], PackedPart], *, workers: int) -> Iterator[PackedPart]:
    """``load`` over ``parts`` in order with at most ``2 * workers`` loaded parts waiting, so memory stays bounded."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        waiting: deque[Future[PackedPart]] = deque()
        pending = iter(parts)
        for part in pending:
            waiting.append(pool.submit(load, part))
            if len(waiting) >= 2 * workers:
                break
        while waiting:
            packed = waiting.popleft().result()
            for part in pending:
                waiting.append(pool.submit(load, part))
                break
            yield packed


def segment_name(key: str, index: int) -> str:
    """A filename-safe, deterministic segment name for the ``index``-th segment a repack writes into stream ``key``."""
    return f"repack-{hashlib.sha256(key.encode('ascii')).hexdigest()[:16]}-{index:05d}"


def group_parts(parts: list[SourcePart], budget_bytes: int) -> list[list[SourcePart]]:
    """``parts`` in order, grouped so each group's files total about ``budget_bytes``: one group is one committed segment."""
    groups: list[list[SourcePart]] = [[]]
    used = 0
    for part in parts:
        size = part.tensor_bytes
        if groups[-1] and used + size > budget_bytes:
            groups.append([])
            used = 0
        groups[-1].append(part)
        used += size
    return groups


def repack_stream(
    root: Path, feature: Any, source_directory: Path, keep: Collection[str], *, segment_bytes: int, workers: int,
    fetch: Callable[[Path], None] | None = None,
) -> dict[str, int]:
    """Write the kept rows of one source stream into ``root`` as new segments; returns rows, parts and bytes written."""
    from fastplms.features import FeatureStore

    store = FeatureStore.open(root, feature, deep_verify=False)
    groups = group_parts(list(source_parts(source_directory, keep)), segment_bytes)
    recorded = (root / feature.key / "feature.json").read_text(encoding="utf-8")

    def descriptor_unchanged() -> None:
        if (root / feature.key / "feature.json").read_text(encoding="utf-8") != recorded:
            raise RuntimeError(f"The descriptor of {feature.key} changed while it was repacked.")

    written = {"rows": 0, "parts": 0, "bytes": 0, "segments": 0}
    bar = tqdm(total=sum(len(group) for group in groups), desc=feature.key[:28], unit="part",
               mininterval=PROGRESS_SECONDS, file=sys.stderr)
    for index, group in enumerate(groups):
        metadata = {"job": REPACK_SCHEMA, "source_stream": source_directory.name}
        with store.segment(segment_name(feature.key, index), metadata, before_commit=descriptor_unchanged,
                           verify_staged=False) as writer:
            for packed in prefetched(group, lambda part: load_part(feature.layout, part, keep, fetch), workers=workers):
                record = writer.append_packed(
                    writer.reserve_part(), packed.digests, packed.tensors, packed.residues,
                    row_metadata=packed.identities or None,
                )
                written["rows"] += len(packed.digests)
                written["parts"] += 1
                written["bytes"] += record["tensor_bytes"]
                bar.update(1)
        written["segments"] += 1
    bar.close()
    return written


def repack_store(
    source: Path, target: Path, keep: Collection[str], *, list_revision: str, keep_flags: tuple[str, ...],
    segment_bytes: int = 8 * GIB, workers: int = 3, streams: Sequence[str] = (), absent_ok: bool = False,
    fetch: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    """Write a store at ``target`` holding the ``streams`` of ``source`` (every stream when empty) for the rows in ``keep``.

    The manifest and descriptors are the source's with only the kept streams listed, so keys never change and a later
    `embed` appends to the repacked store, computing those streams alone (`canonical.retain_streams`). A kept row absent
    from a kept stream of the source stops the repack, unless ``absent_ok``: then the rows every kept stream holds are
    written and the rest recorded as `absent`, for an `embed` to add. ``fetch`` materializes a part or sidecar the source
    holds only in its commit markers. Refuses a ``target`` that already holds a store. Returns the record also written to
    `repack.json`.
    """
    if (target / MANIFEST_FILE).exists():
        raise FileExistsError(f"{target} already holds a store; a repack never overwrites.")
    manifest = read_manifest(source)
    names = tuple(streams) or tuple(manifest["streams"])
    unknown = sorted(set(names) - set(manifest["streams"]))
    if unknown:
        raise ValueError(f"{source} holds no stream named {unknown}.")
    features = manifest_features(source, manifest, names)
    wanted = set(keep)
    held = set.intersection(*(marker_digests(source / feature.key) for feature in features.values()))
    absent = sorted(wanted - held)
    if absent and not absent_ok:
        raise ValueError(f"{len(absent)} of the {len(wanted)} kept rows are missing from a kept stream of the source store")
    kept = wanted & held
    # The streams repack side by side, each with its own fetchers and writer, since one stream's writer bounds its rate
    # (about 220 MB/s of source parts on a GH200, 2026-10-19) well below what the machine downloads.
    with ThreadPoolExecutor(max_workers=len(features)) as pool:
        futures = {name: pool.submit(repack_stream, target, feature, source / feature.key, kept, segment_bytes=segment_bytes,
                                     workers=workers, fetch=fetch) for name, feature in features.items()}
        written: dict[str, Any] = {name: future.result() for name, future in futures.items()}
    for name, counts in written.items():
        if counts["rows"] != len(kept):
            raise AssertionError(f"{name}: repacked {counts['rows']} rows, expected {len(kept)}")
    write_manifest(target, {**manifest, "streams": {name: manifest["streams"][name] for name in names}})
    record = {
        "schema": REPACK_SCHEMA, "finished_utc": datetime.now(UTC).isoformat(), "base": manifest["base"],
        "source_store": str(source), "source_manifest_sha256": hashlib.sha256((source / MANIFEST_FILE).read_bytes()).hexdigest(),
        "list_revision": list_revision, "keep_flags": list(keep_flags), "kept_rows": len(kept), "streams": written,
        "dropped_streams": sorted(set(manifest["streams"]) - set(names)), "absent": absent,
        "note": "rows copied from the source parts without re-embedding; keys, descriptors, identities and values are the source's",
    }
    (target / REPACK_FILE).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def check_repack(
    source: Path, target: Path, texts: Sequence[str], keys: Sequence[str], keep: Collection[str], *, sample: int, seed: int,
    deep: bool = True,
) -> dict[str, Any]:
    """The repacked store holds exactly the kept rows in every stream, intact, and ``sample`` of them equal the source's.

    ``texts`` and ``keys`` are the list's normalized sequences and keys. Every stream is opened with deep verification
    (each part and sidecar re-hashed against its commit marker) unless ``deep`` is false, and must hold exactly the rows in
    ``keep``: no kept row missing, no other row present.
    """
    from fastplms.features import FeatureStore

    manifest = read_manifest(target)
    features = manifest_features(target, manifest, tuple(manifest["streams"]))
    wanted = sorted(keep)
    accounting: dict[str, dict[str, int]] = {}
    for name, feature in features.items():
        store = FeatureStore.open(target, feature, deep_verify=deep)
        absent = set(wanted) - store.present_digests(wanted)
        if absent or len(store) != len(wanted):
            raise AssertionError(f"{name}: {len(absent)} kept rows absent, {len(store)} rows held, {len(wanted)} expected")
        accounting[name] = {"rows": len(store), "segments": len(list((target / feature.key / "segments").glob("*/run.json")))}
    if sample == 0:  # a source of commit markers alone has no rows to read; each fetched part matched its marker's digest
        return {"streams": accounting, "sampled_sequences": 0, "rows_compared": 0, "deep": deep, "seed": seed}
    pool = [text for text, key in zip(texts, keys, strict=True) if key in keep]
    chosen = random.Random(seed).sample(pool, min(sample, len(pool)))
    inventory = sequence_inventory(chosen)
    with open_canonical_view(source, inventory, budget=COMPARE_BUDGET) as before, open_canonical_view(
        target, inventory, budget=COMPARE_BUDGET,
    ) as after:
        compared = compare_views(before, after, tuple(features), chosen)
    return {"streams": accounting, "sampled_sequences": len(chosen), "rows_compared": compared, "deep": deep, "seed": seed}


def hub_source(
    repository: str, revision: str, folder: str, local_dir: Path, streams: Sequence[str] = (), *, workers: int = 16,
    download: Callable[[str], Path] | None = None, listing: Sequence[str] | None = None,
) -> tuple[Path, Callable[[Path], None]]:
    """A repack source for the store published at ``repository``/``folder``@``revision``: its markers here, its parts on demand.

    Downloads the manifest and, for each of ``streams`` (every stream when empty), the descriptor and every commit marker
    into ``local_dir``/``folder``; returns that root and the ``fetch`` that `repack_store` calls for a part or sidecar, which
    downloads it to the same path. ``download`` and ``listing`` replace the Hub download of one repository path and the
    repository's file list (a test).
    """
    from huggingface_hub import HfApi

    from .hub import _hub_download

    fetch_path = download or _hub_download(repository, revision, local_dir)
    manifest = json.loads(fetch_path(f"{folder}/{MANIFEST_FILE}").read_text(encoding="utf-8"))
    names = tuple(streams) or tuple(manifest["streams"])
    unknown = sorted(set(names) - set(manifest["streams"]))
    if unknown:
        raise ValueError(f"{repository}/{folder} holds no stream named {unknown}.")
    files = listing if listing is not None else HfApi().list_repo_files(repository, repo_type="dataset", revision=revision)
    prefixes = tuple(f"{folder}/{manifest['streams'][name]['key']}/" for name in names)
    wanted = [path for path in files if path.startswith(prefixes)
              and (path.endswith("/feature.json") or (path.endswith("/run.json") and "/segments/" in path))]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in tqdm(pool.map(fetch_path, wanted), total=len(wanted), desc="markers", unit="file",
                      mininterval=PROGRESS_SECONDS, file=sys.stderr):
            pass

    def fetch(path: Path) -> None:
        fetch_path(path.relative_to(local_dir).as_posix())

    return local_dir / folder, fetch


__all__ = ["REPACK_FILE", "REPACK_SCHEMA", "PackedPart", "SourcePart", "check_repack", "hub_source", "keep_mask",
           "marker_digests", "repack_store", "repack_stream", "select_rows", "source_parts"]
