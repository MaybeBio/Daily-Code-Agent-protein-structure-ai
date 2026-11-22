#!/usr/bin/env python3
"""
DrNemo Caries Foundry: 24/7 Continuous Contender Hunter Daemon
Author: Dr. Roi Castrellon, DDS (DrNemo Caries Foundry)

Continuous evolutionary discovery service running under WSL systemd:
1. Queries data/foundry_contenders.sqlite for top Pareto contenders.
2. Evolves next-generation candidate cyclic peptides (point mutations, recombinations, Stephan-switch tuning).
3. Evaluates candidates using uncompressed 28A AutoDock Vina + Vinardo + OpenMM Amber14/GBn2 physics.
4. Checks oral biochemical barriers (Donnan ceiling, Stephan switch, protease resistance).
5. Commits new contenders to SQLite vault and mirrors to data/contenders_ledger.csv.
6. Logs Pareto frontier advancements and saves docked PDBQT poses.
"""

import os
import sys
import time
import random
import signal
import shutil
import logging
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from biophysics_engine import (
    build_macrocycle_3d,
    run_docking_vina_and_vinardo,
    relax_with_openmm
)
from solubility_shield import (
    calc_net_charge_at_ph,
    calc_stephan_switch,
    count_protease_cleavage_sites,
    MAX_DONNAN_CHARGE_PH6
)
from vault import ContenderVault

# Configure logging
LOG_DIR = REPO_ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "continuous_hunter.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("continuous_hunter")

TMP_DIR = Path("/tmp/foundry_hunter")
TMP_DIR.mkdir(parents=True, exist_ok=True)

RUNNING = True


def signal_handler(signum, frame):
    global RUNNING
    logger.info(f"Received shutdown signal ({signum}). Exiting gracefully...")
    RUNNING = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

SAFE_AA = "ACFGHMNPQRSTVWY"
MOTIFS = [
    "PHWR", "HWRP", "WRPW", "RPWH", "HPWH", "PWRP", "PRHW", "HWPY",
    "PHWP", "RWPH", "WPHR", "HPRW", "PRWH", "WPRH", "HRWP", "RHWP"
]


def generate_candidate(vault: ContenderVault) -> tuple[str, int]:
    """Generates a novel candidate with O(1) vault checking and indel mutations across 6..18 residues."""
    top_candidates = vault.get_top_contenders(limit=10)

    for _ in range(100):
        mode = random.random()
        if top_candidates and mode < 0.40:
            # 1. Point mutation of a top contender
            parent = random.choice(top_candidates)
            seq = parent["sequence"]
            gen = parent["generation"] + 1
            core = list(seq[1:-1])
            if core:
                idx = random.randint(0, len(core) - 1)
                core[idx] = random.choice(SAFE_AA)
                new_seq = "C" + "".join(core) + "C"
                if not vault.has_sequence(new_seq) and 6 <= len(new_seq) <= 18:
                    return new_seq, gen
        elif top_candidates and mode < 0.65:
            # 2. Variable-length indel mutation across 6..18 residues (4..16 core residues)
            parent = random.choice(top_candidates)
            seq = parent["sequence"]
            gen = parent["generation"] + 1
            core = list(seq[1:-1])
            if len(core) > 4 and random.random() < 0.5:
                # Deletion of an internal core residue (minimum 6 residues total)
                del_idx = random.randint(0, len(core) - 1)
                core.pop(del_idx)
            elif len(core) < 16:
                # Insertion of a safe amino acid (maximum 18 residues total)
                ins_idx = random.randint(0, len(core))
                core.insert(ins_idx, random.choice(SAFE_AA))
            new_seq = "C" + "".join(core) + "C"
            if not vault.has_sequence(new_seq) and 6 <= len(new_seq) <= 18:
                return new_seq, gen
        elif mode < 0.85:
            # 3. Motif crossover
            m1 = random.choice(MOTIFS)
            m2 = random.choice(MOTIFS)
            core_len = random.randint(4, 16)
            mid = ((m1 + m2) * 2)[:core_len]
            new_seq = f"C{mid}C"
            if not vault.has_sequence(new_seq) and 6 <= len(new_seq) <= 18:
                return new_seq, 4
        else:
            # 4. Conservative random drift
            core_len = random.randint(4, 16)
            mid = "".join(random.choice(SAFE_AA) for _ in range(core_len))
            new_seq = f"C{mid}C"
            if not vault.has_sequence(new_seq) and 6 <= len(new_seq) <= 18:
                return new_seq, 4

    # Fallback default variant
    fallback = f"CPHWRPW{random.choice(SAFE_AA)}C"
    return fallback, 5


def evaluate_candidate(seq: str, gen: int, vault: ContenderVault, priority_id: int = None):
    """Evaluates candidate using uncompressed 28A Vina + Vinardo + OpenMM."""
    cid = f"contender_g{gen:02d}_{seq}_{int(time.time())}"
    pdbqt_ligand = str(TMP_DIR / f"{cid}.pdbqt")
    pdb_ligand = str(TMP_DIR / f"{cid}.pdb")
    docked_3aic = str(TMP_DIR / f"{cid}_3aic_docked.pdbqt")
    docked_1smd = str(TMP_DIR / f"{cid}_1smd_docked.pdbqt")

    logger.info(f"Evaluating candidate {seq} (Gen {gen})...")
    if priority_id:
        vault.update_priority_status(priority_id, "DOCKING_3AIC")

    try:
        # 1. 3D Macrocycle Building
        heavy_atoms = build_macrocycle_3d(seq, pdbqt_ligand, out_pdb=pdb_ligand)

        # 2. Docking into 3AIC (Uncompressed 28A grid, exhaustiveness=8)
        dock_3aic = run_docking_vina_and_vinardo(
            pdbqt_ligand, target="3AIC", exhaustiveness=8, cpu=4, out_pdbqt=docked_3aic
        )
        vina_3aic = dock_3aic["vina_kcal"]
        vinardo_3aic = dock_3aic["vinardo_kcal"]
        le = round(-vina_3aic / heavy_atoms, 3)
        ss_dist = dock_3aic["ss_bond_angstrom"]
        pose_sha = dock_3aic["pose_sha256"]

        # 3. Counter-screening into 1SMD
        if priority_id:
            vault.update_priority_status(priority_id, "DOCKING_1SMD")

        dock_1smd = run_docking_vina_and_vinardo(
            pdbqt_ligand, target="1SMD", exhaustiveness=8, cpu=4, out_pdbqt=docked_1smd
        )
        vina_1smd = dock_1smd["vina_kcal"]
        selectivity_ddg = round(vina_3aic - vina_1smd, 2)

        # 4. OpenMM Amber14 / GBn2 Relaxation at 310.15 K
        try:
            openmm_kj = relax_with_openmm(pdb_ligand, temp_k=310.15)
        except Exception as e:
            logger.warning(f"OpenMM relaxation failed for {seq}: {e}")
            openmm_kj = None

        # 5. Solubility & Oral Biochemistry
        q72 = calc_net_charge_at_ph(seq, 7.2)
        q60 = calc_net_charge_at_ph(seq, 6.0)
        q52 = calc_net_charge_at_ph(seq, 5.2)
        stephan = calc_stephan_switch(seq)
        delta_q = stephan["delta_q_stephan"]
        protease = count_protease_cleavage_sites(seq)
        p_sites = protease["cleavage_site_count"]

        # Hard physical gate on disulfide geometry
        ss_ok = (ss_dist is not None and 1.95 <= ss_dist <= 2.25)
        donnan_ok = q60 <= MAX_DONNAN_CHARGE_PH6
        protease_ok = p_sites == 0
        stephan_ok = delta_q >= 1.0
        affinity_ok = vina_3aic < -7.5
        selectivity_ok = selectivity_ddg <= -0.80

        if not ss_ok:
            status = "FALSIFIED_BROKEN_DISULFIDE"
        elif donnan_ok and protease_ok and stephan_ok and affinity_ok and selectivity_ok:
            status = "CORROBORATED"
        elif not donnan_ok or not protease_ok or not stephan_ok:
            status = "FALSIFIED_ORAL_BARRIER"
        elif not selectivity_ok:
            status = "FALSIFIED_AMYLASE_CROSSREACTIVITY"
        else:
            status = "SUBTHRESHOLD_AFFINITY"

        # Store docked pose
        vault_poses_dir = REPO_ROOT / "data" / "poses"
        vault_poses_dir.mkdir(parents=True, exist_ok=True)
        perm_pose = vault_poses_dir / f"{cid}_3aic.pdbqt"
        if os.path.exists(docked_3aic):
            shutil.copyfile(docked_3aic, perm_pose)

        record = {
            "contender_id": cid,
            "sequence": seq,
            "generation": gen,
            "heavy_atoms": heavy_atoms,
            "vina_3aic_kcal": vina_3aic,
            "vinardo_3aic_kcal": vinardo_3aic,
            "ligand_efficiency": le,
            "vina_1smd_kcal": vina_1smd,
            "selectivity_ddg": selectivity_ddg,
            "openmm_relaxed_kj": openmm_kj,
            "ss_bond_angstrom": ss_dist,
            "q_ph72": q72,
            "q_ph60": q60,
            "q_ph52": q52,
            "delta_q_stephan": delta_q,
            "protease_sites": p_sites,
            "pareto_rank": 1 if status == "CORROBORATED" else (3 if "FALSIFIED" in status else 2),
            "falsification_status": status,
            "pose_sha256": pose_sha
        }

        vault.add_contender(record)
        logger.info(
            f"Contender {seq} evaluated: Vina={vina_3aic:.2f} kcal, Vinardo={vinardo_3aic:.2f} kcal, "
            f"LE={le:.3f}, DeltaDeltaG={selectivity_ddg:.2f}, Status={status}"
        )

        if priority_id:
            vault.update_priority_status(
                priority_id,
                "COMPLETED",
                result_vina=vina_3aic,
                result_status=status
            )

        # Check if champion
        current_champ = vault.get_pareto_champion()
        if current_champ and current_champ["contender_id"] == cid:
            logger.info(f"*** NEW PARETO CHAMPION DISCOVERED: {seq} (Vina: {vina_3aic:.2f} kcal/mol) ***")

        return record

    except Exception as e:
        if priority_id:
            vault.update_priority_status(priority_id, "FAILED", error=str(e))
        logger.error(f"Evaluation failed for {seq}: {e}", exc_info=True)
        raise


def run_discovery_cycle(vault: ContenderVault):
    """Executes a single discovery cycle (checking priority queue first)."""
    item = vault.get_next_priority_item()
    if item:
        p_id = item["id"]
        seq = item["sequence"]
        gen = item.get("generation", 4)
        logger.info(f"Processing priority queue item #{p_id}: {seq} (Gen {gen})")
        return evaluate_candidate(seq, gen, vault, priority_id=p_id)
    else:
        seq, gen = generate_candidate(vault)
        return evaluate_candidate(seq, gen, vault)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="DrNemo Continuous Contender Hunter")
    parser.add_argument("--single-cycle", action="store_true", help="Run exactly one evaluation cycle and exit")
    args = parser.parse_args()

    vault = ContenderVault()

    if args.single_cycle:
        logger.info("Executing single discovery cycle on demand...")
        record = run_discovery_cycle(vault)
        logger.info(f"Single cycle completed: {record.get('sequence')} ({record.get('vina_3aic_kcal')} kcal/mol)")
        return

    logger.info("=" * 70)
    logger.info("  DrNemo Caries Foundry: Continuous Hunter Daemon Starting")
    logger.info("=" * 70)
    logger.info(f"Connected to Contender Vault: {vault.get_count()} existing contenders.")

    cycle = 0
    while RUNNING:
        cycle += 1
        try:
            run_discovery_cycle(vault)
        except Exception as e:
            logger.error(f"Error in discovery cycle {cycle}: {e}", exc_info=True)

        # Sleep between iterations to respect CPU budget
        time.sleep(10)

    logger.info("Continuous Hunter Daemon stopped cleanly.")


if __name__ == "__main__":
    main()
