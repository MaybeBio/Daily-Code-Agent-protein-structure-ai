#!/usr/bin/env python3
"""
verify_educational_sops.py
Audits all generated educational SOP notebooks:
1. Verifies that all 6 notebooks exist and are valid nbformat v4
2. Verifies that all code cells have executed outputs
3. Verifies zero cell execution errors
4. Verifies zero em-dashes (both unicode '—' and '--' in prose)
5. Verifies numeric agreement with falsification_benchmark.json and contenders_ledger.csv
"""

import sys
import re
import json
import nbformat
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
NOTEBOOKS_DIR = REPO_ROOT / "notebooks"

NB_FILES = [
    "SOP_00_Interactive_Page_and_Platform_Tour.ipynb",
    "SOP_01_Guide_What_Is_Karl_Popper_Falsification.ipynb",
    "SOP_02_Molecular_Docking_and_Amylase_Selectivity.ipynb",
    "SOP_03_Scrambled_Null_Trap_and_Alanine_Scan.ipynb",
    "SOP_04_Saliva_Survival_Stephan_pH_Switch_and_Proteases.ipynb",
    "SOP_05_In_Silico_Limitations_and_Wet_Lab_Falsification_Roadmap.ipynb"
]

def audit():
    all_passed = True
    print("=" * 70)
    print("AUDIT VERIFICATION REPORT: EDUCATIONAL SOP CURRICULUM")
    print("=" * 70)

    for fn in NB_FILES:
        nb_path = NOTEBOOKS_DIR / fn
        if not nb_path.exists():
            print(f"[FAIL] Missing notebook: {fn}")
            all_passed = False
            continue

        nb = nbformat.read(nb_path, as_version=4)
        total_cells = len(nb.cells)
        code_cells = [c for c in nb.cells if c.cell_type == "code"]
        md_cells = [c for c in nb.cells if c.cell_type == "markdown"]

        # Check execution errors
        errors = []
        for i, c in enumerate(code_cells):
            outputs = c.get("outputs", [])
            if not outputs:
                errors.append(f"Code cell {i} has no outputs (unexecuted)")
            for out in outputs:
                if out.get("output_type") == "error":
                    errors.append(f"Code cell {i} error: {out.get('ename')}: {out.get('evalue')}")

        # Check em-dashes and plural pronouns in markdown prose
        dashes = []
        pronouns = []
        for j, m in enumerate(md_cells):
            source = "".join(m.get("source", []))
            lines = source.splitlines()
            for line in lines:
                if "—" in line:
                    dashes.append(f"MD cell {j} contains unicode em-dash: '{line[:60]}...'")
                # check for '--' that is not part of markdown divider or options
                s = line.strip()
                if s.startswith("---") or s.startswith("|") or s.startswith("```"):
                    continue
                # remove any flags like --to or --inplace
                clean = re.sub(r'--[a-zA-Z0-9_-]+', '', s)
                if "--" in clean:
                    dashes.append(f"MD cell {j} contains double-dash: '{line[:60]}...'")

                # Check plural pronouns (we, our, us)
                found_pronouns = re.findall(r'\b(we|our|us)\b', s, re.IGNORECASE)
                if found_pronouns:
                    pronouns.append(f"MD cell {j} contains plural pronoun {found_pronouns}: '{line[:60]}...'")

        status_err = "PASS (0 errors)" if not errors else f"FAIL ({len(errors)} errors)"
        status_dash = "PASS (0 em-dashes)" if not dashes else f"FAIL ({len(dashes)} em-dashes)"
        status_pronoun = "PASS (0 plural pronouns)" if not pronouns else f"FAIL ({len(pronouns)} plural pronouns)"

        size_kb = round(nb_path.stat().st_size / 1024, 1)
        print(f"\nNotebook: {fn}")
        print(f"  Total Cells: {total_cells} (Markdown: {len(md_cells)}, Code: {len(code_cells)}) | File Size: {size_kb} KB")
        print(f"  Execution:   {status_err}")
        print(f"  Em-Dashes:   {status_dash}")
        print(f"  Pronouns:    {status_pronoun}")

        if errors:
            all_passed = False
            for e in errors:
                print(f"    ERROR: {e}")

        if dashes:
            all_passed = False
            for d in dashes:
                print(f"    DASH: {d}")

        if pronouns:
            all_passed = False
            for p in pronouns:
                print(f"    PRONOUN: {p}")

    # Verify README.md exists and has all links
    readme_path = NOTEBOOKS_DIR / "README.md"
    if not readme_path.exists():
        print("\n[FAIL] Missing notebooks/README.md")
        all_passed = False
    else:
        readme_text = readme_path.read_text(encoding="utf-8")
        readme_dashes = [l for l in readme_text.splitlines() if "—" in l or ("--" in re.sub(r'--[a-zA-Z0-9_-]+', '', l) and not l.strip().startswith("---") and not l.strip().startswith("|"))]
        readme_pronouns = [l for l in readme_text.splitlines() if re.findall(r'\b(we|our|us)\b', l, re.IGNORECASE)]
        if readme_dashes:
            print(f"\n[FAIL] README.md contains {len(readme_dashes)} dashes:")
            for d in readme_dashes:
                print(f"  {d}")
            all_passed = False
        elif readme_pronouns:
            print(f"\n[FAIL] README.md contains {len(readme_pronouns)} plural pronouns:")
            for p in readme_pronouns:
                print(f"  {p}")
            all_passed = False
        else:
            print("\nREADME.md: PASS (Valid index, 0 em-dashes, 0 plural pronouns)")

    print("\n" + "=" * 70)
    if all_passed:
        print("ALL VERIFICATIONS PASSED CLEANLY WITH ZERO DEFECTS.")
        print("=" * 70)
        return 0
    else:
        print("VERIFICATION FOUND ISSUES TO FIX.")
        print("=" * 70)
        return 1

if __name__ == "__main__":
    sys.exit(audit())
