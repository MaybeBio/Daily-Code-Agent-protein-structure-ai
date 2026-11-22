"""
Foundry Manager: Core Controller for DrNemo Continuous Hunter & Custom Sequence Lab
Author: Dr. Roi Castrellon, DDS (DrNemo Caries Foundry)

Unified daemon management, process signaling (SIGSTOP/SIGCONT), priority queueing,
point mutation workbench, and biophysical pre-screening shared by:
- Streamlit dashboard (dashboard.py)
- CLI tool (foundry / ~/.local/bin/foundry)
- Systemd services (drnemo-discovery.service, drnemo-dashboard.service)
"""

import os
import sys
import signal
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

REPO_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from vault import ContenderVault
from solubility_shield import (
    calc_net_charge_at_ph,
    calc_stephan_switch,
    count_protease_cleavage_sites,
    MAX_DONNAN_CHARGE_PH6
)

LOG_FILE = REPO_ROOT / "data" / "logs" / "continuous_hunter.log"
SERVICE_NAME = "drnemo-discovery.service"
DASHBOARD_SERVICE_NAME = "drnemo-dashboard.service"
SAFE_AA = "ACFGHMNPQRSTVWY"
ALL_AA = "ACDEFGHIKLMNPQRSTVWY"


def _run_cmd(cmd: List[str]) -> Tuple[int, str, str]:
    """Helper to run a shell command cleanly without terminal prompts."""
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def get_child_pids(parent_pid: int) -> List[int]:
    """Retrieves all descendant child PIDs for a given parent PID."""
    if parent_pid <= 0:
        return []
    code, stdout, _ = _run_cmd(["pgrep", "-P", str(parent_pid)])
    if code == 0 and stdout:
        pids = []
        for line in stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                cpid = int(line)
                pids.append(cpid)
                pids.extend(get_child_pids(cpid))
        return list(set(pids))
    return []


def get_process_state(pid: int) -> Optional[str]:
    """Reads the process state from /proc/<pid>/status."""
    status_path = Path(f"/proc/{pid}/status")
    if not status_path.exists():
        return None
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("State:"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        return None
    return None


def get_daemon_status() -> Dict[str, Any]:
    """
    Inspects systemd user service state and /proc process state.
    Returns:
      status: 'ACTIVE' (🟢 HUNTING (Active)), 'PAUSED' (⏸ PAUSED), 'STOPPED' (🔴 STOPPED)
      badge: formatted text badge
      pid: main process PID (int or None)
      child_pids: list of child PIDs
      proc_state: raw process state string
      vault_count: total contenders in SQLite
      latest_contender: dict of latest contender
      top_leads: list of top 5 Pareto leads
      priority_queue: list of recent queue items
      last_logs: last 5 log lines
    """
    vault = ContenderVault()
    code, stdout, _ = _run_cmd([
        "systemctl", "--user", "show", SERVICE_NAME,
        "--property=ActiveState,SubState,MainPID"
    ])

    props = {}
    if code == 0:
        for line in stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()

    active_state = props.get("ActiveState", "inactive")
    main_pid_str = props.get("MainPID", "0")
    main_pid = int(main_pid_str) if main_pid_str.isdigit() else 0

    status = "STOPPED"
    badge = "🔴 STOPPED"
    proc_state = None
    child_pids = []

    if active_state == "active" and main_pid > 0:
        proc_state = get_process_state(main_pid)
        child_pids = get_child_pids(main_pid)
        if proc_state and ("T" in proc_state.split()[0]):
            status = "PAUSED"
            badge = "⏸ PAUSED"
        else:
            status = "ACTIVE"
            badge = "🟢 HUNTING (Active)"
    elif active_state == "active":
        status = "ACTIVE"
        badge = "🟢 HUNTING (Active)"
    else:
        status = "STOPPED"
        badge = "🔴 STOPPED"

    # Read last 5 log lines
    last_logs = []
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                last_logs = [line.strip() for line in lines[-5:] if line.strip()]
        except Exception:
            pass

    return {
        "status": status,
        "badge": badge,
        "active_state": active_state,
        "pid": main_pid if main_pid > 0 else None,
        "child_pids": child_pids,
        "proc_state": proc_state,
        "vault_count": vault.get_count(),
        "latest_contender": vault.get_latest_contender(),
        "top_leads": vault.get_top_contenders(limit=5),
        "priority_queue": vault.get_priority_queue(limit=10),
        "last_logs": last_logs
    }


def start_or_resume_daemon() -> Tuple[bool, str]:
    """Starts the service or resumes if paused (SIGCONT)."""
    current = get_daemon_status()
    pid = current.get("pid")

    if current["status"] == "PAUSED" and pid:
        # Resume main process and all children via SIGCONT
        all_pids = [pid] + current.get("child_pids", [])
        for p in all_pids:
            try:
                os.kill(p, signal.SIGCONT)
            except ProcessLookupError:
                pass
        return True, f"Resumed hunter process (PID {pid}) and children with SIGCONT."

    # Start service via systemctl
    code, stdout, stderr = _run_cmd(["systemctl", "--user", "start", SERVICE_NAME])
    if code == 0:
        return True, "Started drnemo-discovery.service cleanly."
    return False, f"Failed to start service: {stderr or stdout}"


def pause_daemon() -> Tuple[bool, str]:
    """Freezes the daemon and any active Vina children via SIGSTOP without losing progress."""
    current = get_daemon_status()
    pid = current.get("pid")

    if current["status"] == "STOPPED" or not pid:
        return False, "Daemon is not currently running; cannot pause."

    all_pids = [pid] + current.get("child_pids", [])
    paused_pids = []
    for p in all_pids:
        try:
            os.kill(p, signal.SIGSTOP)
            paused_pids.append(p)
        except ProcessLookupError:
            pass
        except Exception as e:
            return False, f"Failed to pause PID {p}: {e}"

    return True, f"Paused hunter processes (PIDs: {paused_pids}) at 0% CPU with SIGSTOP."


def restart_daemon() -> Tuple[bool, str]:
    """Unfreezes if paused, then restarts drnemo-discovery.service cleanly."""
    current = get_daemon_status()
    pid = current.get("pid")
    if current["status"] == "PAUSED" and pid:
        all_pids = [pid] + current.get("child_pids", [])
        for p in all_pids:
            try:
                os.kill(p, signal.SIGCONT)
            except Exception:
                pass

    code, stdout, stderr = _run_cmd(["systemctl", "--user", "restart", SERVICE_NAME])
    if code == 0:
        return True, "Restarted drnemo-discovery.service cleanly."
    return False, f"Failed to restart service: {stderr or stdout}"


def stop_daemon() -> Tuple[bool, str]:
    """Unfreezes if paused, then stops drnemo-discovery.service."""
    current = get_daemon_status()
    pid = current.get("pid")
    if current["status"] == "PAUSED" and pid:
        all_pids = [pid] + current.get("child_pids", [])
        for p in all_pids:
            try:
                os.kill(p, signal.SIGCONT)
            except Exception:
                pass

    code, stdout, stderr = _run_cmd(["systemctl", "--user", "stop", SERVICE_NAME])
    if code == 0:
        return True, "Stopped drnemo-discovery.service cleanly."
    return False, f"Failed to stop service: {stderr or stdout}"


def run_immediate_cycle() -> Tuple[bool, str]:
    """
    Runs 1 immediate discovery cycle in the background using python scripts/continuous_hunter.py --single-cycle.
    """
    python_bin = REPO_ROOT / ".venv" / "bin" / "python"
    script = REPO_ROOT / "scripts" / "continuous_hunter.py"

    if not python_bin.exists():
        python_bin = Path(sys.executable)

    try:
        subprocess.Popen(
            [str(python_bin), str(script), "--single-cycle"],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        return True, "Triggered 1 immediate evolutionary cycle in background worker."
    except Exception as e:
        return False, f"Failed to launch immediate cycle: {e}"


def compute_dynamic_box_size(seq: str) -> float:
    """Computes dynamic search box size (in Angstroms) based on sequence length."""
    seq_len = len(seq.strip())
    # Baseline 28.0 A for <= 9 residues, expanding by 1.2 A per additional residue
    return round(28.0 + max(0.0, (seq_len - 9) * 1.2), 2)


def get_torsion_warning(seq: str) -> Optional[str]:
    """Generates a warning if sequence length exceeds 20 residues due to Vina torsion explosion."""
    seq_len = len(seq.strip())
    if seq_len > 20:
        return (
            f"Caution: Macrocycle length ({seq_len} residues) exceeds 20 residues. "
            "AutoDock Vina search efficiency degrades exponentially with high rotatable torsion counts. "
            "Consider constraining key dihedrals or using rigid-core subsegments."
        )
    return None


def validate_cyclic_sequence(seq: str) -> Tuple[bool, str]:
    """Validates that a sequence is a valid cyclic peptide starting and ending with C (5 to 30 residues)."""
    seq = seq.strip().upper()
    if not seq:
        return False, "Sequence cannot be empty."
    if len(seq) < 5 or len(seq) > 30:
        return False, f"Sequence length {len(seq)} outside supported range (5-30 residues)."
    if not (seq.startswith("C") and seq.endswith("C")):
        return False, "Cyclic peptide must start and end with Cysteine ('C')."
    invalid_chars = set(seq) - set(ALL_AA)
    if invalid_chars:
        return False, f"Sequence contains invalid amino acid codes: {', '.join(sorted(invalid_chars))}"
    return True, seq


def precheck_sequence(seq: str) -> Dict[str, Any]:
    """
    Runs instant biophysical pre-checks:
    - Net Charge at pH 7.2, 6.0, 5.2
    - Stephan Delta Q switch
    - Donnan ceiling pass/fail (at pH 6.0)
    - Protease cleavage sites count
    - Dynamic box sizing and torsion count warning
    """
    seq = seq.strip().upper()
    q72 = calc_net_charge_at_ph(seq, 7.2)
    q60 = calc_net_charge_at_ph(seq, 6.0)
    q52 = calc_net_charge_at_ph(seq, 5.2)
    stephan = calc_stephan_switch(seq)
    delta_q = stephan["delta_q_stephan"]
    protease = count_protease_cleavage_sites(seq)
    p_sites = protease["cleavage_site_count"]

    donnan_ok = q60 <= MAX_DONNAN_CHARGE_PH6
    stephan_ok = delta_q >= 1.0
    protease_ok = p_sites == 0

    box_size = compute_dynamic_box_size(seq)
    torsion_warn = get_torsion_warning(seq)

    return {
        "sequence": seq,
        "length": len(seq),
        "q_ph72": q72,
        "q_ph60": q60,
        "q_ph52": q52,
        "delta_q_stephan": delta_q,
        "protease_sites": p_sites,
        "donnan_pass": donnan_ok,
        "stephan_pass": stephan_ok,
        "protease_pass": protease_ok,
        "precheck_passed": bool(donnan_ok and stephan_ok and protease_ok),
        "box_size_angstrom": box_size,
        "torsion_warning": torsion_warn
    }


def mutate_sequence(seq: str, pos: int, target_aa: str) -> Tuple[bool, str]:
    """
    Mutates position `pos` (1-based, 2..N-1) to `target_aa`.
    Disallows mutating terminal cysteines.
    """
    seq = seq.strip().upper()
    target_aa = target_aa.strip().upper()

    if pos < 2 or pos > len(seq) - 1:
        return False, f"Position {pos} is invalid. Can only mutate internal residues (2..{len(seq)-1})."
    if target_aa not in ALL_AA:
        return False, f"Target amino acid '{target_aa}' is invalid."

    seq_list = list(seq)
    seq_list[pos - 1] = target_aa
    mutated = "".join(seq_list)
    return True, mutated


def generate_all_single_site_variants(seq: str, aa_palette: str = SAFE_AA) -> List[str]:
    """Generates all single-site variants for positions 2..N-1."""
    seq = seq.strip().upper()
    variants = []
    for pos in range(1, len(seq) - 1):
        orig_aa = seq[pos]
        for aa in aa_palette:
            if aa != orig_aa:
                variant = seq[:pos] + aa + seq[pos + 1:]
                variants.append(variant)
    return variants


def enqueue_sequence_for_docking(seq: str, generation: int = 4) -> Tuple[bool, str, int]:
    """
    Validates, queues sequence into priority_queue in SQLite.
    If discovery daemon is stopped, starts a dedicated single-cycle background worker.
    """
    valid, res = validate_cyclic_sequence(seq)
    if not valid:
        return False, res, -1

    clean_seq = res
    vault = ContenderVault()
    item_id = vault.enqueue_priority(clean_seq, generation=generation)

    # Check daemon status
    daemon = get_daemon_status()
    if daemon["status"] == "STOPPED":
        # Launch dedicated worker
        run_immediate_cycle()
        msg = f"Enqueued #{item_id}: {clean_seq} (Daemon stopped -> Launched dedicated background worker)"
    elif daemon["status"] == "PAUSED":
        msg = f"Enqueued #{item_id}: {clean_seq} (Daemon is PAUSED: resume to begin processing)"
    else:
        msg = f"Enqueued #{item_id}: {clean_seq} (Active daemon will pick up on next cycle)"

    return True, msg, item_id
