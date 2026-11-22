#!/usr/bin/env python3
"""
Compliance Logger - Append-only JSONL format.
Each event is one line of JSON, eliminating race conditions and file corruption
that occurred when 4+ workers simultaneously read/write a single large JSON file.
"""
import json
import os
import platform
import hashlib
import fcntl
from datetime import datetime
from pathlib import Path
import subprocess

BASE_DIR = Path.home() / "drnemo_research"
# JSONL file: one event per line, append-only — no corruption risk
AUDIT_LOG_FILE = BASE_DIR / "results" / "compliance_audit_trail.jsonl"

def get_system_specs():
    specs = {
        "os": platform.platform(),
        "python_version": platform.python_version(),
        "architecture": platform.machine()
    }
    try:
        nvidia_smi = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            text=True
        ).strip()
        specs["gpu"] = nvidia_smi
    except (subprocess.SubprocessError, FileNotFoundError):
        specs["gpu"] = "NVIDIA-SMI not accessible locally or not installed."
    return specs

def init_audit_log():
    if not AUDIT_LOG_FILE.parent.exists():
        AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not AUDIT_LOG_FILE.exists():
        header = {
            "record_type": "HEADER",
            "lab_initiation_time": datetime.now().isoformat(),
            "researcher": "Dr. Nemo (Dual Certified Dentist & Data Scientist)",
            "system_baseline": get_system_specs()
        }
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(header) + "\n")

def log_event(event_type, job_id, details, parameters):
    """
    Logs an immutable event. Uses append-only JSONL — safe for concurrent workers.
    Each record is one line: atomic write, no read-modify-write cycle.
    """
    if not AUDIT_LOG_FILE.exists():
        init_audit_log()

    event_record = {
        "record_type": "EVENT",
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        "job_id": job_id,
        "content_hash": hashlib.sha256(str(details).encode("utf-8")).hexdigest(),
        "details": details,
        "reproducibility_parameters": parameters
    }

    # Append one line — atomic, safe for concurrent workers
    with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(event_record) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)

def log_openfold_execution(job_id, payload):
    detail = "Executing OpenFold3 cloud prediction via NVIDIA NIM"
    params = {
        "api_endpoint": "https://health.api.nvidia.com/v1/biology/openfold/openfold3/predict",
        "output_format": payload.get("output_format", "pdb"),
        "molecules": payload.get("molecules", [])
    }
    log_event("STRUCTURAL_PREDICTION", job_id, detail, params)

def log_medgemma_inference(job_id, model_id, prompt, metrics):
    detail = "Generating clinical synthesis via LLM synthesizer"
    backend = "GitHub Models API (Cloud)" if "ollama/" not in model_id else "Ollama (Local)"
    params = {
        "model_id": model_id,
        "backend": backend,
        "inference_mode": "chat_completion",
        "input_metrics_analyzed": metrics,
        "prompt_template": prompt
    }
    log_event("CLINICAL_SYNTHESIS", job_id, detail, params)

def read_events():
    """Read all events from JSONL file. Useful for reporting."""
    if not AUDIT_LOG_FILE.exists():
        return []
    events = []
    with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # Skip any corrupted lines
    return events

if __name__ == "__main__":
    init_audit_log()
    print("Compliance Audit Logger Initialized (JSONL format).")
    print("Audit file: " + str(AUDIT_LOG_FILE))
