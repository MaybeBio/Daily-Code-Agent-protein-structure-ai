"""Export a MACE model into a .loup bundle. Every model, MACE-OMAT-0 medium included, exports through the generic
path (``loupmd.export.generic``); the kernels specialised to MACE-OMAT-0 medium were retired (JIT_DESIGN.md
stage 5).

  python -m loupmd.export --model M --elements 8,22,38 --output out.loup [--head H]
                          [--charge Q --spin-multiplicity M]   (models with a total charge / spin embedding:
                                                                MACE-OMOL-0)

``--generic`` is accepted and ignored (it selected the generic path before every model took it).

The exporters need torch, mace-torch and cuequivariance (the package's ``export`` extra). Nothing here is imported
by ``import loupmd``: the bundle cache (``loupmd.bundles``) runs this module in a process of its own.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--elements", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--head", default=None)
    ap.add_argument("--generic", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--charge", type=int, default=None)
    ap.add_argument("--spin-multiplicity", type=int, default=None)
    a = ap.parse_args()
    from . import generic as export_generic

    from ..errors import UnsupportedModel
    from ..kernels import UNSUPPORTED_MARKER, UNSUPPORTED_STATUS

    elems = [int(x) for x in a.elements.split(",") if x.strip()]
    try:
        export_generic.export_model(a.model, elems, Path(a.output), a.head, a.charge, a.spin_multiplicity)
    except UnsupportedModel as error:      # for the caller (bundles.ensure_bundle): the marker, then the status
        print(str(error), file=sys.stderr)
        print(f"{UNSUPPORTED_MARKER} {' '.join(error.signatures)}", file=sys.stderr)
        raise SystemExit(UNSUPPORTED_STATUS) from None
