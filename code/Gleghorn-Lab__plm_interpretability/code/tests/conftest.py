"""Fixtures shared by the units tests."""

from __future__ import annotations

import pytest
import torch

from collections.abc import Callable
from torch import nn

from fastplms.models.esm_plusplus.modeling_esm_plusplus import ESMplusplusConfig, ESMplusplusForMaskedLM
from fastplms.models.esm_plusplus.modeling_esm_plusplus_sae import ESMplusplusSAELayer, ESMplusplusSAEParams


@pytest.fixture(scope="session")
def tiny_esmc() -> nn.Module:
    """A randomly initialized ESM++ with three blocks of width 64 (256 SwiGLU units), float32 on the CPU."""
    torch.manual_seed(0)
    config = ESMplusplusConfig(hidden_size=64, num_attention_heads=4, num_hidden_layers=3, vocab_size=64)
    return ESMplusplusForMaskedLM(config).eval()


@pytest.fixture(scope="session")
def tiny_sae() -> Callable[..., nn.Module]:
    """A maker of seeded random TopK SAE layers on `tiny_esmc`'s width-64 stream, `codebook` latents with `k` active."""
    def make(codebook: int = 96, k: int = 8, seed: int = 5) -> nn.Module:
        generator = torch.Generator().manual_seed(seed)
        layer = ESMplusplusSAELayer(ESMplusplusSAEParams(d_model=64, codebook_dim=codebook, k=k, layer=2))
        with torch.no_grad():
            layer.W_enc.copy_(torch.randn(64, codebook, generator=generator) / 8)
            layer.W_dec.copy_(torch.randn(codebook, 64, generator=generator) / 8)
            layer.b_dec.copy_(torch.randn(64, generator=generator) / 10)
        return layer
    return make
