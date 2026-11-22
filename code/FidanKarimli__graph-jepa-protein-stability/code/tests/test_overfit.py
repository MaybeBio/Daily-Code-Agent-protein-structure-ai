"""If the model cannot memorise a handful of mutations, something is wired wrong."""
import torch
import torch.nn as nn
from torch_geometric.loader import DataLoader

from pobj.data.dataset import load_all, protein_items
from pobj.eval.metrics import pooled_spearman
from pobj.models.encoder import Encoder
from pobj.models.heads import DDGHead, DDGModel
from pobj.utils import set_seed


def tiny_batch(n_proteins=2, n_mutations=16):
    labels, graphs = load_all()
    items = protein_items(labels, graphs, "test")[:n_proteins]
    for item in items:
        for key in ("mut_node", "mut_wt", "mut_aa", "ddg"):
            item[key] = item[key][:n_mutations]
    return next(iter(DataLoader(items, batch_size=n_proteins)))


def test_overfit_batch():
    set_seed(0)
    batch = tiny_batch()
    model = DDGModel(Encoder(dim=32, layers=2, dropout=0.0),
                     DDGHead(dim=32, hidden=64, aa_dim=8, dropout=0.0))
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-3)
    loss_fn = nn.MSELoss()

    model.train()
    for _ in range(400):
        optimizer.zero_grad()
        loss = loss_fn(model(batch), batch.ddg)
        loss.backward()
        optimizer.step()

    model.eval()
    with torch.no_grad():
        pred = model(batch)
    variance = batch.ddg.var().item()

    assert loss.item() < 0.05 * variance, "cannot fit a tiny batch"
    assert pooled_spearman(pred.numpy(), batch.ddg.numpy()) > 0.95


def test_frozen_encoder_receives_no_gradients():
    set_seed(0)
    batch = tiny_batch(n_mutations=8)
    model = DDGModel(Encoder(dim=32, layers=2, dropout=0.0),
                     DDGHead(dim=32, hidden=64, aa_dim=8, dropout=0.0),
                     freeze_encoder=True)
    model.train()
    nn.MSELoss()(model(batch), batch.ddg).backward()

    assert all(p.grad is None for p in model.encoder.parameters())
    assert any(p.grad is not None and p.grad.abs().sum() > 0 for p in model.head.parameters())
