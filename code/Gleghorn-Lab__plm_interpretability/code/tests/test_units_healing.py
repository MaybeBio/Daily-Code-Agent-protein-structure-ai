from __future__ import annotations

import numpy as np
import pytest
import torch

from pathlib import Path
from safetensors.torch import load_file
from torch import nn

from plm_interpretability.units import ablation, causal, healing, pruning
from plm_interpretability.units.sparsify import masked_distributions


SEQUENCES = ["MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ", "MSDNELTRAVQEAGYKPTWLAHHGKEIRVAMDQ", "MAHHHHHHVGTGSNDDDDKSPDPKLMNQRSTVW",
             "MGSSHHHHHHSSGLVPRGSHMASMTGGQQMGRGS", "MKKLLPTAAAGLLLLAAQPAMAMDIGINSDP"]


def test_the_learning_rate_rises_to_its_peak_then_falls_to_its_floor() -> None:
    rates = [healing.learning_rate(step, 50, 1.0, warmup=10, floor=0.1) for step in range(50)]
    assert rates[0] == pytest.approx(0.1) and rates[9] == pytest.approx(1.0) and rates[10] == pytest.approx(1.0)
    assert rates[-1] == pytest.approx(0.1)
    assert all(later <= earlier + 1e-12 for earlier, later in zip(rates[10:], rates[11:], strict=False))


def test_a_pass_holds_every_protein_once() -> None:
    lengths = np.array([30, 500, 31, 29, 480, 33, 510, 28], dtype=np.int64)
    batches = healing.pass_batches(lengths, np.random.default_rng(0), tokens=1100, chunk=4)
    assert sorted(np.concatenate(batches).tolist()) == list(range(8))
    assert all(len(batch) * (lengths[batch].max() + 2) <= 1100 or len(batch) == 1 for batch in batches)


def test_the_terms_vanish_for_a_student_that_is_its_teacher() -> None:
    generator = torch.Generator().manual_seed(0)
    logits = torch.randn(6, 9, generator=generator)
    streams = [torch.randn(2, 5, 4, generator=generator) for _ in range(3)]
    tokens = torch.tensor([[True] * 5, [True, True, True, False, False]])
    terms = healing.heal_terms(logits, logits, torch.arange(6), streams, streams, tokens)
    assert float(terms["kl"]) == pytest.approx(0.0, abs=1e-7) and float(terms["stream"]) == 0.0 and float(terms["ce"]) > 0
    moved = [stream.clone() for stream in streams]
    moved[1][1, 4] += 5.0  # a padded token, which the stream term leaves out
    assert float(healing.heal_terms(logits, logits, torch.arange(6), moved, streams, tokens)["stream"]) == 0.0
    moved[1][0, 0] += 1.0
    assert float(healing.heal_terms(logits, logits, torch.arange(6), moved, streams, tokens)["stream"]) > 0
    assert set(healing.heal_terms(logits, logits + 1.0, torch.arange(6), (), (), tokens)) == {"ce", "kl"}


def test_healing_brings_a_resized_model_toward_its_teacher(tiny_esmc: nn.Module, tmp_path: Path) -> None:
    device = torch.device("cpu")
    generator = torch.Generator().manual_seed(3)
    kept = [torch.randperm(256, generator=generator)[:96].sort().values for _ in causal.transformer_blocks(tiny_esmc)]
    student = pruning.resized(tiny_esmc, kept).float().requires_grad_(True)
    chosen = ablation.readout_positions(np.array([len(sequence) for sequence in SEQUENCES], dtype=np.int64))
    clean, _ = masked_distributions(tiny_esmc, SEQUENCES, chosen, device, token_budget=512)
    before = healing.masked_read(student, SEQUENCES, chosen, clean, device, token_budget=512)
    logged = []
    history = healing.heal(student, tiny_esmc, SEQUENCES, SEQUENCES, chosen, device, tmp_path, steps=40, peak=3e-3, tokens=128,
                           validate_every=20, log_every=10, record=lambda metrics, step: logged.append((step, sorted(metrics))),
                           log=lambda _: None)
    assert [row["step"] for row in history] == [20, 40] and history[0]["kept"]
    # The toy teacher is untrained, so the true residues, not the teacher, are what the student can learn here.
    assert min(row["loss"] for row in history) < before["loss"]
    state = load_file(str(tmp_path / "best.safetensors"))
    assert set(state) == set(student.state_dict())
    assert any("train/stream" in names for _, names in logged) and any("val/loss" in names for _, names in logged)
    assert not any(layer._forward_hooks for layer in causal.transformer_blocks(tiny_esmc))
    assert not any(layer._forward_hooks for layer in causal.transformer_blocks(student))

    control = pruning.resized(tiny_esmc, kept).float().requires_grad_(True)
    healing.heal(control, tiny_esmc, SEQUENCES, SEQUENCES, chosen, device, tmp_path, steps=4, tokens=128, validate_every=4,
                 log_every=2, match_streams=False, record=lambda metrics, step: logged.append((step, sorted(metrics))),
                 log=lambda _: None)
    assert "train/stream" not in logged[-2][1]
