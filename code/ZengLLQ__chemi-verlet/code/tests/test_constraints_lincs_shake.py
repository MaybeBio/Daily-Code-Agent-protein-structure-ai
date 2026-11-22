"""Tests for SHAKE, RATTLE, and LINCS holonomic bond constraints."""

from __future__ import annotations

import numpy as np
import pytest

from chemi_verlet.constraints import LincsSolver, ShakeSolver, constraint_rms_deviation
from chemi_verlet.forcefield import ForceField, ForceFieldConfig
from chemi_verlet.integrators import SimulationConfig, run_simulation
from chemi_verlet.pbc import minimum_image_displacement
from chemi_verlet.topology import build_solvated_ligand_box


@pytest.mark.parametrize("solver_cls", [LincsSolver, ShakeSolver])
def test_constraints_project_positions_and_velocities(solver_cls: type) -> None:
    topo, coords, box = build_solvated_ligand_box("CCO", box_length_nm=2.2, n_waters=6, seed=31)
    solver = solver_cls(topo)
    rng = np.random.default_rng(32)
    perturbed = coords + rng.normal(0.0, 0.008, size=coords.shape)
    r_proj, _ = solver.constrain_positions(coords, perturbed, box, dt=0.002)
    rms = constraint_rms_deviation(r_proj, topo.constraints, box)
    assert rms < 1e-6

    vel = rng.normal(0.0, 1.5, size=coords.shape)
    v_proj = solver.constrain_velocities(r_proj, vel, box)
    for c in topo.constraints:
        dr = minimum_image_displacement(r_proj[c.j] - r_proj[c.i], box)
        dv = v_proj[c.j] - v_proj[c.i]
        assert abs(float(np.dot(dr, dv))) / c.distance < 1e-5


def test_lincs_maintains_rigid_water_triangle_during_nvt() -> None:
    topo, coords, box = build_solvated_ligand_box("CO", box_length_nm=2.2, n_waters=8, seed=33)
    ff = ForceField(topo, ForceFieldConfig(cutoff=0.9, electrostatics="pme"))
    state, _ = run_simulation(
        topo,
        ff,
        coords,
        box,
        config=SimulationConfig(dt_ps=0.002, n_steps=80, ensemble="nvt", constraint_mode="lincs", seed=33),
    )
    assert state.constraint_rms_error < 1e-5
