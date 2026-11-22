"""``loupmd quench``: relax picked frames of a finished run to their minima."""
from __future__ import annotations

import json
from pathlib import Path

from .. import protocols, provenance, quench
from ..forcefield import load


def add_parser(sub):
    parser = sub.add_parser(
        "quench", help="quench frames of a finished run",
        description="Picks trajectory frames of a finished run per bin of the thermostat's target temperature (on "
                    "each ramp, evenly spaced, plus the final frame), relaxes each at fixed cell and writes the "
                    "minima, a CSV row per frame and a summary into DIR/quench/. An interrupted quench continues.")
    parser.add_argument("directory", metavar="DIR", help="the output directory of a run made with a schedule")
    parser.add_argument("--min-K", type=float, dest="min_K", help="the lowest target temperature picked from")
    parser.add_argument("--bin-K", type=float, dest="bin_K", help="the width of a temperature bin")
    parser.add_argument("--per-bin", type=int, dest="per_bin", help="frames per bin and ramp")
    parser.add_argument("--fmax", type=float, help="relax until the largest force is below this, eV/A")
    parser.add_argument("--optimizer", choices=tuple(quench.OPTIMIZERS), help="default gpu-LBFGS (FastMACE's name; "
                                                                              "LoupMD's LBFGS)")
    parser.add_argument("--max-steps", type=int, dest="max_steps", help="optimiser steps per frame at most")
    parser.add_argument("--name", default=quench.QUENCH_DIRECTORY, help="the quench's folder in DIR (default "
                                                                        "quench)")
    parser.add_argument("--device", type=int, default=0, metavar="N", help="the GPU index (default 0)")
    parser.set_defaults(run=run)


def settings_of(args, metadata) -> dict:
    """The run's profile's quench settings, else FastMACE's defaults, with the command line's on top."""
    settings = dict(quench.DEFAULTS)
    profile = (metadata.get("arguments") or {}).get("profile")
    if profile in protocols.PROFILES and protocols.PROFILES[profile].quench:
        settings.update(protocols.PROFILES[profile].quench)
    for key in protocols.QUENCH_KEYS:
        if getattr(args, key) is not None:
            settings[key] = getattr(args, key)
    return settings


def run(args) -> int:
    directory = Path(args.directory)
    record = directory / provenance.METADATA_NAME
    metadata = json.loads(record.read_text()) if record.is_file() else {}
    model = metadata.get("model") or {}
    force_field = None
    if model:
        if model["label"] is not None:
            force_field = load(model["label"], model["head"], charge=model["charge"],
                               spin_multiplicity=model["spin_multiplicity"], device=args.device)
        else:
            force_field = load(model["path"], model["head"], sha256=model["sha256"], charge=model["charge"],
                               spin_multiplicity=model["spin_multiplicity"], device=args.device)
    summary = quench.quench_run(directory, force_field, settings_of(args, metadata), name=args.name)
    for phase in ("heating", "cooling"):
        part = summary[phase]
        if part:
            print(f"{phase}: {part['frames']} frames, quenched energies {part['min_eV_atom']:.6f} to "
                  f"{part['max_eV_atom']:.6f} eV/atom (mean {part['mean_eV_atom']:.6f})")
    print(f"final frame: {summary['final_quenched_eV_atom']:.6f} eV/atom; {summary['frames']} frames in "
          f"{summary['quench_wall_s']:.1f} s; {summary['not_converged']} not converged; results in "
          f"{directory / args.name}")
    return 0 if summary["not_converged"] == 0 else 1
