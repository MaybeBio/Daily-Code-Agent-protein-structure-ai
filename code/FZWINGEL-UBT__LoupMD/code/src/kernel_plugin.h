#pragma once
// Kernel plugins (PLAN.md S2-T06). The library is built with the product kernels of the models listed in
// src/generated_generic_manifest.json. A model whose symmetric contraction has another signature gets its kernels
// from a plugin: a shared library named loupmd-kernels-<signature>.so in one of the folders of LOUP_KERNEL_PATH
// (colon-separated; the loupmd package sets it to its cache's lib folder), built by `loupmd build-kernels MODEL`
// from codegen/gen_generic.py --plugin. A plugin exports
//   int loup_kernel_abi();                                  // LOUP_KERNEL_ABI of the headers it was built with
//   const GProdKernels* loup_plugin_gprod(const char* sig); // its kernels for that signature, or NULL
// and is loaded when a bundle names a signature the library does not have. Raise LOUP_KERNEL_ABI whenever
// GProdKernels, a product kernel's argument list or kernels_common.cuh changes in a way a plugin would notice.
// 2: GProdKernels has the scalar-only and compact readouts (ro1s, ro1c) and the compact products (fwdc, bwdc).
// Since JIT_DESIGN.md stage 3 a bundle also carries its products' source, which the library compiles at load when
// NVRTC is there: a plugin is then needed only without NVRTC, with LOUP_JIT=0, or for a bundle without the source.
#define LOUP_KERNEL_ABI 2
