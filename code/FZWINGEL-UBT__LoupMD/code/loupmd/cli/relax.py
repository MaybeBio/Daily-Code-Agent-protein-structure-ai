"""``loupmd relax``: relax a structure at fixed cell and write it as extended XYZ."""
from __future__ import annotations

from pathlib import Path

from .. import optimize
from ..errors import InputError
from ..forcefield import load


def add_parser(sub):
    parser = sub.add_parser(
        "relax", help="relax a structure",
        description="Relaxes a structure at fixed cell with ASE's LBFGS or FIRE until the largest force on an atom "
                    "is below --fmax, and writes it with its energy and forces as extended XYZ.")
    parser.add_argument("structure", help="the structure file (anything ASE reads)")
    parser.add_argument("--model", required=True, metavar="MODEL", help="a label (see `loupmd models`), a checkpoint "
                                                                       "path or a URL")
    parser.add_argument("--head", help="the head of a multi-head model")
    parser.add_argument("--checkpoint", metavar="PATH", help="the file of a label, when it is not in LOUPMD_MODELS")
    parser.add_argument("--sha256", metavar="HEX", help="the stated hash of a file that is not in the label table")
    parser.add_argument("--trusted", action="store_true", help="load a file outside the label table without a hash")
    parser.add_argument("--download", action="store_true", help="download a label's checkpoint if it is missing")
    parser.add_argument("--charge", type=int, help="total charge (models with a charge embedding)")
    parser.add_argument("--spin-multiplicity", type=int, help="2S + 1 (models with a spin embedding)")
    parser.add_argument("--optimizer", choices=("lbfgs", "fire"), default="lbfgs", help="default lbfgs")
    parser.add_argument("--fmax", type=float, default=0.05, metavar="EV_PER_A", help="default 0.05 eV/A")
    parser.add_argument("--steps", type=int, default=100_000_000, help="at most this many optimiser steps")
    parser.add_argument("--maxstep", type=float, default=0.2, metavar="A", help="the longest step (default 0.2 A)")
    parser.add_argument("--repeat", type=int, nargs=3, metavar=("A", "B", "C"), default=[1, 1, 1], help="the supercell")
    parser.add_argument("--dispersion", metavar="PRESET", help="a dispersion preset (`loupmd dispersion list`): the "
                                                               "D3 term in every force call")
    parser.add_argument("--d3-functional", metavar="NAME", dest="d3_functional",
                        help="with --dispersion: the functional whose D3 parameters to use (default: the model's)")
    parser.add_argument("--device", type=int, default=0, metavar="N", help="the GPU index (default 0)")
    parser.add_argument("--output", metavar="FILE", help="the relaxed structure (default <structure "
                                                         "stem>.relaxed.extxyz)")
    parser.set_defaults(run=run)


def relax_file(structure, *, model, head=None, checkpoint=None, sha256=None, trusted=False, download=False,
               charge=None, spin_multiplicity=None, optimizer="lbfgs", fmax=0.05, steps=100_000_000, maxstep=0.2,
               repeat=(1, 1, 1), device=0, output=None, dispersion=None):
    """What ``loupmd relax`` does: read, relax, write. Returns ``(RelaxResult, output path)``."""
    from ase.io import read, write

    path = Path(structure)
    if not path.is_file():
        raise InputError(f"structure file {path} not found")
    record = (optimize.LBFGS(maxstep_A=maxstep) if optimizer == "lbfgs" else optimize.FIRE(maxstep_A=maxstep))
    atoms = read(path)
    if tuple(repeat) != (1, 1, 1):
        atoms = atoms.repeat(tuple(repeat))
    force_field = load(model, head, checkpoint=checkpoint, sha256=sha256, trusted=trusted, download=download,
                             charge=charge, spin_multiplicity=spin_multiplicity, device=device)
    result = optimize.relax(force_field, atoms, record, fmax=fmax, steps=steps, dispersion=dispersion)
    target = Path(output) if output else Path(path.stem + ".relaxed.extxyz")
    write(target, result.atoms, format="extxyz")
    return result, target


def run(args) -> int:
    dispersion = args.dispersion
    if args.d3_functional is not None:
        if dispersion is None:
            raise InputError("--d3-functional names the parameters of --dispersion, which is not given",
                             next_step="Add --dispersion d3bj (or another preset of `loupmd dispersion list`).")
        dispersion = {"preset": dispersion, "functional": args.d3_functional}
    result, target = relax_file(args.structure, model=args.model, head=args.head, checkpoint=args.checkpoint,
                                sha256=args.sha256, trusted=args.trusted, download=args.download, charge=args.charge,
                                spin_multiplicity=args.spin_multiplicity, optimizer=args.optimizer, fmax=args.fmax,
                                steps=args.steps, maxstep=args.maxstep, repeat=args.repeat, device=args.device,
                                output=args.output, dispersion=dispersion)
    calls = result.force_calls
    print(f"{result}; {calls} force calls in {result.force_s:.2f} s, {result.optimizer_s:.3f} s in the optimiser")
    print(f"written to {target}")
    return 0 if result.converged else 1
