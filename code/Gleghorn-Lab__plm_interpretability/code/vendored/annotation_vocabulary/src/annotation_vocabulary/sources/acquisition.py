"""Pinned, resumable acquisition of annotation source files."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


_CHUNK_SIZE = 1024 * 1024
_RELEASE_HEADER_NAMES = frozenset(
    {
        "accept-ranges",
        "content-length",
        "content-range",
        "date",
        "etag",
        "last-modified",
        "x-release-date",
        "x-uniprot-release",
    }
)


@dataclass(frozen=True)
class SourceSpec:
    """A source URL pinned by its expected SHA-256 digest."""

    name: str
    url: str
    sha256: str
    release: str | None = None
    filename: str | None = None
    expected_bytes: int | None = None

    def __post_init__(self) -> None:
        digest = self.sha256.lower()
        invalid_character = any(
            character not in "0123456789abcdef" for character in digest
        )
        if len(digest) != 64 or invalid_character:
            raise ValueError("sha256 must be a 64-character hexadecimal digest")
        if not self.name or not self.url:
            raise ValueError("name and url are required")
        if self.expected_bytes is not None and self.expected_bytes < 0:
            raise ValueError("expected_bytes must be non-negative")
        object.__setattr__(self, "sha256", digest)

    @property
    def output_name(self) -> str:
        """Return the explicit filename or the URL basename."""

        if self.filename:
            return Path(self.filename).name
        name = Path(self.url.split("?", maxsplit=1)[0]).name
        if not name:
            raise ValueError(f"cannot derive a filename for source {self.name!r}")
        return name


@dataclass(frozen=True)
class FetchSpec:
    """A source location whose observed bytes will establish a new pin."""

    name: str
    url: str
    release: str
    filename: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("name", "url", "release"):
            value = getattr(self, field_name)
            if not value or value.strip() != value or "\n" in value or "\r" in value:
                raise ValueError(f"{field_name} must be a non-empty single-line string")

    @property
    def output_name(self) -> str:
        """Return the explicit filename or the URL basename."""

        if self.filename:
            return Path(self.filename).name
        name = Path(self.url.split("?", maxsplit=1)[0]).name
        if not name:
            raise ValueError(f"cannot derive a filename for source {self.name!r}")
        return name


@dataclass(frozen=True)
class AcquiredSource:
    """Observed provenance for one finalized source file."""

    name: str
    url: str
    path: str
    sha256: str
    observed_bytes: int
    release: str | None
    release_headers: dict[str, str]
    reused: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def sha256_file(path: Path) -> tuple[str, int]:
    """Return the SHA-256 digest and byte count of ``path``."""

    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as source:
        while chunk := source.read(_CHUNK_SIZE):
            digest.update(chunk)
            byte_count += len(chunk)
    return digest.hexdigest(), byte_count


def _release_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key.lower(): value
        for key, value in headers.items()
        if key.lower() in _RELEASE_HEADER_NAMES
    }


def _verified_existing(path: Path, spec: SourceSpec) -> tuple[str, int]:
    if not path.is_file():
        raise FileNotFoundError(path)
    observed_digest, observed_bytes = sha256_file(path)
    if observed_digest != spec.sha256:
        raise ValueError(f"checksum mismatch for existing source {path}")
    if spec.expected_bytes is not None and observed_bytes != spec.expected_bytes:
        raise ValueError(f"byte count mismatch for existing source {path}")
    return observed_digest, observed_bytes


def acquire_source(
    spec: SourceSpec,
    destination: Path,
    *,
    offline: bool = False,
    timeout: float = 60.0,
) -> AcquiredSource:
    """Acquire one pinned source, resuming a partial download when possible.

    In offline mode, only an already-finalized file with a matching digest is
    accepted. Authorization headers are never constructed or copied.
    """

    destination.mkdir(parents=True, exist_ok=True)
    final_path = destination / spec.output_name
    if final_path.exists():
        try:
            _, observed_bytes = _verified_existing(final_path, spec)
        except (ValueError, FileNotFoundError):
            if offline:
                raise
        else:
            return AcquiredSource(
                spec.name,
                spec.url,
                str(final_path),
                spec.sha256,
                observed_bytes,
                spec.release,
                {},
                True,
            )

    if offline:
        raise FileNotFoundError(f"verified offline source is unavailable: {final_path}")

    partial_path = final_path.with_name(f".{final_path.name}.part")
    resume_bytes = partial_path.stat().st_size if partial_path.exists() else 0
    request_headers = {"Range": f"bytes={resume_bytes}-"} if resume_bytes else {}
    request = Request(spec.url, headers=request_headers, method="GET")
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as error:
        if resume_bytes and error.code == 416:
            partial_path.unlink(missing_ok=True)
            return acquire_source(spec, destination, offline=False, timeout=timeout)
        raise

    response_headers = _release_headers(dict(response.headers.items()))
    append = bool(resume_bytes and response.status == 206)
    if resume_bytes and not append:
        resume_bytes = 0
    mode = "ab" if append else "wb"
    with response, partial_path.open(mode) as target:
        while chunk := response.read(_CHUNK_SIZE):
            target.write(chunk)
        target.flush()
        os.fsync(target.fileno())

    observed_digest, observed_bytes = sha256_file(partial_path)
    if observed_digest != spec.sha256:
        raise ValueError(f"checksum mismatch for downloaded source {spec.name}")
    if spec.expected_bytes is not None and observed_bytes != spec.expected_bytes:
        raise ValueError(f"byte count mismatch for downloaded source {spec.name}")
    os.replace(partial_path, final_path)
    return AcquiredSource(
        spec.name,
        spec.url,
        str(final_path),
        observed_digest,
        observed_bytes,
        spec.release,
        response_headers,
        False,
    )


def fetch_source(
    spec: FetchSpec,
    destination: Path,
    *,
    timeout: float = 60.0,
) -> AcquiredSource:
    """Fetch one source and record the bytes used to establish its pin.

    This is a trust-on-first-use operation. A later release build verifies the
    resulting strict pin before parsing.
    """

    destination.mkdir(parents=True, exist_ok=True)
    final_path = destination / spec.output_name
    if final_path.exists():
        raise FileExistsError(
            "Unpinned fetch destination already exists; supply that path explicitly "
            f"to pin it or choose a clean download directory: {final_path}"
        )

    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=destination,
        prefix=f".{final_path.name}.",
        suffix=".download",
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
    request = Request(spec.url, method="GET")
    try:
        response = urlopen(request, timeout=timeout)
        response_headers = _release_headers(dict(response.headers.items()))
        with response, temporary_path.open("wb") as target:
            while chunk := response.read(_CHUNK_SIZE):
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        observed_digest, observed_bytes = sha256_file(temporary_path)
        os.replace(temporary_path, final_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return AcquiredSource(
        spec.name,
        spec.url,
        str(final_path),
        observed_digest,
        observed_bytes,
        spec.release,
        response_headers,
        False,
    )


def acquire_sources(
    specs: tuple[SourceSpec, ...] | list[SourceSpec],
    destination: Path,
    *,
    offline: bool = False,
    timeout: float = 60.0,
    manifest_path: Path | None = None,
) -> dict[str, object]:
    """Acquire sources and return a JSON-serializable manifest."""

    acquired = [
        acquire_source(
            spec,
            destination,
            offline=offline,
            timeout=timeout,
        )
        for spec in specs
    ]
    manifest: dict[str, object] = {
        "sources": [source.to_dict() for source in acquired],
        "offline": offline,
    }
    if manifest_path is not None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=manifest_path.parent, delete=False
        ) as temporary:
            json.dump(manifest, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, manifest_path)
    return manifest
