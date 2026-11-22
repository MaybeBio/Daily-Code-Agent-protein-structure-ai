from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import numpy as np
import torch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "boltz" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "boltz_dap" / "boltz_dap_v2"))

from boltz.data.feature.featurizerv2 import process_token_features  # noqa: E402
from boltz.data.types import TokenBondV2, TokenV2  # noqa: E402
from boltz.model.modules.encodersv2 import RelativePositionEncoder  # noqa: E402
from dap_features import (  # noqa: E402
    CompactPairFeatures,
    PairRowLayout,
    atom_to_token_indices,
    local_dense_pair_view,
    local_pair_mask,
    local_relative_position_encoding,
    representative_atom_indices,
)
from dap_diffusion_score import (  # noqa: E402
    _broadcast_token_features_to_atoms,
    _pool_atom_features_by_token,
)


class DapFeaturesContractTest(unittest.TestCase):
    def test_indexed_atom_token_ops_match_dense(self) -> None:
        torch.manual_seed(7)
        indices = torch.tensor([[0, 0, 1, 2, -1]])
        valid = indices >= 0
        dense = torch.zeros(1, 5, 3)
        dense[0, :4].scatter_(1, indices[0, :4, None], 1.0)
        atom_values = torch.randn(1, 5, 4)
        token_values = torch.randn(1, 3, 4)

        dense_mean = dense / (dense.sum(dim=1, keepdim=True) + 1e-6)
        expected_pool = torch.bmm(dense_mean.transpose(1, 2), atom_values)
        expected_broadcast = torch.bmm(dense, token_values)

        actual_pool = _pool_atom_features_by_token(
            atom_values,
            indices,
            valid,
            token_count=3,
        )
        actual_broadcast = _broadcast_token_features_to_atoms(
            token_values,
            indices,
            valid,
        )
        self.assertTrue(torch.allclose(actual_pool, expected_pool, atol=1e-6))
        self.assertTrue(torch.equal(actual_broadcast, expected_broadcast))

    def test_atom_mapping_indices_match_dense_fallback(self) -> None:
        atom_indices = torch.tensor([[0, 0, 1, -1]])
        atom_dense = torch.tensor(
            [[[1, 0], [1, 0], [0, 1], [0, 0]]],
            dtype=torch.long,
        )
        representative_indices = torch.tensor([[1, 2, -1]])
        representative_dense = torch.tensor(
            [[[0, 1, 0], [0, 0, 1], [0, 0, 0]]],
            dtype=torch.long,
        )

        indexed_atom = atom_to_token_indices(
            {"atom_to_token_idx": atom_indices}
        )
        dense_atom = atom_to_token_indices({"atom_to_token": atom_dense})
        indexed_representative = representative_atom_indices(
            {"token_to_rep_atom_idx": representative_indices}
        )
        dense_representative = representative_atom_indices(
            {"token_to_rep_atom": representative_dense}
        )

        self.assertTrue(torch.equal(indexed_atom[0], atom_indices))
        self.assertTrue(torch.equal(indexed_atom[0], dense_atom[0].masked_fill(~dense_atom[1], -1)))
        self.assertTrue(torch.equal(indexed_atom[1], dense_atom[1]))
        self.assertTrue(
            torch.equal(
                indexed_representative[0],
                dense_representative[0].masked_fill(~dense_representative[1], -1),
            )
        )
        self.assertTrue(torch.equal(indexed_representative[1], dense_representative[1]))

    def test_nondivisible_layout_and_dense_view(self) -> None:
        tensor = torch.arange(1 * 7 * 7 * 2).reshape(1, 7, 7, 2)
        rank_zero = PairRowLayout.create(original_size=7, world_size=2, rank=0)
        rank_one = PairRowLayout.create(original_size=7, world_size=2, rank=1)

        self.assertEqual((rank_zero.row_start, rank_zero.valid_rows), (0, 4))
        self.assertEqual((rank_one.row_start, rank_one.valid_rows), (4, 3))
        self.assertTrue(
            torch.equal(local_dense_pair_view(tensor, rank_zero), tensor[:, :4])
        )
        rank_one_view = local_dense_pair_view(tensor, rank_one)
        self.assertTrue(torch.equal(rank_one_view[:, :3], tensor[:, 4:]))
        self.assertEqual(torch.count_nonzero(rank_one_view[:, 3:]).item(), 0)

    def test_pair_mask_matches_full_slice_and_zero_padding(self) -> None:
        token_mask = torch.tensor([[1.0, 1.0, 0.0, 1.0, 1.0]])
        full = token_mask[:, :, None] * token_mask[:, None, :]
        layout = PairRowLayout.create(original_size=5, world_size=2, rank=1)
        local = local_pair_mask(token_mask, layout)

        self.assertTrue(torch.equal(local[:, :2], full[:, 3:5]))
        self.assertEqual(torch.count_nonzero(local[:, 2:]).item(), 0)

    def test_layout_rejects_invalid_rank(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside world size"):
            PairRowLayout.create(original_size=4, world_size=2, rank=2)

    def test_relative_position_matches_stock_nondivisible_slice(self) -> None:
        torch.manual_seed(7)
        encoder = RelativePositionEncoder(
            token_z=4,
            r_max=2,
            s_max=1,
            fix_sym_check=True,
            cyclic_pos_enc=True,
        )
        feats = {
            "asym_id": torch.tensor([[0, 0, 0, 1, 1]]),
            "residue_index": torch.tensor([[0, 1, 2, 0, 1]]),
            "entity_id": torch.tensor([[0, 0, 0, 1, 1]]),
            "token_index": torch.tensor([[0, 1, 2, 0, 1]]),
            "sym_id": torch.tensor([[0, 0, 0, 1, 1]]),
            "cyclic_period": torch.tensor([[3, 3, 3, 0, 0]]),
        }
        stock = encoder(feats)
        layout = PairRowLayout.create(original_size=5, world_size=2, rank=1)
        local = local_relative_position_encoding(encoder, feats, layout)

        self.assertTrue(torch.equal(local[:, :2], stock[:, 3:5]))
        self.assertEqual(torch.count_nonzero(local[:, 2:]).item(), 0)

    def test_compact_pair_features_match_stock_with_forced_contact(self) -> None:
        tokenized = _synthetic_tokenized()
        contact_constraints = [
            ((0, 0), (1, 0), 7.0, True),
            ((0, 0), (1, 0), 8.0, True),
        ]
        stock = process_token_features(
            tokenized,
            random=np.random.default_rng(42),
            inference_pocket_constraints=[],
            inference_contact_constraints=contact_constraints,
        )
        compact = CompactPairFeatures.from_tokenized(
            tokenized,
            pocket_constraints=[],
            contact_constraints=contact_constraints,
        )
        candidate = compact.materialize_tile(0, 4, device=torch.device("cpu"))

        stock_pair_mask = (
            stock["token_pad_mask"][:, None] * stock["token_pad_mask"][None, :]
        )
        self.assertTrue(torch.equal(candidate["pair_mask"][0], stock_pair_mask))
        for name in (
            "token_bonds",
            "type_bonds",
            "contact_conditioning",
            "contact_threshold",
        ):
            self.assertTrue(torch.equal(candidate[name][0], stock[name]))

    def test_pairless_token_features_match_stock_linear_features(self) -> None:
        tokenized = _synthetic_tokenized()
        stock = process_token_features(
            tokenized,
            random=np.random.default_rng(42),
            inference_pocket_constraints=[],
            inference_contact_constraints=[],
        )
        pairless = process_token_features(
            tokenized,
            random=np.random.default_rng(42),
            inference_pocket_constraints=[],
            inference_contact_constraints=[],
            compute_pair_features=False,
        )
        pair_names = {
            "token_bonds",
            "type_bonds",
            "contact_conditioning",
            "contact_threshold",
        }

        self.assertTrue(pair_names.isdisjoint(pairless))
        for name, feature in pairless.items():
            self.assertTrue(torch.equal(feature, stock[name]), name)

    def test_compact_pair_features_match_stock_pocket_constraints(self) -> None:
        tokenized = _synthetic_tokenized()
        pocket_constraints = [(0, [(1, 0)], 9.0, True)]
        stock = process_token_features(
            tokenized,
            random=np.random.default_rng(42),
            inference_pocket_constraints=pocket_constraints,
            inference_contact_constraints=[],
        )
        compact = CompactPairFeatures.from_tokenized(
            tokenized,
            pocket_constraints=pocket_constraints,
            contact_constraints=[],
        )
        candidate = compact.materialize_tile(0, 4, device=torch.device("cpu"))

        self.assertTrue(
            torch.equal(candidate["contact_conditioning"][0], stock["contact_conditioning"])
        )
        self.assertTrue(
            torch.equal(candidate["contact_threshold"][0], stock["contact_threshold"])
        )

    def test_compact_contact_default_matches_stock_without_constraints(self) -> None:
        tokenized = _synthetic_tokenized()
        stock = process_token_features(
            tokenized,
            random=np.random.default_rng(42),
            inference_pocket_constraints=[],
            inference_contact_constraints=[],
        )
        compact = CompactPairFeatures.from_tokenized(tokenized)
        candidate = compact.materialize_tile(1, 3, device=torch.device("cpu"))

        self.assertTrue(
            torch.equal(candidate["contact_conditioning"][0], stock["contact_conditioning"][1:3])
        )
        self.assertTrue(
            torch.equal(candidate["contact_threshold"][0], stock["contact_threshold"][1:3])
        )


def _synthetic_tokenized() -> SimpleNamespace:
    tokens = np.zeros(4, dtype=TokenV2)
    tokens["token_idx"] = np.arange(4)
    tokens["res_idx"] = [0, 1, 2, 0]
    tokens["asym_id"] = [0, 0, 0, 1]
    tokens["entity_id"] = [0, 0, 0, 1]
    tokens["sym_id"] = [0, 0, 0, 1]
    tokens["mol_type"] = 0
    tokens["resolved_mask"] = True
    tokens["disto_mask"] = True
    bonds = np.array([(0, 1, 2), (0, 1, 5), (2, 3, 5)], dtype=TokenBondV2)
    chains = np.array([(0, 3), (1, 1)], dtype=[("asym_id", "i4"), ("res_num", "i4")])
    structure = SimpleNamespace(chains=chains, bonds=[])
    return SimpleNamespace(
        tokens=tokens,
        bonds=bonds,
        structure=structure,
        record=None,
    )


if __name__ == "__main__":
    unittest.main()