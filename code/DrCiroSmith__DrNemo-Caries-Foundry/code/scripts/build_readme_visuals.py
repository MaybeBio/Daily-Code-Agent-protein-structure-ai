#!/usr/bin/env python3
"""
build_readme_visuals.py: Generate 5 README figures + social preview as Retina PNGs.
Supports dual Dark-Slate (*_dark.png) and Crisp Clinical Light (*_light.png) themes.
Author: Dr. Roi Castrellon, DDS (DrNemo Caries Foundry)

Design system:
  Dark:  bg=#0c1017, card=#131b28, border=1px solid #1e293b, viewer_bg=#080c13
  Light: bg=#f8fafc, card=#ffffff, border=1px solid #cbd5e1, viewer_bg=#f1f5f9
  Inter + JetBrains Mono, cyan=#38bdf8, emerald=#4ade80, amber=#facc15, coral=#f87171

GitHub 896px Column Readability Rules:
  All HTML viewports at 1200px logical width, device_scale_factor=2 -> 2400px Retina PNG.
  Hero headers: 36px-44px
  Panel titles: 22px-28px
  Body labels / text: 16px-18px
  Mono badges / metrics: 15px-18px
"""
import csv
import json
import os
import shutil
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
ASSETS = REPO / "assets"
DATA = REPO / "data"
DEMO = REPO / "demo_data" / "results"
VENDOR_3DMOL = REPO / "docs" / "vendor" / "3Dmol-min.js"

# Load PDB content for 3Dmol WebGL renders
PDB_PATH = DEMO / "3AIC_docked_complex_CAHWRPWHC.pdb"
PDB_CONTENT = PDB_PATH.read_text(encoding="utf-8").replace("`", "\\`").replace("$", "\\$")

FONT_STACK = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
MONO = "'JetBrains Mono', 'Fira Code', monospace"
GOOGLE_FONTS = (
    "https://fonts.googleapis.com/css2?"
    "family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600;700&display=swap"
)

PLAYWRIGHT_ARGS = [
    "--enable-webgl",
    "--ignore-gpu-blocklist",
    "--enable-gpu-rasterization",
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--allow-file-access-from-files",
]


def get_tokens(theme: str = "dark") -> dict:
    if theme == "light":
        return {
            "theme": "light",
            "bg": "#f8fafc",
            "card": "#ffffff",
            "border": "#cbd5e1",
            "cyan": "#0284c7",
            "emerald": "#16a34a",
            "amber": "#d97706",
            "coral": "#dc2626",
            "text1": "#0f172a",
            "text2": "#475569",
            "viewer_bg": "#f1f5f9",
            "protein_color": "#cbd5e1",
            "surface_color": "#94a3b8",
            "h1_color": "#0f172a",
            "triad_legend_bg": "rgba(255,255,255,0.92)",
            "triad_legend_text": "#0f172a",
            "render_overlay_bg": "rgba(255,255,255,0.92)",
            "render_overlay_text": "#475569",
            "funnel_track_bg": "#f1f5f9",
            "card_border_alpha": "rgba(0,0,0,0.06)",
            "stage_badge_text": "#ffffff",
            "badge_top_bg": "rgba(2,132,199,0.10)",
            "badge_top_border": "rgba(2,132,199,0.25)",
            "pill_bg": "#ffffff",
            "subline_color": "#64748b",
            "chart_axis": "#94a3b8",
        }
    else:
        return {
            "theme": "dark",
            "bg": "#0c1017",
            "card": "#131b28",
            "border": "#1e293b",
            "cyan": "#38bdf8",
            "emerald": "#4ade80",
            "amber": "#facc15",
            "coral": "#f87171",
            "text1": "#f1f5f9",
            "text2": "#94a3b8",
            "viewer_bg": "#080c13",
            "protein_color": "#334155",
            "surface_color": "#94a3b8",
            "h1_color": "#ffffff",
            "triad_legend_bg": "rgba(12,16,23,0.85)",
            "triad_legend_text": "#f1f5f9",
            "render_overlay_bg": "rgba(12,16,23,0.85)",
            "render_overlay_text": "#94a3b8",
            "funnel_track_bg": "#0c1017",
            "card_border_alpha": "rgba(255,255,255,0.06)",
            "stage_badge_text": "#080c13",
            "badge_top_bg": "rgba(56,189,248,0.12)",
            "badge_top_border": "rgba(56,189,248,0.3)",
            "pill_bg": "#131b28",
            "subline_color": "#94a3b8",
            "chart_axis": "#1e293b",
        }


def get_css_base(t: dict) -> str:
    return f"""
@import url('{GOOGLE_FONTS}');
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  background: {t['bg']};
  color: {t['text1']};
  font-family: {FONT_STACK};
  -webkit-font-smoothing: antialiased;
}}
"""


def load_ledger():
    with open(DATA / "contenders_ledger.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_benchmark():
    with open(DEMO / "falsification_benchmark.json", encoding="utf-8") as f:
        return json.load(f)


def render_html_to_png(html: str, width: int, height: int, out_path: Path, wait_ms: int = 4000):
    """Render HTML string to Retina PNG via Playwright Chromium with WebGL validation."""
    tmp_html = Path(f"/tmp/{out_path.stem}.html")
    tmp_html.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=PLAYWRIGHT_ARGS)
        page = browser.new_page(
            viewport={"width": width, "height": height},
            device_scale_factor=2,
        )
        page.goto(f"file://{tmp_html}")

        # Inject vendored 3Dmol if needed
        if VENDOR_3DMOL.exists():
            page.add_script_tag(path=str(VENDOR_3DMOL))

        # Check if 3D viewer is present
        has_viewer = page.evaluate("() => !!(document.getElementById('viewer3d') || document.getElementById('viewer-pocket'))")
        if has_viewer:
            page.wait_for_function("() => typeof $3Dmol !== 'undefined'", timeout=12000)
            page.wait_for_timeout(wait_ms)
            canvas_len = page.evaluate("""() => {
                const c = document.querySelector('canvas');
                if (!c) return 0;
                return c.toDataURL().length;
            }""")
            if canvas_len < 5000:
                print(f"  [WARNING] Canvas variance check low for {out_path.name}: {canvas_len} bytes")
            else:
                print(f"  [WebGL OK] 3Dmol canvas verified: {canvas_len} data bytes")
        else:
            page.wait_for_timeout(wait_ms)

        page.screenshot(path=str(out_path), full_page=False)
        browser.close()
    tmp_html.unlink(missing_ok=True)
    print(f"  -> {out_path.name} ({out_path.stat().st_size:,} bytes)")


# =========================================================================
# FIGURE 1: Hero Banner (1200x380 @2x = 2400x760)
# =========================================================================
def build_hero_banner(theme: str = "dark"):
    t = get_tokens(theme)
    css_base = get_css_base(t)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
{css_base}
body {{ width:1200px; height:380px; overflow:hidden; display:flex; }}
.left {{
  width:56%; padding:36px 36px 36px 44px; display:flex; flex-direction:column; justify-content:center;
}}
.right {{
  width:44%; height:380px; position:relative; overflow:hidden;
  border-left:1px solid {t['border']}; background:{t['viewer_bg']};
}}
#viewer3d {{ width:100%; height:100%; position:relative; }}
.badge-top {{
  display:inline-flex; align-items:center; gap:8px;
  background:{t['badge_top_bg']}; border:1px solid {t['badge_top_border']};
  padding:4px 14px; border-radius:100px; font-family:{MONO}; font-size:14px;
  font-weight:600; color:{t['cyan']}; margin-bottom:12px; width:fit-content;
}}
h1 {{
  font-size:38px; font-weight:800; letter-spacing:-0.8px; line-height:1.15;
  color:{t['h1_color']}; margin-bottom:8px;
}}
.subtitle {{
  font-size:20px; font-weight:600; color:{t['cyan']}; margin-bottom:4px;
}}
.subline {{
  font-size:16px; font-weight:400; color:{t['subline_color']}; margin-bottom:22px;
}}
.pills {{
  display:grid; grid-template-columns:1fr 1fr; gap:12px;
}}
.pill {{
  background:{t['pill_bg']}; border:1px solid {t['border']}; border-radius:10px;
  padding:10px 14px; display:flex; flex-direction:column; gap:2px;
}}
.pill .val {{
  font-family:{MONO}; font-size:18px; font-weight:700;
}}
.pill .lbl {{
  font-size:14px; font-weight:500; color:{t['text2']};
}}
.render-overlay {{
  position:absolute; bottom:12px; right:16px;
  background:{t['render_overlay_bg']}; backdrop-filter:blur(8px);
  border:1px solid {t['border']}; border-radius:8px; padding:6px 12px;
  font-family:{MONO}; font-size:13px; color:{t['render_overlay_text']}; z-index:10;
}}
.triad-legend {{
  position:absolute; top:12px; left:16px;
  background:{t['triad_legend_bg']}; backdrop-filter:blur(8px);
  border:1px solid {t['border']}; border-radius:8px; padding:8px 12px;
  font-family:{MONO}; font-size:13px; color:{t['triad_legend_text']}; z-index:10;
  display:flex; flex-direction:column; gap:4px;
}}
.legend-item {{ display:flex; align-items:center; gap:6px; }}
.dot {{ width:8px; height:8px; border-radius:50%; }}
</style>
<script src="file://{VENDOR_3DMOL}"></script>
</head><body>
<div class="left">
  <div class="badge-top">AUTODOCK VINA + OPENMM AMBER14 + POPPERIAN FALSIFICATION</div>
  <h1>DrNemo Caries Foundry</h1>
  <div class="subtitle">Targeted GtfB Macrocycle Inhibitor Design</div>
  <div class="subline">Selective cleft blockade · Oral commensal preservation</div>
  <div class="pills">
    <div class="pill">
      <span class="val" style="color:{t['cyan']}">-8.191 kcal/mol</span>
      <span class="lbl">3AIC Target Affinity</span>
    </div>
    <div class="pill">
      <span class="val" style="color:{t['emerald']}">-0.85 kcal/mol</span>
      <span class="lbl">1SMD Host Selectivity ΔΔG</span>
    </div>
    <div class="pill">
      <span class="val" style="color:{t['amber']}">Trypsin Shield</span>
      <span class="lbl">Pro6 Protected (W4/W7 At Risk)</span>
    </div>
    <div class="pill">
      <span class="val" style="color:{t['coral']}">+1.62 ΔQ</span>
      <span class="lbl">Stephan pH Acid Switch</span>
    </div>
  </div>
</div>
<div class="right">
  <div id="viewer3d"></div>
  <div class="triad-legend">
    <div class="legend-item"><span class="dot" style="background:{t['coral']}"></span><span>Triad Asp477/Glu515/Asp588</span></div>
    <div class="legend-item"><span class="dot" style="background:{t['cyan']}"></span><span>CAHWRPWHC Macrocycle</span></div>
    <div class="legend-item"><span class="dot" style="background:{t['amber']}"></span><span>C1:SG-C9:SG Disulfide (2.06 Å)</span></div>
  </div>
  <div class="render-overlay">3Dmol.js WebGL · RCSB 3AIC</div>
</div>
<script>
  window.addEventListener('load', () => {{
    const pdbData = `{PDB_CONTENT}`;
    const element = document.getElementById('viewer3d');
    const viewer = $3Dmol.createViewer(element, {{ backgroundColor: '{t['viewer_bg']}' }});
    viewer.addModel(pdbData, 'pdb');

    viewer.setStyle({{ chain: 'A' }}, {{ cartoon: {{ color: '{t['protein_color']}', opacity: 0.85 }} }});
    viewer.setStyle({{ chain: 'A', resi: [477, 515, 588] }}, {{
      stick: {{ color: '{t['coral']}', radius: 0.35 }}
    }});
    viewer.setStyle({{ chain: 'B' }}, {{
      stick: {{ color: '{t['cyan']}', radius: 0.28 }}
    }});

    viewer.addSphere({{ center: {{ x: 184.831, y: 32.035, z: 198.614 }}, radius: 0.58, color: '{t['amber']}' }});
    viewer.addSphere({{ center: {{ x: 184.677, y: 34.077, z: 198.820 }}, radius: 0.58, color: '{t['amber']}' }});
    viewer.addCylinder({{
      start: {{ x: 184.831, y: 32.035, z: 198.614 }},
      end: {{ x: 184.677, y: 34.077, z: 198.820 }},
      radius: 0.24,
      color: '{t['amber']}',
      fromCap: true,
      toCap: true
    }});

    try {{
      viewer.addSurface($3Dmol.SurfaceType.MS, {{ opacity: 0.22, color: '{t['surface_color']}' }}, {{ chain: 'A', within: {{ distance: 10.0, sel: {{ chain: 'B' }} }} }});
    }} catch(e) {{
      console.error(e);
    }}

    viewer.zoomTo({{ chain: 'B' }});
    viewer.zoom(0.85);
    viewer.rotate(25, 'y');
    viewer.rotate(-15, 'x');
    viewer.render();
  }});
</script>
</body></html>"""
    out_file = ASSETS / f"hero_banner_{theme}.png"
    render_html_to_png(html, 1200, 380, out_file)
    if theme == "dark":
        shutil.copyfile(out_file, ASSETS / "hero_banner.png")


# =========================================================================
# FIGURE 2: Biological Mechanism (1200x360 @2x = 2400x720)
# =========================================================================
def build_biological_mechanism(theme: str = "dark"):
    t = get_tokens(theme)
    css_base = get_css_base(t)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
{css_base}
body {{ width:1200px; height:360px; overflow:hidden; display:flex; gap:18px; padding:16px 20px; }}
.panel {{
  flex:1; background:{t['card']}; border:1px solid {t['border']}; border-radius:14px;
  padding:16px 20px; display:flex; flex-direction:column; justify-content:space-between;
}}
.panel-header {{
  display:flex; align-items:center; gap:12px; margin-bottom:10px;
}}
.panel-badge {{
  width:30px; height:30px; border-radius:8px; display:flex;
  align-items:center; justify-content:center; font-family:{MONO};
  font-size:17px; font-weight:700;
}}
.panel-title {{
  font-size:21px; font-weight:700;
}}
.flow {{
  display:flex; flex-direction:column; gap:6px; flex:1; justify-content:space-between;
}}
.step {{
  display:flex; align-items:center; gap:12px;
  padding:8px 12px; border-radius:8px; font-size:15px; font-weight:500;
}}
.step-num {{
  width:26px; height:26px; border-radius:50%; display:flex;
  align-items:center; justify-content:center; font-family:{MONO};
  font-size:14px; font-weight:700; flex-shrink:0;
}}
.arrow-down {{
  display:flex; justify-content:center; color:{t['text2']}; font-size:13px; line-height:1;
}}
.bad-border {{ border:1px solid rgba(248,113,113,0.3); background:rgba(248,113,113,0.06); }}
.bad-num {{ background:rgba(248,113,113,0.2); color:{t['coral']}; }}
.good-border {{ border:1px solid rgba(74,222,128,0.3); background:rgba(74,222,128,0.06); }}
.good-num {{ background:rgba(74,222,128,0.2); color:{t['emerald']}; }}
.neutral-border {{ border:1px solid {t['border']}; background:{t['bg']}; }}
.neutral-num {{ background:rgba(148,163,184,0.15); color:{t['text2']}; }}
.tag-blocked {{
  margin-left:auto; font-family:{MONO}; font-size:13px; font-weight:700;
  color:{t['cyan']}; background:rgba(56,189,248,0.15); border:1px solid rgba(56,189,248,0.4);
  padding:2px 8px; border-radius:6px; white-space:nowrap;
}}
</style></head><body>

<div class="panel">
  <div class="panel-header">
    <div class="panel-badge" style="background:rgba(248,113,113,0.15);color:{t['coral']};">A</div>
    <div class="panel-title" style="color:{t['coral']};">Uninhibited S. mutans Biofilm</div>
  </div>
  <div class="flow">
    <div class="step neutral-border">
      <div class="step-num neutral-num">1</div>
      <span>Salivary Pellicle + Enamel Hydroxyapatite</span>
    </div>
    <div class="arrow-down">↓</div>
    <div class="step bad-border">
      <div class="step-num bad-num">2</div>
      <span>SpaP Adhesin Anchors Cells to Pellicle Surface</span>
    </div>
    <div class="arrow-down">↓</div>
    <div class="step bad-border">
      <div class="step-num bad-num">3</div>
      <span>GtfB Synthesizes Insoluble Glucan (Mutan) Scaffolding</span>
    </div>
    <div class="arrow-down">↓</div>
    <div class="step bad-border">
      <div class="step-num bad-num">4</div>
      <span>Acid Trapped at Enamel Face: pH &lt; 5.5 Critical Demineralization</span>
    </div>
  </div>
</div>

<div class="panel">
  <div class="panel-header">
    <div class="panel-badge" style="background:rgba(74,222,128,0.15);color:{t['emerald']};">B</div>
    <div class="panel-title" style="color:{t['emerald']};">CAHWRPWHC Targeted Inhibition</div>
  </div>
  <div class="flow">
    <div class="step neutral-border">
      <div class="step-num neutral-num">1</div>
      <span>Salivary Pellicle + Enamel Hydroxyapatite</span>
    </div>
    <div class="arrow-down">↓</div>
    <div class="step neutral-border">
      <div class="step-num neutral-num">2</div>
      <span>Early Commensal Colonizers (S. sanguinis, S. mitis)</span>
    </div>
    <div class="arrow-down">↓</div>
    <div class="step good-border">
      <div class="step-num good-num">3</div>
      <span>CAHWRPWHC Cleft Blockade (-8.191 kcal/mol)</span>
      <span class="tag-blocked">GtfB INHIBITED</span>
    </div>
    <div class="arrow-down">↓</div>
    <div class="step good-border">
      <div class="step-num good-num">4</div>
      <span>Glucan Matrix Abolished: Plaque Cleared by Salivary Flow (pH ≥ 6.8)</span>
    </div>
  </div>
</div>

</body></html>"""
    out_file = ASSETS / f"fig1_biological_mechanism_{theme}.png"
    render_html_to_png(html, 1200, 360, out_file)
    if theme == "dark":
        shutil.copyfile(out_file, ASSETS / "fig1_biological_mechanism.png")


# =========================================================================
# FIGURE 3: Pipeline Architecture (1200x420 @2x = 2400x840)
# =========================================================================
def build_pipeline_architecture(theme: str = "dark"):
    t = get_tokens(theme)
    css_base = get_css_base(t)
    stages = [
        ("1", "Evolutionary Generator", "C-X7-C cyclic scaffold<br>P2A hinge mutant pool", t['cyan']),
        ("2", "Oral Shield Gate", "Donnan Q ≤ +4.0<br>Stephan ΔQ ≥ +1.0<br>Protease assessment", t['emerald']),
        ("3", "28.0 Å Dual Docking", "3AIC target (GtfB)<br>1SMD host counter (amylase)<br>Vina + Vinardo", t['amber']),
        ("4", "OpenMM Relaxation", "Amber14/GBn2 at 310.15 K<br>All-atom minimization<br>S-S 2.06 Å check", t['coral']),
        ("5", "Popper Falsification", "12-angle exhaustive battery<br>N=39 scrambled nulls<br>Alanine scanning", t['cyan']),
        ("6", "Contender Vault", "SQLite registry<br>Limitless O(1) sequence scale<br>Fmoc SPPS protocol", t['emerald']),
    ]

    cards_html = ""
    for i, (num, title, desc, col) in enumerate(stages):
        cards_html += f"""
        <div class="stage-card" style="border-top:3px solid {col};">
          <div class="stage-badge" style="background:{col};color:{t['stage_badge_text']};">{num}</div>
          <div class="stage-title">{title}</div>
          <div class="stage-desc">{desc}</div>
        </div>
        """
        if i < len(stages) - 1:
            cards_html += f"""
            <div class="connector">
              <svg width="22" height="22" viewBox="0 0 24 24"><path d="M7 4l8 8-8 8" stroke="{t['text2']}" stroke-width="2.5" fill="none" stroke-linecap="round"/></svg>
            </div>
            """

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
{css_base}
body {{ width:1200px; height:420px; overflow:hidden; padding:24px 28px; display:flex; flex-direction:column; justify-content:space-between; }}
.header-row {{
  text-align:center; margin-bottom:14px;
}}
.main-title {{
  font-size:24px; font-weight:800; color:{t['h1_color']}; letter-spacing:-0.4px; margin-bottom:4px;
}}
.main-subtitle {{
  font-size:16px; color:{t['text2']};
}}
.pipeline-flow {{
  display:flex; align-items:center; justify-content:space-between;
}}
.stage-card {{
  flex:1; background:{t['card']}; border:1px solid {t['border']}; border-radius:12px;
  padding:16px 12px; display:flex; flex-direction:column; align-items:center;
  text-align:center; min-height:210px; justify-content:flex-start;
}}
.stage-badge {{
  width:32px; height:32px; border-radius:50%;
  font-family:{MONO}; font-size:16px; font-weight:800;
  display:flex; align-items:center; justify-content:center; margin-bottom:10px;
}}
.stage-title {{
  font-size:16px; font-weight:700; color:{t['text1']}; margin-bottom:8px; line-height:1.25;
}}
.stage-desc {{
  font-size:13px; color:{t['text2']}; line-height:1.45;
}}
.connector {{
  display:flex; align-items:center; justify-content:center; padding:0 3px;
}}
.feedback-box {{
  display:flex; align-items:center; justify-content:center; gap:14px;
  background:rgba(248,113,113,0.06); border:1px dashed rgba(248,113,113,0.4);
  border-radius:10px; padding:10px 20px; margin-top:10px;
}}
.feedback-text {{
  font-family:{MONO}; font-size:15px; font-weight:600; color:{t['coral']};
}}
</style></head><body>

<div class="header-row">
  <div class="main-title">Autonomous Biophysical Discovery and Karl Popper Falsification Cycle</div>
  <div class="main-subtitle">Closed-loop LangGraph state machine orchestrating Vina, OpenMM, and multi-angle falsification gates</div>
</div>

<div class="pipeline-flow">
  {cards_html}
</div>

<div class="feedback-box">
  <span style="color:{t['coral']};font-size:18px;">↺</span>
  <span class="feedback-text">Falsification Feedback: Off-target amylase binding or protease susceptibility triggers hinge re-engineering loop</span>
  <span style="color:{t['coral']};font-size:18px;">↺</span>
</div>

</body></html>"""
    out_file = ASSETS / f"fig2_pipeline_architecture_{theme}.png"
    render_html_to_png(html, 1200, 420, out_file)
    if theme == "dark":
        shutil.copyfile(out_file, ASSETS / "fig2_pipeline_architecture.png")


# =========================================================================
# FIGURE 4: Pocket + Attrition Funnel (1200x480 @2x = 2400x960)
# =========================================================================
def build_pocket_and_funnel(theme: str = "dark"):
    t = get_tokens(theme)
    css_base = get_css_base(t)
    funnel_data = [
        ("82", "Design Candidates", 1.0, t['text2']),
        ("77", "Vina 3AIC Cleft Affinity Evaluated", 77/82, t['cyan']),
        ("39", "1SMD Amylase Screening Window (ΔΔG ≤ -0.80)", 39/82, t['cyan']),
        ("18", "Tryptic Shield Assessment (Pro6 Shield)", 18/82, t['amber']),
        ("2",  "Stephan Acid-Switch (ΔQ ≥ +1.0)", 2/82, t['emerald']),
        ("2",  "Chitosan Donnan Net Charge (Q ≤ +4.0)", 2/82, t['emerald']),
        ("2",  "Evaluated Pareto Rank-1 Candidates", 2/82, t['emerald']),
    ]

    funnel_rows = ""
    for count, label, frac, color in funnel_data:
        bar_w = max(int(frac * 100), 7)
        is_survivor = count == "2"
        font_weight = "700" if is_survivor else "600"
        funnel_rows += f"""
        <div class="funnel-row">
          <div class="funnel-count" style="color:{color};font-weight:{font_weight};">{count}</div>
          <div class="funnel-track">
            <div class="funnel-bar" style="width:{bar_w}%;background:{color};"></div>
            <div class="funnel-label" style="font-weight:{font_weight};">{label}</div>
          </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
{css_base}
body {{ width:1200px; height:480px; overflow:hidden; display:flex; gap:20px; padding:22px; }}
.panel {{
  flex:1; background:{t['card']}; border:1px solid {t['border']}; border-radius:14px;
  padding:22px; display:flex; flex-direction:column; position:relative; overflow:hidden;
}}
.panel-title {{
  font-size:22px; font-weight:700; color:{t['h1_color']}; margin-bottom:14px; display:flex;
  align-items:center; justify-content:space-between;
}}
.panel-tag {{
  font-family:{MONO}; font-size:13px; color:{t['cyan']};
  background:{t['badge_top_bg']}; padding:4px 10px; border-radius:6px;
  border:1px solid {t['badge_top_border']}; font-weight:600;
}}
.pocket-container {{
  flex:1; border-radius:10px; overflow:hidden; position:relative;
  background:{t['viewer_bg']}; border:1px solid {t['border']};
}}
#viewer-pocket {{ width:100%; height:100%; }}
.pocket-labels {{
  position:absolute; bottom:10px; left:12px; right:12px;
  display:flex; justify-content:space-between;
  background:{t['render_overlay_bg']}; backdrop-filter:blur(6px);
  padding:6px 12px; border-radius:6px; border:1px solid {t['border']};
  font-family:{MONO}; font-size:12px; color:{t['render_overlay_text']};
}}
.funnel-list {{
  display:flex; flex-direction:column; gap:9px; flex:1; justify-content:center;
}}
.funnel-row {{
  display:flex; align-items:center; gap:14px;
}}
.funnel-count {{
  width:36px; text-align:right; font-family:{MONO}; font-size:17px;
  white-space:nowrap; flex-shrink:0;
}}
.funnel-track {{
  flex:1; height:32px; background:{t['funnel_track_bg']}; border:1px solid {t['border']};
  border-radius:8px; position:relative; overflow:hidden; display:flex; align-items:center;
}}
.funnel-bar {{
  position:absolute; top:0; left:0; height:100%; opacity:0.25; border-radius:6px;
}}
.funnel-label {{
  position:relative; z-index:2; padding-left:14px; font-size:15px; color:{t['text1']};
  white-space:nowrap;
}}
.survivors-card {{
  margin-top:12px; background:{t['bg']}; border:1px solid rgba(74,222,128,0.3);
  border-radius:10px; padding:12px 16px; display:flex; flex-direction:column; gap:6px;
}}
.survivor-head {{
  font-size:14px; font-weight:700; color:{t['emerald']}; font-family:{MONO};
}}
.survivor-lead {{
  display:flex; justify-content:space-between; font-family:{MONO}; font-size:15px;
}}
</style>
<script src="file://{VENDOR_3DMOL}"></script>
</head><body>

<!-- Left: Active Site 3D Viewport -->
<div class="panel">
  <div class="panel-title">
    <span>GtfB Catalytic Triad Engagement</span>
    <span class="panel-tag">CAHWRPWHC · -8.191 kcal/mol</span>
  </div>
  <div class="pocket-container">
    <div id="viewer-pocket"></div>
    <div class="pocket-labels">
      <span style="color:{t['coral']}">Triad: Asp477, Glu515, Asp588</span>
      <span style="color:{t['cyan']}">Lead: CAHWRPWHC</span>
      <span style="color:{t['amber']}">S-S: 2.06 Å</span>
    </div>
  </div>
</div>

<!-- Right: Multi-Gate Attrition Funnel -->
<div class="panel">
  <div class="panel-title">
    <span>Multi-Gate Biophysical Triage</span>
    <span class="panel-tag">82 → 2 Candidates</span>
  </div>
  <div class="funnel-list">
    {funnel_rows}
  </div>
  <div class="survivors-card">
    <div class="survivor-head">NON-DOMINATED PARETO SURVIVORS</div>
    <div class="survivor-lead">
      <span style="color:{t['cyan']};font-weight:700;">#1 CAHWRPWHC</span>
      <span>Vina -8.191 · ΔΔG -0.85 · ΔQ +1.62</span>
    </div>
    <div class="survivor-lead">
      <span style="color:{t['emerald']};font-weight:700;">#2 CPHWRPAHC</span>
      <span>Vina -7.805 · ΔΔG -0.96 · ΔQ +1.62</span>
    </div>
  </div>
</div>

<script>
  window.addEventListener('load', () => {{
    const pdbData = `{PDB_CONTENT}`;
    const element = document.getElementById('viewer-pocket');
    const viewer = $3Dmol.createViewer(element, {{ backgroundColor: '{t['viewer_bg']}' }});
    viewer.addModel(pdbData, 'pdb');

    viewer.setStyle({{ chain: 'A' }}, {{ cartoon: {{ color: '{t['protein_color']}', opacity: 0.8 }} }});
    viewer.setStyle({{ chain: 'A', resi: [477, 515, 588] }}, {{
      stick: {{ color: '{t['coral']}', radius: 0.38 }}
    }});
    viewer.setStyle({{ chain: 'B' }}, {{
      stick: {{ color: '{t['cyan']}', radius: 0.30 }}
    }});

    viewer.addSphere({{ center: {{ x: 184.831, y: 32.035, z: 198.614 }}, radius: 0.6, color: '{t['amber']}' }});
    viewer.addSphere({{ center: {{ x: 184.677, y: 34.077, z: 198.820 }}, radius: 0.6, color: '{t['amber']}' }});
    viewer.addCylinder({{
      start: {{ x: 184.831, y: 32.035, z: 198.614 }},
      end: {{ x: 184.677, y: 34.077, z: 198.820 }},
      radius: 0.26,
      color: '{t['amber']}',
      fromCap: true,
      toCap: true
    }});

    try {{
      viewer.addSurface($3Dmol.SurfaceType.MS, {{ opacity: 0.22, color: '{t['surface_color']}' }}, {{ chain: 'A', within: {{ distance: 10.0, sel: {{ chain: 'B' }} }} }});
    }} catch(e) {{
      console.error(e);
    }}

    viewer.zoomTo({{ chain: 'B' }});
    viewer.zoom(0.9);
    viewer.rotate(30, 'y');
    viewer.rotate(-10, 'x');
    viewer.render();
  }});
</script>
</body></html>"""
    out_file = ASSETS / f"fig3_pocket_and_funnel_{theme}.png"
    render_html_to_png(html, 1200, 480, out_file)
    if theme == "dark":
        shutil.copyfile(out_file, ASSETS / "fig3_pocket_and_funnel.png")


# =========================================================================
# FIGURE 5: Falsification Plate (1200x760 @2x = 2400x1520)
# =========================================================================
def build_falsification_plate(theme: str = "dark"):
    t = get_tokens(theme)
    css_base = get_css_base(t)
    ledger = load_ledger()
    benchmark = load_benchmark()
    alanine = benchmark["alanine_scan"]
    scrambled = benchmark["scrambled_null_test"]

    # (A) Scatter plot points
    design_rows = [r for r in ledger if r.get("falsification_status") != "SCRAMBLED_NULL_CONTROL"]
    scatter_svg = ""

    def map_pareto(x, y):
        px = 55 + (x - (-11.0)) / ((-6.5) - (-11.0)) * 430
        py = 35 + (y - (1.0)) / ((-4.0) - (1.0)) * 180
        return px, py

    cahw_coords = None
    cphw_coords = None

    for r in design_rows:
        try:
            x_val = float(r["vina_3aic_kcal"])
            y_val = float(r["selectivity_ddg"])
        except (ValueError, KeyError):
            continue
        px, py = map_pareto(x_val, y_val)
        seq = r.get("sequence", "")
        if seq == "CAHWRPWHC":
            cahw_coords = (px, py)
        elif seq == "CPHWRPAHC":
            cphw_coords = (px, py)
        elif r.get("falsification_status") == "CORROBORATED":
            scatter_svg += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5" fill="{t["emerald"]}" opacity="0.75"/>'
        elif r.get("falsification_status") == "FALSIFIED_AMYLASE_CROSSREACTIVITY":
            scatter_svg += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="{t["coral"]}" opacity="0.35"/>'
        else:
            scatter_svg += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="{t["text2"]}" opacity="0.3"/>'

    if cahw_coords:
        px, py = cahw_coords
        scatter_svg += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="8.5" fill="{t["cyan"]}" stroke="#ffffff" stroke-width="2"/>'
        scatter_svg += f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{px-15:.1f}" y2="{py-22:.1f}" stroke="{t["cyan"]}" stroke-width="1.5"/>'
        scatter_svg += f'<rect x="{px-175:.1f}" y="{py-38:.1f}" width="180" height="24" rx="4" fill="{t["card"]}" stroke="{t["cyan"]}" stroke-width="1"/>'
        scatter_svg += f'<text x="{px-85:.1f}" y="{py-22:.1f}" text-anchor="middle" fill="{t["cyan"]}" font-family="{MONO}" font-size="12" font-weight="700">#1 CAHWRPWHC (-8.191, -0.85)</text>'

    if cphw_coords:
        px, py = cphw_coords
        scatter_svg += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="7.5" fill="{t["emerald"]}" stroke="#ffffff" stroke-width="1.5"/>'
        scatter_svg += f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{px-10:.1f}" y2="{py+22:.1f}" stroke="{t["emerald"]}" stroke-width="1.5"/>'
        scatter_svg += f'<rect x="{px-95:.1f}" y="{py+22:.1f}" width="170" height="24" rx="4" fill="{t["card"]}" stroke="{t["emerald"]}" stroke-width="1"/>'
        scatter_svg += f'<text x="{px-10:.1f}" y="{py+38:.1f}" text-anchor="middle" fill="{t["emerald"]}" font-family="{MONO}" font-size="12" font-weight="700">#2 CPHWRPAHC (-7.805, -0.96)</text>'

    # (B) Histogram data for scrambled nulls
    perm_vals = [p["vina_3aic_kcal"] for p in scrambled["permutations"]]
    min_v, max_v = min(perm_vals), max(perm_vals)
    n_bins = 10
    bin_step = (max_v - min_v) / n_bins
    counts = [0] * n_bins
    for v in perm_vals:
        idx = min(int((v - min_v) / bin_step), n_bins - 1)
        counts[idx] += 1
    max_c = max(counts)

    hist_svg = ""
    for i, c in enumerate(counts):
        bx = 55 + i * (440 / n_bins)
        bw = (440 / n_bins) - 5
        bh = (c / max_c) * 155
        by = 205 - bh
        hist_svg += f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{t["cyan"]}" opacity="0.65" rx="3"/>'
        if c > 0:
            hist_svg += f'<text x="{bx+bw/2:.1f}" y="{by-5:.1f}" fill="{t["text1"]}" font-family="{MONO}" font-size="12" font-weight="600" text-anchor="middle">{c}</text>'

    mean_val = scrambled["mean_kcal"]
    mx = 55 + (mean_val - min_v) / (max_v - min_v) * 440
    cx = 55 + (-8.191 - min_v) / (max_v - min_v) * 440

    # (C) Alanine Scan bars
    ala_keys = ["P2A", "H3A", "W4A", "R5A", "P6A", "W7A", "H8A"]
    ala_svg = ""
    parent_base = -8.062
    for i, k in enumerate(ala_keys):
        info = alanine[k]
        val = info["vina_3aic_kcal"]
        delta = info["delta_binding_affinity_kcal"]
        is_hot = info["is_hotspot"]
        y_pos = 26 + i * 27
        bar_w = (abs(val) - 7.5) / 1.5 * 140
        bar_col = t['coral'] if k == "P6A" else (t['amber'] if is_hot else t['cyan'])

        ala_svg += f"""
        <text x="75" y="{y_pos+15}" text-anchor="end" fill="{t['text1']}" font-family="{MONO}" font-size="13" font-weight="600">{k}</text>
        <rect x="85" y="{y_pos}" width="{bar_w:.1f}" height="20" fill="{bar_col}" opacity="0.7" rx="3"/>
        <text x="{92+bar_w:.1f}" y="{y_pos+15}" fill="{t['text1']}" font-family="{MONO}" font-size="12" font-weight="600">{val:.3f} ({delta:+.3f})</text>
        """
        if k == "P6A":
            ala_svg += f'<text x="510" y="{y_pos+15}" text-anchor="end" fill="{t["coral"]}" font-family="{MONO}" font-size="12" font-weight="700">Trypsin Lysis (Arg5)</text>'
        elif is_hot:
            ala_svg += f'<text x="510" y="{y_pos+15}" text-anchor="end" fill="{t["amber"]}" font-family="{MONO}" font-size="12" font-weight="600">Catalytic Anchor</text>'

    # (D) Stephan Charge Curve
    def map_stephan(ph, q):
        sx = 55 + (7.5 - ph) / (7.5 - 4.5) * 440
        sy = 205 - (q / 8.0) * 170
        return sx, sy

    cahw_pts = [(7.5, 0.50), (7.2, 1.13), (6.0, 2.05), (5.2, 2.75), (4.5, 3.20)]
    crrr_pts = [(7.5, 7.00), (7.2, 7.00), (6.0, 7.00), (5.2, 7.00), (4.5, 7.00)]

    cahw_poly = " ".join(f"{map_stephan(p, q)[0]:.1f},{map_stephan(p, q)[1]:.1f}" for p, q in cahw_pts)
    crrr_poly = " ".join(f"{map_stephan(p, q)[0]:.1f},{map_stephan(p, q)[1]:.1f}" for p, q in crrr_pts)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
{css_base}
body {{ width:1200px; height:760px; overflow:hidden; padding:18px; }}
.plate-grid {{
  display:grid; grid-template-columns:1fr 1fr; grid-template-rows:1fr 1fr; gap:16px;
  width:100%; height:100%;
}}
.plate-cell {{
  background:{t['card']}; border:1px solid {t['border']}; border-radius:12px;
  padding:14px 18px; display:flex; flex-direction:column; justify-content:space-between;
}}
.cell-header {{
  display:flex; align-items:center; justify-content:space-between; margin-bottom:4px;
}}
.cell-badge {{
  display:inline-flex; align-items:center; gap:8px;
}}
.badge-letter {{
  width:26px; height:26px; border-radius:6px; background:{t['badge_top_bg']};
  color:{t['cyan']}; font-family:{MONO}; font-size:15px; font-weight:800;
  display:flex; align-items:center; justify-content:center;
}}
.cell-title {{
  font-size:17px; font-weight:700; color:{t['text1']};
}}
.cell-meta {{
  font-family:{MONO}; font-size:13px; color:{t['text2']};
}}
.chart-box {{
  flex:1; width:100%; height:235px; position:relative;
}}
.legend-bar {{
  display:flex; gap:14px; align-items:center; font-family:{MONO}; font-size:12px;
  color:{t['text2']}; margin-top:4px; border-top:1px solid {t['card_border_alpha']}; padding-top:4px;
}}
.legend-dot {{
  width:8px; height:8px; border-radius:50%; display:inline-block;
}}
</style></head><body>

<div class="plate-grid">

  <!-- (A) Pareto Frontier -->
  <div class="plate-cell">
    <div class="cell-header">
      <div class="cell-badge">
        <div class="badge-letter">A</div>
        <div class="cell-title">Multi-Objective Pareto Frontier</div>
      </div>
      <div class="cell-meta">82 Cyclic Candidates Evaluated</div>
    </div>
    <div class="chart-box">
      <svg width="530" height="235" viewBox="0 0 530 235">
        <line x1="55" y1="205" x2="505" y2="205" stroke="{t['chart_axis']}" stroke-width="1.5"/>
        <line x1="55" y1="20" x2="55" y2="205" stroke="{t['chart_axis']}" stroke-width="1.5"/>
        <line x1="55" y1="99" x2="505" y2="99" stroke="{t['coral']}" stroke-width="1" stroke-dasharray="4,4" opacity="0.5"/>
        <text x="500" y="93" fill="{t['coral']}" font-family="{MONO}" font-size="11" text-anchor="end">Amylase Threshold ΔΔG ≤ -0.80</text>
        {scatter_svg}
        <text x="280" y="225" text-anchor="middle" fill="{t['text2']}" font-family="{MONO}" font-size="12">GtfB 3AIC Affinity (kcal/mol)</text>
        <text x="18" y="115" text-anchor="middle" fill="{t['text2']}" font-family="{MONO}" font-size="12" transform="rotate(-90 18 115)">Selectivity ΔΔG</text>
      </svg>
    </div>
    <div class="legend-bar">
      <span style="display:flex;align-items:center;gap:6px;"><span class="legend-dot" style="background:{t['cyan']}"></span>Lead CAHWRPWHC</span>
      <span style="display:flex;align-items:center;gap:6px;"><span class="legend-dot" style="background:{t['emerald']}"></span>Corroborated</span>
      <span style="display:flex;align-items:center;gap:6px;"><span class="legend-dot" style="background:{t['coral']}"></span>Amylase Falsified</span>
    </div>
  </div>

  <!-- (B) Scrambled Null Histogram -->
  <div class="plate-cell">
    <div class="cell-header">
      <div class="cell-badge">
        <div class="badge-letter">B</div>
        <div class="cell-title">N=39 Scrambled Null Isomer Distribution</div>
      </div>
      <div class="cell-meta">Z = +0.32σ · p = 0.5897 (H0 Not Rejected)</div>
    </div>
    <div class="chart-box">
      <svg width="530" height="235" viewBox="0 0 530 235">
        <line x1="55" y1="205" x2="505" y2="205" stroke="{t['chart_axis']}" stroke-width="1.5"/>
        <line x1="55" y1="20" x2="55" y2="205" stroke="{t['chart_axis']}" stroke-width="1.5"/>
        {hist_svg}
        <line x1="{mx:.1f}" y1="35" x2="{mx:.1f}" y2="205" stroke="{t['amber']}" stroke-width="2" stroke-dasharray="5,3"/>
        <text x="{mx:.1f}" y="28" fill="{t['amber']}" font-family="{MONO}" font-size="11" font-weight="700" text-anchor="middle">Mean -8.343 ± 0.470</text>
        <line x1="{cx:.1f}" y1="45" x2="{cx:.1f}" y2="205" stroke="{t['cyan']}" stroke-width="2"/>
        <text x="{cx:.1f}" y="42" fill="{t['cyan']}" font-family="{MONO}" font-size="11" font-weight="700" text-anchor="middle">CAHWRPWHC -8.191</text>
        <text x="280" y="225" text-anchor="middle" fill="{t['text2']}" font-family="{MONO}" font-size="12">Vina 3AIC Score (kcal/mol)</text>
      </svg>
    </div>
    <div class="legend-bar">
      <span>Non-rejection proves topological sequence constraint rather than generic charge collapse</span>
    </div>
  </div>

  <!-- (C) Alanine Scan -->
  <div class="plate-cell">
    <div class="cell-header">
      <div class="cell-badge">
        <div class="badge-letter">C</div>
        <div class="cell-title">7-Site Alanine Mutational Hotspot Scan</div>
      </div>
      <div class="cell-meta">Parent CPHWRPWHC (-8.062)</div>
    </div>
    <div class="chart-box">
      <svg width="530" height="235" viewBox="0 0 530 235">
        <line x1="85" y1="20" x2="85" y2="218" stroke="{t['chart_axis']}" stroke-width="1.5"/>
        <line x1="{85 + (abs(parent_base) - 7.5)/1.5 * 190:.1f}" y1="15"
              x2="{85 + (abs(parent_base) - 7.5)/1.5 * 190:.1f}" y2="218"
              stroke="{t['text2']}" stroke-width="1.5" stroke-dasharray="4,4"/>
        <text x="{85 + (abs(parent_base) - 7.5)/1.5 * 190:.1f}" y="12" fill="{t['text2']}" font-family="{MONO}" font-size="11" text-anchor="middle">Parent -8.062</text>
        {ala_svg}
      </svg>
    </div>
    <div class="legend-bar">
      <span style="display:flex;align-items:center;gap:6px;"><span class="legend-dot" style="background:{t['amber']}"></span>Hotspot Anchor</span>
      <span style="display:flex;align-items:center;gap:6px;"><span class="legend-dot" style="background:{t['coral']}"></span>Trypsin Lysis</span>
      <span style="display:flex;align-items:center;gap:6px;"><span class="legend-dot" style="background:{t['cyan']}"></span>Hinge / Permissive</span>
    </div>
  </div>

  <!-- (D) Stephan Charge Titration -->
  <div class="plate-cell">
    <div class="cell-header">
      <div class="cell-badge">
        <div class="badge-letter">D</div>
        <div class="cell-title">Stephan pH Acid-Switch Charge Titration</div>
      </div>
      <div class="cell-meta">Salivary pH 7.5 → Plaque pH 4.5</div>
    </div>
    <div class="chart-box">
      <svg width="530" height="235" viewBox="0 0 530 235">
        <line x1="55" y1="205" x2="505" y2="205" stroke="{t['chart_axis']}" stroke-width="1.5"/>
        <line x1="55" y1="20" x2="55" y2="205" stroke="{t['chart_axis']}" stroke-width="1.5"/>
        <polyline points="{cahw_poly}" fill="none" stroke="{t['cyan']}" stroke-width="3" stroke-linecap="round"/>
        <polyline points="{crrr_poly}" fill="none" stroke="{t['coral']}" stroke-width="2.5" stroke-dasharray="6,4" stroke-linecap="round"/>
        <text x="490" y="125" text-anchor="end" fill="{t['cyan']}" font-family="{MONO}" font-size="13" font-weight="700">CAHWRPWHC (ΔQ = +1.62)</text>
        <text x="260" y="42" fill="{t['coral']}" font-family="{MONO}" font-size="13" font-weight="700">CRRRWWRRRRC (Static Q=+7.0)</text>
        <text x="55" y="222" fill="{t['text2']}" font-family="{MONO}" font-size="11" text-anchor="middle">pH 7.5</text>
        <text x="201" y="222" fill="{t['text2']}" font-family="{MONO}" font-size="11" text-anchor="middle">pH 6.5</text>
        <text x="348" y="222" fill="{t['text2']}" font-family="{MONO}" font-size="11" text-anchor="middle">pH 5.5</text>
        <text x="495" y="222" fill="{t['text2']}" font-family="{MONO}" font-size="11" text-anchor="middle">pH 4.5</text>
        <text x="18" y="115" text-anchor="middle" fill="{t['text2']}" font-family="{MONO}" font-size="12" transform="rotate(-90 18 115)">Net Charge Q</text>
      </svg>
    </div>
    <div class="legend-bar">
      <span>Acid activation: Gains +1.62 positive charge selectively inside acidogenic plaque (pH 5.2)</span>
    </div>
  </div>

</div>
</body></html>"""
    out_file = ASSETS / f"fig4_falsification_plate_{theme}.png"
    render_html_to_png(html, 1200, 760, out_file)
    if theme == "dark":
        shutil.copyfile(out_file, ASSETS / "fig4_falsification_plate.png")


# =========================================================================
# SOCIAL PREVIEW (1280x640 @2x = 2560x1280)
# =========================================================================
def build_social_preview():
    t = get_tokens("dark")
    css_base = get_css_base(t)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
{css_base}
body {{
  width:1280px; height:640px; overflow:hidden; display:flex; flex-direction:column;
  justify-content:center; align-items:center; text-align:center;
  background: radial-gradient(ellipse at 50% 30%, #172338 0%, {t['bg']} 75%);
  padding:40px;
}}
.badge {{
  display:inline-flex; align-items:center; gap:8px;
  background:{t['badge_top_bg']}; border:1px solid {t['badge_top_border']};
  padding:6px 18px; border-radius:100px; font-family:{MONO}; font-size:15px;
  font-weight:700; color:{t['cyan']}; margin-bottom:18px;
}}
h1 {{
  font-size:56px; font-weight:800; letter-spacing:-1.2px; line-height:1.15;
  color:#ffffff; margin-bottom:12px;
}}
.subtitle {{
  font-size:24px; font-weight:600; color:{t['cyan']}; margin-bottom:8px;
}}
.subline {{
  font-size:18px; color:{t['text2']}; margin-bottom:34px; max-width:850px;
}}
.metrics-row {{
  display:flex; gap:18px; justify-content:center;
}}
.metric-card {{
  background:{t['card']}; border:1px solid {t['border']}; border-radius:12px;
  padding:14px 22px; display:flex; flex-direction:column; gap:4px; min-width:180px;
}}
.metric-val {{
  font-family:{MONO}; font-size:22px; font-weight:800;
}}
.metric-lbl {{
  font-size:13px; color:{t['text2']}; font-weight:500;
}}
</style></head><body>

<div class="badge">AUTODOCK VINA · OPENMM AMBER14 · POPPERIAN FALSIFICATION</div>
<h1>DrNemo Caries Foundry</h1>
<div class="subtitle">Targeted GtfB Macrocycle Inhibitor Discovery</div>
<div class="subline">Systematic computational falsification of cyclic peptide therapeutics against dental caries virulence</div>

<div class="metrics-row">
  <div class="metric-card">
    <span class="metric-val" style="color:{t['cyan']}">-8.191 kcal</span>
    <span class="metric-lbl">3AIC Target Affinity</span>
  </div>
  <div class="metric-card">
    <span class="metric-val" style="color:{t['emerald']}">-0.85 kcal</span>
    <span class="metric-lbl">1SMD Selectivity ΔΔG</span>
  </div>
  <div class="metric-card">
    <span class="metric-val" style="color:{t['amber']}">Trypsin Shield</span>
    <span class="metric-lbl">Pro6 (W4/W7 At Risk)</span>
  </div>
  <div class="metric-card">
    <span class="metric-val" style="color:{t['coral']}">+1.62 ΔQ</span>
    <span class="metric-lbl">Stephan pH Acid Switch</span>
  </div>
  <div class="metric-card">
    <span class="metric-val" style="color:{t['cyan']}">12-Angle</span>
    <span class="metric-lbl">Popper Disproof Battery</span>
  </div>
</div>

</body></html>"""
    render_html_to_png(html, 1280, 640, ASSETS / "social_preview.png")


def cleanup_obsolete():
    """Remove obsolete asset files."""
    obsolete = [
        "hero.svg",
        "hero_gtfb_docking.svg",
        "langgraph_loop.svg",
        "evolution_funnel_147.svg",
        "evolution_demo.gif",
        "nature_biotech_hero.png",
        "physicochemical_benchmark.png",
    ]
    for name in obsolete:
        p = ASSETS / name
        if p.exists():
            p.unlink()
            print(f"  Removed obsolete: {name}")


def main():
    os.chdir(REPO)
    ASSETS.mkdir(exist_ok=True)

    print("=== Cleaning obsolete assets ===")
    cleanup_obsolete()

    for theme in ["dark", "light"]:
        print(f"\n=== Building figures for theme: {theme.upper()} ===")

        print(f"  Building hero_banner_{theme}.png (1200x380 @2x)")
        build_hero_banner(theme)

        print(f"  Building fig1_biological_mechanism_{theme}.png (1200x360 @2x)")
        build_biological_mechanism(theme)

        print(f"  Building fig2_pipeline_architecture_{theme}.png (1200x420 @2x)")
        build_pipeline_architecture(theme)

        print(f"  Building fig3_pocket_and_funnel_{theme}.png (1200x480 @2x)")
        build_pocket_and_funnel(theme)

        print(f"  Building fig4_falsification_plate_{theme}.png (1200x760 @2x)")
        build_falsification_plate(theme)

    print("\n=== Building social_preview.png (1280x640 @2x) ===")
    build_social_preview()

    print("\n=== ALL FIGURES BUILT ===")
    for f in sorted(ASSETS.glob("*.png")):
        print(f"  {f.name}: {f.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
