"""Check enabled sources using representative read-only queries, without an LLM."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from drugevolve.evidence import EvidenceSession, load_config  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Check enabled cognition sources.")
    parser.add_argument(
        "--config", required=True, help="Path to evidence JSON configuration"
    )
    parser.add_argument(
        "--run-dir", required=True, help="Directory for test evidence records"
    )
    args = parser.parse_args()
    os.environ["DRUGEVOLVE_EVIDENCE_CONFIG"] = str(Path(args.config).resolve())
    try:
        cfg = load_config()
        if not cfg.get("enabled"):
            parser.error("The evidence tool is disabled in the config.")
        cases = [
            ("pubmed", "pubmed_search", "EGFR inhibitor"),
            ("chembl", "chembl_target", "CHEMBL203"),
            ("bindingdb", "bindingdb_target", "P00533"),
            ("string", "string_protein", "EGFR"),
        ]
        session = EvidenceSession(args.run_dir, cfg)
        failures = 0
        for source, operation, query in cases:
            if not cfg.get("sources", {}).get(source, {}).get("enabled"):
                continue
            result = session.query(operation, query)
            ok = result["status"] == "ok" and result.get("count", 0) > 0
            if not ok:
                failures += 1
            print(
                json.dumps(
                    {
                        "source": source,
                        "status": "ok" if ok else "error",
                        "count": result.get("count", 0),
                        "error": result.get("error")
                        or (None if ok else "no records returned"),
                    },
                    ensure_ascii=False,
                )
            )
        print("records:", session.root)
        return 1 if failures else 0
    except (ValueError, OSError) as exc:
        print("configuration error:", str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
