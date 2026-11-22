"""List the licences of LoupMD's run-time dependencies, as `pip-licenses` would (PLAN.md S7-T03).

    python tools/release/dependency_licences.py [--extra export] [--output FILE]

Reads `pyproject.toml`'s `dependencies` (and the extras named), follows each installed distribution's own
requirements, and prints a Markdown table of every distribution reached: name, version, licence (the metadata's
`License-Expression`, else `License`, else the `License ::` classifiers) and where the licence came from. Run it
with the Python of the environment to describe; it reads installed metadata only and installs nothing. A
requirement that is not installed is listed as missing.
"""
from __future__ import annotations

import argparse
import sys
from importlib import metadata
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]


def _project():
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def _applies(requirement: Requirement, extras) -> bool:
    if requirement.marker is None:
        return True
    env = default_environment()
    return any(requirement.marker.evaluate({**env, "extra": e}) for e in (extras or {""}))


def _licence(dist) -> tuple:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip(), "License-Expression"
    text = (meta.get("License") or "").strip()
    if text and "\n" not in text and len(text) <= 80 and text.upper() != "UNKNOWN":
        return text, "License"
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return "; ".join(classifiers), "classifier"
    if text:
        return text.splitlines()[0][:80] + " (first line of the licence text)", "License"
    return "not stated in the metadata", "-"


def closure(requirements, extras_of_root=()):
    """Every distribution reached from ``requirements``: {name: (dist or None, requested by)}."""
    found = {}
    todo = [(Requirement(r), "loupmd", set(extras_of_root) | {""}) for r in requirements]
    while todo:
        requirement, parent, extras = todo.pop(0)          # breadth first: a distribution's shortest path
        if not _applies(requirement, extras):
            continue
        key = requirement.name.lower().replace("_", "-")
        if key in found:
            continue
        try:
            dist = metadata.distribution(requirement.name)
        except metadata.PackageNotFoundError:
            found[key] = (None, parent)
            continue
        found[key] = (dist, parent)
        for sub in dist.requires or []:
            todo.append((Requirement(sub), dist.metadata["Name"], set(requirement.extras) | {""}))
    return found


def render(extras=()) -> str:
    project = _project()
    requirements = list(project["dependencies"])
    for extra in extras:
        requirements += project["optional-dependencies"][extra]
    found = closure(requirements)
    rows = []
    for key in sorted(found):
        dist, parent = found[key]
        if dist is None:
            rows.append(f"| {key} | missing | - | - | {parent} |")
            continue
        licence, source = _licence(dist)
        rows.append(f"| {dist.metadata['Name']} | {dist.version} | {licence.replace('|', '/')} | {source} | {parent} |")
    head = [f"Run-time dependencies of LoupMD{' with ' + ', '.join(extras) if extras else ''}: "
            f"{sum(d is not None for d, _ in found.values())} installed, {sum(d is None for d, _ in found.values())} "
            f"missing (Python {sys.version.split()[0]}; written by `tools/release/dependency_licences.py`).", "",
            "| Distribution | Version | Licence | From | Required by |", "| --- | --- | --- | --- | --- |"]
    return "\n".join(head + rows) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--extra", action="append", default=[], help="an optional-dependencies group to add")
    parser.add_argument("--output", help="write the table to this file instead of standard output")
    args = parser.parse_args(argv)
    text = render(tuple(args.extra))
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
