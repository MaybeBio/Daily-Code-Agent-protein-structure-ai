"""A saved annotation transformer loads back unchanged, and registers with the Auto classes.

Transformers 5 builds a model on the meta device, copies in the tensors the checkpoint holds, and
leaves every other parameter and buffer to the model's `_init_weights` as uninitialized memory.
The rotary tables are registered with `persistent=False`, so no checkpoint holds them, and until
`_init_weights` rebuilt them a loaded model rotated positions by whatever the memory held.

These tests save a tiny, randomly initialized model and load it back with `from_pretrained`, the
path `Synthyra/AT-Base` takes, so they need neither the Hub nor a GPU. Allocations made while
loading hold NaN, so a table the load leaves unfilled cannot match by chance.
"""

from __future__ import annotations

import torch

from pathlib import Path
from typing import TypedDict
from transformers import AutoConfig, AutoModel

from annotation_transformer import (
    PRESETS,
    AnnotationTransformer,
    AnnotationTransformerConfig,
    register_with_auto_classes,
)
from foundry.checkpoint_loading import assert_unsaved_buffers_match, uninitialized_memory_as_nan


BATCH = 2  # b
LENGTH = 7  # l, tokens per padded row
VOCAB_SIZE = 40  # v, annotation tokens in the tiny vocabulary


class LoadingInfo(TypedDict):
    """What Transformers 5 reports from `from_pretrained(..., output_loading_info=True)`."""

    missing_keys: set[str]
    unexpected_keys: set[str]
    mismatched_keys: set[tuple[str, tuple[int, ...], tuple[int, ...]]]
    error_msgs: list[str]


def tiny_model() -> AnnotationTransformer:
    config = AnnotationTransformerConfig(
        vocab_size=VOCAB_SIZE,
        hidden_size=64,  # the attention pooler splits it into 64-wide heads
        num_hidden_layers=2,
        n_heads=4,
        expansion_ratio=2.0,
        dropout=0.0,
        pad_token_id=0,
        mask_token_id=VOCAB_SIZE - 1,
    )
    torch.manual_seed(0)
    return AnnotationTransformer(config).eval()


def save_and_load(model: AnnotationTransformer, tmp_path: Path) -> tuple[AnnotationTransformer, LoadingInfo]:
    """Load `model` back from disk with every allocation made while loading filled with NaN."""
    model.save_pretrained(str(tmp_path))
    with uninitialized_memory_as_nan():
        loaded, loading_info = AnnotationTransformer.from_pretrained(str(tmp_path), output_loading_info=True)
    return loaded.eval(), loading_info


def padding_mask() -> torch.Tensor:
    mask = torch.ones(BATCH, LENGTH, dtype=torch.long)  # (b, l)
    mask[1, 4:] = 0  # the second row holds four tokens, then padding
    return mask  # (b, l)


def test_every_saved_tensor_loads(tmp_path: Path) -> None:
    _, loading_info = save_and_load(tiny_model(), tmp_path)

    assert not loading_info["missing_keys"]
    assert not loading_info["unexpected_keys"]
    assert not loading_info["mismatched_keys"]


def test_unsaved_buffers_match_a_freshly_built_model(tmp_path: Path) -> None:
    saved = tiny_model()
    loaded, _ = save_and_load(saved, tmp_path)

    unsaved = assert_unsaved_buffers_match(loaded, saved.state_dict(), lambda: AnnotationTransformer(loaded.config))

    assert unsaved > 0, "the rotary tables are the buffers under test"


def test_loaded_model_computes_what_the_saved_one_did(tmp_path: Path) -> None:
    saved = tiny_model()
    loaded, _ = save_and_load(saved, tmp_path)
    generator = torch.Generator().manual_seed(0)
    input_ids = torch.randint(1, VOCAB_SIZE, (BATCH, LENGTH), generator=generator)  # (b, l)

    with torch.inference_mode():
        expected = saved(input_ids=input_ids, attention_mask=padding_mask())
        actual = loaded(input_ids=input_ids, attention_mask=padding_mask())

    assert torch.isfinite(actual.last_hidden_state).all()  # (b, l, d)
    torch.testing.assert_close(actual.last_hidden_state, expected.last_hidden_state, rtol=0, atol=0)
    torch.testing.assert_close(actual.pooler_output, expected.pooler_output, rtol=0, atol=0)  # (b, d)


def test_forward_shapes_and_the_tuple_form() -> None:
    model = tiny_model()
    input_ids = torch.randint(1, VOCAB_SIZE, (BATCH, LENGTH))  # (b, l)

    with torch.inference_mode():
        output = model(input_ids=input_ids, attention_mask=padding_mask(), return_lm_logits=True)
        hidden, pooled, logits = model(
            input_ids=input_ids,
            attention_mask=padding_mask(),
            return_lm_logits=True,
            return_dict=False,
        )  # (b, l, d), (b, d), (b, l, v)

    assert output.last_hidden_state.shape == (BATCH, LENGTH, 64)
    assert output.pooler_output.shape == (BATCH, 64)
    assert output.logits.shape == (BATCH, LENGTH, VOCAB_SIZE)
    torch.testing.assert_close(hidden, output.last_hidden_state, rtol=0, atol=0)
    torch.testing.assert_close(pooled, output.pooler_output, rtol=0, atol=0)
    torch.testing.assert_close(logits, output.logits, rtol=0, atol=0)


def test_auto_classes_load_it_by_model_type(tmp_path: Path) -> None:
    register_with_auto_classes()
    register_with_auto_classes()  # a second call is harmless
    tiny_model().save_pretrained(str(tmp_path))

    assert type(AutoConfig.from_pretrained(str(tmp_path))) is AnnotationTransformerConfig
    assert type(AutoModel.from_pretrained(str(tmp_path))) is AnnotationTransformer


def test_presets_name_the_published_shapes() -> None:
    at_base = AnnotationTransformerConfig.from_preset("at_base", vocab_size=VOCAB_SIZE)

    assert set(PRESETS) == {"at_base", "camp_at", "camp_at_large"}
    assert (at_base.hidden_size, at_base.num_hidden_layers, at_base.n_heads) == (512, 4, 8)
    assert at_base.vocab_size == VOCAB_SIZE, "an override wins over the preset"
