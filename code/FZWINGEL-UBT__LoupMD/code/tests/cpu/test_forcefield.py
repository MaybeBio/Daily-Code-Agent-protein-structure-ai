"""``lm.load`` and ``ForceField`` (plan task S3-T02) with the engine, the exporter and the checkpoint probe
replaced: what is refused before any export, and when the engine is reused. Needs neither a GPU nor torch."""
from __future__ import annotations

import numpy as np
import pytest
from ase.build import bulk

import loupmd
from loupmd import forcefield, models
from loupmd.errors import CheckpointTrustError, InputError, ModelElementError, PlanRefused


class SpringEngine:
    made = []

    def __init__(self, bundle, device_id=0):
        self.bundle, self.device_id, self.calls = bundle, device_id, []
        SpringEngine.made.append(self)

    def set_system(self, numbers, masses, skin=0.5):
        self.calls.append(("set_system", tuple(int(z) for z in numbers), skin))

    def evaluate(self, positions, cell, compute_stress=True):
        self.calls.append(("evaluate", bool(compute_stress)))
        positions = np.asarray(positions, dtype=float)
        return 0.25 * float((positions ** 2).sum()), -0.5 * positions, np.eye(3) * 1e-3 if compute_stress else None


@pytest.fixture
def checkpoint(tmp_path):
    path = tmp_path / "some.model"
    path.write_bytes(b"never unpickled here")
    return path


@pytest.fixture
def load(checkpoint):
    SpringEngine.made = []
    exported = []

    def ensure_bundle(model_path, numbers, head=None, charge=None, spin_multiplicity=None, environ=None):
        exported.append((model_path.name, tuple(numbers), head, charge, spin_multiplicity))
        return model_path.with_name("bundle-" + "-".join(map(str, numbers)) + ".loup")

    def make(model=None, **options):
        options.setdefault("trusted", True)
        options.setdefault("probe", lambda path: None)
        return loupmd.load(str(checkpoint) if model is None else model, engine_factory=SpringEngine,
                           ensure_bundle=ensure_bundle, **options)

    make.exported = exported
    return make


def _nacl():
    return bulk("NaCl", "rocksalt", a=5.64, cubic=True)


# ----------------------------------------------------------------------------------------------- the table

def test_the_table_knows_what_each_release_holds():
    assert len(models.CHECKPOINTS["medium-omat-0"].elements) == 89 and 84 not in models.LABELS["omat0-medium"].elements
    assert models.LABELS["off23-small"].elements == (1, 6, 7, 8, 9, 15, 16, 17, 35, 53)
    assert models.LABELS["polar1-s"].elements == tuple(range(1, 84))
    assert [models.CHECKPOINTS[name].interactions for name in ("polar-1-s", "polar-1-m", "polar-1-l", "omol-0-xl",
                                                                "medium-omat-0")] == [1, 2, 3, 3, 2]
    assert [models.CHECKPOINTS[name].r_max_A for name in ("large", "off23-small", "off23-medium", "mh-1")] == [
        4.5, 4.5, 5.0, 6.0]
    for entry in models.CHECKPOINTS.values():
        assert entry.elements == tuple(sorted(set(entry.elements))) and entry.r_max_A > 0 and entry.interactions >= 1
    for label in models.LABELS.values():
        assert label.checkpoint is models.CHECKPOINTS[label.checkpoint.name]
    assert models.checkpoint_of_digest(models.CHECKPOINTS["mh-1"].sha256) is models.CHECKPOINTS["mh-1"]
    assert models.checkpoint_of_digest("00" * 32) is None


# --------------------------------------------------------------------------------------------------- load

def test_load_a_label_gives_its_facts_without_reading_the_file(load, checkpoint):
    ff = load("omat0-medium", checkpoint=str(checkpoint))
    assert isinstance(ff, loupmd.ForceField)
    assert (ff.label, ff.head, ff.licence, ff.functional, ff.r_max_A) == ("omat0-medium", None, models.ASL, "pbe", 6.0)
    assert ff.path == checkpoint.resolve() and len(ff.sha256) == 64 and len(ff.elements) == 89
    text = repr(ff)
    assert "omat0-medium" in text and "some.model" in text and ff.sha256[:16] in text
    assert load.exported == [] and SpringEngine.made == []        # nothing is exported or loaded by load


def test_a_multi_head_model_without_a_head_is_refused_naming_its_heads(load):
    with pytest.raises(InputError) as caught:
        load("mh1")
    assert "several heads and no default" in str(caught.value) and "matpes_r2scan, mp_pbe_refit_add" in str(caught.value)
    assert load("mh1", head="matpes_r2scan", checkpoint=__file__).head == "matpes_r2scan"
    assert load("mh1-omat", checkpoint=__file__).head == "omat_pbe"


def test_a_file_outside_the_table_needs_trust_and_is_probed_for_its_heads_and_elements(load, checkpoint):
    with pytest.raises(CheckpointTrustError):
        load(trusted=False)
    ff = load(probe=lambda path: {"elements": [11, 17], "heads": ["a", "b"], "r_max": 5.0, "class": "ScaleShiftMACE",
                                  "num_interactions": 2})
    assert ff.label is None and ff.elements is None               # not probed until a structure is evaluated
    with pytest.raises(InputError) as caught:
        ff.evaluate(_nacl())
    assert "has several heads and no default" in str(caught.value) and "a, b" in str(caught.value)
    ff = load(head="b", probe=lambda path: {"elements": [11, 17], "heads": ["a", "b"], "r_max": 5.0})
    energy, forces, stress = ff.evaluate(_nacl())
    assert ff.elements == (11, 17) and ff.r_max_A == 5.0 and stress is None
    assert load.exported == [("some.model", (11, 17), "b", None, None)]


# ---------------------------------------------------------------------------------------------- elements

def test_a_missing_element_is_refused_before_any_export(load, checkpoint):
    ff = load("off23-small", checkpoint=str(checkpoint))
    with pytest.raises(ModelElementError) as caught:
        ff.evaluate(_nacl())
    text = str(caught.value)
    assert text.startswith("the structure has Na, which off23-small has no embedding for")
    assert "Why: its elements are H, C, N, O, F, P, S, Cl, Br, I" in text
    assert load.exported == [] and SpringEngine.made == []
    with pytest.raises(ModelElementError, match="has Na, Fr, which"):
        ff.check_elements([11, 87, 1])


def test_a_long_element_list_is_given_as_ranges(load, checkpoint):
    ff = load("omat0-medium", checkpoint=str(checkpoint))
    with pytest.raises(ModelElementError) as caught:
        ff.check_elements([84, 8])
    assert "has Po, which omat0-medium has no embedding for" in str(caught.value)
    assert "its elements are H to Bi (Z 1-83) and Ac to Pu (Z 89-94)" in str(caught.value)


def test_a_file_whose_elements_cannot_be_probed_is_left_to_the_exporter(load):
    ff = load(probe=lambda path: None)                              # no torch here
    ff.evaluate(_nacl())
    assert ff.elements is None and load.exported == [("some.model", (11, 17), None, None, None)]


def test_a_released_file_given_by_path_is_recognised_by_its_hash(load, checkpoint, monkeypatch):
    digest = models.sha256_of(checkpoint)
    monkeypatch.setattr(models, "checkpoint_of_digest",
                        lambda d: models.CHECKPOINTS["off23-small"] if d == digest else None)
    ff = load(probe=lambda path: pytest.fail("a known release needs no probe"))
    assert ff.label is None and ff.elements == (1, 6, 7, 8, 9, 15, 16, 17, 35, 53) and ff.licence == models.ASL
    with pytest.raises(ModelElementError, match="which some.model has no embedding for"):
        ff.evaluate(_nacl())


def test_a_released_multi_head_file_given_by_path_needs_its_head(load, checkpoint, monkeypatch):
    """MACE-MH-1's file given by path follows its label's rule: no default head, and the training functional (the D3
    parameters) is the chosen head's, not the first stored head's."""
    digest = models.sha256_of(checkpoint)
    monkeypatch.setattr(models, "checkpoint_of_digest", lambda d: models.CHECKPOINTS["mh-1"] if d == digest else None)
    with pytest.raises(InputError) as caught:
        load()
    assert "some.model has several heads and no default" in str(caught.value) and "omat_pbe" in str(caught.value)
    with pytest.raises(InputError, match="some.model has no head 'nonsense'"):
        load(head="nonsense")
    ff = load(head="omat_pbe")
    assert (ff.label, ff.head, ff.functional) == (None, "omat_pbe", "pbe")
    assert load(head="matpes_r2scan").functional == "r2scan"


def test_lm_config_is_reachable_as_the_guides_write_it():
    import importlib

    assert loupmd.__getattr__("config") is importlib.import_module("loupmd.config")
    assert loupmd.config.CapacityConfig(mode="tiled", receivers=8192).receivers == 8192


# ---------------------------------------------------------------------------------------------- evaluate

def test_evaluate_returns_energy_forces_and_the_stress_when_asked(load):
    ff = load()
    at = _nacl()
    energy, forces, stress = ff.evaluate(at)
    assert energy == pytest.approx(0.25 * (at.positions ** 2).sum()) and np.allclose(forces, -0.5 * at.positions)
    assert stress is None
    assert ff.evaluate(at, stress=True)[2].shape == (3, 3)
    engine, = SpringEngine.made
    assert [c for c in engine.calls if c[0] == "evaluate"] == [("evaluate", False), ("evaluate", True)]
    assert len([c for c in engine.calls if c[0] == "set_system"]) == 1


def test_the_engine_is_kept_while_the_elements_fit_the_bundle(load):
    ff = load(device=1)
    at = _nacl()
    ff.evaluate(at)
    ff.evaluate(at.repeat((2, 1, 1)))                               # another count: the system is set again
    doped = at.copy()
    doped.numbers[0] = 19
    ff.evaluate(doped)                                              # a new element: a new bundle and engine
    ff.evaluate(at, skin=0.3)                                       # back, with another skin
    assert [e.bundle.name for e in SpringEngine.made] == ["bundle-11-17.loup", "bundle-11-17-19.loup"]
    assert SpringEngine.made[1].device_id == 1 and ff.engine is SpringEngine.made[1]
    assert [c[2] for c in SpringEngine.made[1].calls if c[0] == "set_system"] == [0.5, 0.3]
    assert len(load.exported) == 2


def test_a_cell_that_is_not_periodic_is_refused(load):
    slab = _nacl()
    slab.pbc = (True, True, False)
    with pytest.raises(PlanRefused, match="periodic in all three directions"):
        load().evaluate(slab)
    assert load.exported == []


def test_the_calculator_takes_a_force_field(load):
    ff = load()
    at = _nacl()
    at.calc = loupmd.calc(ff)
    assert at.calc.force_field is ff and at.get_potential_energy() == pytest.approx(0.25 * (at.positions ** 2).sum())
    assert at.calc.engine is ff.engine
    with pytest.raises(InputError, match="already loaded"):
        loupmd.calc(ff, head="x")


# ------------------------------------------------------------------------------- the table against the files

_ALL = bool(__import__("os").environ.get("LOUPMD_TEST_ALL_MODELS"))


@pytest.mark.parametrize("name", sorted(models.CHECKPOINTS) if _ALL else ["small-omat-0", "off23-small", "polar-1-s"])
def test_the_table_equals_what_the_released_file_holds(name):
    """Reads the released file with torch on the CPU (three small files; LOUPMD_TEST_ALL_MODELS=1 for all 18).
    Skips without the file, without torch, or when the file is not the release."""
    import os
    from pathlib import Path

    entry = models.CHECKPOINTS[name]
    if not os.environ.get("LOUPMD_MODELS"):
        pytest.skip("LOUPMD_MODELS names no folder with the released model files")
    path = Path(os.environ["LOUPMD_MODELS"]) / entry.file_name
    if not path.is_file():
        pytest.skip(f"{path} not found")
    if models.sha256_of(path) != entry.sha256:
        pytest.skip(f"{path} is not the released file")
    found = forcefield.probe_checkpoint(path)
    if found is None:
        pytest.skip("torch or mace-torch is not installed")
    assert tuple(found["elements"]) == entry.elements
    assert (found["r_max"], found["num_interactions"], tuple(found["heads"])) == (entry.r_max_A, entry.interactions,
                                                                                 entry.heads)
    assert found["class"] == ("PolarMACE" if entry.model_type == "PolarMACE" else "ScaleShiftMACE")
