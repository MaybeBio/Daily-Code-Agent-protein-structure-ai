#!/usr/bin/env bash
# The release artefacts of one commit (PLAN.md S7-T07). It never uploads.
#
#   tools/release/make_release.sh [REF]          REF: the commit or tag to release (default HEAD)
#
# Writes dist/release-<version>-<commit>/ with
#   loupmd-<version>-src.tar.gz    `git archive` of the commit: the whole source tree (library, generators, tests,
#                                  documentation), which is what builds the library;
#   loupmd-<version>-*.whl         the wheel, built from the same archive in the build container (build_wheel.sh:
#                                  every compute capability, manylinux_2_28);
#   SHA256SUMS                     the SHA-256 of each.
# and runs `twine check --strict` on the wheel inside the build image. No source distribution is made: an sdist
# could not build the CUDA library on the user's machine, so the wheel is the package and the source tarball is the
# source release. Uploading (PyPI, GitHub) is the owner's step (S7-T08) and is not done here.
# Needs git and docker (the build image of tools/release/Dockerfile.wheel); runs in Git Bash on Windows too.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
# Git Bash: with the path conversion off (below) git.exe does not take /d/...; D:/... serves bash, git and docker.
if command -v cygpath > /dev/null 2>&1; then root=$(cygpath -m "$root"); fi
ref=${1:-HEAD}
image=${LOUPMD_WHEEL_IMAGE:-loupmd-wheel-build:cuda13.3-rocky8}
docker=${DOCKER:-docker}
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
native() { if command -v cygpath > /dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

commit=$(git -C "$root" rev-parse --verify "$ref^{commit}")
version=$(git -C "$root" show "$commit:loupmd/__init__.py" | sed -n 's/^__version__ = "\([^"]*\)".*/\1/p')
[ -n "$version" ] || { echo "no __version__ in loupmd/__init__.py of $commit" >&2; exit 1; }
out=$root/dist/release-$version-${commit:0:12}
if [ -e "$out" ]; then
    echo "$out exists: remove it to build this release again" >&2
    exit 1
fi
if [ "$ref" = HEAD ] && [ -n "$(git -C "$root" status --porcelain --untracked-files=no)" ]; then
    echo "note: the working tree has uncommitted changes; the release is $commit as committed"
fi
echo "release $version of $commit"
mkdir -p "$out"

git -C "$root" archive --format=tar.gz --prefix="loupmd-$version/" -o "$out/loupmd-$version-src.tar.gz" "$commit"
LOUPMD_WHEEL_REF=$commit bash "$here/build_wheel.sh" "$out"

wheel=$(cd "$out" && ls loupmd-"$version"-*.whl)
echo "--- twine check --strict $wheel"
"$docker" run --rm -v "$(native "$out"):/dist:ro" "$image" python3.11 -m twine check --strict "/dist/$wheel"

(cd "$out" && sha256sum loupmd-"$version"-src.tar.gz "$wheel" > SHA256SUMS)
echo "--- $out"
ls -l "$out"
cat "$out/SHA256SUMS"
echo "nothing was uploaded"
