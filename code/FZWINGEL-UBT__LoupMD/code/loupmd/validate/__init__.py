"""The accuracy gate as a library (``loupmd validate``, PLAN.md section 2 and task S2-T09)."""
from __future__ import annotations

from . import gate, references, sets
from .gate import GateRow, format_gate, make_record, write_record  # noqa: F401


def run_gate(model, **options):
    """See ``loupmd.validate.gate.run_gate``."""
    return gate.run_gate(model, **options)
