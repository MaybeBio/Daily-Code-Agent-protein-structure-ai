import json
import re

html_path = 'docs/index.html'
pdb_path = 'demo_data/results/3AIC_docked_complex_CAHWRPWHC.pdb'

with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

with open(pdb_path, 'r', encoding='utf-8') as f:
    clean_pdb = f.read()

# 1. Update EMBEDDED_PDBS["3AIC_docked_complex_CAHWRPWHC.pdb"]
# Find the key and replace its json string value
json_pdb = json.dumps(clean_pdb)
# Match: "3AIC_docked_complex_CAHWRPWHC.pdb": "..."
pattern = r'("3AIC_docked_complex_CAHWRPWHC\.pdb":\s*)"(?:\\.|[^"\\])*"'
if re.search(pattern, html):
    html = re.sub(pattern, r'\1' + json_pdb.replace('\\', '\\\\'), html, count=1)
    print('[1] Successfully replaced EMBEDDED_PDBS["3AIC_docked_complex_CAHWRPWHC.pdb"]')
else:
    print('[1] WARN: Could not find EMBEDDED_PDBS key via regex')

# 2. Add html, body overflow-x: hidden
if 'overflow-x: hidden' not in html[:1500]:
    old_body = """    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg-page);
      color: var(--text-main);
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }"""
    new_body = """    html, body {
      overflow-x: hidden;
      max-width: 100vw;
    }

    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg-page);
      color: var(--text-main);
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }"""
    if old_body in html:
        html = html.replace(old_body, new_body)
        print('[2] Added html, body overflow-x: hidden')
    else:
        print('[2] WARN: old_body not found verbatim')
else:
    print('[2] overflow-x: hidden already present in head')

# 3. Fix leads-bar flex-wrap
old_leads = """    .leads-bar {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 16px 0 12px 0;
      overflow-x: auto;
      padding-bottom: 4px;
    }"""
new_leads = """    .leads-bar {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 16px 0 12px 0;
      overflow-x: auto;
      padding-bottom: 4px;
      flex-wrap: wrap;
      max-width: 100%;
      box-sizing: border-box;
    }"""
if old_leads in html:
    html = html.replace(old_leads, new_leads)
    print('[3] Updated .leads-bar with flex-wrap and max-width')
else:
    print('[3] leads-bar already updated or modified')

# 4. Fix molecular-stage-container height: 520px -> 430px
old_stage = """    .molecular-stage-container {
      position: relative;
      width: 100%;
      height: 520px;"""
new_stage = """    .molecular-stage-container {
      position: relative;
      width: 100%;
      height: 430px;"""
if old_stage in html:
    html = html.replace(old_stage, new_stage)
    print('[4] Updated .molecular-stage-container height to 430px')
else:
    print('[4] molecular-stage-container height already updated')

# 5. Inject preserveDrawingBuffer monkey-patch before initViewer
preserve_patch = """    // Inject preserveDrawingBuffer and antialias for WebGL screenshot fidelity
    (function() {
      const origGetContext = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function(type, attrs) {
        if (type === 'webgl' || type === 'webgl2' || type === 'experimental-webgl') {
          attrs = Object.assign({}, attrs || {}, { preserveDrawingBuffer: true, antialias: true, alpha: true });
        }
        return origGetContext.call(this, type, attrs);
      };
    })();"""

if 'preserveDrawingBuffer' not in html:
    html = html.replace(
        "    // --- 3Dmol Viewer Initialization ---",
        preserve_patch + "\n\n    // --- 3Dmol Viewer Initialization ---"
    )
    print('[5] Injected WebGL preserveDrawingBuffer hook')
else:
    print('[5] preserveDrawingBuffer hook already present')

# 6. Update zoom and render behavior in loadCurrentLeadStructure
old_zoom = """        viewer.zoomTo({ chain: 'B' }, 800);
        viewer.zoom(0.82, 800);"""
new_zoom = """        viewer.zoomTo({ chain: 'B' }, 0);
        viewer.zoom(0.78, 0);"""
if old_zoom in html:
    html = html.replace(old_zoom, new_zoom)
    print('[6] Updated viewer zoomTo parameters')

# Save updated HTML
with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f'Saved updated {html_path} ({len(html)} bytes)')
