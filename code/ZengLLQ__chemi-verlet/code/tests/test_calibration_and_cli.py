"""Tests for force-field calibration, Sobol sensitivity, conservation audit, and CLI."""

from __future__ import annotations

import numpy as np
import pytest

from chemi_verlet.calibration import (
    bounded_nelder_mead,
    calibrate_lj_parameters,
    run_conservation_audit,
    sobol_sensitivity_indices,
)
from chemi_verlet.cli import main as cli_main
from chemi_verlet.visualizer import assert_strict_ascii


def test_bounded_nelder_mead_and_sobol_sensitivity() -> None:
    def _ishigami_like(x: np.ndarray) -> float:
        return float((x[0] - 0.35) ** 2 + 0.1 * (x[1] - 2.0) ** 2)

    best_x, best_f, evals, history = bounded_nelder_mead(
        _ishigami_like,
        np.array([0.1, 0.5]),
        bounds=[(0.0, 1.0), (0.0, 4.0)],
        max_iter=50,
    )
    assert best_f < 1e-4
    assert evals > 5
    assert history[-1] <= history[0]
    assert pytest.approx(best_x[0], abs=0.02) == 0.35

    s1, st = sobol_sensitivity_indices(
        _ishigami_like,
        param_names=["x0", "x1"],
        bounds=[(0.0, 1.0), (0.0, 4.0)],
        n_samples=64,
        seed=81,
    )
    assert 0.0 <= s1["x0"] <= 1.0 and 0.0 <= st["x0"] <= 1.0
    assert st["x1"] >= st["x0"]  # wider x1 range with 0.1*dx^2 has larger variance contribution


def test_lj_calibration_and_conservation_audit() -> None:
    cal = calibrate_lj_parameters(max_iter=15, seed=82)
    assert cal.best_loss <= cal.initial_loss
    assert 0.28 <= cal.best_params["sigma_nm"] <= 0.42

    audit = run_conservation_audit(seed=82)
    assert audit.nve_relative_energy_drift < 1e-2
    assert audit.lincs_constraint_rms_nm < 1e-5
    assert audit.pme_vs_exact_energy_rel_err < 2e-3
    assert audit.pme_vs_exact_force_rel_rmse < 3e-3


@pytest.mark.parametrize(
    "argv",
    [
        ["simulate", "--steps", "30", "--waters", "6", "--seed", "91"],
        ["alchemical", "--windows", "4", "--steps-per-window", "30", "--waters", "5", "--seed", "92"],
        ["umbrella", "--windows", "4", "--steps-per-window", "30", "--seed", "93"],
        ["dock", "--smiles", "c1ccccc1O", "--iterations", "60", "--seed", "94"],
        ["msm", "--n-trajectories", "3", "--steps", "60", "--states", "3", "--seed", "95"],
        ["calibrate", "--max-iter", "10", "--seed", "96"],
        ["--json", "demo", "--seed", "97"],
    ],
)
def test_cli_subcommands_run_and_emit_strict_ascii(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli_main(argv)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert len(captured.out) > 20
    assert_strict_ascii(captured.out)
