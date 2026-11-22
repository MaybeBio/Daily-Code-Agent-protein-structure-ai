"""Which models the library has kernels for, and kernel plugins for the others (plan task S2-T06).

The library is built with the product kernels of the models its release was generated from; the list is the
kernel manifest (``src/generated_generic_manifest.json`` in a checkout, ``_lib/generated_generic_manifest.json``
in an installed package): one signature per symmetric contraction. A model with another signature needs a
kernel plugin, a small shared library that ``loupmd build-kernels MODEL`` compiles with ``nvcc`` into the
cache's ``lib`` folder, where the engine finds it by the signature (``src/kernel_plugin.h``).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import cache
from .errors import InputError, LoupError, UnsupportedModel

_PACKAGE = Path(__file__).resolve().parent
MANIFEST_NAME = "generated_generic_manifest.json"
MANIFEST_SCHEMA = "loupmd.kernel-manifest/1"
PLUGIN_PATH_VARIABLE = "LOUP_KERNEL_PATH"
UNSUPPORTED_MARKER = "loupmd-unsupported-kernel:"      # the exporter's last stderr line before exit status 3
UNSUPPORTED_STATUS = 3
_HEADERS = ("generated_generic.cuh", "generated_sh16.cuh", "kernels_common.cuh", "kernel_plugin.h")


def manifest_path() -> Path | None:
    """The manifest of the library this package uses: shipped in ``_lib`` or, in a checkout, in ``src``."""
    for candidate in (_PACKAGE / "_lib" / MANIFEST_NAME, _PACKAGE.parent / "src" / MANIFEST_NAME):
        if candidate.is_file():
            return candidate
    return None


def load_manifest(path=None) -> dict | None:
    """The manifest as a dict, or ``None`` when there is none (a library from elsewhere: nothing is checked)."""
    path = manifest_path() if path is None else Path(path)
    if path is None:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != MANIFEST_SCHEMA:
        raise LoupError(f"{path} is not a kernel manifest of this version (schema {data.get('schema')!r})",
                        next_step="Rebuild the library and its generated files from one source tree.")
    return data


def plugin_directory(environ=None, create: bool = False) -> Path:
    """Where ``loupmd build-kernels`` puts kernel plugins: the cache's ``lib`` folder."""
    return cache.cache_dir("lib", create=create, environ=environ)


def plugin_path(signature: str, environ=None) -> Path:
    return plugin_directory(environ) / f"loupmd-kernels-{signature}.so"


_added = None       # the folder this module put into the process's LOUP_KERNEL_PATH last


def plugin_search_path(environ=None) -> str:
    """The engine's ``LOUP_KERNEL_PATH``: what the caller set, then the cache's ``lib`` folder. In the process's
    own environment the folder this module added before is replaced, so a changed cache root is followed."""
    global _added
    env = os.environ if environ is None else environ
    parts = [p for p in env.get(PLUGIN_PATH_VARIABLE, "").split(os.pathsep)
             if p and not (environ is None and p == _added)]
    own = str(plugin_directory(environ))
    if environ is None:
        _added = own
    return os.pathsep.join(parts + ([own] if own not in parts else []))


def missing_signatures(signatures, manifest=None, environ=None) -> list:
    """The signatures the library has no kernels for and no plugin exists for. With no manifest: none (unknown)."""
    manifest = load_manifest() if manifest is None else manifest
    if manifest is None:
        return []
    built = {product["signature"] for product in manifest["products"]}
    folders = [Path(p) for p in plugin_search_path(environ).split(os.pathsep) if p]
    return [sig for sig in dict.fromkeys(signatures)
            if sig not in built and not any((folder / f"loupmd-kernels-{sig}.so").is_file() for folder in folders)]


def unsupported(model_name: str, signatures, manifest=None) -> UnsupportedModel:
    """The error for a model with kernels the library lacks: it names the signatures and ``loupmd build-kernels``."""
    signatures = list(signatures)
    built = len((manifest or load_manifest() or {"products": []})["products"])
    error = _unsupported(model_name, signatures, built)
    error.signatures = signatures
    return error


def _unsupported(model_name, signatures, built) -> UnsupportedModel:
    return UnsupportedModel(
        f"{model_name}: no compiled kernels for its symmetric contraction (signature "
        f"{', '.join(signatures)})",
        why=f"the library has the kernels of {built} contraction signatures, those of the models its release was "
            "built from, and no kernel plugin for this one is in the cache",
        next_step=f"loupmd build-kernels {model_name} compiles them (needs nvcc from the CUDA toolkit and the export "
                  "extra); the model then loads as any other.",
        signature=signatures[0] if signatures else None)


# ------------------------------------------------------------------------------------------- building a plugin

def find_nvcc(environ=None) -> str:
    env = os.environ if environ is None else environ
    candidates = [shutil.which("nvcc", path=env.get("PATH"))]
    for root in (env.get("CUDA_HOME"), env.get("CUDA_PATH"), "/usr/local/cuda"):
        if root:
            candidates.append(str(Path(root) / "bin" / "nvcc"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise LoupError("nvcc was not found", why="kernel plugins are compiled on this machine",
                    next_step="Install the CUDA toolkit (13.x for this release) and put its bin folder on the PATH, "
                              "or set CUDA_HOME.")


def kernel_sources() -> tuple:
    """``(header folder, generator)``: the headers a plugin includes and ``gen_generic.py``, from a checkout
    (``src/``, ``codegen/``) or from an installed package (``_lib/kernel-src/``)."""
    for headers, generator in ((_PACKAGE.parent / "src", _PACKAGE.parent / "codegen" / "gen_generic.py"),
                               (_PACKAGE / "_lib" / "kernel-src", _PACKAGE / "_lib" / "kernel-src" / "gen_generic.py")):
        if generator.is_file() and all((headers / name).is_file() for name in _HEADERS):
            return headers, generator
    raise LoupError("the kernel sources are not part of this installation",
                    why=f"build-kernels needs {', '.join(_HEADERS)} and gen_generic.py",
                    next_step="Use a source checkout of LoupMD, or a release whose wheel ships them.")


def gpu_architecture() -> str:
    """``sm_XY`` of GPU 0, for nvcc's ``-arch``."""
    from . import _gpu

    try:
        capability = _gpu.query_gpus()[0][2]
    except (OSError, IndexError) as error:
        raise LoupError("the GPU's compute capability could not be read", why=str(error),
                        next_step="Name it: loupmd build-kernels MODEL --arch sm_89") from None
    return f"sm_{capability}"


def build_plugins(model_path, *, arch=None, force=False, environ=None, run=subprocess.run, log=print) -> list:
    """Compile the kernel plugins ``model_path`` needs into the cache's ``lib`` folder.

    Returns ``[(signature, path, built)]`` for every product signature of the model: ``built`` is ``False`` for
    one the library already has or whose plugin exists (unless ``force``). ``run`` is ``subprocess.run`` (the
    tests replace it).
    """
    from . import bundles

    model_path = Path(model_path)
    if not model_path.is_file():
        raise InputError(f"model file {model_path} not found")
    headers, generator = kernel_sources()
    manifest = load_manifest()
    built_in = {product["signature"] for product in (manifest or {"products": []})["products"]}
    out_dir = plugin_directory(environ, create=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="loupmd-kernels-") as scratch:
        done = run([sys.executable, str(generator), "--plugin", str(model_path), scratch], capture_output=True,
                   text=True, env=bundles.exporter_environment(environ))
        if done.returncode != 0:
            tail = (done.stderr or done.stdout or "").strip().splitlines()[-6:]
            raise LoupError(f"the kernel generator failed on {model_path.name}", why="; ".join(tail),
                            next_step="It needs the export extra (torch, e3nn, mace-torch, cuequivariance).")
        products = [line.split() for line in done.stdout.splitlines() if line.startswith("plugin ")]
        if not products:
            raise UnsupportedModel(f"{model_path.name} has no product the generic kernels cover",
                                   why="; ".join(line for line in done.stdout.splitlines() if line.startswith("skip "))
                                       or "the generator named none")
        nvcc = arch_flag = None
        for _, signature, _, _, source in products:
            target = out_dir / f"loupmd-kernels-{signature}.so"
            if not force and (signature in built_in or target.is_file()):
                why = "the library has these kernels" if signature in built_in else "its plugin is in the cache"
                log(f"{signature}: {why}")
                results.append((signature, target if target.is_file() else None, False))
                continue
            if nvcc is None:
                nvcc = find_nvcc(environ)
                arch_flag = arch or gpu_architecture()
            part = target.with_name(target.name + f".part.{os.getpid()}")
            # The shared CUDA runtime, as the library's: nvcc links a static copy by default, and kernels registered
            # with that copy are unknown to the runtime the library launches them through.
            cmd = [nvcc, "-O3", "-std=c++17", f"-arch={arch_flag}", f"-I{headers}", "-diag-suppress=1046",
                   "-Xcompiler", "-fPIC", "-shared", "--cudart", "shared", source, "-o", str(part)]
            log(f"{signature}: compiling for {arch_flag} ...")
            compiled = run(cmd, capture_output=True, text=True)
            if compiled.returncode != 0 or not part.is_file():
                part.unlink(missing_ok=True)
                tail = (compiled.stderr or compiled.stdout or "").strip().splitlines()[-8:]
                raise LoupError(f"nvcc failed on the kernels of signature {signature}", why="; ".join(tail),
                                next_step="Run it by hand: " + " ".join(cmd))
            os.replace(part, target)
            log(f"{signature}: {target} ({target.stat().st_size} bytes)")
            results.append((signature, target, True))
    return results
