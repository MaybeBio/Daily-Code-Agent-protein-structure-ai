"""The pooled rows of a canonical profile store, as one float32 matrix.

A consumer of the pooled store (`layer_mean_var`, `structural_mean_var`, `final_mean_var`) wants a matrix of the streams
side by side for the proteins it trains or scores. `fetch_pooled` copies the parts that hold those proteins from the Hub
at a pinned revision (`hub.fetch_rows`), opens the partial copy (`open_canonical_view`) and joins the streams in windows,
so no read exceeds a small tensor budget.

Symbols: n proteins, w the summed width of the streams.
"""

from __future__ import annotations

import numpy as np

from collections.abc import Sequence
from pathlib import Path

from .readers import ReadBudget


READ_WINDOW = 1024  # proteins one read joins
READ_BYTES = 256 * 1024 * 1024  # the tensor budget of one read, far above the window's 1,024 rows of a few thousand floats


def fetch_pooled(
    repository: str, folder: str, sequences: Sequence[str], *, streams: Sequence[str], revision: str, local_dir: Path,
    window: int = READ_WINDOW,
) -> np.ndarray:
    """The rows of ``streams`` for ``sequences``, side by side in the order given: an (n, w) float32 matrix.

    ``revision`` is a commit hash, so the result names what it read. A protein the store lacks raises, naming it, before
    any part downloads. ``local_dir`` receives the partial copy and may be reused: a second call downloads only the parts
    it lacks.
    """
    from .canonical import open_canonical_view, sequence_inventory
    from .hub import fetch_rows

    if not sequences:
        raise ValueError("fetch_pooled needs at least one sequence")
    if window < 1:
        raise ValueError("A read window holds at least one protein")
    texts = list(sequences)
    names = list(streams)
    root = fetch_rows(repository, folder, texts, revision=revision, local_dir=local_dir, streams=names)
    budget = ReadBudget(max_rows=window, max_padded_residues=32768, max_bytes=READ_BYTES)
    view = open_canonical_view(root, sequence_inventory(texts), streams=names, budget=budget)
    blocks = [view.pooled(texts[start:start + window], names=names).numpy() for start in range(0, len(texts), window)]  # (b_j, w)

    return np.concatenate(blocks).astype(np.float32, copy=False)  # (n, w)
