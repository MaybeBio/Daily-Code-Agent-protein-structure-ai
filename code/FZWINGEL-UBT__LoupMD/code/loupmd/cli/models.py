"""``loupmd models``: the label table, and ``--download LABEL``."""
from __future__ import annotations

from .. import models
from ..errors import InputError


def add_parser(sub):
    parser = sub.add_parser("models", help="list the model labels; --download LABEL fetches one",
                            description="The model labels LoupMD knows, with the released file, head, training "
                                        "functional, licence and SHA-256 of each.")
    parser.add_argument("--download", metavar="LABEL", help="download the label's checkpoint into the cache "
                                                              "(checked against the table's SHA-256)")
    parser.add_argument("--long", action="store_true", help="full SHA-256, URL and the source of each functional")
    parser.set_defaults(run=run)


def _found(entry):
    """Where the label's file is now, or "-"."""
    try:
        return str(models.resolve_checkpoint(entry.label).path)
    except InputError:
        return "-"


def run(args) -> int:
    if args.download:
        entry = models.find(args.download)
        if entry is None:
            raise InputError(f"{args.download!r} is not a model label",
                             next_step=f"Labels: {', '.join(models.LABELS)}.")
        resolved, digest, trust = models.trusted_checkpoint(entry.label, download=True)
        print(f"{entry.label}: {resolved.path}")
        print(f"  origin {resolved.origin}, SHA-256 {digest} ({'matches the table' if trust == 'label' else trust})")
        print(f"  licence: {models.LICENCE_TEXT[entry.licence]}")
        return 0
    rows = []
    for entry in models.LABELS.values():
        ckpt = entry.checkpoint
        head = entry.head or (ckpt.heads[0] if ckpt.heads else "-")
        sha = ckpt.sha256 if args.long else ckpt.sha256[:12]
        rows.append((entry.label, ckpt.file_name, head, entry.functional or "unknown", entry.licence, sha,
                     _found(entry)))
    header = ("label", "file", "head", "functional", "licence", "SHA-256" if args.long else "SHA-256 (12)", "found at")
    widths = [max(len(str(r[i])) for r in rows + [header]) for i in range(len(header))]
    line = "  ".join(f"{{:{w}}}" for w in widths)
    print(line.format(*header))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(line.format(*row))
    print()
    print(f"{len(rows)} labels. A multi-head checkpoint takes other heads by name: "
          + "; ".join(f"{alias} (heads: {', '.join(models.CHECKPOINTS[name].heads)})"
                      for alias, name in models.ALIASES.items() if len(models.CHECKPOINTS[name].heads) > 1) + ".")
    for code, text in models.LICENCE_TEXT.items():
        print(f"{code}: {text}")
    if args.long:
        print()
        for entry in models.LABELS.values():
            print(f"{entry.label}: {entry.checkpoint.url}")
            print(f"  functional: {entry.functional_source}")
    return 0
