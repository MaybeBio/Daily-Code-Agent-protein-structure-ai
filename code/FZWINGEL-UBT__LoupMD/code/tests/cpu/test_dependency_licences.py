"""``tools/release/dependency_licences.py`` (plan task S7-T03): the run-time dependencies with their licences."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _tool():
    spec = importlib.util.spec_from_file_location("dependency_licences", ROOT / "tools/release/dependency_licences.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_declared_dependency_is_listed_with_a_licence():
    text = _tool().render()
    rows = {line.split(" | ")[0].strip("| ").lower(): line for line in text.splitlines() if line.startswith("| ")}
    for name in ("numpy", "ase"):
        assert name in rows and "missing" not in rows[name]
    assert "LGPL-2.1-or-later" in rows["ase"]
    assert "/home/" not in text                     # no local paths in the shipped record
