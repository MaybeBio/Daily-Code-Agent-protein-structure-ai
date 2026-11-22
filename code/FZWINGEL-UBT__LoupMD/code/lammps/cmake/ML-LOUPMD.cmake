# ML-LOUPMD: MACE models on CUDA GPUs through the LoupMD engine (pair styles loupmd and loupmd/kk).
#
# The package needs LoupMD's C header and shared library:
#   -D LOUPMD_ROOT=<dir>     a directory with include/loupmd.h and libloupmd.so (in <dir>, <dir>/lib or <dir>/lib64),
#                            e.g. a LoupMD checkout after `make`
# or -D LOUPMD_INCLUDE_DIR=<dir with loupmd.h> -D LOUPMD_LIBRARY=<path to libloupmd.so>
set(LOUPMD_ROOT "" CACHE PATH "Directory of the LoupMD engine (include/loupmd.h, libloupmd.so)")

find_path(LOUPMD_INCLUDE_DIR loupmd.h HINTS ${LOUPMD_ROOT} ENV LOUPMD_ROOT PATH_SUFFIXES include NO_DEFAULT_PATH)
find_path(LOUPMD_INCLUDE_DIR loupmd.h)
find_library(LOUPMD_LIBRARY NAMES loupmd HINTS ${LOUPMD_ROOT} ENV LOUPMD_ROOT PATH_SUFFIXES . lib lib64 NO_DEFAULT_PATH)
find_library(LOUPMD_LIBRARY NAMES loupmd)
if(NOT LOUPMD_INCLUDE_DIR OR NOT LOUPMD_LIBRARY)
  message(FATAL_ERROR "ML-LOUPMD: loupmd.h or libloupmd.so not found. Set -D LOUPMD_ROOT=/path/to/LoupMD "
                      "(a directory with include/loupmd.h and libloupmd.so), or LOUPMD_INCLUDE_DIR and LOUPMD_LIBRARY.")
endif()
message(STATUS "ML-LOUPMD: header in ${LOUPMD_INCLUDE_DIR}, library ${LOUPMD_LIBRARY}")

target_include_directories(lammps PRIVATE ${LOUPMD_INCLUDE_DIR})
target_link_libraries(lammps PRIVATE ${LOUPMD_LIBRARY})

# libloupmd.so is found at run time from the build tree automatically; keep its directory for installed binaries too.
get_filename_component(LOUPMD_LIBRARY_DIR ${LOUPMD_LIBRARY} DIRECTORY)
foreach(_tgt lmp lammps)
  if(TARGET ${_tgt})
    set_property(TARGET ${_tgt} APPEND PROPERTY INSTALL_RPATH ${LOUPMD_LIBRARY_DIR})
  endif()
endforeach()
