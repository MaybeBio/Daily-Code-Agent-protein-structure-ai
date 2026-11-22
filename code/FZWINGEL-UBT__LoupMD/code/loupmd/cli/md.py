"""``loupmd md``, ``loupmd init`` and ``loupmd run``: one-command MD, a run file of its arguments, running one."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import protocols, provenance, report, runfile
from ..errors import InputError


def _arguments_parser(parser):
    """The arguments of ``loupmd md``; ``loupmd init md`` takes the same."""
    parser.add_argument("structure", nargs="?", help="the structure file (anything ASE reads)")
    parser.add_argument("--structure", metavar="FILE", dest="structure_flag",
                        help="the structure file, as FastMACE spells it (instead of the positional argument)")
    parser.add_argument("--model", required=True, metavar="MODEL", help="a label (see `loupmd models`), a checkpoint "
                                                                       "path or a URL")
    parser.add_argument("--head", help="the head of a multi-head model")
    parser.add_argument("--checkpoint", metavar="PATH", help="the file of a label, when it is not in LOUPMD_MODELS")
    parser.add_argument("--sha256", metavar="HEX", help="the stated hash of a file that is not in the label table")
    parser.add_argument("--trusted", action="store_true", help="load a file outside the label table without a hash")
    parser.add_argument("--download", action="store_true", help="download a label's checkpoint if it is missing")
    parser.add_argument("--charge", type=int, help="total charge (models with a charge embedding)")
    parser.add_argument("--spin-multiplicity", type=int, help="2S + 1 (models with a spin embedding)")
    parser.add_argument("--ensemble", default="NVT", help="NVT (default), NVE or NPT (Langevin BAOAB at "
                                                          "--pressure; experimental)")
    parser.add_argument("--pressure", type=float, metavar="GPA", dest="pressure_GPa",
                        help="the target pressure in GPa of --ensemble NPT (default 0)")
    parser.add_argument("--cell-mode", choices=("hydrostatic", "full"), dest="cell_mode",
                        help="--ensemble NPT: hydrostatic (default: the cell keeps its shape) or full")
    parser.add_argument("--thermostat", choices=("langevin", "csvr"), help="the NVT thermostat: langevin (default) "
                        "or csvr (Bussi's velocity rescaling, which needs --tau)")
    parser.add_argument("--friction", type=float, metavar="PER_FS", help="Langevin's friction per fs (default about "
                                                                         "0.002)")
    parser.add_argument("--tau", type=float, metavar="FS", dest="tau_fs", help="the thermostat's time constant in "
                                                                               "fs (csvr; no default)")
    parser.add_argument("--temperature", type=float, metavar="K", dest="temperature_K", help="the thermostat's target")
    parser.add_argument("--schedule", metavar="SEGMENTS", help="ramps and holds in order, separated by commas: "
                        "ramp:START_K:END_K:PS and hold:K:PS, for example ramp:0:400:3,hold:400:1,ramp:400:0:24")
    parser.add_argument("--profile", metavar="NAME", help="a shipped profile (" + ", ".join(protocols.PROFILES) +
                        ") or a profile file: its schedule and output cadences, and for a profile at constant "
                        "pressure NPT at its pressure")
    parser.add_argument("--timestep", type=float, default=0.5, metavar="FS", dest="timestep_fs",
                        help="the timestep in fs (default 0.5)")
    parser.add_argument("--steps", type=int, help="the number of steps (optional with a schedule or a profile)")
    parser.add_argument("--repeat", type=int, nargs=3, metavar=("A", "B", "C"), default=[1, 1, 1], help="the supercell")
    parser.add_argument("--seed", type=int, help="the noise seed (default: drawn and recorded)")
    parser.add_argument("--initial-velocities", default="keep", metavar="HOW", help="keep (default), "
                        "maxwell_boltzmann or a temperature in K: what a structure at rest starts with")
    parser.add_argument("--check", default="skip", help="skip (default), gate or allow_unavailable: the accuracy "
                                                        "gate before the first step")
    parser.add_argument("--device", type=int, default=0, metavar="N", help="the GPU index (default 0)")
    parser.add_argument("--capacity", choices=("auto", "whole", "tiled", "wavefront"), default="auto",
                        help="auto (default): the whole cell when it fits the GPU, else tiles (every integrator; "
                             "with a dispersion term NVE and Langevin only, no barostat); "
                             "whole, tiled or wavefront (tiles in the wavefront order, two-layer models) force one")
    parser.add_argument("--skin", default="auto", metavar="A", help="the neighbour-list skin in A, or auto "
                        "(default): chosen from how far the atoms move per step; it decides speed only")
    parser.add_argument("--output", metavar="DIR", help="the output directory (default <structure stem>.loupmd)")
    parser.add_argument("--thermo-every", type=int, metavar="N", help="thermo rows every N steps (default 20)")
    parser.add_argument("--trajectory-every", type=int, metavar="N", help="trajectory frames every N steps (default "
                                                                          "20; 0: none)")
    parser.add_argument("--restart-every", type=int, metavar="N", help="restart points every N steps (default 10000; "
                                                                       "0: only at the end)")
    parser.add_argument("--dispersion", metavar="PRESET", help="a dispersion preset (`loupmd dispersion list`): "
                                                               "the D3 term on every step")
    parser.add_argument("--d3-functional", metavar="NAME", dest="d3_functional",
                        help="with --dispersion: the functional whose D3 parameters to use (default: the model's)")


def _segments(text) -> list:
    segments = []
    for part in text.split(","):
        fields = part.strip().split(":")
        try:
            if fields[0] == "ramp" and len(fields) == 4:
                segments.append({"kind": "ramp", "start_K": float(fields[1]), "end_K": float(fields[2]),
                                 "ps": float(fields[3])})
                continue
            if fields[0] == "hold" and len(fields) == 3:
                segments.append({"kind": "hold", "temperature_K": float(fields[1]), "ps": float(fields[2])})
                continue
        except ValueError:
            pass
        raise InputError(f"--schedule segment {part.strip()!r} is not ramp:START_K:END_K:PS or hold:K:PS")
    return segments


def arguments_of(args) -> dict:
    """The run file's table of the parsed command line: only what differs from the defaults."""
    velocities = args.initial_velocities
    if velocities not in ("keep", "maxwell_boltzmann"):
        try:
            velocities = float(velocities)
        except ValueError:
            raise InputError(f"--initial-velocities {velocities!r} is not keep, maxwell_boltzmann or a temperature "
                             "in K") from None
    if (args.structure is None) == (args.structure_flag is None):
        raise InputError("give the structure file once: as the first argument or as --structure FILE",
                         next_step="loupmd md STRUCTURE --model M ... (or --structure STRUCTURE)")
    arguments = {"structure": args.structure or args.structure_flag, "model": args.model}
    if args.skin != "auto":
        try:
            arguments["skin"] = float(args.skin)
        except ValueError:
            raise InputError(f"--skin {args.skin!r} is not a length in A or auto") from None
    for key in ("head", "checkpoint", "sha256", "charge", "spin_multiplicity", "temperature_K", "profile", "steps",
                "seed", "pressure_GPa", "cell_mode", "dispersion"):
        if getattr(args, key) is not None:
            arguments[key] = getattr(args, key)
    for key, default in (("trusted", False), ("download", False), ("ensemble", "NVT"), ("timestep_fs", 0.5),
                         ("repeat", [1, 1, 1]), ("check", "skip"), ("device", 0), ("capacity", "auto")):
        if getattr(args, key) != default:
            arguments[key] = getattr(args, key)
    if velocities != "keep":
        arguments["initial_velocities"] = velocities
    if args.d3_functional is not None:
        if args.dispersion is None:
            raise InputError("--d3-functional names the parameters of --dispersion, which is not given",
                             next_step="Add --dispersion d3bj (or another preset of `loupmd dispersion list`).")
        arguments["dispersion"] = {"preset": args.dispersion, "functional": args.d3_functional}
    if args.thermostat == "csvr":
        if args.tau_fs is None or args.friction is not None:
            raise InputError("--thermostat csvr takes --tau FS (its time constant, which has no default) and no "
                             "--friction")
        arguments["integrator"] = {"type": "CSVR", "tau_fs": args.tau_fs}
    elif args.tau_fs is not None:
        raise InputError("--tau is the time constant of --thermostat csvr; Langevin takes --friction")
    elif args.friction is not None and (str(args.ensemble).upper() == "NPT" or _npt_profile(args)):
        # the record holds the barostat's settings too: lm.md takes them from one place
        arguments["integrator"] = {"type": "LangevinBAOAB", "friction_per_fs": args.friction,
                                   "cell_mode": arguments.pop("cell_mode", "hydrostatic")}
        if "pressure_GPa" in arguments or not _npt_profile(args):     # else the profile's pressure (runfile)
            arguments["integrator"]["pressure_GPa"] = arguments.pop("pressure_GPa", 0.0)
    elif args.friction is not None:
        arguments["integrator"] = {"type": "Langevin", "friction_per_fs": args.friction}
    if args.schedule:
        arguments["schedule"] = _segments(args.schedule)
    out = {}
    if args.output:
        out["directory"] = args.output
    for key in ("thermo_every", "trajectory_every", "restart_every"):
        value = getattr(args, key)
        if value is not None:
            out[key] = None if value == 0 and key != "thermo_every" else value
    if out:
        arguments["output"] = out
    runfile.check(arguments)
    return arguments


def _npt_profile(args) -> bool:
    return args.profile is not None and protocols.find_profile(args.profile).ensemble == "NPT"


def add_parser(sub):
    md = sub.add_parser("md", help="run MD in one command",
                        description="Molecular dynamics on a structure with a MACE model. Writes thermo rows, a "
                                    "trajectory, a restart and metadata.json into the output directory and prints a "
                                    "one-screen report.")
    _arguments_parser(md)
    md.set_defaults(run=run_md)

    init = sub.add_parser("init", help="write a run file of `loupmd md`'s arguments",
                          description="Prints a commented TOML file of every argument of `loupmd md`, with the ones "
                                      "given here filled in: loupmd init md STRUCTURE --model M ... > run.toml")
    kinds = init.add_subparsers(dest="kind", metavar="KIND")
    init_md = kinds.add_parser("md", help="a run file for `loupmd run`")
    _arguments_parser(init_md)
    init_md.set_defaults(run=run_init)
    init.set_defaults(run=lambda args: _usage(init))

    run = sub.add_parser("run", help="run a run file, or resume a run",
                         description="Runs a TOML run file (see `loupmd init md`) or the metadata.json of a finished "
                                     "run. With --resume, continues the run of a directory from its restart.")
    run.add_argument("file", nargs="?", help="a run file (.toml) or a metadata.json")
    run.add_argument("--resume", metavar="DIR", help="continue the run in DIR from its restart file")
    run.add_argument("--steps", type=int, help="with --resume: the number of further steps (default: what is left "
                                               "of the run's steps or schedule)")
    run.set_defaults(run=run_file)


def _usage(parser) -> int:
    parser.print_usage(sys.stderr)
    return 2


def run_md(args) -> int:
    result = runfile.run(arguments_of(args))
    print(result.summary)
    result.simulation.close()
    return 0


def run_init(args) -> int:
    sys.stdout.write(runfile.to_toml(arguments_of(args)))
    return 0


def run_file(args) -> int:
    if (args.file is None) == (args.resume is None):
        raise InputError("loupmd run takes a run file or --resume DIR, one of the two")
    if args.resume is not None:
        return _resume(Path(args.resume), args.steps)
    if args.steps is not None:
        raise InputError("--steps is for --resume; a run file names its own steps")
    result = runfile.run(runfile.load(args.file))
    print(result.summary)
    result.simulation.close()
    return 0


def _resume(directory, steps) -> int:
    from ..simulation import Simulation

    sim = Simulation.resume(directory)
    previous = {}
    record = directory / provenance.METADATA_NAME
    if record.is_file():
        previous = json.loads(record.read_text())
    schedule = sim._schedule if sim._schedule is not None and not sim._schedule.finished else None
    if steps is None and schedule is None:
        wanted = (previous.get("arguments") or {}).get("steps")
        if wanted is None or wanted <= sim.step:
            raise InputError(f"the run in {directory} is at step {sim.step} and has no steps left",
                             next_step="Pass --steps N to run N more.")
        steps = wanted - sim.step
    sim.run(steps=steps)
    sim.save_restart()
    metadata = provenance.collect(sim, source=(previous.get("structure") or {}).get("source"),
                                  repeat=(previous.get("structure") or {}).get("repeat"),
                                  arguments=previous.get("arguments"),
                                  warnings=list(previous.get("warnings") or []) + [
                                      f"resumed at step {sim.step - sim.totals['steps']}"])
    provenance.write(metadata, directory)
    print(report.text(metadata))
    sim.close()
    return 0
