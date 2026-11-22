"""For both test folders: which package the tests run.

``tests/cpu`` needs neither a GPU nor the library nor torch; ``tests/gpu`` needs a GPU, the library and the model
files (its ``conftest.py``). The tests run the package of this checkout. With ``LOUPMD_TEST_INSTALLED=1`` the
import path is left alone, so that an installed package (a wheel) is what runs; start pytest by its script then,
not with ``python -m pytest`` from the checkout's root, which puts that folder first.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not os.environ.get("LOUPMD_TEST_INSTALLED"):
    sys.path.insert(0, str(ROOT))
