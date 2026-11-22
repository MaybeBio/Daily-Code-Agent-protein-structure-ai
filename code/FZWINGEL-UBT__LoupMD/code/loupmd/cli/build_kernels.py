"""``loupmd build-kernels MODEL``: compile the kernels of a model the library was not built with."""
from __future__ import annotations

from .. import kernels, models


def add_parser(sub):
    parser = sub.add_parser(
        "build-kernels", help="compile the kernels of a model the library was not built with (needs nvcc)",
        description="The library has the kernels of the models its release was built from. A model with another "
                    "symmetric contraction needs its own, compiled here with nvcc into a kernel plugin in the "
                    "cache; the engine then finds it by itself. Needs the CUDA toolkit and the export extra.")
    parser.add_argument("model", metavar="MODEL", help="a label (see `loupmd models`) or a checkpoint path")
    parser.add_argument("--checkpoint", metavar="PATH", help="the file of a label, when it is not in LOUPMD_MODELS")
    parser.add_argument("--sha256", metavar="HEX", help="the expected SHA-256 of a file outside the label table")
    parser.add_argument("--trusted", action="store_true", help="load a file outside the label table without a hash")
    parser.add_argument("--arch", metavar="sm_XY", help="the GPU architecture to compile for (default: GPU 0's)")
    parser.add_argument("--force", action="store_true", help="compile even where the library or the cache already "
                                                             "has the kernels")
    parser.set_defaults(run=run)


def run(args) -> int:
    # The generator unpickles the checkpoint, so the trust rule of every other entry point applies (PLAN.md section 2).
    resolved, _, _ = models.trusted_checkpoint(args.model, checkpoint=args.checkpoint, sha256=args.sha256,
                                               trusted=args.trusted)
    path = resolved.path
    results = kernels.build_plugins(path, arch=args.arch, force=args.force)
    built = [signature for signature, _, was_built in results if was_built]
    if built:
        print(f"built {len(built)} kernel plugin{'s' if len(built) > 1 else ''} in {kernels.plugin_directory()}; "
              f"{path.name} now loads as any other model")
    else:
        print(f"nothing to build: every kernel of {path.name} is there")
    return 0
