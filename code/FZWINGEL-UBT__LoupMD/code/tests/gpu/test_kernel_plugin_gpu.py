"""A kernel plugin on the GPU (plan task S2-T06): ``loupmd build-kernels`` compiles a model's product kernels
with nvcc, and the engine runs them from the plugin when its own are missing (before it turns to the source the
bundle carries). No local model lacks kernels, so
``LOUP_DEBUG_HIDE_KERNEL`` hides the library's own for one signature. Needs nvcc and the export extra."""
from __future__ import annotations

import numpy as np
import pytest
from gpu_support import find_model, srtio3

from loupmd import BackendError, LoupEngine, kernels


def _evaluate(bundle, at):
    eng = LoupEngine(bundle)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    energy, forces, stress = eng.evaluate(at.positions, at.cell.array, compute_stress=True)
    return energy, forces, stress, eng.info().kernel_signature


def test_a_plugin_s_kernels_give_the_library_s_results(sto_bundle, tmp_path, monkeypatch):
    try:
        kernels.find_nvcc()
    except Exception as error:                                  # pragma: no cover - a machine without the toolkit
        pytest.skip(f"no nvcc: {error}")
    at = srtio3(3)
    at.positions += np.random.default_rng(3).normal(scale=0.05, size=at.positions.shape)
    e_ref, f_ref, s_ref, signature = _evaluate(sto_bundle, at)
    signatures = list(dict.fromkeys(signature.split(";")))

    monkeypatch.setenv("LOUPMD_CACHE", str(tmp_path / "cache"))
    lines = []
    results = kernels.build_plugins(find_model("mace-omat-0-medium.model"), force=True, log=lines.append)
    assert sorted(sig for sig, _, _ in results) == sorted(signatures) and all(built for _, _, built in results)
    sizes = {sig: path.stat().st_size for sig, path, _ in results}

    worst = {}
    for hidden in signatures:
        monkeypatch.setenv("LOUP_DEBUG_HIDE_KERNEL", hidden)
        energy, forces, stress, _ = _evaluate(sto_bundle, at)
        worst[hidden] = (abs(energy - e_ref) / len(at), np.abs(forces - f_ref).max(), np.abs(stress - s_ref).max())
    print("kernel plugins of mace-omat-0-medium built with nvcc: "
          + "; ".join(f"{sig} ({sizes[sig]} bytes): energy within {w[0]:.1e} eV/atom, forces {w[1]:.1e} eV/A, "
                      f"stress {w[2]:.1e} eV/A^3 of the library's own kernels" for sig, w in worst.items()))
    # forces and stress at the gate's floors (AGENTS.md section 3), energy at 3e-6 eV/atom: plugin and library differ
    # here by up to 3.4e-6 eV/A and 1.3e-6 eV/atom from run to run (float32 order, GEMM plans), which the earlier
    # 3e-6 / 1e-6 bounds failed now and then
    for dE, dF, dS in worst.values():
        assert dE < 3e-6 and dF < 1e-5 and dS < 1e-7

    # Without a plugin a hidden signature is compiled from the source the bundle carries (JIT_DESIGN.md stage 3);
    # where NVRTC is not there it is an error that names the command. (A loaded plugin stays loaded, so the engine
    # is pointed at another, empty folder. tests/gpu/test_jit.py has the refusal with LOUP_JIT=0.)
    monkeypatch.setenv("LOUPMD_CACHE", str(tmp_path / "empty"))
    try:
        compiled = _evaluate(sto_bundle, at)
    except BackendError as error:
        assert "no compiled product kernel for signature " + signatures[-1] in str(error)
        assert "loupmd build-kernels MODEL" in str(error) and "loupmd-kernels-" in str(error)
    else:
        assert compiled[0] == pytest.approx(e_ref, abs=3e-6 * len(at))
        assert np.abs(compiled[1] - f_ref).max() < 1e-5
    monkeypatch.delenv("LOUP_DEBUG_HIDE_KERNEL")
    assert _evaluate(sto_bundle, at)[0] == pytest.approx(e_ref, abs=3e-6 * len(at))
