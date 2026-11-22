"""Checks on the pretraining loop itself."""
import math
from pathlib import Path

import pytest
import torch
import torch.nn as nn
from torch_geometric.loader import DataLoader

from pobj.data.pretrain_set import load_pretrain_graphs
from pobj.eval.rank import effective_rank
from pobj.models.encoder import Encoder
from pobj.models.heads import LetterHead
from pobj.train.pretrain import Running, letter_frequencies, step_losses
from pobj.utils import set_seed

pytestmark = pytest.mark.skipif(
    not Path("data/processed/pretrain_ids.txt").exists(),
    reason="run scripts/build_pretrain_set.py first")


@pytest.fixture(scope="module")
def batch():
    return next(iter(DataLoader(load_pretrain_graphs(limit=16), batch_size=8)))


def test_untrained_loss_is_near_chance(batch):
    """An untrained 20-way classifier must sit at about ln(20) = 3.0.

    Any other starting value means the loss is being averaged or scaled wrongly.
    """
    set_seed(0)
    encoder = Encoder(dim=32, layers=2, dropout=0.0)
    heads = nn.ModuleDict({"letter": LetterHead(32)})
    loss, stats, weight = step_losses(encoder, heads, batch, 0.2)

    assert math.log(20) - 0.6 < stats["loss"] < math.log(20) + 0.6
    assert 0 < weight <= batch.num_nodes
    assert 0.0 <= stats["letter_accuracy"] <= 1.0


def test_running_average_weights_by_residues():
    """Two batches of different size average by residue, not by batch."""
    running = Running()
    running.add({"loss": 1.0}, weight=10)
    running.add({"loss": 2.0}, weight=90)
    assert running.mean()["loss"] == pytest.approx(1.9)


def test_letter_frequencies_sum_to_one():
    graphs = load_pretrain_graphs(limit=200)
    freq = letter_frequencies(graphs)
    assert freq.shape == (20,)
    assert float(freq.sum()) == pytest.approx(1.0)
    assert 0.05 < float(freq.max()) < 0.20      # the most common residue, around 9%


def test_overfit_one_batch(batch):
    """The letter task must be learnable: memorising one batch drives the loss down."""
    set_seed(0)
    encoder = Encoder(dim=64, layers=2, dropout=0.0)
    heads = nn.ModuleDict({"letter": LetterHead(64)})
    optimizer = torch.optim.AdamW(list(encoder.parameters()) + list(heads.parameters()),
                                  lr=3e-3)

    generator = torch.Generator().manual_seed(0)          # the same mask every step
    first = None
    for _ in range(150):
        optimizer.zero_grad()
        loss, stats, _ = step_losses(encoder, heads, batch, 0.2,
                                     torch.Generator().manual_seed(0))
        loss.backward()
        optimizer.step()
        first = first if first is not None else stats["loss"]

    assert stats["loss"] < 0.5 * first
    assert stats["letter_accuracy"] > 0.5


def test_effective_rank_bounds():
    assert effective_rank(torch.eye(16)) == pytest.approx(16.0, abs=1e-3)
    collapsed = torch.ones(64, 16)                        # every row identical
    assert effective_rank(collapsed) == pytest.approx(1.0, abs=1e-3)
