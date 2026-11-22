"""``loupmd validate --dispersion``: LoupMD's D3 term against simple-dftd3 at the same settings on the user's
structures (PLAN.md S6-D10; ``docs/design/dispersion.md`` section 5, item 7).

simple-dftd3 (LGPL-3.0-or-later, the ``dftd3`` Python package) is called as an external library and is not shipped
with LoupMD. It covers every damping, the cutoffs and the three-body term, so it is a complete reference for what this
version computes. The bounds are the plan's for the term (S6-D04): 1e-6 eV/atom, 1e-5 eV/A, 1e-7 eV/A^3.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..errors import InputError, PlanRefused

BOHR = 0.529177210903
HARTREE = 27.211386245988
BOUNDS = {"energy_eV_atom": 1e-6, "force_eV_A": 1e-5, "stress_eV_A3": 1e-7}
SCHEMA = "loupmd.dispersion-check/1"


def _dftd3():
    try:
        from dftd3 import interface
    except ImportError as error:
        raise InputError("the dispersion check needs simple-dftd3's Python package (dftd3)",
                         why=str(error),
                         next_step="Install it: `conda install -c conda-forge simple-dftd3 dftd3-python` or "
                                   "`pip install dftd3`.") from None
    return interface


def reference(atoms, record):
    """simple-dftd3's energy (eV), forces (eV/A) and stress (eV/A^3, 3x3, dE/d strain / V) at ``record``'s settings."""
    d3 = _dftd3()
    p = record.parameters
    s9 = 1.0 if record.three_body else 0.0
    if record.damping == "bj":
        param = d3.RationalDampingParam(s6=p["s6"], s8=p["s8"], a1=p["a1"], a2=p["a2"], s9=s9)
    elif record.damping == "bjm":
        param = d3.ModifiedRationalDampingParam(s6=p["s6"], s8=p["s8"], a1=p["a1"], a2=p["a2"], s9=s9)
    elif record.damping == "zero":
        param = d3.ZeroDampingParam(s6=p["s6"], s8=p["s8"], rs6=p["rs6"], rs8=p["rs8"], alp=p["alpha"], s9=s9)
    else:
        param = d3.ModifiedZeroDampingParam(s6=p["s6"], s8=p["s8"], rs6=p["rs6"], rs8=p["rs8"], alp=p["alpha"],
                                            bet=p["beta"], s9=s9)
    model = d3.DispersionModel(atoms.numbers, atoms.positions / BOHR, np.asarray(atoms.cell) / BOHR,
                               np.array([True, True, True]))
    model.set_realspace_cutoff(disp2=record.pair_cutoff_bohr, disp3=record.three_body_cutoff_bohr,
                               cn=record.cn_cutoff_bohr)
    res = model.get_dispersion(param, grad=True)
    return (float(res["energy"]) * HARTREE, -np.asarray(res["gradient"]) * HARTREE / BOHR,
            np.asarray(res["virial"]) * HARTREE / atoms.get_volume())


def checkable(record):
    """Refuse what simple-dftd3 does not compute the same way."""
    from .. import dispersion as _dispersion

    if record.smoothing != "none":
        raise PlanRefused(f"the dispersion check with smoothing={record.smoothing:g}",
                          why="simple-dftd3 has no switch of the same form; the switch's forces and stress are "
                              "checked against finite differences in tests/gpu/test_d3.py",
                          next_step="Check the same settings without smoothing.")
    _dispersion.runnable(record)          # refuses what is not built


def check(structures, record, *, lib=None, reference_record=None) -> dict:
    """``structures``: ``[(name, atoms)]``, periodic. Each is evaluated with LoupMD's term at ``record`` and with
    simple-dftd3 at ``reference_record`` (default: the same record; a different one makes the check fail on purpose,
    which is how the check itself is tested). Returns the record ``loupmd.dispersion-check/1``."""
    from .. import _d3
    from .. import dispersion as _dispersion

    checkable(record)
    ref_record = reference_record or record
    rows = []
    for name, atoms in structures:
        if not all(atoms.pbc):
            raise InputError(f"{name} is not periodic in all three directions",
                             next_step="Put a molecule or slab in a box with vacuum and set pbc=True.")
        got = _d3.evaluate(atoms, record, lib=lib)
        e, f, s = reference(atoms, ref_record)
        n = len(atoms)
        dev = {"energy_eV_atom": abs(got["energy"] - e) / n,
               "force_eV_A": float(np.abs(got["forces"] - f).max()),
               "stress_eV_A3": float(np.abs(got["stress"] - s).max())}
        rows.append({"structure": name, "atoms": n, "energy_eV": got["energy"], "reference_energy_eV": e,
                     "deviation": dev, "passed": all(dev[k] <= BOUNDS[k] for k in BOUNDS)})
    return {"schema": SCHEMA, "dispersion": _dispersion.entry(record), "description": _dispersion.describe(record),
            "reference": "simple-dftd3 " + _dftd3_version(), "bounds": dict(BOUNDS), "rows": rows,
            "passed": bool(rows) and all(r["passed"] for r in rows)}


def _dftd3_version():
    try:
        import dftd3

        return str(getattr(dftd3, "__version__", "unknown version"))
    except ImportError:
        return "not installed"


def format_check(result) -> str:
    lines = [f"dispersion: {result['description']}", f"reference: {result['reference']}, same settings",
             f"{'structure':24s} {'atoms':>6s} {'E (eV/atom)':>12s} {'dE eV/atom':>11s} {'dF eV/A':>10s} "
             f"{'dS eV/A^3':>10s}  result"]
    for r in result["rows"]:
        d = r["deviation"]
        lines.append(f"{r['structure'][:24]:24s} {r['atoms']:6d} {r['energy_eV'] / r['atoms']:12.6f} "
                     f"{d['energy_eV_atom']:11.1e} {d['force_eV_A']:10.1e} {d['stress_eV_A3']:10.1e}  "
                     f"{'pass' if r['passed'] else 'FAIL'}")
    b = result["bounds"]
    lines.append(f"bounds: {b['energy_eV_atom']:g} eV/atom, {b['force_eV_A']:g} eV/A, {b['stress_eV_A3']:g} eV/A^3")
    return "\n".join(lines)


def write(result, target):
    text = json.dumps(result, indent=2)
    if target == "-":
        print(text)
    else:
        Path(target).write_text(text + "\n", encoding="utf-8")
