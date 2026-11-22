#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "demo_data" / "results"
DOCS_HTML = ROOT / "docs" / "index.html"

FILES = [
    "S_mutans_GtfB_Insoluble_variant_CRRRWWRRRRC.pdb",
    "S_mutans_GtfB_Insoluble_variant_CRRRWFRRRRC.pdb",
    "S_mutans_GtfB_Insoluble_variant_CRRRWWPRRRC.pdb",
    "S_mutans_GtfB_Insoluble_variant_CRRRAWPRRRC.pdb",
    "S_mutans_GtfB_Insoluble_variant_CRRAGWPRRRC.pdb"
]

embedded_pdbs = {}
for fname in FILES:
    p = RESULTS_DIR / fname
    if not p.exists():
        raise FileNotFoundError(f"Missing {p}")
    content = p.read_text(encoding="utf-8")
    embedded_pdbs[fname] = content
    print(f"Loaded {fname}: {len(content)/1024.0:.1f} KB")

json_str = json.dumps(embedded_pdbs)

html_text = DOCS_HTML.read_text(encoding="utf-8")

# Replace bio text
old_bio = "Practicing clinician with 5+ years of software engineering in AWS PostgreSQL, medical claims analytics, and local clinical AI systems."
new_bio = "Clinician-turned-engineer combining 6 years of clinical dentistry (DDS) with production AWS PostgreSQL data engineering, medical claims analytics, and clinical AI systems."
if old_bio in html_text:
    html_text = html_text.replace(old_bio, new_bio)
    print("Updated bio text.")
else:
    print("Bio text already up-to-date or not matched.")

start_tag = "const EMBEDDED_PDBS = "
end_tag = "const EVOLUTION_DATA"

start_idx = html_text.find(start_tag)
if start_idx == -1:
    raise ValueError("Could not find start_tag in HTML")

end_idx = html_text.find(end_tag, start_idx)
if end_idx == -1:
    raise ValueError("Could not find end_tag in HTML")

new_html = html_text[:start_idx] + start_tag + json_str + ";\n\n    " + html_text[end_idx:]
DOCS_HTML.write_text(new_html, encoding="utf-8")
print(f"docs/index.html updated successfully! Size: {DOCS_HTML.stat().st_size / 1024.0:.1f} KB")
