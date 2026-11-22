#!/bin/bash
# Adds the LoupMD styles (pair styles loupmd and loupmd/kk, run style loupmd) to a LAMMPS source tree as the
# package ML-LOUPMD.
#
#   lammps/install.sh /path/to/lammps
#
# It copies the source files and one CMake module and registers the package in cmake/CMakeLists.txt. Running it
# again updates the copies. Then configure LAMMPS with
#
#   -D PKG_ML-LOUPMD=ON -D LOUPMD_ROOT=/path/to/LoupMD        (plus -D PKG_KOKKOS=ON ... for loupmd/kk)
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
lmp=${1:-}
if [ -z "$lmp" ] || [ ! -f "$lmp/src/pair.h" ] || [ ! -f "$lmp/cmake/CMakeLists.txt" ]; then
  echo "usage: $0 /path/to/lammps   (a LAMMPS source tree with src/ and cmake/)" >&2
  exit 1
fi

mkdir -p "$lmp/src/ML-LOUPMD"
cp "$here"/ML-LOUPMD/*.h "$here"/ML-LOUPMD/*.cpp "$lmp/src/ML-LOUPMD/"
cp "$here/KOKKOS/pair_loupmd_kokkos.h" "$here/KOKKOS/pair_loupmd_kokkos.cpp" "$lmp/src/KOKKOS/"
cp "$here/cmake/ML-LOUPMD.cmake" "$lmp/cmake/Modules/Packages/"

f="$lmp/cmake/CMakeLists.txt"
if ! grep -q "ML-LOUPMD" "$f"; then
  # the package list (alphabetical) and the packages with a CMake module of their own
  sed -i 's/^  ML-IAP$/  ML-IAP\n  ML-LOUPMD/' "$f"
  sed -i 's/^foreach(PKG_WITH_INCL \(.*\) ML-IAP /foreach(PKG_WITH_INCL \1 ML-IAP ML-LOUPMD /' "$f"
  if ! grep -q "^  ML-LOUPMD$" "$f" || ! grep -q "^foreach(PKG_WITH_INCL .* ML-LOUPMD " "$f"; then
    echo "$0: could not register ML-LOUPMD in $f (its layout differs from the LAMMPS versions this was written for)" >&2
    exit 1
  fi
fi

echo "ML-LOUPMD installed in $lmp"
echo "configure with: -D PKG_ML-LOUPMD=ON -D LOUPMD_ROOT=$(cd "$here/.." && pwd)"
