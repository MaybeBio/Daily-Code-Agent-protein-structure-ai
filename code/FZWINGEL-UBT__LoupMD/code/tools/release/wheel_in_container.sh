#!/usr/bin/env bash
# Inside the build image, in a copy of the source tree (tools/release/build_wheel.sh starts it): the
# multi-architecture library, the package's _lib folder, the wheel, and the checks of PLAN.md S2-T02.
# WHEEL_ARCHS narrows the compute capabilities (default: the Makefile's six); LOUPMD_WHEEL_JOBS the make jobs.
set -euo pipefail
set +u; source /opt/rh/gcc-toolset-13/enable; set -u       # its script reads unset variables
export PATH=/usr/local/cuda/bin:$PATH
echo "nvcc $(nvcc --version | grep -o 'V[0-9][0-9.]*'), g++ $(g++ -dumpfullversion), glibc $(ldd --version | head -1 | grep -o '[0-9.]*$'), $(python3.11 --version)"

# build_wheel.sh always passes WHEEL_ARCHS, empty for the default: an empty value in the environment would replace
# the Makefile's list and nvcc would compile for its own default architecture.
archs=()
if [ -n "${WHEEL_ARCHS:-}" ]; then archs=("WHEEL_ARCHS=$WHEEL_ARCHS"); else unset WHEEL_ARCHS; fi
start=$(date +%s)
make -j"${LOUPMD_WHEEL_JOBS:-4}" wheel-lib "${archs[@]}" > build-lib.log 2>&1 || { tail -30 build-lib.log; exit 1; }
echo "library built in $(( $(date +%s) - start )) s"

# What the package ships beside its modules (pyproject.toml, package-data): the library, the tensor-core kernel
# files it loads from its own folder, the kernel manifest, and what `loupmd build-kernels` compiles a plugin from.
lib=loupmd/_lib
mkdir -p $lib/cubins $lib/kernel-src
cp build/wheel/libloupmd.so $lib/
cp cubins/*.cubin $lib/cubins/
cp src/generated_generic_manifest.json $lib/
cp src/kernel_plugin.h src/generated_generic.cuh src/generated_sh16.cuh src/kernels_common.cuh codegen/gen_generic.py $lib/kernel-src/

python3.11 -m build --wheel --no-isolation --outdir dist . > build-wheel.log 2>&1 || { tail -30 build-wheel.log; exit 1; }
python3.11 -m wheel tags --platform-tag manylinux_2_28_x86_64 --remove dist/*.whl > /dev/null
wheel=$(ls dist/*.whl)
echo "wheel $(basename "$wheel"), $(stat -c %s "$wheel") bytes, library sha256 $(sha256sum $lib/libloupmd.so | cut -c1-16)"

# ---- checks ----
for arch in ${WHEEL_ARCHS:-80 86 89 90 100 120}; do
    count=$(cuobjdump -lelf $lib/libloupmd.so | grep -c "sm_$arch" || true)
    echo "sm_$arch: $count ELF images in the library"
    [ "$count" -gt 0 ] || { echo "no code for sm_$arch"; exit 1; }
done
# The newest symbol versions the library asks of the system: manylinux_2_28 allows glibc up to 2.28 and
# libstdc++ of GCC 8 (GLIBCXX_3.4.25, CXXABI_1.3.11). auditwheel's verdict is printed after it.
python3.11 - "$lib/libloupmd.so" "$wheel" <<'PY'
import re
import subprocess
import sys
import zipfile

lib, wheel = sys.argv[1:3]
table = subprocess.run(["objdump", "-T", lib], capture_output=True, text=True, check=True).stdout
limits = {"GLIBC": (2, 28), "GLIBCXX": (3, 4, 25), "CXXABI": (1, 3, 11)}
worst = {}
for family, version in re.findall(r"\b(GLIBC|GLIBCXX|CXXABI)_([0-9.]+)", table):
    worst[family] = max(worst.get(family, ()), tuple(int(part) for part in version.split(".")))
for family, limit in limits.items():
    found = worst.get(family, ())
    print(f"{family}: needs up to {'.'.join(map(str, found)) or 'nothing'}, manylinux_2_28 allows {'.'.join(map(str, limit))}")
    if found > limit:
        sys.exit(f"the library needs {family}_{'.'.join(map(str, found))}")
needed = re.findall(r"NEEDED\s+(\S+)", subprocess.run(["objdump", "-p", lib], capture_output=True, text=True).stdout)
print("needs:", " ".join(needed))

names = zipfile.ZipFile(wheel).namelist()
must = ["loupmd/_lib/libloupmd.so", "loupmd/_lib/generated_generic_manifest.json",
        "loupmd/_lib/kernel-src/gen_generic.py", "loupmd/_lib/kernel-src/kernel_plugin.h",
        "loupmd/_lib/kernel-src/generated_generic.cuh", "loupmd/_lib/kernel-src/generated_sh16.cuh",
        "loupmd/_lib/kernel-src/kernels_common.cuh",
        "loupmd/_lib/cubins/tf32x3_hyb_sm120.cubin", "loupmd/bench/reference.json",
        "loupmd/bench/structures/water_216.extxyz", "loupmd/export/_vendor/VERSION"]
missing = [name for name in must if name not in names]
stray = [name for name in names if name.startswith(("tests/", "tools/", "src/", "codegen/", "docs/"))]
print(f"{len(names)} files in the wheel; missing: {missing or 'none'}; outside the package: {stray or 'none'}")
if missing or stray:
    sys.exit("the wheel's contents are not as planned")
meta = zipfile.ZipFile(wheel).read(next(n for n in names if n.endswith(".dist-info/METADATA"))).decode()
tags = zipfile.ZipFile(wheel).read(next(n for n in names if n.endswith(".dist-info/WHEEL"))).decode()
print(" | ".join(line for line in meta.splitlines() if line.startswith(("Name:", "Version:", "Requires-Dist:"))))
print(" | ".join(line for line in tags.splitlines() if line.startswith(("Tag:", "Root-Is-Purelib:"))))
PY
echo "--- auditwheel show (the CUDA libraries come from the pinned NVIDIA wheels, not from this one)"
python3.11 -m auditwheel show "$wheel" 2>&1 | sed -n 1,25p || true
