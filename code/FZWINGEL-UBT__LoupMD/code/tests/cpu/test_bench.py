"""``loupmd bench`` (plan task S2-T08): protocol arithmetic, the record, suites, refusals, the A/B order and the
command. The engine, the exporter and nvidia-smi are replaced, so nothing here needs a GPU or the library."""
from __future__ import annotations

import json
import math
import types

import pytest

from loupmd import bench
from loupmd.bench import protocol, reference, suites
from loupmd.cli import main
from loupmd.errors import InputError, LoupError

GPU = {"name": "NVIDIA GeForce RTX 5060 Ti", "compute_capability": "12.0", "driver": "621.14"}
MODEL = {"label": "omat0-medium", "file": "mace-omat-0-medium.model", "sha256": "d4" * 32, "head": None}


def _row(name="SrTiO3 6x6x6", atoms=1080, blocks=(2.0, 2.2), temperature=301.0, **more):
    return protocol.row_from_blocks(name, atoms, list(blocks), protocol.PROTOCOLS["quick"], temperature, **more)


# ------------------------------------------------------------------------------------------------- protocol

def test_the_standard_protocol_is_the_one_of_bench_md():
    p = protocol.PROTOCOLS["standard"]
    assert (p.temperature_K, p.timestep_fs, p.friction_per_fs, p.skin_A) == (300.0, 1.0, 0.01, 0.5)
    assert (p.warmup_steps, p.blocks, p.block_steps, p.velocity_seed) == (100, 6, 256, 42)
    fm = protocol.PROTOCOLS["fastmace"]
    assert (fm.warmup_steps, fm.blocks, fm.block_steps) == (300, 4, 300)
    quick = protocol.PROTOCOLS["quick"]
    assert (quick.blocks, quick.block_steps) == (2, 128)


def test_a_row_is_the_median_block_with_its_derived_figures():
    row = protocol.row_from_blocks("SrTiO3 10x10x10", 5000, [8.0, 8.2, 8.1, 8.4, 8.0, 8.1], protocol.PROTOCOLS["standard"],
                                   final_temperature_K=302.0, dangerous_builds=1, pipelined_steps=1500, rebuilds=7,
                                   bundle="abc.loup")
    assert row.ms_per_step == pytest.approx(8.1)
    assert row.us_per_atom_step == pytest.approx(8.1e3 / 5000)
    assert row.ns_per_day == pytest.approx(86.4 * 1.0 / 8.1)          # 1 fs steps
    assert row.block_spread == pytest.approx(0.4 / 8.1)
    assert (row.dangerous_builds, row.pipelined_steps, row.rebuilds, row.bundle, row.status) == (
        1, 1500, 7, "abc.loup", "ok")


def test_a_non_finite_temperature_marks_the_row_unstable():
    row = _row(temperature=float("nan"))
    assert row.status == "UNSTABLE" and math.isnan(row.ns_per_day)
    assert "UNSTABLE" in protocol.format_table([row])


def test_the_table_names_every_column_of_the_plan():
    text = protocol.format_table([_row()])
    head, rule, line = text.splitlines()
    for column in ("system", "atoms", "ms/step", "us/atom-step", "ns/day", "spread", "T / K", "dangerous", "status"):
        assert column in head
    assert set(rule) <= {"-", " "}
    assert line.split()[:3] == ["SrTiO3", "6x6x6", "1080"] and "2.100" in line and "301" in line
    assert "reference" not in head


def test_the_table_shows_the_stored_reference_and_the_ratio():
    text = protocol.format_table([_row()], references={"SrTiO3 6x6x6": 2.0})
    assert "reference" in text.splitlines()[0] and "ratio" in text.splitlines()[0]
    assert "2.000" in text.splitlines()[2] and "1.050" in text.splitlines()[2]


class _Stats(types.SimpleNamespace):
    pass


class FakeEngine:
    """Records the calls of the protocol; every block of n steps takes ``2 + block index / 10`` ms per step."""

    made = []

    def __init__(self, bundle, device_id=0):
        self.bundle, self.device_id, self.calls = bundle, device_id, []
        FakeEngine.made.append(self)

    def set_system(self, numbers, masses, skin):
        self.calls.append(("set_system", len(numbers), skin))

    def set_state(self, positions, velocities, cell):
        self.calls.append(("set_state", float(abs(velocities).max()) > 0.0))

    def run_langevin(self, n, dt_fs, temp_k, friction_per_fs, seed):
        self.calls.append(("run", n, dt_fs, temp_k, friction_per_fs, seed))
        return _Stats(step_ms=2.0 + 0.1 * (seed - 2), final_temperature_k=300.0 + seed, dangerous_builds=0,
                      pipelined_steps=n - 1, rebuilds=1)


def test_time_system_runs_warm_up_then_the_blocks_with_the_seeds_of_bench_md():
    engine = FakeEngine("x.loup")
    row = protocol.time_system(engine, "SrTiO3 6x6x6", suites.srtio3(2), protocol.PROTOCOLS["standard"], bundle="x.loup")
    assert engine.calls[0] == ("set_system", 40, 0.5)
    assert engine.calls[1] == ("set_state", True)                # Maxwell-Boltzmann velocities, not a cell at rest
    assert engine.calls[2] == ("run", 100, 1.0, 300.0, 0.01, 1)
    assert [c[1] for c in engine.calls[3:]] == [256] * 6 and [c[5] for c in engine.calls[3:]] == [2, 3, 4, 5, 6, 7]
    assert row.atoms == 40 and row.ms_per_step == pytest.approx(2.25) and row.final_temperature_K == 307.0
    assert row.rebuilds == 6 and row.pipelined_steps == 6 * 255


# --------------------------------------------------------------------------------------------------- record

def test_a_record_validates_and_survives_json():
    record = protocol.make_record([_row()], protocol.PROTOCOLS["quick"], "quick", GPU, MODEL,
                                  "0.1.0a1+0123456789abcdef", "0.1.0a1", other_gpu_processes=[],
                                  gpu_utilisation_percent=0)
    assert record["schema"] == "loupmd.bench/1" and protocol.validate_record(record) == []
    back = json.loads(json.dumps(record))
    assert protocol.validate_record(back) == []
    assert back["rows"][0]["blocks_ms"] == [2.0, 2.2] and back["protocol"]["block_steps"] == 128
    assert back["gpu"] == GPU and back["model"]["sha256"] == "d4" * 32


@pytest.mark.parametrize("damage,problem", [
    (lambda r: r.pop("library"), "missing key 'library'"),
    (lambda r: r.update(schema="loupmd.bench/0"), "schema is 'loupmd.bench/0'"),
    (lambda r: r["gpu"].pop("driver"), "gpu lacks 'driver'"),
    (lambda r: r["model"].pop("sha256"), "model lacks 'sha256'"),
    (lambda r: r["rows"][0].pop("blocks_ms"), "row 0 lacks 'blocks_ms'"),
    (lambda r: r["rows"][0].update(status="fine"), "row 0: status 'fine'"),
    (lambda r: r["rows"][0].update(atoms="many"), "row 0: 'atoms' is not a int"),
])
def test_a_damaged_record_is_reported(damage, problem):
    record = protocol.make_record([_row()], protocol.PROTOCOLS["quick"], "quick", GPU, MODEL, "lib", "0.1.0a1")
    damage(record)
    assert any(problem in p for p in protocol.validate_record(record)), protocol.validate_record(record)


# --------------------------------------------------------------------------------------------------- suites

def test_the_quick_suite_needs_no_file():
    (name, atoms), = suites.systems_of("quick", environ={})
    assert name == "SrTiO3 6x6x6" and len(atoms) == 1080


def test_the_standard_suite_names_the_missing_structure_and_the_way_out():
    with pytest.raises(InputError) as caught:
        suites.systems_of("standard", environ={})
    text = str(caught.value)
    assert "NbCl5_R2SCAN.cif was not found" in text and "LOUPMD_BENCH_STRUCTURES" in text and "--suite quick" in text


def test_several_structure_folders_are_searched_in_order(tmp_path):
    import os

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "NbCl5_R2SCAN.cif").write_text("")
    found = suites.find_file("NbCl5_R2SCAN.cif", {"LOUPMD_BENCH_STRUCTURES": os.pathsep.join(
        [str(tmp_path / "a"), str(tmp_path / "b")])})
    assert found == tmp_path / "b" / "NbCl5_R2SCAN.cif"


def test_the_shipped_structures_are_found_first_and_named_with_their_hashes():
    import hashlib
    from pathlib import Path

    folder = Path(suites.__file__).resolve().parent / "structures"
    sources = (folder / "SOURCES.md").read_text(encoding="utf-8")
    shipped = sorted(p for p in folder.iterdir() if p.name != "SOURCES.md")
    assert [p.name for p in shipped] == ["naphthalene_cod2311090.cif", "paracetamol_cod2104364.cif",
                                         "urea_cod1008787.cif", "water_216.extxyz"]
    for path in shipped:
        assert f"| `{path.name}` |" in sources and hashlib.sha256(path.read_bytes()).hexdigest() in sources
        assert suites.find_file(path.name, {}) == path
    (name, water), = suites.systems_of("standard", systems=["water 216"], environ={})   # no folder is named
    assert name == "water 216" and len(water) == 648


def test_the_standard_suite_reads_the_structure_folder(tmp_path):
    from ase.build import bulk
    from ase.io import write

    write(tmp_path / "NbCl5_R2SCAN.cif", bulk("NaCl", "rocksalt", a=5.64, cubic=True))   # any cell under that name
    systems = suites.systems_of("standard", environ={"LOUPMD_BENCH_STRUCTURES": str(tmp_path)})
    assert [name for name, _ in systems] == ["NbCl5 3x3x3", "SrTiO3 10x10x10"]
    assert [len(atoms) for _, atoms in systems] == [8 * 27, 5000]


@pytest.mark.parametrize("family,system,atoms", [("density", "SrTiO3 10x10x10", 5000), ("mh1", "SrTiO3 10x10x10", 5000),
                                                 ("polar", "NaCl 3x3x3", 216)])
def test_the_families_suite_takes_one_system_for_the_model_family(family, system, atoms):
    (name, structure), = suites.systems_of("families", family=family, environ={})
    assert name == system and len(structure) == atoms


def test_the_families_suite_needs_a_family_and_explicit_systems_replace_a_suite():
    with pytest.raises(InputError, match="family"):
        suites.systems_of("families", family=None, environ={})
    chosen = suites.systems_of("standard", systems=["SrTiO3 6x6x6", "NaCl 3x3x3"], environ={})
    assert [name for name, _ in chosen] == ["SrTiO3 6x6x6", "NaCl 3x3x3"]
    with pytest.raises(InputError, match="unknown system 'Fe'"):
        suites.systems_of("standard", systems=["Fe"], environ={})


def test_unknown_and_unbuilt_suites_are_refused():
    with pytest.raises(InputError, match="unknown suite 'nope'"):
        suites.systems_of("nope", environ={})
    with pytest.raises(LoupError, match="tiled"):
        suites.systems_of("capacity", environ={})


# ------------------------------------------------------------------------------------------------ busy GPU

def _gpu(monkeypatch, processes=(), utilisation=0):
    monkeypatch.setattr(bench, "gpu_processes", lambda device=0: list(processes))
    monkeypatch.setattr(bench, "gpu_utilisation", lambda device=0: utilisation)
    monkeypatch.setattr(bench, "gpu_description", lambda device=0: dict(GPU))


def test_another_process_on_the_gpu_stops_the_benchmark(monkeypatch):
    import os

    other = {"pid": 4242, "name": "python", "memory": "9000 MiB"}
    _gpu(monkeypatch, [other, {"pid": os.getpid(), "name": "python", "memory": "1 MiB"}])
    with pytest.raises(LoupError) as caught:
        bench.check_gpu_is_free()
    assert "python (pid 4242, 9000 MiB)" in str(caught.value) and "--force" in str(caught.value)
    assert bench.check_gpu_is_free(force=True) == ([other], 0)       # the own process is not another one


def test_a_busy_gpu_without_a_listed_process_is_refused_too(monkeypatch):
    _gpu(monkeypatch, [], utilisation=87)                           # WSL lists no processes
    with pytest.raises(LoupError, match="87 %"):
        bench.check_gpu_is_free()
    assert bench.check_gpu_is_free(force=True) == ([], 87)
    _gpu(monkeypatch, [], utilisation=3)
    assert bench.check_gpu_is_free() == ([], 3)


def test_nvidia_smi_output_is_parsed(monkeypatch):
    def fake_run(cmd, **kw):
        if "--query-compute-apps=pid,process_name,used_memory" in cmd:
            return types.SimpleNamespace(returncode=0, stdout="4242, python, 9000 MiB\n77, /usr/bin/x, [N/A]\n", stderr="")
        if "--query-gpu=utilization.gpu" in cmd:
            return types.SimpleNamespace(returncode=0, stdout="41\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="NVIDIA GeForce RTX 5060 Ti, 12.0, 621.14\n", stderr="")

    monkeypatch.setattr(bench, "_nvidia_smi", lambda: "nvidia-smi")
    monkeypatch.setattr(bench.subprocess, "run", fake_run)
    monkeypatch.setattr(bench.time, "sleep", lambda s: None)
    assert bench.gpu_processes() == [{"pid": 4242, "name": "python", "memory": "9000 MiB"},
                                     {"pid": 77, "name": "/usr/bin/x", "memory": "[N/A]"}]
    assert bench.gpu_utilisation() == 41
    assert bench.gpu_description() == GPU
    monkeypatch.setattr(bench, "_nvidia_smi", lambda: None)
    assert bench.gpu_processes() == [] and bench.gpu_utilisation() is None
    assert bench.gpu_description() == {"name": None, "compute_capability": None, "driver": None}


# ------------------------------------------------------------------------------------------------ run_suite

@pytest.fixture
def checkpoint(tmp_path):
    path = tmp_path / "some.model"
    path.write_bytes(b"not a pickle anyone loads here")
    return path


def _run(monkeypatch, checkpoint, **more):
    FakeEngine.made = []
    exported = []

    def ensure_bundle(model_path, numbers, head=None, environ=None):
        exported.append((model_path.name, tuple(numbers), head))
        return model_path.with_name("bundle-" + "-".join(map(str, numbers)) + ".loup")

    record, rows = bench.run_suite(str(checkpoint), trusted=True, engine_factory=FakeEngine,
                                   ensure_bundle=ensure_bundle, environ={}, **more)
    return record, rows, exported


def test_run_suite_times_every_system_and_writes_a_valid_record(monkeypatch, checkpoint):
    _gpu(monkeypatch)
    record, rows, exported = _run(monkeypatch, checkpoint, suite="quick", device=1)
    assert protocol.validate_record(record) == []
    assert exported == [("some.model", (8, 22, 38), None)]
    assert [r.system for r in rows] == ["SrTiO3 6x6x6"] and rows[0].bundle == "bundle-8-22-38.loup"
    assert record["suite"] == "quick" and record["protocol"]["name"] == "quick" and record["device"] == 1
    assert record["model"]["file"] == "some.model" and record["model"]["label"] is None
    assert len(record["model"]["sha256"]) == 64 and record["gpu"] == GPU
    assert FakeEngine.made[0].device_id == 1
    assert [c[1] for c in FakeEngine.made[0].calls if c[0] == "run"] == [50, 128, 128]


def test_run_suite_refuses_an_untrusted_file_before_anything_else(monkeypatch, checkpoint):
    from loupmd.errors import CheckpointTrustError

    _gpu(monkeypatch)
    with pytest.raises(CheckpointTrustError):
        bench.run_suite(str(checkpoint), suite="quick", engine_factory=FakeEngine, environ={},
                        ensure_bundle=lambda *a, **k: pytest.fail("exported an untrusted file"))


def test_run_suite_records_what_was_on_the_gpu_when_forced(monkeypatch, checkpoint):
    other = {"pid": 4242, "name": "python", "memory": "9000 MiB"}
    _gpu(monkeypatch, [other], utilisation=64)
    with pytest.raises(LoupError, match="in use"):
        _run(monkeypatch, checkpoint, suite="quick")
    assert FakeEngine.made == []                                    # refused before any engine exists
    record, _, _ = _run(monkeypatch, checkpoint, suite="quick", force=True)
    assert record["other_gpu_processes"] == [other] and record["gpu_utilisation_percent"] == 64


def test_run_suite_with_another_protocol_and_chosen_systems(monkeypatch, checkpoint):
    _gpu(monkeypatch)
    record, rows, _ = _run(monkeypatch, checkpoint, suite="standard", protocol_name="fastmace",
                           systems=["SrTiO3 6x6x6"])
    assert [r.system for r in rows] == ["SrTiO3 6x6x6"] and record["protocol"]["name"] == "fastmace"
    assert [c[1] for c in FakeEngine.made[0].calls if c[0] == "run"] == [300, 300, 300, 300, 300]
    with pytest.raises(InputError, match="unknown protocol 'slow'"):
        _run(monkeypatch, checkpoint, suite="quick", protocol_name="slow")


def test_a_comparison_is_recorded_with_its_ratio_and_a_failed_one_with_its_error(monkeypatch, checkpoint):
    from loupmd.bench import compare

    _gpu(monkeypatch)
    seen = []

    def time_mace(model_path, name, atoms, proto, head=None, device=0):
        seen.append((model_path.name, name, len(atoms), device))
        return {"engine": "mace-torch", "version": "0.3.15", "ms_per_step": 105.0, "blocks_ms": [100.0, 105.0, 110.0],
                "final_temperature_K": 299.0}

    monkeypatch.setitem(compare.ENGINES, "mace", time_mace)
    record, rows, _ = _run(monkeypatch, checkpoint, suite="quick", compare_with=("mace",))
    assert seen == [("some.model", "SrTiO3 6x6x6", 1080, 0)]
    entry, = record["comparisons"]
    assert entry["engine"] == "mace-torch" and entry["system"] == "SrTiO3 6x6x6" and entry["blocks"] == 3
    assert entry["ratio_to_loupmd"] == pytest.approx(105.0 / rows[0].ms_per_step)
    assert "105.00 ms/step" in compare.format_comparisons(record["comparisons"])

    def out_of_memory(*a, **k):
        raise RuntimeError("CUDA out of memory")

    monkeypatch.setitem(compare.ENGINES, "mace", out_of_memory)
    record, rows, _ = _run(monkeypatch, checkpoint, suite="quick", compare_with=("mace",))
    assert record["comparisons"][0]["ms_per_step"] is None and len(rows) == 1
    assert "RuntimeError: CUDA out of memory" in record["comparisons"][0]["error"]
    assert "failed (RuntimeError: CUDA out of memory)" in compare.format_comparisons(record["comparisons"])
    with pytest.raises(InputError, match="unknown comparison 'lammps'"):
        _run(monkeypatch, checkpoint, suite="quick", compare_with=("lammps",))


# ---------------------------------------------------------------------------------------------- reference

def test_the_reference_table_is_keyed_by_gpu_model_system_and_protocol(tmp_path):
    table = tmp_path / "reference.json"
    table.write_text(json.dumps({"schema": "loupmd.bench-reference/1", "entries": [
        {"gpu": GPU["name"], "model_sha256": MODEL["sha256"], "system": "SrTiO3 6x6x6", "protocol": "quick",
         "ms_per_step": 2.0, "library": "0.1.0a1+0123456789abcdef", "measured": "2026-11-15"}]}))
    record = protocol.make_record([_row(), _row(name="NaCl 3x3x3", atoms=216)], protocol.PROTOCOLS["quick"], "quick",
                                  GPU, MODEL, "lib", "0.1.0a1")
    found = reference.lookup(record, table)
    assert set(found) == {"SrTiO3 6x6x6"} and found["SrTiO3 6x6x6"]["ms_per_step"] == 2.0
    other = dict(record, gpu=dict(GPU, name="NVIDIA A100-SXM4-40GB"))
    assert reference.lookup(other, table) == {}
    assert reference.lookup(dict(record, protocol=dict(record["protocol"], name="standard")), table) == {}


def test_the_shipped_reference_table_is_well_formed():
    table = json.loads(reference.SHIPPED.read_text())
    assert table["schema"] == "loupmd.bench-reference/1"
    for entry in table["entries"]:
        assert set(entry) >= {"gpu", "model_sha256", "system", "protocol", "ms_per_step", "library", "measured"}
        assert entry["system"] in suites.SYSTEMS and entry["protocol"] in protocol.PROTOCOLS
        assert len(entry["model_sha256"]) == 64 and entry["ms_per_step"] > 0.0


# ------------------------------------------------------------------------------------------------------ A/B

def test_ab_runs_the_sides_in_fresh_processes_in_the_order_a_b_b_a(monkeypatch, tmp_path):
    seen = []

    def fake_run(cmd, env=None, **kw):
        target = cmd[cmd.index("--json") + 1]
        seen.append((env.get("LOUP_LIB"), env.get("LOUP_NO_HYBRID"), cmd[:4], cmd[4:-2]))
        ms = 2.0 if env.get("LOUP_LIB") == "/a.so" else 1.9
        record = protocol.make_record([_row(blocks=(ms, ms))], protocol.PROTOCOLS["quick"], "quick", GPU, MODEL, "lib",
                                      "0.1.0a1")
        with open(target, "w") as out:
            json.dump(record, out)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(bench.subprocess, "run", fake_run)
    result = bench.run_ab(["LOUP_LIB=/a.so", "LOUP_LIB=/b.so,LOUP_NO_HYBRID=1"], ["--model", "m", "--suite", "quick"],
                          environ={"PATH": "/bin"})
    assert [s[0] for s in seen] == ["/a.so", "/b.so", "/b.so", "/a.so"]
    assert [s[1] for s in seen] == [None, "1", "1", None]
    assert seen[0][2][1:] == ["-m", "loupmd", "bench"] and seen[0][3] == ["--model", "m", "--suite", "quick"]
    assert result["schema"] == "loupmd.bench-ab/1" and result["order"] == [s for s in (
        "LOUP_LIB=/a.so", "LOUP_LIB=/b.so,LOUP_NO_HYBRID=1", "LOUP_LIB=/b.so,LOUP_NO_HYBRID=1", "LOUP_LIB=/a.so")]
    assert result["mean_ms"]["LOUP_LIB=/a.so"] == {"SrTiO3 6x6x6": pytest.approx(2.0)}
    assert result["ratio"]["LOUP_LIB=/b.so,LOUP_NO_HYBRID=1"] == {"SrTiO3 6x6x6": pytest.approx(0.95)}
    assert len(result["runs"]) == 4 and all(protocol.validate_record(r["record"]) == [] for r in result["runs"])
    text = bench.format_ab(result)
    assert "MEAN" in text and "0.9500" in text and text.count("SrTiO3 6x6x6") >= 4


def test_ab_refuses_a_malformed_side_and_reports_a_failed_one(monkeypatch):
    with pytest.raises(InputError, match="ENV=VAL"):
        bench.run_ab(["LOUP_LIB"], [], environ={})
    monkeypatch.setattr(bench.subprocess, "run",
                        lambda cmd, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr="error: the GPU is in use"))
    with pytest.raises(LoupError) as caught:
        bench.run_ab(["-"], [], environ={})
    assert "side '-' failed" in str(caught.value) and "the GPU is in use" in str(caught.value)


# -------------------------------------------------------------------------------------------------- command

@pytest.fixture
def fake_suite(monkeypatch):
    calls = []

    def run_suite(model, **kw):
        calls.append((model, kw))
        rows = [_row()]
        return protocol.make_record(rows, protocol.PROTOCOLS["quick"], kw["suite"], GPU, MODEL, "lib", "0.1.0a1"), rows

    monkeypatch.setattr(bench, "run_suite", run_suite)
    monkeypatch.setattr(reference, "lookup", lambda record, table=None: {})
    return calls


def test_the_command_prints_the_table_and_writes_the_record(fake_suite, tmp_path, capsys):
    target = tmp_path / "bench.json"
    assert main(["bench", "--model", "omat0-medium", "--suite", "quick", "--json", str(target)]) == 0
    out = capsys.readouterr().out
    assert "NVIDIA GeForce RTX 5060 Ti" in out and "SrTiO3 6x6x6" in out and "ms/step" in out
    assert protocol.validate_record(json.loads(target.read_text())) == []
    model, kw = fake_suite[0]
    assert model == "omat0-medium" and kw["suite"] == "quick" and kw["force"] is False and kw["protocol_name"] is None


def test_quick_is_a_short_form_and_the_options_reach_run_suite(fake_suite, capsys):
    assert main(["bench", "--model", "/x/y.model", "--quick", "--trusted", "--force", "--device", "1", "--head", "h",
                 "--protocol", "fastmace", "--system", "SrTiO3 6x6x6"]) == 0
    _, kw = fake_suite[0]
    assert kw["suite"] == "quick" and kw["trusted"] is True and kw["force"] is True and kw["device"] == 1
    assert kw["head"] == "h" and kw["protocol_name"] == "fastmace" and kw["systems"] == ["SrTiO3 6x6x6"]


def test_the_command_reports_a_refusal_without_a_traceback(monkeypatch, capsys):
    def run_suite(model, **kw):
        raise LoupError("the GPU is in use by 1 other process(es): python (pid 4242, 9000 MiB)",
                        next_step="Wait for them to finish, or pass --force.")

    monkeypatch.setattr(bench, "run_suite", run_suite)
    assert main(["bench", "--model", "omat0-medium"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: the GPU is in use") and "Next: Wait" in err and "Traceback" not in err


def test_an_unstable_row_makes_the_command_fail(monkeypatch, capsys):
    def run_suite(model, **kw):
        rows = [_row(temperature=float("inf"))]
        return protocol.make_record(rows, protocol.PROTOCOLS["quick"], "quick", GPU, MODEL, "lib", "0.1.0a1"), rows

    monkeypatch.setattr(bench, "run_suite", run_suite)
    monkeypatch.setattr(reference, "lookup", lambda record, table=None: {})
    assert main(["bench", "--model", "omat0-medium", "--quick"]) == 1
    captured = capsys.readouterr()
    assert "UNSTABLE" in captured.out and "not a valid timing" in captured.err


def test_usage_errors(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["bench", "--model", "omat0-medium", "--suite", "nope"])
    assert caught.value.code == 2
    with pytest.raises(SystemExit) as caught:
        main(["bench"])                                               # a model is required
    assert caught.value.code == 2


def test_the_ab_form_of_the_command(monkeypatch, tmp_path, capsys):
    seen = {}

    def run_ab(sides, argv, environ=None):
        seen.update(sides=sides, argv=argv)
        return {"schema": "loupmd.bench-ab/1", "order": sides + sides[::-1], "runs": [],
                "mean_ms": {s: {"SrTiO3 6x6x6": 2.0} for s in sides}, "ratio": {s: {"SrTiO3 6x6x6": 1.0} for s in sides}}

    monkeypatch.setattr(bench, "run_ab", run_ab)
    target = tmp_path / "ab.json"
    assert main(["bench", "--model", "omat0-medium", "--quick", "--force", "--ab", "-", "LOUP_NO_HYBRID=1", "--json",
                 str(target)]) == 0
    assert seen["sides"] == ["-", "LOUP_NO_HYBRID=1"]
    assert seen["argv"] == ["--model", "omat0-medium", "--suite", "quick", "--force"]
    assert json.loads(target.read_text())["schema"] == "loupmd.bench-ab/1"
    assert "MEAN" in capsys.readouterr().out
