"""``loupmd doctor`` (plan task S2-T07). Every probe is replaced, so the tests need neither a GPU nor the library;
the last test runs the real command where a GPU is present."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from loupmd import models
from loupmd.cli import doctor
from loupmd.errors import BackendError

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def healthy(tmp_path, monkeypatch):
    """A machine on which every check passes: one RTX 5060 Ti, libraries present, a library beside its cubins, a
    writable cache, no model files, the export extra installed."""
    lib = tmp_path / "pkg" / "libloupmd.so"
    (lib.parent / "cubins").mkdir(parents=True)
    lib.write_bytes(b"")
    for name in doctor.CUBIN_OF_MAJOR.values():
        (lib.parent / "cubins" / name).write_bytes(b"")
    monkeypatch.setattr(doctor, "probe_gpus", lambda: [("NVIDIA GeForce RTX 5060 Ti", "621.14", 120)])
    monkeypatch.setattr(doctor, "probe_runtime_library", lambda name: None)
    monkeypatch.setattr(doctor, "probe_library", lambda: (lib, "0.1.0a1+0123456789abcdef"))
    monkeypatch.setattr(doctor, "probe_module", lambda name: True)
    monkeypatch.setenv("LOUPMD_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("LOUPMD_MODELS", str(tmp_path / "models"))
    monkeypatch.delenv("LOUP_CACHE_DIR", raising=False)
    monkeypatch.delenv("LOUP_HYBRID_CUBIN", raising=False)
    return tmp_path


def _status(checks, word):
    return [c for c in checks if word in c.what]


def _report(checks):
    return "\n".join(line for c in checks for line in c.lines())


def test_a_healthy_machine_has_no_failure_and_only_the_missing_models_warning(healthy, capsys):
    checks = doctor.run_checks()
    assert not [c for c in checks if c.status == doctor.FAIL], _report(checks)
    assert [c.what for c in checks if c.status == doctor.WARN] == ["model files"]
    text = _report(checks)
    assert "[ ok ] GPU 0: NVIDIA GeForce RTX 5060 Ti, driver 621.14, compute capability 12.0" in text
    assert "[ ok ] libloupmd 0.1.0a1+0123456789abcdef" in text
    assert "[ ok ] tensor-core GEMM kernels for GPU 0" in text and "tf32x3_hyb_sm120.cubin" in text
    assert "[ ok ] cache root" in text and "(not created yet)" in text
    assert not (healthy / "cache").exists()                      # the doctor changes nothing
    assert "[warn] model files: none found" in text and "fix: Set LOUPMD_MODELS" in text

    class Args:
        no_hashes = False

    assert doctor.run(Args()) == 0
    assert capsys.readouterr().out.strip().endswith("0 failed, 1 with a warning")


def _fail(checks):
    return [c for c in checks if c.status == doctor.FAIL]


def test_no_driver(healthy, monkeypatch):
    def missing():
        raise OSError("nvidia-smi was not found on the PATH")

    monkeypatch.setattr(doctor, "probe_gpus", missing)
    failed = _fail(doctor.run_checks())
    assert [c.what for c in failed] == ["NVIDIA GPU and driver"] and "nvidia-smi was not found" in failed[0].detail
    assert "Install the NVIDIA driver" in failed[0].fix


def test_a_gpu_below_compute_capability_8(healthy, monkeypatch):
    monkeypatch.setattr(doctor, "probe_gpus", lambda: [("Tesla T4", "580.1", 75)])
    failed = _fail(doctor.run_checks())
    assert len(failed) == 1 and "compute capability 7.5" in failed[0].what
    assert "needs compute capability 8.0 or newer" in failed[0].detail


def test_a_missing_cuda_runtime_library(healthy, monkeypatch):
    def load(name):
        if name == "libcublasLt.so.13":
            raise OSError("libcublasLt.so.13: cannot open shared object file: No such file or directory")

    monkeypatch.setattr(doctor, "probe_runtime_library", load)
    failed = _fail(doctor.run_checks())
    assert [c.what for c in failed] == ["CUDA runtime library libcublasLt.so.13"]
    assert "cannot open shared object file" in failed[0].detail and "CUDA 13 runtime" in failed[0].fix


def test_a_library_of_another_interface_version(healthy, monkeypatch):
    def load():
        raise BackendError("/x/libloupmd.so has C interface version 0, and this loupmd package needs version 1",
                           why="the library and the Python package come from different builds",
                           next_step="Rebuild the library from this source tree (`make`), or unset LOUP_LIB.")

    monkeypatch.setattr(doctor, "probe_library", load)
    checks = doctor.run_checks()
    failed = _fail(checks)
    assert [c.what for c in failed] == ["libloupmd"] and "interface version 0" in failed[0].detail
    assert failed[0].fix.startswith("Rebuild the library")
    assert not _status(checks, "tensor-core")                     # nothing to say about cubins without a library


def test_missing_cubin_and_unknown_architecture_only_warn(healthy, monkeypatch):
    (healthy / "pkg" / "cubins" / "tf32x3_hyb_sm120.cubin").unlink()
    checks = doctor.run_checks()
    cubin = _status(checks, "tensor-core")[0]
    assert cubin.status == doctor.WARN and "not found" in cubin.detail and not _fail(checks)
    monkeypatch.setattr(doctor, "probe_gpus", lambda: [("Future GPU", "700.0", 130)])
    cubin = _status(doctor.run_checks(), "tensor-core")[0]
    assert cubin.status == doctor.WARN and "none is shipped for compute capability 13.0" in cubin.detail
    # Compute capability 8.0 loads LoupMD's own build, the other 8.x GPUs FastMACE's (src/engine.cu).
    for name in doctor.CUBIN_OF_CAPABILITY.values():
        (healthy / "pkg" / "cubins" / name).write_bytes(b"")
    monkeypatch.setattr(doctor, "probe_gpus", lambda: [("NVIDIA A100", "580.0", 80), ("RTX 4000 Ada", "580.0", 89)])
    a100, ada = _status(doctor.run_checks(), "tensor-core")
    assert a100.status == doctor.OK and a100.detail.endswith("gemm_tc_hyb_sm80.cubin")
    assert ada.status == doctor.OK and ada.detail.endswith("tf32x3_hyb_sm80.cubin")


def test_cache_root_inside_the_python_installation_or_read_only(healthy, monkeypatch):
    monkeypatch.setenv("LOUPMD_CACHE", str(Path(sys.prefix) / "var" / "loupmd"))
    failed = _fail(doctor.run_checks())
    assert [c.what for c in failed] == ["cache root"] and "lies inside the Python installation" in failed[0].detail
    locked = healthy / "readonly"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("this user can write anywhere (root)")
        monkeypatch.setenv("LOUPMD_CACHE", str(locked / "cache"))
        failed = _fail(doctor.run_checks())
        assert [c.what for c in failed] == ["cache root"] and "cannot be written" in failed[0].detail
    finally:
        locked.chmod(0o755)


def test_a_model_file_that_is_not_the_release(healthy):
    store = healthy / "models"
    store.mkdir()
    (store / models.LABELS["omat0-small"].checkpoint.file_name).write_bytes(b"not the released file")
    checks = doctor.run_checks()
    failed = _fail(checks)
    assert len(failed) == 1 and failed[0].what == "model file mace-omat-0-small.model"
    assert "loupmd models --download omat0-small" in failed[0].fix
    unhashed = doctor.run_checks(hashes=False)
    assert not _fail(unhashed)
    assert "1 of 18 released files found, hashes not checked" in _status(unhashed, "model files")[0].detail


def test_missing_export_extra_is_a_warning(healthy, monkeypatch):
    monkeypatch.setattr(doctor, "probe_module", lambda name: name != "mace")
    checks = doctor.run_checks()
    extra = _status(checks, "export extra")[0]
    assert extra.status == doctor.WARN and "missing: mace" in extra.detail and "loupmd[export]" in extra.fix
    assert not _fail(checks)


def test_exit_status_is_1_on_a_failure(healthy, monkeypatch, capsys):
    monkeypatch.setattr(doctor, "probe_gpus", lambda: [])

    class Args:
        no_hashes = True

    assert doctor.run(Args()) == 1
    out = capsys.readouterr().out
    assert "[FAIL] NVIDIA GPU and driver: nvidia-smi lists no GPU" in out and "1 failed" in out


def test_the_real_command_runs_here():
    """On a machine with nvidia-smi the command itself runs and names the GPU; skipped elsewhere."""
    if shutil.which("nvidia-smi") is None:
        pytest.skip("no nvidia-smi")
    out = subprocess.run([sys.executable, "-m", "loupmd", "doctor", "--no-hashes"], cwd=ROOT, capture_output=True,
                         text=True)
    assert out.returncode in (0, 1), out.stderr
    assert "GPU 0:" in out.stdout and "checks:" in out.stdout and "Traceback" not in out.stderr
