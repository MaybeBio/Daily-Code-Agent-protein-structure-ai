"""Where the exporters and the kernel generator get FastMACE's functions.

By default the vendored subset under ``_vendor/`` (written by ``tools/release/vendor_fastmace.py`` from a FastMACE
commit named in ``_vendor/VERSION``), so an export needs no FastMACE checkout. With the environment variable
``LOUPMD_EXPORT_FASTMACE`` set to a FastMACE checkout the same names come from FastMACE itself: that is how the
byte-identity check (``tools/release/export_identity.sh``) shows that the vendored subset exports the same bundles.
"""
from __future__ import annotations

import os
import sys

_CHECKOUT = os.environ.get("LOUPMD_EXPORT_FASTMACE")
if _CHECKOUT:
    if not os.path.isdir(os.path.join(_CHECKOUT, "fastmace")):
        raise ImportError(f"LOUPMD_EXPORT_FASTMACE={_CHECKOUT} is not a FastMACE checkout (no fastmace/ in it)")
    sys.path.insert(0, _CHECKOUT)
    from fastmace.kernels.cuda import sc_factored, sc_generated
    from fastmace.kernels.triton import compose_skip
    from fastmace.rewrites import radial as rad
    from fastmace.rewrites.generic import modules as generic_modules
    from fastmace.rewrites.linear import modules as linear_modules
    from fastmace.rewrites.radial import spline as rspline
    SOURCE = f"FastMACE checkout {_CHECKOUT}"
else:
    from ._vendor.fastmace.kernels.cuda import sc_factored, sc_generated
    from ._vendor.fastmace.kernels.triton import compose_skip
    from ._vendor.fastmace.rewrites import radial as rad
    from ._vendor.fastmace.rewrites.generic import modules as generic_modules
    from ._vendor.fastmace.rewrites.linear import modules as linear_modules
    from ._vendor.fastmace.rewrites.radial import spline as rspline
    SOURCE = "vendored subset (loupmd/export/_vendor)"

__all__ = ["SOURCE", "compose_skip", "generic_modules", "linear_modules", "rad", "rspline", "sc_factored",
           "sc_generated"]
