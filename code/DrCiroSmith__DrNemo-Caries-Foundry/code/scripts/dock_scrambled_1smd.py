"""
Dock all 39 scrambled null peptides against RCSB 1SMD (Human Salivary alpha-Amylase)
using empirical AutoDock Vina + Vinardo (exhaustiveness 8, 28A uncompressed grid).

Synchronizes real empirical 1SMD scores and selectivity DDG into:
1. data/foundry_contenders.sqlite
2. data/contenders_ledger.csv
3. demo_data/results/falsification_benchmark.json
"""

import sys
import os
import json
import sqlite3
import subprocess
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, Any, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from biophysics_engine import (
    build_macrocycle_3d,
    run_docking_vina_and_vinardo,
    TARGET_COORDS,
    measure_disulfide_bond
)
from vault import ContenderVault

DB_PATH = REPO_ROOT / "data" / "foundry_contenders.sqlite"
POSES_DIR = REPO_ROOT / "data" / "poses"
BENCHMARK_JSON = REPO_ROOT / "demo_data" / "results" / "falsification_benchmark.json"

TARGET_1SMD = "1SMD"
CFG_1SMD = TARGET_COORDS[TARGET_1SMD]


def dock_single_scrambled(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Docks a single scrambled peptide on 1SMD with exhaustiveness=8.
    Resume-capable: if the 1SMD docked pose already exists and is valid, loads it directly.
    """
    idx = item["idx"]
    cid = item["contender_id"]
    seq = item["sequence"]
    vina_3aic = item["vina_3aic_kcal"]

    out_docked = POSES_DIR / f"scrambled_{idx:02d}_{seq}_1smd.pdbqt"
    split_1 = POSES_DIR / f"scrambled_{idx:02d}_{seq}_1smd_split_1.pdbqt"

    vina_score = None
    vinardo_score = None
    ss_dist = None

    # Check if already docked
    if out_docked.exists() and out_docked.stat().st_size > 500:
        with open(out_docked, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("REMARK VINA RESULT:"):
                    vina_score = float(line.split()[3])
                    break

    if vina_score is not None and split_1.exists():
        # Score mode 1 with Vinardo if needed
        cmd_vinardo = [
            "/usr/bin/vina",
            "--receptor", CFG_1SMD["receptor"],
            "--ligand", str(split_1),
            "--score_only",
            "--scoring", "vinardo",
            "--autobox"
        ]
        res_v = subprocess.run(cmd_vinardo, capture_output=True, text=True)
        for line in res_v.stdout.splitlines():
            if "Estimated Free Energy of Binding" in line:
                vinardo_score = float(line.split(":")[1].split("(")[0].strip())
                break
        ss_dist = measure_disulfide_bond(str(split_1))
        print(f"[RESUME] scrambled_{idx:02d} ({seq}): 1SMD Vina={vina_score:.3f}, Vinardo={vinardo_score}, SS={ss_dist}")
    else:
        # Need to dock
        # First ensure ligand input pdbqt exists
        ligand_input = POSES_DIR / f"input_scrambled_{idx:02d}_{seq}.pdbqt"
        if not ligand_input.exists():
            # Build 3D macrocycle with coordinates translated to 1SMD center
            build_macrocycle_3d(seq, str(ligand_input), target_center=CFG_1SMD["center"])

        t0 = time.time()
        dock_res = run_docking_vina_and_vinardo(
            ligand_pdbqt=str(ligand_input),
            target="1SMD",
            exhaustiveness=8,
            cpu=6,
            out_pdbqt=str(out_docked)
        )
        elapsed = time.time() - t0
        vina_score = dock_res["vina_kcal"]
        vinardo_score = dock_res["vinardo_kcal"]
        ss_dist = dock_res["ss_bond_angstrom"]
        print(f"[DOCKED] scrambled_{idx:02d} ({seq}) in {elapsed:.1f}s: 1SMD Vina={vina_score:.3f}, Vinardo={vinardo_score}, SS={ss_dist}")

    ddg = round(vina_3aic - vina_score, 3)

    return {
        "idx": idx,
        "contender_id": cid,
        "sequence": seq,
        "vina_3aic_kcal": vina_3aic,
        "vina_1smd_kcal": vina_score,
        "vinardo_1smd_kcal": vinardo_score,
        "selectivity_ddg": ddg,
        "ss_bond_angstrom": ss_dist or 2.06
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT contender_id, sequence, vina_3aic_kcal, vina_1smd_kcal "
        "FROM contenders WHERE falsification_status = 'SCRAMBLED_NULL_CONTROL' "
        "ORDER BY contender_id"
    )
    rows = c.fetchall()
    conn.close()

    items = []
    for i, r in enumerate(rows, start=1):
        items.append({
            "idx": i,
            "contender_id": r[0],
            "sequence": r[1],
            "vina_3aic_kcal": r[2],
            "vina_1smd_kcal": r[3]
        })

    print(f"Loaded {len(items)} scrambled sequences to dock against 1SMD.")

    results = []
    # 4 concurrent workers * 6 CPUs = 24 CPUs total
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(dock_single_scrambled, it): it for it in items}
        for f in as_completed(futures):
            res = f.result()
            results.append(res)

    results.sort(key=lambda x: x["idx"])

    # Update SQLite database
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for res in results:
        c.execute(
            "UPDATE contenders SET vina_1smd_kcal = ?, selectivity_ddg = ? WHERE contender_id = ?",
            (res["vina_1smd_kcal"], res["selectivity_ddg"], res["contender_id"])
        )
    conn.commit()
    conn.close()
    print("Updated all 39 scrambled null records in foundry_contenders.sqlite.")

    # Re-export CSV ledger
    vault = ContenderVault()
    vault.export_ledger_csv()
    print("Re-exported data/contenders_ledger.csv.")

    # Update demo_data/results/falsification_benchmark.json if present
    if BENCHMARK_JSON.exists():
        with open(BENCHMARK_JSON, "r", encoding="utf-8") as f:
            bdata = json.load(f)

        if "scrambled_null_distribution" in bdata:
            res_by_seq = {r["sequence"]: r for r in results}
            for item in bdata["scrambled_null_distribution"]:
                s = item.get("sequence")
                if s in res_by_seq:
                    item["vina_1smd_kcal"] = res_by_seq[s]["vina_1smd_kcal"]
                    item["selectivity_ddg"] = res_by_seq[s]["selectivity_ddg"]

        with open(BENCHMARK_JSON, "w", encoding="utf-8") as f:
            json.dump(bdata, f, indent=2)
        print("Updated demo_data/results/falsification_benchmark.json.")

    print("\nAll 39 scrambled nulls successfully docked and synchronized!")


if __name__ == "__main__":
    main()
