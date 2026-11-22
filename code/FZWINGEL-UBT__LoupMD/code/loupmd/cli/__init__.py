"""The ``loupmd`` command: ``loupmd [--version] [--debug] COMMAND``.

Exit codes: 0 success, 1 a LoupMD error (its message is printed without a traceback unless ``--debug`` is given),
2 a usage error.
"""
from __future__ import annotations

import argparse
import sys

from ..errors import LoupError
from . import bench as _bench
from . import build_kernels as _build_kernels
from . import cache as _cache
from . import dispersion as _dispersion
from . import doctor as _doctor
from . import md as _md
from . import models as _models
from . import quench as _quench
from . import relax as _relax
from . import validate as _validate

COMMANDS = (_doctor, _models, _cache, _bench, _validate, _build_kernels, _md, _relax, _quench, _dispersion)


def build_parser() -> argparse.ArgumentParser:
    from .. import __version__

    parser = argparse.ArgumentParser(prog="loupmd", description="Molecular dynamics with MACE potentials on a "
                                                                "C++/CUDA engine.")
    parser.add_argument("--version", action="version", version=f"loupmd {__version__}")
    parser.add_argument("--debug", action="store_true", help="show the traceback of an error")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    for module in COMMANDS:
        module.add_parser(sub)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_usage(sys.stderr)
        print("loupmd: error: a command is required", file=sys.stderr)
        return 2
    try:
        return int(args.run(args) or 0)
    except LoupError as err:
        if args.debug:
            raise
        print(f"error: {err}", file=sys.stderr)
        return 1
