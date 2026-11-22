from __future__ import annotations

import pytest
import torch

from torch.nn import functional

from plm_interpretability.units import poles


def test_silu_minimum_matches_the_function() -> None:
    grid = torch.linspace(-3.0, 0.0, 300_001, dtype=torch.float64)  # (n,)
    assert float(functional.silu(grid).min()) == pytest.approx(poles.SILU_MINIMUM, abs=1e-9)


def test_poles_rebuild_the_product_and_stay_nonnegative() -> None:
    generator = torch.Generator().manual_seed(0)
    gate = torch.randn(512, 64, generator=generator)  # (r, f)
    up = torch.randn(512, 64, generator=generator)  # (r, f)
    split = poles.swiglu_poles(gate, up)
    torch.testing.assert_close(split.product(), functional.silu(gate) * up, rtol=0, atol=0)
    for name in ("positive", "negative", "leak_positive", "leak_negative"):
        assert bool((getattr(split, name) >= 0).all()), name


def test_each_residue_and_unit_lands_in_at_most_one_pole() -> None:
    generator = torch.Generator().manual_seed(1)
    gate = torch.randn(256, 32, generator=generator)  # (r, f)
    up = torch.randn(256, 32, generator=generator)  # (r, f)
    split = poles.swiglu_poles(gate, up)
    occupied = sum((getattr(split, name) > 0).int() for name in ("positive", "negative", "leak_positive", "leak_negative"))
    assert int(occupied.max()) <= 1


def test_quadrants_follow_the_gate_and_the_up_projection() -> None:
    gate = torch.tensor([[2.0, 2.0, -1.0, -1.0]])  # (1, 4)
    up = torch.tensor([[3.0, -3.0, -3.0, 3.0]])  # (1, 4)
    split = poles.swiglu_poles(gate, up)
    assert split.positive[0].tolist() == pytest.approx([float(functional.silu(torch.tensor(2.0))) * 3, 0, 0, 0])
    assert float(split.negative[0, 1]) > 0 and float(split.negative[0, 0]) == 0
    assert float(split.leak_positive[0, 2]) > 0 and float(split.leak_negative[0, 3]) > 0
    # A closed gate scales |u| by at most |SiLU's minimum|.
    assert float(split.leak_positive[0, 2]) <= abs(poles.SILU_MINIMUM) * 3 + 1e-6


def test_main_and_sign_layouts_put_negative_poles_after_positive_ones() -> None:
    gate = torch.tensor([[1.0, 1.0]])  # (1, 2)
    up = torch.tensor([[1.0, -1.0]])  # (1, 2)
    main = poles.swiglu_poles(gate, up).main()  # (1, 4)
    assert main.shape == (1, 4)
    assert float(main[0, 0]) > 0 and float(main[0, 3]) > 0 and float(main[0, 1]) == 0 and float(main[0, 2]) == 0
    signed = poles.sign_poles(torch.tensor([[2.0, -5.0]]))  # (1, 4)
    assert signed.tolist() == [[2.0, 0.0, 0.0, 5.0]]
    assert poles.pole_unit(3, 2) == (1, "negative")
    assert poles.pole_unit(0, 2) == (0, "positive")
    with pytest.raises(ValueError):
        poles.pole_unit(4, 2)


def test_bfloat16_inputs_are_read_in_float32() -> None:
    gate = torch.randn(64, 8).to(torch.bfloat16)  # (r, f)
    up = torch.randn(64, 8).to(torch.bfloat16)  # (r, f)
    assert poles.swiglu_poles(gate, up).positive.dtype == torch.float32


def test_mismatched_shapes_raise() -> None:
    with pytest.raises(ValueError):
        poles.swiglu_poles(torch.zeros(2, 3), torch.zeros(2, 4))
