"""The annotation transformer as a Transformers `PreTrainedModel`.

The forward mirrors a stock Transformers encoder, so a caller runs
`model(input_ids=..., attention_mask=...)` and reads `last_hidden_state`, shape `(b, l, d)`, or
`pooler_output`, shape `(b, d)`. Atlas's dual-encoder preembedding reads the per-token states and
pools them itself.
"""

from __future__ import annotations

import torch
import torch.nn as nn

from dataclasses import dataclass
from transformers import PreTrainedModel
from transformers import initialization as init
from transformers.utils import ModelOutput

from foundry.layers.attention import AttentionPooler
from foundry.layers.rotary import RotaryEmbedding
from foundry.layers.transformer import TransformerBlock
from .config import AnnotationTransformerConfig


@dataclass
class AnnotationTransformerOutput(ModelOutput):
    """Per-token states, the pooled state, and language-model logits when asked for."""

    last_hidden_state: torch.FloatTensor | None = None  # (b, l, d)
    pooler_output: torch.FloatTensor | None = None  # (b, d)
    logits: torch.FloatTensor | None = None  # (b, l, v)


class AnnotationTransformer(PreTrainedModel):
    """Encoder over annotation tokens, with an attention pooler and a language-model head.

    The state dict of `Synthyra/AT-Base`:
        token_embedding.weight
        layers.{i}.attention.layernorm_qkv.0.weight, .bias (a LayerNorm)
        layers.{i}.attention.layernorm_qkv.1.weight (the fused query, key, and value projection)
        layers.{i}.attention.out_proj.weight
        layers.{i}.attention.q_ln.weight, k_ln.weight
        layers.{i}.ffn.{0,1,4}.weight (a LayerNorm and two linears; 2 is the SwiGLU, 3 a dropout)
        final_layer_norm.weight, .bias
        pooler.{input,Wq,Wv,Wk,Wo}.weight, pooler.Q
        lm_head.weight, .bias
    The rotary table `layers.{i}.attention.rotary.inv_freq` is not persistent, so no checkpoint
    holds it.
    """

    config_class = AnnotationTransformerConfig
    base_model_prefix = "annotation_transformer"

    def __init__(self, config: AnnotationTransformerConfig) -> None:
        super().__init__(config)
        self.config = config

        self.token_embedding = nn.Embedding(
            num_embeddings=config.vocab_size,
            embedding_dim=config.hidden_size,
            padding_idx=config.pad_token_id,
        )
        if config.rotary:
            self.position_embedding = None
        else:
            self.position_embedding = nn.Embedding(
                num_embeddings=config.max_position_embeddings,
                embedding_dim=config.hidden_size,
            )

        self.dropout = nn.Dropout(config.dropout)
        self.layers = nn.ModuleList([TransformerBlock(config) for _ in range(config.num_hidden_layers)])
        self.final_layer_norm = nn.LayerNorm(config.hidden_size)
        self.pooler = AttentionPooler(
            hidden_size=config.hidden_size,
            intermediate_size=config.hidden_size,
            n_tokens=1,
        )
        self.lm_head = nn.Linear(config.hidden_size, config.vocab_size, bias=True)

        self.post_init()

    @torch.no_grad()
    def _init_weights(self, module: nn.Module) -> None:
        """Initialize one module's tensors, rebuilding the rotary table no checkpoint holds.

        `RotaryEmbedding.inv_freq` is registered with `persistent=False`. Transformers 5 loads a
        checkpoint into a model built on the meta device and hands every tensor the checkpoint
        lacks to this method as uninitialized memory, so the table is recomputed with the
        formula its constructor uses. Every other module keeps the Transformers default.
        """
        if isinstance(module, RotaryEmbedding):
            inv_freq = module._compute_inv_freq(module.inv_freq.device)  # (d_h / 2,)
            init.copy_(module.inv_freq, inv_freq)
            return

        super()._init_weights(module)

    def forward(
        self,
        input_ids: torch.LongTensor,
        attention_mask: torch.Tensor | None = None,
        return_lm_logits: bool = False,
        return_dict: bool = True,
        **_unused: object,
    ) -> AnnotationTransformerOutput | tuple[torch.Tensor, ...]:
        """Per-token states, a pooled sequence state, and language-model logits when asked for."""
        # input_ids: (b, l); attention_mask: (b, l), 1 for a real token, or None
        batch_size, seq_len = input_ids.shape  # b, l
        hidden_states = self.token_embedding(input_ids)  # (b, l, d)
        if self.position_embedding is not None:
            positions = torch.arange(seq_len, device=input_ids.device)  # (l,)
            positions = positions.unsqueeze(0).expand(batch_size, seq_len)  # (b, l)
            hidden_states = hidden_states + self.position_embedding(positions)  # (b, l, d)

        hidden_states = self.dropout(hidden_states)  # (b, l, d)

        for layer in self.layers:
            hidden_states = layer(hidden_states, attention_mask=attention_mask)  # (b, l, d)

        hidden_states = self.final_layer_norm(hidden_states)  # (b, l, d)
        pooled = self.pooler(hidden_states, attention_mask=attention_mask).squeeze(1)  # (b, 1, d) -> (b, d)

        logits = self.lm_head(hidden_states) if return_lm_logits else None  # (b, l, v) or None

        if not return_dict:
            if logits is None:
                return hidden_states, pooled  # (b, l, d), (b, d)

            return hidden_states, pooled, logits  # (b, l, d), (b, d), (b, l, v)

        return AnnotationTransformerOutput(
            last_hidden_state=hidden_states,
            pooler_output=pooled,
            logits=logits,
        )  # (b, l, d), (b, d), and (b, l, v) or None
