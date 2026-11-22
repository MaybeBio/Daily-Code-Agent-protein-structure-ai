"""The Transformers config of the annotation transformer, with its three checkpoint presets.

`Synthyra/AT-Base` stores `model_type="annotation_transformer"` in its `config.json`, so this
class deserializes it without remote code once `register_with_auto_classes` has run.
"""

from __future__ import annotations

from typing import Any, TypedDict
from transformers import PretrainedConfig


class ArchitecturePreset(TypedDict):
    """The architecture fields one checkpoint preset fixes."""

    hidden_size: int
    num_hidden_layers: int
    n_heads: int
    expansion_ratio: float
    dropout: float


PRESETS: dict[str, ArchitecturePreset] = {
    "at_base": {
        "hidden_size": 512,
        "num_hidden_layers": 4,
        "n_heads": 8,
        "expansion_ratio": 8 / 3,
        "dropout": 0.1,
    },
    "camp_at": {
        "hidden_size": 512,
        "num_hidden_layers": 6,
        "n_heads": 8,
        "expansion_ratio": 4.0,
        "dropout": 0.1,
    },
    "camp_at_large": {
        "hidden_size": 768,
        "num_hidden_layers": 12,
        "n_heads": 12,
        "expansion_ratio": 4.0,
        "dropout": 0.1,
    },
}


class AnnotationTransformerConfig(PretrainedConfig):
    """A BERT-like encoder over the tokens of the Annotation Vocabulary."""

    model_type = "annotation_transformer"

    def __init__(
        self,
        vocab_size: int = 88282,
        hidden_size: int = 512,
        num_hidden_layers: int = 6,
        n_heads: int = 8,
        expansion_ratio: float = 4.0,
        dropout: float = 0.1,
        max_position_embeddings: int = 1024,
        pad_token_id: int = 0,
        rotary: bool = True,
        mask_token_id: int = 88281,
        mlm_mask_probability: float = 0.15,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.vocab_size = vocab_size  # v
        self.hidden_size = hidden_size  # d
        self.num_hidden_layers = num_hidden_layers
        self.n_heads = n_heads  # h
        self.expansion_ratio = expansion_ratio
        self.dropout = dropout
        self.max_position_embeddings = max_position_embeddings
        self.pad_token_id = pad_token_id
        self.rotary = rotary
        self.mask_token_id = mask_token_id
        self.mlm_mask_probability = mlm_mask_probability

    @classmethod
    def from_preset(cls, name: str, **overrides: Any) -> AnnotationTransformerConfig:
        """One named checkpoint preset, with explicit overrides."""
        return cls(**{**PRESETS[name], **overrides})
