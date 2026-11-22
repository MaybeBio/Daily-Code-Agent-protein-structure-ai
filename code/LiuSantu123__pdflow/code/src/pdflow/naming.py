from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def slug(text: str, max_length: int = 48) -> str:
    cleaned = _SAFE.sub("-", str(text)).strip("-._")
    return (cleaned or "x")[:max_length]


def backbone_id(campaign: str, designer: str, seed: int, index: int, tag: str = "") -> str:
    parts = [slug(campaign), slug(designer), f"s{int(seed)}", f"{int(index):04d}"]
    if tag:
        parts.append(slug(tag))
    return "__".join(parts)


def sequence_id(backbone: str, method: str, index: int) -> str:
    return f"{backbone}__{slug(method)}{int(index):03d}"


def prediction_id(seq_id: str, predictor: str, rank: int) -> str:
    return f"{seq_id}__{slug(predictor)}__m{int(rank):02d}"


def format_header(record_id: str, **fields: object) -> str:
    extras = " ".join(
        f"{key}={value}" for key, value in fields.items() if value not in (None, "")
    )
    return f">{record_id} {extras}".strip()


def parse_header(header: str) -> dict[str, str]:
    tokens = header.lstrip(">").split()
    if not tokens:
        return {}
    parsed = {"id": tokens[0]}
    for token in tokens[1:]:
        if "=" in token:
            key, value = token.split("=", 1)
            parsed[key] = value
    return parsed


def write_fasta(path: Path, records: Iterable[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for header, sequence in records:
            handle.write(header.rstrip() + "\n")
            sequence = sequence.strip()
            for start in range(0, len(sequence), 60):
                handle.write(sequence[start : start + 60] + "\n")


def read_fasta(path: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    header: str | None = None
    chunks: list[str] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(chunks)))
            header, chunks = line, []
        elif header is None:
            raise ValueError(f"FASTA sequence before header in {path}")
        else:
            chunks.append(line.replace(" ", "").upper())
    if header is not None:
        records.append((header, "".join(chunks)))
    return records
