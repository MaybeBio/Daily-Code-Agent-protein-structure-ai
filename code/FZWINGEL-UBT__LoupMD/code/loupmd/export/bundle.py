"""The .loup container (see src/bundle.hpp): named, typed, shaped arrays plus a "meta" text entry."""
from __future__ import annotations

import os
import struct
from pathlib import Path

import numpy as np

MAGIC = b"LOUPC001"
END = b"LOUPEND\0"
_DTYPES = {np.dtype(np.float32): 0, np.dtype(np.float64): 1, np.dtype(np.int32): 2, np.dtype(np.uint8): 3}
_CODES = {v: k for k, v in _DTYPES.items()}


def write_bundle(path, meta: dict, tensors: dict) -> None:
    """Write atomically (temporary file, then rename). Meta values must be str or int (floats go in tensors)."""
    lines = []
    for k, v in meta.items():
        if isinstance(v, (list, tuple)):
            v = ",".join(str(int(x)) for x in v)
        elif isinstance(v, bool):
            v = int(v)
        elif isinstance(v, float):
            raise TypeError(f"meta {k}: floats belong in a tensor entry")
        s = str(v)
        if "\n" in s or "=" in k:
            raise ValueError(f"bad meta entry {k}={s}")
        lines.append(f"{k}={s}")
    entries = {"meta": np.frombuffer("\n".join(lines).encode(), dtype=np.uint8)}
    for name, arr in tensors.items():
        if name == "meta":
            raise ValueError("'meta' is reserved")
        a = np.ascontiguousarray(arr)
        if a.dtype not in _DTYPES:
            raise TypeError(f"{name}: unsupported dtype {a.dtype}")
        entries[name] = a
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    with open(tmp, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<I", len(entries)))
        for name, a in entries.items():
            nb = name.encode()
            f.write(struct.pack("<H", len(nb)))
            f.write(nb)
            f.write(struct.pack("<BB", _DTYPES[a.dtype], a.ndim))
            for d in a.shape:
                f.write(struct.pack("<Q", int(d)))
            f.write(a.astype(a.dtype.newbyteorder("<"), copy=False).tobytes())
        f.write(END)
    os.replace(tmp, path)


def read_bundle(path):
    """(meta dict of str, {name: ndarray})."""
    data = Path(path).read_bytes()
    if data[:8] != MAGIC or data[-8:] != END:
        raise ValueError(f"{path}: not a LOUPC001 bundle")
    pos = 8
    (n,) = struct.unpack_from("<I", data, pos)
    pos += 4
    out = {}
    for _ in range(n):
        (ln,) = struct.unpack_from("<H", data, pos)
        pos += 2
        name = data[pos:pos + ln].decode()
        pos += ln
        dt, nd = struct.unpack_from("<BB", data, pos)
        pos += 2
        dims = struct.unpack_from("<" + "Q" * nd, data, pos)
        pos += 8 * nd
        dtype = _CODES[dt]
        count = int(np.prod(dims)) if nd else 1
        out[name] = np.frombuffer(data, dtype=dtype, count=count, offset=pos).reshape(dims)
        pos += count * dtype.itemsize
    if pos != len(data) - 8:
        raise ValueError(f"{path}: size mismatch")
    meta = dict(line.split("=", 1) for line in out.pop("meta").tobytes().decode().splitlines() if line)
    return meta, out
