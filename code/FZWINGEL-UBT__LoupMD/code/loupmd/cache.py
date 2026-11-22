"""LoupMD's cache root and its sub-directories (PLAN.md section 4.7).

One root, ``$LOUPMD_CACHE`` (default ``~/.cache/loupmd``; ``LOUP_CACHE_DIR`` is accepted as an older name), with
``models/``, ``bundles/``, ``plans/``, ``gate_refs/`` and ``lib/``. The root must lie outside the Python
installation (``sys.prefix``): a cache inside it would be removed with the environment and shipped by tools that
copy environments.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import CacheLocationError, InputError

CACHE_VARIABLE = "LOUPMD_CACHE"
OLD_CACHE_VARIABLE = "LOUP_CACHE_DIR"
KINDS = ("models", "bundles", "plans", "gate_refs", "lib")


def cache_root(environ=None) -> Path:
    """The cache root: ``$LOUPMD_CACHE``, else ``$LOUP_CACHE_DIR``, else ``~/.cache/loupmd``. Not created."""
    environ = os.environ if environ is None else environ
    chosen = environ.get(CACHE_VARIABLE) or environ.get(OLD_CACHE_VARIABLE)
    root = Path(os.path.expanduser(chosen)) if chosen else Path.home() / ".cache" / "loupmd"
    root = root.resolve()
    prefix = Path(sys.prefix).resolve()
    if root == prefix or prefix in root.parents:
        raise CacheLocationError(
            f"the cache root {root} lies inside the Python installation {prefix}",
            why="a cache there is deleted with the environment and copied with it",
            next_step=f"Set {CACHE_VARIABLE} to a directory outside the environment.")
    return root


_plan_dir_set = None    # the value this module last put into the process's LOUP_CACHE_DIR


def engine_plan_environment(environ=None):
    """Point the engine's GEMM plan files (``LOUP_CACHE_DIR``, which ``src/engine.cu`` reads) at the cache root when
    ``LOUPMD_CACHE`` names one, so plans live where ``loupmd cache`` looks. A ``LOUP_CACHE_DIR`` the caller set is
    kept; one this function set before follows a changed ``LOUPMD_CACHE``. Returns the directory the engine uses, or
    None for its default (``$HOME/.cache/loupmd``)."""
    global _plan_dir_set
    env = os.environ if environ is None else environ
    current = env.get(OLD_CACHE_VARIABLE)
    own = current is not None and current == _plan_dir_set
    if env.get(CACHE_VARIABLE) and (not current or own):
        _plan_dir_set = str(cache_root(env))
        env[OLD_CACHE_VARIABLE] = _plan_dir_set
    elif own and not env.get(CACHE_VARIABLE):
        del env[OLD_CACHE_VARIABLE]
        _plan_dir_set = None
    return env.get(OLD_CACHE_VARIABLE) or None


def cache_dir(kind: str, create: bool = True, environ=None) -> Path:
    """``<cache root>/<kind>`` for one of ``KINDS``."""
    if kind not in KINDS:
        raise ValueError(f"unknown cache kind {kind!r}; kinds are {', '.join(KINDS)}")
    path = cache_root(environ) / kind
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------------- locks, listing, pruning

@contextlib.contextmanager
def locked(path):
    """Hold an exclusive lock for ``path`` (a file ``<path>.lock`` beside it) while the block runs. Another process
    in the same block for the same path waits. The lock file stays; it is empty and is skipped by the listing."""
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _is_locked(path) -> bool:
    """True while another process holds ``locked(path)``."""
    lock_path = Path(str(path) + ".lock")
    if not lock_path.is_file():
        return False
    with open(lock_path, "a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False


_IN_USE: set = set()   # files this process has handed out (bundles it loaded): prune leaves them


def mark_in_use(path):
    _IN_USE.add(Path(path).resolve())


@dataclass(frozen=True)
class CacheEntry:
    kind: str       # one of KINDS
    path: Path
    size: int       # bytes
    used: float     # last use: the later of the file's access and modification times (seconds since the epoch)


def _kind_of_root_file(name: str):
    """Files of the layout before the sub-directories lie in the root itself: bundles and GEMM plan files."""
    if name.endswith(".loup"):
        return "bundles"
    if name.startswith("plans_") and name.endswith(".bin"):
        return "plans"
    return None


def entries(kinds=None, environ=None) -> list:
    """Every cached file of the given kinds (default: all), oldest use first."""
    kinds = KINDS if kinds is None else tuple(kinds)
    for kind in kinds:
        if kind not in KINDS:
            raise ValueError(f"unknown cache kind {kind!r}; kinds are {', '.join(KINDS)}")
    root = cache_root(environ)
    found = []

    def add(kind, path):
        if path.name.endswith((".lock", ".part")) or ".part." in path.name or ".tmp." in path.name:
            return
        st = path.stat()
        found.append(CacheEntry(kind, path, st.st_size, max(st.st_atime, st.st_mtime)))

    for kind in kinds:
        directory = root / kind
        if directory.is_dir():
            for path in sorted(p for p in directory.rglob("*") if p.is_file()):
                add(kind, path)
    if root.is_dir():
        for path in sorted(p for p in root.iterdir() if p.is_file()):
            kind = _kind_of_root_file(path.name)
            if kind in kinds:
                add(kind, path)
    return sorted(found, key=lambda e: (e.used, str(e.path)))


def sizes(environ=None) -> dict:
    """Bytes per kind, and under ``"total"``."""
    out = {kind: 0 for kind in KINDS}
    for entry in entries(environ=environ):
        out[entry.kind] += entry.size
    out["total"] = sum(out[kind] for kind in KINDS)
    return out


PRUNABLE = ("bundles", "plans", "gate_refs")   # what LoupMD can make again by itself; models and lib only by name


def prune(older_than_days=None, max_size=None, kinds=PRUNABLE, keep=(), dry_run=False, environ=None, now=None) -> list:
    """Remove cached files and return the entries removed (with ``dry_run``: that would be removed).

    ``older_than_days`` removes what was not used for that long. ``max_size`` (bytes) then removes the least
    recently used files until the kinds together fit. Never removed: files in ``keep``, files this process has in
    use (``mark_in_use``), and files another process holds a lock on.
    """
    if older_than_days is None and max_size is None:
        raise InputError("prune needs a rule", next_step="Give older_than_days, max_size or both.")
    now = time.time() if now is None else now
    kept = {Path(p).resolve() for p in keep} | _IN_USE
    candidates = entries(kinds, environ)

    def removable(entry):
        return entry.path.resolve() not in kept and not _is_locked(entry.path)

    doomed = []
    if older_than_days is not None:
        limit = now - float(older_than_days) * 86400.0
        doomed = [e for e in candidates if e.used < limit and removable(e)]
    if max_size is not None:
        remaining = [e for e in candidates if e not in doomed]
        total = sum(e.size for e in remaining)
        for entry in remaining:          # oldest use first
            if total <= max_size:
                break
            if removable(entry):
                doomed.append(entry)
                total -= entry.size
    if not dry_run:
        for entry in doomed:
            entry.path.unlink(missing_ok=True)
            Path(str(entry.path) + ".lock").unlink(missing_ok=True)
    return doomed


def parse_size(text: str) -> int:
    """``"1G"``, ``"500M"``, ``"2.5GiB"``, ``"1000000"`` as bytes (binary multiples)."""
    match = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*([kKmMgGtT]?)(i?[bB])?\s*", str(text))
    if not match:
        raise InputError(f"{text!r} is not a size", next_step="Write it as 500M, 1G or a number of bytes.")
    power = {"": 0, "k": 1, "m": 2, "g": 3, "t": 4}[match.group(2).lower()]
    return int(float(match.group(1)) * 1024 ** power)
