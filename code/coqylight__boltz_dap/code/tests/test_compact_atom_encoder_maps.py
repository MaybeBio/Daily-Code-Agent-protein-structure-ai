#!/usr/bin/env python3
"""Dense-versus-indexed contracts for Boltz atom encoder mappings."""

from __future__ import annotations

import unittest
from functools import partial

import torch

from boltz.model.modules.encodersv2 import (
    _broadcast_token_features_to_atoms,
    _pool_atom_features_by_token,
    _token_pair_features_to_atom_windows,
    get_indexing_matrix,
    single_to_keys,
)


class CompactAtomEncoderMapsTest(unittest.TestCase):
    def setUp(self) -> None:
        atom_indices = torch.tensor([[0, 0, 1, 1, 2, 2, -1, -1]])
        dense = torch.zeros(1, 8, 3)
        valid = atom_indices >= 0
        dense[0, valid[0], atom_indices[valid]] = 1
        self.dense_feats = {"atom_to_token": dense}
        self.compact_feats = {"atom_to_token_idx": atom_indices}

    def test_broadcast_and_pool_match_dense_maps(self) -> None:
        token_features = torch.randn(2, 3, 5)
        atom_features = torch.randn(2, 8, 5)

        dense_broadcast = _broadcast_token_features_to_atoms(
            token_features, self.dense_feats, multiplicity=2
        )
        compact_broadcast = _broadcast_token_features_to_atoms(
            token_features, self.compact_feats, multiplicity=2
        )
        dense_pool = _pool_atom_features_by_token(
            atom_features, self.dense_feats, token_count=3, multiplicity=2
        )
        compact_pool = _pool_atom_features_by_token(
            atom_features, self.compact_feats, token_count=3, multiplicity=2
        )

        torch.testing.assert_close(compact_broadcast, dense_broadcast)
        torch.testing.assert_close(compact_pool, dense_pool)

    def test_pair_window_lookup_matches_dense_maps(self) -> None:
        token_pairs = torch.randn(1, 3, 3, 7)
        indexing_matrix = get_indexing_matrix(2, 4, 8, token_pairs.device)
        to_keys = partial(
            single_to_keys,
            indexing_matrix=indexing_matrix,
            W=4,
            H=8,
        )

        dense = _token_pair_features_to_atom_windows(
            token_pairs, self.dense_feats, to_keys, W=4
        )
        compact = _token_pair_features_to_atom_windows(
            token_pairs, self.compact_feats, to_keys, W=4
        )

        torch.testing.assert_close(compact, dense)


if __name__ == "__main__":
    unittest.main()