#!/usr/bin/env python3
"""Compatibility entry point. Prefer analyze_run.py."""
import runpy
from pathlib import Path
if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("analyze_run.py")), run_name="__main__")
