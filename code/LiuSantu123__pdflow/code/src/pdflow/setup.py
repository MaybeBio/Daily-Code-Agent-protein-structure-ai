from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .config import EXAMPLE_CONFIG, REPO_ROOT

NATIVE_PROFILE = REPO_ROOT / "config" / "backends.native.example.yaml"
PROFILE_FILES = {"kit": EXAMPLE_CONFIG, "native": NATIVE_PROFILE}
TOKENS = ("HOME", "CONDA_BASE", "MODEL_ROOT", "KIT_ROOT", "AF3_ROOT", "USALIGN")


def default_values() -> dict[str, str]:
    home = Path.home()
    conda_exe = os.environ.get("CONDA_EXE") or shutil.which("conda")
    conda_base = (
        Path(conda_exe).resolve().parent.parent
        if conda_exe
        else home / "miniconda3"
    )
    model_root = Path("/mnt/f/protein_design/02_soft/model")
    if not model_root.is_dir():
        model_root = home / "models"
    kit_root = Path(
        "/mnt/f/protein_design/07_arc/claude-blackwell-protein-accel-kit"
    )
    if not kit_root.is_dir():
        kit_root = home / "claude-blackwell-protein-accel-kit"
    af3_root = Path("/mnt/f/protein_design/02_soft/00_alphafold3")
    if not af3_root.is_dir():
        af3_root = home / "alphafold3"
    usalign = Path("/mnt/f/protein_design/02_soft/tool/usalign/USAlign")
    return {
        "HOME": str(home),
        "CONDA_BASE": str(conda_base),
        "MODEL_ROOT": str(model_root),
        "KIT_ROOT": str(kit_root),
        "AF3_ROOT": str(af3_root),
        "USALIGN": str(usalign) if usalign.is_file() else "USalign",
    }


def _ask(label: str, default: str) -> str:
    try:
        answer = input(f"{label} [{default}]: ").strip()
    except EOFError:
        return default
    return answer or default


def interactive_values(profile: str, values: dict[str, str] | None = None) -> dict[str, str]:
    values = dict(values or default_values())
    print(f"pdflow setup ({profile} profile)")
    print("Press Enter to accept a detected default.\n")
    for key in ("HOME", "CONDA_BASE", "MODEL_ROOT"):
        values[key] = _ask(key, values[key])
    if profile == "kit":
        values["KIT_ROOT"] = _ask("KIT_ROOT", values["KIT_ROOT"])
    values["AF3_ROOT"] = _ask("AF3_ROOT", values["AF3_ROOT"])
    values["USALIGN"] = _ask("USALIGN", values["USALIGN"])
    return values


def materialize_profile(
    profile: str,
    dest: Path,
    values: dict[str, str],
    force: bool = False,
) -> Path:
    if profile not in PROFILE_FILES:
        raise ValueError(f"unknown profile: {profile}")
    template = PROFILE_FILES[profile]
    if not template.is_file():
        raise FileNotFoundError(f"profile template not found: {template}")
    if dest.exists() and not force:
        raise FileExistsError(f"{dest} exists; use --force to overwrite")
    text = template.read_text(encoding="utf-8")
    for key in TOKENS:
        text = text.replace("__" + key + "__", str(values.get(key, "")))
    if "__" in text:
        leftover = sorted(
            {
                part.split("__")[0]
                for part in text.split("__")[1:]
                if part.split("__")[0] in TOKENS
            }
        )
        if leftover:
            raise ValueError(f"unresolved template tokens: {leftover}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest


def choose_profile(profile: str | None) -> str:
    if profile:
        return profile
    if sys.stdin.isatty():
        answer = input("Profile [native/kit] (native): ").strip().lower()
        return answer or "native"
    return "native"
