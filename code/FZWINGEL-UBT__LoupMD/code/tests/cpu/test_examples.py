"""The examples (plan task S7-T04) import, print ``--help`` and are listed in ``examples/README.md``. They run on
the GPU in ``tests/gpu/test_examples.py`` (acceptance tier)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
SCRIPTS = sorted(p.name for p in EXAMPLES.glob("[0-9][0-9]_*.py"))


def test_there_are_six_examples_and_the_readme_lists_each():
    assert len(SCRIPTS) == 6
    readme = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    for name in SCRIPTS:
        assert f"`{name}`" in readme, name


@pytest.mark.parametrize("name", SCRIPTS)
def test_each_example_prints_its_help(name):
    done = subprocess.run([sys.executable, str(EXAMPLES / name), "--help"], capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, done.stderr
    assert "--steps" in done.stdout and "--checkpoint" in done.stdout
