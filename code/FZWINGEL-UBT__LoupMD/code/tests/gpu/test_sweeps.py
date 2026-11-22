"""The generic pass as per-layer sweeps (plan task S1-T08).

LOUP_SWEEP_REPLAY=1 makes the generic path run the schedule a domain with ghost atoms will run, on the whole
system: forward sweeps that keep only each layer's output, the last layer forward and backward, then for each
earlier layer a backward sweep that replays the layer's forward after every other buffer was overwritten with NaN.
Energy, forces and stress must equal the ordinary pass up to what two ordinary engines differ by.
Every test creates an engine and skips when its model file is absent.
"""
from __future__ import annotations

import os

import numpy as np
import pytest
from gpu_support import find_model, srtio3

from loupmd import BackendError, LoupEngine, ensure_loup_bundle



def _oxide():
    at = srtio3(3)
    at.positions += np.random.default_rng(7).normal(scale=0.04, size=at.positions.shape)
    at.set_cell(at.cell.array * np.array([[1.01, 0.004, 0.0], [0.0, 0.995, 0.003], [0.002, 0.0, 1.004]]),
                scale_atoms=True)
    return at


def _water():
    from ase.io import read

    from loupmd.bench import suites

    box = suites.find_file("water_216.extxyz", {})      # shipped with the package
    at = read(box)
    at.positions += np.random.default_rng(8).normal(scale=0.02, size=at.positions.shape)
    return at


# (model file, structure, generic=True for a model that would take the specialised kernels, layers)
CASES = [
    ("mace-omat-0-small.model", _oxide, False, 2),
    ("mace-omat-0-medium.model", _oxide, True, 2),
    ("2023-12-03-mace-128-L1_epoch-199.model", _oxide, False, 2),
    ("MACE_MPtrj_2022.9.model", _oxide, False, 2),
    ("mace-mh-1.model", _oxide, False, 2),
    ("MACE-OFF23_medium.model", _water, False, 2),
    ("MACE-omol-0-extra-large-1024.model", _water, False, 3),
]


def _evaluate(bundle, at, monkeypatch, env):
    for key in ("LOUP_SWEEP_REPLAY", "LOUP_CHAIN_FOLD"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)   # read when the engine loads the bundle
    eng = LoupEngine(bundle)
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    e, f, s = eng.evaluate(at.positions, at.cell.array)
    layers = eng.info().n_layers
    del eng
    return e, f, s, layers


@pytest.mark.parametrize("model,structure,generic,layers", CASES, ids=[c[0].split(".model")[0] for c in CASES])
@pytest.mark.full
def test_sweep_schedule_reproduces_the_ordinary_pass(model, structure, generic, layers, monkeypatch):
    at = structure()
    zs = sorted(set(at.get_atomic_numbers().tolist()))
    bundle = ensure_loup_bundle(find_model(model), zs, generic=generic if "omat-0-medium" in model else None)
    # The ordinary pass without the skip-chain fold, which never forms the layer outputs a sweep hands on (every
    # multi-layer model folds by default since the merge of round6-hardening 13d6337). The replay's engine is a
    # default one: LOUP_SWEEP_REPLAY turns the fold off itself.
    plain = {"LOUP_CHAIN_FOLD": "0"}
    a = _evaluate(bundle, at, monkeypatch, plain)
    b = _evaluate(bundle, at, monkeypatch, plain)
    r = _evaluate(bundle, at, monkeypatch, {"LOUP_SWEEP_REPLAY": "1"})
    assert a[3] == layers
    n = len(at)
    assert np.isfinite(r[0]) and np.isfinite(r[1]).all() and np.isfinite(r[2]).all()
    spread = (abs(a[0] - b[0]) / n, np.abs(a[1] - b[1]).max(), np.abs(a[2] - b[2]).max())
    diff = (abs(r[0] - a[0]) / n, np.abs(r[1] - a[1]).max(), np.abs(r[2] - a[2]).max())
    # eV/atom, eV/A, eV/A^3: float32 rounding of the same operations. The energy's floor is what engines that
    # timed other GEMM plans differ by (each engine times its own; 1.6e-8 eV/atom seen here on OFF23 medium,
    # 1.0e-7 between two OMAT-0 medium engines in tests/test_run_api.py).
    floors = (1e-7, 2e-6, 2e-8)
    for name, d, sp, floor in zip(("energy", "forces", "stress"), diff, spread, floors):
        assert d <= max(5.0 * sp, floor), f"{name}: replay differs by {d:.3e}, two ordinary engines by {sp:.3e}"


def test_sweep_schedule_in_md_conserves_energy(monkeypatch):
    """The replay also has to hold step after step inside the captured MD graphs."""
    from gpu_support import maxwell_velocities

    at = _oxide()
    bundle = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])
    monkeypatch.setenv("LOUP_SWEEP_REPLAY", "1")
    eng = LoupEngine(bundle)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.set_state(at.positions, maxwell_velocities(at, 300.0, 3), at.cell.array)
    first = eng.run_nve(20, 1.0)
    last = eng.run_nve(400, 1.0)
    e0 = first.final_potential_energy_ev + first.final_kinetic_energy_ev
    e1 = last.final_potential_energy_ev + last.final_kinetic_energy_ev
    assert abs(e1 - e0) / len(at) < 2e-5, (e1 - e0) / len(at)   # eV/atom over 0.4 ps
    assert last.pipelined_steps > 300


def test_sweep_schedule_is_refused_for_a_long_range_model(monkeypatch):
    bundle = ensure_loup_bundle(find_model("MACE-POLAR-1-S.model"), [11, 17])
    monkeypatch.delenv("LOUP_CHAIN_FOLD", raising=False)
    monkeypatch.setenv("LOUP_SWEEP_REPLAY", "1")
    with pytest.raises(BackendError, match="LOUP_SWEEP_REPLAY: the sweep schedule is not available"):
        LoupEngine(bundle)


def test_sweep_schedule_runs_a_chain_folded_model_without_the_fold(monkeypatch):
    """A model whose whole-system pass folds the skip chain (OMOL-0 extra large; refused with the fold before the
    merge of round6-hardening 13d6337): the replay's engine leaves the fold off and gives the unfolded pass."""
    at = _water()
    bundle = ensure_loup_bundle(find_model("MACE-omol-0-extra-large-1024.model"), [1, 8])
    a = _evaluate(bundle, at, monkeypatch, {"LOUP_CHAIN_FOLD": "0"})
    r = _evaluate(bundle, at, monkeypatch, {"LOUP_SWEEP_REPLAY": "1"})
    assert a[3] == r[3] == 3
    # the floors of the full tier's test_sweep_schedule_reproduces_the_ordinary_pass, with one ordinary engine
    assert abs(r[0] - a[0]) / len(at) <= 1e-7 and np.abs(r[1] - a[1]).max() <= 1e-5
    assert np.abs(r[2] - a[2]).max() <= 1e-7
