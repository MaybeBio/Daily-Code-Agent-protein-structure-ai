"""The command-line reference page (PLAN.md S7-T01): generated from the parser, up to date, every flag listed."""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _generator():
    spec = importlib.util.spec_from_file_location("gen_cli_reference", ROOT / "tools" / "dev" / "gen_cli_reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _all_flags(parser, path=("loupmd",)):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from _all_flags(sub, path + (name,))
        elif not isinstance(action, argparse._HelpAction):      # -h / --help: every command, said once at the top
            for flag in action.option_strings:
                yield path, flag


def test_the_page_is_what_the_parser_gives():
    gen = _generator()
    assert gen.PAGE.read_text(encoding="utf-8") == gen.render(), "run python tools/dev/gen_cli_reference.py"


def test_every_flag_of_every_command_is_in_the_reference():
    from loupmd.cli import build_parser

    page = (ROOT / "docs" / "reference" / "cli.md").read_text(encoding="utf-8")
    sections = {}
    current = None
    for line in page.splitlines():
        if line.startswith("#") and "`" in line:
            current = line.split("`")[1]
            sections[current] = []
        elif current:
            sections[current].append(line)
    missing = [(" ".join(p), f) for p, f in _all_flags(build_parser())
               if f"`{f}`" not in "\n".join(sections.get(" ".join(p), []))]
    assert not missing, missing
