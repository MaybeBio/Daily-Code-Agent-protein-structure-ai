# LoupMD Optimisation Ledger

Status: compiled on 13 November 2026 from the LoupMD working tree and
[STATUS_AND_PROFILE.md][status] at its sixth update (13 November, 14:15). Modelled on FastMACE's
`docs/optimisation-ledger.md`. The tree is under git since 14:20 that day (first commit `4477d66`); entries before
that have no commit to cite.

This file is the index and the verdict list for every optimisation LoupMD has tried, adopted or not, so that
work is not repeated. It does not replace the evidence: `STATUS_AND_PROFILE.md` stays authoritative for numbers,
profiles and methods, and each entry links the section it comes from. Numbers are copied as recorded; "not
recorded" means no source gives one. Before 12 November the sources give no dates, only the stage of the
[chronology](#chronology) at which an item landed (S0-S5).

Maintenance rule: every new attempt adds its index row and its appendix entry together with the
`STATUS_AND_PROFILE.md` update that records its numbers. Rows are never deleted: a reverted or superseded attempt
changes its status.

Conventions:

- **MD A/B**: `python/bench_md.py` (median of 6 x 256 Langevin steps, 300 K, 1 fs, skin 0.5 A, friction 0.01/fs,
  after 100 warm-up steps), old and new library in the same process, run in both build orders: "A / B" are the two
  orders. Percentages are the change in MD step time; **negative is faster**. A change is adopted only if it wins or
  ties in both orders on both GPUs. On the Ada the first run of a sequence is systematically ~0.6% fast, which biases
  order A against the new build.
- **Kernel times** are nsys kernel sums per step (us) unless stated; "span" is wall-clock GPU time of a stage.
- **GPUs**: 5060 Ti = RTX 5060 Ti 16 GB (`sm_120`, WSL2, the desktop shares the GPU); Ada = RTX 4000 Ada 20 GB
  (`sm_89`, `leeloo`, no performance-counter permission, so every `ncu` number is from the 5060 Ti).
- **Systems**: `NbCl5` 3x3x3 (1,944 atoms, 2 species), `SrTiO3` 10x10x10 (5,000 atoms, 3 species, ~370k edges).
  Two values "x / y" without other labels are `NbCl5` / `SrTiO3`.
- **Path**: spec = the specialised MACE-OMAT-0 medium kernels (sections 1-4 of the status file); gen = the generic
  path for the other families (section 5); POLAR = MACE-POLAR-1's long-range part (`src/polar.cu`). S144 retired
  the spec path ([gen-retire-specialised](#gen-retire-specialised)). Its DEFAULT items left the build with it, and
  its NOT BUILT ideas are closed; the rows stay as the record.
- **Status**: DEFAULT (in the build and on); DEFAULT (scoped: ...); REJECTED (built and measured, not adopted);
  SUPERSEDED; NOT BUILT (dropped on paper or deferred); PENDING (owner decision); BLOCKED; MEASUREMENT (profile or
  check, no switch); FIX (a correctness defect found while optimising).
- **Accuracy gate**: `python/test_gate.py`, 3x MACE float32-vs-float64 rule (dE <= max(3 dE32, 0.01 meV/atom),
  dF <= max(3 dF32, 1e-5 eV/A), dS <= max(3 dS32, 1e-7 eV/A^3)). Every adopted item passes it on both GPUs.

## Index by area

### Interaction-1 radial spline forward (`spline_forward_inter1`)

| ID | Idea | Switch/flag | Path | Status | Stage | Effect | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [spl-paired-edges](#spl-paired-edges) | Decode a table slab once for two consecutive edges of a receiver | template `PAIR` | spec | DEFAULT (per-system choice) | S3 | table loads per edge 1 -> 0.805 (`SrTiO3`); spline -7% (5060 Ti), -3% (Ada) | [§3.1 #20][s31] |
| [spl-multi-receiver](#spl-multi-receiver) | R consecutive receivers per block, variant timed at the first rebuild | `spline_forward_inter1<R, PAIR>`, `LOUP_SPLINE_VARIANT` | spec | DEFAULT | S4-S5 | L1 hit 5% -> 36%, L2 3.92 -> 2.66 GB; Ada `SrTiO3` -3.1% / -3.6% | [§3.1 #29][s31] |
| [spl-launch-128-7](#spl-launch-128-7) | `(128, 7)` / min-blocks 5 on `sm_89` | launch bounds | spec | REJECTED | – | spills; Ada +17% / +3% | [§3.3][s33] |
| [spl-16-edge-tiles](#spl-16-edge-tiles) | 16-edge tiles | – | spec | REJECTED | – | tie | [§3.3][s33] |
| [spl-receiver-remap](#spl-receiver-remap) | Blocks strided over the receiver range for L1 locality | – | spec | REJECTED | – | tie | [§3.3][s33] |
| [spl-paired-r5](#spl-paired-r5) | Paired 5-receiver blocks; lockstep R = 2 / 4 | – | spec | REJECTED | S4-S5 | spills 48-72 B; lockstep slower than named barriers | [§3.3][s33] |
| [spl-edge-split](#spl-edge-split) | One receiver's edges over 2 / 4 thread groups (small systems) | – | spec | REJECTED | S5 | 135 atoms 98 / 82 us vs 64 us; 1.4-1.6x slower at 5,000 atoms | [§4.1][s41] |
| [spl-unroll2](#spl-unroll2) | 2-edge unroll (before pairing) | – | spec | REJECTED | – | not recorded | [§3.3][s33] |
| [spl-cubic-forward](#spl-cubic-forward) | The 8-byte cubic table in the forward too | – | spec | REJECTED | – | not recorded | [§3.3][s33] |
| [tab-far-edge-4byte](#tab-far-edge-4byte) | 4-byte table rows for far edges (T2) | – | spec | REJECTED | – | `w'` +0.9% / +1.9%, spline +1.4% / +3.4% (5060 Ti / Ada) | [§3.3][s33] |
| [spl-receiver-order](#spl-receiver-order) | Receiver / sublattice ordering in `spline` and `w'` for L1/L2 slab locality | – | spec | REJECTED (S108, measured by reordered input) | S108 | species-major + Morton order: forward L1 hit 48.9% -> 48.6% at 300 K, force pass +4% | this file |
| [spl-r6-r8](#spl-r6-r8) | Unpaired `R=6` or `R=8` spline blocks if register pressure drops <= 80 | – | spec | REJECTED (`R=6`, 5060 Ti only); `R=8` not built | S32 | `R=6` as compiled (80 registers, 8 B stack): MD spline `1796 / 1801 -> 1830 / 1863 us` (`+3%`, `OMAT-0-M` `SrTiO3`) | this file |
| [spl-v6-cubic-cg-fold](#spl-v6-cubic-cg-fold) | `w'` cubic decode (`d_cubic_packed8_1`) + staged per-edge CG linear forms in `s_sh` (`ED = 36`, `TILE = 16`) | `_emit_spline_forward1` | spec | DEFAULT (5060 Ti only) | S15 | 5060 Ti `SrTiO3` 8.40 -> 8.28 ms (`0.985`, `R1p` 1,403 -> 1,306 us), `NbCl5` 1.863 -> 1.853 (`0.994`); all `LOUP_SPLINE_VARIANT` gates pass | this file |
| [s108-wide-table](#s108-wide-table) | Wider interaction-1 intervals so thermalised shells keep reusing slabs: 2-8x coarser cubic grid (ceiling), 8-byte quintic / Chebyshev formats | branch `s108-quintic-proto` (`LOUP_GEN_SPLINE1`) | spec | REJECTED (5060 Ti) | S108 | ceiling with accuracy ignored: 300 K -4.5% (8x); accurate 8-byte quintic (4x): +5% to +11% | this file |

### Interaction-1 chain as a whole

| ID | Idea | Switch/flag | Path | Status | Stage | Effect | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [int1-two-halves](#int1-two-halves) | Chain split into two receiver halves on two streams; high-priority GEMM streams | – | spec | REJECTED | – | 5060 Ti +0.9% / +0.7% | [§3.3][s33] |
| [int1-l2-chunks](#int1-l2-chunks) | Whole chain per L2-sized receiver chunk so `m1` / `dm1` stay in L2 | – | spec | REJECTED | – | +0.2% to +2.8% at 650-1,700-atom chunks | [§3.3][s33] |
| [int1-lin1-fusion](#int1-lin1-fusion) | Fuse `lin1` into the spline / `w'` kernels | – | spec | NOT BUILT | – | ceiling: `lin1` groups 529 + 597 us (`SrTiO3`) | [§4.1 #1][s41] |
| [int1-radial-low-rank](#int1-radial-low-rank) | Tabulate fewer radial functions: the 64 hidden activations, or a few basis functions per channel | – | spec | NOT BUILT (closed by measurement) | – | rank 64 of 64; per channel 10 of 10 paths | this file |
| [s109-exponent-or](#s109-exponent-or) | Table exponents shifted by 2^k (exact) to a 32-aligned base so the decode ORs it in; 2^-k folded into the forward's stores and `w'`'s staged q | – | spec | REJECTED (5060 Ti) | S109 | MD a-b-b-a `NbCl5` 1.0100, `SrTiO3` 1.0067; gate passes | this file |

### Interaction-1 backward (`w'`, `wprime_backward_inter1`)

| ID | Idea | Switch/flag | Path | Status | Stage | Effect | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [wp-cubic-packed8](#wp-cubic-packed8) | 8-byte exact quantised cubic table instead of `float4` | `d_cubic_packed8_1` | spec | DEFAULT | S1 | part of S0 -> S1: 2.384 -> 2.187 / 11.380 -> 10.458 ms (5060 Ti) | [§3.1 #1][s31], [§1][s1] |
| [wp-receiver-owned](#wp-receiver-owned) | One receiver per block, q staged once (N >= 512; every N on `sm_120` since S96 and on cc 8.0 since S114) | `wprime_backward_inter1_rcv`, `LOUP_WPRIME_RCV` | spec | DEFAULT | S3, S96, S114 | -170 us on both GPUs; S96 small SrTiO3 cells (5060 Ti) 40 / 135 / 320 atoms `0.984` / `0.953` / `0.967`; A100 (S96c, forced `LOUP_WPRIME_RCV=1`) `0.994` / `0.989` / `0.968`, both orders below 1: default on cc 8.0 since S114 | [§3.1 #12][s31], this file |
| [wp-channel-major-q](#wp-channel-major-q) | Channel-major staged q, conflict-free `LDS.128` | – | spec | DEFAULT | S3 | `w'` -1.7% (5060 Ti), -2.5% (Ada) | [§3.1 #21][s31] |
| [wp-shift-free-decode](#wp-shift-free-decode) | Coefficient bits packed at their float position: one `LOP3` per decode | – | spec | DEFAULT | S4 | `w'` 3,177 -> 3,065 us; MD up to -1.3% | [§3.1 #27][s31] |
| [wp-dt-scale](#wp-dt-scale) | Radial derivative scaled by 2^8 (one `FMUL` less per path) | – | spec | DEFAULT | S4 | `w'` 3,069 -> 3,010 us; MD -0.1% to -0.6% | [§3.1 #28][s31] |
| [wp-block-size](#wp-block-size) | 256 or 512 threads per block, chosen per system | `LOUP_WPRIME_THREADS` | spec | DEFAULT | S5 | Ada `SrTiO3` -1.0% / -1.2%; 5060 Ti tie | [§3.1 #31][s31] |
| [wp-vector2](#wp-vector2) | 2-channel vectorised `w'` (T1) | – | spec | REJECTED | – | -1.6% (5060 Ti), +2.3% (Ada) | [§3.3][s33] |
| [wp-paired-edges](#wp-paired-edges) | Paired edges as in the spline | – | spec | REJECTED | – | 3.23 -> 3.28 / 3.35 ms (spills) | [§3.3][s33] |
| [wp-channel-passes](#wp-channel-passes) | 2 / 4-pass channel staging (smaller `s_dout`) | – | spec | REJECTED | – | 3.23 -> 3.40 / 3.80 ms | [§3.3][s33] |
| [wp-x0-hoist](#wp-x0-hoist) | Hoist the `x0` scale of the four scalar paths | – | spec | REJECTED | – | 3,016 -> 3,086 us (spills) | [§3.3][s33] |
| [wp-launch-256-3](#wp-launch-256-3) | `(256, 3)` launch bounds, 80 registers | – | spec | REJECTED | – | below A/B resolution | [§3.3][s33] |
| [wp-persistent](#wp-persistent) | SM-local persistent blocks with `%smid` cursors | – | spec | REJECTED | – | 3,014 -> 3,240 us | [§3.3][s33] |
| [wp-no-allocate](#wp-no-allocate) | Table loads with `L1::no_allocate` | – | spec | REJECTED | – | 3,022 -> 3,120 us | [§3.3][s33] |
| [wp-decode-bias-fold](#wp-decode-bias-fold) | Fold the four `- hb` subtractions of the cubic decode into the polynomials | `LOUP_GEN_DECODE_FOLD` (generator, on) | spec | DEFAULT (13 Nov) | – | 5060 Ti `SrTiO3` 0.9929 / 0.9948 / 0.9925, `NbCl5` 0.9951 / 0.9938 / 0.9965; Ada tie; -24 / -16 instructions | this file |
| [wp-scalar3-quad](#wp-scalar3-quad) | Scalar rank-three path `(0, 3, 3)` contracted with the five quadratics of the edge direction (three five-term sums) instead of eight three-term dots plus the trace | `LOUP_GEN_SCALAR3_U` (generator, reverted) | spec | REJECTED (5060 Ti) | S117 | all three variants spill in `wprime_backward_inter1_rcv` (64 registers, 48 B stack; HEAD none): `w'` SrTiO3 2,785-2,788 -> 3,025-3,116 us (+9-12%), NbCl5 429-430 -> 468-475 us (+9-11%) | this file |

### Interaction 0 and the symmetric contractions

| ID | Idea | Switch/flag | Path | Status | Stage | Effect | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [i0-receiver-owned-fwd](#i0-receiver-owned-fwd) | Receiver-owned i0 forward, register accumulation per sender-species run | `check_row_species_order_kernel` guard | spec | DEFAULT | S2 | removes atomics and the 61 MB per-step zero-fill | [§3.1 #4][s31] |
| [i0-bwd-prefetch](#i0-bwd-prefetch) | Lane-parallel chunk metadata in i0 backward | – | spec | DEFAULT | S2 | not recorded alone | [§3.1 #5][s31] |
| [i0-bwd-fused-assembly](#i0-bwd-fused-assembly) | i0 backward fused with force / virial assembly (T5) | – | spec | DEFAULT | S3 | removes `d_dsh0`, `d_dr0` | [§3.1 #14][s31] |
| [i0-bwd-sh-staging](#i0-bwd-sh-staging) | SH staged in the warp's rows, `float2` channel pairs | – | spec | DEFAULT | S3 | 685 -> 564 us (5060 Ti), 736 -> 668 us (Ada) | [§3.1 #23][s31] |
| [i0-fwd-warp-per-receiver](#i0-fwd-warp-per-receiver) | Warp per receiver, 2 channels per lane | – | spec | DEFAULT | S3 | 390 -> 245 us (5060 Ti), 415 -> 304 us (Ada) | [§3.1 #25][s31] |
| [i0-sh-shuffle](#i0-sh-shuffle) | SH shuffle broadcast in i0 backward (old idea 3) | – | spec | SUPERSEDED | – | tie; superseded by i0-bwd-sh-staging | [§3.3][s33] |
| [i0-bwd-receiver-owned](#i0-bwd-receiver-owned) | Receiver-owned i0 backward (T7) | – | spec | REJECTED | – | +1.8% / +1.1% (5060 Ti) | [§3.3][s33] |
| [i0-bwd-micro](#i0-bwd-micro) | Coefficient prefetch, early loads, 4 partial sums | – | spec | REJECTED | – | 551 -> 571, 554 -> 564, 554 -> 626 us | [§3.3][s33] |
| [i0-per-species-fwd](#i0-per-species-fwd) | Per-species i0 forward | – | spec | REJECTED | – | not recorded | [§3.3][s33] |
| [sc-sc1-fused](#sc-sc1-fused) | `sc1` forward + readout forward / backward + `sc1` backward in one launch | `sc1_fused` | spec | DEFAULT | S2 | not recorded alone | [§3.1 #6][s31] |
| [sc-sc0-bwd-launch](#sc-sc0-bwd-launch) | `sc0_backward` at `(128, 3)` | – | spec | REJECTED | – | not recorded | [§3.3][s33] |
| [sc-sc0-overlap](#sc-sc0-overlap) | `sc0` per species beside the other species' `compose0` products | – | spec | REJECTED | – | +19 / +47 us on the `SrTiO3` stage gaps | [§3.3][s33] |
| [frc-segmented-f64](#frc-segmented-f64) | Receiver-warp segmented float64 force reduction | – | spec | REJECTED | – | not recorded | [§3.3][s33] |
| [frc-per-atom-energy](#frc-per-atom-energy) | Per-atom energy array instead of atomics (T6) | – | spec | REJECTED | – | +0.5% / +0.1% (5060 Ti) | [§3.3][s33] |
| [i0-bwd-rcv-warp-agg](#i0-bwd-rcv-warp-agg) | Warp-aggregate receiver `atomicAdd`s in `tabled_outer_sum0_backward_kernel` | – | spec | NOT BUILT | – | untried (1-2 receivers/warp -> ~2x fewer force atomics) | `OMAT0_SPEEDUP_BRIEF.md` |

### GEMMs and the autotune

| ID | Idea | Switch/flag | Path | Status | Stage | Effect | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [gemm-hybrid-cubin](#gemm-hybrid-cubin) | 3xTF32 hybrid tensor-core GEMM cubins as autotune candidates | `cubins/tf32x3_hyb_sm*.cubin`, `LOUP_NO_HYBRID` | both | DEFAULT (scoped: not for long-range models since S6) | S1 | part of S0 -> S1 | [§3.1 #2][s31] |
| [gemm-autotune](#gemm-autotune) | Time up to 32 cuBLASLt heuristics + 3 hybrid tiles (+ own SGEMM) per shape | `sgemm_rm`, `LOUP_DEBUG_GEMM` | both | DEFAULT | S2 | not recorded alone | [§3.1 #11][s31] |
| [gemm-cold-l2](#gemm-cold-l2) | Operands larger than L2/2 timed with a flushed L2 | – | both | DEFAULT | S3 | Ada `lin1_fwd` group 672 -> 575 us | [§3.1 #18][s31] |
| [gemm-cold-l2-all](#gemm-cold-l2-all) | Every GEMM timed cold | – | spec | REJECTED | S3 | Ada `NbCl5` +2.9% | [§3.3][s33] |
| [gemm-no-split-k](#gemm-no-split-k) | Exclude split-K cuBLASLt algorithms | `REDUCTION_SCHEME_MASK = NONE` | both | DEFAULT | S3 | 5060 Ti idle -120 us per step; deterministic | [§3.1 #22][s31] |
| [gemm-plan-cache](#gemm-plan-cache) | Persistent per-GPU plan cache | `LOUP_CACHE_DIR`, `LOUP_RETUNE` | both | DEFAULT | S3; S6 | cold-start `evaluate` 1.3 -> 0.21 s (5060 Ti), 0.76 -> 0.05 s (Ada) | [§3.1 #16][s31], [§3.2 F4][s32] |
| [gemm-own-sgemm](#gemm-own-sgemm) | Own 128 x 128 x 16 `cp.async` SIMT SGEMM as a candidate | `loup::sgemm128` | both | DEFAULT | S5 | 5060 Ti `NbCl5` -1.6% / -2.0% (first version), -1.4% / -1.3% (`cp.async`) | [§3.1 #30][s31] |
| [gemm-own-n192](#gemm-own-n192) | 128 x 64 tiles for N = 192 | – | spec | DEFAULT (tie) | S5 | 7 products 297 -> 248 us; MD tie | [§3.1 #30][s31] |
| [gemm-own-n144](#gemm-own-n144) | `sgemm128_kernel<4, false>` partial-`N` `128 x 64` tiles when `(N % 128) <= 64` (e.g. `N = 144`) | `loup::sgemm128` | both | DEFAULT (5060 Ti only) | S16 | replaces `magma_sgemmEx` on `N = 144` (`POLAR-1-M` `NbCl5` `170.7 -> 76.6 us` in `prof_k`); tie on `M >= 1944` MD | this file |
| [gemm-own-sgemm64](#gemm-own-sgemm64) | Own `64 x 64 x 16` `cp.async` SIMT SGEMM (`128` threads) scoped to `M <= 1600` | `loup::sgemm64`, `DiskPlan::use_own == 2` | both (`M <= 1600`) | DEFAULT (5060 Ti only) | S16 | fresh-plan ABBA: `POLAR-1-S` `NaCl216` `1.85 -> 1.61 ms` (`0.873`), `POLAR-1-M` `NaCl216` `4.30 -> 3.61` (`0.839`), `POLAR-1-L` `NaCl216` `8.24 -> 7.22` (`0.876`), `MH-1` `NaCl216` `1.71 -> 1.57` (`0.919`), `OFF23-M` `water216` `1.39 -> 1.30` (`0.938`), `MH-1` `NbCl5` tie (`1.0002`) | this file |
| [gemm-own-sgemm32](#gemm-own-sgemm32) | Own `32 x 32 x 16` `cp.async` SIMT SGEMM (`64` threads) + deterministic split-K (`1, 2, 4`) into per-stream `4 MB` workspace, scoped to `sm_120` and `M <= 1600` | `loup::sgemm32`, `DiskPlan::use_own` in `3..5` | both (`sm_120`, `M <= 1600`) | DEFAULT (5060 Ti only) | S17 | fresh-plan ABBA: `POLAR-1-S` `NaCl216` `1.65 -> 1.50 ms` (`0.909`), `POLAR-1-M` `NaCl216` `3.70 -> 3.46` (`0.936`), `POLAR-1-L` `NaCl216` `7.28 -> 6.89` (`0.947`), `MH-1` `NaCl216` `1.61 -> 1.53` (`0.948`), `MH-1` `NbCl5` tie (`1.003`) | this file |
| [gemm-own-narrow-n](#gemm-own-narrow-n) | Extend `sm_120` `sgemm64` (`N <= 64` or `M <= 2500 && N <= 160`) and `sgemm32` (`N <= 32` or `M <= 2500 && N <= 160`) to narrow-`N` GEMMs above `M = 1600` | `src/engine.cu` | both (`sm_120`) | DEFAULT (5060 Ti only) | S18 | fresh-plan ABBA: `POLAR-1-M` `NbCl5` `24.66 -> 24.48 ms` (`0.9925`), `MH-1` `NbCl5` `12.62 -> 12.51` (`0.9907`), `OFF23-M` `water` tie (`1.0009`), `OMAT-0-S` `SrTiO3` tie (`1.0001`) | this file |
| [gemm-own-raster](#gemm-own-raster) | Own SGEMMs rasterised with `N` tiles fastest (`blockIdx.x` = `N` tile, `blockIdx.y` = `M` tile) so the `N` tiles of one `A` row block are issued together (observed better cold-`A` reuse; issue order is not guaranteed); `sgemm128` only when `is_sm120` (`n_fastest` argument), `sgemm64/32` are `sm_120`-only already | `src/sgemm.cu` (`sgemm128/64/32`), `sgemm128(..., n_fastest)` | both (`sm_120`) | DEFAULT (5060 Ti only) | S20 | cold `13608x512x512` `529 -> 425 us`; ABBA `MH-1` `NbCl5` `0.977`, `POLAR-1-M` `NbCl5` `0.987`, `OMAT-0-M` `0.989`, `OFF23-M` water `0.993` | this file |
| [gemm-own-sgemm64-unscoped](#gemm-own-raster) | `sgemm64` candidate for every shape on `sm_120` once rasterised | – | both | REJECTED | S20 | ABBA `MH-1` `NbCl5` `1.008`, `POLAR-1-M` `NbCl5` `1.012`, `OMAT-0-S` `0.992`, `POLAR-1-S` `1.007` | this file |
| [gemm-own-n96](#gemm-own-n96) | `128 x 96` own-SGEMM tile (`8 x 6` outputs per thread) for `N = 96` (C = 96 models), which ran `sgemm128_kernel<8>` with a quarter of its FMAs on padding columns | `sgemm96_kernel` inside `sgemm128(..., n_fastest = is_sm120)` | both (`sm_120`, `N = 96`) | DEFAULT (5060 Ti only) | S38 | microbench `0.79-0.84` per `N = 96` shape (bit-identical); ABBA `OFF23-S` water `0.9866` / `0.9758` (new / old, both orders) | this file |
| [gemm-own-n112](#gemm-own-n96) | `128 x 112` own-SGEMM tile (`8 x 7` outputs per thread) for `N = 224` (OFF23-L) and `N = 208` (MH-1), which run two padded 128-wide tiles (12.5% / 19% padding) | – | both | REJECTED (falsifier, 5060 Ti only) | S39 | standalone, traced shapes: `0.929-0.955` (bit-identical), below the 10% stop rule | this file |
| [gemm-sgemm-variants](#gemm-sgemm-variants) | 4 stages BK = 8; register-staged BK = 8; 1 block / SM; extra 64 x 128 / 128 x 64 tiles | – | spec | REJECTED | S5 | 5-50% slower, or `NbCl5` +0.8% to +1.8% in the pass | [§3.3][s33] |
| [gemm-issue-rate](#gemm-issue-rate) | Own-SGEMM issue rate on `sm_120`: serpentine FFMA column order for operand reuse; packed `f32x2` FMA | – (scratch) | gen + spec (`sm_120`) | REJECTED (5060 Ti only) | S53 | limiter (`sgemm128`, full waves): FFMAs without operand reuse (3 register-file reads) precede 8.8 vs 3.5 dispatch-stall samples; `sgemm64` at `M = 648`: fill (0.61 waves) and shared-memory latency (short scoreboard), the reuse effect small; serpentine `sgemm128` `+3-5%` (ptxas reschedules: no-reuse FFMAs 227 -> 185 of 1,024); `fma.rn.f32x2` lowers to two FFMAs on `sm_120` (native `FFMA2` on `sm_100a` only) | this file |
| [gemm-pretransposed](#gemm-pretransposed) | Pre-transposed forward weights (old idea 1) | – | spec | REJECTED | – | 5060 Ti tie, Ada +1.0% / +0.3% | [§3.3][s33] |
| [gemm-grouped-species](#gemm-grouped-species) | One grouped species GEMM for `compose0_fwd` + `skip16` (T4) | `fm_tf32x3_species_rr_64x64` | spec | REJECTED | – | 5060 Ti +1.7% / +0.8% | [§3.3][s33] |
| [gemm-row-chunked](#gemm-row-chunked) | Hybrid GEMM per quarter-L2 row chunk for cold operands | – | spec | REJECTED | – | never chosen by the autotune | [§3.3][s33] |
| [gemm-group-policy](#gemm-group-policy) | Own-SGEMM policy timed per fork group in context | – | spec | REJECTED | S5 | 5060 Ti `NbCl5` -0.4% to -0.8%, `SrTiO3` +0.1% / +0.2%, Ada tie | [§3.3][s33] |
| [gemm-split-k-own](#gemm-split-k-own) | Split-K own SGEMM for small systems | – | spec | REJECTED | S5 | 135 atoms: GEMM groups 123 -> 147 / 158 us | [§4.1 #3][s41] |
| [gemm-grouped-launch](#gemm-grouped-launch) | A fork group's small products in one own-SGEMM launch | – | spec | REJECTED | S5 | 135 atoms step 355 -> 345 us; benchmarks +0.2% to +1.2% | [§4.1 #3][s41] |
| [gemm-skip16-overlap](#gemm-skip16-overlap) | `skip16` GEMMs overlapped across the spline | – | spec | REJECTED | – | not recorded | [§3.3][s33] |
| [gemm-simt-for-lr](#gemm-simt-for-lr) | Float32 SIMT GEMMs only for long-range models | `GenericModel::has_lr` | POLAR | DEFAULT (scoped: POLAR) | S6 | gate: Ada POLAR-S / -L failures -> all pass; cost +0% to +7% | [§5.4][s54] |
| [gemm-tc-rounded-polar](#gemm-tc-rounded-polar) | Round the TF32 split; isolate big/cross MMA partials before FP32 accumulation | `LOUP_TC_SPLIT_RN`, `LOUP_TC_ACC_RN` (build flags, default 0) | POLAR experiment | EXPERIMENTAL; FP32 default retained | S71 | split bias reduced; corrected-reference force/stress failures still prevent adoption | this file |
| [gate-polar-fixed-kset](#gate-polar-fixed-kset) | Hold reciprocal integer indices fixed in POLAR stress finite differences | historical reference cache format 2 | correctness gate | RETAINED FD DIAGNOSTIC | S71 | two stress jumps traced to cutoff membership changes; production target superseded by strain autograd | this file |
| [gate-polar-strain-autograd](#gate-polar-strain-autograd) | Differentiate native POLAR energy through complete strained geometry | reference cache format 3 | correctness gate | REFERENCE FIX | S71 | removes fixed-step FD truncation without changing the FP32 yardstick or 3x limit | this file |
| [a100-own-ext-nb-groups](#a100-own-ext-nb-groups) | The `sm_120` own-SGEMM extensions and lane-group neighbour kernels on compute capability 8.0 (A100); `LOUP_FORCE_TC=1` test override | `LoupHandle::own_ext` / `nb_groups_ok` (`LOUP_OWN_EXT=0\|1`, `LOUP_NB_GROUPS=0\|1`), `force_tc` | both | lane groups DEFAULT on cc 8.0 (S80); own-SGEMM extensions on cc 8.0 only without a GEMM cubin (long-range models, S84) | S70, S80, S84 | S80 in-process A/B on the S78 tree (side 1 = noise), lane groups / own extensions: OFF23-S water216 `0.843` / `1.034` (noise `1.020`), OFF23-M water216 `0.885` / `0.994`, MH-1 NaCl216 `0.965` / `0.969`, POLAR-1-M NaCl216 `1.005` / `0.924`, OMOL-0 water216 `0.990` / `1.008`, OMAT-0 generic SrTiO3 `0.995` / `0.998`; library ABBA, lane groups by default: OFF23-S water216 `0.830`, OFF23-M `0.914`, OFF24-M water `0.982`; own extensions on POLAR (S84): S / M / L NaCl216 `0.870` / `0.959` / `0.926`; library ABBA s81 -> s84 with the dot fold (S84c): `0.795` / `0.802` / `0.814` | [below](#a100-own-ext-nb-groups) |
| [a100-cc80-defaults](#a100-cc80-defaults) | Compute capability 8.0 (A100) defaults: the generic chain fold and species tables (S57 / S59 / S73), and LoupMD's own format-2 six-tile beta cubin `gemm_tc_hyb_sm80.cubin` instead of FastMACE's three-tile `tf32x3_hyb_sm80.cubin` | `folds_measured_here()` (`src/generic.cu`), `HybCubin::init` cubin name (`src/engine.cu`); `LOUP_CHAIN_FOLD=0`, `LOUP_SPECIES_TABLES=0`, `LOUP_HYBRID_CUBIN` override | both (cubin) / gen (folds) | DEFAULT (A100) | S77 | A100 in-process, new / old: OMOL-0 water216 `0.752`, MH-1 NaCl216 `0.875`, MH-1 SrTiO3 `0.889`, MPtrj SrTiO3 `0.935`, OFF23-M water216 `0.959`, OMAT-0 generic SrTiO3 `0.977`, MP-0 SrTiO3 `0.979`, OMAT-0 specialised SrTiO3 `0.998`; 3x gates pass on all 19 non-POLAR family runs | [below](#a100-cc80-defaults) |
| [gen-gate-epilogue](#gen-gate-epilogue) | Gate forward fused into the `W_2` GEMMs' A load (`A = G * (lin * s)` transformed in shared memory; `gout0` and gates `G` from a pre-pass); S54: backward writing one gradient instead of `dpre` and `dlin = dpre * s` | – | gen | REJECTED (falsifiers, 5060 Ti only) | S36, S54 | microbench, MH-1 shapes (`N = 5,000`, `C = 512`, random data): gate + 4 GEMMs `3,800 us` (best of own / cuBLAS per `l`) -> fused `3,594` (`0.946`, stop rule `<= 0.90`); bit-exact. S54 bound (duplicate writes skipped, timing only): `gate_bwd` `-3%` to `-9%` | this file |
| [gen-gate-bwd-epilogue](#gen-gate-bwd-epilogue) | Gate backward in the epilogue of the `W_2^T` GEMMs: own `sgemm128` row tiles of whole atoms (128 / 126 / 125 / 126 rows for l = 0..3), the C tile staged in shared memory, `gate_bwd_kernel`'s per-degree arithmetic in its order, per-block dD partials; `dgout_l` never written | `sgemm128_kernel<8, true, true, 2l + 1>` (`sgemm128_gate`), `gemm_gate` (only where the tuned plan is the own N-fastest `sgemm128`; otherwise the plain GEMM and `gate_bwd_kernel`); `LOUP_GATE_FUSE=0` disables | gen (kind 4: MH-1, OMOL-0, POLAR-1) | DEFAULT (sm_120: the plan condition keeps it there) | S137 | `W_2^T` + gate span 9,457 -> 7,153 us per step (MH-1 SrTiO3; `gate_bwd`'s 3,697 us gone); library ABBA MH-1 SrTiO3 `0.9446`, NaCl216 `0.9869`, POLAR-1-M NbCl5 `0.9647`, POLAR-1-L NaCl216 `0.9955` | this file |
| [gen-gate-fwd-store](#gen-gate-fwd-store) | Layer 0's residual-free degrees 1-3 stored gated (`gout_l = g (lin_l s)`) by their projection's epilogue, the l = 0 projection first (it holds the gate logits); the reverse through the saved `v` (`d pre0 = (1 - sigmoid) sum dgout v`, `dD += -beta s sum dgout v`) | `sgemm128_kernel<8, true, true, 2l + 1, true>`, the `fused` / `vform` masks of `gate_fwd_kernel` / `gate_bwd_kernel`; `LOUP_GATE_FUSE_FWD=0` disables | gen (layer 0 with the S59 species table: MH-1, OMOL-0) | DEFAULT (sm_120) | S137 | layer-0 forward span 5,064 -> 4,371 us per step, its `gate_fwd` 1,031 -> 85 us; ABBA on top of the backward fusion MH-1 SrTiO3 `0.9911`; both against S129: MH-1 SrTiO3 `0.9342` (32.77 -> 30.62 ms), OMOL-0 XL water216 `0.9633`, MH-1 NaCl216 tie | this file |
| [gemm-cold-l2-ada-fix](#gemm-cold-l2-ada-fix) | Fix Ada `22 MiB < L2/2` cold-L2 rule for `lin1_fwd l=1` + wider 3xTF32 `mma` tiles | – | both | NOT BUILT | – | untried (`lin1_fwd l=1` timed hot on Ada despite 97 MB `m1`) | `OMAT0_SPEEDUP_BRIEF.md` |
| [gemm-dual-pipe-lanes](#gemm-dual-pipe-lanes) | Forked GEMM lanes forced onto the tensor-core cubin while the other lanes stay on SIMT, so both pipes work at once | lab `LOUP_LAB_TC_LANES` mask (reverted) | spec, gen (OMAT-0 medium) | REJECTED (5060 Ti only) | S141 | every mask slower: generic path +0.5% (one lane) to +5.8% (all lanes), specialised +1.8% to +5.3% | this file |

### Scheduling, memory and edge data

| ID | Idea | Switch/flag | Path | Status | Stage | Effect | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [sched-side-streams](#sched-side-streams) | GEMM fork / join on 8 side streams with own workspaces | – | both | DEFAULT | S2 | serialising them costs +2.0% to +5.7% | [§3.1 #9][s31], [§3.3][s33] |
| [sched-serialised](#sched-serialised) | GEMM groups serialised (check of the above) | – | spec | REJECTED | – | 5060 Ti +5.7% / +5.0%, +2.1% / +2.0% | [§3.3][s33] |
| [sched-reversed-order](#sched-reversed-order) | Kernels between GEMMs walk receivers from the top (L2 reuse) | – | spec | REJECTED | – | step span 8,274 -> 8,285 us | [§3.3][s33] |
| [mem-aliasing](#mem-aliasing) | Gradient buffers alias forward ones (`dm1 -> m1`, `dh0 -> h0`, `dS0 -> S0`) | – | spec | DEFAULT | S3 | not recorded alone | [§3.1 #16][s31] |
| [mem-inplace-s110](#mem-inplace-s110) | `db` written over `b` (`sc1_fused`), `dm0` over `m0` (`sc0_backward`); rebuild temporaries as views of `tmp_vec_len` / `edge_force_1`; dead `y1` dropped | – | spec | DEFAULT (5060 Ti only) | S110 | VRAM `SrTiO3` 5,000 atoms 658 -> 542 MiB, 40,000 atoms 3,632 -> 2,840 MiB (93.0 -> 72.7 KiB/atom); MD a-b-b-a 1.0001 / 0.9968; gate passes | this file |
| [mem-b-in-s0](#mem-b-in-s0) | `b` / `db` in the S0 regions of the zero slab (S0 is dead from the C0 GEMMs to the dS0 GEMMs); one-species bundles get 128-float S0 rows | – | spec | DEFAULT (5060 Ti only) | S111 | VRAM `SrTiO3` 5,000 atoms 542 -> 498 MiB, 40,000 atoms 2,840 -> 2,524 MiB; MD a-b-b-a over six rounds `NbCl5` 0.9994-1.0056 (mean 1.0016), `SrTiO3` 0.9975-1.0002 (mean 0.9992) | this file |
| [mem-m1-chunks](#mem-m1-chunks) | `m1` / `dm1` in receiver chunks of <= 8,192 above 16,384 atoms, two alternating buffers; odd chunks' spline / `w'` on a second stream, lin1 GEMMs on lanes 0-3 overlapping the next chunk | `LOUP_M1_CHUNK` (testing) | spec | DEFAULT (5060 Ti only) | S112 | VRAM `SrTiO3` 40,000 atoms 2,524 -> 2,060 MiB; 40k MD a-b-b-a over seven rounds mean 1.0006 (0.9996-1.0015); one-stream pipeline +0.18%, serial chunks +0.29% | this file |
| [mem-l1-carveout](#mem-l1-carveout) | Per-arch smallest carveout keeping occupancy | `tune_l1` | both | DEFAULT | S3 | i0 forward 305 -> ~250 us at 64 KB (5060 Ti) | [§3.1 #17][s31], [§2.5][s2] |
| [edge-packed](#edge-packed) | Packed edge arrays (`float4` x, y, z, r; `float2`) | `act_vec_len`, `act_t_sx` | both | DEFAULT | S3 | not recorded alone | [§3.1 #13][s31] |
| [edge-sh-coalesced](#edge-sh-coalesced) | Coalesced SH stores in `scatter_active_edges` | – | spec | SUPERSEDED | S3 | superseded by edge-sh-recompute | [§3.1 #19][s31] |
| [edge-sh-recompute](#edge-sh-recompute) | SH computed where staged, never stored | `edge_sh16` | spec | DEFAULT | S3 | -24 MB of stores per step; `scatter_active_edges` 0.11-0.16 -> 0.05 ms | [§3.1 #24][s31], [§2.5][s2] |
| [edge-row-receiver](#edge-row-receiver) | Candidate-edge list without per-edge receiver and pair index: row i holds receiver i's edges, `scatter_active_edges` takes the receiver from the row and recomputes `sym_pair` | – | both | DEFAULT (5060 Ti only) | S113 | -8 B per edge slot: VRAM `SrTiO3` 5,000 atoms 498 -> 490 MiB, 40,000 atoms 2,060 -> 2,020 MiB; MD a-b-b-a `NbCl5` 0.9993, `SrTiO3` 0.9978 | this file |
| [edge-compaction-1pass](#edge-compaction-1pass) | Single-pass active-edge compaction (decoupled look-back) | – | spec | REJECTED | – | kernel 96 -> 80 us; MD tie | [§3.3][s33] |
| [mem-reorder](#mem-reorder) | Morton reorder within species groups every 16th rebuild, above L2 | `LOUP_REORDER` | both | DEFAULT (scoped: N x 4 KB > L2) | S2 | part of S1 -> S2 | [§3.1 #8][s31] |
| [mem-reorder-small](#mem-reorder-small) | Morton reorder below L2 size | – | spec | REJECTED | – | not recorded | [§3.3][s33] |
| [mem-shift-cart](#mem-shift-cart) | Cartesian float64 shifts precomputed at rebuild | `d_shift_cart` | both | DEFAULT | S2 | removes the cell from the force graph | [§3.1 #7][s31] |
| [mem-l2-persist-x](#mem-l2-persist-x) | CUDA Graph `AccessPolicyWindow` (~10-12 MiB) on `x0`+`x1` in `spline`/`w'` | – | spec | NOT BUILT | – | untried (`x0+x1` = 9.77 MiB on `SrTiO3`; check `ncu` hit rate first) | `OMAT0_SPEEDUP_BRIEF.md` |
| [mem-l1-carveout-retune](#mem-l1-carveout-retune) | Re-check `tune_l1` shared/L1 carveouts on `w'` and `i0_bwd` after items 23-31 | `tune_l1` | spec | NOT BUILT | – | untried (carveouts tuned before later kernel rewrites) | `OMAT0_SPEEDUP_BRIEF.md` |

### Neighbour list, integrator and MD loop

| ID | Idea | Switch/flag | Path | Status | Stage | Effect | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [nl-bucketing-sort](#nl-bucketing-sort) | Edge grid rounded to 8,192; `cub::DeviceSegmentedSort` | – | both | DEFAULT (bucketing; sort replaced in S75) | S1-S2 | rebuild sort ~2.3 ms -> ~16 us | [§3.1 #3][s31] |
| [nl-f32-pretest](#nl-f32-pretest) | Float32 pre-test, float64 re-check of borderline pairs; 32-thread blocks (T3) | – | both | DEFAULT | S3 | rebuild 1,222 -> 510 us (5060 Ti), 1,121 -> 684 us (Ada) | [§3.1 #15][s31] |
| [int-langevin-32](#int-langevin-32) | Langevin first half in 32-thread blocks; counter folded into the second half | – | both | DEFAULT | S3 | first half 14.9 -> 8.0 us (`NbCl5`) | [§3.1 #26][s31] |
| [md-evaluate-reuse](#md-evaluate-reuse) | Non-destructive `evaluate()` reusing the list | – | both | DEFAULT | – | not recorded | [§3.1 #10][s31] |
| [md-adaptive-pipeline](#md-adaptive-pipeline) | Start unpipelined, pipeline once the step displacement allows | `LoupMDStats::dangerous_builds`, `pipelined_steps` (removed) | both | SUPERSEDED (S75) | S6 | MD unchanged; dangerous builds 1 / ~1,600 steps -> 0 with a 3-step margin | [§3.2 M1, S1][s32], [§5.4][s54] |
| [md-skin](#md-skin) | Larger / adaptive skin (T10) | – | both | PENDING (owner) | – | 0.5-1.5% at 5,000 atoms, ~10% at 135 atoms | [§4.1 #4][s41] |
| [md-graph-reuse](#md-graph-reuse) | MD step graphs kept across run calls; no force pass at the start of a call whose forces are current (release task S1-T03, review item S4) | `LOUP_DEBUG_GRAPHS` reports captures and initial force passes | both | DEFAULT on `release/v1` (5060 Ti only) | release S1-T03 | 100 calls of 10 steps against one call of 1,000 (`SrTiO3`, wall time): 1.113 -> 1.011 / 1.006; standard A/B tie | [§6][s6] |
| [md-disp-decay](#md-disp-decay) | Step-displacement maximum kept for two windows instead of from `set_state` on (release task S1-T11, review item S2) | – | both | SUPERSEDED by the round6 merge's guarded loop (17 Nov; kept for the step-displacement API) | release S1-T11 | one fast step no longer blocks pipelining; water pipelines at skin 1.0 A, not at 0.5 A; standard A/B tie | [§6][s6] |
| [md-thermo-buffer](#md-thermo-buffer) | Thermo rows written on the device inside the captured step (release task S1-T05) | `LoupIntegrator.thermo_every` | both | DEFAULT on `release/v1`, off unless asked (5060 Ti only) | release S1-T05 | `thermo_every = 20` against off: `NbCl5` 1.0005 / 1.0041, `SrTiO3` 1.0003 / 1.0007 | [§6][s6] |
| [rel-stage1-api](#rel-stage1-api) | Release branch, Stage 1 as a whole against its baseline (error channel, `loup_run`, state blob, memory plan, `loup_evaluate2`, per-layer sweeps, open domains) | – | both | DEFAULT on `release/v1` (5060 Ti only) | release Stage 1 | A/B 0.9994 / 1.0006 (baseline first), 0.9986 / 0.9975 (head first): tie | [§6][s6] |
| [rel-merge-r6tip](#rel-merge-r6tip) | Release branch after merging `round6-hardening` `e21faa2` (S64 to S67), against that tip's own build | – | both | DEFAULT on `release/v1` (5060 Ti only) | release Stage 1 | seven A/B: `NbCl5` 1.0030 (0.9946 to 1.0080), `SrTiO3` 0.9997 (0.9965 to 1.0044): tie; generic families 0.9944 to 1.0066 | [§6.1][s61] |
| [lmp-run-style-fixes](#lmp-run-style-fixes) | `run_style loupmd` runs the engine's integrator of the input's fixes (`fix nve`, `nvt`, `npt iso`, `langevin`, `temp/csvr`, `temp/berendsen`, `press/berendsen`, `setforce 0 0 0`, `momentum`) between LAMMPS's output steps | `run_style loupmd` (LAMMPS input) | both | DEFAULT on the local `release/v1` (5060 Ti under WSL 2 only) | release, O40 | run style / the package's own loop 0.996 to 1.012 on 320, 1,080 and 5,000 atoms (NVT, NPT, Langevin); LAMMPS integrating / run style: `fix nvt` 1.27 / 1.12 / 1.04, `fix npt` 1.65 / 1.43 / 1.16 | this file, [§6.37][s637] |
| [eng-evaluate-keeps-md](#lmp-run-style-fixes) | `loup_evaluate` between two blocks of a run launches the force graph and leaves the integrator's step graphs standing (it used to capture the host step over them, and the next block the integrator's again) | – (`evaluate_once`: `keep_md`, `eval_since_run`) | both | DEFAULT on the local `release/v1` (5060 Ti under WSL 2 only) | release, O40 | Langevin on 320 atoms through LAMMPS, output every 1,000 / 100 / 10 steps: 0.600 / 0.617 / 0.920 -> 0.580 / 0.594 / 0.734 ms/step, graph captures 20 / 92 / 884 -> 6 / 6 / 6 (with the next row) | [lmp-run-style-fixes](#lmp-run-style-fixes) |
| [lmp-system-once](#lmp-run-style-fixes) | The LAMMPS pair style sends the system to the engine only when the atomic numbers, masses or skin changed, not at every `run` command (which dropped the list, the tuned plans, the thermostat's state and the noise counter) | – (`PairLoupMD::ensure_system`) | both | DEFAULT on the local `release/v1` | release, O40 | not timed by itself (in the figures of the row above); two `run` commands continue one trajectory (`tests/gpu/test_lammps_run_style.py`) | [lmp-run-style-fixes](#lmp-run-style-fixes) |
| [rel-merge-develop](#rel-merge-develop) | Release branch after merging `develop` `dec2e1f` (S115 to S146: the kernel rounds since `13d6337`, the run-time compiler, one kernel path, the device-resident call, `lammps/`), against `develop`'s own build and against the branch before the merge | – | both | DEFAULT on `merge/develop-s146` (step times 5060 Ti only; tests and gates also on the RTX 4000 Ada) | release, O38 | merged / develop: OMAT-0 medium `SrTiO3` 1.003, 1.001, 1.001, 0.998, OFF23-M water 1.017, 1.003, 0.998, 1.011, five more cases 0.989 to 1.001: ties. Merged / before: 0.980 (OMAT-0 medium), 0.382 (MP-0 medium), 0.859 (POLAR-1-S), 0.976 to 0.986 elsewhere | [§6.36][s636] |
| [md-langevin-target](#md-langevin-target) | Langevin's target temperature as a device scalar that the step advances (release task S3-T06): ramps move it every step, a changed temperature captures no graph | `LoupIntegrator.temp_rate_k_per_step` | both | DEFAULT on `release/v1` (5060 Ti only) | release Stage 3 | A/B 1.0085 / 0.9989 (old first), 0.9943 / 0.9938 (new first): tie | [§6.2][s62] |
| [md-fixed-atoms](#md-fixed-atoms) | Fixed atoms as zero inverse masses; the reported temperature counts 3 (N - n_fixed) (release task S4-T02) | `loup_set_fixed_atoms` | both | DEFAULT on `release/v1` (5060 Ti only) | release Stage 4 | A/B mean of four 1.0032 / 0.9995: tie; no step kernel changed | [§6.3][s63] |
| [md-fix-com](#md-fix-com) | Centre of mass at rest: Langevin's noise in two passes without its mass-weighted mean, NVE's momentum removed at a call's start; noise coefficients formed once per step (release task S4-T01) | `LoupIntegrator.fix_com` | both | DEFAULT on `release/v1` for `lm.md` / `lm.Simulation`; off in `loup_run_langevin` (5060 Ti only) | release Stage 4 | current build against the merge build, four A/B: 0.9999 / 0.9982: tie; `fix_com` on against off 1.0009 at 5,000 atoms | [§6.4][s64] |
| [md-csvr](#md-csvr) | CSVR (Bussi) as three small nodes before a velocity-Verlet step; the integrator's scalars travel in the state block (release task S4-T03) | `LOUP_CSVR`, `lm.integrators.CSVR` | both | DEFAULT on `release/v1` for CSVR runs (5060 Ti only) | release Stage 4 | CSVR against Langevin 1.0029 at 5,000 atoms; the benchmark's Langevin step unchanged (four A/B: 0.9991 / 1.0032) | [§6.5][s65] |
| [md-skin-auto](#md-skin-auto) | The neighbour skin chosen from the largest per-step displacement, so that light atoms run in the pipelined loop (owner's decision O17) | `skin="auto"`, `loup_get_step_displacement` | both | DEFAULT on `release/v1` for `lm.md`, `loupmd md` and the ASE drop-ins; the engine's default stays 0.5 A (5060 Ti only) | release Stage 3 | water 216, OFF23 small: 0.676 -> 0.556 ms/step (0.82); 0 -> 799 of 800 steps pipelined | [§6.5][s65] |
| [md-nose-hoover](#md-nose-hoover) | Nose-Hoover chain: per half step one kinetic-energy sum, one single-thread kernel and one velocity scale (release task S4-T04) | `LOUP_NHC`, `lm.integrators.NoseHooverChain` | both | DEFAULT on `release/v1` for Nose-Hoover runs (5060 Ti only) | release Stage 4 | against Langevin 1.0067 at 5,000 atoms; the benchmark's Langevin step unchanged (0.9995 / 0.9993 against the build before CSVR) | [§6.6][s66] |
| [md-berendsen-nvt](#md-berendsen-nvt) | Berendsen NVT: one scale per step from the kinetic energy (release task S4-T05) | `LOUP_BERENDSEN_NVT`, `lm.integrators.Berendsen` | both | DEFAULT on `release/v1` for Berendsen runs (5060 Ti only) | release Stage 4 | cost against Langevin not measured (two small nodes fewer than the Nose-Hoover step) | [§6.6][s66] |
| [min-lbfgs-device](#min-lbfgs-device) | LBFGS on the device (`loup_minimize`, owner's decision O15): history on the device, one host wait per step, the list check of a small step after the force pass | `loup_minimize`, `LOUP_MIN_AHEAD=0|1` (testing) | both | DEFAULT on `release/v1` for LBFGS at fixed cell (5060 Ti only) | release Stage 4 | optimiser's own time at 5,000 atoms 17% of the force calls (host) -> 9.70% (device, two waits and pageable copies) -> 1.71%; a step 10.7 -> 9.1 -> 8.2 ms | [§6.6][s66] |
| [md-variable-cell](#md-variable-cell) | The variable-cell step: the cell on the device, Cartesian shifts formed per step, stress in every force pass, list check against the deformed reference; not pipelined (release task S4-T06) | `LOUP_VARIABLE_CELL=1`, `LOUP_DEBUG_CELL_RATE` (testing); the NPT integrators | both | DEFAULT on `release/v1` for runs with a barostat (5060 Ti only) | release Stage 4 | against the pipelined fixed-cell step at 5,000 atoms 1.026 to 1.030; the fixed-cell benchmark unchanged (generic 0.9998 to 1.0015) | [§6.7][s67] |
| [md-berendsen-npt](#md-berendsen-npt) | Berendsen NPT in the variable-cell step, hydrostatic or per axis, one force call per step (release task S4-T07) | `LOUP_BERENDSEN_NPT`, `lm.integrators.Berendsen(pressure_GPa=...)` | both | DEFAULT on `release/v1` for Berendsen NPT runs; experimental (5060 Ti only) | release Stage 4 | its step time is not measured (the variable-cell step plus three small nodes) | [§6.7][s67] |
| [md-baoab-npt](#md-baoab-npt) | Langevin BAOAB NPT in the variable-cell step: one thread for the barostat and the step's matrices, one kernel per atom for B, A, O, A (release task S4-T08) | `LOUP_BAOAB_NPT`, `lm.integrators.LangevinBAOAB`, `lm.md(ensemble="NPT")` | both | DEFAULT on `release/v1` for NPT runs; experimental (5060 Ti only) | release Stage 4 | its step time is not measured (the variable-cell step plus two small nodes) | [§6.8][s68] |
| [md-mtk-npt](#md-mtk-npt) | MTK NPT in the variable-cell step: both Nose-Hoover chains, the cell kick and the step's matrices by one thread per half step (release task S4-T09) | `LOUP_MTK_NPT`, `lm.integrators.MTK` | both | DEFAULT on `release/v1` for MTK runs; experimental (5060 Ti only) | release Stage 4 | its step time is not measured (the variable-cell step plus six small nodes) | [§6.8][s68] |
| [md-small-systems](#md-small-systems) | Small-system latency (< ~1,000 atoms) | – | spec | NOT BUILT (open) | – | 135 atoms: GEMM groups 32% of 358 us | [§4.1 #3][s41] |
| [comp-active-edge-tighten](#comp-active-edge-tighten) | Tighten active-edge compaction (`compute_and_count_active` + `scatter_active_edges`) | – | both | NOT BUILT | – | untried (101 us/step on `SrTiO3` 5060 Ti, `tmp_vec_len` round-trip) | `OMAT0_SPEEDUP_BRIEF.md` |
| [nl-lane-groups](#nl-lane-groups) | Neighbour count / fill with 8 lanes per atom (neighbouring bins split round-robin; fill keeps the exact row order via per-bin offsets in shared memory) | `kNeighborLanes`, `count/fill_neighbors_kernel`; other GPUs `*_scalar_kernel` | both (`sm_120`) | DEFAULT (5060 Ti only) | S34 | per rebuild `SrTiO3` 433 -> 292 us, `NbCl5` 284 -> 110, water 439 -> 302; ABBA `OFF23-S` water `0.9945` / `0.9856`, `OFF23-M` `0.9961` / `0.9943`, `OMAT-0-S` `0.9961` / `0.9972` | this file |
| [nl-lane-groups-variants](#nl-lane-groups) | Lane groups striding the slots of each bin (ballot compaction); bins split by lane with lane-major row order | – | both | REJECTED | S34 | slot split: 4x instructions, slower (count 184 -> 292 us); lane-major order: faster (count + fill 492 -> 297 us) but changed the order of equal-key edges, failing `test_replicated_cell...[MACE-POLAR-1-S]` (`dF` 3.25e-3 > 3e-3, deterministic) | this file |
| [nl-single-readback](#nl-single-readback) | One host round trip per rebuild instead of two: fill / sort / gather / check over the current edge capacity with `row_ptr` clamped to it, then edge count and order flag read together (overflow: grow, rescan, old path) | – | both (`sm_120`) | REJECTED (5060 Ti only) | S35 | `nsys` rebuild span (water) 657 -> 544 us at equal GPU busy time, but untraced round trip only ~49 us: ABBA new / old, both orders: `OFF23-S` water `1.0016` / `0.9990`, `OFF23-M` `0.9970` / `1.0019`, `OMAT-0-S` `1.0011` / `1.0006` (ties) | this file |
| [md-wait-value](#md-wait-value) | Unpipelined step: force graph queued behind `cuStreamWaitValue32` on a host-mapped flag, released by the host after the skin check, instead of `memcpy` + sync + launch | – | both | REJECTED (falsifier, 5060 Ti only) | S37 | standalone: saves 82-105 us of the 155-174 us round trip per step without a rebuild; no safe rebuild branch (a queued graph cannot be cancelled and may hold freed edge buffers), so projected <= ~1.5% on `OFF23-S` water | this file |
| [md-guarded-loop](#md-guarded-loop) | One exact MD loop: each step graph ends with a guard kernel (skin-check flag to mapped host memory) and an IF node holding the force pass, so the host queues the next step while it runs; host reads poll mapped memory instead of synchronising; rebuild order flag read later behind a checked-rest IF node | `run_md_loop`, `guard_step_kernel`, `rest_guard_kernel`, `publish_kernel` / `wait_published` | both | DEFAULT | S75 | 5060 Ti ABBA new / HEAD: `OFF23-M` water216 `0.800`, `OFF23-S` water216 `0.700`, `OFF24-M` water `0.961`, `MH-1` `NaCl216` `0.990`, `OMAT-0` `NbCl5` / `SrTiO3` `0.994` / `0.998`; A100 water216 in-process 6-9% (polling), the conditional step a tie | this file |
| [nl-row-sort](#nl-row-sort) | Neighbour rows sorted (bitonic on `key << 32 \| fill position`, one block per row), gathered and order-checked in one kernel instead of `cub::DeviceSegmentedSort` (a host round trip) + gather + check | `sort_gather_rows_kernel`, `sort_gather_rows_global_kernel` (`LOUP_ROW_SORT=global`), `max_degree_kernel` | both | DEFAULT | S75 | same row order as the stable sort (host check, 0 mismatches); with the checked rest: `OFF23-M` / `OFF23-S` water216 `0.933` / `0.864`, `OFF24-M` water `0.971` | this file |
| [md-device-rebuild](#md-device-rebuild) | Neighbour rebuild inside the MD step graph: the guard's second IF node runs bin + count + a gate kernel (edge count, longest row: within the captured sizes?) and then fill + sort + commit + the checked rest, without a host round trip; when the new list does not fit, the host finishes from the counted rows and recaptures | `run_md_loop` (`capture_ifs`, `rebuild_gate_kernel`), `nl_bin` / `nl_count` / `nl_fill` / `nl_commit` / `nl_finish`; `LOUP_MD_REBUILD=host\|fallback` (tests) | both | DEFAULT | S76 | 5060 Ti ABBA over S75: `OFF23-M` water216 `0.939`, `OFF23-S` water216 `0.862`, `OFF24-M` water `0.992`, `MH-1` `NaCl216` `0.998`, `OMAT-0` `SrTiO3` `0.998` | this file |
| [md-langevin-draw-threads](#md-langevin-draw-threads) | Langevin first half with one thread per normal pair (three per atom, the same Philox words), each thread then updating one component, instead of one thread drawing all three pairs | `src/integrator.cu` `langevin_first_half_kernel` (96 threads per 32 atoms) | both | DEFAULT | S106 | kernel 7.8 -> 3.6 us (water216); ABBA over S105 POLAR-1-S `NaCl216` `0.990`, OMAT-0 generic `SrTiO3` `0.997` (both orders), the rest ties; noise bitwise unchanged | this file |
| [nl-bin-skip](#nl-bin-skip) | Lane-group neighbour count / fill: a bin whose lower distance bound (lattice-plane distances per axis; their root sum of squares in an axis-aligned orthogonal cell) reaches the float pre-test radius `r_hi` is skipped before its image shift and candidates; the same rows in the same order | `src/neighbors.cu` `scan_neighbor_bins` | both (lane-group kernels: sm_120 and cc 8.0) | DEFAULT (5060 Ti only) | S120 | `nsys` count + fill per MD step: OFF23-S water216 21.4 -> 20.1 us (-6%), OFF23-M water216 -4%, OFF24-M water -1%; library ABBA OFF23-S water216 `0.988`, OFF23-M `0.996` (both orders, small); forces at noise (NbCl5's non-orthogonal cell included); gates pass | this file |
| [eng-evaluate-one-graph](#eng-evaluate-one-graph) | `loup_evaluate` as one captured graph per call: positions and results through page-locked staging, the upload, skin check, guard, force pass or on-device rebuild and the downloads in the MD loop's step graph (kind 3), the host polling two publications instead of blocking transfers and a stream synchronisation | – (`run_md_loop` kind 3, `queue_results`) | both | DEFAULT (5060 Ti under WSL 2 only) | S145 | OFF23-S water216: 0.95-1.14 -> 0.41-0.51 ms per call (Python, same job); LAMMPS `pair_style loupmd` 0.87 -> 0.57-0.59 ms/step | this file |
| [eng-device-io](#eng-device-io) | `loup_compute_device`: an evaluation on the caller's device arrays (rows in any order by atom id, any strides, forces added), queued behind the caller's stream and handed back through an event; the external step of the MD graph (kind 2, no integrator) | – (new entry point; `LoupEngine.compute_device`) | both | DEFAULT (new call) | S145 | forces / energy / virial equal `loup_evaluate`'s (tests/test_device_io.py); used by `pair_style loupmd/kk` | this file |
| [eng-run-graph-reuse](#eng-run-graph-reuse) | `loup_run_nve` / `loup_run_langevin` reuse the captured MD graphs when called again with the same step, thermostat and seed (they were re-captured in every call) | – | both | DEFAULT | S145 | not timed on its own; with it `run_style loupmd` in blocks of 100 steps runs water216 NVE at 0.376 ms/step (the engine's Langevin loop in 256-step blocks: 0.34-0.36) | this file |
| [lmp-styles](#lmp-styles) | LAMMPS package ML-LOUPMD (`lammps/`): `pair_style loupmd` (host arrays), `loupmd/kk` (Kokkos device views), `run_style loupmd` (the engine integrates between output steps) | LAMMPS input | both | MEASUREMENT (new interface; 5060 Ti under WSL 2 only) | S145 | OMAT-0 medium SrTiO3 5,000 / 320 atoms, ms/step: run style 7.84-7.86 / 0.61-0.63, `loupmd` 8.20 / 0.86-0.90, `loupmd/kk` 8.38-8.45 / 1.29-1.38, Symmetrix foundation float32/kk 13.47-13.54 / 1.55-1.59 | `LAMMPS_KOKKOS_PLAN.md` |
| [lmp-kokkos-wsl-cost](#lmp-styles) | LAMMPS-Kokkos's own per-step cost on this machine (WSL 2): zero-strength LJ on 648 atoms, `fix nve/kk` + `fix langevin/kk` | – | – | MEASUREMENT | S145 | 2.43 ms/step (`neigh_modify check no`: 0.52; plain LAMMPS 0.115): several blocking host-GPU exchanges per step at 0.1-0.2 ms each | [lmp-styles](#lmp-styles) |
| [lmp-kk-occasional-list](#lmp-styles) | `pair_style loupmd/kk` requests an occasional neighbour list (never built), so that LAMMPS-Kokkos keeps its displacement check and bond topology on the device | – (`PairLoupMDKokkos::init_style`) | – | DEFAULT (5060 Ti under WSL 2 only) | S145 | OMAT-0 medium SrTiO3, benchmark protocol, separate jobs: 320 atoms 1.29-1.38 -> 0.97-1.03 ms/step, 5,000 atoms 8.38-8.45 -> 8.14-8.19; fixes an abort of `fix rigid/small` in bonded systems under Kokkos | [lmp-styles](#lmp-styles) |
| [eng-evaluate-ahead](#eng-evaluate-ahead) | `loup_evaluate` with its next step graph queued ahead behind a stream wait on a host-mapped word (`cuStreamWaitValue32`), released by the next call's store: no launch on the call's path | `loup_set_evaluate_ahead`, `pair_style loupmd ahead yes`, `LOUP_EVAL_ARM=0\|1` | both | OFF (opt-in: a queued step blocks default-stream work of the whole process; 5060 Ti under WSL 2 only) | S146 | LAMMPS `pair_style loupmd`, `a b b a`: SrTiO3 320 atoms 0.838 / 0.826 -> 0.752 / 0.783 ms/step, water216 0.553 / 0.567 -> 0.528 / 0.533, 5,000 atoms a tie | this file |
| [eng-evaluate-one-copy](#eng-evaluate-ahead) | `loup_evaluate`'s results in one copy of the zeroed slab (energy, forces, virial) instead of three | – | both | DEFAULT | S146 | no step time changed measurably (LAMMPS 5,000 atoms 8.15-8.18 before, 8.15-8.27 after) | [eng-evaluate-ahead](#eng-evaluate-ahead) |
| [lmp-step-profile](#eng-evaluate-ahead) | Where a LAMMPS step with `pair_style loupmd` spends its time (`LOUP_DEBUG_EVAL_TIMES=1`) | – | – | MEASUREMENT | S146 | 320 / 5,000 atoms, us: launch 20 / 51, launch to the guard 208 / 225, guard to results 571 / 7,588, LAMMPS's own work 17 / 200; the engine's own step 580-590 / 7,680-7,720 | [eng-evaluate-ahead](#eng-evaluate-ahead) |
| [lmp-ghost-no](#lmp-styles) | `pair_style loupmd ghost no`: a pair cutoff of zero reported to LAMMPS, so it creates no ghost atoms and skips their communication | `ghost yes\|no` (default yes) | – | OFF (kept as an option; no gain on this machine) | S145 | `loupmd/kk` water216 2.64 -> 2.25-2.53 ms/step, inside the run-to-run spread: the Kokkos cost is not ghost traffic | [lmp-styles](#lmp-styles) |

### Generic path (other model families, 12-13 November 2026)

| ID | Idea | Switch/flag | Path | Status | Stage | Effect | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [gen-probe-export](#gen-probe-export) | Extract every linear map by probing the float64 modules; fold constants numerically | `export_generic.py` | gen | DEFAULT | S6 | design: one exporter for every family | [§5.1][s51] |
| [gen-pair-sym](#gen-pair-sym) | Symmetric pair tables for blocks that do not embed sender and receiver separately | bundle `pair_sym` | gen | DEFAULT | S6 | S(S+1)/2 instead of S^2 tables; size not recorded | [§5.1][s51] |
| [gen-first-layer](#gen-first-layer) | Layer 0 as an outer sum over the radial chain's columns | `first_fwd_kernel`, `first_bwd_kernel`, bundle `first_hidden` | gen | DEFAULT | S6 | 66-column table instead of 4C + 1; OMAT-0 small bundle 40 MB | [§5.1][s51] |
| [gen-factored-products](#gen-factored-products) | FastMACE's factored symmetric contraction, kernels by program signature | `gprod_*` | gen | DEFAULT | S6 | design | [§5.1][s51] |
| [gen-certified-spline](#gen-certified-spline) | FastMACE's certified cubic-Hermite radial spline per pair | `spline.fit` | gen | DEFAULT | S6 | export refuses certificate > 1 | [§5.1][s51] |
| [gen-profile](#gen-profile) | nsys profile of MH-1 `SrTiO3` | – | gen | MEASUREMENT | S6 | SGEMMs ~50%, conv 20%, gate 15% | [§5.5][s55] |
| [gen-fork-zero-slab](#gen-fork-zero-slab) | GEMM fork / join lanes in `GenericModel` and `PolarLR`, one zero slab per pass, dead gate-backward stores cut | `GenericPassInputs::gemm_fork/lane/join` | gen + POLAR | DEFAULT (5060 Ti only) | S7 | 5060 Ti ABBA b/a 0.914-0.990 (all families) | this file |
| [gen-cublas-stream](#gen-cublas-stream) | `cublasSgemm` fallback ignored the GEMM lane's stream | `sgemm_rm` | both | FIX | S7 | POLAR-1-M gate ratios 1e4-4e5 -> PASS | this file |
| [gen-skip-fold](#gen-skip-fold) | `W_skip_msg` folded into `W_lin` / `C0` per species; last layer's `W_p` / `W_sc` folded into `ro_W1` | `GenericLayer::skip_folded`, `ro_folded` | gen | DEFAULT (5060 Ti only) | S7 | ABBA b/a 0.939-0.991 (OMAT-S, OFF, MH-1) | this file |
| [gen-conv-v2](#gen-conv-v2) | Conv kernels with 8-byte cubic tables, staged edges, R-receiver forward, late pull-back backward; warp-staged first layer | `python/gen_generic.py`, `first_fwd/bwd_kernel` | gen | DEFAULT (5060 Ti only) | S7 | ABBA b/a 0.688 (OMAT-S `SrTiO3`) to 0.987 (POLAR-1-S) | this file |
| [gen-skinny-gemm](#gen-skinny-gemm) | Own kernels for products with N <= 16 or K <= 16 (warp K-split, thread per output) in place of cuBLAS | – | gen, POLAR, OMAT-M | REJECTED | S7 | ABBA b/a 1.040 (OMAT-S `SrTiO3`), 1.009 (POLAR-1-M `NbCl5`), 1.016 (OMAT-M `SrTiO3`) | this file |
| [gen-first-bwd-tail](#gen-first-bwd-tail) | First-layer backward: the per-edge `sh16_grad` tail batched one edge per lane | – | gen | REJECTED | S7 | ABBA b/a 1.040 (OMAT-S `SrTiO3`), 1.017 (OFF23-M water) | this file |
| [gen-conv-l2-split](#gen-conv-l2-split) | lx 2 conv backward split: the 10 paths with x degree <= 1 in the late pull-back form, the 7 with x degree 2 kept explicit | `gconv_bwd_L2lp` + `gconv_bwd_L2` | gen (OFF23-L, POLAR-1-L) | DEFAULT (5060 Ti only) | S8 | ABBA b/a 0.925 (OFF23-L water 2x2x2) | this file |
| [gen-first-fwd-race](#gen-first-fwd-race) | `first_fwd_kernel`: species-segment end in two parity slots | – | gen | FIX | S8 | no timing change expected; forces at noise level | this file |
| [gen-first-bwd-v2](#gen-first-bwd-v2) | First-layer backward: receiver's `G` rows staged once in swizzled shared memory; one edge per half-warp | `first_bwd_kernel<STAGE_G>` | gen | DEFAULT (5060 Ti only) | S8 | ABBA b/a 0.948 (OMAT-S `SrTiO3`), 0.982 (OFF23-M water), 0.986 (OMAT-S `NbCl5`), 0.996 (MH-1) | this file |
| [gen-conv-fwd-r1](#gen-conv-fwd-r1) | Conv forward at C = 128 with one receiver per block (was 4 for lx 0, 2 for lx 1) | `launch_conv_fwd` | gen | DEFAULT (5060 Ti only) | S8 | ABBA b/a 0.949-0.989 | this file |
| [gen-conv-fwd-l2-split](#gen-conv-fwd-l2-split) | lx 2 conv forward as two kernels by x degree | `gconv_fwd_L2a` / `L2b` | gen (OFF23-L, POLAR-1-L) | DEFAULT (5060 Ti only) | S8 | OFF23-L water forward 7.6 -> 3.1 + 3.1 ms | this file |
| [gen-conv-bwd-128](#gen-conv-bwd-128) | Conv backward (lx 0 / 1) with 128-thread blocks | – | gen | REJECTED | S8 | ABBA b/a 0.997 (OMAT-S), 0.992 (OFF23-M): below resolution, halves per-receiver warps on small cells | this file |
| [gen-conv-fwd-l1-split](#gen-conv-fwd-l1-split) | lx 1 conv forward as two kernels by x degree | – | gen | REJECTED | S8 | 1.70 -> 1.78-1.87 ms (x degree 1 kernel alone at 128 registers) | this file |
| [rv8-fixes](#rv8-fixes) | Eighth review pass: packed-table error check at load, cuBLAS workspace per lane, reorder carries Langevin noise, MD needs a state, safe edge growth, band / plan / input checks, unstable gate row opt-in | `kPackedTableMaxRelErr`, `cublas_bind`, `--include-unstable` | all | FIX | S9 | accuracy and robustness, no speed change intended | this file |
| [gen-zbl-in-assembly](#gen-zbl-in-assembly) | ZBL computed in the force-assembly pass (float32, skip beyond the largest ZBL cutoff) instead of its own pass | `assemble_forces_kernel(ZblParams)` | gen (ZBL models: OMAT-S, MH-1) | DEFAULT (5060 Ti only) | S10 | OMAT-S `SrTiO3`: 389 -> 221 us per call | this file |
| [gen-first-bwd-assembly](#gen-first-bwd-assembly) | Force / virial assembly (and ZBL) folded into the first-layer backward | – | gen | REJECTED | S10 | 990-1,029 -> 1,113-2,243 us | this file |
| [gen-first-hidden-k0-align](#gen-first-hidden-k0-align) | Layer 0 `first_hidden` `K` alignment (drop zero bias col 64, pad nonzero `K` to 16) to unlock `sgemm128` + `3xTF32` | `GenericLayer::K0` | gen (`first_hidden`) | DEFAULT (5060 Ti only) | S11 | OMAT-S `SrTiO3` 5.88 -> 5.62 ms/step (0.956); OFF23-M water 8.85 -> 8.67 (0.979); OMAT-M gen 10.56 -> 10.30 (0.976) | this file |
| [gen-conv-bwd-lazy-q](#gen-conv-bwd-lazy-q) | Lazy `s_q` loads + register-cap launch bounds on `gconv_bwd_L0/L1/L2` | – | gen | REJECTED | S11 | `gconv_bwd_L1`: 2.67-2.78 -> 2.88-2.95 ms (`STACK:64` spill, or stalled `LDS.128` at 128 regs); `gconv_bwd_L0` 512 threads 1.26 -> 1.31 ms | this file |
| [gen-first-bwd-edge](#gen-first-bwd-edge) | Edge-parallel layer-0 backward + ZBL + force/virial assembly (`tabled_outer_sum0_backward_kernel` design) | `first_bwd_edge_kernel` | gen (`first_hidden`, `J - 1 <= 96`) | DEFAULT (5060 Ti only) | S12 | OMAT-S `SrTiO3` 5.62 -> 5.13 ms/step (0.913); OFF23-M water 8.65 -> 8.28 (0.957); OMAT-M gen 10.30 -> 9.80 (0.951); MH-1 0.990, POLAR-1-M 0.995 | this file |
| [gen-gprod-ro1-fused](#gen-gprod-ro1-fused) | Fused product fwd + linear/bias/silu/linear readout (`ro_H = 16`) + product bwd (`sc1_fused` generalisation) + 128-thread `gprod_fwd`/`bwd` | `gprod_ro1_fused_<sig>`, `launch_prod` | gen (`ro_folded`, `readout == 1`, `ro_H == 16`; `C % 128 == 0`) | DEFAULT (5060 Ti only) | S13 | OMAT-S `SrTiO3` 5.12 -> 4.99 ms/step (0.976); OFF23-M water 8.29 -> 8.16 (0.984); OMAT-M gen 9.81 -> 9.67 (0.986); POLAR-1-M `NbCl5` 27.28 -> 27.14 (0.995) | this file |
| [gen-gconv-cfix-preloc](#gen-gconv-cfix-preloc) | `C_FIX` (`96/128/224`) template on `gconv_bwd_L0/L1` (`gconv_bwd_L1<true,128>`: `REG:128 -> 62`) + prelocated `act_slab`/`act_t_sx` from `scatter_active_edges_kernel` (`pair_sym && C_x <= 256`) + 256 thr on `L1` | `C_FIX`, `PRELOC`, `preloc_grid()` | gen (`C = 96/128/224`; preloc `pair_sym && C_x <= 256`) | DEFAULT (5060 Ti only) | S14 | OMAT-S `SrTiO3` 4.91 -> 4.73 ms/step (0.964); OFF23-M water 8.00 -> 7.43 (0.928); MH-1 `NbCl5` 12.82 -> 12.50 (0.976); POLAR-1-M 27.20 -> 27.06 (0.995); OMAT-M gen 9.67 -> 8.91 (0.921, `1.051x` spec) | this file |
| [gen-conv-fwd-cg-fold](#gen-conv-fwd-cg-fold) | Staged per-edge CG linear forms in `s_sh` (`ED = 16/36/72`) + per-edge `s_pw` polynomial scalars in `gconv_fwd` | `emit_conv_fwd` | gen | DEFAULT (5060 Ti only) | S15 | `gconv_fwd_L1` `1,688 -> 1,572 us` (`OFF23-M`), `L2b` `3,029 -> 2,898 us` (`OFF23-L`); ABBA OMAT-S `SrTiO3` `0.989` (`4.82 -> 4.77 ms`), `OFF23-L` `0.989` (`28.30 -> 28.00`), `OFF23-M` tie (`0.997`), `POLAR-1-M` tie (`0.999`), `MH-1` `0.981` inconclusive (`1.682/1.746` spread) | this file |
| [gen-conv-bwd-128-regq](#gen-conv-bwd-128-regq) | `128`-thread register-`Q` edge-staged `gconv_bwd_L0/L1_128` (`PAIR = false` / `true`) | – | gen | REJECTED | S16 | `PAIR=false`: `L1` `2,216 -> 2,147 us`, MD `OFF23-M` tie (`0.999`), `OMAT-0-S` `0.997`; `PAIR=true` (`REG:128`): MD `+0.4%`/`+0.8%` | this file |
| [gen-conv-l1-carve0](#gen-conv-l1-carve0) | `PreferredSharedMemoryCarveout = 0` on generic conv & `first_bwd_edge` kernels | – | gen | REJECTED | S16 | capped `gconv_fwd_L1` to `8.19 KB` & `gconv_bwd_L1` to `32.77 KB` (`1` blk/SM); `OFF23-M` `7,372 -> 11,592 us/eval` | this file |
| [gen-first-bwd-edge-minb](#gen-first-bwd-edge-minb) | `first_bwd_edge_kernel<COLS = 2>` capped at 80 registers (`__launch_bounds__(128, 6)`, sm_120 device code only) | `LOUP_FIRST_BWD_EDGE_MINB2` | gen (`first_hidden`, `J - 1 <= 64`) | DEFAULT (5060 Ti only) | S21 | kernel `510 -> 480 us` (`OMAT-0-S`), `358 -> 334` (`OFF23-M`); step, both argument orders: `OMAT-0-S` mean `0.9954` (5 runs, all <= 1), `OFF23-M` `0.9979` (6 runs, one `1.0030`) | this file |
| [gen-first-bwd-lpe](#gen-first-bwd-edge-minb) | Lane-per-edge `first_bwd_edge` (no cross-lane SH folds, staged table rows, uniform `dS0` loads) | – | gen | REJECTED | S21 | instructions `-43%` but `168` registers: `505 -> 570 us`; capped `128 / 96 / 80` regs `1024 / 681 / 714 us` (spills) | this file |
| [s93-sm80-caps](#s93-sm80-caps) | `sm_80` register caps on the generic path: `first_bwd_edge_kernel<COLS = 2>` at 6 blocks / SM (80 registers; `s93a`), plus `gconv_fwd_L1` R1 at `C = 128` at 5 blocks / SM (104 -> 96 registers; `s93b`) | – (scratch builds on Alex, not committed) | gen | REJECTED (A100) | S93 | library ABBA against S86 on shared plans, 2 rounds: `s93b` OMAT-0 generic SrTiO3 `0.986`, MP-0 medium SrTiO3 `0.984`, OFF23-M water216 `1.015` (slower in both orders); `s93a` `1.000` / `0.998` / `1.003` | this file |
| [gen-conv-fwd-l1-r4](#gen-conv-fwd-l1-r4) | `gconv_fwd_L1<4, true, 512, ..., 128, 16>` (`4` receivers/block, `TILE = 16`) | – | gen | REJECTED | S16 | `OMAT-0-M` generic `SrTiO3` `8.79 -> 8.66 ms` (`0.985`), `OFF23-M` water `7.44 -> 7.54` (`1.013`, `REG:124`) | this file |
| [gen-conv-l2-cfix-preloc](#gen-conv-l2-cfix-preloc) | `C_FIX` (`128/224`) on `gconv_fwd_L2a/L2b`, `gconv_bwd_L2lp/L2`; `PRELOC` on `gconv_bwd_L2`; prelocated slabs for `pair_sym = 0` models (`preloc_grid()` / `preloc_pair_sym()` pick the same layer) | `C_FIX`, `PRELOC`, `pick_preloc_layer` | gen (lx 2: OFF23-L, POLAR-1-L; preloc: also POLAR-1-M/L, MH-1) | DEFAULT (5060 Ti only) | S19 | `gconv_bwd_L2lp` `REG:128 -> 62`; ABBA `OFF23-L` water `27.81 -> 27.16 ms` (`0.977`), water216 `0.985`, `POLAR-1-L` `NaCl216` `0.991`; `POLAR-1-M` / `MH-1` `NbCl5` tie | this file |
| [gen-conv-bwd-l1-c256](#gen-conv-bwd-l1-c256) | `C_FIX = 256` dispatch for `gconv_bwd_L1` (`MACE_MPtrj_2022.9`, `C = 256`, ran runtime `C` at 128 registers) | `launch_conv_bwd` | gen (`C = 256`, lx 1) | DEFAULT (5060 Ti only) | S29 | `REG:128 -> 62`; L1 convs `4928 / 4975 -> 4837 / 4848 us`; ABBA `MPtrj` `SrTiO3` `0.9935` / `0.9896` (both orders) | this file |
| [gen-conv-fwd-l1-c256](#gen-conv-fwd-l1-c256) | `C_FIX = 256` (`PAIR = false`) dispatch for `gconv_fwd_L1` at `C = 256` | `launch_conv_fwd` | gen (`C = 256`, lx 1) | DEFAULT (5060 Ti only) | S30 | 80 registers (as runtime `C`); `gconv_fwd_L1` `1971 / 1949 -> 1861 / 1860 us`; ABBA `MPtrj` `SrTiO3` `0.9921` / `0.9910` (both orders) | this file |
| [gen-conv-fwd-l1-pair-c256](#gen-conv-fwd-l1-c256) | `PAIR = true`, `C_FIX = 256` for `gconv_fwd_L1` at `C = 256` | – | gen | REJECTED | S29 | 104 registers; L1 convs tie (`4952 / 4953` vs `4928 / 4975 us`) | this file |
| [gen-conv-bwd-512thr](#gen-conv-bwd-512thr) | 512-thread blocks for the shared-memory-limited lx 1 / 2 backward convs (`gconv_bwd_L1` at `C = 256`, `gconv_bwd_L2lp` at `C = 224`): one 39-45 KB `s_q` per block shared by 16 warps instead of 8 | `launch_conv_bwd` | gen (`MPtrj`, `OFF23-L`) | DEFAULT (5060 Ti only) | S31 | `bwd_L1` (`MPtrj`) `-12.7%`, `bwd_L2lp` (`OFF23-L` water216) `~-10%`; ABBA `MPtrj` `0.9695 / 0.9685`, `OFF23-L` water216 `0.9825 / 0.9847`, water `0.9825 / 0.9839` | this file |
| [gen-conv-fwd-l2-minb3](#gen-conv-fwd-l2-minb3) | `__launch_bounds__(224, 3)` for `gconv_fwd_L2a/L2b` at `C = 224` (register-limited to 2 blocks, 29% occupancy) | – | gen (`OFF23-L`) | REJECTED | S31 | 104 / 125 -> 80 registers with 56-72 B stack; both kernels `759 -> 1018 us` (`+34%`) | this file |
| [gen-conv-bwd-l0-red](#gen-conv-bwd-l0-red) | `gconv_bwd_L0`: per-edge `edge_dvec` update as a fire-and-forget atomic add (RED) instead of read-add-store | `EDGE_DVEC_RED` in `python/gen_generic.py` | gen (lx 0: OMAT-0-S, OFF23-S, ...; every GPU since S129) | DEFAULT (every GPU since S129, [gen-arch-neutral](#gen-arch-neutral)) | S40 | kernel `-8%` (`OMAT-0-S`) / `-16%` (`OFF23-S`); ABBA `OMAT-0-S` `0.9813` / `0.9768`, `OFF23-S` water `0.9718` / `0.9763` (new / old, both orders) | this file |
| [gen-conv-bwd-edge-prefetch](#gen-conv-bwd-l0-red) | Next-edge metadata (`vec_len`, sender, slab, `t`) loaded one iteration ahead in the late pull-back backward convs; and RED on lx 1 / 2 | – | gen | REJECTED (5060 Ti only) | S40 | prefetch over RED: `-1%` to `-3%` on L0, `+1%` on L1 (8 B spill); RED on L1 / L2: `-1%` / `-2%` (below the 10% stop rule) | this file |
| [gen-conv-fwd-l0-xprefetch](#gen-conv-bwd-l0-red) | `gconv_fwd_L0`: sender `x0` of the next two edges held in registers one iteration ahead | – | gen (lx 0) | REJECTED (5060 Ti only) | S41 | `ncu`: ~27% of its stall samples wait on the per-edge `x0` load; prefetch: `OMAT-0-S` `721 -> 783 us` (`+8.5%`), `OFF23-S` tie | this file |
| [gen-conv-bwd-l2-pullr](#gen-conv-bwd-l2-pullr) | `gconv_bwd_L2`: radial pull from the x-gradient contraction (`sum_m1 x[m1] Cg[m1]`, `Cg[m1] = sum_m2 A[m1, m2] Y[m2]`) instead of the full sum over every `A x Y` term | `python/gen_generic.py` `emit_conv_bwd_L2` (every GPU since S129) | gen (lx 2: OFF23-L, POLAR-1-L) | DEFAULT (every GPU since S129, [gen-arch-neutral](#gen-arch-neutral)) | S48 | SASS 1624 -> 1464; kernel `-18%` (water216) / `-16%` (water); ABBA `OFF23-L` water `0.9624` / `0.9609`, water216 `0.9666` / `0.9639`; `POLAR-1-L` `NaCl216` `1.0024` / `0.978` (tie) | this file |
| [gen-conv-bwd-lp-defer-sh](#gen-conv-bwd-lp-defer-sh) | Late pull-back convs: scalar `(0, 2, 2)` / `(0, 3, 3)` paths with per-edge `h` coefficients and the pull-back deferred to one `v(T)` per lane and edge | `python/gen_generic.py` `emit_conv_bwd_lp` (`sm_120` branch, reverted) | gen (`L0` / `L1` / `L2lp`; `sm_120`) | REJECTED | S50 | `gconv_bwd*` per step `OMAT-0-S` +2 / +5%, `OFF23-S` +3 / +4%, `OFF23-M` +12 / +13% (registers `L1` / `L2lp` 62 -> 101, `L0` 60 -> 64; no spill) | this file |
| [gen-pack-refine](#gen-pack-refine) | Export refines every radial band whose 8-byte (CUBIC_PACKED8) packing error would exceed half the loader's bound, then re-certifies | `python/export_generic.py` `refine_for_packing` | gen (export; conv layers) | FIX | OMOL-0 support | OMOL-0 XL layer 1 packing error 2.06e-3 (refused at load) -> 1.76e-4; H, C, N, O layer 1 1,764 -> 2,031 intervals, layer 2 400 -> 719; organic gate passes | this file |
| [gen-chain-fold](#gen-chain-fold) | Skip-chain fold: a non-last layer's output `hout_t = y_t W_p_t + h_in_t W_sc_t` is never formed; per degree, `y_t` (and layer 0's species-only input) multiplies one weight per downstream consumer, `W_p_t W_sc_{t+1} ... W_up_s` (or `... ro_W1`), composed in double at load; the backward forms `dy_t` from the consumers' gradients through the same weights | `GenericModel::setup_chain_fold`, `GenericLayer::fold` (`sm_120` and cc 8.0; `LOUP_CHAIN_FOLD=0` disables) | gen (all layers gated, no readout before the last, no per-species skip, folded last readout, no long range: of the cached families only OMOL-0) | DEFAULT (5060 Ti; A100 since S77, [a100-cc80-defaults](#a100-cc80-defaults)) | S57 | OMOL-0 XL fold / plain, same build: water216 `0.821` / `0.821` (29.0 -> 23.8 ms/step), water `0.825` / `0.825` (217.9 -> 179.8) | this file |
| [gen-sgemm-issue](#gen-sgemm-issue) | `sgemm128_kernel` on OMOL-0's 1024-wide GEMMs: FFMA issue order (serpentine, column-outer), `__launch_bounds__(256, 1)`, and a 192 x 128 tile with 384 threads (~168 registers, 12 warps per SM) against its dispatch stalls | `.tmp_o/sgv.py`, `.tmp_o/sg192.cu` (harness only) | own SGEMM (`sm_120`) | REJECTED | S58 | `4536 x 1024 x 1024`: serpentine +4%, column-outer +7%, one block per SM +5-9%, 192-tile +12-14% (`3240` -4 / -1%, `1944` +10-13%, `648` -27% but `sgemm64` already 107 us); none >= 10% faster | this file |
| [gen-species-tables](#gen-species-tables) | Layer 0's species-only products as per-species tables composed in double at load and gathered per atom: the gated block's residual (embedding `W_up W_res`) and, under S57, the skip terms (embedding `W_sc_0 M`); no layer-0 `x` / residual GEMMs, no `Wh` GEMMs | `GenericModel::setup_species_tables`, `GenericLayer::res0_table`, `FoldTarget::Th` (`sm_120` and cc 8.0; `LOUP_SPECIES_TABLES=0` disables) | gen (layer 0 first-hidden gated with lmax_x 0, no long range: OMOL-0, MH-1) | DEFAULT (5060 Ti; A100 since S77) | S59 | final binary, tables / plain, both orders: OMOL-0 water216 `0.978` / `0.977` (23.78 -> 23.26 ms/step), MH-1 NaCl216 `0.988` / `0.991`, NbCl5 `0.997` / `0.996`; POLAR-1-L no win tables-first (excluded with the other long-range models) | this file |
| [s60-omol-prod-floor](#s60-omol-prod-floor) | OMOL-0 product and gate kernels after S59: `ncu` limiter | (measurement) | gen (OMOL-0) | MEASURED | S60 | all four product kernels DRAM-bound (`ncu` DRAM 87-95% of peak, FMA pipe 4-16%, L2 hit 1-4%): `gprod_fwd` / `gprod_bwd` 121 / 259 us (layers 0, 1), 118 / 191 us (last layer); gates at the same floor; only fewer bytes (fusion into the per-degree `W_2` GEMMs) would shorten them | this file |
| [gen-prod-w2-fusion](#gen-prod-w2-fusion) | Symmetric product fused into the `W_2` GEMMs: atom-major tiles mixing the four degrees; forward prototype = grouped GEMM writing `msgf` with the generated product body in its epilogue | `.tmp_o/sg_grp.cu`, `.tmp_o/gen_fused.py` / `sg_fused_tmpl.cu` (harness only) | gen (OMOL-0) | REJECTED | S61 | fused forward (GEMM + product, bit-identical `msgf` and `y`) vs four GEMM lanes + `gprod_fwd`: 648 atoms `0.921` / `0.946` (90-135 us per layer), 5,184 atoms `1.053`; grouped GEMM alone `1.028-1.042` / `1.133`; ~1% of the water216 step, a loss on large systems; backward not prototyped (product backward recomputed per output-channel tile, 8x) | this file |
| [gen-w2-fused](#gen-w2-fused) | S61's fused forward built into the engine: `gprod_w2f_<sig>` per product signature (generated; the grouped GEMM in a shared header), used for gated layers with `C_msg >= 1024` up to 448 atoms (sm_120) | `src/w2_grouped.cuh`, `gen_generic.py`, `generic.cu` record (reverted) | gen (OMOL-0) | REJECTED | S62 | exact (`dF` 1.4-3.5e-6); full-step ABBA fused / plain, both orders: urea128 `1.020` / `1.019`, naph288 `1.014` / `1.011`, urea432 `1.013` / `1.012`; nsys naph288: summed kernel time -812 us per step but step span +135 us (the per-layer W_2 + product segment 694-704 -> 727-742 us) | this file |
| [gen-default](#gen-default) | The generic path as the default for OMAT-0 medium too (owner's decision O20); the specialised kernels stay built and gated | `LOUP_GENERIC=0`, `generic=False`, `test_gate.py --specialised`, `loupmd validate --specialised` | generic | DEFAULT on `release/v1` (5060 Ti only) | release Stage 2 | generic / specialised in one library, both orders: `NbCl5` 1.0409, 1.0399; `SrTiO3` 1.0184, 1.0144 | [§6.6][s66] |
| [s63-spec-vs-gen](#s63-spec-vs-gen) | OMAT-0 medium on the specialised path against the generic path (`LOUP_GENERIC=1`), stage by stage; falsifier for the interaction-0 backward gap: the density-derivative polynomial per lane before the edge loop (sm_120) | `src/interaction0.cu` (reverted) | specialised | REJECTED | S63 | generic 7.4% / 2.9% slower overall (SrTiO3 / NbCl5); faster only in the interaction-0 backward (`first_bwd_edge` 484 / 76 us vs 554 / 113); the per-lane `qd` change: ABBA SrTiO3 `0.9997` / `0.9998`, NbCl5 `1.0015` / `1.010` (tie) | this file |
| [gen-conv-fwd-variants](#gen-conv-fwd-variants) | `gconv_fwd_L1` at `C = 128` with five receivers per 640-thread block (the specialised forward's `R5`) or unpaired, chosen per layer and system by timing at the first MD rebuild | `launch_conv_fwd` `var`, `GenericModel::tune_conv_variants` (sm_120; `LOUP_CONV_TUNE=0` disables, `LOUP_CONV_FWD_VARIANT=0\|1\|2` forces) | gen (lx 1, `C = 128`: OFF23-M, OFF23b-M, OFF24-M, MH-1, MP-0 medium, POLAR-1-M) | DEFAULT (5060 Ti only) | S64 | kernel R1p / R1 / R5: OMAT-0-M generic SrTiO3 2,200 / 2,176 / 1,742 us, OFF24-M water 2,723 / 2,686 / 2,437, MP-0-M SrTiO3 2,385 / 2,273 / 2,136, NbCl5 354 / 348 / 357; full-step ABBA tuned / old, both orders: MP-0-M SrTiO3 `0.968` / `0.967`, OFF24-M water `0.978` / `0.978`, OFF23-M water `0.975` / `0.980`, small cells tie; A100 (S83t, tuner on cc 8.0): no gain, OFF23-M water216 `1.024` against noise `1.013`; kept on `sm_120` only | this file |
| [gen-conv-bwd-multi-rcv](#gen-conv-bwd-multi-rcv) | `gconv_bwd_L1` (C 128, dx) with R receivers per block (own `s_q` slice and named barrier each), so receivers walking the same table slabs share them in L1 (the forward's R5 idea) | `emit_conv_bwd_lp` `R`, `TPR` (reverted) | gen (lx 1, `C = 128`) | REJECTED (5060 Ti) | S68 | `ncu` (5060 Ti, MP-0 medium SrTiO3): the backward is L2-bandwidth bound (83.8% of peak; sectors 85% reads, 14% `dx` atomics, LG throttle 0.09%); variants exact (`dF` <= 1.3e-6) but slower: R2 x 256 `+20%`, R4 x 128 `+16%`, R2 x 128 `+69%` (2,910-2,935 -> 3,374-4,941 us) | this file |
| [gen-conv-sliced](#gen-conv-sliced) | Conv backward / forward at `C = 128` with one warp per (receiver, 32-channel slice), RS receivers per block, the backward's `dmid` in registers instead of `s_q`, so consecutive receivers share table slabs through L1 | `emit_conv_bwd_lp(sliced)`, `emit_conv_fwd(sliced)`, `launch_conv_bwd` `var` (reverted) | gen (lx 1, `C = 128`) | REJECTED (5060 Ti) | S72 | backward: L1 hit 15.7% -> 58.7%, L2 reads 122 M -> 44 M sectors, but 128 registers (16 warps / SM) leave it issue-bound at the same time (2.94 -> 3.06 ms); lower register caps spill (4.5-5.0 ms); two passes by x degree 3.7-3.9 ms; forward 1.60 -> 1.83 ms (L1 34% vs R5's 66%) | [below](#gen-conv-sliced) |
| [s72-omat0-limiters](#s72-omat0-limiters) | OMAT-0 medium generic SrTiO3 (5,000 atoms) on the 5060 Ti: the limiter of every kernel family in the MD step | (measurement) | gen (OMAT-0) | MEASURED | S72 | conv backward issue 75% and L2 75%; conv forward issue 72%; lin1 `sgemm128` FMA pipe 65-70% at 70% issue; products DRAM 78-92%; layer 0 latency-bound (issue 62-65%): no kernel has a free resource | [below](#s72-omat0-limiters) |
| [gen-res0-table-read](#gen-res0-table-read) | The gate kernels read layer 0's residual straight from the S59 `[S, 4 C]` species table (row of the atom's species) instead of a per-atom copy | `gate_fwd_kernel` / `gate_bwd_kernel` `res0_sp`, `GenericModel::record` (no `gather_rows_kernel` for it, no `res[0]` buffer) | gen (with S59 tables: OMOL-0, MH-1 on sm_120) | DEFAULT | S72 | removes a write and two reads of `N x 4 C` floats per step (MH-1 SrTiO3: 3 x 41 MB); ABBA candidate / S70, both orders: MH-1 SrTiO3 `0.993` / `0.991`, NaCl216 `0.987` / `0.983`, OMOL-0 water216 `0.998` / `0.997` | [below](#gen-res0-table-read) |
| [gen-chain-fold-ext](#gen-chain-fold-ext) | S57's skip-chain fold for every multi-layer generic model without long range: any layer kind, a non-last linear readout (its gradient a constant seed of `dy_t[0]`), per-species skips (per-species composed weights, species-grouped GEMMs) | `GenericModel::setup_chain_fold` (eligibility, `FoldTarget::ns` / `ns_h`, energy targets `dest_layer = -2`), `record`, `species_energy_kernel` (`sm_120` and cc 8.0; `LOUP_CHAIN_FOLD=0` disables, `=1` forces elsewhere) | gen (now also MH-1, OMAT-0 / MPA-0 / MP-0b3 / MatPES / OMAT-0 small on the generic path, MP-0 medium, MPtrj, OFF23 / OFF23b / OFF24) | DEFAULT (5060 Ti; A100 since S77) | S73 | in-process plain / fold, both orders, noise side <= 0.2%: MH-1 NaCl216 `1.075`, SrTiO3 `1.053` (34.86 -> 33.11 ms); MPtrj SrTiO3 `1.040`; OMAT-0 generic SrTiO3 `1.017` (8.17 -> 8.03, the specialised path's time); MP-0 SrTiO3 `1.017`; OFF24-M water `1.015` | [below](#gen-chain-fold-ext) |
| [gen-pass-glue](#gen-pass-glue) | Per-pass glue on the generic path: the layer-0 embedding gather only when a consumer reads it, and a folded linear readout assigning its gradient seed (so that buffer leaves the zero slab) (S97); the top conv layer's backward assigning the per-edge force vectors instead of a zero fill plus read-add-store (S98); each conv layer's `dx` zeroed per receiver at the start of its forward conv kernel instead of in the pass's memset (S99); the folded linear readout inside the layer's product kernels (energy in the forward, gradient seed in the backward) instead of its own kernel (S100) | `GenericModel::h0_read_`, `ro_linear_kernel(assign)`, `launch_conv_bwd(..., dvec_assign)`, `launch_conv_fwd(..., zx)`, `launch_prod(..., ro_w, energy)` | gen | DEFAULT | S97-S100 | library ABBA on shared plans, both orders, S97: OMAT-0 generic SrTiO3 `0.998`, MP-0 medium SrTiO3 `0.999`, OFF23-M water216 `0.991`; S98: OMAT-0 generic `0.995`, MP-0 `0.992`, OFF23-M water216 `0.993`, OFF23-S water216 `0.989`, MH-1 NaCl216 `0.999`, OMOL-0 water216 `1.000`; S99: OMAT-0 generic `0.997`, MP-0 `0.996`, OFF23-M water216 `0.996`, MH-1 NaCl216 `0.993`, OFF23-S water216 `1.000`; S100: OFF23-M water216 `0.987`, MP-0 `0.999`, OMAT-0 generic `1.000`, OFF23-S water216 `0.999` | [below](#gen-pass-glue) |
| [gen-first-fwd-cols](#gen-first-fwd-cols) | `first_fwd_kernel` with one thread per radial column: warp 0 sums the density column (one lane per staged edge, added in edge order) instead of a warp of its own with one active lane | `src/generic.cu` `first_fwd_kernel`, `max(J - 1, 64)` threads | gen (layer 0 of every generic model) | DEFAULT | S105 | kernel 255-260 -> 240-245 us (OMAT-0 generic `SrTiO3`); ABBA over S101 OMAT-0 generic `0.9991`, MH-1 `NaCl216` `0.9973` (both orders), OFF23-M water216 tie | this file |
| [gen-single-table](#gen-single-table) | One radial table for every species pair when all pair slabs of a conv layer are byte-identical at load (the radial MLP does not see the species): `pair_sym = 2`, `loup::table_pair` maps every pair to slab 0 | `src/generic.cu` loader (`memcmp`), `loup::table_pair` (`kernels_common.cuh`), `gen_generic.py`, `neighbors.cu` | gen (conv layers: OFF23 / OFF23b / OFF24, MP-0 medium, MPtrj) | DEFAULT (5060 Ti only) | S116 | VRAM OFF23-M water216 206 -> 192 MiB, OFF23-L water216 306 -> 274, MP-0 medium SrTiO3 876 -> 718, MPtrj SrTiO3 1,148 -> 1,056; library ABBA on shared plans OFF23-S / -M / -L water216 `0.996` / `0.991` / `0.996`, MPtrj SrTiO3 `0.998` (both orders below 1), MP-0 medium SrTiO3 `0.9996` (a tie); gates pass | this file |
| [gen-conv-l2-cartesian](#gen-conv-l2-cartesian) | Five of the seven x-degree-2 conv paths, (2,2,0), (2,1,1), (2,3,1), (2,2,2), (2,0,2), as Cartesian forms of one `Q = sum_m x2_m B'_m`: `v = Q n` and `h = n . v` per edge and channel serve all five (outputs `C h`, `C v`, `C (n h - 2/5 v)`, `C (v . B'_m n - 2/3 x_m)`, `C x`, constants fitted to the Wigner-3j contractions); the backward forms one `c = al n + b + C22 R22 G n` for the x gradient and feeds the direction gradient into `dY[1..3]` | `python/gen_generic.py` `DEG2_CART`, `deg2_cart`, `_cart_bwd`, `emit_conv_fwd` (every GPU since S129) | gen (lx 2: OFF23-L, POLAR-1-L, OMOL-0 XL) | DEFAULT (every GPU since S129, [gen-arch-neutral](#gen-arch-neutral)) | S119, S121 | `gconv_bwd_L2` 651-654 -> 573-581 us, `gconv_fwd_L2b` 362-369 -> 342-346 us (OFF23-L water216); library ABBA, every order below 1, S119 / S121: OFF23-L water216 `0.975` / `0.986`, POLAR-1-L NaCl216 `0.995` / `0.995`, OMOL-0 XL water216 `0.993` / `0.997`, OFF23-L water (S119) `0.974`; gates pass | this file |
| [gen-conv-l1-cartesian](#gen-conv-l1-cartesian) | Four x-degree-1 conv paths, (1,1,0), (1,2,1), (1,1,2), (1,3,2), as Cartesian forms of the sender vector p and the direction: one `d = p . Y1` and one `q_m = p . B'_m Y1` per edge and channel serve them; the 13 staged linear forms only these paths read are dropped (ED 36 -> 24 per edge in `gconv_fwd_L1` / `L2a`) | `python/gen_generic.py` `CART1`, `cart1_consts`, `_cart1_fwd` (every GPU since S129) | gen (lx 1 and 2) | DEFAULT (every GPU since S129, [gen-arch-neutral](#gen-arch-neutral)) | S122 | `gconv_fwd_L1` 1,766 / 1,786 -> 1,712 / 1,725 us (OMAT-0 generic SrTiO3), `L2a` 409 / 417 -> 399 / 400 (OFF23-L water216); library ABBA OMAT-0 generic SrTiO3 `0.9943`, OFF23-M water216 `0.9923`, OFF24-M water `0.9952`, OFF23-L water216 `0.9944`, MH-1 NaCl216 `1.0018` (tie); A4000 with the forms compiled in: MP-0 SrTiO3 `0.9935` | this file |
| [gen-conv-prune](#gen-conv-prune) | Conv paths pruned when a layer's projections W_lin_1..3 are exactly zero (certified at load): the lx 1 kernels with the output-degree-0 paths only (`gconv_fwd_L1s` / `gconv_bwd_L1s`: 2 of 10 paths, the full table stride), the l >= 1 projections skipped in both directions, their outputs zeroed once: MP-0 medium's second interaction | `GenericLayer::conv_prune` (`LOUP_CONV_PRUNE=0` disables); `launch_conv_fwd / bwd (..., prune)` | gen (MP-0 medium) | DEFAULT (5060 Ti, sm_86, sm_89) | S125 | MP-0 SrTiO3 (5,000 atoms) 8.20 -> 4.03 ms per step, library ABBA `0.4918` (A4000 `0.4134`, RTX 4000 Ada `0.4822`); NbCl5 `0.5211` (`0.4573`, `0.5209`); `gconv_bwd_L1` 2,875 -> 1,089 us, `gconv_fwd_L1` 2,099 -> 678 us, `sgemm128` 1,623 -> 774 us per step | this file |
| [gen-prod-scalar](#gen-prod-scalar) | The fused product + readout for a pruned layer (S125: m_1..3 exactly zero) generated from the product program with x1..x15 = 0 propagated: MP-0's terminal product becomes the cubic `w0 x0 + w1 x0^2 + w2 x0^3` per channel and its adjoint, `dm0` the only gradient written | `python/gen_generic.py` `_scalar_prune`, `gprod_ro1s_fused_<sig>`; `launch_prod_ro1_fused(..., scalar_only)` (`conv_prune` and kind != 4) | gen (MP-0 medium) | DEFAULT (5060 Ti) | S127 | `gprod_ro1_fused` 235 -> 71 us per step (MP-0 SrTiO3); library ABBA MP-0 SrTiO3 `0.9622`, NbCl5 `0.9120` | this file |
| [gen-l0-no-density](#gen-l0-no-density) | Layer 0's table without its unread density column for agnostic first layers (kinds 0 / 1: MP-0 medium, MPtrj, OFF23 / OFF23b / OFF24): rows of `J - 1` float4 (1,024 B at 64 columns), and `first_fwd` neither loads nor sums the density | `GenericLayer::Jt` (row stride), `first_fwd_kernel` / `first_bwd_kernel` / `first_bwd_edge_kernel` (`Jt`) | gen (agnostic layer 0) | DEFAULT (5060 Ti) | S128 | `first_fwd` 250 / 254 -> 228 / 230 us (MP-0 SrTiO3), 20.2 / 20.9 -> 18.6 / 18.7 (OFF23-M water216); library ABBA MP-0 SrTiO3 `0.9958`, NbCl5 `0.9908`, OFF23-M water216 `0.9985` (tie) | this file |
| [gen-bwd-stage-float4](#gen-bwd-stage-float4) | The generic conv backward's per-receiver staging (`s_q`, stride QS = 44 floats) written as float4 instead of scalar stores (4-way bank conflicts: bank step 12) | `python/gen_generic.py` `emit_conv_bwd_lp` prologue | gen (lx <= 2 backward) | REJECTED | S126 | `gconv_bwd_L1` 3,061 / 3,020 -> 3,055 / 3,019 us (OMAT-0 generic SrTiO3), `L2lp` 485 / 483 -> 490 / 487 (OFF23-L); library ABBA OMAT-0 generic `0.9989`, MH-1 NaCl216 `1.0029`, OFF23-M `0.9950`, OFF23-L `1.0087` (mixed orders) | this file |
| [gen-conv-fwd-tile-pair](#gen-conv-fwd-tile-pair) | The forward convs' paired decode (one packed-table row read for two edges with the same slab) over any two edges of the 32-edge tile, matched by slab with `__match_any_sync` in the staging warp, instead of only adjacent edges (rows keep their rebuild order while the radii move) | `python/gen_generic.py` `emit_conv_fwd` (reverted) | gen (every forward conv) | REJECTED | S133 | registers within +-4 (8 of 46 kernels), no stack; library ABBA OMAT-0 generic SrTiO3 `0.9969` (`0.9993` / `0.9945`, noisy), OFF24-M water `1.0007`, OFF23-L water216 `1.0037` (both orders slower), MP-0 SrTiO3 tie | this file |
| [gen-arch-neutral](#gen-arch-neutral) | Every `sm_120`-only block of the generated conv kernels on every GPU: the Cartesian forms of S119 / S121 / S122, S48's x-gradient rewrite and the S40 / S101 RED edge-vector updates (73 `__CUDA_ARCH__ == 1200` conditions dropped; 1,491 lines of per-path / read-add-store alternatives gone) | `python/gen_generic.py` (no arch conditions) | gen (every conv layer, every GPU) | DEFAULT (5060 Ti, sm_86, sm_89; A100 confirmation queued) | S129 | 5060 Ti SASS identical (136 kernels); RTX 4000 Ada OFF23-L water216 `0.9471`, POLAR-1-L `0.9886`, OMAT-0 generic `0.9940`, OFF23-M `0.9944`, MP-0 `0.9958`, OFF24-M `0.9961` (all both orders), OFF23-S / OMAT-0 small ties; A4000 OFF23-L `0.9418`, POLAR-1-L `0.9851`, OFF24-M `0.9887`, OMAT-0 generic `0.9949` (both orders), MP-0 / OMAT-0 small / OFF23-S ties, OFF23-M noise-limited | this file |
| [gen-lin-compact-ro](#gen-lin-compact-ro) | The terminal kind-1 layer's product and folded readout on its live channels, certified from exact zeros at load: a channel is dead when its product weights (the system's species) or its folded readout row are zero, or no projection column reaches it, and angular when a degree >= 1 projection column is nonzero; each projection keeps its live columns (MPtrj-2022.9 SrTiO3: 205 of 256 channels kept, 12 angular, degree 1-3 projections 8 / 8 / 16 columns wide instead of 256) and `gprod_ro1c_fused` runs the angular channels with the full program, the scalar-only ones with S127's cubic | `compact_layout`, `GenericLayer::lin_compact / n_ang / kept / d_pos`, `gprod_ro1c_fused_<sig>` (`launch_prod_ro1c_fused`); `LOUP_LIN_COMPACT=0` disables, `LOUP_DEBUG_COMPACT=1` prints the layouts | gen (kind-1 terminal layers: MPtrj-2022.9) | DEFAULT | S130 | MPtrj SrTiO3 10.98 -> 8.63 ms per step, library ABBA `0.7848`, NbCl5 `0.7029` | this file |
| [gen-l0-even-odd](#gen-l0-even-odd) | Layer 0's table rows with the even radial columns first, then the odd ones: `first_bwd_edge`'s lanes read the column pairs (2 lane, 2 lane + 1), now two contiguous 512 B runs instead of two loads that each touch the same 32 sectors | `first_col_pos` (`src/generic.cu`), the loader's row layout | gen (every hidden-table layer 0) | DEFAULT | S131 | library ABBA MP-0 SrTiO3 `0.9971`, NbCl5 `0.9934`, OMAT-0 generic SrTiO3 `0.9988` (4 rounds), each faster in both orders | this file |
| [gen-lin-compact](#gen-lin-compact) | Non-terminal kind-1 layers on their live channels (certificate as [gen-lin-compact-ro](#gen-lin-compact-ro); dead channels write zero outputs): each degree's projection keeps its live columns (position maps, widths padded to 8), `gprod_fwdc` / `gprod_bwdc` run on the compact positions and scatter their outputs to the dense layout, so the consumers keep their weights: MP-0 medium's layer 0 (128 kept, 38 angular: degree 1-3 projections 40 columns wide instead of 128), MPtrj-2022.9's layer 0 (251 kept: 256 / 192 / 144 / 128) | `compact_layout`, `GenericLayer::d_order / d_pos`, `gprod_fwdc / bwdc_<sig>` (`launch_prod_c`); `LOUP_LIN_COMPACT=0` | gen (MP-0 medium, MPtrj-2022.9) | DEFAULT | S132 | library ABBA MP-0 SrTiO3 `0.9036` (3.86 -> 3.49 ms), NbCl5 `0.8748` (degree-prefix widths); the per-degree maps then MPtrj SrTiO3 `0.9920`, NbCl5 `0.9464` (MP-0 `1.0095`), padding to 8 MPtrj `0.9799` / `0.9911` (MP-0 SrTiO3 `1.0035`, NbCl5 tie) | this file |
| [gen-conv-bwd-sender](#gen-conv-bwd-sender) | The pruned lx 1 backward ([gen-conv-prune](#gen-conv-prune)) owned by the sender: the neighbour list is symmetric, so block j walks its own row reversed, gathers each neighbour's two `dmid0` values per channel, keeps its own features in registers and writes its x gradient once (a fixed-order sum over its four warps, no atomics); the reversed edge's force goes into the row's own slot, negated | `emit_conv_bwd_l1s_sender` -> `gconv_bwd_L1sr<NCH, WANT_DX, PRELOC>` (C 128 / 256; `LOUP_SENDER_BWD=0`: the receiver-owned kernel) | gen (MP-0 medium's second interaction) | DEFAULT | S135 | `gconv_bwd_L1s` 1,023 -> 764 us per force call (MP-0 SrTiO3); library ABBA MP-0 SrTiO3 `0.9166` (3.55 -> 3.26 ms), NbCl5 `0.9343` | this file |
| [gen-conv-fwd-dict](#gen-conv-fwd-dict) | The forward conv's radial rows from a per-group dictionary in shared memory: blocks of 32 consecutive (same-species) receivers x 8 channels, the group's most used slabs (at most KD, each used at least twice, chosen per force call from the precomputed slabs) copied once per block, every other slab read from the table through the same per-edge pointer | `gconv_fwd_L1d / L1sd<KD>`, `conv_dict_build_kernel` (`launch_conv_fwd` variant 3; reverted) | gen (lx 1 forward at C 128) | REJECTED | S138 | `gconv_fwd_L1` 1,693 -> 4,306 us per step at KD 96 (one 8-warp block per SM) and 2,717 at KD 40 (two), MP-0 `L1s` 662 -> 1,278 / 1,168, plus 37-51 us of dictionary builds; MD ABBA OMAT-0 generic SrTiO3 `1.300`, MP-0 `1.189` (both orders) | this file |
| [gen-conv-fwd-path-teams](#gen-conv-fwd-path-teams) | The generic lx 1 forward conv's ten paths split between warp teams of one receiver block (round-4 research: `f2_0`, two 128-thread teams owning paths {1,3,4,6,7} / {0,2,5,8,9}, 64 registers; `f3_0`, three teams, 56 registers), each output component in one team with its accumulation order | scratch `launch_conv_fwd` variants 3 / 4 (reverted) | gen (lx 1 forward at C 128) | REJECTED | S139 | nsys us per step, OMAT-0 generic: SrTiO3 R5 1,709, `f2_0` 2,291 (+34%), `f3_0` 2,250, the one-receiver R1 2,283; NbCl5 R5 322, `f2_0` 355, `f3_0` 351; step 7.97 -> 8.43 ms | this file |
| [gen-l0-bwd-lsu](#gen-l0-bwd-lsu) | Layer 0's edge backward on fewer load/store-pipe instructions: each staged edge's metadata (receiver, sender species, slab, t, slope scale) read by the warp as two broadcast shared loads instead of six shuffles, and the radial pull reduced in the unused slot 0 of the 16-value angular fold instead of its own five-shuffle butterfly | `first_bwd_edge_kernel` (`s_meta`, `s_sxi`) | gen (hidden-table layer 0 with <= 96 columns: OMAT-0, MP-0, MPtrj, OFF) | DEFAULT | S140 | `first_bwd_edge` 431 -> 379 us per step (MP-0 SrTiO3), 493 -> 457 (OMAT-0 generic); library ABBA 5060 Ti MP-0 SrTiO3 `0.9846`, OMAT-0 generic `0.9976`, OFF23-M water216 `0.9880`; RTX 4000 Ada MP-0 SrTiO3 `0.9895`, NbCl5 `0.9933`, OMAT-0 generic `0.9978`, OFF23-M tie | this file |
| [gen-conv-fwd-pruned-r5](#gen-conv-fwd-pruned-r5) | The pruned lx 1 forward (`gconv_fwd_L1s`, [gen-conv-prune](#gen-conv-prune)) stages only the four degree-0 / 1 harmonics per edge (512 B per receiver instead of 2,048), its R > 1 group barriers take literal ids (an id in a register reserves all 16 hardware barriers: one block per SM), and on `sm_120` it runs at the 16 KB shared-memory configuration (carveout 10%) | `emit_conv_fwd` (`sh4`, `bar_code`), `pruned_r5_carveout()` in the generated launcher | gen (MP-0 medium's second interaction) | DEFAULT (5060 Ti only; sm_89 not measured) | S141 | `gconv_fwd_L1s` 648 -> 576 us per force call (`ncu`, MP-0 SrTiO3); MD MP-0 SrTiO3 `0.985`, NbCl5 `0.974` (lab); develop library against `d6e97b7` SrTiO3 `0.984` | this file |
| [gen-conv-fwd-r6](#gen-conv-fwd-r6) | Six receivers per forward conv block (R6, 768 threads) instead of five | lab `LOUP_LAB_R=6` (reverted) | gen (OMAT-0 generic, MP-0) | REJECTED (5060 Ti only) | S141 | OMAT-0 generic `gconv_fwd_L1` 1,594 -> 1,579 us (`ncu`), MD a tie; MP-0 pruned 598 -> 600 us | this file |
| [gen-conv-fwd-bar-literal-full](#gen-conv-fwd-bar-literal-full) | Literal barrier ids in the full lx 1 forward (`gconv_fwd_L1` R5) as well | lab (reverted) | gen (OMAT-0 generic) | REJECTED (5060 Ti only) | S141 | MD OMAT-0 generic SrTiO3 +0.7% (7.810 / 7.797 against 7.739 / 7.755 ms with the register id) | this file |
| [gen-conv-bwd-fold4](#gen-conv-bwd-fold4) | The lx <= 1 conv backwards fold their four pull partials (`pull_Gx` / `Gy` / `Gz` / `R`) together: the two first xor stages split the values between the lanes, the last three are plain, then lane 0 gathers the other three sums (9 shuffles and 6 adds instead of 20 and 20; lane 0's sums are bit for bit the plain fold's) | `FOLD4` in `emit_conv_bwd_lp` and `emit_conv_bwd_l1s_sender` (`python/gen_generic.py`) | gen (`gconv_bwd_L1`, `L1s`, `L1sr`, `L2lp`) | DEFAULT (bit-exact; timed on the 5060 Ti only) | S142 | `gconv_bwd_L1` 2,773 -> 2,741 us per force call (nsys, six interleaved rounds, OMAT-0 generic SrTiO3); 952 -> 864 static instructions, 62 registers | this file |
| [gen-first-bwd-edge-j64](#gen-first-bwd-edge-j64) | `first_bwd_edge_kernel` compiled for a 64-column layer-0 table (J = 65, two columns per lane): the column predicates, the even-width test and `first_col_pos` fold away | template parameter `J_FIX`, dispatch on `L->J == 65` (`src/generic.cu`) | gen (layer 0 with 64 radial columns: OMAT-0 medium / small, MP-0 medium, ...) | DEFAULT (5060 Ti only; sm_89 not measured) | S142 | 424.3 -> 375.0 us per force call (OMAT-0 generic SrTiO3, four rounds), MP-0 NbCl5 62.4 -> 59.0 us; 1,984 -> 1,568 static instructions, 80 registers | this file |
| [gen-conv-fwd-y0-fma](#gen-s142-lab-screens) | The forward conv's paths 0 and 3 multiply by the constant `Y0 = 1` no more (`fmaf(w, x, acc)`) | lab (reverted) | gen | REJECTED (5060 Ti only) | S142 | `gconv_fwd_L1` R5 x1.002 (three rounds): 4 `FMUL` fewer, 2 `LDS` more per edge-channel | [gen-s142-lab-screens](#gen-s142-lab-screens) |
| [gen-conv-bwd-q-slots](#gen-s142-lab-screens) | The four receiver constants `q7` / `q8` of the backward's l = 3 paths staged in the spare `s_q` slots 40-43 | lab (reverted) | gen | REJECTED (5060 Ti only) | S142 | `gconv_bwd_L1` x1.002: 4 `FADD` per edge-channel traded for one `LDS.128` | [gen-s142-lab-screens](#gen-s142-lab-screens) |
| [gen-conv-fwd-tq32](#gen-s142-lab-screens) | 32-bit radial-table offsets in the R5 forward's staging (640 B less shared memory per block) | lab (reverted) | gen | REJECTED (5060 Ti only) | S142 | `gconv_fwd_L1` x1.005; same static instruction count (registers limit the block count) | [gen-s142-lab-screens](#gen-s142-lab-screens) |
| [gen-conv-bwd-expanded-path](#gen-s142-lab-screens) | One backward path (9) read as four FP32 coefficients (16 B) instead of the packed 8 B entry | lab stand-in table (reverted) | gen | REJECTED (5060 Ti only) | S142 | `gconv_bwd_L1` x1.022 (+61 us): the extra L2 traffic costs more than the saved decode | [gen-s142-lab-screens](#gen-s142-lab-screens) |
| [gen-readout-shfl16](#gen-s142-lab-screens) | The fused readout's first barrier replaced by width-16 shuffles of `y0` | lab (reverted) | gen | REJECTED (5060 Ti only) | S142 | `gprod_ro1_fused` x0.980, within its +-3% round-to-round scatter (an untouched variant read x0.975) | [gen-s142-lab-screens](#gen-s142-lab-screens) |
| [gen-readout-unit-seed](#gen-s142-lab-screens) | The fused readout's polynomial backward run with unit seed before the readout's barriers, scaled by the gradient after them | lab (reverted) | gen | REJECTED (5060 Ti only) | S142 | `gprod_ro1_fused` x0.989 (noise), registers 110 -> 124 | [gen-s142-lab-screens](#gen-s142-lab-screens) |
| [gen-jit-layer0](#gen-jit-layer0) | JIT stage 1 (`JIT_DESIGN.md`): layer 0's `first_fwd_kernel` and `first_bwd_edge_kernel` compiled at load by NVRTC with the model's species count, intervals, table width and stride, `K0`, `sh_perm` and pair symmetry as constants (one source, `src/layer0_kernels.cuh`, for both builds; disk cache of the cubins) | `LOUP_JIT=1` (`src/jit.cu`, `src/kernel_ir.cu`, `GenericModel::setup_jit`) | gen (layer 0 with up to 96 radial columns) | OFF (opt-in; a tie, 5060 Ti only) | S143 | `first_bwd_edge` 374.4 -> 375.1 us, `first_fwd` 231.5 -> 230.3 (OMAT-0 generic SrTiO3); OFF23-S 28.2 -> 28.7 / 15.3 -> 15.0; MH-1 21.2 -> 20.7 / 8.3 -> 8.3; static SASS 5-37% smaller, same registers; forces at the cross-process level; 5 gate cases (68 rows) pass | this file |
| [gen-jit-layer0-grid](#gen-jit-layer0) | The same with the spline grid's numbers compiled in as literals (`LOUP_JIT_BAKE_GRID=1`, lab knob) | `Layer0IR::bake_grid` | gen | REJECTED (5060 Ti only) | S143 | OFF23-S `first_bwd_edge` 28.2 -> 28.9 us, `first_fwd` 15.3 -> 15.4 (and OMAT-0 generic +0.9% / +2.2% in the first job): seven bands become select chains over literals (about 60 instructions more per kernel than the grid argument) where the argument costs one indexed constant load per field | [gen-jit-layer0](#gen-jit-layer0) |
| [gen-jit-conv](#gen-jit-conv) | JIT stage 2: a conv layer whose width has no built-in instance compiled at load with its width as a constant (`src/generated_conv.cuh`, embedded), instead of the launchers' run-time-width branch | default (`LOUP_JIT=0` off; `LOUP_CONV_GENERIC=1` forces every conv layer there, tests) | gen (conv widths outside 128 / 256 / 224, e.g. OFF23-S's forward at 96) | DEFAULT (5060 Ti only) | S144 | OFF23-S water216 MD `LOUP_JIT=0` vs default b/a 1.014 (orders 1.020 / 1.009), inside the single-run spread; forces at the cross-process level; tests | this file |
| [gen-jit-products](#gen-jit-products) | JIT stage 3: each bundle carries its products' source (`gen_product.py`, `L<t>.prod_src`); a signature the library was not built with is compiled at load instead of needing `nvcc` | default (`LOUP_JIT_PRODUCTS=1` compiles every product so, gates; `LOUP_JIT=0` refuses such a bundle) | gen (every family) | DEFAULT (coverage; 5060 Ti only) | S144 | with every product compiled from the bundle 92/92 gate rows over seven families (worst force / stress 2.63 / 1.83); a renamed-signature bundle compiles and matches; 1.3 s per product compile, then the disk cache | this file |
| [gen-retire-specialised](#gen-retire-specialised) | JIT stage 5: the specialised OMAT-0-medium path retired (`interaction0.cu`, `model_loader.cu`, `generated_kernels.cuh`, `gen_kernels.py`, `export_omat0.py`); OMAT-0 medium runs the generic path | always (`arch=omat0_medium_spec` bundles refused) | OMAT-0 medium | DEFAULT (owner's approval; 5060 Ti only) | S144 | MD specialised -> generic: SrTiO3 7.905 -> 7.671 ms/step (b/a 0.970, orders 0.972 / 0.969), NbCl5 1.756 -> 1.713 (0.975, 0.975 / 0.976); library 10.48 -> 9.97 MB | this file |
| [gen-conv-tune-early](#gen-conv-tune-early) | The conv forward variants timed after 50 force passes when no rebuild has come (a solid near its lattice, LAMMPS's pair style under `fix npt`); the first rebuild still times them again | `tune_early_variants` (`LOUP_CONV_TUNE=0` disables) | gen (lx 1, `C = 128`) | DEFAULT on the local `release/v1` (5060 Ti only) | release, O41 | the benchmark's SrTiO3 cells from rest, f g g f f g g f: OMAT-0 medium 5,000 / 10,140 atoms `0.978` / `0.978`, MH-1 5,000 `0.992`; OFF24-M water tie (`0.999`, it rebuilds first); 20-39 ms of timing | [gen-conv-tune-early](#gen-conv-tune-early), [§6.39][s639] |
| [gen-jit-epilogue-bound](#gen-jit-epilogue-bound) | JIT stage 4 bound: what epilogue fusion chosen from the IR (gate, readout, density into the GEMM epilogues) could still save | – | gen | MEASUREMENT (not built; 5060 Ti only) | S144 | the gate kernels left after S137 are 3.9% / 3.8% of kernel time on MH-1 NaCl216 / SrTiO3, 3.1% on OMOL-0 XL water216, 1.7% on POLAR-1-L NaCl216 and absent elsewhere; readout and density already run inside the product kernels (`gprod_ro1_fused`), so the bound is ~2-3% on those families only | this file |

<a id="gen-jit-layer0"></a>
#### gen-jit-layer0: layer 0's kernels compiled at load (JIT stage 1)
- Switch: `LOUP_JIT=1` (off by default); `LOUP_NVRTC` names the NVRTC library (only that one is tried); `LOUP_DEBUG_JIT=1` prints each layer's IR and whether its kernels were compiled or read from the cache; `LOUP_JIT_BAKE_GRID=1` (lab knob) compiles the grid in as well.
- Stage: S143 (19 November 2026), the owner's request "do the single IR and jit compiler first" after the five-pillar redesign proposal; plan and later stages in `JIT_DESIGN.md`.
- Design:
  - The layer-0 kernels and the ZBL pair term moved, unchanged apart from their parameter names, from `src/generic.cu` to `src/layer0_kernels.cuh`.
  - `nvcc` compiles the header as before. The Makefile also embeds it, `kernels_common.cuh` and the new `generated_sh16.cuh` (`sh16_grad`, which `gen_generic.py` now writes to a header of its own) as raw strings.
  - At load `GenericModel::setup_jit` lowers layer 0 to a `Layer0IR` (`src/kernel_ir.hpp`). `layer0_jit_source` writes a prelude of `LOUP_JIT_L0_*` defines, and `LOUP_L0_INT` turns each argument into a `constexpr`.
  - `jit::build` (`src/jit.cu`):
    - loads NVRTC with `dlopen`, so the library gains no link dependency;
    - compiles for the device's `sm_XY`;
    - keeps the cubin in `<LOUP_CACHE_DIR or ~/.cache/loupmd>/jit/layer0_<key>.bin`, keyed by FNV-1a over source, headers, options, NVRTC version and architecture;
    - loads it with `cudaLibraryLoadData`;
    - returns `cudaLibraryGetKernel` handles.
  - The launches (`launch_jit_as`) pass the ahead-of-time kernel's parameter list to `cudaLaunchKernel`, inside the captured graphs as before.
  - On any failure (no NVRTC, a compile error, a refused cubin) the library prints one message and keeps the built-in kernels.
- Measured (5060 Ti, nsys over 16 force calls, three interleaved rounds, same library and plans, conv tuning off):

  | family | `first_bwd_edge`, AOT → JIT | `first_fwd`, AOT → JIT |
  | --- | --- | --- |
  | OMAT-0 medium generic SrTiO3 (R5) | 374.4 → 375.1 us (AOT the S142 `J_FIX = 65` kernel) | 231.5 → 230.3 |
  | OFF23-S water216 | 28.2 → 28.7 (`J_FIX = 65`) | 15.3 → 15.0 |
  | MH-1 NaCl216 (J 66, three columns per lane, no fixed-width AOT kernel) | 21.2 → 20.7 | 8.3 → 8.3 |

  - Static SASS without `NOP`s (offline NVRTC census of the models' IRs on a seven-band grid): `first_bwd_edge` 1,398 → 1,274, 1,031 → 897 and 1,412 → 1,365; `first_fwd` 1,312 → 1,028, 832 and 1,050. Registers are unchanged (80, `first_fwd` 54 → 53 / 45).
  - The fewer instructions buy no time: the edge backward is bound by its load/store pipe, and the S142 fixed-width kernel had already folded the constant that mattered (`J`).
- Accuracy:
  - Forces and energies against the built-in kernels with conv tuning off: OMAT-0 generic dF 3.6e-6 (two built-in runs: 4.6e-6), OFF23-S 2.2e-6 (1.3e-6), MH-1 1.6e-7 (2.3e-7). The difference is the order of the floating-point atomics between processes.
  - Gates with `LOUP_JIT=1`: OMAT-0 medium generic, OMAT-0 small, MH-1 and MP-0 medium oxide, OFF23-S organic. 68 rows, none failing; worst force / stress ratio 2.03 / 1.77.
- Cost: the first load of a model compiles three kernels; later loads read the disk cache. The compile was not timed on its own; `tests/test_jit.py`'s first test (a built-in run, a compiling run and a cached run of MH-1 NaCl54, each with its imports and model load) takes 7 s.
- Tests: 43 + 36 = 79 passed, including the new `tests/test_jit.py`: JIT against built-in, the cache file written and then read, and the fallback with `LOUP_NVRTC` pointing at a missing library.
- Status: OFF (opt-in; a tie on the 5060 Ti; sm_89 not measured). The infrastructure is what stages 2-3 of `JIT_DESIGN.md` build on: conv kernels for widths without an AOT instance, and products of models outside the build set without `nvcc`. The grid variant is REJECTED.
- Sources: this file, `JIT_DESIGN.md`.

<a id="gen-jit-conv"></a>
#### gen-jit-conv: conv layers of any width compiled at load (JIT stage 2)
- Switch: on by default; `LOUP_JIT=0` turns it off (the run-time-width branch again); `LOUP_CONV_GENERIC=1` sends every conv layer to the run-time-width path, so that with the JIT on every conv layer is compiled (tests).
- Stage: S144 (19 November 2026), the owner's "do all the stages".
- Design:
  - `gen_generic.py` writes the conv kernels to `src/generated_conv.cuh` (moved out of `generated_generic.cu`); the Makefile embeds it with the other JIT headers.
  - At load `GenericModel::setup_jit` lowers each conv layer to a `ConvIR` (`lx`, `C`, pruning, which of forward / backward lack a built-in instance). `conv_jit_source` compiles the run-time-width templates with `C_FIX` = the layer's width; the launchers (`conv_launch`) start the JIT kernel with the built-in kernel's parameter list.
  - `S`, `I` and the grid stay arguments: stage 1 measured that baking them buys nothing.
  - `jit::level()`: unset = stages 2 and 3, `LOUP_JIT=1` adds layer 0, `LOUP_JIT=0` nothing.
- Measured (5060 Ti): OFF23-S water216 (`lx` 0, `C` 96: its forward has no built-in instance), MD `a b b a`, two rounds, same library and plans: default (the JIT forward) 0.347 ms/step, `LOUP_JIT=0` (the run-time-width forward) 0.352; b/a 1.014, orders 1.020 / 1.009, inside the single runs' 0.342-0.362 spread.
- Accuracy: `tests/test_jit.py` compares the JIT conv kernels (`LOUP_CONV_GENERIC=1`, every layer compiled) with the run-time-width built-in ones at the cross-process level (conv tuning off).
- Status: DEFAULT (5060 Ti only). The models of the build set with built-in widths (128 and the other instances) compile nothing.
- Sources: this file, `JIT_DESIGN.md`.

<a id="gen-jit-products"></a>
#### gen-jit-products: products from the bundle's source (JIT stage 3)
- Switch: on by default for signatures the library lacks; `LOUP_JIT_PRODUCTS=1` compiles every product from the bundle (gates); with `LOUP_JIT=0` a bundle whose signature the library lacks is refused ("no compiled product kernel for signature X", with the reason).
- Stage: S144 (19 November 2026).
- Design:
  - The product emitter (`emit_product`, `_scalar_prune` and helpers) moved verbatim from `gen_generic.py` to `python/gen_product.py`; the generated files are byte-identical, and `gen_product.py` joins the generator's cache key and the bundle cache key (`EXPORTER_SOURCES`).
  - `export_generic.py` stores each layer's emitted source as `L<t>.prod_src` (U8).
  - The loader (`src/generic.cu`, `jit_product`) prepends the `kernels_common.cuh` / `generated_sh16.cuh` includes (`product_jit_source`) and fetches the kernels in the built-in table's order (`product_jit_names`: forward, backward, the fused readouts for `lmax_out` 0 at three block shapes, then `fwdc` / `bwdc`). One process-wide table per (signature, source) holds them.
  - On a compile failure the library warns and keeps the built-in kernel if it has one; otherwise the load fails with the reason.
- Measured (5060 Ti):
  - Gates with `LOUP_JIT_PRODUCTS=1` (every product compiled from the bundle): OFF23-S 8/8, OMAT-0 small 6/6, MP-0 medium 18/18, MPtrj 6/6, MH-1 18/18, POLAR-1-M 18/18, OMAT-0 medium generic 18/18; 92/92 rows, worst force / stress ratio 2.63 / 1.83.
  - A bundle whose signatures and sources were renamed (so the library has none of them) loads, compiles and matches the built-in run; with `LOUP_JIT=0` it is refused (`tests/test_jit.py`).
  - One product compiles in 1.3 s offline (NVRTC 13.0, `sm_120`); later loads read `<cache>/jit/prod_*.bin`.
- Status: DEFAULT (coverage; 5060 Ti only). A model outside the build set no longer needs `loupmd build-kernels`' `nvcc` step on `develop`; the release branch's plugin path (`release/v1`) is not changed here, and a release built from `develop` has to ship `gen_product.py`.
- Sources: this file, `JIT_DESIGN.md`.

<a id="gen-jit-epilogue-bound"></a>
#### gen-jit-epilogue-bound: what stage 4 (epilogue fusion from the IR) could save
- Stage: S144 (19 November 2026); a bound from the 19 November nsys profiles (`results/profiles-20261119/summary.md`), no code.
- Basis (share of kernel time per MD step, 5060 Ti):

  | case | gates (kind 4) |
  | --- | --- |
  | MH-1 NaCl216 | 3.9% (`gate_bwd` 66 us, `gate_fwd` 25 us of 2,365) |
  | MH-1 SrTiO3 | 3.8% |
  | OMOL-0 XL water216 | 3.1% |
  | POLAR-1-L NaCl216 | 1.7% |
  | every other family | none (no gate layers) |

  - S137 already moved the gate backward into the `W_2^T` GEMMs' epilogue ([gen-gate-bwd-epilogue](#gen-gate-bwd-epilogue)) and layer 0's gated store into its projections' epilogue ([gen-gate-fwd-store](#gen-gate-fwd-store)), where the plan is the own `sgemm128`. What remains are the gate passes beside GEMMs that run on other plans.
  - The readout and the density are already fused into the product kernels (`gprod_ro1_fused`, 81-91% of DRAM peak on OMAT-0).
  - A fusion keeps the gate's arithmetic and saves the pass's memory traffic and launches, so it saves at most the 1.7-3.9% above: about 2-3% of the step on MH-1, OMOL-0 and POLAR, nothing elsewhere.
- Status: not built. A per-family epilogue choice from the IR costs a GEMM template per (plan, epilogue) pair for a gain at the A/B noise level of those families.
- Sources: this file, `JIT_DESIGN.md`.

<a id="gen-retire-specialised"></a>
#### gen-retire-specialised: the specialised OMAT-0-medium path retired (JIT stage 5)
- Switch: none. Every bundle is `arch=generic`. `arch=omat0_medium_spec` bundles are refused ("... is no longer supported; re-export it"). `generic=` / `--generic` / `LOUP_GENERIC` are accepted and ignored.
- Stage: S144 (19 November 2026), the owner's "Its fine to retire the seperate kernels".
- Removed:
  - `src/interaction0.cu`, `src/model_loader.cu`, `src/generated_kernels.cuh`, `src/generated_kernels_signature.h`, `python/gen_kernels.py`, `python/export_omat0.py`;
  - ~740 lines of `src/engine.cu`: the spline / `w'` / `m1`-chunk variants and their timing (`tune_l1`, `choose_spline_rpb`), the specialised buffers and force pass;
  - the specialised overrides (`LOUP_SPLINE_VARIANT`, `LOUP_WPRIME_THREADS`, `LOUP_WPRIME_RCV`, `LOUP_M1_CHUNK`, `LOUP_GENERIC`);
  - the specialised variant matrix of `test_gate.py`;
  - the `act_pairs` output of `scatter_active_edges_kernel`.
- Kept: `src/model.hpp` keeps the error-check macros and `PackErrTracker`, which the generic loader uses. The library shrinks from 10.48 to 9.97 MB.
- Measured (5060 Ti, MD `a b b a`, two rounds, on the last library with both paths, same plans; specialised = a, generic = b):

  | system | specialised | generic | b/a (orders) |
  | --- | --- | --- | --- |
  | SrTiO3 (5,000 atoms) | 7.905 ms/step | 7.671 | 0.970 (0.972 / 0.969) |
  | NbCl5 (1,944 atoms) | 1.756 | 1.713 | 0.975 (0.975 / 0.976) |

  The 19 November nsys profile agrees in direction: kernel time 8,624 us generic against 8,739 us specialised per SrTiO3 step.
- Accuracy: the formerly specialised families gated on the generic-only library (`libloupmd_s5`), 90/90 rows. Worst force / stress ratios:

  | family | set | worst force / stress |
  | --- | --- | --- |
  | OMAT-0 medium | oxide | 2.03 / 1.75 |
  | MP-0b3 medium | oxide | 1.14 / 1.30 |
  | MPA-0 medium | oxide | 2.02 / 1.81 |
  | MatPES PBE | crystals | 0.98 / 1.00 |
  | MatPES r2SCAN | crystals | 1.35 / 0.58 |
- Tests: 47 + 35 = 82 passed on the generic-only library, including the new refused-bundle test (`tests/test_engine_guards.py`) and the rewritten `tests/test_export.py`.
- Status: DEFAULT (owner's approval; 5060 Ti only; sm_89 and the A100 not measured since S100). The release branch still has both paths.
- Sources: this file, `JIT_DESIGN.md`.

<a id="gen-conv-bwd-fold4"></a>
#### gen-conv-bwd-fold4: the four pull partials of the L1 conv backwards folded together
- Switch: none (generator, `FOLD4` in `python/gen_generic.py`; the lab variant `v23` measured it first).
- Stage: S142 (19 November 2026), the owner's eighth idea list (item 23).
- Design: each edge-warp of `gconv_bwd_L1` (and `L1s`, `L1sr`, `L2lp`) ends with four warp sums read by lane 0. The plain fold runs five xor stages per value (20 shuffles, 20 adds). Now the stage at 16 sends `Gz` / `R` from the lower lanes and `Gx` / `Gy` from the upper ones (two shuffles), the stage at 8 halves again (one), three plain stages follow, and lane 0 reads the other three sums from lanes 8, 16 and 24 (three): 9 shuffles, 6 adds, 6 selects. Every value is summed over the same pairs in the same tree, and IEEE addition commutes, so lane 0's sums are the plain fold's bits (the split of `src/warp_fold.cuh`).
- Measured (5060 Ti, OMAT-0 medium generic SrTiO3, R5 forced, same GEMM plans, nsys over 16 force calls): `gconv_bwd_L1` 2,773 -> 2,741 us per call (medians of six interleaved rounds; dev 2,754-2,784, `v23` 2,728-2,770; an earlier three-round job 0.997). Static SASS 952 -> 864 instructions (`SHFL` 40 -> 18, `FADD` 63 -> 36), 62 registers, no spill.
- Library: the S142 candidate (with [gen-first-bwd-edge-j64](#gen-first-bwd-edge-j64)) against the develop library `595ee89`, see there.
- Status: DEFAULT (bit-exact; timed on the 5060 Ti only).
- Sources: this file.

<a id="gen-first-bwd-edge-j64"></a>
#### gen-first-bwd-edge-j64: the layer-0 edge backward compiled for 64 radial columns
- Switch: none (`first_bwd_edge_kernel<2, ZBL, STRESS, 65>` runs when `L->J == 65`; other widths keep the run-time kernel).
- Stage: S142 (19 November 2026), the owner's eighth idea list (item 29).
- Design: with `J` a compile-time 65 the even-width branch is the only one, `2 * lane + 1 < Jp` is always true and `first_col_pos(col, Jh)` is a constant per lane, so the kernel shrinks from 1,984 to 1,568 static instructions at the same 80 registers (6 blocks per SM).
- Measured (5060 Ti, same plans, nsys over 16 force calls): OMAT-0 generic SrTiO3 424.3 -> 375.0 us per call (four interleaved rounds, spread under 1 us; lab `v29`); MP-0 medium NbCl5 62.4 -> 59.0 us.
- Library (S142 candidate: this and [gen-conv-bwd-fold4](#gen-conv-bwd-fold4)) against the develop library `595ee89` on shared plans, MD medians of 6 x 256 steps, `d c c d`: OMAT-0 medium generic SrTiO3 7.733 / 7.751 -> 7.670 / 7.674 ms (`0.991`), OMAT-0 small SrTiO3 `0.988`, MP-0 medium SrTiO3 3.049 / 3.051 -> 3.011 / 3.014 (`0.988`), MP-0 medium NbCl5 `1.020` in the first job and `0.984` in the second (0.6655 / 0.6590 -> 0.6515 / 0.6519 ms; kernels: all `0.993`, the two changed ones -2.3 and -3.4 us). Forces against the develop library at its own run-to-run level (OMAT-0 generic dF 2.6e-6, POLAR-1-M NbCl5 5.3e-5).
- Gates (3x, lab copies of the cached references): OMAT-0 medium generic oxide (worst force / stress ratio 2.01 / 1.79), OMAT-0 small oxide, MP-0 medium oxide default and with prune / sender backward / compaction / chain fold off, POLAR-1-M crystals (2.66 / 1.16; 2.23 on the develop library, within the 2.2-3.1 plan scatter of AGENTS.md), POLAR-1-S and -L crystals, MPtrj-2022.9, MPA-0 medium and MatPES-PBE oxide, MH-1 oxide, OFF23-S and -M organic: 13 cases, 213 rows, none failing. Tests: 41 + 36 = 77 passed (`tests/test_engine.py`, `test_engine_guards.py`, `test_export.py`, `test_families.py`, `test_gate_cache.py`, `test_gate_wrapper.py`, `test_polar_reference.py`, `test_polar_strain_reference.py`).
- Status: DEFAULT (5060 Ti only; sm_89 not measured).
- Sources: this file.

<a id="gen-s142-lab-screens"></a>
#### gen-s142-lab-screens: the other generator-level ideas of the eighth 19 November list
- Switch: none (lab variants of develop's generated kernels, `.tmp_o/lab_v123.py`, `lab_v4.py`, not kept).
- Stage: S142 (19 November 2026), the owner's items 21, 22, 24, 26, 33 and 34.
- Method: each variant is develop's generated file with one edit, linked with develop's other objects; OMAT-0 medium generic SrTiO3, R5 forced, the develop library's GEMM plans copied to every side, nsys over 16 force calls in three (or four) interleaved rounds. Kernels the edit does not touch scatter by about +-1% between rounds (the readout by +-3%).
- Item 21, `fmaf(w, x, acc)` for the forward's `Y0 = 1` paths (15 updates): static SASS 4 `FMUL` fewer and 2 `LDS` more (the compiler had read `she[0..3]` as one vector), `gconv_fwd_L1` x1.002; forces at float32 rounding (dF 3.9e-6).
- Item 22, `q7` / `q8` of the two l = 3 paths in `s_q` slots 40-43: the four `FADD` per edge-channel move into the prologue and one `LDS.128` joins the loop, `gconv_bwd_L1` x1.002. With 21 and 23 together (`vall`) the backward read 2,731 us against 2,741 for 23 alone, within the rounds' scatter.
- Item 24, 32-bit table offsets in the R5 staging: shared memory 20,864 -> 20,224 B, the same 784 static instructions (the block count is set by the 96 registers), `gconv_fwd_L1` x1.005.
- Item 26, path 9 of the backward as four FP32 coefficients (a zero-filled 8 MB stand-in table at the same index; timing only): 8 static instructions fewer, 64 registers (from 62), `gconv_bwd_L1` 2,751 -> 2,812 us (x1.022) in all three rounds.
- Item 34, the readout's first barrier replaced by width-16 `__shfl_sync` of `y0` (same summation order, forces at noise): barriers 4 -> 3, `gprod_ro1_fused` x0.980, but a variant that does not touch the readout read x0.975 in the same job.
- Item 33, the readout's polynomial backward with unit seed before the barriers and the stores scaled by the gradient after them: registers 110 -> 124 instead of fewer, `gprod_ro1_fused` x0.989 (four rounds); the lab edit also had a force error (dF 0.14 eV/A) that was not chased, since the timing gave no reason to.
- Status: REJECTED (5060 Ti only).
- Sources: this file.

### MACE-POLAR-1 long range (`src/polar.cu`)

| ID | Idea | Switch/flag | Path | Status | Stage | Effect | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [pol-double-sf](#pol-double-sf) | Structure factors and feature passes accumulated in double | – | POLAR | DEFAULT | S6 | not recorded alone | [§5.1][s51] |
| [pol-fixed-point-phase](#pol-fixed-point-phase) | Fractional coordinates as 32-bit fixed point; exact n . s mod 1 | `kphase` | POLAR | DEFAULT | S6 | perfect NaCl 10x4x4 residual force 3.0e-4 -> 8.7e-5 eV/A | [§5.4][s54] |
| [pol-mlp-aliasing](#pol-mlp-aliasing) | LayerNorm-MLP reverse wrote its GEMM output over its input | `mlp_bwd` | POLAR | FIX | S6 | NaCl 6x6x6 forces 3-11 eV/A -> 1e-5 eV/A | [§5.4][s54] |
| [pol-corrected-stress](#pol-corrected-stress) | Stress with the k-space terms' cell dependence (MACE PR 1718) | `lr_virial_kernel` | POLAR | DEFAULT | S6 | installed PolarMACE misses up to 2e-5 eV/A^3 | [§5.1][s51] |
| [pol-precise-math](#pol-precise-math) | Precise `expf` / `sqrt` for the float32 stress error | – | POLAR | REJECTED | S6 | no change | this file |
| [pol-stress-diagnosis](#pol-stress-diagnosis) | Where POLAR's float32 stress error comes from | – | POLAR | MEASUREMENT | S6 | local electron energy term; k-space virial to 1e-10 | this file |
| [pol-set-cell](#pol-set-cell) | Re-capture the force graph on every cell change | `PolarLR::set_cell` | POLAR | FIX | round 6 | strained cell on a reused engine: 1e-6 eV/atom, 9e-5 eV/A off -> identical | [§3.2 S5][s32] |
| [pol-sf-f32](#pol-sf-f32) | Structure factors: float32 chunk sums folded into double, coalesced `float4` loads | `sf_kernel<NC>` | POLAR | DEFAULT (5060 Ti only) | S7 | ABBA b/a 0.833 (M `NbCl5`) to 0.987 (L NaCl) | this file |
| [pol-contig-weights](#pol-contig-weights) | Per-degree contiguous `Wpot` / `Wq` / `le_W*` slices, fused `qnew = qin + out` | – | POLAR | REJECTED | S7 | ABBA b/a 0.952-1.045, mixed | this file |
| [pol-kpass-32](#pol-kpass-32) | 32-thread blocks for the per-atom k-space passes when N <= 512 | – | POLAR | REJECTED | S7 | NaCl 216 (with pol-contig-weights): +7.4% (S), +6.0% (M) | this file |
| [pol-k-split](#pol-k-split) | Per-atom k passes split over k chunks (`blockIdx.y`), chunk partials reduced in fixed order | `k_chunk`, `k_reduce_kernel` | POLAR | DEFAULT (5060 Ti only) | S8 | ABBA b/a 0.876 (S NaCl 1,728) to 0.978 (L NaCl 216); M `NbCl5` 0.928 | this file |
| [pol-2d3d-nodiv](#pol-2d3d-nodiv) | 2D/3D div-free grids for `add_bias`/`bcast_mul`/`inv` + fused `inv2_kernel` | – | POLAR | REJECTED | S15 | `POLAR-1-M` `NbCl5` quick ABBA `b/a = 1.0004` (27.06 -> 27.07 ms; DRAM-BW bound) | this file |
| [pol-sf-tiled](#pol-sf-tiled) | Multi-`k`-vector warp tiling (`8` warps = `8` `k`-vectors) sharing SoA `s_X[NC][129]` + `s_frac[3][129]` (`TILE = 128`, `float4` `X` loads) | `sf_kernel_tiled<NC, TK>`, `launch_sf` | POLAR | DEFAULT (5060 Ti only) | S15 | `sf_kernel<16/8/4>` 900/455/233 -> 316/150/84 us; ABBA (fresh plans) `POLAR-1-M` `NbCl5` 27.00 -> 25.00 ms (`0.926`), `NaCl` 4.41 -> 4.36 (`0.990`), `S` `NaCl` 1.92 -> 1.86 (`0.966`), `L` `NaCl` 8.36 -> 8.31 (`0.993`) | this file |
| [pol-dot-fold](#pol-dot-fold) | SCF / electron-energy weights composed with `dot^T` at load: `Z = pot Wpot' + q Wq' + fm Wnf'`, `Zq = q le_Wq' + bq'` (`Zv` alike), so one C x C GEMM per SCF step and l in each direction instead of two and none for the electron energy | `fold_dotT_kernel`, `Impl::up_fold`, `P.fold` (`sm_120` and cc 8.0; `LOUP_POLAR_FOLD=0` disables, `=1` forces elsewhere) | POLAR | DEFAULT (5060 Ti; A100 since S84) | S52, S84 | `POLAR-1-M` `NaCl216` GEMM launches 165.6 -> 149.5 per step; final binary ABBA `POLAR-1-M` `NaCl216` `0.888` / `0.922`, `NbCl5` `0.906` / `0.906`, `POLAR-1-S` `NaCl216` `0.911` / `0.914`, `POLAR-1-L` `NaCl216` `0.886` / `0.895`; A100 in-process (S84): `POLAR-1-S` / `-M` / `-L` `NaCl216` `0.922` / `0.892` / `0.887`, `-M` `NbCl5` `0.885`; A100 library ABBA s81 -> s84 with the own-SGEMM extensions (S84c): `0.795` / `0.802` / `0.814`, both orders | this file |
| [pol-bias-ln-fuse](#pol-bias-ln-fuse) | Long-range pass launch trims: the MLP hidden layers' bias add folded into the LayerNorm-SiLU forward (`z += b` in place, then the norm; S85), and the SCF / electron-energy `q` copies with their add as one `add8_to_kernel` (S86) | `bias_ln_silu_fwd_kernel` (`mlp_fwd`), `add8_to_kernel` | POLAR | DEFAULT (cc 8.0 too, owner's decision) | S85, S86 | library ABBA on shared plans, 5060 Ti, S85 / S86: `POLAR-1-S` `NaCl216` `0.995` / `0.995`, `-M` `0.998` / `0.997`, `-L` `0.995` / `0.999`; the same float sums; A100 (S86c, S84 -> S86, shared plans, 3 rounds): S `0.989`, M `0.988`, L `1.011` (slower in both orders); A100 crystal gates pass (S86g) | [below](#pol-bias-ln-fuse) |
| [pol-tpo-fold](#pol-tpo-fold) | Each SCF update MLP's last layer (affine, no activation) composed with `tpo_l` at load (`W tpo_l^T`, `b tpo_l^T`, double accumulation), so `P_l` comes from the last hidden layer (64 / 128 columns) instead of `nl` (C = 512); the readout's unused `P_2` / `nw_2` (POLAR-1-L) no longer computed | `Update::tpo_fold` (with `P.fold`: sm_120 and cc 8.0; `LOUP_POLAR_FOLD=0` disables) | POLAR | DEFAULT (5060 Ti; cc 8.0 not measured) | S115 | library ABBA on shared plans, 3 rounds: POLAR-1-S NaCl216 `0.944`, -M `0.957`, -L `0.976`, every round and order below 1; gates pass on both paths | this file |
| [pol-mono-channels](#pol-mono-channels) | POLAR-1-S (lmax 0): the k-space passes on the channels that can be nonzero, certified at load from the weights' exact zeros (sources' and readouts' dipole columns; Wpot / le_Wv rows of field features): 2 + 2 + 1 + 4 + 4 of 8 + 8 + 4 + 16 + 16 channels in the five structure-factor transforms, 4 of 16 features in `feat_pass`, monopoles and 4 of 16 feature gradients in `grad_pass`; dead columns written as 0 | `Impl::mono` (`PolarLR::load`; `LOUP_POLAR_MONO=0` disables), `launch_sf<NC, NL>`, `feat_pass_kernel<MONO>`, `grad_pass_kernel<.., MONO>` | POLAR (POLAR-1-S) | DEFAULT (5060 Ti only) | S118 | library ABBA on shared plans: POLAR-1-S NaCl216 `0.948` (3 rounds), NbCl5 `0.892` (2 rounds), every round and order below 1; forces at HEAD's own spread (NbCl5 identical); gates pass on both GEMM paths | this file |
| [pol-zero-blocks](#pol-zero-blocks) | POLAR-1: weight blocks certified exactly zero at load are skipped: every update's `Wpot` / `Wq` l block (SCF forward and reverse GEMMs; the first GEMM that runs initialises the sum) and the electron energy's `le_Wq` / `le_Wv` blocks above the highest nonzero l (`Zq_l` / `Zv_l`, their inv terms and the reverse): POLAR-1-L's l = 2 blocks | `Update::zpot / zq`, `Impl::le_lq / le_lv` (`PolarLR::load`; `LOUP_POLAR_ZBLK=0` disables) | POLAR (L) | DEFAULT (5060 Ti, sm_86, sm_89) | S123 | GEMM launches 233.6 -> 221.4 per step, inv kernels 112 -> 72 us (POLAR-1-L NaCl216); library ABBA `0.9767` (5060 Ti, folded), `0.9480` (`LOUP_POLAR_FOLD=0`), `0.9578` (A4000), `0.9643` (RTX 4000 Ada); exact to fp32 rounding | this file |
| [pol-ro-scalar](#pol-ro-scalar) | POLAR-1-S (lmax 0): the update readout without vectors runs its scalar path alone: the readout GEMMs over the scalar half (N 64 -> 32 forward, K 64 -> 32 reverse), no gate or vector work in `ro_fwd_kernel` / `ro_bwd_kernel` | `ro_fwd_kernel` / `ro_bwd_kernel` (`!has_v`) | POLAR (S) | DEFAULT (5060 Ti, sm_86, sm_89) | S124 | readout kernels 38.0 -> 16.3 us per step (NaCl216); library ABBA (with S123) NaCl216 `0.9708`, NbCl5 `0.9787` (5060 Ti), `0.9763` / `0.9830` (A4000), `0.9903` / `0.9952` (RTX 4000 Ada; NbCl5 mixed orders, a tie) | this file |
| [pol-hidden-fold-l2](#pol-hidden-fold-l2) | POLAR-1-L: the degree-2 hidden chain folded into its consumers: no layer forms `hout[2]` (it aliases `y[2]`); the mixers become `W_p_v B_v` (`B_2 = M_2`, `B_1 = M_1 + W_sc_2 B_2`, `B_0 = M_0 + W_sc_1 B_1`), the next layers' `linear_up` take `W_p_0 W_up_1`, `W_p_1 W_up_2`, `W_p_0 W_sc_1 W_up_2`, and the composed sources stay exactly zero (skipped); composed in double at load, rounded once | `GenericModel::setup_lr_fold`, `GenericLayer::hfold / x_extra / sc_extra`, `PolarLR::set_hidden_fold` (`sm_120`; `LOUP_POLAR_HFOLD=0` disables, bit 2 = degree 2) | gen + POLAR (L) | DEFAULT (5060 Ti only) | S136 | GEMM launches 216.3 -> 208.2 per step (against the zero-source skip alone), sgemm128 35.5 -> 25.4; library ABBA POLAR-1-L NaCl216 `0.9234` (`0.9218` / `0.9250`, 3 rounds), with degree 1 `0.9143` (`0.9158` / `0.9129`); -28 MiB; gates L 6 / 6, M 18 / 18, S 5 / 5 on every path | this file |
| [pol-hidden-fold-l1](#pol-hidden-fold-l1) | POLAR-1-M / -L: the first hidden vector `h_0[1] = y_0[1] W_p_0[1]` never formed: `W_p_0[1]` composed into layer 1's `W_up_1` and `W_sc_1`, `LR.mix_0_1` and the three m blocks of `LR.src_0`'s l = 1 rows; the reverse adds all four consumers' gradients into `dy_0[1]` | as above (bit 1 = degree 1) | gen + POLAR (M, L) | DEFAULT (5060 Ti only) | S136 | 2 GEMM launches fewer per force call (forward and transpose `3N x 512 x 512`); library ABBA POLAR-1-M NbCl5 `0.9807` (`0.9807` / `0.9807`, 2 rounds, 21.05 -> 20.64 ms), NaCl216 `0.9766` (`0.9752` / `0.9779`, 3 rounds), POLAR-1-L NaCl216 `0.9766` (`0.9759` / `0.9774`); NbCl5 -24 MiB | this file |
| [pol-zero-sources](#pol-zero-sources) | POLAR-1-L: the long-range source blocks certified exactly zero (every layer's l = 2 rows of `LR.src_t`) skip their forward and reverse `qsrc` GEMMs (the first that runs takes beta 0) | `PolarLR::Impl::src_zero`, `src_block_zero` (`LOUP_POLAR_ZBLK=0` disables) | POLAR (L) | DEFAULT | S136 | GEMM launches 222.4 -> 216.3 per step; library ABBA POLAR-1-L NaCl216 `0.9855` (`0.9852` / `0.9858`, 2 rounds, with the hidden fold off) | this file |
| [pol-sf-split-fold](#pol-sf-split-fold) | The structure factor's FP64 warp fold of its `2 NL` per-lane partials split: each xor step halves the values a lane carries, so lane L ends with partial `L >> SH`'s warp sum, bit for bit the plain xor fold's, with far fewer FP64 adds | `warp_fold_split` (`src/warp_fold.cuh`) in `sf_kernel_tiled` / `sf_kernel_1` | POLAR | DEFAULT (bit-exact; timed on the 5060 Ti only) | S141 | MD POLAR-1-M NbCl5 19.65 -> 19.22 ms (`0.979`), NaCl216 `0.989`, POLAR-1-L NaCl216 `0.994` | this file |

### Measurements without a switch

| ID | What | Status | Result | Evidence |
| --- | --- | --- | --- | --- |
| [meas-stage-spans](#meas-stage-spans) | Stage spans and top kernels, both GPUs | MEASUREMENT | `w'` 36%, spline 23% of the `SrTiO3` step (5060 Ti) | [§2][s2] |
| [meas-ncu](#meas-ncu) | Nsight Compute facts, 5060 Ti | MEASUREMENT | `w'` issue-bound (80% issue slots); spline L2-bound (83%) | [§2][s2] |
| [meas-size-scaling](#meas-size-scaling) | System-size scaling, `SrTiO3` 135-40,000 atoms | MEASUREMENT | linear above ~1,000 atoms: 1.66-1.72 us/atom-step | [§1][s1] |
| [meas-nve-drift](#meas-nve-drift) | NVE drift, `SrTiO3`, 1 ps | MEASUREMENT | -0.00011 / -0.00012 meV/atom/ps | [§1][s1] |
| [meas-ada-counters](#meas-ada-counters) | Ada performance counters | BLOCKED | `ERR_NVGPUCTRPERM`, needs admin | [§4.1 #2][s41] |
| [meas-family-bench](#meas-family-bench) | MD speed of every family, both GPUs, against FastMACE's documented numbers | MEASUREMENT | POLAR-1 level to 20% slower than FastMACE (11 Nov lines) | [§5][s5] |
| [meas-plan-variance](#meas-plan-variance) | GEMM plans differ between library builds | MEASUREMENT | POLAR-1-M NaCl 216 S8/S7 b/a 1.013 with each build's cached plans, 0.969 after both retuned | this file |
| [meas-temperature-cost](#meas-temperature-cost) | Where a thermalised (300 K) `SrTiO3` force pass loses time against one at rest, per kernel, 5060 Ti | MEASUREMENT | the four tabled kernels lose L1 slab reuse (spline 1.58 -> 1.79 ms, i0 backward 497 -> 552 us); the dense contractions are DRAM-bound and do not change | this file |
| [meas-conv-ablation-bounds](#meas-conv-ablation-bounds) | Upper bounds for table-traffic, atomic and angular-arithmetic ideas: kernel times with one cost removed (timing-only builds, wrong forces), OMAT-0 generic and MP-0 SrTiO3, 5060 Ti | MEASUREMENT | free forward-conv table reads `gconv_fwd_L1` -26% (OMAT-0, 468 us per call) / -40% (MP-0); free backward table reads -5% / -8%; no sender-gradient atomics -5% / -21%; layer 0: free table -6% forward / -9% backward, free angular arithmetic -1-2% forward | this file |
| [meas-conv-bwd-algebra-bound](#meas-conv-bwd-algebra-bound) | Upper bound for a bond-frame (SO(2)) interaction-1 backward: OMAT-0 generic `gconv_bwd_L1` with its per-path algebra cut to a few FMAs (same loads and table decode; timing only, wrong forces), 5060 Ti | MEASUREMENT | 2,738.5 -> 2,286.7 us per force call (-16.5% of the kernel, 5.8% of 7.80 ms kernel time) | this file |
| [meas-radial-precision-screens](#meas-radial-precision-screens) | Accuracy screens (float64 MACE, OMAT-0 medium SrTiO3, gate rule) of tensor-core radial synthesis, FP16 outer-shell weights and a Chebyshev outer-shell factorisation; dense matmul rates, 5060 Ti | MEASUREMENT | single-pass FP16 / TF32 synthesis 28-54x the float32 force error, BF16 360-1,130x; FP16 weights pass beyond 5.0 A (0.5-0.9x), fail beyond 4.5 A (3.6x); Chebyshev fails at K 4-24; FP32 17.1, TF32 25.2, FP16 / BF16 ~49-50 TFLOP/s | this file |
| [meas-degree-channel-shell-screens](#meas-degree-channel-shell-screens) | Accuracy screens (float64 MACE, OMAT-0 medium SrTiO3, gate rule) of FP16 degree-2 / 3 projection blocks, an earlier cutoff for the l_y = 3 (2, 3) conv paths, one cubic per coordination shell, and FP16 for the least sensitive conv channels | MEASUREMENT | every variant fails: FP16 l = 3 blocks 3.2-4.9x the float32 force error (l = 2, 3: 7.6-7.9x); l_y = 3 cut at 5.5 A 56-106x (l_y >= 2 or earlier: up to 3,300x); shell cubics fit to 5.6e-3-1.8e-2 of the column peak (bound 5e-4), forces 108-6,500x; FP16 tail channels 4.8-6.0x at 32 of 128, 1.4x / 4.3x at 8 | this file |
| [meas-tc-overlap-ozaki-locality](#meas-tc-overlap-ozaki-locality) | Tensor rates at OMAT-0 GEMM shapes, engine force calls beside a side-stream tensor-core matmul loop, Ozaki-I slice accuracy, a sender-locality bound and an active-degree census (OMAT-0 medium generic SrTiO3, 5060 Ti) | MEASUREMENT | INT8 172 TOP/s square but 18-73 at K 128-512; overlap of force calls with matmuls 0.04-0.07 (FP32), 0.20-0.25 (TF32), 0.07-0.12 (FP16); Ozaki-I 3 slices x 6 products 6.8-19x the float32 force error, 4 slices x 10 pass; perfect sender locality saves 56 us (forward) + 17 us (backward) per call; R5 blocks within +-3% of their edges | this file |
| [meas-sgemm-reuse-pair-cutoff](#meas-sgemm-reuse-pair-cutoff) | Offline censuses: `sgemm128` operand reuse in the `sm_120` SASS; radial weights near the cutoff (per-pair effective cutoff) | MEASUREMENT | 2.33-2.47 register-file reads per FFMA (floor 2.0); OMAT-0 weights fall below 1e-5 of their peak only above ~5.99 A: 0.03-0.13% of edges droppable (MP-0 1.1-2.4%) | this file |
| [meas-s142-bounds](#meas-s142-bounds) | Bounds and screens for the owner's eighth 19 November list (OMAT-0 medium generic SrTiO3, 5060 Ti): species-run ends for `first_fwd`, layer 1's density force term, the force atomics, the projections' numerical rank | MEASUREMENT | run ends handed to `first_fwd` 231 -> 218 us (+4.8 us to form them unfused); no density term: a tie; no force atomics: -29.5 us; every projection full rank, rank 112 already 440-1,130x the float32 force error | this file |

### Tiled mode (Stage 5)

| ID | Idea | Switch/flag | Path | Status | Stage | Effect | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [tile-workspace](#tile-workspace) | One set of per-system buffers for every tile: the domain of the most rows is set up once, the others reshape it (species grouping, row counts) instead of `loup_set_system`'s free, allocate and cuBLASLt cache clear | none | generic, tiled | ADOPTED | S5 | tiled call 2.5-3.4x faster: `SrTiO3` 40,000 atoms 8 tiles, OMAT-0 medium 67.1 -> 19.7 us/atom, small 75.0 -> 23.2; still 6-27x the whole-system call | [§6.15][s615] |
| [tile-kept-lists](#tile-kept-lists) | Each tile's list built once per call and kept on the device; the sweeps restore it with device copies; energy and virial summed on the device, read once; the workspace kept between calls when it is large enough (no `loup_set_system` path, so the cuBLASLt cache survives) | none | generic, tiled | ADOPTED | S5 | `SrTiO3` 40,000 atoms, OMAT-0 medium 8 tiles 19.7 -> 4.33 us/atom (2.6x whole), 2 tiles 10.0 -> 2.97 (1.8x); small 23.2 -> 2.55 (2.9x) | [§6.16][s616] |
| [tile-md-device](#tile-md-device) | Tiled MD's integrator on the device (`loup_tiled_run`): state stays on the GPU, the whole-system loop's kernels | `LOUP_TILED_HOST_MD=1` | generic, tiled | ADOPTED | O31 | 320,000 atoms: NVE 712.5 -> 697.6 ms/step, Langevin 744-807 -> 706.5 | [§6.34][s634] |
| [tile-host-stage](#tile-host-stage) | Host tile lists copied into two device buffers on a copy stream one compaction ahead instead of read over the bus | `LOUP_TILE_HOST_STAGE=0` | generic, tiled (host lists) | ADOPTED | O31 | 320,000 atoms host lists 701.6 -> 612.1 ms (b / a 0.871); wavefront 1,081,600 2,535.7 -> 2,207.1 (b / a 0.870) | [§6.34][s634] |
| [tile-keep-layer0](#tile-keep-layer0) | Each tile keeps layer 0's `msgf` and `D` from its forward sweep; its backward sweep of layer 0 skips the forward replay (plain order, density layer 0 models) | `LOUP_TILE_KEEP_L0=0` | generic, tiled | ADOPTED | O31 | 320,000 atoms kept call 643.2 -> 597.6 ms (b / a 0.929) | [§6.34][s634] |
| [tile-slot-reserve](#tile-slot-reserve) | Active-edge slots within free memory less max(256 MB, 2%) instead of a quarter of it | `LOUP_TILE_KEEP_ACTIVE=k` | generic, tiled | ADOPTED | O31 | wavefront 1,081,600 atoms 2,274.4 -> 2,228.3 ms (b / a 0.979) | [§6.34][s634] |
| [tile-host-state](#tile-host-state) | Capacity (O32, S5-T07 step 2): the plain order's layer outputs and gradients in pinned host memory, tile blocks copied on two streams and host gathers / adds overlapped with the sweeps | `LOUP_TILE_HOST_STATE=0`, `LOUP_TILE_HOST_PIPE=0` | generic, tiled (plain order) | ADOPTED (fallback) | O32 | forced, 320,000 atoms: device state 611 ms, host synchronous 902, host overlapped 750-780 | [§6.34][s634] |
| [tile-pinned-reuse](#tile-pinned-reuse) | A released tiled state's pinned host buffers (layer state, windows, staging, host lists' edges) kept on the handle and taken by the next state at a list rebuild | none | tiled | ADOPTED | O32 | 2.56M atoms rebuild call 12.96 -> 7.17 s (steady; first rebuild 10.41), kept calls unchanged | [§6.34][s634] |
| [tile-compact-only](#tile-compact-only) | Compact slots (8 B per edge, restored per sweep) for every tile instead of full slots (36 B) where those fit | none | tiled | REJECTED (as default) | O32 | 2.56M atoms peak 12.84 -> 6.16 GiB but +1.5%; 320,000 +2.1%; 1.08M wavefront +0.6%; available as LOUP_TILE_KEEP_ACTIVE=0 LOUP_TILE_KEEP_COMPACT=999 | [§6.34][s634] |
| [tile-list-arena](#tile-list-arena) | Tile lists' device arrays from 128 MB chunks, slots from one chunk, instead of an allocation per tile or slot | none | tiled | ADOPTED | O32 | 2.56M atoms: device plan lists 3,072 -> 2,550 MB; default plan 1.3 GB more free after the slots (537-541 -> 1,860 MB); times tie | [§6.34][s634] |
| [tile-slot-block](#tile-slot-block) | One allocation per kept-active-edge slot, cut at 256 B, instead of six | none | tiled | NEUTRAL (kept) | O32 | the 1.14 GB first seen did not repeat (cudaMalloc alone: 20 MB); superseded by tile-list-arena | [§6.34][s634] |
| [tile-wave-host-bus](#tile-wave-host-bus) | The wavefront's host pool mapped; ghost gathers, gradient adds and block zeroing as kernels over the bus instead of host work after a synchronisation | `LOUP_TILE_HOST_BUS=0` (branch only) | generic, wavefront (host pool) | NEUTRAL (branch `wip/tile-wave-host-bus`) | O32 | 320,000-atom rod forced: 928.8 ms against 939.7 / 931.6 ms; forced host-pool timing jobs took WSL down three times | [§6.34][s634] |
| [tile-plan-fit](#tile-plan-fit) | The planner's tile workspace from the grid fit's widest piece and halo per candidate cap instead of cap-sized blocks | none | tiled | NEUTRAL (not kept) | O32 | estimate at 320,000 atoms 9.3 -> 6.9 GB; 3.52M / 5M at fraction 0.75 take larger caps but the same tiles, peak and times | [§6.34][s634] |
| [tile-grid-rows](#tile-grid-rows) | The grid fit takes the fewest rows (block atoms + halo per piece) instead of the fewest pieces when a reach is given | none | tiled | ADOPTED | O32 | 2.56M atoms at cap 65,536: widest domain 135,000 -> 65,700 rows, 12.6 -> 5 GB workspace, 6.49 -> 5.23 s; 320,000 and 1.08M unchanged | [§6.34][s634] |
| [tile-plan-slot-room](#tile-plan-slot-room) | The planner leaves room for compact slots in the plain host state and takes it at 4x-8x the cap of a device plan of 256+ small tiles | none | generic, tiled | ADOPTED | O32 | 2.56M atoms default plan b / a 0.911 (5.75 -> 5.24 s), peak 12.95 -> 12.84 GiB; 320,000 unchanged | [§6.34][s634] |
| [tile-host-state-window](#tile-host-state-window) | The plain host state also from 2.5x the cap of a device plan of 256+ small tiles, where nothing from 4x fits | none | generic, tiled | ADOPTED | O32 | 8,008,065 atoms default plan 17.29 / 17.28 -> 16.60 / 16.64 s (A B B A), b / a 0.961; peak 13.10 -> 12.97 GiB; 14 other plans unchanged | [§6.34][s634] |
| [tile-slot-room-limit](#tile-slot-room-limit) | The plain host state's cap search gives up room for every tile's compact slots when that costs more than 4x in cap | none | generic, tiled | ADOPTED | O32 | 5M atoms at fraction 0.5: cap 4,096 -> 32,768, 11.24 / 11.26 -> 10.44 / 10.39 s (b / a 0.926), peak 7.26 -> 7.22 GiB; 19 other plans unchanged | [§6.34][s634] |
| [tile-host-state-larger-cap](#tile-host-state-larger-cap) | From 2^20 atoms, a device plan held below the largest cap gives way to the plain host state where that reaches a larger cap | none | generic, tiled | ADOPTED | O32 | 1.08M atoms at 0.9 / 0.75 / 0.5: -3.6% / -2.7% / -4.7%; 8M at 0.75 -4.9% (A B B A); peak equal or lower; 31 other plans unchanged | [§6.34][s634] |
| [tile-pinned-headroom](#tile-pinned-headroom) | New pinned host buffers of the tiled state get 1/32 room to grow, so the first list rebuild reuses them | none | generic, tiled (host lists / host state) | ADOPTED | O32 | 2.56M atoms first rebuild call 10.22 -> 7.06 s (later ones 7.1-7.2 s both), kept calls unchanged; +3% pinned host memory | [§6.34][s634] |
| [tile-host-state-device-lists](#tile-host-state-device-lists) | The plain host state keeps the tile lists on the device where that reaches the same cap | none | generic, tiled | NEUTRAL (not kept) | O32 | 5 of 20 plans change; kept calls +0.1-2%, rebuild calls mixed, peak -0.35 to +0.31 GiB | [§6.34][s634] |
| [tile-merge-round6](#tile-merge-round6) | The tiled mode on the kernels of `round6-hardening` `13d6337`: tile lists without per-edge receivers and pairs (28 B per edge in the full form, 36 before, as S113's whole-system list), the chain fold off for tiled systems | `kTileFullEdgeB`, `GenericModel::use_chain_fold` (`src/engine.cu`, `src/generic.cu`) | generic, tiled | ADOPTED (with the merge) | O30, D84, D85 | merged / pre-merge library, kept calls A B B A: OMAT-0 medium 320,000 to 8,008,065 atoms at fractions 0.9 to 0.25, 18 plans: 0.981-0.989, but 0.914 at 320,000 / 0.5 (every tile keeps its active edges); OMAT-0 small 4 plans 0.977-0.986; peaks +0.04 to -0.19 GiB; 4 of 70 plans move to a larger cap | [§6.34][s634] |
| [tile-shared-layers](#tile-shared-layers) | A tiled or domain system keeps its layers' own buffers in one arena as large as the largest layer (a sweep runs one layer); the layer outputs and their gradients stay buffers of their own; the plan counts a row as before | `LOUP_TILE_SHARE_LAYERS=0` (`GenericModel::share_layer_buffers`, `alloc_system`) | generic, tiled | ADOPTED | O31, D86 | tile workspace -33% (OMAT-0 medium) / -39% (small); same plans; kept calls arena / merged, A B B A, 30 plans (135,000 to 8,008,065 atoms): 0.874-1.009, within 1% in 24, 1.1-12.6% faster in six; device peak 0.4-2.0 GiB lower in 14 plans | [§6.34][s634] |
| [tile-shared-layers-caps](#tile-shared-layers) | The cap search counting the shared workspace (larger caps), alone or with room for every tile's full slot in device plans | none | generic, tiled | REJECTED | O31 | 320,000 atoms at 0.5: 0.582 -> 0.629 s (larger cap, no slot); with the slot rule 135,000 at 0.25 0.254 -> 0.266 s, 320,000 at 0.25 0.663 -> 0.674 s | [§6.34][s634] |
| [mem-free-nvml](#mem-free-nvml) | The free device memory behind every plan, budget and peak: the smaller of CUDA's and NVML's figures (under WSL 2 CUDA's leaves out most of what other programs hold) | `LOUP_NO_NVML=1` (`device_memory`, `src/engine.cu`) | both | ADOPTED | O33, D87 | CUDA 15.16 GiB free against NVML's 13.1 with 2.9 GiB held by Windows programs, and a 1.2 GiB step at 10.2 GiB held; budgets 1.5-2 GiB lower, peaks exact | [§6.35][s635] |
| [tile-plan-exact](#tile-plan-exact) | The tiled plan reports what the call will hold (the plan's own tiles, the shared arena, kept slots, staging, layer 0, the host windows' schedule), checks it against the fraction and leaves room for a first call's GEMM scratch; the whole count follows the fold | `LOUP_DEBUG_PLAN`, `LOUP_DEBUG_PLAN_FREE` (tests) | generic, tiled | ADOPTED | O33, D88 | plan / device peak 0.55-2.07 -> 1.003-1.049 (22 plans to 20,480,000 atoms); plan / pinned host 0.66-0.81 -> 0.99-1.04; whole count 1.03-1.06 -> 0.98-1.004 at size; the largest cells: 10,985,000 atoms (OMAT-0 medium), 20,480,000 run (small) | [§6.35][s635] |
| [tile-compact-slots](#tile-compact-slots) | Kept active edges as row pointers, senders and integer shifts (8 B per edge) for the tiles full slots cannot cover; restored per sweep | none | generic, tiled | ADOPTED | O32 | 3.52M atoms b / a about 0.975 (8 full -> 40 compact slots); 320,000 b / a 0.985 | [§6.34][s634] |
| [tile-device-compact](#tile-device-compact) | Device tile lists as senders and integer image shifts (8 B per edge), decoded per compaction | none | generic, tiled | ADOPTED | O32 | 320,000 atoms b / a 0.93; wavefront 1,081,600 b / a 0.977; edges 4.5x smaller | [§6.34][s634] |
| [tile-slot-reserve](#tile-slot-reserve) | The kept slots and layer 0 leave the memory fraction's share of the budget free | none | generic, tiled | ADOPTED | O32 | 3.52M atoms at fraction 0.75 ran out of memory before, runs after; wavefront 1,081,600 about +1.5% alone (0 slots) | [§6.34][s634] |
| [tile-wave-host-pool](#tile-wave-host-pool) | The wavefront's row pool in pinned host memory as blocks of a tile's locals | none | generic, wavefront | ADOPTED (capacity) | O32 | 1,081,600 atoms forced: about 2.26 -> 3.10 s (+37%); only where the device pool does not fit | [§6.34][s634] |
| [tile-host-edges](#tile-host-edges) | Host state: the last forward tile's outputs and the last last-layer tile's gradient rows used on the device at the phase boundaries | none | generic, tiled (host state, two layers) | ADOPTED | O32 | 320,000 atoms forced host state: b / a 0.974-0.98 (about 648 -> 630 ms) | [§6.34][s634] |
| [tile-host-dma](#tile-host-dma) | Host state: gradient copy out queued after the next tile's input copy; unreused windows kept instead of folded | none | generic, tiled (host state, two layers) | ADOPTED | O32 | 320,000 atoms forced host state: 729 -> 651 ms (b / a 0.893) | [§6.34][s634] |
| [tile-host-compact](#tile-host-compact) | Host lists: sender and integer image shift per edge (8 B instead of 36), the rest rebuilt on the device per compaction | `LOUP_TILE_HOST_COMPACT=0` | generic, tiled (host lists) | ADOPTED | O32 | 320,000 atoms host lists forced: b / a 0.975; 4.5x less host memory for the lists | [§6.34][s634] |
| [tile-host-alias](#tile-host-alias) | Host state: `dx` on `x`'s rows once a block's last reader has its inputs (window blocks until then), no `dx` array or zeroing | `LOUP_TILE_HOST_ALIAS=0` | generic, tiled (host state, two layers) | ADOPTED | O32 | 320,000 atoms forced host state: b / a 0.963 (815 -> 785 ms medians), half the layer state's host memory | [§6.34][s634] |
| [tile-host-flow](#tile-host-flow) | Host state: no drains between phases, tiles ordered by when their inputs are ready | none | generic, tiled (host state, two layers) | KEPT (neutral) | O32 | 320,000 atoms: b / a 1.01 (8 tiles, all neighbours) | [§6.34][s634] |
| [tile-host-lists](#tile-host-lists) | Capacity (O31, S5-T07): the tile lists' edge arrays in mapped pinned host memory when they do not fit the device | `LOUP_TILE_HOST_LISTS=0` | generic, tiled | ADOPTED (fallback) | O31 | forced: 320,000 atoms 654 -> 751 ms; wavefront 1,081,600 2,280 -> 2,747 | [§6.34][s634] |
| [tile-active-once](#tile-active-once) | A tile's active edges compacted once per call into a slot it holds until its last sweep, instead of in each sweep | `LOUP_TILE_KEEP_ACTIVE=0` | generic, tiled | ADOPTED | O31 | kept call 657.3 -> 645.7 ms (b / a 0.982, A B B A); wavefront 1,081,600 atoms tie (one slot fits) | [§6.34][s634] |
| [tile-list-borrow](#tile-list-borrow) | The sweeps point the handle at each tile's list buffers instead of copying them in (4.1 GB per call at 320,000 atoms) | none | generic, tiled | ADOPTED | O31 | kept call 672.7 -> 664.0 ms (b / a 0.987, A B B A) | [§6.34][s634] |
| [tile-gemm-buckets](#tile-gemm-buckets) | In the tiled call a GEMM decision timed for one row count serves every row count of its size bucket (four per octave); kept in memory for the handle | `LOUP_TILE_GEMM_BUCKETS=0` | generic, tiled | ADOPTED | S5 | OMAT-0 medium 40,000 atoms 12 tiles: first call 5.95 -> 2.21 s, after a list rebuild 4.36 -> 0.86 s; shapes timed 358 -> 114; step path a tie | [§6.21][s621] |
| [tile-wavefront](#tile-wavefront) | Two-layer models in the tiled call: the sweeps in the wavefront's order, layer outputs and gradients in a row pool instead of whole-system arrays | `LOUP_TILE_WAVEFRONT=0` | generic, tiled | ADOPTED (`auto` from 2^20 atoms and 12 layers) | S5 | 368,640 atoms 20,000 receivers: device peak 4.91 -> 4.05 GiB, kept call 0.80 s both; 1,081,600 atoms: pool 11.1% of the atoms, 10.84 GiB, 2.35 s per call | [§6.22][s622] |
| [tile-overhead-screen](#tile-overhead-screen) | Receiver cap below the plan's; CUDA graphs per tile bucket; list builds without host round trips | - | generic, tiled | REJECTED | S5 | cap: 0.68-0.73 s at 320,000 atoms for 8,192-65,536, the largest fastest; graphs and device list builds bounded at 1.5% and 1% of a step (estimated from measured phases) | [§6.23][s623] |
| tile-lists-across-steps | The tiled state (plan, kept lists, whole-system buffers) stays between tiled calls until an atom moves skin/2; a kept call refreshes the tiles' positions on the device | none | generic, tiled | ADOPTED | S5 | NVE 320,000 atoms: 1.120 s per step (3.50 us/atom, 2.1x the whole-system call per atom), 55 list builds in 1,000 steps | [§6.18][s618] |
| [tile-strained-lists](#tile-strained-lists) | The tiled state's lists kept across a change of the cell (a barostat, LAMMPS's `fix npt` through the pair style) while the strain since their build leaves the atoms room: the whole system's variable-cell rule on the displacement from x0 F less its mean; the rows' places refreshed in the new cell | none | generic, tiled | ADOPTED | O42, D99 | MH-1 50,820 atoms, `fix npt` through the pair style: 491 -> 412.4 / 413.2 ms per step (a fixed cell with the virial: 410.4 / 413.2); no list build in 30 measured steps, before one per step | [§6.41][s641] |

### Dispersion (Stage 6D)

| ID | Idea | Switch/flag | Path | Status | Stage | Effect | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [d3-rows-projections](#d3-rows-projections) | Real-space D3: atoms in bin order, a walk over rows of bins contiguous in memory, per-receiver C6 projections in shared memory | prototype `variant` 1 | `src/dispersion/d3_proto.cu` | ADOPTED for S6-D04 | S6-D02 | 40 bohr sum 1.7-2.2x faster than the per-bin walk (three passes: NbCl5 5.35 -> 2.44 ms, SrTiO3 14.2 -> 8.6 ms) | [bakeoff][d3bo] |
| [d3-tail-shorter-cutoff](#d3-tail-shorter-cutoff) | Shorter real-space cutoff (20-30 bohr) plus the uniform-density tail correction | - | prototype | REJECTED as default | S6-D02 | energy and pressure far inside the contract, forces outside it at every cutoff below 40 bohr | [bakeoff][d3bo] |
| [d3-shell-every-k](#d3-shell-every-k) | Short part every step, the 20/25-40 bohr shell every k steps | - | prototype | REJECTED | S6-D02 | stale forces above the 40 bohr sum's error on all three systems even at k = 2 (ballistic estimate) | [bakeoff][d3bo] |
| [d3-cn-cutoff](#d3-cn-cutoff) | Coordination-number cutoff 20-35 bohr with the 40 bohr pair sum | `cn_cutoff_bohr` | prototype | OPEN (D73) | S6-D02 | CN 30: -19 to -21%; passes on SrTiO3 and water, misses on NbCl5 pressure by 1.7e-6 GPa | [bakeoff][d3bo] |
| [d3-pair-production](#d3-pair-production) | The bake-off's variant 1 in the library: device-side grid and reach, four dampings, switch, energy-only path | - | `src/dispersion/d3_pair.cu` | ADOPTED | S6-D04 | same speed as the prototype (2.51 / 8.48 / 9.87 ms vs 2.48 / 8.42 / 9.88); energy-only path 0.68 / 1.43 / 1.53 ms | [status 6.28](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md) |
| [d3-atm-first](#d3-atm-first) | Three-body ATM term: one block per atom, its neighbour list in shared memory in chunks, corner-owned forces without atomics | - | `src/dispersion/d3_pair.cu` | ADOPTED | S6-D08 | first version, nothing to compare with: d3bj-atm 12.3 / 102 / 133 ms against d3bj 2.5 / 8.5 / 9.8 ms | [status 6.29](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md) |
| [d3-split-mesh](#d3-split-mesh) | Split D3 sum: real space to 20 bohr, the C6/C8 channels' long-range part by smooth PME (order 8, 0.8 A) | - | `src/dispersion/d3_split.cuh`, `d3_mesh.cuh` | ADOPTED (as an accuracy option) | S6-D06 | not faster: 4.27 / 12.7 / 9.5 ms against the plain 40 bohr sum's 2.61 / 8.56 / 10.2 ms (NbCl5, SrTiO3, water); 203 against 153 ms at 98,415 atoms, 1975 against 1494 ms at 975,560; energy error 0.007 / 0.033 / 0.0002 meV/atom against 0.59 / 1.08 / 0.065 | [status 6.31](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md) |
| [d3-walk-reach](#d3-walk-reach) | Each D3 walk covers the bins of its own cutoff, not of max(pair, CN) | d3-split-mesh | `src/dispersion/d3_pair.cu` | ADOPTED | S6-D06 | split 20 bohr: NbCl5 4.39 -> 4.27 ms, SrTiO3 12.81 -> 12.67, water 9.90 -> 9.52, 975,560 atoms 2015 -> 1975 (single runs; the plain sum unchanged within noise) | [status 6.31](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md) |
| [d3-f32-partials](#d3-f32-partials) | D3 force kernels sum forces, virial and dE/dCN in float32 per lane, added to float64 every 32 pairs or triangles; the energy stays float64 per pair | - | `src/dispersion/d3_pair.cu` | ADOPTED | D77 | d3bj 2.56 / 8.51 / 10.08 -> 1.36 / 3.67 / 4.43 ms (NbCl5, SrTiO3, water); d3bj-atm 7.59 / 76.0 / 103.1 -> 5.80 / 54.9 / 73.4 ms; OMAT-0 medium MD step with d3bj x2.01 -> x1.44 of the model alone at 5,000 atoms; forces within 2.2e-8 eV/A | [status 6.33](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md) |
| [d3-dedcn-f32](#d3-dedcn-f32) | The CN chain rule reads a float32 copy of dE/dCN instead of converting float64 per pair | d3-f32-partials | `src/dispersion/d3_pair.cu` | ADOPTED | D77 | d3bj 1.35 / 3.67 / 4.45 -> 1.33 / 3.53 / 4.21 ms (NbCl5, SrTiO3, water); forces bit-identical | [status 6.33](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md) |
| [d3-walk-trim](#d3-walk-trim) | The D3 walks skip bin columns beyond the cutoff and cut each column to its chord | d3-dedcn-f32 | `src/dispersion/d3_pair.cu` | ADOPTED | D77 | d3bj 1.33 / 3.54 / 4.20 -> 1.22 / 3.46 / 4.16 ms (NbCl5, SrTiO3, water); split 25 and three-body 1 to 3% | [status 6.33](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md) |
| [d3-atm-proj](#d3-atm-proj) | Three-body term: C6_jk from per-entry projections in shared memory (5 FMA per triangle instead of 25) | d3-walk-trim | `src/dispersion/d3_pair.cu` | ADOPTED | D77 | d3bj-atm 5.66 / 53.9 / 72.6 -> 5.39 / 51.0 / 68.0 ms (NbCl5, SrTiO3, water); d3bj unchanged | [status 6.33](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md) |

## Chronology

Step times are `bench_md.py` OMAT-0 medium MD steps, `NbCl5` / `SrTiO3`, ms. Rows are successive builds of the
same benchmark, not A/B pairs. "Tried" lists only attempts whose stage is recorded; most rejected items of
section 3.3 of the status file carry no stage.

| Stage | Tried | Adopted | 5060 Ti | Ada |
| --- | --- | --- | --- | --- |
| S0 | session baseline (before `CUBIC_PACKED8`) | – | 2.384 / 11.380 | 2.533 / 12.985 |
| S1 | 8-byte cubic table, hybrid cubin for `sm_120`, edge-grid bucketing | wp-cubic-packed8, gemm-hybrid-cubin, nl-bucketing-sort | 2.187 / 10.458 | 2.353 / 11.764 |
| S2 | receiver-owned i0 forward, i0 backward prefetch, segmented sort, Cartesian shifts, `sc1_fused`, spatial reorder, forked GEMMs | all of these | 2.089 / 9.939 | 2.260 / 11.184 |
| S3 | receiver-owned `w'`, packed edges, fused assembly, float32 pre-test, aliasing, carveouts, cold-L2 autotune, paired edges, staged q, no split-K, SH staging and recompute, warp-per-receiver i0, Langevin blocks | items 12-26 | 1.930 / 8.858 | 2.090 / 10.021 |
| S4 | shift-free decode, 2^8 derivative, 4-receiver spline on `sm_89` | items 27-29 (partly) | 1.904 / 8.646 | 2.088 / 9.576 |
| S5 | per-system spline / `w'` variants, own SGEMM; SGEMM variants, group policy, split-K, grouped launch, edge-split spline, paired R5 | items 29-31 | **1.849 / 8.458** | **2.054 / 9.27** |
| S6 (12-13 Nov) | review round 5 (adaptive pipeline), generic path for every FastMACE family, POLAR long range, SIMT GEMMs for POLAR, fixed-point phases | md-adaptive-pipeline, gen-*, pol-*, gemm-simt-for-lr | 1.836 / 8.454 | 2.056 / 9.262 |
| round 6 (13 Nov) | review round 6 fixes (S1, S5, S6, S7) | – (correctness) | 1.81 / 8.33 | not run |

## Closed directions

Do not retry these unless the stated condition changes.

| Direction | Evidence | Reopen only if |
| --- | --- | --- |
| Splitting the interaction-1 chain over streams or L2-sized receiver chunks | [int1-two-halves](#int1-two-halves) +0.7% to +0.9%; [int1-l2-chunks](#int1-l2-chunks) +0.2% to +2.8%: per-chunk launch and tail costs exceed the DRAM savings | `lin1` is fused into the chain ([int1-lin1-fusion](#int1-lin1-fusion)) so a chunk no longer pays two GEMM launches |
| Register-raising `w'` variants at 64 registers | [wp-paired-edges](#wp-paired-edges), [wp-x0-hoist](#wp-x0-hoist), [wp-vector2](#wp-vector2) spill or lose on one GPU; [wp-launch-256-3](#wp-launch-256-3) below resolution | `w'` is restructured so it is no longer issue-bound at 63% occupancy |
| Cache-placement schedules for `w'` and the spline | [wp-persistent](#wp-persistent), [wp-no-allocate](#wp-no-allocate), [sched-reversed-order](#sched-reversed-order), [spl-receiver-remap](#spl-receiver-remap): ties or losses | Ada counters ([meas-ada-counters](#meas-ada-counters)) show an L2 limit the 5060 Ti does not have |
| More GEMM tile shapes, split-K, grouped or per-group policies | [gemm-sgemm-variants](#gemm-sgemm-variants), [gemm-split-k-own](#gemm-split-k-own), [gemm-grouped-launch](#gemm-grouped-launch), [gemm-group-policy](#gemm-group-policy): isolated timings do not carry over to concurrent GEMM groups; the small-product floor is launch latency | the graph launch model changes (e.g. programmatic dependent launch measured exact and faster) |
| Split-K cuBLASLt algorithms | [gemm-no-split-k](#gemm-no-split-k): captured memset nodes idle the GPU, non-deterministic | never |
| 3xTF32 GEMMs for MACE-POLAR-1 | [gemm-simt-for-lr](#gemm-simt-for-lr): Ada stress ratios 3.4-6.3 and a NaN | a different arithmetic implementation or a demonstrated reference defect; never relax the accuracy gate |
| Atomics replaced by extra reduction launches | [frc-per-atom-energy](#frc-per-atom-energy) +0.5%, [i0-bwd-receiver-owned](#i0-bwd-receiver-owned) +1.8%, [frc-segmented-f64](#frc-segmented-f64) | a reproducibility (bitwise) mode is required |
| Wider interaction-1 intervals in 8-byte entries | [s108-wide-table](#s108-wide-table): no 8-byte format with 4x wider intervals keeps the current accuracy, and the six-field decode costs more (+5-11%) than the slab reuse saves (at most 4.5% at 300 K) | a decode costing no more than CUBIC_PACKED8's with >= 4x wider intervals at the current accuracy |

## Open or untried

| Item | State | Where |
| --- | --- | --- |
| Fuse `lin1` into interaction 1 | needs a receiver-tiled tensor-core GEMM consuming spline tiles from shared memory | [int1-lin1-fusion](#int1-lin1-fusion) |
| Ada performance counters | blocked on admin rights on `leeloo` | [meas-ada-counters](#meas-ada-counters) |
| Small-system latency | GEMM launch floor; split-K, grouped launch and edge-split spline rejected | [md-small-systems](#md-small-systems) |
| Larger / adaptive skin | owner decision (changes the benchmark configuration) | [md-skin](#md-skin) |
| Gate fused into the generic path's GEMMs | forward prologue fusion falsified (S36: `0.946` of the chain, stop rule 10%); done otherwise (S137): the backward in the `W_2^T` epilogue with row tiles of whole atoms, so no per-atom sum crosses tiles ([gen-gate-bwd-epilogue](#gen-gate-bwd-epilogue)), and layer 0's forward in the producing projection's store instead of the `W_2` GEMM's A load ([gen-gate-fwd-store](#gen-gate-fwd-store)); layer 1's projections, tuned to cuBLASLt, keep the gate kernel | [gen-gate-epilogue](#gen-gate-epilogue) |
| Generic-path GEMMs (~50% of MH-1) | not screened beyond the shared autotune | [gen-profile](#gen-profile) |
| Decaying step-displacement maximum | closed by S75: the MD loop no longer pipelines or tracks the maximum; every step checks its own list exactly and the force pass waits behind a conditional node ([md-guarded-loop](#md-guarded-loop)). S46 had found water above the pipelining threshold in every step at skin 0.5. `release/v1` had built the decaying maximum ([md-disp-decay](#md-disp-decay)); the merge of `round6-hardening` on 17 November replaced it with the guarded loop | [md-guarded-loop](#md-guarded-loop) |
| `w'` path order and shared scalars | untried: emit the six `x1` paths before the four `x0` paths (shorter live ranges at the 64-register limit) and add the three `xx / xy / xz` pull terms of paths 1, 4, 7 through one summed scalar (6 FMA per channel). Differs from [wp-x0-hoist](#wp-x0-hoist), which added a live accumulator. Test: SASS count and spill bytes first, then A/B | external suggestion, 13 Nov |
| Shift-free decode for the forward's PACKED8 table | untried: the layout change of `w'` (S4) applied to `spline_forward_inter1`; the forward is L2-bound on the 5060 Ti, so expect little there | external suggestion, 13 Nov |
| Exponent field without the add | tried, S109: a 2^k rescale makes every table's exponent base 32-aligned, but the compiler had no IADD to remove (static SASS IADD3 count 0 before and after) and the staged-q scaling added FMULs: MD +0.7-1.0% | [s109-exponent-or](#s109-exponent-or) |
| Dead `y1` store in `sc1_fused` | done (S110): store, argument and allocation removed | [mem-inplace-s110](#mem-inplace-s110) |
| Receiver / sublattice ordering in `spline` and `w'` | falsified (S108): the slab reuse that matters is within each receiver's own edge list, not across receivers | [spl-receiver-order](#spl-receiver-order) |
| Unpaired `R=8` spline blocks | `R=6` at 80 registers spilled and lost 3% (S32). S47 tried the register cut from the other side (each receiver's 10 paths split over two 128-thread parts: 64 registers, 32 warps / SM): 9-12% slower than R5. More warps do not pay for the duplicated per-edge work | [spl-r6-r8](#spl-r6-r8) |
| CUDA Graph L2 persistence (`AccessPolicyWindow`) on `x0+x1` | untried: ~10-12 MiB persistent window (`SrTiO3` `x0+x1` = 9.77 MiB), check `ncu` eviction first | [mem-l2-persist-x](#mem-l2-persist-x) |
| Cold-L2 rule for Ada `lin1_fwd l=1` + wider 3xTF32 `mma` tiles | untried: `22.0 MiB < 24 MiB` (`L2/2`) times `lin1_fwd l=1` hot on Ada; check `LOUP_DEBUG_GEMM=1` and `128x64`/`64x128` 3xTF32 tiles on 5060 Ti | [gemm-cold-l2-ada-fix](#gemm-cold-l2-ada-fix) |
| Warp-aggregate `rcv` `atomicAdd`s in `i0_bwd` | untried: 1-2 receivers per 32-edge warp (`SrTiO3`); check `ncu` atomic stall counters first | [i0-bwd-rcv-warp-agg](#i0-bwd-rcv-warp-agg) |
| Active-edge compaction (`101 us`) & `tune_l1` re-check | untried: `compute_and_count_active` + `scatter_active_edges` (`tmp_vec_len` round-trip); re-check `w'`/`i0_bwd` carveouts | [comp-active-edge-tighten](#comp-active-edge-tighten), [mem-l1-carveout-retune](#mem-l1-carveout-retune) |
| Gate reference cache | done (tooling): `python/test_gate.py` caches the MACE float64 / float32 references and PolarMACE's finite-difference stress, keyed by model sha256, head, set, reference device (GPU model, compute capability, CUDA version; a reference from another GPU is not reused), MACE / torch versions, stress step and every configuration's atoms; `--no-ref-cache` recomputes, an unreadable entry is recomputed. POLAR-1-S crystals gate 40 -> 6 s on a repeat; the float32 bound is then fixed between runs. Test: `tests/test_gate_cache.py` | `python/test_gate.py` |
| POLAR k-space on a mesh (smooth PME) | untried, post-release (`PLAN.md` §11). Our `src/polar.cu` sums directly over the k-vectors (N x K, K growing with the volume, so O(N^2) in large cells) and has no tiled mode. symmetrix 0.3.0 (`wcwitt/symmetrix` `53933df`, `pair_style symmetrix/mace/polar`) runs MACE-POLAR-1's electrostatics as SPME with defaults it validated for the 1.85/A k-space cutoff: grid spacing at most 0.7 A, B-spline order 8, the direct sum kept as an option. Start from the D3 mesh (`src/dispersion/d3_mesh.cuh`); gate POLAR-1-S/M/L both ways (`LOUP_POLAR_FOLD=0`) and against the direct sum | external prior art, 16 Nov |
| Per-GEMM power-of-two scale for the FP16 hybrid | untried, post-release (`PLAN.md` §11). The hybrid's cross term overflows at operands of 32,752 or more and is guarded ([gemm-hybrid-cubin](#gemm-hybrid-cubin)). symmetrix's `float32-mixed` (`1771c84`, `mace_foundation_cuda.hpp`) splits fp32 operands into fp16 hi / lo on the fly, takes one power-of-two scale per GEMM from a device-side amax, and pre-splits the weights at load. Its README warns that one extremely close contact then degrades all forces (one scale per system), so it is off by default there. Test: the 3x gate on every family plus a close-contact case; the scale must not hide an overflow silently (PLAN §2) | external prior art, 16 Nov |
| FP16 storage of the higher spline coefficients | untried, low priority. symmetrix's mixed mode stores the `c2`, `c3` coefficients of its layer-1 splines as `__half2` and refuses a model whose coefficients exceed 6e4 at load (`1771c84`, `mace_foundation_cuda.hpp` `R1Block`). Our packed tables already hold the 5e-4 relative-error guard; the gain would be table bandwidth in `spline_forward_inter1` / `w'` (L2-bound on the 5060 Ti). Test: `LOUP_DEBUG_PACK=1` error, then the 3x gate with every forced spline variant | external prior art, 16 Nov |
| GEMM plans timed in the captured graph | not built. S45: six fresh isolated tunings land within 2.7% (`POLAR-1-S` `NaCl216`) / 1.3% (`MH-1`). S51: own-kernel alternatives forced per shape group inside the graph (`POLAR-1-M` `NaCl216`) lose 1-8.5% or tie (M=1080's one-order `0.975` / `0.989` did not reproduce in a both-order repeat); cuBLAS algorithm alternatives untested | [meas-plan-variance](#meas-plan-variance) |
| First-layer `C0` projected into the spline coefficients (OFF, degree 3) | not built (owner's review list, 17 Nov): it would remove the l = 3 `C0` GEMMs (OFF23-M water216: the per-species 216 x 7 and 432 x 7 rows x 128 x 128, 8.4 + 13.8 us forward and 8.3 + 13.6 us transposed, `LOUP_DEBUG_GEMM`; 44 of 1,173 us of kernel time per step) but needs a second, `C_msg`-wide per-pair table (128 columns, beside the 64 of l <= 2) read per edge in `first_fwd` / `first_bwd_edge` (21 + 53 us), kernels bound by per-edge table traffic: expected net at or below zero | owner's review list |
| `sc1_fused` reusing the forward's quadratic for the cubic invariant's gradient | not built: the kernel is DRAM-bound (82-91% of peak, `ncu`), so fewer instructions do not shorten it | owner's review list, 17 Nov |
| Interaction-0 species blocks skipped per receiver (dilute alloys, OMAT-0) | not built: no benchmark system has a dilute species; needs a per-receiver species mask from the skin list and compaction / scatter of the minority rows around the forward and transpose GEMMs. The owner's screen (NbCl5 1,944 atoms with Ta on Nb sites): 3 Ta skip 31% of those GEMMs' arithmetic, 16 Ta 24% | owner's review list, 18 Nov |
| Shorter layer-0 radial polynomials (OMAT-0) | not built: each quintic piece is a cubic Hermite interpolant plus `(1 - x^2)^2 (A + B x)`, so dropping B (a quartic) or both (a cubic) keeps the knot values and slopes with bounded interior error; the owner's screen on 300 K SrTiO3: 15% fewer coefficients per edge and column at a 1e-7 relative bound. Interaction 0 is 9.4% of the SrTiO3 step (`tabled_outer_sum0_forward` 266 + `_backward` 552 us of 8,666 us of kernel time, `nsys`), so at most ~1%; needs an exporter certificate against the network and per-piece degree flags | owner's review list, 18 Nov |
| ZBL once per physical pair | not built: 32,964 of 371,624 directed SrTiO3 edges (300 K) enter ZBL, about 66k exponentials per force call inside `tabled_outer_sum0_backward_kernel` (552 us per step); halving them is far below the step's resolution, unless compressed configurations put most edges inside the repulsive range | owner's review list, 18 Nov |
| Particle-mesh reciprocal space for large POLAR cells | not built (a separate project): the direct atom-by-mode sums grow as N^2 at fixed density; at 1,944 atoms (NbCl5, POLAR-1-S) the k-space kernels were 18.5% of the step before S118, and 8x the atoms is ~64x that work. The owner's CPU screen: order-10 B-splines on a 99 x 99 x 33 grid reach 1e-8 relative structure factors | owner's review list, 18 Nov |
| Tighter neighbour-bin bound for tilted cells | not built: S120's skip of 57% of the bins cut count + fill by only 6% ([nl-bin-skip](#nl-bin-skip)), so removing a further ~31% of the bin checks is far below 0.1% of a step | owner's review list, 18 Nov |
| Periodic shifts stored once per translation | not built: `d_shift_cart` is written only by `sort_gather_row` and read only by `compute_and_count_active_kernel` (41-47 us of SrTiO3's step), so at most ~0.2%; it would save 24 B per edge slot (~4% of VRAM at 40,000 atoms), but positions are unwrapped (`pos64`), so the number of distinct translations grows with diffusion (27 holds only for the initial crystal) and needs a per-rebuild dedupe table with a fallback | owner's review list, 18 Nov |
| POLAR-1 l = 1 electron-energy blocks as one vector per triplet | not built (S123 skips the l = 2 zero blocks): the l = 1 blocks of `le_Wq` / `le_Wv` and the updates' `Wq` / `Wpot` are delta-structured, but their K = 8 / 16 GEMMs write the same N x 3C outputs either way; only a fused contraction that never forms `Zq_1` / `Zv_1` would pay (four launches and their traffic, an estimated 20-40 us of POLAR-1-L NaCl216's 5.7 ms) | owner's review list, 18 Nov |
| Layer-0 force once per physical bond (OMAT-0, MP-0; MH-1's equal-species bonds) | not built: the pair needs the second endpoint's 16 x Jp gradient rows (4 KB at Jp = 64) as a random gather (61 MB on SrTiO3, 5,000 atoms: beyond L2) in place of the 1 KB table row per directed edge, while each receiver's rows are now loaded once per (receiver, sender species) run; `first_bwd_edge_kernel` is 471 us (5.4%) of MP-0 SrTiO3's kernel time | owner's review list, 18 Nov |
| MH-1: message and residual projections as one GEMM | not built: `pre_l = lin_l s + res_l` (`gate_fwd_kernel`, s = 1 / (beta D + alpha) per atom) needs `mid` scaled by s and stored contiguous with `x`, both fixed by the generated conv kernels' strides, and the backward split likewise; bound: the owner's 50.7 kB per atom of intermediate traffic, ~0.6 ms of MH-1 SrTiO3's 33.4 ms (at most ~2%; GEMMs are 61% of its kernel time, the gates 15.6%) | owner's review list, 18 Nov |
| Coefficient decodes shared across eight nearby receivers; backward grouped by sender | not built: S108 found the slab reuse that matters within each receiver's own edge list, not across receivers ([spl-receiver-order](#spl-receiver-order)); the owner's screen counts 50% (OMAT-0) / 37% (MH-1) fewer distinct slabs across eight receivers and 66% / 51% fewer sender loads (SrTiO3 / NbCl5), but building and walking the groups every step is the cost to measure first | owner's review list, 18 Nov |
| Rebuild only when a fast atom's pairs are really missing | not built: SrTiO3 rebuilds about every 16 steps at 300 K (4 per 64-step profile); the owner's ballistic screen moves the median first rebuild from 15 to 20 steps (SrTiO3), 23 to 29 (NbCl5), 22 to 29 (NaCl), so at most a quarter of the rebuilds' amortized cost, far below 1% of a step; melt-quench runs with many fast atoms would gain less | owner's review list, 18 Nov |
| Virial from atomic forces plus boundary-crossing corrections | not built: forces-only MD (the benchmark) forms no virial; with stress, the owner's screen cuts 3.32 M FP64 outer products to 45,027 on SrTiO3 (identity to 2.6e-15), to be qualified near zero stress where the summation order matters most | owner's review list, 18 Nov |
| Interaction-1 radial functions near the cutoff from a few shared curves | not built: 4 (MP-0) to 6-7 (OMAT-0) shared cubics reproduce all 1,280 functions over ~5.5-6 A at 1e-7 to 3e-7 of the peak slope (owner's screen), 24-26% of the active edges; it trades the packed table's 8 B per path and channel (L2) for M cached coefficients and M FMAs, which needs a timing falsifier; MP-0's case is superseded by [gen-conv-prune](#gen-conv-prune) (2 of its 10 paths left) | owner's review list, 18 Nov |
| Fewer layer-0 radial channels on long bonds | not built: layer 0 is 8.3% (MP-0) / 8.4% (OMAT-0 generic) of SrTiO3's kernel time (`first_fwd` + `first_bwd_edge`, `nsys`), so 45.5% fewer column evaluations on 91% of the edges bound it at ~3.5%; needs `first_fwd` restructured (one column per thread now), a per-pair rotation fitted at load with the inverse folded into the per-species `C0` (only skip-folded layers have one) and a smooth cut at 2.5-2.75 A | owner's review list, 18 Nov |
| Angular gradients converted once per output degree (OMAT-0 `w'`) | not built: paths with the same output degree do share one conversion matrix up to a scalar (paths 5-7 of `wprime_backward_inter1_rcv`: x 0.316 / 1.291), but the conversion runs once per receiver and channel in the staging prologue (~40 FMAs per channel), against the per-edge loop over ~70 edges and 10 paths per channel: below 0.5% of the kernel, so nothing to move before the transpose GEMM | owner's review list, 18 Nov |
| Spline control points shared by neighbouring intervals (B-spline blocks of 32) | not built: FastMACE's per-knot shared rows were rejected at the kernel lab (its ledger's `bspline-table`, 9 Nov: table-share ceiling under its bar before the 2-4x load instructions); here an isolated lookup would fetch 24 B against today's 8 B per path and channel, and a receiver's edges are ordered by sender species, not distance, so six occupied intervals per block are not the common case | owner's review list, 18 Nov |
| MH-1: layer-0 projection kept as its 128-wide factors (three or more species) | not built: `first_C0_l = (x_sp ⊙ Wf_l)^T W_lin_l` per species block, so `S0 C0` could run as `(S0 A) W_lin` with K = 128 in between: 2.02 M -> 1.67 M MACs per atom and direction for O/Ti/Sr (17.4%; 40.9% for five species, 54.7% for eight, NaCl 1%). Measured shapes (MH-1 SrTiO3, `LOUP_DEBUG_GEMM`, tuned times): the projection is 272 + 217 + 352 + 490 us forward (l = 0..3, K = 208) and 438 + 266 + 411 + 593 us transposed, 3.04 ms of the 33.2 ms step, but these GEMMs are output-bound (M = 15,000 x N = 512: 217 us at K = 208, 143 us at K = 128), so the factored chain would add a 208 -> 128 GEMM per degree to save at most ~80 us per degree | owner's review list, 18 Nov |
| MH-1: last layer's forward and backward on atom tiles | not built (a separate project): the gate kernels are 15.6% of MH-1 SrTiO3's kernel time (5.8 ms), near DRAM peak; tiling the fused readout's message gradient, the transposed projections and the gate derivative over 64-256 atoms keeps four 156 MiB arrays (5,000 atoms) in cache, but every GEMM of that chain becomes 16-80x smaller | owner's review list, 18 Nov |
| Radial tables stored losslessly as corrections to anchors | not built: the owner's encoding reproduces every packed coefficient and exponent and shrinks the tables by 31.9% (OMAT-0 O/Ti/Sr), 33.3% (MH-1 O/Ti/Sr), 33.2% (MH-1 NaCl); the conv kernels read 8 B per path and channel per edge, mostly from L2 (96% hit rate in the `w'` profile), so the gain depends on anchor reuse and on the decoder's extra integer work: a lab first | owner's review list, 18 Nov |
| Hot radial rows cached per 32-receiver group (OMAT-0 forward conv) | tried as a per-call dictionary (S138, [gen-conv-fwd-dict](#gen-conv-fwd-dict)): 1.6-2.5x slower, latency-bound at 8-16 resident warps. The bound stands ([meas-conv-ablation-bounds](#meas-conv-ablation-bounds): with every table read served from one hot row, `gconv_fwd_L1` drops 1,810 -> 1,342 us per call on OMAT-0 generic SrTiO3, 6% of the step, and MP-0's `L1s` 683 -> 407 us); a second design would need R5's occupancy (20 warps per SM) and its once-per-tile staging, with the dictionary slices far below 64 KiB per block | owner's review list, 18-19 Nov |
| Radial weights from low-rank (4-8) products over eight-interval panels | not built: it chases the same forward-table bound as the cache above with an approximation (1e-7 of each pair's scale per value and slope, unqualified end to end) and ~24-27 GFLOP per call, i.e. 34.5 effective TFLOP/s inside the convolution budget; the exact cache is the better route to that bound | owner's review list, 18 Nov |
| Radial coefficients stored as shifted neighbouring cubics plus exact corrections | not built: storage 45.2 -> 23.9 MB, but only ~4 MB of the table is active on rattled SrTiO3 (it sits in L2), and each lookup would still read the neighbour plus the correction; the step-time lever is the L2 traffic per lookup, which the cache addresses | owner's review list, 19 Nov |
| Layer-0 kernels on tensor cores (compensated TF32 MMA) | not built: `first_fwd` is not bound by its arithmetic (its 16-term angular update cut to one term saves 1-2%: 234 -> 232 us per call on OMAT-0 generic SrTiO3, 232 -> 227 on MP-0; [meas-conv-ablation-bounds](#meas-conv-ablation-bounds)); `first_bwd_edge` (497 / 461 us per call) loses 9% / 8% with free table reads, and its contraction bound was not obtained (the ablated build did not complete a force call); an exact (3xTF32) MMA rewrite of the backward would be a separate project against at most ~6% of the OMAT-0 step | owner's review list, 19 Nov |
| Sender gradients reduced within spatial patches (OMAT-0 backward) | not built: with every sender-gradient atomic removed the OMAT-0 generic backward drops only 3,086 -> 2,927 us per step (-5%, 2% of the step; [meas-conv-ablation-bounds](#meas-conv-ablation-bounds)), before the patch-merge cost the design adds; MP-0's pruned layer, where the atomics were 21%, took the sender-owned kernel instead ([gen-conv-bwd-sender](#gen-conv-bwd-sender)) | owner's review list, 18 Nov |
| Dense projections from INT8 products (seven small-modulus products per FP32 dot product) | not built: the owner's break-even is 90.5 effective INT8 TOP/s just to match the current projections before conversion and reconstruction; OMAT-0 generic's projection GEMMs are 28.5% of its kernel time and already run at 12-17 TFLOP/s FP32, so the reachable gain is a fraction of that share at high engineering cost; one fused forward / transpose pair would be the first test | owner's review list, 19 Nov |
| Eight receivers' terminal projections, cubic invariant, readout and both adjoints in one block (round-4 research) | not built: to save 5% of the OMAT-0 generic step the fused kernel must finish below 848 us, i.e. run its 13.1 GFLOP of projection work at >= 15.46 effective TFLOP/s (65% of the 5060 Ti's FP32 peak) on 8-receiver tiles (8 / 24 / 40 / 56 rows per degree) that also stream 0.82 GB of weights from L2 per pass, while the tuned standalone projection GEMMs reach 12.9 TFLOP/s (54%) on full tiles; the boundary transfers it keeps (M in, dM out) alone take 457 us at DRAM peak | `omat0-round4-20261119/terminal` |
| Backward projections as two TF32 products (forward energies native; round-4 research) | not built for the terminal GEMMs: on the 5060 Ti (TF32 tensor rate about the FP32 rate) two products of the eight terminal shapes cost at least 1.105 ms at peak against 1.014 ms for the tuned FP32 GEMMs (the research's own floor); splitting rows between FP32 and tensor pipes concurrently is untested. Allowed in principle (AGENTS.md: accuracy decides, 3x gate on every family); the research's CPU screen passed 9 / 9 held-out cases and a 320-step NVE run | `omat0-round4-20261119/two_products` |
| Backward conv (`gconv_bwd_L1`) split by sender feature type between warp teams (round-4 research) | not built: uncompiled in the research; its forward analogue lost 32-34% ([gen-conv-fwd-path-teams](#gen-conv-fwd-path-teams)), and the backward kernel already runs at 76% of SM and 81% of L2 throughput (ncu, OMAT-0 generic SrTiO3), which a split with an extra per-edge handoff of the four (Gx, Gy, Gz, R) partials cannot relieve | `omat0-round4-20261119/path_codegen` |
| Layer-0 backward as an MMA product with two TF32 terms (round-4 research, first interaction) | not built: the research expected to halve the 0.472 ms kernel with cheaper matrix arithmetic, but ncu shows it bound by its load/store pipe (71% of peak, two thirds of it shuffles) with the FMA pipe at 30%; S140 removed a quarter of those instructions exactly (-7% / -12% kernel time, [gen-l0-bwd-lsu](#gen-l0-bwd-lsu)). A tensor-core version would also retire the 16-shuffle fold and the per-lane FMAs, but must stage its MMA operands through shared memory, keeps the table reads (free table reads: -9%) and needs the 3x gate on every hidden-table family; the research's target of halving the kernel would now save about 0.23 ms per OMAT-0 generic step (3%), unmeasured | `omat0-round4-20261119/first_center` |
| Interaction-1 backward in a bond-aligned (SO(2)) frame | not built (19 Nov): its bound is 452 us per force call, 5.8% of OMAT-0 generic SrTiO3's kernel time ([meas-conv-bwd-algebra-bound](#meas-conv-bwd-algebra-bound)). The late pull-back already contracts each receiver adjoint with the bond direction (`h = q . n`, `v = Q n`: the m = 0 and m = +-1 projections), and rotating every path's adjoint into the bond frame costs more FMAs per channel and edge than those contractions; a multi-day generated kernel for less than that bound | owner's idea list, 19 Nov |
| Both directions of a bond in one pass; cluster-pair undirected convolution | not built: the idea's byte count (6.4 KB more reads against 10.2 KB saved per bond on SrTiO3, about even on NbCl5) is before cache reuse, which already serves most table rows ([spl-receiver-order](#spl-receiver-order)); it adds output reductions for the second endpoint and loses the fixed per-receiver summation order. Layer 0's analogue above was dropped for the same gather | owner's idea list, 19 Nov |
| Radial weights by texture-unit interpolation (`tex1D`) | not built: ~945 M filtered fetches per forward pass, ~2.6 ms at the 5060 Ti's texture peak (an estimate), against ~1.5 ms for the whole current forward conv | owner's idea list, 19 Nov |
| Fast multipole expansion of the outer radial shell | not built: at a 6 A cutoff with 1.5 A cells every interaction is near field; there is no far field to expand | owner's idea list, 19 Nov |
| Outer shell (3.5-6 A) as a particle-mesh convolution (B-spline spread, batched 3D FFTs, k-space kernel, interpolation) | not built (an estimate): SrTiO3 5,000 atoms on a 0.8 A grid is ~49^3 points; per pass one forward FFT per sender species, channel and input component (3 x 128 x 4) and one inverse per receiver species, channel and output component (3 x 128 x 16), ~7,700 FFTs that touch ~14 GB, ~30 ms at the 5060 Ti's DRAM rate against ~1.5 ms for the whole forward conv; the species-pair kernels' transforms would take ~10 GB, and the 3.5 A split needs a smooth switch the radial functions do not have | owner's idea list, 19 Nov |
| Product forward / backward fused into the projections at C = 128 (OMAT-0 generic; reopens [gen-prod-w2-fusion](#gen-prod-w2-fusion)) | not built: at C = 128 one N tile removes S61's 8x backward recompute, but the atom-major tile still needs all four degrees' B tiles per K step (B tiles are BK x 128 whatever C is), the structure S61 measured at 13.3 against 15.1 TFLOP/s at 5,184 atoms, and per-degree GEMMs with the product backward in their A prologue would recompute it once per degree (4x). Bound: the product kernels, 564 us per OMAT-0 generic SrTiO3 force call (`gprod_fwd` 102, `gprod_bwd` 235, `gprod_ro1_fused` 227; S141 profile), less the grouped GEMM's loss. Falsifier first: a grouped four-degree GEMM at OMAT-0's shapes against the four tuned lanes | owner's idea list, 19 Nov |
| `lin1` backward fused into the conv backward's staging (persistent blocks of 16-32 receivers) | not built: it removes the `dm1` round trip and the 597 us `lin1` backward group ([int1-lin1-fusion](#int1-lin1-fusion)), but the GEMM's work stays: 5,000 atoms x 38 rows x 128 x 128 x 2 = 6.2 GFLOP per call, ~0.41 ms at `sgemm128`'s ~15 TFLOP/s, so most of the 597 us is arithmetic that would move into an issue-bound kernel at 96 registers, not traffic that would vanish (`dm1` is 97 MB, written by a GEMM at about its arithmetic peak and read by an issue-bound kernel: both overlap the traffic); `W_lin1` (655 KB) does not fit in shared memory, so each receiver batch streams it from L2, and the backward conv becomes a batched-receiver kernel (S47 / S139: one-receiver blocks are L2-bound, R5 wins by sharing rows in L1). Falsifier first: a standalone batched mini-GEMM writing `s_q` tiles, which must beat 597 us | owner's idea list, 19 Nov |
| Direct-force readout head (forward pass only, no backward) | not built: the forces are no longer the model's (-grad E), so it cannot pass the accuracy gate by construction and needs a trained head; a different model rather than an implementation of MACE (owner decision) | owner's idea list, 19 Nov |
| Single-pass FP16 tensor-core GEMMs for the degree-2 / 3 projection blocks | closed by the screen ([meas-degree-channel-shell-screens](#meas-degree-channel-shell-screens)): l = 3 alone 3.2-4.9x the float32 force error, l = 2, 3 7.6-7.9x, before FP32 accumulation error | owner's idea list, 19 Nov |
| Earlier cutoff for the l_y = 3 conv paths (split edge loops per sender-species run) | closed by the screen: the l_y = 3 weights do not decay sooner (layer 1: 0.40 of their peak at r >= 5.5 A, l_y = 0 0.30); cutting them at 5.5 A in layer 1 alone gives 56-106x the float32 force error | owner's idea list, 19 Nov |
| One wide cubic interval per coordination shell (crystal-aware radial tables) | closed by the screen: one cubic over +-0.1-0.2 A fits each column only to 5.6e-3-1.8e-2 of its peak (the tables' bound is 5e-4), forces 108-6,500x the float32 error; only 41% of the edges fall within +-0.15 A of a shell at rattle 0.20 A | owner's idea list, 19 Nov |
| Least sensitive conv channels in FP16 (`HFMA2`, 4-byte tables) after a load-time permutation | closed by the screen: 32 of 128 channels in FP16 (weights and per-edge outputs, accumulation exact) give 4.8-6.0x the float32 force error, 8 channels 1.4x / 4.3x; ordered by a sensitivity proxy against random order 4.8x / 24.8x at 32 | owner's idea list, 19 Nov |
| Persisting-L2 window for the hot radial slabs, or for the model weights; `L2::evict_first` on `m1` / `dm1` and product buffers | closed by the archived profile (`results/profiles-20261119/ncu`, OMAT-0 generic SrTiO3): the L1 convs already hit L2 on 96.5% (forward) / 95.0% (backward) of their reads, so no window or eviction hint can raise it much; their cost is L2-to-SM traffic and latency, not DRAM. GEMM weights (~2 MB) are re-read from L2 by every tile already | owner's idea lists, 19 Nov |
| Backward adjoint `s_q` in swizzled shared-memory layouts | closed by the archived profile: shared-load bank conflicts add 1.62 M to 60.7 M load wavefronts (2.7%) in `gconv_bwd_L1`; the forward's 0.35 M store conflicts are 1.4% of its 25.8 M shared wavefronts | owner's idea list, 19 Nov |
| Radial rows aligned to observed sector demand; columns permuted to the forward's consumption order | not built: each warp reads one path's 32 channels x 8 B = 256 B contiguous, and slab rows start at multiples of 10 x 128 x 8 B, so every sector a warp touches is fully used already | owner's idea list, 19 Nov |
| Byte-identical packed subrows interned across slabs | not built: the table's active part (~4 MB on rattled SrTiO3) is L2-resident (above), so a smaller working set does not cut the L2-to-SM traffic, the forward's cost; only an L1-level effect could, and the dictionary of S138 showed how indirection costs occupancy | owner's idea list, 19 Nov |
| Prefetching the next forward tile's rows; warp-specialised producer warps; TMA staging | closed by earlier falsifiers: `prefetch.global.L1` of the next unit's rows +2.6-3.1% (the prefetched lines evict the rows R5's five receivers share in L1), register prefetch one edge ahead ties (R5 cannot hold the registers); a slab row is 10 KB per edge at 128 channels, too large to stage a tile of them in shared memory | owner's idea lists, 19 Nov |
| Bond-direction lookups shared by both directed edges; the previous step's interval reused with an exact check | not built: the slab and t of every active edge are computed once per force call in the compaction pass (`PRELOC`, `compute_and_count_active` 41-47 us of SrTiO3's step), so either saves a fraction of that pass, below 0.5% of the step | owner's idea list, 19 Nov |
| Pre-normalised `(nx, ny, nz, 1/r)` in the active-edge vectors | not built: it removes a reciprocal and three multiplies per edge (not per channel-edge) in kernels that spend ~490 instructions per channel-edge at 128 channels: below 0.01% of their instructions | owner's idea list, 19 Nov |
| Cross-path shared exponent in the packed tables | not built: the 5-bit exponent is per (slab, channel, path) and adapts to each path's magnitude; one exponent for ten paths shifts the smaller paths' mantissas and loses their bits (not exact), and 10 entries of 59 bits break the 8-byte alignment every lane load relies on | owner's idea list, 19 Nov |
| Byte-permute (`prmt`) decode of the packed entries | not built: the fields are 20 / 19 / 12 / 8 bits plus a 5-bit exponent (64 bits); byte-aligned fields would need 24 / 16 / 16 / 8 with no room for the exponent, i.e. fewer mantissa bits, the S103 direction that failed | owner's idea list, 19 Nov |
| FP4 / NVFP4 slices; 2:4 structured sparsity for the projections | not built: FP4 carries one mantissa bit, so FP32-grade products need on the order of ten slices and dozens of products; an exact 2:4 split leaves a residual with the other half of the entries (unstructured), so the dense work does not shrink | owner's idea list, 19 Nov |
| `lin1` l = 0 block fused into the forward conv | not built: l = 0 is 1 of the 38 `m1` rows per atom: ~1/38 of the `lin1` forward group (529 us) and of the `m1` traffic, and its 128 x 128 product per receiver moves into the latency-bound forward conv | owner's idea list, 19 Nov |
| Hybrid / cluster (DSMEM) sender-gradient reduction | not built: removing every sender-gradient atomic saves 5% of the OMAT-0 generic backward ([meas-conv-ablation-bounds](#meas-conv-ablation-bounds)); in a crystal every sender has about the same fan-in, so there are no hotspots to route | owner's idea lists, 19 Nov |
| Programmatic dependent launch between the backward conv and the layer-0 edge backward | not built: S72 measured the GPU idle between kernels at 1.9-5.3% of the step in all (median gap 0.2-0.6 us), and `edge_dvec` (4.5 MB) stays in the 32 MB L2 between the two kernels anyway | owner's idea list, 19 Nov |
| Specialised or generic OMAT-0 path chosen per system shape | not built: on the 5060 Ti the generic path leads at every size tested (S97-S101: 0.964-0.993 of the specialised path's step from 320 to 5,000 atoms), and the release runs it by default | owner's idea list, 19 Nov |
| Product intermediates laid out for their consumer | not built: the product kernels run at 81-91% of DRAM peak, so a layout change that keeps their bytes keeps their time; only fusion removes bytes (above) | owner's idea list, 19 Nov |
| Force-only steps without stress-only stores | not built: `evaluate(..., compute_stress=False)` and the MD loop already skip the virial; a byte-level liveness audit of the remaining stores was not done | owner's idea list, 19 Nov |
| Ozaki-I GEMMs (INT8 mantissa slices, shifted FP32 accumulation) | closed by [meas-tc-overlap-ozaki-locality](#meas-tc-overlap-ozaki-locality): three 7-bit slices with the six products i + j <= 2 give 6.8x / 19x the float32 force error (all nine: 2.1x / 6.9x); four slices with ten products pass, which at the measured INT8 rate (172 TOP/s at 8,192^3, 18-73 TOP/s at OMAT-0's K = 128-512 shapes) is at most ~17 effective TFLOP/s, before slicing passes: no better than the SIMT GEMMs | owner's idea list, 19 Nov |
| Convs on SIMT beside tensor-core GEMMs (receiver-chunked overlap, `fm_tf32x3` or split-warp dual-pipe GEMMs) | closed by the co-run measurement: force calls beside a side-stream matmul loop overlap it by 0.04-0.07 of the shorter part with FP32 SIMT matmuls (S104's zero-sum), 0.20-0.25 with TF32 and 0.07-0.12 with FP16 tensor-core matmuls; three TF32 products for FP32 accuracy at 80% of their standalone time cost more than the SIMT GEMM they replace. The forked-lane test of [gemm-dual-pipe-lanes](#gemm-dual-pipe-lanes) lost the same way | owner's idea lists, 19 Nov |
| Sender feature rows permuted for locality (independent of the receiver order) | closed by the bound in [meas-tc-overlap-ozaki-locality](#meas-tc-overlap-ozaki-locality): with every sender load and atomic sent to one of 16 atoms next to the receiver (perfect locality, timing only) the forward conv drops 56 us and the backward 17 us per force call, under 1% of the step, before the permuted producer's cost | owner's idea list, 19 Nov |
| Receiver rows split, ordered or given kernel variants by predicted work; a short-tail path for the last partial tile | closed by the census: active degrees on a 300 K-like SrTiO3 cell are Sr 62-68, Ti 75-86, O 70-80; R5 blocks hold 357-380 edges (the block's longest receiver 1.056x the mean tiles); the backward walks edges by warp stride (no tiles), and the forward's partial last tile only stages and contracts the edges it has | owner's idea list, 19 Nov |
| Undirected tensor-core synthesis of the radial weights from a 64-wide hidden table | not built: the bound is what the convs pay for their tables ([meas-conv-ablation-bounds](#meas-conv-ablation-bounds): 468 us forward, 147 us backward per call, decode kept); the synthesis must pass the gate, i.e. three FP16 products ([meas-radial-precision-screens](#meas-radial-precision-screens)) of 30.4 GFLOP each for w and again for w' at <= 49 TFLOP/s: >= 3.7 ms, or >= 1.9 ms if the pair tables were symmetric | owner's idea list, 19 Nov |
| S72's sliced backward with `dmid` in shared memory instead of registers | not built: 32 channels x 40 values x 4 B = 5 KB per warp; the 5060 Ti's 100 KB of shared memory per SM then holds at most 20 warps, about S72's 16, and leaves ~28 KB of L1, where S72's 58.7% hit rate came from | owner's idea list, 19 Nov |
| Path pairs loaded as 16 B (`LDG.128`) in the convs | not built: the backward's SASS has 10 table `LDG.E.64` per channel-edge of ~490 dynamic instructions (952 static), so pairing saves ~1% of its issue; the forward likewise; it changes the table layout both share | owner's idea list, 19 Nov |
| Register-cap sweeps (`__maxnreg__`) and NVRTC-baked pointers for `gconv_bwd_L1`; two edges pipelined per backward warp; angular components rematerialised | not built: kernel parameters are constant-bank operands already (no registers to free); `gconv_bwd_L1` runs at 62 registers and 4 blocks per SM, and the earlier caps on this kernel spilled ([gen-conv-bwd-lazy-q](#gen-conv-bwd-lazy-q)); the backward already recomputes its harmonics per edge from the direction (`edge_sh16`); a second edge in flight needs registers the 64-register limit does not have | owner's idea lists, 19 Nov |
| L1 eviction priorities between table rows and sender rows (`evict_last` / `evict_normal`) | not built: the sender-locality bound (above) caps what better sender hits can give at ~70 us per call; the tables' L1 share comes from R5's five receivers, which the earlier L1 prefetch showed is easily disturbed | owner's idea list, 19 Nov |
| Active edges kept distance-sorted each step; compaction fused into `first_fwd`; transposed `S0` layout | not built: pairs beyond adjacent edges save ~5% of slab loads at 300 K (S108), and rows are re-sorted at every rebuild (every ~16 steps); the compaction pass is ~100 us per step and `first_fwd` is per receiver, so fusing them needs a cross-row prefix sum; `first_bwd_edge` is bound by its shuffles (S140), not its `S0` layout | owner's idea list, 19 Nov |
| Persistent multi-stage kernel held in L2; HFMA2 / tensor-core radial weights | not built: see [meas-radial-precision-screens](#meas-radial-precision-screens) for the precision side (single-pass synthesis fails; the three-product split passes but runs no faster than SIMT at the measured rates; FP16 outer-shell weights pass only beyond 5.0 A, where the 4-byte far-edge tables already lost) | owner's idea lists, 19 Nov |
| Local site-energy updates (Monte Carlo moves, finite-difference phonons) | not built: a feature, not a speed-up of MD; the owner's count is 518 site energies (1.30%) per move on SrTiO3 and 3,839 atoms (9.60%) at 40,000 atoms | owner decision |
| Cheap bond potential plus multiple time steps (r-RESPA) | not tried (owner: not for now); the owner's screen cuts SrTiO3's fast-force RMS 0.833 -> 0.395 eV/A, NaCl 0.157 -> 0.054 | owner's idea list, 19 Nov |
| Round-4 research directions closed by their own measurements | whole-graph transforms (no shared accurate basis for the radial adjacency matrices: 7.6-23.0% error lower bounds; a local hierarchy covers 0.57% of edges), sparse tensor-core layouts (>= 63.5-97.8 compensated GFLOP per force call), cheaper quadratic radial decoders (fail the force / stress gate on all four test cells, up to 1.81x / 5.26x), whole spatial slabs (3.59x repeated layer-0 work or 36.3 MiB of frontier state against a 32 MiB L2), speculative batches of future trajectory steps (one certified step per wave) | `omat0-round4-20261119/REPORT.md` |
| Species-run boundaries published by the active-edge compaction for `first_fwd_kernel` | closed by the bound in [meas-s142-bounds](#meas-s142-bounds): with the run ends handed in, `first_fwd` drops 231 -> 218 us per force call (a lab kernel forms them in 4.8 us); the compaction pass could write them for less, but 13 us is 0.17% of the step and needs a per-receiver array kept in step with every rebuild path | owner's idea list, 19 Nov |
| Layer 1's density force term moved from the backward conv's lane 0 to the layer-0 edge assembly | closed by the bound in [meas-s142-bounds](#meas-s142-bounds): `gconv_bwd_L1` without the term at all ties (x1.002) | owner's idea list, 19 Nov |
| Bounded fixed-point (integer) atomics for the final force assembly | closed by the bound in [meas-s142-bounds](#meas-s142-bounds): `first_bwd_edge` with all six FP64 force atomics skipped saves 29.5 us per force call; integer atomics still issue the same atomics plus the conversions | owner's idea list, 19 Nov |
| Low-rank factorisation of the dense projections | closed by [meas-s142-bounds](#meas-s142-bounds): every OMAT-0 medium projection is full rank (smallest singular value 3e-5 to 7e-2 of the largest); truncating any interaction-1 `linear` block to rank 112 gives 440-1,130x the float32 force error, rank 96 720-4,800x | owner's idea list, 19 Nov |
| Solid harmonics `[w(r) / r^l] H_l(r)` on one angular path | not built: the angular pullback it would simplify (`fn = G . n`, the tangential projection, `1 / d`) runs once per edge after the warp fold, a dozen instructions against ~2,000 per edge-warp in the channel loop; the channel loop's contractions keep their form, and the table gains an `r^-l` the short-distance branch must undo | owner's idea list, 19 Nov |
| Layer-0 adjoint contracted once per repeated (receiver, species, interval) run as 16 cubics | not built: forming `G^T A` costs as much as two edges' contractions (64 columns x 16 harmonics x 4 coefficients), so it pays only on runs of three or more edges; S108 found that sharing slabs beyond adjacent pairs saves ~5% of slab loads at 300 K, so such runs are rare, and `first_bwd_edge` is latency / LSU bound (FMA pipe 30%) | owner's idea list, 19 Nov |
| Layer-0 angular gradients projected to Cartesian components before the fold | not built: per lane this needs the 16 x 3 Jacobian of the edge's harmonics, either recomputed by all 32 lanes (~80 FP32 operations each plus 48 FMAs, where S140's 16-slot fold costs 16 shuffles and 15 selects per edge) or staged per edge in shared memory (12 `LDS.128` per lane), after which three or four values still need a fold (6 shuffles plus gathers): at least as many LSU operations as the fold it replaces, in a kernel bound by its LSU pipe | owner's idea list, 19 Nov |
| Active edges compacted in place in each candidate row (no global scan and scatter) | not built: the scan is 2.5 us and `scatter_active_edges` 27 us per force call (nsys, OMAT-0 generic SrTiO3), and the in-place form still writes each active edge's `PRELOC` slab / t; the edge-parallel kernels (`first_bwd_edge`, 375 us) would walk the rows' inactive tails, ~21% of candidate edges at skin 0.5 A on a 6 A cutoff ((6.5 / 6)^3 = 1.27) | owner's idea list, 19 Nov |
| Density gradient of the fused readout from Euler's identity (`x . grad P = P1 + 2 P2 + 3 P3`) | not built: it replaces a 16-term dot product by a 13-term weighted sum per channel (3 FMAs of ~1,200 instructions per thread) in a kernel at 81% of DRAM peak (`gprod_ro1_fused`, ncu 19 Nov) | owner's idea list, 19 Nov |
| One 144-column projection for the 128 scalar features and the 16 skip outputs | not built: the skip is per species (16 columns, `ns` rows each) while `linear_up` is one GEMM over all atoms, so the merge turns the 128-column GEMM into per-species GEMMs; it saves one more read of the 2.6 MB scalar block from L2 and a few small launches, under 10 us per step | owner's idea list, 19 Nov |
| Hybrid GEMM weights pre-split into TF32-high and FP16-residual fragments at load | not built: the hybrid cubin runs 119 us per step on OMAT-0 generic SrTiO3 (2 launches, `fm_tf32x3_rr_64x64`); the B half of its fragment transform is a fraction of that while the weight operand's bytes double, and the cubin is FastMACE's container build | owner's idea list, 19 Nov |
| One level of Strassen on the 25,000 x 128 x 384 projection | not built: seven products instead of eight save at most 1/8 of its 192.5 us (24 us); five of the seven need a sum of two activation blocks (12,500 x 192, 9.6 MB each), as passes ~145 MB of DRAM traffic (> 300 us) or as fused loads 50% more A reads in a GEMM bound by FP32 issue, plus the recombination of four output blocks from seven | owner's idea list, 19 Nov |
| JIT stage 2: the conv kernels compiled at load for the layer's width, species and intervals (`JIT_DESIGN.md`) | done for the widths without a built-in instance: [gen-jit-conv](#gen-jit-conv) (S144); species, intervals and grid stay arguments (stage 1: baking them buys nothing) | owner's request, 19 Nov |
| JIT stage 3: products of models outside the build set from the bundle's factored program, compiled by NVRTC instead of `loupmd build-kernels`' `nvcc` | done on `develop`: [gen-jit-products](#gen-jit-products) (S144); the release's plugin path (`release/v1`) is unchanged | owner's request, 19 Nov |
| JIT stage 4: epilogue fusion (gate, readout, density) chosen from the IR | not built: bounded at about 2-3% of the step on MH-1, OMOL-0 and POLAR only, see [gen-jit-epilogue-bound](#gen-jit-epilogue-bound) | owner's request, 19 Nov |

## Appendix: entries

Each entry has the same fields. Unless stated, the system is OMAT-0 medium on the specialised path.

### Interaction-1 radial spline forward

<a id="spl-paired-edges"></a>
#### spl-paired-edges: paired-edge decode
- Switch: template parameter `PAIR` of `spline_forward_inter1`; chosen per system with spl-multi-receiver.
- Stage: S3 (item 20).
- What: two consecutive edges of a receiver that read the same table slab (edges sorted by `(pair, r)`) decode it once.
- Status: DEFAULT (one of the per-system variants).
- Measured: table loads per edge 1 -> 0.805 (`SrTiO3`), 0.927 (`NbCl5`); spline -7% (5060 Ti), -3% (Ada) on `SrTiO3`. Costs 17-30 registers.
- Why: the spline is L2-bound; fewer slab loads per edge.
- Sources: [§3.1 #20][s31].

<a id="spl-multi-receiver"></a>
#### spl-multi-receiver: R receivers per block, chosen at the first rebuild
- Switch: `spline_forward_inter1<R, PAIR>`, `choose_spline_rpb`, `tune_rebuild_variants`; `LOUP_SPLINE_VARIANT=R1|R1p|R4|R4p|R5` forces one; `LOUP_DEBUG_SPLINE=1` prints the timings.
- Stage: S4-S5 (item 29).
- What: R consecutive receivers per 128R-thread block with per-receiver named barriers and the smallest carveout, so receivers of a symmetric crystal walk the same slabs together and later reads hit L1. Five variants (R1, R1 paired, R4, R4 paired, R5 unpaired) are timed on the last force pass's inputs at the first MD rebuild; the fastest is adopted if >= 2% faster.
- Status: DEFAULT.
- Measured: 5060 Ti `SrTiO3` R4: L1 hit 5% -> 36%, L2 3.92 -> 2.66 GB. Choices: 5060 Ti `SrTiO3` R5, `NbCl5` R1 paired; Ada `SrTiO3` R5, `NbCl5` R4. MD: occupancy rule alone Ada `NbCl5` +1.5% / +0.3%, `SrTiO3` -3.1% / -3.6%; + rebuild-time choice 5060 Ti `SrTiO3` -0.8% / -0.8%; + unpaired and R5 variants 5060 Ti -0.1% to -0.3% (`SrTiO3`), Ada `SrTiO3` -0.4% / -0.9%.
- Why: the gain depends on the system (registers are held until the slowest receiver finishes), hence the per-system timing. Timing at setup on the ideal lattice picked R4 everywhere, which is wrong for thermalised `NbCl5`.
- Sources: [§3.1 #29][s31]; gated per variant by review F1 ([§3.2][s32]).

<a id="spl-launch-128-7"></a>
#### spl-launch-128-7: tighter launch bounds on `sm_89`
- Stage: not recorded.
- What: `(128, 7)` / min-blocks 5 for `spline_forward` on the Ada.
- Status: REJECTED.
- Measured: spills; Ada +17% / +3%.
- Sources: [§3.3][s33].

<a id="spl-16-edge-tiles"></a>
#### spl-16-edge-tiles: 16-edge tiles in the spline
- Status: REJECTED. Measured: tie. Sources: [§3.3][s33].

<a id="spl-receiver-remap"></a>
#### spl-receiver-remap: strided receiver remap
- What: blocks strided over the receiver range for L1 locality.
- Status: REJECTED. Measured: tie. Sources: [§3.3][s33].

<a id="spl-paired-r5"></a>
#### spl-paired-r5: paired 5-receiver blocks and lockstep blocks
- Stage: S4-S5.
- What: R = 5 with pairing (640 threads at 96 registers); lockstep R = 2 / 4 with block-wide barriers.
- Status: REJECTED.
- Measured: paired R5 spills 48-72 B and loses to R1 / R4 (the unpaired R5 fits without spills and is a variant). Lockstep blocks are slower than per-receiver named barriers.
- Sources: [§3.3][s33].

<a id="spl-edge-split"></a>
#### spl-edge-split: edge-split spline for small systems
- Stage: S5.
- What: one receiver per block with its edges over 2 / 4 thread groups and a fixed-order shared-memory reduction.
- Status: REJECTED.
- Measured: 135-atom `SrTiO3` 98 / 82 us against 64 us for the R4 variant; 1.4-1.6x slower at 5,000 atoms.
- Why: even at 135 atoms the 135 blocks keep ~15 warps per SM issuing; the spline is not the small-system limit.
- Sources: [§4.1 #3][s41].

<a id="spl-unroll2"></a>
#### spl-unroll2: 2-edge unroll (before pairing)
- Status: REJECTED. Measured: not recorded. Sources: [§3.3][s33] ("other earlier drops").

<a id="spl-cubic-forward"></a>
#### spl-cubic-forward: the 8-byte cubic table in the forward
- Status: REJECTED. Measured: not recorded. Sources: [§3.3][s33] ("other earlier drops").

<a id="tab-far-edge-4byte"></a>
#### tab-far-edge-4byte: 4-byte table rows for far edges (T2)
- Status: REJECTED.
- Measured: 5060 Ti `w'` 3,286 -> 3,316 us, spline 2,211 -> 2,242 us; Ada `w'` 3,561 -> 3,628 us, spline 2,974 -> 3,075 us.
- Sources: [§3.3][s33].

<a id="spl-receiver-order"></a>
#### spl-receiver-order: receiver / sublattice ordering for slab locality
- Status: REJECTED (S108).
- What: at `N = 5,000`, `mem-reorder` is off (`N * 4 KB < L2`). In `SrTiO3`, the 3,000 oxygen atoms sit in three interleaved sublattices `(0.5,0.5,0)`, `(0.5,0,0.5)`, `(0,0.5,0.5)` in caller order, so consecutive receivers in `R=4/5` blocks mix sublattices. Ordering receivers (or block walk order) by species/sublattice or spatial cell keeps co-resident SMs on the same `(pair, r)` slabs (cf. FastMACE `BLOCK_ORDER`). Do **not** replace the `(sym_pair, r)` edge sort with `sender_idx` (that breaks `PAIR` and slab reuse).
- Measured (S108, 5060 Ti, `SrTiO3` 5,000 atoms after Langevin equilibration to 296.5 K): the input reordered species-major with Morton order within each species (the engine keeps the caller order at this size). The distinct-slab proxy per 5-receiver block fell 0.483 -> 0.357, but `ncu` R5 `spline_forward_inter1` L1 hit stayed at 48.9% -> 48.6% (1.74 ms both) and the force pass got slower (R5 8.02 -> 8.34 ms, +4%). The slab reuse that counts comes from each receiver's own edges (0.30 distinct slabs per edge at rest, 0.75 at 300 K), which the order of receivers does not change; see [s108-wide-table](#s108-wide-table).
- Sources: `OMAT0_SPEEDUP_BRIEF.md`; this file.

<a id="spl-r6-r8"></a>
#### spl-r6-r8: unpaired `R=6` / `R=8` spline blocks
- Status: `R=6` REJECTED (S32, 5060 Ti only); `R=8` not built.
- What: `R=5` unpaired (96 regs, 640 threads = 20 warps/block) already won `SrTiO3` on both GPUs. Check whether trimming `acc[40]` / `she[16]` register pressure lets `R=6` or `R=8` fit at <= 80 registers for higher occupancy and L1 slab sharing.
- Measured (S32, 5060 Ti, `OMAT-0-M` `SrTiO3`): scratch `launch_spline` swap of `spline_forward_inter1<5, false>` for `<6, false>` (768 threads, `__launch_bounds__(768)` from the template) without restructuring: 80 registers with 8 B of stack. `nsys` MD spline kernel time with `LOUP_SPLINE_VARIANT=R5`, two rounds: R5 1796 / 1801 us, R6 1830 / 1863 us (`+3%`). The tuned R5 is register-limited to one block per SM (41.7% occupancy; `s32-specialised-occupancy`), so more warps would need the register restructuring this entry originally proposed; a plain larger block spills.
- S47 (14 November 2026, 5060 Ti only, owner-chosen direction): `spline_forward_inter1_split<R, PAIR>` (generator `_emit_spline_forward1_split`, scratch build): each receiver's 10 paths split over two 128-thread parts of 256 threads per receiver (5 paths / 21 accumulators and 5 paths / 19; paths sharing an accumulator kept together so every output keeps its summation order), part 0's first two warps staging edges as before, named barrier over 256 threads, R <= 4. Registers: S2 / S4 unpaired 64 (no spill; 32 resident warps per SM against R5's 20), S2p 86, S4p 64 with 80 B of stack. Fresh `ncu` before the change (tuned launch, R4 in that process: 99 registers, 33% occupancy): long scoreboard 24% (table `LDG.64` 10%, sender `x` gathers ~10%), not selected 20%, selected 16%, wait 12%. `nsys` spline time per step with the variant forced (two runs each, us): `SrTiO3` R5 1803 / 1777, R4 1833 / 1838, R1p 2064 / 2074, S4 1998 / 1996 (`+12%` vs R5), S2p 2410 / 2432, S2 2829 / 2892; `NbCl5` R5 337 / 337, R4 360 / 353, R1p 335 / 341, S4 358 / 379 (`+9%`), S2p 408 / 408, S2 475 / 485. Forces at the float32 noise of the existing variants (the downstream atomics are order-nondeterministic, so end-to-end bit identity is not observable). Rejected: per thread, each edge's loop overhead (shared-memory staging reads, pair test) and the sender's `x` loads are now paid twice per channel, and the extra warps do not hide enough of it; the 5-receiver L1 slab sharing of R5 is also lost (R <= 4).
- Sources: `OMAT0_SPEEDUP_BRIEF.md`; this file.

<a id="spl-v6-cubic-cg-fold"></a>
#### spl-v6-cubic-cg-fold: `w'` cubic decode and staged CG linear forms in `spline_forward_inter1`
- Stage: S15 (14 November 2026).
- What: switched `spline_forward_inter1` (`python/gen_kernels.py`, `src/engine.cu`) from the 3-coefficient `d_packed8_table_1` + unfolded decode to `d_cubic_packed8_1` (`cubic_bias_shift`) with the `w'` bias-folded cubic decode and warp-staged `s_pw` (`float4`) polynomial factors; grouped per-edge Clebsch-Gordan `CONST * she[m]` linear forms into 18 shared-memory slots (`ED = 36`) computed once per edge in warp 1, applied accumulator scales at store, and narrowed `TILE` from 32 to 16 so `R = 5` stays at `REG:96, STACK:0, SHARED:14784` inside the 16 KB carveout.
- Status: DEFAULT (5060 Ti only).
- Measured (5060 Ti): frozen `SrTiO3` (`R1p`) `1,403.4 -> 1,305.9 us`, all kernels `8,075 -> 7,860 us/eval`; ABBA vs `c24b6c4`: `SrTiO3` `8.4024 -> 8.2752 ms/step` (`0.9848`; with `LOUP_DEBUG_SPLINE`: `8.4259 -> 8.2714`, `0.9817`), `NbCl5` `1.8630 -> 1.8525` (`0.9944`). `mace-omat-0-medium` oxide gate passes on default plus every forced `LOUP_SPLINE_VARIANT` (`R1, R1p, R4, R4p, R5`).
- Sources: this file; `.internal/research/2026-11-14-omat0-medium-speedup-candidates.md` (v6); commit `ca23b3c`.

### Interaction-1 chain as a whole

<a id="int1-radial-low-rank"></a>
#### int1-radial-low-rank: fewer tabulated radial functions
- What: the interaction-1 radial MLP ends in a bias-free linear layer 64 -> 1,280 (10 paths x 128 channels). Two
  proposals (external suggestion, 13 November): (a) tabulate the 64 hidden activations per pair and contract with
  the pair-independent 64 x 1,280 matrix; (b) per channel, tabulate a few basis functions that span its 10 paths.
- Status: NOT BUILT, closed by measurement.
- Measured (CPU, `mace-omat-0-medium.model`, SVD of the last layer's weight, 13 November):
  - whole layer: rank 64 of 64, smallest / largest singular value 0.098. Nothing below the hidden width.
  - per channel, its 10 paths: rank 10 of 10 in all 128 channels (smallest / largest 0.085 to 0.19). A rank-5 basis
    leaves a relative error of 37% (median), rank 8 leaves 18%.
- Why (a) does not pay: 64 FMA per weight against about 17 instructions for one table decode, in a kernel that is
  issue-bound; the first interaction can use the hidden basis only because its input is one scalar per sender
  species, which lets the sum over edges be taken before the contraction.
- Same finding as FastMACE's low-rank table entry (rank 65 of 65) and as the weight statistics of
  `loupmd-review-20261112.md` (fourth pass).
- Sources: this file.

<a id="int1-two-halves"></a>
#### int1-two-halves: two receiver halves on two streams
- What: the chain split into two receiver halves on two streams (spline / GEMM / `w'` overlap), and high-priority GEMM streams.
- Status: REJECTED.
- Measured: 5060 Ti +0.9% / +0.7%.
- Sources: [§3.3][s33].

<a id="int1-l2-chunks"></a>
#### int1-l2-chunks: interaction 1 per L2-sized receiver chunk
- What: spline + `lin1` + `sc1` + `lin1^T` + `w'` per receiver chunk so `m1` / `dm1` stay in L2.
- Status: REJECTED.
- Measured: 5060 Ti 1,700-atom chunks +2.4% / +0.2%, 1,000 +2.4% / +1.1%, 650 +2.6% / +2.8%.
- Why: per-chunk launch and tail costs exceed the DRAM savings; the `lin1` GEMMs run at ~50% DRAM, latency-limited.
- Sources: [§3.3][s33].

<a id="int1-lin1-fusion"></a>
#### int1-lin1-fusion: `lin1` inside the interaction-1 kernels
- What: avoid writing and re-reading `m1` / `dm1` (`N x 4864` floats, 97 MB at 5,000 atoms).
- Status: NOT BUILT.
- Measured: ceiling: the `lin1` groups are 529 + 597 us (5060 Ti `SrTiO3`).
- Why: in the one-receiver-per-block spline each block would read all 655 KB of `W_lin1` (~3.3 GB more L2 traffic per step for an L2-bound kernel), and sharing it over R receivers needs R x 38 accumulator registers. Needs a different decomposition (a receiver-tiled tensor-core GEMM consuming spline tiles from shared memory).
- Sources: [§4.1 #1][s41].

### Interaction-1 backward (`w'`)

<a id="wp-decode-bias-fold"></a>
#### wp-decode-bias-fold: bias of the cubic decode folded into the polynomials
- Switch: `LOUP_GEN_DECODE_FOLD` when running `python/gen_kernels.py` (on by default since 13 November; `=0`
  regenerates the unfolded form). It changes both `w'` kernels.
- What: each coefficient is decoded as `raw_k - hb` with `hb = 1.5 * 2^e`. Substituting into `w` and `radial_dt`
  gives `w = raw0 + s1 raw1 + s2 raw2 + s3 raw3 - 1.5 (1 + s1 + s2 + s3) 2^e` (and likewise the slope), with the two
  bias factors computed once per edge: 4 FADD + 1 LOP3 per path become 2 FFMA. External suggestion, 13 November.
- Status: DEFAULT since 13 November. A win on the 5060 Ti in all three runs, a tie on the Ada, the gate passes on
  both: the adoption bar of `OMAT0_SPEEDUP_BRIEF.md`.
- Measured (13 November, libraries built from the same tree, differing only in this switch; `bench_md.py`, order
  a b b a, twice per GPU):
  - SASS, `wprime_backward_inter1_rcv`: `sm_120` 1,000 -> 976 instructions and the 8-byte stack spill disappears;
    `sm_89` 1,016 -> 1,000; 64 registers on both, before and after.
  - RTX 5060 Ti: `SrTiO3` 8.241 -> 8.183 ms (0.9929) and 8.308 -> 8.265 ms (0.9948); `NbCl5` 1.799 -> 1.790 (0.9951)
    and 1.807 -> 1.796 (0.9938). In all four neighbouring `SrTiO3` pairs the folded side is faster (0.3 to 0.9%).
    A third run after the final rebuild: `SrTiO3` 8.285 -> 8.223 ms (0.9925), `NbCl5` 1.803 -> 1.797 (0.9965).
  - RTX 4000 Ada: `SrTiO3` 9.316 -> 9.331 ms (1.0015) and 9.455 -> 9.413 ms (0.9955); `NbCl5` 1.0002 and 0.9925: a
    tie.
  - Accuracy: the default gate passes all 30 rows on both GPUs. On the 5060 Ti, two gate runs per library: mean
    stress ratio 1.385 / 1.187 unfolded against 1.080 / 1.210 folded (max 2.36 / 2.32 against 1.77 / 1.80); mean
    force ratio 0.702 / 0.670 against 0.698 / 0.696. The gate's ratios vary by about 15% from run to run, more than
    any difference between the two. (A single run each on the Ada, 0.764 against 0.940 for stress, had looked like
    a cost; it is inside that spread.)
  - Ada: 46 tests pass with the folded library (twice).
- Verified with the fold on: 5060 Ti 47 tests and the full gate for all eight model sets (78 rows, worst force
  ratio 1.45, stress 2.27); Ada 46 tests (OMAT-0 small skipped) and the default gate. The full family gate was not
  rerun on the Ada with the fold (the workstations were closed for a power outage); the fold touches only the
  OMAT-0 medium kernels, which the default gate covers.
- Sources: this file.

<a id="wp-cubic-packed8"></a>
#### wp-cubic-packed8: 8-byte exact cubic table
- Switch: `d_cubic_packed8_1`.
- Stage: S1 (item 1).
- What: 20 / 19 / 12 / 8-bit signed quantised coefficients around `s = t - 0.5` with a 5-bit shared exponent (clamped to `emax - 31`, review H4) instead of a 16-byte `float4`.
- Status: DEFAULT.
- Measured: alone not recorded; S0 -> S1 (with the hybrid cubin and bucketing) 2.384 -> 2.187 / 11.380 -> 10.458 ms (5060 Ti), 2.533 -> 2.353 / 12.985 -> 11.764 ms (Ada).
- Sources: [§3.1 #1][s31], [§1][s1].

<a id="wp-receiver-owned"></a>
#### wp-receiver-owned: one receiver per block
- Switch: `wprime_backward_inter1_rcv` for N >= 512, and for every N on `sm_120` since S96 and on compute capability 8.0 since S114 (`LoupHandle::wprime_rcv_small`, `use_wprime_rcv`); the edge-tiled kernel stays for N < 512 on other GPUs. `LOUP_WPRIME_RCV=0|1` forces either kernel.
- Stage: S3 (item 12); S96 (16 November 2026); S114 (17 November 2026).
- Status: DEFAULT.
- Measured: -170 us on both GPUs. S96 (5060 Ti): the threshold dated from S3, before the receiver-owned kernel's later tuning (shift-free decode, per-system block size, decode bias fold). Small SrTiO3 cells, `LOUP_WPRIME_RCV=1` against the default in separate processes, 3 ABBA rounds: 40 / 135 / 320 atoms `0.984` / `0.953` / `0.967` (both orders below 1). Library ABBA on shared GEMM plans, S86 -> S96: 135 atoms `0.974` (`0.975` / `0.973`), 320 atoms `0.963` (`0.967` / `0.959`), NbCl5 and the 5,000-atom SrTiO3 (already receiver-owned) `1.000` / `1.000`. Gates (oxide set, OMAT-0 medium and MPA-0 medium specialised): the small cells now run the receiver-owned kernel by default and the edge-tiled one forced (`test_gate.py` `SMALL_VARIANTS` gate both kernels on any GPU), all PASS; 77 tests pass.
- S96c (17 November 2026, NHR Alex A100-SXM4-40GB node a0701, job 5014761 `loup-s96c`, library s86): `LOUP_WPRIME_RCV=1` against the default (edge-tiled below 512 atoms off `sm_120`) in separate processes, 3 ABBA rounds: 40 / 135 / 320 atoms `0.994` (`0.996` / `0.992`), `0.989` (`0.988` / `0.989`), `0.968` (`0.969` / `0.967`). This meets the [A100 queue](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/alex-a100-queue-20261116/README.md)'s criterion for extending `use_wprime_rcv()` to cc 8.0. The A100 gates already run the receiver-owned kernel on these cells (`test_gate.py` forces `wprime_rcv=1` below 512 atoms): at the cc 8.0 defaults (`loup-s80g`) every row passed, the specialised SrTiO3_3x3x3_c1 stress row at 2.63-2.88x ([a100-own-ext-nb-groups](#a100-own-ext-nb-groups)).
- S114 (17 November 2026, the owner's decision): the receiver-owned kernel is the default at every size on compute capability 8.0 too (`wprime_rcv_small = is_sm120 || cc80` in `loup_create`). Nothing changes on the 5060 Ti (`tests/test_engine.py` 31 passed on the side build); the new default has not yet run on an A100 itself, only the forced variant above.
- Why: the receiver's q is staged once per block. At 320 atoms the edge-tiled `w'` took 208 us against the generic path's receiver-owned `gconv_bwd_L1` at 186 us (`nsys`), which made the generic path 5.5% faster than the specialised one there (`ab_libs.py`, both orders); after S96 the paths are within 2% at every size (generic / specialised, 3 ABBA rounds: 135 atoms `1.017`, 320 atoms `0.983`, 1,080 atoms `1.006`, 5,000 atoms `1.001`).
- Sources: [§3.1 #12][s31], this file.

<a id="wp-channel-major-q"></a>
#### wp-channel-major-q: channel-major staged q
- Stage: S3 (item 21).
- What: `s_q[channel * 44 + slot]` (11 x 16 B, odd stride), so each lane reads its 40 q values as 10 conflict-free `LDS.128`.
- Status: DEFAULT.
- Measured: `w'` -1.7% (5060 Ti), -2.5% (Ada).
- Sources: [§3.1 #21][s31].

<a id="wp-shift-free-decode"></a>
#### wp-shift-free-decode: coefficients packed at their float bit position
- Stage: S4 (item 27).
- What: each coefficient's mantissa bits sit at their float position, so a coefficient decodes as one `LOP3` (or a funnel shift + `LOP3`).
- Status: DEFAULT.
- Measured: inner loop 480 -> 448 static instructions; `w'` 3,177 -> 3,065 us (5060 Ti). MD 5060 Ti -0.5% / -1.2% (A), -0.8% / -1.3% (B); Ada +0.4% / -0.8% (A), -0.6% / -1.1% (B).
- Sources: [§3.1 #27][s31].

<a id="wp-dt-scale"></a>
#### wp-dt-scale: radial derivative scaled by 2^8
- Stage: S4 (item 28).
- What: `fma(ds3', d3, fma(ds2', d2, d1))` with `ds2' = 2^8 ds2`, `ds3' = 2^8 ds3` and one `2^-8` at the epilogue; bit-identical (power-of-two scaling), one `FMUL` less per path.
- Status: DEFAULT.
- Measured: `w'` 3,069 -> 3,010 us, 774 -> 760 M instructions (5060 Ti). MD 5060 Ti -0.1% / -0.5% (A), -0.5% / -0.6% (B); Ada tie.
- Sources: [§3.1 #28][s31].

<a id="wp-block-size"></a>
#### wp-block-size: 256 or 512 threads, chosen per system
- Switch: `(512, 2)` launch bounds, warp stride `blockDim.x / 32`; timed with the spline variants; `LOUP_WPRIME_THREADS=512` forces it.
- Stage: S5 (item 31).
- Status: DEFAULT.
- Measured: 512 threads halve the shared memory per SM (5060 Ti L1 hit 5.9% -> 10.5%, L2 5.27 -> 5.05 GB). Ada `SrTiO3` 3,230 -> 3,130 us (picked); 5060 Ti 3,009 -> 3,034 us and Ada `NbCl5` 519 -> 511 us (within 2%: 256 kept). MD 5060 Ti tie; Ada `SrTiO3` -1.0% / -1.2%.
- Sources: [§3.1 #31][s31].

<a id="wp-vector2"></a>
#### wp-vector2: 2-channel vectorised `w'` (T1)
- Status: REJECTED. Measured: -1.6% at `(256, 3)` on the 5060 Ti, +2.3% on the Ada. Sources: [§3.3][s33].

<a id="wp-paired-edges"></a>
#### wp-paired-edges: paired edges in `w'`
- Status: REJECTED.
- Measured: instructions -3% to -6%, but 64 -> 80 / 128 registers (spills at 64); 3.23 -> 3.28 / 3.35 ms.
- Sources: [§3.3][s33].

<a id="wp-channel-passes"></a>
#### wp-channel-passes: 2 / 4-pass channel staging
- What: smaller `s_dout`, more L1.
- Status: REJECTED. Measured: 3.23 -> 3.40 / 3.80 ms. Sources: [§3.3][s33].

<a id="wp-x0-hoist"></a>
#### wp-x0-hoist: scalar-path `x0` hoisting
- What: accumulate the `x0`-scaled pull terms of the four `a = 0` paths and multiply once per channel.
- Status: REJECTED.
- Measured: -2 M instructions, but spills at 64 registers (3,016 -> 3,086 us); still slower at `(256, 3)` / 80 registers (2,992 -> 3,018 us).
- Sources: [§3.3][s33].

<a id="wp-launch-256-3"></a>
#### wp-launch-256-3: `(256, 3)` launch bounds
- Status: REJECTED.
- Measured: 80 registers, 50% occupancy: 5060 Ti 3,013 -> 2,992 us, Ada 3,184 -> 3,184 / 3,221 us; below A/B resolution.
- Sources: [§3.3][s33].

<a id="wp-persistent"></a>
#### wp-persistent: SM-local persistent `w'`
- What: grid = resident blocks; receivers handed out from per-SM contiguous ranges (`%smid`, atomic cursors, stealing at the end), so co-resident blocks work on neighbouring receivers.
- Status: REJECTED.
- Measured: L1 hit 5.7% -> 12%, L2 bytes 5.3 -> 5.4 GB, 40 B stack; 3,014 -> 3,240 us (5060 Ti).
- Sources: [§3.3][s33].

<a id="wp-no-allocate"></a>
#### wp-no-allocate: table loads without L1 allocation
- What: `ld.global.nc.L1::no_allocate` for the table, to keep L1 for sender rows.
- Status: REJECTED.
- Measured: L1 hit 9.7% -> 1.3%, L2 5.06 -> 5.53 GB, 3,022 -> 3,120 us (5060 Ti).
- Why: adjacent warps do re-read table rows through L1.
- Sources: [§3.3][s33].

<a id="wp-scalar3-quad"></a>
#### wp-scalar3-quad: the scalar rank-three path with direction quadratics
- Switch (reverted): `python/gen_kernels.py` `_emit_wprime_backward1`, scalar `L = 3` branch; `LOUP_GEN_SCALAR3_U` chose where the quadratics live.
- Stage: S117 (18 November 2026), 5060 Ti. From the owner's review list of 17 November.
- What: the scalar path `(0, 3, 3)` needs `v_a = T_abc n_b n_c` and `h = n . v` only. With T symmetric and traceless (stored q0..q6; q7 = -q0 - q3, q8 = -q1 - q5) and the five quadratics `u = (nx^2 - nz^2, ny^2 - nz^2, 2 nx ny, 2 nx nz, 2 ny nz)`, each `v_a` is one five-term sum: 15 FMAs and two adds per channel instead of eight three-term dots (`Q_ab = T_abc n_c`, then `v = Q n`) plus the trace, about 26. Three variants: u per edge in registers (`regs`), staged per edge in shared memory and read through a volatile pointer inside the path (`shared`), and computed inside the path (`path`; the compiler hoisted it out of the channel loop).
- Measured (5060 Ti): `cuobjdump --dump-resource-usage`: `wprime_backward_inter1_rcv` 64 registers with 48 B stack in all three variants (HEAD: 64, no stack; the cap comes from `__launch_bounds__(512, 2)`), the tiled kernel 40 B stack (`regs`, `path`) or none (`shared`). `w'` time from the tuner at the first MD rebuild, two rounds alternating with HEAD: SrTiO3 (256 threads) HEAD 2,788 / 2,785 us, `regs` 3,030 / 3,069, `shared` 3,032 / 3,025, `path` 3,116 / 3,086; NbCl5 HEAD 429 / 430, `regs` 474 / 474, `shared` 468 / 468, `path` 475 / 474: 9-12% slower in every case.
- Why: the receiver-owned kernel already sits at its 64-register cap; the quadratics (live across the channel loop, or their loads and q7 / q8 inside it) push it into local-memory spills that cost more than the ~9 instructions per channel saved.
- Status: REJECTED. The generator and `src/generated_kernels.cuh` are back at HEAD (regenerated, byte-identical).
- Sources: this file.

### Interaction 0 and the symmetric contractions

<a id="i0-receiver-owned-fwd"></a>
#### i0-receiver-owned-fwd: receiver-owned i0 forward
- Stage: S2 (item 4).
- What: register accumulation per sender-species run, zero writes for absent species; guarded at rebuild end by `check_row_species_order_kernel`.
- Status: DEFAULT.
- Measured: removes the atomics and the 61 MB per-step `S0` / `D0` zero-fill; alone not recorded.
- Sources: [§3.1 #4][s31].

<a id="i0-bwd-prefetch"></a>
#### i0-bwd-prefetch: lane-parallel metadata in i0 backward
- Stage: S2 (item 5). Status: DEFAULT. Measured: not recorded alone. Sources: [§3.1 #5][s31].

<a id="i0-bwd-fused-assembly"></a>
#### i0-bwd-fused-assembly: i0 backward with force / virial assembly (T5)
- Stage: S3 (item 14).
- What: `force_virial_assemble_kernel` folded in; `d_dsh0`, `d_dr0` removed; 32-edge warp chunks.
- Status: DEFAULT. Measured: not recorded alone. Sources: [§3.1 #14][s31].

<a id="i0-bwd-sh-staging"></a>
#### i0-bwd-sh-staging: staged SH and `float2` channel pairs in i0 backward
- Stage: S3 (item 23).
- Status: DEFAULT.
- Measured: 685 -> 564 us (5060 Ti), 736 -> 668 us (Ada); L1 requests per edge ~29 -> ~11.
- Sources: [§3.1 #23][s31], [§2][s2].

<a id="i0-fwd-warp-per-receiver"></a>
#### i0-fwd-warp-per-receiver: warp-per-receiver i0 forward
- Stage: S3 (item 25).
- What: 4 receivers per 128-thread block, 2 channels per lane (`float2` coefficient loads, one SH broadcast per two channels), per-edge D0 term at staging.
- Status: DEFAULT.
- Measured: 390 -> 245 us (5060 Ti, 64 KB carveout), 415 -> 304 us (Ada).
- Sources: [§3.1 #25][s31].

<a id="i0-sh-shuffle"></a>
#### i0-sh-shuffle: SH shuffle broadcast in i0 backward (old idea 3)
- Status: SUPERSEDED. Measured: tie; replaced by i0-bwd-sh-staging. Sources: [§3.3][s33].

<a id="i0-bwd-receiver-owned"></a>
#### i0-bwd-receiver-owned: receiver-owned i0 backward (T7)
- Status: REJECTED.
- Measured: +1.8% / +1.1% (5060 Ti).
- Why: per-chunk edge parallelism beats per-receiver runs.
- Sources: [§3.3][s33].

<a id="i0-bwd-micro"></a>
#### i0-bwd-micro: i0 backward micro-variants
- What: SASS stall sampling put ~14% of samples on the first FFMA consuming the edge's coefficients. Tried: next edge's coefficients prefetched into registers (96 registers); coefficient loads at the top of the iteration (80 registers); `grad_a` in 4 interleaved partial sums.
- Status: REJECTED.
- Measured: 551 -> 571 us; 554 -> 564 us; 554 -> 626 us (+4 M instructions).
- Sources: [§3.3][s33].

<a id="i0-per-species-fwd"></a>
#### i0-per-species-fwd: per-species i0 forward
- Status: REJECTED. Measured: not recorded. Sources: [§3.3][s33] ("other earlier drops").

<a id="sc-sc1-fused"></a>
#### sc-sc1-fused: fused `sc1` forward, readout and backward
- Stage: S2 (item 6).
- What: `sc1_forward`, the `128 -> 16 -> 1 -> 16 -> 128` readout forward / backward and `sc1_backward` in one `N x 128` launch.
- Status: DEFAULT. Measured: not recorded alone. Sources: [§3.1 #6][s31].

<a id="sc-sc0-bwd-launch"></a>
#### sc-sc0-bwd-launch: `sc0_backward` at `(128, 3)`
- Status: REJECTED. Measured: not recorded. Sources: [§3.3][s33].

<a id="sc-sc0-overlap"></a>
#### sc-sc0-overlap: `sc0` per species beside the other species' products
- What: forward `sc0_forward` of species s on its l = 3 lane after its four products; backward `sc0_backward` of s, then its products, while the next species' `sc0_backward` runs (16 side streams).
- Status: REJECTED.
- Measured: 5060 Ti `SrTiO3` i0 forward end -> spline start 470 -> 489 us, `w'` end -> i0 backward start 600 -> 647 us; `NbCl5` -4 / +1 us.
- Why: the DRAM-bound `sc0` kernels compete with the products.
- Sources: [§3.3][s33].

<a id="frc-segmented-f64"></a>
#### frc-segmented-f64: receiver-warp segmented float64 force reduction
- Status: REJECTED. Measured: not recorded. Sources: [§3.3][s33].

<a id="frc-per-atom-energy"></a>
#### frc-per-atom-energy: per-atom energy array (T6)
- Status: REJECTED.
- Measured: +0.5% / +0.1% (5060 Ti).
- Why: the extra reduction launch costs more than the removed atomics.
- Sources: [§3.3][s33].

<a id="i0-bwd-rcv-warp-agg"></a>
#### i0-bwd-rcv-warp-agg: warp-aggregated `rcv` force atomics in `i0_bwd`
- Status: NOT BUILT.
- What: `tabled_outer_sum0_backward_kernel` (`src/interaction0.cu:421-426`) performs 3 `double atomicAdd`s for `rcv` and 3 for `snd` on every active edge. Because active edges are receiver-sorted (~75 edges/atom on `SrTiO3`), a 32-edge warp spans 1-2 receivers; warp-aggregating `rcv` contributions before `atomicAdd` roughly halves `forces_f64` atomic traffic. Falsifier: check `ncu` atomic stall counters first; stop if no material stall or < 0.5% MD gain.
- Sources: `OMAT0_SPEEDUP_BRIEF.md`.

### GEMMs and the autotune

<a id="gemm-hybrid-cubin"></a>
#### gemm-hybrid-cubin: TF32 + FP16 hybrid GEMM cubins (labelled "3xTF32 hybrid" until 15 November 2026)
- Switch: `cubins/tf32x3_hyb_sm120.cubin` on `sm_120`, `tf32x3_hyb_sm80.cubin` on `sm_80` / `sm_86` / `sm_89`, `_sm90` on `sm_90`; three tiles (64 x 64, 32 x 64, 64 x 32) as autotune candidates; `LOUP_NO_HYBRID=1` disables them.
- What it computes (correction, 15 November 2026, from FastMACE's `fastmace/kernels/cutlass/hybrid_f16.h`): CUTLASS's 3xTF32 split with the big x big product on one TF32 MMA and the two cross products in ONE FP16 MMA (`m16n8k16`), the cross term scaled by 2^11. Not pure 3xTF32: every |element| of A and B must stay below 32,752 or the cross term overflows to `inf`; below 2^-14 the cross term loses bits. The owner allows FP16 where it is accurate (`AGENTS.md`, 15 November 2026).
- Overflow detection (S65, `src/engine.cu` `drop_hybrid`; fail-loud detection with recovery for later calls, not prevention): a non-finite energy, force or stress from `loup_evaluate` with the hybrid loaded disables it for the engine (GEMM plans re-tuned without it, disk plans that chose it skipped while it is unloaded, graphs re-recorded) and re-evaluates once; still non-finite returns -1 ("model output"). An MD block whose final energy is non-finite drops it too and returns -1 (the block's state is lost; the caller restarts from a saved state). Both paths exercised with throwaway NaN injections (5060 Ti, OMAT-0 small SrTiO3, 4 of 37 shapes on the hybrid): `evaluate`, one poisoned call -> hybrid dropped, 10 shapes re-tuned, the retry returned finite results; two -> the call failed with the model-output error, later calls ran without the hybrid. MD, the first 64-step block poisoned -> hybrid dropped, `run_langevin` raised with the lost-state message; after `set_state` the next two blocks ran (10 shapes re-tuned, no hybrid picks).
- Stage: S1 (item 2); scoped in S6 (gemm-simt-for-lr).
- Status: DEFAULT (scoped: every model without long-range terms).
- Measured: alone not recorded (part of S0 -> S1). Ada uses them for most products ([§2][s2] top kernels: `fm_tf32x3_*` 1,179 / 750 us on `SrTiO3`).
- Sources: [§3.1 #2][s31].

<a id="gemm-tc-own-cubins"></a>
#### gemm-tc-own-cubins: LoupMD's own tensor-core GEMM cubins (A100 candidates)
- Switch: `cubins/src/gemm_tc.cu` (CUTLASS v4.8.1 `DefaultGemm`, from FastMACE's `tf32x3_sm80.cu`), `cubins/src/build_gemm_tc.sh`; self-describing table `loup_gemm_tc_info` (math, beta support, tiles), entries `loup_gemm_tc_{rr,rc}_<t>` taking beta. `HybCubin` (`src/engine.cu`) reads both this format and the shipped `fm_tf32x3_info` cubins; the autotune offers every tile the cubin has, and products with beta != 0 only if it supports beta. Compute capability 8.0 loads the format-2 `cubins/gemm_tc_hyb_sm80.cubin` by default since S77 ([a100-cc80-defaults](#a100-cc80-defaults)); other GPUs keep the shipped FastMACE cubins, and `LOUP_HYBRID_CUBIN` loads any build (tests).
- Stage: S66 / S67 (15 November 2026).
- Builds: `gemm_tc_hyb_sm80` (TF32 + FP16 hybrid) and `gemm_tc_3x_sm80` (true 3xTF32, no FP16), 6 tiles (64x64, 32x64, 64x32; 128x64 and 64x128 with 32x32 warps, 132-138 registers; 128x128 with 64x32 warps, 240-246 registers; no spills) and beta; `_sm90` / `_sm120` hybrid builds with the three legacy tiles and no beta. A 128x128 tile with 64x64 warps (CUTLASS example 27) spilled 368-392 B of stack with the 3xTF32 fragments and was replaced.
- Plan cache: the file name now carries the loaded cubin's FNV-1a hash (`_c<hash>`), so a replaced or overridden cubin is re-timed (a one-time re-tune on every GPU); after `drop_hybrid` the engine clears its disk plans and saves none, so a later process with the hybrid still times it.
- Status: DEFAULT on compute capability 8.0 since S77 (`gemm_tc_hyb_sm80.cubin`, format 2: [a100-cc80-defaults](#a100-cc80-defaults)); a test path (`LOUP_HYBRID_CUBIN`) elsewhere.
- `sm_120` six-tile beta build (S78, 16 November 2026, 5060 Ti `tc_bench`, format 2): the 128x64 / 64x128 / 128x128 tiles are 5-35% slower than its 64x64 tile on every shape tried (`5000 x 512 x 512`, `3000` / `1944` / `648 x 512 x 512`, `15000 x 128 x 384`, `5000 x 128 x 128`), except `35000 x 128 x 256` (64x128 222.8 against 231.9 us, cuBLAS 187.5); the beta entries reach 1.10x cuBLAS on `5000 x 512 x 128` beta products. TF32 throughput, not tile shape, limits this GPU: not built into the `sm_120` default.
- Measured (5060 Ti, `.tmp_o/alex64/tc_bench.cu`, hybrid three-tile build): `5000 x 512 x 512` 0.83x `cublasSgemm` (190 us), `1944 x 128 x 512` (transposed B) 1.36x; relative error of the hybrid 3.6e-7 / 4.0e-7 against cuBLAS FP32's 9.8e-7 / 3.5e-7 (float64 reference).
- A100 (S70 session, NHR Alex A100-SXM4-40GB, job 5005454, library s67): `tc_bench` on the 30 GEMM shapes with the largest picked time over 11 generic profiles (MH-1, OMOL-0, MPtrj, MP-0, OFF, OMAT-0): all 720 tile measurements (both cubins, every tile, every shape) are more accurate than pedantic cuBLAS FP32 on the same shape (max relative error 6.1e-7; cuBLAS 3.7e-7-1.4e-6). Hybrid best tile against cuBLAS FP32 1.76-2.57x; the new 128x128 / 64x128 tiles win most large shapes (e.g. `35000 x 512 x 512` transposed 506 us against the shipped 64x64 pick's 568 us). True 3xTF32 1.58-1.94x cuBLAS, 10-15% behind the hybrid. Full-step in-process A/B (6 rounds, both orders, a second default engine as the noise floor, 0.996-1.001 on large cells): 6-tile hybrid cubin MH-1 SrTiO3 `0.939`, OMOL-0 water216 `0.920`, MPtrj SrTiO3 `0.963`, MP-0 medium / OMAT-0 medium / OFF24-M tie, but MH-1 NaCl216 `1.141` and OFF23-M water216 `1.037` slower; 3xTF32 cubin (also 6 tiles and beta) `1.009-1.023` slower on the large cells and `1.022` / `1.143` on OFF23-M water216 / MH-1 NaCl216 (the same small-cell regression); no hybrid at all (`LOUP_NO_HYBRID=1`) `1.10-1.59`. The small-cell regression is being isolated (tiles vs beta, job loup-s70) before any adoption.
- Format 2 (S72, 16 November 2026): the own three-tile build differed from the shipped cubin (S70 job `loup-s70`: MH-1 NaCl216 `1.134-1.176`, OFF23-M water216 `1.05-1.09` slower, even with the shipped tile shapes and no beta) only in passing beta at run time, so CUTLASS's epilogue kept its source path in every entry (tile-0 SASS 1,032 instructions against the shipped 928). `gemm_tc.cu` now fixes beta at 0 in `loup_gemm_tc_{rr,rc}_<t>` (`loup_gemm_tc_info` format 2) and adds runtime-beta `loup_gemm_tc_{rrb,rcb}_<t>` to beta builds; `HybCubin` launches those for beta != 0 and still reads format 1. Tiles 0-2 of the rebuilt `gemm_tc_hyb_sm80` / `_sm90` / `_sm120` are SASS-identical to the shipped FastMACE tiles (same instructions, constant-bank offsets aside, both transposes, all three architectures), so the format-2 6-tile beta cubin is a superset of the shipped one. A100 speed and gates: job `loup-s72d` (pending).
- Sources: this file.

<a id="a100-own-ext-nb-groups"></a>
#### a100-own-ext-nb-groups: the `sm_120` SGEMM extensions and neighbour lane groups on the A100 (lane groups default since S80)
- Switch: `src/engine.cu` `LoupHandle::own_ext` (sgemm64 / sgemm32 + split-K candidates, narrow-N rules, N-fastest rasterisation, the N = 96 kernel; on for `sm_120` and, since S84, for compute capability 8.0 when no GEMM cubin is loaded) and `nb_groups_ok` (lane-group neighbour count / fill kernels; on for `sm_120` and, since S80, compute capability 8.0); `LOUP_OWN_EXT=0|1` and `LOUP_NB_GROUPS=0|1` force them on any GPU. `LOUP_FORCE_TC=1` (tests) runs every GEMM the tensor-core cubin can take on its fastest cubin tile and neither loads nor saves plans, so a gate covers the cubin's arithmetic on every eligible shape.
- Stage: S70 (15 November 2026), NHR Alex A100-SXM4-40GB, library s70.
- Measured (in-process A/B, 6 rounds both orders; both off against both on, side 1 a second default engine): MH-1 NaCl216 `1.094` (noise `1.030`), OFF23-M water216 `1.133` (`1.038`), POLAR-1-M NaCl216 `1.072`, OFF24-M water `1.021`; MH-1 SrTiO3 `1.002`, MP-0 medium SrTiO3 `1.005`, OMOL-0 water216 `1.007`, POLAR-1-M NbCl5 `1.005`.
- Gates with both on: two rows crossed the 3x stress limit, MP-0 medium oxide SrTiO3_3x3x3_c0 3.16 (`dS` 1.18e-7, MACE float32 3.7e-8) and OMAT-0 medium generic oxide SrTiO3_3x3x3_c1 3.27 (`dS` 3.96e-7, float32 1.21e-7); S67 passed them at 2.81 / 2.97. On the 5060 Ti (float32 SIMT GEMMs) the same rows are 0.27 and 1.27, so the margin is set by the A100's TF32 + FP16 GEMM arithmetic; attribution and rounded-split cubins: jobs `loup-s72a` / `loup-s72d`.
- S80 (16 November 2026, library s78 = the S78 tree at the cc 8.0 defaults, job `loup-s80s`; in-process A/B, 3 rounds in both orders, side 1 a second default engine), `LOUP_NB_GROUPS=1` / `LOUP_OWN_EXT=1` / both: OFF23-S water216 `0.843` / `1.034` / `0.853` (noise `1.020`); OFF23-M water216 `0.885` / `0.994` / `0.893` (`0.979`); MH-1 NaCl216 `0.965` / `0.969` / `0.919` (`1.009`); POLAR-1-M NaCl216 `1.005` / `0.924` / `0.942` (`1.007`); OMOL-0 XL water216 `0.990` / `1.008` / `0.998` (`0.999`); OMAT-0 medium generic SrTiO3 `0.995` / `0.998` / `0.995` (`1.000`). The lane groups build the same lists: water216 energies bit-identical to the default side, force differences 3.1e-7 / 5.2e-7 eV/A against 2.9e-7 / 4.1e-7 between two default engines. Library ABBA s78 -> s81 (lane groups on by default; job `loup-s81c`, shared GEMM plans, 3 rounds): OFF23-S water216 `0.830` (`0.827` / `0.832`), OFF23-M water216 `0.914`, OFF24-M water `0.982`, MH-1 NaCl216 `1.003` (`1.016` / `0.989`).
- Gates: the lane groups change no arithmetic, so the default's gates stand (`loup-s80g` at the cc 8.0 defaults). With both switches on (`loup-s81g1`), OMAT-0 medium generic oxide passes (worst stress 2.84) and the specialised path's SrTiO3_3x3x3_c1 row crossed with one forced variant (`wprime_rcv=1,wprime_threads=512`, stress 3.02; the default and `wprime_rcv=1` rows 2.70). That row has sat at 2.6-3.0x on the A100 in every run since S67 (2.97; `loup-s75g` 2.78, `loup-s80g` 2.63-2.88 at the defaults), set by the TF32 + FP16 GEMM arithmetic and moved by the GEMM picks the own-SGEMM extensions change.
- Status: lane groups DEFAULT on compute capability 8.0 (S80). The own-SGEMM extensions stay off there while the GEMM cubin is loaded: slower on OFF23-S water216 (`1.034`) and OMOL-0 (`1.008`), faster only on MH-1 NaCl216 and POLAR-1-M NaCl216, and they move the marginal oxide stress row. Without a cubin (long-range models, whose GEMMs stay float32 SIMT) they are on since S84 (`loup_create`, after `HybCubin::init`): in-process A/B (`loup-s82a`) POLAR-1-S NaCl216 `0.870`, POLAR-1-M NaCl216 `0.959`, POLAR-1-L NaCl216 `0.926`, POLAR-1-M NbCl5 `0.996`; with the S84 dot fold `0.801` / `0.840` / `0.842` / `0.880` ([pol-dot-fold](#pol-dot-fold)); POLAR crystal gates with both pass (`loup-s82g`).
- S84c (17 November 2026, job 5012942 `loup-s84c`): library ABBA s81 -> s84 in separate processes confirms S82-S84 on cc 8.0; the numbers are under [pol-dot-fold](#pol-dot-fold).
- Sources: this file.

<a id="a100-cc80-defaults"></a>
#### a100-cc80-defaults: chain fold, species tables and the own format-2 cubin on compute capability 8.0
- Switch: `src/generic.cu` `folds_measured_here()` (cc 12.0 and 8.0; gates `setup_chain_fold` and `setup_species_tables`), `src/engine.cu` `HybCubin::init` (cc 8.0 loads `cubins/gemm_tc_hyb_sm80.cubin`, the format-2 TF32 + FP16 build of `cubins/src/gemm_tc.cu` with six tiles and compile-time-beta entries; other 8.x keep `tf32x3_hyb_sm80.cubin`). `LOUP_CHAIN_FOLD=0`, `LOUP_SPECIES_TABLES=0`, `LOUP_HYBRID_CUBIN=path` restore the old configuration. Of the S70 switches, `own_ext` stays off on cc 8.0 and `nb_groups` is on since S80 ([a100-own-ext-nb-groups](#a100-own-ext-nb-groups)).
- Stage: S74a (speed), S75g (gates), S77 (default), 16 November 2026, NHR Alex A100-SXM4-40GB.
- Measured (job `loup-s74a` 5012149, library `libloupmd_s73c.so` = commit `ead50901`; in-process A/B, 4 rounds in both orders, side 1 a second default engine within 0.1-1.4%; ratio new / old): cubin alone, fold + tables alone, both: OMOL-0 XL water216 `0.919` / `0.773` / `0.752`; MH-1 NaCl216 `0.981` / `0.874` / `0.875`, SrTiO3 `0.941` / `0.939` / `0.889`; MPtrj SrTiO3 `0.961` / `0.964` / `0.935`; OFF23-M water216 `1.014` (noise `1.014`) / `0.978` / `0.959`; OMAT-0 medium generic SrTiO3 `0.993` / `0.986` / `0.977`; MP-0 medium SrTiO3 `0.994` / `0.984` / `0.979`; OMAT-0 medium specialised SrTiO3 `0.997` / `1.002` / `0.998`. `tc_bench` on 16 shapes: the format-2 build's tiles 0-2 match the shipped cubin's times (SASS-identical); its 128x128 / 64x128 tiles win the large transposed products (`35000 x 512 x 512` 498 us against 557-605).
- Gates (job `loup-s75g` 5012238, both on through the environment, the same arithmetic as the new default; worst force / stress ratio, every forced variant included): OMAT-0 medium specialised oxide 1.94 / 2.78, its generic path 2.23 / 2.67, OMAT-0 small oxide 1.38 / 1.97, MP-0 medium oxide 0.74 / 2.18, MP-0b3 1.11 / 1.13, MPA-0 1.48 / 1.20, MPtrj 1.38 / 1.01, MH-1 crystals 0.94 / 0.78 (`matpes_r2scan` 0.87 / 0.77, `omol` organic 0.32 / 0.50), OMOL-0 organic 0.92 / 0.28 (cation doublet 0.28 / 0.38), OFF24-M 0.67 / 0.56, OFF23-M 0.39 / 0.66, OFF23-S 0.67 / 1.19, OFF23-L 0.62 / 1.47, OFF23b-M 1.07 / 1.63, MatPES PBE 0.75 / 1.16, r2SCAN 1.45 / 1.13: 19 runs, none failing. POLAR (FP32 SIMT GEMMs, no folds) is unaffected.
- S80 confirmation on the defaults themselves (library s78 = the S78 tree; no environment overrides): gates (`loup-s80g`) OMAT-0 medium generic oxide 2.01 / 2.95, specialised 1.72 / 2.88, MH-1 crystals 0.90 / 0.77, OMOL-0 organic 0.90 / 0.35, none failing; with the S80 lane groups (`loup-s83g`, library s81) 2.01 / 2.82, 1.70 / 2.92, MP-0 medium oxide 0.70 / 1.41. The OMAT-0 oxide SrTiO3_3x3x3_c1 stress row is the A100's thin margin: 2.6-3.0x in every run since S67 (2.97). LoupMD's error there is unchanged (generic default `dS` 3.23e-7 in `loup-s75g` and 3.24e-7 in `loup-s80g`); the ratio moved because the MACE float32 yardstick did (1.21e-7 in `loup-s75g`, 1.10e-7 in the later runs). Library ABBA against the HEAD-era build (s73c = `ead50901`, its own wrapper; `loup-s80a`, 2 rounds), which adds S75-S78's MD loop: OFF23-S water216 `0.936`, OFF23-M water216 `0.945`, MH-1 NaCl216 `0.894`, MH-1 SrTiO3 `0.883`, OMAT-0 medium generic SrTiO3 `0.981`, specialised `0.995`.
- Status: DEFAULT (A100, cc 8.0).
- Sources: this file.

<a id="fp64-share-bound"></a>
#### fp64-share-bound: how much a faster FP64 unit (A100: 1/2 rate against 1/64 on the 5060 Ti) could save (local screen)
- Stage: S67 (15 November 2026), measurement; 5060 Ti `nsys`. Kernel set: every kernel whose `sm_120` SASS contains a float64 instruction (`DADD` / `DMUL` / `DFMA` / `DSETP` / `DMNMX` / F64 conversions; 63 functions, `.tmp_o/fp64_sass.sh`); each matched kernel's whole time counted (`.tmp_o/fp64_share.py`), so the share is a ceiling for any FP64 speedup. A first version matched kernels by name and both missed `first_bwd_edge` / `assemble_forces` / `gprod_ro1_fused` / `ro_mlp` / `sc0` / `sc1` and wrongly included `first_fwd` (no FP64 instruction); the figures below replace it.
- Ceiling, share of the summed kernel time per MD step: OFF24-M water 948 of 10,129 us (9.4%; `first_bwd_edge` 528, `gprod_ro1_fused` 229), MH-1 SrTiO3 1,654 of 38,165 (4.3%; `gprod_ro1_fused` 947, `first_bwd_edge` 572), MP-0 medium SrTiO3 793 of 8,797 (9.0%), POLAR-1-M NbCl5 1,977 of 25,849 (7.6%; `sf_kernel_tiled` 1,000, `grad_pass` 439, `feat_pass` 224).
- Instruction mix of the two big generic carriers (static `sm_120` SASS): `first_bwd_edge` 6-14 FP64 of 1,456-2,176 instructions, `gprod_ro1_fused` 10 of 1,192 (0.3-0.9%), all in the per-atom epilogues (force / energy sums), none in the edge or channel loops; POLAR's `sf_kernel_tiled` / `feat_pass` fold float32 partial sums into double once per 1,024-atom chunk or k tile. So the saving from faster FP64 is well below the ceiling, and an FP64 inner-loop rewrite (DMMA) has nothing to accelerate.
- A100 (S70 session, job 5005454, library s67; `sm_80` SASS gives the same 41-kernel FP64 set as `sm_120`, `.tmp_o/alex64/fp64_list.sh`): whole-kernel ceilings MH-1 SrTiO3 5.5%, NaCl216 4.3%, POLAR-1-M NbCl5 4.7%, OMOL-0 water216 1.0%, MPtrj 6.5%, OFF23-L water216 7.7%, MP-0 medium SrTiO3 9.6%, OMAT-0 medium 9.5-10.3%, OFF24-M water 12.1%, OFF23-M water216 19.4%; the last two above the 5060 Ti's 9.4% because the one-thread-per-atom neighbour kernels (`count_neighbors_scalar` / `fill_neighbors_scalar`, which hold FP64 instructions for the positions but are integer / float32-bound) run on the A100 where the 5060 Ti uses the lane-group kernels (121 of 213 us on water216; see S70 `nb-groups-a100`). The big generic carriers' FP64 fraction is unchanged (static SASS). Status: CLOSED as a lever (no FP64 rewrite can save more than the sparse epilogue sums; the A100's 1/2-rate FP64 already makes them cheap).
- Sources: this file.

<a id="gemm-autotune"></a>
#### gemm-autotune: per-shape GEMM autotune
- Switch: `sgemm_rm`; `LOUP_DEBUG_GEMM=1` prints every choice.
- What: up to 32 cuBLASLt heuristics, 3 hybrid tiles and the own SGEMM timed per shape in an uncaptured pass; the fork is disabled while timing. A winner within 3% of the runner-up is used but not persisted (review F4).
- Status: DEFAULT. Measured: not recorded alone. Sources: [§3.1 #11][s31], [§3.2 F4][s32].

<a id="gemm-cold-l2"></a>
#### gemm-cold-l2: selective cold-L2 timing
- Stage: S3 (item 18).
- What: operands larger than half the L2 are timed with a flushed L2, because they stream from DRAM in the force pass.
- Status: DEFAULT.
- Measured: Ada `lin1_fwd` group 672 -> 575 us (the 64 x 32 hybrid tile won hot and ran ~2x slower in the pass).
- Sources: [§3.1 #18][s31].

<a id="gemm-cold-l2-all"></a>
#### gemm-cold-l2-all: every GEMM timed cold
- Status: REJECTED. Measured: Ada `NbCl5` +2.9%. Sources: [§3.3][s33].

<a id="gemm-no-split-k"></a>
#### gemm-no-split-k: no split-K cuBLASLt algorithms
- Switch: `CUBLASLT_MATMUL_PREF_REDUCTION_SCHEME_MASK = NONE` (plan cache `LOUPPLN3` at the time).
- Stage: S3 (item 22).
- Status: DEFAULT.
- Measured: their captured per-launch workspace memsets left the 5060 Ti idle ~120 us per step; GPU idle inside a step is now ~20 us.
- Why: also order-deterministic; K <= 384, so split-K has nothing to gain.
- Sources: [§3.1 #22][s31], [§2][s2].

<a id="gemm-plan-cache"></a>
#### gemm-plan-cache: persistent GEMM plan cache
- Switch: `~/.cache/loupmd/plans_<gpu>_sm<cc>_lt<ver>_hyb<0|1>_<library hash>.bin`; `LOUP_CACHE_DIR`, `LOUP_RETUNE`.
- Stage: S3 (item 16); S6: library FNV hash in the name and the 3% persistence rule (review F4).
- Status: DEFAULT.
- Measured: cold-start `evaluate` 1.3 -> 0.21 s (5060 Ti), 0.76 -> 0.05 s (Ada).
- Sources: [§3.1 #16][s31], [§3.2 F4][s32].

<a id="gemm-own-sgemm"></a>
#### gemm-own-sgemm: own SIMT SGEMM
- Switch: `src/sgemm.cu`, `loup::sgemm128`; plan field `use_own` (cache `LOUPPLN4`).
- Stage: S5 (item 30).
- What: 128 x 128 x 16 block tiles, 256 threads with 8 x 8 outputs, 3-stage `cp.async` pipeline, 126 registers, 48 KB shared memory, 2 blocks (16 warps) per SM where cuBLAS' SIMT kernels run 8 warps at 200-210 registers. Transposed weights get a [K, N] copy. Bit-identical to `cublasSgemm` on every tested shape.
- Status: DEFAULT (an autotune candidate; picked for the large `lin1` / `lin1^T` / `compose0` forward products on the 5060 Ti).
- Measured: cold microbenchmark (5060 Ti) `lin1` l = 1 / 2 / 3 forward 132 / 196 / 181 us (cuBLASLt's pick 136 / 207 / 175); MD first version vs item 29: 5060 Ti -1.6% / -2.0% (`NbCl5`), -0.6% / -0.7% (`SrTiO3`), Ada +0.8% / +0.2% (A), -0.2% / -0.3% (B); `cp.async` vs first version: 5060 Ti -1.4% / -1.3%, -0.1% / -0.4%; Ada +1.1% / +0.5% (A), -0.3% / +0.0% (B).
- Sources: [§3.1 #30][s31].

<a id="gemm-own-n192"></a>
#### gemm-own-n192: 128 x 64 tiles for N = 192
- Stage: S5.
- Status: DEFAULT (an MD tie, kept).
- Measured: 111 registers, 36 KB; the 5060 Ti autotune picks it for all seven `SrTiO3` `compose0` backward products (297 -> 248 us); MD 5060 Ti `NbCl5` +0.5% / +0.0%, `SrTiO3` -0.1% / -0.4%; Ada +1.2% / +1.0% (A), +0.0% / -0.2% (B).
- Sources: [§3.1 #30][s31].

<a id="gemm-own-n144"></a>
#### gemm-own-n144: partial-`N` `128 x 64` tiles in `loup::sgemm128`
- Stage: S16 (14 November 2026).
- What: extended `loup::sgemm128` (`src/sgemm.cu`) to launch `sgemm128_kernel<4, false>` (`128 x 64` tiles, `REG:105, STACK:0`) whenever `(N % 128) != 0 && (N % 128) <= 64` (such as `N = 144` padded `K0` layers), avoiding nearly half-empty `128 x 128` tiles.
- Status: DEFAULT (5060 Ti only).
- Measured (5060 Ti): in `POLAR-1-M` `NbCl5` `prof_k`, partial-`N` `sgemm128` cut that shape from `170.7` to `76.6 us`. (A paired `L2/4` cold-L2 threshold test in `d906545` was reverted in `0a240ec` after mixed `OMAT-0-S` ordering.)
- Sources: this file; commits `d906545`, `0a240ec`.

<a id="gemm-own-sgemm64"></a>
#### gemm-own-sgemm64: `64 x 64 x 16` `cp.async` SIMT SGEMM for `M <= 1600`
- Switch: `loup::sgemm64` (`sgemm64_kernel<FULL_N>` in `src/sgemm.cu`), autotuned when `is_sm120 && M <= 1600`, stored in `DiskPlan::use_own == 2`.
- Stage: S16 (14 November 2026).
- What: on small cells (`N = 216..648`, `M <= 1512`), `128 x 128` tiles launched only 2–12 blocks on 36 SMs and cuBLASLt fell back to `magma_sgemmEx_kernel` (e.g. `124 us` on `POLAR-1-S` `M = 216, N = 144, K = 2048`). `sgemm64_kernel` uses `128` threads (`8 x 4` outputs/thread, `REG:103, STACK:0, SHARED:25600`), giving `4x` more threadblocks across SMs. Unscoped `sgemm64` won hot-L2 autotuning on `M = 1944..5832` (`nbcl5`) where cold `A` streams hurt (`+0.68%` `POLAR-1-M`, `+0.25%` `MH-1`), and Ada was not tested, so it is scoped to `sm_120` and `M <= 1600`.
- Status: DEFAULT (5060 Ti only).
- Measured (5060 Ti, fresh plans): `POLAR-1-S` `NaCl216` `1.8458 -> 1.6105 ms` (`b/a = 0.8726`), `POLAR-1-M` `NaCl216` `4.2996 -> 3.6069` (`0.8389`), `POLAR-1-L` `NaCl216` `8.2416 -> 7.2164` (`0.8756`), `MH-1` `NaCl216` `1.7089 -> 1.5700` (`0.9187`), `OFF23-M` `water216` `1.3912 -> 1.3047` (`0.9378`), `MH-1` `NbCl5` tie (`12.5860 -> 12.5888`, `1.0002`). Gates pass on `POLAR-1-S/M`, `MH-1` (crystals + organic), `OMAT-0-S/M`, `OFF23-M`; `POLAR-1-L` `cmp_libs` `dF = 2.07e-7` (`nacl216`); pytest suite passes.
- Sources: this file.

<a id="gemm-own-sgemm32"></a>
#### gemm-own-sgemm32: `32 x 32 x 16` `cp.async` SIMT SGEMM + deterministic split-K for `sm_120` `M <= 1600`
- Switch: `loup::sgemm32` (`sgemm32_kernel<FULL_N>` + `splitk_reduce_kernel` in `src/sgemm.cu`), autotuned for `split_k` in `{1, 2, 4}` when `is_sm120 && M <= 1600` (with `K >= 64 * sk` and `sk * M * N * 4 <= cublas_ws_bytes`), stored in `DiskPlan::use_own` in `{3, 4, 5}`.
- Stage: S17 (14 November 2026).
- What: even with `sgemm64`, `M = 216, N = 8..256` GEMMs in `POLAR-1-S/M/L` and `MH-1` `NaCl216` (`63–71%` of GPU kernel time) launched only `4..16` blocks on 36 SMs (`4` `M`-tiles x `1..4` `N`-tiles), leaving 55–89% of SMs idle (`M=216, N=144, K=2048` took `53.2 us`; `N=16, K=512` took `14.7 us`). `32 x 32` tiles + deterministic split-K (`ws_p` per-stream 4 MB workspace + in-order `splitk_reduce_kernel`, zero atomics/memsets) cut those to `20.8 us` / `7.6 us`.
- Status: DEFAULT (5060 Ti only).
- Measured (5060 Ti, fresh plans): `POLAR-1-S` `NaCl216` `1.6451 -> 1.4958 ms` (`b/a = 0.9092`), `POLAR-1-M` `NaCl216` `3.6966 -> 3.4591` (`0.9357`), `POLAR-1-L` `NaCl216` `7.2813 -> 6.8949` (`0.9469`), `MH-1` `NaCl216` `1.6097 -> 1.5264` (`0.9483`), `OFF23-M` `water216` tie (`1.3436 -> 1.3520`, `1.0063`), `MH-1` `NbCl5` tie (`12.5460 -> 12.5867`, `1.0032`). Cached 3x gates pass on `POLAR-1-S/M`, `MH-1` (crystals + organic), `OMAT-0-S/M`, `OFF23-M`; `cmp_libs` `dF <= 3.1e-6` (`POLAR-1-L` `nacl216` `dF = 1.13e-6` vs pre-S17); pytest suite passes (`67 passed`).
- S88 falsifier (16 November 2026, 5060 Ti, reverted): the split-K reduction inside the GEMM, so a split GEMM is one graph node instead of two (`POLAR-1-M` `NaCl216` launches 19.6 `splitk_reduce_kernel` per step): each split block writes its slice, counts on a per-tile word behind the stream's workspace, and the last block sums the slices in slice order (the same sums) and resets the word. Library ABBA on shared plans, 3 rounds, against S86 (with S87's POLAR changes in the same build): `POLAR-1-M` `NaCl216` `1.002`, `POLAR-1-S` `1.003`, `POLAR-1-L` `1.002`, `MH-1` `NaCl216` `1.012` (`1.016` / `1.008`), and `OFF23-S` water216 `1.014` (`1.006` / `1.023`), which runs no split GEMM, so the longer `sgemm32_kernel` presumably costs time even unsplit (not profiled). Gates passed (`POLAR-1-S` / `-M` / `-L` 0.57 / 0.66, 2.14 / 1.13, 2.07 / 0.92; MH-1 crystals 0.85 / 0.29).
- Sources: this file.

<a id="gemm-own-narrow-n"></a>
#### gemm-own-narrow-n: narrow-`N` `sgemm64` / `sgemm32` above `M = 1600` (`sm_120`)
- Switch: `src/engine.cu` (`sgemm64` when `M <= 1600 || N <= 64 || (M <= 2500 && N <= 160)`; `sgemm32` when `M <= 1600 || N <= 32 || (M <= 2500 && N <= 160)`).
- Stage: S18 (14 November 2026).
- What: on `NbCl5` (`M = 1944..5832`), `sgemm64` / `sgemm32` were blocked above `M = 1600` to avoid cold-L2 `A` re-reads on `N >= 256`. On `N <= 64` (`sgemm64`) and `N <= 32` (`sgemm32`), `grid.y == 1` so `A` is read only once regardless of `M`, and on `M <= 2500 && N <= 160` (`1944 x 128..144 x 2048`), `A <= 16 MB` stays resident in the 32 MB L2 while `sgemm128` under-occupied 36 SMs (`1944x144x2048` `150.5 -> 116.7 us`, `1944x8x1536` `65.5 -> 24.6 us`).
- Status: DEFAULT (5060 Ti only).
- Measured (5060 Ti, fresh plans): `POLAR-1-M` `NbCl5` `24.6629 -> 24.4787 ms` (`b/a = 0.9925`), `MH-1` `NbCl5` `12.6237 -> 12.5065` (`0.9907`), `OFF23-M` `water` tie (`7.4110 -> 7.4174`, `1.0009`), `OMAT-0-S` `SrTiO3` tie (`4.7100 -> 4.7106`, `1.0001`). Cached 3x gates pass across `POLAR-1-S/M`, `MH-1`, `OMAT-0-S`, `OFF23-M`; on `M > 1600` narrow-`N` paths (`LOUP_DEBUG_GEMM` confirmed `own32_1`/`own64_0` at `M = 1728`): `576`-atom `NbCl5` `POLAR-1-M` full force + corrected-FD-stress 3x gate passes (`dF = 0.66x`, `dS = 0.00x`), `1,944`-atom `NbCl5` `MH-1` full 3x gate passes (`dF = 0.31x`, `dS = 1.14x`), and `1,944`-atom `NbCl5` `POLAR-1-M` force-only 3x check passes (`dF = 0.47x`, no stress check); `pytest` passes (`67 passed`).
- Sources: this file.

<a id="gemm-own-raster"></a>
#### gemm-own-raster: `N`-tile-fastest rasterisation of the own SGEMMs
- Switch: `src/sgemm.cu` (`sgemm64_kernel`, `sgemm32_kernel`: `n0` from `blockIdx.x`, `m0` from `blockIdx.y`; grids `(N tiles, M tiles[, split_k])`; both already run only on `sm_120`). `sgemm128_kernel<TN, FULL_N, N_FASTEST>`, chosen host-side by `sgemm128(..., h->is_sm120, ...)`: other GPUs launch the `N_FASTEST = false` instantiation with the original grid, whose `sm_89` / `sm_90` SASS is instruction-for-instruction identical to the pre-S20 kernel (all four `TN` / `FULL_N` variants checked), since the change was measured on the 5060 Ti only. Both orders give bit-identical outputs (5 shapes checked).
- Stage: S20 (14 November 2026).
- What: `ncu` on `MH-1` `NbCl5` put own `sgemm128` at 68-73% FMA-pipe activity versus 61% for cuBLASLt's `cutlass_80_simt_sgemm_256x128`, yet the autotune still chose cuBLASLt for the large cold-`A` products. A standalone comparison found the cause: with `M` tiles fastest, every `N` tile column re-read the whole `A` (`13608 x 512` = 28 MB, cold, against a 32 MB L2), so own `sgemm128` ran `13608x512x512` cold at 529 us (13.5 TFLOP/s) against cuBLASLt's 402 us (17.8). Making `N` the fastest grid dimension, so the `N` tiles of one `A` row block are issued together, cut this to 425 us (16.8 TFLOP/s); `9720x512x512` cold 354 -> 320 us; `sgemm64` cold 906 -> 443 / 560 -> 318 us. CUDA does not guarantee block issue order, so the single read of `A` is an observed effect on this GPU and driver, not a guarantee; the change is kept on these measurements. Hot shapes unchanged (same per-tile work). Every output is computed by the same thread with the same `fmaf` order, so results are unchanged for a given plan.
- Status: DEFAULT (5060 Ti only).
- Measured (5060 Ti, fresh plans, ABBA vs S19): `MH-1` `NbCl5` `12.516 -> 12.224 ms` (`0.9767`), `POLAR-1-M` `NbCl5` `24.504 -> 24.190` (`0.9872`), `OMAT-0-M` `SrTiO3` `8.175 -> 8.084` (`0.9889`), `OFF23-M` water `7.406 -> 7.354` (`0.9930`), `OMAT-0-S` `SrTiO3` tie (`0.9984`), `POLAR-1-S` `NaCl216` tie (`1.0022`). The `sm_120`-only template gate is a tie against the ungated S20 build (`MH-1` `NbCl5` `1.0002`). Cached 3x gates pass (`POLAR-1-S/M`, `MH-1` crystals, `OMAT-0-S/M` oxide, `OFF23-M` organic); `pytest` `67 passed`. With the cold-`A` penalty gone, `sgemm64` was also offered for every shape (`gemm-own-sgemm64-unscoped`); ABBA against the rasterised build (above 1 = slower): `MH-1` `NbCl5` `1.0082` and `POLAR-1-M` `NbCl5` `1.0115` slower, `POLAR-1-S` `1.0069` slower, `OFF23-M` `1.0000` tie, `OMAT-0-S` `0.9918` and `OMAT-0-M` `0.9964` faster: mixed, rejected (the S16/S18 scopes stay).
- Sources: this file.

<a id="gemm-own-n96"></a>
#### gemm-own-n96: 128 x 96 tiles for `N = 96`
- Switch: `src/sgemm.cu` `sgemm96_kernel`, launched by `sgemm128_launch<true>` (the `sm_120` / `n_fastest` instantiation) when `N == 96`; other widths and other GPUs keep their kernels (`sm_89` / `sm_90` SASS of every existing kernel in `sgemm.cu` instruction-identical to S37, anonymous-namespace names normalised). It is the own candidate of the GEMM autotune, so a shape where it loses keeps its previous pick.
- Stage: S38 (14 November 2026).
- What: fresh `nsys` (`OFF23-S` water, `C = 96`): `N = 96` products ran `sgemm128_kernel<8, false>` (grid `1 x M/128`, a 128-wide tile over 96 columns) at 330 us / step, the rest on 3xTF32 `64 x 32` hybrid tiles. The new kernel keeps `sgemm128`'s A path and 3-stage `cp.async` pipeline; B is a `16 x 96` tile (384 16-byte chunks, two copies for the first 128 threads), each thread computes `8 x 6` outputs (a `float4` and a `float2` B fragment per k), 128 registers, no spill, 43 KB shared memory (2 blocks / SM). Same in-order `fmaf` chain per output as `sgemm128_kernel`, so outputs are bit-identical.
- Status: DEFAULT (5060 Ti only).
- Measured (5060 Ti): standalone, random data, median of 3 x 31 (us, current / new / cuBLAS): `25920 x 96 x 96` 51.3 / 42.2 / 71.4, `x 128` 64.9 / 52.0 / 91.9, `36288 x 96 x 96` 66.6 / 53.3 / 99.0, `x 128` 87.8 / 69.6 / 125.6, `17280 x 96 x 128` 44.8 / 36.4, `24192 x 96 x 128` 64.4 / 53.8, `15552 x 96 x 96` 35.1 / 28.8, `12096 x 96 x 128` 34.7 / 28.4, `8640 x 96 x 96` 20.7 / 17.3 (`0.79-0.84`, 0 of all outputs differ). The autotune now takes the own kernel for most `N = 96` shapes (e.g. `24192 x 96 x 128`, previously 3xTF32 `hyb2` at 60.2 us, now `own0` at 47.9 us); the 5,184-row products stay on `hyb2`. Final binary, fresh-plan ABBA: `OFF23-S` water `3.0877 -> 3.0463 ms` (`0.9866`) and reversed `3.1014 -> 3.0264` (`0.9758`). An earlier build (dispatch on `N % 96 == 0 && N % 128 > 64`) measured `0.9797` / `0.9867` on `OFF23-S` water and a tie on `OMAT-0-S` `SrTiO3` (`1.0108` / `0.9971`; no `N = 96` products); the dispatch was then narrowed to the measured `N = 96`. `cmp_libs` `OFF23-S` water `dE 1.4e-4` on `-3.6e6 eV`, `dF 1.0e-5`; gates `OFF23-S` organic 8 / 8, `OMAT-0-S` oxide 6 / 6; `pytest` 67 passed.
- Sources: this file.
- S39 extension to other padded widths (rejected by its falsifier). Fresh traces: OFF23-L water spends ~2.55 ms / step in `N = 224` own GEMMs (two 128-wide tiles, 12.5% padding), MH-1 `SrTiO3` ~3.5 ms / step in `N = 208` (19%). A `128 x 112` tile (`8 x 7` outputs per thread: `float4` + `float2` + scalar B fragments; 128 registers, no spill, 46 KB) gives two exact tiles at 224 and 7% padding at 208. Standalone, random data, median of 3 x 31 (us, current / 112 / cuBLAS): `24192 x 224 x 128` 120.2 / 114.8 / 131.2, `17280 x 224 x 128` 87.4 / 83.3, `25920 x 224 x 224` 216.1 / 202.9, `15552 x 224 x 224` 126.4 / 120.1, `15552 x 224 x 1120` 588.5 / 546.6, `35000 x 208 x 512` 619.7 / 578.9 / 578.4, `25000 x 208 x 512` 431.2 / 407.7, `15000 x 208 x 512` 276.8 / 261.8, `5000 x 208 x 2048` 455.0 / 427.1 / 393.9: `0.929-0.955`, bit-identical. Below the 10% stop rule (at most ~0.5% of either step): the 7-wide fragment's extra scalar shared-memory load per k and the lower FMA-to-load ratio take most of the removed padding. Not built.
<a id="gemm-sgemm-variants"></a>
#### gemm-sgemm-variants: other own-SGEMM shapes and pipelines
- Stage: S5.
- Status: REJECTED.
- Measured (5060 Ti): `cp.async` 4 stages with BK = 8: 1.2-1.5x slower than BK = 16; register-staged with BK = 8 or 1 block per SM: 5-30% slower; 64 x 128 and 128 x 64 tiles as extra candidates: picked in isolation, MD `NbCl5` +1.6% / +0.8%; 64 x 128 for every N = 128 product (cold microbenchmark 7-8% faster): MD `NbCl5` +1.7% / +1.8%, `SrTiO3` +0.5% / +0.8%, Ada +1.1% / +0.2% (A).
- Why: isolated cold timings of tile shapes do not carry over to the concurrent GEMM groups.
- Sources: [§3.3][s33].

<a id="gemm-issue-rate"></a>
#### gemm-issue-rate: own-SGEMM issue rate on `sm_120` (owner-chosen direction)
- Stage: S53 (14 November 2026), 5060 Ti only; standalone harness `.tmp_o/sg_mb.cu` (includes `src/sgemm.cu`; random data, median of 3 x 31 launches, output hash for bit-identity).
- Baseline (hot L2; cold L2 within 2%): `sgemm128` `13608 x 512 x 512` 474.6 us (15.0 TFLOP/s, 5.94 waves), `5832 x 512 x 512` 236.2 us (12.9, 2.56 waves: the last wave part-full), `25000 x 208 x 512` 436.4 us (12.2); `sgemm64` `648 x 512 x 512` 36.6 us (9.3), `216 x 512 x 512` 18.7 us (6.0). `ncu` of `sgemm128` `13608 x 512 x 512`: 128 registers, 2 blocks / SM (3.87 active warps per scheduler), issue slots busy 72.6%, no eligible warp in 26.3% of active cycles (2.50 eligible warps per scheduler on average); 125.8 M warp instructions, of which 112.5 M FFMA (89.4%) and 7.3 M `LDS` (5.8%); at 100% issue the kernel would need 873 k cycles per scheduler instead of 1,185 k.
- Limiter: PC sampling (41,660 samples): selected 19.8%, not selected 45.0%, dispatch stall 18.4% (11.5 points on FFMAs), barrier 5.6%, short scoreboard 3.0%, MIO throttle 3.0%. Joining the samples with the `cuobjdump` SASS (for the `.reuse` flags): the dispatch samples of an FFMA follow the register-file reads of the FFMA before it, not register banks: after an FFMA with 1 / 2 / 3 register-file source reads (operands not from the reuse cache), 2.2 / 3.6 / 8.8 dispatch samples; bank models `reg % 2` and `reg % 4` show no effect within a read count. 227 of the 1,024 FFMAs read all three sources from the register file (by the source order, one row change in eight loses both operands; ptxas's schedule adds the rest).
- `sgemm64` (`648 x 512 x 512`, the `POLAR-1-M` `NaCl216` shape), same method: 0.61 waves (88 blocks for 144 slots), 101 registers, 2.44 active warps per scheduler, no eligible warp in 32.0% of active cycles. PC sampling (2,477 samples): FFMA stalls are mostly short scoreboard (11.3% of samples: the `LDS` latency with too few warps to hide it) and dispatch (8.1%); after an FFMA with 1 / 2 / 3 register-file reads, 0.15 / 0.30 / 0.62 dispatch samples (155 of 512 FFMAs read three). Its limiter is fill and latency, not the reuse effect that limits `sgemm128`.
- Tried: (1) serpentine column order (odd rows reversed) in `sgemm128_kernel` and `sgemm64_kernel`, so a row change keeps the B operand: outputs bit-identical, but ptxas reschedules (no-reuse FFMAs 227 -> 185 in `sgemm128<8>`, 155 -> 123 in `sgemm64`) and `sgemm128` is 3-5% slower on every large shape (`13608 x 512 x 512` 476 -> 500 / 504 us, two interleaved rounds); `sgemm64` unchanged within noise. Reverted. (2) Packed FMA: `fma.rn.f32x2` compiles on `sm_120` but ptxas lowers it to two `FFMA`s; native `FFMA2` is emitted for `sm_100a` only, so the instruction count cannot be halved on this GPU.
- Status: REJECTED (stop rule: no variant within reach of the 10% kernel bar). The remaining levers need control nvcc does not give (the FFMA schedule and reuse flags), or more warps (a smaller thread tile, more `LDS` per FMA) or larger k tiles (1 block per SM), both already rejected in `gemm-sgemm-variants`. cuBLAS's own SIMT kernels on the same products run at the same level (`ncu` S53, `POLAR-1-M` `NbCl5`: `cutlass_80_simt_sgemm_256x128` issue 76-79%, FMA pipe 70-75%; own `sgemm128` 71-73% / 72-75%).
- Sources: this file.

<a id="gemm-pretransposed"></a>
#### gemm-pretransposed: pre-transposed forward weights (old idea 1)
- Status: REJECTED. Measured: 5060 Ti tie, Ada +1.0% / +0.3%. Sources: [§3.3][s33].

<a id="gemm-grouped-species"></a>
#### gemm-grouped-species: grouped species GEMM (T4)
- Switch: `fm_tf32x3_species_rr_64x64` for `compose0_fwd` + `skip16`.
- Status: REJECTED.
- Measured: 5060 Ti +1.7% / +0.8%; the grouped launch is slower than the forked per-species GEMMs.
- Sources: [§3.3][s33].

<a id="gemm-row-chunked"></a>
#### gemm-row-chunked: row-chunked hybrid GEMM for cold operands
- What: the 64-wide hybrid tiles launched per quarter-L2 row chunk so the second column tile re-reads A from L2.
- Status: REJECTED. Measured: never chosen by the cold autotune on either GPU (Ada `lin1` forward stays on cuBLASLt at 148 / 228 / 209 us). Sources: [§3.3][s33].

<a id="gemm-group-policy"></a>
#### gemm-group-policy: own-SGEMM policy per fork group, timed in context
- Stage: S5.
- What: each fork group timed whole at a second uncaptured pass under three policies (as autotuned / own wherever eligible / never own); the fastest kept per group signature.
- Status: REJECTED.
- Measured: group timings differ from the per-product picks (`SrTiO3` `lin1^T` group 637 -> 552 us with own everywhere, warm L2), but MD 5060 Ti `NbCl5` -0.4% to -0.8%, `SrTiO3` +0.1% / +0.2%, Ada tie (stream-timed and graph-timed variants).
- Why: not worth the collection / replay machinery.
- Sources: [§3.3][s33].

<a id="gemm-split-k-own"></a>
#### gemm-split-k-own: split-K own SGEMM for small systems
- Stage: S5.
- What: partials per K slice, the last block of a tile sums them in z order.
- Status: REJECTED.
- Measured: the isolated autotune cannot rank such products (every candidate 6-14 us, launch-bound); forcing split 2 / 4: 135-atom GEMM groups 123 -> 147 / 158 us (step 367 -> 392 / 409 us).
- Why: the per-GEMM floor in the graph is launch / completion latency, not the K pipeline.
- Sources: [§4.1 #3][s41].

<a id="gemm-grouped-launch"></a>
#### gemm-grouped-launch: one own-SGEMM launch per fork group of small products
- Stage: S5.
- What: products of a fork group collected and, when each has fewer tiles than SMs, issued as one launch over a problem table (64 x 64 tiles).
- Status: REJECTED.
- Measured: 135-atom GEMM groups 114 -> 101 us (step 355 -> 345 us, wall -3% to -5%, 5060 Ti); 320 atoms within noise; Ada 135 atoms +2%; the refactored kernel cost the benchmarks +1.2% / +0.9% (`NbCl5`), +0.3% / +0.2% (`SrTiO3`).
- Sources: [§4.1 #3][s41].

<a id="gemm-skip16-overlap"></a>
#### gemm-skip16-overlap: `skip16` GEMMs across the spline
- Status: REJECTED. Measured: not recorded. Sources: [§3.3][s33].

<a id="gemm-simt-for-lr"></a>
#### gemm-simt-for-lr: float32 SIMT GEMMs only for long-range models
- Switch: `loup_create` skips `HybCubin::init` when `GenericModel::has_lr()`; `LOUP_NO_HYBRID=1` does it for any model.
- Stage: S6 (13 November 2026).
- What: exclude tensor-core GEMM candidates that fail full-model POLAR gates. A three-term TF32 decomposition is not uniformly "4x float32 error": the omitted residual product and tensor-core accumulation depend on the operands. S71's positive-input probe identifies coherent downward bias; its propagation through the full model is being measured separately.
- Status: DEFAULT (scoped: long-range models).
- Measured: gate on the Ada with hybrid GEMMs: POLAR-1-S NaCl stress ratios 5.16 / 3.43, NaNbO3_c0 NaN; POLAR-1-L NaCl_c1 stress 3.52, NaNbO3 force 3.13, stress 6.27 / 3.63. With SIMT GEMMs (`LOUP_NO_HYBRID=1`, then the scoped build): every checked configuration in the original crystal gate passes on both GPUs (Ada worst 0.99 / 1.14 / 2.69 for S / M / L; 5060 Ti 1.30 / 0.97 / 1.16). Cost, separate `bench_family.py` runs (not an A/B): 5060 Ti NaCl 216 atoms +1.8% to +3.0%, 1,728 atoms +0.0% to +0.4%; Ada NaCl 1,728 atoms +5.4% / +7.2% / +6.9% (S / M / L), POLAR-1-M `NbCl5` +5.1% (the Ada's earlier run also predates pol-fixed-point-phase).
- Why: correctness first; the other families' gates pass with the hybrid GEMMs on both GPUs.
- A100 re-test (S70 session, NHR Alex A100-SXM4-40GB, job 5005454, library s67; `LOUP_LR_HYBRID=1`): the existing hybrid and true 3xTF32 implementations fail POLAR's gates. The default POLAR-M true-3xTF32 rows pass, but forced conv-forward variants fail. [Failure ratios and historical FastMACE speed comparison](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/historical-a100-comparison.json) preserve the source jobs, matched cells, different A100 capacities, and measured-versus-inferred distinction. These are failures of those implementations, not a proof that every tensor-core implementation must fail.
- Core-only experiment (S71, 5060 Ti; every eligible core GEMM forced onto the cubin, long-range block FP32): S passes (worst 1.80 hybrid / 1.75 true 3xTF32); M hybrid passes (worst force 2.53), M true 3xTF32 fails (NaNbO3_c1 force 3.20 / 3.27 / 3.24); L fails both (NaNbO3_c1 stress 6.57 / 5.68, CPU references). REJECTED locally; test switch and separate cache removed. This shows that perturbations introduced in the core can cause a final-output failure even with FP32 long-range GEMMs. It does not locate the later amplification or prove a GPU-independent result.
- FastMACE comparison: its A100 POLAR adoption jobs (`results/off-polar-alex-20261106`, 4936581 / 4937921-4) gated **NaCl and NbCl5 only**, with `GATE_STRUCTS="NaCl NbCl5"`. Its documented NaNbO3 runaway concerns **POLAR-1-S**, not every POLAR size; NaTaO3 is separately problematic. LoupMD's NaNbO3 failures cannot be dismissed as that same issue without matching evidence.
- The gates are not directly comparable. FastMACE pools each structure's worst production error against its worst float32 yardstick over six configurations; LoupMD gates each configuration separately. Cells, strain draws and rattle amplitudes also differ (FastMACE NbCl5 1,944 atoms versus LoupMD 216; rattle 0.05 A versus LoupMD c1 0.08 A). Re-scoring the printed rows of the original A100 log (job 5005454) with pooled bounds still fails S NaCl stress (3.43 true 3xTF32 / 3.60 hybrid) and L (true 3xTF32 NbCl5 5.08; hybrid NaCl 3.21). Thus pooling alone does not explain the discrepancy.
- Reference protocols also differ: FastMACE uses corrected autograd stress with a fixed-reciprocal-set finite-difference self-check; LoupMD's original gate used live-set finite differences for the float64 stress and still uses uncorrected autograd differences for its float32 yardstick. S71 confirmed cutoff crossings in two new wide-screen configurations and corrected its finite differences ([details below](#gate-polar-fixed-kset)). Historical errors on different cells cannot establish equal arithmetic accuracy. A same-input, same-reference comparison is required; the 3x rule and absolute floors remain unchanged.
- Arithmetic coverage differs too: FastMACE's `rewrites/precision.py` routes `BlockLinear`, `ResidualBlockLinear`, `GatedRows`, `SpeciesSkip` and `FirstInteractionReassociation`; it does not globally convert every `nn.Linear`/matrix multiply. The recorded POLAR-M candidate has `tf32_matmul="none"` alongside `tf32x3_gemms`. LoupMD's `LOUP_FORCE_TC=1` instead forces every eligible GEMM through its cubin, including long-range MLP GEMMs. Calling these the same whole-model tensor-core path was incorrect.
- Sources: [§5.4][s54], [§5.2][s5].

<a id="gemm-tc-rounded-polar"></a>
#### gemm-tc-rounded-polar: rounded splits and isolated accumulation
- Scope: experimental cubins only; no shipped cubin replacement and no POLAR tensor-core default. Neither three-product approximation is bitwise FP32. Build-time define `LOUP_TC_SPLIT_RN=1` rounds the high part to nearest, ties away; `LOUP_TC_ACC_RN=1` isolates the high and cross products before FP32 combination. Both experimental defines default to 0, preserving the old operator.
- The tested full-range variant uses **all** of `-DLOUP_TC_MATH=0 -DLOUP_TC_SPLIT_RN=1 -DLOUP_TC_ACC_RN=1 -DLOUP_TC_TILESET=3 -DLOUP_TC_BETA=0`. For math 0, isolated accumulation belongs to the RN operator; setting `LOUP_TC_ACC_RN` alone does not select it. Runtime selection is `LOUP_LR_HYBRID=1` plus `LOUP_HYBRID_CUBIN=/absolute/path/to/the/cubin`; build-time defines are not environment-variable switches.
- Mechanism: the old truncated high part leaves a residual with the operand's sign. Dropping residual x residual therefore introduces a coherent signed omission for same-sign products. Nearest splitting reduces the residual bound and removes that fixed-sign relation, but does not guarantee unbiased errors for correlated inputs. Keeping the smaller cross product separate also avoids repeatedly adding it directly to the large MMA accumulator.
- FastMACE comparison (source read 15 November 2026, the local FastMACE checkout): FastMACE ships **no** GEMM accuracy correction beyond LoupMD's. On compute capability 8.0 its `tf32x3_gemms` products run in CUTLASS (`fastmace/kernels/triton/tf32x3_gemm.py`, `CUTLASS_CAPABILITIES = ((8, 0), (9, 0))`): `OpMultiplyAddFastF32` with the truncated big part (the source LoupMD's `gemm_tc_3x` cubin copies), and since 11 November the TF32 + FP16 hybrid (`HYBRID_GPUS`: A100-SXM4-80GB, H200; LoupMD's `hybrid_f16.h` is the same file). Its rounded split and "B1" (W rounded to 22 bits, a's high part rounded) exist only in the OMAT-0 fused-forward kernel lab: bias slope on the A100 `-1.05e-6` (mask) / `-5.2e-7` (round) / `-6.6e-7` (B1), CUTLASS 3xTF32 `-1.6e-7` to `-1.9e-7` at K = 128; neither adopted because the gate passed (`results/research-answers-20261105`, idea 20; `fused_forward.TC_SPLIT = "mask"`). Triton's `tf32x3` (used where CUTLASS is not, e.g. the RTX 5060 Ti) rounds both parts with `cvt.rna.tf32` and sums the cross products from a zero accumulator before adding the big product (Triton 3.8 `F32DotTC.cpp`, `emuTF32` for capability >= 8.0), close to `3x_rnacc`. Scope safeguards that do exist: only atom-row GEMMs (block linears, gated rows, species skip, first-interaction products; edge radial networks and POLAR's field blocks and long-range part stay IEEE FP32; `E3NN_BLOCK_LINEAR_GPUS` is empty), products with K or N below 32 on IEEE, and fewer than 54 output tiles with K above 256 on cuBLAS IEEE. LoupMD's generic GEMMs are all atom-row too (`N` or `N * dimL(l)` rows), so the core-only experiment already matched that scope. FastMACE's POLAR passes therefore come from its gate protocol (see the comparison above), not from more accurate arithmetic; `3x_rnacc` is more accurate than any GEMM FastMACE runs on the A100.
- Distinguish the formats: `hyb` is TF32 high x high plus **scaled FP16** cross products, not pure 3xTF32. New `3x_rnacc` uses TF32 for all three products and avoids the hybrid's FP16-range restriction. Existing hybrid overflow disables the cubin: a later finite SIMT result is not a tensor-core pass.
- Targeted 5060 Ti POLAR-S results (five configurations selected from independent wide-screen failures; ratios to the same per-configuration float32 yardstick, limit 3):

  | Configuration | Old hybrid F / stress | Old 3xTF32 F / stress | New 3xTF32 RN + isolated accumulation F / stress |
  |---|---:|---:|---:|
  | Na2O_c0 | 0.988 / 5.857 | 0.346 / 6.528 | 0.249 / 1.828 |
  | NaNbCl6_c1 | 1.735 / 3.746 | 0.273 / 0.683 | 0.200 / 0.451 |
  | NaNbOCl4_Pbca_c2 | 2.111 / 3.098 | 0.272 / 0.508 | 0.411 / 0.230 |
  | NbCl2O_c0 | 4.850 / 1.691 | 0.413 / 0.661 | 0.247 / 0.289 |
  | NbCl2O_c1 | 5.866 / 1.294 | 0.359 / 0.425 | 0.408 / 0.260 |

- All five new rows pass energy, force and stress with tensor-core execution observed and no fallback. This is targeted evidence, not broad model qualification. For Na2O the old hybrid stress error is almost isotropic: maximum `4.6881e-6 eV/A^3`, trace/3 `4.6787e-6`; its non-isotropic remainder is only `2.93e-8`. Hybrid RN + isolated accumulation reduces that maximum to `1.2275e-6`. This measures downstream stress propagation, not which charge/SCF stage amplifies it.
- Microprobe (sm_120, M=2048, N=128, K=128, positive operands, double-precision dot reference): new full-range `3x_rnacc` mean signed error / sum|ab| `-2.377e-8`, RMS `5.605e-8`; pedantic cuBLAS FP32 mean `+4.458e-10`, RMS `1.537e-7`. Random-sign tests alone conceal coherent signed error; smaller RMS does not establish a universal accuracy bound.
- Exact-operand control on sm_120 removes split error entirely: inputs are quantized to TF32, so both low parts and every omitted low-low product are zero. At K=8, positive-dot `3x_rnacc` has normalized mean error `-2.310e-8`; 130,681 of 262,144 results are below the exact double sum, **none above**. Pedantic FP32 has mean `-1.646e-11` and balanced signs. Thus downward bias remains inside MMA accumulation, even with exact operands; software RN combination does not make the MMA itself correctly rounded. At K=128 its mean is `-2.381e-8`. [Exact-input diagnostic](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/exact-tf32-operands.log).
  [Standalone reproducer](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/gemm_bias_probe.cu): compile with `nvcc -O3 -std=c++17 -arch=sm_120 -DDIAGNOSTIC_TF32_INPUTS gemm_bias_probe.cu -lcublas -lcuda -o gemm_bias_probe`, then run `gemm_bias_probe 2048 128 8 /path/to/3x_rnacc_sm120.cubin` and K=128 **inside the shared GPU reservation**. Omit `DIAGNOSTIC_TF32_INPUTS` for the original unquantized-input probe. Builds are CPU work; execution is not.

- Historical local expanded screen: **90/90 candidate configurations pass E/F/stress** under the then-current fixed-step reference, with real tensor-core execution and no fallback or excluded configurations. Each model has 15 structures x 3 configurations. The structures are Na2O, NaCl, NaNbCl6, NaNbO3, NaNbOCl4_Pbca, NaTaCl6, NaTaO3, NaTaOCl4_Pbca, Nb2O5, NbCl2O, NbCl3O, NbCl5, Ta2O5, TaCl3O, TaCl5; cells have 128-504 atoms, repeated to edges >=13 A. c0/c1 use anisotropic strain +0.02/-0.015 and rattles 0.05/0.08 A with seed 20261112 reset per structure; c2 uses symmetric random strain +/-0.02 and rattle 0.05 A, seed 20261015. These differ from the original crystal gate's draws and are static accuracy checks, not an MD-stability certificate. See the [subsequent reference correction](#gate-polar-strain-autograd) before interpreting these historical pass counts.

  | Model / arithmetic | Passing configurations | Maximum energy ratio | Maximum force ratio | Maximum stress ratio |
  |---|---:|---:|---:|---:|
  | S / FP32 | 44/45 | 2.0393 | 4.6153 | 8.0590 |
  | S / `3x_rnacc` | 45/45 | 0.1865 | 0.6312 | 1.8323 |
  | M / FP32 | 45/45 | 0.000893 | 1.7043 | 1.8866 |
  | M / `3x_rnacc` | 45/45 | 0.001594 | 2.3837 | 2.6713 |

  Ratios use the unchanged per-configuration yardsticks/floors and fixed-set FD stress; limit 3. Maxima need not occur on the same configuration. [All rows, reference provenance and output metadata](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/local-wide-full.json).
- The expanded screen uses 15 structures x 3 configurations. Its original M run also found tuned-hybrid stress failures on NaCl_c2 (3.44) and TaCl5_c0/c2 (3.43/4.31), beyond NaNbO3; forced-hybrid NbCl2O_c0 force reaches 6.99. Therefore neither a bad NaNbO3 structure nor forcing every GEMM explains all failures.
- A separate FP32 baseline issue remains on S NaTaO3_c0, with no cutoff crossing. The original screen's stress ratio was about 4.75; later fresh-autotune runs recorded 5.12 and 8.06 (the latter also force 4.62). Disabling POLAR folding still fails (stress 5.069); the measured FD step-size change is only 0.028 of the old yardstick. No individual GEMM or later amplification stage has been isolated. Do not disable folding or label this a reference-cutoff failure.
- Historical local original-crystal gates for `3x_rnacc`: **S, M and L pass**, both tuned and forced-TC selection; M also passes both forced convolution-forward variants. S used the frozen-set FD cache; M's CUDA and L's CPU old references were reused after checking that every +/-h probe preserves the original reciprocal index set. That membership check did not establish FD step-size convergence. The original gate's existing unstable S NaNbO3_c0 exclusion remains. The expanded screen uses different draws, includes all its configurations, and is a separate qualification.
- Same-process local A/B, six rounds of 256 steps alternating **timing order**, under `local_gpu.py run --quiet`; candidate is tuned `3x_rnacc`, baseline is FP32. Engines were constructed baseline first: this is not a two-construction-order experiment. S regresses; the other changes are too small to establish a useful speed win. These are 5060 Ti measurements, not A100 results:

  | Model / system | FP32 ms/step | Candidate ms/step | Candidate / baseline, forward timing order | Reverse timing order |
  |---|---:|---:|---:|---:|
  | S / NaCl 216 | 1.4073 | 1.4468 | 1.0310 | 1.0303 |
  | M / NaCl 216 | 3.0141 | 3.0333 | 1.0052 | 1.0075 |
  | M / NbCl5 1944 | 22.0191 | 21.9851 | 0.9976 | 0.9985 |
  | L / NaCl 216 | 6.0021 | 5.9872 | 0.9961 | 0.9984 |

- Independent yardstick check: apply FastMACE's stress correction to the **same e3nn MACE core and same input**, without its other reference/engine policies. Float64 energies agree exactly and forces within `2.7e-12 eV/A`. Corrected stress agrees with frozen FD to `1.63e-9` on Na2O and `2.20e-8` on NaTaO3 at h=`1e-6`; NaTaO3's h=`1e-5` truncation is `2.00e-6`. The correction's reciprocal implementation also changes float32 summation, so this is not an isolated derivative-only patch or a full FastMACE gate. The following two-case sample is **not a stable universal yardstick**; repeated-reference measurements below explain why.

  | S configuration | Existing stress yardstick, eV/A^3 | Corrected stress yardstick, eV/A^3 | `3x_rnacc` ratio to corrected yardstick |
  |---|---:|---:|---:|
  | Na2O_c0 | 8.0046e-7 | 4.1887e-7 | **3.498: fail** |
  | NaTaO3_c0 | 7.2213e-5 | 1.2205e-4 | 0.129 |

- The full corrected-reference screen also passes **90/90** candidate configurations: S maximum E/F/stress ratios `0.1923 / 0.7035 / 1.7866`, M `0.001573 / 1.6477 / 2.3909`. The FP32 S NaTaO3_c0 failure remains (F 4.156, stress 6.437). However, that screen sampled a Na2O stress yardstick `8.2003e-7`, almost twice the two-case sample above. [Complete corrected rescore](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/local-wide-corrected-yardsticks.json).
- Reference repeatability is a real limitation: eight evaluations of the same calculator/input produce Na2O stress yardsticks `4.1029e-7` to `8.2752e-7`, and NaTaO3 `7.1979e-5` to `1.3874e-4`. An energy-only warm-up does not remove the variation. This is measured output nondeterminism, not just a different model, structure, or first call. Parallel FP32 reductions are the likely source [INFERENCE]; no individual reduction has been isolated. Do not select favorable repeats or pool them after inspecting the candidate. [Repeatability samples](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/reference-repeatability.json).
- Deterministic diagnostic: `CUBLAS_WORKSPACE_CONFIG=:4096:8`, `torch.use_deterministic_algorithms(True)`, TF32 disabled, same corrected reference. After one warm call, seven Na2O evaluations have identical reported energy, force yardstick and stress; the stress yardstick is `3.13388e-7 eV/A^3`. Against that bound, FP32 has ratio **0.936**, `3x_rnacc` **4.675**, and the four-product falsifier **4.400**. The candidate's absolute stress error is `1.46507e-6`, versus the 3x allowance `9.40165e-7`: **55.8% over the allowed error**. This is a reproducible stricter diagnostic, not a silent change to the production gate. [Samples and rescore](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/deterministic-reference.json).
- Thus the sampled 90/90 passes do **not** establish reference-policy-independent accuracy. Correcting the derivative, stabilizing the float32 reference and choosing a gate policy are distinct issues. The existing LoupMD yardstick, floors and 3x limit have not been changed to manufacture a pass. [Initial independent comparison](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/yardstick-comparison.json).
- Fourth-product falsifier: adding `A_low * B_low` before the two cross products lowers Na2O's corrected-stress ratio only to **3.292**, still above 3. Positive-dot signed bias remains `-2.368e-8` (three-product `-2.377e-8`). Restoring this omitted term alone is not the remaining cure; the experimental switch was removed. Built for sm_120/sm_80, tested only on sm_120; no A100 qualification or speed claim. [Raw falsifier](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/four-product-falsifier.json).
- A100 arithmetic matrix, job **5007888**, s70, three-tile/beta-0 cubins, forced eligible GEMMs: S original hybrid stress 6.51 and original 3xTF32 4.94 fail; rounded hybrid, rounded-hybrid isolated accumulation, and rounded 3xTF32 pass S. M original hybrid reaches force 3.57 / stress 3.87, original 3xTF32 force 4.21, and rounded-only 3xTF32 force 3.79; rounded hybrid with/without isolated accumulation passes M. L original hybrid reaches force 3.80 / stress 9.08. The job hit its one-hour limit before L's rounded variants finished; missing rows are not passes. Full-range `3x_rnacc` is a separate qualification. [Complete raw log](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/a100-arithmetic-5007888.log).
- Historical full-range `3x_rnacc` result, A100 job **5007932**: **all 58 original-crystal rows pass** with the then-current fixed-step reference (S 5, M 18, L 6, each tuned and forced). Largest F/stress ratios are S `0.36 / 0.68`, M `2.02 / 0.80`, L `2.12 / 1.58`; these are independent maxima across both selections. The original unstable S NaNbO3_c0 exclusion remains. Positive-dot normalized bias is still `-2.453e-8`, versus pedantic FP32 `-2.335e-11`. [Unabridged gates and baseline-first timings](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/a100-full-range-5007932-raw.log).
- A100 same-process A/B now covers **both engine-construction orders**: job 5007932 constructs baseline first; job **5008153** constructs candidate first. Each alternates timing order over six rounds of 256 steps. Both are A100-SXM4-40GB, on different nodes; absolute times are not a same-board paired experiment across jobs. All four systems improve in both construction orders:

  | Model / system | Baseline-first FP32 -> TC, ms/step | Candidate-first FP32 -> TC, ms/step | TC / FP32, baseline-first | TC / FP32, candidate-first |
  |---|---:|---:|---:|---:|
  | S / NaCl 216 | 1.7514 -> 1.6247 | 1.7831 -> 1.6015 | 0.9277 | 0.8981 |
  | M / NaCl 216 | 3.6672 -> 3.1702 | 3.7198 -> 3.2296 | 0.8645 | 0.8682 |
  | M / NbCl5 1944 | 17.2268 -> 13.7580 | 17.2114 -> 13.7798 | 0.7986 | 0.8006 |
  | L / NaCl 216 | 7.0965 -> 5.7362 | 6.8272 -> 5.7350 | 0.8083 | 0.8400 |

  Candidate-first ratios invert the log's baseline/candidate median ratio, rather than dividing aggregate timing medians. [Candidate-first raw log](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/a100-reverse-build-5008153.log). These are **experimental** timings: the stricter local Na2O miss, missing Ada qualification and local S slowdown still prevent production adoption. The separate 15-structure A100 S/M/L screen is not inferred from these crystal gates.
- [Local crystal gates and alternating-timing-order results](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/local-crystals-and-speed.json); [completed rounded-alternative wide screens](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/rounded-alternatives.json). Rounded FP16-cross hybrids still fall back on S NaNbO3_c0 and all three Ta2O5 configurations, despite finite final outputs; these are not tensor-core passes. Rounded-only full-range 3xTF32 fails M NaNbO3_c1 stress (3.653), motivating isolated accumulation rather than rounding alone.
- Evidence: [targeted measurements, raw metrics, hashes, cutoff diagnostic and GEMM probe](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/local-targeted.json). Gate policy is unchanged. POLAR remains FP32 by default; neither the broader sampled passes nor the A100 speed win overrides the accuracy counterexample.

<a id="gate-polar-fixed-kset"></a>
#### gate-polar-fixed-kset: differentiate a fixed reciprocal sum
- Root cause: `compute_k_vectors_flat` rebuilds a hard reciprocal cutoff mask for every strained cell. If a vector crosses the boundary between +h and -h, a finite difference includes a discrete energy jump / (2h), rather than the derivative of the unstrained reciprocal sum.
- Confirmed at h=`1e-5` in the expanded structures: NaTaCl6_c2 changes 261 to 262 vectors (`(4,-1,-4)`, xz strain); live versus fixed stress differs by `1.6461e-5 eV/A^3`. TaCl3O_c1 changes 389 to 388 (`(6,2,-1)`, xx); the difference is `1.9877e-4`. Fixed-set h=`1e-5` versus h=`1e-6` differs by only `2.99e-8` / `3.17e-8`, respectively.
- Fix: `python/polar_reference.py` freezes integer indices selected at the unstrained cell, then recomputes reciprocal vectors and their squared norms at every strained cell. It does **not** freeze Cartesian vectors, change the model cutoff, omit configurations or change engine arithmetic. The scoped MACE callback replacement is for serial reference evaluation.
- Initially integrated as cache namespace `gate-refs-2-fixed-polar-kset`; old live-set entries were not overwritten. This removed cutoff jumps but not finite-step truncation. Production targets now use the strain-gradient method below; frozen-set FD remains an independent convergence diagnostic. Energy/force references, the existing autograd float32 yardstick, 3x ratio, and `0.01 meV/atom`, `1e-5 eV/A`, `1e-7 eV/A^3` floors remain unchanged.
- Regression covers rotated and unrotated cells with an actual cutoff crossing, comparing all six stress components of a reciprocal quadratic energy to its independent analytic derivative. A mask-freeze alone is insufficient if vectors or norms are stale.
- Pre-strain-gradient verification: the two cutoff-crossing cases and two reference-cache tests passed together under the shared GPU reservation (**4 passed**). The installed library and experimental cubin hashes matched every saved local expanded-screen run. [Historical commands, output, source hashes and default-policy audit](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/current-state-verification.json).
- This fixes the demonstrated cutoff discontinuities, not every POLAR discrepancy. Na2O and NaTaO3 controls have no membership changes; fixed/live references agree there. Full reference-policy equivalence with FastMACE is not claimed.

<a id="gate-polar-strain-autograd"></a>
#### gate-polar-strain-autograd: remove finite-step reference bias
- Local diagnosis used the exact failing A100 inputs, saved reference arrays and yardsticks, not new random structures. Positions/cells are bit-identical. For S/Nb2O5 and S/Ta2O5, the local FP32 stress yardsticks are respectively **18.774x** and **3.127x** the saved A100 yardsticks. Thus a local pass need not mean a smaller engine error. Replaying S/Nb2O5, S/Ta2O5 and L/Na2O on the 5060 Ti with the A100 bounds reproduces failures; disabling POLAR folding does not cure them. Each model had its own shared reservation, with no new Alex GPU job. [Reference swap](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/cross-device-reference-swap.json); [local folded/unfolded replay](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/local-a100-failure-replay.json).
- A second reference defect survived the fixed-cutoff correction: **h=1e-5 is too large on highly curved POLAR energies**. Energy-only and full-evaluation float64 energies agree exactly. Frozen-set central differences converge towards the independently corrected analytic derivative, approximately quadratically until roundoff dominates:

  | Model / configuration / component | FD minus analytic at h=1e-5 | h=1e-6 | h=1e-7 |
  |---|---:|---:|---:|
  | S / Nb2O5_c0 / zz | +7.27546e-6 | +7.69268e-8 | -6.75539e-8 |
  | S / Ta2O5_c0 / zz | -101.103964 | -1.010349 | -0.0101491 |
  | L / Na2O_c2 / yy | -0.948433 | -0.00947572 | -0.0000941685 |

  Units are eV/A^3. Minimum separations are 1.640, 1.751 and 2.130 A respectively, not atom overlaps. S/Ta2O5 nevertheless predicts maximum float64 force **1.911e6 eV/A**; L/Na2O predicts **2804.43 eV/A**. These are observed extreme predictions, not proof that a particular species or all its structures are invalid. [Convergence, physical scales and rescores](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/reference-curvature-and-repeatability.json).
- Holding the **saved A100 FP32 yardsticks and engine outputs fixed**, correcting only the float64 stress target changes the diagnosis:

  | A100 configuration | FP32 stress ratio, fixed FD -> analytic | TC stress ratio, fixed FD -> analytic | Corrected interpretation |
  |---|---:|---:|---|
  | S / Nb2O5_c0 | 6.619 -> 7.366 | 3.722 -> 2.975 | TC passes this configuration; FP32 still fails |
  | S / Ta2O5_c0 | 1.105 -> 2.896 | 3.151 -> 0.644 | TC passes; FP32 still fails energy at 3.263 |
  | L / Na2O_c2 | 5.007 -> 0.0692 | 9.687 -> 4.749 | FP32 passes; TC fails force 4.565 and stress |
  | L / Nb2O5_c0 | 124.914 -> 84.376 | 143.502 -> 184.041 | Both paths still fail energy, force and stress |

  Limit is 3, not 1. For L/Na2O, TC force error is **1.81973 eV/A**, allowance **1.19587 eV/A** (52.2% over); stress error **0.912205 eV/A^3**, allowance **0.576243 eV/A^3** (58.3% over). The old stress miss of 9.687 included FD bias and is not the corrected engine error. TC can improve or worsen a particular configuration; it is not simply a fixed multiplier on an already-failing FP32 path.
- Permanent reference mitigation: `polar_reference.energy_stress` differentiates the **native MACE energy** through positions, Cartesian periodic shifts, cell, reciprocal cell and volume. It preserves the unstrained native geometry and radial-operation order. Scoped differentiable replacements remove a radial `out=` operation and avoid taking a singular square-root derivative at k=0. No model physics, cutoff, engine arithmetic or gate allowance is changed; no FastMACE runtime dependency is introduced. The helper is for serial reference evaluation.
- `test_gate.py` now uses these float64 targets with namespace **`gate-refs-3-polar-strain-autograd`**, invalidating both old FD protocols. The stock FP32-vs-FP64 yardstick remains unchanged. Its measured nondeterminism is a separate unresolved qualification limitation; this change does not choose a more permissive yardstick or make deterministic mode the production policy.
- Verification under the shared reservation: **9 tests pass** (complete strain derivative on rotated/unrotated cells; stiff-energy FD truncation; real radial basis including k=0; existing cutoff and cache cases). Real L/Na2O CPU reference energy is unchanged and stress agrees with the independent correction to **5.48e-11 eV/A^3**. The earlier S prototype agrees to 7.99e-15 on Nb2O5 and 8.38e-9 on Ta2O5. Actual FP32 CLI gate, `test_gate.py MACE-POLAR-1-S.model --set crystals`, passes **5/5** with the new target/cache; the existing unstable NaNbO3_c0 exclusion is unchanged. [Tests and reference comparisons](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/native-strain-verification.json); [CLI integration](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/native-gate-verification.json).
- The already-submitted A100 array **5008099** is complete: all 135 baseline and 135 candidate rows were collected, with real TC execution and no fallback. Raw FP32/TC pass counts are S **43/45 / 43/45**, M **45/45 / 45/45**, L **41/45 / 40/45**. These use the **old fixed-h target**, so they are historical results, not corrected-reference qualification. Only the explicitly rescored cases above have corrected verdicts. Energy/force misses are unaffected by the stress-reference change: L/Nb2O5_c0 reaches FP32 E/F **193.504 / 14.963** and TC **414.356 / 25.731**; L/NbCl5_c1 force is **4.377 / 3.595**. Stress-only failures require reference checks before attribution. [Complete rows, hashes and metadata](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/a100-wide-complete.json).
- Normalization diagnostic: hooks on native MACE's initial and two recursive Fukui maps measure `kappa = sum(abs(f)) / abs(sum(f))` before normalization. This is the condition number of that signed sum, not of the complete network. The L CPU results are:

  | Configuration | Maximum float64 kappa | Stage / spin index | FP32 denominator shift at that stage | FP32 minus FP64 total energy, eV |
  |---|---:|---|---:|---:|
  | NaCl_c0 | 1.258 | recursion 1 / 0 | +0.0000209% | -0.3946 |
  | Na2O_c2 | 32.538 | recursion 0 / 0 | -0.0014747% | +1.7928 |
  | Nb2O5_c0 | 37.427 | recursion 1 / 0 | -0.0164375% | +115.0073 |

  Cancellation provides an amplification mechanism, but these measurements do **not** isolate the sole cause of full-model error. Both installed MACE and `src/polar.cu` already sum the denominators in double precision; merely changing that reduction to FP64 is not a missing fix. The energy-only diagnostic is not a repeat of the saved A100 full E/F/stress reference: its FP32 Nb2O5 energy differs substantially, and hardware, reduction execution and forward flags differ. No particular one of those differences has been isolated. This run also evaluated the production native strain gradient for L/Nb2O5 to obtain the corrected stress row above; it did not repeat a separate FD convergence sweep. [All seven S/L cases, captured maps, source and rescore](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/polar-accuracy-20261115/normalization-conditioning.json).
- FastMACE's A100 POLAR pass is not a matched counterexample: its gate covers NaCl/NbCl5 rather than these expanded draws, pools error/yardstick maxima over six configurations per structure, and enables selected tensor-core classes rather than forcing every eligible GEMM. It also used a corrected analytic stress reference already. These protocol differences must be held fixed before attributing a pass/fail difference to the engines.
- Decision: keep POLAR on FP32 and retain the full-range rounded TC implementation as an experiment. The reference fix removes false failures, but genuine TC failures remain even where FP32 passes. No species blacklist, clipping, fallback-as-pass, tolerance relaxation or speculative numerical production patch was added. A matched full FastMACE-engine comparison and complete corrected-target wide-screen certification have **not** been performed.


<a id="gen-gate-epilogue"></a>
#### gen-gate-epilogue: generic gate fused into the GEMMs
- What: the nonlinear blocks' gate reads the rows a GEMM just wrote and writes rows the next GEMM reads; fuse it into the own SGEMM's epilogue / prologue.
- Status: forward REJECTED by its falsifier (S36, 14 November 2026, 5060 Ti only); backward not built.
- Measured: ceiling = the gate kernels' time. Fresh `nsys` (S36, MH-1 `SrTiO3`): `gate_bwd` 3.71 ms/step (9.4%), `gate_fwd` 2.36 (6.0%) of 39.4 ms. `ncu`: both at 87-89% of DRAM peak, 6-8% issue active (memory-bound; the GEMMs around them run at ~72% issue, ~74% of FP32 peak, and cannot hide them).
- Falsifier (S36, `.tmp_o/gf_mb.cu`, deleted; standalone, MH-1 layer shapes `N = 5,000`, `C = 512`, random data, median of 20): baseline `gate_fwd` 1,143 us + `W_2` GEMMs `l = 0..3` own `sgemm128` 206 / 575 / 870 / 1,227 us, cuBLAS 198 / 518 / 794 / 1,147 us. Fused: a pre-pass writing `s`, `gout0` and the three gate columns `G` (334 us: it still reads all of `lin0` / `res0`), the `l = 0` GEMM on `gout0`, and for `l = 1..3` an `sgemm128` copy that cp.asyncs the `lin_l` tile and the tile's `G` rows into shared memory and transforms `A = G * (lin * s)` in place (one extra barrier per k-step): 645 / 1,007 / 1,410 us with 2 stages (39 KB), 700 / 1,095 / 1,529 with 3 (58 KB, 1 block / SM); 128 registers with 28 B of spill either way. Chain `3,800 -> 3,594 us` (`0.946`, 2 stages) and `3,856` (`1.015`, 3 stages) against the stop rule `<= 0.90`. Results bit-identical to gate + plain GEMM. The real kernel would need the `res_l` tile as well for `l <= lx` (one more 8 KB stage buffer), so the proxy is optimistic.
- Why: the fused GEMM loses 12-23% against the plain own / cuBLAS GEMMs (2 stages to fit shared memory, the transform pass and its barrier, spills at the 128-register cap of 2 blocks / SM), which eats most of the gate time it removes.
- S54, backward write trim (falsifier only, 5060 Ti): `gate_bwd` writes both `dpre_l` (the `W_res` GEMMs' input, for `l <= lx`) and `dlin_l = dpre_l * s` (the `W_lin` GEMMs' input); writing one unscaled gradient and applying the per-atom `s` downstream (in the conv-backward prologue that loads `dmid`) would drop the duplicate writes. Upper bound measured with a scratch build that skips the `dlin` writes wherever `dpre` is written (wrong forces, timing only; no downstream scaling cost), `nsys` `gate_bwd` per step, two A/B pairs: MH-1 `SrTiO3` `3827 / 3904 -> 3612 / 3546 us` (`-5.6% / -9.2%`), `POLAR-1-M` `NbCl5` `1477 / 1482 -> 1385 / 1433` (`-6% / -3%`). The step totals of these runs are not reported: the scratch build's gradients are wrong, which changes the dynamics that follow. Below the 10% kernel stop rule even as a bound (a real version also pays the downstream scaling, so it can only gain less): not built.
- Sources: [§4.1 #5][s41], [§5.5][s55]; this file.

<a id="gen-gate-bwd-epilogue"></a>
#### gen-gate-bwd-epilogue: the gate backward in the `W_2^T` GEMMs' epilogue
- Switch: `src/sgemm.cu` `sgemm128_kernel<TN, FULL_N, N_FASTEST, GATE_DEG, GATE_FWD>` (`GATE_DEG = 0`: the old kernel; the 13 plain own-SGEMM kernels' SASS is unchanged), `gate_bwd_epilogue<DEG>`, `sgemm128_gate`; `src/engine.cu` `gemm_gate` (runs only where `sgemm_rm`'s plan for that GEMM is the own `sgemm128` with N tiles fastest, `M = N_atoms (2l + 1)`, `N = C`, `C % 128 == 0`; otherwise the plain GEMM and the gate kernel run), `LoupHandle::gate_fuse` (`LOUP_GATE_FUSE=0` disables); `src/generic.hpp` `GateArgs`, `GenericPassInputs::gemm_gate_bwd`; `src/generic.cu` `record` (each `W_2^T` lane tries the fused GEMM; `gate_bwd_kernel` runs for the degrees that fell back, `fused` mask).
- Stage: S137 (19 November 2026), from the dense-model research list (MH-1, the gate derivative in the transpose GEMM's epilogue with atom-aligned tiles); built in a separate worktree and integrated on top of S136.
- What: `dgout_l = dmsgf_l W_2[l]^T` was written by four GEMMs and read back by `gate_bwd_kernel` (655 MB per MH-1 SrTiO3 force call over two layers; `gate_bwd` 3.7 ms per step at 87% of DRAM peak). Row tile t of the fused GEMM starts at atom `t * (128 / (2l + 1))`, so its first 128 / 126 / 125 / 126 rows hold whole atoms (the rest, the next tile's, are computed and dropped: 0 / 1.6 / 2.4 / 1.6% extra FMAs) and no per-atom sum crosses tiles, the obstacle [gen-gate-epilogue](#gen-gate-epilogue) had left. The epilogue stages the tile in shared memory one 64-column half at a time and evaluates `gate_bwd_kernel`'s expressions for its atoms and columns: dpre_l / dlin_l, the logit gradient into dpre0 / dl0 at column `l C + c`, and dD per atom (warp shuffle, shared array, one atomic per atom and block). 128 registers, no stack, 48 KB, 2 blocks per SM, like the plain kernel.
- Exactness: the `dgout` values are the plain GEMM's (the same in-order fmaf chains) and the gate expressions run in the same order, so dpre / dlin are the same floats; only dD's sum is reassociated. Rattled cells (base against itself / base against the fused build): MH-1 SrTiO3 max dF 9.9e-7 / 9.4e-7 eV/A of |F|max 5.27, NaCl216 1.7e-7 / 2.1e-7, POLAR-1-M NbCl5 4.6e-5 / 5.4e-6 of 14.2, POLAR-1-L NaCl216 1.9e-7 / 7.1e-7.
- Measured (5060 Ti): `nsys` MH-1 SrTiO3 per step: `W_2^T` + gate kernel time 9,944 -> 7,738 us, span 9,457 -> 7,153 us (the span fell more than the kernel time: no lane serialised); the fused GEMMs l = 0..3 take 724 / 1,585 / 2,439 / 2,990 us against ~6,247 us plain (+1,491 us of epilogue against `gate_bwd`'s 3,697 us). POLAR-1-M NbCl5: 4,143 -> 3,456 us. MH-1 NaCl216: only l = 2 picks `sgemm128` (`gate_bwd` 101 -> 64 us). Library ABBA on shared plans against `c3858a4` (a-first / b-first): MH-1 SrTiO3 `0.9445` / `0.9447` (3 rounds, 33.27 -> 31.43 ms), NaCl216 `0.9881` / `0.9857`, POLAR-1-M NbCl5 `0.9647` / `0.9648` (21.02 -> 20.28 ms), POLAR-1-L NaCl216 `0.9966` / `0.9943`.
- Gates (the final S129-S137 library, its own plans): MH-1 crystals 18 / 18 (0.83 / 0.31; `LOUP_GATE_FUSE=0 LOUP_GATE_FUSE_FWD=0` 0.85 / 0.32), MH-1 `omol` head organic 24 / 24 (0.33 / 0.38; off 0.32 / 0.44), OMOL-0 XL organic 8 / 8 (0.82 / 0.48 either way), POLAR-1-L crystals 6 / 6 (2.10 / 0.71, CPU references), POLAR-1-M crystals 18 / 18 (2.51 / 1.16; off 2.68 / 1.07), and in four more processes 18 / 18 each, NaNbO3_c0's force ratio 2.32-2.51 over the default and both forced conv variants (2.1-2.3e-4 eV/A). In the worktree (on `c3858a4`) MH-1 also passed with the `matpes_r2scan` head and with `LOUP_SPECIES_TABLES=0`. That POLAR-1-M row moved between 2.2 and 3.1 there with each build's GEMM plan picks, the fusion on or off alike (the fused build: 2.8-3.1 on its own plans, 2.5-2.7 on the base build's plan file; the base build 2.2-2.7).
- Status: DEFAULT (sm_120; other GPUs never pick the N-fastest own `sgemm128`, so they keep the old path).
- Sources: this file; the owner's CPU screen `gate_reverse_tiles.py` (18 November).

<a id="gen-gate-fwd-store"></a>
#### gen-gate-fwd-store: layer 0's residual-free degrees stored gated by their projection
- Switch: `src/sgemm.cu` `gate_fwd_epilogue<DEG>` (`sgemm128_kernel<8, true, true, 2l + 1, true>`), `gemm_gate(fwd)` (the same plan and shape conditions; a null A only probes); `LoupHandle::gate_fuse_fwd` (`LOUP_GATE_FUSE_FWD=0` disables); `src/generic.cu` `record` (a first-hidden kind-4 layer with the S59 `res0_table` probes its degrees `l > lmax_x`; if any fuses, the l = 0 `C0` projection runs first, the fused degrees store `gout_l` and never `lin_l`, and `gate_vform[t]` tells `gate_fwd_kernel` to skip them and the backward to take the saved values), `gate_bwd_kernel` / `gate_bwd_epilogue` `vform`.
- Stage: S137 (19 November 2026), the research list's MH-1 rank 2 (gated angular values written by the producing GEMM), layer 0 degrees 1-3.
- What: the epilogue computes the tile's gates `cg sigmoid(pre0[l C + c])` and `s` into shared memory, then stores `g (lin s)`, the float `gate_fwd_kernel` wrote. The reverse runs through the saved `v = gout_l`: `dlin = (dgout g) s`, `d pre0 = (1 - sigmoid) sum dgout v`, `dD += -beta s sum dgout v` (the old terms reassociated, no division by the gate). Unlike S36 ([gen-gate-epilogue](#gen-gate-epilogue)) the `W_2` GEMM is unchanged. The l = 0 projection now runs before the other three lanes start; the span shows this costs less than the gate traffic it removes.
- Measured (5060 Ti, `nsys` MH-1 SrTiO3 per step, on top of [gen-gate-bwd-epilogue](#gen-gate-bwd-epilogue)): layer-0 forward span 5,064 -> 4,371 us, kernel time 5,393 -> 4,652, layer-0 `gate_fwd` 1,031 -> 85 us (l = 0 only). Library ABBA MH-1 SrTiO3 `0.9912` / `0.9910` (2 rounds, 30.93 -> 30.66 ms); with the backward fusion against `c3858a4`: MH-1 SrTiO3 `0.9340` / `0.9344` (32.77 -> 30.62 ms), OMOL-0 XL water216 `0.9636` / `0.9631` (22.37 -> 21.55 ms), MH-1 NaCl216 `1.0007` / `0.9994` (3 rounds, a tie). Rattled cells: MH-1 SrTiO3 max dF 1.0e-6 (base's own 1.2e-6), NaCl216 1.6e-7 (1.3e-7).
- Gates: as [gen-gate-bwd-epilogue](#gen-gate-bwd-epilogue) (MH-1 crystals with `LOUP_GATE_FUSE_FWD=0` alone also 18 / 18 in the worktree).
- Not done: layer 1's residual-free projections are tuned to cuBLASLt (no epilogue); layers without the S59 table keep the gate kernel; `lin_1..3` stay allocated for the fallback.
- Status: DEFAULT (sm_120).
- Sources: this file; `loupmd-speed-research-20261118/dense/sections.md` (MH-1 and OMOL-0 XL).

<a id="gemm-cold-l2-ada-fix"></a>
#### gemm-cold-l2-ada-fix: cold-L2 classification on Ada `lin1_fwd l=1` + wider 3xTF32 `mma` tiles
- Status: NOT BUILT.
- What: on Ada (`l2_bytes = 48 MiB`), `sgemm_rm`'s `M * K * 4 > l2_bytes / 2` threshold (`24 MiB`) times `lin1_fwd l=1` (`15000 * 384 * 4 = 22.0 MiB`) **hot**, even though `m1_0..3` total 97 MB and stream from DRAM; also check `lin1_bwd` (`db_l` vs `m1_l`) and `LOUP_DEBUG_GEMM=1` picks on both GPUs. Separately, `HybCubin` only provides `64x64`, `32x64`, `64x32` tiles (beaten by `sgemm128` on 5060 Ti `lin1`); test `128x64` / `64x128` 3xTF32 `mma` tiles.
- Sources: `OMAT0_SPEEDUP_BRIEF.md`.

<a id="gemm-dual-pipe-lanes"></a>
#### gemm-dual-pipe-lanes: forked GEMM lanes on the tensor-core cubin beside SIMT lanes
- Switch: none (reverted). A lab build added `LOUP_LAB_TC_LANES` (a lane mask) and `LOUP_LAB_TC_TILE`: GEMMs on the masked fork-group lanes ran on the hybrid cubin's tile 0 whatever the plan said.
- Stage: S141 (19 November 2026), owner's idea list (dual-pipe GEMM lanes).
- What: concurrent GEMM groups split between the FP32 pipe (own SIMT kernels) and the tensor pipe (the hybrid cubin), so that both pipes are busy at once.
- Measured (5060 Ti, OMAT-0 medium SrTiO3, MD 6 x 256 steps, same library and plans on every side): generic path +0.5% (one lane), +2% (two), +4% (four), +5.8% (all lanes); specialised path +1.8% to +5.3%.
- Reading: the planner had already timed these GEMMs on both kernels and chosen SIMT; forcing tile 0 of the cubin is slower per GEMM, and the overlap does not pay for it.
- Status: REJECTED (5060 Ti only; code removed).
- Sources: this file.

### Scheduling, memory and edge data

<a id="sched-side-streams"></a>
#### sched-side-streams: side-stream GEMM fork / join
- Stage: S2 (item 9).
- What: 8 non-blocking side streams, each with its own 4 MB cuBLASLt workspace, inside the captured graph.
- Status: DEFAULT.
- Measured: alone not recorded; serialising them costs +2.0% to +5.7% (sched-serialised).
- S104 falsifier (16 November 2026, 5060 Ti, scratch, reverted): would a receiver-chunked pipeline (conv of one atom chunk beside the GEMMs / product of the previous chunk; the last layer's chain from `mid` to `dmid` is per atom) hide GEMM time under the L2-bound convs? Measured with the last layer's GEMM groups launched a second time on the side lanes, into scratch buffers, concurrent with its conv kernels (OMAT-0 medium generic SrTiO3, same library both sides, ABBA, 3 rounds): the `dmid` group (~450 us alone) beside `gconv_fwd_L1` `1.062` (+480 us), the `lin` group (~470 us) beside `gconv_bwd_L1` `1.059` (+460 us), both `1.121`. Each overlapped group costs its full standalone time: the convs and the SIMT GEMMs share the SMs zero-sum, so overlap between them is closed on this GPU.
- Sources: [§3.1 #9][s31].

<a id="sched-serialised"></a>
#### sched-serialised: GEMM groups without side streams
- Status: REJECTED (a check of sched-side-streams).
- Measured: 5060 Ti `NbCl5` +5.7% / +5.0%, `SrTiO3` +2.1% / +2.0%.
- Sources: [§3.3][s33].

<a id="sched-reversed-order"></a>
#### sched-reversed-order: reversed block order between GEMMs
- What: spline, `sc0_forward`, `sc1_fused`, `w'`, `sc0_backward` and i0 forward / backward walk receivers from the top, so they first read the rows the preceding GEMM wrote last and leave the rows the next GEMM reads first in L2.
- Status: REJECTED.
- Measured: step span 8,274 -> 8,285 us (5060 Ti `SrTiO3`); no stage gained more than 6 us.
- Sources: [§3.3][s33].

<a id="mem-aliasing"></a>
#### mem-aliasing: gradient buffers aliased onto forward buffers
- Stage: S3 (item 16). What: `dm1 -> m1`, `dh0 -> h0`, `dS0 -> S0`. Status: DEFAULT. Measured: not recorded alone. Sources: [§3.1 #16][s31].

<a id="mem-inplace-s110"></a>
#### mem-inplace-s110: in-place `db` / `dm0`, rebuild temporaries as views, no `y1`
- Stage: S110 (16 November 2026), 5060 Ti. The arithmetic is unchanged.
- What:
  - `sc1_fused` writes `db` over its inputs `b`, and `sc0_backward` writes `dm0` over `m0` (16 KB/atom). Each thread reads its channel's 16 inputs before it writes the same 16 addresses, and no thread reads another channel. The aliased pointers therefore lose `__restrict__` and `__ldg`. `b` and `m0` are dead after those kernels.
  - The dead `y1` output of `sc1_fused` is removed (512 B/atom).
  - The neighbour rebuild's fill and sort temporaries are views into arrays that the force pass rewrites before reading and that are dead during a rebuild. `tmp_snd`, `tmp_rcv`, `tmp_pairs` and `sort_keys` (16 B per edge slot) live in `d_tmp_vec_len`; `tmp_shifts` (12 B) lives in `d_edge_force_1`.
- Measured (`cudaMemGetInfo` deltas over the engine's lifetime, `SrTiO3`):

  | Atoms | Before (MiB) | After (MiB) | Per atom (KiB) |
  | --- | --- | --- | --- |
  | 5,000 | 658 | 542 | 134.8 -> 111.0 |
  | 40,000 | 3,632 | 2,840 | 93.0 -> 72.7 |

  - Results at equal GEMM plans (the s106a plan file copied to the new build's key) differ by dE 2.4-3.5e-6 eV, max dF 0.9-1.2e-6 eV/A and max dS 1.7-5.5e-10. That is the installed build's own run-to-run spread (2.9-4.7e-6 eV, 0.9-1.3e-6 eV/A, 3.1e-10). With freshly tuned plans the difference is dE 1.6-3.0e-4 eV, max dF 3.3-3.6e-6 eV/A.
  - MD a-b-b-a vs s106a: `NbCl5` 1.779 -> 1.779 ms (1.0001), `SrTiO3` 8.016 -> 7.990 ms (0.9968), faster or tied in both orders. The gate passes on every variant.
- Status: DEFAULT (5060 Ti only).
- Sources: this file.

<a id="mem-b-in-s0"></a>
#### mem-b-in-s0: `b` / `db` in the S0 regions of the zero slab
- Stage: S111 (16 November 2026), 5060 Ti. The arithmetic is unchanged.
- What: the C0 GEMMs read S0, and the dS0 GEMMs are the next to write it. `b` / `db` live only between lin1's forward and backward GEMMs, inside that window, so `b_l` starts at `S0_l`. Each `S0_l` region holds max(K0, 128) floats per row (K0 = 64 S): from two species on S0 already holds `b`, and a one-species bundle gets 128-float rows (8 KiB per atom for S0 and `b` instead of 4 + 8). S0 needs no zeroing (the interaction-0 forward writes all of it), so the slab's memset is unchanged.
- Measured (`cudaMemGetInfo` deltas over the engine's lifetime, `SrTiO3`):

  | Atoms | Before (MiB) | After (MiB) | Per atom (KiB) |
  | --- | --- | --- | --- |
  | 5,000 | 542 | 498 | 111.0 -> 102.0 |
  | 40,000 | 2,840 | 2,524 | 72.7 -> 64.6 |

  - Results at equal GEMM plans: `SrTiO3` vs s106a dE 2.3-3.1e-6 eV, max dF 1.0-1.4e-6 eV/A, max dS 3.8-4.0e-10, the run-to-run spread. Cu 6x6x6 (one species, widened rows) vs s110a: dE 4.9e-6 eV, max dF 3.3e-7 eV/A, max dS 5.6e-10.
  - MD a-b-b-a vs s110a, six rounds (the last five with S112 built in, whose 5,000-atom path is one chunk): `NbCl5` 1.0056, 1.0010, 1.0018, 0.9994, 1.0021, 0.9995 (mean 1.0016); `SrTiO3` 1.0002, 0.9975, 1.0002, 0.9991, 0.9989, 0.9994 (mean 0.9992). Sides of one library differ by up to 1.3% on `NbCl5` within a round, so this is a tie. The gate passes.
- Status: DEFAULT (5060 Ti only).
- Sources: this file.

<a id="mem-m1-chunks"></a>
#### mem-m1-chunks: `m1` / `dm1` in receiver chunks above 16,384 atoms
- Stage: S112 (16 November 2026), 5060 Ti.
- What: `m1` / `dm1` (5,120 floats, 20 KiB per atom) hold one chunk of receivers at a time. Above 2 x 8,192 atoms (`kM1ChunkAtoms`) the receivers split into equal chunks of at most 8,192, rounded up to 20 (whole blocks of every spline variant), and two buffers alternate.
  - Forward: chunk c's spline writes buffer c & 1, on the main stream for even chunks and on side stream 4 for odd ones, so each chunk's spline fills the last wave of the previous one. Its lin1 GEMMs (lanes 0-3, forked from the spline's stream) write `b` rows while the next chunk's spline runs. Chunk c + 2's spline waits for them through per-buffer lane events (`ev_m1`).
  - Backward: `w'` alternates streams the same way. Chunk c + 1's lin1 GEMMs overlap chunk c's `w'`; chunk c + 2's GEMMs are forked after that `w'`.
  - The receiver-owned kernels take a chunk as shifted `row_ptr` / `D1` / `dD1` pointers with chunk-local `m1` rows; senders, edges and `dx0` / `dx1` stay global. Chunks therefore need the receiver-owned `w'`: the edge-tiled kernel indexes `dm1` by global receiver, and a forced `LOUP_WPRIME_RCV=0` keeps one chunk.
  - `LOUP_M1_CHUNK=<atoms>` forces chunks of that size on any larger system (gate variants `m1_chunk=40` and `m1_chunk=100`, both with a shorter last chunk); `0` keeps one chunk.
- Measured (`SrTiO3` 20x20x20, 40,000 atoms, MD a-b-b-a at 300 K with scratch `bench40k.py`, one chunk vs default):
  - VRAM: 2,524 -> 2,060 MiB (64.6 -> 52.7 KiB/atom; five chunks of 8,000). Chunks of 4,096 (ten): 1,900 MiB, but 1.0064 with the one-stream pipeline.
  - Run back to back on one stream, the chunk loop costs a last, partly filled wave per chunk: the tuner's timings at 40,000 atoms were spline R5 13,472 -> 13,716 us (+1.8%) and `w'` 23,046 -> 23,545 us (+2.2%).
  - Final version (two streams): seven rounds 1.0014, 1.0011, 1.0004, 1.0015 (+0.16% / +0.14%), 0.9996 (+0.01% / -0.08%), 0.9999 (-0.10% / +0.08%), 1.0000 (-0.09% / +0.08%); mean 1.0006, a tie. VRAM as above.
  - Earlier versions: one stream with the GEMMs overlapped, four rounds 1.0005, 1.0034, 1.0031, 1.0000 (mean +0.18%, six of eight orders slower); one buffer and serial chunks of at most 16,384 (three chunks), 2,004 MiB but 1.0029 (+0.44% / +0.15%).
  - One force pass at rest (`profile_force`, 40,000 atoms, one-stream pipeline): 59.9 ms both ways; `nsys` kernel sums grow (+2.1 ms, mostly `w'` and the lin1 GEMMs) because overlapping kernels share SMs.
  - Results: at 5,000 atoms (one chunk) and equal GEMM plans the difference to s106a is the run-to-run spread. Forced chunks of 1,000 vs one chunk: with float32 SIMT GEMMs only (`LOUP_NO_HYBRID=1`) dE 0.5-3.0e-6 eV, max dF 1.0-1.2e-6 eV/A (the spread); with the default GEMMs up to dE 1.8e-3 eV over 5,000 atoms, because the chunk-sized shapes get their own (re-timed) hybrid tensor-core plans. The two-stream and one-stream builds with the same plan file agree within the spread (no race). `tests/test_engine.py` passes with `LOUP_M1_CHUNK=40`; the gate passes on every variant, the forced chunks included.
- Status: DEFAULT (5060 Ti only).
- Sources: this file.

<a id="mem-l1-carveout"></a>
#### mem-l1-carveout: per-arch L1 carveouts
- Switch: `tune_l1`.
- Stage: S3 (item 17).
- What: the smallest shared-memory configuration that keeps occupancy for the gather kernels, per arch.
- Status: DEFAULT.
- Measured: i0 forward L1 hit 53% at the 64 KB configuration against 33% at the default 100 KB (305 us there).
- Sources: [§3.1 #17][s31], [§2][s2].

<a id="edge-packed"></a>
#### edge-packed: packed edge arrays
- Stage: S3 (item 13). What: `act_vec_len` (`float4` x, y, z, r), `act_t_sx` (`float2`). Status: DEFAULT. Measured: not recorded alone. Sources: [§3.1 #13][s31].

<a id="edge-row-receiver"></a>
#### edge-row-receiver: no per-edge receiver or pair index in the candidate list
- Stage: S113 (16 November 2026), 5060 Ti. The arithmetic is unchanged.
- What: the fill kernels write row i with the edges whose receiver is i, so the candidate list's `receivers` array only repeated the row index, and `pairs` was `sym_pair(species[sender], species[i])`. `d_receivers` and `d_pairs` (8 B per edge slot) and the rebuild temporaries `tmp_rcv` / `tmp_pairs` are gone; `scatter_active_edges` writes `act_receivers` from the row and recomputes the pair index (the sort key in the fill kernels still uses it). The candidate list keeps `senders` (4 B) and `shift_cart` (24 B); the rebuild's sender and sort-key temporaries take 8 of `tmp_vec_len`'s 16 B per slot. Both the specialised and the generic paths use these kernels.
- Measured (`SrTiO3`):
  - VRAM: 5,000 atoms 498 -> 490 MiB (100.4 KiB/atom), 40,000 atoms 2,060 -> 2,020 MiB (51.7 KiB/atom); the edge buffers of the first evaluate 522 -> 482 MiB at 40,000 atoms.
  - Results at equal GEMM plans vs s106a: dE 3.7-4.0e-6 eV, max dF 0.9-1.0e-6 eV/A, max dS 2.1-6.0e-10, the run-to-run spread.
  - MD a-b-b-a vs S112: `NbCl5` 1.773 -> 1.772 ms (0.9993; +0.28% / -0.45%), `SrTiO3` 7.995 -> 7.977 ms (0.9978; -0.01% / -0.44%).
  - `tests/test_engine.py` 31 passed, also with `LOUP_M1_CHUNK=40` (the S112 chunks under NVE, Langevin and every MD rebuild mode); gate 42 / 42.
  - Generic-path gates on the final build (HEAD `0cc8e33`, which shares these kernels): OMAT-0 small (oxide) 6 / 6, OFF23-S (organic) 8 / 8, POLAR-1-S (oxide) 6 / 6, MH-1 (oxide) 18 / 18.
- Cumulative S110-S113 (final build vs the installed s106a): VRAM `SrTiO3` 5,000 atoms 658 -> 490 MiB (134.8 -> 100.4 KiB/atom), 40,000 atoms 3,632 -> 2,020 MiB (93.0 -> 51.7 KiB/atom); MD a-b-b-a `NbCl5` 1.773 -> 1.773 ms (0.9995), `SrTiO3` 8.002 -> 7.987 ms (0.9982, both orders faster); `pytest -q` 77 passed; OMAT-0 medium gate 42 / 42.
- Status: DEFAULT (5060 Ti only).
- Sources: this file.

<a id="edge-sh-coalesced"></a>
#### edge-sh-coalesced: coalesced SH stores
- Stage: S3 (item 19). Status: SUPERSEDED by edge-sh-recompute. Sources: [§3.1 #19][s31].

<a id="edge-sh-recompute"></a>
#### edge-sh-recompute: SH computed where staged
- Switch: `edge_sh16`.
- Stage: S3 (item 24).
- What: `scatter_active_edges` no longer writes 64 B per edge; i0 forward / backward and the spline compute the 16 values from `act_vec_len` while staging.
- Status: DEFAULT.
- Measured: 24 MB fewer stores per step at 5,000 atoms; `scatter_active_edges` 0.11-0.16 -> 0.05 ms.
- Sources: [§3.1 #24][s31], [§2][s2].

<a id="edge-compaction-1pass"></a>
#### edge-compaction-1pass: single-pass active-edge compaction
- What: decoupled look-back over 4-row tiles, pass-1 vectors cached in shared memory.
- Status: REJECTED.
- Measured: kernel 96 -> 80 us (5060 Ti `SrTiO3`), equal on `NbCl5`; MD tie on both GPUs in both orders.
- Why: the simpler count + scan + scatter path stays.
- Sources: [§3.3][s33].

<a id="mem-reorder"></a>
#### mem-reorder: L2-gated spatial atom reorder
- Switch: on when `N * 4096 > l2_bytes`; `LOUP_REORDER=0|1` forces it.
- Stage: S2 (item 8).
- What: Morton reorder within species groups every 16th rebuild.
- Status: DEFAULT (scoped: above L2 size). Gate: reorder on vs off agree to 5e-7 eV/A (review F1).
- Sources: [§3.1 #8][s31], [§3.2 F1][s32].

<a id="mem-reorder-small"></a>
#### mem-reorder-small: Morton reorder below L2 size
- Status: REJECTED. Measured: not recorded. Why: the reorder's extra sync is pure overhead when the system fits L2. Sources: [§3.3][s33].
- S95 measurement (16 November 2026, 5060 Ti, `libloupmd_s86a.so`, `nsys`, `LOUP_REORDER=1` against the default off; the atoms are already species-grouped, so this is the Morton order inside each group against the caller's): OMAT-0 generic SrTiO3 `gconv_bwd_L1` 2,979 -> 2,932 us, `gconv_fwd_L1` 1,710 -> 1,677, step 7.98 -> 7.96 ms; OMAT-0 specialised SrTiO3 `w'` 2,890 -> 2,874, spline 1,736 -> 1,726, step 8.03 -> 8.00 ms; NbCl5 `w'` 441 -> 431 but spline 317 -> 328, step 1.780 -> 1.781 ms; OFF23-M water216 `gconv_fwd_L1` 222 -> 208, backward unchanged. At most 0.5% of a step before the reorder's costs (it also keeps MD on the host-driven rebuild), so the gate stays at the L2 size.

<a id="mem-shift-cart"></a>
#### mem-shift-cart: Cartesian float64 shifts
- Switch: `d_shift_cart`. Stage: S2 (item 7). What: precomputed at rebuild; removes the cell from the force graph. Status: DEFAULT. Sources: [§3.1 #7][s31].

<a id="mem-l2-persist-x"></a>
#### mem-l2-persist-x: CUDA Graph L2 persistence (`AccessPolicyWindow`) for `x0 + x1`
- Status: NOT BUILT.
- What: attach `cudaKernelNodeAttributeAccessPolicyWindow` to the `spline_forward_inter1` and `wprime_backward_inter1_rcv` graph nodes for `x0 + x1` (`9.77 MiB` on `SrTiO3`), with `cudaLimitPersistingL2CacheSize` around `10-12 MiB` (leaving >= 20 MiB on 5060 Ti for table slabs). Gate on checking `ncu` L2 hit rate on `x0`/`x1` first (`spline` writes `m1` after the edge loop, not during it, so `x0`/`x1` may already stay L2-resident).
- Sources: `OMAT0_SPEEDUP_BRIEF.md`.

<a id="mem-l1-carveout-retune"></a>
#### mem-l1-carveout-retune: re-check `tune_l1` carveouts after items 23-31
- Status: NOT BUILT.
- What: `tune_l1` shared/L1 carveouts in `src/engine.cu` were measured before items 23-31 (`i0_bwd` staging, `w'` `s_q` / `wp_threads`); re-checking `w'` and `i0_bwd` carveouts is cheap.
- Sources: `OMAT0_SPEEDUP_BRIEF.md`.

### Neighbour list, integrator and MD loop

<a id="eng-evaluate-one-graph"></a>
#### eng-evaluate-one-graph: loup_evaluate as one graph launch
- Switch: none (default).
- Stage: S145 (19 November 2026), found while timing the LAMMPS pair style.
- Before: a call copied the positions from pageable memory (a stream synchronisation before the copy), launched the skin check and a publication, read the flag, launched the force graph, copied energy, forces and virial to pageable memory and synchronised the stream: about eight submissions and three blocking host-GPU exchanges, each 0.1-0.2 ms under WSL 2.
- Now:
  - `set_system` allocates page-locked staging (3N positions, 3N forces, energy, virial).
  - With a standing list and an unchanged cell, a call is one launch of the MD loop's step graph without an integrator (`run_md_loop` kind 3): upload from the staging, skin check, `guard_step_kernel`, the SWITCH node (force pass, or the on-device rebuild and checked force pass), then, after the SWITCH node, the results' copies into the staging and a publication of the rows' order flag (`queue_results`).
  - The host reads the guard's publication and the last one. No transfer blocks and nothing synchronises the stream.
  - A new cell or a first call takes the host-driven rebuild and the force graph as before, with the same staging and publication.
- Measured (5060 Ti, WSL 2, OFF23-S water216, Python `LoupEngine.evaluate`, 300 calls with 1e-3 A noise, medians, old and new library in one job): 0.95 / 1.14 ms per call (without / with stress) -> 0.51 / 0.41. The engine's own MD step is 0.34-0.36 ms: a call still waits for its forces before the caller can queue the next one.
- Accuracy: unchanged arithmetic (the same force pass). 101 tests pass on the library, the families' gates among them (`STATUS_AND_PROFILE.md` S145).
- Status: DEFAULT (5060 Ti under WSL 2 only; the gain on native Linux, where a host-GPU exchange is cheaper, is not measured).
- Sources: this file, `LAMMPS_KOKKOS_PLAN.md`.

<a id="eng-evaluate-ahead"></a>
#### eng-evaluate-ahead: loup_evaluate's next step queued ahead, and where a LAMMPS step's time goes
- Switch: `loup_set_evaluate_ahead(h, 1)` (off by default), `pair_style loupmd ahead yes`, `LoupEngine.set_evaluate_ahead`; `LOUP_EVAL_ARM=0|1` for every handle (tests); `LOUP_DEBUG_EVAL_TIMES=1` prints the probes below when a handle goes.
- Stage: S146 (19 November 2026), `LAMMPS_SYMMETRIX_PARITY_PLAN.md` stage L1 (the owner's "go ahead").
- Design:
  - After a call that took the step graph (kind 3), once two such calls in a row had one virial flag, the engine queues `cuStreamWaitValue32(stream, d_go, seq)` and behind it the step graph (`arm_evaluate`). The next call stages its positions and stores `seq` in the mapped word; the graph then runs with no launch on the call's path.
  - A call that does not fit the queued step (another cell or virial flag) and every other entry point first let it run as a step on the staged positions and read its publications (`settle_armed`); `invalidate_md_graphs`, the exception path and `loup_destroy` drain it (`drain_armed`). Results therefore never depend on the setting.
  - S37 ([md-wait-value](#md-wait-value)) rejected the idea for the MD loop for want of a safe rebuild branch; the guarded step graph with its SWITCH node (S75) is that branch.
  - The results now come back in one copy of the zeroed slab (energy, forces, virial) instead of three.
- Why opt-in: the engine's stream is a blocking stream. While a step is queued on it, any work on CUDA's default stream anywhere in the process (another handle's set-up, PyTorch) and any device-wide synchronisation wait for it, forever. The first build, on by default, hung in the tests while a second engine was set up. Other explicit streams are not held up (checked in isolation: a graph launch, a kernel launch and a copy with synchronisation on a second stream all ran while the first waited).
- Primitive, in isolation (driver 621.14, a one-kernel graph): a launch behind the wait returns in about 5 us and the graph has run 4-73 us after the store; a plain launch takes 44-220 us to the same point. A plain kernel launch (not a graph) on the waiting stream blocks the host until the store.
- Measured (5060 Ti, WSL 2):
  - LAMMPS `pair_style loupmd`, `fix nve` + `fix langevin`, `a b b a` on one build (`ahead no` / `ahead yes`), ms/step: SrTiO3 320 atoms 0.838, 0.826 / 0.752, 0.783; OFF23-S water216 0.553, 0.567 / 0.528, 0.533 and, after the one-copy change, 0.581, 0.547 / 0.548, 0.561; SrTiO3 5,000 atoms 8.189, 8.232 / 8.146, 8.269.
  - Python `LoupEngine.evaluate` on water216, ms per call, off / on: 0.531-0.595 / 0.441-0.484 before the one-copy change, 0.423-0.499 / 0.449-0.493 after it (no clear difference left).
  - Probes, LAMMPS, means over about 1,080 quiet steps, us (320 / 5,000 atoms), `ahead no`: entry to launch 20 / 51, launch to the guard's publication 208 / 225, guard to results 571 / 7,588, results to return 1 / 29, between calls 17 / 200. With `ahead yes`: 3 / 14, 174 / 170, 580 / 7,587, 19 / 62, 17 / 206.
  - Lab build without the upload and / or the download in the step graph (water216, Python, launch to guard, us): as built 167, no upload 107, no download 156, neither 181; with evaluate ahead 149 and 111. The delay is not the host copies.
- Reading: the force pass costs what it costs in the engine's loop (571-580 against 580-590 us at 320 atoms). What a host-integrating caller pays on top is a fixed 0.11-0.2 ms from a launch or release to the start of the force pass, the start of the large step graph on an idle GPU, plus its own CPU work. The engine's loop hides the first by queueing each step during the previous force pass. Evaluate ahead removes the launch call and about 35 us of the delay, and costs 18 us to queue.
- Tests: `tests/test_device_io.py::test_evaluate_ahead_changes_no_result_and_yields_to_every_other_call` (a queued step through a rebuild, the other virial flag, another cell, a run, a state read, a new system, and the handle's end), `tests/test_lammps.py::test_evaluate_ahead_gives_the_same_run`.
- Status: OFF (opt-in; 5060 Ti under WSL 2 only). The one-copy change is DEFAULT. For LAMMPS the consequence is that only an integrator inside the engine reaches the engine's step time (`run_style loupmd`, and stage L3 of the plan).
- Sources: this file, `LAMMPS_SYMMETRIX_PARITY_PLAN.md`.

<a id="eng-device-io"></a>
#### eng-device-io: loup_compute_device, an evaluation on the caller's device arrays
- Switch: a new entry point (`include/loupmd.h`), with `loup_cutoff` and `loup_species`; `LoupEngine.compute_device`, `cutoff`, `species` in `python/loupmd.py`.
- Stage: S145, `LAMMPS_KOKKOS_PLAN.md` stage B.
- Design:
  - `LoupDeviceIO` names device pointers with row and component strides (row-major and column-major arrays both fit), an optional id per row (rows in any order) and flags.
  - The engine orders itself behind the caller's stream with an event, gathers the rows into its atom order through a device copy of the inverse permutation (refreshed after `set_system` and after an atom reorder), runs the external step (kind 2 of the MD graph: skin check, guard, force pass or on-device rebuild), adds the forces to the caller's rows and makes the caller's stream wait on a second event.
  - The host waits only for the guard's publication, and for energy or virial when asked. With those, a non-finite result drops the tensor-core cubin and reruns the pass before any force is added, as `loup_evaluate` does.
  - The virial is formed in every pass, so steps that ask for it run the same graphs.
- Tests: `tests/test_device_io.py` (twelve): shuffled rows and both layouts against `loup_evaluate`; the device call and `loup_evaluate` through moves and rebuilds on each rebuild path (on-device, `LOUP_MD_REBUILD=host`, `fallback`, `LOUP_REORDER=1`) against freshly built lists; refusals (and a corrected call accepted again); run calls in blocks; the model facts.
- Status: DEFAULT (a new call; nothing existing changes).
- Sources: this file, `LAMMPS_KOKKOS_PLAN.md`.

<a id="eng-run-graph-reuse"></a>
#### eng-run-graph-reuse: run calls with the same parameters keep their graphs
- Switch: none.
- Stage: S145.
- The MD graphs bake in the step, the thermostat constants and the seed, so every `loup_run_*` call dropped and re-captured them. They are now kept while those values are unchanged (`md_graph_key` -2 with `md_int_*`); the Langevin noise continues through the device step counter as before. The external steps (kinds 2 and 3) have their own keys.
- Effect: a run in blocks (the LAMMPS run style, between output steps) costs one initial force pass per block and no re-capture. Not timed on its own.
- Status: DEFAULT.
- Sources: this file.

<a id="lmp-styles"></a>
#### lmp-styles: LoupMD in LAMMPS (package ML-LOUPMD)
- Switch: LAMMPS input (`pair_style loupmd [device N] [skin S] [ghost yes|no]`, `pair_style loupmd/kk`, `run_style loupmd nve | langevin T damp seed`); user guide `lammps/README.md`.
- Stage: S145 (19 November 2026), the owner's "build the lammps version"; plan and results in `LAMMPS_KOKKOS_PLAN.md`.
- Design:
  - The engine keeps the system by atom ID (its atom k is the atom with ID k + 1) and evaluates the whole periodic cell with its own neighbour list; LAMMPS's lists and ghost atoms are not used. One MPI process.
  - Positions are unwrapped with the image flags, so LAMMPS's re-wrapping does not look like motion to the skin check. The system is sent again only when the atom count, a type or the skin changed (looked for at run start and on reneighbouring steps).
  - `loupmd`: `loup_evaluate` per step. `loupmd/kk`: one Kokkos kernel (unwrap, ids), then `loup_compute_device` on LAMMPS's device views behind Kokkos's stream. `run_style loupmd`: `loup_run_nve` / `loup_run_langevin` in blocks up to the next output step, where the state comes back and the pair style evaluates energy and pressure.
  - LAMMPS build used: a local clone of `stable_30Sep2026_update1` with Kokkos 5.2.1 (CUDA, `sm_120`), system g++ 13.3, OpenMPI, CUDA 13.3, in `~/loupmd_lammps`.
- Measured (5060 Ti under WSL 2):
  - Accuracy, `run 0` against the Python engine, both pair styles, five cases (OFF23-S water216; OMAT-0 medium SrTiO3 320 atoms in a sheared cell and 5,000 atoms; MH-1 NaCl216; POLAR-1-M NaCl216 in a sheared cell): forces within 2e-7 to 5e-6 eV/A and the six pressure components within 6e-4 to 0.08 bar (of up to 7.8e4), the spread of two engine runs.
  - MD, OFF23-S water216, 2,000 steps of 0.5 fs: total-energy drift +0.092 (engine integrator), +0.099 (`fix nve`, `loupmd`), +0.080 meV/atom (`fix nve/kk`, `loupmd/kk`). After 100 steps the engine's integrator and `fix nve` agree to 5e-9 eV/atom in the kinetic energy. Sorting every step changes nothing. `fix npt` runs (1.7-1.9x the NVE step: the list is rebuilt every step).
  - Speed, MACE-OMAT-0 medium, Langevin, the benchmark environment's SrTiO3 inputs and protocol (100 + 256 steps, each code twice in one job):

    | | 5,000 atoms, ms/step | 320 atoms, ms/step |
    | --- | --- | --- |
    | `run_style loupmd` | 7.84-7.86 | 0.61-0.63 |
    | `pair_style loupmd` | 8.20 | 0.86-0.90 |
    | `pair_style loupmd/kk` | 8.38-8.45 | 1.29-1.38 |
    | Symmetrix `symmetrix/mace/foundation/float32/kk` (benchmark build, 16 Nov) | 13.47-13.54 | 1.55-1.59 |

  - The engine's own loop (`LoupEngine.run_langevin`) on the same two data files and protocol, in one job with the run style (`a b b a`): 7.71-7.74 against 7.81-7.83 ms/step at 5,000 atoms, 0.59-0.61 against 0.62-0.64 at 320. The run style is the same loop plus the hand-back at each output step: 1-1.5% and 2-7% slower, never faster.
  - NaCl 216 atoms (the 5 November Symmetrix-XL case, 500 + 3,000 steps): `loupmd` 0.52-0.54, `loupmd/kk` 1.60, the engine's own loop 0.29-0.30 ms/step; Symmetrix-XL was 3.55-3.61 on 5 November (not rerun).
  - LAMMPS-Kokkos alone (zero-strength LJ, the 648 water atoms, `fix nve/kk` + `fix langevin/kk`): 2.43 ms/step; with `neigh_modify every 20 delay 0 check no` 0.52; plain LAMMPS 0.115. On this machine the Kokkos style's small-system step is LAMMPS-Kokkos's own cost.
  - `ghost no`: `loupmd/kk` water216 2.64 -> 2.25-2.53 ms/step, inside the spread (2.2-2.9 over the day's runs).
  - LAMMPS features with the pair styles (19 November, after the first S145 commits): 26 of 28 setups run with `pair_style loupmd` (integrators `nve`, `nvt`, `npt`, `nph`; thermostats and barostats; `setforce`, `spring/self`, `momentum`, `recenter`, `addforce`, `deform`; `shake`, `rattle`, `rigid/small`; minimisers and `box/relax`; `hybrid/overlay`), at 0.2-0.3 ms per step over the engine's loop on a 320-atom cell; `compute pe/atom` is refused, and `press/berendsen` needs a material `modulus`. Table in `LAMMPS_SYMMETRIX_PARITY_PLAN.md`, Part 1.
  - `loupmd/kk` with an occasional list request (see [lmp-kk-occasional-list](#lmp-styles)): LAMMPS-Kokkos sets its device flag only when a list is requested on the device; without one its displacement check and bond topology ran on the host. SrTiO3 320 atoms 1.29-1.38 -> 0.97-1.03 ms/step, 5,000 atoms 8.38-8.45 -> 8.14-8.19 (separate jobs); `fix rigid/small` in a bonded system no longer aborts.
- Not built: a strain-aware list for changing cells, per-atom energies, open boundaries, several processes or GPUs (`LAMMPS_KOKKOS_PLAN.md` stages C-F).
- Tests: `tests/test_lammps.py` (nine, needs `LOUPMD_LMP`; two of them rigid bodies in a bonded system, both modes), `tests/test_device_io.py`.
- Status: a new interface on `develop`; 5060 Ti under WSL 2 only (native Linux, sm_89 and the A100 not measured).
- Sources: this file, `LAMMPS_KOKKOS_PLAN.md`, `lammps/README.md`.

<a id="nl-bucketing-sort"></a>
#### nl-bucketing-sort: edge-grid bucketing and segmented sort
- Stage: S1 (bucketing), S2 (`cub::DeviceSegmentedSort::StableSortPairs`).
- What: the edge grid rounded to 8,192 so graphs survive edge-count changes; the rebuild sort as a segmented sort.
- Status: DEFAULT (bucketing); the segmented sort was replaced in S75 by [nl-row-sort](#nl-row-sort).
- Measured: rebuild sort ~2.3 ms -> ~16 us.
- Sources: [§3.1 #3][s31].

<a id="nl-f32-pretest"></a>
#### nl-f32-pretest: float32 pair pre-test (T3)
- Stage: S3 (item 15).
- What: float32 distance test in `count` / `fill_neighbors` with borderline pairs re-checked in float64; 32-thread blocks.
- Status: DEFAULT.
- Measured: rebuild 1,222 -> 510 us (5060 Ti), 1,121 -> 684 us (Ada).
- Sources: [§3.1 #15][s31].

<a id="nl-lane-groups"></a>
#### nl-lane-groups: lane groups per atom for the neighbour count / fill
- Switch: `src/neighbors.cu` `count_neighbors_kernel` / `fill_neighbors_kernel` (`kNeighborLanes = 8` in `kernels_common.cuh`, 128-thread blocks), dispatched in `rebuild_neighbors` when `h->is_sm120` and the fill's shared table (`16 x nscan` ints) fits in 48 KB; otherwise `count_neighbors_scalar_kernel` / `fill_neighbors_scalar_kernel` (the previous one-thread-per-atom kernels, `sm_89` / `sm_90` SASS identical to S33).
- Stage: S34 (14 November 2026).
- What: water never pipelines at skin 0.5 (0 of 256 steps; `OFF23-S` / `OFF23-M`) and rebuilds every ~4 steps (68 / 256), so the rebuild sits on the step's critical path. `ncu` (`OFF23-S` water, 5,184 atoms): the one-thread-per-atom kernels launch 162 warps in all, 8% achieved occupancy, latency-bound (long scoreboard 3.5-4.2; count 184 us, fill 308 us). Now 8 lanes share one atom and split its `(2rx+1)(2ry+1)(2rz+1)` neighbouring bins round-robin; each lane walks its bins with the same float pre-test / float64 band and the same image-shift arithmetic as before. Count reduces in the group. Fill counts each bin's candidates into shared memory, lane 0 turns the counts into running offsets from `row_ptr[i]`, and a second sweep writes each bin's edges at its offset, so rows follow the one-thread kernels' order by construction. Edge arrays were not compared directly; `MH-1` `NbCl5` (a deterministic path) matches the old build to `dE 3.6e-12` (same-library repeats: 0 to 5e-12). The count kernel's unused `sqrt` is removed by the compiler (no `MUFU` / `DSQRT` in its SASS, as in the old count kernel).
- Status: DEFAULT (5060 Ti only).
- Measured (5060 Ti): `ncu` count 184 -> 81 us, fill 308 -> ~215 us (occupancy ~55%, now issue-bound at 73-85%). `nsys` medians per rebuild (count + fill): `SrTiO3` 150 + 283 -> 77 + 215 us, `NbCl5` 115 + 169 -> 34 + 76, water 166 + 273 -> 76 + 226. Fresh-plan ABBA with the installed binary, new / old: `OFF23-S` water `0.9945` and reversed `1.0146` (`0.9856`), `OFF23-M` water `0.9961` / `1.0057` (`0.9943`), `OMAT-0-S` `SrTiO3` `0.9961` / `1.0028` (`0.9972`). Gates pass (`OFF23-S` organic 8 / 8, `OMAT-0-S` oxide 6 / 6, `MH-1` crystals 6 / 6, `POLAR-1-S` crystals 5 / 5); `pytest` 67 passed; `test_replicated_cell...[MACE-POLAR-1-S]` `dF` 2.24e-3 (old build 2.19-2.30e-3).
- Rejected on the way: (1) lanes striding the slots of each bin with a ballot / prefix-popcount compaction (exact order): every lane repeated the per-bin bookkeeping, including its float64 image shifts (FP64 is 1/64 rate here), for ~3.4 atoms per bin: 4x the instructions, issue-bound at 84%, count 184 -> 292 us, fill 308 -> 383 us. (2) Bins split by lane with each lane's edges written as one run (lane-major order, per-lane counts from the count kernel): count + fill 492 -> 297 us, but equal-key edges (stable sort) came out in a different order, which moved `MACE-POLAR-1-S`'s replicated-cell force difference from 2.19e-3 to 3.25e-3 against the test's 3e-3 (deterministic, three runs each); fixed by the per-bin offsets above.
- Sources: this file.

<a id="nl-single-readback"></a>
#### nl-single-readback: one host round trip per neighbour rebuild
- Stage: S35 (14 November 2026).
- What: a rebuild synchronises twice: after the row scan (the host needs `E_new` for the edge capacity, the sort size and the edge grids) and after the row-order check (`order_err`, which must stop a corrupt list before any force pass). On water (rebuild every ~3.7 steps, never pipelined at skin 0.5) the `nsys` trace shows ~136 us of idle GPU behind each. Built on the `sm_120` lane-group path when edge arrays exist: a kernel stores the true count in `deg[N]` and clamps `row_ptr` to the capacity (monotone; a no-op without overflow, so fill writes stay in bounds and cub never sees an offset past the capacity); the segmented sort runs with `num_items = capacity`; gather and check (`<DEV_E>` templates, `false` instantiation SASS-identical to S34 on `sm_89` / `sm_90`) read the count from `row_ptr[N]`; one readback of count and flag. A count above the capacity grows the arrays, rescans and takes the two-readback path.
- Status: REJECTED (5060 Ti only).
- Measured (5060 Ti, `OFF23-S` water, 150 steps, 41 rebuilds): `nsys` span from bin scatter to the order check `657 -> 544 us` per rebuild, GPU busy `351 -> 350 us` (sorting over the capacity costs nothing). Untraced, a launch + 4-byte readback + synchronise costs ~49 us median (pageable; p90 ~194 us) against ~136 us inside `nsys`, so the saving is <= ~13 us/step (~0.4%). Fresh-plan ABBA, new / old (the reversed run prints old / new; inverted here): `OFF23-S` water `1.0016` and `0.9990`; `OFF23-M` water `0.9970` and `1.0019`; `OMAT-0-S` `SrTiO3` `1.0011` and `1.0006`: ties, mixed in sign for both water models. Correctness held: MD trajectories (`MH-1` `NbCl5` 300 steps, `OFF23-S` water 60, `OMAT-0-S` 100) at the same-library noise level; a scratch build without capacity headroom took the overflow retry 10 times in 60 water steps with the same rebuild count and energy at noise level.
- Why: the `nsys` gap overstated the untraced host round trip by ~3x; one round trip less is below ABBA resolution.
- Sources: this file.

<a id="md-wait-value"></a>
#### md-wait-value: unpipelined MD step behind a stream wait-value
- Stage: S37 (14 November 2026), 5060 Ti only.
- What: water stays in the unpipelined loop at skin 0.5 (`4 x max step displacement >= skin / 2`), so every step pays `move graph -> memcpy flag -> cudaStreamSynchronize -> launch rest graph`. Fresh `nsys` idle census (union of kernel intervals, traced): `OFF23-S` water 545 us / step idle (83.5% busy), `OFF23-M` water 456 (94.0%), against 82-196 us on pipelined systems (`OMAT-0-S` `SrTiO3` 96.7%, `MH-1` / `POLAR-1-S` `NaCl216` 94.2% / 87.7%, `OMAT-0-M` `NbCl5` 95.6%). Idea: enqueue the rest graph behind `cuStreamWaitValue32(go >= step)` on host-mapped pinned memory before the host decision, so the GPU starts it as soon as the host writes `go`, without a launch into an empty queue.
- Status: REJECTED by its falsifier; not built.
- Measured (`.tmp_o/wv_mb.cu`, deleted; standalone; `CU_DEVICE_ATTRIBUTE_CAN_USE_STREAM_WAIT_VALUE_NOR = 1` on this WSL driver; 300-step loops, median of 5): round trip (current loop minus no host decision) 156-174 us per step; the wait-value loop saves 82 / 82 / 105 us (300 kernels x 400 FMA, 300 x 100, 600 x 400). The ~75 us that remain are the host's event wake-up and the device's poll of host memory.
- Why not built: the saving applies only to steps without a rebuild. With a rebuild (water: every ~3.7 steps) the queued graph must not run on the old list, cannot be cancelled once enqueued, and holds captured pointers that `ensure_edge_capacity` may free. A safe branch needs conditional graph nodes (137-200 us of GPU time per step on this driver, [s22-limiters](#s22-limiters)) or a speculative force pass discarded on a rebuild (~3 ms per rebuild). Netting the saving over the steps the speculation could cover leaves <= ~1.5% of `OFF23-S` water.
- Sources: this file.
- S75: the conditional-node branch this lacked is [md-guarded-loop](#md-guarded-loop). Measured inside the MD loop and in a full-queue microbenchmark, an IF node with its guard kernel costs 6-8 us per step on this WSL driver (10-11 us on the A100), not the 137-200 us of S22, and a mapped-memory poll replaces the event wake-up.

<a id="md-guarded-loop"></a>
#### md-guarded-loop: one exact MD loop with the force pass behind a conditional graph node
- Switch: `src/engine.cu` `run_md_loop` (step graph: first half + `check_skin_kernel` + `guard_step_kernel` + IF node whose body is the force pass and second half; checked rest after a rebuild: `rest_guard_kernel` + IF), `publish_kernel` / `wait_published` / `read_device_ints` (mapped pinned words `h_pub`, device counter `d_pub_counter`), `rebuild_neighbors(h, check_order)`. Removed: the unpipelined / pipelined loops, `kPipeLag`, the step-displacement maximum (`d_max_step_disp2`, `record_step_disp2` in the first-half kernels), flag bits 2 / 4, `LoupMDStats::dangerous_builds` / `pipelined_steps`.
- Stage: S75 (16 November 2026), 5060 Ti and A100.
- What: water and other light-atom systems never pipelined at skin 0.5, so every step paid `move graph -> memcpy -> cudaStreamSynchronize -> launch rest` into an idle GPU, and every rebuild three more round trips (edge count, CUB's segmented-sort partition, row-order flag). (a) Host reads now poll mapped pinned memory: a one-thread kernel copies the values and then a sequence number (`__threadfence_system` between), the host spins on the number (with a `cudaStreamQuery` every 4,096 polls so a failed launch cannot hang it). (b) Each step is one graph: first half, the exact skin check (rebuild when an atom moved more than skin/2; always at skin 0), `guard_step_kernel` (publishes the flag and the last rebuild's row-order flag, sets the IF condition), and the IF node holding the force pass and second half. The host waits only for the guard's publication, which lands before the force pass starts, and queues the next step while it runs; on a flagged step the GPU skips the force pass, the host rebuilds at the new positions and launches the checked rest. Every force pass follows its own check, as the old unpipelined loop did, so there is no lagged threshold and no incomplete list (the pipelined loop's dangerous-build accounting goes). (c) The rebuild's row-order flag is no longer read synchronously in MD: the checked rest's `rest_guard_kernel` and the step guard skip the force pass on rows that failed it, and the host reads it with the next publication or at the end of the block (`evaluate` / `set_state` still read it at once).
- Measured, 5060 Ti (in-process `ab_sides.py`, 4 rounds in both orders, noise side; ratio = old / new step time): polling vs `cudaStreamSynchronize` in the old loop: `OFF23-M` water216 `1.082` (`1.111` / `1.063`), `OFF24-M` water216 `1.089`, `OFF23-S` water216 `1.146`, `MH-1` `NaCl216` `1.003`, `OMAT-0` generic `NbCl5` `1.019` (noise `0.989`), `SrTiO3` `1.005` (noise `1.007`). Guarded steps vs the polled unpipelined loop: `OFF23-M` water216 `1.173` (`1.173` / `1.165`), `OFF23-S` `1.199` (`1.231` / `1.188`), `MH-1` `NaCl216` `1.008`, `NbCl5` `1.013` (noise `1.011`), `SrTiO3` `1.005` (noise `1.005`). Guarded only vs guarded with the pipelined loop kept for small displacements: `0.994`, `1.024` (noise `1.007`), `1.006`, `1.002`, `1.005`; 40 / 135-atom `SrTiO3` `0.998` / `0.989` (noise `0.972` / `0.981`): ties, so the pipelined loop went.
- Measured, A100 (in-process, `libloupmd_s75d.so` sides; old loop = `LOUP_MD_LOOP=0`): `OFF23-M` water216 guarded 0.8324 ms, guarded only 0.8291, old loop polled 0.8201, old loop synchronised 0.8810; `OFF23-S` water216 0.4824 / 0.4985 / 0.4814 / 0.5265 (a repeat: guarded only `1.008`, polled old loop `0.980`, noise side `0.972`); `MH-1` `NaCl216`, `OMAT-0` generic `NbCl5` / `SrTiO3`, 40 / 135-atom `SrTiO3`: all within 0.7%. Polling is the A100 gain (6-9% on water216); the guarded step is a tie there (the IF node's ~11 us against a ~10 us native round trip), so one loop serves both GPUs.
- Overhead (`.tmp_o/condbench.cu`, deleted; queue full, chains of 60-400 kernels): plain graph vs move + guard kernel + IF{rest}: 5060 Ti +6-8 us per iteration, A100 +10-11 us; folding the guard into the move kernel (last-block condition) saves <= 1.5 us: not done.
- Measured against HEAD (5060 Ti, library ABBA in subprocesses, order a b b a, each build with its own Python wrapper; new / old, S75 complete with [nl-row-sort](#nl-row-sort)): `OFF23-M` water216 1.262 -> 1.010 ms `0.800`, `OFF23-S` water216 0.662 -> 0.463 `0.700`, `OFF24-M` water (5,184 atoms) 10.05 -> 9.65 `0.961`, `MH-1` `NaCl216` `0.990`, `OMAT-0` `NbCl5` `0.994`, `OMAT-0` `SrTiO3` `0.998`, `MH-1` `SrTiO3` `1.000`. Guarded only (this build) vs guarded with the pipelined loop kept: `1.005`, `1.002`, `1.004` (ties).
- Measured against HEAD, A100 (same protocol, `sm_80` builds `libloupmd_s73c.so` / `libloupmd_s75e.so`; first / second order): `OFF23-M` water216 `0.978` (`0.972` / `0.985`), `OFF23-S` water216 `0.989` (`0.967` / `1.011`), `OFF24-M` water `0.995`, `MH-1` `NaCl216` `1.003` (`1.003` / `1.003`), `OMAT-0` generic `NbCl5` `0.995`, generic `SrTiO3` `0.998`, specialised `SrTiO3` `0.998`: wins or ties (each build tunes its own GEMM plans, so 0.5-1% is plan noise).
- Exactness: no force-path kernel changed (`engine.cu` 17 kernels, `neighbors.cu` 9 SASS-identical to HEAD on `sm_89` / `sm_90` / `sm_120`); the neighbour rows keep their order ([nl-row-sort](#nl-row-sort)). Trajectories under the old and new loops differ only at the noise of two engines of one loop (atomic summation order; `MH-1` `NaCl216` 600 steps 5-7e-8 A, `SrTiO3` 3-5e-7 A; water216 diverges chaotically for both pairs alike), with equal rebuild counts. `tests/test_engine.py`: the pipelining tests went; `test_langevin_skin_list_matches_rebuild_every_step` covers the skipped-force / rebuild / checked-rest path against skin 0.
- Status: DEFAULT (all GPUs).
- Sources: this file.

<a id="nl-row-sort"></a>
#### nl-row-sort: neighbour rows sorted, gathered and checked by one kernel
- Switch: `src/neighbors.cu` `sort_gather_rows_kernel` (shared memory, rows up to 4,096 edges), `sort_gather_rows_global_kernel` (scratch in `act_vec_len`, longer rows; `LOUP_ROW_SORT=global` forces it), `max_degree_kernel`; `rebuild_neighbors` reads the edge count and the longest row in one poll. Removed: `cub::DeviceSegmentedSort`, `gather_sorted_edges_kernel`, `check_row_species_order_kernel`, `d_sort_vals`.
- Stage: S75 (16 November 2026).
- What: `cub::DeviceSegmentedSort` reads its segment partition back to the host (one more round trip per rebuild), and gather and order check were two more launches. One block per receiver row sorts `(key << 32 | fill position)` with a bitonic network padded to the next power of two (the order of the stable sort it replaces: each edge's sort value was its fill position), gathers the edges with the Cartesian shifts and flags a decreasing sender species.
- Exactness: `.tmp_o/test_rowsort.cu` (deleted): random rows with many equal keys, up to 5,597 edges, both kernels equal to a host `std::stable_sort` in every edge, 0 mismatches, and a planted species violation flagged. In the engine, the shared and global paths agree at the two-engine noise level (`OFF23-M` water216 `dF` 4.9e-7, `MH-1` `NaCl216` `dE` 0, `OMAT-0` `SrTiO3` `dF` 9.7e-7; equal rebuild counts over 200 steps).
- Measured (5060 Ti, library ABBA, guarded loop with CUB sort vs this plus the checked rest): `OFF23-M` water216 `0.933`, `OFF23-S` water216 `0.864`, `OFF24-M` water (5,184 atoms) `0.971`, `MH-1` `NaCl216` `0.992`, `OMAT-0` `NbCl5` `0.997`.
- Gates (`libloupmd_s75e.so`, the complete S75 build; worst force / stress ratio): OMAT-0 medium oxide 1.61 / 2.46, its generic path 2.03 / 1.77 (with `LOUP_ROW_SORT=global` 2.03 / 1.78), MH-1 crystals 0.85 / 0.29, OFF23-M organic 0.35 / 0.52 (global 0.35 / 0.51), POLAR-1-S crystals 0.68 / 0.67: 7 runs, none failing.
- Status: DEFAULT.
- Sources: this file.

<a id="md-device-rebuild"></a>
#### md-device-rebuild: the neighbour rebuild inside the MD step graph
- Switch: `src/engine.cu` `run_md_loop` (step graph: move + check + `guard_step_kernel`, then one SWITCH node: body 0 the rest, body 1 {`nl_bin` + `nl_count` + `rebuild_gate_kernel` (verdict in `d_max_deg[1]`) + `nl_fill` + `nl_commit` (their kernels skip themselves on a negative verdict) + `rest_guard_kernel`, IF (fits and valid rows) rest}; `capture_ifs` captures the IF node), `rebuild_neighbors` split into `nl_geom` / `nl_bin` / `nl_count` / `nl_fill` / `nl_commit` / `nl_finish`; publications use four mapped slots so a step's guard and gate cannot overwrite each other. `LOUP_MD_REBUILD=host` (no rebuild branch) / `fallback` (the gate never fits) for tests.
- Stage: S76 (16 November 2026), 5060 Ti.
- What: after S75 a rebuild step still left the GPU idle twice: from the guard's flag to the host's first rebuild launch (~190-200 us under WSL2) and from the edge-count readback to the fill launch (~140-200 us); `OFF23-S` water216 rebuilds every ~4 steps, so that was ~19% of its step (`nsys` census, 26 rebuilds in 100 steps, 10.4 ms of 53.5). The step graph now carries the rebuild: the gate kernel publishes the edge count and longest row and lets fill, sort, commit and the checked rest run if the list fits the captured edge bucket and a row-sort width with a quarter of headroom over the last longest row. The host waits for the gate's publication instead of the rebuild (the force pass is then running), so it queues the next step at once. A list that does not fit (bucket or width outgrown) is finished on the host from the counted rows (`nl_finish`) and the graphs are recaptured. Systems whose rebuilds reorder atoms (a host round trip) or sort rows in global scratch, and a system's first rebuild (variant timing), keep the host-driven rebuild.
- Measured (5060 Ti, library ABBA over S75, order a b b a, 2 rounds; first / second order): `OFF23-M` water216 `0.939` (`0.938` / `0.940`), `OFF23-S` water216 `0.862` (`0.872` / `0.851`), `OFF24-M` water (5,184 atoms) `0.992`, `MH-1` `NaCl216` `0.998` (`1.011` / `0.985`), `OMAT-0` `SrTiO3` `0.998`.
- Idle after S76 (`nsys` census, 100 steps; gaps over 20 us): `OFF23-S` water216 10.4 -> 2.9 ms of steady-state gaps, `OFF23-M` 8.6 -> 2.4. What is left is the device-side launch of the rebuild branch (~55 us from the guard to the first rebuild kernel) and the return from the nested branch to the next step graph (~50 us), once per rebuild. With the rebuild's memset / memcpy nodes (as in the host path) those were 74 / 62 us; `nl_reset_kernel`, `copy_ints_kernel` and `nl_commit_kernel` replace them in both paths (ABBA tie, `0.990` / `0.997` / `1.005`).
- Conditional-node layout (S77, in-process, 4 rounds in both orders, noise side): every conditional node a step evaluates costs time on this driver even when its body does not run. One SWITCH node (rest / rebuild) instead of two sibling IF nodes: `OFF23-S` water216 `0.951` (noise `1.014`), `OFF23-M` `0.992` (noise `1.008`), `MH-1` `NaCl216` `1.000`, 135-atom `SrTiO3` `1.002`: adopted. A flat layout (the nested IF nodes moved to the top level as IF nodes on handles reset at every launch, four per step) lost: `1.153`, `1.049`, `1.043`, `1.191`.
- One nesting level (S78): the gate stores its verdict for the fill, sort and commit kernels (an early exit) instead of an IF node around them, so the rest's IF node is the only nested one. Library ABBA over S77: `OFF23-S` water216 `0.991` (`0.993` / `0.989`), `OFF23-M` `0.996`, `MH-1` `NaCl216` `0.999`. `nsys` census (100 steps, gaps over 20 us): `OFF23-S` water216 2.85 -> 0.85 ms of steady-state gaps, `OFF23-M` 2.42 -> ~0: rebuild steps no longer idle the GPU.
- Idle left after S78 (S79 `nsys`, `OFF23-S` water216, 100 steps, `.tmp_o/gaphist.py`): about 25 us of steady-state idle per 0.43 ms step: the launch of the next step graph (6.2 us after `langevin_second_half_kernel`), the SWITCH node's body (5.9 us from `guard_step_kernel` to the rest's first kernel), 21 gaps under 1 us (4.2 us) and four of 1-2 us (5.3 us) between dependent kernels.
- Falsifier (S79, reverted): the skin check folded into the first-half kernels, one kernel fewer per step (`check_skin_kernel` 1.1 us). Library ABBA on shared GEMM plans, 3 rounds: `OFF23-S` water216 `1.000` (`0.993` / `1.008`), `OFF23-M` water216 `0.997`: a tie, not adopted. Trajectories against S78 differ only as much as two runs of one build do (300 Langevin + 300 NVE steps, largest position difference: MH-1 NaCl216 3.5e-8 / 3.0e-8 A, OMAT-0 SrTiO3 2.8e-7 / 2.5e-7): MD runs are not bitwise reproducible run to run, so trajectory identity across builds is judged against that spread.
- Method: the GEMM plan file is keyed by the library's hash, so each build in a library ABBA times its own picks, and pick noise reaches 1% (the same S79 pair read `1.010` / `1.010` on separate plans). `.tmp_o/ab_libs.py --same-plans` runs both sides on the first side's picks; effects near 1% need it.
- Exactness: the same kernels in the same order (the row sort's result does not depend on its width); `tests/test_engine.py` checks Langevin skin 0.2 against skin 0 on all three paths (device, host, fallback).
- Status: DEFAULT.
- Sources: this file.

<a id="int-langevin-32"></a>
#### int-langevin-32: Langevin first half in 32-thread blocks
- Stage: S3 (item 26).
- What: the first half's float64 Box-Muller is FP64-throughput bound on consumer GPUs; the step-counter increment moves into the second half (one graph node less). Random stream bit-identical.
- Status: DEFAULT.
- Measured: 14.9 -> 8.0 us (`NbCl5`).
- Sources: [§3.1 #26][s31].

<a id="md-evaluate-reuse"></a>
#### md-evaluate-reuse: non-destructive `evaluate()`
- What: keeps velocities, skips rebuilds when `max_disp < skin/2` and the cell is unchanged.
- Status: DEFAULT. Measured: not recorded. Sources: [§3.1 #10][s31].

<a id="md-adaptive-pipeline"></a>
#### md-adaptive-pipeline: adaptive pipelined MD loop
- Switch: `LoupMDStats::dangerous_builds`, `LoupMDStats::pipelined_steps`; `check_skin_kernel`, `d_max_step_disp2`.
- Stage: S6 (review round 5, M1, 12 November 2026); margin raised 13 November; switch rule tightened in review round 6 (S1).
- What: pipelining reads step k's skin check after step k + 1 is launched, so two force calls follow each check. The loop starts unpipelined (exact for any skin) and pipelines once 4 x the largest per-step displacement (tracked on the device) is below skin/2; the pipelined check lowers its threshold by three times that displacement (two steps of lag, one of margin). Round 6: the unpipelined check also flags atoms beyond the pipelined threshold, and the loop switches only when none is.
- Status: SUPERSEDED (S75) by [md-guarded-loop](#md-guarded-loop): every step checks its own list exactly and the force pass waits behind a conditional node, at the pipelined loop's speed; the pipelined loop, its lagged threshold and both statistics were removed.
- Measured: MD speed unchanged (5060 Ti 1.836 / 8.454 ms, Ada 2.056 / 9.262 ms). With a two-step margin, 1 of ~1,600 steps of three 300 K benchmarks ran on an incomplete list; with three, 0 in every benchmark on both GPUs. Round 6: 9 incomplete-list force calls in 60 switches of the regression test -> 0.
- Sources: [§3.2 M1, S1][s32], [§5.4][s54].

<a id="md-skin"></a>
#### md-skin: larger / adaptive skin (T10)
- Status: PENDING (owner decision: it changes the benchmark configuration).
- Measured: estimate 0.5-1.5% at 5,000 atoms, ~10% at 135 atoms.
- Measured (S46, 5060 Ti, single-step Langevin runs at 300 K / 1 fs after 100 steps, 200 steps): per-step maximum atomic displacement, `OFF23-S` water (5,184 atoms): median 0.0814 A, p10 0.0709, p90 0.0878, max 0.1065, always a hydrogen; `OMAT-0-S` `SrTiO3`: median 0.0171, max 0.0213 (oxygen). The pipelined loop needs `4 x max step displacement < skin / 2`, i.e. `< 0.0625 A` at skin 0.5: water fails in every step (it never pipelines, 0 of 256 steps measured in S34), `SrTiO3` passes with a 3x margin. The criterion must hold in every step: the p90 corresponds to skin ~0.7 A, the observed maximum (0.1065 A) to ~0.85 A, both from a 200-step sample and before any margin for rarer, faster steps in long runs; at skin 1.5 `OFF23-S` water ran 2.90 against 3.13 ms/step at 0.5 (S34; more edges per step but no per-step host round trip and fewer rebuilds).
- Sources: [§4.1 #4][s41].

<a id="md-graph-reuse"></a>
#### md-graph-reuse: MD step graphs and forces kept across run calls
- Switch: none (always on); `LOUP_DEBUG_GRAPHS` prints a line per MD graph capture and per force pass a run call makes before its first step.
- Stage: release task S1-T03 (`release/v1`, `dd5268d`); review item S4.
- Status: DEFAULT on `release/v1`. 5060 Ti only.
- What: `run_md_loop` dropped its captured graphs at entry and ran a force pass before its first step on every call. The graphs are now kept while kind, timestep, temperature, friction and seed are the same (everything else a graph bakes in already invalidates it where it changes), and a call that follows a completed run or evaluation at the same positions starts from the forces on the device.
- Measured (15 November 2026, `SrTiO3` 5,000 atoms, Langevin 300 K, one seed, wall time of 1,000 steps after 300 warm-up steps, median of three repeats in alternating order, `.tmp_o/chunk_cost.py`): baseline library one call 8,082.6 ms, 100 calls of 10 steps 8,997.9 ms, ratio 1.1133 (second run 1.1132); head one call 8,066.2 ms, 100 calls 8,152.0 ms, ratio 1.0106 (second run 8,073.1 / 8,118.2 ms, 1.0056). The release plan's criterion is 2%.
- Standard A/B: see [rel-stage1-api](#rel-stage1-api).
- Sources: [§6][s6]; `tests/test_md_graph_reuse.py`.

<a id="md-disp-decay"></a>
#### md-disp-decay: decaying step-displacement maximum
- Switch: none.
- Stage: release task S1-T11 (`release/v1`, `d4d5433`, fix `2f56b11`); review item S2.
- Status: SUPERSEDED (17 November 2026) by the merge of `round6-hardening` (S75-S78): the MD loop checks every step's list before its force pass (`guard_step_kernel`), so it neither pipelines nor reads the maximum. The decaying maximum itself stays, for `loup_get_step_displacement`, the saved state and the automatic skin; the host ends its windows between step launches. Before: DEFAULT on `release/v1`, 5060 Ti only.
- What: the maximum per-step displacement, which decided whether the loop may pipeline and by how much the pipelined skin check lowers its threshold, covers the current and the previous window instead of everything since `set_state`. A window ends at a neighbour rebuild once it holds 32 steps, and after 512 steps without one. Ending a window also clears bit 4 of the skin check's flag word, which otherwise stays set until a rebuild.
- Measured: no timing of its own; `tests/test_pipeline_decay.py` (a kicked atom at 300 K: 0 pipelined steps in the first 40, more than 200 of 300 after 1,200 further steps; a cold system without rebuilds pipelines again after two 512-step windows; four reheating cycles to 1,500 K without a dangerous build; water 648 atoms at 300 K: more than 1,500 of 2,000 steps pipelined at skin 1.0 A, 0 at skin 0.5 A, as S46 predicts).
- Standard A/B: see [rel-stage1-api](#rel-stage1-api).
- Sources: [§6][s6]; [md-skin](#md-skin) for the water data.

<a id="md-thermo-buffer"></a>
#### md-thermo-buffer: thermo rows on the device
- Switch: `LoupIntegrator.thermo_every` (0 = off, the default; the old run entry points never ask for rows).
- Stage: release task S1-T05 (`release/v1`, `d0b1fc9`).
- Status: DEFAULT on `release/v1`, off unless asked. 5060 Ti only.
- What: two kernels at the end of the captured step (`src/thermo.cu`): a kinetic-energy sum whose threads return at once on steps that write no row, and a one-thread kernel that counts the step and appends the row. Only on / off is part of the graph key; the cadence is a device value.
- Measured (15 November 2026, `bench_md.py`'s protocol through `loup_run`, 6 blocks of 256 steps per side in the order a b b a, `.tmp_o/thermo_cost.py`, two runs): `thermo_every = 20` against off, `NbCl5` 1.7969 / 1.7960 ms (1.0005) and 1.8022 / 1.7949 ms (1.0041); `SrTiO3` 8.0563 / 8.0535 ms (1.0003) and 8.0464 / 8.0405 ms (1.0007). Block spread within a side is about 0.4%.
- Sources: [§6][s6]; `tests/test_thermo.py`.

<a id="rel-stage1-api"></a>
#### rel-stage1-api: the release branch's Stage 1 against its baseline
- Stage: release Stage 1 (`release/v1` at `a68cc04`, snapshot library `2e7e904abac64b91`) against the baseline of `plans/baseline-20261115.md` (`bac354c`, sources of `round6-hardening` `11778cd`, library `df58a9bd2623a502`).
- Status: DEFAULT on `release/v1`. 5060 Ti only.
- What: everything of release tasks S1-T01 to S1-T11 that is built: the error channel, version calls and `loup_get_info`, kept MD graphs, `loup_run`, the thermo buffer, the state blob, `loup_evaluate2` with the energy-only pass, the generic pass cut into per-layer pieces with the sweep selector, open domains (testing only), the memory plan and the decaying displacement maximum.
- Measured (15 November 2026, `python/bench_md.py`, both orders, fresh plan cache for each library): baseline first: baseline 1.812 / 8.052 ms, head 1.811 / 8.056 ms (0.9994 / 1.0006); head first: head 1.807 / 8.045 ms, baseline 1.809 / 8.065 ms (head / baseline 0.9986 / 0.9975). A tie in both orders.
- Gate: `python/test_gate.py` at head PASS, 30 rows, worst force ratio 1.55, worst stress ratio 1.71 (baseline 1.56 / 1.71). `pytest`: 205 passed at `7bafa23` (baseline 71).
- Sources: [§6][s6].

<a id="rel-merge-r6tip"></a>
#### rel-merge-r6tip: the release branch after merging the `round6-hardening` tip
- Stage: release Stage 1 (`release/v1` at `11edd3c`, library `9f89f02c26e7792a`) against `round6-hardening` `e21faa2` built from a `git archive` (library `5cbfaca706805301`).
- Status: DEFAULT on `release/v1`. 5060 Ti only.
- What: the merge keeps both sides in `src/engine.cu` (upstream's hybrid drop-and-retry of S65 around the release branch's `prepare_evaluate` and `loup_evaluate2`; failure messages on the error channel) and `src/generic.cu` (S64's conv variants beside the per-layer pieces and the ghost rows). The head's MD loop differs from the tip's by Stage 1's changes only: kept graphs, the two-window displacement maximum, the optional thermo kernels.
- Measured (15 November 2026, `python/bench_md.py`, each library with its own plan files): tip first 1.0040 / 1.0044 and 1.0080 / 1.0017; head first 1.0052 / 0.9977 and 0.9946 / 0.9990 (head / tip, `NbCl5` / `SrTiO3`); three more with fresh plan directories 0.9955 / 1.0006, 1.0069 / 0.9965, 1.0067 / 0.9981. Mean of seven: 1.0030 (standard error 0.0021) / 0.9997 (0.0010). Single `NbCl5` runs of the head spread from 1.783 to 1.839 ms, the tip's from 1.781 to 1.834 ms. Counted as a tie; the owner has the number (`PLAN.md` §1.3 D21).
- Measured, generic path (`python/bench_family.py`, r6 head head r6): OMAT-0 small `SrTiO3` 4.541 to 4.531 ms (0.9977); OMAT-0 small `NbCl5` 1.058 to 1.065 ms over six runs a side (1.0066; one head run at 1.115); MH-1 `SrTiO3` 34.978 to 35.010 ms (1.0009); OFF23 medium `water216` 1.234 to 1.250 ms over six runs a side (1.0127) and 1.230 to 1.223 ms over 18 blocks a side (0.9944), with no pipelined step and equal rebuild counts in both builds.
- Gate: `python/test_gate.py` at head PASS, 30 rows and both reorder checks, worst force ratio 1.52, stress 1.68. `pytest`: 212 passed.
- Not measured: the tip's own gate and suite; the gates of the generic families at head; anything on the RTX 4000 Ada.
- Sources: [§6.1][s61].

<a id="lmp-run-style-fixes"></a>
#### lmp-run-style-fixes: LAMMPS's NVT and NPT inputs at the engine's step time
- Stage: release, O40 (`LAMMPS_SYMMETRIX_PARITY_PLAN.md` L3; PLAN.md D97). Library `037b67e07ad2f5d2` on `sm_120`; LAMMPS `stable_30Sep2026_update1` built against it.
- Status: DEFAULT on the local `release/v1` (the user chooses the route with the `run_style` line). Step times on the 5060 Ti under WSL 2 only.
- What, three parts:
  1. `run_style loupmd` without an ensemble reads the input's fixes (`read_fixes` in `lammps/ML-LOUPMD/integrate_loupmd.cpp`) and runs the engine's integrator of that ensemble between LAMMPS's output steps: `fix nve`, `nvt`, `npt iso`, `nve` + `langevin` / `temp/csvr` / `temp/berendsen` (+ `press/berendsen`), `setforce 0 0 0` and atoms outside the integrating group as held atoms, `momentum linear`. Everything else that acts during the steps is refused by name.
  2. `loup_evaluate` between two blocks of a run (`evaluate_once`, `keep_md`): while the MD graphs hold an integrator's step, the first two evaluations after it check the skin and launch the force graph, which stands beside them. Before, the evaluation captured the host step over the integrator's graphs and the next block captured the integrator's again: four captures per output step.
  3. The pair style sends the system to the engine only when the atomic numbers, the masses or the skin changed (`PairLoupMD::ensure_system`). Before, every `run` command sent it again, which dropped the list, the tuned plans, the thermostat's state and the noise counter.
- Measured, the three routes (19 November 2026, RTX 5060 Ti, `.tmp_o/rs_l3_speed.py`: MACE-OMAT-0 medium, rattled SrTiO3, 300 K, 1 fs, thermostat time 0.1 ps, barostat time 1 ps, 200 steps and then 2,000 timed with thermo every 1,000; each run a process of its own with a fresh `LOUP_CACHE_DIR`; order own loop, run style, LAMMPS and back; ms/step, first / second run):

  | atoms | input | package's own loop | `run_style loupmd` | LAMMPS integrates |
  | --- | --- | --- | --- | --- |
  | 320 | `fix nvt` | 0.6474 / 0.6471 | 0.6512 / 0.6468 | 0.8102 / 0.8371 |
  | 320 | `fix npt iso` | 0.7952 / 0.7804 | 0.7829 / 0.7916 | 1.3094 / 1.2865 |
  | 320 | `fix nve` + `fix langevin` | 0.5803 / 0.5734 | 0.5935 / 0.5776 | 0.7952 / 0.8007 |
  | 1,080 | `fix nvt` | 1.7479 / 1.7511 | 1.7747 / 1.7612 | 1.9692 / 2.0068 |
  | 1,080 | `fix npt iso` | 1.8465 / 1.8633 | 1.8436 / 1.8465 | 2.6300 / 2.6431 |
  | 1,080 | `fix nve` + `fix langevin` | 1.7178 / 1.7109 | 1.7175 / 1.7162 | 1.9861 / 2.0324 |
  | 5,000 | `fix nvt` | 7.6892 / 7.6778 | 7.7434 / 7.7290 | 8.0693 / 8.0826 |
  | 5,000 | `fix npt iso` | 7.6874 / 7.6656 | 7.6743 / 7.6634 | 8.8910 / 8.8612 |
  | 5,000 | `fix nve` + `fix langevin` | 7.6588 / 7.6758 | 7.6627 / 7.6765 | 8.1921 / 8.1657 |

  Run style against the package's own loop: 0.996 to 1.012 (the largest: `fix nvt` on 1,080 atoms). LAMMPS integrating against the run style: `fix nvt` 1.27 / 1.12 / 1.04 at 320 / 1,080 / 5,000 atoms, `fix npt` 1.65 / 1.43 / 1.16, Langevin 1.36 / 1.17 / 1.07.
- Measured, the output interval (`.tmp_o/rs_block.py`: 320 atoms, 200 steps and then 2,000, one plan folder; ms/step and the job's graph captures at thermo every 1,000 / 100 / 10 steps):

  | | 1,000 | 100 | 10 |
  | --- | --- | --- | --- |
  | Langevin, before parts 2 and 3 (library `7f976766de199e71`) | 0.5996, 20 captures | 0.6174, 92 | 0.9204, 884 |
  | Langevin, after | 0.5803, 6 | 0.5935, 6 | 0.7340, 6 |
  | `fix nvt`, after | 0.6477, 6 | 0.6600, 6 | 0.8658, 6 |
  | `fix npt iso`, after | 0.7654, 6 | 0.7851, 6 | 1.0095, 4 |

  What an output step still costs is two force passes (its own evaluation, and the first of the next block on the same positions) and the state's way through the host.
- Tests: `tests/gpu/test_lammps_run_style.py` runs each ensemble through LAMMPS and, from LAMMPS's own starting state, through the Python engine with the integrator the run style is to pick: the same positions, velocities and box after 40 steps (positions to 2e-5 A), as one block and as four; held atoms, `fix momentum`, two runs that continue one trajectory, the noise stream after a new state and after a new system, the captures with output every 10 steps (at most 8), eleven refusals. Tests of `57bf988`. RTX 5060 Ti (`sm_120`, library `037b67e07ad2f5d2`): `tests/gpu/test_lammps_run_style.py` 31 passed and `tests/gpu/test_lammps.py` 10 passed against an `lmp` rebuilt on this library; `tests/gpu` fast 414 passed, 7 skipped for a wrong structure path in that run (they are in `tests/gpu/test_d3.py`, which passed whole, 53, with the right one); full 52 passed and 1 failed on a timing bound (`test_a_schedule_tracks_its_target_on_5000_atoms`: the ramp's step 3.5% above the hold's where 3% is allowed; four reruns, two on this library and two on the merge's, gave 0.1 to 1.0% and passed). RTX 4000 Ada (`sm_89`, library built on `leto` from `57bf988`): `tests/cpu` 500 passed, 1 skipped; fast 351 passed, 72 skipped (no `lmp` and no `dftd3` there), 2 failed, both the machine's: the kernel-plugin test (its `/usr/bin/nvcc` does not know `sm_89`) and the first device call after `loup_set_state`, whose child process crashed at `import torch` because that build exported its statically linked libstdc++ (linked again with those symbols hidden, `tests/gpu/test_device_io.py`, `test_engine.py` and `test_run_api.py`: 59 passed); full 52 passed, 1 skipped (`leeloo`).
- Not measured: the RTX 4000 Ada (no LAMMPS build there); native Linux; `fix temp/csvr` and the Berendsen pair for speed (the same step graphs as the engine's own runs of those integrators).
- Left open: `fix npt aniso` / `tri` (the engine's full-cell mode is neither); fixes that only read the state every N steps (`fix ave/time`, `fix print`), which could be served as output is; the second force pass per output step.
- Sources: `LAMMPS_SYMMETRIX_PARITY_PLAN.md` L3; [§6.37][s637]; `.tmp_o/mrg/gpu_rs4.log` (not kept in the tree).

<a id="rel-merge-develop"></a>
#### rel-merge-develop: the release branch after merging `develop`
- Stage: release, O38 (`merge/develop-s146`: `1d15783` the merge, `00f6b75` the two fixes below; library `7f976766de199e71` on `sm_120`) against `develop` `dec2e1f` (library `1b4afd6065012b28`) and against the branch before the merge (`./libloupmd.so` of 18 November, the code of 0.0.1).
- Status: DEFAULT on `merge/develop-s146`. Step times on the 5060 Ti only; tests and accuracy gates on both GPUs.
- What: PLAN.md D92 lists what the merge keeps on either side. Two things had to be built for this branch (D93, `00f6b75`): the zeros that S125 / S130 / S132 write once at allocation stay outside the arena the layers of a sweeping system share, and a pass with ghost atoms runs the receiver-owned pruned conv backward instead of S135's sender-owned kernel. Without them MP-0 medium and MPtrj-2022.9 could not be set up as a domain or run tiled. One defect of `develop` is fixed on the way: `loup_evaluate` after `loup_set_state` captured its step graph on untuned GEMM plans (the plans stayed untuned); it now takes the host-driven pass first.
- Measured (19 November 2026, RTX 5060 Ti, `.tmp_o/mrg_ab.py`: each run a process of its own through the C interface, a fresh `LOUP_CACHE_DIR` per run, Langevin 300 K, 1 fs, friction 0.01 / fs, 100 warm-up steps, median of six 256-step blocks; a b b a, ms/step):

  | Case | develop | merged | merged | develop | merged / develop |
  | --- | --- | --- | --- | --- | --- |
  | OMAT-0 medium `SrTiO3` 5,000 | 7.589 | 7.638 | 7.652 | 7.661 | 1.0026 |
  | the same, three more rounds | 7.647 / 7.653 / 7.667 | 7.660 / 7.662 / 7.662 | 7.665 / 7.670 / 7.649 | 7.661 / 7.663 / 7.671 | 1.0011 / 1.0011 / 0.9982 |
  | OMAT-0 medium `SrTiO3` 320 | 0.5773 | 0.5788 | 0.5855 | 0.5866 | 1.0004 |
  | OMAT-0 small `SrTiO3` 5,000 | 4.2105 | 4.2227 | 4.2204 | 4.2236 | 1.0011 |
  | MP-0 medium `SrTiO3` 1,080 | 0.6686 | 0.6536 | 0.6656 | 0.6655 | 0.9889 |
  | OFF23-M water 648 | 0.8740 | 0.8856 | 0.8889 | 0.8705 | 1.0172 |
  | the same, three more rounds | 0.8596 / 0.8675 / 0.8680 | 0.8633 / 0.8670 / 0.8719 | 0.8717 / 0.8708 / 0.8836 | 0.8707 / 0.8731 / 0.8676 | 1.0028 / 0.9984 / 1.0114 |
  | MH-1 `NaCl` 216 | 1.3443 | 1.3527 | 1.3337 | 1.3384 | 1.0014 |
  | POLAR-1-S `NaCl` 216 | 1.1281 | 1.1306 | 1.1160 | 1.1202 | 0.9993 |

- Measured, against the branch before the merge (same protocol, one round; before / merged / merged / before, ms/step): OMAT-0 medium 5,000 atoms 7.822 / 7.663 / 7.669 / 7.827 (0.980); 320 atoms 0.5858 / 0.5756 / 0.5749 / 0.5811 (0.986); OMAT-0 small 4.300 / 4.212 / 4.233 / 4.302 (0.982); MP-0 medium 1.760 / 0.674 / 0.672 / 1.763 (0.382); OFF23-M water 0.892 / 0.883 / 0.872 / 0.889 (0.985); MH-1 1.349 / 1.322 / 1.322 / 1.362 (0.976); POLAR-1-S 1.307 / 1.111 / 1.125 / 1.295 (0.859).
- Gate and tests: PLAN.md's row "O38, the merge of `develop`" has the counts on both GPUs (accuracy gates of ten model cases PASS on `sm_120` and on `sm_89`).
- Not measured: step times on the RTX 4000 Ada; the tiled call's times and memory after the merge; LAMMPS step times on this library (the tests pass; the times of S145 / S146 are `develop`'s).
- Sources: [§6.36][s636]; `.tmp_o/mrg/ab_dev1.log`, `ab_dev2.log`, `ab_rel1.log` (not kept in the tree).

<a id="md-langevin-target"></a>
#### md-langevin-target: the thermostat's target on the device
- Switch: `LoupIntegrator.temp_rate_k_per_step` (0 = constant temperature). `src/integrator.cu` (`langevin_first_half_kernel`, `langevin_second_half_kernel`), `src/engine.cu` (`run_md_loop`, `d_langevin_target`).
- Status: DEFAULT on `release/v1`. 5060 Ti only.
- What: the noise amplitude sigma = sqrt(2 gamma kB T) was folded into three coefficients baked into the captured step, so every change of temperature captured the MD graphs again. Now the first half-kick reads the target from two doubles on the device and forms sigma itself; the second half-kick, which already advances the step counter, adds the call's rate to the target. The host writes the first step's target and the rate at the start of a call. A temperature schedule's calls reuse the graphs, and a ramp's target moves every step at the step's end point, as FastMACE's does. Constant-temperature results change at rounding level (sigma is formed in another order).
- Measured (15 November 2026, `python/bench_md.py`, library `6bd216e368ca63f0` against `9f89f02c26e7792a`): old first 1.817 / 8.015 against 1.802 / 8.024 ms (1.0085 / 0.9989); new first 1.792 / 8.009 against 1.803 / 8.059 ms (0.9943 / 0.9938). A tie.
- Measured, ramp (5,000 atoms `SrTiO3`, friction 0.02/fs, 200 to 400 K at 100 K/ps through `lm.Simulation`): mean kinetic temperature 296.6 K for a mean target of 301.0 K; 7.985 ms/step on the ramp against 7.839 on the hold before it.
- Gate: `python/test_gate.py` PASS, worst force ratio 1.56, stress 1.73 (the force path is unchanged). `tests/test_md_graph_reuse.py`: a run whose temperature changes with every call captures as many graphs as one at constant temperature.
- Sources: [§6.2][s62]; `tests/test_schedule_gpu.py`.

<a id="md-fixed-atoms"></a>
#### md-fixed-atoms: fixed atoms without a changed kernel
- Switch: `loup_set_fixed_atoms(h, mask)`; `src/engine.cu` (`set_fixed_impl`), `src/thermo.cu` (the row's degrees of freedom).
- Status: DEFAULT on `release/v1`. 5060 Ti only.
- What: a fixed atom gets zero inverse mass, zero 1/sqrt(m) and zero velocity on the device, so the velocity-Verlet and Langevin kernels leave it in place as they are; masses stay, so the kinetic energy of the others is unchanged. The temperature of the thermo rows and of the run statistics divides by 3 (N - n_fixed).
- Measured (15 November 2026, `python/bench_md.py`, library `6c2af2c880580942` against `6bd216e368ca63f0`): old first 1.0124 / 1.0011 and 1.0050 / 1.0008; new first 1.0009 / 0.9986 and 0.9946 / 0.9973; mean 1.0032 / 0.9995. A tie: the step's kernels and their arguments are the same.
- Gate: `python/test_gate.py` PASS, worst force ratio 1.54, stress 1.68. `pytest`: 458 passed.
- Sources: [§6.3][s63]; `tests/test_fixed_atoms_gpu.py`.

<a id="md-fix-com"></a>
#### md-fix-com: the centre of mass at rest, and the noise coefficients once per step
- Switch: `LoupIntegrator.fix_com`; `IntegratorConfig.fixcm`, `lm.integrators.*(fixcm="auto")`. `src/integrator.cu` (`langevin_noise_kernel`, `langevin_first_half_fixcom_kernel`, `momentum_sum_kernel`, `momentum_remove_kernel`), `src/engine.cu` (`run_md_loop`).
- Status: DEFAULT for `lm.md` and `lm.Simulation` (`fixcm="auto"` is on without fixed atoms, as in FastMACE); off for `loup_run_langevin`, `loup_run_nve` and `bench_md.py`. 5060 Ti only.
- What: with `fix_com` the Langevin noise of a step is drawn by a kernel of its own that also sums m_i times both random terms over the atoms; the half-kick subtracts the mass-weighted mean, so the thermostat puts no momentum into the centre of mass (FastMACE's `mass_weighted` projection, canonical for unequal masses). NVE removes the total momentum once per run call. The temperature then counts 3N - 3 degrees of freedom. Without `fix_com` the step is the one of before. In both variants the noise coefficients (ASE's c3, c4, c5 without the mass factor) are now formed by the first thread of the second half-kick for the next step and read from the device, so the first half-kick does per atom what it did before the ramp of `md-langevin-target`.
- Measured (15 November 2026, `python/bench_md.py`, library `7c835aab4e62167d` against the merge build `9f89f02c26e7792a`): merge first 1.0064 / 0.9982 and 1.0047 / 1.0005; new first 0.9965 / 0.9964 and 0.9919 / 0.9976; mean 0.9999 / 0.9982. A tie: Stages 1 to 4 so far cost nothing on the standard benchmarks.
- Measured, `fix_com` on against off (5,000 atoms `SrTiO3`, Langevin through `lm.Simulation`, a b b a): 1.0009; on the build before 0.9995. Total momentum after 500 steps on 135 atoms: 1.6e-15 of sqrt(M kB T) with `fix_com`, 1.40 without.
- Gate: `python/test_gate.py` PASS, worst force ratio 1.55, stress 1.64.
- Not measured: `fix_com`'s cost on the 1,944-atom cell; anything on the RTX 4000 Ada.
- Sources: [§6.4][s64]; `tests/test_fix_com_gpu.py`.

<a id="md-csvr"></a>
#### md-csvr: CSVR in the captured step
- Switch: `LOUP_CSVR` in `LoupIntegrator`; `lm.integrators.CSVR`, `loupmd md --thermostat csvr --tau FS`, `loupmd.ase.md.Bussi`. `src/integrator.cu` (`csvr_draw`, `csvr_alpha_kernel`, `csvr_first_half_kernel`), `src/engine.cu` (`run_md_loop`, kind 2).
- Status: DEFAULT for CSVR runs. 5060 Ti only.
- What: ASE 3.27's `Bussi` step. Before the half-kick the kinetic energy is summed, one thread draws a normal and a chi-square variate (Marsaglia-Tsang on Philox, offset by the device step counter), forms alpha of equation A7 and adds (alpha^2 - 1) K to the transferred energy, and the half-kick multiplies the velocities by alpha. The target is the device scalar of `md-langevin-target`, so ramps move it and a changed target captures nothing. The state block's header gained 64 slots for an integrator's scalars (640 bytes instead of 120), so the transferred energy, and with it the conserved quantity, survives a restart.
- Measured (15 November 2026): with the engine's noise ASE's `Bussi` gives the same positions to 2.5e-7 A after 200 steps; three runs of 20,000 steps on 135 atoms give Kolmogorov-Smirnov p = 0.886, 0.605, 0.639 against the canonical distribution and a conserved-quantity drift of at most 0.0003 meV/atom/ps. Cost against Langevin at 5,000 atoms: 1.0029.
- Gate: `tools/dev/test_gate.py` PASS, worst force ratio 1.57, stress 1.55.
- Not measured: the full suite on this build (the crash of 12:32); anything on the RTX 4000 Ada.
- Sources: [§6.5][s65]; `tests/test_csvr_gpu.py`.

<a id="md-skin-auto"></a>
#### md-skin-auto: the skin from the largest step
- Switch: `lm.md(skin="auto")` (the default), `loupmd md --skin`, `lm.Simulation(skin="auto")`; `loupmd/skin.py`; `loup_get_step_displacement` (`src/engine.cu`).
- Status: DEFAULT for `lm.md`, `loupmd md` and the ASE drop-ins; `lm.Simulation` and the engine keep 0.5 A unless asked. 5060 Ti only.
- What: the pipelined loop runs while four times the largest per-step displacement is below half the skin, which hydrogen at 300 K and 1 fs misses at 0.5 A (ledger S46). The skin is estimated before the run from the highest target, the lightest atom and the timestep (5 sqrt(kT / m) dt, or the fastest atom now) and corrected once, after 200 steps near that target, from the engine's own displacement tracker: ten times the largest step on a 0.05 A grid within 0.5 to 1.5 A. The correction sets the system again with the new skin and moves the state block across. The skin decides speed only: the engine checks its list against it in every step.
- Measured (15 November 2026, water 216, MACE-OFF23 small, Langevin 300 K, 1 fs): skin 0.5 A: 0 of 800 steps pipelined, 0.676 ms/step; auto: estimate 0.8 A, measured step 0.079 A, skin 0.8 A, 799 of 800 pipelined, 0.556 ms/step. `SrTiO3` (largest step 0.014 A) keeps 0.5 A.
- Not measured: other light-atom systems and models; the upper bound of 1.5 A (the only point on file is S46's water at 1.5 A: 2.90 against 3.13 ms/step); anything on the RTX 4000 Ada.
- Sources: [§6.5][s65]; `tests/test_skin.py`, `tests/test_skin_gpu.py`.

<a id="md-nose-hoover"></a>
#### md-nose-hoover: the Nose-Hoover chain in the captured step
- Switch: `LOUP_NHC` in `LoupIntegrator` (`tau_t_fs`, `chain_length`, `chain_loops`, `mass_temp_k`); `lm.integrators.NoseHooverChain`, `loupmd.ase.md.NoseHooverChainNVT`. `src/integrator.cu` (`nhc_half_kernel`, `scale_velocities_kernel`), `src/engine.cu` (`run_md_loop`, kind 3).
- Status: DEFAULT for Nose-Hoover runs. 5060 Ti only.
- What: ASE 3.27's `NoseHooverChainNVT`. Each half step sums the kinetic energy, one thread integrates the chain (Suzuki-Yoshida weights times `tloop`, the kinetic energy carried along analytically) and returns one factor, and a kernel scales the velocities by it. The chain's variables are in the integrator's state slots, so they travel in the state block; the thermo row's conserved quantity adds the chain's energy. The thermostat masses come from their own temperature, so a ramp of the target captures nothing.
- Measured (15 November 2026): positions within 2.1e-7 to 2.5e-7 A of ASE's after 200 steps for chains of 3 x 1, 1 x 1 and 5 x 2; 20,000 steps: drift +0.0002 meV/atom/ps. Cost against Langevin at 5,000 atoms: 1.0067 (medians of four runs of 400 steps each; single runs scatter by about 2%).
- Gate: `tools/dev/test_gate.py` PASS on this build, default and `--specialised`.
- Not measured: anything on the RTX 4000 Ada or an A100.
- Sources: [§6.6][s66]; `tests/test_nhc_gpu.py`.

<a id="md-berendsen-nvt"></a>
#### md-berendsen-nvt: Berendsen NVT in the captured step
- Switch: `LOUP_BERENDSEN_NVT` (`tau_t_fs`); `lm.integrators.Berendsen`, `loupmd.ase.md.NVTBerendsen`. `src/integrator.cu` (`berendsen_scale_kernel`), `src/engine.cu` (kind 4).
- Status: DEFAULT for Berendsen runs. 5060 Ti only.
- What: ASE's `NVTBerendsen`: before the velocity-Verlet step the velocities are scaled by sqrt(1 + (T0 / T - 1) dt / tau), kept within [0.9, 1.1]. One kinetic-energy sum, one thread, one scaling. A time constant below the timestep is refused.
- Measured (15 November 2026): positions within 2.0e-7 and 2.1e-7 A of ASE's after 200 steps (tau 50 fs; tau 2 fs from 900 K).
- Not measured: its cost against Langevin (it has two small nodes fewer than the Nose-Hoover step, which costs 1.0067); anything on the RTX 4000 Ada.
- Sources: [§6.6][s66]; `tests/test_berendsen_gpu.py`.

<a id="min-lbfgs-device"></a>
#### min-lbfgs-device: LBFGS on the device
- Switch: `loup_minimize` (`LoupMinimizer`, `LoupMinStats`), `LoupEngine.minimize`; `lm.optimize.relax` with `LBFGS` at fixed cell. `src/minimize.cu`, `src/engine.cu` (`minimize_impl`). `LOUP_MIN_AHEAD=0|1` (testing) forces the list check before or after the force pass.
- Status: DEFAULT for LBFGS at fixed cell. FIRE and cell relaxations run on host arrays. 5060 Ti only.
- What: ASE 3.27's LBFGS without line search in matrix form. The history S, Y is a ring on the device; one pass over it gives the five products per row the host needs, the host solves the two triangular systems of at most `memory` unknowns, a second pass forms the direction, and a kernel moves the atoms.
- Three versions, optimiser's own time at 5,000 atoms after 40 steps (history up to 39 pairs): on the host 1.4 ms a step, 17% of the force calls; on the device with pageable copies and two host waits per step 0.825 ms, 9.70% (the kernels were not the cost: three synchronous downloads, three uploads and a second wait for the list check); with pinned buffers, one wait per step and the list check after the force pass 0.141 ms, 1.71%. A whole step: 10.7, 9.1 and 8.2 ms.
- The list check: where the displacement since the list was built plus twice the last step is inside half the skin, the force pass is launched at once and the measured displacement arrives with the next step's downloads; a pass that ran on an outdated list is run again. With a skin of 0.2 A and a rattle of 0.12 A: 5 rebuilds in 30 steps; forced to check afterwards 5 passes are repeated, by the engine's choice none.
- Gate: not a force-path change; `tools/dev/test_gate.py` PASS on this build.
- Not measured: relaxations of other systems and sizes; the cost at small cells, where a host wait is a larger part of a step; anything on the RTX 4000 Ada.
- Sources: [§6.6][s66]; `tests/test_optimize_gpu.py`; PLAN.md D30, D43, D44.

<a id="md-variable-cell"></a>
#### md-variable-cell: the variable-cell step
- Switch: none for users: the step of every integrator with a barostat. `LOUP_VARIABLE_CELL=1` sends a fixed-cell integrator through it and `LOUP_DEBUG_CELL_RATE=r` scales cell and positions by 1 + r per step (tests). `src/cell.hpp`, `src/cell.cu`, `src/engine.cu` (`run_md_loop`, `rebuild_neighbors`, `upload_cell_dev`, `download_cell_dev`).
- Status: DEFAULT for runs with a barostat. 5060 Ti only.
- What: the cell is a struct on the device. A rebuild leaves the edges' integer image shifts in the edges' order in its own scratch arrays (no extra memory), and each step forms the Cartesian shifts from them and the cell of the step before its force pass, which carries stress. The list check measures an atom's displacement from where the cell's deformation F has taken its reference position and compares it with (r_list (1 - |F - 1|) - r_max) / 2, half the skin for an undeformed cell. The host's cell follows the device's before a rebuild and at the end of a call. A volume outside [V0 / 20, 20 V0] stops the run.
- Not pipelined: the step waits for the host once (the list check). Measured against the pipelined fixed-cell step, Langevin at 5,000 atoms, constant cell: 1.0296 and 1.0263.
- Fixed-cell runs: unchanged graph; `bench_md.py` against the build before, both orders: generic `NbCl5` 0.9998 / 1.0007, `SrTiO3` 1.0015 / 1.0001; specialised 1.0105 / 0.9973 and 1.0028 / 0.9995.
- Gate: PASS, default and `--specialised`.
- Not measured: the three parts of the extra cost apart; a fused variant that forms the shifts where the edge vectors are computed (saves the 24 bytes per edge written and read); pipelining; anything on the RTX 4000 Ada.
- Sources: [§6.7][s67]; `tests/test_variable_cell_gpu.py`; PLAN.md D49.

<a id="md-berendsen-npt"></a>
#### md-berendsen-npt: Berendsen NPT
- Switch: `LOUP_BERENDSEN_NPT` (`pressure_gpa`, `tau_p_fs`, `compressibility_per_gpa`, `cell_mode`, `cell_mask`); `lm.integrators.Berendsen(pressure_GPa=..., taup_fs=..., compressibility_per_GPa=..., mask=...)`, `loupmd.ase.md.NPTBerendsen`, `Inhomogeneous_NPTBerendsen`. `src/cell.cu` (`berendsen_npt_kernel`, `kinetic_diag_kernel`).
- Status: DEFAULT for Berendsen NPT runs; experimental. 5060 Ti only.
- What: ASE 3.27's `NPTBerendsen` and `Inhomogeneous_NPTBerendsen` with one force call per step (ASE: two; PLAN.md D48). After the thermostat's scale one thread forms the barostat's factors from the last force pass's virial and the scaled velocities' ideal-gas part; atoms and cell are scaled, then the half-kick and the drift.
- Measured (15 November 2026, `SrTiO3` 3x3x3 from 10 GPa above the target): volume within 2e-8 relative of ASE's class taken with one force call per step after 200 steps, 1.1e-5 of ASE's own class.
- Not measured: its step time (the variable-cell step of `md-variable-cell` plus one single-thread kernel and, per axis, one kinetic sum); other systems; anything on the RTX 4000 Ada.
- Sources: [§6.7][s67]; `tests/test_berendsen_npt_gpu.py`, `tests/test_simulation_npt.py`.

<a id="md-baoab-npt"></a>
#### md-baoab-npt: Langevin BAOAB NPT
- Switch: `LOUP_BAOAB_NPT` (`friction_per_fs` = 1 / T_tau, `tau_p_fs` = P_tau, `pressure_gpa`, `cell_mode`); `lm.integrators.LangevinBAOAB`, `lm.md(ensemble="NPT")`, `loupmd md --ensemble NPT`, `loupmd.ase.LangevinBAOAB`. `src/integrator.cu` (`baoab_cell_first_kernel`, `baoab_first_kernel`, `kinetic_tensor_kernel`, `baoab_cell_second_kernel`).
- Status: DEFAULT for NPT runs; experimental. 5060 Ti only.
- What: ASE 3.27's `LangevinBAOAB` with a barostat. One thread kicks the barostat, forms the cell's two half steps and the O step's matrix (friction plus the barostat's drag), and applies the barostat's own friction and noise; one kernel per atom does B, the cell's half step, A, O, A, the cell's half step; after the force pass the cell force comes from the kinetic tensor, the virial and the volume. Barostat momentum and cell force travel in the state block.
- Measured (15 November 2026): without noise 100 steps equal ASE's to 2.4e-9 of the cell's length; `SrTiO3` 5x5x5 at 300 K and 1 GPa over 20,000 steps: 1.000 +- 0.001 GPa, 299.3 +- 0.4 K.
- Not measured: its step time; anything on the RTX 4000 Ada.
- Sources: [§6.8][s68]; `tests/test_baoab_gpu.py`; PLAN.md D53.

<a id="md-mtk-npt"></a>
#### md-mtk-npt: Martyna-Tobias-Klein NPT
- Switch: `LOUP_MTK_NPT` (`tau_t_fs`, `tau_p_fs`, `chain_length`, `chain_loops`, `p_chain_length`, `p_chain_loops`, `mass_temp_k`, `cell_mode`); `lm.integrators.MTK`, `loupmd.ase.IsotropicMTKNPT`, `MTKNPT`. `src/integrator.cu` (`mtk_first_kernel`, `mtk_first_atoms_kernel`, `mtk_kick_kernel`, `mtk_second_kernel`).
- Status: DEFAULT for MTK runs; experimental. 5060 Ti only.
- What: ASE 3.27's `IsotropicMTKNPT` and `MTKNPT`. Per half step one thread integrates both Nose-Hoover chains and kicks the cell from the stress with the ideal-gas part; the atoms' kick and drift are two 3 x 3 matrices each (exp and exprel of the cell momentum, a Horner series with scaling and squaring where ASE diagonalises).
- Measured (15 November 2026): volume within 3.5e-10 relative of ASE's after 200 steps; conserved quantity drift 0.0002 meV/atom/ps over 20,000 steps.
- Not measured: its step time; anything on the RTX 4000 Ada.
- Sources: [§6.8][s68]; `tests/test_mtk_gpu.py`; PLAN.md D54.

<a id="md-small-systems"></a>
#### md-small-systems: small-system latency
- Status: NOT BUILT (open).
- Measured: 135-atom `SrTiO3` step 358 us: GEMM groups 115 us (32%; ~25 tiny products at ~6-13 us each regardless of size), edge-tiled `w'` 100 us, spline 58 us, i0 backward 28 us. Tried and rejected: gemm-split-k-own, gemm-grouped-launch, spl-edge-split.
- Sources: [§4.1 #3][s41].

<a id="md-langevin-draw-threads"></a>
#### md-langevin-draw-threads: one thread per normal pair in the Langevin first half
- Switch: `src/integrator.cu` `langevin_first_half_kernel`, launched with 96 threads per 32 atoms by `run_md_loop` (`src/engine.cu`).
- Stage: S106 (16 November 2026), 5060 Ti.
- What: one thread per atom drew its three normal pairs with `curand_normal2_double` (double-precision Box-Muller, 1/64 rate on GeForce) one after another: 7.8 us per step on water216 (648 atoms in 21 one-warp blocks, a latency chain) and 10.4 us on SrTiO3 (5,000 atoms). Thread (atom, c) now draws pair c at Philox offset `step * 16 + 4 c`, the same 32-bit words the c-th sequential call consumed, stages it in shared memory, and then updates component c of its atom (contiguous accesses).
- Measured (5060 Ti): kernel 7.8 -> 3.6 us (water216, `nsys`). Standalone check (`.tmp_o/lang_check.cu`: the old and new kernels on the same random inputs, N = 1, 31, 32, 33, 216, 648, 5,000 and 5,003): positions, velocities and saved noise bitwise identical. Library ABBA on shared plans, 3 rounds, S105 -> S105 + S106: POLAR-1-S NaCl216 `0.990` (`0.986` / `0.994`), OMAT-0 generic SrTiO3 `0.997` (`0.997` / `0.997`), OFF23-S water216 `0.990` (`0.979` / `1.002`), OFF23-M water216 `1.000`, MH-1 NaCl216 `1.000`. With S105, S101 -> S106: OMAT-0 generic `0.9985`, OFF23-M water216 `0.991`, MH-1 NaCl216 `0.993`, each faster in both orders.
- A100: queued (job `s106c`, [results/alex-a100-queue-20261116](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/alex-a100-queue-20261116/README.md)).
- Status: DEFAULT.
- Sources: this file.

<a id="comp-active-edge-tighten"></a>
#### comp-active-edge-tighten: active-edge compaction pass
- Status: NOT BUILT.
- What: `compute_and_count_active` (47 us) + `DeviceScan::ExclusiveSum` + `scatter_active_edges` (54 us) take ~101 us/step on 5060 Ti `SrTiO3`, writing and re-reading `d_tmp_vec_len`. Note single-pass decoupled look-back compaction (`edge-compaction-1pass`) was already rejected as an MD tie.
- S102 falsifier (16 November 2026, 5060 Ti, reverted): one block of 1,024 threads scanning the offsets (one launch) instead of CUB's two kernels, for systems up to 64 Ki atoms, after S100 showed a single removed node worth 1.3% on OFF23-M water216. Library ABBA on shared plans, 3 rounds: OFF23-M water216 `0.994` (`0.995` / `0.993`), OFF23-S water216 `1.008` (`1.010` / `1.007`), MH-1 NaCl216 `1.002` (`1.004` / `1.000`), POLAR-1-S NaCl216 `1.001`: CUB's decoupled scan over many blocks beats one block even at 216-648 atoms; not kept.
- Sources: `OMAT0_SPEEDUP_BRIEF.md`.

<a id="nl-bin-skip"></a>
#### nl-bin-skip: bins that cannot hold a candidate skipped in the neighbour build
- Switch: `src/neighbors.cu` `scan_neighbor_bins`, used by `count_neighbors_kernel` and both passes of `fill_neighbors_kernel` (the lane-group build: sm_120 and compute capability 8.0, `nb_groups_ok`); the one-thread kernels are unchanged.
- Stage: S120 (18 November 2026), 5060 Ti. From the owner's review list of 17 November; built after the profile below showed the build at 4.9% of the smallest benchmark.
- What: along each cell axis the atom sits at u_a (bin units) inside its own bin; a bin at offset o lies at least L_a = (o > 0 ? o - u_a : o < 0 ? u_a - o - 1 : 0) bin heights h_a / n_a away (h_a the lattice-plane spacing, 1 / |column a of inv(cell)|), so the bin is at least max_a L_a away, and sqrt(sum_a L_a^2) away in an axis-aligned orthogonal cell. A bin whose bound reaches `r_hi^2` (the float pre-test's radius: r_list plus a margin of at least 0.01 A) is skipped before its image shift, bin offsets and candidates: it holds no atom within r_list, so every row and its order are unchanged, and count and fill skip the same bins. All in float; the bound's rounding (~1e-5 A at 100 A positions) is far inside the margin. A first version computing u_a and the bin heights in double per atom (S120a; FP64 is 1/64 rate on the 5060 Ti) measured OFF23-M water216 `1.0053` and OFF23-S `0.997` (mixed orders).
- Profile before (`nsys`, 256-step MD segments, HEAD + S115): the neighbour build was 4.9% of OFF23-S water216's kernel time (24.3 us per step: fill 15.3, count 6.2; 55 rebuilds in 256 steps), 2.2% of OFF23-M water216, 0.7% of OFF23-L water216, 1.05% of OFF24-M water (5,184 atoms), 0.26% of OMAT-0 SrTiO3, 0.1-0.2% of POLAR-1-S. With OFF's 5.5 A list radius the water216 cell has 5 bins of 3.7 A per axis and the +-2 stencil scans every bin, while the list sphere covers ~11% of that volume.
- Measured (5060 Ti, S121 -> S121 + S120; `nsys` per MD step, two runs each): OFF23-S water216 fill 15.2 / 15.2 -> 14.5 / 14.0 us, count 6.2 / 6.2 -> 5.8 / 5.8; OFF23-M water216 build 26.1 / 25.4 -> 24.4 / 24.7; OFF24-M water 107.3 / 104.7 -> 104.9 / 104.4. Far less than the skipped volume suggests, so the candidate tests are not what bounds these kernels. Library ABBA on shared plans: OFF23-S water216 `0.9881` (`0.9981` / `0.9782`, 4 rounds, noisy at 0.36 ms per step), OFF23-M water216 `0.9957` (`0.9975` / `0.9938`, 3 rounds).
- Results (rattled cell, one evaluate, against S121; S121 against itself in brackets): OFF23-S water216 max dF 3.9e-6 (3.3e-6) eV/A, MH-1 NbCl5 (a non-orthogonal cell) 5.1e-7 (6.3e-7).
- Tests and gates (S120a, the same skip test): `tests/test_engine.py -k "skin or rebuild"` 6 passed; OFF23-S organic 8 / 8, MH-1 crystals 18 / 18.
- Status: DEFAULT (5060 Ti only; the A100 runs the same lane-group kernels, not measured).
- Sources: this file.

### Generic path

Families: MACE-OMAT-0 small, MACE-OFF23 S / M / L, OFF23b M, OFF24 M, MACE-MH-1 (any head), MACE-POLAR-1 S / M / L.
The first entries below are design decisions of the first version (12-13 November 2026), not A/B-timed against an
alternative; the S7 entries from gen-fork-zero-slab on carry ABBA measurements (5060 Ti only).

<a id="gen-probe-export"></a>
#### gen-probe-export: probe-based weight extraction
- Switch: `python/export_generic.py` (exporter version 2), `python/export.py` dispatcher.
- What: every linear map extracted by probing the float64 e3nn modules with basis inputs, so path weights, `1/avg_num_neighbors`, normalize2mom constants, ScaleShift and the head are folded numerically; conv paths checked to be multiples of `wigner_3j` with the factor folded into the radial table.
- Status: DEFAULT.
- Sources: [§5.1][s51].

<a id="gen-pair-sym"></a>
#### gen-pair-sym: symmetric radial pair tables
- Switch: bundle meta `pair_sym`.
- What: blocks whose radial MLP does not embed sender and receiver separately get one table per unordered species pair.
- Status: DEFAULT.
- Measured: bundle size not recorded against the ordered-pair version. Models with nonlinear (ordered-pair) blocks stay large: MH-1 74-200 MB, POLAR-1-L 790 MB for 3 species.
- Sources: [§5.1][s51], [§5.5][s55].

<a id="gen-first-layer"></a>
#### gen-first-layer: layer 0 as an outer sum over the radial chain's columns
- Switch: `first_fwd_kernel` / `first_bwd_kernel`; bundle meta `first_hidden`, `J = H + 2`.
- What: layer 0's input is the species embedding, so the conv weights, the layer input, the path factors and the message linear fold into one matrix per degree; the per-edge table holds the radial chain's columns (66) instead of 4C + 1 weights.
- Status: DEFAULT.
- Measured: OMAT-0 small bundle 40 MB; speed against the plain conv not measured. In the MH-1 profile the first-layer kernels are 5% of the step.
- Sources: [§5.1][s51], [§5.5][s55].

<a id="gen-factored-products"></a>
#### gen-factored-products: factored symmetric contractions
- Switch: `gprod_fwd_<sig>` / `gprod_bwd_<sig>` (three configurations generated by `python/gen_generic.py`).
- What: FastMACE's factored program (`sc_factored.factor` / `fold_weights`), one kernel per program signature.
- Status: DEFAULT. Measured: products 5% of the MH-1 step. Sources: [§5.1][s51], [§5.5][s55].

<a id="gen-certified-spline"></a>
#### gen-certified-spline: certified radial splines
- What: FastMACE's cubic-Hermite spline fit per species pair; the export refuses a certificate above 1 (spline error above the float32 network's own rounding error on `radial.certify`'s points).
- Status: DEFAULT. Sources: [§5.1][s51].

<a id="gen-profile"></a>
#### gen-profile: generic-path profile
- What: nsys over 200 Langevin steps, MH-1 `omat_pbe`, `SrTiO3` 5,000 atoms, 5060 Ti, 46.9 ms per step.
- Status: MEASUREMENT.
- Measured: SIMT SGEMMs ~50% (cuBLAS CUTLASS SIMT kernels 39%, own SGEMM 8%, magma 2%), `gconv_bwd_L1` 11.7%, `gconv_fwd_L1` 7.9%, gate backward 9.6%, gate forward 4.7%, first-layer kernels 4.7%, products 4.6%.
- Sources: [§5.5][s55].

The entries below are speed work of 13 November 2026 (stage S7), A/B-timed on the RTX 5060 Ti only: the owner
ruled the workstations out (planned power outage), so none of them has an Ada measurement. Method:
`.tmp_o/ab_fam.py` (`bench_family.py` protocol, one process per side, order a b b a; b/a < 1 is faster).
Cells: OMAT-0 small `SrTiO3` 5,000 atoms; OFF23 medium `water_216` (648) and water 2x2x2 (5,184); MH-1 `SrTiO3`;
POLAR-1 NaCl 3x3x3 (216) and POLAR-1-M `NbCl5` 3x3x3 (1,944).

<a id="gen-fork-zero-slab"></a>
#### gen-fork-zero-slab: GEMM lanes, one zero slab, dead stores
- Switch: `GenericPassInputs::gemm_fork / gemm_lane / gemm_join` (engine side streams), passed into `PolarLR::record`; `GenericModel::d_zero_slab_`, `PolarLR` `bwd_zero_slab`.
- Stage: S7.
- What: the per-degree and per-species GEMMs of each layer, and the source / mixer / readout GEMMs of the long-range part, run on the engine's side streams; the per-step gradient accumulators sit in one slab cleared by one memset; `gate_bwd_kernel` no longer stores `dp` buffers that are never read (layer 0, l = 3) and the dead `dnw[2]` is gone.
- Status: DEFAULT.
- Measured (b/a against the build before, which already had pol-sf-f32): OMAT-S 0.987, OFF23-M 0.961 / 0.990, MH-1 0.975, POLAR-1-S 0.918, POLAR-1-M 0.974 / 0.963 (NaCl / `NbCl5`), POLAR-1-L 0.914. Gates: all families PASS; 47 tests pass.
- S80 falsifier (16 November 2026, 5060 Ti, reverted): `nsys` of OMAT-0 medium generic SrTiO3 shows the slab's memset (12.8 MB: layer 1's `dx` and the S73 energy-fold `dy[0]`) running alone for 21-33 us per step, plus `zero_edge_kernel` 9 us. Both moved to a forked side stream beside `gather_rows` / `first_fwd_kernel` (the first join comes before any reader): library ABBA on shared GEMM plans, 3 rounds, OMAT-0 generic SrTiO3 `1.000`, MP-0 medium SrTiO3 `1.001`, MH-1 SrTiO3 `1.001`, OFF23-M water216 `0.996`, OFF23-S water216 `1.005`: the overlapped writes cost the forward what they save.
- S89 falsifier (16 November 2026, 5060 Ti, reverted): the same memset issued first in the engine's force pass, before the edge compaction (the specialised OMAT-0 path's 10.4 MB tail memset takes 9 us there against the generic slab's 35 us after the compaction). Library ABBA on shared GEMM plans, 3 rounds: OMAT-0 generic SrTiO3 `0.999`, MP-0 medium SrTiO3 `1.001`, MH-1 SrTiO3 `1.000`, OFF23-M water216 `1.002`, POLAR-1-M NaCl216 `0.996`: a tie, the zeroing cost moves to the kernels that follow.
- Sources: this file (commit `1310ddc`).

<a id="gen-cublas-stream"></a>
#### gen-cublas-stream: cuBLAS fallback on the lane's stream
- Switch: `sgemm_rm` in `src/engine.cu`.
- Stage: S7.
- What: GEMMs with a non-packed layout (POLAR's strided `Wpot` / `Wq` column blocks) fall back to `cublasSgemm`, which ran on the main stream even when a fork lane was selected, so it raced the side-stream GEMMs writing its operands.
- Status: FIX (found by the gate after gen-fork-zero-slab).
- Measured: POLAR-1-M crystals gate force / stress ratios 1.4e4-4e5 (energies off by 15-145 meV/atom) -> every row PASS (worst 0.72 / 0.72).
- Sources: this file.

<a id="gen-skip-fold"></a>
#### gen-skip-fold: skip-message and readout-tail folds
- Switch: `GenericLayer::skip_folded` (blocks of kind agnostic / density), `GenericLayer::ro_folded` (last layer, scalar output, no long range, MLP readout).
- Stage: S7.
- What: the per-species `W_skip_msg` that follows the message linear is folded at load (in float64) into a per-species `W_lin` (and `C0` for the first layer), removing one species GEMM per degree in each direction; on the last layer `hout = y W_p + h_in W_sc` feeds only the readout's first linear, so `W_p ro_W1` and `W_sc ro_W1` replace three GEMMs by two narrower ones. Exactness checked on CPU against MACE float64 (OMAT-S 4.9e-6 meV/atom, 4.1e-8 eV/A; OFF23-M 1.3e-5, 4.2e-8).
- Status: DEFAULT.
- Measured: OMAT-S 0.947, OFF23-M 0.939 / 0.956, MH-1 0.991. Gates PASS (OMAT-S worst force 0.91, OFF23-M 0.21, MH-1 0.64); 47 tests pass.
- Sources: this file (commit `7fff54d`).

<a id="gen-conv-v2"></a>
#### gen-conv-v2: conv and first-layer kernels rewritten
- Switch: `python/gen_generic.py` -> `gconv_fwd_L{0,1,2}<R, PAIR>`, `gconv_bwd_L{0,1,2}<WANT_DX>`; `first_fwd_kernel`, `first_bwd_kernel` in `src/generic.cu`.
- Stage: S7.
- What: (1) the conv tables are re-packed at load into the specialised path's 8-byte cubic format (`CUBIC_PACKED8`, 5-bit shared exponent; error 1e-4 to 1.8e-3 of each interval's largest value on every cached bundle, CPU check), with the edge density in its own `float4` table; (2) the forward stages each 32-edge tile's sender, spline offset and SH in shared memory, 4 (lx 0) or 2 (lx 1) receivers per block at C = 128, paired decode of edges sharing a slab; (3) the backward of lx 0 / 1 uses the late pull-back of FastMACE's `wprime_pullback` (q = M g staged per channel, geometry differentiated once per edge from 4 warp-reduced scalars; formulas checked against e3nn autograd to 1e-15 for all 14 paths), lx 2 keeps the per-channel SH gradient with a 16-shuffle fold, one warp per edge, no atomics on `edge_dvec`; (4) the first layer stages SH per 32-edge tile in the forward and walks edges per warp in the backward. Zero spills at the chosen bounds (`ptxas -v`, `sm_120`).
- Status: DEFAULT.
- Measured: OMAT-S 0.688, OFF23-M 0.789 / 0.753, MH-1 0.907, POLAR-1-S 0.987, POLAR-1-M 0.968 / 0.982, POLAR-1-L 0.971. Gates PASS for OMAT-S (worst force 1.23), OFF23-S, OFF23-M, MH-1, POLAR-1-S / -M (worst 1.71); 47 tests pass.
- Sources: this file (commit `3e526d5`).

<a id="gen-skinny-gemm"></a>
#### gen-skinny-gemm: own kernels for skinny products
- Stage: S7.
- What: `sgemm_rm` routed every product with N <= 16 or K <= 16 (any strides) to two own kernels: N <= 16 with eight warps splitting K over 4 rows and a fixed-order reduction; K <= 16 with one thread per output. Target: the strided POLAR `Wpot` / `Wq` products (`cublasSgemm` fallback, `magma_sgemmEx` 55-93 us each at 216 atoms; a 216 x 8 output with K = 2560 got a handful of CTAs).
- Status: REJECTED.
- Measured: the POLAR launches dropped to ~7 us each (nsys), but OMAT-S's packed N = 16 / K = 16 products at 5,000 rows ran 32-45 us against ~16 us for the cuBLAS / hybrid tiles. ABBA b/a: OMAT-S `SrTiO3` 1.040, POLAR-1-M `NbCl5` 1.009, OMAT-M `SrTiO3` 1.016 (the specialised path's two `skip16` products took the route; it never runs `first_bwd`). POLAR-1-M crystals gate passed (worst 1.27).
- Why: unconditional routing loses on large-M shapes; a per-call tuner candidate repeats [gemm-group-policy](#gemm-group-policy). A retry should be one static rule for the strided long-K shapes only, judged by MD A/B.
- Sources: this file.

<a id="gen-first-bwd-tail"></a>
#### gen-first-bwd-tail: batched first-layer backward tail
- Stage: S7.
- What: `first_bwd_kernel` ran `sh16_grad` and the force projection on lane 0 once per edge; each warp instead buffered 32 edges' reduced `dY[16]` and `er` in shared memory (17 KB per block) and finished them one edge per lane. Arithmetic unchanged.
- Status: REJECTED.
- Measured: ABBA b/a against gen-skinny-gemm: OMAT-S `SrTiO3` 1.040, OFF23-M water 2x2x2 1.017.
- Why: [INFERENCE] the kernel's `G` and table reads rely on L1, and the 17 KB buffer costs carveout and resident blocks; the serial tail was not the limiter.
- Sources: this file.

<a id="gen-conv-l2-split"></a>
#### gen-conv-l2-split: late pull-back for the lx 2 backward's degree <= 1 paths
- Switch: `emit_conv_bwd_lp(2)` -> `gconv_bwd_L2lp`, `emit_conv_bwd_L2(groups=(2,))` -> `gconv_bwd_L2` in `python/gen_generic.py`; `launch_conv_bwd` runs both (the first owns the density term, the second gets `dD = nullptr`).
- Stage: S8.
- What: the ten paths of x degree <= 1 are exactly lx 1's path set, so lx 1's late pull-back kernel indexed into the 17-path table covers them; the seven x degree 2 paths (no Cartesian form, as in FastMACE's `wprime_pullback`) keep the per-channel SH gradient. Falsifier first: with either group removed the old kernel took 7.15 ms (degree <= 1) and 6.92 ms (degree 2) of 13.9 ms on OFF23-L water.
- Status: DEFAULT.
- Measured: OFF23-L water backward 13.59 ms -> 4.46 + 7.47 ms per call (nsys, frozen cell); ABBA b/a 0.925 (33.91 -> 31.36 ms/step). Forces vs S7: 9.8e-7 eV/A (run-to-run 2.1e-6). OFF23-L organic gate PASS (worst stress 1.94).
- Sources: this file.

<a id="gen-first-fwd-race"></a>
#### gen-first-fwd-race: species-segment end in parity slots
- Stage: S8 (review T2, `loupmd-review-20261112.md`).
- What: `first_fwd_kernel` kept a receiver's species-segment end in one shared int; when a species had no edge no barrier separated the other warps' read from thread 0's write for the next species. Now `s_ee[s & 1]`: the next barrier bounds thread 0's lead to one slot.
- Status: FIX.
- Measured: forces unchanged at noise level (OMAT-S, MH-1, OFF23-M, POLAR-1-S). `tests/test_families.py::test_receiver_with_an_empty_species_segment_matches_mace` (OMAT-S, MH-1) covers the path, receivers with an empty species segment between non-empty ones, against MACE float64; it cannot force the warp timing of the race itself.
- Sources: this file.

<a id="gen-first-bwd-v2"></a>
#### gen-first-bwd-v2: staged gradient rows and half-warp edges in the first-layer backward
- Switch: `first_bwd_kernel<STAGE_G>` (staged when 16 S (J - 1) floats fit in 46 KB of dynamic shared memory).
- Stage: S8.
- What: ncu (OMAT-S `SrTiO3`): issue slots 79% busy, 17.2 active threads per warp, L1 hit 97%: instruction-bound on half-empty warps. (1) the receiver's `G[m][s Jp + j]` (identical for all its edges) staged once, m innermost in float4 chunks swizzled by `(k >> 1) & 3`: 4 conflict-free shared loads per column instead of 16 global ones; (2) each half-warp owns an edge and strides the J = 66 columns by 16 (5 passes per two edges instead of 3 per edge, the third with 2 lanes), the `sh16_grad` tail on lanes 0 and 16 together. Arithmetic per column unchanged.
- Status: DEFAULT.
- Measured: kernel 1,114 -> ~809 us (OMAT-S `SrTiO3`), 929 -> 723 us (OFF23-M water). ABBA b/a: OMAT-S `SrTiO3` 0.948, OFF23-M water 0.982, OMAT-S `NbCl5` 0.986, MH-1 `SrTiO3` 0.996. Forces at noise level.
- Sources: this file.

<a id="gen-conv-fwd-r1"></a>
#### gen-conv-fwd-r1: one receiver per conv-forward block
- Stage: S8.
- What: gen-conv-v2 packed 4 (lx 0) / 2 (lx 1) receivers per block at C = 128; every block lasts as long as its busiest receiver, and ncu showed achieved occupancy at half the theoretical (33% of 66%, 16% of 33%).
- Status: DEFAULT.
- Measured: kernels 676 -> 495 us (OMAT-S `gconv_fwd_L0`; R = 2: 1,060 us), 2,054 -> 1,664 us (OFF23-M `gconv_fwd_L1`; R = 4: 1,772 us). ABBA b/a: OMAT-S `SrTiO3` 0.981, OFF23-M water 0.956, water_216 0.949, POLAR-1-M NaCl 216 0.989.
- Sources: this file.

<a id="gen-conv-fwd-l2-split"></a>
#### gen-conv-fwd-l2-split: lx 2 conv forward by x degree
- Switch: `emit_conv_fwd(2, groups=...)` -> `gconv_fwd_L2a` (x degree <= 1, owns the density) and `gconv_fwd_L2b` (x degree 2, `density_table = nullptr`).
- Stage: S8.
- What: the single kernel held 71 accumulators at 174 registers (one 256-thread block per SM); the halves hold 40 / 31 at 122 / 102 registers.
- Status: DEFAULT.
- Measured: OFF23-L water forward 7.59-7.69 -> 3.10 + 3.13 ms (nsys, frozen cell); forces vs before 9.8e-7 eV/A.
- Sources: this file.

<a id="gen-conv-bwd-128"></a>
#### gen-conv-bwd-128: 128-thread conv backward blocks
- Stage: S8. Status: REJECTED.
- Measured: kernels -4% (lx 0 and 1, nsys); ABBA b/a 0.997 (OMAT-S `SrTiO3`), 0.992 (OFF23-M water). 64 threads: +17% / +22%. Below resolution, and it halves the warps per receiver on 216-atom POLAR cells. Sources: this file.

<a id="gen-conv-fwd-l1-split"></a>
#### gen-conv-fwd-l1-split: lx 1 conv forward by x degree
- Stage: S8. Status: REJECTED.
- Measured: 1.70 ms -> 0.58 + 1.20-1.29 ms (OFF23-M water); the x degree 1 kernel alone needs 128 registers, more than the joint 122. Sources: this file.

<a id="gen-zbl-in-assembly"></a>
#### gen-zbl-in-assembly: ZBL in the force-assembly pass
- Stage: S10.
- What: the separate `zbl_kernel` read every active edge and its species, did double-precision `exp` and divisions on the close ones (FP64 at 1/64 rate on GeForce) and wrote back dE/dvec, before the backward. The assembly pass now adds ZBL to each edge's total dE/dvec and sums its energy (warp reduction, double), skipping edges beyond the largest ZBL cutoff (the specialised path's `zbl_r_max_max` early-out); the per-edge terms are float32, as in MACE's float32 model, which is the gate's yardstick.
- Measured (OMAT-S `SrTiO3`, nsys, frozen cell): `zbl_kernel` 188 + `assemble_forces_kernel` 201 -> 375 us merged in double, 221 us in float32. Forces against the double version at run-to-run noise (1e-6 eV/A).
- Sources: this file.

<a id="gen-first-bwd-assembly"></a>
#### gen-first-bwd-assembly: assembly in the first-layer backward
- Stage: S10. Status: REJECTED.
- What: `first_bwd_kernel` is the last per-edge kernel, so it could finish each edge: total dE/dvec, sender force by atomics, receiver force and virial reduced per block. The specialised path does this, but its layer-0 backward is edge-parallel (one edge per lane); the generic one finishes an edge on one lane per half-warp.
- Measured (OMAT-S `SrTiO3`): with ZBL in the tail 2,243 us (128 registers, FP64 on two lanes per warp), without it 1,113 us, with `__launch_bounds__(256, 3)` (80 registers) 1,142 us, against 790 + 201 (separate assembly) = 990 us. The serial tail, not occupancy, is the cost.
- Sources: this file.

<a id="gen-first-hidden-k0-align"></a>
#### gen-first-hidden-k0-align: layer-0 `K` alignment (`sgemm128` + `3xTF32`)
- Stage: S11.
- What: `export_generic.py` wrote `J - 1 = 65` columns (64 radial + 1 bias) into `first_C0`, making `K = 195` (`S=3`) or `130` (`S=2`) and blocking both `sgemm128` (`K % 16 == 0, N % 4 == 0`) and `HybCubin` (`K % 4 == 0, N % 4 == 0`) on all layer-0 `S0 @ C0` / `dS0 = dlin @ C0^T` GEMMs. In `GenericModel::load()`, if column `J - 2` of `first_C0` is identically zero across all species and degrees (all `ScaleShiftMACE` models: OMAT-0, OFF23/23b/24, MP), it is stripped from `C0` and `table` (`J: 66 -> 65, K = 64 S`). Otherwise (nonlinear models: POLAR-1, MH-1), `K0` is padded to a multiple of 16 with zero rows in `C0` and trailing zeros written by `first_fwd_kernel`.
- Measured (5060 Ti, ABBA): OMAT-0 small `SrTiO3` 5.88 -> 5.62 ms/step (`0.956`), OMAT-0 medium generic `SrTiO3` 10.56 -> 10.30 (`0.976`), OFF23-M water 8.85 -> 8.67 (`0.979`), MH-1 `NbCl5` 13.27 -> 13.16 (`0.992`), POLAR-1-M `NbCl5` 27.37 -> 27.35 (`0.999`). Oxide, crystals, organic gates pass.
- S90 measurement (16 November 2026, CPU, `.tmp_o/rank0.py`, deleted): a low-rank basis for the 64 hidden columns would shrink `K0` (layer 0's `S0 @ C0` / `dS0` GEMMs are 703 us of OMAT-0 medium generic's 8.0 ms step on the 5060 Ti, `first_fwd` + `first_bwd_edge` another 773 us). Per ordered pair (OMAT-0 medium, SrTiO3), the singular values of the edge's message map `col(r) @ C0` over `r` in [0.3, 6] Å decay slowly: rank 42-51 at `1e-7` of the largest, 49-57 at `1e-8`, 56-63 at `1e-9`. A truncation that stays below float32 rounding saves at most 12% of `K0`: not built.
- Sources: this file.

<a id="gen-conv-bwd-lazy-q"></a>
#### gen-conv-bwd-lazy-q: lazy `s_q` loads and launch bounds in `gconv_bwd`
- Stage: S11. Status: REJECTED.
- What: `gconv_bwd_L1<true>` uses 128 registers (`REG:128, STACK:0`, 256 threads) vs `wprime_backward_inter1_rcv`'s 64 registers (`STACK:0`, 512 threads). Tried loading `sq4[0..9]` lazily per path instead of all upfront, with `__launch_bounds__(512, 2)` and `(256, 3)`, and 512 threads on `L0`.
- Measured (5060 Ti, `OFF23-M` water / `OMAT-S` `SrTiO3`): `(512, 2)` and `(256, 3)` spilled (`STACK:64`, 2,875-2,948 vs 2,671-2,776 us), and even uncapped at 128 registers lazy `sq4` loads ran at 2,942 us because preloading all `sq4` lets `nvcc` batch the `LDS.128` reads. `gconv_bwd_L0` at 512 threads ran 1,313 vs 1,257 us. Reverted.
- Sources: this file.

<a id="gen-first-bwd-edge"></a>
#### gen-first-bwd-edge: edge-parallel layer-0 backward + ZBL + force/virial assembly
- Stage: S12.
- What: `first_bwd_kernel` was receiver-parallel (1 block/atom, dynamic `s_G` staging, half-warp serial tail + separate `assemble_forces_kernel`). Ported the `interaction0.cu` `tabled_outer_sum0_backward_kernel` architecture (`first_bwd_edge_kernel<COLS, HAS_ZBL, STRESS>`, 4 warps x 32 edges/warp, `COLS = 2` for `J - 1 <= 64` with `float2` `dS0` loads and `COLS = 3` for `J - 1 <= 96`): caches `dS0` in registers across consecutive sorted active edges with the same `(rcv, snd_sp)`, folds SH gradients in `s_edge[4][32][20]`, then all 32 lanes run `sh16_grad`, `edge_dvec` sum, float32 ZBL, forces and virial in parallel. Replaces both `first_bwd_kernel` and `assemble_forces_kernel` when `J - 1 <= 96`.
- Measured (5060 Ti, ABBA): OMAT-0 small `SrTiO3` 5.62 -> 5.13 ms/step (`0.913`, kernel `779+223 -> 526 us`), OFF23-M water 8.65 -> 8.28 (`0.957`, kernel `685+149 -> 362 us`), OMAT-0 medium generic `SrTiO3` 10.30 -> 9.80 (`0.951`), MH-1 `NbCl5` 13.20 -> 13.07 (`0.990`), POLAR-1-M `NbCl5` 27.40 -> 27.27 (`0.995`). Oxide, crystals, organic gates pass.
- Sources: this file.

<a id="gen-gprod-ro1-fused"></a>
#### gen-gprod-ro1-fused: fused product + nonlinear readout and multi-warp `gprod`
- Stage: S13.
- What: generalised `gen_kernels.py`'s `sc1_fused` to `gen_generic.py` (`gprod_ro1_fused_<sig><MAX_B, MIN_BLK>`, `blockDim = C <= 512`, `ro_H = 16`): runs product forward, `s_y @ ro_W1 + sc_skip16 + ro_b1`, `c * silu` energy + derivative, `dhid @ ro_W1^T`, and product backward in one kernel without writing `y0`/`dy0` or launching `ro_W1` GEMMs or `ro_mlp_kernel`. Also switched `gprod_fwd`/`gprod_bwd` from 32 threads/block to `128` threads/block when `C % 128 == 0` (with `(threadIdx.x & 31) == 0` for warp `dD` atomics), helping `POLAR-1-M` (`C = 512`, `gprod_bwd` 435 -> 387 us/call) and layer-0 `gprod`.
- Measured (5060 Ti, ABBA): OMAT-0 small `SrTiO3` 5.12 -> 4.99 ms/step (`0.976`), OFF23-M water 8.29 -> 8.16 (`0.984`), OMAT-0 medium generic `SrTiO3` 9.81 -> 9.67 (`0.986`, generic-vs-specialised gap now +913 us vs +2,144 us before S10), POLAR-1-M `NbCl5` 27.28 -> 27.14 (`0.995`). Oxide, OFF23-S/M organic, POLAR-1-M crystals gates pass.
- Sources: this file.

<a id="gen-gconv-cfix-preloc"></a>
#### gen-gconv-cfix-preloc: `C_FIX` template and prelocated spline indices in `gconv_fwd`/`gconv_bwd`
- Stage: S14.
- What: `gconv_bwd_L1<true>` previously held 128 registers (`REG:128, STACK:0`) with runtime `C` and per-edge `locate_spline(grid)` + `species`/`sym_pair` inside the loop. Templated `C_FIX` (`96, 128, 224, 0` on `gconv_bwd_L0/L1` and `128` on `gconv_fwd_L0/L1`) and passed prelocated `act_slab` and `act_t_sx` from `scatter_active_edges_kernel` via `GenericPassInputs` when `pair_sym && C_x <= 256` and `L->grid == preloc_grid()`. `gconv_bwd_L1<true, 128, true>` drops to `REG:62, STACK:0`. On `gconv_bwd_L1<..., 128>`, 256 threads/block beat 512 threads (`OFF23-M` water 2,158 vs 2,297 us; `OMAT-M` generic `SrTiO3` 2,682 vs 2,712 us). (Separately tested `LOUP_REORDER=1` on OMAT-S, OFF23-M, OMAT-M: no win observed at `N <= 5,184`.)
- Measured (5060 Ti, clean ABBA vs S13): OMAT-0 small `SrTiO3` 4.91 -> 4.73 ms/step (`0.964`), OFF23-M water 8.00 -> 7.43 (`0.928`), MH-1 `NbCl5` 12.82 -> 12.50 (`0.976`), POLAR-1-M `NbCl5` 27.20 -> 27.06 (`0.995`), OMAT-0 medium generic `SrTiO3` 9.67 -> 8.91 (`0.921`; `ab_mode.py`: `8.73 ms` vs specialised `8.31 ms` = `1.051x`, down from `1.273x` pre-S10). Oxide, OFF23-S/M organic, MH-1, POLAR-1-M crystals gates pass; `cmp_libs.py` passes on OMAT-S, OFF23-S/M/L, MH-1, POLAR-1-M.
- Sources: this file.

<a id="gen-conv-fwd-cg-fold"></a>
#### gen-conv-fwd-cg-fold: staged CG linear forms and `s_pw` in `gconv_fwd`
- Stage: S15 (14 November 2026).
- What: applied the same per-edge Clebsch-Gordan linear-form staging (`ED = 16/36/72` for `lx = 0/1/2` in `s_sh`, computed once per edge where `edge_sh16` runs) and warp-0 `s_pw` (`float4`) polynomial scaling to `emit_conv_fwd` in `python/gen_generic.py`.
- Status: DEFAULT (5060 Ti only).
- Measured (5060 Ti): kernel profiles `OFF23-M` water `gconv_fwd_L1` `1,687.8 -> 1,572.4 us` (`-6.8%`), `OFF23-L` water `gconv_fwd_L2b` `3,029.3 -> 2,897.5 us` (`-4.4%`); ABBA `OMAT-0` small `SrTiO3` `4.8219 -> 4.7672 ms` (`0.9886`), `OFF23-L` water `28.3006 -> 27.9964 ms` (`0.9893`), `OFF23-M` water tie (`7.5261 -> 7.5063`, `0.9974`), `POLAR-1-M` `NbCl5` tie (`25.0199 -> 24.9920`, `0.9989`), `MH-1` `NaCl` `1.7464 -> 1.7138` (`0.9813`, inconclusive: candidate reps spanned `1.6816` vs `1.7460 ms`). Cached 3x gates pass on `OMAT-0` medium/small, `OFF23-S/M/L`, `OFF24-M`, `MH-1` (crystals + organic), `POLAR-1-S/M`; pytest suite passes.
- Sources: this file.

<a id="gen-conv-bwd-128-regq"></a>
#### gen-conv-bwd-128-regq: `128`-thread register-`Q` edge-staged `gconv_bwd`
- Stage: S16 (14 November 2026).
- What: replaced `s_q` shared-memory staging and `4`-iteration `ch` loop in `gconv_bwd_L0/L1` (`C = 128`) with `128` threads (`1` channel/thread), `Q` in registers, `32`-edge tile staging, and `s_pull[4][32]` reduction (`PAIR = false` and `true`).
- Status: REJECTED.
- Measured (5060 Ti): `PAIR = false` (`L1 REG:80`, `L0 REG:56`, `STACK:0`): `gconv_bwd_L1` `2,216 -> 2,147 us` (`ncu` `L1 Hit 8.51%`, `L2 79.9%`), `OFF23-M` water ABBA `7.405 -> 7.398 ms` (`0.9991` tie), `OMAT-0-S` `SrTiO3` `4.725 -> 4.712` (`0.9972`). Adding staged `s_n/s_pw/s_dpw` + `PAIR = true` hit `REG:128` (`L1`) / `80` (`L0`) and regressed MD (`7.43 -> 7.46 ms`, `4.73 -> 4.77 ms`). Reverted.
- Sources: this file.

<a id="gen-conv-l1-carve0"></a>
#### gen-conv-l1-carve0: `PreferredSharedMemoryCarveout = 0` on generic conv & `first_bwd_edge`
- Stage: S16 (14 November 2026).
- Status: REJECTED.
- Measured (5060 Ti, `OFF23-M` water): `ncu` confirmed driver dropped shared config to `8.19 KB` (`gconv_fwd_L1`) and `32.77 KB` (`gconv_bwd_L1`), raising `L1 Hit` `4.5 -> 6.8%` and `9.1 -> 15.1%` but capping each SM to `1` block (`gconv_fwd_L1` `1,537 -> 2,805 us`, `gconv_bwd_L1` `2,242 -> 3,892 us`, `first_bwd_edge` `364 -> 1,140 us`). Reverted.
- S91 survey (16 November 2026, 5060 Ti, scratch `LOUP_GEN_CARVE` build, reverted): the driver's default configurations (`ncu`, OMAT-0 medium generic SrTiO3) are 100 KB for `gconv_bwd_L1` (4 blocks, shared- and register-limited alike), `first_fwd_kernel` and `first_bwd_edge_kernel` (register-limited at 13 and 6 blocks), 64 KB for `gconv_fwd_L1` and `gprod_ro1_fused` (4 blocks by registers) and 32 KB for `gprod_fwd` / `gprod_bwd`. Carveouts that keep the register-limited block count, per kernel (`nsys` us per step, default -> smaller configuration): `gconv_fwd_L1` at 32 KB (L1 hit 8.5% -> 18.5%) 1,760 -> 1,756; `gprod_ro1_fused` at 32 KB 236 -> 228; `first_bwd_edge` at 64 KB (5 blocks) 483 -> 495 on OMAT-0, 53 -> 55 on OFF23-M water216, 655 -> 549 on MH-1 SrTiO3 (its 119-register variant); `first_fwd` at a 40% carveout 266 -> 243 on OMAT-0 but 288 -> 297 on MH-1; `gprod_*` at 0-10% within noise; `gconv_bwd_L1` at 64 KB (2 blocks) 3,054 -> 3,491. S92 built the one candidate, a 50% carveout on the `COLS = 3` `first_bwd_edge` variants only (cc 12.0; MH-1, POLAR-1): MH-1 SrTiO3 `first_bwd_edge` 586 -> 531 us, library ABBA on shared GEMM plans MH-1 SrTiO3 `1.000` / `1.000`, POLAR-1-M NaCl216 `0.999`. A tie; reverted.
- Sources: this file.

<a id="gen-conv-fwd-l1-r4"></a>
#### gen-conv-fwd-l1-r4: `R = 4, TILE = 16` in `gconv_fwd_L1`
- Stage: S16 (14 November 2026).
- Status: REJECTED.
- Measured (5060 Ti, `REG:124, SHARED:12032`, `L1 Hit 4.5 -> 18.3%`): `OMAT-0-M` generic `SrTiO3` `8.79 -> 8.66 ms` (`0.985`), `OFF23-M` water `7.44 -> 7.54` (`1.013`, `1,571 -> 1,700 us`). Interleaved water molecules lose to higher register count. Reverted (needs per-system selection if pursued).
- Sources: this file.

<a id="gen-conv-l2-cfix-preloc"></a>
#### gen-conv-l2-cfix-preloc: `C_FIX` and prelocated slabs on the lx 2 convs, prelocation for `pair_sym = 0`
- Stage: S19 (14 November 2026).
- What: fresh profiles put the lx 2 convs at 51% of `OFF23-L` water216 kernel time (`gconv_bwd_L2` 838, `L2lp` 666, `fwd_L2a` 426, `L2b` 385 us/step), all with runtime `C` (`REG:125-128`, 23-31% warps active). S14's `C_FIX` / `PRELOC` covered only lx 0 / 1. Added `C_FIX = 128 / 224` dispatch to `gconv_fwd_L2a/L2b`, `gconv_bwd_L2lp`, `gconv_bwd_L2` (plus `PRELOC` on `gconv_bwd_L2`, which still located its spline per edge). Also `preloc_grid()` required `pair_sym`, so `POLAR-1-M/L` and `MH-1` (`pair_sym = 0`) never used `act_slab` / `act_t_sx`; `pick_preloc_layer()` now selects one layer for both `preloc_grid()` and `preloc_pair_sym()` (the layer's own `pair_sym`, matching `scatter_active_edges_kernel`'s slab encoding).
- Status: DEFAULT (5060 Ti only).
- Measured (5060 Ti): `ncu` (one launch each, S18 -> S19): `gconv_bwd_L2lp` `REG:128 -> 62`, `608.8 -> 589.5 us`; `gconv_fwd_L2a` `REG:125 -> 104`, `410.9 -> 400.6 us`; `gconv_fwd_L2b` `394.9 -> 380.4 us`; `gconv_bwd_L2` `857.7 -> 819.4 us`. Fresh-plan ABBA `OFF23-L` water (5,184 atoms) `27.81 -> 27.16 ms` (`0.9766`), water216 `3.850 -> 3.794` (`0.9854`), `POLAR-1-L` `NaCl216` `6.825 -> 6.766` (`0.9913`), `POLAR-1-M` `NbCl5` tie (`1.0018`), `MH-1` `NbCl5` tie (`1.0000`). Attribution: `OFF23-L` already prelocated (`pair_sym = 1`), so its gain is the lx 2 `C_FIX` plus `PRELOC` on `gconv_bwd_L2`; the `pair_sym = 0` prelocation shows only in `POLAR-1-L` (`0.991`, which also gets lx 2 `C_FIX = 128`) and is a tie on `POLAR-1-M` / `MH-1` `NbCl5`. Isolation (review follow-up): `gconv_bwd_L2lp` back on runtime `C` with everything else S19 measured `553/580 -> 557/617 us` (nsys, two runs each) and ABBA `OFF23-L` water `1.0055`, water216 `1.0108` (slower), so `C_FIX` stays on all four lx 2 kernels. `cmp_libs` vs S18: `OFF23-L` `dF = 1.4e-6`, `POLAR-1-L` `9.3e-7`, `POLAR-1-M` `NbCl5` `2.0e-4` (`|F|max = 26.8`), `MH-1` `6.6e-7`. Cached 3x gates pass on `OFF23-S/M/L`, `OFF24-M` (organic), `POLAR-1-S/M`, `MH-1` (crystals + organic), `OMAT-0-S` (oxide); `POLAR-1-L` `NaCl_c0` force + FD-stress 3x check passes (`dF = 0.58x`; its float32 FD-stress reference is noisy, so the stress ratio is weak evidence); pytest `67 passed` (rerun after freeing disk space; the first run hit `ENOSPC`).
- Sources: this file.

<a id="gen-first-bwd-edge-minb"></a>
#### gen-first-bwd-edge-minb: register cap on `first_bwd_edge_kernel<COLS = 2>`, and the rejected lane-per-edge rewrite
- Switch: `src/generic.cu` `LOUP_FIRST_BWD_EDGE_MINB2` (6 in sm_120 device code, else 0) in `__launch_bounds__(128, COLS == 2 ? LOUP_FIRST_BWD_EDGE_MINB2 : 0)`.
- Stage: S21 (14 November 2026).
- What: fresh `ncu` on `OMAT-0-S` `SrTiO3` (`492.7 us`, 10% of the step) found the kernel latency-bound, not bandwidth-bound: issue active 57% (`No Eligible` 43%), stalls per issue short scoreboard 2.20 (the serial 16-value shuffle fold and `dr` reduction per edge), long scoreboard 2.03, wait 1.44; L2 throughput 32%; 94 registers, so 41.7% theoretical occupancy (4.7 warps / scheduler); ~155 warp instructions per edge (75 FMA). Capping `COLS = 2` at 80 registers (6 blocks / SM) has no spills; min-blocks 8 (64 registers) spills 40 B and is slower (`570-600 us`); `COLS = 3` spills 64-88 B under the cap, so it keeps the uncapped kernel (SASS identical to S20). Other architectures were not measured and keep the uncapped kernel: `sm_89` / `sm_90` SASS of all checked instantiations is identical to S20.
- Status: DEFAULT (5060 Ti only). Small: a reproducible 6% kernel gain, about 0.2-0.5% of the step.
- Measured (5060 Ti): `nsys` kernel time per step, two runs each: `OMAT-0-S` `SrTiO3` `517.5 / 503.1 -> 479.0 / 480.8 us`, `OFF23-M` water `354.0 / 362.7 -> 335.5 / 332.4 us` (`-6%`). Fresh-plan ABBA, `a` = S20, `b` = S21: `OMAT-0-S` `0.9946`, `0.9958`, `0.9997`; `OFF23-M` `0.9956`, `1.0030`, `1.0002`, `0.9950`; `OFF23-S` `1.0008`. Arguments reversed (`a` = S21, `b` = S20; above 1 = S20 slower): `OMAT-0-S` `1.0082`, `1.0051`; `OFF23-M` `1.0047`, `1.0016`. Combined S21 / S20: `OMAT-0-S` `0.9954` (5 runs, all <= 1), `OFF23-M` `0.9979` (6 runs, one `1.0030`). `cmp_libs` `OMAT-0-S` S20 vs S21 `dE 9.2e-7`, `dF 9.5e-7` against an S20-vs-S20 run-to-run `dE 1.8e-3`, `dF 3.6e-6`. Cached 3x gates pass (`OMAT-0-S` oxide, `OFF23-M` / `OFF23-S` organic); `pytest` 67 passed (one earlier run had 1 failure that did not reproduce on rerun; the failing test was not captured).
- Rejected, lane-per-edge (`gen-first-bwd-lpe`): each lane owns one edge and walks the `Jp` columns in groups of 4, so the 15 SH gradients and `dr` accumulate in the lane (no folds); table rows staged through shared memory in coalesced 8-column chunks; `dS0` rows (fixed per receiver and sender species) as warp-uniform `float4` loads. Instructions fell as predicted (`99.7M -> 56.9M`, `-43%`) but the kernel held 128-168 registers (`25%` occupancy, long scoreboard 6.27 on the `dS0` loads): `505 -> 570 us` (`OMAT-0-S`), `360 -> 434 us` (`OFF23-M`). Caps: 128 registers `1024 us`, 96 (`48-104 B` spill) `681 us`, 80 (`96-112 B` spill) `714 us`. Stopped; a version that wins needs the 16 `dS0` rows out of registers (e.g. staged per warp in shared memory), which the uniform-load design was meant to avoid.
- A100 (S93, `s93a`): the same cap built for `sm_80` ties there (`1.000` / `0.998` / `1.003`), so other architectures keep the uncapped kernel ([s93-sm80-caps](#s93-sm80-caps)).
- Sources: this file.

<a id="s93-sm80-caps"></a>
#### s93-sm80-caps: the generic layer-0 backward and conv-forward register caps on the A100 (rejected)
- Stage: S93 (built 16 November 2026 on the Alex login node; measured 17 November 2026, NHR Alex A100-SXM4-40GB node a0701, job 5014425 `loup-s93c`).
- What: scratch builds of S86 (`round6-hardening` `9f8cac77`) for `sm_80`, not committed. `s93a`: the cap of [gen-first-bwd-edge-minb](#gen-first-bwd-edge-minb) on `sm_80`, `first_bwd_edge_kernel<COLS = 2>` at 6 blocks / SM (80 registers, 8-16 B stack). `s93b`: `s93a` plus `gconv_fwd_L1` R1 at `C = 128` capped at 5 blocks / SM (104 -> 96 registers, no stack), the A100 counterpart of the S94 falsifier in [gen-conv-fwd-variants](#gen-conv-fwd-variants).
- Measured (library ABBA against S86 on shared GEMM plans, 2 rounds; first / second order): `s93b` OMAT-0 medium generic SrTiO3 `0.986` (`0.987` / `0.985`), MP-0 medium SrTiO3 `0.984` (`0.984` / `0.984`), OFF23-M water216 `1.015` (`1.023` / `1.007`); `s93a` `1.000` (`1.000` / `1.001`), `0.998` (`0.996` / `1.000`), `1.003` (`1.003` / `1.004`).
- Status: REJECTED (A100). The queue required a win in both orders on all three systems. The conv-forward cap wins on the two SrTiO3 cells and loses on water216; the `first_bwd_edge` cap alone ties.
- Sources: this file; [A100 queue](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/alex-a100-queue-20261116/README.md) (`logs/slurm-loup-s93c-5014425.out`).

<a id="s21-limiters"></a>
#### s21-limiters: S21 profile findings on the GEMMs and the generic convs (no change adopted)
- Stage: S21 (14 November 2026), 5060 Ti.
- Own `sgemm128` (`5832x512x512`, `ncu`, 2.51 GHz, peak 23.1 TFLOP/s): issue 2.92 / 4 IPC, FMA pipe 74%, 89% of instructions are FFMA (`48.4M` of `54.1M`; minimum `47.8M`); stalls per issue: not selected 2.26, dispatch 0.91, barrier 0.29, short scoreboard 0.16. Tails: 2.56 waves (`5832`) and 4.22 (`9720`) lose ~15% standalone, but the per-degree GEMMs already overlap on the fork / lane side streams. FMA loop order is register-allocation sensitive: j-outer `12%` slower, 2x2-blocked tie with the current i-outer order. The existing `TN = 4` (128 x 64) tile on full `N = 512`, hot / cold (us): `1944` 74.0 / 76.5 -> 77.8 / 80.4, `5832` 213.3 / 215.9 -> 206.6 / 211.3, `9720` 319.3 / 322.2 -> 316.3 / 324.2, `13608` 421.0 / 424.9 -> 444.5 / 449.1: a win only at `5832` (~7 us per GEMM, ~0.2% of an `MH-1` step), so the tail is not worth a new autotune candidate. No change.
- `gconv_bwd_L1` / `gconv_fwd_L1` (`OFF23-M` water, `ncu`): L2 throughput 83.7% / 82.9%, L2 hit 94%, L1 hit 5.1% / 1.2%; `108M` / `99M` L2 read sectors per launch, ~83% packed table (10 paths x 8 B per channel per edge), the rest sender `x`. A slab is `C x 10 x 8 B` = 10 KB, so the ~60 KB of L1 left beside the shared memory holds ~6 slabs. Undirected-pair table sharing (`pair_sym`) would cost 40C forward atomics or a 160 B per channel `s_q` gather per edge to save 80 B of table: not pursued. These kernels are at the L2 roofline for the current algorithm.
- Sources: this file.

<a id="s22-limiters"></a>
#### s22-limiters: gate kernels, grouped per-degree GEMMs, and host round trips (no change adopted)
- Stage: S22 (14 November 2026), 5060 Ti.
- Benchmark caveat: zero-filled operands overstate SIMT GEMM throughput on the 5060 Ti (lower power, higher clocks under the power cap). A stacked single launch looked 27% faster than four per-degree GEMMs with zeros; with random operands the effect mostly vanished. GEMM microbenchmarks must use random data.
- `gate_fwd` / `gate_bwd` (`MH-1` `NbCl5`, `Cm = 512`, `ncu`): 404 / 723 us at 86.5% DRAM throughput, L2 hit ~0% (inputs are GEMM outputs far larger than L2); ~111 / ~187 MB read per launch plus 16C / 26C floats per atom written. At the DRAM floor. Byte-saving options all need GEMM epilogue / prologue fusion across the own and cuBLASLt backends: write only `dp` and row-scale the lin-backward GEMM output (`dl = s dp`; `dpre` exists only for layers t > 0 and l <= lx, so on `MH-1` this removes the `dl0` / `dl1` writes (4C + 3C of ~73C per atom) from one of the two `gate_bwd` launches: ~70 us / step, ~0.6%), or build `pre` from `s`-scaled inputs with a `beta = 1` accumulate (7C of reads in `fwd`, not measured). The `dl` option alone is ~0.6%; 1-2% of `MH-1` is a speculative ceiling for both options together. Not pursued.
- Grouped per-degree GEMM (one launch, per-group A / B / C / M / N / K descriptors, bit-identical to per-group `sgemm128`), random data, against the current per-shape picks: `NaCl216` l = 0..3 `N = K = 512` 162.0 -> 168.9 us (`1.04`), `N = 144` 83.9 -> 65.4 (`0.78`), `K = 144` 57.0 -> 50.6 (`0.89`), `NbCl5` `N = K = 512` 1173 -> 1115 (`0.95`), l = 1..3 `N = 640` 176.9 -> 168.9 (`0.955`). The main shape loses; the narrow wins are ~1% of a small-system step. Rejected. (Serial vs four concurrent streams was measured only with zero-filled operands, so it is not evidence either way.)
- Idle time from a graph-node trace (union of kernel intervals; node tracing inflates the span, e.g. `POLAR-1-S` `NaCl216` 1.72 ms traced vs 1.50 ms untraced, so these percentages rank causes and are not targets): busy 86-91% on `NaCl216` / water systems, 97% on `OMAT-0-S` `SrTiO3`. Water runs the unpipelined loop (light H: `4 x max step displacement >= skin / 2` at skin 0.5), so every step pays one host round trip; an untraced standalone microbenchmark puts that round trip at ~165 us (`memcpy` + `cudaStreamSynchronize` + relaunch into an empty queue). Each rebuild pays three more (traced: `E_new` 136 us, `order_err` 137 us, plus the drained pipeline), ~745 us idle per rebuild on `OFF23-S` water.
- Round-trip falsifiers: CUDA graph conditional nodes (`IF !need_rebuild { move } -> IF !need_rebuild { rest }`) gave exact counters in a standalone test (stall at a queued step, skipped launches, host resume), but cost 137-200 us of GPU time per step on this WSL driver against an ~877 us busy step, as much as the round trip they remove: rejected. A mapped pinned flag with host spin instead of `memcpy` + `cudaStreamSynchronize` saves ~15 us of the ~165 us round trip (most of it is launch-to-start latency into an empty queue). Deferring the `order_err` check would save one drain per rebuild (~1% on water) but would let force passes run on unvalidated rows before the error is seen: the synchronous check stays.
- Sources: this file.

<a id="s23-small-m-gemm"></a>
#### s23-small-m-gemm: small-system GEMM occupancy (no change adopted)
- Stage: S23 (14 November 2026), 5060 Ti.
- Where the time goes (`POLAR-1-L` `NaCl216`, node trace): GEMMs are ~87% of kernel time, dominated by under-filled grids: `sgemm128` 36 blocks (2.78 ms / step, 39 launches), `sgemm64` 88 blocks (2.78 ms, 44 launches), `sgemm64` 32 blocks (1.70 ms, 50 launches). `nsys --gpu-metrics-devices=all` (works under WSL; sampled at 20 kHz, the mean of all ~9,000 samples of the capture, ~0.45 s for 60 steps, so it includes the capture edges): GR active 91%, SMs active 77%, SM issue 47%, i.e. roughly a quarter of SM-time with no active warps. On `POLAR-1-M` `NaCl216` the sum of grid blocks over overlapping launches is below 36 for 13.5% of traced time (a launch-size count, not measured residency), led by the `M = 216, N = 512` products (`sgemm64`, 32 blocks, 192 us / step traced).
- Deterministic split-K on `sgemm64` (k-slices into the workspace + `splitk_reduce_kernel`, random data): `216x512x512` 16.4 -> 18.2 / 18.2 us (split 2 / 4, the reduce launch costs more than the parallelism gains); `216x256x2048` 32.3 (best existing, `own32 sk4`) -> 27.8; `216x144x2048` 20.5 -> 27.6; `216x128x2048` 20.1 -> 19.9; `648x512x512` 33.4 -> 33.3. One shape class gains ~5 us per launch: rejected.
- Grouped / stacked per-degree GEMM, corrected: a stacked `M = 3456` launch (216 + 648 + 1080 + 1512 rows) looked 24% faster than the serial `sgemm64` picks with random data (125-129 vs 161-163 us), but the grouped kernel on the real split stayed at 167-169 us. The grouped kernel itself is not the problem (one group of 3456 rows: 125-132 us). The cause is tile count, not partial tiles: plain `sgemm128` at `N = K = 512` takes 121-123 us for `M = 3456` (108 full tiles = 72 + 36, a full wave plus one block per SM) and 154-160 us for `M = 3464` (112 tiles, one partial), `3584` (112 full), `3712` (116 full) and `4096` (128 full) alike. The real four groups (116 tiles, either order) and two groups of 1728 (112) therefore take 166-169 us; groups padded to 128-row multiples (256 / 640 / 1024 / 1536, 108 tiles) are fast again. The stacked number was a quantisation coincidence; the S22 rejection stands.
- Sources: this file.

<a id="s24-l0-conv"></a>
#### s24-l0-conv: generic lx 0 convs on `OMAT-0-S` and `OFF23-S` (no change adopted)
- Stage: S24 (14 November 2026), 5060 Ti, `ncu`: `OMAT-0-S` `SrTiO3` (5,000 atoms), `OFF23-S` water (5,184 atoms).
- `OMAT-0-S` `gconv_bwd_L0<true, 128, true>`: 1.16 ms, issue 67% (`No Eligible` 32%), L2 throughput 53% (hit 94%), L1 hit 32%, 280.7M warp instructions (177.6M FMA-pipe), ~109 lane instructions per edge-channel; stalls per issue: long scoreboard 4.76, not selected 2.10, wait 1.22, dispatch 0.76. `gconv_fwd_L0<1, true, 256, true, 128>`: 591 us, L1 / L2 throughput 72% / 71%, issue 67%, long scoreboard 4.73.
- `OFF23-S` (`C = 96`): `gconv_bwd_L0`: 627 us, L2 56.5%, compute 59.5% (`No Eligible` 38%), long scoreboard 6.07, 129.8M warp instructions (80.5M FMA-pipe). `gconv_fwd_L0`: 378 us, L2 87.5% (L2-bound), long scoreboard 9.73.
- Unpacked backward table, tested (S25) and rejected: a scratch `gconv_bwd_L0<..., F4>` reading a bias-folded `float4` copy (`c_k = r_k - 1.5 * 2^e`, so `w = c0 + s1 c1 + s2 c2 + s3 c3`, `dw = c1 + ds2 c2 + ds3 c3`; 64 registers, no stack) removed the decode but doubled the backward's table bytes. `nsys` kernel time per step, two runs each: `OMAT-0-S` `SrTiO3` 1232 / 1243 -> 1556 / 1546 us (`+25%`), `OFF23-S` water 612 / 628 -> 748 / 774 us (`+23%`); the extra L2 traffic costs more than the decode it removes. Forces matched the packed path to float32 rounding (`dF` 7.1e-6 / 5.2e-6 against a same-library run-to-run 9.4e-7 / 3.6e-6). The packed table stays for both directions.
- Sources: this file.

<a id="s107-l2-match"></a>
#### s107-l2-match: matching symmetrix's L2 throughput in the layer-1 convs (no change adopted)
- Stage: S107 (16 November 2026), 5060 Ti, OMAT-0 medium, SrTiO3 10x10x10 (5,000 atoms, 371,624 directed edges).
- Comparison (`ncu`, `evaluate()` path, `results/symmetrix-main-20261116` rounds 2 / 3):
  - **symmetrix main b907f04, `float32`:** `k_Phi1` at 87.8% of L2 peak, `k_Phi1_reverse` at 89.2%.
  - **LoupMD:** `spline_forward_inter1<1, true>` 85.1%, `wprime_backward_inter1_rcv` 82.7%; generic `gconv_fwd_L1<1, true, 256, true, 128>` 78.4% (104 registers, 33% occupancy), `gconv_bwd_L1` 82.1%.
  - **Instructions are equal per edge-channel** (~490): 411M against 382M in the forward, 735M against 717M in the backward. symmetrix reads 727 L2 sectors per edge in the forward against 313; it is memory-bound (`lg_throttle` 5.6, `mio_throttle` 3.2 warps per issue: the load queue is full).
  - **LoupMD is latency- or issue-bound instead.** Forward: long scoreboard 4.3, `lg_throttle` 0.03, issue 0.55 per cycle. Backward: issue 0.75, not selected 3.8, dispatch 1.4.
- MD-tuned kernels (`ncu` of `loup_profile_force` after 150 Langevin steps):
  - **Forward is R5:** `spline_forward_inter1<5, false>` / `gconv_fwd_L1<5, false, 640, ...>`, 1.80 / 1.76 ms. L1 hit 43% / 38% from the slab sharing; L2 at only 67% / 73%; long scoreboard 2.49.
  - **R5 beats R1p by 15%** (tuning 1,649 against 1,947 us), so the MD forward is not L2-bound.
  - **Backward:** `wprime_backward_inter1_rcv` 81% of L2 peak, `gconv_bwd_L1` 83%.
- Falsifier 1 (reverted): L1 prefetch of the next unit in both forward kernels.
  - What: at the top of each unit, `prefetch.global.L1` of the next unit's 10 slab rows and 4 sender rows.
  - Tuning R5 1,649 -> 2,004 us (default), generic R5 1,617 -> 1,949 us.
  - ABBA SrTiO3 default 8.21 -> 8.42 ms (`+2.6%`), generic 7.98 -> 8.23 ms (`+3.1%`).
  - Cause: the prefetched lines evict the slabs R5's five receivers share in L1.
- Falsifier 2 (reverted): register prefetch one edge ahead in the unpaired variants with `R <= 4`.
  - What: the next edge's slab row and sender rows were loaded before the current edge's math (`gen_kernels.py`, switch `LOUP_GEN_FWD_PF`).
  - Registers: R4 unpaired 96 -> 128 (still one 512-thread block per SM).
  - Forced R4 in MD 1,937 -> 1,868 us (`-3.6%`); tuning R4 1,683 -> 1,667 us.
  - R5 cannot hold the extra registers (640 threads x 96 = 61k of 64k), still wins at 1,633-1,636 us and stays the pick.
  - ABBA default SrTiO3 8.163 -> 8.155 ms, NbCl5 1.810 -> 1.826 ms: ties.
- Backward stall sampling (`ncu` source counters, MD-tuned rcv `w'`):
  - Samples: not selected 36%, long scoreboard 19%, dispatch 13%, selected 10%.
  - Long scoreboard: 6% on the first use of each channel's first table entry, 3% on the per-edge metadata.
  - Dispatch: spread over FFMA / LOP3 / SHF, no hotspot.
  - Executed instructions: FFMA 49%, FMUL 15%; the decode (LOP3 / SHF / IADD) is 19%.
  - Consequence: the backward reaches higher L2 throughput only with fewer instructions per edge-channel. More loads in flight cannot raise it.
- Not built:
  - cp.async staging of R5's slab rows. 60 KB of shared memory forces the 100 KB carveout, leaving 28 KB of L1 and losing the slab sharing that makes R5 faster than R1p.
  - A register cap for the generic R1 / R1p forward (104 registers against the specialised kernel's 96). These variants run only in `evaluate()` before tuning, and in systems where they win.
- Sources: this file; `results/symmetrix-main-20261116` (README rounds 2 and 3, `ncu/`, `ncu_full/`).

<a id="s108-wide-table"></a>
#### s108-wide-table: wider interaction-1 intervals for thermalised slab reuse (rejected)
- Stage: S108 (16 November 2026), 5060 Ti, OMAT-0 medium, `SrTiO3` 10x10x10 (5,000 atoms), configurations at rest and after Langevin equilibration to 160 K and 296.5 K.
- Cause of the temperature penalty (force pass 7.46-7.52 ms at rest, 8.06-8.12 ms at 160 K, default variants):
  - Edges within 6 A change by only +0.4%, so the work is the same.
  - Table slab reuse collapses. Within one receiver there are 0.30 distinct slabs per edge at rest and 0.75 at 300 K.
  - `ncu` R5 `spline_forward_inter1`: 1.58 -> 1.79 ms, L1 hit 78.7% -> 48.9%, L2 throughput 28.6% -> 59.7%. `w'` L1 hit 32% -> 8%.
  - The variant tuner already follows it. At 300 K R5 is best (8.03 ms; R4 8.08, R4p 8.11, R1p 8.22, R1 8.27); at rest R1p and R4p are best (7.53).
- Stage 1, the ceiling with accuracy ignored: the cubic grid coarsened k-fold on the bands from 1.5 A (scratch export), force pass with the best variant:

  | Grid | 300 K (ms) | Rest (ms) |
  | --- | --- | --- |
  | k = 1 (current) | 8.035 | 7.562 |
  | k = 2 | 7.913 | 7.481 |
  | k = 4 | 7.799 | 7.390 |
  | k = 8 | 7.676 | 7.372 |

  At k = 8 the 300 K forward L1 hit recovers to 78.8%. The whole reachable gain is 4.5% at 300 K.
- Accuracy of candidate formats (per-column error relative to the column maximum, r >= 1 A):

  | Representation | Value | Slope |
  | --- | --- | --- |
  | float32 MACE network (reference) | 1.7e-4 | 1.35e-4 |
  | current CUBIC_PACKED8 | 1.44e-4 | 5.0e-5 |
  | cubic spline (float), k = 2 | 5.9e-6 | 1.05e-4 |
  | quintic Hermite (float), k = 4 | 3.5e-7 | 4.7e-6 |
  | quintic Hermite (float), k = 8 | 1.95e-5 | 1.06e-4 |
  | 8-byte quintic, k = 4 (monomial fields of 17 / 14 / 13 / 9 / 5 / 1 bits) | 3.1e-4 | 3.1e-4 (all r: 6.3e-4) |
  | 8-byte Chebyshev, k = 4 (local search) | 9.6e-4 | – |
  | 8-byte Chebyshev, 4 fields, k = 2 | 1.5e-4 | 1.8e-4 |
  | 8-byte Chebyshev, 4 fields, k = 1 | 2.4e-4 | 1.5e-4 |

  Intervals 4x wider need degree 5 to keep the current accuracy, and six coefficients do not fit 64 bits at the precision a cubic's four get. The 8-byte quintic misses the current slope error by 6x.
- Prototype (branch `s108-quintic-proto`; generator `LOUP_GEN_SPLINE1=wide:NB/SH`, loader `spline1_degree = 5`): k = 4 on all bands (186 intervals), six monomial fields.
  - Registers: forward R5 96, R1p / R4p 128. `w'` (64-register cap) spills: receiver-owned kernel 48 B of stack, edge-tiled kernel 32 B.
  - Force pass: rest 7.39-7.54 -> 8.09-8.39 ms (+9-11%), 300 K 7.86-8.08 -> 8.44-8.63 ms (+5-9%). `nsys` at 300 K: `w'` +445 us, forward +76 us.
  - VRAM: layer-1 packed table 43 MB -> 10.9 MB; engine total 658 -> 626 MiB at 5,000 atoms.
- Status: REJECTED. Any wider 8-byte format costs more in decode than it gains in locality, and the formats that fit 8 bytes lose accuracy.
- Sources: this file; branch `s108-quintic-proto`.

<a id="s109-exponent-or"></a>
#### s109-exponent-or: OR-ed exponent base in the cubic decode (rejected)
- Stage: S109 (16 November 2026), 5060 Ti.
- What: the CUBIC_PACKED8 decode adds the table's exponent base to each 5-bit exponent field. Scaling a table by 2^k (exact) moves the base to a multiple of 32, so the decode becomes `(c.y & 0x0F800000u) | bias_shift`. The 2^-k goes into the forward's output stores and into `w'`'s staged q.
- Measured:
  - Static SASS: forward R5 728 -> 712 instructions. `w'` receiver-owned FMUL 118 -> 147 (the q scaling). Neither build has an IADD3, so there was no separate add to remove.
  - MD a-b-b-a vs s106a: `NbCl5` 1.781 -> 1.798 ms (1.0100), `SrTiO3` 8.005 -> 8.058 ms (1.0067). The gate passes.
- Status: REJECTED, reverted.
- Sources: this file.

<a id="s26-fwd-pair-c96"></a>
#### s26-fwd-pair-c96: paired-edge forward with `C_FIX` for `C = 96 / 224` (rejected)
- Stage: S26 (14 November 2026), 5060 Ti.
- What: the lx 0 / 1 forward dispatch (`launch_conv_fwd`, generated by `python/gen_generic.py`) uses `PAIR = true` with `C_FIX = 128` only for `C = 128`; other `C <= 256` run `PAIR = false` with runtime `C` (e.g. `OFF23-S`, `C = 96`, whose `gconv_fwd_L0` is L2-bound at 87.5%). Added `C = 96 / 224` branches with `PAIR = true` and `C_FIX` (59 / 102 registers, no stack, as for 128).
- Measured (`nsys` kernel time per step, two runs): `OFF23-S` water `gconv_fwd_L0` 341.0 / 340.3 -> 329.8 / 338.2 us (about `-2%`, ~0.2% of the step); the pair hit rate was not measured, so the cause of the small gain is not established. No current model runs the lx 0 / 1 forward at `C = 224` (`OFF23-L` layer 0 is the first-hidden path, later layers are lx 2, which already pair). Below the stop rule: reverted.
- Sources: this file.

<a id="s27-elementwise-products"></a>
#### s27-elementwise-products: `inv_bwd` (POLAR) and `gprod` (MH-1) limiters (no change adopted)
- Stage: S27 (14 November 2026), 5060 Ti, `ncu`.
- `inv_bwd_kernel` (`POLAR-1-M` `NbCl5`, 796 us / step traced over ~8 launches): 12 consecutive launches: degree 0 (grid 3888) 40.7-42.9 us at 92.3-93.9% DRAM throughput (L2 hit 15-16%), degree 1 (grid 11664) 104.6-139.8 us at 90.2-94.8% (L2 hit 27%); 20 registers; a pure streaming update (`dfm += g Z`, `dZ = g fm`). Only the electron-energy pair (`polar.cu` `Zq` / `Zv` calls, same `hL` and `dh`) could be fused, saving one `fm` read and one `dfm` read-modify-write: 3 of the pair's ~11-12 element passes (each call streams `fm`, `Z`, `dfm` twice and `dZ`, plus the per-atom `dinv`: one pass at degree 0, a third at degree 1), i.e. 25-28%. Recomputed from the per-degree launch times above, assuming the pair runs once per degree per step (l = 0 and l = 1 for `POLAR-1-M`; the pair launches were not individually identified): 2 x ~41 + 2 x ~105-140 us = ~290-360 us, so the fusion would save ~75-100 us, ~0.3-0.4% of the ~24 ms step; below the bar, not built; the SCF-loop calls are single. The S-earlier index cleanup (`inv2` fusion) already left the rest DRAM-bound.
- `gprod_bwd` (`MH-1` `NbCl5`): 377 us at 84% DRAM, L2 hit 3%, 153 registers (25% occupancy), long scoreboard 5.31. `gprod_ro1_fused`: 353 us at 80% DRAM, 110 registers, barrier 4.57 / long scoreboard 4.88. Both stream per-atom features from DRAM near the bandwidth floor; only traffic removal (fusion with the neighbouring GEMMs) would help.
- Sources: this file.

<a id="s28-inpass-gemm-picks"></a>
#### s28-inpass-gemm-picks: are standalone-tuned GEMM picks wrong inside the pass? (no evidence)
- Stage: S28 (14 November 2026), 5060 Ti.
- What: a scratch `LOUP_FORCE_OWN` switch overrode, at dispatch, every GEMM whose tuned plan was an own kernel with one family (`sgemm128`, `sgemm64`, or `sgemm32` without split-K), on fresh plans. MD step time ratio against the tuned plan (two interleaved runs each): `POLAR-1-M` `NaCl216` 1.272 / 1.065 / 1.138, `MH-1` `NaCl216` 1.202 / 1.040 / 1.178, `POLAR-1-L` `NaCl216` 1.189 / 1.038 / 1.162, `MH-1` `NbCl5` 1.010 / 1.023 / 1.162 (own128 / own64 / own32).
- Targeted follow-up (scratch `LOUP_FORCE_BUCKET=M:N:mode`, matching `M` and `N` only, so each bucket covers every `K`, `transB` and `beta` with that `M x N` (for `216 x 512` that is `K = 512, 128, 64, 8`); everything else tuned; `POLAR-1-M` `NaCl216`, two interleaved runs): the two dominant small-system buckets, `M = 216, N = 512` (tuned `sgemm64`, 32 blocks) -> `sgemm128` 1.143, `sgemm32` 1.022; `M = 648, N = 512` (tuned `sgemm64`, 88 blocks) -> `sgemm128` 1.089, `sgemm32` 1.065.
- Conclusion: the standalone autotuner's picks beat every uniform family in the pass (by 1-27%) and every tested alternative for the two dominant small-system `M x N` buckets as a whole (by 2-14%); single plan keys `(M, N, K, transB, beta)` were not isolated. Plans routed to cuBLASLt / hybrid and combinations of buckets were not perturbed, so this is not a proof that no in-pass choice can win, but there is no measured sign that the standalone picks are wrong; pass-aware tile selection is not pursued without such evidence.
- Sources: this file.

<a id="gen-conv-bwd-l1-c256"></a>
#### gen-conv-bwd-l1-c256: `C_FIX = 256` on `gconv_bwd_L1`
- Switch: `python/gen_generic.py` `launch_conv_bwd` (`C == 256` branch, `gconv_bwd_L1<WANT_DX, 256, PRELOC>`), regenerated into `src/generated_generic.cu`.
- Stage: S29 (14 November 2026).
- What: a sweep over every installed model found `MACE_MPtrj_2022.9` (`C = 256`; the bundle export reports `256x0e+256x1o` for layer 1) running `gconv_bwd_L1<true, 0, true>` (runtime `C`, 128 registers) and `gconv_fwd_L1<1, false, 256, true, 0>`, the two at 39% of its kernel time (`SrTiO3`, 5,000 atoms, 12.8 ms / step). The `C_FIX` dispatch covered only `C = 128 / 224`. `C_FIX = 256` cuts the backward to 62 registers, as at 128; the gain is small because the kernel is occupancy-limited by its shared memory, not by registers: `ncu` (`MPtrj`, after the change) 2.81 ms, 62 registers, `s_q` = 256 x 44 x 4 B = 45 KB per block so 2 blocks (16 warps) per SM, achieved occupancy 29%, `No Eligible` 41%, L2 throughput 45% (hit 86%), DRAM 36%; it is latency-bound at low occupancy, not L2-bound. The forward is in `gen-conv-fwd-l1-c256`. Of the installed models only `MPtrj` reaches the `C = 256` lx 1 branches: the other `SrTiO3` / water models run `C = 128` or the specialised `spline_forward_inter1` / `wprime` path (S29 traces).
- Status: DEFAULT (5060 Ti only). Same arithmetic order as the runtime-`C` kernel.
- Measured (5060 Ti, `nsys` kernel time per step for both L1 convs, two runs): base 4928 / 4975 us, `C_FIX` backward 4837 / 4848, `PAIR` forward 4952 / 4953. Fresh-plan ABBA on `MPtrj` `SrTiO3`: `a` = base `12.0336`, `b` = new `11.9549` (`0.9935`); reversed `a` = new `11.9591`, `b` = base `12.0846` (new / base `0.9896`). Final installed build vs a rebuilt parent commit, fresh plans: `0.9913` (`12.046 -> 11.941`) and reversed `1.0089` (new / base `0.9912`). `cmp_libs` base vs new `dE 8.4e-7`, `dF 6.8e-7` against base-vs-base `dE 2.2e-7`, `dF 8.2e-7`. 3x gate (`MPtrj`, oxide set, new float64 / float32 references cached) passes on all six configurations (`dF` ratio <= 1.28, `dS` ratio <= 0.93); `pytest` 67 passed.
- Sources: this file.

<a id="gen-conv-fwd-l1-c256"></a>
#### gen-conv-fwd-l1-c256: `C_FIX = 256` on `gconv_fwd_L1`
- Switch: `python/gen_generic.py` `launch_conv_fwd` (`C == 256` branch, `gconv_fwd_L1<1, false, 256, PRELOC, 256>`, 256 threads), regenerated into `src/generated_generic.cu`.
- Stage: S30 (14 November 2026).
- What: S29 tested the forward with `PAIR = true` and `C_FIX = 256` together (104 registers, a tie), which left `C_FIX` alone untested. With `PAIR = false` the kernel keeps the runtime-`C` kernel's 80 registers and drops the dynamic-`C` indexing.
- Status: DEFAULT (5060 Ti only).
- Measured (5060 Ti): `nsys` `gconv_fwd_L1` per step, two runs: 1971 / 1949 -> 1861 / 1860 us (`-5%`). Fresh-plan ABBA on `MPtrj` `SrTiO3` with the installed binary: `a` = S29 `12.0380`, `b` = new `11.9423` (`0.9921`); reversed `a` = new `11.9519`, `b` = S29 `12.0612` (new / old `0.9910`). `cmp_libs` S29 vs new `dE 1.8e-4` eV total on `E = -39857` eV, `dF 1.2e-6`. 3x gate (`MPtrj`, oxide set, cached references) passes on all six configurations with the installed binary (`dF` ratio <= 1.30, `dS` ratio <= 0.88); `pytest` 67 passed. The installed `libloupmd.so` is the exact binary that was timed and gated.
- Rejected with it (S29): `PAIR = true` at `C = 256` (`gen-conv-fwd-l1-pair-c256`): 104 registers, L1 convs `4952 / 4953` vs base `4928 / 4975 us`.
- Sources: this file.

<a id="gen-conv-bwd-512thr"></a>
#### gen-conv-bwd-512thr: 512-thread blocks for the shared-memory-limited backward convs
- Switch: `python/gen_generic.py` `launch_conv_bwd`: `gconv_bwd_L1` launches 512 threads when `C == 256`, `gconv_bwd_L2lp` when `C == 224` (otherwise 256); regenerated into `src/generated_generic.cu`. Both kernels already have `__launch_bounds__(512)`; the prologue strides channels by `blockDim.x` and edges by the warp count.
- Stage: S31 (14 November 2026).
- What: `ncu` on `MPtrj` `gconv_bwd_L1` (S29 entry) showed 62 registers but 29% achieved occupancy: the per-block `s_q` (`C x 44` floats, 45 KB at `C = 256`, 39 KB at `C = 224`) allows 2 blocks per SM, so 256-thread blocks give 16 warps. With 512 threads the same 2 blocks hold 32 warps; registers (62 x 512 x 2) still fit. Measured after the change (`ncu`, installed build): `MPtrj` `gconv_bwd_L1` 2 blocks of 512 (limited by both registers and shared memory), theoretical occupancy 66.7%, achieved 59.1% (28.3 active warps per SM, was 29%), 2.44 ms; `OFF23-L` water216 `gconv_bwd_L2lp` the same limits, achieved 57.4% (27.6 warps), 531 us. At `C = 128` (22.5 KB, 4 blocks of 8 warps) occupancy is already 32 warps, so the change is limited to the measured large-`C` shapes.
- Status: DEFAULT (5060 Ti only). Each edge is still handled by one warp (`edge_dvec` written once per edge); only the order of the existing `dx` atomics can change.
- Measured (5060 Ti, scratch build with the guard `C >= 224`, identical device code for these models): `nsys` kernel per step, two runs: `MPtrj` `SrTiO3` `gconv_bwd_L1` 2932 / 2904 -> 2552 / 2544 us; `OFF23-L` water216 `gconv_bwd_L2lp` 600 / 598 -> 557 / 516 us. Fresh-plan ABBA, new / old: `MPtrj` `SrTiO3` `0.9695` (`11.926 -> 11.563 ms`) and reversed `0.9685`; `OFF23-L` water216 `0.9825` / `0.9847`; `OFF23-L` water (5,184 atoms) `0.9825` (`26.95 -> 26.48 ms`) / `0.9839`. `cmp_libs`: `MPtrj` `dE 2.7e-7`, `dF 7.9e-7`; `OFF23-L` water216 `dE 8.7e-6` (of `E = -449493` eV), `dF 2.0e-6`. The adopted guards are exact (`C == 256`, `C == 224`) so untested `C` values keep 256 threads. Final exact-guard binary (installed) vs S30: kernels `MPtrj` `bwd_L1` 2927 / 2946 -> 2545 / 2536 us, `OFF23-L` water216 `bwd_L2lp` 603 / 620 -> 532 / 520 us; ABBA `MPtrj` `0.9703` (`11.930 -> 11.576 ms`) and reversed `1.0302` (new / old `0.9707`), `OFF23-L` water216 `0.9838` and reversed `1.0219` (`0.9786`). 3x gates pass: `MPtrj` oxide all six (`dF` ratio <= 1.34, `dS` <= 1.31), `OFF23-L` organic all eight (`--ref-device cpu`, `dF` <= 0.41, `dS` <= 1.00); `pytest` 67 passed.
- `gconv_bwd_L2` (`C = 224`, same pass, `ncu` `OFF23-L` water216): 829 us, 128 registers and 27.8 KB shared memory (3 blocks of 4 warps, 25% occupancy), but SM compute 68%, long scoreboard 0.50 and not-selected 1.30, so it is issue-limited and more warps are not expected to help (not tried). The forward lx 2 occupancy test is in `gen-conv-fwd-l2-minb3`.
- Sources: this file.

<a id="gen-conv-fwd-l2-minb3"></a>
#### gen-conv-fwd-l2-minb3: three blocks per SM for the `C = 224` lx 2 forward convs
- Switch: none (scratch: `__launch_bounds__(MAX_T, MAX_T == 224 ? 3 : 1)` in the forward template of `python/gen_generic.py`, `gconv_fwd_L2a/L2b` dispatched with `MAX_T = 224` at `C = 224`).
- Stage: S31 (14 November 2026).
- What: `ncu` (`OFF23-L` water216) on `gconv_fwd_L2a` / `L2b` (`C = 224`, 224 threads): 410 / 392 us, 104 / 125 registers, register-limited to 2 blocks (14 warps, 29% occupancy), L2 throughput 73% / 64%, long scoreboard 3.11 / 1.59. A third block per SM needs <= 97 registers.
- Status: REJECTED.
- Measured (5060 Ti): the compiler went to 80 registers with 56-72 B of stack; `nsys` kernel time for the pair, two runs: 761 / 757 -> 1013 / 1023 us (`+34%`).
- Sources: this file.

<a id="gen-conv-bwd-l0-red"></a>
#### gen-conv-bwd-l0-red: atomic per-edge update in `gconv_bwd_L0`
- Switch: `python/gen_generic.py` `EDGE_DVEC_RED` (used by `emit_conv_bwd_lp(0)` only), `#if __CUDA_ARCH__ == 1200`: `atomicAdd` into `edge_dvec`; other architectures and the lx 1 / 2 kernels keep `EDGE_DVEC_RMW` (`sm_89` / `sm_90`: all 91 kernels of `generated_generic.cu` SASS-identical to S39; `sm_120`: only the 12 `gconv_bwd_L0` instantiations differ).
- Stage: S40 (14 November 2026).
- What: `ncu` source counters on `gconv_bwd_L0<true, 128, true>` (`OMAT-0-S` `SrTiO3`): long scoreboard is 38.7% of all warp stall samples. By consumer instruction: the per-edge metadata at the top of the edge loop (`FMNMX` on `vec_len.w`, `FADD` on `act_t_sx.t`) ~14%, the packed-table decode `LOP3`s ~12%, the sender `x0` ~6%, and lane 0's `edge_dvec[e] += f` read-modify-write ~4%. Each edge has one writer (lane 0 of its warp) in this kernel, so an atomic add rounds like the read-add-store (except for subnormals, which per-edge forces do not reach) and, as a RED, has no load to wait on.
- Status: DEFAULT (5060 Ti since S40; every GPU since S129, [gen-arch-neutral](#gen-arch-neutral)).
- Measured (5060 Ti): `nsys` kernel time per step, two runs each: `OMAT-0-S` `SrTiO3` `1264 / 1256 -> 1174 / 1138 us` (`-8%`), `OFF23-S` water `616 / 620 -> 524 / 519 us` (`-16%`). Final binary, fresh-plan ABBA: `OMAT-0-S` `SrTiO3` `4.689 -> 4.601 ms/step` (`0.9813`), reversed `4.705 -> 4.596` (`0.9768`); `OFF23-S` water `3.052 -> 2.966` (`0.9718`), reversed `3.043 -> 2.971` (`0.9763`). `cmp_libs` at float32 noise (`OMAT-0-S` `dF 1.2e-6`, `OFF23-S` `5.6e-6`, `MPA-0` `2.4e-6`); gates `OFF23-S` organic 8 / 8, `OMAT-0-S` oxide 6 / 6, `MPA-0` oxide 32 / 32; `pytest` 67 passed.
- Rejected on the way (one variable each, same `ktime` protocol): RED in the lx 1 / 2 backward convs: `OFF23-M` `gconv_bwd_L1` `2281 -> 2255 us` (`-1%`), `OFF23-L` water216 `L2lp + L2` `1329 -> 1305` (`-2%`), below the stop rule, so they keep the read-add-store. Next-edge metadata prefetch (registers, one iteration ahead, `sm_120` only) on top of RED: `gconv_bwd_L0` `-3%` (`OMAT-0-S`), `-1%` to `-10%` within noise (`OFF23-S`), and `gconv_bwd_L1` `+1%` with an 8-byte spill at its 64-register limit: rejected.
- S101 (16 November 2026): with S98 the top conv layer assigns its per-edge vectors, so the remaining read-add-stores were the lower conv layers' (multi-layer models) and `gconv_bwd_L2`'s (after `L2lp`); they now use RED on sm_120 too (generator: `EDGE_DVEC_RED` in both). Library ABBA on shared plans, S100 -> S101, 3 rounds: OMOL-0 water216 `0.9989` (`0.9989` / `0.9990`), OFF23-L water216 `1.0004` (`1.0013` / `0.9994`), POLAR-1-L NaCl216 `1.0006` (`1.0015` / `0.9997`); gates OFF23-L organic 0.47 / 1.28 (CPU references), OMOL-0 organic 0.80 / 0.91, POLAR-1-L crystals 1.46 / 0.70. Kept: the same arithmetic, one fewer load per edge, OMOL-0 slightly faster in both orders and the lx 2 models at a tie.
- Sources: this file.
- S41, the next kernels by the same attribution (`ncu` source counters, 5060 Ti; shares of all warp stall samples):
  - `gconv_fwd_L0` (`OMAT-0-S` `SrTiO3`): long scoreboard 34%, of which two per-edge 4-byte `x0[snd]` gathers feeding the first products ~27% and the packed-table decode ~6%; barrier ~10% (tile staging). A variant keeping the next two edges' `x0` in registers one iteration ahead (`sm_120` only, lx 0 only; 59-60 registers at `C = 128`, a 40-byte spill in the runtime-`C` variant) was slower: `nsys` kernel time `733 / 710 -> 774 / 791 us` (`OMAT-0-S`, `+8.5%`), `349 / 344 -> 351 / 346` (`OFF23-S`, tie); results at float32 noise. Reverted.
  - `first_bwd_edge_kernel` (`OMAT-0-S`): short scoreboard (shared memory) 24%, not selected 18%, long scoreboard 16% spread over two `LDG.128` loads (6% / 4%); no single dominant load.
  - `gconv_bwd_L1` (`OFF23-M` water): not selected 34%, long scoreboard 21% (largest single load ~5%), dispatch 12%: issue-limited, as recorded in `s33-mptrj-l1-after`.
  - OMAT-0 medium (specialised, `SrTiO3`; fresh `nsys`: `w'` 34%, spline 21%, `sgemm128` 21%, i0 backward 6.4% of 8.8 ms of kernels): `wprime_backward_inter1_rcv` not selected 40%, dispatch 15%, long scoreboard 11% with no load above 3%: issue-limited, as `meas-ncu` / S32 found. `tabled_outer_sum0_backward_kernel`: wait 24%, short scoreboard 21%, long scoreboard 17%, no instruction above 4%. No single latency target in either.
- S42 (`ncu`, `OMAT-0-S` `SrTiO3` unless noted): `gprod_ro1_fused` 82% and `gprod_bwd` 87% of DRAM peak (at the roofline, as S28 found); `POLAR-1-S` `NaCl216` `sgemm64` (17 us launches): `selected` 50%, i.e. issue at the small-grid limit (`s23-small-m-gemm`). `first_fwd_kernel` (226 us, DRAM 59%): barrier 23%, long scoreboard 21% (its per-edge table `LDG.128` ~10%). `#pragma unroll 4` on its edge loop (`sm_120` only, 60 registers, no spill) to keep four rows in flight was slower: `nsys` `268 -> 304 us` (`OMAT-0-S`, `+13%`), `154 -> 179` (`OFF23-S`, `+17%`), `188 -> 237` (`OFF23-M`, `+26%`). Reverted.
- S43, `OFF23-L` water (fresh `nsys`, 28.3 ms of kernels per step: `gconv_bwd_L2` 22.7%, own `sgemm128` 21%, `gconv_bwd_L2lp` 14.7%, `gconv_fwd_L2a` / `L2b` 11.7% / 10.8%, cuBLAS 8.1%); `ncu` on water216: `gconv_bwd_L2<true, 224, true>` 830 us, 128 registers, 128 threads, 27.8 KB shared, theoretical / achieved occupancy 25% / 23% (shared memory: 3 blocks per SM), stalls not selected 31%, selected 26%, dispatch 15%, long scoreboard 14% with no load above 5%: issue-limited even at 3 warps per scheduler. `gconv_bwd_L2lp` (after S31's 512 threads): 508 us, not selected 33%, long scoreboard 20% (largest load 5%), L2 75%: issue-limited. Neither has a latency target; only fewer instructions per edge-channel would help.
  - S44: `gconv_bwd_L2` at `C = 224` with 256-thread blocks (template `NT`, `s_dy[NT / 32][16]`; S31's lever for its siblings): 128 registers, no spill, 2 blocks / 16 warps per SM instead of 3 / 12. `nsys` kernel time per step: water216 `806 / 784 -> 750 / 771 us` (`-4%`), water `6885 / 6715 -> 6714 / 6530 us` (`-3%`); results at float32 noise. Below the 10% stop rule: reverted. More warps barely help an issue-limited kernel.
- S45, GEMM plans timed in the captured graph (open item from `meas-plan-variance`), falsifier: six independent fresh tunings each (empty `LOUP_CACHE_DIR`, so every shape is re-timed in isolation; `ab_fam` child, median of 6 x 256 steps). `POLAR-1-S` `NaCl216`: 1.4935-1.5335 ms/step (spread 2.7%, median 1.4% above the best); `MH-1` `NaCl216`: 1.5262-1.5462 (spread 1.3%, median 0.9% above the best). The spread includes run-to-run noise and is mostly the tuner's isolated near-tie picks varying, so it bounds only what re-tuning in isolation leaves on the table (<= ~1%). It does not test the idea itself: plans that the isolated tuner never picks (e.g. the 54 vs 80 us alternative recorded above) could still win inside the graph. That needs forced alternatives timed in the captured graph; still open.

<a id="gen-conv-bwd-l2-pullr"></a>
#### gen-conv-bwd-l2-pullr: radial pull from the x-gradient contraction in `gconv_bwd_L2`
- Switch: `python/gen_generic.py` `emit_conv_bwd_L2`: each path's per-channel contraction is emitted twice, the new form under `#if __CUDA_ARCH__ == 1200`, the old one otherwise (`sm_89` / `sm_90`: all 91 kernels of `generated_generic.cu` SASS-identical to S47; `sm_120`: only the 12 `gconv_bwd_L2` instantiations differ).
- Stage: S48 (14 November 2026; direction chosen by the owner after S47).
- What: `gconv_bwd_L2` (the x-degree-2 backward paths of the lx 2 models) was issue-limited (S43: not selected 31% + selected 26%, no load above 5% of stall samples). Per edge and channel, each path forms the edge-invariant `A[m1, m2] = sum_m3 W g[m3]` (111 values over the 7 paths, ~15% of the arithmetic; hoisting them would need 111 floats per channel of shared memory) and then three contractions: the radial pull `sum_{m1, m2} A x[m1] Y[m2]` (one triple product per `A` entry, about a third of the arithmetic), `dY[m2] += R sum_m1 A x`, and the x gradient `gx[m1] += R sum_m2 A Y`. The radial pull equals `sum_m1 x[m1] Cg[m1]` with `Cg[m1] = sum_m2 A[m1, m2] Y[m2]`, which the x gradient computes anyway: one term per `m1` instead of one per `A` entry. The summation order of the pull changes (float32 rounding level).
- Status: DEFAULT (5060 Ti since S48; every GPU since S129, [gen-arch-neutral](#gen-arch-neutral)).
- Measured (5060 Ti): `gconv_bwd_L2<true, 224, true>` SASS 1624 -> 1464 instructions, 128 registers both, no spill. `nsys` kernel time per step: `OFF23-L` water216 `808 / 796 -> 655 / 655 us` (`-18%`), water `6705 / 6689 -> 5590 / 5663 us` (`-16%`), `POLAR-1-L` `NaCl216` `219 / 218 -> 202 / 201 us` (`-8%`). Fresh-plan ABBA, new / old: `OFF23-L` water `26.47 -> 25.47 ms/step` (`0.9624`), reversed `0.9609`; water216 `3.680 -> 3.558` (`0.9666`), reversed `0.9639`; `POLAR-1-L` `NaCl216` `1.0024` / `0.978` (the kernel is ~1.6% of that step: a tie). `cmp_libs` at float32 noise (`OFF23-L` water216 `dF 1.3e-6`, `POLAR-1-L` `3.2e-7`). Gates (CPU references) `OFF23-L` organic 8 / 8, `POLAR-1-L` crystals 6 / 6. `pytest`: one full run had `test_polar_energy_follows_a_small_cell_change_on_the_same_engine` fail (`POLAR-1-S`, which has no lx 2 kernel; it passed 2 / 2 in isolation with both this and the previous library); two further full runs on the installed binary: 67 passed each.
- S49, the same search in the other issue-limited per-edge-channel kernels (a source-level survey of the generated code, path by path; no SASS or timing check): `gconv_bwd_L1` and the specialised `wprime_backward_inter1_rcv` (same late pull-back structure) contract each path's own `Q` block with `n` / `x`, and their repeated `x . n` terms are identical pure expressions (left to the compiler's common-subexpression elimination; not verified in SASS); `gconv_bwd_L2lp` has no `A` forms (S48 count); the forward convs (`gconv_fwd_L2b` and the others) use one `w * x` product per sender component and one FMA per folded Clebsch-Gordan form. No sum of the S48 kind (a full contraction recomputed beside a partial one that contains it) remains. The one rewrite left, spherical-harmonic `h` with the pull gradient deferred to the edge end for the scalar paths of `gconv_bwd_L0` / `L1` (`0,2,2` and `0,3,3`), would save ~22 FMA per edge-channel in the source but add ~12 values to each edge's cross-lane reduction: a single-digit net estimate from source counts, not built.
- Sources: this file.

<a id="gen-conv-bwd-lp-defer-sh"></a>
#### gen-conv-bwd-lp-defer-sh: deferred pull-back of the scalar l >= 2 paths in the late pull-back convs
- Switch (reverted): `python/gen_generic.py` `emit_conv_bwd_lp`, `sm_120` branch, paths `(0, 2, 2)` / `(0, 3, 3)` of `gconv_bwd_L0` / `L1` / `L2lp`.
- Stage: S50 (14 November 2026; owner chose to build the S49 estimate as a falsifier).
- What: `h = sum_i q_i c_i(n)` with per-edge polynomial coefficients `c_i` (expanded with sympy from the same Cartesian contraction), and each lane summing `T_i = sum_ch w x0 q_i` over its channels, adding `l v(T)` to `pull_G` once per edge before the existing four-value shuffle reduction (v is linear in q, so no extra shuffles). Per channel iteration the source drops 16 -> 10 operations for `(0, 2, 2)` and 33 -> 14 for `(0, 3, 3)`.
- Status: REJECTED.
- Measured (5060 Ti): registers (`cuobjdump --dump-resource-usage`, S48 build vs S50) `gconv_bwd_L0<true, 128, true>` 60 -> 64, `gconv_bwd_L1<true, 128, true>` 62 -> 101, `gconv_bwd_L2lp<true, 224, true>` 62 -> 101, `STACK:0` throughout (the 12 `c` and 12 `T` values live across the channel loop); static SASS `L0<128>` 600 -> 656, `L0<96>` 656 -> 712, `L1<128>` 944 -> 992. `nsys` sum of `gconv_bwd*` per step, two A/B pairs each: `OMAT-0-S` `SrTiO3` 1156 / 1164 -> 1181 / 1219 us (+2 / +5%), `OFF23-S` water 515 / 516 -> 528 / 535 (+3 / +4%), `OFF23-M` water 2310 / 2288 -> 2580 / 2591 (+12 / +13%). `cmp_libs` at float32 noise (`OFF23-M` water `dF 3.0e-5` of `|F|max 40`). Slower even in `L0`, which stayed within 64 registers: the per-edge polynomial and `v(T)` work, done by every lane, costs more than the ~3-4 channel iterations per lane save. Reverted; the rebuilt library is SASS-identical to S48, and the installed binary is the S48 one.
- Sources: this file.

<a id="gen-pack-refine"></a>
#### gen-pack-refine: radial bands refined until the 8-byte tables pack
- Switch: `python/export_generic.py` `refine_for_packing` / `packed8_band_errors` (after `spline.fit`, conv layers).
- Stage: OMOL-0 support (14 November 2026, `4af8b06`).
- What: the conv layers' radial tables are stored as 8-byte cubics (CUBIC_PACKED8: one exponent per entry, set by the largest of `|a0|`, `2^8 |a1|`, `2^14 |a2|`, `2^19 |a3|`; 20 / 19 / 12 / 8 mantissa bits), and the loader refuses a table whose error exceeds `kPackedTableMaxRelErr` (5e-4 of the column's largest value or r-slope). `spline.fit` refines bands for its accuracy certificate only. MACE-OMOL-0 XL's steep short-range radial functions left bands where the curvature terms set the exponent: layer 1 (H, C, N, O) measured 2.06e-3 in the 0.5-0.75 A band, layer 2 1.3e-3; `loup_create` refused the bundle. The export now estimates the packing error per band (sampled; it matched the loader's exact 2.061e-3), refines every band above half the bound (spacing x `1.05 sqrt(score / target)`), recomputes the coefficients and re-certifies.
- Status: FIX.
- Measured: OMOL-0 H, C, N, O layer 1 1,764 -> 2,031 intervals (worst band 1.76e-4), layer 2 400 -> 719 (1.83e-4); its organic gate passes (`STATUS_AND_PROFILE.md` 5.2). Other families, every non-OMOL generic bundle in the cache (`.tmp_o/pack_all.py`): the 25 model / species sets with a copy from before the refinement (OFF23 S / M, OFF23b, POLAR-1 S / M / L, MH-1, OMAT-0 small) have identical conv grids before and after; the 16 with one copy (OFF23-L, OFF24, MPtrj, MH-1 `matpes_r2scan`, OMAT-0 medium generic, `2023-12-03-mace-128-L1`, some species sets) estimate at most 1.44e-4, below the 2.5e-4 trigger. Three legacy specialised-path files were not readable and are not generic bundles. The full pytest (70 passed) ran with the refinement in place.
- S103 falsifier (16 November 2026, 5060 Ti, scratch, reverted): a 6-byte entry would cut the L1 convs' L2 traffic by ~20%. `ncu` (OMAT-0 medium generic SrTiO3, 5,000 atoms): `gconv_fwd_L1` L2 at 81.5% of peak, 347 read sectors per edge (packed table ~83%, sender `x` the rest), issue 49%; `gconv_bwd_L1` L2 at 82.4%, 370 read + 64 reduction sectors per edge, issue 76%. Both run at the L2 limit for 8-byte entries. Precision simulated at load in the current layout (`a0..a3` re-quantized to 16 / 15 / 8 / 5 bits, as a 48-bit entry with a 4-bit exponent would hold; `pack L1` 1.6e-3 to 2.4e-3): 3x gates fail everywhere, worst force / stress ratio OMAT-0 medium generic oxide 21.7 / 37.9 (2.04 / 1.83 at 8 bytes), OFF23-M organic 7.9 / 13.5 (0.34 / 0.60), MH-1 crystals 11.7 / 6.1 (0.84 / 0.28), OMAT-0 small oxide 17.5 / 14.3 (1.22 / 1.24). The table quantization already sets much of OMAT-0 medium's gate margin; fewer table bits are closed.
- Sources: this file.

<a id="gen-chain-fold"></a>
#### gen-chain-fold: the skip chain of the non-last layers folded into composed weights
- Switch: `src/generic.cu` `GenericModel::setup_chain_fold` (end of `load`), `GenericLayer::fold`, `record` (forward: one GEMM per fold target after a non-last layer's product, in place of that layer's `W_p` / `W_sc` products and the later layers' `linear_up`; backward: `dy_t` from the targets' `dx` / readout `dhid`, no `dh_in` products), `alloc_system` (no `hout` / `dhout` for folded layers). Compute capability 12.0 only; `LOUP_CHAIN_FOLD=0` disables.
- Stage: S57 (14 November 2026), 5060 Ti only.
- What: in a model whose layers are all gated blocks (kind 4), with no readout before the last layer, no per-species skip, a folded last readout and no long range, a non-last layer's `hout_t` is read only through linear maps: the next layer's `linear_up` and skip, down to the last layer's readout (`ro_W1_sc = W_sc ro_W1`). The load composes, from the last layer back and per degree l, the target list of `hout_t[l]`: `(x_{t+1}[l], W_up_{t+1}[l])` plus every target of `hout_{t+1}[l]` right-multiplied by `W_sc_{t+1}[l]`, the last skip ending in the readout hidden (`W_sc_last[0] ro_W1`). Each target stores `Wy = W_p_t[l] M` and, for layer 0 and l 0, `Wh = W_sc_0[0] M` on the species-embedding input. The composition runs in double on the GPU (`dmm_kernel`) and is rounded once to float32 (`d2f_kernel`). Forward: one GEMM per target into `x_s[l]` or `hid` (the first write assigns, later ones accumulate). Backward: `dy_t[l] = sum over targets of d(dest) Wy^T`.
- OMOL-0 XL (3 layers, 1024 hidden channels): the 1024 x 1024 `W_p` / `W_sc` products of layers 0 and 1, and layers 1 and 2's `linear_up` from 1024 channels, go in both directions; in their place come products of width 128 (`x`) and 16 (readout hidden).
- Status: DEFAULT (5060 Ti only; other GPUs keep the plain path). S73 ([gen-chain-fold-ext](#gen-chain-fold-ext)) lifted the gated-only, readout-free and species-free conditions: MH-1 and the non-gated families fold too.
- Measured (5060 Ti): fold against `LOUP_CHAIN_FOLD=0` on one build (`ab_env.py`, fresh GEMM plans): water216 (648 atoms) 29.02 -> 23.83 ms/step (`0.821`), reversed 29.05 -> 23.85 (`0.821`); water (5,184) 217.9 -> 179.8 (`0.825`), reversed 217.9 -> 179.8 (`0.825`). Exactness, same build, rattled water216: neutral `dF` 1.8e-6 eV/A (`|F|max` 9.9), `dE` 1e-5 meV/atom, `dS` 1.7e-9; charge +1 / doublet `dF` 3.6e-6, `dE` 1.4e-5 meV/atom, `dS` 1.2e-8. Organic gates on the fold path pass: neutral worst force / stress ratio 0.86 / 0.79, charge +1 doublet 0.31 / 0.19. Eligibility of the newest cached bundle per family (setup's rules): only OMOL-0 XL; MH-1 has a layer-0 readout, POLAR-1 long range, OFF / OMAT-0 / MPtrj non-gated layers and per-species skips. SASS of `generic.cu`'s 23 existing kernels identical to HEAD for `sm_89`, `sm_90` and `sm_120`; the composition kernels are new.
- Sources: this file.

<a id="gen-sgemm-issue"></a>
#### gen-sgemm-issue: issue limits of `sgemm128_kernel` on 1024-wide products (no change)
- Stage: S58 (14 November 2026), 5060 Ti, standalone harness (`.tmp_o/sg_mb.cu`, `.tmp_o/sgv.py`, `.tmp_o/sg192.cu`), OMOL-0 XL after S57.
- Why: after S57 the GEMMs are 73% of OMOL-0's kernel time on water216 (21.3 of 29.2 ms per step); the 1024 x 1024 message linears (`W_2`, forward and backward, all three layers) are ~130 of ~242 GFLOP per step and sit between two nonlinear steps (gate, symmetric product), so only a faster GEMM shortens them. Tuned per shape, the step's 49 GEMM shapes run at 9-17 TFLOP/s in isolation; inside the step at the same times (no concurrency penalty).
- `ncu`, `sgemm128_kernel<8, true, true>` at `4536 x 1024 x 1024` (2.41 GHz under `ncu`: 22.2 TFLOP/s float32 peak): 15.5 TFLOP/s (70%); 88% of issued instructions are FFMAs; issue slots busy 74% at 3.8 warps per scheduler (2 blocks of 256, capped by 128 registers and 48 KB); stalls per issued instruction: `dispatch_stall` 0.94, `barrier` 0.32, `short_scoreboard` 0.15, `mio_throttle` 0.13, memory < 0.05.
- Falsifiers (each output's in-order fmaf chain kept; bit-identical): FFMA order serpentine over columns (dispatch 0.94 -> 1.18, issue 70%) and column-outer (1.43, 67%): 4-7% slower. `__launch_bounds__(256, 1)`: 167 registers, dispatch 0.44, but 2 warps per scheduler, issue 68%: 4-9% slower. A 192 x 128 tile with 384 threads (167 registers, 3 warps per scheduler, 60 KB): dispatch 0.57, barrier 0.33, issue 72%; `4536` +12-14%, `1944` +10-13% (2.4 / 5.3 waves against 4.0), `3240` -1 to -4%, `648` -27% (where the tuner's `sgemm64` already runs 107 us). Register allocation drives the dispatch stalls, but none of these lifts issue enough to pay for its lost warps or waves.
- Status: REJECTED (no change; stop rule: no >= 10% kernel gain).
- Sources: this file.

<a id="gen-species-tables"></a>
#### gen-species-tables: layer 0's species-only GEMMs as per-species tables
- Switch: `src/generic.cu` `GenericModel::setup_species_tables` (end of `load`, before `setup_chain_fold`), `GenericLayer::res0_table`, `GenericLayer::FoldTarget::Th`, `record` (both gathers on the main stream before the lanes fork; layer 0's `x` GEMM skipped). Compute capability 12.0 only; `LOUP_SPECIES_TABLES=0` disables. The load-time composition helpers (`DevCompose`, `device_is_cc120`) are shared with S57.
- Stage: S59 (14 November 2026), 5060 Ti only.
- What: layer 0's input is the species embedding row (OMOL-0: with the charge / spin vector folded in at export), so the gated block's residual `res[0] = (h W_up[0]) W_res[0]` (its `x` feeds nothing else in the hidden-table layer) and the S57 skip terms `h Wh` depend on the species only. They become [S, cols] tables composed in double and rounded once to float32, one row gather per atom; layer 0 takes no gradient into `h`, so the backward is unchanged. OMOL-0 XL water216 loses a 648 x 1024 x 1024 (`W_up`) and a 648 x 4096 x 1024 (`W_res`, 381 us, the longest lane at layer 0's start) GEMM and the `Wh` GEMMs per step.
- Exactness (tables vs `LOUP_SPECIES_TABLES=0`, one build): OMOL-0 water216 neutral `dF` 1.2e-6 eV/A, `dE` 2.1e-5 meV/atom, `dS` 1.1e-9; +1 doublet `dF` 4.0e-6, `dE` 9.5e-5, `dS` 2.3e-8; MH-1 NaCl216 `dF` 2.5e-7, `dE` 5.9e-5, `dS` 7.8e-10. With `LOUP_CHAIN_FOLD=0` on both sides (residual table only): OMOL-0 neutral `dF` 2.7e-6, +1 doublet `dF` 2.3e-6.
- First build (every first-hidden gated family), ABBA tables / plain, plain-first / tables-first: OMOL-0 water216 0.977 / 0.978; MH-1 NaCl216 0.993 / 0.996, NbCl5 0.997 / 0.997; POLAR-1-S NaCl216 0.957 / 0.972; POLAR-1-M 0.988 / 0.994; POLAR-1-L 0.981 / 1.006, repeated 0.968 / 1.006 and 0.995 / 1.000: no win in the tables-first order. The long-range models (POLAR-1 S / M / L) therefore keep the GEMMs; with the exclusion their on / off differences are at their per-process GEMM-plan level (3e-8 to 6e-7 eV/A).
- Final binary (`libloupmd_s59.so`, installed): ABBA tables / plain OMOL-0 water216 23.78 -> 23.26 ms/step (`0.978`), reversed `0.977`; MH-1 NaCl216 `0.988` / `0.991`; NbCl5 `0.997` / `0.996`. Gates pass (8/8 organic, 6/6 crystals): OMOL-0 neutral / +1 doublet / -1 doublet / triplet worst force 0.86 / 0.31 / 0.83 / 0.83, stress 0.88 / 0.18 / 0.89 / 0.65; MH-1 `omat_pbe` crystals 0.87 / 0.27, `matpes_r2scan` crystals 0.86 / 0.32, `omol` organic 0.32 / 0.63. `generic.cu`'s 25 kernels SASS-identical to S57 for `sm_89` / `sm_90` / `sm_120` (S59 is host-side). `pytest` 71 passed.
- Status: DEFAULT (5060 Ti only; long-range models and other GPUs keep the GEMMs).
- Sources: this file.

<a id="s60-omol-prod-floor"></a>
#### s60-omol-prod-floor: OMOL-0 product and gate kernels at the DRAM floor (no change)
- Stage: S60 (14 November 2026), 5060 Ti, `ncu` in a water216 step (installed S59 library).
- `gprod_bwd_6f194247389dfa5c` (layers 0 and 1; 128 threads, 5,184 blocks, 80 registers, achieved occupancy 46%): 259 us at 2.54 GHz; DRAM throughput 89% of peak, L2 hit 2.7%, FMA pipe 13%; stalls per issued instruction long scoreboard 31.3, lg throttle 3.8, others < 1. ~103 MB moved: its compulsory traffic (reads the messages, 648 x 16 x 1024 floats = 42 MB, and the output gradient, 24 MB; writes the message gradient, 42 MB). The other three product kernels, one launch each: `gprod_fwd_6f194247389dfa5c` 121 us, DRAM 93.5%, FMA pipe 15.7%, L2 hit 3.9%; `gprod_fwd_4715eda4cc3ebda5` (last layer, scalar output) 118 us, DRAM 95.4%, FMA 4.1%, L2 hit 1.9%; `gprod_bwd_4715eda4cc3ebda5` 191 us, DRAM 86.7%, FMA 3.8%, L2 hit 1.1%; long-scoreboard stalls dominate in all. `gate_fwd` / `gate_bwd` (300 / 529 us) move ~125 / ~207 MB, the same floor.
- So these kernels shorten only with fewer bytes: fusing the product into the `W_2` GEMMs would need all 16 (l, m) rows of an atom in one block, while the GEMMs run per degree. Not pursued (no cheap falsifier).
- Status: MEASURED (no change).
- Sources: this file.

<a id="gen-prod-w2-fusion"></a>
#### gen-prod-w2-fusion: the symmetric product fused into the `W_2` GEMMs (no change)
- Stage: S61 (14 November 2026), 5060 Ti, standalone harness `.tmp_o/sg_grp.cu`, OMOL-0 XL shapes (C = 1024).
- Why: the four product kernels are DRAM-bound (S60, ~1.07 ms per water216 step); fusing them into the `W_2` GEMMs (`msgf[l] = gout[l] W_2[l]`, then the product) would drop their DRAM round trips. The product needs all 16 (l, m) rows of an atom per channel, so the fused GEMM must tile atom-major: 8 atoms = 8 + 24 + 40 + 56 rows of degrees 0-3, each with its own weight. Each thread's 8 rows can share one degree (8 / 24 / 40 / 56 are multiples of 8), but every block needs all four B tiles per K step: 4x the B traffic and 80 KB of shared memory at two stages, one block per SM (168 registers, no spill).
- Falsifier: that grouped GEMM alone (no product), against the four per-degree products the tuner picks (`sgemm64` at 648 rows, `sgemm128` above) sequentially and on four concurrent streams (the step's fork / lane / join); hot L2, median of 5 x 11. 648 atoms: separate 1,439-1,504 us, four lanes 1,493 / 1,504 us, grouped 1,555 / 1,547 us (`1.042` / `1.028`); 5,184 atoms: four lanes 11,537 us, grouped 13,070 us (`1.133`). Outputs bit-identical (0 of 10.6 M / 84.9 M differ).
- Fused forward prototype (`.tmp_o/gen_fused.py` builds `.tmp_o/sg_fused.cu` from `sg_fused_tmpl.cu`): the grouped GEMM still writes `msgf` (the product backward reads it), stages the 128 x 128 tile in its shared memory and runs the generated body of `gprod_fwd_6f194247389dfa5c` per (atom, channel) (4 per thread; 168 registers, no spill). Against four GEMM lanes + the generated kernel, same harness: 648 atoms 1,708 -> 1,573 us (`0.921`), repeated 1,641 -> 1,552 (`0.946`); 5,184 atoms 12,610 -> 13,281 (`1.053`). `msgf` and `y` bit-identical (0 differing values). So the forward fusion pays at small sizes (90-135 us per layer: with three layers ~0.3 ms, ~1.3% of the water216 step, assuming the last layer's scalar product fuses alike) and loses on large ones (one block per SM); it would need a size-dependent choice.
- Backward (not prototyped): each of the eight output-channel tiles needs the product backward over all channels of its atoms, so it is recomputed 8x inside the GEMM, against <= ~450 us per layer saved (product backward + `dmsgf` round trip).
- Size sweep and diagnosis (S61c; `GBK` / `GMINB` compile options and per-part timings in the harness). Fused / current, two sweeps (the second with parts): 72 atoms 0.59 / 0.64, 144 0.74 / 0.75, 216 0.83 / 0.92, 432 0.88 / 0.93, 648 0.96 / 0.96, 864 0.95 / 1.03, 1,080 0.98 / 1.02, 1,296 0.97 / 1.00, 1,728 1.01 / 1.05, 2,160-5,184 1.03-1.04 (run-to-run spread ~3%). Parts (us; four GEMM lanes, grouped GEMM alone, product kernel, epilogue = fused - grouped): 72 atoms 257 (9.4 TFLOP/s) / 168 (14.4) / 11 / 1; 216 570 (12.7) / 501 (14.5) / 15 / 6; 432 1,018 (14.2) / 1,011 (14.3) / 104 / 11; 648 1,507 (14.4) / 1,549 (14.0) / 176 / 39; 1,296 2,871 (15.2) / 3,205 (13.6) / 386 / 49; 2,592 5,607 (15.5) / 6,530 (13.3) / 740 / 76; 5,184 11,496 (15.1) / 13,121 (13.3) / 1,511 / 166 (the epilogue's share at large sizes is within the ~3% spread). Below ~400 atoms the win is not the fusion: the product costs 10-30 us (`msgf` stays in the 32 MB L2), and one grouped launch fills the GPU better than four small per-degree GEMMs (9-13 TFLOP/s). From ~400 atoms `msgf` leaves L2, the product becomes a DRAM round trip and the fusion saves ~0.26 us per atom, while the per-degree GEMMs reach 15.1-15.5 TFLOP/s and the grouped one stays at 13.3-13.6, ~0.31 us per atom more. Both grow linearly. Five repeats per size (fused / current, min-max): 648 atoms 0.90-0.96, 756 0.97-1.00, 864 0.97-0.98, 972 0.99-1.02, 1,080 0.97-1.04, 1,188 1.02-1.07, 1,296 0.99-1.05, 1,512 1.03-1.06, 1,728 1.01-1.04: (all timed current-first). Timing order matters: whichever path is timed first runs up to ~5% faster (current-first 648 atoms 0.99-1.00, fused-first 0.94-1.00; 864-1,296 atoms current-first 1.01-1.06, fused-first 0.95-0.98). Interleaved ABBA rounds (16 per size, alternating order; median, three passes): 216 atoms 0.73 / 0.93 / 0.91, 432 0.89 / 0.97, 540 0.95 / 1.03, 648 0.94 / 0.97 / 0.95-0.99, 756 1.01 / 1.03, 864 0.97 / 0.98, 972 0.99 / 1.02, 1,080 0.98 / 1.00 / 1.01-1.02, 1,188 1.02 / 1.00, 1,296 0.97 / 0.99, 1,512 0.99 / 0.96, 2,592 1.03 / 1.01, 5,184 1.03-1.04 (single rounds spread +-5-10%). Why the spread: the card runs at its 180 W power limit (178-180 W drawn); the SM clock follows power, 2,512 / 2,572 / 2,835 MHz at the 10th / 50th / 90th percentile of one pass (nvidia-smi, 250 ms samples), so the two paths, which draw power differently, run at different clocks (clock locking needs admin rights on the Windows host). Stable result: a win below ~450 atoms, a loss of 1-4% from ~2,600 atoms; between ~500 and ~1,500 atoms the difference (<= ~3%) is smaller than the power-limited clock noise, so no crossover can be named there.
- Why the grouped GEMM is slower (`ncu`, identical at 648 and 5,184 atoms): one block per SM (shared memory 80 KB **and** registers 168 each allow one), 2.00 warps per scheduler, 1.23 eligible, issue slots 66.7% busy, against `sgemm128` (one degree, 36,288 x 1024 x 1024) 2 blocks, 3.97 warps, 2.61 eligible, 74.8% busy; the issue ratio 0.89 matches the TFLOP/s ratio 0.88. FMA share equal (88.7 / 89.7%); memory stalls negligible (long scoreboard 0.08), though L2 traffic is ~2.4x the four GEMMs' (14.25 GB at 5,184 atoms: four B tiles per K step). Two blocks per SM need half the shared memory: `GBK = 8`, `__launch_bounds__(256, 2)` gives 128 registers (24 B spill), 3.98 warps, but issue 65.5% (barrier stalls 0.07 -> 0.92 with twice the K steps, dispatch 0.42 -> 0.93 at the 128-register cap) and 12.5 TFLOP/s at 5,184 atoms. The cause is structural: mixing the four degrees in one tile needs four weight tiles per K step, so the tile either holds 2 warps per scheduler (BK 16) or doubles its barriers under a register cap (BK 8); the per-degree GEMMs load one weight tile and fit two blocks at BK 16 with three stages.
- Status: REJECTED (no change). Built into the engine behind a size limit as S62 (gen-w2-fused): slower in the full step at every size tested, because the harness baseline (fixed GEMM picks) was slower than the engine's tuned, overlapping lanes.
- Sources: this file.

<a id="gen-w2-fused"></a>
#### gen-w2-fused: S61's fused forward in the engine (no change)
- Stage: S62 (14 November 2026), 5060 Ti only, OMOL-0 XL.
- Built (reverted): `src/w2_grouped.cuh` (the grouped atom-major `W_2` GEMM of S61, writing `msgf` and leaving the tile in shared memory), `gen_generic.py` emitting `gprod_w2f_<sig>` per product signature (the product's own generated straight-line body reading x0..x15 from the tile; existing generated text unchanged, 168 registers, no spill; 208 for `00dc9085957f7969`), `generic.cu` `record` running it instead of the four `W_2` lanes + `gprod_fwd` for gated layers with `C_msg >= 1024` (sm_120, `LOUP_W2_FUSED=0` disabled it) up to 448 atoms (S61's harness boundary).
- Exact: fused vs `LOUP_W2_FUSED=0`, one build: naph288 `dF` 1.4e-6 eV/A, urea432 1.6e-6 (charge +1 doublet 3.5e-6); water216 (648 atoms, above the limit) at the per-process plan level (7e-7).
- Measured, full-step ABBA on one build, fused / plain (plain-first, then fused-first inverted): urea 2x2x2 (128 atoms) `1.020` / `1.019`, naphthalene 2x2x2 (288) `1.014` / `1.011`, urea 3x3x3 (432) `1.013` / `1.012`: slower at every size.
- Why (nsys, naph288, same plan cache): summed kernel time per step 14,326 -> 13,514 us, step span 10,885 -> 11,020 us. Per layer, from `gate_fwd`'s end to the product's end: plain 694-704 us with 984-997 us of kernels inside (the four `W_2` GEMMs on four lanes overlap, ~1.4x, using the tuner's per-shape picks, mostly `sgemm64` at these row counts), fused 727-742 us (one launch, one block per SM). S61's harness compared against a fixed `sgemm128` / `sgemm64` assignment on four streams, slower than the engine's tuned lanes, so its "win below ~450 atoms" does not hold in the step; the saved kernel time was off the critical path.
- Status: REJECTED (code reverted).
- Sources: this file.

<a id="gen-default"></a>
#### gen-default: every model on the generic path
- Switch: `loupmd/bundles.py` (`default_generic`): `LOUP_GENERIC=0` or `generic=False` select the specialised OMAT-0 medium kernels; `tools/dev/test_gate.py --specialised`, `loupmd validate --specialised`.
- Status: DEFAULT on `release/v1` (owner's decision O20: the specialised kernels are marginally faster on the 5060 Ti and not faster on the A100). 5060 Ti only here.
- Measured (15 November 2026, `tools/dev/bench_md.py`, one library, both orders): generic / specialised `NbCl5` 3x3x3 1.896 / 1.821 and 1.886 / 1.814 ms/step (1.0409, 1.0399); `SrTiO3` 10x10x10 8.245 / 8.097 and 8.230 / 8.113 (1.0184, 1.0144). `loupmd bench`'s shipped reference is the generic path's since: 1.881, 8.243 and 1.833 (`SrTiO3` 6x6x6, quick) against 1.813, 8.018 and 1.777.
- Against S63: 2.9% and 7.4% then; the per-system conv forward variants (S64) are the generic change since.
- Gate: PASS for the default and for `--specialised`.
- Not measured: the A100's figure on this build (the owner's statement stands for it); anything on the RTX 4000 Ada.
- Sources: [§6.6][s66]; PLAN.md O20, D42.

<a id="s63-spec-vs-gen"></a>
#### s63-spec-vs-gen: the specialised OMAT-0 path against the generic path (no change)
- Stage: S63 (14 November 2026), 5060 Ti, installed S59 library, `nsys` and `ncu`, `mace-omat-0-medium` (the specialised path also serves MP-0b3, MPA-0 and both MatPES models).
- What transfers: the specialised exporter already folds `products.0.linear` into interaction 1's `linear_up`, its skip and readout 0 (`W_up_0` / `W_up_1`, `w_ro0`; FastMACE's C3, the single-layer form of S57's skip-chain fold), composes interaction 0 per species (`C0`, `COMPOSE_SKIP`; the counterpart of S59's tables) and fuses product 1 with readout 1 (`sc1_fused`). S57's multi-layer fold and S61 / S62's product fusion need gated layers; OMAT-0 has density blocks and a layer-0 readout.
- Whole path: `bench_family` specialised SrTiO3 8.056 / NbCl5 1.838 ms/step, generic (`LOUP_GENERIC=1`) 8.649 / 1.892. By stage (`nsys`, us per step, specialised / generic): SrTiO3 interaction-1 conv backward 2,952 / 3,031, conv forward 1,785 / 2,215, GEMMs 2,417 / 2,593, products 590 / 569, interaction-0 backward 554 / 484, forward 259 / 259, lists and integrator 145 / 109; NbCl5 GEMMs 1,049 / 1,092, conv backward 442 / 462, forward 330 / 351, interaction-0 backward 113 / 76. The specialised conv forward (`spline_forward_inter1`) is 24% faster than the generic `gconv_fwd` on the same work (SrTiO3).
- Interaction-0 backward: `ncu` SrTiO3, `tabled_outer_sum0_backward_kernel` 540 us, 97 M instructions, issue 52.6%, achieved occupancy 37%, 27.9 active threads per instruction, L2 588 MB; `first_bwd_edge_kernel` 497 us, 102 M, 60.8%, 47%, 29.7, L2 490 MB (both 80 registers, 128 threads, same design: 32 edges per warp, dS0 cached per (receiver, sender species), 16-shuffle fold). They differ in the radial representation: a degree-5 power polynomial per piece (6 `float2` coefficient rows per lane and edge, lane 0 adding the density derivative with 6 more dependent loads) against one cubic `float4` per column. Falsifier (S63): each lane evaluates its own edge's density derivative in the metadata stage instead of lane 0 inside the edge loop (sm_120 only, same arithmetic): `cmp_libs` against S59 at the per-process plan level (`dF` 2.5e-6 / 1.1e-6 eV/A); fresh-plan ABBA S63 / S59 SrTiO3 `0.9997`, reversed `0.9998`; NbCl5 `1.0015`, reversed `1.010`: a tie. The remaining difference is the representation itself (an exporter and kernel change for all five specialised models, worth <= 70 / 36 us, 0.9% / 2.0%): not pursued.
- `scatter_active_edges` (the same kernel on both paths) ran 55 us in the specialised step and 25 us in the generic one (SrTiO3, no overlapping kernels in either), but 42 / 48 us under `ncu` (separate runs) with identical instruction counts; the in-step difference is unexplained and was not pursued (<= ~0.4% of the SrTiO3 step).
- Status: REJECTED (code reverted). The open lead goes the other way: the generic conv forward could take over the specialised spline forward's design.
- Sources: this file.

<a id="s33-mptrj-l1-after"></a>
#### s33-mptrj-l1-after: `MPtrj` L1 conv limiters after S29-S31 (no change)
- Stage: S33 (14 November 2026), 5060 Ti, `ncu`, `MPtrj` `SrTiO3`.
- `gconv_fwd_L1<1, false, 256, true, 256>`: 1.81 ms, 80 registers, 3 blocks of 256 (register-limited, 50%, achieved 49%); L2 throughput 89.3% (hit 92%), long scoreboard 6.48: L2-bound, so more warps would not help.
- `gconv_bwd_L1<true, 256, true>` (512 threads): 2.50 ms, achieved 58.7%; SM compute 71.9%, not selected 3.44, long scoreboard 1.72, L2 70%: issue-limited.
- Both kernels are at a hardware limit for the current algorithm; no launch or occupancy lever remains.
- S56 (14 November 2026), the `C = 128` lx 1 convs that dominate the OFF medium models (fresh `nsys`, water 5,184 atoms: `gconv_bwd_L1` 3.62 ms and `gconv_fwd_L1` 2.71 ms per step, 60% of the summed kernel time for `OFF24-M` and `OFF23b-M`; 59% for the generic `2023-12-03-mace-128-L1`). `ncu` (`OFF24-M` water): `gconv_fwd_L1<1, true, 256, true, 128>` 2.56 ms, 128 threads, 104 registers, 33% theoretical / 33% achieved occupancy, L2 throughput 82% (hit 96%), L1 hit 2.7%, no eligible warp in 50% of cycles, long scoreboard 3.91 per issue; `gconv_bwd_L1<true, 128, true>` 3.30 ms, 256 threads, 62 registers, 64% achieved, L2 82.5% (hit 95%), SM 74.8%, no eligible 25%, not selected 3.63, long scoreboard 2.09, dispatch 1.27. Both run near the L2 bandwidth limit (the backward also near the issue limit). The launch-shape levers for this kernel pair are already measured: more receivers per forward block (`gen-conv-fwd-r1`: R = 4 slower; `gen-conv-fwd-l1-r4`), the lx 1 forward split by x degree (`gen-conv-fwd-l1-split`), `PAIR` / `C_FIX` choices at C = 256 (`gen-conv-fwd-l1-c256`); fewer table bytes per entry was slower on the specialised path (T2, section 3.3 of the status file). Falsifier for the one untested launch choice, `PAIR = false` at `C = 128` (scratch dispatch; 84 instead of 104 registers, no spill; `cmp_libs` `OFF24-M` water `dF 2.9e-6`), `nsys` `gconv_fwd_L1` per step, two A/B pairs: `OFF24-M` water `2756 / 2767 -> 2753 / 2743 us` (`-0.1% / -0.9%`), MH-1 `SrTiO3` `2282 / 2278 -> 2262 / 2270` (`-0.9% / -0.3%`), `2023-12-03-mace-128-L1` `SrTiO3` `2440 / 2389 -> 2287 / 2365` (`-6.3% / -1.0%`): below the 10% stop rule, not adopted. The forward's long-scoreboard waits are not relieved by the extra warps, consistent with the L2 limit. No change.
- Sources: this file.

<a id="s32-specialised-occupancy"></a>
#### s32-specialised-occupancy: occupancy check of the specialised `w'` / spline kernels (no change)
- Stage: S32 (14 November 2026), 5060 Ti, `ncu`, `OMAT-0-M` `SrTiO3` (the path also serves `MPA-0`, `MP-0b3` and both `matpes` fine-tunes, where it is ~55% of kernel time).
- `wprime_backward_inter1_rcv` (256 threads, the tuned choice): 2.82 ms, 64 registers, 22.5 KB static shared memory, 4 blocks per SM (registers and shared memory both), theoretical 66.7%, achieved 64.0% (30.7 warps); SM compute 74.9%, stalls per issue not selected 4.12, long scoreboard 1.16, L2 52% (hit 93%): issue-limited, consistent with `meas-ncu` and the `w'` history (instruction-count tuning exhausted).
- `spline_forward_inter1`: the variant used in MD is `<5, false>` (R5 unpaired, 640 threads), picked at the first rebuild. Profiled after tuning (`ncu` launch 116): 1.79 ms, 96 registers, one 640-thread block per SM (41.7%), achieved 40.6%; SM compute 63.9%, L2 62% (hit 92%), L1 hit 47.5%, stalls per issue long scoreboard 2.17, not selected 1.28: mixed latency / issue, neither saturated. An earlier sample (`<1, true>`, 1.37 ms, L2 57%) was a pre-tuning launch on the start-of-run structure and is not comparable; the older `meas-ncu` figure (R1 L2-bound at 83%) predates `spl-v6-cubic-cg-fold`. Tuner and MD agree on the ranking: tuner R1 / R1p / R4 / R4p / R5 1922 / 1911 / 1664 / 1739 / 1622 us (three processes within 1.5%); MD `nsys` with the variant forced, R1 2100, R1p 2092, R4 1859, R4p 1898, R5 1780 us / step.
- Conclusion: `w'` is issue-limited. The selected spline variant is register-limited to one block per SM; fitting more warps needs fewer registers (the open `spl-r6-r8` idea), which was not tried here. No launch-shape change was made.
- Sources: this file.

<a id="rv8-fixes"></a>
#### rv8-fixes: eighth review pass (`loupmd-review-20261112.md`, U1-U9)
- Stage: S9.
- U1, packed tables: both loaders (generic conv layers, specialised interaction 1) now measure the CUBIC_PACKED8 error per column, exactly (maxima over each interval from the derivative's roots / the vertex), for the value and for d/dr (dv/dt times the band's inv_h), over the whole table and separately over r >= 1 A (an interval straddling 1 A contributes its part above, extrema on the clipped range) (the export certificate's second region), relative to the column's largest value / slope; load refuses above `kPackedTableMaxRelErr` = 5e-4. Measured on every current bundle (`LOUP_DEBUG_PACK=1`): 2.7e-5 (POLAR-1-L) to 1.7e-4 (OFF23 medium); OMAT-0 medium 8.0e-5, OMAT-0 small 1.0e-4. A guard against tables far outside what has been gated, not a certificate. Test: a bundle with one entry 2^40 larger is refused.
- U4, cuBLAS: the legacy handle's workspace is set with every `cublasSetStream` (`cublas_bind`: the lane's own workspace, as cuBLAS requires for reproducibility with concurrent streams). Whether it is behind POLAR-1-S NaNbO3_c0's per-process energies is not settled: five fresh processes each before and after gave two or three distinct values either way, but each process re-timed the near-tie GEMM plans, so plan choice was not held fixed (inconclusive; needs one complete fixed plan file).
- U2: the atom reorder also gathers `d_rnd_vel`, so the second Langevin half-kick after a rebuild uses the atom's own noise.
- U3: `loup_run_*` and `loup_profile_force` return -1 unless a neighbour list exists (`nl_valid`); `loup_set_system` zeroes velocities, so a run after only `evaluate` starts from rest instead of the previous system's velocities; non-finite `dt_fs` and `n_calls <= 0` are refused. Test: the call orders.
- U6: `ensure_edge_capacity` and `GenericModel::ensure_edges` drop the capacity to 0 and the graphs before reallocating, so a failed allocation leaves no stale capacity on freed arrays. U7: the specialised variant timing waits for a list with edges. U8: spline bands must be contiguous and end at r_max (both loaders); a plan file's `hyb_tile` must be < 3.
- U5: POLAR-1-S NaNbO3_c0 is left out of the gate unless `--include-unstable` (FastMACE excludes it too).
- Symmetrix-XL checks: a cell change followed by a pair crossing r_max on the reused list matches a fresh engine (test, OMAT-0 medium and small). MACE's e3nn -> cuEquivariance conversion, which the exporter probes, reproduces the original model in float64 (OMAT-0 small, OFF23 medium: 1e-14 eV / eV/A; POLAR-1-S: 1e-10 / 3e-9), and every family's gate compares LoupMD with the original model file, so a sign flip in the conversion (their PR 34) would show there. Not covered: a model that has not been gated; a synthetic sign-flipped U-column test is still open.
- Sources: this file; `tests/test_engine_guards.py`.

<a id="gen-conv-bwd-multi-rcv"></a>
#### gen-conv-bwd-multi-rcv: R receivers per conv-backward block (rejected)
- Stage: S68 (15 November 2026), 5060 Ti; motivated by the A100 profile (MP-0 medium SrTiO3: `gconv_bwd_L1` 1,985 us, 38.6% of kernel time; `gconv_fwd_L1` 20.8%).
- Diagnosis (5060 Ti `ncu`, `gconv_bwd_L1<true, 128, true>`, MP-0 medium SrTiO3, one launch): 62 registers, achieved occupancy 63.5%, issue 74%; L2 throughput 83.8% of peak, L1 58.7%, DRAM 28.6%; L2 sectors 166.0 M = 141.3 M reads (85%; the per-edge table slab, 10 paths x 128 channels x 8 B, and the sender rows) + 23.65 M `dx` reductions (14%) + 1.35 M writes; L2 hit 94.9%; stalls: not selected 33.1%, long scoreboard 23.8%, selected 9.8%, wait 9.5%, short scoreboard 6.2%, LG throttle 0.09%. L2-bandwidth bound on reads; the `dx` atomics are not the limiter (a sender-owned rewrite could save at most their 14% of sectors and would add a buffer pass).
- Tried: `emit_conv_bwd_lp` with template `R`, `TPR` (R groups of TPR threads, each with its own `s_q` slice and named barrier; R = 1 unchanged), forced through a test switch: R2 x 256, R4 x 128, R2 x 128 threads; 62 registers, no spills; exact against the default (`cmp_fold`, separate processes: `dF` 1.3e-6 / 4.8e-7 / 5.0e-7 eV/A on MP-0 medium NbCl5). `nsys` `gconv_bwd_L1` per step, MP-0 medium SrTiO3, two rounds: default 2,910 / 2,935 us, R2 x 256 3,497 / 3,509 (`+20%`), R4 x 128 3,384 / 3,374 (`+16%`), R2 x 128 4,923 / 4,941 (`+69%`).
- Status: REJECTED on the 5060 Ti (stop rule: no variant >= 10% faster; all slower). The larger shared-memory footprint per block lowers the resident warps, and receivers in one block do not walk their slabs in step, so L1 sharing does not appear. Not tried on the A100 (its `ncu` is pending); revisit only if the A100 backward shows a different limiter.
- Sources: this file; `.tmp_o/a100_notes.md`.

<a id="gen-conv-sliced"></a>
#### gen-conv-sliced: one warp per (receiver, channel slice) in the L1 convs (rejected)
- Stage: S72 (16 November 2026), 5060 Ti; `libloupmd_s72.so` / `_s72b.so` (scratch builds, code reverted).
- Motivation (CPU falsifier `.tmp_o/slab_reuse.py`, deleted): within one receiver, consecutive edges in the same table slab (pair, spline interval) are 8-25% of edges (loads / edges 0.75-0.92: OMAT-0 medium SrTiO3 0.755, NbCl5 0.922, OFF24-M water 0.794, MP-0 SrTiO3 0.919, MH-1 SrTiO3 0.773); across a window of R consecutive receivers the distinct slabs per edge fall to 0.38-0.55 (R8) and 0.16-0.40 (R16), lower with species-grouped Morton order. So L1 could serve most table reads if neighbouring receivers ran on one SM.
- Built: `gconv_bwd_L1_sl<WANT_DX, RS, MINB>` (grid `(N / RS, 4)`, warp = receiver, lane = channel of the slice; the receiver's 40 `dmid` values in registers; per-warp staged edge metadata; per-slice pull reduction and an atomic add of the slice's share of each edge force, the density term in slice 0) and `gconv_fwd_L1_sl<RS, PAIR>` (accumulators per lane, per-warp staged SH). Exact against the default (`dF` 7.6e-7 to 1.8e-6 eV/A in-process A/B).
- Measured (OMAT-0 medium generic SrTiO3, `ncu`, default / sliced RS 8): backward L1 hit 15.7% / 58.7%, L2 read sectors 122.2 M / 44.3 M, L2 throughput 75.0% / 41.3%, instructions 730 M / 754 M, issue 75.3% / 72.1%, warps active 63.7% / 32.8% (62 / 128 registers): the L2 limit is gone but the kernel is issue-bound at half the occupancy, 2.98 / 2.99 ms. `nsys` per step, default / RS8-MINB2 / RS4-MINB5 / RS16-MINB1 / RS8-MINB3: SrTiO3 2,941 / 3,064 / 4,550 / 2,990 / 5,032 us, OFF24-M water 3,507 / 3,768 / 5,468 / 3,686 / 6,069, NbCl5 454 / 470 / 672 / 465 / 769 (the capped builds spill 88-120 B). Two passes by x degree (`dmid` of one degree group live at a time; dx0 and dx1 disjoint): still 126 registers uncapped, 3,706-3,891 us. Forward RS 8 against R5: 1.83 / 1.60 ms, L1 hit 34% / 66% (R5's five receivers in one block share better than independent warps); full step `1.03` (SrTiO3), `1.02` (water).
- Status: REJECTED. The backward's instruction count (about 490 per channel-edge: 10 decodes of 8 integer + 7 FP operations, the path algebra, 11 `LDS.128` of `s_q`) is as binding as its L2 traffic; removing one limit exposes the other.
- Also measured (S72): GPU idle between kernels in the MD step is 1.9-5.3% of the span at 1,944-5,184 atoms (median gap 0.2-0.6 us), so programmatic dependent launch has little to gain at these sizes.
- Sources: this file.

<a id="gen-conv-fwd-variants"></a>
#### gen-conv-fwd-variants: per-system conv forward variant (receivers per block), the specialised spline forward's design
- Switch: `python/gen_generic.py` `launch_conv_fwd(..., var)` and `conv_fwd_variants(lx, C)` (generated); `src/generic.cu` `GenericLayer::fwd_var`, `GenericModel::tune_conv_variants`, called from `tune_rebuild_variants` (`src/engine.cu`) at the first MD rebuild. Compute capability 12.0 only; `LOUP_CONV_TUNE=0` keeps variant 0; `LOUP_CONV_FWD_VARIANT=0|1|2` forces one (tests; `test_gate.py` runs 1 and 2 for every generic bundle with an lx 1, `C = 128` layer); `LOUP_DEBUG_SPLINE=1` prints the timings.
- Stage: S64 (15 November 2026), 5060 Ti only.
- What: the generic `gconv_fwd_L1` template already had the specialised `spline_forward_inter1`'s receivers-per-block parameter (`R`, per-receiver named barriers) but always launched `R = 1` with the paired decode. Variants at `C = 128`: 0 = R1 paired (the old launch), 1 = R1 unpaired (84 registers), 2 = R5 unpaired (640 threads, 96 registers, 28.5 KB shared; the specialised R5's register count). As in the specialised path, each layer's variants are timed (best of 3 after a warm-up) on the last recorded pass's inputs at the first MD rebuild, and one replaces the current only if >= 2% faster; the timed launches' outputs (`mid`, `D`) are rewritten by every pass. `tune_conv_variants` returns -1 until a pass has been recorded for the system, so the engine retries at a later rebuild instead of marking the system tuned. R4 (paired 121 registers, unpaired 106) never won and is not instantiated.
- Falsifier (`nsys`, `gconv_fwd_L1` us per step, two passes, R1p / R1 / R4p / R4 / R5): OMAT-0 medium generic SrTiO3 2,200 / 2,176 / 2,014 / 2,172 / 1,742; OFF24-M water 2,723 / 2,686 / 2,803 / 2,895 / 2,437; OFF23-M water 1,722 / 1,666 / 1,816 / 1,852 / 1,569; MP-0 medium SrTiO3 2,385 / 2,273 / 2,520 / 2,528 / 2,136; NbCl5 (R1p / R1 / R5): OMAT-0 generic 346 / 327 / 321, MP-0 medium 354 / 348 / 357. R5 wins on water too, so its gain is not only the crystal slab sharing that motivated it in the specialised path; MP-0 NbCl5 prefers R1, hence a per-system choice. Tuner picks in MD: OFF24-M water R5 (2,504 / 2,436 / 2,205 us), MP-0 SrTiO3 R5, MP-0 NbCl5 R1.
- Exactness (forced variant vs 0, one build): OFF24-M water216 `dF` 1.6e-6 / 9.5e-7 eV/A (`|F|max` 9.4), MP-0 NbCl5 5.4e-7 / 7.4e-7, MH-1 NaCl216 3.3e-7 / 2.2e-7; `dE` <= 3.4e-4 meV/atom.
- Gates (both forced variants, 84 / 84 rows): OFF24-M, OFF23-M, OFF23b-M organic (worst force 0.99), MH-1, MP-0 medium, POLAR-1-M crystals (worst 1.69, NaNbO3), OMAT-0 medium generic oxide (worst 1.87). `generated_generic.cu`'s 99 existing kernels and `generic.cu`'s 25 SASS-identical to HEAD for sm_89 / sm_90 / sm_120 (the four new instantiations only added).
- Full step (`libloupmd_s64.so`, tuned vs `LOUP_CONV_TUNE=0`, fresh plans, ABBA in both orders; tuned / old): MP-0 medium SrTiO3 `0.968` / `0.967`, NbCl5 `0.987` / `0.996`; OFF24-M water `0.978` / `0.978`; OFF23-M water `0.975` / `0.980`, water216 `0.982` / `0.989`; MH-1 SrTiO3 `0.988` / `0.991`; ties: OFF23b-M water216 `0.994` / `1.011`, MH-1 NaCl216 `1.003` / `0.994`, POLAR-1-M NaCl216 `1.002` / `0.995`, NbCl5 `1.000` / `0.999`.
- Status: DEFAULT (5060 Ti only; other GPUs keep variant 0).
- S74 falsifier (scratch generator change, reverted): the same three-way choice for `lx` 1 at `C = 256` (R1 unpaired default, R1 paired, two receivers per 512-thread block) and `lx` 2 at `C = 128` / `224` (R1 paired default, R1 unpaired, four / two receivers per 512 / 448-thread block), the multi-receiver blocks generalised to `C` threads per receiver (no spills). Tuner timings (`LOUP_DEBUG_SPLINE=1`, us, variants 0 / 1 / 2): MPtrj SrTiO3 1,779 / 1,886 / 1,940, NbCl5 334 / 373 / 396; OFF23-L water 5,680 / 5,662 / 5,791, water216 744 / 743 / 768; OMOL-0 water216 layers 1 / 2 643 / 664 / 741 and 637 / 637 / 733; POLAR-1-L NaCl216 100 / 97 / 115 and 101 / 94 / 112. The default wins or ties everywhere but POLAR-1-L at 216 atoms (unpaired 3-7% faster on a 0.2 ms kernel): REJECTED (stop rule). Still open: the backward (`gconv_bwd_L1`, 3.6 ms on OFF24-M water), whose S68 / S72 multi-receiver and sliced forms already lost.
- S94 falsifier (16 November 2026, 5060 Ti, scratch generated-file change, reverted): one receiver per block at `C = 128` (128 threads) capped at 5 blocks per SM (`__launch_bounds__(128, 5)`; paired decode 104 -> 96 registers with 8 B stack, unpaired 84 -> 96, both 4 -> 5 blocks). `nsys` with variant 0 forced: OMAT-0 generic SrTiO3 `gconv_fwd_L1` 2,120 -> 2,025 us, OFF23-M water216 231 -> 204 us. Library ABBA on shared GEMM plans with the tuner on, 3 rounds: OFF23-M water216 `0.994` (`0.993` / `0.996`), OMAT-0 generic SrTiO3 `1.000`, MP-0 medium SrTiO3 `1.000`, OFF23-M water `1.000`, OFF24-M water216 `0.999` (`0.997` / `1.001`), MH-1 NaCl216 `1.005` (`1.008` / `1.002`): mixed, not kept. (The specialised `spline_forward_inter1<1, true>` already holds 96 registers.)
- S83t (17 November 2026, NHR Alex A100-SXM4-40GB node a0701, job 5012939 `loup-s83t`, library s81): the tuner on cc 8.0 (`LOUP_CONV_TUNE=1`) against the default, in-process A/B with 3 rounds, side 1 a second default engine (noise). Tuner timings, `gconv_fwd_L1` us for variants 0 / 1 / 2: OMAT-0 medium generic SrTiO3 1,026 / 1,019 / 1,074 (kept 0), MP-0 medium SrTiO3 1,044 / 1,017 / 1,080 (picked 1), OFF24-M water 1,201 / 1,190 / 1,241 (kept 0), OFF23-M water216 119 / 114 / 165 (picked 1); R5 is the slowest variant on the A100 on every system. Step, tuner / default with the noise side in brackets: OMAT-0 generic `1.003` (`1.002`), MP-0 medium `0.998` (`0.998`), OFF24-M water `0.996` (`0.997`), OFF23-M water216 `1.024` (`1.013`; tuner orders `1.024` / `1.027`). No gain: the tuner stays on `sm_120` only. The A100 counterpart of S94 is [s93-sm80-caps](#s93-sm80-caps).
- Sources: this file.

<a id="s72-omat0-limiters"></a>
#### s72-omat0-limiters: where OMAT-0 medium generic spends the 5060 Ti step (S72)
- Stage: S72 (16 November 2026), 5060 Ti, installed `libloupmd_s70.so`; `nsys` per MD step (8.17 ms, SrTiO3 5,000 atoms, `LOUP_GENERIC=1`) and `ncu` on one step's kernels.
- Conv backward `gconv_bwd_L1` 2.99 ms (37%): 62 registers, warps active 63.7%, issue 75.3%, L2 75%. SASS of its channel loop (one channel-edge per lane and iteration): 455 instructions, 233 `FFMA`, 76 `FMUL`, 20 `FADD`, 50 `LOP3` + 20 `SHF` + 12 `IADD` (the ten packed-cubic decodes), 10 `LDG.64` table + 4 `LDG` sender rows, 10 `LDS.128` of `s_q`, 4 `RED` (`dx`); about 25 of them recompute per-edge constants and row pointers in every iteration (ptxas rematerialises them; at 62 registers four 256-thread blocks fit per SM, above 64 only three).
- Conv forward (R5) 1.60-1.75 ms (21%): issue 71.8%, L1 hit 66%, L2 45%.
- Conv memory traffic (S74, `ncu`, `dram__bytes_op_read` / `lts__*`): both convs hit L2 for 95% of sectors (OMAT-0 medium generic SrTiO3, whose layer-1 table is 45 MB; MP-0 medium SrTiO3 too, 181 MB at 2,940 intervals; NbCl5 92%), DRAM at 18-21% of peak (backward 234 MB read per step, of which 102 MB `dmid`), but L2 throughput at 72-82% of peak: 107-137 M read sectors per conv pass, about the table's 8 bytes per path-channel-edge (370 k edges x 128 x 10 x 8 B = 3.8 GB). The table bytes per edge, not its size, bind the convs; a narrower entry would trade against the 3x margin (OMAT-0 generic oxide worst force 2.02).
- GEMMs 2.63 ms (32%, lanes overlap): own `sgemm128` on the lin1 shapes (M 25,000-35,000, N 128-384, K 128-384) runs the FMA pipe 65-70% of cycles at 70% issue, DRAM 32-52%; stalls are `not_selected` and `dispatch_stall` (the FFMA stream itself). M 15,000 shapes: DRAM 71%, FMA 54%.
- Products: `gprod_bwd` (layer 0) 0.21 ms at 86.8% of DRAM peak, `gprod_fwd` 0.12 ms at 92.1%, `gprod_ro1_fused` 0.20 ms at 78.1%.
- Layer 0: `first_bwd_edge` 0.48 ms, issue 62%, warps 47% (80-register cap), L2 39%, long-scoreboard stalls; `first_fwd` 0.24 ms, issue 65%, DRAM 58%.
- Layer-0 backward occupancy falsifier (S74, scratch builds): `first_bwd_edge_kernel<2>` at 7 blocks / SM (72 registers, 8 B stack) 471 / 461 us against 475 / 465 at 6 (OMAT-0 generic SrTiO3, two runs) and 505 / 499 against 515 / 517 (OFF24-M water); 8 blocks (64 registers, 40 B stack) 560-617 us. Under the stop rule.
- Falsifier (scratch build, code not kept): the decode's exponent bias as an OR instead of an add (one `LOP3` per path instead of `LOP3` + `IADD`, possible with a power-of-two rescale of the table and of `W_lin`; channel loop 455 -> 446 instructions, 64 registers). `nsys` per step: `gconv_bwd_L1` 2,932 -> 2,987 us, `wprime_backward_inter1_rcv` 2,902 -> 2,897 us: no gain, so the backward's issue rate is not what limits it at this margin.
- Consequence: each kernel sits at an issue, L2 or DRAM limit; what is left on this GPU is byte removal between kernels (the earlier attempts: lin1 fusion, the gate epilogue, the fused `W_2` product, all rejected) and host-side FLOP removal per family.
- S86 comparison of the two OMAT-0 medium paths (5060 Ti, `libloupmd_s86a.so`): in-process A/B, two engines, 4 rounds, generic / specialised `1.0015` on SrTiO3 (8.09 / 8.08 ms) and `1.0050` on NbCl5; in separate processes (`ab_libs.py` with one side `+generic`, 3 ABBA rounds) `1.0007` (`1.0007` / `1.0008`) and `0.9993` (`1.0005` / `0.9982`). A tie, so the specialised path stays the default (it also leads on the A100 by 2.4%). Per kernel (`nsys`, us per step, specialised / generic): conv backward 2,998 / 3,014, conv forward 1,815 / 1,761, layer 0 (tabled outer sum / `first_*`) 836 / 773, products 608 / 592, GEMMs 2,466 / 2,435, edge compaction 115 / 69 (the same compaction kernels; `scatter_active_edges` runs 26-67 us with its L2 hit rate, 22-52% under `ncu --cache-control none`, set by what the previous step left in L2); the specialised path is already folded (`sc0_forward` emits the product output before its linear, `W_up_0`, `W_skip1_16` and the readout weights are composed at export), so S73 has nothing to add there.
- After S96-S100 (5060 Ti, `libloupmd_s100a.so`, separate processes, 3 ABBA rounds, generic / specialised): SrTiO3 5,000 atoms `0.9889` (`0.9892` / `0.9885`), NbCl5 `0.9837` (`0.9803` / `0.9871`), SrTiO3 1,080 atoms `0.9933` (`0.9927` / `0.9939`), 320 atoms `0.9641` (`0.9598` / `0.9684`): the generic path now leads at every size on this GPU. `nsys` (generic SrTiO3, 7.85 ms): `gconv_bwd_L1` 2,873 us, GEMMs ~2,460, `gconv_fwd_L1` 1,667, layer 0 730, products 580, edge compaction 76, memsets 1.6, idle ~31 us outside the per-run boundaries. The default stays the specialised path for now (`ensure_loup_bundle` picks it by architecture on every GPU, and the A100, where it led by 2.4% before S97, is not re-measured yet; a per-GPU default would be the owner's call).
- Sources: this file.

<a id="gen-res0-table-read"></a>
#### gen-res0-table-read: layer 0's gated-block residual read from the species table
- Switch: `src/generic.cu` `gate_fwd_kernel` / `gate_bwd_kernel` (`res0_sp`: with it, `res0` is the S59 `[S, 4 C]` table and atom `a` reads row `res0_sp[a]`), `GenericModel::record` (both gate launches pass `res0_table` and the species; the residual's `gather_rows_kernel` is gone), `alloc_system` (no `res[0]` with the table). Applies wherever S59's tables apply (`sm_120` by default, `LOUP_SPECIES_TABLES=1` elsewhere).
- Stage: S72 (16 November 2026), 5060 Ti.
- What: S59 gathered the per-species residual into a per-atom `res[0]` (`N x 4 C` floats written) that `gate_fwd` and `gate_bwd` each read back; the table itself is `S x 4 C` and stays in L2. MH-1 SrTiO3 (`C = 512`, 5,000 atoms): 41 MB written and 82 MB read per step less. Same floats, same arithmetic: the results change only by per-process GEMM-plan picks.
- Exactness (separate processes, installed S70 vs candidate, rattled cells): MH-1 NaCl216 `dF` 2.8e-7 eV/A (`|F|max` 0.75), `dE` 2e-6 eV, `dS` 7.7e-10; OMOL-0 water216 `dF` 2.9e-6 (`|F|max` 16.3), `dE` 1.7e-5 eV, `dS` 5.8e-10.
- Speed (`ab_fam.py` ABBA, installed `libloupmd_s70.so` against `libloupmd_s72r.so`, both orders, candidate / S70): MH-1 SrTiO3 34.88 / 35.13 ms (`0.993`), reversed `0.991`; NaCl216 `0.987` / `0.983`; OMOL-0 water216 `0.998` / `0.997`.
- Gates (`libloupmd_s72m.so`, same kernels): default path 7 / 7 runs pass (OMOL-0 organic neutral, +1 doublet, -1 doublet, triplet; MH-1 `omat_pbe` and `matpes_r2scan` crystals, `omol` organic); `LOUP_SPECIES_TABLES=0` (`libloupmd_s72n.so`) 4 / 4: OMOL-0 neutral worst force / stress 0.82 / 0.79, +1 doublet 0.31 / 0.15, MH-1 crystals 0.90 / 0.32, `omol` organic 0.36 / 0.45. SASS (with S73): `generic.cu`'s other 22 kernels identical to HEAD for `sm_89` / `sm_90` / `sm_120`; the two gate kernels gained `res0_sp`.
- Status: DEFAULT.
- Sources: this file.

<a id="gen-chain-fold-ext"></a>
#### gen-chain-fold-ext: the skip-chain fold beyond the all-gated models
- Switch: `src/generic.cu` `GenericModel::setup_chain_fold` (new eligibility; `Target` / `FoldTarget` carry `ns`, 1 or S, and `ns_h` for the layer-0 skip weights; `dest_layer = -2` is the energy), `record` (forward: energy targets on the main stream before the lanes fork, `ro_linear_kernel` on `y_t[0]` with the composed vector and `species_energy_kernel` for the layer-0 skip's per-species constant, per-species targets through `species_gemm`; backward: `dy_t[0]` accumulates onto the forward's seed), `alloc_system` (a seeded `dy_t[0]` sat in the zero slab until S97, which assigns the seed instead: [gen-pass-glue](#gen-pass-glue)). Same switches as S57: `sm_120` by default, `LOUP_CHAIN_FOLD=0` disables, `=1` forces on other GPUs.
- Stage: S73 (16 November 2026), 5060 Ti.
- What: S57 needed every layer gated, no readout before the last and no per-species skip, so only OMOL-0 folded. The other multi-layer generic families differ in exactly those points: a linear readout on layer 0 (`E += hout_0[0] . ro_w`, linear, so a consumer like any other: the composed vector `W_p_0[0] ro_w` on `y_0[0]`, whose gradient is that vector, seeded into `dy_0[0]` by the forward's `ro_linear_kernel`), the last layer's per-species skip into its readout hidden (`W_p_0[0] W_sc_1[s] ro_W1`, one `[C_out, H]` block per species, species-grouped GEMMs in both directions), and for MP-0 medium / MPtrj a per-species skip on layer 0 itself (its input is the species embedding, so its share of each consumer is an `[S, cols]` table and its share of the energy a per-species constant). The specialised OMAT-0 path's exporter already composes `W_p_0` into its consumers (`W_up_*`, `w_ro0`, `W_skip1_16`); the generic path now does the same at load for any eligible model. OMOL-0's fold is unchanged (same targets, same order).
- Removed per step (5,000 atoms): OMAT-0-type models the layer-0 `W_p` products (`l` 0 and 1, `C = 128`) in both directions and the `dh_in += dx W_up^T` products; MPtrj the same at `C = 256`; MH-1 the `C = 512` `W_p_0` products (`l` 0, 1) both ways, its `W_sc_0` skip and `dh_in` products.
- Exactness (in-process, fold vs `LOUP_CHAIN_FOLD=0`, beside the noise side fold vs fold): OMAT-0 generic SrTiO3 `dF` 1.32e-6 eV/A (noise 1.38e-6), `dE` 5.9e-4 meV/atom (1.0e-3); MP-0 SrTiO3 1.0e-6 (1.1e-6), 1.4e-4 (1.1e-4); MPtrj SrTiO3 9.0e-7 (9.3e-7); OFF24-M water 8.3e-7 (6.8e-7); MH-1 NaCl216 7.0e-8 (7.4e-8); MH-1 SrTiO3 1.09e-6 (1.11e-6); OMOL-0 water216 3.7e-7 (2.4e-7).
- Speed (`ab_sides.py`, `libloupmd_s73.so`, 4 rounds in both orders; plain / fold; forward / reverse order): MH-1 NaCl216 1.507 / 1.403 ms `1.075` (`1.082` / `1.070`), SrTiO3 34.86 / 33.11 `1.053` (`1.053` / `1.053`); MPtrj SrTiO3 11.48 / 11.04 `1.040` (`1.041` / `1.038`); OMAT-0 medium generic SrTiO3 8.17 / 8.03 `1.017` (`1.018` / `1.021`); MP-0 medium SrTiO3 8.41 / 8.27 `1.017` (`1.018` / `1.017`); OFF24-M water 10.10 / 9.95 `1.015` (`1.013` / `1.015`); OMOL-0 water216 28.17 / 22.93 (S57, unchanged). Noise sides 0.9997-1.0022. OMAT-0 medium generic SrTiO3 now runs at the specialised path's 8.03 ms (`ab_mode.py`, S70 library: specialised 8.03, generic 8.19).
- Gates (`libloupmd_s73.so`, fold on; worst force / stress ratio): OMAT-0 medium generic oxide 2.02 / 1.81 (plain 2.01 / 1.74), MPA-0 medium generic oxide 2.02 / 1.83, OMAT-0 small generic oxide 1.19 / 1.26, MP-0 medium oxide 0.78 / 0.52, MPtrj oxide 1.42 / 0.72, MH-1 `omat_pbe` crystals 0.85 / 0.29 (plain 0.88 / 0.29), `matpes_r2scan` crystals 0.86 / 0.30, `omol` organic 0.33 / 0.45, OFF24-M organic 0.71 / 0.59, OFF23-M 0.35 / 0.61, OFF23b-M 1.03 / 1.16, OFF23-S 0.66 / 1.66, OFF23-L 0.41 / 1.20, OMOL-0 organic 0.81 / 0.91: 16 runs, none failing (the OFF24-M, OFF23b-M and OFF23-L references on the CPU).
- SASS: `generic.cu`'s other 22 kernels identical to HEAD for `sm_89` / `sm_90` / `sm_120`; `species_energy_kernel` is new (the gate kernels changed with S72).
- Status: DEFAULT (5060 Ti only; other GPUs keep the plain path until measured).
- Sources: this file.

<a id="gen-pass-glue"></a>
#### gen-pass-glue: per-pass glue on the generic path
- Switch: `src/generic.cu` `GenericModel::h0_read_` (set at load; `record` gathers layer 0's embedding rows `d_h0_` only when it is true), `ro_linear_kernel(..., assign)`; `alloc_system` (the folded readout's `dy[0]` left the zero slab).
- Stage: S97 (16 November 2026), 5060 Ti.
- What: at the start of every pass `gather_rows_kernel` copied each atom's species embedding into `d_h0_` (OMAT-0 generic SrTiO3: 11 us per step). Its readers are layer 0's `x` products without the S59 residual table, the skip / readout terms of an unfolded layer 0 and the fold's skip terms without the S59 tables (`Wh`); with the S57 / S73 fold and the S59 tables every one of them reads a species table, so the gather is dead work there (`h0_read_` mirrors those conditions; one-layer models always gather). And the S73 energy target's `ro_linear_kernel` added its gradient seed onto `dy[0]`, which therefore sat in the per-step zero slab (2.56 MB of the 12.8 MB memset); it is the pass's first write of `dy[0]` (the backward's fold GEMMs accumulate after it), so it now assigns. The plain readout (`dhout[0]`, other contributions in the zero slab too) keeps adding.
- Measured: library ABBA on shared GEMM plans, S96 -> S97, 3 rounds: OMAT-0 medium generic SrTiO3 `0.9982` (`0.9982` / `0.9982`), MP-0 medium SrTiO3 `0.9990` (`0.9996` / `0.9984`), OFF23-M water216 `0.9913` (`0.9941` / `0.9884`).
- Gates (worst force / stress ratio): OMAT-0 medium generic oxide 2.06 / 1.80, MP-0 medium oxide 0.80 / 0.49, OFF23-M organic 0.35 / 0.62, MH-1 crystals 0.85 / 0.29, POLAR-1-S crystals 0.63 / 0.64: all pass; 77 tests pass.
- S98 (16 November 2026): every conv backward ended each edge with a read-add-store of its force vector into `edge_dvec` (lx 0: an atomic add on sm_120), so the buffer was zeroed at the start of the pass (`zero_edge_kernel`, 9 us on OMAT-0 generic SrTiO3) and the per-edge tail waited on a load. The top layer's conv backward runs first in the backward pass and touches every active edge once, so it now assigns (`dvec_assign`, uniform per launch; for lx 2 the late pull-back kernel assigns and `gconv_bwd_L2` adds after it); lower conv layers and the layer-0 backward accumulate as before, and only a model without conv layers keeps the zero fill. Generator: `python/gen_generic.py` (`EDGE_DVEC_SET`, the `dvec_assign` kernel argument, `launch_conv_bwd`), regenerated `src/generated_generic.cu` (no other change). Library ABBA on shared plans, S97 -> S98, 3 rounds, both orders: OMAT-0 medium generic SrTiO3 `0.9945` (`0.9941` / `0.9950`), MP-0 medium SrTiO3 `0.9917` (`0.9912` / `0.9921`), OFF23-M water216 `0.9930` (`0.9943` / `0.9917`), OFF23-S water216 `0.9887` (`0.9856` / `0.9919`), MH-1 NaCl216 `0.9991` (`0.9991` / `0.9991`), OMOL-0 water216 `0.9997` (`0.9995` / `0.9999`). Gates: OMAT-0 medium generic oxide 2.02 / 1.82, OFF23-S organic 0.64 / 1.51, OFF23-L organic 0.45 / 1.18 (lx 2; CPU references), MH-1 crystals 0.85 / 0.29, POLAR-1-L crystals 1.33 / 0.89, OMOL-0 organic 0.86 / 0.53; 77 tests pass.
- S99 (16 November 2026): with S97 / S98 the pass's memset was left with the conv layers' `dx` (the sender gradients the conv backward accumulates with atomics: 10.24 MB of the 10.28 MB on OMAT-0 generic SrTiO3, ~28 us). Each forward conv kernel now zeroes its receiver's `dx` rows (`zx` arguments, nullable; for lx 2 the first of the two kernels), and `dx` left the zero slab: the forward conv is L2-bound with DRAM to spare (A100 `ncu`: DRAM 7.75%), and every reader of `dx` (gate GEMMs, conv backward, fold GEMMs) runs after it. Generator: `emit_conv_fwd` (`zero_rows`), `launch_conv_fwd(..., zx)`; `src/generated_generic.cu` regenerated. Placement matters: zeroing after the edge loop (S99a) kept the targets live across it (paired decode 104 -> 122 registers), which cost the small cells (library ABBA S98 -> S99a: OFF23-S water216 `1.018`, OFF23-M water216 `1.003`, MH-1 NaCl216 `1.002`; OMAT-0 generic `0.996`, MP-0 `0.995`); zeroing before it (S99) leaves every forward kernel's register count as before (one runtime-`C` lx 2 variant 124 -> 125). Library ABBA on shared plans, S98 -> S99, 3 rounds: OMAT-0 medium generic SrTiO3 `0.9965` (`0.9972` / `0.9959`), MP-0 medium SrTiO3 `0.9960` (`0.9961` / `0.9958`), OFF23-M water216 `0.9964` (`0.9981` / `0.9948`), MH-1 NaCl216 `0.9932` (`0.9937` / `0.9927`), OFF23-S water216 `0.9999` (`1.0044` / `0.9954`, a tie). Gates (worst force / stress ratio): OMAT-0 medium generic oxide 2.02 / 1.81, MP-0 medium oxide 0.80 / 0.50, OFF23-S organic 0.65 / 1.83, OFF23-L organic 0.42 / 1.16 (CPU references), MH-1 crystals 0.85 / 0.31, OMOL-0 organic 0.85 / 0.54, POLAR-1-M crystals 2.36 / 1.18; 77 tests pass.
- S100 (16 November 2026): the S73 energy target (a folded linear readout of `y_t[0]`) ran `ro_linear_kernel` after the layer's product (21 us on OMAT-0 generic SrTiO3, one more serial node), assigning the gradient seed `dy_t[0] = Wy` for the backward's fold GEMMs to add onto. When some other fold target writes `dy_t[0]` (always, for the cached models), the product forward now adds `E += y_t[0] . Wy` itself (double products, warp and block sums, one atomic per block) and the product backward adds the seed `Wy` to its upstream gradient `g0` at load, so the first fold GEMM assigns `dy_t[0]` and no kernel writes the seed (`fused_readout` in `record`; generator: `gprod_fwd_*` / `gprod_bwd_*` arguments `ro_w`, `energy`, `gseed`, `launch_prod(..., ro_w, energy)`). Library ABBA on shared plans, S99 -> S100, 3 rounds: OFF23-M water216 `0.9869` (`0.9834` / `0.9904`), MP-0 medium SrTiO3 `0.9987` (`0.9982` / `0.9993`), OMAT-0 medium generic SrTiO3 `1.0000` (`0.9997` / `1.0004`), OFF23-S water216 `0.9986` (`0.9932` / `1.0040`). Gates: OMAT-0 medium generic oxide 2.02 / 1.80, MP-0 medium oxide 0.76 / 0.37, OFF23-M organic 0.33 / 0.57, OFF23-S organic 0.64 / 1.77, MPtrj oxide 1.40 / 0.72, OMAT-0 small generic oxide 1.20 / 1.25, MH-1 crystals 0.86 / 0.28; 77 tests pass.
- Full gate sweep on the installed S100 library (`libloupmd.so` = `libloupmd_s100a.so`, 5060 Ti; worst force / stress ratio): OMAT-0 medium specialised oxide 1.67 / 2.50 (34 rows with the forced variants) and generic 2.02 / 1.80, MP-0 medium 0.83 / 0.48, MPtrj 1.37 / 0.74, MH-1 `omat_pbe` / `matpes_r2scan` crystals 0.85 / 0.31 and 0.86 / 0.35, `omol` organic 0.33 / 0.42, OFF24-M 0.70 / 0.55, OFF23-M 0.34 / 0.58, OFF23b-M 0.98 / 1.21, OFF23-S 0.64 / 1.74, OFF23-L 0.42 / 1.19, OMAT-0 small generic 1.21 / 1.25, MPA-0 medium generic 2.02 / 1.84, OMOL-0 organic 0.79 / 0.87, POLAR-1-S / -M / -L crystals 0.69 / 0.64, 2.17 / 1.20, 1.85 / 0.71, and with `LOUP_CHAIN_FOLD=0` OMAT-0 generic 2.01 / 1.74, MH-1 0.87 / 0.29: 20 runs, none failing.
- Status: DEFAULT.
- Sources: this file.

<a id="gen-first-fwd-cols"></a>
#### gen-first-fwd-cols: one thread per radial column in `first_fwd_kernel`
- Switch: `src/generic.cu` `first_fwd_kernel` and its launch in `GenericModel::record` (`max(J - 1, 64)` threads rounded up to whole warps; before, `max(J, 64)`).
- Stage: S105 (16 November 2026), 5060 Ti.
- What: one thread per column of layer 0's radial chain, and column `J - 1` (the edge density, summed into `D`) had a thread of its own: for `J - 1 = 64` (every ScaleShift model: OMAT-0, MP-0, OFF) each block ran a third warp with one active lane through every edge's loop. Lane k of warp 0 now evaluates the density of each staged tile's edge k beside its own column, and warp 0 adds the tile's values in edge order with shuffles after its column loop: the same sums in the same order as the former density thread, so `D` and `S0` are bitwise unchanged by construction. `ncu` before (OMAT-0 generic SrTiO3): 248 us, DRAM 64.5%, issue 63%, stalls long scoreboard 34% and barrier 26%.
- Measured (5060 Ti): `nsys` kernel time per step 255-260 -> 240-245 us (two runs each). Library ABBA on shared plans, 3 rounds, S101 -> S105 alone (scratch build): OMAT-0 generic SrTiO3 `0.9991` (`0.9992` / `0.9990`), MH-1 NaCl216 `0.9973` (`0.9973` / `0.9974`), OFF23-M water216 `0.9991` (`0.9953` / `1.0030`, a tie). Rejected on the way: `#pragma unroll 4` on the column loop (more table loads in flight), slower (241 / 235 -> 248 / 246 us); a first version that reduced per-lane density sums with a butterfly ran at the same speed, but its rounding differs, so the in-order sum was kept (its POLAR-1-M crystal gate read 2.71 / 1.26 against 2.50 / 1.13 for S101, inside that gate's run-to-run spread of 2.17-2.71 from atomic accumulation order).
- Gates (final S105 + S106 library): OMAT-0 medium generic oxide 2.00 / 1.80, POLAR-1-M crystals 2.43 / 0.98; the first version also passed OFF23-M organic 0.35 / 0.56 and MH-1 crystals 0.86 / 0.31. `pytest`: 77 passed.
- A100: queued (job `s106c` and the `s106g*` gate sweep, [results/alex-a100-queue-20261116](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/alex-a100-queue-20261116/README.md)).
- Status: DEFAULT.
- Sources: this file.

<a id="gen-single-table"></a>
#### gen-single-table: one radial table when every pair's table is the same
- Switch: `src/generic.cu` loader (each conv layer's packed pair slabs compared with pair 0 by `memcmp`; all equal: `pair_sym = 2` and one slab uploaded); `loup::table_pair(pair_sym, s, t, S)` (`src/kernels_common.cuh`; 2: slab 0 for every pair), used by the generated conv kernels (`python/gen_generic.py`, three template sites; regenerated `src/generated_generic.cu`), `src/generic.cu`'s pre-location kernels and the `src/neighbors.cu` slab scatter.
- Stage: S116 (18 November 2026), 5060 Ti. From the owner's review list of 17 November.
- What: the exporter writes one radial table per species pair. Where the radial MLP does not take the species, every pair slab is byte-identical, so the device held S(S+1)/2 copies of one table. A survey of the cached bundles found identical slabs in every conv layer of OFF23 / OFF23b / OFF24, MACE-MP-0 medium and MACE_MPtrj_2022.9, and distinct slabs in POLAR-1, MH-1, OMAT-0, MPA-0, MP-0b3, MatPES and OMOL-0.
- Measured (5060 Ti, HEAD `13d6337` -> S116; the build also had S115, which these models do not run): VRAM (bundle + system + first evaluate) OFF23-M water216 206 -> 192 MiB, OFF23-L water216 306 -> 274, OFF23-M water 624 -> 608, MP-0 medium SrTiO3 876 -> 718, MPtrj SrTiO3 1,148 -> 1,056. Library ABBA on shared plans (first / second order): OFF23-S water216 `0.9956` (`0.9975` / `0.9936`), OFF23-M `0.9908` (`0.9912` / `0.9903`), OFF23-L `0.9961` (`0.9966` / `0.9955`), MPtrj SrTiO3 `0.9979` (`0.9990` / `0.9968`), MP-0 medium SrTiO3 `0.9996` (`1.0011` / `0.9981`, a tie).
- Results against HEAD (rattled cell, one evaluate; HEAD against itself in brackets): max dF OFF23-S 2.2e-6 (1.1e-6), OFF23-M 1.8e-6 (1.6e-6), OFF23-L 2.0e-6 (6.1e-7), MP-0 medium 1.1e-6 (1.2e-6), MPtrj 8.6e-7 (6.2e-7) eV/A; MH-1 (distinct slabs, unchanged path) 1.7e-7 (8.6e-8). The table bytes are the same, so only GEMM plans and atomic order differ.
- Gates: OFF23-S organic 8 / 8, OFF23-M organic 24 / 24, MH-1 crystals 18 / 18, MP-0 medium crystals 18 / 18, MPtrj crystals 6 / 6.
- Status: DEFAULT (5060 Ti only; cc 8.0 runs the same code, not measured).
- Sources: this file.

<a id="gen-conv-l2-cartesian"></a>
#### gen-conv-l2-cartesian: five x-degree-2 conv paths as Cartesian forms of one Q
- Switch: `python/gen_generic.py` `DEG2_CART`, `deg2_cart` (the constants), `_cart_bwd` (in `emit_conv_bwd_L2`) and `_cart_fwd` (in `emit_conv_fwd`) in the regenerated `src/generated_generic.cu`, used when a kernel holds all five paths (every lx 2 layout). Until S129 they were emitted under `#if __CUDA_ARCH__ == 1200` with the per-path forms for other GPUs; since S129 they are the only form ([gen-arch-neutral](#gen-arch-neutral)).
- Stage: S119 (three paths) and S121 (five), 18 November 2026, 5060 Ti. From the owner's second review list of 18 November, whose CPU check covered all seven degree-two paths.
- What: with the scaled l = 2 basis B'_m (`n B'_m n = 2 Y2_m(n) / sqrt 15`, `tr(B'_m B'_k) = 2 delta_mk`) the sender's x2 is a symmetric traceless `Q = sum_m x2_m B'_m` (one multiply, three adds). For the unit edge direction n, with `v = Q n` and `h = n . v`, the outputs are `C h` (2,2,0), `C v` (2,1,1), `C (n h - 2/5 v)` (2,3,1), `C (v . B'_m n - 2/3 x_m)` (2,2,2) and `C x` (2,0,2), each with its own radial weight; the constants sqrt(3)/2, sqrt(0.3), sqrt(5)/2, sqrt(9/14) and 1/sqrt(5) are fitted at generation time against the Wigner-3j contractions (exact to 1e-12; identity component order in the harmonics' frame). The forward takes `Y1 = sqrt 3 n` from the staged harmonics and puts the factors into the stores. The backward writes `F = al h + b . v + C22 R22 (v . G n - 2/3 gd . x) + C02 R02 ge . x` (`al = C0 R0 g0 + C3 R3 g3 . n`, `b = C1 R1 g1 - 2/5 C3 R3 g3`, `G = sum_m gd_m B'_m`): the x gradient is `c . B'_m n - 2/3 C22 R22 gd_m + C02 R02 ge_m` with one `c = al n + b + C22 R22 G n`; the radial pull is F with the radial derivatives; the direction gradient `Q c + al v + C3 R3 h g3 + C22 R22 G v` (radial parts dropped: the edge end projects them out) goes into `dY[1..3] / sqrt 3`, which `sh16_grad` maps back exactly (`Y1 = sqrt 3 n`), so the per-edge reduction is unchanged. In the source the five paths' backward drops from about 213 to 132 operations per edge and channel (S119's three from about 145 to 80). Float64 certificate (`deg2_cert.py`, scratch; 1,560 random inputs, the emitted expressions mirrored): forward outputs, x gradient, radial pull and tangential direction gradient agree with the contractions and their autograd derivatives to 5-8e-16 relative L2.
- Measured (5060 Ti): registers (`cuobjdump`) `gconv_bwd_L2<true, 224, *>` 128 (S118, S119) -> 126-127 (S121), no spill; `gconv_fwd_L2b<1, true, 256, *, 224>` 125 -> 102 / 92 -> 88 / 97; S119 had 8-16 B stacks in two other `gconv_fwd_L2b` instantiations (`<1, false, 512, true, 0>`, `<1, true, 128, true, 128>`), S121 none. `nsys` per MD step (OFF23-L water216, 128 steps, two runs each): `gconv_bwd_L2` 651 / 654 (S118) -> 600 / 595 (S119) -> 581 / 573 us (S121); `gconv_fwd_L2b` 369 / 362 -> 346 / 357 -> 346 / 342. Library ABBA on shared plans (first / second order): S118 -> S119: OFF23-L water216 `0.9753` (`0.9758` / `0.9749`, 3 rounds), OFF23-L water (5,184 atoms) `0.9739` (`0.9755` / `0.9723`, 1 round), POLAR-1-L NaCl216 `0.9953` (`0.9926` / `0.9980`), OMOL-0 XL water216 `0.9934` (`0.9934` / `0.9933`); S119 -> S121: OFF23-L water216 `0.9857` (`0.9858` / `0.9857`), POLAR-1-L `0.9952` (`0.9924` / `0.9981`), OMOL-0 XL `0.9967` (`0.9965` / `0.9969`).
- Results (rattled cell, one evaluate, against the previous stage; that stage against itself in brackets): S121 OFF23-L water216 max dF 1.5e-6 (1.5e-6) eV/A, POLAR-1-L NaCl216 5.6e-7 (1.7e-7), OMOL-0 XL water216 2.2e-6 (2.5e-6); S119 alike (1.3e-6, 4.5e-7, 2.4e-6).
- Gates (CPU references), S119 and S121 each: OFF23-L organic 8 / 8, POLAR-1-L crystals 6 / 6, OMOL-0 XL organic 8 / 8.
- Not converted: (2,1,3) and (2,3,3), whose l = 3 outputs need a rank-three basis and share little with `Q n`.
- Status: DEFAULT (5060 Ti since S119 / S121; every GPU since S129, [gen-arch-neutral](#gen-arch-neutral)).
- Sources: this file.

<a id="gen-conv-l1-cartesian"></a>
#### gen-conv-l1-cartesian: four x-degree-1 conv paths as Cartesian forms
- Switch: `python/gen_generic.py` `CART1`, `cart1_consts` (the constants) and `_cart1_fwd` (in `emit_conv_fwd`) in `src/generated_generic.cu`, used when a forward kernel holds all four paths (`gconv_fwd_L1`, `gconv_fwd_L2a`); the staged linear forms only the per-path versions read are not staged. Until S129 the forms were emitted under `#if __CUDA_ARCH__ == 1200` (an arch-dependent `ED`, the per-path forms on other GPUs); since S129 they are the only form ([gen-arch-neutral](#gen-arch-neutral)).
- Stage: S122 (18 November 2026), 5060 Ti; RTX A4000 as a compiled-in test build. From the owner's review list of 18 November (idea 1: share angular work across four interaction-1 paths, 13 fewer staged values, 144 -> 96 B per edge).
- What: for the sender vector p and unit direction n, with `d = p . n`, `q_m = p . B'_m n` and `u_m = n . B'_m n` (= 2 Y2_m(n) / sqrt 15), the outputs are `C d` (1,1,0), `C (n d - p / 3)` (1,2,1), `C q` (1,1,2) and `C (d u - 2/5 q)` (1,3,2), constants fitted at generation time (1/sqrt 3, ... ; exact to 1e-12). The kernel uses `d' = p . Y1` and `q'_m = p . B'_m Y1` (Y1 = sqrt 3 n, the staged harmonics) and puts the factors into the stores (`(1,2,1)`: `(Y1 d' - p) / 3`; `(1,3,2)`: `(d' Y2 - sqrt 15 / 5 q') 2 / (3 sqrt 5)`). Certificate (CPU, float64, the emitted expressions against the Wigner-3j contractions on 7,168 random edges): at most 1.2e-15 of the peak per path.
- Measured (5060 Ti): static shared memory `gconv_fwd_L1` 6.5 -> 5.0 KB per block (R = 5: 28.5 -> 20.9 KB), `gconv_fwd_L2b` 10.1 -> 7.0 KB; registers equal or lower (`<1, false, 512, *, 0>` 100 -> 96), one 8-16 B stack in two `L2b` instantiations no benchmark launches. `nsys` per MD step (two runs each): `gconv_fwd_L1` 1,766 / 1,786 -> 1,712 / 1,725 us (OMAT-0 generic SrTiO3), 211 / 213 -> 212 / 213 (OFF23-M water216, unchanged), `gconv_fwd_L2a` 409 / 417 -> 399 / 400 (OFF23-L water216). Library ABBA on shared plans, HEAD -> S122 (first / second order): OMAT-0 generic SrTiO3 `0.9943` (`0.9935` / `0.9951`, 3 rounds), OFF23-M water216 `0.9923` (`0.9946` / `0.9901`), OFF24-M water `0.9952` (`0.9938` / `0.9966`, 2 rounds), OFF23-L water216 `0.9944` (`0.9948` / `0.9940`), MH-1 NaCl216 `1.0018` (`1.0017` / `1.0018`; rounds 0.987-1.015, a tie). A first round of measurements on a contended GPU (other jobs outside the reservation) was discarded. RTX A4000 with the forms compiled for sm_86 (test build): MP-0 SrTiO3 `0.9935` (`0.9956` / `0.9913`).
- Results (rattled cell, one evaluate, against HEAD; HEAD against itself in brackets): MP-0 SrTiO3 max dF 2.7e-6 (1.1e-6) eV/A of 5.0, OFF23-M water216 3.3e-6 (1.1e-6) of 15.1, OFF23-L water216 1.0e-6 (9.7e-7), MH-1 NaCl216 1.8e-7 (1.0e-7), POLAR-1-M NaCl216 6.1e-7 (1.4e-7); A4000 test build MP-0 SrTiO3 1.6e-6 (7.3e-7), OFF23-M 2.9e-6 (7.9e-7).
- Gates (S126 library, which includes S122): MP-0 oxide 18 / 18, OMAT-0 generic oxide 18 / 18, OFF23-M organic 24 / 24, MH-1 crystals 18 / 18 (each with the forced conv variants).
- Other GPUs (test builds with every `sm_120`-only block of `src/generated_generic.cu` compiled for sm_86 / sm_89 against the default build: all 72 conditions, i.e. the Cartesian forms of S119 / S121 / S122 together with S48's x-gradient rewrite and the S40 / S101 RED edge-vector updates; the SASS of the sm_89 test library has 156 more `RED` and 156 fewer `STG` in its 52 conv backward kernels. Recorded at first as the Cartesian forms alone, corrected in S129. Library ABBA on shared plans, 2 rounds, first / second order): RTX A4000 (sm_86, `coraline`): OFF23-L water216 `0.9375` (`0.9391` / `0.9359`; lx 2, all three stages), POLAR-1-L NaCl216 `0.9853` (`0.9852` / `0.9853`), OMAT-0 generic SrTiO3 `0.9908` (`0.9914` / `0.9902`), OFF24-M water `0.9916` (`0.9925` / `0.9907`), MP-0 SrTiO3 `0.9935` (`0.9956` / `0.9913`), OFF23-M water216 `1.0050` (`0.9996` / `1.0104`, mixed). RTX 4000 Ada (sm_89, `murphy`): OFF23-L water216 `0.9411` (`0.9419` / `0.9403`), POLAR-1-L NaCl216 `0.9878` (`0.9927` / `0.9828`), OFF23-M water216 `0.9939` (`0.9934` / `0.9943`), MP-0 SrTiO3 `0.9976` (`0.9978` / `0.9974`), OMAT-0 generic SrTiO3 `0.9979` (`0.9987` / `0.9971`), OFF24-M water `0.9985` (`0.9986` / `0.9985`). Results at the default build's spread on both (sm_89: OFF23-L water216 max dF 2.7e-6, its own spread 1.0e-6). Enabled on every GPU in S129 ([gen-arch-neutral](#gen-arch-neutral)).
- Final library (S122-S125, S127, S128; 5060 Ti): OFF23-M organic 24 / 24 (worst force / stress ratios 0.35 / 0.57), OFF23-L organic 8 / 8 (CPU references; 0.42 / 1.21), MP-0 oxide 18 / 18; `pytest` 77 passed.
- Status: DEFAULT (5060 Ti since S122; every GPU since S129, [gen-arch-neutral](#gen-arch-neutral)).
- Sources: this file.

<a id="gen-conv-prune"></a>
#### gen-conv-prune: conv paths pruned from exactly-zero projections (MP-0 medium)
- Switch: `src/generic.cu` `GenericLayer::conv_prune`, certified in `GenericModel::load` for a conv layer with lx 1 when every entry of W_lin_1..3 is exactly zero (`LOUP_CONV_PRUNE=0` disables it); `launch_conv_fwd / launch_conv_bwd (..., prune)` (the lx 1 branches as macros over the full and the pruned kernels); the pruned kernels `gconv_fwd_L1s` / `gconv_bwd_L1s` from `python/gen_generic.py` (`emit_conv_fwd(..., l3s)`, `emit_conv_bwd_lp(..., l3s, qs_name)`).
- Stage: S125 (18 November 2026), 5060 Ti. From the owner's review list of 18 November ("MP-0 medium: ten convolution paths, two can affect the answer").
- What: in MP-0 medium's second interaction the projections of the output degrees 1-3 are about 5.5e-94 in the float64 checkpoint and exactly 0 after the float32 conversion (all 131,072 entries; the owner's checkpoint inspection, and `prune_scan.py` over every cached bundle: only MP-0 medium qualifies; MPtrj-2022.9 is nearly but not exactly zero, 768 / 1,536 / 4,799 nonzero entries; OMAT-0, MP-0b3, MPA-0, MatPES, MH-1, OFF and OMOL-0 keep every path). So lin_1..3 are exactly zero whatever the geometry, and only the output-degree-0 conv paths (0,0,0) and (1,1,0) reach the answer. The pruned kernels run those two paths against the unchanged packed table (path offset `k * C`, so the dead paths' 80% of each row is never touched), the l >= 1 projection GEMMs are skipped forward and backward, and the skipped projections' outputs (`lin` or `msgf`, read by the product) are zeroed once per allocation. Exact: the kept paths' arithmetic is the full kernel's (per-path forms; S122's Cartesian block needs all four of its paths and is not emitted here).
- Measured (5060 Ti, `nsys` per MD step, S123 -> S125): MP-0 SrTiO3 `gconv_bwd_L1` 2,875 -> 1,089 us (`L1s`), `gconv_fwd_L1` 2,099 -> 678 us, `sgemm128` 1,623 -> 774 us (14.2 -> 9.1 launches); kernel time 8,519 -> 4,232 us. Library ABBA on shared plans (first / second order): MP-0 SrTiO3 (5,000 atoms) 8.20 -> 4.03 ms per step, `0.4918` (`0.4919` / `0.4917`, 3 rounds); NbCl5 (1,944 atoms) 1.72 -> 0.90 ms, `0.5211` (`0.5209` / `0.5213`, 3 rounds).
- Results (against S123; S123 against itself in brackets): MP-0 SrTiO3 max dF 2.7e-6 (1.4e-6) eV/A of 5.0, dE 1.8e-4 (1.0e-7) meV/atom, the same with `LOUP_CONV_PRUNE=0` (a GEMM-plan rounding difference on a -4e4 eV total, not the pruning); NbCl5 9.9e-7 (5.6e-7); NaCl216 1.2e-7 (1.1e-7); OFF23-M water216 (not eligible) dE 0.
- Gates (S126 library): MP-0 oxide 18 / 18 (worst force / stress ratios 0.75 / 0.52), with `LOUP_CHAIN_FOLD=0` 18 / 18 (0.61 / 0.32), each with the forced conv variants 1 and 2.
- Other GPUs (S122-S124 -> + S125, library ABBA on shared plans, 2-3 rounds): RTX A4000 (sm_86, `coraline`) MP-0 SrTiO3 `0.4134` (`0.4145` / `0.4122`), NbCl5 `0.4573` (`0.4552` / `0.4594`); RTX 4000 Ada (sm_89, `murphy`) SrTiO3 `0.4822` (`0.4824` / `0.4820`), NbCl5 `0.5209` (`0.5211` / `0.5206`). Results: A4000 dE 0, max dF 6.7e-7 (6.6e-7 with `LOUP_CONV_PRUNE=0`; the default build against itself 9.0e-7); RTX 4000 Ada max dF 1.2e-6 (its own spread 1.1e-6).
- Final library (S122-S125, S127, S128): MP-0 oxide 18 / 18 (0.78 / 0.97), with `LOUP_CHAIN_FOLD=0` 18 / 18 (0.64 / 0.37).
- Status: DEFAULT (5060 Ti, A4000 and RTX 4000 Ada; GPU-independent code; the A100 run is queued).
- Sources: this file; the owner's scripts `mp0_original_paths.py`, `loup_projection_support.py`, `mp0_scalar_replay.py`.

<a id="gen-l0-no-density"></a>
#### gen-l0-no-density: layer 0 without the unread density column
- Switch: `src/generic.cu` `GenericLayer::Jt` (layer 0's table row stride in float4: `J` for kinds 2-4, `J - 1` for the agnostic kinds 0 / 1, set at load where the table is repacked) passed to `first_fwd_kernel`, `first_bwd_kernel` and `first_bwd_edge_kernel`; `first_fwd_kernel` skips the density load, cubic and warp sum and the `D` store when `Jt == J - 1`.
- Stage: S128 (18 November 2026), 5060 Ti. From the owner's review list of 18 November ("MP-0: remove the unused first-layer density calculation ... also makes the radial row exactly 1,024 bytes").
- What: an agnostic first layer (MP-0 medium and MPtrj: `agnostic_res`; OFF23, OFF23b, OFF24: `agnostic`) reads no density: products take `D` only for kinds 2 / 3, the gate for kind 4, and the backward passes `dD` only for kinds >= 2. Yet the table kept the column (the last of each row) and `first_fwd` loaded its coefficients, evaluated the cubic and summed it per receiver. Dropping it shortens each (pair, interval) row from 65 to 64 float4 (MP-0: 1,040 -> 1,024 B, so rows stay 128 B aligned). Exact for every kept value.
- Measured (5060 Ti, `nsys` per MD step, two runs each, S127 -> S128): MP-0 SrTiO3 `first_fwd` 250 / 254 -> 228 / 230 us, `first_bwd_edge` 457 / 452 -> 438 / 467 (noise); OFF23-M water216 `first_fwd` 20.2 / 20.9 -> 18.6 / 18.7. Library ABBA on shared plans (first / second order): MP-0 SrTiO3 `0.9958` (`0.9936` / `0.9980`, 3 rounds), NbCl5 `0.9908` (`0.9849` / `0.9967`, 2 rounds), OFF23-M water216 `0.9985` (`0.9908` / `1.0063`, 3 rounds: a tie; one round at 1.025).
- Results (against S127; S127 against itself in brackets): MP-0 SrTiO3 max dF 1.5e-6 (9.4e-7) eV/A, NbCl5 1.0e-6 (9.1e-7), OFF23-M water216 1.7e-6 (1.0e-6), MH-1 NaCl216 (not eligible) 2.9e-7 (3.3e-7).
- Gates (final library): MP-0 oxide 18 / 18 on both chain-fold paths (0.78 / 0.97, 0.64 / 0.37), OFF23-M organic 24 / 24, OFF23-L organic 8 / 8.
- Status: DEFAULT (5060 Ti; GPU-independent code).
- Sources: this file.

<a id="gen-prod-scalar"></a>
#### gen-prod-scalar: the terminal product with only its scalar input (MP-0 medium)
- Switch: `python/gen_generic.py` `_scalar_prune` (constant propagation of x1..x15 = 0 through the product program: `mul` nodes with a zero operand, `lin` / `dot` nodes whose terms are all zero and feature terms on zero nodes are dropped; the kept sums keep their order) and `gprod_ro1s_fused_<sig>` (emitted beside `gprod_ro1_fused_<sig>` for every lmax-0 product; `GProdKernels::ro1s_*`); `src/generic.cu` selects it with `launch_prod_ro1_fused(..., L->conv_prune && L->kind != 4)`. Kind 4 is excluded: its product input `msgf_l = W_2 gate(...)` stays nonzero even when `lin_1..3` vanish.
- Stage: S127 (18 November 2026), 5060 Ti. From the owner's review list of 18 November ("the following per-channel product reduces to a cubic in one scalar").
- What: in a pruned layer (S125) the product's inputs m_1..3 are exactly zero, and so are all gradients the backward would write for them (no l >= 1 output can come from a single l >= 1 factor next to scalars; S125 skips the GEMMs that would read them anyway). The propagated program of MP-0's terminal product is `v0 = x0^2`, `v1 = x0 v0`, `y0 = w0 x0 + w1 v0 + w2 v1`, its adjoint three FMAs; the readout part is the full kernel's. Exact: every dropped term contributes an exact zero to sums the kernel evaluates in the same order, so y0 and dm0 are the full kernel's values up to the sign of zero.
- Measured (5060 Ti, S126 -> S127, `nsys` per MD step): MP-0 SrTiO3 `gprod_ro1_fused` 235 us -> `gprod_ro1s_fused` 71 us; kernel time 4,185 -> 4,067 us (the GEMM kernels' split moves with each library's own plans). Library ABBA on shared plans (first / second order, 3 rounds): MP-0 SrTiO3 4.00 -> 3.85 ms per step, `0.9622` (`0.9618` / `0.9626`); NbCl5 0.90 -> 0.82 ms, `0.9120` (`0.9051` / `0.9189`).
- Results (against S126; S126 against itself in brackets): MP-0 SrTiO3 max dF 3.3e-6 (1.5e-6) eV/A of 5.0, dE 1.3e-4 meV/atom (plan rounding, as for S125); NbCl5 1.5e-6 (1.1e-6).
- Gates (final library): MP-0 oxide 18 / 18 (0.78 / 0.97), with `LOUP_CHAIN_FOLD=0` 18 / 18 (0.64 / 0.37), each with the forced conv variants 1 and 2.
- Status: DEFAULT (5060 Ti; GPU-independent code).
- Sources: this file.

<a id="gen-bwd-stage-float4"></a>
#### gen-bwd-stage-float4: vectorized staging stores in the conv backward (rejected)
- Switch: none (reverted). The test: `emit_conv_bwd_lp`'s prologue computing every slot value first and writing `QS / 4` float4 stores per channel instead of `n_slots` scalar stores.
- Stage: S126 (18 November 2026), 5060 Ti. From the owner's review list of 18 November (OMAT-0 idea 3: the force kernel's staging written four values at a time; the saved ncu profile of `wprime_backward_inter1_rcv` shows 760,000 shared store requests at 4.6-way conflicts, 2.73 M conflicts, for SrTiO3 5,000 atoms).
- What: the staging of a receiver's converted gradients (`s_q[ch * 44 + slot]`) has bank step 12 between channels, so 32 consecutive channels hit 8 banks; float4 stores of a quarter warp at stride 11 chunks hit distinct banks. The generic backward uses the same layout as the specialized one, so it is the cheaper test.
- Measured (5060 Ti, S125 -> S125 + S126): registers equal (two variants 60 -> 62, no spill). `nsys` per MD step (two runs each): OMAT-0 generic SrTiO3 `gconv_bwd_L1` 3,061 / 3,020 -> 3,055 / 3,019 us; MH-1 NaCl216 73 / 69 -> 74 / 71; OFF23-L water216 `gconv_bwd_L2lp` 485 / 483 -> 490 / 487. Library ABBA on shared plans (first / second order, 2 rounds): OMAT-0 generic SrTiO3 `0.9989` (`0.9985` / `0.9993`), MH-1 NaCl216 `1.0029` (`1.0097` / `0.9960`), OFF23-M water216 `0.9950` (`0.9966` / `0.9933`), OFF23-L water216 `1.0087` (`1.0222` / `0.9951`).
- Why: the staging runs once per receiver before the per-edge loop, which bounds the kernel; the conflicts there are off the critical path. The specialized `wprime_backward_inter1_rcv` has the same prologue and is not changed either.
- Status: REJECTED.
- Sources: this file; `results/symmetrix-main-20261116/ncu_full/loup.csv` (the conflict counts).

<a id="gen-conv-fwd-tile-pair"></a>
#### gen-conv-fwd-tile-pair: slab-matched edge pairs in the forward conv tile (rejected)
- Switch: none (reverted; the forward template is SASS-identical to S132's again, 46 kernels).
- Stage: S133 (19 November 2026), 5060 Ti. From the owner's third review list of 18-19 November (OMAT-0 idea 3: pair edges by their current spline interval inside each forward tile).
- What: the forward convs decode a packed-table row once for two edges when the next edge in the tile has the same slab (`PAIR`). Rows keep their rebuild order while the atoms move, so same-slab edges drift apart. The staging warp, which holds every edge's slab, matched them with `__match_any_sync`, paired ranks 0-1, 2-3, ... of each slab group and wrote a processing order (leaders in lane order, each followed by its partner); the body loop walked that order with the existing paired decode. Each edge keeps its own sender, direction and interpolation coordinate; only the order of the receiver's sum changes. The owner's CPU screen counted 0.08% fewer coefficient loads right after a rebuild and 14.0-14.1% fewer after bounded displacements of 0.12-0.24 A.
- Measured (5060 Ti, S132 -> S132 + S133): registers within +-4 in 8 of 46 forward kernels, no stack, +144 B static shared memory in the `PAIR` variants. Library ABBA on shared plans (first / second order; 100 warm-up steps then 6 x 256 steps, so the neighbour lists age through the run): OMAT-0 generic SrTiO3 `0.9969` (`0.9993` / `0.9945`, 3 rounds; one round's A side varied by 1%), OFF24-M water `1.0007` (`1.0006` / `1.0007`), OFF23-L water216 `1.0037` (`1.0020` / `1.0054`), MP-0 SrTiO3 `1.0002` (tie). Results at the float32 spread (OMAT-0 generic max dF 4.1e-6 against its own 1.3e-6 run-to-run, plan noise; OFF23-L 1.5e-6 against 1.3e-6).
- Why: the saved row reads were already served by L1 / L2: a duplicate row within a tile is a cache hit, so fewer requests do not shorten the L2-bound forward (ncu: 78-85% of L2 peak), and the matching adds a shuffle round and a less regular loop.
- Status: REJECTED.
- Sources: this file; the owner's screen `generic_tile_pairs.py`.

<a id="gen-arch-neutral"></a>
#### gen-arch-neutral: the sm_120-only blocks of the generated convs on every GPU
- Switch: none: `python/gen_generic.py` emits no `__CUDA_ARCH__` condition any more (the Cartesian blocks, S48's `Cg` form and `EDGE_DVEC_RED` unconditionally; the per-path forms of the Cartesian paths, their staged linear forms, the old `A x Y` pull and the read-add-store edge update are gone).
- Stage: S129 (19 November 2026). The owner's question of 18 November: with three GPUs faster, enable them on every GPU.
- What: the test builds of S122 (sm_86 / sm_89) and the queued A100 build `s123x80` widened every `__CUDA_ARCH__ == 1200` condition of the generated file, so what three GPUs measured is the whole set: the Cartesian forms (S119 / S121 / S122), S48's radial pull from the x-gradient contraction and the S40 / S101 fire-and-forget edge-vector atomics. All three only remove work (FP32 instructions, registers, staged shared memory, a load) and none depends on the architecture; one code path also means the gates on any GPU cover what every GPU runs. AGENTS.md's adoption rule asks for sm_120 and sm_89; the A100 confirmation (`q123c2`, the same set) is queued on Alex. Tuning-type scopes (sgemm64 at M <= 1600, the `first_bwd_edge` register cap, the conv-variant tuner, carveouts) stay per GPU.
- Measured: 5060 Ti: the regenerated file's sm_120 SASS is identical to HEAD's (136 kernels), so nothing changes there. Registers / stack against HEAD (`cuobjdump`, one compile per architecture): sm_80 32 kernels fewer registers, 0 more, no new stack; sm_86 / sm_89 31 fewer, 2 more (+3, same allocation granule); sm_90 28 fewer, 5 more (`gconv_bwd_L0` 54 -> 62, from the RED update); sm_100 31 fewer, 4 more, an 8 B stack moves between two `gconv_fwd_L2b` variants; 28 kernels need less shared memory on every architecture. Library ABBA on shared plans, HEAD -> S129 (first / second order, 2 rounds unless noted): RTX 4000 Ada (sm_89, `murphy`): OFF23-L water216 `0.9471` (`0.9521` / `0.9420`), POLAR-1-L NaCl216 `0.9886` (`0.9916` / `0.9856`), OMAT-0 generic SrTiO3 `0.9940` (`0.9958` / `0.9922`), OFF23-M water216 `0.9944` (`0.9968` / `0.9920`, 3 rounds), MP-0 SrTiO3 `0.9958` (`0.9978` / `0.9939`), OFF24-M water `0.9961` (`0.9956` / `0.9967`), OFF23-S water216 `0.9997` (`1.0029` / `0.9965`, 3 rounds, a tie), OMAT-0 small SrTiO3 `1.0001` (tie). RTX A4000 (sm_86, `trillian`, the same card as `coraline`): OFF23-L water216 `0.9418` (`0.9506` / `0.9330`), POLAR-1-L `0.9851` (`0.9860` / `0.9841`), OFF24-M water `0.9887` (`0.9895` / `0.9878`), OMAT-0 generic `0.9949` (`0.9948` / `0.9951`), MP-0 `1.0003` (`0.9990` / `1.0016`, tie), OMAT-0 small `1.0008` (`1.0043` / `0.9972`, tie), OFF23-S `0.9997` (`0.9994` / `1.0001`, 6 rounds; a first 3-round run read `1.0036`), OFF23-M `1.0036` (4 rounds; both libraries alternate between two timing modes 1.61 / 1.65 ms on this card, so the ratio follows the mode, a noise-limited tie).
- Results (rattled cell, one evaluate, against HEAD; HEAD against itself in brackets): sm_89 MP-0 SrTiO3 max dF 8.4e-7 (1.2e-6), OMAT-0 generic 1.5e-6 (9.4e-7), OFF23-S water216 1.9e-6 (9.7e-7), OMAT-0 small 1.5e-6 (1.2e-6), OFF23-L water216 2.3e-6 (1.1e-6), POLAR-1-L NaCl216 4.0e-7 (1.5e-7); sm_86 alike (OFF23-L 2.5e-6 (1.1e-6), POLAR-1-L 4.6e-7 (1.7e-7)).
- Status: DEFAULT (5060 Ti, sm_86, sm_89; GPU-independent code; the A100 run `q123c2` / gates `q123g1` confirm cc 8.0).
- Sources: this file; `results/alex-a100-queue-20261116/README.md` (`s123x80`).

<a id="gen-lin-compact-ro"></a>
#### gen-lin-compact-ro: the terminal product and readout on the live channels
- Switch: `src/generic.cu` `compact_layout` (the certificate, in the loader's product block), `GenericLayer::lin_compact / n_ang / kept / d_pos`; `python/gen_generic.py` `gprod_ro1c_fused_<sig>` (`launch_prod_ro1c_fused`). `LOUP_LIN_COMPACT=0` keeps the dense layout; `LOUP_DEBUG_COMPACT=1` prints each compacted layer.
- Stage: S130 (18 November 2026), rank 1 of the owner's dense-model research list (`loupmd-speed-research-20261118`).
- What: a kind-1 layer (projections feeding the product directly) whose linear readout is folded into the fused product (S73) wastes most of its projection work on MPtrj-2022.9: for SrTiO3's species, 51 of the second interaction's 256 channels never reach the energy (product weights or folded readout row exactly zero), and only 12 of the 205 kept have a nonzero degree 1-3 projection column (1 / 2 / 12 per degree). The certificate reads only exact zeros of the loaded float32 weights. Kept channels are ordered angular first, then scalar-only; degree 0's projection keeps a column per kept channel (208 with padding), degree l >= 1 only its live columns (8 / 8 / 16 instead of 256 each). `gprod_ro1c_fused` runs the full product program on the angular channels and S127's cubic on the scalar-only ones, and the readout rows follow the compact order. The layer compacts only if its degree 1-3 projection work shrinks by at least a quarter.
- Measured (5060 Ti, library ABBA on shared plans against S129): MPtrj-2022.9 SrTiO3 (5,000 atoms) 10.98 -> 8.63 ms per step, `0.7848`; NbCl5 `0.7029` (173 of 256 kept).
- Results (rattled SrTiO3, one evaluate): max dF 1.05e-6 eV/A against the dense build's own spread of 8.1e-7.
- Gates (5060 Ti, the S129-S136 library): MPtrj-2022.9 oxide 6 / 6 on every path, worst force / stress ratio default 1.33 / 0.77, `LOUP_CHAIN_FOLD=0` 1.28 / 0.78, `LOUP_LIN_COMPACT=0` 1.39 / 0.73.
- Other GPUs: RTX 4000 Ada (sm_89, `murphy`), library ABBA of S129 against S129-S136 (here S130 and S132 together): MPtrj SrTiO3 `0.7603` (`0.7628` / `0.7578`, 14.11 -> 10.73 ms), NbCl5 `0.6666` (`0.6632` / `0.6701`); results against S129 (S129 against itself in brackets) SrTiO3 max dF 9.9e-7 (7.1e-7) eV/A, NbCl5 8.5e-7 (5.1e-7).
- Status: DEFAULT (GPU-independent).
- Sources: this file.

<a id="gen-l0-even-odd"></a>
#### gen-l0-even-odd: layer 0's table columns even first, then odd
- Switch: `src/generic.cu` `first_col_pos(j, Jh)` (column j at `j / 2`, or `Jh + j / 2` for odd j, `Jh = ceil((J - 1) / 2)`), applied by the loader to every hidden-table row and by `first_fwd_kernel`, `first_bwd_kernel` and `first_bwd_edge_kernel`; the density column (if kept) stays last.
- Stage: S131 (18 November 2026), from the OMAT-0 review list ("32 even + 32 odd columns").
- What: `first_bwd_edge_kernel`'s lane i reads columns 2i and 2i + 1 of its edge's row: two float4 loads whose 32 lanes each touch the same 32 sectors (1 KB). With the even columns first, the two loads read two contiguous 512 B runs (16 sectors each); `first_fwd` / `first_bwd` index columns by thread and read two contiguous runs per warp instead of one. The values and the order of every sum are unchanged.
- Measured (5060 Ti, library ABBA on shared plans): MP-0 medium SrTiO3 `0.9971`, NbCl5 `0.9934`, OMAT-0 medium generic SrTiO3 `0.9988` (4 rounds); every case faster in both orders.
- Gates (5060 Ti, the S129-S136 library): MP-0 medium oxide 18 / 18 (0.80 / 0.56), OMAT-0 medium generic oxide 18 / 18 (2.04 / 1.80), OFF23-M organic 24 / 24 (0.35 / 0.61), OFF23-L organic 8 / 8 (0.44 / 1.13, CPU references).
- Other GPUs: RTX 4000 Ada (sm_89), library ABBA of S129 against S129-S136, where S131 is the only change for these models: OMAT-0 generic SrTiO3 `1.0009` (`1.0027` / `0.9990`), OFF23-M water216 `1.0002` (`1.0001` / `1.0003`, 3 rounds): ties.
- Status: DEFAULT.
- Sources: this file.

<a id="gen-lin-compact"></a>
#### gen-lin-compact: non-terminal products on the live channels
- Switch: as [gen-lin-compact-ro](#gen-lin-compact-ro); `GenericLayer::d_order` (compact position -> channel, the dead channels last), `gprod_fwdc_<sig>` / `gprod_bwdc_<sig>` (`launch_prod_c`). The compact layers' padding columns of `dlin` are zeroed once in `alloc_system`.
- Stage: S132 (18-19 November 2026), rank 3 of the dense-model research list (MP-0 layer 0), extended to MPtrj's layer 0.
- What: the certificate of [gen-lin-compact-ro](#gen-lin-compact-ro) without the readout test; a dead channel's product output is zero and is written as zero. The compact projections (layer 0: the `C0_l` tables; later layers: `W_lin_l`) keep each degree's live columns; the product kernels read them through the position maps and write their outputs in the dense layout, so the next layer's weights and the chain fold are untouched. MP-0 medium layer 0: 128 kept, 38 angular, degree 1-3 projections 40 columns wide instead of 128. MPtrj-2022.9 layer 0 (SrTiO3): 251 kept, 214 angular, 256 / 192 / 144 / 128.
- Measured (5060 Ti, library ABBA on shared plans):
  - First version, each degree's width the prefix of positions up to its last live column: MP-0 SrTiO3 `0.9036` (3.86 -> 3.49 ms), NbCl5 `0.8748`; MPtrj's layer 0 did not qualify.
  - Per-degree position maps (exact widths; MPtrj's layer 0 now compacts), widths padded to 4: MPtrj SrTiO3 `0.9920`, NbCl5 `0.9464`; MP-0 `1.0095` (slower in both orders). One `nsys` run showed MP-0's degree-3 projection (N = 36) on a hybrid GEMM tile at 114 us in the pass against 27.5 us for N = 40, but padding to 8 (below) did not recover the 1%, so that pick is not the cause; it stays unexplained, within the plans' variance between builds ([meas-plan-variance](#meas-plan-variance)).
  - Widths padded to 8 instead of 4, nothing else changed: MPtrj SrTiO3 `0.9799` (`0.9809` / `0.9789`, 8.51 -> 8.34 ms), NbCl5 `0.9911` (`0.9913` / `0.9908`); MP-0 SrTiO3 `1.0035` (`1.0037` / `1.0034`, 3 rounds), NbCl5 `0.9998` (tie). Kept: one rule, and MPtrj's gain is larger than MP-0's loss.
- Results (rattled cells, one evaluate, against the previous build (maps, padding 4) and against the dense layout `LOUP_LIN_COMPACT=0`; the previous build against itself in brackets): MPtrj SrTiO3 max dF 8.0e-7 / 1.1e-6 eV/A (1.4e-6), MP-0 SrTiO3 2.5e-6 / 2.7e-6 (9.3e-7) of |F|max 5.0.
- Gates (5060 Ti, the S129-S136 library): MPtrj-2022.9 oxide 6 / 6 as in [gen-lin-compact-ro](#gen-lin-compact-ro); MP-0 medium oxide 18 / 18 on every path, worst force / stress ratio default 0.80 / 0.56, `LOUP_CHAIN_FOLD=0` 0.63 / 0.30, `LOUP_CONV_PRUNE=0` 0.78 / 0.50, `LOUP_SENDER_BWD=0` 0.80 / 0.49, `LOUP_LIN_COMPACT=0` 0.80 / 0.47.
- Other GPUs: RTX 4000 Ada (sm_89), library ABBA of S129 against S129-S136: MPtrj as in [gen-lin-compact-ro](#gen-lin-compact-ro); MP-0 SrTiO3 `0.8194` (`0.8157` / `0.8231`, 4.88 -> 4.00 ms), NbCl5 `0.8083` (`0.8071` / `0.8095`), with S131 and S135; results SrTiO3 max dF 1.2e-6 (1.2e-6), the 5-atom `srtio3x1` cell 2.1e-7 (3.0e-7).
- Status: DEFAULT (GPU-independent).
- Sources: this file.

<a id="gen-conv-bwd-sender"></a>
#### gen-conv-bwd-sender: the pruned conv backward owned by the sender
- Switch: `python/gen_generic.py` `emit_conv_bwd_l1s_sender` -> `gconv_bwd_L1sr<NCH, WANT_DX, PRELOC>` in `src/generated_generic.cu`, launched for the pruned lx 1 layer at C 128 / 256; `LOUP_SENDER_BWD=0` runs the receiver-owned `gconv_bwd_L1s`.
- Stage: S135 (18 November 2026), rank 6 of the dense-model research list (MP-0 sender-owned backward).
- What: the receiver-owned backward scatters every edge's x gradient to its sender with atomics (21% of MP-0's pruned backward: [meas-conv-ablation-bounds](#meas-conv-ablation-bounds)). The neighbour list is symmetric: edge (i -> j) in row j has its reverse (j -> i) in row i at the same distance and direction -n. So block j walks its own row reversed: for each slot, the reversed edge (sender j, receiver i) gathers receiver i's two `dmid0` values per channel, j's features stay in registers, and j's x gradient accumulates per warp and is written once, a fixed-order sum over the four warps. The reversed edge's force dE/du' goes into the row's own slot as -dE/du' (its vector is u = -u'), which keeps forces and virial; every slot is written once.
- Measured (5060 Ti, MP-0 medium SrTiO3): `gconv_bwd_L1s` 1,023 -> `gconv_bwd_L1sr` 764 us per force call (`nsys`, fixed cell); library ABBA on shared plans SrTiO3 `0.9166` (3.55 -> 3.26 ms), NbCl5 `0.9343`.
- Results: within float32 rounding of the receiver-owned kernel on SrTiO3, NbCl5 and the 5-atom cell (`srtio3x1`, periodic self-images in range).
- Gates (5060 Ti, the S129-S136 library): MP-0 medium oxide 18 / 18 with the sender-owned kernel (0.80 / 0.56) and with `LOUP_SENDER_BWD=0` (0.80 / 0.49).
- Other GPUs: RTX 4000 Ada (sm_89): in the MP-0 ABBA of [gen-lin-compact](#gen-lin-compact) (`0.8194` / `0.8083` with S131 and S132).
- Status: DEFAULT (GPU-independent).
- Sources: this file.

<a id="gen-conv-fwd-dict"></a>
#### gen-conv-fwd-dict: the forward conv's radial rows from a per-group shared-memory dictionary
- Switch: none (reverted). The test build added `launch_conv_fwd` variant 3 for lx 1 at C 128 with precomputed slabs: `gconv_fwd_L1d<KD>` / `gconv_fwd_L1sd<KD>` (generated from the unpaired kernel's per-path code, the table load replaced by a load through a per-edge pointer and stride) and `conv_dict_build_kernel<KD>` in `src/generic.cu`; `LOUP_CONV_DICT_KD=40|64` chose the size, `LOUP_CONV_FWD_VARIANT=3` forced it.
- Stage: S138 (19 November 2026), the OMAT-0 review list's radial-row cache (idea 1), after [meas-conv-ablation-bounds](#meas-conv-ablation-bounds) put its bound at 26% of the OMAT-0 forward conv and 40% of MP-0's.
- What: a block took 32 consecutive receivers (the atoms are sorted by species, so one species but at the boundaries) and 8 of the 128 channels; warp w held receivers 4w..4w+3, lane (receiver, channel). Per force call, one kernel counted each group's slab ids in a shared hash table and kept the at most KD used at least twice, sorted. Each block copied its 8-channel slice of those rows (10 paths x 64 B per slab, padded to 704 B so slab parities fall in different bank halves) to shared memory. Staging lanes looked each edge's slab up by binary search and stored a pointer into the dictionary (stride 8) or into the packed table (stride C), so hits and misses ran the same code without divergence. The per-path arithmetic and each receiver's edge order were the unpaired kernel's: results stayed at float32 rounding (OMAT-0 generic SrTiO3 max dF 1.9e-6 eV/A against variant 2 in the same library, MP-0 2.1e-6, MPtrj NbCl5 1.7e-6, each at the atomic backward's run-to-run spread).
- Measured (5060 Ti, SrTiO3 5,000 atoms, `nsys` over 64 MD steps, us per step): OMAT-0 generic `gconv_fwd_L1` 1,693 (R5) -> 4,306 at KD 96 (82 KiB of shared memory: one 8-warp block per SM) and 2,717 at KD 40 (44 KiB: two blocks), plus 51 / 40 us of dictionary builds; MP-0 `gconv_fwd_L1s` 662 -> 1,278 / 1,168, plus 44 / 37. MD ABBA against variant 2 in the same library: OMAT-0 generic `1.300` (`1.2995` / `1.3005`), MP-0 `1.189` (`1.1865` / `1.1911`).
- Reading: occupancy decided it: one -> two blocks per SM (KD 96 -> 40) cut the kernel by 37% although the smaller dictionary misses more, so it waited on latency, not on table bandwidth. At 16 resident warps (R5: 20, by registers) it still ran 1.6x slower than R5. Not profiled further; the likely costs are the staging (the spherical harmonics and a binary search for every 4 edges per 8 lanes, where R5 computes them once per receiver tile for 128 channels) and the generic-pointer loads.
- Status: REJECTED (code removed).
- Sources: this file.

<a id="gen-conv-fwd-path-teams"></a>
#### gen-conv-fwd-path-teams: the forward conv's paths split between warp teams
- Switch: none (reverted). A scratch build appended the round-4 research's compiled kernels `f2_0` / `f3_0` (`omat0-round4-20261119/path_codegen`, generated from the production unpaired edge loop) to `src/generated_generic.cu` as `launch_conv_fwd` variants 3 / 4 (lx 1, C 128, precomputed slabs), forced with `LOUP_CONV_FWD_VARIANT`.
- Stage: S139 (19 November 2026), round-4 research idea 1 (after LunaTP's path-group parallelism).
- What: one receiver per block. Team 0's first warps stage the 32-edge tile (geometry, slabs, sender ids, density) once; each 128-thread team then runs the edge loop over its own paths (`f2_0`: {1,3,4,6,7} / {0,2,5,8,9}, 136 + 136 loop instructions; `f3_0`: {1,6,7} / {0,2,5,8} / {3,4,9}), each output component in one team with its accumulation order unchanged. 64 / 56 registers against R5's 96, no spills; 17 global loads per edge against 14.
- Measured (5060 Ti, nsys over 64 MD steps, one library, variants forced; us per step): SrTiO3 R1p 2,189, R1 2,283, R5 1,709, `f2_0` 2,291, `f3_0` 2,250; NbCl5 344 / 351 / 322 / 355 / 351. Steps in the same runs: 7.97 ms with R5, 8.43 / 8.42 with `f2_0` / `f3_0`. Forces against R5: SrTiO3 max dF 3.8e-6 eV/A (R5 against itself 3.3e-6), NbCl5 9.4e-7 (4.0e-7).
- Reading: against R1, which also runs one receiver per block, the split gains nothing (`f2_0` +0.3%, `f3_0` -1.5%), so fewer registers do not pay even per receiver. A one-receiver block is bound by L2 traffic (ncu of the 18 November profile, R1p: L2 at 81% of peak, L1 hit rate 5.6%, long scoreboard the top stall), which a path split does not reduce. R5 is not (ncu of `results/profiles-20261119`, OMAT-0 generic SrTiO3: L2 58%, L1 hit rate 56%, SM 68%): its five receivers share table rows in L1, which a one-receiver block forgoes. S47 had found the same on the specialised spline ([spl-r6-r8](#spl-r6-r8)).
- Status: REJECTED (code removed).
- Sources: this file; `omat0-round4-20261119/path_codegen/FINDINGS.md`.

<a id="gen-l0-bwd-lsu"></a>
#### gen-l0-bwd-lsu: layer 0's edge backward on fewer load/store-pipe instructions
- Switch: `src/generic.cu` `first_bwd_edge_kernel` (all its instantiations; no switch: every value is computed as before, one per-edge sum in another order).
- Stage: S140 (19 November 2026). Prompted by the round-4 research's proposal for this kernel (two TF32 products for its backward matrix work), whose premise the archived ncu profile does not support.
- What: ncu of the archived OMAT-0 generic SrTiO3 profile (`results/profiles-20261118/ncu/omat0m_gen_srtio3_raw.csv.gz`): `first_bwd_edge` 483 us, issue active 59%, LSU pipe 70.7% of peak, FMA pipe 30%, tensor pipe 0; long and short scoreboard the top stalls. ncu counts 4.1 M memory instructions (1.70 M global loads, 1.52 M shared loads, 0.78 M shared stores, 0.08 M reductions); the code adds 27 shuffles per edge (about 10 M over 369,266 edges), which also issue on the LSU pipe: six broadcasts of the staged edge's metadata, the 16-shuffle fold of the angular gradients and a 5-shuffle butterfly of the radial pull. The change: the staging lanes write the metadata (receiver, sender species, slab = pair x I + interval, t, slope scale) to shared memory, read in the edge loop as one 16-byte and one 4-byte broadcast load; the radial pull's per-lane partial rides in slot 0 of the angular fold (the gradient of the constant Y0, computed and discarded before), so lane 0 ends with its warp sum and the butterfly goes. Nine of ~38 LSU instructions per edge removed. The capped COLS = 2 kernels stay at 80 registers without stack, the COLS = 3 ones fall from 120-123 to 96-118; shared memory +2.5 KB per block (14.0 KB, 6 blocks per SM still fit).
- Exactness: every value is bitwise as before except the radial pull, now summed in the fold's tree order instead of the butterfly's (one float32 reassociation per edge).
- Measured (5060 Ti): `nsys` `first_bwd_edge` per step: MP-0 medium SrTiO3 431 -> 379 us (-12%), OMAT-0 medium generic SrTiO3 493 -> 457 us (-7%). Library ABBA on shared plans against S137: MP-0 SrTiO3 `0.9846` (`0.9854` / `0.9838`, 3 rounds), OMAT-0 generic SrTiO3 `0.9976` (`0.9982` / `0.9969`, 3 rounds), OFF23-M water216 `0.9880` (`0.9878` / `0.9881`, 2 rounds).
- Other GPUs: RTX 4000 Ada (sm_89, `murphy`), library ABBA: MP-0 SrTiO3 `0.9895` (`0.9939` / `0.9850`), NbCl5 `0.9933` (`0.9944` / `0.9923`), OMAT-0 generic SrTiO3 `0.9978` (`0.9991` / `0.9964`), OFF23-M water216 `0.9960` (`1.0004` / `0.9915`, a tie).
- Results (rattled cells, one evaluate, against S137; S137 against itself in brackets): 5060 Ti OMAT-0 generic SrTiO3 max dF 5.6e-6 (4.2e-6) eV/A, MP-0 SrTiO3 2.8e-6 (2.0e-6), OFF23-M water216 1.4e-6 (1.2e-6); RTX 4000 Ada 1.2e-6 (1.0e-6), 1.1e-6 (1.2e-6), 8.4e-7 (1.5e-6).
- Gates (5060 Ti): MPtrj oxide 6 / 6 (worst force / stress ratio 1.31 / 0.74), MP-0 oxide 18 / 18 (0.81 / 0.51), OMAT-0 generic oxide 18 / 18 (2.03 / 1.83), OFF23-M organic 24 / 24 (0.35 / 0.60), OFF23-L organic 8 / 8 (0.40 / 1.18, CPU references), MH-1 crystals 18 / 18 (0.85 / 0.31), MH-1 `omol` organic 24 / 24 (0.35 / 0.45), OMOL-0 XL organic 8 / 8 (0.84 / 0.54), POLAR-1-M crystals 18 / 18 (2.70 / 1.09), POLAR-1-L crystals 6 / 6 (1.94 / 0.72, CPU references). pytest 77 / 77; the POLAR cell-change test's first-run flake (AGENTS.md) hit the library's first suite run once and passed 6 / 6 in isolation with fresh plans, as on S137's library.
- Status: DEFAULT (GPU-independent).
- Sources: this file; `results/profiles-20261118/ncu/omat0m_gen_srtio3_raw.csv.gz`.

<a id="gen-conv-fwd-pruned-r5"></a>
#### gen-conv-fwd-pruned-r5: four staged harmonics, literal barrier ids and a 16 KB carveout for the pruned forward
- Switch: `python/gen_generic.py` `emit_conv_fwd` (`sh4`: no extras, no Cartesian forms, every path reads harmonics of degree <= 1; `bar_code`: literal `bar.sync` ids when `sh4`), and `pruned_r5_carveout()` in the generated launcher (cc 12 only; `gconv_fwd_L1s<5, false, 640, *, 128>`). No environment switch; `LOUP_CONV_PRUNE=0` runs the full kernel instead.
- Stage: S141 (19 November 2026), from the owner's idea lists (occupancy of the pruned layer).
- What: MP-0 medium's pruned second interaction ([gen-conv-prune](#gen-conv-prune)) keeps paths (0,0,0) and (1,1,0), which read only Y0 and Y1. Its forward staged all sixteen harmonics per edge (2,048 B per 32-edge receiver tile); it now stages four as one `float4` (512 B), so the block needs 7.0 KB of shared memory instead of 14.7 KB. With the group barrier id in a register, the compiler reserved all 16 hardware barriers (`ncu` `launch__barrier_count` 16), so one block filled an SM; literal ids (`bar.sync n+1, 128` under `if constexpr (R > n)`) reserve six. The driver then picked the 32 KB shared-memory configuration; the 16 KB one (carveout 10%) leaves more L1 for the table reads.
- Measured (5060 Ti, MP-0 medium SrTiO3 5,000 atoms, `ncu`, one force call): `gconv_fwd_L1s` 647.5 us (S135) -> 597.7 us (four harmonics, literal ids, the driver's 32 KB) -> 576.4 us (carveout 10; 15 gives 577.7, 0 gives 8 KB and 635.1). MD (lab, base / switches / carveout, a b c c b a order): SrTiO3 3.092 / 3.067 / 3.043 and 3.095 / 3.068 / 3.050 ms (`0.985` with the carveout); NbCl5 0.672 / 0.662 / 0.651 and 0.668 / 0.658 / 0.653 (`0.974`). Develop library against `d6e97b7` on shared plans (a d d a): SrTiO3 3.098 / 3.043 / 3.046 / 3.092 (`0.984`); NbCl5 0.660 / 0.666 / 0.649 / 0.664 (a noisy first dev run, max 0.690; `0.995` overall). OMAT-0 generic SrTiO3 (kernels unchanged): 7.724 / 7.728 / 7.750 / 7.761, a tie.
- Results (develop library against `d6e97b7`, same plans, one evaluate): MP-0 SrTiO3 max dF 5.7e-7 eV/A, dE 2.6e-7 meV/atom; OMAT-0 generic SrTiO3 max dF 3.8e-6 (own spread 1.1e-6).
- Gates (5060 Ti, the develop library, one GEMM plan set per model): POLAR-1-M crystals 18 / 18 (worst force / stress ratio 2.23 / 1.38), POLAR-1-S 5 / 5 (0.62 / 0.63; NaNbO3_c0 skipped as UNSTABLE), POLAR-1-L 6 / 6 (1.66 / 0.75, cached references), MP-0 medium oxide 18 / 18 (0.80 / 0.46) and 18 / 18 with `LOUP_CONV_PRUNE=0 LOUP_SENDER_BWD=0 LOUP_LIN_COMPACT=0 LOUP_CHAIN_FOLD=0` (0.68 / 0.33), OMAT-0 medium generic oxide 18 / 18 (2.03 / 1.81). pytest 77 / 77 (`tests/`, the develop library).
- Other GPUs: not measured (the owner's workstations were not used); the carveout is set on cc 12 only, the harmonics and barrier changes run everywhere.
- Status: DEFAULT (5060 Ti only).
- Sources: this file.

<a id="gen-conv-fwd-r6"></a>
#### gen-conv-fwd-r6: six receivers per forward conv block
- Switch: none (reverted). Lab `LOUP_LAB_R=6` launched `gconv_fwd_L1<6, ..., 768>` / `gconv_fwd_L1s<6, ...>`.
- Stage: S141 (19 November 2026).
- Measured (5060 Ti, `ncu`, one force call): OMAT-0 generic SrTiO3 `gconv_fwd_L1` R5 1,594.8 us (96 registers) -> R6 1,579.0 us (80 registers); MP-0 pruned R5 597.7 -> R6 600.1 us. MD OMAT-0 generic SrTiO3: base 7.701 / 7.761, R6 (register ids) 7.744 / 7.752, R6 (literal ids) 7.721 / 7.733 ms: a tie.
- Status: REJECTED (5060 Ti only).
- Sources: this file.

<a id="gen-conv-fwd-bar-literal-full"></a>
#### gen-conv-fwd-bar-literal-full: literal barrier ids in the full lx 1 forward
- Switch: none (S141 keeps the register id for every kernel but the pruned one).
- Stage: S141 (19 November 2026).
- Measured (5060 Ti, OMAT-0 generic SrTiO3): `ncu` 1,593.7 -> 1,594.8 us (16 -> 6 barriers, no change in blocks per SM: registers limit it); MD with literal ids 7.810 / 7.797 ms against 7.739 / 7.755 with the register id (+0.7%).
- Status: REJECTED (5060 Ti only).
- Sources: this file.

<a id="gen-conv-tune-early"></a>
#### gen-conv-tune-early: the conv forward variants timed after 50 passes without a rebuild
- Switch: `tune_early_variants` (`src/engine.cu`, `kTuneEarlyPasses` = 50), after every MD or caller-integrated step (`run_md_loop`'s `one_step`) and after an evaluation that rebuilt on the host (`evaluate_once`); `LOUP_CONV_TUNE=0` and `LOUP_CONV_FWD_VARIANT` act on it as on the rebuild's timing.
- Stage: release, PLAN.md O41 (20 November 2026), 5060 Ti only.
- What: [gen-conv-fwd-variants](#gen-conv-fwd-variants) times the variants at a system's first MD rebuild, so a system whose list is never rebuilt kept variant 0: a solid near its lattice (the benchmark's SrTiO3 cells from rest: no rebuild in 300 steps), short runs, and callers whose every evaluation rebuilds on the host (LAMMPS's pair style under `fix npt`: a new cell at every call). After 50 force passes without a timing the variants are timed on the last pass's inputs; the first rebuild, if one comes, times them again (the set-up lattice picked wrongly for thermalised `NbCl5`, [spl-multi-receiver](#spl-multi-receiver)). Runs that rebuild before 50 passes (water from rest: 7 rebuilds in 100 steps) are unchanged. The `loup_evaluate` step graph already went through `run_md_loop` and was timed at its first rebuild (LAMMPS's pair style on OFF24-M water picked R5), contrary to what §6.38 first said.
- Measured (5060 Ti, the benchmark's NVE from rest, 100 + 200 steps, `step_ms` of the 200, fresh process and GEMM plans per run, library `42425b8a699e8a90` (f) against `6c14052532dc53b4` (g), f g g f f g g f): OMAT-0 medium generic SrTiO3 5,000 atoms 7.288 -> 7.131 ms (`0.978`), 10,140 atoms 14.870 -> 14.547 (`0.978`); MH-1 SrTiO3 5,000 29.413 -> 29.169 (`0.992`); every g run below every f run. OFF24-M water 5,184 8.812 -> 8.804 (`0.999`, tie: timed at its first rebuild on both). The timing: 20-23 ms at 5,000 atoms, 39 ms at 10,140, reported as `tune_ms`. Forced variant 2 against variant 0 on library f gave the same picture (A B B A, A B at 98,415: OMAT-0 SrTiO3 5,000 / 10,140 / 98,415 `0.978` / `0.980` / `0.977`, MH-1 5,000 / 10,140 `0.988` / `0.986`).
- Not measured: the RTX 4000 Ada, where the variants are not timed (cc 12.0 only) and nothing changes by construction.
- Status: DEFAULT on the local `release/v1` (5060 Ti only).
- Sources: this file, [§6.39][s639].

### MACE-POLAR-1 long range

<a id="pol-double-sf"></a>
#### pol-double-sf: double accumulation in k-space
- What: structure factors over atoms and the per-atom feature / gradient passes over k accumulate in double; k data tiled in shared memory.
- Status: DEFAULT. Measured: not recorded alone. Sources: [§5.1][s51].

<a id="pol-fixed-point-phase"></a>
#### pol-fixed-point-phase: exact fixed-point k-space phases
- Switch: `frac_kernel` (32-bit fixed point), `kphase`.
- Stage: S6 (13 November 2026).
- What: fractional coordinates are stored as `s * 2^32 mod 2^32`; `n . s mod 1` comes out of wrapping integer arithmetic, then `sincospif` on [-0.5, 0.5). Before: float fractional coordinates, a phase error growing with |n|.
- Status: DEFAULT.
- Measured: perfect NaCl 10x4x4 (POLAR-1-S), residual force 3.0e-4 -> 8.7e-5 eV/A.
- Sources: [§5.4][s54].

<a id="pol-mlp-aliasing"></a>
#### pol-mlp-aliasing: MLP reverse writing over its own input
- Switch: `mlp_bwd` in `src/polar.cu`; `ln_silu_bwd_kernel` now runs in place.
- Stage: S6 (13 November 2026).
- What: after the first hidden layer the reverse GEMM's destination was the buffer holding its input dz. Found while chasing NaN temperatures in POLAR MD.
- Status: FIX.
- Measured: perfect NaCl 6x6x6 (1,728 atoms), POLAR-1-S: max force 4.8 eV/A (2.99 and 10.8 on repeated calls) -> 1.1e-5 eV/A; NVE no longer heats (T 302 -> 429 K in 6 fs before, 300 -> 290 K after). Smaller cells at rounding level: NaCl 7x4x4 residual 1.1e-4 -> 2.5e-6 eV/A.
- Why: harmless while one GEMM tile covered all rows; from ~1,700 atoms the tiles raced.
- Sources: [§5.4][s54].

<a id="pol-corrected-stress"></a>
#### pol-corrected-stress: stress with the k-space cell dependence
- Switch: `lr_virial_kernel`.
- What: the k-space energy's dependence on the cell (MACE PR 1718, as FastMACE). The gate's POLAR stress reference is the float64 energy's finite difference.
- Status: DEFAULT.
- Measured: the installed PolarMACE (0.3.16) hands the k-space terms the unstrained geometry, so its autograd stress misses up to 2e-5 eV/A^3 (NaCl). Reference vs finite difference 2.4e-9, LoupMD vs finite difference 8e-8 eV/A^3.
- Sources: [§5.1][s51].

<a id="pol-precise-math"></a>
#### pol-precise-math: precise `expf` / `sqrt` in POLAR
- Stage: S6 (12 November 2026).
- What: an attempt to cut the float32 stress error on symmetric crystals (marginal failures on the Ada at the time).
- Status: REJECTED.
- Measured: the stress error did not change (numbers not kept). The failures were later traced to the 3xTF32 GEMMs (gemm-simt-for-lr).
- Sources: session record of 12 November 2026 (not in the status file).

<a id="pol-stress-diagnosis"></a>
#### pol-stress-diagnosis: origin of POLAR's float32 stress error
- Stage: S6 (12 November 2026).
- Status: MEASUREMENT.
- Measured: the error is an isotropic diagonal and comes from the local electron energy term (it contributes -0.043 eV/A^3 to the stress; LoupMD's relative error there ~3e-6); the k-space virial matches the reference to 1e-10; without that term the error is ~2e-8. MACE float32's own error on the same cells varies 1e-8 to 1.8e-7.
- Sources: session record of 12 November 2026 (not in the status file).

<a id="pol-set-cell"></a>
#### pol-set-cell: force graph re-captured on cell changes
- Switch: `PolarLR::set_cell` reports every cell change.
- Stage: review round 6 (S5, 13 November 2026).
- Status: FIX.
- Measured: NaCl 2x2x2, POLAR-1-S, strain 3e-4 on the same engine: 1e-6 eV/atom, 9e-5 eV/A and 3e-7 eV/A^3 against a fresh engine before; identical now.
- Sources: [§3.2 S5][s32].

<a id="pol-sf-f32"></a>
#### pol-sf-f32: structure factors in float32 chunks
- Switch: `sf_kernel<NC>` (128 threads per k).
- Stage: S7.
- What: each thread sums its atoms' `X cos` / `X sin` in float32 over 1,024-atom chunks and folds them into double per chunk (as the feature and gradient passes already did), with coalesced `float4` loads of X; before, every term was a 1/64-rate FP64 add.
- Status: DEFAULT.
- Measured: POLAR-1-S NaCl 0.942, POLAR-1-M NaCl 0.973, `NbCl5` 0.833, POLAR-1-L NaCl 0.987. Gates POLAR-1-S / -M / -L PASS.
- Sources: this file (commit `9417f4a`).

<a id="pol-contig-weights"></a>
#### pol-contig-weights: per-degree contiguous SCF weights
- Stage: S7.
- What: `Wpot` / `Wq` (and the electron-energy `le_Wq` / `le_Wv`) sliced at load into one contiguous matrix per degree so their GEMMs take the packed `cublasLt` / own-SGEMM path instead of the strided `cublasSgemm` fallback; `qnew = qin + out` in one kernel instead of a copy and an add.
- Status: REJECTED.
- Measured (b/a against gen-conv-v2): POLAR-1-S NaCl 1.008, POLAR-1-M NaCl 0.952, `NbCl5` 0.993, POLAR-1-L NaCl 1.045. Gates passed. Mixed on one GPU; not kept.
- Sources: this file.

<a id="pol-kpass-32"></a>
#### pol-kpass-32: small blocks for the per-atom k-space passes
- Stage: S7.
- What: `feat_pass_kernel` / `grad_pass_kernel` with 32 threads per block for N <= 512, to spread 216 atoms over more SMs.
- Status: REJECTED.
- Measured (together with pol-contig-weights): POLAR-1-S NaCl 1.074, POLAR-1-M NaCl 1.060; each block then re-stages the same k tiles, which costs more than the extra SMs gain.
- Sources: this file.

<a id="pol-k-split"></a>
#### pol-k-split: k chunks for the per-atom k-space passes
- Switch: `k_chunk(N, K)` / `k_splits_max(N)` in `src/polar.cu`; `feat_pass_kernel` and `grad_pass_kernel` take the chunk length and range over `blockIdx.y`; `k_reduce_kernel` adds the chunks.
- Stage: S8.
- What: one thread per atom over all k left 1,944 atoms in 16 blocks (< 1 warp per scheduler on 36 SMs). The k sum is now split into enough chunks for ~2 blocks per SM; each chunk keeps its double sums and writes them to `kpart[chunk][atom]`, and `k_reduce_kernel` adds the chunks in chunk order (f assigned; dq added; forces by one atomic per atom and component, as before). One chunk keeps the direct path. A first version adding the chunks with float atomics moved POLAR-1-M `NbCl5` forces by 1.05e-4 eV/A (18x run-to-run) and was replaced; the fixed-order version differs from S8 by 8.1e-6 eV/A against 6.9e-6 run-to-run.
- Measured: kernels (POLAR-1-M `NbCl5`, nsys): `grad_pass<2>` 924-964 -> 225 us, `feat_pass` 402-449 -> 107 us, `grad_pass<1>` 250-267 -> 72 us. ABBA b/a against S8, fresh GEMM plans on both sides: POLAR-1-M `NbCl5` 0.928 (29.92 -> 27.75 ms), NaCl 216 0.958; POLAR-1-S NaCl 216 0.906, NaCl 1,728 0.876; POLAR-1-L NaCl 216 0.978. Gates PASS: POLAR-1-S (NaNbO3_c0 energy row at 0.679 meV/atom, see STATUS 5.2), POLAR-1-M (worst force 1.32), POLAR-1-L (CPU refs, worst 1.15).
- Status: DEFAULT.
- Sources: this file.

<a id="pol-2d3d-nodiv"></a>
#### pol-2d3d-nodiv: 2D/3D div-free elementwise grids and fused `inv2_kernel`
- Stage: S15 (14 November 2026).
- What: replaced `int64` div/mod indexing in `add_bias_kernel`, `bcast_mul_kernel`, `bcast_mul_bwd_kernel`, `inv_kernel`, `inv_bwd_kernel` with 2D/3D grid coordinates and fused two `inv_kernel` calls into `inv2_kernel`.
- Status: REJECTED.
- Measured (5060 Ti, `POLAR-1-M` `NbCl5`): `inv2` cut `2 * 80 -> 116 us`, while `bcast_mul` (`36.5 -> 36.1 us`), `bcast_mul_bwd` (`86.8 -> 90.2 us`), and `inv_bwd` (`112.0 -> 110.2 us`) stayed DRAM-bandwidth bound; quick 2x128 ABBA `27.0598 -> 27.0719 ms` (`b/a = 1.0004`). Reverted.
- Sources: this file.

<a id="pol-sf-tiled"></a>
#### pol-sf-tiled: multi-`k`-vector warp tiling around SoA shared-`X` in `sf_kernel`
- Switch: `sf_kernel_tiled<NC, TK>`, `launch_sf` in `src/polar.cu` (`TK = 8` for `K >= 288`, `TK = 4` for `K >= 144`, fallback `sf_kernel_1`).
- Stage: S15 (14 November 2026).
- What: `sf_kernel` previously ran 1 block per `k`, so all `K` blocks re-read `X[N, NC]` and `frac` through L1/L2 (`sf_kernel<16/8/4>` scaled linearly `900 / 455 / 233 us` on `NbCl5`). Now `TK` warps (`8` `k`-vectors per 256-thread block) share one SoA tile `s_X[NC][129]` (`float4` global loads) and `s_frac[3][129]` (`TILE = 128`), keeping `STACK:0` via `__launch_bounds__(TK * 32)` without a `minBlocks` cap.
- Status: DEFAULT (5060 Ti only).
- Measured (5060 Ti): `POLAR-1-M` `NbCl5` kernel avg `sf_kernel<16/8/4>` `899.9 / 454.9 / 232.8 -> 316.1 / 150.4 / 83.5 us`; fresh-plan ABBA vs `1e110f4`: `POLAR-1-M` `NbCl5` `27.0013 -> 24.9966 ms/step` (`b/a = 0.9258`), `NaCl` 216 `4.4061 -> 4.3599` (`0.9895`), `POLAR-1-S` `NaCl` 216 `1.9230 -> 1.8569` (`0.9657`), `POLAR-1-L` `NaCl` 216 `8.3614 -> 8.3058` (`0.9934`). `POLAR-1-S/M` crystals gates pass; `POLAR-1-L` exactness verified vs `1e110f4` via `cmp_libs.py` (`nacl216` `dF = 4.33e-7`, `nbcl5` `dF = 1.21e-3`; CPU float64 stress ref for `POLAR-1-L` `NbCl5` not re-run due to >6 min CPU autograd runtime).
- Sources: this file; commit `c24b6c4`.

<a id="pol-dot-fold"></a>
#### pol-dot-fold: SCF and electron-energy weights composed with `dot^T` at load
- Switch: `src/polar.cu`: `fold_dotT_kernel` (load time, double accumulation), `Impl::up_fold`, `Impl::fold` = compute capability 12.0 and, since S84, 8.0 (`LOUP_POLAR_FOLD=0` disables it, for testing the unfolded path; `=1` forces it on any GPU). Other GPUs load and run the unfolded weights and GEMMs as before; the 41 existing `polar.cu` kernels are SASS-identical to S48 on `sm_89`, `sm_90` and `sm_120` (the only device-code addition is the load-time kernel).
- Stage: S52 (14 November 2026).
- What: profiles of the small POLAR / MH-1 cells (S51) show the GEMMs dominating, with the own `sgemm64` at 55-60% of the FMA pipe. Each SCF step computed `mixed = pot Wpot + q Wq + fm Wnf` and then `Z = mixed dot^T`, with nothing between the two linear maps; the electron energy computed `qu = q le_Wq + bq`, then `Zq = qu le_dotq^T` (and `Zv` from `pot` alike). The weights are now composed once at load (`Wpot' = Wpot dot^T` per l block, `Wq'`, `Wnf' = Wnf dot^T`, `le_Wq'`, `le_Wv'`, and the biases `bq' = dot bq`, `bv'`), so the forward is `Z = pot Wpot' + q Wq' + fm Wnf'` (one C x C product per step and l instead of two) and the electron energy is `Zq = q le_Wq' + bq'` (a K = 8 / 16 product; its two C x C products are gone). The backward follows: `dfm += dZ Wnf'^T`, `dpot += dZ Wpot'^T`, `dq2 += dZ Wq'^T` (no `dmix` product), electron energy `dq0 += dZ le_Wq'^T`, `dpot += dZ le_Wv'^T`. `mixed`, `dmix`, `qu`, `vu` are not allocated on the folded path. The `dpot` / `dq2` contributions of every l stay on one lane each, in l order.
- Status: DEFAULT (5060 Ti; A100 since S84).
- S84 (16 November 2026, NHR Alex A100-SXM4-40GB, library s82 with `LOUP_POLAR_FOLD=1`, job `loup-s82a`; in-process A/B, 3 rounds in both orders, side 1 a second default engine within 0.6%): fold alone / with the own-SGEMM extensions (on by default on cc 8.0 without a GEMM cubin since S84, [a100-own-ext-nb-groups](#a100-own-ext-nb-groups)): POLAR-1-S NaCl216 `0.922` / `0.801`, POLAR-1-M NaCl216 `0.892` / `0.840`, POLAR-1-L NaCl216 `0.887` / `0.842`, POLAR-1-M NbCl5 `0.885` / `0.880` (one round). Crystal gates with both (`loup-s82g`, every row of every set passing): POLAR-1-S worst force / stress 0.47 / 0.72, POLAR-1-M 1.28 / 1.49, POLAR-1-L 1.20 / 0.61.
- S84c (17 November 2026, NHR Alex A100-SXM4-40GB node a0701, job 5012942 `loup-s84c`): library ABBA s81 -> s84 (the dot fold and, since long-range models load no tensor-core cubin, the own-SGEMM extensions) in separate processes, 2 rounds, fresh GEMM plans: POLAR-1-S NaCl216 `0.795` (`0.796` / `0.794`), POLAR-1-M `0.802` (`0.809` / `0.795`), POLAR-1-L `0.814` (`0.814` / `0.814`); the no-change control OFF23-S water216 on shared plans `1.001` (`1.018` / `0.983`, a tie). Faster in both orders: S82-S84 stay on cc 8.0.
- Measured (5060 Ti): `nsys` `POLAR-1-M` `NaCl216`: GEMM launches `165.6 -> 149.5` per step, GEMM kernel time `4416 -> 3832 us` per step (summed durations), all kernels `5243 -> 4676 us`. Fresh-plan ABBA, new / old. First build (fold for every GPU): `POLAR-1-S` `NaCl216` `1.519 -> 1.397 ms/step` (`0.920`), reversed `0.927`; `POLAR-1-M` `NaCl216` `3.566 -> 3.241` (`0.909`), reversed `0.909`; `POLAR-1-L` `NaCl216` `6.786 -> 6.005` (`0.885`), reversed `0.904`; `POLAR-1-M` `NbCl5` `24.39 -> 22.19` (`0.910`), reversed `0.906`. Final gated binary: `POLAR-1-M` `NaCl216` `3.461 -> 3.073` (`0.888`), reversed `0.922`; `NbCl5` `24.39 -> 22.11` (`0.906`), reversed `0.906`; `POLAR-1-S` `NaCl216` `1.511 -> 1.377` (`0.911`), reversed `0.914`; `POLAR-1-L` `NaCl216` `6.908 -> 6.122` (`0.886`), reversed `0.895`. `cmp_libs` against S48: NaCl `dF` `1e-6` (S / M / L), `POLAR-1-M` `NbCl5` `dF 1.8e-4` of `|F|max 26.8` (`pol-sf-tiled`, a different code change, recorded `1.2e-3` on this cell); the final binary's fold path against the first build `dF 4.9e-5` (`NbCl5`), `6.5e-7` (`POLAR-1-S` NaCl), and `LOUP_POLAR_FOLD=0` against S48 `dE 0`, `dF 1.1e-5` (`NbCl5`), `1.3e-6` (`POLAR-1-S` NaCl). The paths are not bit-identical across these builds; the cause was not isolated (each library tunes its own GEMM plans, which was not held fixed). Gates (crystals; `POLAR-1-L` with CPU references) pass on both paths of the installed binary: folded `POLAR-1-S` / `-M` / `-L` exit 0, `LOUP_POLAR_FOLD=0` 5 / 6 / 6 rows PASS. `pytest` 67 passed (installed binary).
- S55, follow-up (not built): `fm Wnf'_i` does not depend on the SCF state, so the `n_rec` products per l could run as one GEMM with `N = n_rec C` before the loop (and the backward `dfm += dZ_i Wnf'_i^T` as one with `K = n_rec C` after it). Standalone own-SGEMM harness, random data, two `N = 512` products against one `N = 1024` (us, two rounds): `M = 648` `2 x 37.0 -> 56.6 / 58.1` (`-22%`), `M = 1944` `2 x 84.5 -> 160` (`-5%`), `M = 5832` `2 x 235 -> 425` (`-10%`); `M = 216` unstable for `sgemm64` (`28.9` then `55.1`), `sgemm32` `26.7 / 28.3` against `2 x 19.7`. The l = 0 and l = 1 products run on separate GEMM lanes, so the critical-path proxy on `POLAR-1-M` `NaCl216` is the longer lane: `2 x 37.0 = 74` against `56.6` us, about 17 us or ~0.6% of the 3.07 ms step, before the cost of the layout change it needs (the two steps' `Z[l]` would be interleaved rows of one `N = 1024` output; the own GEMMs require a contiguous output, so either `inv_kernel`, `inv_bwd` and the `pot` / `q` products take a row stride, or a copy is paid). The backward shape (`N = 512`, `K = 1024`) was not measured. Not built.
- Sources: this file.

<a id="pol-bias-ln-fuse"></a>
#### pol-bias-ln-fuse: long-range pass launch trims (MLP bias inside the LayerNorm-SiLU forward; `q` copy + add as one kernel)
- Switch: `src/polar.cu` `bias_ln_silu_fwd_kernel` (replaces `ln_silu_fwd_kernel`), `mlp_fwd`: a hidden layer runs GEMM -> bias + LayerNorm + SiLU (one launch); the last layer keeps `add_bias_kernel`. `add8_to_kernel` (S86): the SCF step's `q_new` and the electron energy's `q_in`.
- Stage: S85, S86 (16 November 2026), 5060 Ti.
- What: `nsys` of `POLAR-1-M` `NaCl216` (S84 build): 324 kernels per step, 219 gaps, most of them 1-3 us between small kernels; `add_bias_kernel` 14.5 launches per step, 9.3 of them directly before `ln_silu_fwd_kernel`. The fused kernel adds the bias in its first pass over the row and stores the biased pre-activation in place (the backward reads it), so the arithmetic is the old one: the same float additions in the same order.
- Measured (library ABBA S84 -> S85 on shared GEMM plans, 3 rounds; first / second order): `POLAR-1-S` `NaCl216` `0.995` (`0.992` / `0.998`), `POLAR-1-M` `0.998` (`0.999` / `0.996`), `POLAR-1-L` `0.995` (`0.994` / `0.997`). Trajectories against S84 (300 Langevin + 300 NVE steps, `POLAR-1-M` `NaCl216`) differ by 8.7e-8 A, within the run-to-run spread of one build (S79: 3.0e-8 on MH-1 NaCl216, 2.5e-7 on OMAT-0 SrTiO3). Gates (crystals): `POLAR-1-S` 0.57 / 0.66, `POLAR-1-M` 2.43 / 0.95 against 2.61 / 1.06 for S84 in the same session (its `NaNbO3_c0` forced conv-variant force rows vary 2.1-2.6 between runs of either build), `POLAR-1-L` 1.50 / 0.93; `tests/test_families.py` POLAR cases pass.
- S86: the SCF step's `q_new = q_in + out[:8]` (a device copy of `q_in`, then `add8_kernel`) and the electron energy's `q_in(le) = q_fin + q_0` (a copy, then `axpy_kernel` with `a = 1`, a fused multiply-add of an exact product) each run as one `add8_to_kernel`: the same rounded sum, one graph node fewer per SCF step and per pass. Library ABBA S85 -> S86 on shared plans, 3 rounds: `POLAR-1-S` `NaCl216` `0.995` (`0.993` / `0.998`), `POLAR-1-M` `0.997` (`0.997` / `0.996`), `POLAR-1-L` `0.999` (`1.000` / `0.997`); trajectories against S85 differ by 8.7e-8 A (the run-to-run spread); gates `POLAR-1-S` 0.61 / 0.66, `POLAR-1-M` 2.52 / 0.94, `POLAR-1-L` 1.50 / 0.93; `pytest` 77 passed and the OMAT-0 / MH-1 / OFF23-S gates pass on the installed build.
- S87 falsifier (reverted): three more nodes per SCF reverse step folded away (the `dq` copy as a swap of the two buffers, the `dpot` memset inside `pot_bwd_kernel`, the `dout` copy inside `fukui_bwd_kernel`). Library ABBA S86 -> S87 on shared plans, 3 rounds: `POLAR-1-M` `NaCl216` `1.001` (`1.001` / `1.001`), `POLAR-1-S` `0.996`, `POLAR-1-L` `0.999`: a tie; gates passed (`POLAR-1-S` / `-M` / `-L` 0.58 / 0.69, 2.37 / 1.22, 1.47 / 0.73).
- A100 (17 November 2026, NHR Alex A100-SXM4-40GB node a0701). Library ABBA S84 -> S86 on shared GEMM plans, 3 rounds (job 5014323 `loup-s86c`): POLAR-1-S NaCl216 `0.989` (`0.988` / `0.989`), POLAR-1-M `0.988` (`0.979` / `0.997`), POLAR-1-L `1.011` (`1.018` / `1.005`): S and M faster, L slower in both orders. The job shared the node with `loup-s84c` and `loup-s86g` (on other GPUs). Crystal gates at S86 with the defaults (job 5014324 `loup-s86g`, library s86 = `9f8cac77`): 29 rows, none failing; worst force / stress POLAR-1-M 1.29 / 1.49 (18 rows, both forced conv variants included), POLAR-1-L 1.32 / 0.80 (6), POLAR-1-S 0.47 / 0.72 (5; NaNbO3_c0 left out as UNSTABLE).
- Status: DEFAULT. On cc 8.0 too: kept by the owner's decision (17 November 2026) despite POLAR-1-L `1.011` there.
- Sources: this file.

<a id="pol-tpo-fold"></a>
#### pol-tpo-fold: the update MLP's last layer composed with `tpo` at load
- Switch: `src/polar.cu` `Update::tpo_fold` (`P.fold` and an MLP with a hidden layer); `tpo_W_l` / `tpo_b_l` from `up_fold` (`fold_dotT_kernel`, double accumulation); `bcast_mul_kernel` / `bcast_mul_bwd_kernel` add `tpo_b_l` to `P_l`. `LOUP_POLAR_FOLD=0` runs the unfolded MLP and `tpo` products.
- Stage: S115 (18 November 2026), 5060 Ti. From the owner's review list of 17 November.
- What: each SCF update's MLP ends with an affine layer H -> C (H = 64 on S / M, 128 on L; C = 512) whose only consumer is `P_l = nl tpo_l^T` (C x C per l). Folded, `P_l = h (W tpo_l^T) + b tpo_l^T` from the last hidden activation h. The reverse sums `dP_l (W tpo_l^T)^T` into the gradient of h and starts the MLP reverse at that layer's LayerNorm-SiLU. The readout reads only `nw_0` and `nw_1`, so `P_2` and `nw_2` (POLAR-1-L) are no longer computed on either path; they had no consumer. The review counted 1.05 M / 1.97 M / 2.49 M multiply-adds per atom and force call removed on S / M / L.
- Measured (library ABBA HEAD `13d6337` -> S115 on shared GEMM plans, 3 rounds, first / second order): POLAR-1-S NaCl216 `0.944` (`0.943` / `0.945`), POLAR-1-M `0.957` (`0.948` / `0.966`), POLAR-1-L `0.976` (`0.979` / `0.974`); every round and order below 1.
- Results against HEAD (rattled NaCl216, one evaluate): folded path dE/atom 1.1-2.2e-5 meV, max dF 0.5-1.5e-6 eV/A, max dS 1.1-9.2e-9; the unfolded path, whose arithmetic is unchanged, differs by the same amounts (GEMM plans, atomics).
- Gates (crystals, folded / `LOUP_POLAR_FOLD=0`): POLAR-1-S 5 / 5 rows (worst force / stress 0.58 / 0.66, 0.62 / 0.74), POLAR-1-M 18 / 18 (2.83 / 1.20, 2.55 / 1.02), POLAR-1-L 6 / 6 with CPU references (1.95 / 1.07, 2.08 / 1.03). POLAR-1-M's worst row (NaNbO3_c0, default) over two further runs each: HEAD 2.28 and 2.85, S115 2.76 and 2.62, inside HEAD's run-to-run spread.
- Status: DEFAULT (5060 Ti; cc 8.0 shares `P.fold` but is not measured).
- Sources: this file.

<a id="pol-mono-channels"></a>
#### pol-mono-channels: the k-space passes on the live channels (POLAR-1-S)
- Switch: `src/polar.cu` `Impl::mono`, set in `PolarLR::load` when `LR.lmax` is 0 and the structural zeros below hold; `LOUP_POLAR_MONO=0` disables it. Kernels: `sf_kernel_tiled<NC, TK, NL>` / `sf_kernel_1<NC, NL>` (`launch_sf<8, 2>`, `<4, 1>`, `<16, 4>`: the NL live columns 4 j summed, the others written as 0), `feat_pass_kernel<true>` (raw features ch * 8 + {0, 4}), `grad_pass_kernel<1, false, true>` / `<2, true, true>` (monopoles and those feature gradients).
- Stage: S118 (18 November 2026), 5060 Ti. From the owner's second review list of 18 November.
- What: charges are `q[a][ch * 4 + m]` (m = 0 monopole, 1..3 dipole) and the raw k-space features `f[a][ch * 8 + 4 s + m]` (s the Gaussian width; m = 0 the potential, 1..3 the field). At lmax 0 (POLAR-1-S) the loader certifies: every source matrix, and every update readout's scalar rows and bias, is exactly zero on the dipole columns (at lmax 0 the readout reads only its scalar rows; the Fukui constraint and the SCF add change only the monopoles), so the dipoles stay exactly zero; and every pot row that reads a field feature is exactly zero in each update's Wpot and in le_Wv (the folded weights inherit the zero rows), so those features and their gradients reach only zero weights. The five transforms of a force call then sum 2 + 2 + 1 + 4 + 4 channels instead of 8 + 8 + 4 + 16 + 16, `feat_pass` 4 of 16 features, and `grad_pass` the monopoles and 4 of 16 feature gradients. The live sums are the same operations in the same order (the dropped terms were fma(0, x, y) = y); the dipoles' dq, consumed only through zero weights, is no longer updated there; the per-k kernels see the same inputs (dead columns written as 0, as their sums were). Cached bundles (`polar_zeros.py`, scratch): POLAR-1-S has exactly these zeros (Wpot / le_Wv rows 0, 1, 8, 9 nonzero, i.e. pot features 0 and 1 = raw features 0 and 4 per spin); POLAR-1-M / -L have no zero rows or columns and keep the full passes.
- Measured (5060 Ti; S116 -> S118 libraries, on shared plans, first / second order): POLAR-1-S NaCl216 `0.9477` (`0.9479` / `0.9474`, 3 rounds), NbCl5 (1,944 atoms) `0.8915` (`0.8917` / `0.8913`, 2 rounds). Before S118 the k-space kernels were ~11% (NaCl216) and 18.5% (NbCl5: `sf_kernel_tiled` 992, `grad_pass_kernel` 509, `feat_pass_kernel` 225 us of 9,753 us) of the MD step's kernel time (`nsys`).
- Results against HEAD (rattled cell, one evaluate; HEAD against itself in brackets): POLAR-1-S NaCl216 max dF 9.4e-7 (9.3e-7) eV/A, NbCl5 4.8e-7 (4.8e-7), dE the same; `LOUP_POLAR_MONO=0` alike; POLAR-1-M (not eligible) 2.7e-7 (1.7e-7).
- Gates: POLAR-1-S crystals 5 / 5 on both GEMM paths (default and `LOUP_POLAR_FOLD=0`).
- Status: DEFAULT (5060 Ti only; the code is GPU-independent).
- Sources: this file.

<a id="pol-zero-blocks"></a>
#### pol-zero-blocks: exactly-zero POLAR weight blocks skipped (POLAR-1-L)
- Switch: `src/polar.cu` `Update::zpot[l]`, `Update::zq[l]` (block l of `Wpot` / `Wq` exactly zero) and `Impl::le_lq`, `Impl::le_lv` (the highest l whose `le_Wq` / `le_Wv` block is nonzero), certified in `PolarLR::load` from the bundle's float32 weights before the fold (folding keeps a zero block: `W_l dot_l^T = 0`); `LOUP_POLAR_ZBLK=0` disables the skips.
- Stage: S123 (18 November 2026), 5060 Ti and RTX A4000 (`coraline`). From the owner's review list of 18 November (idea 2: skip zero and repeated local-electron coefficients).
- What: the CPU survey (POLAR-1-M and -L, `le_Wq` / `le_Wv` and every update's `Wq` / `Wpot`) found the l = 0 blocks reading scalar inputs only, the l = 1 blocks delta-structured (one vector per triplet) and the l = 2 blocks (POLAR-1-L) exactly zero. The SCF forward skips the zero blocks' pot and q GEMMs (the first GEMM that runs, at worst the `fm` product, takes beta 0), the reverse skips their `dpot` / `dq2` GEMMs; the electron energy forms `Zq_l` / `Zv_l` only up to `le_lq` / `le_lv`, and the inv kernels and their reverse stop there. The delta-structured l = 1 blocks are not exploited (see "Open or untried").
- Measured: `nsys` per MD step, POLAR-1-L NaCl216 (S122 -> S123): GEMM launches 233.6 -> 221.4, GEMM time 8.90 -> 8.59 ms (summed over lanes), inv kernels 112 -> 72 us. Library ABBA on shared plans (first / second order): 5060 Ti `0.9767` (`0.9771` / `0.9764`, 3 rounds), with `LOUP_POLAR_FOLD=0` `0.9480` (`0.9478` / `0.9481`, 2 rounds); RTX A4000 (sm_86, where the unfolded GEMMs are the default) `0.9578` (`0.9582` / `0.9574`, 3 rounds; HEAD -> S122-S124, the other changes inactive for POLAR there).
- Results (rattled cell, one evaluate, against S122; S122 against itself in brackets): POLAR-1-L NaCl216 max dF 6.8e-7 (1.6e-7) eV/A of |F|max 0.63, `LOUP_POLAR_FOLD=0` 7.3e-7, `LOUP_POLAR_ZBLK=0` 6.8e-7; A4000 1.6e-7 (1.7e-7).
- Gates (final library, CPU references): POLAR-1-L crystals 6 / 6 folded (worst force / stress ratios 2.17 / 1.42, NbCl5_c1 / NaNbO3_c0) and 6 / 6 with `LOUP_POLAR_FOLD=0` (1.72 / 1.26).
- Other GPUs: RTX 4000 Ada (sm_89, `murphy`, HEAD -> S122-S124): POLAR-1-L NaCl216 `0.9643` (`0.9698` / `0.9589`); results max dF 1.5e-7 (its own spread 1.2e-7).
- Status: DEFAULT (5060 Ti, A4000 and RTX 4000 Ada; the code is GPU-independent).
- Sources: this file.

<a id="pol-ro-scalar"></a>
#### pol-ro-scalar: the scalar-only update readout (POLAR-1-S)
- Switch: `src/polar.cu` `ro_fwd_kernel` / `ro_bwd_kernel` with `has_v = 0` (lmax 0), and the readout GEMMs' widths in `PolarLR::record` (`lm >= 1 ? 64 : 32`).
- Stage: S124 (18 November 2026), 5060 Ti and RTX A4000 (`coraline`). From the owner's review list of 18 November (idea 3).
- What: without vectors both gates multiply zeros, so the readout's scalar path runs alone: `s0`'s gate half is neither computed (the forward GEMM writes N = 32 of 64 columns, ldc 64) nor read, `smid`'s gate half and `vmid` are neither written nor read, and `ds0`'s gate half is not written (the reverse GEMM reads K = 32). The kept sums are the old ones minus exact zero terms.
- Measured: readout kernels 38.0 -> 16.3 us per MD step (POLAR-1-S NaCl216, `nsys`, one run each). Library ABBA on shared plans, S122 -> S123 + S124 (first / second order): 5060 Ti NaCl216 `0.9708` (`0.9705` / `0.9712`, 3 rounds), NbCl5 `0.9787` (`0.9818` / `0.9755`, 2 rounds), `LOUP_POLAR_FOLD=0` NaCl216 `0.9842` (`0.9830` / `0.9854`); RTX A4000 NaCl216 `0.9763` (`0.9777` / `0.9749`), NbCl5 `0.9830` (`0.9798` / `0.9862`).
- Results (against S122; S122 against itself in brackets): POLAR-1-S NaCl216 max dF 1.1e-6 (3.7e-8) eV/A of |F|max 0.56 (the readout GEMMs' new shapes change their kernels), `LOUP_POLAR_FOLD=0` 9.9e-7; NbCl5 1.7e-4 (2.8e-4) of |F|max 137; A4000 NaCl216 1.3e-6 (1.2e-6).
- Gates (final library): POLAR-1-S crystals 5 / 5 folded (0.62 / 0.62) and 5 / 5 with `LOUP_POLAR_FOLD=0` (0.56 / 0.65).
- Other GPUs: RTX 4000 Ada (sm_89, `murphy`): POLAR-1-S NaCl216 `0.9903` (`0.9898` / `0.9909`), NbCl5 `0.9952` (`1.0019` / `0.9885`, a tie); results max dF 4.6e-7 (its own spread 7.6e-9; the readout GEMMs' new shapes).
- Status: DEFAULT (5060 Ti, A4000 and RTX 4000 Ada).
- Sources: this file.

<a id="pol-hidden-fold-l2"></a>
#### pol-hidden-fold-l2: POLAR-1-L's degree-2 hidden chain folded into the long-range mixer and the next linear_up
- Switch: `src/generic.cu` `GenericModel::setup_lr_fold` (end of `load`, after `setup_chain_fold`); `GenericLayer::hfold[l]`, `x_extra[l]`, `sc_extra[l]`; `alloc_system` aliases `hout[l]` to `y[l]` and `dhout[l]` to `dy[l]` (in the zero slab); `record` runs no `W_p` / skip product for a folded degree in either direction and adds the extra `y_src W` terms; `src/polar.cu` `PolarLR::set_hidden_fold`, `le_lmax`. Compute capability 12.0 by default; `LOUP_POLAR_HFOLD=0` disables it, `1` / `2` / `3` (bit l - 1 = degree l) choose the folded degrees on any GPU.
- Stage: S136 (19 November 2026), from the dense-model research list (`loupmd-speed-research-20261118`, POLAR ranks 4 and 5), built in a separate worktree and integrated on top of S135.
- What: S57's chain fold excludes the long-range models because each layer's `hout` also feeds the multipole source and the feature mixer, both linear. For POLAR-1-L's degree 2 every consumer is linear (the next `linear_up` and skip, the mixer, the source), the source and electron-energy l = 2 blocks are exactly zero, and layer 0 has no skip into l = 2. So `hout_u[2] = sum_{v <= u} y_v[2] G_{v,u}` is never formed, and the consumers take weights composed in double and rounded once: the mixers `W_p_v B_v` (`B_2 = M_2`, `B_1 = M_1 + W_sc_2 B_2`, `B_0 = M_0 + W_sc_1 B_1`); `x_1 = y_0 (W_p_0 W_up_1)` and `x_2 = y_1 (W_p_1 W_up_2) + y_0 (W_p_0 W_sc_1 W_up_2)`; the composed sources, re-certified zero in float32 and skipped. The reverse accumulates the mixer, source, `dx W_up'^T` and extra-term gradients straight into `dy_v[2]`. Per force call each direction goes from 8 square, 2 thin and 3 zero-source GEMMs to 3 square and 3 thin: 14 launches fewer, 5.43 GFLOP less at 216 atoms. Guards: every layer's degree l is `LR.C` wide, the chain has no per-species skip and no `ro_folded` layer, the last layer is left out when the electron energy reads its degree l; under `LOUP_POLAR_ZBLK=0` nothing is certified zero and degree 2 folds layers 0-1 only.
- Measured (5060 Ti): `nsys` per MD step, POLAR-1-L NaCl216, against `HFOLD=0`: GEMM launches 216.3 -> 208.2, GEMM time 8.66 -> 7.84 ms (summed over lanes), `sgemm128` launches 35.5 -> 25.4. Library ABBA on shared plans, 3 rounds, on `c3858a4`: degree 2 alone `0.9234` (`0.9218` / `0.9250`, 5.48 -> 5.05 ms), with degree 1 `0.9143` (`0.9158` / `0.9129`, 5.48 -> 5.01 ms). Integrated on top of S135 (both folds and the zero-source skips): `0.9155` (`0.9137` / `0.9172`, 2 rounds, 5.41 -> 4.96 ms). Peak device memory 754 -> 726 MiB.
- Results (rattled cell, one evaluate, against `c3858a4`; `c3858a4` against itself in brackets): POLAR-1-L NaCl216 max dF 7.2e-7 (7.1e-7) eV/A of |F|max 0.63; both folds 6.2e-7, `LOUP_POLAR_FOLD=0` 5.9e-7, `LOUP_POLAR_ZBLK=0` 6.1e-7. Integrated, against S135: 5.7e-7 (6.6e-7), `LOUP_POLAR_HFOLD=0` 4.9e-7.
- Gates (CPU references, on `c3858a4` + S136): POLAR-1-L crystals 6 / 6 on every path, worst force / stress ratio default 2.03 / 0.90, `LOUP_POLAR_FOLD=0` 1.83 / 0.64, `LOUP_POLAR_ZBLK=0` 2.29 / 0.77, `LOUP_POLAR_HFOLD=0` 2.05 / 1.26; POLAR-1-S control 5 / 5 (0.69 / 0.65).
- Gates (the final S129-S137 library, its own plans): POLAR-1-L crystals 6 / 6, default 2.10 / 0.71, `LOUP_POLAR_HFOLD=0` 2.20 / 1.27 (CPU references).
- Other GPUs: RTX 4000 Ada (sm_89), the S129-S136 library with `LOUP_POLAR_HFOLD=3` against `=0`: POLAR-1-L NaCl216 `0.9306` (`0.9361` / `0.9251`, 8.17 -> 7.60 ms); results against S129 (S129 against itself) 3.2e-7 (1.4e-7) eV/A.
- Status: DEFAULT (5060 Ti; off by default elsewhere, `LOUP_POLAR_HFOLD=3` on any GPU).
- Sources: this file.

<a id="pol-hidden-fold-l1"></a>
#### pol-hidden-fold-l1: the first hidden vector of POLAR-1-M / -L folded into its four consumers
- Switch: as [pol-hidden-fold-l2](#pol-hidden-fold-l2); bit 1 of `LOUP_POLAR_HFOLD` is degree 1, on by default on `sm_120`.
- Stage: S136 (19 November 2026).
- What: `h_0[1] = y_0[1] W_p_0[1]`, and layer 0 has no vector skip. `W_p_0[1]` is composed into layer 1's `W_up_1` and `W_sc_1`, `LR.mix_0_1` and each of the three m blocks of `LR.src_0`'s l = 1 rows (the k = 1 case of the same code). The forward and transpose `3N x 512 x 512` products go, with layer 0's `hout[1]` / `dhout[1]` buffers; no GEMM is added.
- Measured (5060 Ti): `nsys` per MD step, POLAR-1-M NbCl5 GEMM launches 154.1 -> 151.9, GEMM time 17.88 -> 17.30 ms; NaCl216 146.1 -> 144.1, 3.95 -> 3.88 ms. Library ABBA on shared plans, on `c3858a4`: POLAR-1-M NbCl5 `0.9807` (`0.9807` / `0.9807`, 2 rounds, 21.05 -> 20.64 ms), NaCl216 `0.9766` (`0.9752` / `0.9779`, 3 rounds); POLAR-1-L NaCl216 with degree 1 only `0.9766` (`0.9759` / `0.9774`, 3 rounds). Integrated on top of S135: POLAR-1-M NbCl5 `0.9812` (`0.9813` / `0.9812`, 2 rounds). NbCl5 peak memory -24 MiB.
- Results (against `c3858a4`; its own spread in brackets): POLAR-1-M NbCl5 max dF 2.0e-4 (2.7e-4) eV/A of |F|max 14.2 (the self-consistent charges' spread), NaCl216 6.9e-7 (1.7e-7) of 0.51; `LOUP_POLAR_FOLD=0` 1.2e-4 / 7.3e-7, `LOUP_POLAR_ZBLK=0` 8.5e-5 / 6.6e-7. Integrated, against S135: NbCl5 9.9e-5 (4.2e-5), NaCl216 7.6e-7 (1.7e-7).
- Gates (on `c3858a4` + S136): POLAR-1-M crystals 18 / 18 on every path, worst force / stress ratios (NaNbO3_c0, within S115's 2.28-2.85 spread) default 2.29 / 1.05, `LOUP_POLAR_FOLD=0` 2.27 / 1.09, `LOUP_POLAR_ZBLK=0` 2.22 / 1.11, `LOUP_POLAR_HFOLD=0` 2.42 / 1.07; POLAR-1-L as above.
- Gates (the final S129-S137 library, its own plans): POLAR-1-M crystals 18 / 18, default 2.51 / 1.16, `LOUP_POLAR_HFOLD=0` 2.55 / 1.10, with the S137 gate fusions off 2.68 / 1.07 (NaNbO3_c0 each time; see [gen-gate-bwd-epilogue](#gen-gate-bwd-epilogue) for that row's plan sensitivity).
- Other GPUs: RTX 4000 Ada (sm_89), `LOUP_POLAR_HFOLD=1` against `=0`: POLAR-1-M NbCl5 `0.9819` (`0.9798` / `0.9841`, 30.01 -> 29.47 ms); results with both degrees forced on, against S129: 1.4e-4 eV/A (S129 against itself 3.8e-5) of |F|max 14.2.
- Status: DEFAULT (5060 Ti; off by default elsewhere, `LOUP_POLAR_HFOLD` on any GPU).
- Sources: this file.

<a id="pol-zero-sources"></a>
#### pol-zero-sources: exactly-zero long-range source blocks skipped
- Switch: `src/polar.cu` `PolarLR::Impl::src_zero[t][l]` (`src_block_zero`), certified in `PolarLR::load` from the bundle's float32 sources and again on a hidden fold's composed block; `record` skips the forward `qsrc` GEMM and the reverse `dq2 src^T` GEMM of a zero block, the first source GEMM that runs takes beta 0 (none: `qsrc` is memset). `LOUP_POLAR_ZBLK=0` disables it, as for [pol-zero-blocks](#pol-zero-blocks).
- Stage: S136 (19 November 2026).
- What: POLAR-1-L's l = 2 rows of every `LR.src_t` are exactly zero: 3 forward and 3 reverse `N x 8 x 5C` GEMMs per force call.
- Measured (5060 Ti): `nsys` per MD step, POLAR-1-L NaCl216: GEMM launches 222.4 -> 216.3, split-K reductions 46.7 -> 36.6. Library ABBA with the hidden fold off (`LOUP_POLAR_HFOLD=0`): `0.9855` (`0.9852` / `0.9858`, 2 rounds).
- Gates: POLAR-1-L 6 / 6 with `LOUP_POLAR_HFOLD=0` (2.05 / 1.26).
- Status: DEFAULT (GPU-independent code).
- Sources: this file.

<a id="pol-sf-split-fold"></a>
#### pol-sf-split-fold: the structure factor's warp fold split
- Switch: `src/warp_fold.cuh` (`warp_fold_split<V>`, `kWarpFoldShift<V>`), used by `sf_kernel_tiled` and `sf_kernel_1` (`src/polar.cu`). No switch: the result is bitwise the old fold's.
- Stage: S141 (19 November 2026).
- What: each lane holds `2 NL` FP64 partials (cos and sin per channel) that the plain fold reduced with five xor shuffles and adds per value. The split fold pairs lanes at each xor step so that one lane keeps the lower half of the values and the other the upper half, each adding its partner's copy: after `SH = log2(2 NL)` steps every lane holds one value's partial sum over its lane group, and the remaining steps fold that one value. Each sum is formed in the same tree order as the plain fold, so the bits are the same (`tests/fold_check.cu`: 320,000 sums at V = 16 and 640,000 at V = 32, 0 differing); FP64 adds per warp fall from `5 x 32 x V` to `32 x (V - 1 + 5 - SH)` (and the shuffles likewise).
- Measured (5060 Ti, MD a b b a on the base library's plans): POLAR-1-M NbCl5 19.626 / 19.215 / 19.232 / 19.665 ms (`0.979`), NaCl216 2.650 / 2.624 / 2.615 / 2.645 (`0.989`); POLAR-1-L NaCl216 4.855 / 4.814 / 4.798 / 4.812 (`0.994`). Develop library against `d6e97b7` on shared plans: POLAR-1-M NbCl5 19.663 / 19.254 / 19.259 / 19.685 (`0.979`); forces max dF 4.1e-5 eV/A of |F|max 14.2 (own spreads 3.6e-6 / 4.2e-6). POLAR-1-S NbCl5 could not be timed: the cell heats to 700-1,000 K with either library and one split-fold run diverged (a bit-exact fold cannot cause it; not rerun).
- Results: three processes per library on one plan file, POLAR-1-M NbCl5: base against base max dF up to 7.1e-5 eV/A, split against split 5.9e-5, across the libraries 7.8e-5 (the GEMM picks of separate processes).
- Gates (5060 Ti, the develop library, one GEMM plan set per model): POLAR-1-M crystals 18 / 18 (worst force / stress ratio 2.23 / 1.38), POLAR-1-S 5 / 5 (0.62 / 0.63; NaNbO3_c0 skipped as UNSTABLE), POLAR-1-L 6 / 6 (1.66 / 0.75, cached references), MP-0 medium oxide 18 / 18 (0.80 / 0.46) and 18 / 18 with `LOUP_CONV_PRUNE=0 LOUP_SENDER_BWD=0 LOUP_LIN_COMPACT=0 LOUP_CHAIN_FOLD=0` (0.68 / 0.33), OMAT-0 medium generic oxide 18 / 18 (2.03 / 1.81). pytest 77 / 77 (`tests/`, the develop library).
- Other GPUs: not measured.
- Status: DEFAULT (bit-exact; timed on the 5060 Ti only).
- Sources: this file.

### Measurements without a switch

<a id="meas-stage-spans"></a>
#### meas-stage-spans: stage spans and top kernels
- What: nsys with `--cuda-graph-trace=node`, 100 Langevin steps after 50 warm-up; medians over non-rebuild steps; both GPUs.
- Measured: 5060 Ti `SrTiO3` step span 8,232 us: `w'` 2,961, spline 1,928, GEMM groups 1,825 (22%), i0 backward 524. Ada 9,268 us.
- Sources: [§2][s2].

<a id="meas-ncu"></a>
#### meas-ncu: Nsight Compute facts (5060 Ti)
- Measured: `w'` 3.01 ms, 63% occupancy, issue slots 80% busy (issue-bound, `not_selected` dominant), 760 M instructions, L2 5.3 GB; spline R1 2.04 ms, L2 83%, L1 hit 5%; R4 L1 hit 36%.
- Sources: [§2][s2].

<a id="meas-size-scaling"></a>
#### meas-size-scaling: system-size scaling
- Measured (5060 Ti, `SrTiO3` n^3, us per atom-step): 135 atoms 3.00, 320 atoms 2.18, 1,080 1.73, 5,000 1.66-1.68, 20,480 1.69-1.71, 40,000 1.71-1.72.
- Sources: [§1][s1].

<a id="meas-nve-drift"></a>
#### meas-nve-drift: NVE energy drift
- Measured: `SrTiO3` 10^3, 1 fs, 300 K, 1 ps after 200 Langevin steps: -0.00011 meV/atom/ps (5060 Ti), -0.00012 (Ada).
- Sources: [§1][s1].

<a id="meas-ada-counters"></a>
#### meas-ada-counters: Ada performance counters
- Status: BLOCKED (`ERR_NVGPUCTRPERM` on `leeloo`; needs `NVreg_RestrictProfilingToAdminUsers=0`).
- Why it matters: `w'` is 9% slower on the Ada than on the 5060 Ti although the Ada has 33% more SMs; the spline gained 10% from L1 slab sharing there, so the Ada looks L2-sensitive.
- Sources: [§4.1 #2][s41].

<a id="meas-family-bench"></a>
#### meas-family-bench: family benchmarks against FastMACE
- What: `python/bench_family.py` (Langevin 300 K, 1 fs, skin 0.5 A, median of 6 x 256 steps) for every family on both GPUs.
- Measured: see [§5][s5]. Against FastMACE's raw A/B lines of 11 November (same 3x3x3 cells) LoupMD's POLAR-1 is level to 20% slower (S 1.13, M 1.16 / 1.20, L 1.03 on the 5060 Ti; M 1.01 / 1.07 on the Ada). MH-1 NaCl 216 atoms 2.33 ms against FastMACE's documented 2.65-2.90 ms (5060 Ti, `matpes_r2scan`).
- Correction: an earlier version of the status table compared with FastMACE's October baseline (`SPEC.md` 3.3) and made LoupMD's POLAR-1 look 1.5-1.9x faster; that comparison was wrong.
- Sources: [§5][s5].

<a id="meas-plan-variance"></a>
#### meas-plan-variance: GEMM plan choice between builds
- What: the plan cache file is keyed by a hash of the whole library, so every build tunes its own plans; winners within 3% of the runner-up are re-timed in each process. On GEMM-bound small POLAR cells the plans one build pins can differ from another's by more than the code change under test.
- Measured (5060 Ti, S8 against S7): POLAR-1-S NaCl 216 1.019 and POLAR-1-M NaCl 216 1.013 with each build's existing plans; after moving all plan files aside 0.998 / 1.006 (S) and 0.969 (M). nsys of one POLAR-1-S evaluate: every non-GEMM kernel identical, one shape at 80 us (`sgemm128`, S7's plan) against 54 us (cuBLAS, S8's).
- Why it matters: A/B rows of GEMM-bound cells need fresh plans on both sides; and a tuner that times candidates inside the captured graph (rather than isolated) could recover the spread for users. Not built.
- S51, forced alternatives inside the captured graph (5060 Ti, `POLAR-1-M` `NaCl216`; GEMM kernels are 73-84% of the summed `nsys` kernel durations on the small POLAR / MH-1 cells, a sum that overlapping side-stream launches inflate, not a share of wall time). Baseline: one fresh tuning with `LOUP_DEBUG_GEMM`, every own-kernel pick of the log pinned into the plan file (61 shapes; cuBLAS picks that tied stay re-timed); variants force one shape group (all its `transB` / `beta` keys) to a candidate the isolated tuner lost with, full-step ABBA with one library and two plan directories (b/a = forced / tuned): M=648 N=512 K=512 `sgemm64` -> `sgemm32` `1.0852`, M=216 N=2048 K=512 -> `sgemm64` `1.0186`, M=1080 N=512 K=512 (pinned `sgemm128` / `sgemm64` near-tie) both -> `sgemm128` `0.9753`, both -> `sgemm64` `0.9892`. Earlier variants that changed two of four keys: M=648 -> `sgemm32` `1.0464`, -> `sgemm128` `1.0276`; M=1512 -> `sgemm128` `1.0113`; M=216 N=512 -> `sgemm32` `1.0132`. The M=1080 results were provisional (one ABBA each); repeated after S52 with a fresh pinned set (same mixed pair `sgemm128` / `sgemm64`), both orders, forced / tuned: both -> `sgemm128` `1.0439` and `0.996`, both -> `sgemm64` `1.0061` and `1.016`. No win in both orders, so the provisional result was noise; the `sgemm128` pair also shows a paired ratio moving by ~4% between runs. Every forced alternative lost or tied. Forcing other cuBLAS algorithms was not tried. In-graph tuning not built. `ncu` of the same `sgemm64` launches (serialised): 101 registers, 4 blocks per SM (16 warps), SM active 80-87% (M=648: 88 blocks for 144 slots), issue active 65-70%, FMA pipe 55-60%, all stall reasons below 1.6 per issue.
- Sources: this file.

<a id="meas-temperature-cost"></a>
#### meas-temperature-cost: what a thermalised configuration costs, per kernel
- What: S108 / S109 search for work that grows with temperature. `SrTiO3` 10x10x10 (5,000 atoms), a configuration at rest against ones after Langevin equilibration to 160 K and 296.5 K, `ncu` per kernel (5060 Ti, default variants unless named).
- Measured:
  - Force pass 7.46-7.52 ms at rest, 8.06-8.12 ms at 160 K. Edges within 6 A change by only +0.4%, so the work is the same.
  - `spline_forward_inter1` (R5): 1.58 -> 1.79 ms, L1 hit 78.7% -> 48.9%, L2 throughput 28.6% -> 59.7%. `w'`: L1 hit 32% -> 8%.
  - `tabled_outer_sum0_forward`: 217 -> 250 us, L1 hit 85% -> 50%. `tabled_outer_sum0_backward`: 497 -> 552 us, L1 hit 64% -> 29%.
  - `sc0_forward` 114-116 us, `sc0_backward` 201-227 us, `sc1_fused` 206-214 us at both temperatures: DRAM-bound (82-91% of DRAM throughput).
  - The cause is the spread of each receiver's edges over table slabs (0.30 distinct slabs per edge at rest, 0.75 at 300 K); see [s108-wide-table](#s108-wide-table) for what wider intervals would recover and [spl-receiver-order](#spl-receiver-order) for why the order of receivers does not.
- Sources: this file.

<a id="meas-conv-ablation-bounds"></a>
#### meas-conv-ablation-bounds: what table reads, atomics and angular arithmetic cost the conv and layer-0 kernels
- What: upper bounds for ideas that remove one kind of work, from timing-only libraries (their forces are wrong) that remove it outright, each against its base library (S133 for the conv ablations, S136 for layer 0): every forward conv reads one packed-table row (`s_tq = 0`, pairing decisions unchanged); every backward conv reads one row; the backward convs' sender-gradient atomics skipped behind a test that never holds (the values are still computed); `first_fwd` reads one table row; `first_fwd`'s 16-term angular update cut to one term; `first_bwd_edge` reads one table row. Table and layer-0 variants on a fixed rattled cell (nsys over the whole process, 20 + 16 force calls with a 1e-4 A jitter per call, per-instance medians); the atomics variant in MD (64 steps, its forces stay usable).
- Measured (5060 Ti, median us per force call; MD rows us per step):
  - OMAT-0 medium generic SrTiO3 (5,000 atoms): `gconv_fwd_L1` 1,810 -> 1,342 with free table reads (-26%); `gconv_bwd_L1` 2,740 -> 2,593 with free table reads (-5%), 3,086 -> 2,927 per step without sender atomics (-5%); `first_fwd` 234 -> 219 free table (-6%), -> 232 with the angular update cut to one term (-1%); `first_bwd_edge` 497 -> 453 free table (-9%).
  - MP-0 medium SrTiO3: `gconv_fwd_L1s` 683 -> 407 free table (-40%); `gconv_bwd_L1s` 1,023 -> 944 free table (-8%), 1,105 -> 871 per step without atomics (-21%); `first_fwd` 232 -> 218 (-6%) / 227 (-2%); `first_bwd_edge` 461 -> 425 (-8%).
  - The MD runs of the table variants blew up (a rebuild every step, 42-50 ms per step), which is why they were redone on the fixed cell; repeated `evaluate` calls on identical positions are answered from the cache, hence the jitter.
- Reading: the forward convs are bound by their table traffic (the radial-row cache's lever); the backward convs and layer 0 are not; the layer-0 forward is not bound by its angular arithmetic, so tensor cores cannot speed it up.
- Sources: this file (`.tmp_o` scripts, not kept).

<a id="meas-conv-bwd-algebra-bound"></a>
#### meas-conv-bwd-algebra-bound: what a bond-frame interaction-1 backward could save
- Switch: none. A timing-only lab build (`LOUP_LAB_BWD_STUB=1` in `emit_conv_bwd_lp`) kept every load, the staged adjoint `s_q` and the packed-table decode (w, dw) of `gconv_bwd_L1`, and cut each path's contractions to three or four FMAs (wrong forces).
- Stage: S141 (19 November 2026), the owner's bond-frame (SO(2)) backward proposal.
- Measured (5060 Ti, OMAT-0 medium generic SrTiO3 5,000 atoms, `nsys`, 16 force calls on fixed positions after 20 warm-up calls, same plans): `gconv_bwd_L1<1, 128, 1>` 2,738.5 -> 2,286.7 us per call (-451.8 us, -16.5%); all kernels 7,804.8 -> 7,421.2 us. An MD-based first try was discarded: the stub's forces blew the run up (16 rebuilds).
- Reading: a bond-frame rewrite changes only the per-path algebra, so 452 us (5.8% of the kernel time) bounds it. The late pull-back already evaluates the bond-frame projections it would need: `h = q . n` (m = 0) and `v = Q n` (m = +-1) per path and channel; a rotated form must first rotate each path's receiver adjoint into the edge frame (per edge, since the frame changes per edge), which costs more FMAs than those contractions save. Not built.
- Status: MEASUREMENT.
- Sources: this file.

<a id="meas-radial-precision-screens"></a>
#### meas-radial-precision-screens: lower-precision and factorised radial weights
- Switch: none. CPU screen: torch MACE OMAT-0 medium in float64 with the radial weights perturbed (straight-through: forward value rounded, gradient of the exact expression, so only the forward error is carried; a necessary condition), against the gate's rule on rattled SrTiO3 cells; tensor-core rates with torch matmul on the 5060 Ti.
- Stage: S141 (19 November 2026), the owner's idea lists (tensor-core radial synthesis, HFMA2 outer shell, Chebyshev factorisation).
- Measured: dense matmul (5060 Ti): FP32 17.1, TF32 25.2, FP16 / BF16 49-50 TFLOP/s. Radial MLP's last layer `w = h W` with h and W rounded to 11 bits (FP16 / TF32): force error 28-54x the float32 model's, 8 bits (BF16) 360-1,130x; three products of 11-bit hi / lo parts pass, but cost three products at ~49 TFLOP/s, no faster than the SIMT path that already won this contraction. FP16 weights for edges beyond r_split: 5.0-5.5 A pass (0.5-0.9x), 4.5 A fails (3.6x; 4.7x with each edge's tensor-product output rounded too); the saving would be ~13-16% of the table traffic of edges past 5.5 A, where the 4-byte far-edge tables (T2) already lost 1-3%. Chebyshev outer-shell factorisation: even 24 terms fit each column only to ~1e-3 of its peak (the packed tables' bound is 5e-4); forces 4-14x the float32 error at K = 24, 100-10,000x at K = 4-6.
- Status: MEASUREMENT (every direction closed or below its expected gain).
- Sources: this file.

<a id="meas-sgemm-reuse-pair-cutoff"></a>
#### meas-sgemm-reuse-pair-cutoff: `sgemm128` operand reuse; per-pair effective cutoff
- Switch: none. Offline: `cuobjdump -sass` of the `sm_120` objects; torch screen of the radial weights near the cutoff.
- Stage: S141 (19 November 2026), the owner's idea lists (SASS `.reuse` patching, per-pair `r_eff`).
- Measured: `sgemm128` variants average 2.33-2.47 register-file operand reads per FFMA against a floor of 2.0, so a `.reuse` patcher could save at most ~15% of operand reads, and only where bank conflicts stall. OMAT-0 medium: the radial weights fall below 1e-5 of their peak only above ~5.99 A, so a per-pair effective cutoff drops 0.03-0.13% of the edges; MP-0 1.1-2.4%.
- Status: MEASUREMENT (neither built).
- Sources: this file.

<a id="meas-degree-channel-shell-screens"></a>
#### meas-degree-channel-shell-screens: FP16 degree blocks, per-path cutoffs, shell cubics, FP16 channels
- Switch: none. CPU screens (`.tmp_o/lab_e12.py`, `lab_f12.py`, not kept): torch MACE OMAT-0 medium in float64 on two rattled SrTiO3 4x4x4 cells (320 atoms, rattle 0.08 / 0.20 A), against the gate's rule. FP16 is IEEE half (range and subnormals), straight-through (forward rounded, gradient exact) and accumulated exactly: a necessary condition. The cutoff and shell variants change value and gradient, as the kernels would.
- Stage: S141 (19 November 2026), the owner's third and fourth idea lists.
- Measured (force error over the float32 model's, cells 0.08 / 0.20): (1) the l = 3 blocks of every interaction's `linear` (inputs and weights with the path weight folded; largest operand 47, within FP16's range) 4.9x / 3.2x; l = 2 and 3 7.9x / 7.6x (stress 4.2x on the first cell). (2) l_y = 3 radial weights zeroed beyond r3 in both layers: 1,500x (4.0 A), 469x (4.5), 200x (5.0), 167x (5.5) on the first cell, 118-603x on the second; layer 1 alone at 5.5 A 56x / 106x; l_y = 2 and 3 up to 3,316x. Largest column-relative weight beyond r, layer 1, r = 5.0 / 5.5 / 5.75 / 5.9 A: l_y = 0 0.61 / 0.30 / 0.055 / 0.0038, l_y = 3 0.79 / 0.40 / 0.081 / 0.0057: the high-degree paths do not decay first. (3) One least-squares cubic per (pair, coordination shell of ideal SrTiO3; 24 pair shells) over r_s +- h: fit error 5.6e-3 (h 0.1), 1.8e-2 (0.15, 0.2) of the column's largest value; forces 862x / 108x (h 0.1) to 6,507x / 1,139x (0.2); 63 / 82 / 92% of the edges inside the windows at rattle 0.08, 28 / 41 / 52% at 0.20. (4) Layer 1's conv channels in FP16 (radial weights and each edge's output), the least sensitive first by sum over edges of |w dE/dw| (min / median / max 0.008 / 0.049 / 1 of the largest): 8 channels 1.4x / 4.3x, 32 4.8x / 6.0x, 64 7.8x / 6.5x, all 128 29x / 43x; 32 in random order 24.8x / 6.3x; 32 in both layers 22x / 43x.
- Status: MEASUREMENT (all four directions closed).
- Sources: this file.

<a id="meas-tc-overlap-ozaki-locality"></a>
#### meas-tc-overlap-ozaki-locality: tensor rates, pipe overlap, Ozaki-I accuracy, sender locality, degree census
- Switch: none. Lab scripts (`.tmp_o/lab_g.py`, `lab_oz.py`, `lab_snd.sh`, not kept), library `mp7` (the lab tree of `d6e97b7` with S141), OMAT-0 medium generic SrTiO3 5,000 atoms on the 5060 Ti.
- Stage: S141 (19 November 2026), the owner's fifth to seventh idea lists.
- Tensor rates (torch / cuBLAS, T(FL)OP/s; FP32 / TF32 / FP16 / INT8 / FP8): 8,192^3 17.6 / 25.3 / 50.3 / 171.7 / 173.6; M 80,000 K 128 N 128 11.1 / 11.5 / 27.4 / 17.6 / 21.5; 15,000 x 128 x 384 11.6 / 19.9 / 33.0 / 43.2 / 27.6; 5,000 x 512 x 512 14.4 / 23.0 / 43.9 / 73.4 / 69.6; 35,000 x 128 x 384 12.8 / 14.4 / 31.7 / 19.7 / 16.7.
- Co-run: 10 engine force calls (9.06 ms each including the host) while a torch loop of 2,048^3 matmuls of about the same total time runs on a side stream. Overlap = (force calls alone + loop alone - span together) / the shorter part, two rounds each: FP32 SIMT 0.04 / 0.07, TF32 0.25 / 0.20, FP16 0.07 / 0.12. Together the force calls took 148-172 ms against 80-86 ms alone.
- Ozaki-I (float64 MACE on the CPU, every interaction and product `o3.Linear`, A rows and B columns scaled by a power of two to their largest element, signed 7-bit slices, products exact; force error over the float32 model's, rattled cells 0.08 / 0.20 A): 3 slices, 6 products 6.80x / 19.2x (energy 18.7x / 13.3x, stress 22x / 14x); 3 slices, 9 products 2.11x / 6.87x; 4 slices, 10 products 0.07x / 0.20x (pass); 2 slices, 3 products 588x / 1,498x.
- Sender locality (timing stub `LOUP_LAB_SND_LOCAL`: every sender feature load and sender atomic of the L1 convs goes to one of 16 atoms next to the receiver; tables and geometry real; `nsys`, 16 force calls on fixed positions, same plans): `gconv_fwd_L1` R5 1,516.6 -> 1,460.4 us, `gconv_bwd_L1` 2,768.9 -> 2,751.8 us; all kernels 7,897 -> 7,772 us (the layer-0 kernels, not stubbed, moved by 3-6%: the run-to-run noise of this comparison).
- Degree census (ASE, 10x10x10 SrTiO3 rattled by 0.08 A, cutoff 6 A): Sr 62-68 (median 63), Ti 75-86 (83), O 70-80 (74); 2.84 tiles of 32 edges per receiver, the last 47% full on average; R5 blocks 357-380 edges.
- Archived `ncu` (`results/profiles-20261119`, OMAT-0 generic SrTiO3): `gconv_fwd_L1` L2 read hit 96.5%, L1 hit 56.4%, shared bank conflicts 12 k loads / 346 k stores against 25.1 M / 0.69 M wavefronts; `gconv_bwd_L1` L2 read hit 95.0%, L1 hit 11.3%, conflicts 1.62 M loads / 0.40 M stores against 60.7 M / 1.20 M wavefronts. SASS of `gconv_bwd_L1<true, 128, true>`: 952 instructions, 10 table `LDG.E.64`, 10 `LDS.128`, 40 `SHFL.BFLY`, 7 `REDG`.
- Status: MEASUREMENT (closes the rows in [Open or untried](#open-or-untried) that cite it).
- Sources: this file.

<a id="meas-s142-bounds"></a>
#### meas-s142-bounds: species-run ends, density term, force atomics, projection rank
- Switch: none. Lab variants (`.tmp_o/lab_v28.py`, `lab_v4.py`, `lab_rank.py`, not kept) of develop `595ee89`, OMAT-0 medium generic SrTiO3 5,000 atoms on the 5060 Ti, nsys over 16 force calls on fixed positions, same plans, interleaved rounds.
- Stage: S142 (19 November 2026), the owner's eighth idea list (items 27, 28, 38, 40).
- Species-run ends (item 28): a lab kernel (a warp per receiver, ballots over the active row) writes each receiver's per-species row ends and `first_fwd_kernel` reads them instead of its ballot scan and barrier per species: 231.0 -> 218.0 us (six rounds), the lab kernel 4.8 us, forces unchanged.
- Layer 1's density force term (item 27): `gconv_bwd_L1` with the term removed (wrong forces, timing only) 2,758 -> 2,764 us: nothing to move.
- Force atomics (item 40): `first_bwd_edge` with its six FP64 atomics per edge behind a never-true test (arithmetic kept) 424.3 -> 394.8 us: the atomics cost at most 29.5 us per call.
- Projection rank (item 38, float64 MACE on the CPU): every `o3.Linear` block of OMAT-0 medium's interactions and products has full rank (above 1e-5 of the largest singular value: 128 of 128; smallest over largest 3e-5 to 7e-2); the relative error of the best rank-96 approximation is 0.11-0.13 (interaction 1), 0.06-0.37 (interaction 0). Truncating one interaction-1 `linear` block at a time on a rattled 4x4x4 SrTiO3 cell: rank 112 gives 443-1,128x the float32 force error, rank 96 724-4,778x, rank 64 2,074-22,483x.
- Status: MEASUREMENT (closes the rows in [Open or untried](#open-or-untried) that cite it).
- Sources: this file.

[status]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md
### Tiled mode

<a id="tile-workspace"></a>**tile-workspace** (ADOPTED, 16 November 2026, 5060 Ti only). The eager tiled call
of S5-T03 set the handle up for every tile sweep with `loup_set_system`'s path: every per-system buffer freed and
allocated again, the cuBLASLt cache cleared, the variant tuning reset; 24 set-ups and 8 list builds per call at
8 tiles, 0.3-0.5 s per tile. Now the domain with the most rows (all its ghost candidates) is set up once and every
other tile reshapes it (`reshape_domain`): species grouping, per-atom constants, row counts. The generic model's
kernels take the row count of the call, so buffers with room for more rows are used as they are. Same results
(`tests/gpu/test_tiled.py`, `test_tile_lists.py`, `test_open_domain.py`: 15 passed). Time of one tiled call after a
warm-up (`.tmp_o/probe_tiled_time.py`):

| Model, atoms, tiles | Before (us/atom) | Workspace (us/atom) | Whole system |
| --- | --- | --- | --- |
| OMAT-0 small, 24,565, 3 | 55.5 | 15.0 | 0.92 |
| OMAT-0 small, 40,000, 8 | 75.0 | 23.2 | 0.85 |
| OMAT-0 small, 40,000, 2 | 30.1 | 9.5 | 0.85 |
| OMAT-0 medium, 24,565, 3 | 44.4 | 19.1 | 1.64 |
| OMAT-0 medium, 40,000, 8 | 67.1 | 19.7 | 1.63 |
| OMAT-0 medium, 40,000, 2 | 25.9 | 10.0 | 1.63 |

Still 50-100 ms per tile: four list builds per tile and call (the candidates' build and one per sweep), each with
host syncs, and a host round trip after every tile sweep. Next: keep each tile's list across its sweeps.

<a id="tile-kept-lists"></a>**tile-kept-lists** (ADOPTED, 16 November 2026, 5060 Ti only). Two changes, measured
together because the first alone changed nothing. (1) Every tile's list is built once per call, after the candidate
pass, and kept on the device (positions, species, CSR, senders, receivers, pairs, shifts, the row-to-atom map); a
sweep restores it into the workspace with device-to-device copies, so no tile sweep rebuilds a list or waits for the
host. Energy and virial accumulate on the device over all sweeps and are read once; each tile's forces are folded
into the whole-system array on the stream. Alone: OMAT-0 medium 40,000 atoms 8 tiles 22.45 us/atom, no gain.
(2) The phase timer (`LOUP_DEBUG_TILE_TIMES=1`, syncs at each phase) showed why: the call began with
`set_domain_impl`, whose `free_system` empties the cuBLASLt cache, so every tile shape's GEMMs asked for their
heuristics again in every call (sweeps 0.5-1.2 s). The call now keeps the handle's tile workspace when it has room
for the widest candidate domain and the same skin; `loup_set_system` and `loup_set_domain` drop it. Phases of a
second call, OMAT-0 medium, 40,000 atoms, 8 tiles: plan 3 ms, candidate lists 11, kept lists 23, state 4, forward
sweeps 10, last layer 58, backward 20 (the whole-system call: 65 ms). Same results (`tests/gpu/test_tiled.py`,
`test_tile_lists.py`). Time of one tiled call, median of three after a warm-up (`.tmp_o/probe_tiled_time.py`):

| Model, atoms, tiles | Workspace (us/atom) | Kept lists and workspace (us/atom) | Whole system | Tiled / whole |
| --- | --- | --- | --- | --- |
| OMAT-0 small, 24,565, 3 | 15.0 | 2.39 | 0.91 | 2.6 |
| OMAT-0 small, 24,565, 2 | 12.8 | 1.94 | 0.91 | 2.1 |
| OMAT-0 small, 40,000, 8 | 23.2 | 2.55 | 0.89 | 2.9 |
| OMAT-0 small, 40,000, 2 | 9.5 | 2.01 | 0.89 | 2.3 |
| OMAT-0 medium, 24,565, 3 | 19.1 | 4.01 | 1.64 | 2.4 |
| OMAT-0 medium, 24,565, 2 | 12.9 | 3.62 | 1.64 | 2.2 |
| OMAT-0 medium, 40,000, 8 | 19.7 | 4.33 | 1.65 | 2.6 |
| OMAT-0 medium, 40,000, 2 | 10.0 | 2.97 | 1.65 | 1.8 |

Left: the list builds of a single call (34 ms of 173 at 8 tiles; an MD run keeps them until skin/2, S5-T06), the
ghosts' share of the sweeps (each tile computes its ghost candidates' layer 0 too), and the first call on a new
workspace (5.3 s of sweeps at 8 tiles: every distinct tile row count is a new GEMM shape; size buckets, S5-T10).

[s1]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#1-benchmark--verification-summary
[s2]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#2-detailed-kernel-profile-current-build
[s31]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#31-implemented-optimisations
[s32]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#32-correctness--api-fixes-applied-from-code-review
[s33]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#33-ruled-out-measured
[s41]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#41-remaining-performance-opportunities
[s42]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#42-open-review-hardening-items-correctness--robustness
[s5]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#5-model-families-generic-path
[s51]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#51-pipeline
[s54]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#54-fixes-found-by-the-family-work
[s6]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#6-release-branch-releasev1-stage-1-of-the-release-plan
[s61]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#61-after-the-merge-of-round6-hardening-e21faa2-15-november-2026-0430-to-0515
[s62]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#62-stage-3-front-end-and-the-thermostat-target-on-the-device-15-november-2026-0520-to-0610
[s63]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#63-fixed-atoms-and-the-host-side-optimisers-15-november-2026-0615-to-0650
[s64]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#64-centre-of-mass-at-rest-fix_com-and-the-current-build-against-the-merge-build-15-november-2026-0655-to-0735
[s65]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#65-csvr-the-layout-move-and-the-skin-chosen-from-the-step-size-15-november-2026-1205-to-1310
[s66]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#66-nose-hoover-chain-berendsen-nvt-lbfgs-on-the-device-and-the-generic-path-as-the-default-15-november-2026-1330-to-1740
[s67]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#67-the-variable-cell-and-berendsen-npt-15-november-2026-1720-to-1845
[s68]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#68-langevin-baoab-npt-mtk-npt-and-what-two-builds-differ-by-in-the-benchmark-15-november-2026-1845-to-2025
<a id="tile-gemm-buckets"></a>**tile-gemm-buckets** (ADOPTED, 16 November 2026, 5060 Ti only). The GEMM plan cache is keyed by the exact M, and in the tiled call every tile's row count is an M of its own that changes with every list build, so each tile shape was timed (the candidates of cuBLASLt, the hybrid cubin and the own SGEMMs) on the first call and again after every rebuild. While the handle holds a tile workspace, `sgemm_rm` now also looks up a decision by (M bucket, N, K, transB, beta), four buckets per octave (`m_bucket`), and stores every timed decision there; a hit is validated for the actual M as a plan-file hit is (the own kernels' size rules, the cuBLASLt algorithm check), and timed afresh if it does not fit. The whole-system path is unchanged. Results: first call 5.95 -> 2.21 s and after a rebuild 4.36 -> 0.86 s (OMAT-0 medium, 40,000 atoms, 12 tiles), steady calls unchanged; tiled 3x gate passes with the ratios of §6.14. The hybrid now runs on some tile shapes it was not timed on, which moves the default-GEMM energy spread against the whole-system call from at most 1.03e-6 to 1.42e-6 eV/atom (D66). Status §6.21.

<a id="tile-md-device"></a>**tile-md-device** (ADOPTED, 16 November 2026, 5060 Ti only). A tiled run's integrator ran on the host in numpy around the tiled call. It now runs on the device with the whole-system loop's kernels (`loup_tiled_run`; the tiled call takes device positions and writes device forces). It was 1-5% of a step: 320,000 atoms NVE 712.5 -> 697.6 ms, Langevin 744-807 -> 706.5. It also brings CSVR, the Nose-Hoover chain and Berendsen NVT to the tiled mode. Status §6.34.

<a id="tile-host-stage"></a>**tile-host-stage** (ADOPTED, 16 November 2026, 5060 Ti only). The host lists of `tile-host-lists` were read over the bus by the active-edge compaction (about 14 GB/s). Each compacting sweep's 36 B per edge are now copied into one of two device buffers on a copy stream while the previous sweep runs; the compaction reads the device copy. A B B A in separate processes: 0.871 at 320,000 atoms, 0.870 for the wavefront at 1,081,600; the host-list fallback now runs at about the device lists' speed. Exact (the same kernels on the same numbers). Status §6.34.

<a id="tile-keep-layer0"></a>**tile-keep-layer0** (ADOPTED, 16 November 2026, 5060 Ti only). The backward sweep of layer 0 replayed layer 0's forward to recover `msgf[0..3]` and `D`, the only forward results its backward reads for the density layer 0 with the hidden table (MP-0b3, MPA-0, OMAT-0, MatPES). The tile keeps them (8.2 KB per receiver) from its forward sweep: the layer's pointers point at the tile's buffer during both sweeps, and the backward adds the linear readout's constant seed instead of the replay. Plain order only, within the free memory less the slot reserve. A B B A 642.2 / 598.9 / 596.3 / 644.1 ms, b / a 0.929. Tiled label gates with it: the 8 oxide labels and mh1-omat passed; it engages for mp0b3-medium, mpa0-medium, omat0-small / -medium, matpes-pbe / -r2scan (not MP-0, MH-1, OFF, OMOL-0). Status §6.34.

<a id="tile-slot-reserve"></a>**tile-slot-reserve** (ADOPTED, 16 November 2026, 5060 Ti only). The active-edge slots of `tile-active-once` were limited to a quarter of the free memory, which left the wavefront at 1,081,600 atoms one slot of the five it uses (no gain). Free memory less max(256 MB, 2% of the card) gives it five: b / a 0.979; a list rebuild with them peaks at 13.7 of 14.6 GiB. Status §6.34.

<a id="tile-host-state"></a>**tile-host-state** (ADOPTED as the fallback above the host-lists limit, 16 November 2026, 5060 Ti only). Not a speed change: the memory plan moves the plain order's layer outputs `x` and gradients `dx` to pinned host memory only when no cap fits with the lists there alone. Each atom's host row lies in its tile's block, so a tile's locals move as one copy; ghosts are gathered and gradients added on host threads; the device keeps four ring slots. Forced at 320,000 atoms: 611 ms with the device state, 902 synchronous, 750-780 with the copies and host work overlapped (two copy streams, the ring copies as kernels). The rest is about four 20 ms gaps at the phase boundaries. Open: `dx` aliased onto `x`, compact host lists, the wavefront pool on the host, the boundary gaps. Status §6.34.

<a id="tile-pinned-reuse"></a>**tile-pinned-reuse** (ADOPTED, 17 November 2026, 5060 Ti only). A list rebuild with the host state spent 3.8 s of its 7.5 s in cudaHostAlloc (layer state 1.5 s, windows 2.25 s at 2,560,000 atoms). The released state's pinned buffers now become the handle's spares, taken by size (at most 25% larger) by the next state and freed at the end of its set-up; the planner adds them to `MemAvailable`. Rebuild call 12.96 -> 8.50 s (the first rebuild 11.29 s: its windows found no spare of their size), kept calls unchanged. Status §6.34.

<a id="tile-compact-only"></a>**tile-compact-only** (REJECTED as the default, 17 November 2026, 5060 Ti only). Every tile in a compact slot instead of a full one: 2,560,000 atoms peak 12.84 -> 6.16 GiB at +1.5% (A B B A); 320,000 +2.1%, the 1.08M wavefront +0.6%. The restores write about 28 B per edge into the handle's buffers each later sweep; a sweep that read the compact form directly would be needed for the same speed. The environment pair stays as the low-memory setting. Status §6.34.

<a id="tile-list-arena"></a>**tile-list-arena** (ADOPTED, 17 November 2026, 5060 Ti only). cudaMalloc takes about 1.3 MB more than asked per allocation of a few MB (WSL, RTX 5060 Ti; 891 lists' sizes: 2,606 MB asked, 3,737 MB used), whether the allocation is cut into arrays or not. The tile lists' device arrays now come from 128 MB chunks on the tiled state, the full slots from one chunk and the compact slots from another. 2,560,000 atoms, two runs per side: device plan lists 3,072 -> 2,550 MB; default plan 537-541 -> 1,860 MB free after the slots. Times tie (2.56M device and default plans, 320,000; the 1.08M wavefront within its spread). Status §6.34.

<a id="tile-slot-block"></a>**tile-slot-block** (NEUTRAL, kept; first recorded as ADOPTED, corrected the same day). The measured 1.14 GB did not repeat: free memory read in the call moves by about a gigabyte between runs, and cudaMalloc alone gives 20 MB for 125 slots. The single allocation per slot stays (tile-list-arena uses it). Each slot of kept active edges (full or compact) was six (three) allocations, each rounded up: 125 slots of 74 MB took 10.6 GB at 2,560,000 atoms, 1.4 GB beyond the count and into the memory fraction's reserve (522 MB left free). One allocation per slot cut at 256 B boundaries: 1,659 MB free. Time: 320,000 and the 1.08M wavefront tie (two orders); 2,560,000 b / a about 1.003-1.004 (A B B A), at the noise; adopted for the memory. Status §6.34.

<a id="tile-wave-host-bus"></a>**tile-wave-host-bus** (NEUTRAL, 17 November 2026, 5060 Ti only; local branch `wip/tile-wave-host-bus`, not on release/v1). The wavefront's host pool (`tile-wave-host-pool`, +37% forced at 1,081,600 atoms) runs a synchronisation and host work for each sweep: a forward sweep waits for the stream before zeroing its gradient block, a last-layer sweep waits twice per order for its ghost gathers and its gradient adds. The branch maps the pool and does all three as kernels on the stream (adds in rounds of distinct host rows: a tile's ghosts can be images of its own rows). The wavefront and host tests pass (39). 320,000 atoms in a rod, forced at fraction 0.6: 928.8 ms against the host work's 939.7 / 931.6 ms, a tie: the copies, not the synchronisations, are the host pool's cost. Forced wavefront host-pool timing jobs took the WSL distro down three times that day (8M, 1,081,600 and 320,000 atoms, with and without the bus), and a fourth time the small plain host-state tests did: WSL may have stayed unstable after the first failure; cause not found, Status §6.34.

<a id="tile-plan-fit"></a>**tile-plan-fit** (NEUTRAL, not kept, 17 November 2026, 5060 Ti only). The planner estimated a tile's workspace from blocks of `cap` atoms, about twice what a call uses at large caps. A trial fitted the grid for each candidate cap and estimated from the widest piece and its halo (320,000 atoms 9.3 -> 6.9 GB). Where memory is short it picked larger caps (3.52M atoms at fraction 0.75: 32,768 -> 49,152; 5M: 24,576 -> 32,768), but the grid fit by rows gave the same tiles, peak and times (A B A B within 0.5%), and planning took 0.1-0.2 s more. Reverted. Status §6.34.

<a id="tile-grid-rows"></a>**tile-grid-rows** (ADOPTED, 17 November 2026, 5060 Ti only). FastMACE's fit (fewest pieces) split blocks just above the cap in atom order, so every piece's domain was its whole block and halo: at 2,560,000 atoms and cap 65,536, 3 x 3 x 3 blocks gave 54 tiles with up to 65,536 locals and 69,464 ghosts, a 12.6 GB workspace and no memory for slots (6.49 s). The fit now counts rows (each piece: its block's atoms plus the halo at the mean density over a shell `reach` thick) and takes 4 x 4 x 4 there (64 tiles, 5.23 s). Without a reach the old rule stays. 320,000 and the 1.08M wavefront plans unchanged (A B B A ties). Status §6.34.

<a id="tile-plan-slot-room"></a>**tile-plan-slot-room** (ADOPTED, 17 November 2026, 5060 Ti only). The plain host state's cap search first wants room for compact slots of every tile (1.5 x 8 B per list edge); a device plan in caps under 16,384 with 256 tiles or more gives way to the host state at 4x-8x its cap where that fits with the room. 2,560,000 atoms: cap 4,096 on the device (891 tiles) 5.75 s -> host state at 32,768 (125 tiles, 125 full slots) 5.24 s, b / a 0.911 (A B B A), lower peak. A first rule without the 8x limit took 65,536, where the call found no memory for slots although the estimate left 4 GB: 6.49 s (worse). Status §6.34.

<a id="tile-host-state-window"></a>**tile-host-state-window** (ADOPTED, 17 November 2026, 5060 Ti only). At 8,008,065 atoms (SrTiO3 117^3, OMAT-0 medium, fraction 0.9) the device plan takes cap 6,144 (2,016 tiles, the wavefront) and no cap of 4x-8x fits for the plain host state, which the plan then never tried below 4x. The host state at 16,384 (2.67x, 512 tiles, 23.9 GB host): 16.60 / 16.64 s kept against 17.29 / 17.28 s (A B B A, two kept calls each), b / a 0.961; cold calls 40.6 / 39.0 s against 49.4 / 49.0 s; peak 12.97 against 13.10 GiB; energies within 6 eV of 6.4e7 (float32 sum order, the device runs differ by 3 eV between themselves). The search now goes down to 2.5x after 8x-4x. Plans before / after at 320,000, 1.08M, 2.56M, 5M and 8M atoms at fractions 0.9, 0.75 and 0.5: only 8M at 0.9 changes; the new default there 16.70 s (one run, the library's first call, so the GEMM plans were made cold). The host state at that size takes 60% of WSL's 38 GiB available: the plan's host limit decides where it applies.

<a id="tile-slot-room-limit"></a>**tile-slot-room-limit** (ADOPTED, 17 November 2026, 5060 Ti only). The plain host state's cap search (tile-plan-slot-room) took the largest cap leaving room for compact slots of every tile, however small. 5,000,000 atoms (SrTiO3 100^3, OMAT-0 medium) at fraction 0.5: slot room only at 4,096 (1,362 tiles) 11.26 / 11.24 s, peak 7.26 GiB; 16,384 (343 tiles) 10.44 s; 32,768 (216 tiles, the largest that fits) 10.44 / 10.39 s, peak 7.22 GiB. Without the slot-room pass at all, the plans that change where it costs 1.3x-2x in cap tie (two kept calls, one run each): 5M at 0.9 32,768 / 65,536 10.27 / 10.27 s, 5M at 0.75 24,576 / 49,152 10.30 / 10.28 s, 2,560,000 at 0.5 24,576 / 32,768 5.28 / 5.31 s. The search keeps the slot room unless the cap it gives is under a quarter of the largest that fits. Of 20 plans (320,000 to 8M atoms, fractions 0.9 / 0.75 / 0.5 / 0.35) only 5M at 0.5 changes. `tests/gpu/test_tiled.py`, `test_memory_plan.py`, `test_large_box.py`, `test_capacity.py` 70 passed.

<a id="tile-host-state-larger-cap"></a>**tile-host-state-larger-cap** (ADOPTED, 17 November 2026, 5060 Ti only). A sweep of kept-call times against the memory fraction found the plain host state at 1,080,000 atoms (SrTiO3 60^3, OMAT-0 medium) as fast as the device plan or faster at a third of the VRAM: fraction 0.9 device cap 49,152 (45 tiles) 2.292 s, 11.51 GiB; 0.35 host state at 16,384 2.259 s, 5.06 GiB; 0.25 host state at 12,288 2.282 s, 3.62 GiB. Forced at 0.9 the host state reaches 65,536 (27 tiles): 2.196 / 2.195 s against 2.285 / 2.271 s (A B B A), peak 10.56 against 11.6-11.9 GiB; at 320,000 atoms, where both reach 65,536, it loses (0.613 against 0.593 s). The plan now gives a device plan below the largest cap way to the host state where the host state's cap search reaches a larger cap, from 2^20 atoms. Kept calls, old -> new (three kept calls, one run each unless noted): 1.08M at 0.75 32,768 -> 49,152 2.250 -> 2.190 s, at 0.5 12,288 -> 32,768 2.324 -> 2.214 s (peak 7.22 -> 7.06 GiB); 8,008,065 at 0.75 6,144 (wavefront) -> 16,384 17.58 / 17.60 -> 16.79 / 16.67 s (A B B A, two kept calls), peak 10.91 -> 10.78 GiB. Without the size bound it lost below 2^20: 320,000 at 0.5 / 0.35 +4.2% / +2.9% (0.25 -1.3%), 135,000 at 0.25 +10%. Of 35 plans (135,000 to 8M atoms, fractions 0.9 to 0.25) 4 change. `tests/gpu/test_tiled.py`, `test_memory_plan.py`, `test_capacity.py`, `test_tiled_md.py` 78 passed.

Time against the memory fraction (kept calls, the plans after this change where they differ): 320,000 atoms 0.9 / 0.5 / 0.35 / 0.25: 0.583 / 0.636 / 0.647 / 0.670 s at 11.26 / 4.78 / 4.78 / 3.64 GiB; 2,560,000: 5.24 / 5.28 / 5.38 / 5.45 s at 12.84 / 7.23 / 4.98 / 3.52 GiB; 5,000,000: 10.27 / 10.39 / 10.59 / 10.69 s at 13.05 / 7.22 / 5.04 / 3.62 GiB. From a million atoms a quarter of the card costs 2-4% against 0.9.

<a id="tile-pinned-headroom"></a>**tile-pinned-headroom** (ADOPTED, 17 November 2026, 5060 Ti only). The tiled state's pinned host buffers go to the handle's spares at a list rebuild and are taken again when a spare is at least as large as asked (tile-pinned-reuse). After the atoms move, the first rebuild asks a little more than the first call's buffers: 2,560,000 atoms (fraction 0.9, rigid 0.3 A plus 0.15 A random per move) first rebuild call 10.22 s, of it 2.47 s host windows and 0.56 s state buffers (new cudaHostAlloc), later rebuilds 7.13-7.20 s. A new buffer now has 1/32 more than asked: first rebuild 7.06 / 7.09 s (two runs), later ones 7.06-7.17 s, kept calls 5.23-5.25 s as before; 1/16 the same. 8,008,065 atoms: first and second rebuild 23.06 / 22.79 s. The plan's host estimate does not count the 3%. `tests/gpu/test_tiled.py`, `test_memory_plan.py`, `test_tiled_md.py` 71 passed.

<a id="tile-host-state-device-lists"></a>**tile-host-state-device-lists** (NEUTRAL, not kept, 17 November 2026, 5060 Ti only). Forced, the host state with the lists on the device took 2,560,000 atoms at fraction 0.9 to cap 49,152: kept 5.21 s as the default's host lists at 32,768, the calls that rebuild the lists (after a move past half the skin) 6.68 / 6.65 s against 7.17 / 10.10 s, peak 12.31 against 12.59 GiB. A rule that kept the lists on the device wherever that reached the plan's cap (in the cap search and in the 4x-8x window) changed 5 of 20 plans, none to 49,152 (the window stops at 8x the device cap, 32,768). Kept / rebuild calls, old -> new: 2.56M at 0.9 5.21 / 5.23 -> 5.24 / 5.24 s (A B B A), rebuilds 7.1 / 10.2 both, peak 12.59 -> 12.90 GiB; 5M at 0.75 (24,576 -> 32,768) 10.34 -> 10.41 s, rebuilds 19.3 / 14.0 -> 18.6 / 13.5 s, peak 10.81 -> 10.46 GiB; 2.56M at 0.35 (8,192 -> 12,288) 5.40 -> 5.51 s, rebuilds 8.3 / 7.9 -> 8.5 / 8.5 s; 1.08M at 0.35 2.27 -> 2.28 s. Ties or small losses: reverted. The first rebuild after the call's start is the slower one in most runs (the second differs by up to 5 s between runs of one plan).

<a id="tile-merge-round6"></a>**tile-merge-round6** (ADOPTED with the merge `09d6daa`, 17 November 2026, 5060 Ti only). What the merge of `round6-hardening` `13d6337` does to the tiled mode, measured as the merged library against the library of `97e365d` (not separated by change). The tile lists drop the per-edge receivers and pairs as S113's whole-system list did: a row is one receiver's edges and the pair index follows from the species, so the full form is the Cartesian shift and the sender, 28 B per edge instead of 36 (`kTileFullEdgeB`; the compact form stays 8 B). The chain fold round6 turns on for every multi-layer model stays off for tiled and domain systems (`use_chain_fold`, PLAN.md D85), since the sweeps hand on the layer outputs the fold never forms, so tiled runs do not have the fold's gain (whole systems: 1.7% on OMAT-0 medium, 5-7% on MH-1, 23% on OMOL-0). The tile workspace estimate is 2-4% smaller (OMAT-0 medium) and 3-5% (OMAT-0 small); 4 of 70 plans (two models, 135,000 to 8,008,065 atoms, fractions 0.9 to 0.25) move to a larger cap and none changes its mode. Kept calls, A B B A with a fresh plan directory per process: OMAT-0 medium 320,000 atoms 0.987 / 0.914 / 0.988 / 0.987 at fractions 0.9 / 0.5 / 0.35 / 0.25; 1,080,000 atoms 0.989 / 0.983 / 0.986 / 0.981 / 0.983 at 0.9 / 0.75 / 0.5 / 0.35 / 0.25; 2,560,000 atoms 0.986 / 0.983 / 0.984 / 0.988; 5,000,000 atoms 0.986 / 0.984 / 0.986 / 0.987; 8,008,065 atoms at 0.9 (device wavefront) 0.981; OMAT-0 small 320,000 at 0.5 0.982, 1,080,000 at 0.9 / 0.5 0.985 / 0.986, 2,560,000 at 0.9 0.977. At 320,000 atoms and fraction 0.5 the 28 B lists let every tile keep a full slot of active edges within the budget (0.640 -> 0.584 s, peak 4.78 -> 7.17 GiB, the fraction's limit); elsewhere the peak moves by +0.04 to -0.19 GiB. Tests: `tests/gpu` in three tiers on the merged library (status §6.34). Not built: a fold inside the sweeps (handing on the product outputs), and the specialised path's in-place buffers (S110-S112, 93 -> 53 KiB per atom at 40,000 atoms) for the generic kernels the tiles run (about 100 KiB per atom in the plan's whole-system count).

<a id="tile-shared-layers"></a>**tile-shared-layers** (ADOPTED, 17 November 2026, 5060 Ti only). The generic path gives every layer its own buffers (x, the product intermediates, messages, their gradients, the readout's hidden rows): about 100 KiB per atom for OMAT-0 medium. A whole pass needs them all at once; a sweep runs one layer and reads and writes of another layer only its output and that output's gradient. A system that only sweeps (a tile's or an open domain's, and a whole system under `LOUP_SWEEP_REPLAY`) now carves each layer's own buffers from the start of one arena as large as the largest layer; the outputs, their gradients and the zero slab stay separate, and such a system refuses the whole pass (`GenericModel::share_layer_buffers`, `alloc_system`, the guard in `record`). The engine reads only the outputs and their gradients, and the tiled call already ran every sweep on buffers another tile had left. Tile workspace at cap 65,536: OMAT-0 medium 8.38 -> 5.62 GiB, OMAT-0 small 6.47 -> 3.96 GiB. The memory plan counts a row with every layer's buffers (`system_bytes_unshared`), so the plans are the ones measured before, the whole-system count does not change, and what the workspace gives back goes to the kept slots or stays free. Kept calls against the merged library (A B B A, fresh plan directory per process; ratio, device peak): OMAT-0 medium at fractions 0.9 / 0.5 / 0.35 / 0.25: 135,000 atoms 1.002 / 1.000 / 0.994 / 0.994, peak 5.05 -> 4.05 GiB (3.25 -> 2.86 at 0.25); 320,000 atoms 1.005 / 1.008 / 0.996 / 0.963, 11.07 -> 9.03, 7.17 -> 6.46, 4.72 -> 4.02, 3.59 -> 3.52 GiB; 1,080,000 atoms 1.002 / 0.999 / 1.000 / 0.996, 10.37 -> 8.34 and 6.98 -> 5.99 GiB, the others equal; 2,560,000 atoms 1.009 / 1.002 / 1.002 / 0.992, 12.74 -> 11.57 GiB at 0.9; 5,000,000 atoms 0.997 / 0.989 / 0.988 / 0.994, peaks equal; 8,008,065 atoms at 0.9 0.996. OMAT-0 small at 0.9 / 0.5 / 0.25: 320,000 atoms 1.000 / 0.874 / 0.999 (at 0.5 every tile's slot now fits: 0.346 -> 0.303 s, peak 6.31 -> 6.90 GiB; at 0.9 8.75 -> 6.90 GiB); 1,080,000 atoms 1.005 / 0.985 / 0.999; 2,560,000 atoms 0.994 / 0.995 / 0.969. Rejected with it (`tile-shared-layers-caps`): letting the cap search count the shared size moved device plans to larger caps that leave no room for the slots (320,000 atoms at fraction 0.5: 27 tiles with every slot 0.581 / 0.583 s, 8 tiles without 0.627 / 0.631 s; 1,080,000 at 0.9 a device plan instead of the host state, +0.9% at a 2.5 GiB higher peak), and a rule that also wants room for every tile's full slot (36 B per list edge) in device plans lost at fraction 0.25 (135,000 atoms +4.9%, 320,000 +1.6%). Open: one process at 5,000,000 atoms had two kept calls of twice the time (20.1 and 18.5 s beside 10.2 and 10.5 s); the library's 62 other kept calls at that size and 64 calls of the libraries without the arena were normal; cause not found (status §6.34). Tests: the replay tests run the shared layout with every other buffer overwritten with NaN; `test_a_tiles_layers_share_one_arena_and_give_the_same_result` (two and three layers); all tiers on the library. Next: a cap search that counts the shared size only where larger tiles pay (host-state plans from 2.5M atoms), and the same for the three-layer models.

<a id="mem-free-nvml"></a>**mem-free-nvml** (ADOPTED, 18 November 2026, 5060 Ti in WSL 2 only). `cudaMemGetInfo` under WSL 2 (WDDM) reported 15.16 GiB free of 15.90 while Windows programs held 2.9 GiB (NVML: 13.1 GiB free), followed the process's allocations exactly up to 10.2 GiB held and then dropped by 1.2 GiB more at once; NVML's use rose by each allocation and nothing else, and a single allocation of 64 MiB to 4 GiB costs its size. Every budget made from CUDA's figure was 1.5-2 GiB too large and every peak read above the step 1.2 GiB too high (the status file's §6.34 peaks above about 10.4 GiB; an apparent 1.1 GiB of uncounted memory on MH-1 at 20,480 atoms). `device_memory` takes the smaller of the two figures (NVML loaded at run time by PCI bus id, 0.35 ms a query; CUDA's alone where NVML is missing or `LOUP_NO_NVML=1`). Not a speed change: a memory fraction now means a fraction of the memory that is free in fact, so at an unchanged fraction the plans have about 12% less (11.8 GiB at 0.9 here).

<a id="tile-plan-exact"></a>**tile-plan-exact** (ADOPTED, 18 November 2026, 5060 Ti only). What `loup_plan_execution` reports. Before, it reported the estimates of its cap search (every layer's own buffers, a tile of `cap` receivers, 32 B a kept row, four alias windows, none of what the call adds within the fraction): plan / peak 0.55-2.07 on 13 plans, planned / pinned host memory 0.66-0.81, and plans of thousands of tiles that exceeded the fraction (13,720,000 atoms: 12.4 GiB of 11.8). Now the cap search is as it was (its rules were measured with those estimates, except that it counts both host arrays), and for the cap it picks the plan computes what the call will hold from the plan's own tiles (`tile_shape`: widest domain, rows, tiles in flight, the wavefront's pool, the host windows by the call's schedule), the workspace's shared arena and the call's rules for slots, staging and layer 0; a cap whose figures do not fit steps down or is refused; the slots' reserve leaves room for the GEMM timing's scratch (the model's largest buffer). The whole-system count subtracts what the fold never forms and both planners count 64 MB that do not scale. The host state may take two thirds of the available host memory by the corrected count. Measured: plan / device peak 1.003-1.049 on 22 plans (135,000 to 20,480,000 atoms, fractions 0.9 to 0.25, two models; 4-5% in three plans of 64 to 216 tiles); plan / pinned 0.99-1.04; whole count / measured 0.995-1.004 (OMAT-0 medium, MH-1, OFF23 medium at size), 0.98 (OMOL-0 at 5,184 atoms). Capacity (`docs/validation/capacity.md`): OMAT-0 medium 121,945 atoms whole, 10,985,000 in tiles (24.2 s a call); OMAT-0 small 20,480,000 run (24.5 s). The plan itself takes longer for the largest cells (21.5 s at 10,985,000 atoms). The long-range models' buffers (`src/polar.cu`) are counted too: scaled plan / measured 0.77 -> 1.01-1.03 (POLAR-1-S), 0.965-0.996 (POLAR-1-M). Open: `loup_plan_execution` gives long-range models no whole-system count.

<a id="tile-compact-slots"></a>**tile-compact-slots** (ADOPTED, 17 November 2026, 5060 Ti only). Kept active edges in 8 B per edge (row pointers, senders, char4 integer image shifts) for tiles of compact lists that full slots (now 36 B per edge, without pairs) cannot cover: packed after the first sweep's compaction, restored bit for bit in the later sweeps instead of compacting again. The mix covers the most tiles in flight. 3.52M atoms at fraction 0.75: 8 full -> 40 compact slots, kept call b / a about 0.975. A first build that gave full slots first got no compact slot anywhere (no gain). Status §6.34.

<a id="tile-device-compact"></a>**tile-device-compact** (ADOPTED, 16 November 2026, 5060 Ti only). The compact host lists' form for the device lists too: senders and char4 integer image shifts kept (bitwise exact or the tile keeps 36 B), the compaction's senders, receivers, pairs and Cartesian shifts decoded into the handle's own buffers per compaction (`tile_decode_edges_kernel`). Faster as well as 4.5x smaller: 320,000 atoms b / a 0.93, wavefront 1,081,600 b / a 0.977 (a larger cap). `LOUP_TILE_DEVICE_COMPACT=0` keeps 36 B. Status §6.34.

<a id="tile-slot-reserve"></a>**tile-slot-reserve** (ADOPTED, 16 November 2026, 5060 Ti only). The kept active-edge slots and kept layer 0 fill the free memory less max(256 MB, 2% of the card, (1 - memory fraction) x budget): at fraction 0.75, 3,524,845 atoms took 24 slots of 221 MB and ran out of memory in the sweeps; with the fraction's share kept free it runs (8 slots), and 5M atoms too. Costs the 1,081,600-atom wavefront its slots at fraction 0.9 (about +1.5%) until compact device lists free the memory. Status §6.34.

<a id="tile-wave-host-pool"></a>**tile-wave-host-pool** (ADOPTED for capacity, 16 November 2026, 5060 Ti only). The wavefront's pool in pinned host memory: blocks of the most locals per tile, taken at a tile's sweep 1 and freed at its sweep 3, the plain host state's synchronous copies and host adds. The plan's fourth step. +37% at 1,081,600 atoms forced (no pipeline yet). Status §6.34.

<a id="tile-host-edges"></a>**tile-host-edges** (ADOPTED, 16 November 2026, 5060 Ti only). At the forward-to-last boundary the last forward tile's outputs are still in the layer buffer: its last-layer sweep goes first (always: a first build that left it to the readiness order was 50 eV off where another tile came first) and copies only its ghosts in. At the last-to-backward boundary the last tile's own gradient rows are still in ring slot b: its backward sweep adds them on the device to the others' host adds. Tiles without ghosts of their own atoms. 0.974-0.98 at 320,000 atoms. Status §6.34.

<a id="tile-host-dma"></a>**tile-host-dma** (ADOPTED, 16 November 2026, 5060 Ti only). Two GPU gaps of the host-state call: on this PC (WSL) the copies to and from the host run one at a time in the order queued, so a gradient copy out that waits for its sweep held the next tile's input copy back; it is now queued after it. And a block whose window no later block takes keeps its gradients there instead of folding them into `x` in the phase's last add (the backward sweeps read the pinned window). 0.893 at 320,000 atoms (729 -> 651 ms). Status §6.34.

<a id="tile-host-compact"></a>**tile-host-compact** (ADOPTED, 16 November 2026, 5060 Ti only). Host lists keep the sender and the integer image shift of each edge (8 B); receivers, pairs and Cartesian shifts are rebuilt on the device before each compaction, bitwise the same as the build's (the build's own expression); a tile that cannot be encoded exactly keeps the 36 B form. 0.975 with host lists at 320,000 atoms (fewer bytes staged); the host memory of the lists 4.5 times smaller. Status §6.34.

<a id="tile-host-alias"></a>**tile-host-alias** (ADOPTED, 16 November 2026, 5060 Ti only). In a two-layer model the backward sweeps never read layer 0's outputs again, and a tile block's readers in the last sweeps are the same tiles as its gradient adders. A block's gradients are added into a window block (host memory, reused across calls) from its first adder until its last reader has taken its inputs, then folded into the block's `x` rows, where the backward sweeps read them. The separate `dx` array and its zeroing each call go. A B in separate processes, four each: 0.963 at 320,000 atoms. Status §6.34.

<a id="tile-host-flow"></a>**tile-host-flow** (KEPT, neutral, 16 November 2026, 5060 Ti only). The host state's phases are not drained: the last sweeps take the tiles whose ghosts' tiles wrote their outputs out first, the backward sweeps the tiles whose gradient adds end first; per-tile events and futures replace the drain, and the forward outputs leave through the second ring slot. 1.01 at 320,000 atoms: its 8 tiles all neighbour each other, so nothing is ready early; the cost is the gradient copies of the last-layer phase, not the gaps. Kept because the alias uses its order. Status §6.34.

<a id="tile-host-lists"></a>**tile-host-lists** (ADOPTED as the fallback above the device limit, 16 November 2026, 5060 Ti only). Not a speed change: the memory plan moves the lists' edge arrays (36 B per edge) to mapped pinned host memory only when no cap fits with them on the device (estimated: the lists are about a third of the plain tiled mode's kept device state, most of it with the wavefront; no run above the device limit yet). Forced on a cell that fits: 15% (plain) and 20% (wavefront) slower per call, list builds 7x slower (pinning). Open: staged copies on a second stream, overlapped with the previous tile's sweep. Status §6.34.

<a id="tile-active-once"></a>**tile-active-once** (ADOPTED, 16 November 2026, 5060 Ti only). The three sweeps of a tile each compacted its active edges again (about 19 ms per call at 320,000 atoms by `nsys`). A tile now compacts them in its first sweep of a call into a slot of the tiled state and its later sweeps read them; the slot goes back at its last sweep, so the wavefront needs only as many slots as tiles in flight. Slots are sized for the longest list and take at most a quarter of the free memory. A B B A against `tile-list-borrow`: 656.1 / 649.7 / 641.6 / 658.5 ms, b / a 0.982. Wavefront 1,081,600 atoms: one slot of the five it could use fits, tie. Status §6.34.

<a id="tile-list-borrow"></a>**tile-list-borrow** (ADOPTED, 16 November 2026, 5060 Ti only). `restore_tile_list` copied each tile's list (senders, receivers, pairs, shifts, rows, species, positions) into the handle before each of its three sweeps: 4.1 GB and 23.5 ms of device copies per call at 320,000 atoms. The sweeps only read the list, so the handle now points at the tile's buffers, and a scope guard restores its own pointers at the end of the call. A B B A: 672.1 / 668.4 / 659.6 / 673.3 ms, b / a 0.987. Status §6.34.

<a id="tile-wavefront"></a>**tile-wavefront** (ADOPTED, 16 November 2026, 5060 Ti only). The plain tiled call keeps every layer output and its gradient for the whole system on the device, which is most of its memory (about 30 GiB at a million OMAT-0 medium atoms). For two-layer models the call now can run the three sweeps in the order of FastMACE's wavefront schedule: a tile's forward sweep just before the first last-layer tile that reads it, its backward sweep just after the last one that adds to it, so only the rows between those two steps are held, in a pool the host assigns once per plan; the planner splits the first and last layer at the faces (boundary skins) so the periodic wrap holds only thin skins. The arithmetic per row is the plain call's. Results: 368,640 atoms peak 4.91 -> 4.05 GiB with kept calls tied (0.80 s), first call 2.4 -> 3.4 s (8 more tiles); 1,081,600 atoms with a pool of 11.1% of the atoms in 10.84 GiB. On by `auto` only from 2^20 atoms and 12 layers, so no standard benchmark runs it. Status §6.22.

<a id="tile-overhead-screen"></a>**tile-overhead-screen** (REJECTED, 16 November 2026, 5060 Ti only). S5-T10 listed a receiver-cap screen, graphs per bucket and list builds without host round trips as the way to the 1M-atom speed. The cap screen: kept calls change by under 7% from 8,192 to 65,536 receivers at 320,000 atoms and by under 3% from 16,384 to 49,152 at 1,081,600, the largest cap fastest or tied, so the plan keeps the largest cap that fits. 46 more tiles cost 48 ms, so launches are at most about 1 ms per tile and graphs could save at most 1.5% at the plan's caps; a list rebuild with timed plans costs 190 ms, about 1% of a step at a rebuild every 20 steps. Neither was built. The cost left is the halo: the last-layer sweep is 65% of a kept call. Status §6.23.

<a id="tile-strained-lists"></a>**tile-strained-lists** (ADOPTED, 20 November 2026, 5060 Ti only; LT6 (a) of `LAMMPS_TILED_PLAN.md`, the owner's go D99). Before, any cell not bit for bit the build's dropped the tiled state: the plan, a probe at cap 0, and every tile's list. LAMMPS's `fix npt` through the tiled pair style changes the box in every step, so each step planned and built lists: 491 against 424 ms per step on MH-1 at 50,820 atoms (+16%, §6.40). Now the lists stay while r_list (1 - |F - 1|_F) > r_max and every atom lies within (r_list (1 - |F - 1|_F) - r_max) / 2 of x0 F + t (F = h0^-1 h, t the mean displacement, so the box's dilation about its centre does not count), the variable-cell step's rule; `tile_place_rows_cell_kernel` places each tile's rows in the new cell from the kept offsets. No new device memory. Against the whole call at the strained cell: dE 3.5e-9 to 1.7e-8 eV/atom, dF at most 3.6e-6 eV/Å. MH-1 at 50,820 atoms (8 tiles of at most 12,288), 10 + 30 steps, two rounds: `fix npt` through the pair style 412.4 and 413.2 ms per step, a fixed cell with the virial in every step 410.4 and 413.2, no list build in the measured steps (before: one per step, 491 ms). Status §6.41.

[s621]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#621-tile-gemm-size-buckets-16-november-2026-0410
[s634]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#634-tiled-md-on-the-device-and-where-the-tiled-calls-time-goes-16-november-2026-planmd-o31
[s635]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#635-the-memory-plan-against-what-the-calls-take-and-the-capacity-of-the-rtx-5060-ti-18-november-2026-planmd-o33
[s622]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#622-the-tiled-wavefront-16-november-2026-0500
[s623]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#623-the-receiver-cap-screen-and-the-tiled-calls-overheads-16-november-2026-0600
[s55]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#55-known-limitations

[s615]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#615-the-tile-workspace-16-november-2026-0015
[s616]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#616-tile-lists-kept-and-the-workspace-kept-between-calls-16-november-2026-0040
[s618]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#618-tiled-md-lists-kept-across-steps-16-november-2026-0220
[s636]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#636-the-merge-of-develop-19-november-2026-planmd-o38
[s637]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#637-lammpss-nvt-and-npt-at-the-engines-step-time-19-november-2026-planmd-o40
[s639]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#639-the-benchmarks-warm-up-and-systems-without-a-rebuild-20-november-2026-planmd-o41
[s641]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/STATUS_AND_PROFILE.md#641-barostats-in-tiled-mode-20-november-2026-planmd-o42-d99

### Dispersion

<a id="d3-rows-projections"></a>**d3-rows-projections** (ADOPTED for S6-D04, 16 November 2026, 5060 Ti only). The
bake-off prototype's first layout gave each receiving atom one warp that walked one bin at a time in atom order
and contracted the 5x5 C6 reference table per pair. With bins of a quarter of the cutoff a bin holds a few atoms,
so most lanes idled. Variant 1 sorts the atoms by bin (a radix sort, bin starts on the device), walks rows of bins
along the fastest axis as one contiguous range, and precomputes per receiver u_i(s) = w_i C6ref(s_i, s) and its CN
derivative for every species s in shared memory, so a pair costs a 5-term dot product. Same results (5e-7 eV,
4e-7 eV/A). CN, pairs, CN forces: NbCl5 0.71/2.53/2.11 -> 0.33/1.14/0.97 ms, SrTiO3 1.66/6.77/5.79 ->
0.64/4.22/3.69, water 1.75/7.83/6.69 -> 0.70/4.86/4.24. Untried: a half list (each pair once, atomics on the
sender), splitting rows across lanes of several receivers.

<a id="d3-tail-shorter-cutoff"></a>**d3-tail-shorter-cutoff** (REJECTED as the default, 16 November 2026, 5060 Ti
only). The tail correction (C6 per atom pair from each atom's coordination number, summed per species, integrated
from the cutoff for a uniform density) brings energy and pressure far inside the contract at 20-30 bohr (NbCl5 at
30 bohr: 0.037 meV/atom against 0.583 for the 40 bohr sum), but it does not correct forces, and the force error of
a shorter real-space sum is larger than the 40 bohr sum's on every system (NbCl5 0.024 against 0.0066 meV/A at
30 bohr, water 0.95 against 0.39). Added to the 40 bohr sum it costs nothing measurable and cuts the energy error
40-fold: kept as a selectable option for S6-D05, not as a speed-up.

<a id="d3-shell-every-k"></a>**d3-shell-every-k** (REJECTED, 16 November 2026, 5060 Ti only). The short part to
20 or 25 bohr every step and the shell to 40 bohr every k steps. Stale-force error estimated by moving the atoms as
far as they travel ballistically in k steps at 300 K against a fresh 40 bohr sum: at k = 2 already 0.035 (NbCl5),
0.028 (SrTiO3) and 0.64 meV/A (water, shell from 25 bohr), above the 40 bohr sum's own error of 0.0066, 0.0066 and
0.39. A fresh shell also repeats the coordination-number passes, so small k is slower than the plain sum.

<a id="d3-cn-cutoff"></a>**d3-cn-cutoff** (OPEN, owner decision D73, 16 November 2026, 5060 Ti only). The
coordination-number force pass grows with the cube of its cutoff: with 40 bohr pairs, CN 30 takes 2.01 / 6.68 /
7.76 ms against 2.48 / 8.42 / 9.88 (NbCl5, SrTiO3, water). On NbCl5 and SrTiO3 the errors move by 1e-6 to 1e-4 of
the units in the table; on water the force error moves non-monotonically (0.18 at 35 bohr, 0.21 at 30, 0.39 at
25, 0.57 at 20 against 0.39). Literally CN 30 fails on NbCl5 pressure by 1.7e-6 GPa; with a relative tolerance it
would be the default candidate, to be checked on the full validation set (graphite first).

<a id="d3-pair-production"></a>**d3-pair-production** (ADOPTED, S6-D04, 16 November 2026, 5060 Ti only). The
production kernel is variant 1 with the grid computed on the device at each evaluation, so it is capturable and
follows a changing cell; the timing is a captured graph of the whole evaluation (wrap, sort, three passes). It is
no faster than the prototype and was not meant to be; the energy-only path skips the CN-force pass and the
derivative work (4-6x cheaper), which helps Monte Carlo energy differences.

<a id="d3-atm-first"></a>**d3-atm-first** (ADOPTED, S6-D08, 16 November 2026, 5060 Ti only). The only
implementation of the three-body term, kept because it is correct (within 1e-7 eV/A of simple-dftd3), not because it
is fast: at 20 bohr it costs 4 to 13 times the pair term. The open ideas are in status 6.29; each is to be measured
against this version with the 3x rule before it replaces it.

<a id="d3-split-mesh"></a>**d3-split-mesh** (ADOPTED as an accuracy option, S6-D06, 16 November 2026, 5060 Ti only). The first version of `long_range="split"`. It removes the plain sum's truncation error almost entirely (10 to 300 times smaller in energy, up to 50 times in force on water) but costs 1.0 to 1.6 times the plain 40 bohr sum: the coordination numbers still walk 40 bohr twice (count, then the chain rule), which neither method avoids, and the mesh (2 x channels components, each spread with 512 double atomics per atom, two FFTs, a gather) costs about 5 ms at 5,000 atoms. A 1.0 A mesh saves 0.5 to 2 ms but misses the 1e-5 eV/A force tolerance against the direct k sum on SrTiO3 (1.2e-5). Ideas for the tuning stage (D77): spread every component in one pass, float atomics into shared tiles, batched FFTs, and the CN cutoff (owner, D73).

<a id="d3-walk-reach"></a>**d3-walk-reach** (ADOPTED, S6-D06, 16 November 2026, 5060 Ti only). The bin grid is sized for max(pair, CN cutoff); each pass now walks only the bins its own cutoff reaches (the split sum's 20 bohr pair pass, the three-body list). Single A/B runs, so the gains (1 to 4%) are near noise; kept because it cannot be slower and gives the same sums (the D3 tests pass on the library).

<a id="d3-f32-partials"></a>**d3-f32-partials** (ADOPTED, D77, 16 November 2026, 5060 Ti only). The D3 force path added 10 float64 values per pair (or triangle), and the RTX 5060 Ti runs float64 at 1/64 rate, so forces cost about six times the energy. Per-lane float32 partials flushed to float64 every 32 terms (as the CN kernel already did with 64) halve the plain sum's time and take 25 to 30% off the three-body term, with results equal to 2e-8 eV/A. Summing the energy in float32 as well was tried and dropped: it put the energy-only and forces paths 1.3e-9 to 2.2e-9 apart (bound 1e-9 relative) for about 3% (SrTiO3 3.55 against 3.67 ms). Not measured on an A100, where float64 runs at half rate and the gain should be small.

<a id="d3-dedcn-f32"></a>**d3-dedcn-f32** (ADOPTED, D77, 16 November 2026, 5060 Ti only). A float64-to-float32 conversion runs at float64 rate on consumer GPUs; the chain rule did one per pair. The copy costs one tiny kernel per evaluation. The pair kernel still converts each pair energy to float64 (kept: the energy-only path must give the same energy).

<a id="d3-walk-trim"></a>**d3-walk-trim** (ADOPTED, D77, 16 November 2026, 5060 Ti only). A conservative bound for any cell: a column of bins is a line thickened by its cross-section radius, so a column whose line is farther than cutoff plus that radius holds no pair, and the rest need only the chord's bins (one bin of margin). It removes most of the walk's out-of-range tests but saves only 2 to 8%: the D3 passes are bound by the pairs' own arithmetic (pair kernel 1.83 ms, chain rule 1.09, CN count 0.61 at 5,000 atoms, nsys), not by the distance tests.

<a id="d3-atm-proj"></a>**d3-atm-proj** (ADOPTED, D77, 16 November 2026, 5060 Ti only). Smaller than expected (5 to 6%): the C6 table walk was not the three-body term's bottleneck. It costs 2.5 KB of shared memory per species per block, so it needs the opt-in limit beyond four species and falls back to the old loop beyond about 24 on the RTX 5060 Ti. Next for the three-body term: per-triangle arithmetic (sqrt, powf, the angle factor and its two derivatives).

[d3bo]: https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/docs/validation/dispersion-bakeoff.md
