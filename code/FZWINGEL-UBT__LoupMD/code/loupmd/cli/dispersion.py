"""``loupmd dispersion list``: the dispersion presets, dampings, summation methods with their known limits and the
parameter sets with their sources."""
from __future__ import annotations


def add_parser(sub):
    parser = sub.add_parser("dispersion", help="dispersion presets and methods (`loupmd dispersion list`)",
                            description="Dispersion corrections: what the presets mean, which summation methods "
                                        "exist and where each is wrong, and the parameter sets with their sources.")
    kinds = parser.add_subparsers(dest="what", metavar="WHAT")
    listing = kinds.add_parser("list", help="the presets, dampings, methods and parameter sets")
    listing.set_defaults(run=run_list)
    parser.set_defaults(run=run_list)


def run_list(args):
    from ..dispersion import listing

    print(listing())
    return 0
