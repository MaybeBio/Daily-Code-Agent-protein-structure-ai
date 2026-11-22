"""The examples (plan task S7-T04): each runs with ``--steps 200`` on MACE MH-1 (``matpes_r2scan`` head).

Acceptance tier: each script exports MH-1 once (the export extra) and runs a few hundred steps. Example 02 needs
NbCl5 from the benchmark structures (``LOUPMD_BENCH_STRUCTURES``) and skips without it.
"""
from __future__ import annotations

import importlib.util
import math
import os
from pathlib import Path

import pytest
from gpu_support import ROOT, find_model

pytestmark = pytest.mark.acceptance

EXAMPLES = ROOT / "examples"


def _main(name):
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), EXAMPLES / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


@pytest.fixture(scope="module")
def common(tmp_path_factory):
    return ["--checkpoint", find_model("mace-mh-1.model"), "--steps", "200"]


def test_01_nvt_anneal(common, tmp_path):
    summary = _main("01_nvt_anneal_nacl.py")(common + ["--output", str(tmp_path / "01")])
    assert summary.steps == 200 and math.isfinite(summary.final_temperature_K)
    assert (tmp_path / "01" / "restart.npz").is_file()


def test_02_npt_d3_melt_quench(common, tmp_path):
    from loupmd.bench import suites

    try:
        structure = suites.structure_file("nbcl5", os.environ)
    except Exception as error:  # noqa: BLE001 - the structure set is optional
        pytest.skip(f"NbCl5 not found: {error}")
    run, result = _main("02_npt_d3_melt_quench_nbcl5.py")(
        common + ["--structure", str(structure), "--relax-steps", "200", "--output", str(tmp_path / "02")])
    assert run.metadata["dispersion"]["damping"] == "bj" and run.metadata["step"] == 200
    assert math.isfinite(result.energy) and result.steps <= 200
    assert (tmp_path / "02" / "quenched.extxyz").is_file()


def test_03_swap_mc(common, tmp_path):
    run = _main("03_swap_mc_anneal.py")(common + ["--output", str(tmp_path / "03")])
    swaps = run.metadata["mc"]["counters"]["swap"]
    assert run.metadata["step"] == 200 and swaps["attempted"] == 2 * 50          # after steps 100 and 200


def test_04_relaxations(common, tmp_path):
    results = _main("04_gpu_relaxations.py")(common + ["--output", str(tmp_path / "04")])
    assert set(results) == {"lbfgs_fixed", "fire_fixed", "lbfgs_cell", "fire_cell"}
    assert all(math.isfinite(r.energy) and r.steps <= 200 for r in results.values())
    assert results["lbfgs_fixed"].converged                   # 64 rattled atoms of NaCl: LBFGS gets there


def test_05_ase_port(common, tmp_path):
    temperatures = _main("05_port_ase_script.py")(common + ["--output", str(tmp_path / "05")])
    assert len(temperatures) == 6 and all(50 < t < 1000 for t in temperatures[1:])
    assert (tmp_path / "05" / "md.traj").is_file() and (tmp_path / "05" / "md.loupmd" / "thermo.0.csv").is_file()


def test_06_large_cell_in_tiles(common, tmp_path):
    run = _main("06_large_cell.py")(common + ["--repeat", "6", "6", "6", "--capacity", "tiled",
                                              "--output", str(tmp_path / "06")])
    assert run.metadata["step"] == 200 and "tile" in run.summary
