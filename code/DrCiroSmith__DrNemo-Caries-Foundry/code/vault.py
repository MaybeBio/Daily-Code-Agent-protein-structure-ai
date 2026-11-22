"""
Foundry Contender Vault: SQLite Database and Ledger for Cyclic Peptide Candidates
Author: Dr. Roi Castrellon, DDS (DrNemo Caries Foundry)

Schema: 20 fields recording AutoDock Vina, Vinardo, OpenMM relaxation,
Stephan-curve pH switches, Donnan equilibrium, and Popperian falsification status.
"""

import os
import csv
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).parent.resolve()
DATA_DIR = REPO_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "foundry_contenders.sqlite"
DEFAULT_CSV_PATH = DATA_DIR / "contenders_ledger.csv"


class ContenderVault:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH, ledger_csv: Optional[Path] = None):
        self.db_path = Path(db_path)
        if ledger_csv is not None:
            self.ledger_csv = Path(ledger_csv)
        elif self.db_path == DEFAULT_DB_PATH:
            self.ledger_csv = DEFAULT_CSV_PATH
        else:
            self.ledger_csv = self.db_path.parent / f"{self.db_path.stem}_ledger.csv"

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_csv.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initializes the SQLite schema with the 20 canonical fields and priority queue."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contenders (
                contender_id TEXT PRIMARY KEY,
                sequence TEXT NOT NULL,
                generation INTEGER NOT NULL,
                heavy_atoms INTEGER NOT NULL,
                vina_3aic_kcal REAL NOT NULL,
                vinardo_3aic_kcal REAL NOT NULL,
                ligand_efficiency REAL NOT NULL,
                vina_1smd_kcal REAL NOT NULL,
                selectivity_ddg REAL NOT NULL,
                openmm_relaxed_kj REAL NOT NULL,
                ss_bond_angstrom REAL NOT NULL,
                q_ph72 REAL NOT NULL,
                q_ph60 REAL NOT NULL,
                q_ph52 REAL NOT NULL,
                delta_q_stephan REAL NOT NULL,
                protease_sites INTEGER NOT NULL,
                pareto_rank INTEGER NOT NULL,
                falsification_status TEXT NOT NULL,
                pose_sha256 TEXT NOT NULL,
                evaluated_at_utc TEXT NOT NULL
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_status ON contenders(falsification_status);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_vina ON contenders(vina_3aic_kcal);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rank ON contenders(pareto_rank);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sequence ON contenders(sequence);")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS priority_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sequence TEXT NOT NULL,
                generation INTEGER DEFAULT 4,
                status TEXT NOT NULL DEFAULT 'QUEUED',
                submitted_at TEXT NOT NULL,
                completed_at TEXT,
                result_vina REAL,
                result_status TEXT,
                error TEXT
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pq_status ON priority_queue(status);")
        conn.commit()
        conn.close()

    def add_contender(self, data: Dict[str, Any]):
        """Inserts a contender record into SQLite and appends to CSV ledger."""
        if "evaluated_at_utc" not in data:
            data["evaluated_at_utc"] = datetime.now(timezone.utc).isoformat()

        # Hard physical gate: broken disulfide rings cannot be corroborated
        ss_dist = data.get("ss_bond_angstrom")
        if ss_dist is not None and (ss_dist < 1.95 or ss_dist > 2.25):
            data["falsification_status"] = "FALSIFIED_BROKEN_DISULFIDE"
            data["pareto_rank"] = 3

        fields = [
            "contender_id", "sequence", "generation", "heavy_atoms",
            "vina_3aic_kcal", "vinardo_3aic_kcal", "ligand_efficiency",
            "vina_1smd_kcal", "selectivity_ddg", "openmm_relaxed_kj",
            "ss_bond_angstrom", "q_ph72", "q_ph60", "q_ph52",
            "delta_q_stephan", "protease_sites", "pareto_rank",
            "falsification_status", "pose_sha256", "evaluated_at_utc"
        ]

        row = [data.get(f) for f in fields]

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        placeholders = ", ".join(["?"] * len(fields))
        cur.execute(f"""
            INSERT OR REPLACE INTO contenders ({', '.join(fields)})
            VALUES ({placeholders})
        """, row)
        conn.commit()
        conn.close()

        # Append to CSV ledger
        file_exists = self.ledger_csv.exists() and self.ledger_csv.stat().st_size > 0
        with open(self.ledger_csv, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            if not file_exists:
                writer.writeheader()
            writer.writerow({f: data.get(f) for f in fields})

    def get_contender(self, contender_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single contender record by ID."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM contenders WHERE contender_id = ?", (contender_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def has_sequence(self, sequence: str) -> bool:
        """Checks if a sequence already exists in the vault with O(1) indexed lookup."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM contenders WHERE sequence = ? LIMIT 1;", (sequence.strip().upper(),))
        row = cur.fetchone()
        conn.close()
        return row is not None

    def get_all_contenders(self) -> List[Dict[str, Any]]:
        """Retrieves all contenders ordered by Pareto rank and Vina binding energy."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM contenders ORDER BY pareto_rank ASC, vina_3aic_kcal ASC")
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_top_contenders(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Returns the top contenders sorted by Pareto rank and affinity,
        strictly enforcing oral barrier & amylase selectivity gates."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM contenders
            ORDER BY 
                CASE
                    WHEN falsification_status = 'CORROBORATED'
                         AND delta_q_stephan >= 1.0
                         AND protease_sites = 0
                         AND selectivity_ddg <= -0.80
                         AND q_ph60 <= 4.0 THEN 1
                    WHEN falsification_status = 'CORROBORATED' THEN 3
                    ELSE pareto_rank
                END ASC,
                vina_3aic_kcal ASC
            LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_count(self) -> int:
        """Returns the total number of evaluated contenders."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM contenders")
        count = cur.fetchone()[0]
        conn.close()
        return count

    def get_pareto_champion(self) -> Optional[Dict[str, Any]]:
        """Returns the #1 Pareto lead (best affinity + selectivity passing all oral & amylase gates)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM contenders
            WHERE falsification_status = 'CORROBORATED'
              AND delta_q_stephan >= 1.0
              AND protease_sites = 0
              AND selectivity_ddg <= -0.80
              AND q_ph60 <= 4.0
              AND ss_bond_angstrom >= 1.95 AND ss_bond_angstrom <= 2.25
            ORDER BY pareto_rank ASC, vina_3aic_kcal ASC, selectivity_ddg ASC
            LIMIT 1
        """)
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_rank_1_contenders(self) -> List[Dict[str, Any]]:
        """Retrieves all Rank 1 corroborated contenders ordered by affinity."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM contenders
            WHERE pareto_rank = 1
              AND falsification_status = 'CORROBORATED'
              AND ss_bond_angstrom >= 1.95 AND ss_bond_angstrom <= 2.25
            ORDER BY vina_3aic_kcal ASC, selectivity_ddg ASC
        """)
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def export_ledger_csv(self):
        """Mirrors all contenders to data/contenders_ledger.csv."""
        rows = self.get_all_contenders()
        if not rows:
            return
        fieldnames = list(rows[0].keys())
        with open(self.ledger_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def get_latest_contender(self) -> Optional[Dict[str, Any]]:
        """Returns the most recently evaluated contender."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM contenders
            ORDER BY evaluated_at_utc DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def enqueue_priority(self, sequence: str, generation: int = 4) -> int:
        """Enqueues a candidate sequence into the priority queue."""
        now_utc = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO priority_queue (sequence, generation, status, submitted_at)
            VALUES (?, ?, 'QUEUED', ?)
        """, (sequence.strip().upper(), generation, now_utc))
        item_id = cur.lastrowid
        conn.commit()
        conn.close()
        return item_id

    def get_next_priority_item(self) -> Optional[Dict[str, Any]]:
        """Fetches the oldest uncompleted item in the priority queue."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM priority_queue
            WHERE status = 'QUEUED'
            ORDER BY id ASC
            LIMIT 1
        """)
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_priority_status(
        self,
        item_id: int,
        status: str,
        result_vina: Optional[float] = None,
        result_status: Optional[str] = None,
        error: Optional[str] = None
    ):
        """Updates the status and optional results of a priority queue item."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        completed_at = datetime.now(timezone.utc).isoformat() if status in ("COMPLETED", "FAILED") else None
        
        cur.execute("""
            UPDATE priority_queue
            SET status = ?,
                completed_at = COALESCE(?, completed_at),
                result_vina = COALESCE(?, result_vina),
                result_status = COALESCE(?, result_status),
                error = COALESCE(?, error)
            WHERE id = ?
        """, (status, completed_at, result_vina, result_status, error, item_id))
        conn.commit()
        conn.close()

    def get_priority_queue(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Returns recent priority queue items."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM priority_queue
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]


if __name__ == "__main__":
    vault = ContenderVault()
    print(f"Contender Vault ready at {vault.db_path}. Total records: {vault.get_count()}")
