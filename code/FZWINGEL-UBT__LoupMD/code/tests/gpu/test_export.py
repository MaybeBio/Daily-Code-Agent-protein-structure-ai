"""Exporter and bundle-cache checks (CPU only, except the fixture bundle).

The exporters set CUDA_VISIBLE_DEVICES for themselves, so they are driven in a subprocess, as ensure_loup_bundle does.
"""
from __future__ import annotations

import subprocess
import sys

from gpu_support import ROOT

import loupmd

DRIVER = """
import sys
sys.path.insert(0, {python_dir!r})
from loupmd.export import generic as ex
{patch}
ex.export_model({model!r}, [8, 22, 38], ex.Path({out!r}))
"""


def _export_with(patch: str, model_path: str, tmp_path):
    src = DRIVER.format(python_dir=str(ROOT), patch=patch, model=model_path, out=str(tmp_path / "x.loup"))
    proc = subprocess.run([sys.executable, "-W", "ignore", "-c", src], capture_output=True, text=True)
    return proc, (tmp_path / "x.loup").exists()


def test_export_refuses_an_uncertified_spline(model_path, tmp_path):
    """Each layer's radial spline must be at least as accurate as the float32 network (certificate <= 1)."""
    patch = "\n".join([
        "from loupmd.export import _fastmace as fm",
        "rs = fm.rspline",
        "fit = rs.fit",
        "rs.fit = lambda *a, **k: (fit(*a, **k)[0], {'worst': 1.5})",
        "ex.refine_for_packing = lambda rspline, rad, ch64, ch32, w, pairs, r_max, spl: (spl, None, [0.0])",
    ])
    proc, written = _export_with(patch, model_path, tmp_path)
    assert proc.returncode != 0 and not written
    assert "radial spline certificate 1.500 > 1" in proc.stderr, proc.stderr[-600:]


def test_bundle_carries_each_products_source(sto_bundle):
    """JIT_DESIGN.md stage 3: every layer's product kernels travel with the bundle, so a signature the library was not
    built with is compiled at load."""
    from loupmd.export.bundle import read_bundle

    meta, T = read_bundle(sto_bundle)
    assert meta["arch"] == "generic"
    sigs = {k[:-len("prod_sig")]: v for k, v in meta.items() if k.endswith(".prod_sig")}
    assert sigs
    for prefix, sig in sigs.items():
        src = T[prefix + "prod_src"].tobytes().decode()
        assert f"gprod_fwd_{sig}(" in src and f"gprod_bwd_{sig}(" in src


def test_bundle_cache_key_follows_the_exporter_sources(tmp_path):
    """A changed exporter must not find the bundles of the old one (no version number to remember to bump)."""
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("x = 1\n")
    b.write_text("y = 2\n")
    first = loupmd.exporter_fingerprint([a, b])
    assert first == loupmd.exporter_fingerprint([a, b])
    b.write_text("y = 3\n")
    assert first != loupmd.exporter_fingerprint([a, b])
    # the real key covers every exporter, the product-kernel emitter and the container writer
    names = {p.name for p in loupmd.EXPORTER_SOURCES}
    assert {"__init__.py", "generic.py", "polar.py", "bundle.py", "gen_product.py"} <= names
    assert all(p.is_file() for p in loupmd.EXPORTER_SOURCES)
