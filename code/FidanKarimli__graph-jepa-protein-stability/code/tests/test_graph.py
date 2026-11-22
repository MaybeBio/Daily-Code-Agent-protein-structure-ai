"""Graph construction checks, including the rule that no feature may leak
the residue identity."""
import numpy as np
import pytest
import torch

from pobj.data.features import EDGE_FEAT_DIM, NODE_FEAT_DIM, dihedral
from pobj.data.graph import K_NEIGHBOURS, build_graph
from pobj.data.megascale import load_labels, load_structures


@pytest.fixture(scope="module")
def protein():
    """One real protein, the first test-split name in alphabetical order."""
    labels = load_labels(splits=("test",))
    name = sorted(labels.WT_name.unique())[0]
    seq, coords = load_structures([name])[name]
    return name, seq, coords


@pytest.fixture(scope="module")
def graph(protein):
    name, seq, coords = protein
    return build_graph(seq, coords, name=name)


def test_shapes(graph, protein):
    _, seq, _ = protein
    n = len(seq)
    assert graph.num_nodes == n
    assert graph.x.shape == (n,)
    assert graph.node_feat.shape == (n, NODE_FEAT_DIM)
    assert graph.pos.shape == (n, 3)
    assert graph.edge_index.shape[0] == 2
    assert graph.edge_attr.shape == (graph.edge_index.shape[1], EDGE_FEAT_DIM)


def test_edges_are_undirected_and_self_free(graph):
    src, dst = graph.edge_index
    assert (src != dst).all(), "a residue is connected to itself"
    forward = {(int(a), int(b)) for a, b in zip(src, dst)}
    assert all((b, a) in forward for a, b in forward), "edge present in only one direction"


def test_every_node_has_neighbours(graph):
    counts = torch.bincount(graph.edge_index[1], minlength=graph.num_nodes)
    assert counts.min() >= min(K_NEIGHBOURS, graph.num_nodes - 1)


def test_features_are_finite(graph):
    assert torch.isfinite(graph.node_feat).all()
    assert torch.isfinite(graph.edge_attr).all()


def test_angles_are_unit_or_zero(graph):
    """Each (sin, cos) pair is on the unit circle, or exactly (0, 0) at a chain end."""
    pairs = graph.node_feat.view(graph.num_nodes, -1, 2)
    norms = pairs.norm(dim=-1)
    assert ((norms - 1).abs() < 1e-4) .logical_or(norms < 1e-6).all()


def test_no_letter_leak(protein):
    """Relabelling a residue must not change any geometric feature.

    If it did, arm C could read a hidden letter off the geometry instead of predicting it.
    """
    name, seq, coords = protein
    i = len(seq) // 2
    other = "W" if seq[i] != "W" else "G"
    changed = seq[:i] + other + seq[i + 1:]

    a = build_graph(seq, coords, name=name)
    b = build_graph(changed, coords, name=name)

    assert torch.equal(a.node_feat, b.node_feat)
    assert torch.equal(a.edge_index, b.edge_index)
    assert torch.equal(a.edge_attr, b.edge_attr)
    assert not torch.equal(a.x, b.x), "the residue index itself should differ"


def test_rotation_and_translation_invariance(protein):
    """A rotated, shifted protein is the same protein, so features must not move."""
    name, seq, coords = protein
    rng = np.random.default_rng(0)
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))         # a random rotation
    if np.linalg.det(q) < 0:
        q[:, 0] *= -1                                    # no mirroring: chirality matters
    moved = coords @ q.T.astype(np.float32) + np.float32([10.0, -5.0, 3.0])

    a = build_graph(seq, coords, name=name)
    b = build_graph(seq, moved, name=name)

    assert torch.allclose(a.node_feat, b.node_feat, atol=1e-3)
    assert torch.equal(a.edge_index, b.edge_index)
    assert torch.allclose(a.edge_attr, b.edge_attr, atol=1e-3)


def test_dihedral_matches_known_angles():
    """Three hand-computed cases. p0 and p3 sit either side of the p1->p2 bond.

    Both on the same side (cis) -> 0; opposite sides (trans) -> 180; one lifted out of
    the plane -> 90.
    """
    def angle(p0, p1, p2, p3):
        pts = torch.tensor([p0, p1, p2, p3]).unsqueeze(1)      # 4 x [1, 3]
        return float(dihedral(*pts).abs())

    p0, p1, p2 = [1.0, 1, 0], [0.0, 0, 0], [1.0, 0, 0]
    assert angle(p0, p1, p2, [1.0, 1, 0]) == pytest.approx(0.0, abs=1e-4)
    assert angle(p0, p1, p2, [1.0, -1, 0]) == pytest.approx(np.pi, abs=1e-4)
    assert angle(p0, p1, p2, [1.0, 0, 1]) == pytest.approx(np.pi / 2, abs=1e-4)
