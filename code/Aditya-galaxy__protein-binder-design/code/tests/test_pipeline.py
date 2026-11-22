"""Unit and integration tests for De Novo Protein Binder Design."""

import os
import sys
import numpy as np

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.target import TargetHandler
from src.backbone import BackboneGenerator
from src.mpnn import ProteinMPNNDesigner
from src.geometry import interface_geometry, rank_key
from src.pipeline import DeNovoBinderPipeline


def test_target_handler():
    handler = TargetHandler("data/4ZQK.pdb", target_chain="A")
    assert len(handler.residues) > 50
    assert len(handler.ca_coords) == len(handler.res_ids)

    # Test hotspot identification
    hotspots = handler.find_hotspots_from_complex(partner_chain="B", cutoff=4.5)
    assert len(hotspots) > 5
    hotspot_nums = [h["res_num"] for h in hotspots]
    assert 56 in hotspot_nums or 123 in hotspot_nums  # Known PD-L1 interface residues


def test_backbone_generator():
    gen = BackboneGenerator(seed=42)
    scaffold = gen.generate_three_helix_bundle(helix_lens=(18, 16, 18), loop_len=3)
    assert scaffold.length == (18 + 16 + 18 + 6)
    assert scaffold.ca_coords.shape == (scaffold.length, 3)

    # Verify minimum inter-residue bond distances
    for i in range(scaffold.length - 1):
        d = np.linalg.norm(scaffold.ca_coords[i + 1] - scaffold.ca_coords[i])
        # Consecutive C-alphas should be roughly 3.8 Å apart
        assert 1.0 < d < 6.5


def test_mpnn_designer():
    designer = ProteinMPNNDesigner(seed=42)
    gen = BackboneGenerator(seed=42)
    scaffold = gen.generate_three_helix_bundle()

    target_coords = np.random.randn(20, 3) * 10.0
    target_names = ["TYR"] * 10 + ["ASP"] * 10

    seq, roles = designer.design_sequence(scaffold, target_coords, target_names, temperature=0.2)
    assert len(seq) == scaffold.length
    assert len(roles) == scaffold.length
    assert all(aa in "ACDEFGHIKLMNPQRSTVWY" for aa in seq)


def test_interface_geometry_is_measured_not_invented():
    """Every value must be a count or a distance derived from the coordinates given."""
    gen = BackboneGenerator(seed=42)
    scaffold = gen.generate_three_helix_bundle()
    target_ca = np.random.randn(30, 3) * 15.0
    hotspot_ca = target_ca[:5]

    g = interface_geometry(scaffold.ca_coords, target_ca, hotspot_ca)

    # No folding or binding prediction may reappear under any name.
    for banned in ("plddt", "iptm", "delta_sasa", "shape_complementarity", "composite_score",
                   "passed_filters", "confidence", "score"):
        assert banned not in g, f"{banned} is not computable here and must not be reported"

    # The distance is the real minimum over the pairwise matrix.
    expected = np.linalg.norm(
        scaffold.ca_coords[:, None, :] - target_ca[None, :, :], axis=2).min()
    assert np.isclose(g["min_ca_distance_angstrom"], expected)
    assert 0 <= g["interface_residues"] <= scaffold.length
    assert 0 <= g["hotspots_engaged"] <= g["hotspots_total"] == len(hotspot_ca)
    assert g["ca_clashes"] >= 0


def test_moving_chains_apart_empties_the_interface():
    gen = BackboneGenerator(seed=0)
    scaffold = gen.generate_three_helix_bundle()
    far = scaffold.ca_coords + 500.0
    g = interface_geometry(scaffold.ca_coords, far)
    assert g["interface_residues"] == 0 and g["ca_clashes"] == 0
    assert g["min_ca_distance_angstrom"] > 100.0


def test_exported_pdb_carries_no_invented_confidence():
    """The B-factor column previously held a fabricated pLDDT, where a viewer would read it as real."""
    src = open("src/pipeline.py").read()
    assert "plddt" not in src.lower()
    assert "1.00  0.00" in src


def test_end_to_end_small():
    pipeline = DeNovoBinderPipeline(target_pdb="data/4ZQK.pdb", target_chain="A", seed=42)
    lead = pipeline.run_campaign(
        hotspot_res_nums=[56, 66, 115, 122, 123, 124],
        num_backbones=2,
        seqs_per_backbone=1,
        output_dir="results/test_run",
    )
    assert lead is not None
    assert "sequence" in lead
    assert os.path.exists("results/test_run/top_lead_complex.pdb")
    assert os.path.exists("results/test_run/design_summary.json")


if __name__ == "__main__":
    print("Running test_target_handler...")
    test_target_handler()
    print("Running test_backbone_generator...")
    test_backbone_generator()
    print("Running test_mpnn_designer...")
    test_mpnn_designer()
    print("Running test_validator...")
    test_validator()
    print("Running test_end_to_end_small...")
    test_end_to_end_small()
    print("All tests passed successfully!")
