from __future__ import annotations

import numpy as np
import pytest
import torch

from torch import nn

from plm_interpretability.units import causal, pruning
from plm_interpretability.units.capture import DOWN_PROJECTION_INDEX


SEQUENCES = ["MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ", "MSDNELTRAVQEAGYKPTWLAHHGKEIRVAMDQ", "MAHHHHHHVGTGSNDDDDKSPDPKLMNQRSTVW"]
UNITS = 256


def _logits(model: nn.Module) -> torch.Tensor:
    encoded = model.tokenizer(SEQUENCES, return_tensors="pt", padding=True)
    with torch.no_grad():
        return model(input_ids=encoded["input_ids"], attention_mask=encoded["attention_mask"]).logits  # (b, l, v)


def _problem(units: int = 7, width: int = 3, tokens: int = 40, seed: int = 0) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    generator = torch.Generator().manual_seed(seed)
    mixing = torch.randn(units, units, generator=generator, dtype=torch.float64)  # (f, f)
    product = torch.randn(tokens, units, generator=generator, dtype=torch.float64) @ mixing  # (t, f), correlated units
    write = torch.randn(width, units, generator=generator, dtype=torch.float64)  # (d, f)
    return product, product.T @ product, write  # (t, f), (f, f), (d, f)


def _least_squares_error(product: torch.Tensor, write: torch.Tensor, kept: list[int]) -> float:
    # product: (t, f); write: (d, f)
    target = product @ write.T  # (t, d)
    fitted = torch.linalg.lstsq(product[:, kept], target).solution  # (k, d)
    return float((product[:, kept] @ fitted - target).pow(2).sum())


def test_keeping_every_unit_changes_nothing(tiny_esmc: nn.Module) -> None:
    kept = [torch.arange(UNITS) for _ in causal.transformer_blocks(tiny_esmc)]
    torch.testing.assert_close(_logits(pruning.resized(tiny_esmc, kept)), _logits(tiny_esmc))
    assert pruning.parameter_count(pruning.resized(tiny_esmc, kept)) == pruning.parameter_count(tiny_esmc)


def test_a_resized_model_is_the_model_with_the_other_units_set_to_zero(tiny_esmc: nn.Module) -> None:
    generator = torch.Generator().manual_seed(2)
    blocks = causal.transformer_blocks(tiny_esmc)
    kept = [torch.randperm(UNITS, generator=generator)[:100].sort().values for _ in blocks]
    smaller = pruning.resized(tiny_esmc, kept)
    assert all(block.ffn[DOWN_PROJECTION_INDEX].in_features == 100 for block in causal.transformer_blocks(smaller))
    assert blocks[0].ffn[DOWN_PROJECTION_INDEX].in_features == UNITS
    width = blocks[0].ffn[DOWN_PROJECTION_INDEX].out_features
    assert pruning.parameter_count(tiny_esmc) - pruning.parameter_count(smaller) == 3 * width * (UNITS - 100) * len(blocks)

    def silence(block: int):
        mask = torch.zeros(UNITS)
        mask[kept[block]] = 1.0
        return lambda module, args, output: output * mask

    handles = [layer.ffn[causal.SWIGLU_INDEX].register_forward_hook(silence(block)) for block, layer in enumerate(blocks)]
    try:
        silenced = _logits(tiny_esmc)
    finally:
        for handle in handles:
            handle.remove()
    torch.testing.assert_close(_logits(smaller), silenced, atol=1e-5, rtol=1e-4)


def test_given_writes_replace_the_kept_units_write_vectors(tiny_esmc: nn.Module) -> None:
    blocks = causal.transformer_blocks(tiny_esmc)
    kept = [torch.arange(0, UNITS, 2) for _ in blocks]
    writes = [torch.zeros(64, UNITS // 2) for _ in blocks]
    smaller = pruning.resized(tiny_esmc, kept, writes)
    assert not any(block.ffn[DOWN_PROJECTION_INDEX].weight.any() for block in causal.transformer_blocks(smaller))


def test_the_matched_width_is_the_largest_within_the_budget(tiny_esmc: nn.Module) -> None:
    kept = [torch.arange(90) for _ in causal.transformer_blocks(tiny_esmc)]
    budget = pruning.parameter_count(pruning.resized(tiny_esmc, kept))
    assert pruning.matched_width(tiny_esmc, budget) == 90
    assert pruning.matched_width(tiny_esmc, budget - 1) == 89
    assert pruning.matched_width(tiny_esmc, pruning.parameter_count(tiny_esmc) + 5) == UNITS


def test_the_refit_is_the_least_squares_fit_of_the_whole_write() -> None:
    product, gram, write = _problem()
    kept = torch.tensor([0, 2, 5])
    refitted = pruning.refit_writes(gram, write, kept, ridge=0.0)
    error = pruning.write_error(gram, write, kept, refitted)
    assert error == pytest.approx(_least_squares_error(product, write, kept.tolist()), rel=1e-8)
    assert error < pruning.write_error(gram, write, kept, write[:, kept])
    assert pruning.write_error(gram, write, torch.arange(7), write) == pytest.approx(0.0, abs=1e-9)


def test_optimal_brain_surgeon_removes_the_unit_of_least_rise_each_time() -> None:
    product, gram, write = _problem()
    order = pruning.obs_order(gram, write.T, stop=3, ridge=0.0).tolist()
    assert len(order) == 4 and len(set(order)) == 4
    alive = list(range(7))
    for removed in order:
        rises = {unit: _least_squares_error(product, write, [other for other in alive if other != unit]) for unit in alive}
        assert rises[removed] == pytest.approx(min(rises.values()), rel=1e-8)
        alive.remove(removed)


def test_kept_units_follow_the_order() -> None:
    order = torch.tensor([4, 1, 6, 0])
    assert pruning.kept_units(order, 7, 5).tolist() == [0, 2, 3, 5, 6]
    assert pruning.kept_units(order, 7, 7).tolist() == list(range(7))
    with pytest.raises(ValueError):
        pruning.kept_units(order, 7, 2)


def test_moments_count_every_token(tiny_esmc: nn.Module) -> None:
    moments = pruning.collect_moments(tiny_esmc, SEQUENCES, torch.device("cpu"), token_budget=256, top=16)
    blocks = causal.transformer_blocks(tiny_esmc)
    assert moments.tokens == sum(len(sequence) + 2 for sequence in SEQUENCES)
    assert moments.gram.shape == (len(blocks), UNITS, UNITS)
    torch.testing.assert_close(moments.gram, moments.gram.transpose(1, 2))
    assert bool((moments.gram.diagonal(dim1=1, dim2=2) >= 0).all())
    assert moments.top.sum(dim=1).tolist() == [16.0 * moments.tokens] * len(blocks)
    assert bool((moments.open <= moments.tokens).all()) and bool((moments.open.sum(dim=1) > 0).all())
    assert not blocks[0].ffn[causal.SWIGLU_INDEX]._forward_hooks


def test_a_set_built_block_by_block_holds_the_intact_stream_on_its_calibration_tokens(tiny_esmc: nn.Module) -> None:
    # 105 calibration tokens and 200 kept units: every block's least-squares fit can meet its target exactly, so the
    # resized model's logits on those tokens are the intact model's, which a set cut at once without a refit misses.
    device = torch.device("cpu")
    variant, seconds = pruning.sequential_set(tiny_esmc, SEQUENCES, device, width=200, token_budget=256, ridge=1e-8,
                                              log=lambda _: None)
    blocks = causal.transformer_blocks(tiny_esmc)
    assert variant.kept.shape == (len(blocks), 200) and variant.writes.shape == (len(blocks), 64, 200) and len(seconds) == len(blocks)
    assert not any(block._forward_hooks for block in blocks) and blocks[0].ffn[DOWN_PROJECTION_INDEX].in_features == UNITS
    chosen = pruning.readout_positions(np.array([len(sequence) for sequence in SEQUENCES]))
    clean, truth = pruning.masked_distributions(tiny_esmc, SEQUENCES, chosen, device, token_budget=256)
    built, _ = pruning.read_model(pruning.resized(tiny_esmc, list(variant.kept), list(variant.writes)), SEQUENCES, chosen, clean,
                                  truth, device, token_budget=256)
    at_once, _ = pruning.read_model(pruning.resized(tiny_esmc, list(variant.kept)), SEQUENCES, chosen, clean, truth, device,
                                    token_budget=256)
    assert built["kl"] < 1e-5 and built["kl"] < at_once["kl"]
    pilot, pilot_seconds = pruning.sequential_set(tiny_esmc, SEQUENCES, device, width=200, token_budget=256, limit=2,
                                                  log=lambda _: None)
    assert pilot.kept.shape == (2, 200) and len(pilot_seconds) == 2


def test_a_static_run_reads_every_fixed_set(tiny_esmc: nn.Module) -> None:
    run = pruning.run_static(tiny_esmc, tiny_esmc, SEQUENCES, {"validation": SEQUENCES[:2], "test": SEQUENCES},
                             torch.device("cpu"), widths=(64, 128), token_budget=256, log=lambda _: None)
    assert run.matched_width == UNITS
    sets = (len(pruning.ORDERS) * len(pruning.REPAIRS) - 1) * 3
    assert len(run.table) == 2 * (2 + sets)
    intact = run.table[run.table["model"] == "esmc_600"]
    assert bool((intact["kl"] == 0.0).all()) and set(intact["split"]) == {"validation", "test"}
    whole = run.table[(run.table["width"] == UNITS) & (run.table["order"] != "none")]
    assert bool((whole.loc[whole["repair"] == "none", "kl"].abs() < 1e-6).all()) and bool((whole["kl"].abs() < 1e-2).all())
    cut = run.table[run.table["width"] == 64]
    assert bool((cut["kl"] > 0).all()) and bool((cut["parameters"] < intact["parameters"].iloc[0]).all())
    assert [(variant.order, variant.repair) for variant in run.variants] == [
        ("top_share", "none"), ("top_share", "refit"), ("energy", "none"), ("energy", "refit"), ("obs", "refit")]
    assert all(variant.kept.shape == (3, UNITS) for variant in run.variants)
    assert len(run.units) == 3 * UNITS and set(run.units.columns) >= {"top_share", "open_rate", "energy", "step_obs"}
    test = run.residues["test"]
    assert {"protein", "truth", "esmc_600", "esmc_300", "obs_refit_256"} <= set(test.columns)
    assert test["protein"].nunique() == len(SEQUENCES)

    pilot = pruning.run_static(tiny_esmc, tiny_esmc, SEQUENCES, {"test": SEQUENCES}, torch.device("cpu"), widths=(64,),
                               token_budget=256, limit=2, log=lambda _: None)
    assert len(pilot.table) == 2 + 2 and len(pilot.variants) == 2
