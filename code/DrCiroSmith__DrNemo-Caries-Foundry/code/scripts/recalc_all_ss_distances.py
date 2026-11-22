import sys
import sqlite3
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from biophysics_engine import measure_disulfide_bond
from vault import ContenderVault

DB_PATH = REPO_ROOT / "data" / "foundry_contenders.sqlite"
POSES_DIR = REPO_ROOT / "data" / "poses"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute("SELECT contender_id, sequence, ss_bond_angstrom FROM contenders")
rows = c.fetchall()

updated = 0
unmatched = 0

for cid, seq, old_ss in rows:
    candidates = list(POSES_DIR.glob(f"{cid}_3aic_split_1.pdbqt"))
    if not candidates:
        candidates = list(POSES_DIR.glob(f"{cid}_3aic.pdbqt"))
    if not candidates:
        candidates = list(POSES_DIR.glob(f"{cid}.pdbqt"))
    if not candidates:
        candidates = list(POSES_DIR.glob(f"*{cid}*.pdbqt"))
    if not candidates:
        candidates = list(POSES_DIR.glob(f"*{seq}*_3aic*.pdbqt"))
    if not candidates:
        candidates = list(POSES_DIR.glob(f"*{seq}*.pdbqt"))

    if candidates:
        pose_path = str(candidates[0])
        new_ss = measure_disulfide_bond(pose_path)
        if new_ss is not None:
            if abs(new_ss - old_ss) > 0.05:
                print(f"Updating {cid} ({seq}): old SS={old_ss} -> new SS={new_ss} (from {candidates[0].name})")
            c.execute("UPDATE contenders SET ss_bond_angstrom = ? WHERE contender_id = ?", (new_ss, cid))
            updated += 1
        else:
            print(f"Warning: could not measure SS for {cid} ({seq}) in {pose_path}")
    else:
        print(f"Warning: no pose file found for {cid} ({seq})")
        unmatched += 1

conn.commit()
conn.close()

print(f"\nFinished: updated {updated} records, unmatched {unmatched}")

# Re-export CSV ledger
vault = ContenderVault()
vault.export_ledger_csv()
print(f"Re-exported CSV ledger: {vault.get_count()} contenders")
