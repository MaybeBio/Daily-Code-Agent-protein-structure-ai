"""Bind every result-bearing external analysis input to a local file and immutable revision.

Extraction arrays live in the workspace feature store, so a stored input is bound by the SHA-256 of
each immutable file that holds its rows (`feature_cache.role_identity`). Its record keeps the
three-field shape of a file record: `path` is the feature directory, `bytes` the total size of those
files, and `sha256` the digest of their individual digests. The store is read through the
`features/sequences.parquet` sidecar, which is bound as `extraction_sequences`. The two per-residue
keys, `local_residue_features` and `local_residue_values`, are held by the one `residue_topk`
feature and carry the same identity. Frozen manifests that bound `.npy` files use the same keys, and
`export_interpretations.load_analysis_provenance` accepts them unchanged.
"""

import hashlib
import json
import re

from pathlib import Path

from .biohub import FEATURE_TABLE_FILE, FEATURE_TABLE_REPO
from ..feature_cache import (
    POOLED_COUNT,
    POOLED_MAX,
    POOLED_MEAN,
    RESIDUE_TOPK,
    SEQUENCES_FILE,
    default_store_root,
    role_identity,
)


COMMIT_OID_PATTERN = re.compile(r"[0-9a-f]{40}")
AGENT_LABEL_SOURCE_REPO = "biohub/ESMC-SAE-Overview"
POOLING_ROLES = {
    "max": POOLED_MAX,
    "mean": POOLED_MEAN,
    "count": POOLED_COUNT,
}
POOLING_MODES = tuple(POOLING_ROLES) + ("fraction",)


def _digest(path: Path) -> str:
    """Return a SHA-256 digest that covers every byte of a file."""
    if not path.exists():
        return "missing"
    digest = hashlib.sha256()
    bytes_read = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(1 << 20)
            if not block:
                break
            digest.update(block)
            bytes_read += len(block)
    return f"sha256:{digest.hexdigest()}:{bytes_read}"


def require_file(path: Path, label: str) -> Path:
    """Return an absolute file path or fail before the analysis creates output."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} is not a file: {resolved}")
    return resolved


def validate_commit_oid(field: str, value: str) -> str:
    """Require one exact lowercase 40-hex Git commit identifier."""
    if not COMMIT_OID_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be exactly 40 lowercase hexadecimal characters")
    return value


def _repository_pair(config: object, source: Path) -> tuple[str, str] | None:
    if not isinstance(config, dict):
        raise ValueError(f"extraction manifest config is not an object: {source}")
    base_repo = config.get("base_repo")
    sae_repo = config.get("sae_repo")
    if base_repo is None and sae_repo is None:
        return None
    if not isinstance(base_repo, str) or not base_repo.strip():
        raise ValueError(f"extraction manifest has no base_repo: {source}")
    if not isinstance(sae_repo, str) or not sae_repo.strip():
        raise ValueError(f"extraction manifest has no sae_repo: {source}")
    return base_repo, sae_repo


def extraction_repositories(
    extraction_manifest: Path,
) -> tuple[str, str, tuple[Path, ...]]:
    """Resolve one base-model and SAE repository pair from an extraction manifest."""
    manifest_path = require_file(extraction_manifest, "extraction manifest")
    manifest: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"extraction manifest is not an object: {manifest_path}")
    config = manifest.get("config")
    direct_pair = _repository_pair(config, manifest_path)
    if direct_pair is not None:
        return direct_pair[0], direct_pair[1], ()

    if not isinstance(config, dict):
        raise ValueError(f"extraction manifest config is not an object: {manifest_path}")
    merged_from = config.get("merged_from")
    if not isinstance(merged_from, list) or not merged_from:
        raise ValueError(
            f"extraction manifest has neither repository names nor merged_from: {manifest_path}"
        )

    source_manifests: list[Path] = []
    repository_pairs: set[tuple[str, str]] = set()
    for source in merged_from:
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"merged_from contains an invalid path: {manifest_path}")
        source_directory = Path(source).expanduser()
        if not source_directory.is_absolute():
            source_directory = manifest_path.parent / source_directory
        source_manifest = require_file(
            source_directory / "manifest.json", "merged extraction manifest"
        )
        source_document: object = json.loads(source_manifest.read_text(encoding="utf-8"))
        if not isinstance(source_document, dict):
            raise ValueError(f"extraction manifest is not an object: {source_manifest}")
        pair = _repository_pair(source_document.get("config"), source_manifest)
        if pair is None:
            raise ValueError(f"merged extraction manifest has no repository names: {source_manifest}")
        source_manifests.append(source_manifest)
        repository_pairs.add(pair)

    if len(repository_pairs) != 1:
        raise ValueError(
            "merged extraction manifests disagree on base-model or SAE repository: "
            f"{sorted(repository_pairs)}"
        )
    base_repo, sae_repo = next(iter(repository_pairs))
    unique_sources = tuple(sorted(set(source_manifests), key=str))
    return base_repo, sae_repo, unique_sources


def external_provenance(
    extraction_manifest: Path,
    base_model_revision: str,
    sae_revision: str,
    feature_table_revision: str,
    agent_label_source_revision: str,
    agent_labels_used: bool,
) -> tuple[dict[str, object], tuple[Path, ...]]:
    """Return immutable external repository identities and referenced source manifests."""
    base_repo, sae_repo, source_manifests = extraction_repositories(extraction_manifest)
    record: dict[str, object] = {
        "base_model": {
            "repo": base_repo,
            "revision": validate_commit_oid("base_model_revision", base_model_revision),
        },
        "sae": {
            "repo": sae_repo,
            "revision": validate_commit_oid("sae_revision", sae_revision),
        },
        "feature_table": {
            "repo": FEATURE_TABLE_REPO,
            "file": FEATURE_TABLE_FILE,
            "revision": validate_commit_oid(
                "feature_table_revision", feature_table_revision
            ),
        },
    }
    if agent_labels_used:
        record["agent_label_source"] = {
            "repo": AGENT_LABEL_SOURCE_REPO,
            "revision": validate_commit_oid(
                "agent_label_source_revision", agent_label_source_revision
            ),
        }
    else:
        if agent_label_source_revision:
            raise ValueError(
                "agent_label_source_revision requires a nonempty agent_label_table"
            )
        record["agent_label_source"] = {"status": "unused"}
    return record, source_manifests


def analysis_input_inventory(
    run_directory: Path,
    protein_table: Path,
    term_table: Path,
    feature_table: Path,
    agent_label_table: Path | None,
    pooling: str,
    skip_local: bool,
    extraction_source_manifests: tuple[Path, ...] = (),
) -> dict[str, object]:
    """Hash all files consumed by one analysis and mark disabled local inputs unused."""
    run_directory = run_directory.expanduser().resolve()
    if not run_directory.is_dir():
        raise NotADirectoryError(f"extraction run is not a directory: {run_directory}")
    if pooling not in POOLING_MODES:
        raise ValueError(f"unknown pooling mode: {pooling}")

    cache: dict[Path, dict[str, object]] = {}

    def bind(path: Path, label: str) -> dict[str, object]:
        resolved = require_file(path, label)
        if resolved not in cache:
            algorithm, digest, byte_count = _digest(resolved).split(":")
            if algorithm != "sha256":
                raise AssertionError(f"unexpected digest algorithm: {algorithm}")
            cache[resolved] = {
                "path": str(resolved),
                "bytes": int(byte_count),
                "sha256": digest,
            }
        return dict(cache[resolved])

    def unused(path: Path | None, reason: str) -> dict[str, object]:
        return {
            "path": str(path.expanduser().resolve()) if path is not None else None,
            "status": "unused",
            "reason": reason,
        }

    def stored(role: str) -> dict[str, object]:
        return dict(role_identity(run_directory, role))

    selected_pooling = "count" if pooling == "fraction" else pooling
    inputs: dict[str, object] = {
        "extraction_manifest": bind(
            run_directory / "manifest.json", "extraction manifest"
        ),
        "extraction_source_manifests": [
            bind(path, "merged extraction manifest")
            for path in extraction_source_manifests
        ],
        "protein_index": bind(
            run_directory / "protein_index.parquet", "extraction protein index"
        ),
        "extraction_sequences": bind(
            default_store_root(run_directory) / SEQUENCES_FILE, "extraction sequence sidecar"
        ),
        "protein_table": bind(protein_table, "protein table"),
        "term_table": bind(term_table, "term table"),
        "feature_table": bind(feature_table, "feature table"),
        "pooled": stored(POOLING_ROLES[selected_pooling]),
        "agent_label_table": (
            bind(agent_label_table, "agent label table")
            if agent_label_table is not None
            else unused(None, "not provided")
        ),
    }

    local_roles = {
        "local_residue_features": RESIDUE_TOPK,
        "local_residue_values": RESIDUE_TOPK,
        "local_pooled_count": POOLED_COUNT,
    }
    for name, role in local_roles.items():
        inputs[name] = (
            unused(default_store_root(run_directory), "skip_local=true")
            if skip_local
            else stored(role)
        )
    return inputs


def require_unchanged_inputs(
    initial: dict[str, object], final: dict[str, object]
) -> None:
    """Fail before manifest creation if a bound input changed during the analysis."""
    if initial == final:
        return
    changed = sorted(
        key
        for key in set(initial) | set(final)
        if initial.get(key) != final.get(key)
    )
    raise RuntimeError(f"analysis inputs changed during the run: {changed}")
