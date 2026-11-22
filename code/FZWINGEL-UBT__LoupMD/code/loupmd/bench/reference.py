"""Stored reference timings: what the same GPU model gave for the same model file, system and protocol.

``reference.json`` holds only numbers measured with ``loupmd bench`` itself; each entry names the library build and
the day. A reference is a figure to compare with, not a promise: the ratio a benchmark prints is measured / stored.
"""
from __future__ import annotations

import json
from pathlib import Path

SHIPPED = Path(__file__).resolve().parent / "reference.json"
SCHEMA = "loupmd.bench-reference/1"


def lookup(record, table=None) -> dict:
    """``{system: entry}`` for the rows of ``record`` that have a stored reference."""
    path = Path(table) if table is not None else SHIPPED
    try:
        entries = json.loads(path.read_text()).get("entries", [])
    except (OSError, ValueError):
        return {}
    gpu, sha, proto = record["gpu"].get("name"), record["model"].get("sha256"), record["protocol"].get("name")
    systems = {row["system"] for row in record["rows"]}
    found = {}
    for entry in entries:
        if (entry.get("gpu") == gpu and entry.get("model_sha256") == sha and entry.get("protocol") == proto
                and entry.get("system") in systems):
            found[entry["system"]] = entry
    return found
