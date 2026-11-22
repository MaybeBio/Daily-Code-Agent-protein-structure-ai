"""The gate's MACE-reference cache (tools/dev/test_gate.py): a stale reference would silently change what the gate
measures, so the key must follow every input, and a cached set must read back as it was written."""
from __future__ import annotations

import numpy as np
from gpu_support import srtio3

import test_gate as tg


def _refs(sizes, seed):
    rng = np.random.default_rng(seed)
    return [(float(rng.normal()), rng.normal(size=(n, 3)), rng.normal(size=(3, 3))) for n in sizes]


def test_cached_references_read_back_and_follow_their_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("LOUP_GATE_CACHE", str(tmp_path / "cache"))
    model = tmp_path / "model.model"
    model.write_bytes(b"model one")
    configs = [("a_c0", srtio3(1)), ("b_c0", srtio3(2))]  # 5 and 40 atoms: forces of different shapes
    path = tg.ref_cache_path(str(model), None, "oxide", "cuda", configs)
    assert tg.load_refs(path, len(configs)) is None

    ref64, ref32 = _refs([5, 40], 1), _refs([5, 40], 2)
    sref = [r[2] for r in _refs([5, 40], 3)]
    tg.save_refs(path, ref64, ref32, sref)
    got64, got32, gots = tg.load_refs(path, len(configs))
    for want, got in ((ref64, got64), (ref32, got32)):
        for (e, f, s), (e2, f2, s2) in zip(want, got):
            assert e == e2 and np.array_equal(f, f2) and np.array_equal(s, s2)
    assert all(np.array_equal(a, b) for a, b in zip(sref, gots))

    moved = [(n, at.copy()) for n, at in configs]
    moved[1][1].positions[3, 0] += 1e-9
    model2 = tmp_path / "model2.model"
    model2.write_bytes(b"model two")
    other = {
        tg.ref_cache_path(str(model2), None, "oxide", "cuda", configs),
        tg.ref_cache_path(str(model), "omol", "oxide", "cuda", configs),
        tg.ref_cache_path(str(model), None, "crystals", "cuda", configs),
        tg.ref_cache_path(str(model), None, "oxide", "cpu", configs),
        tg.ref_cache_path(str(model), None, "oxide", "cuda", moved),
    }
    assert path not in other and len(other) == 5



def test_cache_key_names_the_gpu_and_a_corrupt_entry_is_recomputed(tmp_path, monkeypatch):
    monkeypatch.setenv("LOUP_GATE_CACHE", str(tmp_path / "cache"))
    model = tmp_path / "model.model"
    model.write_bytes(b"model")
    configs = [("a_c0", srtio3(1))]
    monkeypatch.setattr(tg, "ref_device_tag", lambda d: f"{d}:RTX 5060 Ti:sm120")
    on_5060 = tg.ref_cache_path(str(model), None, "oxide", "cuda", configs)
    monkeypatch.setattr(tg, "ref_device_tag", lambda d: f"{d}:RTX 4000 Ada:sm89")
    assert tg.ref_cache_path(str(model), None, "oxide", "cuda", configs) != on_5060

    on_5060.parent.mkdir(parents=True)
    on_5060.write_bytes(b"not an npz")
    assert tg.load_refs(on_5060, 1) is None
    tg.save_refs(on_5060, _refs([5], 1), _refs([5], 2), [np.eye(3)])
    assert tg.load_refs(on_5060, 2) is None  # fewer configs stored than asked for: recompute
    assert tg.load_refs(on_5060, 1) is not None