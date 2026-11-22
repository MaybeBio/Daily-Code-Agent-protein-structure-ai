"""Write ``docs/reference/cli.md`` from the ``loupmd`` parser (PLAN.md S7-T01: every CLI flag in the reference).

    python tools/dev/gen_cli_reference.py            # write the page
    python tools/dev/gen_cli_reference.py --check    # exit 1 when the page is not what the parser gives

``tests/cpu/test_cli_reference.py`` runs the check.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "reference" / "cli.md"

HEADER = """# Command-line reference

Generated from the `loupmd` parser by `tools/dev/gen_cli_reference.py`; do not edit by hand. Every command also
prints this with `--help`.

Exit codes: 0 success, 1 a LoupMD error (its message is printed without a traceback unless `--debug` is given),
2 a usage error.
"""


def _subparsers(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {c.dest: c.help for c in action._choices_actions}
            for name, sub in action.choices.items():
                yield name, sub, helps.get(name)


def _option_rows(parser):
    rows = []
    for action in parser._actions:
        if isinstance(action, (argparse._SubParsersAction, argparse._HelpAction)):
            continue
        if action.option_strings:
            names = ", ".join(f"`{s}`" for s in action.option_strings)
            if action.nargs != 0 and action.metavar is not None:
                meta = " ".join(action.metavar) if isinstance(action.metavar, tuple) else action.metavar
                names += f" `{meta}`"
            elif action.nargs != 0 and not isinstance(action, (argparse._StoreTrueAction,
                                                                argparse._StoreFalseAction,
                                                                argparse._VersionAction)):
                names += f" `{action.dest.upper()}`"
        else:
            names = f"`{action.metavar or action.dest}`"
        text = (action.help or "").replace("%(default)s", str(action.default)).replace("%%", "%")
        if action.choices and not isinstance(action, argparse._SubParsersAction):
            text += f" (one of: {', '.join(str(c) for c in action.choices)})"
        rows.append(f"| {names} | {text.replace('|', '/')} |")
    return rows


def _section(path, parser, help_text, level):
    out = [f"{'#' * level} `{' '.join(path)}`", ""]
    desc = parser.description or help_text
    if desc:
        out += [desc, ""]
    out += ["```text", parser.format_usage().strip().replace("usage: ", ""), "```", ""]
    rows = _option_rows(parser)
    if rows:
        out += ["| Argument | Meaning |", "| --- | --- |"] + rows + [""]
    for name, sub, h in _subparsers(parser):
        out += _section(path + [name], sub, h, min(level + 1, 4))
    return out


def render() -> str:
    sys.path.insert(0, str(ROOT))
    import os

    from loupmd.cli import build_parser

    saved = os.environ.get("COLUMNS")
    os.environ["COLUMNS"] = "100"                   # a fixed usage width, whatever the terminal
    try:
        parser = build_parser()
        parser.prog = "loupmd"
        lines = [HEADER] + _section(["loupmd"], parser, None, 2)
    finally:
        if saved is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = saved
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    text = render()
    if check:
        if not PAGE.exists() or PAGE.read_text(encoding="utf-8") != text:
            print(f"{PAGE} is out of date: run python tools/dev/gen_cli_reference.py", file=sys.stderr)
            return 1
        return 0
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {PAGE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
