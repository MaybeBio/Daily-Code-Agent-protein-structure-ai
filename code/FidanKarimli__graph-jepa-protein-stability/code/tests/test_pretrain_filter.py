"""The pretraining set must not contain anything similar to a MegaScale protein,
and its graphs must look exactly like the ones used for fine-tuning."""
from pathlib import Path

import pytest
import torch

from pobj.data.dataset import load_all
from pobj.data.features import EDGE_FEAT_DIM, NODE_FEAT_DIM
from pobj.data.pretrain_set import MAX_LEN, MIN_LEN, load_pretrain_graphs

PROCESSED = Path("data/processed")
IDS = PROCESSED / "pretrain_ids.txt"

pytestmark = pytest.mark.skipif(
    not IDS.exists(), reason="run scripts/build_pretrain_set.py first")


@pytest.fixture(scope="module")
def ids():
    return IDS.read_text().split()


@pytest.fixture(scope="module")
def graphs():
    return load_pretrain_graphs()


def test_no_removed_domain_survived(ids):
    removed = set((PROCESSED / "removed_similar.txt").read_text().split())
    assert not removed & set(ids)


def test_ids_are_unique(ids):
    assert len(ids) == len(set(ids))


def test_megascale_names_are_absent(ids):
    """A sanity check on the filter: MegaScale proteins are not SCOPe domains, so none of
    their names should appear, by identity or by sequence."""
    labels, _ = load_all()
    assert not set(labels.WT_name) & set(ids)

    sequences = {seq for seq, in zip(labels.drop_duplicates("WT_name").wt_seq)}
    from pobj.data.pretrain_set import domain_files, read_domains
    sample = dict(list(domain_files().items())[:200])
    kept, _ = read_domains(sample)
    assert not {seq for seq, _ in kept.values()} & sequences


def test_graphs_match_the_finetuning_format(graphs):
    assert len(graphs) > 0
    for g in graphs[:50]:
        assert MIN_LEN <= g.num_nodes <= MAX_LEN
        assert g.node_feat.shape == (g.num_nodes, NODE_FEAT_DIM)
        assert g.edge_attr.shape == (g.edge_index.shape[1], EDGE_FEAT_DIM)
        assert torch.isfinite(g.node_feat).all() and torch.isfinite(g.edge_attr).all()
        assert g.x.max() < 20          # only standard amino acids survive read_pdb
