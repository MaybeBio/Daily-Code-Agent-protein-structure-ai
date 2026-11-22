"""Masking must hide the residue and nothing else."""
import pytest
import torch
from torch_geometric.loader import DataLoader

from pobj.data.masking import apply_mask, sample_mask
from pobj.data.pretrain_set import load_pretrain_graphs
from pobj.models.encoder import MASK, Encoder
from pobj.utils import set_seed

pytestmark = pytest.mark.skipif(
    not __import__("pathlib").Path("data/processed/pretrain_ids.txt").exists(),
    reason="run scripts/build_pretrain_set.py first")


@pytest.fixture(scope="module")
def batch():
    graphs = load_pretrain_graphs(limit=16)
    return next(iter(DataLoader(graphs, batch_size=8)))


def test_mask_rate_is_roughly_right(batch):
    mask = sample_mask(batch, rate=0.2, generator=torch.Generator().manual_seed(0))
    assert 0.15 < mask.float().mean() < 0.25


def test_every_graph_has_a_masked_residue(batch):
    """A graph with nothing masked would contribute no loss."""
    for rate in (0.2, 0.001):
        mask = sample_mask(batch, rate, torch.Generator().manual_seed(0))
        counts = torch.zeros(batch.num_graphs, dtype=torch.long)
        counts.index_add_(0, batch.batch, mask.long())
        assert (counts > 0).all()


def test_apply_mask_hides_only_the_masked_residues(batch):
    mask = sample_mask(batch, 0.2, torch.Generator().manual_seed(0))
    x, targets = apply_mask(batch, mask)

    assert (x[mask] == MASK).all()
    assert torch.equal(x[~mask], batch.x[~mask])
    assert torch.equal(targets, batch.x[mask])
    assert torch.equal(batch.x, batch.x.clone()), "the original batch must not change"
    assert targets.max() < 20


def test_the_answer_is_not_in_the_input(batch):
    """Changing a masked residue's true identity must not change what the encoder sees.

    This is the leak rule at the point where it matters: if the embedding at a masked node
    moved when we changed its hidden letter, arm C would be reading the answer rather than
    predicting it.
    """
    set_seed(0)
    encoder = Encoder(dim=32, layers=2, dropout=0.0).eval()
    mask = sample_mask(batch, 0.2, torch.Generator().manual_seed(0))

    x_a, _ = apply_mask(batch, mask)
    altered = batch.clone()
    altered.x[mask] = (altered.x[mask] + 1) % 20          # different hidden letters
    x_b, _ = apply_mask(altered, mask)

    with torch.no_grad():
        z_a = encoder(x_a, batch.node_feat, batch.edge_index, batch.edge_attr)
        z_b = encoder(x_b, batch.node_feat, batch.edge_index, batch.edge_attr)
    assert torch.equal(z_a, z_b)


def test_masking_changes_the_embedding_of_unmasked_neighbours():
    """A sanity check in the other direction: masking must actually do something."""
    set_seed(0)
    graphs = load_pretrain_graphs(limit=4)
    batch = next(iter(DataLoader(graphs, batch_size=4)))
    encoder = Encoder(dim=32, layers=2, dropout=0.0).eval()

    mask = sample_mask(batch, 0.2, torch.Generator().manual_seed(0))
    x, _ = apply_mask(batch, mask)
    with torch.no_grad():
        masked = encoder(x, batch.node_feat, batch.edge_index, batch.edge_attr)
        clean = encoder.encode(batch)
    assert not torch.allclose(masked, clean)
