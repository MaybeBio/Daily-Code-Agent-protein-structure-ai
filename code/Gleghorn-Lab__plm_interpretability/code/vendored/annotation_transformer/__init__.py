"""The annotation transformer (AT): an encoder over Annotation Vocabulary tokens.

It is the B-side encoder of Atlas's CAMP model, published as `Synthyra/AT-Base`. That repository
names `model_type="annotation_transformer"` and no `auto_map`, so `AutoModel.from_pretrained`
finds the classes once `register_with_auto_classes` has run:

    from annotation_transformer import register_with_auto_classes
    register_with_auto_classes()
    at = AutoModel.from_pretrained("Synthyra/AT-Base")
"""

from __future__ import annotations

from transformers import AutoConfig, AutoModel

from .config import PRESETS, AnnotationTransformerConfig
from .modeling import AnnotationTransformer, AnnotationTransformerOutput


_REGISTERED = False


def register_with_auto_classes() -> None:
    """Register the config and model with `AutoConfig` and `AutoModel`, once per process."""
    global _REGISTERED
    if _REGISTERED:
        return

    AutoConfig.register("annotation_transformer", AnnotationTransformerConfig)
    AutoModel.register(AnnotationTransformerConfig, AnnotationTransformer)
    _REGISTERED = True


__all__ = [
    "PRESETS",
    "AnnotationTransformer",
    "AnnotationTransformerConfig",
    "AnnotationTransformerOutput",
    "register_with_auto_classes",
]
