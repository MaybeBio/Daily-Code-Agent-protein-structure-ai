"""The model label table and the rules for finding and trusting a checkpoint file.

A label names one released checkpoint and, for multi-head checkpoints, one head. The checkpoint record holds the
official release URL, the file name, the SHA-256 of the released file, the licence and each head's training
functional. A MACE checkpoint is a pickle and runs code when it is loaded, so a file is accepted only when its
SHA-256 matches the table, or matches a hash the caller gives, or the caller says ``trusted=True``.

The table is FastMACE's (``fastmace/model/labels.py`` at commit ``9b801229``; hashes and licences checked there on
17 October 2026, MH-1's functionals on 19 October 2026). This module imports nothing heavy and loads no model.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType

from . import cache
from .errors import CheckpointTrustError, InputError

ASL = "ASL"  # Academic Software License: non-commercial use only
MIT = "MIT"
LICENCE_TEXT = MappingProxyType({
    ASL: "Academic Software License (non-commercial use only), https://github.com/gabor1/ASL",
    MIT: "MIT License",
})
FAMILIES = ("mh1", "omol", "polar", "residual", "density", "off")
MODELS_VARIABLE = "LOUPMD_MODELS"
_CHUNK = 1 << 20


@dataclass(frozen=True)
class Checkpoint:
    """One released checkpoint file."""

    name: str
    url: str
    sha256: str
    licence: str      # ASL or MIT
    model_type: str   # "MACE" or "PolarMACE"
    family: str       # one of FAMILIES
    # Heads stored in the checkpoint, in its order, with the training functional of each head (None where the
    # release does not say). Single-head checkpoints have one entry.
    heads: tuple = ()
    head_functionals: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
    # Joint embedding of per-graph inputs (OMOL-0: total charge and spin), as stored in the checkpoint.
    embedding_specs: MappingProxyType | None = None
    # Where each head's functional comes from, keyed like head_functionals; "unknown: <why>" for None.
    functional_sources: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
    # Read from the released file (python -m loupmd._probe; tests/test_models.py compares when the file is there):
    elements: tuple = ()             # atomic numbers the model has an embedding for
    r_max_A: float | None = None     # cutoff radius
    interactions: int | None = None  # interaction layers

    @property
    def file_name(self):
        return self.url.rsplit("/", 1)[1]


@dataclass(frozen=True)
class ModelLabel:
    """A label of the table: one checkpoint and one head."""

    label: str
    checkpoint: Checkpoint
    head: str | None        # None: the checkpoint's only head
    functional: str | None  # training functional of that head (selects the D3 parameter set)

    @property
    def licence(self):
        return self.checkpoint.licence

    @property
    def model_type(self):
        return self.checkpoint.model_type

    @property
    def family(self):
        return self.checkpoint.family

    @property
    def elements(self):
        return self.checkpoint.elements

    @property
    def functional_source(self):
        """Where ``functional`` comes from; ``"unknown: <why>"`` when it is None."""
        key = self.head if self.head is not None else (_only_head(self.checkpoint) or "")
        return self.checkpoint.functional_sources.get(key)


def _frozen(mapping):
    return MappingProxyType({k: MappingProxyType(dict(v)) if isinstance(v, dict) else v
                             for k, v in mapping.items()})


_MP = "https://github.com/ACEsuit/mace-mp/releases/download"
_FOUNDATIONS = "https://github.com/ACEsuit/mace-foundations/releases/download"
_OFF = "https://raw.githubusercontent.com/ACEsuit/mace-off/main"

# Sources of the training functionals.
_MP_TABLE = ("PBE (PBE+U where MP applies it): the mace-foundations model table, "
             "https://github.com/ACEsuit/mace-foundations (checked 17 October 2026)")
_MATPES_PBE_TABLE = ("PBE (MatPES, without U): the mace-foundations model table, "
                     "https://github.com/ACEsuit/mace-foundations (checked 17 October 2026)")
_R2SCAN_TABLE = ("r2SCAN (MatPES): the mace-foundations model table, "
                 "https://github.com/ACEsuit/mace-foundations (checked 17 October 2026)")
_OMOL_TABLE = ("wB97M-V/def2-TZVPD (OMol25), with its VV10 nonlocal term: the mace-foundations model table, "
               "https://github.com/ACEsuit/mace-foundations (checked 17 October 2026)")
_OFF_README = ("wB97M-D3(BJ)/def2-TZVPPD (SPICE): https://github.com/ACEsuit/mace-off README "
               "(checked 17 October 2026)")
_POLAR_UNKNOWN = ("unknown: the mace_polar_1 release names no single training functional for the head, so no D3 "
                  "parameter set follows from it")
_MH1_CARD = "model card https://huggingface.co/mace-foundations/mace-mh-1, 'Available Model Heads' (19 October 2026)"
_MH1_PAPER = "arXiv:2510.25380 (MACE-MH-1), section 'Multi-head fine-tuning' datasets (19 October 2026)"


def _single(name, url, sha256, licence, family, functional, source, head="default", model_type="MACE", **extra):
    heads = (head,) if head else ()
    return Checkpoint(name=name, url=url, sha256=sha256, licence=licence, model_type=model_type, family=family,
                      heads=heads, head_functionals=_frozen({head or "": functional}),
                      functional_sources=_frozen({head or "": source}), **extra)


CHECKPOINTS = MappingProxyType({c.name: c for c in (
    _single("medium", f"{_MP}/mace_mp_0/2023-12-03-mace-128-L1_epoch-199.model",
            "01bfe22100139f424713cf921144e5509cbe353d67aa9fa1be9c6e1e0ed35845", MIT, "residual", "pbe",
            _MP_TABLE, head=None),
    _single("large", f"{_MP}/mace_mp_0/MACE_MPtrj_2022.9.model",
            "f80e992b65ab8f88fdf26964511357c022e92704e4d9bcd086652635a8495b32", MIT, "residual", "pbe",
            _MP_TABLE, head=None),
    _single("medium-0b3", f"{_MP}/mace_mp_0b3/mace-mp-0b3-medium.model",
            "2f2be696351ac9e94fbe01cdfb6f017679acdbd2db7645209ef55fec9826b012", MIT, "density", "pbe", _MP_TABLE),
    _single("medium-mpa-0", f"{_MP}/mace_mpa_0/mace-mpa-0-medium.model",
            "75428afe3a1d7d8062e19bcaabd5c433623cabf308242ec9fb493e38604fb638", MIT, "density", "pbe", _MP_TABLE),
    _single("medium-omat-0", f"{_MP}/mace_omat_0/mace-omat-0-medium.model",
            "d4b14be9afa294eebdbe31a0280b26a0fa29715771e978cbfd3ca24e0d90307a", ASL, "density", "pbe", _MP_TABLE),
    # OMAT-0 small: the same release and architecture family as medium, stored head "omat_pbe".
    _single("small-omat-0", f"{_MP}/mace_omat_0/mace-omat-0-small.model",
            "0abfde07862cf1e93b8b4d03cb702f29ce9c344ff2fc4de2ec0d7166d6c113a5", ASL, "density", "pbe", _MP_TABLE,
            head="omat_pbe"),
    _single("mace-matpes-pbe-0", f"{_FOUNDATIONS}/mace_matpes_0/MACE-matpes-pbe-omat-ft.model",
            "e618ad582b84239905b9c3b77ce6e9ce111b0ecd1533223a1a6aac7a696b8aa0", ASL, "density", "pbe",
            _MATPES_PBE_TABLE),
    _single("mace-matpes-r2scan-0", f"{_FOUNDATIONS}/mace_matpes_0/MACE-matpes-r2scan-omat-ft.model",
            "8f147ecffa1d06a696e5648b13b81abda9c96fda9d0fb3faba3cd3fb27d9bba9", ASL, "density", "r2scan",
            _R2SCAN_TABLE),
    Checkpoint(
        name="mh-1", url=f"{_FOUNDATIONS}/mace_mh_1/mace-mh-1.model",
        sha256="a522eb7f59c7879963d41586528f4980baf33e086c94aa92e3eafdeccad3be47", licence=ASL,
        model_type="MACE", family="mh1",
        # The heads stored in this file (SHA-256 above), in its order. The model card and the MACE 0.3.15 release
        # notes list rgd1_b3lyp (B3LYP) instead of mp_pbe_refit_add; the released file has mp_pbe_refit_add, the
        # MPTraj head of the paper, and no RGD1 head.
        heads=("matpes_r2scan", "mp_pbe_refit_add", "spice_wB97M", "oc20_usemppbe", "omol", "omat_pbe"),
        head_functionals=_frozen({"matpes_r2scan": "r2scan", "mp_pbe_refit_add": "pbe",
                                  "spice_wB97M": "wb97m-d3bj", "oc20_usemppbe": "pbe", "omol": "wb97m-v",
                                  "omat_pbe": "pbe"}),
        functional_sources=_frozen({
            "matpes_r2scan": f"r2SCAN meta-GGA (MatPES r2SCAN, without U): {_MH1_CARD}; {_MH1_PAPER}",
            "mp_pbe_refit_add": f"PBE/PBE+U (MPTraj, Materials Project): {_MH1_PAPER}",
            "spice_wB97M": f"wB97M-D3(BJ)/def2-TZVP (SPICE-1): {_MH1_CARD}; {_MH1_PAPER}",
            # OC20's original release is RPBE; MH-1's OC20 subset is stated as PBE by both sources.
            "oc20_usemppbe": f"PBE (OC20 subset): {_MH1_CARD}; {_MH1_PAPER}",
            "omol": f"wB97M-V (stated as wB97M-VV10; OMol25 1%): {_MH1_CARD}; {_MH1_PAPER}",
            "omat_pbe": f"PBE/PBE+U (OMat24): {_MH1_CARD}; {_MH1_PAPER}",
        })),
    _single("polar-1-s", f"{_FOUNDATIONS}/mace_polar_1/MACE-POLAR-1-S.model",
            "e4495612037b3b3312633182882a38a694ecac9ea0be2b9889ac0b2a84a99510", ASL, "polar", None, _POLAR_UNKNOWN,
            head="Default", model_type="PolarMACE"),
    _single("polar-1-m", f"{_FOUNDATIONS}/mace_polar_1/MACE-POLAR-1-M.model",
            "fab8b8713c832f31a2a853aaa22fd638be8a369cbf5095e6b3e982a18d10e93a", ASL, "polar", None, _POLAR_UNKNOWN,
            head="Default", model_type="PolarMACE"),
    _single("polar-1-l", f"{_FOUNDATIONS}/mace_polar_1/MACE-POLAR-1-L.model",
            "9f65f8dc6ddaff1d631e299cb531376a7da5e68d1bef04f34a2d5073d5ef114b", ASL, "polar", None, _POLAR_UNKNOWN,
            head="Default", model_type="PolarMACE"),
    _single("omol-0-xl", f"{_FOUNDATIONS}/mace_omol_0/MACE-omol-0-extra-large-1024.model",
            "9b64b4fd5153ca578c694abc57806d8111050de6ff652e695c9b525bc4d36469", ASL, "omol", "wb97m-v", _OMOL_TABLE,
            head="omol",
            # Read from the released checkpoint: total charge -100..100 (offset 100) and total spin 0..100, both
            # one per graph. LoupMD folds both into the bundle at export (PLAN.md decision O7).
            embedding_specs=_frozen({
                "total_spin": {"type": "categorical", "per": "graph", "in_dim": 1, "emb_dim": 1024,
                               "num_classes": 101, "offset": 0},
                "total_charge": {"type": "categorical", "per": "graph", "in_dim": 1, "emb_dim": 1024,
                                 "num_classes": 201, "offset": 100},
            })),
    _single("off23-small", f"{_OFF}/mace_off23/MACE-OFF23_small.model",
            "165cce4cfec5a34b9c64d4ebf95de15d71106bb584b7291c8470f0749977c46f", ASL, "off", "wb97m-d3bj",
            _OFF_README, head=None),
    _single("off23-medium", f"{_OFF}/mace_off23/MACE-OFF23_medium.model",
            "4842c52ad210d6e1f84d6cf1ffa70fae25a7e0d755ed55cf223f43913f587db7", ASL, "off", "wb97m-d3bj",
            _OFF_README, head=None),
    _single("off23-large", f"{_OFF}/mace_off23/MACE-OFF23_large.model",
            "a29e397dbf3e7a24ac50a9b0dfc919bd5a62efa346f5895a6237b0950c1d76f4", ASL, "off", "wb97m-d3bj",
            _OFF_README, head=None),
    _single("off23b-medium", f"{_OFF}/mace_off23/MACE-OFF23b_medium.model",
            "871653738a4fbc8124dba1ff5bc595bd0abf7b849a8538c0825dc29ebadf1680", ASL, "off", "wb97m-d3bj",
            _OFF_README, head=None),
    _single("off24-medium", f"{_OFF}/mace_off24/MACE-OFF24_medium.model",
            "e5ccf5837f685899811a68754e7c994393bfd1a81720393b03c643b46c70bc69", ASL, "off", "wb97m-d3bj",
            _OFF_README, head=None),
)})


# What each released file holds: (elements, cutoff in A, interaction layers), read from the files on 15 November
# 2026 with loupmd._probe. Three element sets: Z 1-83 and 89-94 (the Materials Project models and MH-1), Z 1-83
# (POLAR-1, OMOL-0) and the ten elements of MACE-OFF.
_Z89 = tuple(range(1, 84)) + tuple(range(89, 95))
_Z83 = tuple(range(1, 84))
_Z_OFF = (1, 6, 7, 8, 9, 15, 16, 17, 35, 53)
_CONTENTS = {
    "medium": (_Z89, 6.0, 2), "large": (_Z89, 4.5, 2), "medium-0b3": (_Z89, 6.0, 2), "medium-mpa-0": (_Z89, 6.0, 2),
    "medium-omat-0": (_Z89, 6.0, 2), "small-omat-0": (_Z89, 6.0, 2), "mace-matpes-pbe-0": (_Z89, 6.0, 2),
    "mace-matpes-r2scan-0": (_Z89, 6.0, 2), "mh-1": (_Z89, 6.0, 2),
    "polar-1-s": (_Z83, 6.0, 1), "polar-1-m": (_Z83, 6.0, 2), "polar-1-l": (_Z83, 6.0, 3),
    "omol-0-xl": (_Z83, 6.0, 3),
    "off23-small": (_Z_OFF, 4.5, 2), "off23-medium": (_Z_OFF, 5.0, 2), "off23-large": (_Z_OFF, 5.0, 2),
    "off23b-medium": (_Z_OFF, 6.0, 2), "off24-medium": (_Z_OFF, 6.0, 2),
}
CHECKPOINTS = MappingProxyType({
    name: replace(entry, elements=_CONTENTS[name][0], r_max_A=_CONTENTS[name][1], interactions=_CONTENTS[name][2])
    for name, entry in CHECKPOINTS.items()})


def checkpoint_of_digest(digest):
    """The table's checkpoint with this SHA-256, or None: what a file given by path is, once it is trusted."""
    return next((entry for entry in CHECKPOINTS.values() if entry.sha256 == digest), None)


def _label(label, checkpoint, head=None):
    entry = CHECKPOINTS[checkpoint]
    key = head if head is not None else (entry.heads[0] if entry.heads else "")
    return ModelLabel(label=label, checkpoint=entry, head=head, functional=entry.head_functionals.get(key))


LABELS = MappingProxyType({m.label: m for m in (
    _label("mp0-medium", "medium"),
    _label("mp0-large", "large"),
    _label("mp0b3-medium", "medium-0b3"),
    _label("mpa0-medium", "medium-mpa-0"),
    _label("omat0-medium", "medium-omat-0"),
    _label("omat0-small", "small-omat-0"),
    _label("matpes-pbe", "mace-matpes-pbe-0"),
    _label("matpes-r2scan", "mace-matpes-r2scan-0"),
    _label("mh1-omat", "mh-1", "omat_pbe"),
    _label("mh1-mp", "mh-1", "mp_pbe_refit_add"),
    _label("mh1-r2scan", "mh-1", "matpes_r2scan"),
    _label("polar1-s", "polar-1-s"),
    _label("polar1-m", "polar-1-m"),
    _label("polar1-l", "polar-1-l"),
    _label("omol0-xl", "omol-0-xl", "omol"),
    _label("off23-small", "off23-small"),
    _label("off23-medium", "off23-medium"),
    _label("off23-large", "off23-large"),
    _label("off23b-medium", "off23b-medium"),
    _label("off24-medium", "off24-medium"),
)})

# Short names for a checkpoint whose head is passed separately: lm.load("mh1", head="matpes_r2scan").
ALIASES = MappingProxyType({"mh1": "mh-1", "omol0": "omol-0-xl"})


def _only_head(checkpoint):
    return checkpoint.heads[0] if checkpoint.heads else None


def find(name, head=None):
    """The ModelLabel for a label, alias or checkpoint name with an optional head; None if it is not one.

    A label fixes its head; a different ``head=`` is refused. An alias or checkpoint name takes ``head=``, which
    must be one of the checkpoint's heads; a multi-head checkpoint without ``head=`` is refused with its heads
    listed (there is no default head).
    """
    if name in LABELS:
        entry = LABELS[name]
        if head is not None and head != (entry.head or _only_head(entry.checkpoint)):
            raise InputError(f"label {name!r} is head {entry.head!r}",
                             next_step=f"Drop head={head!r}, or use the checkpoint name {entry.checkpoint.name!r} "
                                       "with the head you want.")
        return entry
    if ":" in name and ALIASES.get(name, name) not in CHECKPOINTS:
        # The label of a head without its own entry ("mh-1:omol", below).
        base, own_head = name.rsplit(":", 1)
        if base in CHECKPOINTS:
            if head is not None and head != own_head:
                raise InputError(f"label {name!r} is head {own_head!r}", next_step=f"Drop head={head!r}.")
            return find(base, own_head)
    checkpoint = CHECKPOINTS.get(ALIASES.get(name, name))
    if checkpoint is None:
        return None
    if head is None:
        if len(checkpoint.heads) > 1:
            raise InputError(f"{name!r} has several heads and no default",
                             next_step=f"Pass head= one of {', '.join(checkpoint.heads)}.")
        head_key = _only_head(checkpoint)
    elif checkpoint.heads and head not in checkpoint.heads:
        raise InputError(f"{name!r} has no head {head!r}",
                         next_step=f"Its heads are {', '.join(checkpoint.heads)}.")
    else:
        head_key = head
    for entry in LABELS.values():
        if entry.checkpoint is checkpoint and (entry.head or _only_head(checkpoint)) == head_key:
            return entry
    # A head without its own label (MH-1's spice_wB97M, oc20_usemppbe, omol).
    return ModelLabel(label=f"{checkpoint.name}:{head_key}", checkpoint=checkpoint, head=head,
                      functional=checkpoint.head_functionals.get(head_key))


# ------------------------------------------------------------------------------------------- finding the file

@dataclass(frozen=True)
class ResolvedCheckpoint:
    path: Path
    origin: str               # "explicit", MODELS_VARIABLE, "cache" or "download"
    label: ModelLabel | None  # None for a path or URL outside the table
    searched: tuple = ()


def _is_url(source):
    return isinstance(source, str) and source.startswith(("https://", "http://"))


def models_cache_directory(environ=None):
    """``<cache root>/models``: where downloads go and the last place a label's file is looked for."""
    return cache.cache_dir("models", create=False, environ=environ)


def resolve_checkpoint(source, head=None, checkpoint=None, environ=None, download=False, sha256=None):
    """Find the checkpoint file of ``source`` (a label, alias, checkpoint name, path or URL).

    Order for a label: ``checkpoint`` (an explicit path), else ``$LOUPMD_MODELS/<file>``, else
    ``<cache root>/models/<file>``, else, with ``download=True`` only, the official URL into the cache directory. A
    path is used as it is. A URL's file is taken from the cache directory if it is there, else downloaded into it
    with ``download=True`` only. A download is checked against the table's SHA-256, or for a URL against
    ``sha256``, and is not kept if it differs.
    """
    environ = os.environ if environ is None else environ
    entry = None if isinstance(source, os.PathLike) or _is_url(source) else find(str(source), head)
    if checkpoint is not None:
        path = Path(os.path.expanduser(checkpoint))
        if not path.is_file():
            raise InputError(f"checkpoint {path} not found")
        return ResolvedCheckpoint(path.resolve(), "explicit", entry, (str(path),))
    if entry is None and not _is_url(source):
        path = Path(os.path.expanduser(source))
        if not path.is_file():
            raise InputError(f"{str(source)!r} is neither a model label nor an existing checkpoint file",
                             next_step=f"Labels: {', '.join(LABELS)}.")
        return ResolvedCheckpoint(path.resolve(), "explicit", None, (str(path),))
    file_name = entry.checkpoint.file_name if entry is not None else source.rsplit("/", 1)[1]
    searched = []
    models = environ.get(MODELS_VARIABLE)
    if models and entry is not None:
        path = Path(os.path.expanduser(models)) / file_name
        searched.append(str(path))
        if path.is_file() and path.stat().st_size:
            return ResolvedCheckpoint(path.resolve(), MODELS_VARIABLE, entry, tuple(searched))
    path = models_cache_directory(environ) / file_name
    searched.append(str(path))
    if path.is_file() and path.stat().st_size:
        return ResolvedCheckpoint(path.resolve(), "cache", entry, tuple(searched))
    if not download:
        raise InputError(f"checkpoint {file_name} not found",
                         why=f"looked in {', '.join(searched)}",
                         next_step=f"Pass checkpoint=, set {MODELS_VARIABLE} to the folder that holds it, or ask for "
                                   "the download (download=True; `loupmd models --download LABEL`).")
    url = entry.checkpoint.url if entry is not None else source
    expected = entry.checkpoint.sha256 if entry is not None else (sha256.lower() if sha256 else None)
    return ResolvedCheckpoint(download_checkpoint(url, path, expected), "download", entry, tuple(searched))


def download_checkpoint(url, target, sha256=None):
    """Download ``url`` to ``target`` atomically; with ``sha256``, a file whose hash differs is deleted and
    refused before anything reads it."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".part")
    temporary = Path(temporary)
    try:
        digest = hashlib.sha256()
        with os.fdopen(handle, "wb") as output, urllib.request.urlopen(url, timeout=120) as response:
            if "text/html" in response.headers.get("Content-Type", "").lower():
                raise OSError(f"checkpoint URL returned HTML: {url}")
            while chunk := response.read(_CHUNK):
                digest.update(chunk)
                output.write(chunk)
            expected_length = response.headers.get("Content-Length")
            if expected_length is not None and output.tell() != int(expected_length):
                raise OSError(f"incomplete checkpoint download: {url}")
            if not output.tell():
                raise OSError(f"empty checkpoint: {url}")
        if sha256 is not None and digest.hexdigest() != sha256:
            raise CheckpointTrustError(
                f"the download {url} has SHA-256 {digest.hexdigest()}, not the expected {sha256}",
                why="the file differs from the one whose hash was given, so it was deleted without being unpickled",
                next_step="Check the URL and the hash; a checkpoint is a pickle and runs code when loaded.")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target.resolve()


def sha256_of(path):
    """The SHA-256 of a file, hex."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def check_trust(resolved, digest, sha256=None, trusted=False):
    """Decide whether the file may be unpickled; returns "label", "sha256" or "trusted".

    ``sha256=`` must match the file. A label's file must match the table. A file without either needs
    ``trusted=True``. This rule is never weakened (PLAN.md section 2).
    """
    if sha256 is not None:
        if digest != sha256.lower():
            raise CheckpointTrustError(
                f"{resolved.path} has SHA-256 {digest}, not the expected {sha256}",
                why="the file is not the one whose hash was given, so it was not unpickled")
        return "sha256"
    if resolved.label is not None:
        if digest == resolved.label.checkpoint.sha256:
            return "label"
        if trusted:
            return "trusted"
        raise CheckpointTrustError(
            f"{resolved.path} has SHA-256 {digest}, but label {resolved.label.label!r} is the release with "
            f"SHA-256 {resolved.label.checkpoint.sha256}",
            why="the file is not the released checkpoint of the label, so it was not unpickled",
            next_step="Download the release again (download=True), or pass trusted=True to load this file anyway.")
    if trusted:
        return "trusted"
    raise CheckpointTrustError(
        f"{resolved.path} (SHA-256 {digest}) is not a model of the label table and was not unpickled",
        why="MACE checkpoints are pickles that run code when loaded; a file from a path or URL needs a stated hash",
        next_step=f"Pass sha256='{digest}' after checking the file against its publisher, or trusted=True.")


def trusted_checkpoint(source, head=None, *, checkpoint=None, sha256=None, trusted=False, download=False,
                       environ=None):
    """Resolve ``source`` and apply the trust rule: ``(ResolvedCheckpoint, digest, trust)``. Nothing is unpickled
    here; the export step loads the file only after this returned."""
    if _is_url(source) and checkpoint is None and sha256 is None and not trusted:
        raise CheckpointTrustError(
            f"{source} is a URL without a hash",
            why="a checkpoint is a pickle and runs code when loaded",
            next_step="Pass sha256= with the hash its publisher gives, or trusted=True.")
    resolved = resolve_checkpoint(source, head, checkpoint, environ, download, sha256)
    digest = sha256_of(resolved.path)
    return resolved, digest, check_trust(resolved, digest, sha256, trusted)
