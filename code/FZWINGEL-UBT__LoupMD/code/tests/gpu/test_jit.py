"""The run-time compiled kernels (JIT_DESIGN.md) against the built-in ones: layer 0 (LOUP_JIT=1, stage 1), the conv
layers' run-time-width branch (stage 2, on by default) and the products compiled from the bundle's source (stage 3).

LOUP_JIT is read once per process, so each side runs in a subprocess of its own. Conv tuning is off (LOUP_CONV_TUNE=0)
so both sides run the same conv variant; what is left between two processes is the order of floating-point atomics
(MH-1 NaCl216, measured 19 November 2026: two built-in runs 2.3e-7 eV/A apart, built-in against JIT 1.6e-7).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from gpu_support import ROOT, find_model

from loupmd import ensure_loup_bundle
from loupmd.export.bundle import read_bundle, write_bundle

_CHILD = r"""
import json, sys
import numpy as np
sys.path.insert(0, sys.argv[1])
from ase.build import bulk
from loupmd import LoupEngine, ensure_loup_bundle
at = bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((3, 3, 3))
at.positions += np.random.default_rng(5).normal(0.0, 0.05, at.positions.shape)
src = sys.argv[2]
eng = LoupEngine(src if src.endswith(".loup") else ensure_loup_bundle(src, [11, 17]))
eng.set_system(at.get_atomic_numbers(), at.get_masses())
e, f, s = eng.evaluate(at.positions, at.cell.array)
print("RESULT " + json.dumps({"e": e, "f": np.asarray(f).tolist(), "s": np.asarray(s).tolist(), "n": len(at)}))
"""

_JIT_ENV = ("LOUP_JIT", "LOUP_JIT_PRODUCTS", "LOUP_CONV_GENERIC", "LOUP_NVRTC")


def _env(cache: Path, **env) -> dict:
    base = {k: v for k, v in os.environ.items() if k not in _JIT_ENV}
    return dict(base, LOUP_CONV_TUNE="0", LOUP_CACHE_DIR=str(cache), LOUP_DEBUG_JIT="1", **env)


def _child(model, cache: Path, **env) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", _CHILD, str(ROOT), str(model)], env=_env(cache, **env),
                          capture_output=True, text=True, timeout=600)


def _run(model, cache: Path, **env) -> tuple[dict, str]:
    p = _child(model, cache, **env)
    assert p.returncode == 0, p.stderr[-2000:]
    line = next(x for x in p.stdout.splitlines() if x.startswith("RESULT "))
    return json.loads(line[7:]), p.stderr


def _close(a: dict, b: dict):
    n = a["n"]
    assert abs(a["e"] - b["e"]) / n < 1e-6
    assert np.abs(np.array(a["f"]) - np.array(b["f"])).max() < 2e-6
    assert np.abs(np.array(a["s"]) - np.array(b["s"])).max() < 1e-8


def test_jit_layer0_matches_built_in_kernels_and_is_cached(tmp_path):
    model = find_model("mace-mh-1.model")  # ZBL, 65 radial columns: the three-column edge backward
    # the built-in side shares the cache folder (its GEMM plans), so both sides run the same plans
    ref, _ = _run(model, tmp_path, LOUP_JIT="0")
    jit, err = _run(model, tmp_path, LOUP_JIT="1")
    assert "kernel(s) compiled" in err, err[-2000:]
    _close(ref, jit)
    files = list((tmp_path / "jit").glob("layer0_*.bin"))
    assert len(files) == 1, files
    again, err2 = _run(model, tmp_path, LOUP_JIT="1")
    assert "from the disk cache" in err2, err2[-2000:]
    _close(ref, again)


def test_jit_without_nvrtc_keeps_built_in_kernels(tmp_path):
    model = find_model("mace-mh-1.model")
    ref, _ = _run(model, tmp_path, LOUP_JIT="0")
    out, err = _run(model, tmp_path, LOUP_JIT="1", LOUP_NVRTC=str(tmp_path / "no_such_libnvrtc.so"))
    assert "using the built-in kernels" in err, err[-2000:]
    assert not (tmp_path / "jit").exists()
    _close(ref, out)


def test_jit_conv_run_time_width_matches_built_in_kernels(tmp_path):
    # LOUP_CONV_GENERIC=1 sends every conv layer down the launchers' run-time-width branch: built in, the kernels with
    # C_FIX = 0 (LOUP_JIT=0); by default, the JIT's kernels with the layer's width compiled in
    model = find_model("mace-mh-1.model")
    ref, _ = _run(model, tmp_path, LOUP_JIT="0", LOUP_CONV_GENERIC="1")
    jit, err = _run(model, tmp_path, LOUP_CONV_GENERIC="1")
    assert "conv IR" in err and "kernel(s) compiled" in err, err[-2000:]
    _close(ref, jit)
    assert list((tmp_path / "jit").glob("conv_*.bin"))
    base, err0 = _run(model, tmp_path)  # widths the library has instances for: nothing compiled
    assert "kernel(s) compiled" not in err0, err0[-2000:]
    _close(ref, base)


def _product_sigs(bundle: Path) -> set[str]:
    meta, _ = read_bundle(bundle)
    return {v for k, v in meta.items() if k.endswith(".prod_sig")}


def test_jit_products_from_the_bundle_match_built_in_kernels(tmp_path):
    model = find_model("mace-mh-1.model")
    bundle = ensure_loup_bundle(model, [11, 17])
    ref, _ = _run(bundle, tmp_path, LOUP_JIT="0")
    jit, err = _run(bundle, tmp_path, LOUP_JIT_PRODUCTS="1")
    assert "kernel(s) compiled" in err, err[-2000:]
    _close(ref, jit)
    assert len(list((tmp_path / "jit").glob("prod_*.bin"))) == len(_product_sigs(bundle))


def test_a_product_outside_the_build_set_is_compiled_from_the_bundle(tmp_path):
    # The bundle's product signatures renamed (meta and kernel names): the library has no kernels for them, as for a
    # model it was not built with, so the load compiles the bundle's source; without the JIT the load is refused.
    model = find_model("mace-mh-1.model")
    good = ensure_loup_bundle(model, [11, 17])
    meta, T = read_bundle(good)
    T = dict(T)
    for k in [k for k in meta if k.endswith(".prod_sig")]:
        old, new = meta[k], "f" * 15 + k.split(".")[0][-1]
        meta[k] = new
        key = k[:-len("sig")] + "src"
        T[key] = np.frombuffer(T[key].tobytes().decode().replace(old, new).encode(), np.uint8)
    renamed = tmp_path / "renamed.loup"
    write_bundle(renamed, meta, T)
    ref, _ = _run(good, tmp_path, LOUP_JIT="0")
    out, err = _run(renamed, tmp_path)
    assert "kernel(s) compiled" in err, err[-2000:]
    _close(ref, out)
    p = _child(renamed, tmp_path, LOUP_JIT="0")
    assert p.returncode != 0 and "no compiled product kernel" in p.stderr, p.stderr[-2000:]
