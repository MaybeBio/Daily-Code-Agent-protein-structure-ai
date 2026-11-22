#pragma once
// Run-time kernel compiler (JIT_DESIGN.md). Builds a kernel source with NVRTC for the current GPU, keeps the cubin in
// a disk cache, and returns kernel handles for cudaLaunchKernel. NVRTC is loaded with dlopen (LOUP_NVRTC, else
// libnvrtc.so.13 / .12), so the library gains no link dependency; without it, or on any failure, build() returns an
// empty list and the caller keeps its ahead-of-time kernel.
#include <string>
#include <vector>

#include <cuda_runtime.h>

namespace loup {
namespace jit {

struct Header {
    const char* name;  // the include name the sources use ("kernels_common.cuh")
    const char* text;
};

// The kernel headers compiled into the library (Makefile: jit_src/*.inc).
const std::vector<Header>& embedded_headers();

// What the JIT compiles (LOUP_JIT, read once): 0 nothing; unset (default) the kernels the library has no instance
// for (stage 2: conv layers of other widths; stage 3: products of models outside the build set); 1 also layer 0's
// kernels (stage 1, a tie).
int level();
inline bool enabled() { return level() >= 2; }  // layer 0 too

// Kernels for `name_exprs` (NVRTC name expressions, e.g. "first_bwd_edge_kernel<2, true, false, 0>"), in that order,
// as handles for cudaLaunchKernel / cudaFuncSetAttribute. Compiled once per (source, headers, options, NVRTC version,
// GPU architecture): in memory for the process, on disk in <LOUP_CACHE_DIR or ~/.cache/loupmd>/jit/. Empty on failure;
// `err` (nullable) then says why. Never unloaded (the handles stay valid for the process).
std::vector<const void*> build(const std::string& tag, const std::string& src, const std::vector<Header>& headers,
                               const std::vector<std::string>& name_exprs, std::string* err = nullptr);

// Statistics of this process's build() calls (tests, LOUP_DEBUG_JIT): compiles run, disk-cache hits, memory hits.
struct Stats {
    int compiled = 0, disk_hits = 0, memory_hits = 0, failures = 0;
};
Stats stats();

}  // namespace jit
}  // namespace loup
