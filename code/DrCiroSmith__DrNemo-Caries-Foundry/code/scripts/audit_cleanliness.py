import re
import sys
from pathlib import Path

TARGETS = [
    'README.md',
    'docs/index.html',
    'manuscript/DrNemo_Preprint.tex',
    'dashboard.py',
    'falsification_engine.py',
    'gtfb_orchestrator.py',
    'solubility_shield.py',
    'vault.py',
    'foundry_manager.py',
    'scripts/continuous_hunter.py',
    'scripts/build_readme_visuals.py',
    'scripts/run_exhaustive_disproof.py'
]

repo_root = Path(__file__).parent.parent.resolve()

def check_file(rel_path):
    fpath = repo_root / rel_path
    if not fpath.exists():
        return [], []
    text = fpath.read_text(encoding='utf-8')
    
    dash_matches = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        # em-dash, en-dash, &mdash;
        if '\u2014' in line or '&mdash;' in line or '\u2013' in line:
            dash_matches.append((line_no, line))
        elif '---' in line:
            stripped = line.strip()
            # allow LaTeX \hline or markdown horizontal rule if line is just --- or markdown table row
            if rel_path.endswith('.tex') and stripped == '---':
                continue
            if rel_path.endswith('.md') and (stripped in ['---', '----', '-----'] or stripped.startswith('|')):
                continue
            dash_matches.append((line_no, line))
        elif '--' in line:
            stripped = line.strip()
            if '<!--' in stripped or '-->' in stripped or '|--' in stripped or '--|' in stripped:
                continue
            # check if it is a CLI flag or python comment
            if not any(flag in line for flag in ['--receptor', '--ligand', '--center', '--size', '--cpu', '--exhaustiveness', '--out', '--server', '--host', '--port', '--stat', '--config', '--seed', '--help', '--score_only', '--scoring', '--headless', '--address', '--enable-webgl', '--ignore-gpu-blocklist', '--enable-gpu-rasterization', '--use-gl', '--use-angle', '--single-cycle']):
                # In prose double hyphens like "word -- word" or "word--word"
                if re.search(r'\w\s*--\s*\w', line):
                    dash_matches.append((line_no, line))

    pronoun_matches = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for m in re.finditer(r'\b(we|our|us)\b', line, re.IGNORECASE):
            pronoun_matches.append((line_no, m.group(0), line))

    return dash_matches, pronoun_matches

def main():
    print("=== AUDIT CLEANLINESS REPORT ===")
    for target in TARGETS:
        d_matches, p_matches = check_file(target)
        print(f"\n[{target}]:")
        print(f"  Dash matches: {len(d_matches)}")
        for lno, line in d_matches[:8]:
            print(f"    L{lno}: {line.strip()[:85]}")
        print(f"  Pronoun matches: {len(p_matches)}")
        for lno, word, line in p_matches[:8]:
            print(f"    L{lno} ({word}): {line.strip()[:85]}")

if __name__ == '__main__':
    main()
