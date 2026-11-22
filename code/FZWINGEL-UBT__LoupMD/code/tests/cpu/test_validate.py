"""``loupmd validate`` (plan task S2-T09): the 3x rule, the structure sets, the reference cache, the variant matrix
and the command, with the engine and the MACE references replaced. Needs neither a GPU nor mace-torch."""
from __future__ import annotations

import json
import os
import types

import numpy as np
import pytest
from ase.build import bulk
from ase.io import write

from loupmd import config, validate
from loupmd.cli import main
from loupmd.errors import GateUnavailable, InputError, PlanRefused
from loupmd.validate import gate, references, sets

F32 = dict(de=0.004, df=4e-5, ds=4e-8)        # MACE's own float32 deviation in the fake references (above floor / 3)


# ------------------------------------------------------------------------------------------------- the rule

def _triple(n, energy=0.0, force=0.0, stress=0.0):
    return energy, np.full((n, 3), force), np.full((3, 3), stress)


def test_the_rule_is_three_times_mace_s_own_float32_deviation_or_the_floor():
    n = 10
    ref64, ref32 = _triple(n), _triple(n, F32["de"] * n / 1000.0, F32["df"], F32["ds"])
    inside = gate.compare("c", {}, n, _triple(n, 2.9 * F32["de"] * n / 1000.0, 2.9 * F32["df"], 2.9 * F32["ds"]),
                          ref64, ref32, ref64[2])
    assert inside.passed and inside.force_ratio == pytest.approx(2.9) and inside.stress_ratio == pytest.approx(2.9)
    assert inside.energy_ratio == pytest.approx(2.9) and inside.de_meV_per_atom == pytest.approx(2.9 * F32["de"])
    for field, value in (("energy", 3.2 * F32["de"] * n / 1000.0), ("force", 3.2 * F32["df"]),
                         ("stress", 3.2 * F32["ds"])):
        row = gate.compare("c", {}, n, _triple(n, **{field: value}), ref64, ref32, ref64[2])
        assert not row.passed and row.failed == (field,)


def test_below_the_floors_a_quantity_passes_whatever_the_ratio():
    n = 10
    ref = _triple(n)
    row = gate.compare("c", {}, n, _triple(n, 0.009 * n / 1000.0, 0.9e-5, 0.9e-7), ref, ref, ref[2])
    assert row.passed and row.force_ratio == pytest.approx(0.9e-5 / (config.GATE_FORCE_FLOOR_EV_PER_A / 3.0))
    row = gate.compare("c", {}, n, _triple(n, 0.0, 1.1e-5, 0.0), ref, ref, ref[2])
    assert not row.passed and row.failed == ("force",)


def test_the_stress_is_compared_with_its_own_reference():
    """PolarMACE: the float64 autograd stress is not the reference; the finite-difference stress is."""
    n = 4
    ref64, ref32 = _triple(n, stress=5e-4), _triple(n, stress=5e-4 + F32["ds"])
    corrected = np.full((3, 3), 1e-4)
    assert gate.compare("c", {}, n, _triple(n, stress=1e-4), ref64, ref32, corrected).passed
    assert not gate.compare("c", {}, n, _triple(n, stress=5e-4), ref64, ref32, corrected).passed


# --------------------------------------------------------------------------------------------------- sets

@pytest.fixture
def structures(tmp_path):
    cell = bulk("NaCl", "rocksalt", a=5.64, cubic=True)
    write(tmp_path / "NbCl5_R2SCAN.cif", cell.repeat((3, 3, 3)))     # 216 atoms under that name; 2x2x2 gives 1,728
    return {"LOUPMD_BENCH_STRUCTURES": str(tmp_path)}


def test_the_oxide_set_is_the_one_of_test_gate(structures):
    configs = sets.configs("oxide", environ=structures)
    assert [name for name, _ in configs] == ["NaCl_2x2x2_c0", "NaCl_2x2x2_c1", "SrTiO3_3x3x3_c0", "SrTiO3_3x3x3_c1",
                                             "NbCl5_2x2x2_c0", "NbCl5_2x2x2_c1"]
    assert [len(at) for _, at in configs][:4] == [64, 64, 135, 135]
    again = sets.configs("oxide", environ=structures)
    assert all(np.array_equal(a.positions, b.positions) and np.array_equal(a.cell.array, b.cell.array)
               for (_, a), (_, b) in zip(configs, again))
    # c0 is strained by +2 % and rattled by 0.05 A, c1 by -1.5 % and 0.08 A (tools/dev/test_gate.py).
    relaxed = bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((2, 2, 2))
    assert configs[0][1].get_volume() > relaxed.get_volume() > configs[1][1].get_volume()


def test_a_set_whose_file_is_missing_names_it():
    with pytest.raises(InputError) as caught:
        sets.configs("oxide", environ={})
    assert "NbCl5_R2SCAN.cif was not found" in str(caught.value) and "LOUPMD_BENCH_STRUCTURES" in str(caught.value)
    with pytest.raises(InputError, match="unknown set 'metals'"):
        sets.configs("metals", environ={})


def test_a_user_structure_is_gated_as_rattled_copies(tmp_path):
    path = tmp_path / "my.cif"
    cell = bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((2, 2, 2))
    write(path, cell)
    configs = sets.user_configs([str(path)], config.GateConfig())
    assert [name for name, _ in configs] == ["my_r0", "my_r1"]
    for _, at in configs:
        moved = at.positions - cell.positions
        assert np.allclose(at.cell.array, cell.cell.array) and 0.03 < moved.std() < 0.07
    assert not np.array_equal(configs[0][1].positions, configs[1][1].positions)
    three = sets.user_configs([cell], config.GateConfig(copies=3, rattle_A=0.01))
    assert [name for name, _ in three] == ["structure0_r0", "structure0_r1", "structure0_r2"]
    with pytest.raises(InputError, match="periodic"):
        sets.user_configs([_slab()], config.GateConfig())


def _slab():
    slab = bulk("NaCl", "rocksalt", a=5.64, cubic=True)
    slab.pbc = (True, True, False)
    return slab


# ------------------------------------------------------------------------------------------ reference cache

def test_references_round_trip_through_the_cache(tmp_path):
    rng = np.random.default_rng(1)
    ref64 = [(-1.5, rng.normal(size=(4, 3)), rng.normal(size=(3, 3))), (-2.5, rng.normal(size=(7, 3)), rng.normal(size=(3, 3)))]
    ref32 = [(e + 1e-6, f + 1e-6, s + 1e-9) for e, f, s in ref64]
    stress_ref = [s * 1.001 for _, _, s in ref64]
    path = tmp_path / "gate_refs" / "x.npz"
    references.save(path, ref64, ref32, stress_ref)
    back64, back32, back_stress = references.load(path, 2)
    for (e, f, s), (e2, f2, s2) in zip(ref64 + ref32, back64 + back32):
        assert e == e2 and np.array_equal(f, f2) and np.array_equal(s, s2)
    assert all(np.array_equal(a, b) for a, b in zip(stress_ref, back_stress))
    assert references.load(tmp_path / "absent.npz", 2) is None
    path.write_bytes(b"not an archive")
    assert references.load(path, 2) is None                      # an unreadable entry is recomputed


def test_the_cache_key_covers_what_a_reference_depends_on(tmp_path, structures):
    configs = sets.configs("oxide", environ=structures)
    key = dict(model_file="some.model", digest="ab" * 32, head=None, set_name="oxide", device_tag="cpu:x86_64",
               versions=("0.3.16", "2.14.1"), configs=configs, charge_spin=(None, None),
               environ={"LOUPMD_CACHE": str(tmp_path)})
    first = references.cache_path(**key)
    assert first.parent == tmp_path / "gate_refs" and first.name.startswith("some_oxide_") and first.suffix == ".npz"
    assert references.cache_path(**key) == first
    moved = [(name, at.copy()) for name, at in configs]
    moved[2][1].positions[0, 0] += 1e-9
    for change in (dict(digest="cd" * 32), dict(head="omat_pbe"), dict(device_tag="cuda:RTX"), dict(configs=moved),
                   dict(versions=("0.3.15", "2.14.1")), dict(charge_spin=(-1, 2))):
        assert references.cache_path(**dict(key, **change)) != first, change
    assert references.cache_path(**dict(key, environ={"LOUP_GATE_CACHE": str(tmp_path / "g")})).parent == tmp_path / "g"


def test_without_the_export_extra_the_gate_is_unavailable(monkeypatch):
    monkeypatch.setattr(references, "_find_spec", lambda name: None if name == "mace" else object())
    with pytest.raises(GateUnavailable) as caught:
        references.require()
    assert "mace-torch" in str(caught.value) and "loupmd[export]" in str(caught.value)


# ------------------------------------------------------------------------------------------------- run_gate

class GateEngine:
    """Returns the float64 reference of the configuration it is asked for, plus ``error`` on the forces."""

    made, error = [], 1e-5

    def __init__(self, bundle, device_id=0):
        self.bundle, self.device_id = bundle, device_id
        self.variant = {k: v for k, v in os.environ.items() if k in gate.VARIANT_KEYS}
        self.chain_fold = os.environ.get("LOUP_CHAIN_FOLD")
        self.tiled = []
        self.evaluated = 0
        GateEngine.made.append(self)

    def info(self):
        return types.SimpleNamespace(specialised=False)

    def set_system(self, numbers, masses, skin=0.5):
        self.n = len(numbers)

    def evaluate(self, positions, cell, compute_stress=True):
        self.evaluated += 1
        energy, forces, stress = GateEngine.truth[np.ascontiguousarray(positions, dtype=float).tobytes()]
        return energy, forces + GateEngine.error, stress

    def evaluate_tiled(self, numbers, positions, cell, receivers, skin=0.5):
        self.tiled.append((len(numbers), receivers, skin))
        energy, forces, stress = self.evaluate(positions, cell)
        return energy, forces, stress, -(-len(numbers) // receivers)

    def set_execution(self, mode, receivers, memory_fraction):
        self.execution = (mode, receivers, memory_fraction)

    def last_execution(self):
        from loupmd import _core

        return _core.Execution(getattr(self, "execution", (_core.LOUP_EXEC_TILED,))[0], 0, 4, 0, 0)


@pytest.fixture
def setup(tmp_path, monkeypatch, structures):
    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"never unpickled here")
    GateEngine.made, GateEngine.error = [], 1e-5
    calls = {"reference": 0, "exported": []}

    def reference(model_path, configs, head, ref_device, charge, spin):
        calls["reference"] += 1
        rng = np.random.default_rng(5)
        ref64 = [(-float(len(at)), rng.normal(size=(len(at), 3)), rng.normal(size=(3, 3)) * 1e-3) for _, at in configs]
        ref32 = [(e + F32["de"] * len(f) / 1000.0, f + F32["df"], s + F32["ds"]) for e, f, s in ref64]
        GateEngine.truth = {at.positions.tobytes(): ref for (_, at), ref in zip(configs, ref64)}
        return ref64, ref32, [s for _, _, s in ref64]

    def ensure_bundle(model_path, numbers, head=None, generic=None, charge=None, spin_multiplicity=None, environ=None):
        calls["exported"].append(tuple(numbers))
        return tmp_path / ("bundle-" + "-".join(map(str, numbers)) + ".loup")

    environ = dict(structures, LOUPMD_CACHE=str(tmp_path / "cache"))
    monkeypatch.setattr(references, "require", lambda: None)
    monkeypatch.setattr(references, "versions", lambda: ("0.3.16", "2.14.1"))
    monkeypatch.setattr(references, "device_tag", lambda device: f"{device}:fake")
    monkeypatch.setattr(references, "resolve_device", lambda wanted: "cpu" if wanted == "auto" else wanted)
    monkeypatch.setattr(references, "default_head", lambda path: None)

    def run(**more):
        options = dict(trusted=True, engine_factory=GateEngine, ensure_bundle=ensure_bundle, reference=reference,
                       bundle_meta=lambda bundle: {"arch": "generic"}, environ=environ)
        options.update(more)
        return validate.run_gate(str(checkpoint), **options)

    run.calls, run.environ = calls, environ
    return run


CONV = {"arch": "generic", "n_layers": 2, "L0.first_hidden": 1, "L0.lmax_x": 0, "L0.C_x": 128,
        "L1.first_hidden": 0, "L1.lmax_x": 1, "L1.C_x": 128}


def test_the_default_gate_runs_every_kernel_path_of_a_model_with_conv_variants(setup, monkeypatch):
    monkeypatch.setenv("LOUP_REORDER", "1")          # the caller's setting reaches no engine of the gate
    record = setup(bundle_meta=lambda bundle: CONV)
    assert record["schema"] == "loupmd.gate/1" and record["passed"] is True and record["set"] == "oxide"
    rows = record["rows"]
    by_config = {}
    for row in rows:
        by_config.setdefault(row["config"], []).append(row["variant"])
    # Every configuration: the default choice, then each conv forward variant forced.
    assert len(by_config) == 6
    assert all(variants == ["default", "conv_fwd_variant=1", "conv_fwd_variant=2"] for variants in by_config.values())
    assert len(rows) == 6 * 3 and all(row["passed"] for row in rows)
    assert rows[0]["force_ratio"] == pytest.approx(1e-5 / F32["df"])
    assert record["reorder"] == []                   # the retired specialised kernels' comparison: the field stays
    # One engine per element set and variant, made with the variant in the environment, which is clean afterwards.
    by_bundle = {}
    for engine in GateEngine.made:
        by_bundle.setdefault(engine.bundle.name, set()).add(tuple(sorted(engine.variant.items())))
    assert len(GateEngine.made) == 3 * len(by_bundle)
    assert all(variants == {(), (("LOUP_CONV_FWD_VARIANT", "1"),), (("LOUP_CONV_FWD_VARIANT", "2"),)}
               for variants in by_bundle.values())
    assert os.environ["LOUP_REORDER"] == "1" and "LOUP_CONV_FWD_VARIANT" not in os.environ
    assert record["worst"]["force_ratio"] == pytest.approx(1e-5 / F32["df"])
    assert record["model"]["file"] == "some.model" and len(record["model"]["sha256"]) == 64
    text = validate.format_gate(record)
    assert "PASS" in text and "NbCl5_2x2x2_c1" in text and "conv_fwd_variant=2" in text


def test_generic_models_gate_their_conv_variants_or_only_the_default(setup):
    plain = setup()
    assert {row["variant"] for row in plain["rows"]} == {"default"} and len(plain["rows"]) == 6
    conv = CONV
    assert gate.has_conv_variants(conv) and not gate.has_conv_variants(dict(conv, **{"L1.C_x": 64}))
    tuned = setup(bundle_meta=lambda bundle: conv)
    assert [row["variant"] for row in tuned["rows"][:3]] == ["default", "conv_fwd_variant=1", "conv_fwd_variant=2"]
    assert tuned["reorder"] == []


def test_the_tiled_gate_runs_every_configuration_tile_by_tile(setup, monkeypatch):
    """S5-T04: --capacity tiled evaluates through the tiled call, about four tiles per cell, on default engines
    (a tiled system leaves the skip-chain fold off itself; the caller's LOUP_CHAIN_FOLD reaches no engine of the
    gate), and records the mode."""
    monkeypatch.setenv("LOUP_CHAIN_FOLD", "1")
    record = setup(capacity="tiled")
    assert record["passed"] is True and record["capacity"] == "tiled"
    assert {row["variant"] for row in record["rows"]} == {"default"} and len(record["rows"]) == 6
    calls = [call for engine in GateEngine.made for call in engine.tiled]
    assert len(calls) == 6 and all(receivers == -(-n // 4) and skin == 0.5 for n, receivers, skin in calls)
    assert all(engine.chain_fold is None for engine in GateEngine.made)
    assert os.environ["LOUP_CHAIN_FOLD"] == "1"                 # the caller's setting is back
    assert setup()["capacity"] == "whole"
    assert "capacity: tiled" in validate.format_gate(record)


def test_the_wavefront_gate_asks_the_engine_for_the_wavefront(setup):
    """S5-T08: --capacity wavefront runs the tiled call with LOUP_EXEC_WAVEFRONT set, and records the mode."""
    from loupmd import _core

    record = setup(capacity="wavefront")
    assert record["passed"] is True and record["capacity"] == "wavefront"
    assert all(engine.execution[0] == _core.LOUP_EXEC_WAVEFRONT for engine in GateEngine.made)
    assert len([call for engine in GateEngine.made for call in engine.tiled]) == 6


def test_the_gate_refuses_the_retired_specialised_kernels(setup):
    for capacity in ("whole", "tiled"):
        with pytest.raises(PlanRefused, match="specialised to MACE-OMAT-0 medium were retired"):
            setup(capacity=capacity, generic=False)
    with pytest.raises(PlanRefused, match="capacity must be 'whole', 'tiled' or 'wavefront'"):
        setup(capacity="auto")


        self.variant = {k: v for k, v in os.environ.items() if k in gate.VARIANT_KEYS}
        self.chain_fold = os.environ.get("LOUP_CHAIN_FOLD")
        self.tiled = []
    GateEngine.error = 3.5 * F32["df"]
    record = setup()
    assert record["passed"] is False and all(row["failed"] == ["force"] for row in record["rows"])
    assert record["worst"]["force_ratio"] == pytest.approx(3.5)
    text = validate.format_gate(record)
    assert "FAIL" in text and "ref32: dE/atom" in text


def test_references_are_computed_once_and_then_read_from_the_cache(setup, tmp_path):
    first = setup()
    assert setup.calls["reference"] == 1 and first["reference"]["cached"] is False
    cache_file = first["reference"]["file"]
    assert cache_file.startswith(str(tmp_path / "cache" / "gate_refs")) and os.path.isfile(cache_file)
    second = setup()
    assert setup.calls["reference"] == 1 and second["reference"]["cached"] is True
    assert second["rows"][0]["df"] == first["rows"][0]["df"]
    setup(use_ref_cache=False)
    assert setup.calls["reference"] == 2


def test_a_reference_that_does_not_fit_the_gpu_goes_to_the_cpu_or_makes_the_gate_unavailable(setup, monkeypatch):
    devices = []

    def reference(model_path, configs, head, ref_device, charge, spin):
        devices.append(ref_device)
        if ref_device.startswith("cuda"):
            raise RuntimeError("CUDA out of memory. Tried to allocate 9.31 GiB")
        rng = np.random.default_rng(5)
        ref64 = [(-float(len(at)), rng.normal(size=(len(at), 3)), rng.normal(size=(3, 3)) * 1e-3) for _, at in configs]
        GateEngine.truth = {at.positions.tobytes(): ref for (_, at), ref in zip(configs, ref64)}
        return ref64, [(e, f + F32["df"], s + F32["ds"]) for e, f, s in ref64], [s for _, _, s in ref64]

    monkeypatch.setattr(references, "resolve_device", lambda wanted: "cuda" if wanted == "auto" else wanted)
    record = setup(reference=reference)
    assert devices == ["cuda", "cpu"] and record["passed"] and record["reference"]["device"] == "cpu:fake"
    for gate_config, word in ((config.GateConfig(cpu_float64_time_limit_s=0), "does not fit the GPU"),
                              (config.GateConfig(reference_device="cuda"), "--ref-device cpu")):
        with pytest.raises(GateUnavailable) as caught:
            setup(reference=reference, gate_config=gate_config, use_ref_cache=False)
        assert word in str(caught.value) and "CUDA out of memory" in str(caught.value)

    def broken(*a):
        raise RuntimeError("something else")

    with pytest.raises(RuntimeError, match="something else"):
        setup(reference=broken, use_ref_cache=False)


def test_a_user_structure_and_the_unstable_list(setup, tmp_path, monkeypatch):
    path = tmp_path / "my.cif"
    write(path, bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((2, 2, 2)))
    record = setup(structures=[str(path)], gate_config=config.GateConfig(copies=3))
    assert record["set"] == "user" and [row["config"] for row in record["rows"] if row["variant"] == "default"] == [
        "my_r0", "my_r1", "my_r2"]
    monkeypatch.setattr(gate, "UNSTABLE", {("some", "SrTiO3_3x3x3_c0")})
    record = setup()
    assert record["left_out"] == ["SrTiO3_3x3x3_c0"]
    assert "SrTiO3_3x3x3_c0" not in {row["config"] for row in record["rows"]}
    assert "SrTiO3_3x3x3_c0" in {row["config"] for row in setup(include_unstable=True)["rows"]}


def test_the_refusals_come_before_any_reference_or_export(setup, monkeypatch):
    from loupmd.errors import CheckpointTrustError

    with pytest.raises(CheckpointTrustError):
        setup(trusted=False)
    with pytest.raises(InputError, match="unknown set"):
        setup(set_name="metals")

    def missing():
        raise GateUnavailable("the gate needs mace-torch")

    monkeypatch.setattr(references, "require", missing)
    with pytest.raises(GateUnavailable):
        setup()
    assert setup.calls == {"reference": 0, "exported": []}


# -------------------------------------------------------------------------------------------------- command

def _record(passed=True):
    row = gate.GateRow(config="NaCl_2x2x2_c0", variant="default", atoms=64, de_meV_per_atom=0.001, df=2e-5, ds=1e-8,
                       de32=0.002, df32=4e-5, ds32=3e-8, energy_ratio=0.5, force_ratio=0.5 if passed else 4.0,
                       stress_ratio=0.33, passed=passed, failed=() if passed else ("force",))
    return gate.make_record([row], [], passed, set_name="oxide", model={"label": "omat0-medium", "file": "m.model",
                            "sha256": "d4" * 32, "head": None}, reference={"device": "cuda:x", "file": "/c/x.npz",
                            "cached": True, "mace": "0.3.16", "torch": "2.14.1"}, library="lib", left_out=[])


def test_the_command_exits_0_on_a_pass_and_1_on_a_failure(monkeypatch, tmp_path, capsys):
    seen = {}

    def run_gate(model, **kw):
        seen.update(kw, model=model)
        return _record(passed=seen.get("want", True))

    monkeypatch.setattr(validate, "run_gate", run_gate)
    target = tmp_path / "gate.json"
    assert main(["validate", "--model", "omat0-medium", "--json", str(target)]) == 0
    out = capsys.readouterr().out
    assert "NaCl_2x2x2_c0" in out and out.rstrip().endswith("gate PASSED")
    assert json.loads(target.read_text())["schema"] == "loupmd.gate/1"
    assert seen["model"] == "omat0-medium" and seen["set_name"] == "oxide" and seen["structures"] is None
    seen["want"] = False
    assert main(["validate", "--model", "omat0-medium", "--set", "crystals", "--ref-device", "cpu", "--no-ref-cache",
                 "--include-unstable", "--specialised", "--charge", "-1", "--spin-multiplicity", "2"]) == 1
    captured = capsys.readouterr()
    assert "gate FAILED" in captured.out
    assert (seen["set_name"], seen["use_ref_cache"], seen["include_unstable"], seen["generic"], seen["charge"],
            seen["spin_multiplicity"]) == ("crystals", False, True, False, -1, 2)
    assert seen["gate_config"].reference_device == "cpu"


def test_the_command_takes_user_structures_and_reports_a_missing_extra(monkeypatch, capsys):
    seen = {}

    def run_gate(model, **kw):
        seen.update(kw)
        raise GateUnavailable("the gate needs mace-torch, which is not installed")

    monkeypatch.setattr(validate, "run_gate", run_gate)
    assert main(["validate", "--model", "omat0-medium", "--structure", "a.cif", "--structure", "b.cif"]) == 1
    assert seen["structures"] == ["a.cif", "b.cif"]
    err = capsys.readouterr().err
    assert err.startswith("error: the gate needs mace-torch") and "loupmd[export]" in err
