"""``loupmd cache list | size | prune``."""
from __future__ import annotations

import time

from .. import cache


def add_parser(sub):
    parser = sub.add_parser("cache", help="list, measure or prune the cache",
                            description="LoupMD's cache: downloaded models, exported bundles, GEMM plans, gate "
                                        "references and locally built libraries.")
    actions = parser.add_subparsers(dest="action", metavar="ACTION")
    listing = actions.add_parser("list", help="every cached file with its size and last use")
    listing.add_argument("--kind", action="append", choices=cache.KINDS, help="only this kind (repeatable)")
    listing.set_defaults(run=run_list)
    size = actions.add_parser("size", help="bytes per kind")
    size.set_defaults(run=run_size)
    prune = actions.add_parser("prune", help="remove files by age or to fit a size",
                               description="Removes bundles, plans and gate references (what LoupMD can make "
                                           "again); models and libraries only when named with --kind.")
    prune.add_argument("--older-than", type=float, metavar="DAYS", help="remove what was not used for DAYS days")
    prune.add_argument("--max-size", metavar="SIZE", help="then remove the least recently used files until the "
                                                          "kinds fit SIZE (500M, 1G, ...)")
    prune.add_argument("--kind", action="append", choices=cache.KINDS, help="prune this kind (repeatable; default: "
                                                                            "bundles, plans, gate_refs)")
    prune.add_argument("--dry-run", action="store_true", help="show what would be removed")
    prune.set_defaults(run=run_prune)
    parser.set_defaults(run=lambda args: _usage(parser))


def _usage(parser) -> int:
    parser.print_usage()
    return 2


def _human(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GiB"


def run_list(args) -> int:
    found = cache.entries(args.kind)
    print(f"cache root: {cache.cache_root()}")
    now = time.time()
    for entry in found:
        print(f"{entry.kind:9s}  {_human(entry.size):>10s}  {(now - entry.used) / 86400.0:6.1f} d  {entry.path}")
    print(f"{len(found)} files, {_human(sum(e.size for e in found))}")
    return 0


def run_size(args) -> int:
    totals = cache.sizes()
    print(f"cache root: {cache.cache_root()}")
    for kind in cache.KINDS:
        print(f"{kind:9s}  {_human(totals[kind]):>10s}")
    print(f"{'total':9s}  {_human(totals['total']):>10s}")
    return 0


def run_prune(args) -> int:
    max_size = cache.parse_size(args.max_size) if args.max_size is not None else None
    removed = cache.prune(args.older_than, max_size, kinds=tuple(args.kind) if args.kind else cache.PRUNABLE,
                          dry_run=args.dry_run)
    verb = "would remove" if args.dry_run else "removed"
    for entry in removed:
        print(f"{verb} {entry.kind:9s} {_human(entry.size):>10s}  {entry.path}")
    print(f"{verb} {len(removed)} files, {_human(sum(e.size for e in removed))}")
    return 0
