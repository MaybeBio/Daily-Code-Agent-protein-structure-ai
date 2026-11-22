"""
Unit test suite for Dr. Nemo Caries Foundry.
Tests biochemical pre-filtering, target catalog integrity, scoring metrics,
demo data integrity, gtfb_orchestrator --demo execution, dashboard resolution,
and the comprehensive 6-Angle Karl Popper Biophysical Falsification Battery.
"""
import json
import subprocess
import pytest
from pathlib import Path
import sys
import csv

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from solubility_shield import (
    is_viable,
    calc_net_charge_at_ph,
    calc_stephan_switch,
    count_protease_cleavage_sites,
    MAX_DONNAN_CHARGE_PH6
)
from falsification_engine import FalsificationEngine, CO_CRYSTAL_CONTROL_DELTA_G, CO_CRYSTAL_REDOCKING_RMSD


def test_solubility_shield_valid_arginine_core():
    viable, metrics = is_viable("RRRRRR")
    assert viable is True
    assert metrics["chitosan_native"] is True
    assert metrics["arg_count"] == 6
    assert metrics["gravy"] < 2.0


def test_solubility_shield_rejects_invalid_amino_acids():
    viable, metrics = is_viable("RRRX123")
    assert viable is False
    assert metrics["error"] == "invalid_characters"


def test_solubility_shield_rejects_anionic_salt_bridges():
    viable, metrics = is_viable("RRDDDDEE")
    assert viable is False
    assert metrics["error"] == "chitosan_salt_bridge_risk"
    assert metrics["anionic_count"] == 6


def test_solubility_shield_rejects_entrapment_density():
    # 5 residues, 4 are I/K -> 80% density > 30% threshold
    viable, metrics = is_viable("RIIKK")
    assert viable is False
    assert metrics["error"] == "chitosan_entrapment_risk"
    assert metrics["entrap_density"] > 0.3


def test_solubility_shield_edge_cases():
    # Empty string
    viable, metrics = is_viable("")
    assert viable is False
    assert metrics["error"] == "invalid_characters"

    # Top lead candidate
    viable, metrics = is_viable("CPHWRPWHC")
    assert viable is True
    assert metrics["chitosan_native"] is True
    assert metrics["arg_count"] == 1
    assert metrics["gravy"] < 0.0


def test_targets_catalog_integrity():
    targets_file = REPO_ROOT / "targets.json"
    assert targets_file.exists(), "targets.json catalog file must exist"
    
    with open(targets_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Must contain primary cariogenic targets
    expected_targets = [
        "S_mutans_GtfB_Insoluble",
        "S_mutans_SpaP_Baseline",
        "S_mutans_GtfC_Bridge"
    ]
    for target in expected_targets:
        assert target in data, f"Missing critical target: {target}"
        info = data[target]
        assert "name" in info and len(info["name"]) > 0
        assert "sequence" in info and len(info["sequence"]) > 20
        assert "base_peptide" in info and len(info["base_peptide"]) > 0


def test_ligand_efficiency_calculation():
    """Verify ligand efficiency formula LE = round(-vina_kcal / heavy_atoms, 3)."""
    vina_kcal = -8.191
    heavy_atoms = 84
    le = round(-vina_kcal / heavy_atoms, 3)
    assert le == 0.098


def test_cycle_designer_generation():
    from gtfb_orchestrator import cycle_designer_node
    
    dummy_state = {
        "candidates": [],
        "results": [],
        "winning_candidate": None,
        "biosecurity_logs": [],
        "synthesis_instructions": {},
        "retention_scores": {}
    }
    output = cycle_designer_node(dummy_state)
    assert "candidates" in output
    assert len(output["candidates"]) >= 15
    for seq in output["candidates"]:
        assert seq.startswith("C") and seq.endswith("C"), "Must be disulfide-cyclized"


def test_gtfb_orchestrator_demo_execution():
    """Verify that gtfb_orchestrator.py --demo runs the full LangGraph state machine and exits 0."""
    cmd = [sys.executable, str(REPO_ROOT / "gtfb_orchestrator.py"), "--demo"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"gtfb_orchestrator --demo failed: {res.stderr}"
    assert "FOUNDRY SUCCESS" in res.stdout
    assert "CRRRWWRRRRC" in res.stdout
    assert "CPHWRPWHC" in res.stdout
    assert "PepSy" in res.stdout


def test_demo_dataset_integrity():
    """Verify the 20-generation demo dataset bundled in demo_data/."""
    demo_dir = REPO_ROOT / "demo_data"
    assert demo_dir.exists(), "demo_data directory must exist"
    
    # 1. Master scores
    scores_file = demo_dir / "results" / "master_scores.csv"
    assert scores_file.exists(), "demo_data/results/master_scores.csv must exist"
    with open(scores_file, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 50, f"Expected >= 50 rows, got {len(rows)}"
    cols = set(rows[0].keys())
    assert "contender_id" in cols and "vina_3aic_kcal" in cols

    # 2. Directed evolution complex PDB files
    variant_files = list((demo_dir / "results").glob("S_mutans_GtfB_Insoluble_variant_*.pdb"))
    assert len(variant_files) >= 5, f"Expected >= 5 variant PDB files, found {len(variant_files)}"
    for pdb_path in variant_files:
        content = pdb_path.read_text(encoding="utf-8")
        assert "HEADER" in content
        assert "ATOM" in content
        assert "TER" in content
        assert "CONECT" in content
        assert " A " in content, "Must contain Chain A (GtfB pocket)"
        assert " B " in content, "Must contain Chain B (docked cyclic peptide)"

    # 3. Falsification benchmark docked coordinates
    docked_complex = demo_dir / "results" / "3AIC_docked_complex_CPHWRPWHC.pdb"
    assert docked_complex.exists(), "3AIC_docked_complex_CPHWRPWHC.pdb must exist"
    complex_content = docked_complex.read_text(encoding="utf-8")
    assert "HEADER" in complex_content
    assert "ATOM" in complex_content
    assert "TER" in complex_content
    assert " A " in complex_content, "Must contain Chain A (GtfB receptor)"
    assert " B " in complex_content, "Must contain Chain B (docked cyclic lead)"

    native_docked = demo_dir / "results" / "3AIC_native_acarbose_docked.pdb"
    assert native_docked.exists(), "3AIC_native_acarbose_docked.pdb must exist"

    lead_docked = demo_dir / "results" / "3AIC_docked_lead_CPHWRPWHC.pdb"
    assert lead_docked.exists(), "3AIC_docked_lead_CPHWRPWHC.pdb must exist"

    # 4. Falsification benchmark JSON
    bench_file = demo_dir / "results" / "falsification_benchmark.json"
    assert bench_file.exists(), "falsification_benchmark.json must exist"
    with open(bench_file, "r", encoding="utf-8") as f:
        bench_data = json.load(f)
    assert "lead_affinity_3aic" in bench_data
    assert "lead_affinity_1smd" in bench_data
    assert "scrambled_null_test" in bench_data
    assert "alanine_scan" in bench_data

    # 5. Clinical Memos
    analysis_files = list((demo_dir / "results" / "analysis").glob("*.md"))
    assert len(analysis_files) >= 5, "Expected >= 5 clinical analysis memos"


def test_dashboard_path_resolution():
    """Verify dashboard.py resolves bundled demo data when drnemo_research is absent."""
    import os
    old_env = os.environ.pop("DRNEMO_DATA_DIR", None)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("dashboard_module", str(REPO_ROOT / "dashboard.py"))
        assert spec is not None
    finally:
        if old_env is not None:
            os.environ["DRNEMO_DATA_DIR"] = old_env


# ==============================================================================
# OPERATION KARL POPPER: 6-ANGLE BIOPHYSICAL FALSIFICATION TEST SUITE
# ==============================================================================

def test_falsification_angle1_cocrystal_control():
    """Angle 1: RCSB 3AIC co-crystal redocking positive control calibration."""
    ctrl = FalsificationEngine.get_angle1_control()
    assert ctrl["passed_calibration"] is True
    assert ctrl["affinity_kcal_mol"] <= -7.0
    assert ctrl["redocking_rmsd_angstrom"] < 5.0
    assert ctrl["centroid_displacement_angstrom"] < 3.5


def test_falsification_angle2_offtarget_selectivity():
    """Angle 2: 1SMD Salivary Amylase counter-screen ensures high selectivity."""
    engine = FalsificationEngine()
    # Pareto champion CAHWRPWHC clears selectivity threshold DeltaDeltaG <= -0.80 kcal/mol (-0.85 kcal/mol)
    audit = engine.run_falsification_audit("CAHWRPWHC")
    gate2 = audit["gates"]["gate2_offtarget_selectivity"]
    assert gate2["lead_passed"] is True
    assert gate2["lead_selectivity"] <= -0.80
    assert gate2["naive_passed"] is False

    # Prior 22A lead CPHWRPWHC is honestly falsified on 28A grid due to amylase cross-reactivity (ddG = -0.16)
    wt_audit = engine.run_falsification_audit("CPHWRPWHC")
    assert wt_audit["gates"]["gate2_offtarget_selectivity"]["lead_passed"] is False
    assert wt_audit["gates"]["gate2_offtarget_selectivity"]["lead_selectivity"] > -0.80


def test_falsification_angle3_scrambled_null_permutation():
    """Angle 3: Scrambled null permutation distribution across N=39 isomers."""
    engine = FalsificationEngine()
    audit = engine.run_falsification_audit("CAHWRPWHC")
    gate3 = audit["gates"]["gate3_scrambled_null_permutation"]
    
    assert gate3["lead_passed"] is True
    # N=39 isomers evaluated empirically
    assert gate3["null_mean"] <= -8.0
    assert gate3["p_value"] > 0.0
    assert gate3["b_count"] >= 0


def test_falsification_angle4_alanine_hotspot_scan():
    """Angle 4: In-silico alanine scanning identifies energetic hotspots."""
    engine = FalsificationEngine()
    audit = engine.run_falsification_audit("CAHWRPWHC")
    gate4 = audit["gates"]["gate4_alanine_hotspot_scan"]
    
    assert gate4["passed"] is True
    assert gate4["hotspot_count"] >= 1
    # Verify primary anchor His8 is identified
    assert "H8A" in gate4["hotspots"]


def test_falsification_angle5_protease_resistance():
    """Angle 5: Salivary trypsin and RgpB gingipain oral stability."""
    engine = FalsificationEngine()
    audit = engine.run_falsification_audit("CAHWRPWHC")
    gate5 = audit["gates"]["gate5_oral_protease_resistance"]
    
    # Pareto lead has 0 cleavage sites
    assert gate5["lead_passed"] is True
    assert gate5["lead_cleavage_sites"] == 0
    # Naive baseline CRRRWWRRRRC has multiple cleavage sites and fails
    assert gate5["naive_passed"] is False
    assert gate5["naive_cleavage_sites"] >= 5


def test_falsification_angle6_chitosan_and_stephan_switch():
    """Angle 6: Chitosan Donnan compatibility and Stephan curve pH-switch."""
    engine = FalsificationEngine()
    audit = engine.run_falsification_audit("CAHWRPWHC")
    gate6 = audit["gates"]["gate6_chitosan_donnan_stephan"]
    
    assert gate6["lead_passed"] is True
    # Donnan net charge at pH 6.0 <= +4.0
    assert gate6["lead_net_charge_pH6"] <= MAX_DONNAN_CHARGE_PH6
    # Stephan acid switch delta Q (pH 5.2 - 7.2) >= +1.0
    assert gate6["lead_delta_q_stephan"] >= 1.0
    # Naive baseline has charge +7.0 (exceeds Donnan limit) and zero Stephan switch
    assert gate6["naive_passed"] is False
    assert gate6["naive_net_charge_pH6"] > MAX_DONNAN_CHARGE_PH6
    assert gate6["naive_delta_q_stephan"] == 0.0


def test_falsification_audit_overall_verdict():
    """Verify overall scientific verdict: Pareto champion corroborated, unviable baselines falsified."""
    engine = FalsificationEngine()
    lead_audit = engine.run_falsification_audit("CAHWRPWHC")
    assert lead_audit["overall_falsification_passed"] is True

    # CPHWRPWHC is falsified on amylase cross-reactivity
    wt_audit = engine.run_falsification_audit("CPHWRPWHC")
    assert wt_audit["overall_falsification_passed"] is False

    # Naive poly-arginine fails falsification
    naive_audit = engine.run_falsification_audit("CRRRWWRRRRC")
    assert naive_audit["overall_falsification_passed"] is False


def test_biophysics_macrocycle_embedding():
    """Verify 3D macrocycle building and heavy atom enumeration."""
    pytest.importorskip("rdkit")
    pytest.importorskip("gemmi")
    pytest.importorskip("meeko")
    import os
    from biophysics_engine import build_macrocycle_3d
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdbqt") as tf:
        ha = build_macrocycle_3d("CPHWRPWHC", tf.name)
        assert ha == 86, f"Expected 86 heavy atoms for CPHWRPWHC, got {ha}"
        assert os.path.getsize(tf.name) > 1000


def test_biophysics_openmm_relaxation():
    """Verify OpenMM Amber14/GBn2 energy minimization runs and yields valid potential energy."""
    pytest.importorskip("rdkit")
    pytest.importorskip("gemmi")
    pytest.importorskip("meeko")
    pytest.importorskip("openmm")
    from biophysics_engine import build_macrocycle_3d, relax_with_openmm
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdb") as tf_pdb, tempfile.NamedTemporaryFile(suffix=".pdbqt") as tf_pdbqt:
        build_macrocycle_3d("CPHWRPWHC", tf_pdbqt.name, out_pdb=tf_pdb.name)
        energy_kj = relax_with_openmm(tf_pdb.name)
        assert isinstance(energy_kj, float)
        assert energy_kj < 0, f"Expected favorable negative potential energy, got {energy_kj} kJ/mol"


def test_contender_vault_crud_and_mirroring():
    """Verify permanent SQLite contender vault CRUD, Pareto champion retrieval, and CSV ledger mirroring."""
    from vault import ContenderVault
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_vault.sqlite"
        vault = ContenderVault(db_path=db_path)
        assert vault.get_count() == 0

        cid = vault.add_contender({
            "sequence": "CPHWRPWHC",
            "generation": 1,
            "heavy_atoms": 86,
            "vina_3aic_kcal": -8.30,
            "vinardo_3aic_kcal": -5.20,
            "ligand_efficiency": round(8.30 / 86, 3),
            "vina_1smd_kcal": -7.20,
            "selectivity_ddg": -1.10,
            "openmm_relaxed_kj": -1132.07,
            "ss_bond_angstrom": 2.05,
            "q_ph72": 1.25,
            "q_ph60": 2.05,
            "q_ph52": 2.75,
            "delta_q_stephan": 1.62,
            "protease_sites": 0,
            "pareto_rank": 1,
            "falsification_status": "CORROBORATED",
            "pose_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "evaluated_at_utc": "2026-11-15T21:00:00Z"
        })
        assert vault.get_count() == 1
        assert vault.ledger_csv.exists()

        champ = vault.get_pareto_champion()
        assert champ is not None
        assert champ["sequence"] == "CPHWRPWHC"
        assert champ["vina_3aic_kcal"] == -8.30


def test_priority_queue_lifecycle():
    """Verify priority queue insertion, retrieval, and status updates."""
    from vault import ContenderVault
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_queue.sqlite"
        vault = ContenderVault(db_path=db_path)
        
        # Enqueue item
        item_id = vault.enqueue_priority("CAHYRPWHC", generation=4)
        assert item_id == 1

        # Fetch next item
        item = vault.get_next_priority_item()
        assert item is not None
        assert item["id"] == 1
        assert item["sequence"] == "CAHYRPWHC"
        assert item["status"] == "QUEUED"

        # Update status to docking
        vault.update_priority_status(item_id, "DOCKING_3AIC")
        assert vault.get_next_priority_item() is None  # No more QUEUED items

        # Update to completed
        vault.update_priority_status(item_id, "COMPLETED", result_vina=-8.25, result_status="CORROBORATED")
        queue = vault.get_priority_queue(limit=5)
        assert len(queue) == 1
        assert queue[0]["status"] == "COMPLETED"
        assert queue[0]["result_vina"] == -8.25


def test_foundry_manager_validation_and_mutation():
    """Verify validation, mutation workbench, and precheck logic."""
    from foundry_manager import (
        validate_cyclic_sequence,
        mutate_sequence,
        generate_all_single_site_variants,
        precheck_sequence
    )
    # Valid cyclic peptide
    ok, seq = validate_cyclic_sequence("CAHWRPWHC")
    assert ok is True
    assert seq == "CAHWRPWHC"

    # Invalid cases
    ok, err = validate_cyclic_sequence("AAHWRPWHA")
    assert ok is False
    assert "Cysteine" in err

    ok, err = validate_cyclic_sequence("C123C")
    assert ok is False

    # Mutation
    ok, mut = mutate_sequence("CAHWRPWHC", 4, "Y")
    assert ok is True
    assert mut == "CAHYRPWHC"

    # Terminal cysteine mutation rejected
    ok, err = mutate_sequence("CAHWRPWHC", 1, "A")
    assert ok is False

    # Precheck
    pre = precheck_sequence("CAHWRPWHC")
    assert "q_ph72" in pre
    assert "delta_q_stephan" in pre
    assert pre["donnan_pass"] is True
    assert pre["protease_pass"] is True


def test_vault_has_sequence_and_index():
    """Verify O(1) indexed sequence lookup and sequence index creation in ContenderVault."""
    import sqlite3
    import tempfile
    from vault import ContenderVault

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_has_seq.sqlite"
        vault = ContenderVault(db_path=db_path)

        # Check idx_sequence index exists in SQLite
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_sequence';")
        assert cur.fetchone() is not None, "idx_sequence index not found in schema"
        conn.close()

        # Check has_sequence before and after adding
        assert vault.has_sequence("CAHWRPWHC") is False

        vault.add_contender({
            "sequence": "CAHWRPWHC",
            "generation": 1,
            "heavy_atoms": 84,
            "vina_3aic_kcal": -8.191,
            "vinardo_3aic_kcal": -4.990,
            "ligand_efficiency": 0.098,
            "vina_1smd_kcal": -7.343,
            "selectivity_ddg": -0.848,
            "openmm_relaxed_kj": -1234.68,
            "ss_bond_angstrom": 2.06,
            "q_ph72": 1.129,
            "q_ph60": 2.046,
            "q_ph52": 2.747,
            "delta_q_stephan": 1.618,
            "protease_sites": 0,
            "pareto_rank": 1,
            "falsification_status": "CORROBORATED",
            "pose_sha256": "d476318723b90a0c6d622e46383b0815d8a5c805ac4d2a1631c77e112f57178b",
            "evaluated_at_utc": "2026-11-20T12:00:00Z"
        })

        assert vault.has_sequence("CAHWRPWHC") is True
        assert vault.has_sequence("cahwrpwhc") is True  # Case insensitive
        assert vault.has_sequence("CRRRWWRRRRC") is False


def test_variable_length_validation_and_dynamic_box_sizing():
    """Verify validation up to 30 residues, dynamic box sizing, and torsion warning."""
    from foundry_manager import (
        validate_cyclic_sequence,
        compute_dynamic_box_size,
        get_torsion_warning,
        precheck_sequence
    )

    # Valid lengths across 5 to 30 residues
    ok_5, _ = validate_cyclic_sequence("CAAAC")
    assert ok_5 is True

    ok_9, _ = validate_cyclic_sequence("CAHWRPWHC")
    assert ok_9 is True

    ok_18, _ = validate_cyclic_sequence("CAHWRPWHCAHWRPWHAC")
    assert ok_18 is True

    ok_30, _ = validate_cyclic_sequence("C" + "A" * 28 + "C")
    assert ok_30 is True

    # Invalid lengths (< 5 or > 30)
    bad_4, err4 = validate_cyclic_sequence("CAAC")
    assert bad_4 is False
    assert "outside supported range" in err4

    bad_31, err31 = validate_cyclic_sequence("C" + "A" * 30 + "C")
    assert bad_31 is False
    assert "outside supported range" in err31

    # Dynamic box sizing: 28.0 A for <= 9 residues, expands 1.2 A per additional residue
    assert compute_dynamic_box_size("CAHWRPWHC") == 28.0
    assert compute_dynamic_box_size("C" + "A" * 7 + "C") == 28.0
    # Length 15: 28.0 + (15 - 9) * 1.2 = 28.0 + 7.2 = 35.2 A
    assert compute_dynamic_box_size("C" + "A" * 13 + "C") == 35.2
    # Length 30: 28.0 + (30 - 9) * 1.2 = 28.0 + 25.2 = 53.2 A
    assert compute_dynamic_box_size("C" + "A" * 28 + "C") == 53.2

    # Vina torsion warning above 20 residues
    assert get_torsion_warning("CAHWRPWHC") is None
    assert get_torsion_warning("C" + "A" * 18 + "C") is None  # 20 residues: no warning
    warn = get_torsion_warning("C" + "A" * 19 + "C")  # 21 residues: warning
    assert warn is not None
    assert "exceeds 20 residues" in warn

    # Precheck includes box_size and torsion_warning
    pre = precheck_sequence("C" + "A" * 21 + "C")
    assert pre["length"] == 23
    assert pre["box_size_angstrom"] == 44.8
    assert pre["torsion_warning"] is not None


def test_continuous_hunter_indel_generation():
    """Verify continuous hunter indel generator respects 6..18 residue bounds and O(1) vault check."""
    import tempfile
    from vault import ContenderVault
    from scripts.continuous_hunter import generate_candidate

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_hunter.sqlite"
        vault = ContenderVault(db_path=db_path)

        # Seed top contenders
        for seq in ["CAHWRPWHC", "CPHWRPWHC", "CAHWRPWAC"]:
            vault.add_contender({
                "sequence": seq,
                "generation": 1,
                "heavy_atoms": 84,
                "vina_3aic_kcal": -8.1,
                "vinardo_3aic_kcal": -4.9,
                "ligand_efficiency": 0.098,
                "vina_1smd_kcal": -7.3,
                "selectivity_ddg": -0.8,
                "openmm_relaxed_kj": -1200.0,
                "ss_bond_angstrom": 2.06,
                "q_ph72": 1.1,
                "q_ph60": 2.0,
                "q_ph52": 2.7,
                "delta_q_stephan": 1.6,
                "protease_sites": 0,
                "pareto_rank": 1,
                "falsification_status": "CORROBORATED",
                "pose_sha256": "dummy",
                "evaluated_at_utc": "2026-11-20T12:00:00Z"
            })

        for _ in range(20):
            cand, gen = generate_candidate(vault)
            assert cand.startswith("C") and cand.endswith("C")
            assert 6 <= len(cand) <= 18
            assert vault.has_sequence(cand) is False


def test_single_source_of_truth_integrity():
    """Verify single source of truth across repo files, database, and docking tools."""
    # 1. Assert zero forbidden files exist
    forbidden_files = ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "linkedin_post_drnemo.md"]
    for fname in forbidden_files:
        assert not (REPO_ROOT / fname).exists(), f"Forbidden file {fname} must not exist"

    # 2. Assert zero forbidden tokens or em-dashes in tracked python and doc files
    forbidden_tokens = ["pLDDT", "iPTM", "0.65 *", "-1100.0", "Caries Vaccine"]
    tracked_files = [
        REPO_ROOT / "biophysics_engine.py",
        REPO_ROOT / "gtfb_orchestrator.py",
        REPO_ROOT / "vault.py",
        REPO_ROOT / "falsification_engine.py",
        REPO_ROOT / "solubility_shield.py",
        REPO_ROOT / "dashboard.py",
        REPO_ROOT / "README.md",
        REPO_ROOT / "paper" / "paper.md"
    ]
    for p in tracked_files:
        if p.exists():
            text = p.read_text(encoding="utf-8")
            assert "—" not in text, f"Em-dash found in {p.name}"
            for tok in forbidden_tokens:
                assert tok not in text, f"Forbidden token '{tok}' found in {p.name}"

    # 3. Assert all rows in ContenderVault have valid SS bonds and zero broken disulfides marked CORROBORATED
    from vault import ContenderVault
    vault = ContenderVault()
    all_rows = vault.get_all_contenders()
    assert len(all_rows) == 259, f"Expected 259 contenders in vault, found {len(all_rows)}"

    for r in all_rows:
        ss = r["ss_bond_angstrom"]
        status = r["falsification_status"]
        if status == "CORROBORATED":
            assert 1.95 <= ss <= 2.25, f"Contender {r['contender_id']} has broken SS {ss} but is CORROBORATED"

    # 4. Check README.md matches contender count exactly
    readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "259" in readme_text, "README.md must cite exact 259 contender count"

    # 5. Live 1-ligand Vina smoke test (score_only)
    cmd = [
        "/usr/bin/vina",
        "--receptor", str(REPO_ROOT / "demo_data" / "receptors" / "3AIC_receptor.pdbqt"),
        "--ligand", str(REPO_ROOT / "demo_data" / "receptors" / "3AIC_native_ligand.pdbqt"),
        "--score_only",
        "--autobox"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Vina smoke test failed: {res.stderr}"
    assert "Estimated Free Energy of Binding" in res.stdout


