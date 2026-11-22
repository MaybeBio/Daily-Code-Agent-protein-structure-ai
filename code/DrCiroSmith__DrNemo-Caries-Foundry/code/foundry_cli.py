#!/usr/bin/env python3
"""
DrNemo Caries Foundry — Command Line Interface
Author: Dr. Roi Castrellon, DDS (DrNemo Caries Foundry)

Unified CLI for daemon controls, custom cyclic sequence docking, and point-mutation experiments.
Usage:
  foundry status
  foundry start
  foundry stop
  foundry pause
  foundry resume
  foundry retry
  foundry dock <sequence>
  foundry mutate <sequence> <pos> <aa>
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

import foundry_manager as fm


def print_status():
    d = fm.get_daemon_status()
    print("=" * 72)
    print("  🧬 DrNemo Caries Foundry — 24/7 Discovery Daemon & Sequence Vault")
    print("=" * 72)
    pid_str = f"(PID: {d['pid']})" if d['pid'] else "(No active process)"
    print(f"  Daemon Status   : {d['badge']} {pid_str}")
    print(f"  Vault Contenders: {d['vault_count']} candidates evaluated")
    
    if d.get("latest_contender"):
        lat = d["latest_contender"]
        print(f"  Latest Contender: {lat.get('sequence')} ({lat.get('vina_3aic_kcal')} kcal/mol, Status: {lat.get('falsification_status')})")
        print(f"  Evaluated At    : {lat.get('evaluated_at_utc')}")

    print("\n" + "-" * 72)
    print("  🏆 Top 5 Pareto Leads (3AIC Affinity & Selectivity):")
    print("-" * 72)
    if d["top_leads"]:
        for i, lead in enumerate(d["top_leads"], 1):
            seq = lead.get("sequence", "N/A")
            vina = lead.get("vina_3aic_kcal", 0.0)
            sel = lead.get("selectivity_ddg", 0.0)
            stephan = lead.get("delta_q_stephan", 0.0)
            status = lead.get("falsification_status", "N/A")
            print(f"  {i}. {seq:<14} Vina: {vina:>6.2f} kcal/mol | Sel: {sel:>5.2f} | ΔQ: +{stephan:.2f} | {status}")
    else:
        print("  (No contenders in vault yet)")

    print("\n" + "-" * 72)
    print("  ⚡ Priority Queue (Recent Submissions):")
    print("-" * 72)
    if d["priority_queue"]:
        for q in d["priority_queue"][:5]:
            qid = q.get("id")
            qseq = q.get("sequence")
            qstat = q.get("status")
            qsub = q.get("submitted_at", "")[:19].replace("T", " ")
            qres = f"-> Vina: {q.get('result_vina')} kcal/mol ({q.get('result_status')})" if q.get("result_vina") else ""
            print(f"  [#{qid:<3}] {qseq:<14} Status: {qstat:<12} Submitted: {qsub} {qres}")
    else:
        print("  (Priority queue is currently empty)")

    print("\n" + "-" * 72)
    print("  📜 Recent Daemon Activity (Last 5 Logs):")
    print("-" * 72)
    if d["last_logs"]:
        for line in d["last_logs"]:
            print(f"  {line}")
    else:
        print("  (No logs recorded yet)")
    print("=" * 72)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__.strip())
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "status":
        print_status()

    elif cmd == "start":
        ok, msg = fm.start_or_resume_daemon()
        print(f"[{'OK' if ok else 'ERROR'}] {msg}")
        sys.exit(0 if ok else 1)

    elif cmd == "resume":
        ok, msg = fm.start_or_resume_daemon()
        print(f"[{'OK' if ok else 'ERROR'}] {msg}")
        sys.exit(0 if ok else 1)

    elif cmd == "pause":
        ok, msg = fm.pause_daemon()
        print(f"[{'OK' if ok else 'ERROR'}] {msg}")
        sys.exit(0 if ok else 1)

    elif cmd == "stop":
        ok, msg = fm.stop_daemon()
        print(f"[{'OK' if ok else 'ERROR'}] {msg}")
        sys.exit(0 if ok else 1)

    elif cmd == "retry" or cmd == "restart":
        ok, msg = fm.restart_daemon()
        print(f"[{'OK' if ok else 'ERROR'}] {msg}")
        sys.exit(0 if ok else 1)

    elif cmd == "dock":
        if len(sys.argv) < 3:
            print("Usage: foundry dock <sequence>")
            sys.exit(1)
        seq = sys.argv[2].strip().upper()
        # Run precheck first
        pre = fm.precheck_sequence(seq)
        print(f"\n🔍 Pre-check for {seq}:")
        print(f"   Net Charge (pH 7.2): {pre['q_ph72']:+.2f} | (pH 6.0): {pre['q_ph60']:+.2f} | (pH 5.2): {pre['q_ph52']:+.2f}")
        print(f"   Stephan Switch ΔQ  : +{pre['delta_q_stephan']:.2f} ({'PASS' if pre['stephan_pass'] else 'FAIL'})")
        print(f"   Donnan Ceiling     : {'PASS' if pre['donnan_pass'] else 'FAIL (q_ph60 > +2.0)'}")
        print(f"   Protease Cleavage  : {pre['protease_sites']} sites ({'RESISTANT' if pre['protease_pass'] else 'VULNERABLE'})")
        
        ok, msg, qid = fm.enqueue_sequence_for_docking(seq)
        if ok:
            print(f"\n🚀 [SUCCESS] {msg}")
            print(f"   Priority Task #{qid} queued for 28Å AutoDock Vina + Vinardo + 1SMD + OpenMM evaluation.")
        else:
            print(f"\n❌ [ERROR] {msg}")
            sys.exit(1)

    elif cmd == "mutate":
        if len(sys.argv) < 5:
            print("Usage: foundry mutate <sequence> <position> <target_aa>")
            sys.exit(1)
        orig_seq = sys.argv[2].strip().upper()
        try:
            pos = int(sys.argv[3])
        except ValueError:
            print("Error: position must be an integer (e.g. 2..N-1).")
            sys.exit(1)
        target_aa = sys.argv[4].strip().upper()

        ok, mutated = fm.mutate_sequence(orig_seq, pos, target_aa)
        if not ok:
            print(f"❌ [ERROR] {mutated}")
            sys.exit(1)

        print(f"\n🧬 Point Mutation: {orig_seq} [Pos {pos} -> {target_aa}] = {mutated}")
        pre = fm.precheck_sequence(mutated)
        print(f"   Net Charge (pH 7.2): {pre['q_ph72']:+.2f} | (pH 6.0): {pre['q_ph60']:+.2f} | (pH 5.2): {pre['q_ph52']:+.2f}")
        print(f"   Stephan Switch ΔQ  : +{pre['delta_q_stephan']:.2f} ({'PASS' if pre['stephan_pass'] else 'FAIL'})")
        print(f"   Donnan Ceiling     : {'PASS' if pre['donnan_pass'] else 'FAIL'}")
        print(f"   Protease Cleavage  : {pre['protease_sites']} sites ({'RESISTANT' if pre['protease_pass'] else 'VULNERABLE'})")

        ok, msg, qid = fm.enqueue_sequence_for_docking(mutated)
        if ok:
            print(f"\n🚀 [SUCCESS] {msg}")
            print(f"   Priority Task #{qid} queued for 28Å AutoDock Vina + Vinardo + 1SMD + OpenMM evaluation.")
        else:
            print(f"\n❌ [ERROR] {msg}")
            sys.exit(1)

    else:
        print(f"Unknown command: '{cmd}'. Run 'foundry --help' for usage.")
        sys.exit(1)


if __name__ == "__main__":
    main()
