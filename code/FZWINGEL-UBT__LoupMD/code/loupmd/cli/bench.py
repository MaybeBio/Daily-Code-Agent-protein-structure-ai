"""``loupmd bench``: time LoupMD on this machine."""
from __future__ import annotations

import sys

from .. import bench as _bench


def add_parser(sub):
    parser = sub.add_parser(
        "bench", help="time MD steps on this machine",
        description="Times Langevin MD (300 K, 1 fs, skin 0.5 A, friction 0.01/fs) with a model on the systems of a "
                    "suite and prints ms/step, us per atom-step and ns/day. The GPU must be idle.")
    parser.add_argument("--model", required=True, metavar="MODEL", help="a label (see `loupmd models`), a checkpoint "
                                                                       "path or a URL")
    parser.add_argument("--head", help="the head of a multi-head model")
    parser.add_argument("--checkpoint", metavar="PATH", help="the file of a label, when it is not in LOUPMD_MODELS")
    parser.add_argument("--sha256", metavar="HEX", help="the stated hash of a file that is not in the label table")
    parser.add_argument("--trusted", action="store_true", help="load a file outside the label table without a hash")
    parser.add_argument("--download", action="store_true", help="download a label's checkpoint if it is missing")
    parser.add_argument("--suite", choices=_bench.suites.SUITE_NAMES, default="standard",
                        help="standard: NbCl5 3x3x3 and SrTiO3 10x10x10 (default); quick: one system, under a "
                             "minute; families: one system for the model's family")
    parser.add_argument("--quick", action="store_true", help="short for --suite quick")
    parser.add_argument("--system", action="append", metavar="NAME", choices=tuple(_bench.suites.SYSTEMS),
                        help="time this system instead of a suite's (repeatable): " +
                             ", ".join(_bench.suites.SYSTEMS))
    parser.add_argument("--protocol", choices=tuple(_bench.PROTOCOLS),
                        help="standard: 100 warm-up steps, median of 6 x 256; fastmace: 300, 4 x 300; quick: 50, "
                             "2 x 128 (default: the suite's)")
    parser.add_argument("--device", type=int, default=0, metavar="N", help="the GPU index (default 0)")
    parser.add_argument("--force", action="store_true", help="time even if the GPU is in use; the record says so")
    parser.add_argument("--compare", action="append", choices=tuple(_bench.compare.ENGINES), default=[],
                        help="also time another engine on the same structure (mace: mace-torch's ASE calculator)")
    parser.add_argument("--ab", nargs="+", metavar="SIDE", help="development: run the benchmark once per side in "
                        "fresh processes in the order a b b a; a side is ENV=VAL[,ENV=VAL...] or - for no change")
    parser.add_argument("--json", metavar="FILE", help="write the record (loupmd.bench/1) to FILE, or - for stdout")
    parser.set_defaults(run=run)


def _passed_on(args, suite):
    """The arguments a side's process gets: everything that chooses what is timed."""
    argv = ["--model", args.model, "--suite", suite]
    for flag, value in (("--head", args.head), ("--checkpoint", args.checkpoint), ("--sha256", args.sha256),
                        ("--protocol", args.protocol)):
        if value:
            argv += [flag, value]
    for name in args.system or []:
        argv += ["--system", name]
    if args.device:
        argv += ["--device", str(args.device)]
    for flag, value in (("--trusted", args.trusted), ("--download", args.download), ("--force", args.force)):
        if value:
            argv.append(flag)
    return argv


def _describe(record) -> str:
    gpu, model, proto = record["gpu"], record["model"], record["protocol"]
    name = model["label"] or model["file"]
    head = f", head {model['head']}" if model["head"] else ""
    return "\n".join([
        f"loupmd {record['loupmd']}, library {record['library']}",
        f"GPU {record['device']}: {gpu['name']}, compute capability {gpu['compute_capability']}, driver "
        f"{gpu['driver']}",
        f"model: {name} ({model['file']}, SHA-256 {model['sha256'][:16]}...{head})",
        f"suite {record['suite']}, protocol {proto['name']}: Langevin {proto['temperature_K']:g} K, "
        f"{proto['timestep_fs']:g} fs, skin {proto['skin_A']:g} A, friction {proto['friction_per_fs']:g}/fs, "
        f"{proto['warmup_steps']} warm-up steps, median of {proto['blocks']} x {proto['block_steps']} steps",
    ])


def run(args) -> int:
    suite = "quick" if args.quick else args.suite
    out = sys.stderr if args.json == "-" else sys.stdout        # with --json - only the record goes to stdout
    if args.ab:
        result = _bench.run_ab(args.ab, _passed_on(args, suite))
        print(_bench.format_ab(result), file=out)
        if args.json:
            _bench.write_record(result, args.json)
        return 0
    record, rows = _bench.run_suite(args.model, suite=suite, protocol_name=args.protocol, head=args.head,
                                    checkpoint=args.checkpoint, sha256=args.sha256, trusted=args.trusted,
                                    download=args.download, systems=args.system, device=args.device, force=args.force,
                                    compare_with=tuple(args.compare))
    stored = _bench.reference.lookup(record)
    if stored:
        record["reference"] = stored
    print(_describe(record), file=out)
    print(_bench.format_table(rows, {system: entry["ms_per_step"] for system, entry in stored.items()}), file=out)
    for system, entry in stored.items():
        print(f"reference for {system}: {entry['ms_per_step']:.3f} ms/step, measured {entry['measured']} on the same "
              f"GPU model with library {entry['library']}", file=out)
    if record.get("comparisons"):
        print(_bench.compare.format_comparisons(record["comparisons"]), file=out)
    if record["other_gpu_processes"] or (record["gpu_utilisation_percent"] or 0) > _bench.BUSY_PERCENT:
        listing = ", ".join(f"{p['name']} (pid {p['pid']}, {p['memory']})" for p in record["other_gpu_processes"])
        print(f"warning: the GPU was in use ({listing or 'no process listed'}; "
              f"{record['gpu_utilisation_percent']} % utilised before the run): these timings are not clean",
              file=sys.stderr)
    if args.json:
        _bench.write_record(record, args.json)
    unstable = [r.system for r in rows if r.status != "ok"]
    if unstable:
        print(f"error: {', '.join(unstable)}: the temperature is not finite, so this is not a valid timing",
              file=sys.stderr)
        return 1
    return 0
