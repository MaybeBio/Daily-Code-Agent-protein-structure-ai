"""The kernel manifest, the exporter's check against it and ``loupmd build-kernels`` (plan task S2-T06). Needs
neither a GPU nor the library: the generator and nvcc are stand-ins."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from loupmd import bundles, kernels, models
from loupmd.cli import main
from loupmd.errors import LoupError, UnsupportedModel

ROOT = Path(__file__).resolve().parents[2]


def test_the_manifest_covers_every_label():
    """The plan's criterion: every label whose export path exists maps to a signature in the manifest."""
    manifest = kernels.load_manifest()
    assert manifest["schema"] == "loupmd.kernel-manifest/1" and kernels.manifest_path().parent.name in ("src", "_lib")
    products = manifest["products"]
    signatures = [p["signature"] for p in products]
    assert len(set(signatures)) == len(signatures) >= 5 and all(len(s) == 16 for s in signatures)
    files = {entry.split("[")[0] for product in products for entry in product["models"]}
    missing = sorted({entry.checkpoint.file_name for entry in models.LABELS.values()} - files)
    assert missing == [], f"labels whose checkpoint has no kernels in the manifest: {missing}"
    abi = int((ROOT / "src" / "kernel_plugin.h").read_text().split("#define LOUP_KERNEL_ABI ")[1].split()[0])
    assert manifest["kernel_abi"] == abi
    # the manifest is what the generated source's table holds
    source = (ROOT / "src" / "generated_generic.cu").read_text(encoding="utf-8")
    table = source[source.index("static const GProdKernels kGProd[] = {"):]
    assert [line.split('"')[1] for line in table.splitlines()[1:len(signatures) + 1]] == signatures


def test_a_signature_the_library_lacks_is_refused_naming_build_kernels(tmp_path):
    manifest = {"schema": "loupmd.kernel-manifest/1", "kernel_abi": 1,
                "products": [{"signature": "aaaaaaaaaaaaaaaa", "lmax_out": 1, "segments_w": 29, "models": ["m[0]"]}]}
    environ = {"LOUPMD_CACHE": str(tmp_path / "cache")}
    assert kernels.missing_signatures(["aaaaaaaaaaaaaaaa"], manifest, environ) == []
    assert kernels.missing_signatures(["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb", "bbbbbbbbbbbbbbbb"], manifest,
                                      environ) == ["bbbbbbbbbbbbbbbb"]
    plugin = kernels.plugin_path("bbbbbbbbbbbbbbbb", environ)
    assert plugin == tmp_path / "cache" / "lib" / "loupmd-kernels-bbbbbbbbbbbbbbbb.so"
    plugin.parent.mkdir(parents=True)
    plugin.write_bytes(b"")
    assert kernels.missing_signatures(["bbbbbbbbbbbbbbbb"], manifest, environ) == []       # its plugin is there
    elsewhere = tmp_path / "plugins"
    elsewhere.mkdir()
    (elsewhere / "loupmd-kernels-cccccccccccccccc.so").write_bytes(b"")
    environ["LOUP_KERNEL_PATH"] = str(elsewhere)
    assert kernels.missing_signatures(["cccccccccccccccc"], manifest, environ) == []
    assert kernels.plugin_search_path(environ) == f"{elsewhere}:{tmp_path / 'cache' / 'lib'}"
    assert kernels.missing_signatures(["dddddddddddddddd"], None, environ) == [] or kernels.load_manifest() is not None

    error = kernels.unsupported("new.model", ["bbbbbbbbbbbbbbbb"], manifest)
    text = str(error)
    assert isinstance(error, UnsupportedModel) and error.signature == "bbbbbbbbbbbbbbbb"
    assert "new.model: no compiled kernels for its symmetric contraction (signature bbbbbbbbbbbbbbbb)" in text
    assert "loupmd build-kernels new.model" in text and "nvcc" in text and "1 contraction signatures" in text


EXPORTER = """
import sys
print("new.model: no compiled kernels", file=sys.stderr)
print("loupmd-unsupported-kernel: bbbbbbbbbbbbbbbb cccccccccccccccc", file=sys.stderr)
raise SystemExit(3)
"""


def test_the_exporter_s_refusal_reaches_the_caller_as_unsupported_model(tmp_path, monkeypatch):
    monkeypatch.setenv("LOUPMD_CACHE", str(tmp_path / "cache"))
    model = tmp_path / "new.model"
    model.write_bytes(b"not a model")
    exporter = tmp_path / "fake_export.py"
    exporter.write_text(EXPORTER)
    with pytest.raises(UnsupportedModel, match="signature bbbbbbbbbbbbbbbb, cccccccccccccccc") as caught:
        bundles.ensure_bundle(model, [8, 22, 38], exporter=[sys.executable, str(exporter)])
    assert caught.value.signature == "bbbbbbbbbbbbbbbb" and "loupmd build-kernels new.model" in str(caught.value)
    assert not list((tmp_path / "cache").rglob("*.loup")) and not list((tmp_path / "cache").rglob("*.part.*"))


def _fake_run(calls, generator_lines, nvcc_status=0):
    def run(cmd, **options):
        calls.append([str(c) for c in cmd])
        if "--plugin" in cmd:                                  # the generator
            scratch = Path(cmd[-1])
            lines = []
            for signature, lmax in generator_lines:
                (scratch / f"loupmd-kernels-{signature}.cu").write_text("// kernels\n")
                lines.append(f"plugin {signature} {lmax} 29 {scratch / f'loupmd-kernels-{signature}.cu'}")
            return SimpleNamespace(returncode=0, stdout="\n".join(lines) + "\n", stderr="")
        if nvcc_status == 0:                                    # nvcc
            Path(cmd[-1]).write_bytes(b"\x7fELF plugin")
        return SimpleNamespace(returncode=nvcc_status, stdout="", stderr="plugin.cu(3): error: no such kernel")
    return run


def test_build_kernels_compiles_what_is_missing(tmp_path, monkeypatch):
    environ = {"LOUPMD_CACHE": str(tmp_path / "cache"), "PATH": ""}
    monkeypatch.setattr(kernels, "find_nvcc", lambda environ=None: "/opt/cuda/bin/nvcc")
    known = kernels.load_manifest()["products"][0]["signature"]
    model = tmp_path / "new.model"
    model.write_bytes(b"not a model")
    calls, log = [], []
    results = kernels.build_plugins(model, arch="sm_89", environ=environ, log=log.append,
                                    run=_fake_run(calls, [(known, 1), ("bbbbbbbbbbbbbbbb", 0)]))
    target = tmp_path / "cache" / "lib" / "loupmd-kernels-bbbbbbbbbbbbbbbb.so"
    assert results == [(known, None, False), ("bbbbbbbbbbbbbbbb", target, True)] and target.read_bytes().startswith(b"\x7fELF")
    generator, nvcc = calls
    assert generator[1].endswith("gen_generic.py") and generator[2:4] == ["--plugin", str(model)]
    assert nvcc[0] == "/opt/cuda/bin/nvcc" and "-arch=sm_89" in nvcc and "-shared" in nvcc
    assert nvcc[nvcc.index("--cudart") + 1] == "shared"          # the library's runtime, not a static copy
    assert nvcc[-3].endswith("loupmd-kernels-bbbbbbbbbbbbbbbb.cu") and f"-I{ROOT / 'src'}" in nvcc
    assert any("the library has these kernels" in line for line in log)

    calls.clear()
    again = kernels.build_plugins(model, arch="sm_89", environ=environ, log=log.append,
                                  run=_fake_run(calls, [("bbbbbbbbbbbbbbbb", 0)]))
    assert again == [("bbbbbbbbbbbbbbbb", target, False)] and len(calls) == 1          # its plugin is in the cache
    forced = kernels.build_plugins(model, arch="sm_89", environ=environ, log=log.append, force=True,
                                   run=_fake_run(calls, [(known, 1)]))
    assert forced[0][2] is True and forced[0][1].name == f"loupmd-kernels-{known}.so"

    with pytest.raises(LoupError, match="nvcc failed on the kernels of signature eeeeeeeeeeeeeeee") as caught:
        kernels.build_plugins(model, arch="sm_89", environ=environ, log=log.append,
                              run=_fake_run(calls, [("eeeeeeeeeeeeeeee", 0)], nvcc_status=2))
    assert "no such kernel" in str(caught.value)
    assert not (tmp_path / "cache" / "lib" / "loupmd-kernels-eeeeeeeeeeeeeeee.so").exists()
    assert not list((tmp_path / "cache" / "lib").glob("*.part.*"))


def test_the_command(tmp_path, monkeypatch, capsys):
    model = tmp_path / "new.model"
    model.write_bytes(b"not a model")
    seen = {}

    def build(path, arch=None, force=False):
        seen.update(path=path, arch=arch, force=force)
        return [("bbbbbbbbbbbbbbbb", tmp_path / "x.so", True), ("aaaaaaaaaaaaaaaa", None, False)]

    monkeypatch.setattr(kernels, "build_plugins", build)
    assert main(["build-kernels", str(model), "--arch", "sm_120", "--force"]) == 1    # untrusted: never unpickled
    assert seen == {}
    capsys.readouterr()
    assert main(["build-kernels", str(model), "--trusted", "--arch", "sm_120", "--force"]) == 0
    assert seen == {"path": model, "arch": "sm_120", "force": True}
    assert "built 1 kernel plugin in" in capsys.readouterr().out
    monkeypatch.setattr(kernels, "build_plugins", lambda path, arch=None, force=False: [("a" * 16, None, False)])
    assert main(["build-kernels", str(model), "--trusted"]) == 0
    assert "nothing to build: every kernel of new.model is there" in capsys.readouterr().out
    assert main(["build-kernels", str(tmp_path / "absent.model")]) == 1
    assert json.loads(json.dumps({"ok": True}))["ok"]
