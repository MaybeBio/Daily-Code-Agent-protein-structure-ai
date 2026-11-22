"""Save the native-unit study's run folder to its private Hub dataset, and free the machine's disk of files confirmed there.

From tree/projects/representation/plm_interpretability of a shipped run, in the project's image (the launcher's HF_TOKEN writes):
    bash scripts/in_container.sh python scripts/units_hub.py --root /units --repo <owner>/<name>
    bash scripts/in_container.sh python scripts/units_hub.py --root /units --repo <owner>/<name> --path passes/e4/maxima --free
It sends RUN/PATH, the whole run when no path is given, with `foundry.downloads.hub.upload_resuming`, leaving out the
pinned release copy (`source/`, named by its revision in the preregistration), each upload's own progress folder and
the download caches the Hub's client keeps beside downloaded data, which its upload never sends.
Then `foundry.downloads.hub.copies.hub_copy_differences` reads the repository's listing back and compares every file sent
with its Hub copy by digest. `--free` deletes PATH's local files once none differs, for maxima that no later stage reads.
A receipt of each upload goes to RUN/hub/. `--restore` brings a freed PATH, a file or a folder, back from the Hub and
checks each copy by digest the same way, for a file a later stage turns out to read:
    bash scripts/in_container.sh python scripts/units_hub.py --root /units --repo <owner>/<name> --path <path> --restore
`--check` sends nothing and names every file of RUN/PATH the Hub lacks or holds differently, before a machine is given up:
    bash scripts/in_container.sh python scripts/units_hub.py --root /units --repo <owner>/<name> --check
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import time

from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download

from foundry.downloads.hub.copies import hub_copy_differences
from foundry.downloads.hub.rate_limit import hub_call, upload_resuming


# The release copy; the upload's progress; the download caches beside downloaded data (`concepts/data/.cache`), which
# the Hub's upload never sends; the queues' clocks. A `*` here also matches across folders, as `fnmatch` reads it.
LEFT_OUT = ("source/**", ".cache/**", "*/.cache/*", ".*_marker")
DIGEST_WORKERS = 16


def local_files(root: Path, path: str | None) -> list[Path]:
    """Every file of RUN/PATH the upload sends."""
    base = root / path if path else root
    return [file for file in sorted(base.rglob("*"))
            if file.is_file() and not any(fnmatch.fnmatch(file.relative_to(root).as_posix(), pattern) for pattern in LEFT_OUT)]


def _log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def restore(api: HfApi, repo: str, root: Path, path: str) -> None:
    """Download RUN/PATH, a file or every file under a folder, from the Hub into the run, then compare each local copy
    with the Hub's by digest."""
    started = time.perf_counter()
    names = [name for name in hub_call(api.list_repo_files, repo, repo_type="dataset")
             if name == path or name.startswith(f"{path}/")]
    if not names:
        raise SystemExit(f"{repo} holds no file at or under {path}.")
    for name in names:
        hub_call(hf_hub_download, repo, name, repo_type="dataset", local_dir=root)
    files = [root / name for name in names]
    differences = hub_call(hub_copy_differences, api, repo, root, files, workers=DIGEST_WORKERS)
    if differences:
        raise SystemExit(f"{len(differences)} restored files differ from the Hub's: {differences[:5]}")
    size = sum(file.stat().st_size for file in files)
    _log(f"restored {len(files)} files of {path} from {repo}, {size / 1e9:.1f} GB, in {time.perf_counter() - started:.0f} s")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo", required=True, help="the private dataset repository, <owner>/<name>")
    parser.add_argument("--path", help="a folder of the run, relative to its root; the whole run when left out")
    parser.add_argument("--free", action="store_true", help="delete PATH's local files once every one is on the Hub")
    parser.add_argument("--restore", action="store_true", help="download PATH from the Hub into the run instead")
    parser.add_argument("--check", action="store_true",
                        help="send nothing: name every file of PATH the Hub lacks or holds differently, by digest")
    options = parser.parse_args(argv)
    if options.check:
        if options.free or options.restore:
            parser.error("--check takes no --free and no --restore")
        files = local_files(options.root, options.path)
        differences = hub_call(hub_copy_differences, HfApi(), options.repo, options.root, files, workers=DIGEST_WORKERS)
        size = sum(file.stat().st_size for file in files)
        for difference in differences:
            print(difference, flush=True)
        _log(f"{options.repo}: {len(files)} files of {options.path or 'the run'}, {size / 1e9:.1f} GB, "
             f"{len(differences)} differences")
        if differences:
            raise SystemExit(f"{len(differences)} files are missing on the Hub or differ there.")
        return
    if options.free and not options.path:
        parser.error("--free needs --path: the whole run is never freed")
    if options.restore:
        if options.free or not options.path:
            parser.error("--restore needs --path and takes no --free")
        restore(HfApi(), options.repo, options.root, options.path)
        return
    started = time.perf_counter()
    files = local_files(options.root, options.path)
    if not files:
        raise SystemExit(f"{options.root / (options.path or '')} holds no file to send.")
    size = sum(file.stat().st_size for file in files)
    api = HfApi()
    hub_call(api.create_repo, options.repo, repo_type="dataset", private=True, exist_ok=True)
    upload_resuming(api, repo_id=options.repo, folder_path=options.root, repo_type="dataset",
                    allow_patterns=[f"{options.path}/**"] if options.path else None, ignore_patterns=list(LEFT_OUT))
    differences = hub_call(hub_copy_differences, api, options.repo, options.root, files, workers=DIGEST_WORKERS)
    receipt = {"repo": options.repo, "path": options.path,
               "revision": hub_call(api.repo_info, options.repo, repo_type="dataset").sha, "files": len(files),
               "bytes": size, "differences": differences[:20], "freed": bool(options.free and not differences),
               "seconds": time.perf_counter() - started}
    folder = options.root / "hub"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{(options.path or 'run').replace('/', '__')}.json").write_text(json.dumps(receipt, indent=2) + "\n",
                                                                              encoding="utf-8")
    _log(f"{options.repo}@{receipt['revision'][:8]}: {len(files)} files of {options.path or 'the run'}, {size / 1e9:.1f} GB, "
         f"{len(differences)} differences")
    if differences:
        raise SystemExit(f"{len(differences)} files are missing on the Hub or differ there: {differences[:5]}")
    if options.free:
        for file in files:
            file.unlink()
        _log(f"freed {size / 1e9:.1f} GB under {options.root / options.path}")


if __name__ == "__main__":
    main()
