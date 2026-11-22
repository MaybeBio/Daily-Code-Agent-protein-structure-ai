"""``loupmd doctor``: checks this installation and changes nothing.

One line per check, ``[ ok ]``, ``[warn]`` or ``[FAIL]``, with what to do about anything that is not ok. The exit
status is 1 if a check failed. The probes are module-level functions so that the tests can replace each of them.
"""
from __future__ import annotations

import ctypes
import importlib.util
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import _gpu, cache, models
from ..bundles import EXPORT_MODULES
from ..errors import LoupError

OK, WARN, FAIL = "ok", "warn", "FAIL"
RUNTIME_LIBRARIES = ("libcudart.so.13", "libcublas.so.13", "libcublasLt.so.13")
MIN_COMPUTE_CAPABILITY = 80           # PLAN.md A5: the own SGEMM needs cp.async, the hybrid GEMMs TF32 tensor cores
CUBIN_OF_MAJOR = {8: "tf32x3_hyb_sm80.cubin", 9: "tf32x3_hyb_sm90.cubin", 12: "tf32x3_hyb_sm120.cubin"}
CUBIN_OF_CAPABILITY = {80: "gemm_tc_hyb_sm80.cubin"}      # the file the engine loads on 8.0 (src/engine.cu)


@dataclass(frozen=True)
class Check:
    status: str      # OK, WARN or FAIL
    what: str
    detail: str = ""
    fix: str = ""

    def lines(self):
        mark = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[FAIL]"}[self.status]
        out = [f"{mark} {self.what}" + (f": {self.detail}" if self.detail else "")]
        if self.fix and self.status != OK:
            out.append(f"       fix: {self.fix}")
        return out


# ------------------------------------------------------------------------------------------------- probes

def probe_gpus():
    """``[(name, driver, compute capability as major * 10 + minor)]`` from nvidia-smi; raises OSError without it."""
    return _gpu.query_gpus()


def probe_runtime_library(name):
    """Load one CUDA runtime library as the engine's library will find it; raises OSError if it cannot."""
    from .. import _core

    try:
        ctypes.CDLL(name)
    except OSError:
        _core._preload_nvidia_libs()   # the NVIDIA pip wheels, as loupmd itself falls back to
        ctypes.CDLL(name)


def probe_library():
    """``(path, version string)`` of libloupmd; raises LoupError (cannot load, other interface version)."""
    from .. import _core

    return _core.library_path(), _core.library_version()


def probe_module(name):
    return importlib.util.find_spec(name) is not None


# ------------------------------------------------------------------------------------------------- checks

def check_gpu():
    try:
        gpus = probe_gpus()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return [Check(FAIL, "NVIDIA GPU and driver", str(exc),
                      "Install the NVIDIA driver; in WSL2, install it on Windows and check that nvidia-smi runs.")], []
    if not gpus:
        return [Check(FAIL, "NVIDIA GPU and driver", "nvidia-smi lists no GPU", "Check the driver installation.")], []
    out = []
    for index, (name, driver, cap) in enumerate(gpus):
        text = f"GPU {index}: {name}, driver {driver}, compute capability {cap // 10}.{cap % 10}"
        if cap < MIN_COMPUTE_CAPABILITY:
            out.append(Check(FAIL, text, "LoupMD needs compute capability 8.0 or newer",
                             "Use an RTX 30-series / A100 or newer GPU."))
        else:
            out.append(Check(OK, text))
    return out, gpus


def check_runtime_libraries():
    out = []
    for name in RUNTIME_LIBRARIES:
        try:
            probe_runtime_library(name)
            out.append(Check(OK, f"CUDA runtime library {name}"))
        except OSError as exc:
            out.append(Check(FAIL, f"CUDA runtime library {name}", str(exc).splitlines()[0],
                             "Install the CUDA 13 runtime (the nvidia-*-cu13 pip wheels, or a CUDA 13 toolkit on the "
                             "loader path)."))
    return out


def check_library():
    try:
        path, version = probe_library()
    except LoupError as exc:
        return [Check(FAIL, "libloupmd", exc.what, exc.next_step or "Build the library with `make`.")], None
    except OSError as exc:
        return [Check(FAIL, "libloupmd", str(exc), "Build the library with `make`.")], None
    return [Check(OK, f"libloupmd {version}", str(path))], Path(path)


def check_cubins(library, gpus):
    if library is None or not gpus:
        return []
    out = []
    for index, (name, _, cap) in enumerate(gpus):
        cubin = CUBIN_OF_CAPABILITY.get(cap, CUBIN_OF_MAJOR.get(cap // 10))
        if cubin is None:
            out.append(Check(WARN, f"tensor-core GEMM kernels for GPU {index}",
                             f"none is shipped for compute capability {cap // 10}.{cap % 10}",
                             "Nothing to do: the engine runs on its other GEMMs, somewhat slower."))
            continue
        path = Path(os.environ.get("LOUP_HYBRID_CUBIN") or library.parent / "cubins" / cubin)
        if path.is_file():
            out.append(Check(OK, f"tensor-core GEMM kernels for GPU {index}", str(path)))
        else:
            out.append(Check(WARN, f"tensor-core GEMM kernels for GPU {index}", f"{path} not found",
                             "Keep the cubins/ folder beside libloupmd.so; without it the engine runs somewhat slower."))
    return out


def check_cache():
    try:
        root = cache.cache_root()
    except LoupError as exc:
        return [Check(FAIL, "cache root", exc.what, exc.next_step or "")]
    probe = root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not os.access(probe, os.W_OK):
        return [Check(FAIL, "cache root", f"{root} cannot be written (no write access to {probe})",
                      f"Set {cache.CACHE_VARIABLE} to a writable directory.")]
    return [Check(OK, "cache root", f"{root}" + ("" if root.exists() else " (not created yet)"))]


def check_models(hashes=True):
    found, bad = [], []
    seen = set()
    for entry in models.LABELS.values():
        if entry.checkpoint.name in seen:
            continue
        seen.add(entry.checkpoint.name)
        try:
            path = models.resolve_checkpoint(entry.label).path
        except LoupError:
            continue
        found.append(path)
        if hashes and models.sha256_of(path) != entry.checkpoint.sha256:
            bad.append((entry, path))
    out = [Check(FAIL, f"model file {path.name}", f"{path} is not the released file of {entry.label!r} (its SHA-256 "
                 "differs from the label table's)",
                 f"Delete it and download the release again: loupmd models --download {entry.label}")
           for entry, path in bad]
    if not found:
        out.append(Check(WARN, "model files", "none found",
                         f"Set {models.MODELS_VARIABLE} to your model folder, or download one: loupmd models "
                         "--download LABEL."))
    elif not bad:
        out.append(Check(OK, "model files", f"{len(found)} of {len(seen)} released files found"
                         + (", hashes match the label table" if hashes else ", hashes not checked")))
    return out


def check_export_extra():
    missing = [name for name in EXPORT_MODULES if not probe_module(name)]
    if missing:
        return [Check(WARN, "export extra", f"not installed (missing: {', '.join(missing)})",
                      "Only needed to turn a checkpoint into a bundle: pip install 'loupmd[export]'. Bundles exported "
                      "elsewhere run without it.")]
    return [Check(OK, "export extra", "torch, mace and e3nn are importable")]


def run_checks(hashes=True):
    checks, gpus = check_gpu()
    checks += check_runtime_libraries()
    library_checks, library = check_library()
    checks += library_checks
    checks += check_cubins(library, gpus)
    checks += check_cache()
    checks += check_models(hashes)
    checks += check_export_extra()
    return checks


# ------------------------------------------------------------------------------------------------- command

def add_parser(sub):
    parser = sub.add_parser("doctor", help="check this installation (changes nothing)",
                            description="Checks the GPU and driver, the CUDA runtime libraries, libloupmd and its "
                                        "interface version, the tensor-core GEMM kernels for the card, the cache "
                                        "root, the model files' hashes and the export extra. Changes nothing.")
    parser.add_argument("--no-hashes", action="store_true", help="do not hash the model files (they can be large)")
    parser.set_defaults(run=run)


def run(args) -> int:
    checks = run_checks(hashes=not args.no_hashes)
    for check in checks:
        for line in check.lines():
            print(line)
    failed = sum(c.status == FAIL for c in checks)
    warned = sum(c.status == WARN for c in checks)
    print(f"{len(checks)} checks: {failed} failed, {warned} with a warning")
    return 1 if failed else 0
