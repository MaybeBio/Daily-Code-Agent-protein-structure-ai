from __future__ import annotations

import pytest
import torch

from torch import nn

from plm_interpretability.units import atlas, capture, causal


SEQUENCES = ["MKTAYIAKQRQISFVKSHFSRQ", "MSTNPKPQRKTKRNTNRRPQD", "MKVLAAGIVG"]


def _module_outputs(model: nn.Module, block: int, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> dict[str, torch.Tensor]:
    """The SwiGLU's and the down projection's outputs of one block, as the model ran them."""
    # input_ids, attention_mask: (b, l); returns product (b, l, f), write (b, l, d) and the hidden states, (b, l, d) each
    seen: dict[str, torch.Tensor] = {}
    ffn = causal.transformer_blocks(model)[block].ffn
    handles = [
        ffn[causal.SWIGLU_INDEX].register_forward_hook(lambda module, args, output: seen.__setitem__("product", output.clone())),
        ffn[capture.DOWN_PROJECTION_INDEX].register_forward_hook(lambda module, args, output: seen.__setitem__("write", output.clone())),
    ]
    with torch.inference_mode():
        seen["hidden"] = model(input_ids=input_ids, attention_mask=attention_mask, output_hidden_states=True).hidden_states
    for handle in handles:
        handle.remove()
    return seen  # product (b, l, f), write (b, l, d), hidden (b, l, d) each


def test_reader_hands_each_block_its_residue_states(tiny_esmc: nn.Module) -> None:
    input_ids, attention_mask, residues = atlas.encode_batch(tiny_esmc.tokenizer, SEQUENCES, torch.device("cpu"))
    seen: dict[int, capture.BlockStates] = {}
    with capture.BlockReader(tiny_esmc, [2, 0, 1], lambda states: seen.__setitem__(states.block, states),
                             write_blocks=[2], stream_blocks=[0, 1]) as reader:
        reader.run(input_ids, attention_mask, residues)
    assert sorted(seen) == [0, 1, 2]
    reference = _module_outputs(tiny_esmc, 2, input_ids, attention_mask)
    n_residues = sum(len(sequence) for sequence in SEQUENCES)
    assert seen[2].gate.shape == (n_residues, 256)
    # FastPLMs' hidden state i is the input to block i, so block b's output stream is hidden state b + 1.
    for block in (0, 1):
        torch.testing.assert_close(seen[block].stream, reference["hidden"][block + 1][residues])
    torch.testing.assert_close(seen[2].product(), reference["product"][residues])
    torch.testing.assert_close(seen[2].write, reference["write"][residues])
    assert seen[0].write is None and seen[2].stream is None


def test_reader_stops_after_the_deepest_block(tiny_esmc: nn.Module) -> None:
    input_ids, attention_mask, residues = atlas.encode_batch(tiny_esmc.tokenizer, SEQUENCES[:2], torch.device("cpu"))
    later: list[int] = []
    handle = causal.transformer_blocks(tiny_esmc)[1].register_forward_hook(lambda module, args, output: later.append(1))
    seen: list[int] = []
    with capture.BlockReader(tiny_esmc, [0], lambda states: seen.append(states.block)) as reader:
        reader.run(input_ids, attention_mask, residues)
    handle.remove()
    assert seen == [0] and later == []
    assert not causal.transformer_blocks(tiny_esmc)[0]._forward_hooks


def test_reader_refuses_streams_at_unread_blocks(tiny_esmc: nn.Module) -> None:
    with pytest.raises(ValueError):
        capture.BlockReader(tiny_esmc, [0], lambda states: None, stream_blocks=[1])
    with pytest.raises(ValueError):
        capture.BlockReader(tiny_esmc, [3], lambda states: None)


def test_residue_mask_marks_columns_one_to_length() -> None:
    attention_mask = torch.tensor([[1, 1, 1, 1, 1], [1, 1, 1, 0, 0]])  # (b, l)
    mask = capture.residue_mask(attention_mask, torch.tensor([3, 1]))  # (b, l)
    assert mask.tolist() == [[False, True, True, True, False], [False, True, False, False, False]]
    with pytest.raises(ValueError):
        capture.residue_mask(attention_mask, torch.tensor([2, 1]))
