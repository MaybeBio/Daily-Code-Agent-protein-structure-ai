from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from . import structures
from .config import get, run_command
from .naming import backbone_id, format_header, read_fasta, slug, write_fasta

FINAL_BACKBONE_SUFFIXES = {".cif", ".pdb"}


def paths(root: Path) -> dict[str, Path]:
    root = Path(root)
    return {
        "root": root,
        "config": root / "campaign.yaml",
        "inputs": root / "inputs",
        "backbones": root / "backbones",
        "sequences": root / "sequences",
        "predictions": root / "predictions",
        "final": root / "final",
        "manifest": root / "manifest.jsonl",
        "csv": root / "designs.csv",
        "design_runs": root / "design_runs",
        "log": root / "logs",
    }


def init_campaign(root: Path) -> dict[str, Path]:
    layout = paths(root)
    for key in ("inputs", "backbones", "sequences", "predictions", "final", "design_runs", "log"):
        layout[key].mkdir(parents=True, exist_ok=True)
    layout["manifest"].touch(exist_ok=True)
    return layout


def load_spec(root: Path) -> dict[str, Any]:
    path = paths(root)["config"]
    if not path.is_file():
        raise FileNotFoundError(f"campaign config not found: {path}")
    with open(path, encoding="utf-8") as handle:
        spec = yaml.safe_load(handle) or {}
    spec["_dir"] = str(Path(root).resolve())
    return spec


def append_manifest(root: Path, record: dict[str, Any]) -> None:
    record = {"created": datetime.now().isoformat(timespec="seconds"), **record}
    with open(paths(root)["manifest"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def read_manifest(root: Path) -> list[dict[str, Any]]:
    manifest = paths(root)["manifest"]
    if not manifest.is_file():
        return []
    return [
        json.loads(line)
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _looks_sequence_less(sequence: str) -> bool:
    if not sequence:
        return True
    unknown = sum(1 for residue in sequence if residue in "XG")
    return unknown / len(sequence) > 0.6


def _choose_boltzgen_files(files: list[Path]) -> list[Path]:
    """BoltzGen exposes both the raw design backbone and the refolded model.

    Both are final artefacts for downstream scoring, so keep them. Point
    ``--input`` at a narrow directory if a run contains extra intermediates.
    """
    return files


def ingest_backbones(
    root: Path,
    *,
    designer: str,
    source_dir: Path,
    method: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Copy the final backbone of every design and register its sequences."""
    layout = init_campaign(root)
    source_dir = Path(source_dir)
    files = sorted(
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in FINAL_BACKBONE_SUFFIXES
    )
    if designer == "boltzgen":
        files = _choose_boltzgen_files(files)
    if limit is not None:
        files = files[: int(limit)]
    records: list[dict[str, Any]] = []
    for index, source in enumerate(files):
        identifier = backbone_id(
            get(load_spec(root), "campaign", root.name),
            designer,
            0,
            index,
            tag=slug(source.parent.name)[:16],
        )
        suffix = source.suffix.lower()
        target = layout["backbones"] / f"{identifier}{suffix}"
        shutil.copyfile(source, target)
        array = structures.load_structure_file(target)
        chains = structures.chain_ids(array)
        sequences = {chain: structures.chain_sequence(array, chain) for chain in chains}
        sequence_less = all(_looks_sequence_less(seq) for seq in sequences.values())
        record = {
            "backbone_id": identifier,
            "designer": designer,
            "source": str(source.resolve()),
            "path": str(target.relative_to(root)),
            "chains": chains,
            "sequences": sequences,
            "needs_seqdesign": sequence_less,
            "seq_ids": [],
        }
        if not sequence_less:
            seq_id = f"{identifier}__{slug(method or designer)}"
            seq_path = layout["sequences"] / f"{seq_id}.fasta"
            write_fasta(
                seq_path,
                [
                    (
                        format_header(
                            f"{seq_id}|{chain}",
                            chain=chain,
                            backbone=identifier,
                            designer=designer,
                            method=method or designer,
                        ),
                        sequences[chain],
                    )
                    for chain in chains
                ],
            )
            record["seq_ids"] = [seq_id]
            record["sequence_file"] = str(seq_path.relative_to(root))
        append_manifest(root, record)
        records.append(record)
    _rebuild_all_fasta(root)
    return records


def _rebuild_all_fasta(root: Path) -> Path:
    layout = paths(root)
    destination = layout["sequences"] / "all.fasta"
    records: list[tuple[str, str]] = []
    for path in sorted(layout["sequences"].glob("*.fasta")):
        if path.name == "all.fasta":
            continue
        records.extend(read_fasta(path))
    write_fasta(destination, records)
    return destination


def register_sequences(
    root: Path,
    *,
    backbone: dict[str, Any],
    seq_id: str,
    chains: dict[str, str],
    method: str,
) -> Path:
    layout = paths(root)
    path = layout["sequences"] / f"{seq_id}.fasta"
    write_fasta(
        path,
        [
            (
                format_header(
                    f"{seq_id}|{chain}",
                    chain=chain,
                    backbone=backbone["backbone_id"],
                    designer=backbone.get("designer", ""),
                    method=method,
                ),
                sequence,
            )
            for chain, sequence in chains.items()
        ],
    )
    _rebuild_all_fasta(root)
    return path


def find_backbone_record(root: Path, backbone_name: str) -> dict[str, Any] | None:
    for record in read_manifest(root):
        if record.get("backbone_id") == backbone_name:
            return record
    return None


def run_design(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Run the configured design engine, then ingest its final backbones."""
    spec = load_spec(root)
    layout = paths(root)
    design = get(spec, "design", {}) or {}
    engine = str(design.get("engine", "rfd4"))
    engine_cfg = get(cfg, f"design.{engine}", {}) or {}
    template = str(engine_cfg.get("command", ""))
    if not template:
        raise ValueError(f"design.{engine}.command is not configured")
    input_value = design.get("input", "")
    input_path = (layout["root"] / str(input_value)).resolve() if input_value else layout["inputs"]
    run_dir = layout["design_runs"] / slug(engine)
    extra = list(design.get("extra", []) or []) + list(
        engine_cfg.get("default_extra", []) or []
    )
    command_text = template.format(
        python=engine_cfg.get("python", "python"),
        binary=engine_cfg.get("binary", engine_cfg.get("python", "python")),
        input=input_path,
        out_dir=run_dir,
        num_designs=int(design.get("num_designs", 10)),
        seed=int(design.get("seed", 0)),
        extra=" ".join(str(item) for item in extra),
    )
    command = command_text.split()
    result = run_command(
        command,
        env={**os.environ, **{str(k): str(v) for k, v in (engine_cfg.get("env", {}) or {}).items()}},
        cwd=root,
        log_path=layout["log"] / f"design_{slug(engine)}.log",
    )
    if result.returncode != 0:
        return {"returncode": result.returncode, "run_dir": str(run_dir)}
    produced_dir = run_dir / "inference_samples"
    if not produced_dir.is_dir():
        produced_dir = run_dir
    records = ingest_backbones(
        root,
        designer=engine,
        source_dir=produced_dir,
        method=engine,
        limit=int(design.get("num_designs", 0)) or None,
    )
    return {"returncode": 0, "run_dir": str(run_dir), "ingested": len(records)}


def run_seqdesign(root: Path, cfg: dict[str, Any], backbone_name: str | None = None) -> list[dict[str, Any]]:
    """Run ProteinMPNN/LigandMPNN for backbones that have no sequence yet."""
    spec = load_spec(root)
    layout = paths(root)
    engine_cfg = get(cfg, "design.mpnn", {}) or {}
    template = str(engine_cfg.get("command", ""))
    if not template:
        raise ValueError("design.mpnn.command is not configured")
    results: list[dict[str, Any]] = []
    for record in read_manifest(root):
        if backbone_name and record["backbone_id"] != backbone_name:
            continue
        if not record.get("needs_seqdesign"):
            continue
        source = root / record["path"]
        out_dir = layout["design_runs"] / "mpnn" / record["backbone_id"]
        command_text = template.format(
            python=engine_cfg.get("python", "python"),
            binary=engine_cfg.get("binary", engine_cfg.get("python", "python")),
            input=source,
            out_dir=out_dir,
            num_designs=1,
            seed=int(get(spec, "design.seed", 0)),
            extra="",
        )
        result = run_command(
            command_text.split(),
            env={**os.environ, **{str(k): str(v) for k, v in (engine_cfg.get("env", {}) or {}).items()}},
            cwd=root,
            log_path=layout["log"] / f"mpnn_{record['backbone_id']}.log",
        )
        if result.returncode != 0:
            results.append({"backbone_id": record["backbone_id"], "returncode": result.returncode})
            continue
        produced = sorted(
            path for path in out_dir.rglob("*.fa*")
            if path.suffix.lower() in {".fa", ".fasta"}
        )
        seq_ids: list[str] = []
        for path in produced:
            for header, sequence in read_fasta(path):
                seq_id = f"{record['backbone_id']}__mpnn{len(seq_ids) + 1:03d}"
                register_sequences(
                    root,
                    backbone=record,
                    seq_id=seq_id,
                    chains={"A": sequence},
                    method="mpnn",
                )
                seq_ids.append(seq_id)
        record["seq_ids"] = sorted(set(record.get("seq_ids", []) + seq_ids))
        record["needs_seqdesign"] = False
        append_manifest(
            root,
            {
                "backbone_id": record["backbone_id"],
                "seqdesign": "mpnn",
                "seq_ids": record["seq_ids"],
            },
        )
        results.append(record)
    return results
