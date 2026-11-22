#!/usr/bin/env python3
"""Vendor the parts of FastMACE that LoupMD's exporters and kernel generator use (PLAN.md S2-T03).

    python tools/release/vendor_fastmace.py /path/to/FastMACE [--check]

Writes ``loupmd/export/_vendor/fastmace/``: for every FastMACE module the exporters import, the top-level
definitions they use and whatever those refer to in the same module, with the original text of each kept
statement. Imports of other FastMACE modules at module level are followed with the names they bring in; imports
inside functions are followed only for the modules of ``FOLLOW_LAZY`` (those an export really reaches) and
otherwise point at a module that is not vendored, so reaching one fails loudly. A top-level statement that sets
an attribute or an item of a kept name (``factor.log = []``) is kept with it. ``--check`` writes nothing and
exits 1 if the vendored tree differs from what this FastMACE checkout would give.

The seeds below are what ``loupmd/export/*.py`` and ``codegen/gen_generic.py`` name. After changing them, or
moving to another FastMACE commit, run the byte-identity check (``tools/release/export_identity.sh``).
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET = REPO / "loupmd" / "export" / "_vendor"
PREFIX = "loupmd.export._vendor.fastmace"

SEEDS = {
    "fastmace.kernels.cuda.sc_factored": {"factor", "fold_weights", "_emit_node", "_expr", "_literal", "Program"},
    "fastmace.kernels.cuda.sc_generated": {"merged_terms", "shape_of"},
    "fastmace.kernels.triton.compose_skip": {"composed"},
    "fastmace.rewrites.radial": {"R_LO", "R_PHYSICAL", "CERTIFY_POINTS", "fit", "certify", "_GenericChain",
                                 "power_basis"},
    "fastmace.rewrites.radial.spline": {"fit", "coefficients", "locate", "grid_knots", "_Scorer"},
    "fastmace.rewrites.generic.modules": {"fc_last_weight", "fc_split", "species_skip"},
    "fastmace.rewrites.linear.modules": {"block_linear", "raw_blocks"},
}
# Modules imported inside functions that an export reaches, besides the seeded ones, with the names taken from
# each. The other names of such an import statement belong to paths an export does not take (the exporters run on
# the CPU); the vendored text binds them to None.
FOLLOW_LAZY = {
    "fastmace.kernels.triton.radial_table": {"evaluate"},     # the table's reference evaluation in torch
}


class Module:
    def __init__(self, root: Path, name: str):
        base = root.joinpath(*name.split("."))
        self.is_package = (base / "__init__.py").is_file()
        self.file = base / "__init__.py" if self.is_package else base.with_suffix(".py")
        self.name = name
        self.package = name if self.is_package else name.rsplit(".", 1)[0]
        self.text = self.file.read_text(encoding="utf-8")
        self.lines = self.text.splitlines(keepends=True)
        self.tree = ast.parse(self.text)
        self.wanted: set = set()
        self.defs = {}           # name -> index of the top-level statement that binds it
        self.imports = {}        # bound name -> (imported module or None, imported name or None, statement index)
        self.attached = {}       # name -> indices of top-level statements that set an attribute or item of it
        for index, node in enumerate(self.tree.body):
            for name_ in _bound(node):
                self.defs.setdefault(name_, index)
            for name_ in _attached_to(node):
                self.attached.setdefault(name_, []).append(index)
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    self.imports[bound] = (*self.resolve(node, alias), index)

    def resolve(self, node, alias):
        """``(fastmace module, name in it or None)`` an import alias refers to; ``(None, None)`` for other imports."""
        if isinstance(node, ast.Import):
            return (alias.name, None) if alias.name.startswith("fastmace") else (None, None)
        if node.level:
            parts = self.package.split(".")
            parts = parts[: len(parts) - (node.level - 1)]
            stem = ".".join(parts + ([node.module] if node.module else []))
        else:
            stem = node.module or ""
        if not stem.startswith("fastmace"):
            return None, None
        return stem, alias.name


def _bound(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]
    return []


def _attached_to(node):
    """The names whose attribute or item a top-level statement sets or whose method it calls (``f.log = []``,
    ``TABLE[key] = value``, ``registry.update(...)``)."""
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        targets = [node.value.func]
    else:
        return []
    names = []
    for target in targets:
        while isinstance(target, (ast.Attribute, ast.Subscript)):
            target = target.value
            if isinstance(target, ast.Name):
                names.append(target.id)
    return names


def _names_used(node):
    """Every name a statement reads, and ``alias.attribute`` pairs (for module aliases)."""
    names, attributes = set(), set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
            attributes.add((child.value.id, child.attr))
    return names, attributes


def is_module(root: Path, name: str) -> bool:
    base = root.joinpath(*name.split("."))
    return (base / "__init__.py").is_file() or base.with_suffix(".py").is_file()


def shake(root: Path):
    """``{module name: (Module, kept statement indices)}`` for the closure of SEEDS."""
    modules, kept = {}, {}
    pending = [(name, set(seeds)) for name, seeds in SEEDS.items()]
    while pending:
        name, seeds = pending.pop()
        module = modules.get(name)
        if module is None:
            module = modules[name] = Module(root, name)
            kept[name] = set()
        new = seeds - module.wanted
        if not new and kept[name]:
            continue
        module.wanted |= new
        frontier = list(new)
        while frontier:
            wanted = frontier.pop()
            if wanted in module.imports:
                target, imported, index = module.imports[wanted]
                kept[name].add(index)
                if target is not None:
                    full = f"{target}.{imported}" if imported else target
                    if imported and is_module(root, full):
                        pending.append((full, set()))                 # a module brought in by name
                    elif imported:
                        pending.append((target, {imported}))
                    else:
                        pending.append((target, set()))
                continue
            index = module.defs.get(wanted)
            if index is None:
                continue
            indices = [i for i in [index] + module.attached.get(wanted, []) if i not in kept[name]]
            if not indices:
                continue
            kept[name].update(indices)
            names, attributes, nested = set(), set(), []
            for i in indices:
                node = module.tree.body[i]
                used_names, used_attributes = _names_used(node)
                names |= used_names
                attributes |= used_attributes
                nested.append(node)
            for used in names:
                if (used in module.defs or used in module.imports) and used not in module.wanted:
                    module.wanted.add(used)
                    frontier.append(used)
            for alias, attribute in attributes:          # alias.attribute on an imported FastMACE module
                if alias in module.imports:
                    target, imported, _ = module.imports[alias]
                    if target is None:
                        continue
                    full = f"{target}.{imported}" if imported else target
                    if is_module(root, full):
                        pending.append((full, {attribute}))
            follow = set(FOLLOW_LAZY) | set(SEEDS)
            for node in nested:                          # imports inside the kept definitions
                for child in ast.walk(node):
                    if child is node or not isinstance(child, (ast.Import, ast.ImportFrom)):
                        continue
                    for alias in child.names:
                        target, imported = module.resolve(child, alias)
                        if target is None:
                            continue
                        full = f"{target}.{imported}" if imported else target
                        bound = alias.asname or alias.name.split(".")[0]
                        if is_module(root, full) and full in follow:     # a module under a local name
                            pending.append((full, {attr for base, attr in attributes if base == bound}))
                        elif target in follow and imported:
                            if target not in FOLLOW_LAZY or imported in FOLLOW_LAZY[target]:
                                pending.append((target, {imported}))
    return modules, kept


def render(module: Module, indices, commit: str) -> str:
    out = [f"# SPDX-License-Identifier: MIT\n# Vendored from FastMACE {commit}: {module.file.as_posix().split('/fastmace/', 1)[-1]}"
           f" (fastmace/), trimmed to what LoupMD's\n# exporters use by tools/release/vendor_fastmace.py. Do not edit: "
           "change FastMACE and vendor again.\n"]
    body = module.tree.body
    first = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        out.append("".join(module.lines[body[0].lineno - 1: body[0].end_lineno]))
        first = 1
    for index, node in enumerate(body):
        future = isinstance(node, ast.ImportFrom) and node.module == "__future__"
        if index < first or not (index in indices or future):
            continue
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]) - 1
        while start > 0 and module.lines[start - 1].lstrip().startswith("#"):     # the comment block above it
            start -= 1
        gap = "\n\n" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else "\n"
        lines = list(module.lines[start: node.end_lineno])
        partial = [child for child in ast.walk(node) if isinstance(child, ast.ImportFrom) and child is not node
                   and module.resolve(child, child.names[0])[0] in FOLLOW_LAZY]
        for child in sorted(partial, key=lambda c: -c.lineno):      # bottom up: line numbers above stay valid
            target = module.resolve(child, child.names[0])[0]
            taken = [a for a in child.names if a.name in FOLLOW_LAZY[target]]
            dropped = [a.asname or a.name for a in child.names if a.name not in FOLLOW_LAZY[target]]
            indent = " " * child.col_offset
            new = [f"{indent}from {target} import "
                   + ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in taken) + "\n"]
            if dropped:
                new.append(f"{indent}{' = '.join(dropped)} = None  # not vendored: a path the exporters do not take\n")
            lines[child.lineno - 1 - start: child.end_lineno - start] = new
        out.append(gap + "".join(lines))
    text = "".join(out)
    text = re.sub(r"(?m)^(\s*)(from|import) fastmace\b", rf"\1\2 {PREFIX}", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text if text.endswith("\n") else text + "\n"


def build(root: Path) -> dict:
    """``{path relative to _vendor: text}`` of the vendored tree."""
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()
    modules, kept = shake(root)
    files = {"VERSION": f"FastMACE {commit}\nMIT License, Copyright (c) 2026 Fabian Zwingel (FastMACE's LICENSE).\n"
                        "Vendored by tools/release/vendor_fastmace.py; the modules and the names kept of each:\n"
                        + "".join(f"  {name}: {', '.join(sorted(modules[name].wanted)) or '(the package only)'}\n"
                                  for name in sorted(modules))}
    for name, module in modules.items():
        relative = Path(*name.split("."))
        path = relative / "__init__.py" if module.is_package else relative.with_suffix(".py")
        files[path.as_posix()] = render(module, kept[name], commit)
        for depth in range(1, len(relative.parts)):                  # empty packages above it
            files.setdefault((Path(*relative.parts[:depth]) / "__init__.py").as_posix(), "")
    files.setdefault("__init__.py", "")
    return files


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("fastmace", type=Path, help="a FastMACE checkout")
    parser.add_argument("--check", action="store_true", help="compare only; exit 1 on a difference")
    args = parser.parse_args(argv)
    files = build(args.fastmace)
    current = {p.relative_to(TARGET).as_posix(): p.read_text(encoding="utf-8")
               for p in TARGET.rglob("*") if p.is_file() and "__pycache__" not in p.parts} if TARGET.is_dir() else {}
    if args.check:
        different = sorted(set(files) ^ set(current)) + sorted(k for k in files if k in current and files[k] != current[k])
        for name in different:
            print(f"differs: {name}")
        return 1 if different else 0
    for stale in set(current) - set(files):
        (TARGET / stale).unlink()
    for name, text in files.items():
        path = TARGET / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    lines = sum(text.count("\n") for text in files.values())
    print(f"{len(files)} files, {lines} lines in {TARGET.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
