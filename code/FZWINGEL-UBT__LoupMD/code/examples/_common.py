"""Shared command-line options of the examples: --model, --head, --checkpoint, --steps, --output, --seed."""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_ROOT = Path("loupmd-examples")


def parser(description: str, *, name: str, steps: int, structure: bool = False) -> argparse.ArgumentParser:
    """An ``ArgumentParser`` with the options every example takes."""
    p = argparse.ArgumentParser(description=description, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--model", default="mh1", help="a model label (`loupmd models`)")
    p.add_argument("--head", default="matpes_r2scan", help="the head of a multi-head model")
    p.add_argument("--checkpoint", metavar="PATH", default=None,
                   help="the label's checkpoint file, checked against its SHA-256; default: LOUPMD_MODELS or the cache")
    p.add_argument("--steps", type=int, default=steps, help="MD or optimiser steps (small for a smoke run)")
    if structure:
        p.add_argument("--structure", metavar="FILE", default=None,
                       help="input structure, any format ASE reads (default: rock-salt NaCl built here)")
    p.add_argument("--output", metavar="DIR", default=str(DEFAULT_ROOT / name), help="output directory")
    p.add_argument("--seed", type=int, default=1, help="noise seed")
    return p


def load(args):
    """The model of ``--model``, ``--head`` and ``--checkpoint``."""
    import loupmd as lm

    return lm.load(args.model, head=args.head, checkpoint=args.checkpoint)


def structure(args):
    """``--structure``, or the 8-atom rock-salt NaCl cell (a = 5.64 A)."""
    from ase.build import bulk
    from ase.io import read

    if getattr(args, "structure", None):
        return read(args.structure)
    return bulk("NaCl", "rocksalt", a=5.64, cubic=True)
