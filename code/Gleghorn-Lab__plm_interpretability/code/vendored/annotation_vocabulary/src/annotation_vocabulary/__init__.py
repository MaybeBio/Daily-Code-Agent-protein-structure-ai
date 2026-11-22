"""Versioned protein annotation vocabularies."""

from .grammar import ASPECT_ORDER, VocabularyIndex, build_vocabulary_index
from .schema import LocalAnnotation, ProteinRecord, TermAnnotation, TermKey


__all__ = [
    "ASPECT_ORDER",
    "LocalAnnotation",
    "ProteinRecord",
    "TermAnnotation",
    "TermKey",
    "VocabularyIndex",
    "build_vocabulary_index",
]
