"""Checks on the generic path's model families that the single-point gate does not make.

Each test skips when its model file is not in the folder LOUPMD_MODELS names.
"""
from __future__ import annotations

import numpy as np
import pytest
from gpu_support import find_model, water_box

from loupmd import LoupEngine, ensure_loup_bundle


def _rattled_nacl(rep: int, sigma: float, seed: int):
    from ase.build import bulk

    at = bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((rep, rep, rep))
    at.positions += np.random.default_rng(seed).normal(0.0, sigma, at.positions.shape)
    return at


def test_polar_energy_follows_a_small_cell_change_on_the_same_engine():
    """A second evaluate with a slightly different cell must give what a fresh engine gives for that cell (the
    volume enters the long-range terms; a volume kept from the first call would scale them wrongly)."""
    bundle = ensure_loup_bundle(find_model("MACE-POLAR-1-S.model"), [11, 17])
    at = _rattled_nacl(2, 0.05, 21)  # 64 atoms
    z, m = at.get_atomic_numbers(), at.get_masses()
    eng = LoupEngine(bundle)
    eng.set_system(z, m)
    eng.evaluate(at.positions, at.cell.array)
    # Strains small enough to keep the number of k-vectors of this cell (measured: it changes near 1e-3). With the
    # first cell's volume kept, the differences were 3e-7 / 1e-6 eV/atom, 3e-5 / 9e-5 eV/A and 8e-8 / 3e-7 eV/A^3.
    for strain in (1e-4, 3e-4):
        s = 1.0 + strain
        e_same, f_same, s_same = eng.evaluate(at.positions * s, at.cell.array * s)
        fresh = LoupEngine(bundle)
        fresh.set_system(z, m)
        e_fresh, f_fresh, s_fresh = fresh.evaluate(at.positions * s, at.cell.array * s)
        assert abs(e_same - e_fresh) / len(at) < 2e-7, f"strain {strain}: {(e_same - e_fresh) / len(at):.3e} eV/atom"
        assert np.abs(f_same - f_fresh).max() < 1e-5, f"strain {strain}"
        assert np.abs(s_same - s_fresh).max() < 3e-8, f"strain {strain}"
        eng.evaluate(at.positions, at.cell.array)  # back to the first cell for the next strain


@pytest.mark.parametrize("model,symbols", [("mace-mh-1.model", "OTiSr"), ("MACE-POLAR-1-S.model", "NaCl")])
def test_generic_model_without_neighbour_pairs_matches_mace(model, symbols):
    """Atoms further apart than the cutoff have no edges; a generic model can still give each a non-zero
    interaction energy (residual first block, readout biases, long-range terms), which must not be dropped.
    Measured before the fix: MACE-MH-1 off by 1.67 eV for three atoms, MACE-POLAR-1-S by 1.27 eV for two."""
    import torch
    from ase import Atoms
    from mace.calculators import MACECalculator

    path = find_model(model)
    nat = len(Atoms(symbols))
    at = Atoms(symbols, positions=[(2.0 + 14.0 * i,) * 3 for i in range(nat)], cell=[14.0 * nat] * 3, pbc=True)
    eng = LoupEngine(ensure_loup_bundle(path, sorted(set(at.get_atomic_numbers().tolist()))))
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    e, f, _ = eng.evaluate(at.positions, at.cell.array)
    heads = list(getattr(torch.load(path, map_location="cpu", weights_only=False), "heads", None) or [])
    head = {"head": next((h for h in ("omat_pbe", "default", "Default") if h in heads), heads[-1])} if len(heads) > 1 else {}
    ref = at.copy()
    ref.calc = MACECalculator(model_paths=path, device="cpu", default_dtype="float64", **head)
    assert abs(e - ref.get_potential_energy()) < 1e-4 * nat
    assert np.abs(f).max() < 1e-6


@pytest.mark.parametrize("model", ["mace-omat-0-small.model", "mace-mh-1.model"])
def test_receiver_with_an_empty_species_segment_matches_mace(model):
    """Two Sr and an O within the cutoff, the Ti beyond it: each Sr receives O and Sr edges but none from Ti, the
    species between them, and the O receives only Sr. The first layer walks a receiver's edges by sender species, so
    an empty segment between two non-empty ones must leave its slot zero and the next one intact (the path of the
    review T2 race in first_fwd_kernel; that race itself depends on warp timing and cannot be forced here)."""
    import torch
    from ase import Atoms
    from mace.calculators import MACECalculator

    path = find_model(model)
    at = Atoms("Sr2OTi", positions=[(5.0, 5.0, 5.0), (8.6, 5.0, 5.0), (6.8, 6.6, 5.4), (20.0, 20.0, 20.0)],
               cell=[30.0] * 3, pbc=True)
    eng = LoupEngine(ensure_loup_bundle(path, sorted(set(at.get_atomic_numbers().tolist()))))
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    e, f, _ = eng.evaluate(at.positions, at.cell.array)
    heads = list(getattr(torch.load(path, map_location="cpu", weights_only=False), "heads", None) or [])
    head = {"head": next((h for h in ("omat_pbe", "default", "Default") if h in heads), heads[-1])} if len(heads) > 1 else {}
    ref = at.copy()
    ref.calc = MACECalculator(model_paths=path, device="cpu", default_dtype="float64", **head)
    assert abs(e - ref.get_potential_energy()) < 1e-4 * len(at)
    assert np.abs(f - ref.get_forces()).max() < 5e-4


def _rattled_srtio3(rep: int, sigma: float, seed: int):
    from gpu_support import srtio3

    at = srtio3(rep)
    at.positions += np.random.default_rng(seed).normal(0.0, sigma, at.positions.shape)
    return at


# model file, base cell, replication (to about 2,000 atoms: several GEMM tiles and thread blocks per species),
# force tolerance in eV/A. A periodic replica is the same physical system, so only rounding may differ; a kernel
# whose result depends on where a tile or block ends (as POLAR's backward GEMM did from ~1,700 atoms) breaks this.
REPLICA_CASES = [
    # Measured on the RTX 4000 Ada, 13 Nov: 4e-6, -, 5e-6, 1e-6 eV/A for the local models; 7e-4 eV/A for POLAR-1-S,
    # whose long-range part amplifies rounding with cell size.
    ("mace-omat-0-medium.model", lambda: _rattled_srtio3(3, 0.04, 31), (4, 2, 2), 5e-5),
    ("mace-omat-0-small.model", lambda: _rattled_srtio3(3, 0.04, 31), (4, 2, 2), 5e-5),
    ("mace-mh-1.model", lambda: _rattled_srtio3(3, 0.04, 31), (4, 2, 2), 5e-5),
    ("MACE-OFF23_small.model", None, (3, 1, 1), 5e-5),  # the 648-atom water box
    ("MACE-POLAR-1-S.model", lambda: _rattled_nacl(2, 0.04, 32), (4, 4, 2), 3e-3),
]


@pytest.mark.parametrize("model,base,rep,f_tol", REPLICA_CASES, ids=[c[0].split(".model")[0] for c in REPLICA_CASES])
def test_replicated_cell_gives_the_same_energy_and_forces(model, base, rep, f_tol):
    path = find_model(model)
    if base is None:
        at = water_box()
    else:
        at = base()
    big = at.repeat(rep)
    eng = LoupEngine(ensure_loup_bundle(path, sorted(set(at.get_atomic_numbers().tolist()))))
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    e1, f1, s1 = eng.evaluate(at.positions, at.cell.array)
    eng.set_system(big.get_atomic_numbers(), big.get_masses())
    e2, f2, s2 = eng.evaluate(big.positions, big.cell.array)
    n, images = len(at), len(big) // len(at)
    f2 = f2.reshape(images, n, 3)  # ase's repeat keeps each image's atoms together, in the base order
    print(f"{model}: dE/atom {abs(e2 / len(big) - e1 / n):.2e} eV, dF {np.abs(f2 - f1[None]).max():.2e} eV/A, "
          f"dS {np.abs(s2 - s1).max():.2e} eV/A^3")
    assert abs(e2 / len(big) - e1 / n) < 2e-6
    assert np.abs(f2 - f1[None]).max() < f_tol
    assert np.abs(s2 - s1).max() < 1e-5


NVE_CASES = [
    ("mace-mh-1.model", lambda: _rattled_srtio3(3, 0.03, 41)),
    ("MACE-OFF23_small.model", None),
    ("MACE-POLAR-1-S.model", lambda: _rattled_nacl(2, 0.03, 42)),
]


@pytest.mark.parametrize("model,base", NVE_CASES, ids=[c[0].split(".model")[0] for c in NVE_CASES])
def test_generic_family_conserves_energy_in_nve(model, base):
    """Forces that are not the gradient of the energy (a backward step that is not the adjoint of its forward) show
    as drift; the single-point gate cannot see that."""
    from gpu_support import maxwell_velocities

    path = find_model(model)
    if base is None:
        at, dt = water_box(), 0.5  # hydrogen: half the step
    else:
        at, dt = base(), 1.0
    eng = LoupEngine(ensure_loup_bundle(path, sorted(set(at.get_atomic_numbers().tolist()))))
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.set_state(at.positions, maxwell_velocities(at, 300.0, 43), at.cell.array)
    energies = []
    for _ in range(10):  # 1,000 steps
        st = eng.run_nve(100, dt)
        energies.append(st.final_potential_energy_ev + st.final_kinetic_energy_ev)
    e = (np.array(energies) - energies[0]) * 1000.0 / len(at)  # meV/atom
    slope = np.polyfit(np.arange(len(e)) * 0.1 * dt, e, 1)[0]  # meV/atom/ps
    print(f"{model}: drift {slope:+.4f} meV/atom/ps, largest excursion {np.abs(e).max():.4f} meV/atom")
    assert abs(slope) < 0.2, f"NVE drift {slope:.4f} meV/atom/ps"
    assert np.abs(e).max() < 0.5, f"NVE excursion {np.abs(e).max():.3f} meV/atom"
