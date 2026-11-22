'''
==============================================================================
HotSpots Finder v3.7 - PyQt Edition
==============================================================================
Author  : JMB-scripts
Version : 3.7
License : Do whatever you want, just don't forget it was coded by a stupid biochemist for this matter me.

OVERVIEW
--------
HotSpots Finder is a PyMOL plugin for automated identification and curation
of protein interface hotspot residues, designed as input for RFdiffusion3
binder design workflows.

It combines a 5-parameter biophysical scoring engine with an interactive
PyQt6/PyQt5 GUI, allowing users to discover, visualize, manually curate,
and export hotspot sets as YAML configuration files.

REQUIREMENTS
------------
  - PyMOL (open-source or incentive build, >= 2.5 recommended)
  - PyQt6 or PyQt5  (PyQt6 is tried first, with automatic fallback to PyQt5)
  - Python 3.8+

INSTALLATION
------------
  Option A — PyMOL Plugin Manager (recommended):
    1. Open PyMOL.
    2. Go to Plugin > Plugin Manager > Install New Plugin.
    3. Browse to this file and click OK.
    4. Restart PyMOL.

  Option B — Startup script:
    Add the following line to your PyMOL startup file (~/.pymolrc or pymolrc.pml):
        run /path/to/HotSpots_Finder_PyQt-v3.7.py

  Option C — Manual load at runtime:
    In the PyMOL command line:
        run /path/to/HotSpots_Finder_PyQt-v3.7.py

LAUNCHING THE GUI
-----------------
  Loading with `run` (Options B and C) opens the GUI automatically.
  To reopen it later, or after installing as a plugin (Option A):
    PyMOL command line:  hs_gui
    OR via:              Plugins > HotSpots Finder (PyQt)

  To suppress the auto-launch (e.g. in a ~/.pymolrc where you don't want a
  window on every start), set the flag before loading:
        HS_AUTOLAUNCH = False
        run /path/to/HotSpots_Finder_PyQt-v3.7.py
  Installing via the Plugin Manager never auto-launches; it only adds the
  Plugins menu entry.

SCORING ENGINE
--------------
  Each candidate residue is scored with 5 biophysical parameters:

  1. Chem Score    (30%) — Residue identity preference for protein-protein
                           interfaces, based on empirical frequency data
                           (TRP > TYR > PHE > LEU > ILE ...).

  2. SASA Score    (20%) — Solvent Accessible Surface Area normalized by
                           the residue's theoretical maximum. Filters buried
                           residues (configurable cutoff).

  3. Protrusion    (20%) — Distance of the Cα from the local center of mass
                           (8 Å neighbourhood). Rewards exposed, protruding
                           residues likely to be at the interface.

  4. Density       (15%) — Inverse of local Cα density (8 Å radius). Penalizes
                           residues packed in dense cores; rewards isolated
                           surface residues.

  5. Proximity     (15%) — Exponential decay of distance to the surface
                           centroid of the selection (sharper decay = strict
                           prioritization of the center).

  Orientation filter:
    A Cα→Cβ vector alignment check is applied before the final score:
      - If the side chain points AWAY from the target centroid (cos θ < 0),
        a severe penalty factor of 0.2 is applied.
      - Glycine residues (no Cβ) always receive this penalty by default.

  Final Score = (Chem×0.30 + SASA×0.20 + Prot×0.20 + Dens×0.15 + Prox×0.15)
                × orientation_penalty

  Score → Color mapping (PyMOL):
    ≥ 0.70  →  tv_red    (excellent)
    ≥ 0.55  →  orange    (good)
    ≥ 0.40  →  wheat     (moderate)
    <  0.40  →  slate     (poor)

GUI TABS
--------
  🎯 Hotspot
    Configure and run the automated biophysical discovery.
    • Run    — score residues and display hotspots.
    • Reset  — restore the PyMOL display (colors, representations, view,
               B-factors) to how it was before the first Run, AND put the
               three sliders back to their defaults
               (Top N = 5, Radar Radius = 10 Å, SASA Cutoff = 20).
               The hotspot list is kept; use Curate > Clear All to empty it.
    Parameters:
      • Top N Residues   — number of top-ranked hotspots to select (1–30).
      • Radar Radius (Å) — if > 0, restricts analysis to residues within
                           this radius of the computed surface centroid.
                           Set to 0 to score the entire selection.
      • SASA Cutoff      — minimum SASA value (Ų) to include a residue.
                           Residues below this threshold are filtered out
                           (colored gray50 in whole-protein mode).

  📊 Scoring
    Displays the detailed per-residue scoring table after each run.
    Columns: Residue | AA | Dist | Chem | SASA% | Prot | Prox | Score | Bar | Atoms

  🔧 Curate
    Manual hotspot management table.
    • ➕ Add Sele    — add atoms from the current PyMOL selection.
    • ➖ Remove Sele — remove atoms from the current PyMOL selection.
    • 🧹 Clear All   — reset all hotspots and remove all hs_* objects.

  🚀 Export
    • Format             — choose the target model's config syntax:

        RFD4-Proteina (default) — hotspots are a `C_HOT` condition whose
        selections use the InputSelection mini-language
        `sel('<chain>/<res_name>/<res_id>/<atom_name>')`:

            conditions:
              C_HOT:
                true:
                  - select: "sel('A/*/56/[CG,OH]')"     # TYR56
                  - select: "sel('A/*/115/[CG,SD]')"    # MET115
                  - select: "sel('A/*/123/[CD2,OH]')"   # TYR123

        Merge this `conditions:` block into your design YAML alongside
        `input:` and `contig:`. NOTE: res_id is the ORIGINAL input
        numbering, not the renumbered contig output.

        RFdiffusion3 — hotspots are a residue -> atom-name mapping:

            select_hotspots:
              A56: CG,OH     # TYR56
              A115: CG,SD    # MET115

        RFD3 also accepts the shorthands ALL, BKBN ('N,CA,C,O') and TIP
        in place of explicit atom names; this tool always writes explicit
        atom names.

    • Refresh YAML       — regenerate the block for the chosen format.
    • Copy to Clipboard  — copy the YAML directly.
    • Show 4.5Å Zone     — display a 4.5 Å transparent cyan sphere around
                           each hotspot atom (useful for visual QC).

COMMAND-LINE API
----------------
  All core functions are also available as PyMOL commands:

  hs_gui
    Launch or bring the GUI to focus.

  hs_reset
    Restore the display to the snapshot taken before the first run.

  hs_yaml [fmt]
    Print the hotspot config block. fmt = "rfd4" (default) or "rfd3".

  hs_auto [selection] [top] [radius] [sasa_cut]
    Run the biophysical scoring engine directly.
    Args:
      selection  (str)   — PyMOL selection or object name. Default: "sele"
      top        (int)   — number of hotspots to return. Default: 5
      radius     (float) — radar radius in Å (0 = whole selection). Default: 0
      sasa_cut   (float) — minimum SASA threshold. Default: 20.0
    Example:
      hs_auto chain_A, top=8, radius=12, sasa_cut=15

  hs_add [selection]
    Manually add all non-hydrogen atoms of a selection to the hotspot list.
    Example:
      select my_res, chain A and resi 42
      hs_add my_res

  hs_remove [selection]
    Remove atoms of a selection from the hotspot list.

  hs_clear
    Clear all hotspots and delete all hs_* PyMOL objects.

VISUALIZATION OBJECTS (created automatically)
---------------------------------------------
  hs_centroid       — red sphere at the surface-projected centroid.
  hs_boundary       — yellow Cα spheres marking the selection boundary.
  hs_atoms          — yellow 0.35-scale spheres on hotspot atoms.
  hs_zone_4A5       — cyan transparent 4.5 Å zone spheres (Export tab).
  hs_auto_sticks    — sticks representation of top-scored residues.
  hs_auto_spheres   — small spheres on selected hotspot atoms.

YAML OUTPUT FORMAT (RFdiffusion3)
----------------------------------
  select_hotspots:
    A42: CB,CG1
    A87: CB,CG
    B15: CB,CD2

NOTES
-----
  - The plugin handles alternative conformations (alt A / blank) automatically.
  - PROTEIN ONLY: every step filters on `polymer.protein`, so waters, ions,
    ligands and nucleic acids are ignored. They are never scored, and -
    more importantly - they cannot shield a surface residue and depress its
    SASA. You do not need to strip solvent before running.
  - SASA is computed ONCE, on a clean protein-only temporary clone with
    alternative conformations removed (both would cause self-shielding).
    The per-atom and per-residue tables come from that single calculation,
    so they can never disagree, and your object's B-factors are never
    overwritten by get_area.
  - Atom priority for hotspot atom selection uses SASA-ranked side-chain atoms.
  - Glycine is penalized by design: it lacks a side chain for RFdiffusion
    anchoring and is unlikely to be a productive hotspot.
  - Each Run REPLACES the previous result. Use the Curate tab to add or
    remove atoms by hand afterwards; a new Run discards manual edits.

CHANGES IN v3.7
---------------
  - Run now replaces the previous result instead of merging into it.
  - All calculations restricted to protein (waters/ligands/ions excluded).
  - SASA computed once on one clean clone (was twice, inconsistently).
  - Removed dead code: _project_surface_local, _HYDRO_OBJ, an overwritten
    score formula, and five unused imports.
  - One Run code path: the logger is built into run_hs_auto(), replacing the
    signal disconnect/reconnect patch that duplicated the logic.
  - Fixed a race where PyMOL's asynchronous command queue could delete the
    SASA clone after it was recreated, breaking every run after the first.

==============================================================================
'''

import math
import collections
from pymol import cmd, stored

try:
    from PyQt6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout,
                                 QComboBox, QPushButton, QLabel, QSlider,
                                 QTableWidget, QTableWidgetItem, QTabWidget,
                                 QTextEdit, QHeaderView, QAbstractItemView,
                                 QRadioButton, QButtonGroup)
    from PyQt6.QtCore import Qt
except ImportError:
    from PyQt5.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout,
                                 QComboBox, QPushButton, QLabel, QSlider,
                                 QTableWidget, QTableWidgetItem, QTabWidget,
                                 QTextEdit, QHeaderView, QAbstractItemView,
                                 QRadioButton, QButtonGroup)
    from PyQt5.QtCore import Qt

# ─────────────────────────────────────────────────────────────────────────────
#  Global State & Config
# ─────────────────────────────────────────────────────────────────────────────

_hotspot_atoms = collections.OrderedDict()
_hotspot_resn  = {}   # (chain, resi) -> residue name, for the YAML comments
_ZONE_OBJ      = "hs_zone_4A5"
_MARKER_OBJ    = "hs_atoms"
CUTOFF_A       = 4.5

_INTERFACE_SCORE = {
    "TRP": 1.00, "TYR": 0.92, "PHE": 0.82, "LEU": 0.72, "ILE": 0.68, "MET": 0.62, 
    "MSE": 0.62, "VAL": 0.52, "CYS": 0.50, "HIS": 0.44, "ALA": 0.38, "ARG": 0.34, 
    "PRO": 0.25, "GLN": 0.20, "THR": 0.20, "ASN": 0.18, "SER": 0.14, "LYS": 0.12, 
    "GLU": 0.10, "ASP": 0.08, "GLY": 0.04,
}

_MAX_SASA = {
    "TRP": 264, "TYR": 255, "PHE": 228, "ARG": 265, "LYS": 230, "HIS": 216, 
    "GLN": 214, "GLU": 214, "MET": 203, "MSE": 203, "ILE": 195, "LEU": 191, 
    "ASN": 187, "ASP": 187, "VAL": 165, "THR": 163, "PRO": 154, "CYS": 148, 
    "SER": 143, "ALA": 121, "GLY": 97
}

_ATOM_PRIORITY = {
    "CB":0, "CG":1, "CG1":1, "CG2":1, "OG":1, "SG":1, "OG1":1,
    "CD":2, "CD1":2, "CD2":2, "ND1":2, "ND2":2, "OD1":2, "OD2":2, "SD":2,
    "CE":3, "CE1":3, "CE2":3, "CE3":3, "NE":3, "NE1":3, "NE2":3, "OE1":3, "OE2":3,
    "CZ":4, "CZ2":4, "CZ3":4, "NZ":4, "NH1":4, "NH2":4, "OH":4, "CH2":5,
}

_SCORE_COLORS = [
    (0.70, "tv_red"),
    (0.55, "orange"),
    (0.40, "wheat"),
    (0.00, "slate"),
]


# ─────────────────────────────────────────────────────────────────────────────
#  Math & Utils
# ─────────────────────────────────────────────────────────────────────────────

def _sub(a, b): return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def _add(a, b): return (a[0]+b[0], a[1]+b[1], a[2]+b[2])
def _scale(v, scalar): return (v[0]*scalar, v[1]*scalar, v[2]*scalar)
def _dot(a, b): return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]
def _normalize(v):
    mag = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
    return (v[0]/mag, v[1]/mag, v[2]/mag) if mag > 0 else (0, 0, 0)
def _dist(a, b): return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
def _centroid(coords): return tuple(sum(c[i] for c in coords) / len(coords) for i in range(3))

def _project_to_surface(hotspot_centroid, all_coords, protein_com, step=0.3, probe=3.8):
    """
    Walk from hotspot_centroid outward (away from protein COM) step by step
    until no protein atom is within `probe` Å → that point IS the surface.
    Guarantees the centroid sits on the molecular surface regardless of protein shape.
    """
    direction = _normalize(_sub(hotspot_centroid, protein_com))
    if direction == (0, 0, 0):
        direction = (0.0, 0.0, 1.0)

    pos = hotspot_centroid
    for _ in range(300):                          # safety cap ~90 Å
        next_pos = _add(pos, _scale(direction, step))
        if not any(_dist(next_pos, c) < probe for c in all_coords):
            return pos                            # last point still inside protein
        pos = next_pos
    return pos

def _bar(score, width=14):
    filled = max(0, min(width, round(score * width)))
    return chr(9608) * filled + chr(9617) * (width - filled)

def _fmt_key(chain, resi): return f"{chain}{resi}"

def _score_color(score):
    for threshold, color in _SCORE_COLORS:
        if score >= threshold: return color
    return "slate"

def _rebuild_marker_obj():
    cmd.delete(_MARKER_OBJ)
    if not _hotspot_atoms: return
    parts = [f"(chain '{c}' and resi '{r}' and name {'+'.join(a)})" for (c, r), a in _hotspot_atoms.items()]
    cmd.select(_MARKER_OBJ, " or ".join(parts))
    cmd.show("spheres", _MARKER_OBJ)
    cmd.set("sphere_scale", 0.35, _MARKER_OBJ)
    cmd.color("yellow", _MARKER_OBJ)

    


# ─────────────────────────────────────────────────────────────────────────────
#  GUI Class
# ─────────────────────────────────────────────────────────────────────────────

class HotSpotsDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HotSpots Finder v3.7")
        self.setMinimumWidth(450)
        self.setMinimumHeight(600)
        
        # --- STYLE ---
        self.setStyleSheet("""
            QDialog { background-color: #2c2f33; color: #ffffff; }
            QLabel { color: #ffffff; font-size: 13px; }
            QRadioButton { color: #ffffff; font-size: 13px; spacing: 6px; }
            QRadioButton::indicator { width: 13px; height: 13px; border-radius: 7px;
                                      border: 1px solid #7289da; background: #23272a; }
            QRadioButton::indicator:checked { background: #7289da; }
            QPushButton { background-color: #7289da; color: white; border-radius: 4px; padding: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #5b6eae; }
            QPushButton#dangerBtn { background-color: #f04747; }
            QPushButton#dangerBtn:hover { background-color: #d83c3e; }
            QTabWidget::pane { border: 1px solid #444; background: #23272a; }
            QTabBar::tab { background: #2c2f33; color: white; padding: 10px; min-width: 80px; }
            QTabBar::tab:selected { background: #23272a; color: white; border-bottom: 2px solid #7289da; }
            QTableWidget { background-color: #23272a; gridline-color: #444; color: #ffffff; }
            QHeaderView::section { background-color: #2c2f33; color: white; padding: 4px; border: 1px solid #444; }
            QTextEdit { background-color: #1e2124; color: white; font-family: 'Courier New'; font-size: 13px; border: 1px solid #444; }
            /* Explicit slider style: avoids the macOS native-style repaint glitch
               where dragging one slider visually moves the others. */
            QSlider { min-height: 22px; }
            QSlider::groove:horizontal { height: 6px; background: #444; border-radius: 3px; }
            QSlider::sub-page:horizontal { background: #7289da; border-radius: 3px; }
            QSlider::handle:horizontal { background: #ffffff; border: 1px solid #7289da;
                                         width: 14px; margin: -5px 0; border-radius: 7px; }
        """)

        main_layout = QVBoxLayout()
        
        # Header Selection (Apply to)
        sel_layout = QHBoxLayout()
        sel_layout.addWidget(QLabel("Apply to:"))
        self.sel_combo = QComboBox()
        self.sel_combo.setEditable(True)
        self.refresh_selections()
        sel_layout.addWidget(self.sel_combo)
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setFixedWidth(45)
        self.refresh_btn.clicked.connect(self.refresh_selections)
        sel_layout.addWidget(self.refresh_btn)
        main_layout.addLayout(sel_layout)

        # TABS
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # Tab 1: Discover
        self.tab_discover = QWidget()
        self.setup_discover_tab()
        self.tabs.addTab(self.tab_discover, "🎯 Hotspot")
        
        # Tab 2: Scoring (Moved after Discover)
        self.tab_scoring = QWidget()
        self.setup_scoring_tab()
        self.tabs.addTab(self.tab_scoring, "📊 Scoring")

        # Tab 3: Curation
        self.tab_curate = QWidget()
        self.setup_curation_tab()
        self.tabs.addTab(self.tab_curate, "🔧 Curate")
        
        # Tab 4: Export
        self.tab_export = QWidget()
        self.setup_export_tab()
        self.tabs.addTab(self.tab_export, "🚀 Export")

        # Console Log
        main_layout.addWidget(QLabel("Console Output:"))
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFixedHeight(80)
        main_layout.addWidget(self.console)

        self.setLayout(main_layout)
        self.log("HotSpots Finder GUI Ready.")

    def log(self, message):
        self.console.append(f"> {message}")

    def refresh_selections(self):
        current = self.sel_combo.currentText()
        self.sel_combo.clear()
        names = ['all', 'sele'] + cmd.get_names('public')
        self.sel_combo.addItems(names)
        if current in names: self.sel_combo.setCurrentText(current)

    def setup_discover_tab(self):
        layout = QVBoxLayout()

        # (slider, default) pairs, so Reset can put the parameters back
        self._slider_defaults = []

        def create_slider_row(label, min_v, max_v, default):
            row = QHBoxLayout()
            lbl = QLabel(f"{label}:")
            val_lbl = QLabel(str(default), self.tab_discover)
            val_lbl.setFixedWidth(45)
            slider = QSlider(Qt.Orientation.Horizontal, self.tab_discover)
            slider.setRange(min_v, max_v)
            slider.setValue(default)
            slider.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            # Bind this row's label explicitly (default arg) so each slider
            # only ever updates its own value label.
            slider.valueChanged.connect(lambda v, l=val_lbl: l.setText(str(v)))
            row.addWidget(lbl)
            row.addWidget(slider)
            row.addWidget(val_lbl)
            self._slider_defaults.append((slider, default))
            return row, slider

        self.row_top, self.slider_top = create_slider_row("Top N Residues", 1, 30, 5)
        self.row_rad, self.slider_rad = create_slider_row("Radar Radius (Å)", 0, 30, 10)
        self.row_sas, self.slider_sas = create_slider_row("SASA Cutoff", 0, 100, 20)

        layout.addLayout(self.row_top)
        layout.addLayout(self.row_rad)
        layout.addLayout(self.row_sas)
        
        layout.addStretch()
        
        btn_row = QHBoxLayout()
        self.discover_btn = QPushButton("▶ Run")
        self.discover_btn.setFixedHeight(40)
        self.discover_btn.clicked.connect(self.run_hs_auto)
        btn_row.addWidget(self.discover_btn, 2)

        self.reset_btn = QPushButton("↺ Reset")
        self.reset_btn.setObjectName("dangerBtn")
        self.reset_btn.setFixedHeight(40)
        self.reset_btn.setToolTip("Restore the PyMOL display as it was before the first Run, "
                                  "and put the three parameters back to their defaults")
        self.reset_btn.clicked.connect(self.run_hs_reset)
        btn_row.addWidget(self.reset_btn, 1)
        layout.addLayout(btn_row)
        
        self.tab_discover.setLayout(layout)

    def setup_curation_tab(self):
        layout = QVBoxLayout()
        
        self.hs_table = QTableWidget(0, 2)
        self.hs_table.setHorizontalHeaderLabels(["Residue", "Atoms"])
        self.hs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.hs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.hs_table)
        
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("➕ Add Sele")
        self.add_btn.clicked.connect(self.run_hs_add)
        self.rem_btn = QPushButton("➖ Remove Sele")
        self.rem_btn.clicked.connect(self.run_hs_remove)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.rem_btn)
        layout.addLayout(btn_layout)
        
        self.clear_btn = QPushButton("🧹 Clear All")
        self.clear_btn.setObjectName("dangerBtn")
        self.clear_btn.clicked.connect(self.run_hs_clear)
        layout.addWidget(self.clear_btn)
        
        self.tab_curate.setLayout(layout)

    def setup_scoring_tab(self):
        layout = QVBoxLayout()
        self.scoring_output = QTextEdit()
        self.scoring_output.setReadOnly(True)
        self.scoring_output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.scoring_output)

        self.zone_btn = QPushButton("🌐 Show 4.5Å Zone (Cyan)")
        self.zone_btn.setToolTip("Draw a transparent 4.5 Å sphere around each hotspot atom "
                                 "(the RFD contact distance) for visual QC")
        self.zone_btn.clicked.connect(self.run_hs_zone)
        layout.addWidget(self.zone_btn)

        self.clear_score_btn = QPushButton("🗑️ Clear Score Board")
        self.clear_score_btn.clicked.connect(self.scoring_output.clear)
        layout.addWidget(self.clear_score_btn)
        self.tab_scoring.setLayout(layout)

    def setup_export_tab(self):
        layout = QVBoxLayout()
        
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Format:"))

        self.radio_rfd4 = QRadioButton("RFD4-Proteina", self.tab_export)
        self.radio_rfd4.setToolTip("conditions: / C_HOT: / - select: \"sel('A/*/56/[CG,OH]')\"")
        self.radio_rfd3 = QRadioButton("RFdiffusion3", self.tab_export)
        self.radio_rfd3.setToolTip("select_hotspots:\n  A56: CG,OH")
        self.radio_rfd4.setChecked(True)          # RFD4 is the default

        self.fmt_group = QButtonGroup(self)       # keeps the two mutually exclusive
        self.fmt_group.addButton(self.radio_rfd4)
        self.fmt_group.addButton(self.radio_rfd3)
        # Regenerate only on the newly-checked button, so this fires once per switch
        self.radio_rfd4.toggled.connect(lambda on: self.update_yaml() if on else None)
        self.radio_rfd3.toggled.connect(lambda on: self.update_yaml() if on else None)

        fmt_row.addWidget(self.radio_rfd4)
        fmt_row.addWidget(self.radio_rfd3)
        fmt_row.addStretch()
        layout.addLayout(fmt_row)

        self.yaml_output = QTextEdit()
        self.yaml_output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.yaml_output)
        
        self.gen_yaml_btn = QPushButton("📄 Refresh YAML")
        self.gen_yaml_btn.clicked.connect(self.update_yaml)
        layout.addWidget(self.gen_yaml_btn)

        self.copy_btn = QPushButton("📋 Copy to Clipboard")
        self.copy_btn.clicked.connect(self.copy_yaml)
        layout.addWidget(self.copy_btn)

        self.tab_export.setLayout(layout)

    # --- LOGIC BRIDGES ---
    
    def update_table(self):
        self.hs_table.setRowCount(0)
        for i, ((c, r), atoms) in enumerate(_hotspot_atoms.items()):
            self.hs_table.insertRow(i)
            self.hs_table.setItem(i, 0, QTableWidgetItem(f"{c}{r}"))
            self.hs_table.setItem(i, 1, QTableWidgetItem(", ".join(sorted(atoms))))

    def run_hs_auto(self):
        """The single Run implementation: scores, fills the score board, and
        refreshes the table. Previously this existed twice — once here without
        logging and once patched in by launch_hotspots_gui()."""
        sel = self.sel_combo.currentText()
        top = self.slider_top.value()
        rad = self.slider_rad.value()
        sas = self.slider_sas.value()

        self.scoring_output.clear()
        self.tabs.setCurrentWidget(self.tab_scoring)
        hs_auto(sel, top, rad, sas, atoms_per_res=2,
                logger=self.scoring_output.append)
        self.update_table()
        if _hotspot_atoms:
            self.log(f"Run finished on '{sel}': {len(_hotspot_atoms)} hotspot(s).")
        else:
            self.log(f"Run on '{sel}' found no residues "
                     f"(empty selection, no protein, or SASA cutoff too high).")

    def run_hs_zone(self):
        if not _hotspot_atoms:
            self.log("No hotspots defined: nothing to draw a zone around.")
            return
        hs_zone()
        self.log(f"4.5 Å zone drawn around {len(_hotspot_atoms)} hotspot residue(s).")

    def reset_sliders(self):
        """Put Top N / Radar Radius / SASA Cutoff back to their defaults.
        setValue fires valueChanged, so each value label follows automatically."""
        for slider, default in self._slider_defaults:
            slider.setValue(default)

    def run_hs_reset(self):
        # The sliders always go back to their defaults, whether or not there
        # is a display snapshot to restore.
        self.reset_sliders()
        restored = hs_reset()
        params = ", ".join(f"{name}={slider.value()}" for name, (slider, _)
                           in zip(("Top N", "Radius", "SASA"),
                                  self._slider_defaults))
        if restored:
            self.log(f"Display restored to its state before Run "
                     f"(hotspot list kept). Parameters reset: {params}.")
        else:
            self.log(f"No snapshot to restore (Run has not been used yet). "
                     f"Parameters reset: {params}.")

    def run_hs_add(self):
        sel = self.sel_combo.currentText()
        hs_add(sel)
        self.update_table()
        self.log(f"Added atoms from '{sel}'.")

    def run_hs_remove(self):
        sel = self.sel_combo.currentText()
        hs_remove(sel)
        self.update_table()
        self.log(f"Removed atoms in '{sel}'.")

    def run_hs_clear(self):
        hs_clear()
        self.update_table()
        self.yaml_output.clear()
        self.log("HotSpots cleared.")

    def current_fmt(self):
        return "rfd4" if self.radio_rfd4.isChecked() else "rfd3"

    def update_yaml(self):
        txt = hs_yaml(fmt=self.current_fmt())
        if txt:
            self.yaml_output.setText(txt)
        else:
            self.yaml_output.setText("# No hotspots defined.")

    def copy_yaml(self):
        self.update_yaml()
        self.yaml_output.selectAll()
        self.yaml_output.copy()
        self.log("YAML copied to clipboard.")

# ─────────────────────────────────────────────────────────────────────────────
#  Biophysical Engine (PyMOL Implementation)
# ─────────────────────────────────────────────────────────────────────────────

_SNAPSHOT_SCENE = "hs_before_run"
_snapshot = None   # dict with saved B-factors / settings, or None if no snapshot

def _take_snapshot():
    """Save the current display once, before the first change made by this tool.
    Later runs keep the original snapshot, so Reset always goes back to the
    state before the very first Run."""
    global _snapshot
    if _snapshot is not None:
        return
    # Colors, representations and camera view (built-in PyMOL scene)
    cmd.scene(_SNAPSHOT_SCENE, "store", color=1, rep=1, view=1)
    # B-factors are overwritten by get_area(load_b=1), so back them up too
    stored.hs_b_backup = {}
    cmd.iterate("all", "stored.hs_b_backup[(model, index)] = b")
    _snapshot = {
        "b": dict(stored.hs_b_backup),
        "dot_solvent": cmd.get("dot_solvent"),
        "objects": set(cmd.get_names("all")),
    }

def hs_reset():
    """Restore the display saved before the first Run. Returns True on success.
    The hotspot list itself is kept (use Clear All to empty it)."""
    global _snapshot
    if _snapshot is None:
        return False
    # Remove helper objects/selections created by this tool (not pre-existing ones)
    for obj in [_ZONE_OBJ, _MARKER_OBJ, "hs_centroid",
                "hs_auto_sticks", "hs_auto_spheres", "hs_boundary"]:
        if obj not in _snapshot["objects"]:
            try: cmd.delete(obj)
            except: pass
    # Restore B-factors
    stored.hs_b_backup = _snapshot["b"]
    cmd.alter("all", "b = stored.hs_b_backup.get((model, index), b)")
    cmd.set("dot_solvent", _snapshot["dot_solvent"])
    # Restore colors, representations and view
    cmd.scene(_SNAPSHOT_SCENE, "recall", animate=0)
    cmd.scene(_SNAPSHOT_SCENE, "delete")
    cmd.rebuild()
    _snapshot = None
    return True

def hs_auto(selection="sele", top=5, radius=0.0, sasa_cut=20.0, atoms_per_res=2, logger=None):
    top, radius, sasa_cut = int(top), float(radius), float(sasa_cut)
    _take_snapshot()

    # A fresh run REPLACES the previous result rather than merging into it,
    # so sliding a parameter and re-running gives exactly `top` residues.
    _hotspot_atoms.clear()
    _hotspot_resn.clear()

    ALT  = " and alt ''+A"        # keep only one conformation per atom
    PROT = " and polymer.protein" # ignore waters, ions, ligands and nucleic acids

    objs = cmd.get_object_list(f"({selection})")
    parent_obj = objs[0] if objs else selection

    stored.ca_coords = []
    cmd.iterate_state(1, f"({selection}) and name CA" + PROT + ALT, "stored.ca_coords.append((chain, resi, resn, x, y, z))")
    if not stored.ca_coords: return

    # ==========================================
    # SASA — computed ONCE, on a clean protein-only clone
    # ==========================================
    # Waters/ligands would shield the very surface residues we are looking for,
    # and alternative conformations shield each other, so both are stripped.
    # The clone also keeps get_area(load_b=1) from overwriting the real
    # object's B-factors. Per-atom and per-residue SASA both come from here,
    # so they can never disagree.
    # PyMOL executes cmd.* asynchronously, so delete/create/get_area can run out
    # of order: on a second run the delete would land *after* the create and wipe
    # the fresh clone ("Invalid selection name temp_sasa_clone"). A unique name
    # per run removes the need to delete first, and cmd.sync() makes sure the
    # object really exists before get_area reads it.
    clone = cmd.get_unused_name("temp_sasa_clone")
    try:
        cmd.create(clone, f"({parent_obj})" + PROT + ALT)
        # count_atoms returns a value, so it blocks until the queued create has
        # actually run: that is what guarantees the object exists below.
        # (cmd.sync() is not used here - it can time out with lock_attempt.)
        if cmd.count_atoms(clone) == 0:
            if logger: logger("No protein atoms in the selection - nothing to score.")
            return
        cmd.set("dot_solvent", 1, clone)
        cmd.get_area(clone, load_b=1)

        stored.atom_sasa = {}   # per atom:    (chain, resi, name) -> SASA
        stored.sasa      = {}   # per residue: (chain, resi)       -> summed SASA
        cmd.iterate(clone, "stored.atom_sasa[(chain, resi, name)] = b")
        cmd.iterate(clone, "stored.sasa[(chain, resi)] = stored.sasa.get((chain, resi), 0.0) + b")
    finally:
        # Always remove the clone, even if scoring raised, so none are left behind
        cmd.delete(clone)

    # Retrieve Beta Carbon coordinates
    stored.cb_coords = {}
    cmd.iterate_state(1, f"(model {parent_obj}) and name CB" + PROT + ALT, "stored.cb_coords[(chain, resi)] = (x, y, z)")

    # --- Visualize hs_boundary (v2) ---
    try: cmd.delete("hs_boundary")
    except: pass
    cmd.select("hs_boundary", f"({selection}) and name CA" + PROT + ALT)
    cmd.show("spheres", "hs_boundary")
    cmd.set("sphere_scale", 0.25, "hs_boundary")
    cmd.color("yellow", "hs_boundary")

    base_coords = [(x,y,z) for (c,r,n,x,y,z) in stored.ca_coords]
    raw_centroid = _centroid(base_coords)
    stored.all_ca = []
    cmd.iterate_state(1, f"(model {parent_obj}) and name CA" + PROT + ALT, "stored.all_ca.append((x, y, z))")

    # local_com: centroid of 8 Å neighbourhood (used for protrusion score)
    neighbors_8 = [c for c in stored.all_ca if _dist(c, raw_centroid) < 8.0]
    local_com = _centroid(neighbors_8) if len(neighbors_8) >= 5 else raw_centroid

    # protein COM as directional reference, then walk to true surface
    protein_com = _centroid(stored.all_ca)
    surface_centroid = _project_to_surface(raw_centroid, stored.all_ca, protein_com)

    # --- Visualize hs_centroid (v2) ---
    try: cmd.delete("hs_centroid")
    except: pass
    cmd.pseudoatom("hs_centroid", pos=list(surface_centroid))
    cmd.alter("hs_centroid", "vdw=0.5")
    cmd.show("spheres", "hs_centroid")
    cmd.color("red", "hs_centroid")
    cmd.rebuild()

    targets = []
    if radius > 0:
        stored.res = set()
        cmd.iterate_state(1, f"(model {parent_obj}) and name CA" + PROT +
                          f" and byres ((model {parent_obj})" + PROT +
                          f" within {radius} of hs_centroid)" + ALT,
                          "stored.res.add((chain, resi, resn, x, y, z))")
        targets = list(stored.res)
    else:
        targets = stored.ca_coords

    res_data = []
    for (chain, resi, resn, x, y, z) in targets:
        sasa_val = stored.sasa.get((chain, resi), 0.0)
        if radius == 0 and sasa_val < sasa_cut:
            cmd.color("gray50", f"(model {parent_obj} and chain '{chain}' and resi '{resi}')")
            continue
        elif radius > 0 and sasa_val < sasa_cut:
            continue

        c_score = _INTERFACE_SCORE.get(resn, 0.05)
        s_score = min(1.0, sasa_val / _MAX_SASA.get(resn, 200.0))
        p_score = min(1.0, _dist((x,y,z), local_com) / 8.0)
        neighbors = sum(1 for c in stored.all_ca if _dist(c, (x,y,z)) < 8.0)
        d_score = 1.0 - min(1.0, neighbors / 18.0)

        radar_dist = _dist((x,y,z), surface_centroid)
        dist_score = math.exp(-0.25 * radar_dist) # Sharper decay: strictly prioritizes the center
       
# --- Cα→Cβ Vector Filter & Anti-Glycine Filter ---
        orient_penalty = 1.0
        
        if resn == "GLY":
            # Glycine has no side chain to anchor RFdiffusion.
            # Apply a severe penalty by default.
            orient_penalty = 0.2 
            
        elif (chain, resi) in stored.cb_coords:
            cb_coord = stored.cb_coords[(chain, resi)]
            ca_coord = (x, y, z)
            
            # Side-chain vector (Cα → Cβ)
            v_sidechain = _normalize(_sub(cb_coord, ca_coord))
            # Vector toward the target (Cα → Centroid)
            v_target = _normalize(_sub(surface_centroid, ca_coord))
            
            # Cosine of the angle between the two vectors
            cos_theta = _dot(v_sidechain, v_target)
            
            # If cosine is negative (side chain points away), apply severe penalty
            if cos_theta < 0:
                orient_penalty = 0.2
            else:
                orient_penalty = 1.0

        # Base score
        base_score = (0.30 * c_score) + (0.20 * s_score) + (0.20 * p_score) + (0.15 * d_score) + (0.15 * dist_score)
        
        # Final score penalized by orientation
        final_score = base_score * orient_penalty

        if radius == 0:
            cmd.color(_score_color(final_score), f"(model {parent_obj} and chain '{chain}' and resi '{resi}')")

        # Each residue is added to the list only once
        res_data.append((chain, resi, resn, (x, y, z), radar_dist, c_score, s_score, p_score, d_score, dist_score, final_score))

    if not res_data: return
    res_data.sort(key=lambda item: -item[10])

    # Atom Selection
    stored.sc_atoms = []
    target_sel = f"(model {parent_obj})" if radius > 0 else f"({selection})"
    cmd.iterate_state(1, f"{target_sel} and not hydrogen and not name N+CA+C+O+OXT" + PROT + ALT, "stored.sc_atoms.append((chain, resi, name, x, y, z))")
    sc_index = collections.defaultdict(list)
    for c, r, n_atom, x, y, z in stored.sc_atoms: sc_index[(c, r)].append((n_atom, (x, y, z)))

    if logger:
        logger("-" * 88)
        logger(f"{'Residue':<8} {'AA':<4} {'Dist':<5} {'Chem':<5} {'SASA%':<6} {'Prot':<5} {'Prox':<5} {'Score':<6} {'Bar':<15} Targets")
        logger("-" * 88)

    sticks_sel, spheres_sel = [], []
    n_final = min(top, len(res_data))
    for i in range(n_final):
        chain, resi, resn, coord_ca, dist, c_sc, s_sc, p_sc, d_sc, prox_sc, final_score = res_data[i]
        sc_list = sc_index.get((chain, resi), [])
        if not sc_list: 
                chosen = ["CA"]
        else:
                # 1. Sort side-chain atoms by SASA (highest to lowest)
            sc_sorted = sorted(sc_list, key=lambda a: stored.atom_sasa.get((chain, resi, a[0]), 0), reverse=True)
                
                # 2. Pick the most solvent-exposed atoms directly
            chosen = [a[0] for a in sc_sorted[:atoms_per_res]]
        
        if (chain, resi) not in _hotspot_atoms: _hotspot_atoms[(chain, resi)] = set()
        _hotspot_atoms[(chain, resi)].update(chosen)
        _hotspot_resn[(chain, resi)] = resn
        
        if logger:
            logger(f"{chain}{resi:<8} {resn:<4} {dist:>4.1f}A  {c_sc:.2f}  {s_sc:>4.0%}  {p_sc:.2f}  {prox_sc:.2f}  {final_score:>5.3f}  {_bar(final_score, 13)}  {', '.join(sorted(chosen))}")
        
        res_str = f"(model {parent_obj} and chain '{chain}' and resi '{resi}')"
        sticks_sel.append(res_str)
        spheres_sel.append(f"({res_str} and name {'+'.join(chosen)})")

    if logger: logger("-" * 88)

    if radius > 0:
        try: cmd.delete("hs_auto_sticks"); cmd.delete("hs_auto_spheres")
        except: pass
        cmd.select("hs_auto_sticks", " or ".join(sticks_sel))
        cmd.select("hs_auto_spheres", " or ".join(spheres_sel))
        cmd.show("sticks", "hs_auto_sticks")
        cmd.show("spheres", "hs_auto_spheres")
        cmd.set("sphere_scale", 0.35, "hs_auto_spheres")
        for i in range(n_final):
            c, r, _, _, _, _, _, _, _, _, f_sc = res_data[i]
            cmd.color(_score_color(f_sc), f"(model {parent_obj} and chain '{c}' and resi '{r}')")
    else:
        _rebuild_marker_obj()
    
    cmd.show("spheres", "hs_centroid")
    cmd.color("red", "hs_centroid")

def hs_add(selection="sele"):
    _take_snapshot()
    stored.picked = []
    cmd.iterate_state(1, f"({selection}) and not hydrogen and alt ''+A", "stored.picked.append((chain, resi, name, resn))")
    for chain, resi, name, resn in stored.picked:
        if (chain, resi) not in _hotspot_atoms: _hotspot_atoms[(chain, resi)] = set()
        _hotspot_atoms[(chain, resi)].add(name)
        _hotspot_resn[(chain, resi)] = resn
    _rebuild_marker_obj()

def hs_remove(selection="sele"):
    stored.picked = []
    cmd.iterate_state(1, f"({selection}) and not hydrogen and alt ''+A", "stored.picked.append((chain, resi, name))")
    for chain, resi, name in stored.picked:
        key = (chain, resi)
        if key in _hotspot_atoms and name in _hotspot_atoms[key]:
            _hotspot_atoms[key].discard(name)
            if not _hotspot_atoms[key]:
                del _hotspot_atoms[key]
                _hotspot_resn.pop(key, None)
    _rebuild_marker_obj()

def hs_zone(alpha=0.35):
    _take_snapshot()
    cmd.delete(_ZONE_OBJ)
    if not _hotspot_atoms: return
    stored.coords = []
    for (chain, resi), atoms in _hotspot_atoms.items():
        for a in atoms:
            cmd.iterate_state(1, f"chain '{chain}' and resi '{resi}' and name '{a}' and alt ''+A", "stored.coords.append((x,y,z))")
    for i, coord in enumerate(stored.coords):
        cmd.pseudoatom(_ZONE_OBJ, pos=list(coord), vdw=CUTOFF_A)
    cmd.show("spheres", _ZONE_OBJ)
    cmd.set("sphere_transparency", alpha, _ZONE_OBJ)
    cmd.color("cyan", _ZONE_OBJ)
    _rebuild_marker_obj()

def _sorted_hotspots():
    """Hotspots sorted by chain then numeric residue number."""
    def key(item):
        (c, r), _ = item
        # Split '52A' into (52, 'A') so insertion codes sort next to their number
        digits = ""
        for ch in str(r):
            if ch.isdigit() or (ch == "-" and not digits): digits += ch
            else: break
        try: return (c, int(digits), str(r)[len(digits):])
        except ValueError: return (c, 0, str(r))
    return sorted(_hotspot_atoms.items(), key=key)

def hs_yaml(fmt="rfd4"):
    """Build the hotspot config block.

    fmt='rfd4' → RFD4-Proteina selector mini-language:
        conditions:
          C_HOT:
            true:
              - select: "sel('A/*/56/[CG,OH]')"   # TYR56

    fmt='rfd3' → RFdiffusion3 residue->atoms mapping:
        select_hotspots:
          A56: CG,OH
    """
    if not _hotspot_atoms: return ""
    items = _sorted_hotspots()

    if fmt == "rfd3":
        rows = [(f"  {c}{r}: {','.join(sorted(atoms))}", _hotspot_resn.get((c, r)), r)
                for (c, r), atoms in items]
        width = max(len(t) for t, _, _ in rows)
        lines = ["select_hotspots:"]
        for text, resn, r in rows:
            lines.append(f"{text.ljust(width)}   # {resn}{r}" if resn else text)
        return "\n".join(lines)

    # --- RFD4-Proteina ---
    # sel('<chain>/<res_name>/<res_id>/<atom_name>'); '*' = any res_name.
    # res_id is the ORIGINAL input numbering, not the renumbered contig output.
    entries = []
    for (c, r), atoms in items:
        sel = f"sel('{c}/*/{r}/[{','.join(sorted(atoms))}]')"
        entries.append((f'      - select: "{sel}"', _hotspot_resn.get((c, r)), r))

    width = max(len(e[0]) for e in entries)
    lines = ["conditions:", "  C_HOT:", "    true:"]
    for text, resn, r in entries:
        lines.append(f"{text.ljust(width)}   # {resn}{r}" if resn else text)
    return "\n".join(lines)

def hs_clear():
    _hotspot_atoms.clear()
    _hotspot_resn.clear()
    for obj in [_ZONE_OBJ, _MARKER_OBJ, "hs_centroid", "hs_auto_sticks", "hs_auto_spheres", "hs_boundary"]:
        try: cmd.delete(obj)
        except: pass

# ─────────────────────────────────────────────────────────────────────────────
#  Launch
# ─────────────────────────────────────────────────────────────────────────────

_hs_dialog = None

def launch_hotspots_gui():
    global _hs_dialog
    if _hs_dialog is None:
        _hs_dialog = HotSpotsDialog()
    _hs_dialog.refresh_selections()
    _hs_dialog.show()
    _hs_dialog.raise_()

cmd.extend("hs_gui", launch_hotspots_gui)
cmd.extend("hs_auto", hs_auto)
cmd.extend("hs_add", hs_add)
cmd.extend("hs_remove", hs_remove)
cmd.extend("hs_clear", hs_clear)
cmd.extend("hs_reset", hs_reset)
cmd.extend("hs_yaml", lambda fmt="rfd4": print(hs_yaml(fmt) or "# No hotspots defined."))

def __init_plugin__(app=None):
    from pymol.plugins import addmenuitemqt
    addmenuitemqt("HotSpots Finder (PyQt)", launch_hotspots_gui)

# ─────────────────────────────────────────────────────────────────────────────
#  Auto-launch
# ─────────────────────────────────────────────────────────────────────────────
#  Set to False (or `HS_AUTOLAUNCH = False` before `run`) to keep the GUI closed
#  on load and open it manually with `hs_gui`.
HS_AUTOLAUNCH = globals().get("HS_AUTOLAUNCH", True)

# When PyMOL's Plugin Manager imports this file it calls __init_plugin__ and only
# adds the menu entry; opening a window on import would be wrong there.
_LOADED_AS_PLUGIN = __name__.startswith(("pmg_tk.startup", "pymol.plugins"))


def _auto_launch():
    """Open the GUI on `run`. Returns True if a window was actually opened."""
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        try:
            from PyQt5.QtWidgets import QApplication
        except ImportError:
            return False
    # No QApplication → headless (pymol -cq) or the legacy Tk GUI: nothing to attach to
    if QApplication.instance() is None:
        return False
    launch_hotspots_gui()
    return True


print("HotSpots Finder v3.7 (PyQt) loaded.")
if HS_AUTOLAUNCH and not _LOADED_AS_PLUGIN:
    try:
        if _auto_launch():
            print("  GUI opened. Reopen it any time with 'hs_gui'.")
        else:
            print("  No Qt GUI available (headless?). Type 'hs_gui' once PyMOL's "
                  "Qt interface is up.")
    except Exception as _e:
        # Never let a GUI failure abort loading the command-line API
        print(f"  Could not open the GUI automatically ({_e}). Type 'hs_gui' to retry.")
else:
    print("  Type 'hs_gui' or use the Plugins menu.")
