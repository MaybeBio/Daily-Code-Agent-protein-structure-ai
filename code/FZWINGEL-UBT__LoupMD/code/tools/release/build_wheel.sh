#!/usr/bin/env bash
# The LoupMD wheel (PLAN.md S2-T02): one library for compute capability 8.0, 8.6, 8.9, 9.0, 10.0 and 12.0, built
# in a CUDA 13.3 image on Rocky Linux 8 (glibc 2.28), tagged py3-none-manylinux_2_28_x86_64.
#
#   tools/release/build_wheel.sh [OUT_DIR]          the wheel lands in OUT_DIR (default: dist/)
#
# The tree that is built is `git archive` of a commit: nothing uncommitted is in the wheel.
#   LOUPMD_WHEEL_REF     the commit (default HEAD)
#   LOUPMD_WHEEL_IMAGE   the build image's name (default loupmd-wheel-build:cuda13.3-rocky8; built on first use from
#                        tools/release/Dockerfile.wheel, about 10 GB)
#   LOUPMD_WHEEL_ARCHS   the compute capabilities, for a quick build (for example "89 120"; default: all six)
#   DOCKER               the docker command (default docker)
# Needs docker and git; neither a GPU nor a CUDA toolkit on the host. Runs in Git Bash on Windows too.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
# Git Bash: with the path conversion off (below) git.exe does not take /d/...; D:/... serves bash, git and docker.
if command -v cygpath > /dev/null 2>&1; then root=$(cygpath -m "$root"); fi
out=${1:-$root/dist}
ref=${LOUPMD_WHEEL_REF:-HEAD}
image=${LOUPMD_WHEEL_IMAGE:-loupmd-wheel-build:cuda13.3-rocky8}
docker=${DOCKER:-docker}

# Git Bash rewrites arguments that look like paths; the container's paths must stay as they are, and the host's
# paths go to docker in the host's own form.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
native() { if command -v cygpath > /dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

commit=$(git -C "$root" rev-parse --verify "$ref^{commit}")
echo "building the wheel of $commit"
"$docker" build -q -t "$image" -f "$(native "$here/Dockerfile.wheel")" "$(native "$here")" > /dev/null

name=loupmd-wheel-$$
trap '"$docker" rm -f "$name" > /dev/null 2>&1 || true' EXIT
git -C "$root" archive --format=tar "$commit" | "$docker" run -i --name "$name" \
    -e WHEEL_ARCHS="${LOUPMD_WHEEL_ARCHS:-}" -e LOUPMD_WHEEL_JOBS="${LOUPMD_WHEEL_JOBS:-4}" "$image" \
    bash -euo pipefail -c 'mkdir -p /work && tar -x -C /work && cd /work && bash tools/release/wheel_in_container.sh'
mkdir -p "$out"
"$docker" cp "$name:/work/dist/." "$(native "$out")"
echo "in $out:"
ls -l "$out" | grep "\.whl$"
