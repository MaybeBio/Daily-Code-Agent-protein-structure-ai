"""``python -m loupmd._probe CHECKPOINT``: what a MACE checkpoint holds, as one line of JSON.

Needs the export extra (torch and mace-torch); it runs in a process of its own so that the runtime never imports
torch. A checkpoint is a pickle: the caller applies the trust rule (``loupmd.models.check_trust``) before this runs.
"""
from __future__ import annotations

import json
import os
import sys


def describe(path) -> dict:
    os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
    import torch

    model = torch.load(path, map_location="cpu", weights_only=False)
    return {"class": type(model).__name__,
            "elements": [int(z) for z in model.atomic_numbers],
            "heads": [str(h) for h in (getattr(model, "heads", None) or [])],
            "r_max": float(model.r_max),
            "num_interactions": int(model.num_interactions)}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m loupmd._probe CHECKPOINT", file=sys.stderr)
        return 2
    print(json.dumps(describe(argv[0])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
