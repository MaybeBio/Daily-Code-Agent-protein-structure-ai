# One kernel IR and a run-time compiler (NVRTC)

Status (S144, 19 November 2026, branch `develop`, 5060 Ti only):

- Stages 2, 3 and 5 are built and on by default.
- Stage 1 is built and opt-in (`LOUP_JIT=1`).
- Stage 4 is bounded and not built.

The ledger (`gen-jit-layer0`, `gen-jit-conv`, `gen-jit-products`, `gen-jit-epilogue-bound`,
`gen-retire-specialised`) and `STATUS_AND_PROFILE.md` hold the measurements.

## Stages 2-5 results (5060 Ti)

- **Stage 2 (conv layers of any width).**
  - The conv kernels moved to `src/generated_conv.cuh`, which the library also embeds.
  - A conv layer whose width has no built-in instance is compiled at load with its width as a constant, instead of
    taking the run-time-width branch (`LOUP_CONV_GENERIC=1` forces that branch, for tests).
  - The built-in instances cover the forward at `C` 128 (and 256 / 224 for `lx` 1 / 2), and the backward also at 96.
    A model such as OFF23-S (`lx` 0, `C` 96) therefore compiles its forward conv at load by default.
  - OFF23-S water216 MD (`a b b a`, same library and plans): `LOUP_JIT=0` (the run-time-width forward) against the
    default (the JIT forward at `C` 96) reads b/a 1.014, orders 1.020 / 1.009. The JIT is 1.4% faster in both
    orders, inside the ±2-3% spread of single runs.
- **Stage 3 (products without `nvcc`).**
  - The product emitter moved verbatim to `python/gen_product.py`; the generated files are byte-identical.
  - Each bundle carries its layers' product source (`L<t>.prod_src`). A product signature the library was not
    built with is compiled from that source at load.
  - `LOUP_JIT_PRODUCTS=1` compiles every product so, for gates. With `LOUP_JIT=0`, such a bundle is refused, and
    the message says why.
  - With every product compiled from the bundle, the gates pass 92/92 rows over seven families (worst force /
    stress ratio 2.63 / 1.83).
  - A bundle whose signatures were renamed, so the library has none of them, loads, compiles and matches.
  - An offline NVRTC compile of one product takes 1.3 s; later loads read the disk cache.
- **Stage 4 (epilogue fusion from the IR).** Not built. The fusions it could add bound the gain at about 2-3% of the
  step on MH-1, OMOL-0 and POLAR only:
  - their gate, readout and density epilogues;
  - every other family already fuses them, or they run inside the product kernels.
- **Stage 5 (one path).** The specialised OMAT-0-medium path is retired with the owner's approval ("Its fine to
  retire the seperate kernels", 19 November):
  - Removed: `interaction0.cu`, `model_loader.cu`, `generated_kernels.cuh`, `gen_kernels.py`, `export_omat0.py`,
    ~740 lines of `engine.cu`.
  - OMAT-0 medium exports and runs on the generic path like every other family.
  - `arch=omat0_medium_spec` bundles are refused with a re-export message.
  - Cost on OMAT-0 medium: none, the generic path is faster. MD `a b b a` on the same library (the last one with both
    paths) and plans, specialised (a) against generic (b): SrTiO3 7.905 → 7.671 ms/step (b/a 0.970, orders 0.972 /
    0.969); NbCl5 1.756 → 1.713 ms/step (b/a 0.975, orders 0.975 / 0.976). The ~8% lead the specialised kernels had
    on 15 November (release `AGENTS.md`) has closed since then.

## Stage 1 result (5060 Ti)

- **Speed.** Compiling layer 0's constants in shrinks the static SASS by 5-37% at the same registers but buys no
  time: `first_bwd_edge` +0.2% / +1.8% / -2.4% and `first_fwd` -0.5% / -1.9% / 0% on OMAT-0 generic, OFF23-S and
  MH-1. The edge backward is bound by its load/store pipe, and S142's `J_FIX = 65` kernel had already folded the one
  constant that mattered.
- **The grid.** Compiling the spline grid in as literals is slower (+2.5%). Seven bands become select chains, where
  the argument costs one indexed constant load per field. So the IR does not bake the grid.
- **Correctness.** Forces agree with the built-in kernels to within the order of the floating-point atomics. The 3x
  gate passes with `LOUP_JIT=1` on five families.

What follows for stages 2 and 3:

- A constant is worth compiling in only where it removes work on the critical path, not just instructions.
- The conv kernels' `C = 0` templates (widths without an AOT instance) are the first stage-2 candidate. The first
  step there is to measure, on one model, what the `C = 128` instance gains over the `C = 0` template.
- Stage 3 (products without `nvcc`) is about coverage, not speed.

## Why

Today a kernel's shape is fixed when the library is built:

- **Generic path.** `python/gen_generic.py` emits template kernels for every model in `/home/fzwin/models`
  (products by signature, conv kernels by `(lx, C)`). `generic.cu` then picks one of a few instances per layer
  from tables written by hand.
- **Specialised path (retired in stage 5).** `gen_kernels.py` emitted OMAT-0 medium's kernels for one shape only.
- **Release.** A model outside the build set needs `loupmd build-kernels`, which runs `nvcc`.

Everything that is known only at load (the table width `J`, species count `S`, interval count, spline grid,
pair symmetry, `sh_perm`, which layers are pruned) reaches the kernels as run-time arguments. S142's `J_FIX = 65`
measured what baking one of them in is worth: 1,984 → 1,568 static instructions and 424 → 375 µs per force call
for `first_bwd_edge` (OMAT-0 generic SrTiO3, 5060 Ti). Each such constant has so far needed its own template row
and dispatch case.

## Shape of the design

1. **IR.** At load, `GenericModel` lowers each layer to a typed record holding every constant a kernel could bake
   in (`src/kernel_ir.hpp`):
   - widths and degrees;
   - the spline grid;
   - pair symmetry and the species count;
   - ZBL and stress flags;
   - pruning;
   - later, the factored product program.

   One record type serves every path. A kernel family reads only its own fields.
2. **Kernel sources are compiled into the library as text.** Each kernel lives in one header that is used twice:
   - `nvcc` compiles it ahead of time as today (the AOT path, kept as the fallback);
   - the library also embeds it as a string (Makefile rule `jit_src_*.inc`).

   A constant is baked in through `LOUP_BAKE_*` macros. With the macro undefined, the value is the kernel argument,
   as now. With it defined (by the JIT prelude), the value is a `constexpr`. There is one source of truth and no
   second copy to keep in step.
3. **JIT runtime (`src/jit.cu`).**
   - Loading:
     - NVRTC is loaded with `dlopen` (`libnvrtc.so.13`, `.12`, or `LOUP_NVRTC`), so the library has no new link
       dependency.
     - The cubin is loaded with `cudaLibraryLoadData`.
     - Kernels are fetched with `cudaLibraryGetKernel` and launched with `cudaLaunchKernel`. That works inside graph
       capture, and the kernel keeps the AOT kernel's parameter list.
   - Disk cache: `<LOUP_CACHE_DIR or ~/.cache/loupmd>/jit/<key>.cubin` plus the lowered names. The key hashes the
     source, headers, options, NVRTC version and target architecture.
   - Failure handling: if NVRTC is missing or a compile fails, the library warns once and keeps the AOT kernel.
4. **Switch.** `LOUP_JIT` unset (the default) runs stages 2 and 3: the JIT compiles only what the library has no
   instance for. `LOUP_JIT=1` adds layer 0 (stage 1, a tie). `LOUP_JIT=0` compiles nothing; a bundle whose product
   the library lacks is then refused. A family's built-in kernels are replaced by default only after the 3x gate
   and an `a b b a` MD A/B on the same library and plans.

## Stages

| stage | scope | done when |
|---|---|---|
| 1 (built, S143) | JIT runtime and disk cache; IR for layer 0; `first_bwd_edge` and `first_fwd` with `S`, `I`, `J`, `Jt`, `K0`, `sh_perm` and `pair_sym` baked in (the grid: measured, rejected) | forces at the cross-process level, gates, nsys A/B and tests: done; a tie, so off by default |
| 2 (built, S144) | conv forward and backward kernels from the embedded generator output (`generated_conv.cuh`), with the width `C` baked in for widths without a built-in instance; `S`, `I` and the grid stay arguments (stage 1: baking them buys nothing) | gates and tests: done; OFF23-S MD 1.4% faster than the run-time-width forward (within the spread) |
| 3 (built, S144) | products: the bundle carries each product's source (`gen_product.py`, `L<t>.prod_src`), compiled at load when the library lacks the signature. A model outside the build set then runs without `nvcc` (replaces `build-kernels`' `nvcc` step) | renamed-signature bundle compiles and matches; 92/92 gate rows with every product compiled from the bundle: done |
| 4 (bounded, not built) | epilogue fusion chosen from the IR (gate, readout, density into the GEMM epilogues), which today are fixed per kind | bound: about 2-3% on MH-1, OMOL-0 and POLAR only |
| 5 (built, S144) | the specialised OMAT-0 path retired; OMAT-0 medium runs the generic path | owner's approval; gates and tests on the generic path; MD 2.5-3.0% faster than the specialised path |

## What this does not change

- Pointers stay run-time arguments. Baked pointers freed no registers (idea 29's census), and they would force
  recompiles on every reallocation and graph re-record.
- Accuracy: the JIT kernel runs the same arithmetic in the same order. Bitwise checks are not possible across
  processes, because the floating-point atomics differ from run to run. Stage 1 therefore compared against two
  built-in runs, with conv tuning off: built-in against JIT has to stay within built-in against built-in.
