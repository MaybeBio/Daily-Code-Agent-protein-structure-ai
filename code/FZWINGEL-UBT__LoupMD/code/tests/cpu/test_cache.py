"""The cache layout, the bundle cache's lock and the ``loupmd cache`` commands (plan task S2-T05). Needs neither
the library nor a GPU: the exporter is a stand-in script."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from loupmd import bundles, cache
from loupmd.errors import InputError, LoupError

ROOT = Path(__file__).resolve().parents[2]

# Stands in for loupmd.export: takes the same arguments, counts its runs, takes a while, writes the bundle.
EXPORTER = r"""
import os, sys, time
args = sys.argv[1:]
out = args[args.index("--output") + 1]
with open(os.environ["COUNT_FILE"], "a") as f:
    f.write(" ".join(args) + "\n")
time.sleep(float(os.environ.get("EXPORT_SECONDS", "0")))
if os.environ.get("EXPORT_FAILS"):
    sys.exit(os.environ.get("EXPORT_MESSAGE", "the model has an unsupported layer"))
with open(out, "wb") as f:
    f.write(b"bundle for " + " ".join(args).encode())
"""


@pytest.fixture
def stage(tmp_path, monkeypatch):
    exporter = tmp_path / "fake_export.py"
    exporter.write_text(EXPORTER)
    model = tmp_path / "tiny.model"
    model.write_bytes(b"model bytes")
    monkeypatch.setenv("COUNT_FILE", str(tmp_path / "count.txt"))
    monkeypatch.setenv("LOUPMD_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv("LOUP_CACHE_DIR", raising=False)
    monkeypatch.delenv("LOUP_GENERIC", raising=False)
    return tmp_path, model, [sys.executable, str(exporter)]


def _runs(tmp_path):
    count = tmp_path / "count.txt"
    return count.read_text().splitlines() if count.exists() else []


def test_a_bundle_is_exported_once_and_found_again(stage):
    tmp_path, model, exporter = stage
    first = bundles.ensure_bundle(model, [38, 8, 22, 8], exporter=exporter)
    assert first.parent == tmp_path / "cache" / "bundles"
    assert first.name == bundles.bundle_name(model, [8, 22, 38]) and first.name.startswith("tiny_8_22_38_")
    assert bundles.ensure_bundle(model, [8, 22, 38], exporter=exporter) == first
    assert len(_runs(tmp_path)) == 1 and "--elements 8,22,38" in _runs(tmp_path)[0]
    assert not list(first.parent.glob("*.part*"))
    # everything that decides the contents is in the key
    others = {
        bundles.ensure_bundle(model, [8, 22], exporter=exporter),
        bundles.ensure_bundle(model, [8, 22, 38], head="omat_pbe", exporter=exporter),
        bundles.ensure_bundle(model, [8, 22, 38], charge=1, spin_multiplicity=2, exporter=exporter),
    }
    assert len(others | {first}) == 4 and len(_runs(tmp_path)) == 4
    assert "--head omat_pbe" in _runs(tmp_path)[2]
    assert "--charge 1 --spin-multiplicity 2" in _runs(tmp_path)[3]
    # `generic` is accepted and ignored (the kernels specialised to MACE-OMAT-0 medium were retired): the same
    # bundle, and no export
    for generic in (True, False):
        assert bundles.ensure_bundle(model, [8, 22, 38], generic=generic, exporter=exporter) == first
    assert len(_runs(tmp_path)) == 4 and not any("--generic" in run for run in _runs(tmp_path))
    assert bundles.ensure_bundle(model, [8, 22, 38], charge=1.0, spin_multiplicity=2, exporter=exporter) in others
    with pytest.raises(InputError, match="charge must be an integer, got 0.5"):
        bundles.ensure_bundle(model, [8, 22, 38], charge=0.5, exporter=exporter)
    with pytest.raises(InputError, match="not found"):
        bundles.ensure_bundle(tmp_path / "missing.model", [8], exporter=exporter)


def test_two_processes_asking_for_the_same_bundle_export_it_once(stage):
    tmp_path, model, exporter = stage
    child = ("import sys; sys.path.insert(0, sys.argv[1])\n"
             "from loupmd import bundles\n"
             "print(bundles.ensure_bundle(sys.argv[2], [8, 22, 38], exporter=[sys.executable, sys.argv[3]]))\n")
    env = dict(os.environ, EXPORT_SECONDS="1.0")
    procs = [subprocess.Popen([sys.executable, "-c", child, str(ROOT), str(model), exporter[1]], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(3)]
    outs = [p.communicate(timeout=120) for p in procs]
    assert all(p.returncode == 0 for p in procs), [o[1][-500:] for o in outs]
    paths = {o[0].strip() for o in outs}
    assert len(paths) == 1 and Path(paths.pop()).read_bytes().startswith(b"bundle for")
    assert len(_runs(tmp_path)) == 1


def test_a_failed_export_leaves_nothing_behind_and_says_why(stage, monkeypatch):
    tmp_path, model, exporter = stage
    monkeypatch.setenv("EXPORT_FAILS", "1")
    with pytest.raises(LoupError, match="the export of tiny.model for elements") as info:
        bundles.ensure_bundle(model, [8], exporter=exporter)
    assert "the model has an unsupported layer" in str(info.value) and "Run the command by hand" in str(info.value)
    assert not [p for p in (tmp_path / "cache" / "bundles").iterdir() if not p.name.endswith(".lock")]
    monkeypatch.delenv("EXPORT_FAILS")
    assert bundles.ensure_bundle(model, [8], exporter=exporter).is_file()   # the next try is not blocked


def test_a_polar_export_without_graph_longrange_says_what_to_install(stage, monkeypatch):
    """An environment made for 0.0.1's export extra has no graph_longrange: MACE cannot load a POLAR-1 checkpoint."""
    tmp_path, model, exporter = stage
    monkeypatch.setenv("EXPORT_FAILS", "1")
    monkeypatch.setenv("EXPORT_MESSAGE", "ModuleNotFoundError: No module named 'graph_longrange'")
    with pytest.raises(LoupError, match="the export of tiny.model needs the graph_longrange package") as info:
        bundles.ensure_bundle(model, [8], exporter=exporter)
    assert "pip install 'loupmd[export]'" in str(info.value) and "POLAR-1" in str(info.value)
    assert not [p for p in (tmp_path / "cache" / "bundles").iterdir() if not p.name.endswith(".lock")]


def test_a_miss_without_the_export_extra_names_the_extra(stage, monkeypatch):
    """A wheel installed without the export extra: a miss says what to install, not the exporter's traceback."""
    tmp_path, model, exporter = stage
    monkeypatch.setattr(bundles, "missing_export_modules", lambda: ["torch", "mace"])
    with pytest.raises(LoupError, match="cannot export one") as info:
        bundles.ensure_bundle(model, [8])
    text = str(info.value)
    assert "missing: torch, mace" in text and "pip install 'loupmd[export]'" in text
    assert bundles.bundle_name(model, [8]) in text                          # where a bundle from elsewhere goes
    assert not _runs(tmp_path)                                              # no export process was started
    assert not [p for p in (tmp_path / "cache" / "bundles").iterdir() if not p.name.endswith(".lock")]
    assert bundles.ensure_bundle(model, [8], exporter=exporter).is_file()   # a given exporter is not second-guessed
    assert bundles.ensure_bundle(model, [8]).is_file()                      # and a cached bundle needs no extra


def test_the_bundle_key_is_made_of_files_of_the_package_alone():
    """A wheel has no ``src`` beside the package: everything in the bundle key lies inside the package, so a
    checkout and a wheel of one commit share their bundles. The product-kernel emitter is part of the key (a
    bundle carries its products' source)."""
    package = ROOT / "loupmd"
    assert all(source.is_file() and package in source.parents for source in bundles.EXPORTER_SOURCES)
    assert "gen_product.py" in {source.name for source in bundles.EXPORTER_SOURCES}


def test_bundles_of_the_old_layout_are_found(stage):
    tmp_path, model, exporter = stage
    old = tmp_path / "cache" / bundles.bundle_name(model, [8, 22, 38])
    old.parent.mkdir(parents=True)
    old.write_bytes(b"written by ensure_loup_bundle")
    assert bundles.ensure_bundle(model, [8, 22, 38], exporter=exporter) == old
    assert _runs(tmp_path) == []


def _file(path, size, age_days, now):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (now - age_days * 86400.0, now - age_days * 86400.0))
    return path


@pytest.fixture
def filled(tmp_path, monkeypatch):
    monkeypatch.setenv("LOUPMD_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv("LOUP_CACHE_DIR", raising=False)
    monkeypatch.setattr(cache, "_IN_USE", set())
    root, now = tmp_path / "cache", time.time()
    files = {
        "old_bundle": _file(root / "bundles" / "a_8_1111.loup", 4000, 40, now),
        "mid_bundle": _file(root / "bundles" / "b_8_2222.loup", 3000, 10, now),
        "new_bundle": _file(root / "bundles" / "c_8_3333.loup", 2000, 1, now),
        "root_bundle": _file(root / "d_8_4444.loup", 1000, 20, now),           # the old layout
        "plan": _file(root / "plans_gpu_sm120_lt1_hyb1_abcd.bin", 500, 30, now),
        "ref": _file(root / "gate_refs" / "ref.npz", 700, 5, now),
        "model": _file(root / "models" / "m.model", 9000, 400, now),
        "lock": _file(root / "bundles" / "c_8_3333.loup.lock", 0, 400, now),
    }
    return root, now, files


def test_listing_and_sizes_cover_both_layouts(filled):
    root, now, files = filled
    kinds = {e.path.name: e.kind for e in cache.entries()}
    assert kinds == {"a_8_1111.loup": "bundles", "b_8_2222.loup": "bundles", "c_8_3333.loup": "bundles",
                     "d_8_4444.loup": "bundles", "plans_gpu_sm120_lt1_hyb1_abcd.bin": "plans", "ref.npz": "gate_refs",
                     "m.model": "models"}
    assert [e.path.name for e in cache.entries(["bundles"])] == ["a_8_1111.loup", "d_8_4444.loup", "b_8_2222.loup",
                                                                 "c_8_3333.loup"]   # oldest use first
    assert cache.sizes() == {"models": 9000, "bundles": 10000, "plans": 500, "gate_refs": 700, "lib": 0, "total": 20200}


def test_prune_by_age_spares_models_and_what_is_in_use(filled):
    root, now, files = filled
    would = cache.prune(older_than_days=15, dry_run=True)
    assert {e.path for e in would} == {files["old_bundle"], files["root_bundle"], files["plan"]}
    assert all(p.exists() for p in files.values())
    cache.mark_in_use(files["old_bundle"])
    removed = cache.prune(older_than_days=15, keep=[files["plan"]])
    assert {e.path for e in removed} == {files["root_bundle"]}
    assert files["old_bundle"].exists() and files["plan"].exists() and files["model"].exists()
    assert {e.path for e in cache.prune(older_than_days=15, kinds=("models",))} == {files["model"]}


def test_prune_to_a_size_removes_the_least_recently_used(filled):
    root, now, files = filled
    removed = cache.prune(max_size=6500)   # bundles, plans and references hold 11,200 bytes
    assert [e.path for e in removed] == [files["old_bundle"], files["plan"], files["root_bundle"]]
    left = sum(e.size for e in cache.entries(cache.PRUNABLE))
    assert left == 5700 and left <= 6500
    assert files["model"].exists()
    with pytest.raises(InputError, match="prune needs a rule"):
        cache.prune()


def test_prune_leaves_a_file_another_process_holds(filled):
    root, now, files = filled
    holder = subprocess.Popen([sys.executable, "-c",
                               "import sys, time; sys.path.insert(0, sys.argv[1])\n"
                               "from loupmd import cache\n"
                               "with cache.locked(sys.argv[2]):\n"
                               "    print('held', flush=True); time.sleep(30)\n", str(ROOT), str(files["old_bundle"])],
                              stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        removed = cache.prune(max_size=0)
        assert files["old_bundle"].exists() and files["old_bundle"] not in {e.path for e in removed}
        assert not files["mid_bundle"].exists()
    finally:
        holder.kill()
        holder.wait()


def test_parse_size():
    assert cache.parse_size("1G") == 1024 ** 3 and cache.parse_size("500M") == 500 * 1024 ** 2
    assert cache.parse_size("2.5GiB") == int(2.5 * 1024 ** 3) and cache.parse_size("4096") == 4096
    with pytest.raises(InputError, match="is not a size"):
        cache.parse_size("lots")


def _cli(*args, env):
    return subprocess.run([sys.executable, "-m", "loupmd", *args], cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, **env})


def test_cli_cache_commands(filled):
    root, now, files = filled
    env = {"LOUPMD_CACHE": str(root)}
    listing = _cli("cache", "list", env=env)
    assert listing.returncode == 0 and "7 files" in listing.stdout and "a_8_1111.loup" in listing.stdout
    size = _cli("cache", "size", env=env)
    assert size.returncode == 0 and "bundles" in size.stdout and "total" in size.stdout
    dry = _cli("cache", "prune", "--max-size", "6500", "--dry-run", env=env)
    assert dry.returncode == 0 and "would remove 3 files" in dry.stdout and files["old_bundle"].exists()
    done = _cli("cache", "prune", "--max-size", "6500", env=env)
    assert done.returncode == 0 and "removed 3 files" in done.stdout and not files["old_bundle"].exists()
    assert _cli("cache", "prune", env=env).returncode == 1          # no rule: a LoupMD error
    assert _cli("cache", env=env).returncode == 2                   # no action: usage
    assert _cli("cache", "prune", "--max-size", "lots", env=env).returncode == 1


def test_engine_plan_files_follow_loupmd_cache(tmp_path, monkeypatch):
    # src/engine.cu reads only LOUP_CACHE_DIR for its GEMM plan files; the package points it at $LOUPMD_CACHE.
    monkeypatch.setattr(cache, "_plan_dir_set", None)
    env = {"LOUPMD_CACHE": str(tmp_path / "a")}
    assert cache.engine_plan_environment(env) == str((tmp_path / "a").resolve())
    env["LOUPMD_CACHE"] = str(tmp_path / "b")                 # a changed root is followed
    assert cache.engine_plan_environment(env) == str((tmp_path / "b").resolve())
    del env["LOUPMD_CACHE"]                                   # and dropped again: the engine's default
    assert cache.engine_plan_environment(env) is None and "LOUP_CACHE_DIR" not in env


def test_engine_plan_files_keep_the_callers_loup_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_plan_dir_set", None)
    env = {"LOUPMD_CACHE": str(tmp_path / "a"), "LOUP_CACHE_DIR": str(tmp_path / "plans")}
    assert cache.engine_plan_environment(env) == str(tmp_path / "plans")
    assert cache.engine_plan_environment({}) is None
