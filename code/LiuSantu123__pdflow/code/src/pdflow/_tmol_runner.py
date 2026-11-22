#!/usr/bin/env python
"""tmol 1.x score / minimize / relax runner.

Executed with the tmol conda environment; pdflow itself never imports tmol.
Writes ``<stem>.metrics.json`` per input.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import torch

logger = logging.getLogger("pdflow.tmol")


def _resolve_device(name: str) -> torch.device:
    if name == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(name)


def _score(pose, sfxn) -> tuple[float, dict[str, float]]:
    module = sfxn.render_whole_pose_scoring_module(pose)
    with torch.no_grad():
        total = float(module(pose.coords)[0])
        unweighted = module.unweighted_scores(pose.coords)
    unweighted = (
        unweighted.reshape(unweighted.shape[0], -1)
        if unweighted.dim() > 1
        else unweighted.reshape(-1, 1)
    )
    weights = sfxn.weights_tensor().tolist()
    terms: dict[str, float] = {}
    for score_type, raw, weight in zip(
        sfxn.all_score_types(), unweighted[:, 0].tolist(), weights
    ):
        value = raw * weight
        if abs(value) > 1e-6:
            terms[str(score_type).rsplit(".", 1)[-1]] = round(value, 3)
    return total, terms


def _process_one(path: str, args, device: torch.device) -> dict:
    import tmol

    pose = tmol.pose_stack_from_file(path, device)
    sfxn = tmol.beta2016_score_function(device)
    start, terms = _score(pose, sfxn)
    metrics: dict = {
        "input_path": str(path),
        "device": str(device),
        "total_score": round(start, 3),
        **terms,
    }
    if args.mode == "score":
        return metrics

    out_path = Path(args.output_dir) / (
        f"{Path(path).stem}.min.pdb"
        if args.mode == "minimize"
        else f"{Path(path).stem}.relaxed.pdb"
    )
    if args.mode == "minimize":
        final_pose = tmol.run_cart_min(pose, sfxn)
    else:
        final_pose = tmol.fast_relax(pose, sfxn, num_repeats=args.num_repeats)
    final, _ = _score(final_pose, sfxn)
    tmol.file_from_pose_stack(final_pose, str(out_path))
    metrics.update(
        {
            "structure_path": str(out_path),
            "energy_start": round(start, 3),
            "energy_final": round(final, 3),
            "energy_delta": round(final - start, 3),
        }
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="pdflow tmol 1.x runner")
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--mode", choices=["score", "minimize", "relax"], required=True)
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--num-repeats", type=int, default=2)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    device = _resolve_device(args.device)
    for path in args.input:
        try:
            metrics = _process_one(path, args, device)
        except Exception as exc:  # one bad structure should not stop the batch
            logger.exception("%s: failed", path)
            metrics = {"input_path": str(path), "skipped": f"error: {exc}"}
        (out_dir / f"{Path(path).stem}.metrics.json").write_text(
            json.dumps(metrics, indent=2)
        )


if __name__ == "__main__":
    main()
