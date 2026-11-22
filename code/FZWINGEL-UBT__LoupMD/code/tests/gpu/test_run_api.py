"""loup_run with LoupIntegrator (plan task S1-T04): one run call for every integrator; NVE and Langevin are built,
the old entry points are the same call with the struct filled in.

The first test compiles a small C program against include/loupmd.h and needs no GPU; the rest create an engine.
"""
from __future__ import annotations

import ctypes
import shutil
import subprocess

import numpy as np
import pytest
from gpu_support import ROOT, maxwell_velocities, srtio3

from loupmd import BackendError, InputError, LoupEngine
from loupmd import _core

LAYOUT_C = r"""
#include <stddef.h>
#include <stdio.h>
#include "loupmd.h"
#define F(T, f) printf(#T "." #f " %zu\n", offsetof(T, f))
int main(void) {
    printf("LoupIntegrator %zu\n", sizeof(LoupIntegrator));
    F(LoupIntegrator, size); F(LoupIntegrator, kind); F(LoupIntegrator, dt_fs); F(LoupIntegrator, temp_k);
    F(LoupIntegrator, temp_rate_k_per_step);
    F(LoupIntegrator, friction_per_fs); F(LoupIntegrator, tau_t_fs); F(LoupIntegrator, mass_temp_k);
    F(LoupIntegrator, pressure_gpa);
    F(LoupIntegrator, tau_p_fs); F(LoupIntegrator, compressibility_per_gpa); F(LoupIntegrator, chain_length);
    F(LoupIntegrator, chain_loops); F(LoupIntegrator, p_chain_length); F(LoupIntegrator, p_chain_loops);
    F(LoupIntegrator, cell_mode); F(LoupIntegrator, cell_mask); F(LoupIntegrator, fix_com);
    F(LoupIntegrator, thermo_every); F(LoupIntegrator, seed);
    printf("LoupInfo %zu\n", sizeof(LoupInfo));
    F(LoupInfo, abi); F(LoupInfo, compute_capability); F(LoupInfo, n_layers); F(LoupInfo, has_long_range);
    F(LoupInfo, specialised); F(LoupInfo, n_species); F(LoupInfo, r_max); F(LoupInfo, gpu_name);
    F(LoupInfo, kernel_signature);
    printf("LoupMemoryPlan %zu\n", sizeof(LoupMemoryPlan));
    F(LoupMemoryPlan, whole_bytes); F(LoupMemoryPlan, tiled_global_bytes); F(LoupMemoryPlan, tile_workspace_bytes);
    F(LoupMemoryPlan, free_bytes); F(LoupMemoryPlan, receivers); F(LoupMemoryPlan, mode);
    F(LoupMemoryPlan, host_lists); F(LoupMemoryPlan, host_bytes); F(LoupMemoryPlan, host_state);
    printf("LoupThermoRow %zu\n", sizeof(LoupThermoRow));
    F(LoupThermoRow, step); F(LoupThermoRow, e_pot); F(LoupThermoRow, e_kin); F(LoupThermoRow, temp_k);
    F(LoupThermoRow, pressure_gpa); F(LoupThermoRow, volume_a3); F(LoupThermoRow, conserved);
    printf("LoupMDStats %zu\n", sizeof(LoupMDStats));
    F(LoupMDStats, step_ms); F(LoupMDStats, rebuilds); F(LoupMDStats, final_potential_energy_ev);
    F(LoupMDStats, final_kinetic_energy_ev); F(LoupMDStats, final_temperature_k); F(LoupMDStats, dangerous_builds);
    F(LoupMDStats, tune_ms); F(LoupMDStats, pipelined_steps);
    printf("LoupMinimizer %zu\n", sizeof(LoupMinimizer));
    F(LoupMinimizer, size); F(LoupMinimizer, kind); F(LoupMinimizer, fmax_ev_a); F(LoupMinimizer, maxstep_a);
    F(LoupMinimizer, memory); F(LoupMinimizer, reserved); F(LoupMinimizer, damping); F(LoupMinimizer, alpha);
    printf("LoupMinStats %zu\n", sizeof(LoupMinStats));
    F(LoupMinStats, steps); F(LoupMinStats, converged); F(LoupMinStats, total_steps); F(LoupMinStats, rebuilds);
    F(LoupMinStats, force_passes); F(LoupMinStats, repeated_passes);
    F(LoupMinStats, max_force_ev_a); F(LoupMinStats, potential_energy_ev); F(LoupMinStats, force_ms);
    F(LoupMinStats, optimizer_ms);
    printf("kinds %d %d %d %d %d %d %d %d\n", LOUP_NVE, LOUP_LANGEVIN, LOUP_CSVR, LOUP_NHC, LOUP_BERENDSEN_NVT,
           LOUP_BERENDSEN_NPT, LOUP_BAOAB_NPT, LOUP_MTK_NPT);
    return 0;
}
"""


def test_ctypes_structs_have_the_headers_layout(tmp_path):
    """The binding repeats the header's structs by hand; a C compiler says what the header really lays out."""
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no C compiler")
    src = tmp_path / "layout.c"
    src.write_text(LAYOUT_C)
    exe = tmp_path / "layout"
    subprocess.run([cc, "-I", str(ROOT / "include"), str(src), "-o", str(exe)], check=True)
    lines = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.split("\n")
    seen = dict(line.rsplit(" ", 1) for line in lines if line and not line.startswith("kinds"))
    assert _core.THERMO_DTYPE.itemsize == ctypes.sizeof(_core.LoupThermoRow)
    for struct in (_core.LoupIntegrator, _core.LoupInfo, _core.LoupMemoryPlan, _core.LoupThermoRow, _core.LoupMDStats,
                   _core.LoupMinimizer, _core.LoupMinStats):
        name = struct.__name__
        assert int(seen.pop(name)) == ctypes.sizeof(struct), name
        for field, _ in struct._fields_:
            assert int(seen.pop(f"{name}.{field}")) == getattr(struct, field).offset, f"{name}.{field}"
    assert not seen, f"fields of the header missing in the binding: {sorted(seen)}"
    kinds = [int(x) for x in next(line for line in lines if line.startswith("kinds")).split()[1:]]
    assert kinds == [_core.LOUP_NVE, _core.LOUP_LANGEVIN, _core.LOUP_CSVR, _core.LOUP_NHC, _core.LOUP_BERENDSEN_NVT,
                     _core.LOUP_BERENDSEN_NPT, _core.LOUP_BAOAB_NPT, _core.LOUP_MTK_NPT]


def test_the_integrator_helper_refuses_unknown_fields():
    with pytest.raises(InputError, match="no settable field 'temperature'"):
        _core.integrator(_core.LOUP_LANGEVIN, temperature=300.0)
    it = _core.integrator(_core.LOUP_LANGEVIN, 0.5, temp_k=300.0, seed=7, cell_mask=(1, 0, 1))
    assert (it.size, it.kind, it.dt_fs, it.temp_k, it.seed) == (ctypes.sizeof(_core.LoupIntegrator), 1, 0.5, 300.0, 7)
    assert list(it.cell_mask) == [1, 0, 1] and it.friction_per_fs == 0.0


def _start(eng, seed=4):
    at = srtio3(3)
    at.positions += np.random.default_rng(seed).normal(scale=0.03, size=at.positions.shape)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.set_state(at.positions, maxwell_velocities(at, 300.0, seed + 1), at.cell.array)
    return at


def _end_state(bundle, how, kind):
    eng = LoupEngine(bundle)
    _start(eng)
    if kind == "nve":
        st = eng.run_nve(60, 1.0) if how == "old" else eng.run(60, _core.integrator(_core.LOUP_NVE, 1.0))
    elif how == "old":
        st = eng.run_langevin(60, 1.0, temp_k=300.0, friction_per_fs=0.01, seed=11)
    else:
        st = eng.run(60, _core.integrator(_core.LOUP_LANGEVIN, 1.0, temp_k=300.0, friction_per_fs=0.01, seed=11))
    return eng.get_state()[0], st.final_potential_energy_ev + st.final_kinetic_energy_ev


@pytest.mark.parametrize("kind", ["nve", "langevin"])
def test_loup_run_matches_the_old_entry_point(sto_bundle, kind):
    """Same state, same seed, 60 steps: loup_run may differ from the old entry point by no more than a few times
    what two runs of the old entry point differ by (force sums use atomics; floor 1e-8 A). The energy's floor is
    what two engines' float32 sums differ by: each engine times its own GEMM plans, and another plan rounds the
    energy differently (1.0e-7 eV/atom seen on the generic path at equal positions)."""
    old_a = _end_state(sto_bundle, "old", kind)
    old_b = _end_state(sto_bundle, "old", kind)
    new = _end_state(sto_bundle, "new", kind)
    spread = np.abs(old_a[0] - old_b[0]).max()
    assert np.abs(new[0] - old_a[0]).max() <= max(5.0 * spread, 1e-8), (np.abs(new[0] - old_a[0]).max(), spread)
    assert abs(new[1] - old_a[1]) <= max(5.0 * abs(old_a[1] - old_b[1]), 3e-7 * 135)


def test_loup_run_and_the_old_entry_point_share_their_step_graphs(sto_engine, capfd, monkeypatch):
    monkeypatch.setenv("LOUP_DEBUG_GRAPHS", "1")
    eng = sto_engine
    _start(eng)
    for _ in range(8):
        eng.run_nve(10, 1.0)
    capfd.readouterr()
    for _ in range(4):
        eng.run(10, _core.integrator(_core.LOUP_NVE, 1.0))
        eng.run_nve(10, 1.0)
    assert capfd.readouterr().err.count("loupmd: MD graph capture") <= 3  # one invalidation at most, not one per call


REFUSED = [
    ("size_small", dict(size=8), "loup_run: LoupIntegrator.size is 8, and this library's layout has"),
    ("size_large", dict(size=4096), "loup_run: LoupIntegrator.size is 4096"),
    ("unknown_kind", dict(kind=99), "loup_run: unknown integrator kind 99"),
    ("thermo_every", dict(thermo_every=-1), "loup_run: thermo_every must not be negative, got -1"),
    ("timestep", dict(dt_fs=0.0), "loup_run: dt_fs must be finite and positive, got 0 fs"),
    ("temperature", dict(kind=_core.LOUP_LANGEVIN, temp_k=-5.0),
     "loup_run: temp_k must be finite and not negative, got -5 K"),
    ("friction", dict(kind=_core.LOUP_LANGEVIN, friction_per_fs=float("nan")),
     "loup_run: friction_per_fs must be finite and not negative, got nan /fs"),
]   # every kind of the enum is built: none is refused as "not built"


@pytest.mark.parametrize("fields,reason", [r[1:] for r in REFUSED], ids=[r[0] for r in REFUSED])
def test_loup_run_refusals_name_their_reason(sto_engine, fields, reason):
    eng = sto_engine
    _start(eng)
    it = _core.integrator(_core.LOUP_NVE, 1.0)
    for name, value in fields.items():
        setattr(it, name, value)
    with pytest.raises(BackendError) as info:
        eng.run(5, it)
    assert str(info.value).startswith(reason), str(info.value)
    assert np.isfinite(eng.run_nve(2, 1.0).final_temperature_k)  # the handle is still usable


def test_a_missing_integrator_is_refused(sto_engine):
    _start(sto_engine)
    assert sto_engine._lib.loup_run(sto_engine._h, None, 5, None) == -1
    assert sto_engine.last_error() == "loup_run: the integrator is NULL"
