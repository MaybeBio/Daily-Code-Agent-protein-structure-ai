from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
EXAMPLE_CONFIG = REPO_ROOT / "config" / "backends.example.yaml"


class ConfigError(RuntimeError):
    pass


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(os.path.expanduser(value))
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand(item) for item in value]
    return value


def config_candidates(path: str | Path | None = None) -> list[Path]:
    if path is not None:
        return [Path(path)]
    return [
        Path.cwd() / "backends.yaml",
        Path.home() / ".config" / "pdflow" / "backends.yaml",
        REPO_ROOT / "config" / "backends.yaml",
    ]


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    for candidate in config_candidates(path):
        if candidate.is_file():
            with open(candidate, encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            if not isinstance(data, dict):
                raise ConfigError(f"{candidate} must contain a YAML mapping")
            data["_config_path"] = str(candidate.resolve())
            return _expand(data)
    searched = ", ".join(str(item) for item in config_candidates(path))
    raise ConfigError(
        f"no pdflow config found (searched: {searched}). "
        "Run `pdflow setup` and edit backends.yaml."
    )


def get(cfg: dict[str, Any], dotted: str, default: Any = None) -> Any:
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def tool_env(
    cfg: dict[str, Any],
    extra: dict[str, str] | None = None,
    clean_ld: bool = False,
    pythonpath: str | None = None,
    path_prepend: str | list[str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ)
    if clean_ld:
        env.pop("LD_LIBRARY_PATH", None)
    if pythonpath:
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            pythonpath if not existing else pythonpath + os.pathsep + existing
        )
    if path_prepend:
        entries = (
            [path_prepend] if isinstance(path_prepend, str) else list(path_prepend)
        )
        expanded = [
            os.path.expandvars(os.path.expanduser(str(item))) for item in entries
        ]
        env["PATH"] = os.pathsep.join([*expanded, env.get("PATH", "")])
    for key, value in (extra or {}).items():
        env[str(key)] = os.path.expandvars(os.path.expanduser(str(value)))
    return env


def require_path(path: str | Path, label: str) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.exists():
        raise ConfigError(f"{label} not found: {resolved}")
    return resolved


def require_executable(path: str | Path, label: str) -> Path:
    resolved = Path(path).expanduser()
    if resolved.is_file():
        return resolved
    found = shutil.which(str(resolved))
    if found:
        return Path(found)
    raise ConfigError(f"{label} is not executable: {resolved}")


def run_command(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    log_path: Path | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as log:
            log.write("$ " + " ".join(command) + "\n\n")
            log.flush()
            return subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )
