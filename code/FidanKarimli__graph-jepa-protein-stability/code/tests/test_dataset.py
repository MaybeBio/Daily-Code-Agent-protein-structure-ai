"""Checks on the protein-level dataset, above all that batching keeps mutations
pointing at the right residues."""
import pytest
import torch
from torch_geometric.loader import DataLoader

from pobj.data.dataset import batch_protein_names, load_all, protein_items
from pobj.data.megascale import AA_IDX


@pytest.fixture(scope="module")
def data():
    return load_all()


@pytest.fixture(scope="module")
def items(data):
    labels, graphs = data
    return protein_items(labels, graphs, "test")


def test_one_item_per_protein(data, items):
    labels, _ = data
    assert len(items) == labels[labels.split == "test"].WT_name.nunique()
    assert sum(item.ddg.numel() for item in items) == (labels.split == "test").sum()


def test_mutations_point_at_the_right_residue(items):
    """The residue type at a mutation's node must be its wild-type letter."""
    for item in items:
        assert torch.equal(item.x[item.mut_node], item.mut_wt)


def test_batching_shifts_node_indices(items):
    """Same check after batching, which is where an off-by-one would appear."""
    for batch in DataLoader(items, batch_size=8):
        assert torch.equal(batch.x[batch.mut_node], batch.mut_wt)
        assert batch.mut_node.max() < batch.num_nodes


def test_batch_protein_names(items):
    for batch in DataLoader(items, batch_size=8):
        names = batch_protein_names(batch)
        assert len(names) == batch.ddg.numel()
        assert set(names) == set(batch.name)


def test_mutant_letter_differs(items):
    for item in items:
        assert (item.mut_wt != item.mut_aa).all()
        assert item.mut_aa.max() < len(AA_IDX)
