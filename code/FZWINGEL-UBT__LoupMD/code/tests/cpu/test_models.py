"""The model label table, the lookup order and the checkpoint trust rule (plan task S2-T04). Needs neither the
library nor a GPU; downloads come from a server on this machine."""
from __future__ import annotations

import functools
import hashlib
import http.server
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import loupmd
from loupmd import models
from loupmd.errors import CacheLocationError, CheckpointTrustError, InputError

ROOT = Path(__file__).resolve().parents[2]


def test_the_table_is_complete_and_well_formed():
    assert len(models.LABELS) == 20   # the 19 of FastMACE's benchmark suite and omat0-small
    assert len(models.CHECKPOINTS) == 18
    for entry in models.LABELS.values():
        ckpt = entry.checkpoint
        assert re.fullmatch(r"[0-9a-f]{64}", ckpt.sha256), entry.label
        assert ckpt.url.startswith("https://") and ckpt.file_name.endswith(".model")
        assert ckpt.licence in models.LICENCE_TEXT and ckpt.family in models.FAMILIES
        assert ckpt.model_type in ("MACE", "PolarMACE")
        source = entry.functional_source
        assert source and (entry.functional is not None or source.startswith("unknown:")), entry.label
    assert len({c.sha256 for c in models.CHECKPOINTS.values()}) == len(models.CHECKPOINTS)
    assert len({c.file_name for c in models.CHECKPOINTS.values()}) == len(models.CHECKPOINTS)


def test_find_labels_aliases_and_heads():
    assert models.find("omat0-medium").checkpoint.file_name == "mace-omat-0-medium.model"
    assert models.find("mh1-r2scan").head == "matpes_r2scan" and models.find("mh1-r2scan").functional == "r2scan"
    assert models.find("mh1", head="matpes_r2scan") is models.LABELS["mh1-r2scan"]
    spice = models.find("mh1", head="spice_wB97M")           # a head without its own label
    assert spice.label == "mh-1:spice_wB97M" and spice.functional == "wb97m-d3bj"
    assert models.find("mh-1:spice_wB97M").head == "spice_wB97M"
    assert models.find("polar1-s").functional is None and models.find("polar1-s").model_type == "PolarMACE"
    assert models.find("not-a-model") is None
    with pytest.raises(InputError, match="has several heads and no default") as info:
        models.find("mh1")
    assert "matpes_r2scan, mp_pbe_refit_add, spice_wB97M, oc20_usemppbe, omol, omat_pbe" in str(info.value)
    with pytest.raises(InputError, match="has no head 'nope'"):
        models.find("mh1", head="nope")
    with pytest.raises(InputError, match="label 'mh1-omat' is head 'omat_pbe'"):
        models.find("mh1-omat", head="omol")


def _fake(directory, label, content=b"not a real checkpoint"):
    path = Path(directory) / models.LABELS[label].checkpoint.file_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_lookup_order_explicit_then_models_folder_then_cache_then_download(tmp_path):
    env = {"LOUPMD_CACHE": str(tmp_path / "cache"), "LOUPMD_MODELS": str(tmp_path / "store")}
    with pytest.raises(InputError, match="checkpoint mace-omat-0-small.model not found") as info:
        models.resolve_checkpoint("omat0-small", environ=env)
    assert str(tmp_path / "store") in str(info.value) and "download=True" in str(info.value)
    in_cache = _fake(tmp_path / "cache" / "models", "omat0-small")
    assert models.resolve_checkpoint("omat0-small", environ=env).origin == "cache"
    in_store = _fake(tmp_path / "store", "omat0-small")
    found = models.resolve_checkpoint("omat0-small", environ=env)
    assert (found.origin, found.path) == ("LOUPMD_MODELS", in_store.resolve())
    explicit = tmp_path / "mine.model"
    explicit.write_bytes(b"x")
    found = models.resolve_checkpoint("omat0-small", checkpoint=explicit, environ=env)
    assert (found.origin, found.path, found.label.label) == ("explicit", explicit.resolve(), "omat0-small")
    assert in_cache.exists()
    with pytest.raises(InputError, match="is neither a model label nor an existing checkpoint file"):
        models.resolve_checkpoint("no-such-label-or-file", environ=env)


def test_trust_rule(tmp_path):
    env = {"LOUPMD_CACHE": str(tmp_path / "cache")}
    path = tmp_path / "custom.model"
    path.write_bytes(b"some bytes")
    digest = hashlib.sha256(b"some bytes").hexdigest()
    with pytest.raises(CheckpointTrustError, match="is not a model of the label table and was not unpickled") as info:
        models.trusted_checkpoint(str(path), environ=env)
    assert f"sha256='{digest}'" in str(info.value)             # the way out names the hash to check
    assert models.trusted_checkpoint(str(path), sha256=digest.upper(), environ=env)[2] == "sha256"
    assert models.trusted_checkpoint(str(path), trusted=True, environ=env)[2] == "trusted"
    with pytest.raises(CheckpointTrustError, match="not the expected"):
        models.trusted_checkpoint(str(path), sha256="0" * 64, environ=env)
    with pytest.raises(CheckpointTrustError, match="not the expected"):   # a wrong hash is not rescued by trusted
        models.trusted_checkpoint(str(path), sha256="0" * 64, trusted=True, environ=env)
    # A label's file must be the release: another file under its name is refused unless trusted.
    with pytest.raises(CheckpointTrustError, match="but label 'omat0-small' is the release with SHA-256"):
        models.trusted_checkpoint("omat0-small", checkpoint=path, environ=env)
    assert models.trusted_checkpoint("omat0-small", checkpoint=path, trusted=True, environ=env)[2] == "trusted"
    with pytest.raises(CheckpointTrustError, match="is a URL without a hash"):
        models.trusted_checkpoint("https://example.invalid/some.model", environ=env)


@pytest.fixture
def server(tmp_path):
    """Serves tmp_path / "www" on 127.0.0.1."""
    www = tmp_path / "www"
    www.mkdir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(www))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield www, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_download_checks_the_hash_before_the_file_is_kept(tmp_path, server):
    www, base = server
    (www / "good.model").write_bytes(b"released bytes")
    good = hashlib.sha256(b"released bytes").hexdigest()
    env = {"LOUPMD_CACHE": str(tmp_path / "cache")}
    cache_models = tmp_path / "cache" / "models"

    with pytest.raises(InputError, match="checkpoint good.model not found"):   # no download unless asked
        models.trusted_checkpoint(f"{base}/good.model", sha256=good, environ=env)
    with pytest.raises(CheckpointTrustError, match="has SHA-256 .* not the expected") as info:
        models.trusted_checkpoint(f"{base}/good.model", sha256="1" * 64, download=True, environ=env)
    assert "deleted without being unpickled" in str(info.value)
    assert not any(cache_models.iterdir())                                      # nothing kept, no partial file

    resolved, digest, trust = models.trusted_checkpoint(f"{base}/good.model", sha256=good, download=True, environ=env)
    assert (resolved.origin, digest, trust) == ("download", good, "sha256")
    assert resolved.path == (cache_models / "good.model").resolve() and resolved.path.read_bytes() == b"released bytes"
    again = models.trusted_checkpoint(f"{base}/good.model", sha256=good, environ=env)   # now from the cache
    assert again[0].origin == "cache"


def test_a_labels_download_must_match_the_tables_hash(tmp_path, server, monkeypatch):
    www, base = server
    entry = models.LABELS["omat0-small"]
    (www / entry.checkpoint.file_name).write_bytes(b"an impostor")
    fake = models.Checkpoint(**{**entry.checkpoint.__dict__, "url": f"{base}/{entry.checkpoint.file_name}"})
    monkeypatch.setattr(models, "LABELS", {**models.LABELS, "omat0-small": models.ModelLabel(
        "omat0-small", fake, entry.head, entry.functional)})
    env = {"LOUPMD_CACHE": str(tmp_path / "cache")}
    with pytest.raises(CheckpointTrustError, match=f"not the expected {entry.checkpoint.sha256}"):
        models.resolve_checkpoint("omat0-small", download=True, environ=env)
    assert not any((tmp_path / "cache" / "models").iterdir())


def test_cache_root_rules(tmp_path):
    from loupmd import cache

    assert cache.cache_root({"LOUPMD_CACHE": str(tmp_path / "a")}) == (tmp_path / "a").resolve()
    assert cache.cache_root({"LOUP_CACHE_DIR": str(tmp_path / "b")}) == (tmp_path / "b").resolve()
    assert cache.cache_root({"LOUPMD_CACHE": str(tmp_path / "a"), "LOUP_CACHE_DIR": str(tmp_path / "b")}).name == "a"
    assert cache.cache_root({}) == (Path.home() / ".cache" / "loupmd").resolve()
    assert not (tmp_path / "a").exists()                          # finding the root creates nothing
    assert cache.cache_dir("models", environ={"LOUPMD_CACHE": str(tmp_path / "a")}).is_dir()
    with pytest.raises(CacheLocationError, match="lies inside the Python installation"):
        cache.cache_root({"LOUPMD_CACHE": str(Path(sys.prefix) / "var" / "loupmd")})
    with pytest.raises(ValueError, match="unknown cache kind"):
        cache.cache_dir("nonsense", environ={"LOUPMD_CACHE": str(tmp_path / "a")})


def _cli(*args, env=None):
    return subprocess.run([sys.executable, "-m", "loupmd", *args], cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


def test_cli_models_lists_every_label(tmp_path):
    out = _cli("models", env={"LOUPMD_CACHE": str(tmp_path / "cache"), "LOUPMD_MODELS": str(tmp_path / "none")})
    assert out.returncode == 0, out.stderr
    for label in models.LABELS:
        assert re.search(rf"^{re.escape(label)}\s", out.stdout, re.M), label
    assert "20 labels" in out.stdout and "Academic Software License" in out.stdout
    long = _cli("models", "--long", env={"LOUPMD_CACHE": str(tmp_path / "cache")})
    assert models.LABELS["mh1-omat"].checkpoint.sha256 in long.stdout and "https://github.com/ACEsuit" in long.stdout


def test_cli_exit_codes_and_error_form(tmp_path):
    env = {"LOUPMD_CACHE": str(tmp_path / "cache")}
    assert _cli("--version").stdout.strip() == f"loupmd {loupmd.__version__}"
    assert _cli(env=env).returncode == 2
    assert _cli("no-such-command", env=env).returncode == 2
    bad = _cli("models", "--download", "no-such-label", env=env)
    assert bad.returncode == 1
    assert bad.stderr.startswith("error: 'no-such-label' is not a model label") and "Traceback" not in bad.stderr
    debug = _cli("--debug", "models", "--download", "no-such-label", env=env)
    assert debug.returncode == 1 and "Traceback" in debug.stderr


def test_local_model_folder_matches_the_table():
    """Where the machine has the released files, their hashes are the table's (skipped elsewhere)."""
    if not os.environ.get("LOUPMD_MODELS"):
        pytest.skip("LOUPMD_MODELS names no folder with the released model files")
    path = Path(os.environ["LOUPMD_MODELS"]) / models.LABELS["omat0-small"].checkpoint.file_name
    if not path.is_file():
        pytest.skip(f"{path} not found")
    assert models.sha256_of(path) == models.LABELS["omat0-small"].checkpoint.sha256
