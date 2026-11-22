"""What the GPU tests share: the model files, the standard structures, velocities.

Model files are found in one place only: the folder ``LOUPMD_MODELS`` names. Structures come from the package
(``loupmd.bench.suites``).
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path

import numpy as np
import pytest

from loupmd.bench import suites

ROOT = Path(__file__).resolve().parents[2]
MODELS_VARIABLE = "LOUPMD_MODELS"
TEST_MODEL_VARIABLE = "LOUPMD_TEST_MODEL"
DEFAULT_MODEL = "mace-omat-0-medium.model"


def find_model(name: str) -> str:
    """The path of a model file in the folder ``LOUPMD_MODELS`` names; skips the test when it is not there."""
    folder = os.environ.get(MODELS_VARIABLE)
    if not folder:
        pytest.skip(f"{MODELS_VARIABLE} names no folder with the model files ({name})")
    path = Path(os.path.expanduser(folder)) / name
    if not path.is_file():
        pytest.skip(f"{name} is not in {MODELS_VARIABLE} ({folder})")
    return str(path)


@contextlib.contextmanager
def unfolded():
    """Engines created inside run without the skip-chain fold (``LOUP_CHAIN_FOLD=0``, read when the engine loads the
    bundle): the whole-system reference for a tiled, domain or sweep result at float32-rounding bounds. Whole systems
    fold by default since the merge of round6-hardening ``13d6337``; a tiled or domain system never does (a sweep
    hands on the layer outputs the fold never forms). The fold is another order of float32 operations: on SrTiO3
    3x3x3 it moves the energy by 2-5e-8 eV/atom, forces by 1.8-2.5e-6 eV/A and stress by 0.6-2e-8 eV/A^3 (OMAT-0 small
    and medium, 17 November 2026), against 1e-6 eV/A and 6e-9 eV/A^3 between a domain and the unfolded call."""
    old = os.environ.get("LOUP_CHAIN_FOLD")
    os.environ["LOUP_CHAIN_FOLD"] = "0"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("LOUP_CHAIN_FOLD", None)
        else:
            os.environ["LOUP_CHAIN_FOLD"] = old


def srtio3(rep: int):
    """Cubic SrTiO3, ``rep`` cells along each axis (5 atoms per cell), as the benchmark's."""
    return suites.srtio3(rep)


def water_box():
    """The 648-atom water box shipped with the package."""
    from ase.io import read

    return read(suites.structure_file("water"))


def maxwell_velocities(atoms, temp_k: float, seed: int) -> np.ndarray:
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution, Stationary

    at = atoms.copy()
    MaxwellBoltzmannDistribution(at, temperature_K=temp_k, rng=np.random.default_rng(seed))
    Stationary(at)
    return at.get_velocities()
