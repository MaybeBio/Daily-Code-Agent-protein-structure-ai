cmake_minimum_required(VERSION 3.20)
project(verlet CXX Fortran)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
option(VERLET_NATIVE "Optimize for this machine (-march=native)" ON)
add_compile_options($<$<COMPILE_LANGUAGE:CXX>:-Wall> $<$<COMPILE_LANGUAGE:CXX>:-Wextra>)
if(VERLET_NATIVE)
  add_compile_options(-march=native)
endif()
set(CMAKE_Fortran_FLAGS "${CMAKE_Fortran_FLAGS} -std=f2018 -Wall -ffree-line-length-none")
# MinGW: static runtime (other libstdc++/libgfortran DLLs on PATH can crash at run time)
if(MINGW)
  add_link_options(-static)
endif()
find_package(OpenMP REQUIRED COMPONENTS CXX)

add_library(verlet_core STATIC
  src/system.cpp src/fft.cpp src/nonbonded.cpp src/forces.cpp src/constraints.cpp src/integrator.cpp src/cuda_loader.cpp src/alchemy.cpp
  fortran/bonded.f90)
target_include_directories(verlet_core PUBLIC include)
target_link_libraries(verlet_core PUBLIC OpenMP::OpenMP_CXX ${CMAKE_DL_LIBS})

add_executable(verlet tools/verlet.cpp)
target_link_libraries(verlet PRIVATE verlet_core)

enable_testing()
add_executable(test_engine tests/test_engine.cpp)
target_link_libraries(test_engine PRIVATE verlet_core)
add_test(NAME test_engine COMMAND test_engine WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
