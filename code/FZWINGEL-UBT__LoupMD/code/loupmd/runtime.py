"""``loupmd.runtime_info()``: what this process runs on (package, library, CUDA runtime, GPUs)."""
from __future__ import annotations

import platform
from dataclasses import dataclass

from . import _core, _gpu
from .errors import LoupError


@dataclass(frozen=True)
class GpuInfo:
    index: int
    name: str
    compute_capability: str      # "12.0"
    driver: str


@dataclass(frozen=True)
class RuntimeInfo:
    """A frozen record; ``print`` shows it as a few lines."""

    version: str                 # the loupmd package
    abi_version: int             # the C interface version this package binds
    library: str                 # the libloupmd.so this process uses (LOUP_LIB, the package's, or a checkout's)
    library_version: str | None  # loup_version(): release + build id; None when the library did not load
    library_error: str | None    # why it did not load
    cuda_runtime: str | None     # the libcudart this process loaded, once the library is loaded
    gpus: tuple                  # of GpuInfo
    gpu_error: str | None        # why no GPU is listed
    python: str

    def __str__(self):
        lines = [f"loupmd {self.version} (C interface {self.abi_version}), Python {self.python}"]
        if self.library_version is not None:
            lines.append(f"library {self.library_version} ({self.library})")
            lines.append(f"CUDA runtime: {self.cuda_runtime or 'not found among the loaded libraries'}")
        else:
            lines.append(f"library not loaded: {self.library_error}")
        for gpu in self.gpus:
            lines.append(f"GPU {gpu.index}: {gpu.name}, compute capability {gpu.compute_capability}, driver "
                         f"{gpu.driver}")
        if not self.gpus:
            lines.append(f"no GPU found: {self.gpu_error}")
        return "\n".join(lines)


def _loaded(part):
    """Path of the first shared library loaded into this process whose name contains ``part`` (Linux)."""
    try:
        with open("/proc/self/maps") as maps:
            for line in maps:
                if part in line:
                    return line.split(None, 5)[-1].strip()
    except OSError:
        pass
    return None


def runtime_info() -> RuntimeInfo:
    """Load the library if it is not loaded yet and describe the runtime. Never raises for a missing GPU or
    library: both are reported in the record (``loupmd doctor`` says how to fix them)."""
    from . import __version__

    library_version = library_error = None
    try:
        library_version = _core.library_version()
    except LoupError as exc:
        library_error = str(exc).replace("\n", "; ")
    gpus, gpu_error = (), None
    try:
        gpus = tuple(GpuInfo(index, name, f"{cap // 10}.{cap % 10}", driver)
                     for index, (name, driver, cap) in enumerate(_gpu.query_gpus()))
        if not gpus:
            gpu_error = "nvidia-smi lists none"
    except (OSError, ValueError) as exc:
        gpu_error = str(exc)
    return RuntimeInfo(version=__version__, abi_version=_core.ABI_VERSION, library=str(_core.library_path()),
                       library_version=library_version, library_error=library_error,
                       cuda_runtime=_loaded("libcudart") if library_version is not None else None,
                       gpus=gpus, gpu_error=gpu_error, python=platform.python_version())
