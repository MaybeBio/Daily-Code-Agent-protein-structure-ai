"""The bundle cache: the ``.loup`` file for a model, an element set, a head and a charge / spin setting.

A bundle is exported once and reused. Its file name carries a key over everything that decides its contents (the
model file's SHA-256, the elements, the head, charge and spin, and the exporter's own sources), so a changed
exporter never finds an old bundle. Two processes that ask for the same bundle export it once: the export
runs under a file lock and the file appears under its name only when it is complete.

The exporter is ``loupmd.export``, run in a process of its own (it needs torch and sets its own environment).
``ensure_loup_bundle`` is the flat cache of the source checkout (bundles directly in the cache root), which the
engine tests and the developer scripts use; ``ensure_bundle`` finds its bundles as well.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from . import cache, kernels
from .errors import InputError, LoupError

_PACKAGE = Path(__file__).resolve().parent
# Everything on LoupMD's side that decides a bundle's contents: the exporters, the product-kernel emitter whose
# source the bundle carries, and the container writer. Their hash is part of the cache key, so a changed exporter
# never finds an old bundle, with no version number to remember. (A change to the product basis changes the product
# signatures a bundle carries; the loader then looks for those kernels: the library's, a plugin's, or the bundle's
# own source compiled at load, JIT_DESIGN.md stage 3.)
EXPORTER_SOURCES = [_PACKAGE / "export" / name for name in ("__init__.py", "generic.py", "polar.py", "bundle.py",
                                                            "gen_product.py")]
# What `python -m loupmd.export` imports and the runtime does not: the export extra of pyproject.toml.
EXPORT_MODULES = ("torch", "mace", "e3nn")
_DIGESTS: dict = {}


def _model_digest(model_path) -> str:
    """sha256 of the model file, memoised per (path, size, mtime) so a large model is hashed once."""
    st = os.stat(model_path)
    memo_key = (str(Path(model_path).resolve()), st.st_size, st.st_mtime_ns)
    if memo_key not in _DIGESTS:
        h = hashlib.sha256()
        with open(model_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _DIGESTS[memo_key] = h.hexdigest()
    return _DIGESTS[memo_key]


def exporter_fingerprint(paths=None) -> str:
    """Hash of the files in ``paths`` (default EXPORTER_SOURCES), by name and content; a missing file counts as empty."""
    h = hashlib.sha256()
    for p in EXPORTER_SOURCES if paths is None else paths:
        p = Path(p)
        h.update(p.name.encode() + b"\0" + (p.read_bytes() if p.is_file() else b"") + b"\0")
    return h.hexdigest()[:16]


def missing_export_modules() -> list:
    """The modules of the export extra that this environment lacks (nothing is imported)."""
    return [name for name in EXPORT_MODULES if importlib.util.find_spec(name) is None]


def exporter_environment(environ=None) -> dict:
    """The environment of an export process: this package's parent directory first on PYTHONPATH, so
    ``python -m loupmd.export`` finds the package the caller imported, installed or not."""
    env = dict(os.environ if environ is None else environ)
    parts = [str(_PACKAGE.parent)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def default_generic() -> bool:
    """Every model takes the generic kernels. The kernels specialised to MACE-OMAT-0 medium (0.0.1: ``generic=False``
    or ``LOUP_GENERIC=0``) were retired; ``generic`` arguments are accepted and ignored, and so is the variable."""
    return True


def _integral(name, value):
    """Charge and spin multiplicity are categorical model inputs: 0.5 must not become 0, and 1.0 is 1."""
    if value is None:
        return None
    if isinstance(value, bool) or int(value) != value:
        raise InputError(f"{name} must be an integer, got {value!r}")
    return int(value)


def bundle_name(model_path, atomic_numbers, head=None, generic=None, charge=None, spin_multiplicity=None) -> str:
    """The file name of the bundle: model stem, elements and the 16-digit key. ``generic`` is ignored."""
    charge = _integral("charge", charge)
    spin_multiplicity = _integral("spin_multiplicity", spin_multiplicity)
    z_sorted = sorted({int(z) for z in atomic_numbers})
    tag = (f"{_model_digest(str(model_path))}|{z_sorted}|{head}|{charge}|"
           f"{spin_multiplicity}|{exporter_fingerprint()}")
    key = hashlib.sha256(tag.encode()).hexdigest()[:16]
    return f"{Path(model_path).stem}_{'_'.join(map(str, z_sorted))}_{key}.loup"


def _export_command(model_path, z_sorted, output, head, charge, spin_multiplicity, exporter):
    exporter = exporter or [sys.executable, "-m", "loupmd.export"]
    cmd = [*exporter, "--model", str(model_path), "--elements", ",".join(map(str, z_sorted)), "--output", str(output)]
    if head is not None:
        cmd += ["--head", head]
    if charge is not None:
        cmd += ["--charge", str(charge)]
    if spin_multiplicity is not None:
        cmd += ["--spin-multiplicity", str(spin_multiplicity)]
    return cmd


def ensure_bundle(model_path, atomic_numbers, *, head=None, generic=None, charge=None, spin_multiplicity=None,
                  environ=None, exporter=None) -> Path:
    """The cached bundle, exporting it on a miss.

    ``exporter`` replaces the export command's first words (``[python, -m, loupmd.export]``); the tests use it.
    ``generic`` is accepted and ignored: every model takes the generic kernels.
    """
    model_path = Path(model_path)
    if not model_path.is_file():
        raise InputError(f"model file {model_path} not found")
    charge = _integral("charge", charge)
    spin_multiplicity = _integral("spin_multiplicity", spin_multiplicity)
    z_sorted = sorted({int(z) for z in atomic_numbers})
    name = bundle_name(model_path, z_sorted, head, None, charge, spin_multiplicity)
    out = cache.cache_dir("bundles", environ=environ) / name
    old_layout = cache.cache_root(environ) / name       # where ensure_loup_bundle keeps its bundles
    for existing in (out, old_layout):
        if existing.is_file():
            cache.mark_in_use(existing)
            return existing
    with cache.locked(out):
        if not out.is_file():                           # another process may have exported it while we waited
            missing = missing_export_modules() if exporter is None else []
            if missing:
                raise LoupError(
                    f"no bundle of {model_path.name} for elements {z_sorted} is in the cache, and this environment "
                    "cannot export one",
                    why=f"the export extra is not installed (missing: {', '.join(missing)})",
                    next_step="Install it into this environment: pip install 'loupmd[export]'. Or copy a bundle "
                              f"that the same LoupMD version exported elsewhere to {out}.")
            part = out.with_name(out.name + f".part.{os.getpid()}")
            cmd = _export_command(model_path, z_sorted, part, head, charge, spin_multiplicity, exporter)
            try:
                done = subprocess.run(cmd, capture_output=True, text=True, env=exporter_environment())
                marked = [line for line in (done.stderr or "").splitlines()
                          if line.startswith(kernels.UNSUPPORTED_MARKER)]
                if done.returncode == kernels.UNSUPPORTED_STATUS and marked:
                    raise kernels.unsupported(model_path.name,
                                              marked[-1][len(kernels.UNSUPPORTED_MARKER):].split())
                if done.returncode != 0 and "No module named 'graph_longrange'" in (done.stderr or ""):
                    # A MACE-POLAR-1 checkpoint cannot even be loaded without it; the export extra has it since
                    # 0.0.2, an environment made for 0.0.1 does not.
                    raise LoupError(
                        f"the export of {model_path.name} needs the graph_longrange package",
                        why="MACE's POLAR-1 models are built on it, and this environment does not have it",
                        next_step="Install it into this environment: pip install 'loupmd[export]', or "
                                  "pip install graph_longrange==0.4.4.")
                if done.returncode != 0 or not part.is_file():
                    tail = (done.stderr or done.stdout or "").strip().splitlines()[-6:]
                    raise LoupError(f"the export of {model_path.name} for elements {z_sorted} failed",
                                    why="; ".join(tail) or f"the exporter ended with status {done.returncode}",
                                    next_step="Run the command by hand to see its full output: " + " ".join(cmd))
                os.replace(part, out)
            finally:
                part.unlink(missing_ok=True)
    cache.mark_in_use(out)
    return out


def ensure_loup_bundle(model_path: str, atomic_numbers: list[int], cache_dir: str | None = None,
                       head: str | None = None, generic: bool | None = None, charge: int | None = None,
                       spin_multiplicity: int | None = None) -> Path:
    """The cached bundle for (model contents, species, head, charge / spin, exporter sources) in the flat
    cache of the source checkout (``cache_dir``, default ``~/.cache/loupmd``), exporting it on a miss.

    Every model takes the generic kernels; ``generic`` is accepted and ignored (the kernels specialised to
    MACE-OMAT-0 medium were retired). ``head`` selects a multi-head model's head
    (default: omat_pbe if present, else the last head). ``charge`` and ``spin_multiplicity`` (total charge in e and
    2S + 1) apply to models with a total charge / spin embedding (MACE-OMOL-0; default 0 and 1); the export folds
    them into the bundle, so each setting is its own bundle. Other models refuse them."""
    def integral(name, v):  # categorical model inputs: 0.5 must not round to 0, 1.0 must share 1's bundle
        if v is None:
            return None
        if isinstance(v, bool) or int(v) != v:
            raise ValueError(f"{name} must be an integer, got {v!r}")
        return int(v)

    charge = integral("charge", charge)
    spin_multiplicity = integral("spin_multiplicity", spin_multiplicity)
    z_sorted = sorted({int(z) for z in atomic_numbers})
    cdir = Path(cache_dir or Path.home() / ".cache" / "loupmd")
    cdir.mkdir(parents=True, exist_ok=True)
    tag = (f"{_model_digest(model_path)}|{z_sorted}|{head}|{charge}|{spin_multiplicity}|"
           f"{exporter_fingerprint()}")
    key = hashlib.sha256(tag.encode()).hexdigest()[:16]
    out = cdir / f"{Path(model_path).stem}_{'_'.join(map(str, z_sorted))}_{key}.loup"
    if not out.is_file():
        cmd = _export_command(model_path, z_sorted, out, head, charge, spin_multiplicity, None)
        subprocess.run(cmd, check=True, env=exporter_environment())
    return out
