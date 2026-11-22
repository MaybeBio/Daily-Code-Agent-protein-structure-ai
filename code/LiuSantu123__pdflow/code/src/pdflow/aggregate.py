from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from . import campaign, metrics, structures, tmol_score
from .config import get
from .naming import parse_header, read_fasta, slug


def _sequence_records(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    chains: dict[str, str] = {}
    metadata: dict[str, str] = {}
    for header, sequence in read_fasta(path):
        parsed = parse_header(header)
        metadata.update({key: value for key, value in parsed.items() if key != "id"})
        chain = parsed.get("chain", "A")
        chains[chain] = sequence
    return chains, metadata


def _align_pairs(spec: dict[str, Any]) -> list[tuple[str, str]]:
    align_chains = get(spec, "score.align_chains", None)
    targets = get(spec, "targets", {}) or {}
    mapping: dict[str, str] = {}
    for target in targets.values():
        design_chain = str(target.get("design_chain", ""))
        predict_chain = str(target.get("predict_chain", design_chain))
        if design_chain:
            mapping[design_chain] = predict_chain
    chains = align_chains if align_chains else ["A"]
    # US-align takes (mobile=prediction, target=design backbone).
    return [(mapping.get(str(chain), str(chain)), str(chain)) for chain in chains]


def score_campaign(root: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    root = Path(root)
    spec = campaign.load_spec(root)
    layout = campaign.paths(root)
    predictor_names = list(get(spec, "score.predictors", []) or [])
    align_pairs = _align_pairs(spec)
    motif = get(spec, "score.motif", None) or None
    use_tmol = bool(get(spec, "score.tmol", True))
    manifest = {record["backbone_id"]: record for record in campaign.read_manifest(root)}

    summary: list[dict[str, Any]] = []
    overlay_summaries: dict[Path, dict[str, dict[str, Any]]] = {}
    for sequence_path in sorted(layout["sequences"].glob("*.fasta")):
        if sequence_path.name == "all.fasta":
            continue
        seq_id = sequence_path.stem
        chains, metadata = _sequence_records(sequence_path)
        backbone_name = metadata.get("backbone", "")
        record = manifest.get(backbone_name, {})
        backbone_rel = record.get("path", "")
        backbone = root / backbone_rel if backbone_rel else None
        if backbone is not None and not backbone.is_file():
            backbone = None

        for predictor_name in predictor_names:
            predictor_dir = layout["predictions"] / seq_id / predictor_name
            search_root = predictor_dir / "output"
            if not search_root.is_dir():
                search_root = predictor_dir
            status_path = predictor_dir / "status.json"
            status = (
                json.loads(status_path.read_text(encoding="utf-8"))
                if status_path.is_file() else {}
            )
            if predictor_name == "esmfold2_overlay":
                artifacts = []
                if not status.get("skipped") and status.get("returncode", 0) == 0:
                    if status.get("output"):
                        search_root = Path(status["output"])
                    if search_root not in overlay_summaries:
                        path = search_root / "summary.json"
                        document = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
                        overlay_summaries[search_root] = {
                            row["design"]: row for row in document.get("results", [])
                        }
                    artifacts = metrics.discover_models(
                        predictor_name, search_root, design=seq_id,
                        batch_summary=overlay_summaries[search_root],
                    )
            else:
                artifacts = metrics.discover_models(predictor_name, search_root)
            if not artifacts:
                predictor_dir.mkdir(parents=True, exist_ok=True)
                payload = {
                    "sequence_id": seq_id,
                    "backbone_id": backbone_name,
                    "backbone_path": str(backbone) if backbone else "",
                    "designer": metadata.get("designer", ""),
                    "method": metadata.get("method", ""),
                    "chains": chains,
                    "predictor": predictor_name,
                    "best_model_rank": None,
                    "best_ranking_score": -1.0,
                    "models": [],
                    "error": status.get("error")
                    or status.get("skipped")
                    or "no prediction structures found",
                }
                (predictor_dir / "scores.json").write_text(
                    json.dumps(payload, indent=2, default=float), encoding="utf-8"
                )
                summary.append(payload)
                continue
            scored: list[dict[str, Any]] = []
            for artifact in artifacts:
                scored.append(
                    metrics.score_model(
                        artifact,
                        cfg,
                        backbone,
                        align_pairs,
                        motif=motif,
                    )
                )
            best = max(scored, key=lambda item: item.get("ranking_score", 0.0))
            if use_tmol:
                tmol_dir = predictor_dir / "tmol"
                tmol_metrics = tmol_score.run_tmol(
                    cfg,
                    [Path(best["structure"])],
                    tmol_dir,
                    log_path=tmol_dir / "tmol.log",
                )
                best["tmol"] = tmol_metrics.get(str(Path(best["structure"]).resolve()), {})
            payload = {
                "sequence_id": seq_id,
                "backbone_id": backbone_name,
                "backbone_path": str(backbone) if backbone else "",
                "designer": metadata.get("designer", ""),
                "method": metadata.get("method", ""),
                "chains": chains,
                "predictor": predictor_name,
                "best_model_rank": best.get("model_rank", 0),
                "best_ranking_score": best.get("ranking_score", 0.0),
                "models": scored,
            }
            (predictor_dir / "scores.json").write_text(
                json.dumps(payload, indent=2, default=float), encoding="utf-8"
            )
            summary.append(payload)
    return summary


def _flatten_model(row: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    pair_margins = {
        key: value.get("iptm", float("nan"))
        for key, value in (model.get("chain_pairs") or {}).items()
    }
    interface = {
        key: {
            "ipae": value.get("ipae"),
            "ipsae_ref": value.get("ipsae_ref"),
            "delta_sasa": value.get("delta_sasa"),
            "sc_approx": value.get("sc_approx"),
            "n_interface_residues_a": value.get("n_interface_residues_a"),
            "n_interface_residues_b": value.get("n_interface_residues_b"),
        }
        for key, value in (model.get("chain_pairs") or {}).items()
    }
    tmol = model.get("tmol") or {}
    return {
        "design_id": row["sequence_id"],
        "backbone_id": row["backbone_id"],
        "designer": row["designer"],
        "sequence_method": row["method"],
        "predictor": row["predictor"],
        "model_rank": model.get("model_rank"),
        "structure": model.get("structure"),
        "ptm": model.get("ptm"),
        "iptm": model.get("iptm"),
        "mean_pae": model.get("mean_pae"),
        "mean_plddt": model.get("mean_plddt"),
        "ranking_score": model.get("ranking_score"),
        "usalign_global_rmsd": (model.get("usalign", {}).get("global", {}) or {}).get("rmsd"),
        "usalign_global_tm": (model.get("usalign", {}).get("global", {}) or {}).get("tm_score"),
        "per_chain_json": json.dumps(model.get("per_chain", {}), default=float),
        "chain_pair_iptm_json": json.dumps(pair_margins, default=float),
        "interface_json": json.dumps(interface, default=float),
        "usalign_per_chain_json": json.dumps(
            model.get("usalign", {}).get("per_chain", {}), default=float
        ),
        "motif_rmsd_json": json.dumps(
            model.get("usalign", {}).get("motif", {}), default=float
        ),
        "physchem_json": json.dumps(model.get("physchem", {}), default=float),
        "tmol_total_score": tmol.get("total_score"),
        "tmol_json": json.dumps(tmol, default=float),
        "error": model.get("error", ""),
        "all_models_json": json.dumps(row.get("models", []), default=float),
        "backbone_path": row.get("backbone_path", ""),
        "sequence_json": json.dumps(row.get("chains", {})),
    }


def finalize(root: Path, cfg: dict[str, Any], clean: bool = True) -> dict[str, Any]:
    root = Path(root)
    spec = campaign.load_spec(root)
    layout = campaign.paths(root)
    rows: list[dict[str, Any]] = []
    per_design: dict[str, dict[str, Any]] = {}

    for scores_path in sorted(layout["predictions"].glob("*/*/scores.json")):
        payload = json.loads(scores_path.read_text(encoding="utf-8"))
        seq_id = payload["sequence_id"]
        models = payload.get("models", [])
        if models:
            best_model = max(models, key=lambda item: item.get("ranking_score", 0.0))
        else:
            best_model = {
                "error": payload.get("error", "no prediction models"),
                "ranking_score": -1.0,
            }
        row = _flatten_model(payload, best_model)
        row["is_best"] = False
        rows.append(row)
        design = per_design.setdefault(
            seq_id,
            {
                "design_id": seq_id,
                "backbone_id": payload["backbone_id"],
                "backbone_path": payload.get("backbone_path", ""),
                "designer": payload.get("designer", ""),
                "sequence_method": payload.get("method", ""),
                "sequences": payload.get("chains", {}),
                "predictions": {},
                "created": datetime.now().isoformat(timespec="seconds"),
                "task": get(spec, "task", ""),
            },
        )
        design["predictions"][payload["predictor"]] = {
            "best_model": best_model,
            "best_model_rank": payload.get("best_model_rank"),
            "best_ranking_score": payload.get("best_ranking_score"),
            "n_models": len(models),
            "models": models,
            "error": payload.get("error", ""),
        }

    if not rows:
        return {"designs": 0, "rows": 0, "csv": ""}

    dataframe = pd.DataFrame(rows)
    for design_id in dataframe["design_id"].unique():
        subset = dataframe[dataframe["design_id"] == design_id]
        best_index = subset["ranking_score"].idxmax()
        error_value = dataframe.loc[best_index, "error"]
        if not isinstance(error_value, str) or not error_value:
            dataframe.loc[best_index, "is_best"] = True

    layout["final"].mkdir(parents=True, exist_ok=True)
    dataframe["final_structure"] = ""
    for design_id, design in per_design.items():
        rows_for_design = dataframe[dataframe["design_id"] == design_id]
        best_row = rows_for_design.loc[rows_for_design["ranking_score"].idxmax()]
        best_predictor = str(best_row["predictor"])
        best_model = design["predictions"][best_predictor]["best_model"]
        design_dir = layout["final"] / slug(design_id)
        design_dir.mkdir(parents=True, exist_ok=True)
        design["intermediates_deleted"] = bool(clean)
        if best_model.get("error"):
            design["best"] = None
            design["error"] = best_model["error"]
            (design_dir / "full_data.json").write_text(
                json.dumps(design, indent=2, default=float), encoding="utf-8"
            )
            continue
        best_path = design_dir / "best.cif"
        array = structures.load_structure_file(best_model["structure"])
        structures.save_structure_file(best_path, array)
        design["best"] = {
            "predictor": best_predictor,
            "model_rank": best_model.get("model_rank"),
            "structure": str(best_path.relative_to(root)),
            "metrics": best_model,
        }
        dataframe.loc[best_row.name, "final_structure"] = str(
            best_path.relative_to(root)
        )
        (design_dir / "full_data.json").write_text(
            json.dumps(design, indent=2, default=float), encoding="utf-8"
        )

    dataframe = dataframe.drop(columns=["all_models_json"], errors="ignore")
    dataframe.to_csv(layout["csv"], index=False)

    archived = {
        "designs": len(per_design),
        "rows": len(dataframe),
        "csv": str(layout["csv"]),
    }
    if clean:
        batch_root = layout["predictions"] / "_batches"
        if batch_root.is_dir():
            # Shared predictor runs contain the retained structures, raw
            # confidence arrays and run summaries, not just intermediates.
            for path in layout["predictions"].iterdir():
                if path != batch_root and path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
        else:
            shutil.rmtree(layout["predictions"], ignore_errors=True)
        shutil.rmtree(layout["design_runs"], ignore_errors=True)
        # RFD4/Hydra writes its run directory next to the campaign.
        shutil.rmtree(layout["root"] / "hydra_outputs", ignore_errors=True)
        for path in layout["backbones"].glob("*.pdb"):
            if path.stem not in {design["backbone_id"] for design in per_design.values()}:
                path.unlink(missing_ok=True)
        archived["cleaned"] = True
    return archived
