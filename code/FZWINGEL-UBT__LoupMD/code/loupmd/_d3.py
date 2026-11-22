"""The library's D3 pair term on its own (``loup_d3_evaluate``, plan task S6-D04): the reference tables LoupMD ships
and one evaluation of a periodic structure. The validation (``tests/gpu/test_d3.py``) and the setup check of
S6-D07 use it; inside a run the engine calls the same kernels."""
from __future__ import annotations

import ctypes
from functools import lru_cache
from pathlib import Path

import numpy as np

from .errors import BackendError, InputError

BOHR = 0.529177210903       # A
DAMPING_CODES = {"bj": 0, "zero": 1, "bjm": 2, "zerom": 3}
# "auto" is resolved before the term is made (S6-D07); until then it runs the plain sum
LONG_RANGE_CODES = {"auto": 0, "none": 0, "tail": 1, "split": 2, "mesh": 3}
TABLES = Path(__file__).parent / "data" / "d3_tables.npz"


class LoupD3Settings(ctypes.Structure):
    _fields_ = [("damping", ctypes.c_int)] + [(name, ctypes.c_double) for name in (
        "s6", "s8", "a1", "a2", "rs6", "rs8", "alpha", "beta", "pair_cutoff_bohr", "cn_cutoff_bohr",
        "smoothing_bohr")] + [("three_body", ctypes.c_int), ("three_body_cutoff_bohr", ctypes.c_double),
                              ("long_range", ctypes.c_int), ("mesh_spacing_A", ctypes.c_double)]


_D = ctypes.POINTER(ctypes.c_double)


class LoupD3Tables(ctypes.Structure):
    _fields_ = [("nref", ctypes.POINTER(ctypes.c_int)), ("cnref", _D), ("rcov", _D), ("r2r4", _D), ("c6ref", _D),
                ("r0ab", _D)]


@lru_cache(maxsize=1)
def tables() -> dict:
    """The arrays of ``loupmd/data/d3_tables.npz`` (torch-dftd 0.5.1's tables, MIT; tools/dev/make_d3_tables.py)."""
    with np.load(TABLES) as d:
        out = {k: np.ascontiguousarray(d[k]) for k in ("nref", "cnref", "rcov", "r2r4", "c6ref", "r0ab")}
    out["nref"] = out["nref"].astype(np.int32)
    return out


def settings(record) -> LoupD3Settings:
    """The C settings of a resolved :class:`loupmd.dispersion.Dispersion` (parameters filled in)."""
    if record.parameters is None:
        raise InputError("the dispersion record has no parameters: resolve it against the model first")
    p = record.parameters
    smoothing = 0.0 if record.smoothing == "none" else float(record.smoothing)
    if record.long_range == "split":
        from ._core import ensure_cufft

        ensure_cufft()          # the library opens cuFFT by name (PLAN.md D79); it refuses the term without it
    return LoupD3Settings(DAMPING_CODES[record.damping], p["s6"], p["s8"], p.get("a1", 0.0), p.get("a2", 0.0),
                          p.get("rs6", 0.0), p.get("rs8", 1.0), p.get("alpha", 14.0), p.get("beta", 0.0),
                          record.pair_cutoff_bohr, record.cn_cutoff_bohr, smoothing, int(record.three_body),
                          record.three_body_cutoff_bohr, LONG_RANGE_CODES[record.long_range],
                          float(record.mesh_spacing_A or 0.0))


def _lib(lib=None):
    if lib is None:
        from ._core import _load_lib

        lib = _load_lib()
    if not hasattr(lib, "loup_d3_evaluate"):
        raise BackendError("the library has no D3 term", why="it was built before PLAN.md task S6-D04",
                           next_step="Rebuild the library from this source tree (`make`).")
    lib.loup_d3_evaluate.argtypes = [ctypes.POINTER(LoupD3Settings), ctypes.POINTER(LoupD3Tables), ctypes.c_int,
                                     ctypes.POINTER(ctypes.c_int), _D, _D, ctypes.c_int, _D, _D, _D, _D, _D]
    lib.loup_d3_evaluate.restype = ctypes.c_int
    lib.loup_d3_last_error.argtypes = []
    lib.loup_d3_last_error.restype = ctypes.c_char_p
    return lib


def _ptr(a):
    return a.ctypes.data_as(_D)


def evaluate(atoms, record, *, forces=True, stress=True, per_atom=False, repeat=0, lib=None) -> dict:
    """One D3 evaluation of a periodic ``atoms`` with a resolved record: ``energy`` (eV), ``forces`` (eV/A),
    ``stress`` (eV/A^3, 3x3, ASE's sign: dE/d strain / V), ``energies`` (eV per atom), ``ms`` (the mean of
    ``repeat`` replays of the captured evaluation)."""
    if not all(atoms.pbc):
        raise InputError("the D3 term needs a periodic cell", next_step="Set atoms.pbc = True with a cell.")
    lib = _lib(lib)
    t = tables()
    tab = LoupD3Tables(t["nref"].ctypes.data_as(ctypes.POINTER(ctypes.c_int)), _ptr(t["cnref"]), _ptr(t["rcov"]),
                       _ptr(t["r2r4"]), _ptr(t["c6ref"]), _ptr(t["r0ab"]))
    n = len(atoms)
    z = np.ascontiguousarray(atoms.numbers, dtype=np.int32)
    pos = np.ascontiguousarray(atoms.positions, dtype=np.float64)
    cell = np.ascontiguousarray(np.asarray(atoms.cell), dtype=np.float64)
    e = np.zeros(1)
    f = np.zeros((n, 3)) if forces else None
    v = np.zeros(6) if stress else None
    ea = np.zeros(n) if per_atom else None
    ms = np.zeros(1)
    s = settings(record)
    rc = lib.loup_d3_evaluate(ctypes.byref(s), ctypes.byref(tab), n, z.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
                              _ptr(pos), _ptr(cell), int(repeat), _ptr(e), _ptr(f) if forces else None,
                              _ptr(v) if stress else None, _ptr(ea) if per_atom else None, _ptr(ms))
    if rc != 0:
        raise BackendError((lib.loup_d3_last_error() or b"loup_d3_evaluate failed").decode())
    out = {"energy": float(e[0])}
    if forces:
        out["forces"] = f
    if stress:
        xx, xy, xz, yy, yz, zz = v
        out["stress"] = np.array([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]]) / atoms.get_volume()
    if per_atom:
        out["energies"] = ea
    if repeat:
        out["ms"] = float(ms[0])
    return out


class Term:
    """A D3 term kept across calls (``loup_d3_create``; the tiled execution, PLAN.md S6-D09): made for the atomic
    numbers and a cell, then ``compute(positions, cell)`` -> ``(energy eV, forces eV/A, stress eV/A^3 3x3)``."""

    def __init__(self, record, numbers, cell, *, lib=None):
        lib = _lib(lib)
        if not hasattr(lib, "loup_d3_create"):
            raise BackendError("the library has no persistent D3 term", why="it was built before PLAN.md S6-D09",
                               next_step="Rebuild the library from this source tree (`make`).")
        lib.loup_d3_create.argtypes = [ctypes.POINTER(LoupD3Settings), ctypes.POINTER(LoupD3Tables), ctypes.c_int,
                                       ctypes.POINTER(ctypes.c_int), _D]
        lib.loup_d3_create.restype = ctypes.c_void_p
        lib.loup_d3_compute.argtypes = [ctypes.c_void_p, _D, _D, _D, _D, _D, _D]
        lib.loup_d3_compute.restype = ctypes.c_int
        lib.loup_d3_device_bytes.argtypes = [ctypes.c_void_p]
        lib.loup_d3_device_bytes.restype = ctypes.c_size_t
        lib.loup_d3_destroy.argtypes = [ctypes.c_void_p]
        lib.loup_d3_destroy.restype = None
        self._lib, self.record = lib, record
        t = tables()
        tab = LoupD3Tables(t["nref"].ctypes.data_as(ctypes.POINTER(ctypes.c_int)), _ptr(t["cnref"]), _ptr(t["rcov"]),
                           _ptr(t["r2r4"]), _ptr(t["c6ref"]), _ptr(t["r0ab"]))
        z = np.ascontiguousarray(numbers, dtype=np.int32)
        self.n = len(z)
        c = np.ascontiguousarray(cell, dtype=np.float64)
        s = settings(record)
        self._h = lib.loup_d3_create(ctypes.byref(s), ctypes.byref(tab), self.n,
                                     z.ctypes.data_as(ctypes.POINTER(ctypes.c_int)), _ptr(c))
        if not self._h:
            raise BackendError((lib.loup_d3_last_error() or b"loup_d3_create failed").decode())

    def device_bytes(self) -> int:
        return int(self._lib.loup_d3_device_bytes(self._h))

    def compute(self, positions, cell, *, stress=True):
        pos = np.ascontiguousarray(positions, dtype=np.float64)
        c = np.ascontiguousarray(cell, dtype=np.float64)
        e, f, v = np.zeros(1), np.zeros((self.n, 3)), np.zeros(6)
        rc = self._lib.loup_d3_compute(self._h, _ptr(pos), _ptr(c), _ptr(e), _ptr(f), _ptr(v) if stress else None,
                                       None)
        if rc != 0:
            raise BackendError((self._lib.loup_d3_last_error() or b"loup_d3_compute failed").decode())
        out_stress = None
        if stress:
            xx, xy, xz, yy, yz, zz = v
            out_stress = np.array([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]]) / abs(float(np.linalg.det(c)))
        return float(e[0]), f, out_stress

    def close(self):
        if getattr(self, "_h", None):
            self._lib.loup_d3_destroy(self._h)
            self._h = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
