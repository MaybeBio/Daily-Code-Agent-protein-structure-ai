"""``lm.md`` on the GPU (plan tasks S3-T07, S3-T09, S3-T10): a real run with its report and metadata, the gate
inside a run, and a corrupted bundle that the gate must stop. Skips when the model file is absent."""
from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
from ase.io import write
from gpu_support import srtio3

import loupmd
from loupmd import bundles, ensure_loup_bundle, output, provenance
from loupmd.errors import GateFailed


def test_md_runs_reports_and_records(model_path, tmp_path):
    write(tmp_path / "sto.cif", srtio3(1))
    result = loupmd.md(str(tmp_path / "sto.cif"), model=model_path, trusted=True, temperature_K=300, steps=200,
                       timestep_fs=1.0, repeat=(4, 4, 4), output=str(tmp_path / "run"), seed=5,
                       initial_velocities="maxwell_boltzmann")
    metadata = json.loads((tmp_path / "run" / "metadata.json").read_text())
    assert provenance.validate(metadata) == [] and metadata["step"] == 200 and metadata["status"] == "idle"
    assert metadata["plan"]["kernels"] == "generic" and metadata["plan"]["interaction_layers"] == 2
    assert metadata["plan"]["memory"]["whole_bytes"] > 0
    assert metadata["plan"]["library"].startswith(loupmd.__version__ + "+")
    assert metadata["gpu"]["name"] and metadata["gpu"]["driver"]
    assert metadata["structure"]["atoms"] == 320 and metadata["bundle"].endswith(".loup")
    assert metadata["counters"]["dangerous_builds"] == 0 and metadata["timing"]["ms_per_step"] > 0
    rows = output.read_thermo(tmp_path / "run")[1]
    assert [int(r[0]) for r in rows] == list(range(0, 201, 20)) and len(output.read_frames(tmp_path / "run")) == 11
    assert 100.0 < float(rows[-1][4]) < 400.0                         # a thermostat at 300 K, 320 atoms
    print(result.summary)
    for line in ("generic kernels, 2 interaction layers, cutoff 6 A", "memory:", "ms/step with output",
                 "Academic Software License", "sto.cif x (4, 4, 4): 320 atoms (O 192, Sr 64, Ti 64)"):
        assert line in result.summary, line
    result.simulation.close()
    resumed = loupmd.Simulation.resume(tmp_path / "run")
    assert resumed.step == 200
    resumed.run(steps=20)
    resumed.close()


def test_the_gate_inside_a_run_passes_on_a_good_bundle(model_path, tmp_path):
    at = srtio3(3)
    result = loupmd.md(at, model=model_path, trusted=True, temperature_K=300, steps=40, timestep_fs=1.0,
                       output=str(tmp_path / "run"), seed=5, initial_velocities="maxwell_boltzmann", check="gate")
    gate = result.gate
    assert gate["status"] == "passed" and gate["passed"] is True
    assert {row["config"] for row in gate["rows"]} == {"structure0_r0", "structure0_r1"}
    assert gate["worst"]["force_ratio"] < 3.0 and gate["worst"]["stress_ratio"] < 3.0
    print("gate inside the run: worst ratios", {k: round(v, 2) for k, v in gate["worst"].items()})
    assert "passed: worst ratios" in result.summary and result.simulation.step == 40
    result.simulation.close()


def test_a_corrupted_bundle_fails_the_gate_and_the_run_does_not_start(model_path, tmp_path, monkeypatch):
    """S3-T10: one weight table of the bundle scaled by 2%: the engine loads it, the gate does not pass it."""
    from loupmd.export.bundle import read_bundle, write_bundle

    good = ensure_loup_bundle(model_path, [8, 22, 38])
    cache = tmp_path / "cache"
    monkeypatch.setenv("LOUPMD_CACHE", str(cache))
    monkeypatch.delenv("LOUP_CACHE_DIR", raising=False)
    target = cache / "bundles" / bundles.bundle_name(model_path, [8, 22, 38])
    target.parent.mkdir(parents=True)
    meta, arrays = read_bundle(good)
    name = max((n for n, a in arrays.items() if a.dtype == np.float32), key=lambda n: arrays[n].size)
    arrays[name] = (arrays[name] * 1.02).astype(np.float32)
    write_bundle(target, meta, arrays)
    assert target.stat().st_size == shutil.os.path.getsize(good)
    with pytest.raises(GateFailed) as caught:
        loupmd.md(srtio3(3), model=model_path, trusted=True, temperature_K=300, steps=40, timestep_fs=1.0,
                  output=str(tmp_path / "run"), seed=5, initial_velocities="maxwell_boltzmann", check="gate")
    record = caught.value.gate_record
    print(f"corrupted table {name}: worst ratios", {k: round(v, 1) for k, v in record["worst"].items()})
    assert record["passed"] is False and max(record["worst"].values()) > 3.0
    assert output.read_thermo(tmp_path / "run")[1] == []              # no step ran, no row was written
