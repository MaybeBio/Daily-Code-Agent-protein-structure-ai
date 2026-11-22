"""The features cut on purpose (PLAN.md decision A3, plan task S6-T09): float64 forces, the fallback to the MACE
calculator and the bitwise-reproducible mode. Each FastMACE spelling raises ``PlanRefused`` naming the alternative,
before any model file is read. Needs neither a GPU nor the library."""
from __future__ import annotations

import pytest
from ase.build import bulk

import loupmd
from loupmd import quick
from loupmd.config import Workload
from loupmd.errors import InputError, PlanRefused


def test_float64_forces_are_refused_with_the_alternative_named(tmp_path):
    missing = tmp_path / "never-read.model"             # the refusal comes before the file is looked for
    with pytest.raises(PlanRefused, match="float64 forces") as caught:
        loupmd.load(str(missing), precision="float64")
    assert "float32" in caught.value.next_step and "validate" in caught.value.next_step
    with pytest.raises(InputError, match="precision='float16'"):
        loupmd.load(str(missing), precision="float16")


def test_the_mace_calculator_fallback_is_refused_with_the_alternative_named():
    at = bulk("Cu", cubic=True)
    for options in ({"allow_reference": True}, {"fallback": "mace"}):
        with pytest.raises(PlanRefused, match="fallback to the MACE calculator") as caught:
            quick.md(at, model="omat0-medium", temperature_K=300, steps=10, **options)
        assert "MACECalculator" in caught.value.next_step


def test_the_bitwise_reproducible_mode_is_refused_with_the_alternative_named():
    assert Workload().reproducible is False
    with pytest.raises(PlanRefused, match="bitwise-reproducible") as caught:
        Workload(reproducible=True)
    assert "seed" in caught.value.next_step
