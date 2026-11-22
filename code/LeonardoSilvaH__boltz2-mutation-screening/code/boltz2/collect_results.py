#!/usr/bin/env python3
"""Gather every Boltz-2 prediction into one table, plus a mutant-vs-wild-type delta.

Produces two CSVs in --work:

* ``results.csv``  -- one row per completed job, with affinity and confidence metrics.
* ``deltas.csv``   -- one row per (gene, mutant, drug) comparing it to the wild-type.

Boltz reports ``affinity_pred_value`` as log10(IC50) with IC50 in micromolar, so a
*lower* value means tighter binding and ``delta_pred`` below zero means the mutant
is predicted to bind more tightly than the wild type. ``affinity_probability_binary``
separates binders from decoys and is the better field for "does this bind at all".
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WT_DIRNAME, parse_job_name, sanitize  # noqa: E402

KCAL_REF = 6.0      # Boltz docs: kcal/mol ~= (6 - y) * 1.364
KCAL_SCALE = 1.364


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def collect(out_root: Path) -> list[dict]:
    rows: list[dict] = []
    for pred_dir in sorted(out_root.glob("*/boltz_results_*/predictions/*")):
        if not pred_dir.is_dir():
            continue
        job = pred_dir.name
        try:
            gene, variant, drug = parse_job_name(job)
        except ValueError:
            continue

        affinity = read_json(pred_dir / f"affinity_{job}.json")
        confidence = read_json(pred_dir / f"confidence_{job}_model_0.json")
        model = next(iter(sorted(pred_dir.glob(f"{job}_model_0.*"))), None)
        if not affinity and not confidence and model is None:
            continue

        pred = affinity.get("affinity_pred_value")
        rows.append({
            "job": job,
            "gene": gene,
            "variant": variant,
            "is_wt": int(variant == sanitize(WT_DIRNAME)),
            "drug": drug,
            "affinity_pred_value": pred,
            "affinity_kcal_per_mol": round((KCAL_REF - pred) * KCAL_SCALE, 4) if pred is not None else None,
            "affinity_probability_binary": affinity.get("affinity_probability_binary"),
            "confidence_score": confidence.get("confidence_score"),
            "complex_plddt": confidence.get("complex_plddt"),
            "iptm": confidence.get("iptm"),
            "ligand_iptm": confidence.get("ligand_iptm"),
            "model": str(model) if model else None,
        })
    return rows


def deltas(rows: list[dict]) -> list[dict]:
    wt_key = sanitize(WT_DIRNAME)
    wt = {(r["gene"], r["drug"]): r for r in rows if r["variant"] == wt_key}
    out: list[dict] = []
    for row in rows:
        if row["variant"] == wt_key:
            continue
        ref = wt.get((row["gene"], row["drug"]))
        if ref is None:
            continue

        def diff(field: str) -> float | None:
            a, b = row.get(field), ref.get(field)
            return round(a - b, 4) if a is not None and b is not None else None

        out.append({
            "gene": row["gene"],
            "variant": row["variant"],
            "drug": row["drug"],
            "mut_pred": row["affinity_pred_value"],
            "wt_pred": ref["affinity_pred_value"],
            "delta_pred": diff("affinity_pred_value"),
            "delta_kcal_per_mol": diff("affinity_kcal_per_mol"),
            "mut_prob": row["affinity_probability_binary"],
            "wt_prob": ref["affinity_probability_binary"],
            "delta_prob": diff("affinity_probability_binary"),
            "mut_confidence": row["confidence_score"],
            "wt_confidence": ref["confidence_score"],
        })
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        print(f"nothing to write to {path}")
        return
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", type=Path, default=Path("boltz2_work"))
    ap.add_argument("--out", type=Path, default=Path("boltz2_out"), help="boltz output root")
    args = ap.parse_args()

    rows = collect(args.out)
    args.work.mkdir(parents=True, exist_ok=True)
    write_csv(args.work / "results.csv", rows)
    write_csv(args.work / "deltas.csv", deltas(rows))

    manifest = args.work / "manifest.tsv"
    if manifest.exists():
        with manifest.open() as fh:
            expected = sum(1 for _ in csv.DictReader(fh, delimiter="\t"))
        missing = expected - len(rows)
        print(f"\n{len(rows)}/{expected} jobs complete" + (f", {missing} still missing" if missing > 0 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
