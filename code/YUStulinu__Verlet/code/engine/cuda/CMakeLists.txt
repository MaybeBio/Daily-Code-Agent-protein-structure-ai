# The CUDA plugin, built separately from the engine (on Windows nvcc needs
# MSVC as the host compiler, while the engine is built with g++/gfortran;
# the two meet through a plain C interface loaded at run time).
cmake_minimum_required(VERSION 3.20)
project(verlet_cuda CXX CUDA)
if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES native)
endif()
set(CMAKE_CUDA_STANDARD 17)
add_library(verlet_cuda SHARED plugin.cu)
target_include_directories(verlet_cuda PRIVATE ../include)
target_compile_options(verlet_cuda PRIVATE $<$<COMPILE_LANGUAGE:CUDA>:-lineinfo>)
set_target_properties(verlet_cuda PROPERTIES CUDA_RUNTIME_LIBRARY Static)
