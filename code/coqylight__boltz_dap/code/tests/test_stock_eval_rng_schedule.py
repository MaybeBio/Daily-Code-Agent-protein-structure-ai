from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

import torch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "boltz" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "boltz_dap" / "boltz_dap_v2"))

from boltz.model.layers.dropout import get_dropout_mask as stock_dropout  # noqa: E402
from dap_pairformer_noseq import get_dropout_mask as dap_dropout  # noqa: E402


class StockEvalRngScheduleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous = os.environ.get("BOLTZ_STOCK_EVAL_RNG_SCHEDULE")
        os.environ["BOLTZ_STOCK_EVAL_RNG_SCHEDULE"] = "1"

    def tearDown(self) -> None:
        if self.previous is None:
            os.environ.pop("BOLTZ_STOCK_EVAL_RNG_SCHEDULE", None)
        else:
            os.environ["BOLTZ_STOCK_EVAL_RNG_SCHEDULE"] = self.previous

    def test_pair_shard_consumes_full_stock_draw(self) -> None:
        stock = torch.zeros(1, 7, 7, 2)
        shard = torch.zeros(1, 4, 7, 2)
        torch.manual_seed(11)
        stock_dropout(0.25, stock, training=False)
        stock_state = torch.get_rng_state()
        torch.manual_seed(11)
        mask = dap_dropout(
            0.25,
            shard,
            training=False,
            stock_pair_size=7,
        )
        self.assertEqual(mask, 1.0)
        self.assertTrue(torch.equal(torch.get_rng_state(), stock_state))

    def test_msa_draw_uses_unsharded_input_shape(self) -> None:
        msa = torch.zeros(1, 5, 7, 2)
        torch.manual_seed(13)
        stock_dropout(0.15, msa, training=False)
        stock_state = torch.get_rng_state()
        torch.manual_seed(13)
        dap_dropout(0.15, msa, training=False)
        self.assertTrue(torch.equal(torch.get_rng_state(), stock_state))

    def test_template_probe_preserves_local_tensor_mask(self) -> None:
        full = torch.zeros(1, 7, 7, 2)
        shard = torch.zeros(1, 4, 7, 2)
        torch.manual_seed(15)
        stock_dropout(0.25, full, training=False)
        stock_state = torch.get_rng_state()
        torch.manual_seed(15)
        mask = dap_dropout(
            0.25,
            shard,
            training=False,
            stock_pair_size=7,
            legacy_stock_behavior=True,
        )
        self.assertEqual(mask.shape, (1, 4, 1, 1))
        self.assertEqual(mask.dtype, torch.float32)
        self.assertTrue(torch.equal(mask, torch.ones_like(mask)))
        self.assertTrue(torch.equal(torch.get_rng_state(), stock_state))

    def test_legacy_template_behavior_is_preserved_when_disabled(self) -> None:
        os.environ["BOLTZ_STOCK_EVAL_RNG_SCHEDULE"] = "0"
        shard = torch.zeros(1, 4, 7, 2)
        torch.manual_seed(17)
        stock_mask = stock_dropout(0.25, shard, training=False)
        stock_state = torch.get_rng_state()
        torch.manual_seed(17)
        dap_mask = dap_dropout(
            0.25,
            shard,
            training=False,
            stock_pair_size=7,
            legacy_stock_behavior=True,
        )
        self.assertTrue(torch.equal(dap_mask, stock_mask))
        self.assertTrue(torch.equal(torch.get_rng_state(), stock_state))


if __name__ == "__main__":
    unittest.main()