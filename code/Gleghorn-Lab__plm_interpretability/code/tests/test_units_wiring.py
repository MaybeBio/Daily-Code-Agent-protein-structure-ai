from __future__ import annotations

import copy
import pytest
import torch

from torch import nn

from plm_interpretability.units import wiring
from plm_interpretability.units.causal import transformer_blocks
from plm_interpretability.units.rotations import haar_rotation


def test_strongest_links_ignore_scale_sign_and_a_constant_offset() -> None:
    generator = torch.Generator().manual_seed(0)
    writes = torch.randn(6, 16, generator=generator)  # (f_w, d)
    reads = torch.stack((3.0 * writes[2] + 5.0, -0.5 * writes[4], torch.randn(16, generator=generator)))  # (f, d)
    links = wiring.strongest_links(reads, writes, chunk=2)  # (f,)
    assert float(links[0]) == pytest.approx(1.0, abs=1e-5) and float(links[1]) == pytest.approx(1.0, abs=1e-5)
    centered = torch.nn.functional.normalize(writes - writes.mean(dim=1, keepdim=True), dim=1)  # (f_w, d)
    last = torch.nn.functional.normalize(reads[2] - reads[2].mean(), dim=0)  # (d,)
    assert float(links[2]) == pytest.approx(float((centered @ last).abs().max()), abs=1e-6)


def test_directions_follow_the_block_s_weights(tiny_esmc: nn.Module) -> None:
    block = transformer_blocks(tiny_esmc)[1]
    reads = wiring.read_directions(block)
    weight = block.ffn[wiring.PROJECTION_INDEX].weight  # (2f, d)
    gain = block.ffn[wiring.NORM_INDEX].weight  # (d,)
    torch.testing.assert_close(reads["gate"], weight[:256] * gain)
    torch.testing.assert_close(reads["up"], weight[256:] * gain)
    writes = wiring.write_directions(block)  # (f, d)
    assert writes.shape == (256, 64)
    rotation = haar_rotation(256, 3)  # (f, f)
    rotated = wiring.write_directions(block, rotation)  # (f, d)
    # a rotated unit k writes what the units write when they hold the rotation's column k
    units = torch.randn(5, 256)  # (r, f)
    torch.testing.assert_close((units @ rotation) @ rotated, units @ writes, rtol=1e-4, atol=1e-4)


def test_table_finds_a_planted_link_that_rotations_lose(tiny_esmc: nn.Module) -> None:
    model = copy.deepcopy(tiny_esmc)
    blocks = transformer_blocks(model)
    with torch.no_grad():
        # every gate row of block 2 reads along one writing unit of block 1, through the layer norm's gain
        down = blocks[1].ffn[3].weight  # (d, f)
        gain = blocks[2].ffn[wiring.NORM_INDEX].weight  # (d,)
        blocks[2].ffn[wiring.PROJECTION_INDEX].weight[:256] = ((down - down.mean(dim=0, keepdim=True)) / gain[:, None]).T
    table = wiring.wiring_table(model)
    assert len(table) == 2 * 2 * (1 + len(wiring.ROTATION_SEEDS)) and set(table["side"]) == set(wiring.SIDES)
    planted = table[(table["writer_block"] == 1) & (table["side"] == "gate")].set_index("arm")
    assert planted.loc["native", "strong_share"] == 1.0 and planted.loc["native", "median"] == pytest.approx(1.0, abs=1e-4)
    assert (planted.drop(index="native")["median"] < 0.7).all()
    summary = wiring.wiring_summary(table)
    assert summary["gate"]["pairs"] == 2 and summary["gate"]["native_strong_share"] >= 0.5
    # at width 64 every chance link passes the fixed mark, so the planted pair shows in the mark set by the rotations
    assert planted.loc["native", "above_rotations_share"] == 1.0 and summary["gate"]["native_above_rotations_share"] >= 0.5
    assert summary["gate"]["native_above_rotations_share_range"][1] == 1.0
    assert 0 <= summary["gate"]["pairs_native_above_every_rotation"] <= 2
    assert 0 <= summary["up"]["rotation_strong_share_max"] <= 1
