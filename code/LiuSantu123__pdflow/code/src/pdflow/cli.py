from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import aggregate, campaign, predict
from . import setup as setup_mod
from .config import (
    EXAMPLE_CONFIG,
    ConfigError,
    get,
    load_config,
    require_executable,
    run_command,
    tool_env,
)


def _predictor_names(spec: dict, cfg: dict, override: str | None) -> list[str]:
    if override:
        return [item.strip() for item in override.split(",") if item.strip()]
    configured = get(spec, "score.predictors", None)
    if configured:
        return list(configured)
    default = get(spec, "score.default", None)
    if default:
        return [str(default)]
    return ["af3"]


def _sequence_jobs(root: Path, spec: dict) -> list[predict.Job]:
    layout = campaign.paths(root)
    jobs: list[predict.Job] = []
    for path in sorted(layout["sequences"].glob("*.fasta")):
        if path.name == "all.fasta":
            continue
        jobs.append(
            predict.build_job(
                path,
                spec,
                layout["root"],
                layout["predictions"] / path.stem,
            )
        )
    return jobs


def _setup_values(args: argparse.Namespace) -> dict[str, str]:
    values = setup_mod.default_values()
    for key, attr in (
        ("HOME", "home"),
        ("CONDA_BASE", "conda_base"),
        ("MODEL_ROOT", "model_root"),
        ("KIT_ROOT", "kit_root"),
        ("AF3_ROOT", "af3_root"),
        ("USALIGN", "usalign"),
    ):
        value = getattr(args, attr, None)
        if value:
            values[key] = str(Path(value).expanduser())
    return values


def cmd_setup(args: argparse.Namespace) -> int:
    profile = setup_mod.choose_profile(getattr(args, "profile", None))
    values = _setup_values(args)
    if not getattr(args, "no_input", False) and sys.stdin.isatty():
        values = setup_mod.interactive_values(profile, values)
    destination = Path(args.dest or "backends.yaml")
    try:
        setup_mod.materialize_profile(
            profile, destination, values, force=bool(getattr(args, "force", False))
        )
    except FileExistsError:
        print(f"{destination} already exists; use --force to overwrite")
        return 1
    print(f"wrote {destination} ({profile} profile)")
    print("Next: `pdflow doctor`, then create a campaign with `pdflow new`.")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    return cmd_setup(
        argparse.Namespace(
            profile="native",
            home=None,
            conda_base=None,
            model_root=None,
            kit_root=None,
            af3_root=None,
            usalign=None,
            dest=args.dest,
            force=args.force,
            no_input=True,
        )
    )


def cmd_new(args: argparse.Namespace) -> int:
    root = Path(args.campaign)
    layout = campaign.init_campaign(root)
    if not layout["config"].exists():
        template = Path(__file__).resolve().parents[2] / "config" / "campaign.example.yaml"
        shutil.copyfile(template, layout["config"])
    print(f"campaign ready: {root}")
    print("Next: edit campaign.yaml, put inputs under inputs/, then `pdflow design`.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    problems: list[str] = []
    print(f"config: {cfg.get('_config_path')}")

    def check(label: str, path: str | None, kind: str = "file") -> None:
        if not path:
            problems.append(f"{label}: missing path")
            print(f"[FAIL] {label}: missing path")
            return
        candidate = Path(path).expanduser()
        if kind == "exec":
            ok = candidate.is_file() or shutil.which(str(candidate)) is not None
        elif kind == "dir":
            ok = candidate.is_dir()
        else:
            ok = candidate.is_file()
        print(f"[{'OK' if ok else 'FAIL'}] {label}: {candidate}")
        if not ok:
            problems.append(f"{label}: {candidate}")

    overlay = get(cfg, "predictors.esmfold2_overlay", {}) or {}
    overlay_only = getattr(args, "predictor", None) == "esmfold2_overlay"
    if overlay.get("enabled"):
        repo = Path(str(overlay.get("repo", ""))).expanduser()
        check("esmfold2_overlay.script", str(repo / "scripts" / "esmfold2_50.sh"))
        env = predict.esmfold2_overlay_env(overlay)
        python = env.get("ESMFOLD2_PYTHON", "python")
        check("esmfold2_overlay.python", python, kind="exec")
        for key in ("ESMFOLD2_WEIGHTS", "ESMFOLD2_ESMC"):
            check(f"esmfold2_overlay.{key}", env.get(key), kind="dir")
    elif overlay_only:
        print("[FAIL] esmfold2_overlay is disabled")
        return 1
    else:
        print("[SKIP] esmfold2_overlay disabled")
    if overlay_only:
        if not problems:
            result = run_command(
                [python, "-c", "from esm.models.esmfold2 import EsmFold2Model, ESMFold2InputBuilder"],
                env=env,
            )
            if result.returncode != 0:
                print(result.stderr.rstrip())
                print("[FAIL] esmfold2_overlay Python imports")
                return 1
            print("[OK] esmfold2_overlay Python imports")
        return int(bool(problems))

    usalign = get(cfg, "usalign.binary")
    check("usalign", usalign, kind="exec")
    if usalign and Path(usalign).is_file():
        env = tool_env({}, clean_ld=bool(get(cfg, "usalign.clean_ld_library_path", True)))
        result = run_command([str(usalign)], env=env)
        if result.returncode not in (0, 1) or "US-align" not in (result.stdout or ""):
            problems.append("usalign does not run")
            print("[FAIL] usalign execution")

    rfd4_binary = get(cfg, "design.rfd4.binary")
    if rfd4_binary:
        check("design.rfd4.binary", rfd4_binary, kind="exec")
    else:
        check("design.rfd4.python", get(cfg, "design.rfd4.python"), kind="exec")
    mpnn_command = str(get(cfg, "design.mpnn.command", ""))
    if "/path/to/" in mpnn_command:
        print("[WARN] design.mpnn.command still contains a placeholder path")

    for name in ("af3", "boltz2", "protenix2", "opendde", "mol1", "esmfold2"):
        predictor = get(cfg, f"predictors.{name}", {}) or {}
        if predictor.get("python"):
            check(f"{name}.python", predictor["python"], kind="exec")
        if predictor.get("binary"):
            check(f"{name}.binary", predictor["binary"], kind="exec")
        if predictor.get("script"):
            check(f"{name}.script", predictor["script"])
        launcher = predictor.get("launcher")
        if launcher:
            check(f"{name}.launcher", str(launcher[0]), kind="exec")
            if len(launcher) > 1:
                check(f"{name}.launcher[1]", str(launcher[1]))
        for key in ("model_dir", "cache", "db_dir", "pythonpath"):
            if predictor.get(key):
                check(f"{name}.{key}", predictor[key], kind="dir")
        if predictor.get("weights"):
            check(f"{name}.weights", predictor["weights"])

    tmol_python = get(cfg, "tmol.python")
    check("tmol.python", tmol_python, kind="exec")
    if tmol_python and Path(tmol_python).is_file():
        result = run_command([str(tmol_python), "-c", "import tmol; print(tmol.__version__)"])
        if result.returncode != 0:
            problems.append("tmol import failed")
            print("[FAIL] tmol import")

    if problems:
        print(f"\n{len(problems)} problem(s). Fix backends.yaml and rerun.")
        return 1
    print("\nall backends look usable.")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    root = Path(args.campaign)
    records = campaign.ingest_backbones(
        root,
        designer=args.designer,
        source_dir=Path(args.input),
        method=args.method,
        limit=args.limit,
    )
    print(f"ingested {len(records)} backbone(s) into {root / 'backbones'}")
    return 0


def cmd_design(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    result = campaign.run_design(Path(args.campaign), cfg)
    print(json.dumps(result, indent=2))
    return 0 if result.get("returncode") == 0 else 1


def cmd_seqdesign(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    results = campaign.run_seqdesign(Path(args.campaign), cfg, args.backbone)
    print(f"sequence-designed {len(results)} backbone(s)")
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    root = Path(args.campaign)
    spec = campaign.load_spec(root)
    layout = campaign.paths(root)
    jobs = _sequence_jobs(root, spec)
    if args.sequences:
        wanted = {item.strip() for item in args.sequences.split(",")}
        jobs = [job for job in jobs if job.name in wanted]
    if not jobs:
        print("no sequence files found; run `pdflow design` / `pdflow ingest` first")
        return 1
    names = _predictor_names(spec, cfg, args.predictors)
    results = predict.run_jobs(cfg, jobs, names, layout["predictions"])
    failed = [item for item in results if item.get("returncode") not in (0, None)]
    for item in results:
        status = "skipped" if item.get("skipped") else ("ok" if item.get("returncode") == 0 else "failed")
        print(f"{item['job']:<40} {item['predictor']:<10} {status}")
    return 0 if not failed else 1


def cmd_score(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    summary = aggregate.score_campaign(Path(args.campaign), cfg)
    print(f"scored {len(summary)} design/predictor combinations")
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    result = aggregate.finalize(
        Path(args.campaign), cfg, clean=not args.keep_intermediates
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    root = Path(args.campaign)
    if not args.skip_design:
        result = campaign.run_design(root, cfg)
        if result.get("returncode") != 0:
            print(json.dumps(result, indent=2))
            return 1
    spec = campaign.load_spec(root)
    layout = campaign.paths(root)
    jobs = _sequence_jobs(root, spec)
    names = _predictor_names(spec, cfg, args.predictors)
    results = predict.run_jobs(cfg, jobs, names, layout["predictions"])
    for item in results:
        status = "skipped" if item.get("skipped") else ("ok" if item.get("returncode") == 0 else "failed")
        print(f"{item['job']:<40} {item['predictor']:<10} {status}")
    aggregate.score_campaign(root, cfg)
    archived = aggregate.finalize(root, cfg, clean=not args.keep_intermediates)
    print(json.dumps(archived, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdflow",
        description="Reproducible backbone -> sequence -> structure -> metrics workflow.",
    )
    parser.add_argument("--config", help="path to backends.yaml", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="write a native backends.yaml with detected paths")
    init.add_argument("--dest", default=None)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    setup = sub.add_parser(
        "setup",
        help="first-time configuration wizard (native or Blackwell kit profile)",
    )
    setup.add_argument("--profile", choices=["native", "kit"], default=None)
    setup.add_argument("--home", default=None)
    setup.add_argument("--conda-base", default=None)
    setup.add_argument("--model-root", default=None)
    setup.add_argument("--kit-root", default=None)
    setup.add_argument("--af3-root", default=None)
    setup.add_argument("--usalign", default=None)
    setup.add_argument("--dest", default=None)
    setup.add_argument("--force", action="store_true")
    setup.add_argument("--no-input", action="store_true",
                       help="use detected defaults without prompting")
    setup.set_defaults(func=cmd_setup)

    new = sub.add_parser("new", help="create a campaign directory")
    new.add_argument("--campaign", required=True)
    new.set_defaults(func=cmd_new)

    doctor = sub.add_parser("doctor", help="check all configured backends")
    doctor.add_argument("--predictor", choices=["esmfold2_overlay"],
                        help="check only this optional backend")
    doctor.set_defaults(func=cmd_doctor)

    ingest = sub.add_parser("ingest", help="import final backbones (RFD3/BoltzGen/RFD4)")
    ingest.add_argument("--campaign", required=True)
    ingest.add_argument("--designer", required=True, choices=["rfd4", "rfd3", "boltzgen"])
    ingest.add_argument("--input", required=True)
    ingest.add_argument("--method", default=None)
    ingest.add_argument("--limit", type=int, default=None)
    ingest.set_defaults(func=cmd_ingest)

    design = sub.add_parser("design", help="run the configured design engine")
    design.add_argument("--campaign", required=True)
    design.set_defaults(func=cmd_design)

    seqdesign = sub.add_parser("seqdesign", help="run MPNN on sequence-less backbones")
    seqdesign.add_argument("--campaign", required=True)
    seqdesign.add_argument("--backbone", default=None)
    seqdesign.set_defaults(func=cmd_seqdesign)

    predict_cmd = sub.add_parser("predict", help="run structure predictors")
    predict_cmd.add_argument("--campaign", required=True)
    predict_cmd.add_argument("--predictors", default=None,
                             help="comma-separated; defaults to campaign score.predictors")
    predict_cmd.add_argument("--sequences", default=None)
    predict_cmd.set_defaults(func=cmd_predict)

    score = sub.add_parser("score", help="compute confidence/interface/usalign/tmol metrics")
    score.add_argument("--campaign", required=True)
    score.set_defaults(func=cmd_score)

    finalize = sub.add_parser("finalize", help="keep best structure + full_data.json + CSV")
    finalize.add_argument("--campaign", required=True)
    finalize.add_argument("--keep-intermediates", action="store_true")
    finalize.set_defaults(func=cmd_finalize)

    run = sub.add_parser("run", help="design -> predict -> score -> finalize")
    run.add_argument("--campaign", required=True)
    run.add_argument("--predictors", default=None)
    run.add_argument("--skip-design", action="store_true")
    run.add_argument("--keep-intermediates", action="store_true")
    run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
