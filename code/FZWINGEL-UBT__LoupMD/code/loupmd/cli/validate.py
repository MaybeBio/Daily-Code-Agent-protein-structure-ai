"""``loupmd validate``: the accuracy gate on a model and a structure set or your own structures; with
``--dispersion``, the D3 term against simple-dftd3 at the same settings (PLAN.md S6-D10)."""
from __future__ import annotations

import sys
from pathlib import Path

from .. import validate as _validate
from ..config import GateConfig
from ..validate import sets as _sets


def add_parser(sub):
    parser = sub.add_parser(
        "validate", help="check LoupMD against MACE float64 (the 3x rule)",
        description="Compares LoupMD's energy, forces and stress with MACE float64 on strained and rattled "
                    "structures. A quantity passes when its deviation is at most three times MACE float32's own "
                    "deviation, or below 0.01 meV/atom, 1e-5 eV/A, 1e-7 eV/A^3. Needs the export extra (torch, "
                    "mace-torch). With --dispersion: LoupMD's D3 term against simple-dftd3 (the dftd3 package) at the "
                    "same settings on the structures, within 1e-6 eV/atom, 1e-5 eV/A, 1e-7 eV/A^3; the model is not "
                    "run. Exit code 1 when the check fails.")
    parser.add_argument("--model", metavar="MODEL", help="a label (see `loupmd models`), a checkpoint path or a URL; "
                                                         "with --dispersion a label, for its training functional")
    parser.add_argument("--dispersion", metavar="PRESET",
                        help="check this dispersion preset (`loupmd dispersion list`) instead of the model")
    parser.add_argument("--functional", metavar="NAME",
                        help="with --dispersion: the functional whose D3 parameters to use (default: the model's)")
    parser.add_argument("--head", help="the head of a multi-head model")
    parser.add_argument("--checkpoint", metavar="PATH", help="the file of a label, when it is not in LOUPMD_MODELS")
    parser.add_argument("--sha256", metavar="HEX", help="the stated hash of a file that is not in the label table")
    parser.add_argument("--trusted", action="store_true", help="load a file outside the label table without a hash")
    parser.add_argument("--download", action="store_true", help="download a label's checkpoint if it is missing")
    parser.add_argument("--set", choices=_sets.SET_NAMES, default="oxide",
                        help="oxide: NaCl, SrTiO3, NbCl5 (default); organic: urea, naphthalene, paracetamol, water; "
                             "crystals: NaCl, NaNbO3, NbCl5 R2SCAN cells")
    parser.add_argument("--structure", action="append", metavar="FILE",
                        help="gate rattled copies of your own structure instead of a set (repeatable)")
    parser.add_argument("--copies", type=int, default=2, metavar="N", help="rattled copies per structure (default 2)")
    parser.add_argument("--rattle", type=float, default=0.05, metavar="A", help="their displacement width in A "
                                                                               "(default 0.05)")
    parser.add_argument("--ref-device", choices=("auto", "cuda", "cpu"), default="auto",
                        help="where MACE computes the references; cpu for models whose float64 pass does not fit the "
                             "GPU (default: the GPU if there is one)")
    parser.add_argument("--no-ref-cache", action="store_true", help="compute the references again and overwrite the "
                                                                    "cached ones")
    parser.add_argument("--include-unstable", action="store_true",
                        help="also gate configurations on which the model itself is not float32-reproducible")
    parser.add_argument("--specialised", action="store_true",
                        help="refused: the kernels specialised to MACE-OMAT-0 medium (an option of 0.0.1) were "
                             "retired, and every model runs the generic kernels")
    parser.add_argument("--capacity", choices=("whole", "tiled", "wavefront"), default="whole",
                        help="whole: one call per structure (default); tiled: tile by tile, about four tiles per "
                             "structure, as large cells run; wavefront: tiled in the wavefront order with the row "
                             "pool (two-layer models)")
    parser.add_argument("--charge", type=int, help="total charge (models with a charge embedding)")
    parser.add_argument("--spin-multiplicity", type=int, help="2S + 1 (models with a spin embedding)")
    parser.add_argument("--device", type=int, default=0, metavar="N", help="the GPU index (default 0)")
    parser.add_argument("--json", metavar="FILE", help="write the record (loupmd.gate/1) to FILE, or - for stdout")
    parser.set_defaults(run=run)


def run(args) -> int:
    out = sys.stderr if args.json == "-" else sys.stdout
    if args.dispersion is not None:
        return run_dispersion(args, out)
    if args.model is None:
        from ..errors import InputError

        raise InputError("loupmd validate needs --model (the accuracy gate) or --dispersion (the D3 check)")
    record = _validate.run_gate(
        args.model, head=args.head, checkpoint=args.checkpoint, sha256=args.sha256, trusted=args.trusted,
        download=args.download, set_name=args.set, structures=args.structure,
        gate_config=GateConfig(rattle_A=args.rattle, copies=args.copies, reference_device=args.ref_device),
        generic=False if args.specialised else None, charge=args.charge, spin_multiplicity=args.spin_multiplicity,
        device=args.device, use_ref_cache=not args.no_ref_cache, include_unstable=args.include_unstable,
        capacity=args.capacity)
    print(_validate.format_gate(record), file=out)
    print("gate PASSED" if record["passed"] else "gate FAILED", file=out)
    if args.json:
        _validate.write_record(record, args.json)
    return 0 if record["passed"] else 1


def run_dispersion(args, out) -> int:
    from .. import dispersion as _dispersion
    from .. import models
    from ..validate import dispersion as _check

    functional, family, name = args.functional, None, None
    if args.model is not None:
        label = models.find(args.model, args.head)
        if label is None:
            from ..errors import InputError

            raise InputError(f"--model {args.model!r} is not a label of the model table",
                             next_step="Give a label (`loupmd models`), or --functional instead.")
        functional = functional or label.functional
        family, name = label.checkpoint.family, label.label
    record = _dispersion.resolve(args.dispersion, functional=functional, family=family, model=name)
    if args.structure:
        structures = [(Path(path).stem, read(path)) for path in args.structure]
    else:
        structures = [(n, a) for n, a in _sets.configs(args.set)]
    result = _check.check(structures, record)
    print(_check.format_check(result), file=out)
    print("dispersion check PASSED" if result["passed"] else "dispersion check FAILED", file=out)
    if args.json:
        _check.write(result, args.json)
    return 0 if result["passed"] else 1


def read(path):
    from ase.io import read as ase_read

    from ..errors import InputError

    if not Path(path).is_file():
        raise InputError(f"structure file {path} not found")
    return ase_read(path)

