"""The vendored FastMACE subset of the exporters (plan task S2-T03). No GPU needed; the comparison with a FastMACE
checkout runs when ``LOUPMD_EXPORT_FASTMACE`` names one."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "loupmd" / "export" / "_vendor"


def test_the_vendored_tree_names_its_commit_and_licence():
    version = (VENDOR / "VERSION").read_text(encoding="utf-8")
    assert re.match(r"FastMACE [0-9a-f]{40}\nMIT License, Copyright \(c\) 2026 Fabian Zwingel", version)
    modules = sorted(p.relative_to(VENDOR).as_posix() for p in VENDOR.rglob("*.py") if p.stat().st_size)
    assert modules == ["fastmace/kernels/cuda/sc_factored.py", "fastmace/kernels/cuda/sc_generated.py",
                       "fastmace/kernels/triton/compose_skip.py", "fastmace/kernels/triton/radial_table.py",
                       "fastmace/rewrites/generic/modules.py",
                       "fastmace/rewrites/linear/modules.py", "fastmace/rewrites/radial/__init__.py",
                       "fastmace/rewrites/radial/spline.py"]
    for name in modules:
        text = (VENDOR / name).read_text(encoding="utf-8")
        assert text.startswith("# SPDX-License-Identifier: MIT\n# Vendored from FastMACE "), name
        assert f"{name.split('fastmace/', 1)[1]} (fastmace/)" in text.splitlines()[1], name
        assert not re.search(r"(?m)^\s*(from|import) fastmace\b", text), name     # no way back to a checkout
    notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
    assert "loupmd/export/_vendor/" in notice and "FastMACE" in notice


def test_no_machine_path_is_left_in_the_package_and_the_generators():
    """S2-T03's criterion, for what ships and what builds: no path under /home, /mnt/d or /mnt/homes."""
    offenders = []
    for folder in ("loupmd", "codegen", "tools/release"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path.suffix in (".py", ".sh", ".toml", ".json", ".md") and "__pycache__" not in path.parts:
                text = path.read_text(encoding="utf-8", errors="replace")
                if re.search(r"/mnt/d\b|/mnt/homes\b|/home/", text):
                    offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_the_exporters_import_without_fastmace():
    """A process that has no FastMACE on its path imports the exporters and finds every name they use. The
    exporters need torch (the export extra); without it the test skips."""
    pytest.importorskip("torch")
    code = ("import sys\n"
            "from loupmd.export import _fastmace as fm, gen_product, generic\n"
            "assert fm.SOURCE.startswith('vendored subset'), fm.SOURCE\n"
            "for module, names in ((fm.sc_factored, 'factor fold_weights _emit_node _expr _literal Program'),\n"
            "                      (fm.sc_generated, 'merged_terms shape_of'), (fm.compose_skip, 'composed'),\n"
            "                      (fm.rad, 'R_LO R_PHYSICAL CERTIFY_POINTS fit certify _GenericChain "
            "power_basis'),\n"
            "                      (fm.rspline, 'fit coefficients locate grid_knots _Scorer'),\n"
            "                      (fm.generic_modules, 'fc_last_weight fc_split species_skip'),\n"
            "                      (fm.linear_modules, 'block_linear raw_blocks')):\n"
            "    for name in names.split():\n"
            "        assert hasattr(module, name), (module.__name__, name)\n"
            "assert not [m for m in sys.modules if m == 'fastmace' or m.startswith('fastmace.')]\n"
            "print('ok')\n")
    env = {k: v for k, v in os.environ.items() if k not in ("LOUPMD_EXPORT_FASTMACE", "PYTHONPATH")}
    env.update(CUDA_VISIBLE_DEVICES="", PYTHONPATH=str(ROOT))
    done = subprocess.run([sys.executable, "-W", "ignore", "-c", code], capture_output=True, text=True, env=env,
                          cwd=str(ROOT.parent))
    assert done.returncode == 0 and done.stdout.strip().endswith("ok"), done.stderr[-1500:]


def test_the_vendored_tree_is_what_the_tool_writes():
    checkout = os.environ.get("LOUPMD_EXPORT_FASTMACE")
    if not checkout:
        pytest.skip("set LOUPMD_EXPORT_FASTMACE to a FastMACE checkout at the vendored commit")
    commit = (VENDOR / "VERSION").read_text(encoding="utf-8").split()[1]
    head = subprocess.run(["git", "-C", checkout, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != commit:
        pytest.skip(f"the checkout is at {head[:12]}, the vendored tree is from {commit[:12]}")
    done = subprocess.run([sys.executable, str(ROOT / "tools" / "release" / "vendor_fastmace.py"), checkout, "--check"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
