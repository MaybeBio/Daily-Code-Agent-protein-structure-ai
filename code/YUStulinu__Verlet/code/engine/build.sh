#!/bin/sh
# Build the engine (C++ and Fortran) and run its tests.
# On Windows with MSYS2, the UCRT64 toolchain must come first on PATH:
# gfortran's compiler crashes when it loads another MinGW's DLLs (e.g. Git's).
set -e
cd "$(dirname "$0")"
if [ -d /c/msys64/ucrt64/bin ]; then
  export PATH=/c/msys64/ucrt64/bin:$PATH
  GEN="-G Ninja -DCMAKE_CXX_COMPILER=g++ -DCMAKE_Fortran_COMPILER=gfortran"
fi
cmake -S . -B build/cm $GEN "$@"
cmake --build build/cm -j 8
