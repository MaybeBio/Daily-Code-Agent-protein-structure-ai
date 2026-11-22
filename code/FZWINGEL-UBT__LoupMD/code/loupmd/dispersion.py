"""Dispersion corrections: the ``lm.Dispersion`` record, its presets, the parameter tables and the refusals
(plan task S6-D03; the design is ``docs/design/dispersion.md``).

One argument at three levels: ``dispersion=None`` (off, the default), a preset name, or a :class:`Dispersion`
record; the CLI's ``--dispersion NAME`` and a run file's ``dispersion = "NAME"`` or ``[dispersion]`` table give the
same. :func:`resolve` fills in the model's functional and its parameter set, and refuses what cannot be computed
with the reason and the way out. :func:`runnable` refuses what is not built and :func:`choose` makes the setup
check of ``long_range="auto"`` (S6-D07). Built: the plain real-space pair sum (S6-D04, ``src/dispersion/d3_pair.cu``),
the three-body term (S6-D08) and the split sum (S6-D06, ``src/dispersion/d3_split.cuh``); the tail and mesh methods
(S6-D05, S6-D06) are not yet.

Units: cutoffs in bohr (as the reference code and the literature give them), ``mesh_spacing_A`` in A.
"""
from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass, field, fields, replace

from .errors import InputError, PlanRefused

METHODS = ("d3",)
DAMPINGS = ("bj", "zero", "bjm", "zerom")
LONG_RANGE = ("auto", "none", "tail", "split", "mesh")
AUTO_CANDIDATES = ("none", "tail", "split", "mesh")

# The parameter names each damping takes, with the defaults of the ones that have one.
_PARAMETER_NAMES = {
    "bj": {"s6": None, "s8": None, "a1": None, "a2": None},
    "bjm": {"s6": None, "s8": None, "a1": None, "a2": None},
    "zero": {"s6": None, "s8": None, "rs6": None, "rs8": 1.0, "alpha": 14.0},
    "zerom": {"s6": None, "s8": None, "rs6": None, "beta": None, "rs8": 1.0, "alpha": 14.0},
}

_D3BJ = "S. Grimme, S. Ehrlich, L. Goerigk, J. Comput. Chem. 32, 1456 (2011), doi:10.1002/jcc.21759"
_D3ZERO = "S. Grimme, J. Antony, S. Ehrlich, H. Krieg, J. Chem. Phys. 132, 154104 (2010), doi:10.1063/1.3382344"
_D3M = ("D. G. A. Smith, L. A. Burns, K. Patkowski, C. D. Sherrill, J. Phys. Chem. Lett. 7, 2197 (2016), "
        "doi:10.1021/acs.jpclett.6b00780")
_R2SCAN = ("S. Ehlert, U. Huniar, J. Ning, J. W. Furness, J. Sun, A. D. Kaplan, J. P. Perdew, J. G. Brandenburg, "
           "J. Chem. Phys. 154, 061101 (2021), doi:10.1063/5.0041008, Table 1 (the four-digit values torch-dftd and "
           "mace_mp use)")

# (functional, damping) -> parameters and their source. Only the functionals of the models in the label table;
# any other set is given as raw parameters.
PARAMETERS = {
    ("pbe", "bj"): ({"s6": 1.0, "s8": 0.7875, "a1": 0.4289, "a2": 4.4407}, _D3BJ),
    ("pbe", "zero"): ({"s6": 1.0, "s8": 0.722, "rs6": 1.217, "rs8": 1.0, "alpha": 14.0}, _D3ZERO),
    ("pbe", "bjm"): ({"s6": 1.0, "s8": 0.358940, "a1": 0.012092, "a2": 5.938951}, _D3M),
    ("pbe", "zerom"): ({"s6": 1.0, "s8": 0.0, "rs6": 2.340218, "beta": 0.129434, "rs8": 1.0, "alpha": 14.0}, _D3M),
    ("r2scan", "bj"): ({"s6": 1.0, "s8": 0.7898, "a1": 0.4948, "a2": 5.7308}, _R2SCAN),
}

# Training functionals whose data already contains dispersion, and why.
_DISPERSION_IN_DATA = {
    "wb97m-d3bj": "it was trained on wB97M-D3(BJ) data, which contains a D3(BJ) correction already",
    "wb97m-v": "it was trained on wB97M-V data, whose VV10 nonlocal correlation describes dispersion already",
}
_FAMILY_WITH_DISPERSION = {
    "polar": "MACE-POLAR-1 models long-range interactions of their own and name no single training functional",
}

# What each summation method computes exactly, and its known limits (`loupmd dispersion list`, the docs).
METHOD_LIMITS = {
    "none": ("the plain real-space sum", "exact up to its cutoff", "cost grows with the cube of the cutoff"),
    "tail": ("the real-space sum plus a uniform-density tail beyond the cutoff", "exact for a uniform density "
             "beyond the cutoff", "wrong for slabs, pores, interfaces and anything with vacuum; corrects energy and "
             "pressure, not forces; 'auto' considers it only for cells whose density is uniform on the scale of the "
             "cutoff"),
    "split": ("the damped pair term minus its smooth long-range part in real space to pair_cutoff_bohr, that part "
              "for every pair and image in reciprocal space", "the infinite sum, up to the damping's departure from "
              "1/r^6 beyond the real-space cutoff, and the mesh's interpolation", "3D periodic cells only; the "
              "reciprocal part on a mesh of mesh_spacing_A (default 0.8 A, B-splines of order 8) needs cuFFT"),
    "mesh": ("the whole damped sum on a mesh (after FourierD3)", "exact up to the mesh tolerance",
             "Becke-Johnson damping only; a modified coordination number that vanishes at 6 A; cost grows with the "
             "number of elements"),
}
# Which methods this version computes: the plain sum (S6-D04) and the split sum (S6-D06).
BUILT = frozenset({"none", "split"})


@dataclass(frozen=True)
class Dispersion:
    """A dispersion correction. Every field can be set; the presets (:data:`PRESETS`) are records with names.

    - ``method``: ``"d3"``.
    - ``damping``: ``"bj"`` (Becke-Johnson), ``"zero"``, ``"bjm"`` or ``"zerom"`` (the modified dampings).
    - ``functional``: the parameter set by functional name (``None``: the model's training functional).
    - ``parameters``: raw parameters instead of a functional's set (``s6``, ``s8``, ``a1``, ``a2`` for the BJ
      dampings; ``s6``, ``s8``, ``rs6``, optional ``rs8`` and ``alpha`` for zero damping, plus ``beta`` for zerom).
    - ``three_body`` with ``three_body_cutoff_bohr``: the Axilrod-Teller-Muto term (s9 = 1) over triangles whose
      sides lie within that cutoff; ``smoothing`` switches each side off at it.
    - ``pair_cutoff_bohr``, ``cn_cutoff_bohr``: the pair sum's and the coordination numbers' cutoffs.
    - ``smoothing``: ``"none"`` or the width in bohr of a switch that takes the pair sum to zero at its cutoff
      (and the three-body term at its own).
    - ``long_range``: ``"auto"`` (the fastest method that meets the accuracy contract on the user's structure,
      checked at setup), or a method by name, used as given: ``"none"``, ``"tail"``, ``"split"``, ``"mesh"``.
    - ``mesh_spacing_A``: the mesh of ``"split"`` and ``"mesh"`` (``None``: the method's default).
    - ``update_every``: 1. Updating the long-range part every n steps was measured and rejected (S6-D02).
    - ``auto_methods``: the methods ``"auto"`` may pick (``None``: all built ones).
    """

    method: str = "d3"
    damping: str = "bj"
    functional: str | None = None
    parameters: dict | None = None
    three_body: bool = False
    three_body_cutoff_bohr: float = 40.0
    pair_cutoff_bohr: float = 40.0
    cn_cutoff_bohr: float = 40.0
    smoothing: object = "none"
    long_range: str = "auto"
    mesh_spacing_A: float | None = None
    update_every: int = 1
    auto_methods: tuple | None = None
    preset: str | None = field(default=None, compare=False)

    def __post_init__(self):
        def bad(what, next_step=None):
            raise InputError(f"Dispersion: {what}", next_step=next_step)

        if self.method not in METHODS:
            bad(f"method={self.method!r} is not one of {METHODS}",
                "D4 is not in this version (docs/design/dispersion.md section 6.3).")
        if self.damping not in DAMPINGS:
            bad(f"damping={self.damping!r} is not one of {DAMPINGS}")
        if self.functional is not None and not isinstance(self.functional, str):
            bad(f"functional must be a name, got {self.functional!r}")
        if self.functional is not None:
            object.__setattr__(self, "functional", self.functional.lower())
        if self.parameters is not None:
            object.__setattr__(self, "parameters", _parameters(self.damping, self.parameters))
        for name in ("three_body_cutoff_bohr", "pair_cutoff_bohr", "cn_cutoff_bohr"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
                bad(f"{name} must be a positive number of bohr, got {value!r}")
            object.__setattr__(self, name, float(value))
        if not isinstance(self.three_body, bool):
            bad(f"three_body must be True or False, got {self.three_body!r}")
        if self.three_body and self.three_body_cutoff_bohr > self.pair_cutoff_bohr:
            bad(f"three_body_cutoff_bohr ({self.three_body_cutoff_bohr:g}) is longer than pair_cutoff_bohr "
                f"({self.pair_cutoff_bohr:g})")
        if self.smoothing != "none":
            if isinstance(self.smoothing, bool) or not isinstance(self.smoothing, (int, float)) or \
                    not 0 < self.smoothing < self.pair_cutoff_bohr:
                bad(f"smoothing must be 'none' or a switch width in bohr between 0 and the pair cutoff, got "
                    f"{self.smoothing!r}")
            object.__setattr__(self, "smoothing", float(self.smoothing))
            if self.three_body and self.smoothing >= self.three_body_cutoff_bohr:
                bad(f"smoothing ({self.smoothing:g}) must be shorter than three_body_cutoff_bohr "
                    f"({self.three_body_cutoff_bohr:g})")
        if self.long_range not in LONG_RANGE:
            bad(f"long_range={self.long_range!r} is not one of {LONG_RANGE}")
        if self.long_range == "mesh" and self.damping != "bj":
            bad(f"long_range='mesh' with damping={self.damping!r}: the mesh sum is derived for Becke-Johnson "
                "damping only", "Use damping='bj', or long_range 'none', 'tail' or 'split'.")
        if self.long_range == "mesh" and self.three_body:
            bad("long_range='mesh' with three_body=True: the mesh sum has no three-body term",
                "Use long_range 'none' or 'split' with the three-body term.")
        if self.mesh_spacing_A is not None:
            if self.long_range not in ("split", "mesh", "auto"):
                bad(f"mesh_spacing_A with long_range={self.long_range!r}: only 'split' and 'mesh' use a mesh")
            if isinstance(self.mesh_spacing_A, bool) or not isinstance(self.mesh_spacing_A, (int, float)) or \
                    not self.mesh_spacing_A > 0:
                bad(f"mesh_spacing_A must be a positive number of A, got {self.mesh_spacing_A!r}")
        if isinstance(self.update_every, bool) or not isinstance(self.update_every, int) or self.update_every < 1:
            bad(f"update_every must be a positive int, got {self.update_every!r}")
        if self.update_every != 1:
            bad(f"update_every={self.update_every}: updating the long-range part every few steps is not offered",
                "The bake-off (docs/validation/dispersion-bakeoff.md) measured its stale forces above the accuracy "
                "contract even at 2 steps; leave update_every at 1.")
        if self.auto_methods is not None:
            methods = tuple(self.auto_methods) if not isinstance(self.auto_methods, str) else (self.auto_methods,)
            unknown = [m for m in methods if m not in AUTO_CANDIDATES]
            if unknown or not methods:
                bad(f"auto_methods={self.auto_methods!r}: each must be one of {AUTO_CANDIDATES}")
            if self.long_range != "auto":
                bad(f"auto_methods with long_range={self.long_range!r}: auto_methods restricts the automatic choice "
                    "only", "Leave long_range='auto', or drop auto_methods.")
            object.__setattr__(self, "auto_methods", tuple(sorted(set(methods), key=AUTO_CANDIDATES.index)))


def _parameters(damping, given):
    if not isinstance(given, dict):
        raise InputError(f"Dispersion: parameters must be a table of names and numbers, got {given!r}")
    names = _PARAMETER_NAMES[damping]
    unknown = sorted(set(given) - set(names))
    if unknown:
        raise InputError(f"Dispersion: parameters {unknown} are not parameters of damping {damping!r}",
                         next_step=f"It takes {', '.join(names)}.")
    missing = [k for k, v in names.items() if v is None and k not in given]
    if missing:
        raise InputError(f"Dispersion: damping {damping!r} needs parameters {missing}")
    out = {}
    for name, default in names.items():
        value = given.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InputError(f"Dispersion: parameter {name} must be a number, got {value!r}")
        out[name] = float(value)
    return out


_D3BJ_FIELDS = dict(damping="bj", pair_cutoff_bohr=40.0, cn_cutoff_bohr=40.0, long_range="auto")
PRESETS = {
    "d3bj": (dict(_D3BJ_FIELDS), "BJ, the model's functional, no three-body term; the pair sum by the fastest method "
                                 "that meets the accuracy contract on the structure, checked at setup"),
    "d3bj-mace": (dict(damping="bj", pair_cutoff_bohr=40.0, cn_cutoff_bohr=40.0, long_range="none"),
                  "BJ, the model's functional, the plain sum cut at 40 bohr for pairs and coordination numbers: the "
                  "numbers of mace_mp(dispersion=True) and FastMACE's d3bj"),
    "d3bj-atm": (dict(_D3BJ_FIELDS, three_body=True, three_body_cutoff_bohr=20.0),
                 "d3bj plus the three-body term to 20 bohr"),
    "d3-reference": (dict(damping="bj", pair_cutoff_bohr=60.0, cn_cutoff_bohr=40.0, three_body=True,
                          three_body_cutoff_bohr=40.0, long_range="none"),
                     "BJ, 60 bohr pairs, 40 bohr coordination numbers and three-body term: simple-dftd3's Python "
                     "defaults"),
    "d3zero": (dict(_D3BJ_FIELDS, damping="zero"), "zero damping with d3bj's cutoffs"),
    "d3bjm": (dict(_D3BJ_FIELDS, damping="bjm"), "modified BJ damping with d3bj's cutoffs"),
    "d3zerom": (dict(_D3BJ_FIELDS, damping="zerom"), "modified zero damping with d3bj's cutoffs"),
    "auto": (dict(_D3BJ_FIELDS), "d3bj when the model's functional has a parameter set and its data has no "
                                 "dispersion; refused otherwise"),
}


def preset(name) -> Dispersion:
    """The record of a preset name."""
    if not isinstance(name, str) or name not in PRESETS:
        raise InputError(f"dispersion={name!r} is not a preset", next_step=f"Presets: {', '.join(PRESETS)}; or "
                         "pass an lm.Dispersion record. `loupmd dispersion list` shows each.")
    return Dispersion(**PRESETS[name][0], preset=name)


def parse(value):
    """``None``, a preset name, a :class:`Dispersion` or its table (a run file's ``[dispersion]``, a metadata
    entry) -> ``None`` or a :class:`Dispersion`."""
    if value is None or isinstance(value, Dispersion):
        return value
    if isinstance(value, str):
        return preset(value)
    if isinstance(value, dict):
        data = dict(value)
        data.pop("parameter_source", None)
        data.pop("long_range_chosen_by", None)
        data.pop("long_range_used", None)
        data.pop("long_range_choice", None)       # what the setup check found: made again at a resume
        data.pop("cost", None)
        name = data.pop("preset", None)
        base = PRESETS[name][0] if name in PRESETS else {}
        known = {f.name for f in fields(Dispersion)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise InputError(f"a dispersion table has unknown keys {unknown}", next_step=f"Keys: {', '.join(sorted(known))}.")
        if isinstance(data.get("auto_methods"), list):
            data["auto_methods"] = tuple(data["auto_methods"])
        return Dispersion(**{**base, **data}, preset=name)
    raise InputError(f"dispersion= takes None, a preset name or an lm.Dispersion record, got {value!r}")


def contains_dispersion(functional, family):
    """Why the model's training data already contains dispersion, or None."""
    if functional is not None and functional.lower() in _DISPERSION_IN_DATA:
        return _DISPERSION_IN_DATA[functional.lower()]
    return _FAMILY_WITH_DISPERSION.get(family)


def resolve(value, *, functional, family=None, model=None):
    """The record to run, with the functional and its parameters filled in: ``value`` as :func:`parse` takes it,
    for a model with this training ``functional`` (``None``: unknown) and ``family``. Refuses a model whose data
    already contains dispersion, a model of unknown functional without a functional or parameters, and a damping
    without a parameter set for the functional; warns when the functional differs from the model's."""
    record = parse(value)
    if record is None:
        return None
    name = model or "this model"
    reason = contains_dispersion(functional, family)
    if reason is not None:
        raise PlanRefused(f"dispersion with {name}: {reason}", why="a D3 term on top would count dispersion twice",
                          next_step="Run it without dispersion=, or use a model trained without dispersion (OMAT-0, "
                                    "MP-0, MPA-0, MatPES, or MH-1's omat_pbe / matpes_r2scan heads).")
    used = record.functional or functional
    if record.functional and functional and record.functional != functional.lower():
        warnings.warn(f"dispersion: the parameter set of {record.functional!r} on {name}, which was trained with "
                      f"{functional!r}", stacklevel=2)
    if record.parameters is not None:
        return replace(record, functional=used)
    if used is None:
        raise PlanRefused(f"dispersion with {name}: the model's training functional is not known, so no D3 parameter "
                          "set follows from it", next_step="Pass Dispersion(functional=...) or "
                                                           "Dispersion(parameters={...}).")
    if (used.lower(), record.damping) not in PARAMETERS:
        have = sorted(d for f, d in PARAMETERS if f == used.lower())
        raise PlanRefused(f"dispersion: no {record.damping!r} damping parameters for the functional {used!r}",
                          why=(f"{used} has parameter sets for {', '.join(have)}" if have else
                               f"LoupMD has no parameter set for {used}"),
                          next_step="Choose another damping, or give Dispersion(parameters={...}) with their source.")
    return replace(record, functional=used.lower(), parameters=dict(PARAMETERS[(used.lower(), record.damping)][0]))


def entry(record: Dispersion) -> dict:
    """The record as ``metadata.json`` holds it: equal records give equal entries. Names the parameters' source
    and whether the long-range method was chosen by the user or is chosen automatically at setup."""
    data = asdict(record)
    data.pop("preset")                 # a name, not a setting: the preset and its record give the same entry
    data["auto_methods"] = list(record.auto_methods) if record.auto_methods is not None else None
    key = (record.functional, record.damping)
    data["parameter_source"] = (PARAMETERS[key][1] if key in PARAMETERS and record.parameters == PARAMETERS[key][0]
                                else "given by the user" if record.parameters is not None else None)
    data["long_range_chosen_by"] = "automatic, at setup" if record.long_range == "auto" else "the user"
    return data


def argument(record):
    """The record as a run file's ``dispersion`` takes it: the preset's name when it is one unchanged, else the
    table of its fields (``None``: off)."""
    if record is None:
        return None
    if record.preset in PRESETS and record == preset(record.preset):
        return record.preset
    data = {k: v for k, v in asdict(record).items() if k != "preset" and v is not None}
    if record.auto_methods is not None:
        data["auto_methods"] = list(record.auto_methods)
    return data


def describe(record: Dispersion) -> str:
    """One line: method, damping, parameters, cutoffs, three-body term, long-range method."""
    p = record.parameters or {}
    values = ", ".join(f"{k} {v:g}" for k, v in p.items()) if p else "the model's set"
    three = (f", three-body term to {record.three_body_cutoff_bohr:g} bohr" if record.three_body
             else ", no three-body term")
    if record.smoothing != "none":
        three += f", switched off over the last {record.smoothing:g} bohr"
    lr = (f"long range: {record.long_range} (chosen by the user)" if record.long_range != "auto"
          else "long range: automatic")
    return (f"D3({record.damping}) {record.functional or ''} [{values}], pairs to {record.pair_cutoff_bohr:g} bohr, "
            f"coordination numbers to {record.cn_cutoff_bohr:g} bohr{three}, {lr}").replace("  ", " ")


def listing() -> str:
    """What ``loupmd dispersion list`` prints."""
    lines = ["Presets:"]
    for name, (_, text) in PRESETS.items():
        lines.append(f"  {name:13s} {text}")
    lines += ["", "Dampings: " + ", ".join(DAMPINGS), "", "Summation methods (long_range=):"]
    for name, (what, exact, limits) in METHOD_LIMITS.items():
        built = "" if name in BUILT else " [not built yet]"
        lines.append(f"  {name:6s} {what}; {exact}. Known limits: {limits}.{built}")
    lines += ["  auto   the fastest of the built methods that meets the accuracy contract on the structure, checked "
              "at setup; an explicit long_range is used as given", "", "Parameter sets:"]
    for (functional, damping), (values, source) in PARAMETERS.items():
        text = ", ".join(f"{k} {v:g}" for k, v in values.items())
        lines.append(f"  {functional:7s} {damping:6s} {text}  ({source})")
    lines += ["", "Refused: models whose training data contains dispersion (" +
              ", ".join(sorted(_DISPERSION_IN_DATA)) + " data; MACE-POLAR-1), a model of unknown functional "
              "without functional= or parameters=, a damping without a parameter set for the functional.",
              "", "Built in this version: the plain real-space pair sum with every damping and the switch "
              "(PLAN.md S6-D04), the three-body term (S6-D08), the split sum (S6-D06) and the automatic choice "
              "between them (S6-D07). Not yet: the tail and mesh methods (S6-D05, S6-D06); runs that ask for them "
              "are refused. In the tiled execution the term runs for the whole system beside the tiled model "
              "(S6-D09)."]
    return "\n".join(lines)


def runnable(record: Dispersion) -> str:
    """The summation method a run with ``record`` uses without the setup check, or :class:`PlanRefused` for what is
    not built. ``"auto"`` gives the first built method ``auto_methods`` allows; :func:`choose` makes the choice."""
    reasons = []
    if record.long_range == "auto":
        allowed = [m for m in (record.auto_methods or AUTO_CANDIDATES) if m in BUILT]
        if not allowed:
            reasons.append(f"auto_methods={record.auto_methods!r}: none of them is built in this version (built: "
                           f"{', '.join(sorted(BUILT))})")
        method = allowed[0] if allowed else None
    else:
        method = record.long_range
        if method not in BUILT:
            reasons.append(f"long_range={method!r} is not built in this version (PLAN.md S6-D05, S6-D06; built: "
                           f"{', '.join(sorted(BUILT))})")
    if reasons:
        raise PlanRefused(reasons, next_step="Use the plain sum (long_range='none' or 'auto'), for example the preset "
                                             "'d3bj'.")
    return method


# The automatic choice (PLAN.md S6-D07, D80): the split sum's candidate real-space cutoffs, and the tight split sum
# every candidate is compared against.
SPLIT_CUTOFFS_BOHR = (20.0, 25.0)
REFERENCE_CUTOFF_BOHR = 30.0
REFERENCE_MESH_A = 0.6
EV_PER_A3_IN_GPA = 160.21766208
_DEVIATIONS = (("energy_meV_per_atom", "energy"), ("max_force_eV_per_A", "largest force"), ("stress_GPa", "stress"))


def candidates(record: Dispersion, *, cufft=True):
    """The ``(name, record)`` pairs ``long_range="auto"`` chooses among, and the methods left out with the reason:
    the plain sum at the record's cutoffs, the split sum at each of :data:`SPLIT_CUTOFFS_BOHR` (its mesh: the
    record's ``mesh_spacing_A`` or the default), restricted by ``auto_methods`` to what is built."""
    out, left = [], []
    for method in [m for m in (record.auto_methods or AUTO_CANDIDATES) if m in BUILT]:
        if method == "none":
            out.append((f"none {record.pair_cutoff_bohr:g}",
                        replace(record, long_range="none", mesh_spacing_A=None, auto_methods=None)))
        elif method == "split":
            if not cufft:
                left.append({"method": "split", "why": "cuFFT was not found"})
                continue
            for rc in SPLIT_CUTOFFS_BOHR:
                out.append((f"split {rc:g}", replace(record, long_range="split", pair_cutoff_bohr=rc,
                                                     auto_methods=None)))
    return out, left


def _deviation(got, ref, n):
    import numpy as np

    return {"energy_meV_per_atom": abs(got["energy"] - ref["energy"]) / n * 1000.0,
            "max_force_eV_per_A": float(np.linalg.norm(got["forces"] - ref["forces"], axis=1).max()),
            "stress_GPa": float(np.abs(got["stress"] - ref["stress"]).max()) * EV_PER_A3_IN_GPA}


def choose(record: Dispersion, atoms, *, evaluate, cufft=True, repeat=3, extra=()):
    """The setup check of ``long_range="auto"`` (PLAN.md S6-D07, D80) on ``atoms``: every candidate is evaluated
    once against the split sum at tight settings; one is kept when its energy, largest force and stress deviations
    from it are each no larger than the plain sum's at the record's cutoffs (the accuracy contract, D73); the kept
    ones are timed (``repeat`` captured replays, two rounds in opposite order, the faster of the two) and the
    fastest is used. ``evaluate`` is :func:`loupmd._d3.evaluate`'s signature; ``extra`` adds ``(name, record)``
    candidates (tests). Returns ``(the record to install, the choice for the metadata)``; an explicit
    ``long_range`` is returned as given with ``None``."""
    if record.long_range != "auto":
        return record, None
    import time

    started = time.perf_counter()
    cands, left = candidates(record, cufft=cufft)
    cands = list(cands) + list(extra)
    reference = (f"the split sum at {REFERENCE_CUTOFF_BOHR:g} bohr, B-splines of order 8, a "
                 f"{REFERENCE_MESH_A:g} A mesh")
    choice = {"reference": reference, "left_out": left, "candidates": []}
    if not cands:
        raise PlanRefused([f"auto_methods={record.auto_methods!r}: no candidate can run here"
                           + (f" ({left[0]['why']})" if left else "")],
                          next_step="Allow the plain sum (auto_methods with 'none'), or set long_range.")
    if len(cands) == 1:
        name, used = cands[0]
        choice["candidates"].append({"name": name, "long_range": used.long_range,
                                     "pair_cutoff_bohr": used.pair_cutoff_bohr, "checked": False, "kept": True,
                                     "why": "the only candidate"})
        choice["chosen"] = name
        return used, choice
    n = len(atoms)
    ref_record = replace(record, long_range="split", pair_cutoff_bohr=REFERENCE_CUTOFF_BOHR,
                         mesh_spacing_A=min(REFERENCE_MESH_A, record.mesh_spacing_A or REFERENCE_MESH_A),
                         auto_methods=None)
    ref = evaluate(atoms, ref_record)
    plain_record = replace(record, long_range="none", mesh_spacing_A=None, auto_methods=None)
    plain = evaluate(atoms, plain_record)      # the bound; the plain candidate is this evaluation, not a second one
    bound = _deviation(plain, ref, n)
    choice["bound"] = bound
    rows = []
    for name, cand in cands:
        row = {"name": name, "long_range": cand.long_range, "pair_cutoff_bohr": cand.pair_cutoff_bohr,
               "mesh_spacing_A": cand.mesh_spacing_A, "checked": True, "ms": None}
        try:
            dev = bound if cand == plain_record else _deviation(evaluate(atoms, cand), ref, n)
        except Exception as error:         # a candidate that cannot run here is dropped with the reason
            row.update(kept=False, why=f"it did not run: {str(error).splitlines()[0]}")
            rows.append((row, cand))
            continue
        row.update(dev)
        worse = [what for key, what in _DEVIATIONS if dev[key] > bound[key]]
        row["kept"] = not worse
        if worse:
            listed = worse[0] if len(worse) == 1 else ", ".join(worse[:-1]) + " and " + worse[-1]
            row["why"] = (f"its {listed} deviation{'s are' if len(worse) > 1 else ' is'} larger than the plain "
                          "sum's")
        rows.append((row, cand))
    kept = [(row, cand) for row, cand in rows if row["kept"]]
    if not kept:
        choice["candidates"] = [row for row, _ in rows]
        raise PlanRefused([f"long_range='auto': none of the candidates ({', '.join(r['name'] for r, _ in rows)}) "
                           "is within the plain sum's deviation from the tight split sum on this structure"],
                          next_step="Allow the plain sum (auto_methods with 'none'), or set long_range.")
    if len(kept) > 1:
        times = {id(row): [] for row, _ in kept}
        for order in (kept, kept[::-1]):
            for row, cand in order:
                times[id(row)].append(evaluate(atoms, cand, repeat=repeat)["ms"])
        for row, _ in kept:
            row["ms"] = round(min(times[id(row)]), 3)
        best_row, best = min(kept, key=lambda rc: rc[0]["ms"])
    else:
        best_row, best = kept[0]
    choice["candidates"] = [row for row, _ in rows]
    choice["chosen"] = best_row["name"]
    choice["setup_s"] = round(time.perf_counter() - started, 3)
    return best, choice
