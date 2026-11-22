"""An unordered protein pair as one key, so a pair stored in either order is found once."""

from __future__ import annotations


def pair_key(left: str, right: str) -> tuple[str, str]:
    """The pair's two keys (sequence digests, accessions or ids) as a tuple, the lesser first."""
    return (left, right) if left <= right else (right, left)
