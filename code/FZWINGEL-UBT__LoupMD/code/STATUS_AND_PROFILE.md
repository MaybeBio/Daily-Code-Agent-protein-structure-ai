# LoupMD Current State, Kernel Profiles, and Open Ideas

Snapshot date: 2026-11-13 (seventh update: generic-path and POLAR speed work S7, 5060 Ti only, section 5.3 and
the ledger's S7 entries; the workstations were ruled out by the owner. Sections 1-2 are from the fifth update.)
Every optimisation tried so far, adopted or not, is indexed in [OPTIMISATION_LEDGER.md](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/OPTIMISATION_LEDGER.md);
a new attempt adds its ledger row and entry together with the numbers recorded here.
Target model of the specialised kernels (sections 1-4): MACE-OMAT-0 medium (float32, 128 channels, l <= 3,
correlation 3, cutoff 6.0 A). S144 (19 November 2026, `JIT_DESIGN.md` stage 5) retired that path. Sections 1-4
record it as it was; every family, OMAT-0 medium included, now runs on the generic path: section 5.
Verified GPUs:
- **RTX 5060 Ti** (`sm_120`, Windows/WSL2 WDDM, CUDA 13, 36 SMs, 32 MB L2)
- **RTX 4000 Ada** (`sm_89`, `leeloo`, Linux, 48 SMs, 48 MB L2; no performance-counter permission, so `ncu` numbers are 5060 Ti only)

---

## 1. Benchmark & Verification Summary

Standard MD benchmark: median of 6 x 256 Langevin steps (300 K, 1 fs, skin 0.5 A, friction 0.01/fs) after 100 warmup steps (`python/bench_md.py`). Every change below was A/B tested in both build orders on both GPUs (`bench_md.py ... LOUP_LIB=<A> LOUP_LIB=<B>` and reversed): on Ada the first run of an ABBA sequence is systematically fastest, which biases order A by ~+0.6% against the new build, so a change is adopted only if it wins or ties in both orders.
Standard single-point gate: 3x MACE float32-vs-float64 rule (`python/test_gate.py` + `NbCl5` 576-atom strained, rattled cell).

| Metric | RTX 5060 Ti (`sm_120`) | RTX 4000 Ada (`sm_89`) |
|---|---|---|
| `NbCl5` 3x3x3 (1,944 atoms, S=2) Langevin | **1.849 ms/step** | **2.054 ms/step** |
| `SrTiO3` 10x10x10 (5,000 atoms, S=3) Langevin | **8.458 ms/step** | **9.27 ms/step** |
| `test_gate.py` (4 configs: `NaCl` c0/c1, `SrTiO3` c0/c1) | PASS (force ratio <= 1.25) | PASS (force ratio <= 1.20) |
| `NbCl5` single-config gate (576 atoms, 1% strain, 0.05 A rattle) | PASS (force 0.51, stress 0.83) | PASS (force 0.49, stress 0.69) |
| `SrTiO3` NVE (10x10x10, 1 fs, 300 K, 1 ps after 200 Langevin steps) | drift -0.00011 meV/at/ps (std 0.00036) | drift -0.00012 meV/at/ps (std 0.00037) |

`bench_md` numbers are the mean of two runs of the final build (Ada run-to-run spread on `SrTiO3` is ~2%: 9.17 / 9.37). The `SrTiO3` 20x20x20 and single-point `evaluate()` timings of the previous snapshot were not re-measured.

System-size scaling (5060 Ti, `SrTiO3` n x n x n, Langevin, after 60 warm-up steps; us per atom-step): 135 atoms 3.00 (0.405 ms/step), 320 atoms 2.18, 1,080 atoms 1.73, 5,000 atoms 1.66-1.68, 20,480 atoms 1.69-1.71, 40,000 atoms 1.71-1.72 (the rebuild-time choices stay R5 spline; `w'` picks 512 threads at 40k atoms). Large systems scale linearly; below ~1,000 atoms fixed latencies dominate (section 4.1).

Timeline on the two standard systems (ms/step, `bench_md.py`):

| Stage | 5060 Ti `NbCl5` | 5060 Ti `SrTiO3` | Ada `NbCl5` | Ada `SrTiO3` |
|---|---|---|---|---|
| Session baseline (pre-CUBIC_PACKED8) | 2.384 | 11.380 | 2.533 | 12.985 |
| + `CUBIC_PACKED8` + `hyb_sm120` + `E_graph` bucketing | 2.187 | 10.458 | 2.353 | 11.764 |
| + receiver-owned i0 forward, i0 bwd prefetch, `DeviceSegmentedSort`, `shift_cart`, `sc1_fused`, spatial reorder (>L2), forked GEMMs | 2.089 | 9.939 | 2.260 | 11.184 |
| + items 12-26 | 1.930 | 8.858 | 2.090 | 10.021 |
| + items 27-29 (shift-free decode, 2^8 radial derivative, 4-receiver spline on `sm_89`) | 1.904 | 8.646 | 2.088 | 9.576 |
| + items 29-31 completed (per-system spline / `w'` variants, own SGEMM) | **1.849** | **8.458** | **2.054** | **9.27** |

---

## 2. Detailed Kernel Profile (Current Build)

Captured with `nsys --capture-range=cudaProfilerApi --cuda-graph-trace=node` over 100 Langevin steps after 50 warmup steps (profiler range opened with `cudaProfilerStart` around `run_langevin`); stage spans are medians over steps of the gaps between the custom kernels (rebuild steps excluded by the median). "Span" is wall-clock GPU time of a stage (GEMM groups overlap on side streams). The spline / `w'` variants are already chosen at the first rebuild of the warm-up. The profiled span is within ~3% of unprofiled `bench_md` (5060 Ti `SrTiO3` 8.23 vs 8.46 ms).

### 2.1 Stage Spans (steady-state non-rebuild step, us)

| Stage | 5060 Ti `SrTiO3` | 5060 Ti `NbCl5` | Ada `SrTiO3` | Ada `NbCl5` |
|---|---:|---:|---:|---:|
| `i0_fwd` (`tabled_outer_sum0_forward_kernel`) | 259.0 | 43.0 | 312.4 | 58.6 |
| `compose0_fwd` GEMMs | 299.7 | 88.8 | 351.7 | 88.7 |
| `sc0_forward` | 105.1 | 24.4 | 156.3 | 29.6 |
| `skip16` + `W_up` GEMMs | 66.5 | 28.7 | 66.0 | 27.2 |
| `spline_forward_inter1` (chosen: R5 / R1 paired / R5 / R4 paired) | 1,927.5 | 314.5 | 2,382.3 | 442.7 |
| `lin1` forward GEMMs | 468.6 | 200.6 | 562.9 | 193.4 |
| `sc1_fused` | 222.4 | 58.0 | 232.7 | 68.3 |
| `lin1` backward GEMMs | 549.7 | 175.7 | 557.8 | 196.7 |
| `wprime_backward_inter1_rcv` | 2,961.0 | 443.3 | 3,168.1 | 510.9 |
| `W_up^T` + skip backward GEMMs | 72.0 | 36.9 | 74.2 | 35.7 |
| `sc0_backward` | 230.9 | 63.0 | 273.8 | 84.8 |
| `compose0_bwd` GEMMs | 368.4 | 87.9 | 337.1 | 88.3 |
| `i0_bwd` (+ fused force/virial assembly) | 523.9 | 109.7 | 645.8 | 135.6 |
| Integrator, active-edge compaction, memset, gaps | 126.2 | 45.1 | 140.8 | 60.4 |
| **Step span** | **8,232.0** | **1,723.6** | **9,267.6** | **2,025.5** |
| GEMM groups (sum of spans) | 1,825.0 (22.2%) | 618.6 (35.9%) | 1,949.7 (21.0%) | 630.0 (31.1%) |

GPU idle inside a step is now ~20 us (5060 Ti `SrTiO3`); the 120 us/step of idle caused by split-K memset nodes is gone (item 22).

### 2.2 Top Kernels by Time per Step (us, kernel sum incl. side streams)

| Kernel | 5060 Ti `SrTiO3` | 5060 Ti `NbCl5` | Ada `SrTiO3` | Ada `NbCl5` |
|---|---:|---:|---:|---:|
| `wprime_backward_inter1_rcv` | 3,009 | 462 | 3,188 | 512 |
| `spline_forward_inter1` | 2,008 | 331 | 2,381 | 442 |
| own `sgemm128_kernel` | 1,507 | 424 | 226 | 0 |
| `fm_tf32x3_rc_*` / `fm_tf32x3_rr_*` (hybrid) | 417 / 288 | 137 / 57 | 1,179 / 750 | 434 / 491 |
| cuBLAS SIMT `Kernel2` / `ampere_sgemm` / `magma` | 352 / 0 / 33 | 467 / 0 / 0 | 0 / 538 / 0 | 0 / 60 / 0 |
| `tabled_outer_sum0_backward_kernel` | 537 | 111 | 649 | 134 |
| `tabled_outer_sum0_forward_kernel` | 272 | 50 | 314 | 58 |
| `sc0_backward` / `sc1_fused` / `sc0_forward` | 238 / 226 / 110 | 64 / 60 / 25 | 277 / 235 / 158 | 86 / 68 / 30 |
| `scatter_active_edges` + `compute_and_count_active` | 54 + 47 | 7 + 12 | 40 + 51 | 7 + 16 |
| `langevin_first_half` | 10.6 | 7.8 | 13.4 | 8.1 |
| **Kernel sum / step** | **9,151** | **2,232** | **10,060** | **2,370** |

### 2.3 Neighbour Rebuild (kernel medians per rebuild)

Cadence at skin 0.5 A, 300 K, 1 fs: ~1 rebuild every 15 steps on `SrTiO3`, every ~22 on `NbCl5`, every ~4 on water (5,184 atoms; never pipelined at this skin, measured S34).

| Kernel | 5060 Ti `SrTiO3` | Ada `SrTiO3` | 5060 Ti `NbCl5` | Ada `NbCl5` | 5060 Ti water |
|---|---:|---:|---:|---:|---:|
| `fill_neighbors_kernel` (S34 lane groups on `sm_120`; was 283 / 169 / 273) | 215 | 401 | 76 | 186 | 226 |
| `count_neighbors_kernel` (S34; was 150 / 115 / 166) | 77 | 209 | 34 | 150 | 76 |
| `gather_sorted_edges_kernel` | 37 | 46 | 7 | 9 | 21 |

Ada columns are the one-thread-per-atom kernels (`*_scalar_kernel` since S34), measured before S34.

### 2.4 Kernel Resource Usage (`cuobjdump -res-usage`; shared includes the 1 KB `sm_120` driver reserve)

| Kernel | `sm_120` Reg / Stack / Smem | `sm_89` Reg / Stack / Smem |
|---|---|---|
| `wprime_backward_inter1_rcv` (`512, 2`; 256 or 512 threads) | 64 / 8 / 23,552 B (4 B spill outside the channel loop) | 64 / 0 / 22,528 B |
| `wprime_backward_inter1` (`256, 4`, N < 512 fallback) | 64 / 0 / 24,388 B | 64 / 0 / 23,364 B |
| `spline_forward_inter1<1, paired / unpaired>` (`128`) | 96 / 79 regs, 3,584 B | 122 / 72 regs, 2,560 B |
| `spline_forward_inter1<4, paired / unpaired>` (`512`) | 123 / 94 regs, 11,264 B | 126 / 93 regs, 10,240 B |
| `spline_forward_inter1<5, unpaired>` (`640`) | 96 / 0 / 13,824 B | 95 / 0 / 12,800 B |
| `sgemm128_kernel` (`256, 2`, own SGEMM; + 48 KB dynamic) | 128 / 0 / 1,024 B | 128 / 0 / 0 B |
| `tabled_outer_sum0_forward_kernel` (`128`, warp per receiver) | 96 / 0 / 9,216 B | 80 / 0 / 8,192 B |
| `tabled_outer_sum0_backward_kernel` (`128`) | 80 / 0 / 11,456 B | 80 / 8 / 10,432 B |
| `sc1_fused` (`128, 4`) | 113 / 0 / 2,128 B | 104 / 0 / 1,104 B |
| `sc0_forward` (`128`) | 72 / 0 / 1,056 B | 72 / 0 / 32 B |
| `sc0_backward` (`128, 4`) | 128 / 0 / 1,040 B | 128 / 32 / 16 B |
| `scatter_active_edges_kernel` (`128`) | 40 / 0 / 0 B | 40 / 0 / 0 B |
| `compute_and_count_active_kernel` (`128`) | 40 / 0 / 0 B | 40 / 0 / 0 B |
| `fill_neighbors_kernel` / `count_neighbors_kernel` (`128`, 8 lanes per atom, `sm_120`) | 62 / 44, fill `16 x nscan` ints dynamic | – |
| `fill_neighbors_scalar_kernel` / `count_neighbors_scalar_kernel` (`32`, other GPUs) | 64 / 48 | 64 / 52 |

The `sm_89` stacks are frames without spills (`ptxas -v`: 0 bytes spill stores/loads).

### 2.5 Nsight Compute Facts (`SrTiO3` 5k, RTX 5060 Ti, current kernels)

| Kernel | Time | Occupancy | Key counters |
|---|---:|---:|---|
| `wprime_backward_inter1_rcv` | 3.01 ms | 63% | issue slots 80% busy (issue-bound, `not_selected` dominant); 760 M instructions (818 M before items 27-28); L2 5.3 GB |
| `spline_forward_inter1<1>` | 2.04 ms | 41% (96 regs) | L2 83%, issue 71%; L2 traffic 3.92 GB, L1 hit 5%. `<4>`: 33% occupancy, L1 hit 36%, L2 2.66 GB, 1.96 ms (`SrTiO3`) but `NbCl5` +7-10% |
| `tabled_outer_sum0_backward_kernel` | 0.56 ms | 37% | L1 requests per edge ~29 -> ~11 (SH staged, `float2` channel pairs); equal time at 64 and 100 KB carveout |
| `tabled_outer_sum0_forward_kernel` | 0.25 ms | 39% | L1 hit 53% at the 64 KB configuration (33% at the default 100 KB, 305 us) |
| `scatter_active_edges_kernel` | 0.05 ms | 80% | no SH output (item 24); was 0.11-0.16 ms |

---

## 3. Current Architecture & Hardening Status

### 3.1 Implemented Optimisations
1. **`CUBIC_PACKED8` (`d_cubic_packed8_1`)**: `wprime_backward_inter1` reads an 8-byte exact cubic table (`20/19/12/8` signed quantized coefficients around `s = t - 0.5`, 5-bit shared exponent clamped to `emax - 31`) instead of 16-byte `float4`.
2. **Hybrid `tf32x3` + `fp16` cubin for `sm_120`**: `cubins/tf32x3_hyb_sm120.cubin`; `sm_80` cubin used on Ada (`sm_89`).
3. **`E_graph` bucketing + `cub::DeviceSegmentedSort::StableSortPairs`**: edge grid rounded to 8192; rebuild sort is ~16 us instead of ~2.3 ms.
4. **Receiver-owned i0 forward**: register accumulation per sender-species run, zero writes for absent species; eliminates atomics and the 61 MB per-step `S0/D0` zero-fill. Guarded at rebuild end by `check_row_species_order_kernel`.
5. **Lane-parallel metadata prefetch in i0 backward**: the chunk's metadata is loaded across lanes and broadcast via shuffles.
6. **`sc1_fused`**: fuses `sc1_forward`, `128->16->1->16->128` readout forward/backward, and `sc1_backward` into one `N x 128` launch.
7. **Cartesian float64 shifts (`d_shift_cart`)**: precomputed at rebuild; removes cell dependence from the force graph.
8. **L2-gated spatial atom reorder**: above `N * 4096 > l2_bytes`, Morton reorder within species groups every 16th rebuild.
9. **Side-stream GEMM fork/join**: 8 non-blocking side streams with per-stream 4 MB cuBLASLt workspaces.
10. **Non-destructive `evaluate()`**: keeps velocities, skips rebuilds when `max_disp < skin/2` and cell unchanged.
11. **GEMM autotuning**: up to 32 cuBLASLt candidates + 3 hybrid tiles; fork disabled during autotune.
12. **1-receiver-per-block `wprime_backward_inter1_rcv`** (`N >= 512`, and every `N` on `sm_120` since S96; the edge-tiled kernel stays for `N < 512` on other GPUs): stages the receiver's q once per block; -170 us on both GPUs.
13. **Packed edge arrays**: `act_vec_len` (`float4` x, y, z, r) and `act_t_sx` (`float2`).
14. **i0 backward fused with force/virial assembly (T5)**: `force_virial_assemble_kernel`, `d_dsh0`, `d_dr0` removed; 32-edge warp chunks.
15. **Float32 pre-test + 32-thread blocks in `count`/`fill_neighbors` (T3)**: borderline pairs re-checked in float64; rebuild 1,222 -> 510 us (5060 Ti), 1,121 -> 684 us (Ada).
16. **Memory aliasing + persistent GEMM plan cache**: `dm1 -> m1`, `dh0 -> h0`, `dS0 -> S0`; plans in `~/.cache/loupmd/plans_<gpu>_sm<cc>_lt<ver>_hyb<0|1>.bin` (`LOUP_RETUNE`, `LOUP_CACHE_DIR`); cold-start `evaluate` 1.3 s -> 0.21 s (5060 Ti), 0.76 s -> 0.05 s (Ada).
17. **Per-arch L1 carveouts** (`tune_l1`): smallest shared-memory configuration that keeps occupancy for the gather kernels (values measured per arch; see `engine.cu`).
18. **Selective cold-L2 GEMM autotune**: operands larger than half the L2 are timed with a flushed L2 (they stream from DRAM in the force pass); Ada's `lin1_fwd` group 672 -> 575 us.
19. **Coalesced SH stores** in `scatter_active_edges` (superseded by item 24).
20. **Paired-edge `spline_forward_inter1`**: two consecutive edges of a receiver that read the same table slab (sorted by `(pair, r)`) decode it once: table loads per edge 1 -> 0.805 (`SrTiO3`), 0.927 (`NbCl5`); spline -7% (5060 Ti), -3% (Ada) on `SrTiO3`.
21. **Channel-major staged q in `wprime_backward_inter1_rcv`**: `s_q[channel * 44 + slot]` (11 x 16 B, odd) so each lane reads its 40 q values as 10 conflict-free `LDS.128`; w' -1.7% (5060 Ti), -2.5% (Ada).
22. **No split-K cuBLASLt algorithms** (`CUBLASLT_MATMUL_PREF_REDUCTION_SCHEME_MASK = NONE`; plan cache `LOUPPLN3`): their per-launch workspace memsets left the 5060 Ti idle ~120 us per step; also deterministic.
23. **i0 backward SH staging + `float2` channel pairs**: the chunk's SH are staged in the warp's result rows (stride 20, `LDS.128` broadcast), coefficients and dS0 rows load as `float2`; 685 -> 564 us (5060 Ti), 736 -> 668 us (Ada).
24. **SH computed where staged, not stored** (`edge_sh16`): `scatter_active_edges` no longer writes 64 B/edge (24 MB per step at 5k atoms); i0 forward/backward and spline forward compute the 16 values from `act_vec_len` while staging. Dead `edge_sh3_forward_kernel` and `common_kernels.cu` removed; rebuild sort key scratch moved to `d_edge_force_1`.
25. **Warp-per-receiver i0 forward**: 4 receivers per 128-thread block, 2 channels per lane (`float2` coefficient loads, one SH broadcast per two channels), per-edge D0 term at staging; 390 -> 245 us (5060 Ti, 64 KB carveout), 415 -> 304 us (Ada).
26. **Langevin integrator**: first half launched with 32-thread blocks (its FP64 Box-Muller is FP64-throughput bound on consumer GPUs: 14.9 -> 8.0 us on `NbCl5`), step-counter increment folded into the second half (one graph node less); random stream bit-identical.
27. **Shift-free 8-byte cubic decode in `w'`**: the loader packs each coefficient's mantissa bits at their float position (`x = u0<<3 | rotr(u2<<11, 20)`, `y = u1<<4 | rotr(u3<<15, 19) | eb<<23`), so a coefficient decodes as one `LOP3` (mask + OR with the biased exponent) or one funnel shift + `LOP3`; inner loop 480 -> 448 static instructions, `w'` 3,177 -> 3,065 us (5060 Ti). MD: 5060 Ti -0.5% / -1.2% (A), -0.8% / -1.3% (B); Ada +0.4% / -0.8% (A), -0.6% / -1.1% (B) (`NbCl5` / `SrTiO3`).
28. **`w'` radial derivative scaled by 2^8**: `radial_dt = fma(ds3', d3, fma(ds2', d2, d1))` with `ds2' = 2^8 ds2`, `ds3' = 2^8 ds3` and one `2^-8` at the edge epilogue (bit-identical: power-of-two scaling), dropping one `FMUL` per path; `w'` 3,069 -> 3,010 us, 774 -> 760 M instructions (5060 Ti). MD: 5060 Ti -0.1% / -0.5% (A), -0.5% / -0.6% (B); Ada tie.
29. **Multi-receiver spline blocks, chosen per system** (`spline_forward_inter1<R, PAIR>`, `choose_spline_rpb`, `tune_rebuild_variants`): with R consecutive receivers per 128R-thread block (per-receiver named barriers, smallest shared-memory carveout), receivers of a symmetric crystal walk the same slabs at the same time and the later reads hit L1 (`SrTiO3` 5060 Ti, R = 4: L1 hit 5% -> 36%, L2 3.92 -> 2.66 GB). The block keeps all its warps' registers until its slowest receiver finishes, so the gain depends on the system, and so does the paired-edge decode (item 13; it costs 17-30 registers). Five variants are compiled: R = 1 and R = 4 with and without pairing, and R = 5 unpaired (640 threads at 94-96 registers: 20 warps). The default is R = 4 paired where it keeps the resident warp count of R = 1 paired (`sm_89`), else R = 1 paired; at the first MD rebuild of a system (thermalised positions; the ideal starting lattice favours sharing everywhere) all five are timed on the last force pass's inputs and the fastest is adopted if >= 2% faster than the current one (`LOUP_DEBUG_SPLINE=1` prints the timings).
    Spline us at the first rebuild (R1 / R1 paired / R4 / R4 paired / R5 -> choice): 5060 Ti `SrTiO3` 2,029 / 1,953 / 1,828 / 1,847 / 1,798 -> R5; 5060 Ti `NbCl5` 317 / 316 / 330 / 344 / 319 -> R1 paired; Ada `SrTiO3` 2,601 / 2,593 / 2,260 / 2,270 / 2,187 -> R5; Ada `NbCl5` 431 / 418 / 411 / 423 / 419 -> R4.
    MD, step by step (A / B orders): occupancy rule only (R1 paired vs R4 paired) vs item 28: Ada `NbCl5` +1.5% / +0.3%, `SrTiO3` -3.1% / -3.6% (5060 Ti unchanged). + rebuild-time choice between those two: 5060 Ti `NbCl5` +0.1% / -0.3%, `SrTiO3` -0.8% / -0.8%; Ada tie. + unpaired and R5 variants: 5060 Ti `NbCl5` +0.4% / -0.2%, `SrTiO3` -0.1% / -0.3%; Ada `NbCl5` +0.8% / -0.2%, `SrTiO3` -0.4% / -0.9% (Ada order A carries the ~+0.6% first-run bias).
30. **Own SIMT SGEMM as an autotune candidate** (`src/sgemm.cu`, `loup::sgemm128`): 128 x 128 x 16 block tiles, 256 threads with 8 x 8 outputs each, 3-stage `cp.async` pipeline (A kept m-major, so a warp's A fragment reads are 2-address broadcasts; B k-major), 126 registers, 48 KB shared memory, 2 blocks (16 warps) per SM where cuBLAS' SIMT kernels run 8 warps at 200-210 registers. A transposed B operand is always a model weight, so `weight_kn` keeps a [K, N] copy per weight (made in the uncaptured autotune pass). Each output is one in-order `fmaf` chain over k (bit-identical to `cublasSgemm` on all tested shapes). `sgemm_rm` times it next to the cuBLASLt heuristics and the hybrid cubins (plan cache `LOUPPLN4`, `use_own`; `LOUP_DEBUG_GEMM=1` prints every choice). Cold-L2 microbenchmark (5060 Ti, us): `lin1` l=1 / l=2 / l=3 forward 132 / 196 / 181 (cuBLASLt's pick 136 / 207 / 175, `cublasSgemm` 236 / 370 / 185); `compose0` forward (M = 48,000, K = 192) 195 vs 210. It is picked for the large `lin1` / `lin1^T` / `compose0` forward products on the 5060 Ti. N = 192 (`compose0` backward) runs 128 x 64 tiles instead of a half-empty 128 x 128 tile (111 registers, 36 KB): the 5060 Ti autotune then picks it over the hybrid cubin for all seven `SrTiO3` products (sum 297 -> 248 us); MD tie on both GPUs (5060 Ti `NbCl5` +0.5% / +0.0%, `SrTiO3` -0.1% / -0.4%; Ada +1.2% / +1.0% (A), +0.0% / -0.2% (B)).
    MD: first version (register-staged, 2 stages) vs item 29: 5060 Ti `NbCl5` -1.6% / -2.0%, `SrTiO3` -0.6% / -0.7% (A / B); Ada +0.8% / +0.2% (A), -0.2% / -0.3% (B). `cp.async` version vs the first: 5060 Ti `NbCl5` -1.4% / -1.3%, `SrTiO3` -0.1% / -0.4%; Ada +1.1% / +0.5% (A), -0.3% / +0.0% (B).
31. **`w'` block size chosen per system** (`wprime_backward_inter1_rcv` at `(512, 2)` launch bounds, warp stride `blockDim.x / 32`, launched with 256 or 512 threads; timed with the spline variants in `tune_rebuild_variants`): 512-thread blocks stage one receiver's q per 16 warps, halving the shared memory per SM (more L1: 5060 Ti L1 hit 5.9% -> 10.5%, L2 5.27 -> 5.05 GB). Ada `SrTiO3` `w'` 3,230 -> 3,130 us (picked); 5060 Ti 3,009 -> 3,034 us and Ada `NbCl5` 519 -> 511 us (within 2%: 256 kept). MD: 5060 Ti tie (+0.6% / -0.1% `NbCl5`, -0.1% / -0.1% `SrTiO3`); Ada `SrTiO3` -1.0% / -1.2%, `NbCl5` +1.4% (A, first-run bias) / +0.2% (B).

32. **`w'` cubic decode with the bias folded into the polynomials** (`python/gen_kernels.py`, `LOUP_GEN_DECODE_FOLD`, on by default since 13 Nov): the four `raw_k - hb` subtractions per path become two FFMA with per-edge bias factors; `wprime_backward_inter1_rcv` 1,000 -> 976 instructions on `sm_120` (the 8-byte stack spill disappears), 1,016 -> 1,000 on `sm_89`. `bench_md.py`, a-b-b-a runs: 5060 Ti `SrTiO3` 0.9929 / 0.9948 / 0.9925 and `NbCl5` 0.9951 / 0.9938 / 0.9965 (three runs; about 8.22 and 1.80 ms/step); Ada a tie (1.0015 / 0.9955, two runs). The default gate passes on both GPUs with ratios inside its own run-to-run spread; 47 tests pass on the 5060 Ti and 46 on the Ada (OMAT-0 small skipped there), and the full gate passes for all eight model sets on the 5060 Ti (78 rows, worst force ratio 1.45, stress 2.27). Ledger: [wp-decode-bias-fold](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/OPTIMISATION_LEDGER.md#wp-decode-bias-fold).

### 3.2 Correctness / API Fixes Applied (from code review)
- **H1**: Langevin Philox offset advanced by `step * 16` (12 outputs consumed/step; previously overlapped at `step * 2`).
- **H2**: Langevin `friction_per_fs` converted via `/ ASE_FS` to match ASE units; header documents ASE velocity units.
- **H3**: `d_step_counter` zeroed only in `loup_set_system` (persists across `run_*` calls).
- **H4**: Cubic-table exponent span > 31 clamped to `emax - 31`; unused `float4` fallback removed.
- **H5**: All C entry points wrapped in `guarded(...)` (closes open stream captures, resets `gemm_stream`/`gemm_ws`, returns `-1`).
- **L3**: `ensure_cub_tmp` invalidates graphs on growth; `cudaGetLastError()` checked after warm-up pass and each rebuild.
- **L4**: `fill_neighbors_kernel` guards its cursor with `cursor < row_ptr[i + 1]`.
- **Review round 5** (`loupmd-review-20261112.md`, fifth pass):
  - F1: `test_gate.py` adds the 576-atom `NbCl5` cell (receiver-owned `w'`) and gates every forced kernel path: `LOUP_SPLINE_VARIANT=R1|R1p|R4|R4p|R5`, `LOUP_WPRIME_THREADS=512`, `LOUP_WPRIME_RCV=1` on the small cells, `LOUP_REORDER=0|1` (reorder on vs off agree to 5e-7 eV/A).
  - F2: `ensure_cub_tmp` synchronises the stream before freeing. F3: the per-system variant timing is reported as `LoupMDStats::tune_ms` and excluded from `step_ms` (aliasing of the timed buffers documented). F4: the plan cache file name carries an FNV hash of the library file; plans whose winner leads by < 3% are not persisted; `LOUP_CACHE_DIR` / `LOUP_RETUNE` documented in `include/loupmd.h`. F5: `loup_debug_tensors` removed (unused, model-specific). F6: scope guards for the autotune buffers and events. F7: the spline's named-barrier conditions are stated in the generator, with `static_assert(R <= 15)`.
  - M1: the MD loop starts unpipelined (each step's skin check is read before its force pass: exact for any skin, including 0) and switches to the pipelined loop once 4 x the largest per-step displacement (tracked on the device by the first-half kernels) is below skin/2; the pipelined check lowers its threshold by three times that displacement (two steps of lag, one of margin for a step longer than any so far: with only the lag, 1 of ~1,600 steps of the 300 K benchmarks ran on an incomplete list), and any step that still did is counted in `LoupMDStats::dangerous_builds` (and drops back to the unpipelined loop; 0 in every benchmark of section 5 on both GPUs). MD speed unchanged (`bench_md.py`: 5060 Ti `NbCl5` 1.836, `SrTiO3` 8.454 ms/step, 1.832 / 8.441 with the two-step margin; Ada 2.056 / 9.262).
  - M2: `loup_set_system` validates Z, masses and skin before freeing the old system. M3: singular / zero / non-finite cells and non-finite positions or velocities are rejected; the engine is documented as fully periodic.
  - M6: bundles are a self-describing container (`LOUPC001`, `python/bundle.py`, `src/bundle.cu`): named, typed, shaped arrays plus a meta text entry (architecture, exporter version, model sha256, kernel signature); every array is shape-checked, truncated files and trailing bytes are rejected, files are closed on every path; `ScaleShift` shift is folded into E0; the bundle cache key is the model's content hash + species + head + path + exporter version; the specialised bundle must match the compiled kernels' signature (`generated_kernels_signature.h`).
  - M7: `tests/` (pytest): NVE energy conservation, skin list vs rebuild-every-step trajectory, hot small-skin Langevin without dangerous builds, `tune_ms` reporting, evaluate-after-MD, and the error paths (unknown species, bad masses / skin / cell / positions / velocities, MD without a system, truncated / padded / missing bundles); `tests/test_gate_wrapper.py` runs the gate. 24 tests pass on both GPUs.
- **Review round 6** (`loupmd-review-20261112.md`, sixth pass; fixed 13 Nov 14:00, each with a test that failed first). Verified on both GPUs: 35 tests pass; the gate passes for every family on the 5060 Ti (worst force ratio 1.31, stress 1.95) and for 7 of 8 sets on the Ada (1.31 / 1.49; OMAT-0 small skipped, its model file is not on `leeloo`); `bench_md.py` unchanged on the 5060 Ti (NbCl5 1.81, SrTiO3 8.33 ms/step; not re-timed on the Ada).
  - S1: the unpipelined skin check also reports whether any atom is beyond the pipelined (three-step) threshold (bit 4 of the flag, `check_skin_kernel`); the loop switches to pipelining only if that bit is clear or the list was rebuilt in the same step. Before: 9 force calls on an incomplete list in 60 switches of `test_switch_to_pipelined_loop_never_uses_an_incomplete_list`; now 0. `LoupMDStats::pipelined_steps` reports how many steps ran pipelined.
  - S5: `PolarLR::set_cell` reports every cell change, so the force graph is re-captured and no longer carries the first cell's volume factors (NaCl 2x2x2, POLAR-1-S, strain 3e-4 on the same engine: 1e-6 eV/atom, 9e-5 eV/A and 3e-7 eV/A^3 against a fresh engine before; identical now). `test_polar_energy_follows_a_small_cell_change_on_the_same_engine`.
  - S6: `python/loupmd.py` stores the atom count only after `loup_set_system` succeeded and refuses arrays of the wrong shape (before: a rejected `set_system` of another size made the next `evaluate` write past its arrays; the test process segfaulted).
  - S7: a generic model's pass also runs when no pair lies within the cutoff (isolated atoms: MACE-MH-1 was off by 0.56 eV per atom, MACE-POLAR-1-S by 0.64 eV; MACE-OFF23 small and OMAT-0 small were unaffected). `test_generic_model_without_neighbour_pairs_matches_mace`.
- **Review round 6, second batch** (13 Nov 14:20-14:50; S8, S3 and the build layout). Verified on both GPUs: 47 tests pass on the 5060 Ti and 46 on the Ada (OMAT-0 small skipped there: its model file is not on `leeloo`); the gate passes for all eight model sets on the 5060 Ti (78 rows, worst ratios 1.45 / 2.27) and for seven of eight on the Ada with freshly exported bundles (72 rows, 1.31 / 1.18).
  - S8, certificates: `export_omat0.py` now refuses a bundle whose interaction-0 table or interaction-1 spline is less accurate than the float32 network (`rad.certify` and the `rspline.fit` certificate, both <= 1; the SrTiO3 set gives 0.28 and 0.49). `rad.fit`'s `fit_error` is not the criterion: the real table has pieces at the deepest level with 4e-5 against a tolerance of 1e-7 and still certifies.
  - S8, kernel signature: the signature now ends in the hashes of the two factored product programs (`:p0=dd662f9d3a2b5b2b:p1=ae0a447b65f4fcd4`), written by `gen_kernels.py` and by the exporter and compared by the loader, so a change of FastMACE's factoring between generation and export is refused. Regenerating the kernels gives a byte-identical `generated_kernels.cuh`; `gen_kernels.py` needs the `mace_cueq_oeq` environment (openequivariance). Exporter version 4.
  - S8, cache key: `loupmd.exporter_fingerprint()` (hash of the four exporters, `bundle.py` and the signature header) replaces the manual `EXPORT_VERSION`; every cached bundle is re-exported once.
  - S3, tests: a replica test for five families (a cell against its periodic replica of about 2,000 atoms; Ada: energy within 8e-7 eV/atom, forces within 5e-6 eV/A for the local models and 7e-4 eV/A for POLAR-1-S) and NVE conservation for MH-1, OFF23 small and POLAR-1-S (drift 0.003, -0.05 and -0.0002 meV/atom/ps). `tests/test_export.py` covers the certificates, the signature and the cache key.
  - Build: one object directory per architecture (`build/<CUDA_ARCH>/`); `make CUDA_ARCH=sm_89 objects` compiles for linking on `leeloo`.

### 3.3 Ruled Out (Measured)
- **T2 / 4-byte far-edge table rows**: slower on both GPUs (5060 Ti `w'` 3,286 -> 3,316 us, spline 2,211 -> 2,242 us; Ada `w'` 3,561 -> 3,628 us, spline 2,974 -> 3,075 us).
- **T1 / 2-channel vectorized `w'`**: -1.6% at `(256, 3)` on 5060 Ti, +2.3% on Ada.
- **Pre-transposed forward GEMM weights (old idea 1)**: 5060 Ti tie, Ada +1.0% / +0.3%.
- **`sh` shuffle broadcast in i0 backward (old idea 3)**: tie; superseded by item 23 (staged SH).
- **`spline_forward` `(128, 7)` / min-blocks 5 on `sm_89`**: spills; Ada +17% / +3%.
- **T4 grouped species GEMM (`fm_tf32x3_species_rr_64x64`)** for `compose0_fwd` + `skip16`: 5060 Ti +1.7% (`NbCl5`) / +0.8% (`SrTiO3`); the grouped launch is slower than the forked per-species GEMMs.
- **T6 per-atom energy array**: +0.5% / +0.1% (5060 Ti); the extra reduction launch costs more than the removed atomics.
- **T7 receiver-owned i0 backward**: +1.8% / +1.1% (5060 Ti); per-chunk edge parallelism beats per-receiver runs.
- **Paired edges in `w'`**: instructions -3% to -6% but 64 -> 80/128 registers (spills at 64); 3.23 -> 3.28/3.35 ms.
- **2/4-pass channel staging in `w'`** (smaller `s_dout`, more L1): 3.23 -> 3.40 / 3.80 ms.
- **Interaction-1 chain split into two receiver halves on two streams** (spline/GEMM/w' overlap) and high-priority GEMM streams: 5060 Ti +0.9% (`NbCl5`) / +0.7% (`SrTiO3`).
- **Global cold-L2 autotune** (all GEMMs timed cold): Ada `NbCl5` +2.9%; kept only for operands larger than half the L2 (item 18).
- **Receiver remap for spline L1 locality** (blocks strided over the receiver range): tie.
- **`spline_forward` 16-edge tiles**: tie.
- **Single-pass active-edge compaction** (decoupled look-back over 4-row tiles, pass-1 vectors cached in shared memory): kernel 96 -> 80 us on 5060 Ti `SrTiO3`, equal on `NbCl5`; MD tie on both GPUs in both orders, so the simpler count + scan + scatter path stays.
- **Interaction-1 chain over L2-sized receiver chunks** (spline + `lin1` + `sc1` + `lin1^T` + `w'` per chunk so `m1`/`dm1` stay in L2): 5060 Ti 1,700-atom chunks +2.4% / +0.2%, 1,000 +2.4% / +1.1%, 650 +2.6% / +2.8% (`NbCl5` / `SrTiO3`); per-chunk launch and tail costs exceed the DRAM savings (the `lin1` GEMMs run at ~50% DRAM, latency-limited).
- **`w'` scalar-path `x0` hoisting** (accumulate the `x0`-scaled pull terms of the four `a = 0` paths, multiply once per channel): -2 M instructions, but spills at 64 registers (3,016 -> 3,086 us) and is still slower at `(256, 3)` / 80 registers (2,992 -> 3,018 us).
- **`w'` `(256, 3)` launch bounds** (80 registers, 50% occupancy): 5060 Ti 3,013 -> 2,992 us, Ada 3,184 -> 3,184 / 3,221 us; below A/B resolution.
- **Paired 5-receiver spline blocks** (640 threads at 96 registers): spill 48-72 B and lose to R = 1 / R = 4 (the unpaired R = 5 of item 29 fits without spills). Timing R = 1 vs R = 4 in the uncaptured setup pass picks R = 4 for `NbCl5` too (the ideal starting lattice shares slabs), hence the rebuild-time choice of item 29. Lockstep R = 2/4 (block-wide barriers, max tile count) is slower than per-receiver named barriers.
- **SM-local persistent `w'`** (grid = resident blocks, receivers handed out from per-SM contiguous ranges via `%smid` and atomic cursors, stealing at the end, so co-resident blocks work on neighbouring receivers): L1 hit 5.7% -> 12%, L2 bytes unchanged (5.3 -> 5.4 GB), 40 B stack from the extra loop state; 3,014 -> 3,240 us (5060 Ti).
- **Reversed block order in the kernels between GEMMs** (spline, `sc0_forward`, `sc1_fused`, `w'`, `sc0_backward`, i0 forward/backward walk receivers from the top, so they first read the rows the preceding GEMM wrote last and leave the rows the next GEMM reads first in L2): step span 8,274 -> 8,285 us (5060 Ti `SrTiO3`), no stage gained more than 6 us.
- **SGEMM variants** (microbenchmark / MD, 5060 Ti): `cp.async` 4 stages with BK = 8: 1.2-1.5x slower than BK = 16 (twice the barriers, 32-byte row segments); register-staged with BK = 8 or 1 block per SM: 5-30% slower; extra 64 x 128 and 128 x 64 tiles as autotune candidates (for small M and N = 192): picked in isolation but `NbCl5` +1.6% / +0.8% in the pass; 64 x 128 tiles for every N = 128 product (cold microbenchmark 7-8% faster than 128 x 128 on the 5060 Ti: `lin1` l=1/2/3 forward 115 / 181 / 172 vs 126 / 196 / 185 us; on Ada still behind `cublasSgemm` for l=1/2): MD `NbCl5` +1.7% / +1.8%, `SrTiO3` +0.5% / +0.8% (5060 Ti), Ada +1.1% / +0.2% (A), -0.0% / -0.2% (B). Isolated cold timings of these tile shapes do not carry over to the concurrent GEMM groups.
- **Row-chunked hybrid GEMM for cold operands** (launch the 64-wide hybrid tiles per quarter-L2 row chunk so the second column tile re-reads A from L2): never chosen by the cold autotune on either GPU (Ada `lin1` forward stays on cuBLASLt at 148 / 228 / 209 us).
- **i0 backward micro-variants** (5060 Ti `SrTiO3`; SASS stall sampling puts ~14% of the samples on the first FFMA consuming the edge's coefficient loads): next edge's coefficients prefetched into registers (96 registers): 551 -> 571 us; coefficient loads moved to the top of the edge iteration (80 registers): 554 -> 564 us; `grad_a` summed in 4 interleaved partial sums: 554 -> 626 us (+4 M instructions, worse schedule).
- **`w'` table loads without L1 allocation** (`ld.global.nc.L1::no_allocate`, to keep L1 for the sender rows): L1 hit 9.7% -> 1.3%, L2 5.06 -> 5.53 GB, 3,022 -> 3,120 us (5060 Ti); adjacent warps do re-read table rows through L1.
- **GEMM groups serialised** (no side streams): 5060 Ti `NbCl5` +5.7% / +5.0%, `SrTiO3` +2.1% / +2.0%: the concurrent lanes matter.
- **Per-group own-SGEMM policy tuned in context** (products of a fork group collected; at a second uncaptured pass each group is timed whole under three policies: as autotuned per product / own wherever eligible / never own; the fastest kept per group signature). Group timings differ a lot from the per-product picks (e.g. `SrTiO3` `lin1^T` group 637 -> 552 us with own everywhere, timed as a captured graph with a warm L2), but MD gained only 5060 Ti `NbCl5` -0.4% to -0.8%, `SrTiO3` +0.1% / +0.2%, Ada tie in both variants (stream-timed, graph-timed); with a cold L2 per launch the policies mostly tie and the timings get noisy. Not worth the collection / replay machinery.
- **`sc0` per species overlapped with the other species' compose0 products** (forward: `sc0_forward` of species s on its l = 3 lane after its four products; backward: `sc0_backward` of species s, then its four products, while the next species' `sc0_backward` runs; 16 side streams): 5060 Ti `SrTiO3` i0 forward end -> spline start 470 -> 489 us, `w'` end -> i0 backward start 600 -> 647 us (the DRAM-bound `sc0` kernels compete with the products); `NbCl5` -4 / +1 us.
- **Other earlier drops**: receiver-warp segmented float64 force reduction, 2-edge unroll in spline (pre-pairing), `sc0_backward` `(128, 3)`, overlapping `skip16` GEMMs across spline, per-species i0 forward, cubic table in forward, Morton reorder below L2.

---

## 4. Open Ideas & Priorities

### 4.1 Remaining Performance Opportunities

All 13 ideas of the previous list are resolved: adopted (2, 5, 7, 9, 10, 13 = items 12-16), ruled out (1, 3, 4, 6, 8, 12; section 3.3), or deferred (11, below).

| Priority | Idea | Target & Estimate | Notes / Falsifier |
|---|---|---|---|
| **1** | **Fuse `lin1` into the interaction-1 kernels** | `m1`/`dm1` are `N x 4864` floats (97 MB at 5k atoms) written by spline / `lin1^T` and read back by `lin1` / `w'`; the `lin1` groups are 529 + 597 us on 5060 Ti `SrTiO3` | Not feasible inside the current one-receiver-per-block spline: each block would read all 655 KB of `W_lin1` (~3.3 GB extra L2 traffic per step for an already L2-bound kernel), and sharing it across R receivers needs R x 38 accumulator registers (spline is at 96-122). Needs a different decomposition (e.g. a receiver-tiled tensor-core GEMM consuming spline output tiles from shared memory). |
| **2** | **Ada performance counters** | all Ada tuning so far is timing-only | `ERR_NVGPUCTRPERM` on `leeloo`; needs `NVreg_RestrictProfilingToAdminUsers=0` (admin) before Ada-specific `ncu` work (`w'` is 9% slower on Ada than on the 5060 Ti although Ada has 33% more SMs; spline gained 10% from L1 slab sharing there, so Ada looks L2-sensitive). |
| **3** | **Small-system latency (< ~1,000 atoms)** | 135-atom `SrTiO3` step 358 us (median span): GEMM groups 115 us (32%; ~25 tiny products, each ~6-13 us in the graph regardless of size), edge-tiled `w'` 100 us, spline 58 us (135 one-receiver blocks), i0 backward 28 us | Split-K for the own SGEMM (partials per K slice, last block of a tile sums them in z order) was tried: the isolated autotune cannot rank such products (every candidate times 6-14 us, launch-bound), and forcing split 2 / 4 for every eligible product raised the 135-atom GEMM groups 123 -> 147 / 158 us (step 367 -> 392 / 409 us), so the per-GEMM floor in the graph is launch/completion latency, not the K pipeline. Grouped launches were tried too: products of a fork group collected and, when each has fewer tiles than SMs, issued as one own-SGEMM launch (problem table, 64 x 64 tiles below two blocks per SM): 135-atom GEMM groups 114 -> 101 us (step 355 -> 345 us on the 5060 Ti, wall time -3% to -5%; 320 atoms within noise; Ada 135 atoms +2%), but the refactored kernel cost the 5060 Ti benchmarks +1.2% / +0.9% (`NbCl5`) and +0.3% / +0.2% (`SrTiO3`); dropped. The spline is not the problem: even at 135 atoms its 135 blocks keep ~15 warps per SM issuing (R4 picked, 64 us); an edge-split variant (one receiver per block, edges over 2 / 4 thread groups, fixed-order shared-memory reduction) measured 98 / 82 us there and 1.4-1.6x slower at 5,000 atoms. S96: on `sm_120` the receiver-owned `w'` now runs below 512 atoms too (135 / 320-atom SrTiO3 steps `0.974` / `0.963`; `wp-receiver-owned`). |
| **4** | **Larger / adaptive skin (`T10`)** | 0.5-1.5% at 5,000 atoms, ~10% at 135 atoms | Changes the benchmark configuration; owner decision. |
| **5** | **Generic path (section 5): gate in the GEMM epilogue** | MH-1 SrTiO3 (5060 Ti): gate forward + backward 15% of the step, ~1 GB of DRAM traffic per call; GEMMs ~50% | The gate reads the `linear_2`-side rows a GEMM just wrote and writes rows the next GEMM reads; fusing it into the own SGEMM's epilogue / prologue removes one round trip per direction. Falsifier: gate kernels already at ~DRAM bandwidth, so the ceiling is their full time (~7 ms of 47); stop if the fused GEMM loses more than it saves. |

### 4.2 Open Review Hardening Items (Correctness / Robustness)
M1-M3, M6, M7 and F1-F7 are resolved, and S1, S3, S5-S8 of the sixth pass (section 3.2). Open from the sixth pass:
- **S2**: the running maximum of the step displacement never decays, so one fast step keeps the loop unpipelined until the next `set_state` (hydrogen at 300 K: always unpipelined at skin 0.5).
- **S4, S9 (small)**: MD graphs re-captured on every `run` call; `temp_k` / `friction_per_fs` not validated; force below the first spline knot on the generic path; unchecked negative `lmax` and meta integers in bundles; three k-space buffers never freed and `set_cell` not exception-safe in `polar.cu`; exporter accepts models by class name only.

---

## 5. Model Families (Generic Path)

Supported, as in FastMACE (every label of its model table; local files match its SHA-256): MACE-MP-0 medium and large
(`2023-12-03-mace-128-L1_epoch-199`, `MACE_MPtrj_2022.9`), MACE-MP-0b3 medium, MACE-MPA-0 medium, MACE-OMAT-0
small and medium, MACE-MatPES PBE and r2SCAN (`MACE-matpes-*-omat-ft`), MACE-OFF23 small / medium / large,
MACE-OFF23b medium, MACE-OFF24 medium, MACE-MH-1 (any head, one per bundle; default `omat_pbe`), MACE-POLAR-1
S / M / L and MACE-OMOL-0 extra large (`MACE-omol-0-extra-large-1024`: 1024 hidden channels; total charge and spin
multiplicity per bundle, `ensure_loup_bundle(..., charge=Q, spin_multiplicity=M)`, default 0 and 1). All of them run
the generic path. Until S144, MACE-OMAT-0 medium, MP-0b3 medium, MPA-0 medium and both MatPES models (the same
density architecture) ran the specialised kernels of sections 1-4. S144 retired those kernels: the generic path was
2.5-3% faster on OMAT-0 medium (5060 Ti). Bundles of that path (`arch=omat0_medium_spec`) are refused with a
re-export message.

### 5.1 Pipeline
- `python/export.py` runs `export_generic.py` (`arch=generic`) for every model. Until S144 it ran `export_omat0.py`
  (specialised, `arch=omat0_medium_spec`) when `check_architecture` accepted the model. The exporter writes the
  `LOUPC001` container (section 3.2, M6), including each layer's product source (`L<t>.prod_src`, S144). The cache
  of `ensure_loup_bundle(model, Z, head=...)` is keyed by model content hash, species, head, charge / spin and the
  exporter sources (`gen_product.py` among them).
- `export_generic.py` extracts every linear map by probing the float64 e3nn modules with basis inputs (`probe_linear`,
  `probe_species_linear`), so e3nn path weights, `1/avg_num_neighbors`, the normalize2mom constants of SiLU / gates,
  ScaleShift (scale into the readouts and ZBL, shift into E0) and the selected head (E0 row, readout column,
  `mask_head` block) are folded numerically. Conv tensor-product paths are checked to be multiples of
  `wigner_3j(l1, l2, l3)`; the factor goes into the radial table. Radial functions (Bessel + cutoff + Agnesi
  transform + MLP, for the nonlinear blocks with the source / target species embeddings, and the edge density) are
  fitted per species pair (symmetric pairs unless the block embeds sender and receiver separately) with FastMACE's
  certified cubic-Hermite spline (`spline.fit`; the export refuses a certificate above 1, i.e. a spline error
  above the float32 network's own rounding error on FastMACE's `radial.certify` points). The conv layers' tables are
  stored as 8-byte cubics (CUBIC_PACKED8); the export then refines every band whose packing error would exceed half
  the loader's bound (`refine_for_packing`: 2.5e-4 of the column's largest value or r-slope, whole table and
  r >= 1 A) and re-certifies the refined grid. The gated bundles of the other families already pack within it and
  are unchanged; OMOL-0's steeper radial functions needed it (layer 1 2.1e-3 before: refused by the loader).
  Products: FastMACE's factored symmetric contraction (`sc_factored.factor` / `fold_weights`), kernels keyed by a
  signature of the factored program.
- MACE-OMOL-0's joint embedding (total charge, spin multiplicity) is one per-system vector added to every atom's
  layer-0 features, so the export folds it into each species' embedding row (everything downstream of layer 0 stays
  species-only) and its embedding readout energy into E0; charge and spin are export arguments (`export.py
  --charge Q --spin-multiplicity M`, part of the bundle cache key) and are refused for models without the embedding.
  Hidden widths up to 1024 (gates with one thread per channel, products on 128-channel blocks); the conv width stays
  at most 512, and the fused product + readout kernel runs only for widths up to 512.
- `python/ref_generic.py`: a float64 PyTorch executor of the bundle (same algorithm as the CUDA path, autograd forces
  and stress), used to check exports against MACE float64 and to localise CUDA-vs-model differences.
- `python/gen_generic.py` -> `src/generated_generic.cuh`: conv forward / backward for x irreps up to 0e+1o+2e
  (one block per receiver, one thread per channel, radial spline per edge; the backward reduces
  each edge's dE/dvec per warp, sender-feature gradients by atomics), the factored products (3 configurations) and
  the SH gradient (sympy).
- `src/generic.cu`: layer loop forward and reverse with GEMMs through the engine's autotuned `sgemm_rm`: linear_up,
  conv, message linear, density / `avg_num_neighbors` / `(beta D + alpha)` normalisation, the nonlinear blocks'
  residual linear, gate and linear_2, species skip connections, product + product linear, readouts (linear, SiLU MLP,
  bias MLP), ZBL, force / virial assembly. Layer 0 (input = species embedding) runs as an outer sum over the radial
  chain's 66 columns per sender species, with the conv weights, the layer input, the path factors and the message
  linear folded into one matrix per degree (`first_fwd_kernel` / `first_bwd_kernel`): its table is 66 columns
  instead of 4 C + 1.
- `src/polar.cu` (MACE-POLAR-1): per-layer spin-charge sources, the layer feature mixer, the Fukui constraint, two
  SCF steps of GTO electrostatic features (k-space: structure factors per k over atoms, feature / gradient passes per
  atom over k with tiled k data, double accumulation, exact fixed-point phases n . s mod 1) and the one-body charge
  update (embeddings, sparse uvu products as GEMMs, LayerNorm MLP, gated readout), the local electron energy and the
  k-space Coulomb energy, forward and reverse. Neutral singlet systems in zero external field, fully periodic.
  The stress includes the k-space terms' cell dependence (MACE PR 1718, as FastMACE): the installed PolarMACE
  (0.3.16) hands those terms the unstrained geometry, so its autograd stress misses up to 2e-5 eV/A^3 (NaCl); the
  gate now differentiates the native float64 energy through all strained geometry (`python/polar_reference.py`), avoiding both the missing cell terms and finite-difference truncation.

### 5.2 Gates (`python/test_gate.py MODEL --set ...`; 3x MACE float32-vs-float64 rule, cells strained / rattled)
Sets as FastMACE's: `oxide` (NaCl, SrTiO3), `organic` (urea 3x3x3, naphthalene 2x2x2, paracetamol 2x2x2,
water_216), `crystals` (NaCl, NaNbO3, NbCl5 R2SCAN cells); two configurations each. `--ref-device cpu` where the
float64 reference does not fit the GPU (OFF23-L / 23b / 24 on the 16 GB 5060 Ti, OFF23-L and POLAR-1-L on the
20 GB Ada).

| Model | Set | RTX 5060 Ti | RTX 4000 Ada |
|---|---|---|---|
| OMAT-0 small | oxide | PASS | PASS |
| OFF23 small / medium | organic | PASS / PASS | PASS / PASS |
| OFF23 large, OFF23b medium, OFF24 medium | organic | PASS (CPU refs) | PASS (worst 1.46 / 1.23 / 0.27; OFF23-L CPU refs) |
| MH-1 `omat_pbe`, `matpes_r2scan`, `mp_pbe_refit_add`, `oc20_usemppbe` | crystals | PASS (S59 build: worst force 0.87 / 0.86 / 0.80 / 0.84, stress 0.27 / 0.32 / 0.25 / 0.26) | PASS (first two) |
| MH-1 `omol`, `spice_wB97M` | organic | PASS (S59 build: worst force 0.32 / 0.28, stress 0.63 / 0.38) | PASS (`omol`) |
| MP-0 medium, MP-0 large | oxide | PASS (S59 build: worst force 0.72 / 1.31, stress 2.97 / 0.94) | not run |
| MP-0b3 medium, MPA-0 medium (specialised, retired in S144; every forced variant) | oxide | PASS (S59 build, 30 / 30 rows: worst force 1.06 / 1.68, stress 0.87 / 0.89) | not run |
| MatPES PBE, r2SCAN (specialised, retired in S144; every forced variant) | crystals | PASS (S59 build, 18 / 18 rows: worst force 0.68 / 1.57, stress 1.10 / 1.04) | not run |
| OMOL-0 extra large | organic: neutral singlet, +1 doublet, -1 doublet, neutral triplet | PASS (S57 path; worst force 0.86 / 0.31 / 0.82 / 0.79, stress 0.79 / 0.19 / 0.63 / 0.47) | not run |
| POLAR-1-S | crystals | PASS (worst ratio 1.30) | PASS (worst 0.99) |
| POLAR-1-M | crystals | PASS (worst 0.97) | PASS (worst 1.14) |
| POLAR-1-L | crystals | PASS (worst 1.16) | PASS (CPU refs; worst 2.69, force NaNbO3_c0) |

POLAR-1-S NaNbO3_c0 is far from float32-exact in MACE itself (MACE float32 vs float64: 27-90 eV/A force,
0.38-1.15 eV/A^3 stress; FastMACE excludes the configuration); LoupMD's error there is 0.15-0.34 of that.
Its energy row is not reproducible run to run: LoupMD's energy there takes one of a few discrete values per
process (dE/atom 0.074, 0.167, 0.679, 0.988 or 2.320 meV against float64; identical within a process, the same set
for the S7 and S8 builds; a discrete set points to the per-process GEMM plan choice, not verified), and MACE's own float32 error, the gate's
bound, also changes between runs (0.44 meV in one). With 2.320 the row failed once for S7 and once for S8 and
passed for S8 in another run; force and stress ratios stayed at or below 0.29.
Since S9 the gate leaves the configuration out (`--include-unstable` gates it; FastMACE excludes it too). A cuBLAS
workspace per lane (review U4) left the per-process values as they were, with plans re-timed per process
(inconclusive). Both loaders also measure the 8-byte tables'
error at load (exact maxima, value and d/dr, whole table and r >= 1 A clipped exactly) and refuse above 5e-4 of the column maximum;
current bundles measure 2.7e-5 to 1.7e-4 (ledger rv8-fixes).
`tests/test_gate_wrapper.py` runs the gate for OMAT-0 small, OFF23-S / M, MH-1 (two sets) and POLAR-1-S / M.
The MACE references are cached per model, set, head and reference GPU (`LOUP_GATE_CACHE`, default
`~/.cache/loupmd/gate_refs`; `--no-ref-cache` recomputes):
a repeat gate costs only LoupMD's evaluations (POLAR-1-S crystals 40 -> 6 s; the ~30 min of the POLAR-1-L CPU-reference
gate is the references), and the float32 bound no longer changes between runs.

### 5.3 MD Speed (`python/bench_family.py`: Langevin 300 K, 1 fs, skin 0.5 A, 100 warm-up + median of 6 x 256 steps)

| Model | System (atoms) | 5060 Ti ms/step (S7) | 5060 Ti before S7 | Ada (before S7) | FastMACE (documented, 5060 Ti unless noted) |
|---|---|---|---|---|---|
| OMAT-0 medium (specialised, retired in S144) | NbCl5 (1,944) / SrTiO3 (5,000) | 1.834 / 8.376 | 1.843 / 8.488 | 2.085 / 9.384 | |
| OMAT-0 small | NbCl5 / SrTiO3 | **1.432 / 6.416** | 2.175 / 10.014 | 2.263 / 10.824 | |
| OFF23 small / medium / large | water 2x2x2 (5,184) | **3.869 / 9.311 / 33.722** | 5.593 / 13.093 / 47.829 | 5.960 / 14.620 / 59.736 | |
| OFF23b medium / OFF24 medium | water 2x2x2 | **13.585 / 13.518** | 19.680 / 19.602 | 22.060 / 22.010 | |
| OFF23 medium | water_216 (648) | **1.553** | 2.121 | 1.969 | H200 1.80 |
| MH-1 `omat_pbe` | NaCl 3x3x3 (216) | **1.780** | 2.334 | 2.001 | 2.65-2.90 (`matpes_r2scan`) |
| MH-1 `omat_pbe` | NbCl5 / SrTiO3 | **13.781 / 41.388** | 15.017 / 46.386 | 16.233 / 51.176 | NbCl5 18.7-21.3 |
| MH-1 `omol` | water 2x2x2 | **43.302** | 50.345 | 54.863 | |
| POLAR-1 S / M / L | NaCl 3x3x3 (216) | **2.167 / 4.671 / 8.907** | 2.492 / 5.273 / 10.076 | 2.291 / 4.928 / 10.227 | 2.19-2.23 / 4.51-4.59 / 9.74-9.81; Ada M 4.88-4.90 |
| POLAR-1 S / M / L | NaCl 6x6x6 (1,728) | **11.637 / 25.418 / 51.876** | 15.975 / 30.484 / 59.997 | 16.149 / 33.263 / 71.207 | |
| POLAR-1-M | NbCl5 | **29.739** | 37.682 | 39.984 | 31.1-31.5; Ada 37.4 |

S7 (13 November, ledger entries pol-sf-f32, gen-fork-zero-slab, gen-skip-fold, gen-conv-v2): GEMM lanes and one zero
slab in the generic and long-range passes, the skip-message and readout-tail folds, conv kernels with the
specialised path's 8-byte cubic tables, staged edges, multi-receiver forward and late pull-back backward, and
float32-chunked structure factors. Every gate passes on the 5060 Ti (section 5.2 sets); 47 tests pass. The Ada
column is the fifth update's (the workstations were not used for S7). Against FastMACE's raw A/B lines of 11
November on the same 3x3x3 cells, LoupMD's POLAR-1 is now 1-3% faster (S), 2-4% slower (M, NaCl 216), 4-6% faster
(M, NbCl5) and 9% faster (L); MH-1 NaCl 216 is 33-39% faster than FastMACE's documented `matpes_r2scan` range.
These are FastMACE's adopted configurations; its non-adopted POLAR-1-L pair-`w'` variant runs NaCl 216 in
9.11-9.19 ms (slower on NbCl5), which LoupMD's 8.907 still beats by 2-3%.
The FastMACE column is its documented numbers (`docs/benchmarks.md`, `docs/optimisation-ledger.md`,
`results/ada-5060-screen-20261110/`), not re-measured here. POLAR-1 rows run with float32 SIMT GEMMs (5.4).
POLAR-1-S / -L on NbCl5 3x3x3 are not listed: the model is unstable there (5.5).

S8 (13 November, 5060 Ti only; ledger gen-conv-l2-split, gen-first-bwd-v2, gen-conv-fwd-r1, gen-conv-fwd-l2-split,
gen-first-fwd-race). Times are the S8 side of ABBA runs against S7 (`ab_fam.py`, same protocol as above):

| Model | System | S7 | S8 | b/a |
|---|---|---|---|---|
| OMAT-0 small | SrTiO3 / NbCl5 | 6.511 / 1.456 | **6.109 / 1.381** | 0.938 / 0.948 |
| OFF23 small / medium / large | water 2x2x2 | 3.869 / 9.427 / 34.198 | **3.793 / 8.927 / 29.714** | 0.980 / 0.947 / 0.869 |
| OFF23 medium | water_216 | 1.549 | **1.431** | 0.924 |
| OFF24 medium | water 2x2x2 | 13.685 | **12.762** | 0.933 |
| MH-1 `omat_pbe` | NaCl 3x3x3 | 1.841 | **1.792** | 0.974 |
| POLAR-1 S / M / L | NaCl 3x3x3 | 2.140 / 4.787 / 8.856 | **2.136 / 4.638 / 8.739** | 0.998 / 0.969 / 0.987 |
| POLAR-1-M | NbCl5 | 30.031 | **30.068** | 1.001 |

POLAR-1-S / -M NaCl rows are with freshly tuned GEMM plans on both sides (ledger meas-plan-variance: with each
build's cached plans they read 1.019 / 1.013). Against FastMACE (same cells, adopted configurations): POLAR-1-S 2-4%
faster, POLAR-1-M NaCl 1-3% slower, NbCl5 3-5% faster, POLAR-1-L 10-11% faster; MH-1 33-38% faster. Gates: every
set in 5.2 passes except the POLAR-1-S NaNbO3_c0 energy row in one of six S8 runs (and one of five S7 runs; see
5.2); 55 tests pass.

S8 + POLAR k split (ledger pol-k-split: the per-atom k-space passes split over k chunks with a fixed-order
reduction), ABBA against S8 with fresh GEMM plans on both sides, ms/step:

| Model | System | S8 | S8 + k split | b/a | FastMACE (adopted) |
|---|---|---|---|---|---|
| POLAR-1-S | NaCl 3x3x3 / 6x6x6 | 2.148 / 11.833 | **1.946 / 10.363** | 0.906 / 0.876 | 2.19-2.23 / – |
| POLAR-1-M | NaCl 3x3x3 / NbCl5 | 4.801 / 29.917 | **4.598 / 27.751** | 0.958 / 0.928 | 4.51-4.59 / 31.1-31.5 |
| POLAR-1-L | NaCl 3x3x3 | 8.758 | **8.563** | 0.978 | 9.74-9.81 |

Against FastMACE's adopted configurations LoupMD's POLAR-1 is now 11-13% faster (S), level to 2% slower (M, NaCl
216), 11-12% faster (M, NbCl5) and 12-13% faster (L). POLAR-1-S / -M / -L crystals gates pass (POLAR-1-L with CPU
references).

S10 (ZBL in the force-assembly pass, `gen-zbl-in-assembly`): OMAT-0 small `SrTiO3` 6.06 -> **5.87 ms/step** (0.969); MH-1 `NbCl5` 13.33 -> 13.27, OFF23 medium water 8.88 -> 8.85, POLAR-1-M `NbCl5` 27.28 -> 27.34.
S11 (layer-0 `K0` alignment, `gen-first-hidden-k0-align`): OMAT-0 small `SrTiO3` 5.88 -> **5.62 ms/step** (0.956); OFF23-M water 8.85 -> **8.67** (0.979); OMAT-0 medium generic `SrTiO3` 10.56 -> **10.30** (0.976); MH-1 `NbCl5` 13.27 -> 13.16 (0.992).
S12 (edge-parallel layer-0 backward + ZBL + assembly, `gen-first-bwd-edge`): OMAT-0 small `SrTiO3` 5.62 -> **5.13 ms/step** (0.913); OFF23-M water 8.65 -> **8.28** (0.957); OMAT-0 medium generic `SrTiO3` 10.30 -> **9.80** (0.951); MH-1 `NbCl5` 13.20 -> **13.07** (0.990); POLAR-1-M `NbCl5` 27.40 -> **27.27** (0.995).
S13 (fused product + `ro1` readout + 128-thread `gprod`, `gen-gprod-ro1-fused`): OMAT-0 small `SrTiO3` 5.12 -> **4.99 ms/step** (0.976, down from 6.06 before S10); OFF23-M water 8.29 -> **8.16** (0.984); OMAT-0 medium generic `SrTiO3` 9.81 -> **9.67** (0.986, kernel gap vs specialised cut from +2,144 to +913 us); POLAR-1-M `NbCl5` 27.28 -> **27.14** (0.995).
S14 (`C_FIX` + prelocated `act_slab`/`act_t_sx` on `gconv_fwd`/`gconv_bwd` + 256 thr `L1`, `gen-gconv-cfix-preloc`): OMAT-0 small `SrTiO3` 4.91 -> **4.73 ms/step** (0.964, down from 6.06 pre-S10); OFF23-M water 8.00 -> **7.43** (0.928, down from 8.88 pre-S10); MH-1 `NbCl5` 12.82 -> **12.50** (0.976); POLAR-1-M `NbCl5` 27.20 -> **27.06** (0.995); OMAT-0 medium generic `SrTiO3` 9.67 -> **8.91** (`1.051x` of specialised `8.31 ms`, down from `1.273x` pre-S10).
S15 (`pol-sf-tiled`, `spl-v6-cubic-cg-fold`, `gen-conv-fwd-cg-fold`, 14 November, 5060 Ti only):
- `sf_kernel_tiled` (`src/polar.cu`, `c24b6c4`): `POLAR-1-M` `NbCl5` 27.00 -> **25.00 ms/step** (`0.926`, `sf_kernel<16/8/4>` 900/455/233 -> 316/150/84 us), `NaCl` 216 4.41 -> **4.36** (`0.990`), `POLAR-1-S` `NaCl` 1.92 -> **1.86** (`0.966`), `POLAR-1-L` `NaCl` 8.36 -> **8.31** (`0.993`).
- `spline_forward_inter1` v6 (`ca23b3c`, OMAT-0 medium): `SrTiO3` 8.40 -> **8.28 ms/step** (`0.985`, frozen `R1p` 1,403 -> 1,306 us), `NbCl5` 1.863 -> **1.853** (`0.994`); all forced `LOUP_SPLINE_VARIANT` gates pass. Removed dead `packed8_table_1` / `packed8_bias` (~45 MB) from `export_omat0.py` and `model_loader.cu`.
- `emit_conv_fwd` CG linear-form fold + `s_pw`: kernel profiles `OFF23-M` `gconv_fwd_L1` `1,688 -> 1,572 us`, `OFF23-L` `gconv_fwd_L2b` `3,029 -> 2,898 us`; ABBA `OMAT-0` small `SrTiO3` 4.82 -> **4.77 ms/step** (`0.989`), `OFF23-L` water 28.30 -> **28.00** (`0.989`), `OFF23-M` tie (`7.53 -> 7.51`, `0.997`), `POLAR-1-M` `NbCl5` tie (`25.02 -> 24.99`, `0.999`), `MH-1` `NaCl` `1.75 -> 1.71` (`0.981`, inconclusive due to `1.682/1.746` rep spread). Cached 3x gates pass across `OMAT-0` medium/small, `OFF23-S/M/L`, `OFF24-M`, `MH-1`, `POLAR-1-S/M`; pytest suite passes.
S16 (`gemm-own-n144`, `gemm-own-sgemm64`, 14 November, 5060 Ti only):
- `sgemm128_kernel<4, false>` partial-`N` `128 x 64` tiles + `sgemm64` (`64 x 64 x 16` `cp.async`, `128` threads, autotuned for `sm_120` and `M <= 1600`): fresh-plan ABBA `POLAR-1-S` `NaCl216` 1.85 -> **1.61 ms/step** (`0.873`, vs FastMACE `2.19-2.23`), `POLAR-1-M` `NaCl216` 4.30 -> **3.61** (`0.839`, vs FastMACE `4.51-4.59`), `POLAR-1-L` `NaCl216` 8.24 -> **7.22** (`0.876`, vs FastMACE `9.74-9.81`), `MH-1` `NaCl216` 1.71 -> **1.57** (`0.919`), `OFF23-M` `water216` 1.39 -> **1.30** (`0.938`), `MH-1` `NbCl5` tie (`12.59 -> 12.59`, `1.000`). Gates pass on `POLAR-1-S/M`, `MH-1` (crystals + organic), `OMAT-0-S/M`, `OFF23-M`; `POLAR-1-L` `cmp_libs` `dF = 2.07e-7`; pytest suite passes.
S17 (`gemm-own-sgemm32`, 14 November, `sm_120` only):
- `sgemm32_kernel` (`32 x 32 x 16` `cp.async`, `64` threads) + deterministic `split_k` (`1, 2, 4` into per-stream `4 MB` workspace, autotuned for `sm_120` and `M <= 1600`): fresh-plan ABBA `POLAR-1-S` `NaCl216` 1.65 -> **1.50 ms/step** (`0.909`), `POLAR-1-M` `NaCl216` 3.70 -> **3.46** (`0.936`), `POLAR-1-L` `NaCl216` 7.28 -> **6.89** (`0.947`), `MH-1` `NaCl216` 1.61 -> **1.53** (`0.948`), `OFF23-M` `water216` tie (`1.34 -> 1.35`, `1.006`), `MH-1` `NbCl5` tie (`12.55 -> 12.59`, `1.003`). Gates pass across `POLAR-1-S/M`, `MH-1`, `OMAT-0-S/M`, `OFF23-M`; `67 passed`.
S18 (`gemm-own-narrow-n`, 14 November, `sm_120` only):
- Narrow-`N` `sgemm64` / `sgemm32` above `M = 1600` (`N <= 64` / `N <= 32`, or `M <= 2500 && N <= 160`): fresh-plan ABBA `POLAR-1-M` `NbCl5` 24.66 -> **24.48 ms/step** (`0.9925`), `MH-1` `NbCl5` 12.62 -> **12.51** (`0.9907`), `OFF23-M` `water` tie (`7.41 -> 7.42`), `OMAT-0-S` `SrTiO3` tie (`4.71 -> 4.71`). Cached 3x gates + `576`-atom `NbCl5` `POLAR-1-M` full force+FD-stress 3x gate (`dF 0.66x`/`dS 0.00x`) + `1,944`-atom `NbCl5` `MH-1` full 3x gate (`dF 0.31x`/`dS 1.14x`) + `POLAR-1-M` force-only 3x check (`dF 0.47x`, no stress check) + `67 passed` pass.
S19 (`gen-conv-l2-cfix-preloc`, 14 November, 5060 Ti only):
- `C_FIX` (`128/224`) on the lx 2 convs, `PRELOC` on `gconv_bwd_L2`, prelocated slabs for `pair_sym = 0` models: fresh-plan ABBA `OFF23-L` water 27.81 -> **27.16 ms/step** (`0.977`), water216 3.85 -> **3.79** (`0.985`), `POLAR-1-L` `NaCl216` 6.83 -> **6.77** (`0.991`), `POLAR-1-M` / `MH-1` `NbCl5` tie. The `OFF23-L` gain is the lx 2 `C_FIX` / `PRELOC` (it was already prelocated); `pair_sym = 0` prelocation alone is a tie on `NbCl5`.
S20 (`gemm-own-raster`, 14 November, 5060 Ti only):
- Own SGEMMs rasterised `N`-tile-fastest (`sgemm128` via an `N_FASTEST` template only on `sm_120`; other GPUs run SASS identical to S19), which improves observed cold-`A` reuse (timing only, no DRAM-byte counters; `13608x512x512` cold 529 -> 425 us): fresh-plan ABBA `MH-1` `NbCl5` 12.52 -> **12.22 ms/step** (`0.977`), `POLAR-1-M` `NbCl5` 24.50 -> **24.19** (`0.987`), `OMAT-0-M` `SrTiO3` 8.18 -> **8.08** (`0.989`), `OFF23-M` water 7.41 -> **7.35** (`0.993`), `OMAT-0-S` / `POLAR-1-S` tie.
S21 (`gen-first-bwd-edge-minb`, 14 November, 5060 Ti only):
- `first_bwd_edge_kernel<COLS = 2>` capped at 80 registers in sm_120 device code (latency-bound, 41.7% occupancy at 94 registers): kernel `-6%` (`OMAT-0-S` 510 -> 480 us, `OFF23-M` 358 -> 334 us); step, both argument orders combined: `OMAT-0-S` `0.9954`, `OFF23-M` `0.9979` (one `1.003` run). Lane-per-edge rewrite rejected (`-43%` instructions, but 168 registers: `+13%`). Own `sgemm128` and the `L1` convs profiled near their limits (`s21-limiters` in the ledger).
S29 (`gen-conv-bwd-l1-c256`, 14 November, 5060 Ti only):
- `C_FIX = 256` on `gconv_bwd_L1` for `MACE_MPtrj_2022.9` (`C = 256`; runtime `C` held 128 registers, now 62): final installed build vs rebuilt parent, fresh-plan ABBA `SrTiO3` (5,000 atoms) `12.05 -> 11.94 ms/step` (`0.9913`; reversed `0.9912`). 3x gate (oxide) passes; `pytest` 67 passed. Found by a sweep over every installed model; only `MPtrj` uses the `C = 256` lx 1 branches.
S30 (`gen-conv-fwd-l1-c256`, 14 November, 5060 Ti only):
- `C_FIX = 256` (`PAIR = false`, 80 registers) on `gconv_fwd_L1` for `MPtrj`: kernel 1960 -> 1860 us, ABBA `SrTiO3` `12.04 -> 11.94 ms/step` (`0.9921`; reversed `0.9910`). 3x gate (oxide) passes; `pytest` 67 passed. S29's `PAIR + C_FIX` forward (104 registers) was a tie.
S31 (`gen-conv-bwd-512thr`, 14 November, 5060 Ti only):
- 512-thread blocks for `gconv_bwd_L1` at `C = 256` and `gconv_bwd_L2lp` at `C = 224` (their 39-45 KB `s_q` allows 2 blocks per SM: 16 warps at 256 threads, 32 at 512; measured achieved occupancy 29% -> 59% on `MPtrj`): final binary vs S30, fresh-plan ABBA `MPtrj` `SrTiO3` `11.93 -> 11.58 ms/step` (`0.9703`; reversed `0.9707`), `OFF23-L` water216 `3.83 -> 3.76` (`0.9838`; reversed `0.9786`); scratch build `OFF23-L` water (5,184 atoms) `26.95 -> 26.48` (`0.9825` / `0.9839`). 3x gates (`MPtrj` oxide, `OFF23-L` organic) pass; `pytest` 67 passed.
S34 (`nl-lane-groups`, 14 November, 5060 Ti only):
- Neighbour count / fill with 8 lanes per atom (bins split round-robin) instead of one thread per atom (162 warps for 5,184 atoms, 8% occupancy); fill is designed to reproduce the one-thread row order (per-bin offsets in shared memory); edge arrays were not compared directly, but `MH-1` `NbCl5` (deterministic path) matches the old build to `dE 3.6e-12` and the `POLAR-1-S` replicated-cell test passes. Per rebuild: `SrTiO3` 433 -> 292 us, `NbCl5` 284 -> 110, water 439 -> 302. Water rebuilds every ~4 steps: ABBA `OFF23-S` water `0.9945` / `0.9856`, `OFF23-M` `0.9961` / `0.9943`, `OMAT-0-S` `0.9961` / `0.9972`. Other GPUs keep the one-thread kernels (SASS identical to S33). Gates (`OFF23-S` organic, `OMAT-0-S` oxide, `MH-1` / `POLAR-1-S` crystals) pass; `pytest` 67 passed.
S38 (`gemm-own-n96`, 14 November, 5060 Ti only):
- `128 x 96` own-SGEMM tile for `N = 96` products (the `C = 96` models; `sgemm128_kernel<8>` spent a quarter of its FMAs on padding): standalone `0.79-0.84` per shape, bit-identical; final binary, fresh-plan ABBA `OFF23-S` water `3.088 -> 3.046 ms/step` (`0.9866`), reversed `3.101 -> 3.026` (`0.9758`). Other widths and other GPUs unchanged (SASS identical). Gates (`OFF23-S` organic, `OMAT-0-S` oxide) pass; `pytest` 67 passed.
S40 (`gen-conv-bwd-l0-red`, 14 November, 5060 Ti only):
- `gconv_bwd_L0`'s per-edge `edge_dvec` update as a fire-and-forget atomic add (one writer per edge; `ncu` attributed ~4% of its stall samples to the read-modify-write's load): kernel `-8%` (`OMAT-0-S`) / `-16%` (`OFF23-S`); final binary, fresh-plan ABBA `OMAT-0-S` `SrTiO3` `4.689 -> 4.601 ms/step` (`0.9813`), reversed `0.9768`; `OFF23-S` water `3.052 -> 2.966` (`0.9718`), reversed `0.9763`. lx 1 / 2 kernels and other GPUs unchanged (SASS identical). Gates (`OFF23-S` organic, `OMAT-0-S` / `MPA-0` oxide) pass; `pytest` 67 passed.
S48 (`gen-conv-bwd-l2-pullr`, 14 November, 5060 Ti only):
- `gconv_bwd_L2` (x-degree-2 backward convs of the lx 2 models) takes its radial pull from the x-gradient contraction (`sum_m1 x[m1] Cg[m1]`) instead of the full sum over every `A x Y` term: SASS 1624 -> 1464, kernel `-16%` (`OFF23-L` water) / `-18%` (water216); fresh-plan ABBA `OFF23-L` water `26.47 -> 25.47 ms/step` (`0.9624`), reversed `0.9609`; water216 `0.9666` / `0.9639`; `POLAR-1-L` `NaCl216` tie (`1.0024` / `0.978`). Other GPUs and other kernels unchanged (SASS identical). Gates (`OFF23-L` organic, `POLAR-1-L` crystals; CPU references) pass; `pytest` 67 passed.
S52 (`pol-dot-fold`, 14 November, 5060 Ti only):
- POLAR SCF and electron-energy weights composed with `dot^T` at load (the two linear maps had nothing between them): one C x C GEMM per SCF step and l in each direction instead of two, none for the electron energy (`POLAR-1-M` `NaCl216` GEMM launches 165.6 -> 149.5 per step). Final binary, fresh-plan ABBA: `POLAR-1-S` `NaCl216` `1.511 -> 1.377 ms/step` (`0.911`), reversed `0.914`; `POLAR-1-M` `NaCl216` `3.461 -> 3.073` (`0.888`), reversed `0.922`; `POLAR-1-M` `NbCl5` `24.39 -> 22.11` (`0.906`), reversed `0.906`; `POLAR-1-L` `NaCl216` `6.908 -> 6.122` (`0.886`), reversed `0.895`. Only on `sm_120` (other GPUs run the unfolded GEMMs; existing kernels SASS-identical on `sm_89` / `sm_90` / `sm_120`); `LOUP_POLAR_FOLD=0` selects the unfolded path for testing. Gates (crystals; `POLAR-1-L` CPU references) pass on both paths; `pytest` 67 passed.
S57 (`gen-chain-fold`, 14 November, 5060 Ti only):
- OMOL-0 XL: the non-last layers' outputs are never formed. Each layer's product output (and layer 0's species-only skip input) goes straight into every later consumer (the next layers' `linear_up` and the last readout) through weights composed in double at load (`W_p W_sc ... W_up`), and the backward follows the same weights; the 1024 x 1024 `W_p` / `W_sc` products of layers 0 and 1 and the 1024-wide `linear_up` of layers 1 and 2 go in both directions. Fold against `LOUP_CHAIN_FOLD=0` on one build: water216 `29.02 -> 23.83 ms/step` (`0.821`), reversed `0.821`; water `217.9 -> 179.8` (`0.825`), reversed `0.825`. Exact to float32 rounding against the plain path (water216 `dF` 1.8e-6 eV/A); organic gates pass on the fold path (neutral worst 0.86 / 0.79, +1 doublet 0.31 / 0.19). Only OMOL-0 qualifies among the supported families (all layers gated, no readout before the last, no per-species skip, no long range); other GPUs keep the plain path (`generic.cu` kernels SASS identical for `sm_89` / `sm_90` / `sm_120`).
- OMOL-0 XL after S57, `nsys` water216 (installed library, default plan cache): kernel sum 29.2 ms/step (35.8 before), GEMM-like 73% (21.3 ms): `sgemm128<8>` 12.6 ms (41.4 launches, mean 305 us), `sgemm64` 3.5, CUTLASS SIMT 2.4, `magma` 0.8, `sgemm32` 1.1; `gate_bwd` 1.6, `gate_fwd` 0.9; all `gconv` kernels together 3.6 ms; products 1.1 ms. The 1024-wide message (`W_2`) and linear GEMMs are the limiter.
- OMOL-0 XL against FastMACE (same 5060 Ti, 14 November; FastMACE `fastmace` 1.0.0 at the current FastMACE checkout, float32, graph tier, `radial_tables=off`: its default plan here falls back, and the fallback's float64 reference does not fit 16 GB; FastMACE's own OMOL-0 5060 Ti number was measured that way too). MD under `bench_family`'s protocol on both sides (`.tmp_o/fm_md.py` for FastMACE): water216 LoupMD **23.86 ms/step**, FastMACE 74.15 (3.1x); `NbCl5` 3x3x3 (1,944 atoms) **60.37**, FastMACE 137.58 (2.3x; FastMACE documented 141.5). Accuracy against MACE float64 on the gate's organic configurations (`.tmp_o/acc_om.py`). FastMACE through its one-off `ForceField.evaluate` with `radial_tables=off` and its rule-13 re-plan applied (`reassociate_first` / `segmented_first_sum` off: their setup self-check fails on urea, and the one-off path raises instead of re-planning); the timed MD plans above kept those two rewrites on, so these FastMACE errors are of that variant plan, not of the timed graph path: neutral worst force error LoupMD 6.6e-5 eV/A (RMS 2.4-7.6e-6), FastMACE 1.23e-4 (RMS 1.0-2.0e-5), MACE float32 up to 1.0e-4; charge +1 doublet LoupMD 1.85e-4 (RMS up to 2.7e-5), FastMACE 1.04e-3 (RMS up to 2.4e-4), MACE float32 up to 9.8e-4. Worst ratios to MACE float32's error (force / stress): LoupMD 0.88 / 0.79 and 0.31 / 0.22, FastMACE 1.21 / 1.52 and 1.33 / 2.49; both within the 3x rule.
S59 (`gen-species-tables`, 14 November, 5060 Ti only):
- Layer 0's species-only products (its input is the embedding row) become per-species tables composed in double at load and gathered per atom: the gated block's residual and, under S57, the skip terms. OMOL-0 XL water216 `23.78 -> 23.26 ms/step` (`0.978`), reversed `0.977`; MH-1 NaCl216 `0.988` / `0.991`, NbCl5 `0.997` / `0.996`. POLAR-1-L showed no win in the tables-first order, so the long-range models keep the GEMMs. Gates pass (OMOL-0 at four charge / spin settings, MH-1 crystals both heads and `omol` organic); kernels SASS-identical; `pytest` 71 passed; `LOUP_SPECIES_TABLES=0` disables.
S64 (`gen-conv-fwd-variants`, 15 November, 5060 Ti only):
- The generic `gconv_fwd_L1` at `C = 128` now has the specialised spline forward's receivers-per-block choice: R1 paired (old), R1 unpaired, R5 (640 threads), timed per layer and system at the first MD rebuild. Kernel up to -21% (OMAT-0 medium generic SrTiO3 2,200 -> 1,742 us; OFF24-M water 2,723 -> 2,437). Full-step ABBA tuned / old, both orders: MP-0 medium SrTiO3 `0.968` / `0.967`, OFF24-M water `0.978` / `0.978`, OFF23-M water `0.975` / `0.980`, MH-1 SrTiO3 `0.988` / `0.991`; small cells (216-648 atoms) and POLAR-1-M tie. Gates pass for both forced variants on all seven families; existing kernels SASS-identical; `LOUP_CONV_TUNE=0` disables.
S72 (`gen-res0-table-read`, `s72-omat0-limiters`, 16 November, 5060 Ti):
- The gate kernels read layer 0's residual from the S59 species table instead of a per-atom copy: MH-1 SrTiO3 `0.993` / `0.991` (ABBA both orders), NaCl216 `0.987` / `0.983`, OMOL-0 water216 `0.998` / `0.997`; gates pass with the tables on and off.
- OMAT-0 medium generic SrTiO3 measured kernel by kernel (`ncu`): every kernel family sits at an issue, L2 or DRAM limit (conv backward issue 75% and L2 75%, SGEMMs 65-70% FMA pipe, products 78-92% of DRAM peak), so the remaining levers are byte and FLOP removal between kernels, not kernel tuning. Rejected falsifiers: sliced conv kernels (`gen-conv-sliced`), the decode bias as an OR (no gain).
S73 (`gen-chain-fold-ext`, 16 November, 5060 Ti only):
- The S57 skip-chain fold now covers every multi-layer generic model without long range (any layer kind, linear non-last readouts, per-species skips), not only OMOL-0. In-process A/B plain / fold, both orders: MH-1 NaCl216 `1.075`, SrTiO3 `1.053` (34.86 -> 33.11 ms/step); MPtrj SrTiO3 `1.040`; OMAT-0 medium generic SrTiO3 `1.017` (8.17 -> 8.03, the specialised path's time); MP-0 medium SrTiO3 `1.017`; OFF24-M water `1.015`. Exact to the noise side; 3x gates pass on every folded family; `LOUP_CHAIN_FOLD=0` disables.
S75 (`md-guarded-loop`, `nl-row-sort`, 16 November, 5060 Ti and A100):
- One exact MD loop replaces the unpipelined / pipelined pair: each step's graph ends with a guard kernel that publishes the skin check to mapped host memory and an IF node holding the force pass, so the host queues the next step while the force pass runs and the GPU waits for the host only at a rebuild; host reads poll mapped memory instead of `cudaStreamSynchronize`; neighbour rows are sorted, gathered and order-checked by one block-per-row kernel (no `cub::DeviceSegmentedSort` round trip), and in MD the order flag is read with the next step's publication behind a checked-rest IF node. Every force pass follows its own skin check (no lagged threshold, no incomplete list): `LoupMDStats::dangerous_builds` and `pipelined_steps` are gone. 5060 Ti library ABBA new / HEAD: `OFF23-M` water216 1.262 -> **1.010 ms/step** (`0.800`), `OFF23-S` water216 0.662 -> **0.463** (`0.700`), `OFF24-M` water `0.961`, MH-1 NaCl216 `0.990`, OMAT-0 medium NbCl5 `0.994`, SrTiO3 `0.998`, MH-1 SrTiO3 `1.000`. A100: polling gains 6-9% on water216 in-process; the conditional step ties the polled old loop there (the IF node costs ~11 us per step against a ~10 us native round trip). Force-path kernels SASS-identical; row order identical to the stable sort.
S76 (`md-device-rebuild`, 16 November, 5060 Ti):
- The neighbour rebuild runs inside the MD step graph: a second IF node after the guard holds bin + count + a gate kernel and, when the new list fits the captured edge bucket and row-sort width, fill + sort + commit + the checked rest. A rebuild step no longer waits for the host (two round trips of ~150-200 us each under WSL2 before). Library ABBA over S75: `OFF23-M` water216 `0.939`, `OFF23-S` water216 `0.862`, `OFF24-M` water `0.992`, MH-1 NaCl216 `0.998`, OMAT-0 SrTiO3 `0.998`. Lists that outgrow the captured sizes are finished on the host and the graphs recaptured; reordering systems keep the host-driven rebuild.
S77 / S78 (`md-device-rebuild`, 16 November, 5060 Ti):
- Every conditional node a step evaluates costs time on this driver even when its body does not run. The step graph now ends in one SWITCH node (body 0 the force pass, body 1 the rebuild) instead of two IF nodes (`OFF23-S` water216 `0.951`, `OFF23-M` `0.992`, MH-1 NaCl216 `1.000`; a flat layout of four IF nodes lost 4-19%), and the rebuild branch's fill / sort / commit read the gate's verdict instead of sitting behind an IF node (`OFF23-S` `0.991`). Rebuild steps no longer idle the GPU (`nsys`: `OFF23-S` water216 steady-state gaps 10.4 ms per 100 steps after S75 -> 0.85 ms; traced step 0.535 -> 0.428 ms).
S77 A100 defaults (`a100-cc80-defaults`, 16 November, NHR Alex A100-SXM4-40GB):
- Compute capability 8.0 now runs the generic chain fold and species tables and LoupMD's own format-2 six-tile cubin (`cubins/gemm_tc_hyb_sm80.cubin`) by default. In-process A/B on the committed tree (job `loup-s74a`), new / old: OMOL-0 XL water216 `0.752`, MH-1 NaCl216 `0.875`, MH-1 SrTiO3 `0.889`, MPtrj SrTiO3 `0.935`, OFF23-M water216 `0.959`, OMAT-0 medium generic SrTiO3 `0.977`, MP-0 medium SrTiO3 `0.979`, OMAT-0 medium specialised SrTiO3 `0.998`. 3x gates (job `loup-s75g`): 19 runs over every non-POLAR family, none failing (worst OMAT-0 medium specialised oxide stress 2.78). The S70 SGEMM / neighbour switches: next paragraph.
S80-S84 A100 (`a100-own-ext-nb-groups`, `pol-dot-fold`, 16 November, NHR Alex A100-SXM4-40GB):
- The S75-S78 MD loop at the S77 cc 8.0 defaults against the HEAD-era build (library ABBA, s73c -> s78, job `loup-s80a`): OFF23-S water216 `0.936`, OFF23-M water216 `0.945`, MH-1 NaCl216 `0.894`, MH-1 SrTiO3 `0.883`, OMAT-0 medium generic SrTiO3 `0.981`, specialised `0.995`. Gates at those defaults pass (`loup-s80g`: OMAT-0 medium generic / specialised oxide 2.01 / 2.95 and 1.72 / 2.88, MH-1 crystals, OMOL-0 organic).
- Lane-group neighbour kernels on cc 8.0 (S80; they build the same lists): library ABBA on shared GEMM plans OFF23-S water216 `0.830`, OFF23-M water216 `0.914`, OFF24-M water `0.982`; oxide gates unchanged (`loup-s83g`).
- POLAR on cc 8.0 (float32 SIMT GEMMs there): the S52 dot fold, and the own-SGEMM extensions whenever no GEMM cubin is loaded. In-process A/B (`loup-s82a`), fold / extensions / both: POLAR-1-S NaCl216 `0.922` / `0.870` / `0.801`, POLAR-1-M NaCl216 `0.892` / `0.959` / `0.840`, POLAR-1-L NaCl216 `0.887` / `0.926` / `0.842`, POLAR-1-M NbCl5 `0.885` / `0.996` / `0.880`. Crystal gates with both (`loup-s82g`): POLAR-1-S worst 0.47 / 0.72, POLAR-1-M 1.28 / 1.49, POLAR-1-L 1.20 / 0.61, none failing.
- Not adopted on cc 8.0: the own-SGEMM extensions with the GEMM cubin loaded (OFF23-S water216 `1.034`, OMOL-0 `1.008`; they also move the oxide stress row, one forced variant at 3.02).
S85 / S86 (`pol-bias-ln-fuse`, 16 November, 5060 Ti):
- POLAR's small cells run 300+ kernels per step (`POLAR-1-M` `NaCl216`: about 5% of the step idles between them). The MLPs' bias add now runs inside the LayerNorm-SiLU forward and the SCF `q` copy + add as one kernel, with the same float sums: library ABBA on shared GEMM plans, S84 -> S86, `POLAR-1-S` / `-M` / `-L` `NaCl216` `0.990` / `0.995` / `0.994`; crystal gates pass. Three further backward node trims (S87) tied and an in-kernel split-K reduction (S88) was slower; both reverted.
S96-S106 (`wp-receiver-owned`, `gen-pass-glue`, `gen-conv-bwd-l0-red`, `gen-first-fwd-cols`, `md-langevin-draw-threads`, 16 November, 5060 Ti):
- S96: the specialised OMAT-0 path's receiver-owned `w'` now runs below 512 atoms too on `sm_120` (SrTiO3 135 / 320 atoms `0.974` / `0.963`); the two OMAT-0 medium paths are now within 2% at every size from 135 to 5,000 atoms.
- S97-S100 (generic path): no layer-0 embedding gather when every consumer reads a species table, the folded readout's gradient seed assigned (S97) and then its energy and seed folded into the layer's product kernels (S100), the top conv layer's backward assigns the per-edge force vectors (no zero fill, no read-add-store), and each forward conv kernel zeroes its layer's `dx` rows instead of the pass's memset. Library ABBA on shared plans, both orders, S96 -> S100 (product of the steps): OMAT-0 medium generic SrTiO3 `0.989`, MP-0 medium SrTiO3 `0.986`, OFF23-M water216 `0.968`, OFF23-S water216 `0.987`, MH-1 NaCl216 `0.992`; gates pass for every family touched.
- S101: the remaining accumulating per-edge updates (lower conv layers, `gconv_bwd_L2`) use RED on `sm_120` (OMOL-0 water216 `0.999`, lx 2 models tie).
- With S97-S101 the generic path leads the specialised one for OMAT-0 medium on this GPU at every size tested (separate processes, generic / specialised: SrTiO3 5,000 atoms `0.989`, NbCl5 `0.984`, 1,080 atoms `0.993`, 320 atoms `0.964`); the default stayed specialised pending the A100 comparison (job `s100c`) and the owner's call, until S144 retired the specialised path with the owner's approval. Full gate sweep on the S100 library: 20 runs, none failing; S101's families (OFF23-L, OMOL-0, POLAR-1-L) gated again on S101; 77 tests pass on the installed S101 library.
- S105 / S106: `first_fwd_kernel` without its density-only warp (warp 0 sums the density in the former order: `S0` and `D` bitwise unchanged; kernel 255-260 -> 240-245 us on OMAT-0 generic SrTiO3) and the Langevin first half with one thread per normal pair (the same Philox words, noise bitwise unchanged; 7.8 -> 3.6 us on water216). Library ABBA S101 -> S106 on shared plans, both orders: OMAT-0 generic SrTiO3 `0.9985`, OFF23-M water216 `0.991`, MH-1 NaCl216 `0.993`; gates pass; 77 tests pass on the installed S106 library.
- A100 validation of S81-S106 (19 jobs on NHR Alex, queued 16 November, none started at 18:40): job list, libraries, decision rules and the checker in [results/alex-a100-queue-20261116](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/results/alex-a100-queue-20261116/README.md).
S141 (`pol-sf-split-fold`, `gen-conv-fwd-pruned-r5`, 19 November, branch `develop`, 5060 Ti only):
- The structure factor's FP64 warp fold split so each lane folds one value (bitwise the old sums): POLAR-1-M NbCl5 `0.979` (19.66 -> 19.26 ms, the develop library against `d6e97b7` on shared plans), NaCl216 `0.989`, POLAR-1-L NaCl216 `0.994`.
- MP-0 medium's pruned forward (`gconv_fwd_L1s`) stages four harmonics instead of sixteen, uses literal barrier ids (16 -> 6 reserved barriers) and, on `sm_120`, the 16 KB shared-memory configuration: 648 -> 576 us per force call; MP-0 SrTiO3 `0.984`, NbCl5 `0.974` (lab) / `0.995` (develop, noisy).
- Gates: POLAR-1-S / -M / -L crystals, MP-0 medium oxide (default and with prune / sender backward / compaction / chain fold off) and OMAT-0 generic oxide pass; 77 tests pass on the develop library. Rejected or not built in the same round, with their numbers: the ledger's S141 rows (dual-pipe GEMM lanes, R6, literal barriers in the full forward, the bond-frame backward bound and the precision screens).
S142 (`gen-conv-bwd-fold4`, `gen-first-bwd-edge-j64`, 19 November, branch `develop`, 5060 Ti only):
- The lx <= 1 conv backwards fold their four pull partials together (9 shuffles instead of 20, lane 0's sums bitwise the old ones): `gconv_bwd_L1` 2,773 -> 2,741 us per force call on OMAT-0 generic SrTiO3.
- The layer-0 edge backward is compiled for 64 radial columns when the model has them: 424 -> 375 us per force call (OMAT-0 generic SrTiO3), MP-0 NbCl5 62.4 -> 59.0 us.
- Together, against the develop library `595ee89` on shared plans: OMAT-0 medium generic SrTiO3 `0.991` (7.742 -> 7.672 ms), OMAT-0 small SrTiO3 `0.988`, MP-0 medium SrTiO3 `0.988`, MP-0 NbCl5 `0.984` (a first run read `1.020`; that cell scatters by 2%). 13 gate cases (213 rows) and 77 tests pass. The other items of the owner's eighth list: the ledger's S142 rows (six lab variants rejected, four bounds, eight paper verdicts).
S143 (`gen-jit-layer0`, 19 November, branch `develop`, 5060 Ti only): stage 1 of `JIT_DESIGN.md`, the run-time compiler.
- Pieces:
  - layer 0's kernels live in one header (`src/layer0_kernels.cuh`) that `nvcc` compiles and the library embeds;
  - with `LOUP_JIT=1`, NVRTC (loaded with `dlopen`) compiles it at load with the model's layer-0 constants (`src/kernel_ir.hpp`);
  - the cubins are kept in `<cache>/jit/`, and launches go through `cudaLaunchKernel` inside the captured graphs;
  - without NVRTC, or on any failure, the built-in kernels run.
- Result: a tie. `first_bwd_edge` 374.4 → 375.1 µs and `first_fwd` 231.5 → 230.3 µs (OMAT-0 generic SrTiO3); OFF23-S and MH-1 within ±2.4%. Static SASS is 5–37% smaller, but the kernels are latency / load-store bound, and S142 had already compiled in the width that mattered.
- Compiling the spline grid in as well is slower (+2.5%, rejected).
- Gates with `LOUP_JIT=1`: five cases, 68 rows, all pass. Tests: 79 pass (new `tests/test_jit.py`). The switch stays off.

S144 (`gen-jit-conv`, `gen-jit-products`, `gen-jit-epilogue-bound`, `gen-retire-specialised`, 19 November, branch
`develop`, 5060 Ti only): stages 2-5 of `JIT_DESIGN.md`.
- Stage 2: conv layers whose width has no built-in instance are compiled at load (`src/generated_conv.cuh`, on by
  default). OFF23-S water216 (forward at `C` 96) is 1.4% faster than the run-time-width forward in both orders,
  inside the spread.
- Stage 3: bundles carry their product source (`gen_product.py`, `L<t>.prod_src`). A signature the library lacks is
  compiled at load, so a model outside the build set needs no `nvcc`. With every product compiled from the bundle,
  92/92 gate rows pass over seven families.
- Stage 4: not built. The gate passes left after S137 are 1.7-3.9% of kernel time on MH-1, OMOL-0 and POLAR and absent
  elsewhere.
- Stage 5: the specialised OMAT-0-medium path is retired (owner's approval). The generic path is faster: MD SrTiO3
  7.905 → 7.671 ms/step (b/a 0.970), NbCl5 1.756 → 1.713 (0.975), both orders. Gates on the generic-only library: the
  five formerly specialised families pass 90/90 rows. `LOUP_JIT` is unset by default (stages 2 and 3); `1` adds
  layer 0, and `0` compiles nothing.
- Tests on the generic-only library: 47 + 35 = 82 pass (`tests/test_jit.py` with five tests, the refused-bundle test in
  `tests/test_engine_guards.py`, `tests/test_export.py` rewritten for the one exporter).

S145 (`lmp-styles`, `eng-evaluate-one-graph`, `eng-device-io`, `eng-run-graph-reuse`, 19 November, branch `develop`,
5060 Ti under WSL 2 only): LoupMD in LAMMPS (`lammps/`, `LAMMPS_KOKKOS_PLAN.md`).
- Styles: `pair_style loupmd` (host arrays), `pair_style loupmd/kk` (Kokkos device views through the new
  `loup_compute_device`), `run_style loupmd` (the engine integrates between LAMMPS's output steps).
- Accuracy: `run 0` equals the Python engine within two engine runs' spread on five cases (two sheared cells, POLAR-1-M
  among them), forces and all six pressure components.
- Speed, OMAT-0 medium SrTiO3 5,000 / 320 atoms, ms/step: run style 7.84-7.86 / 0.61-0.63, `loupmd` 8.20 / 0.86-0.90,
  `loupmd/kk` 8.38-8.45 / 1.29-1.38; Symmetrix foundation float32/kk in the same job 13.47-13.54 / 1.55-1.59.
- `loup_evaluate` is now one graph launch per call with page-locked staging: 0.95-1.14 → 0.41-0.51 ms per call on
  OFF23-S water216.
- LAMMPS-Kokkos's own step on this machine is 2.43 ms (zero-strength LJ, 648 atoms), which bounds `loupmd/kk` on
  small systems under WSL 2.
- LAMMPS's own features with the pair styles: 26 of 28 setups run (integrators, thermostats, barostats, SHAKE,
  RATTLE, rigid bodies, minimisers, `hybrid/overlay`); table in `LAMMPS_SYMMETRIX_PARITY_PLAN.md`. `loupmd/kk` now
  requests an occasional neighbour list: SrTiO3 320 atoms 1.29-1.38 → 0.97-1.03 ms/step, 5,000 atoms 8.38-8.45 →
  8.14-8.19, and rigid bodies in bonded systems no longer abort under Kokkos.
- Tests on the final library: 47 + 35 of the existing suite (the families' gates among them), 12 in the new
  `tests/test_device_io.py` (the device call and `loup_evaluate` on every rebuild path of the step graph, run calls in
  blocks) and 7 in the new `tests/test_lammps.py` (both pair styles and the run style): 101 pass. `tests/test_lammps.py` has nine
  since the rigid-body test (both modes); those and the 12 device tests pass on the build with the list request.

S146 (`eng-evaluate-ahead`, `lmp-step-profile`, 19 November, branch `develop`, 5060 Ti under WSL 2 only): stage L1 of
`LAMMPS_SYMMETRIX_PARITY_PLAN.md`, and a profile of a LAMMPS step.
- `loup_set_evaluate_ahead` / `pair_style loupmd ahead yes`: the next call's step graph queued ahead behind a stream
  wait on a host word. LAMMPS `a b b a`: SrTiO3 320 atoms 0.838 / 0.826 → 0.752 / 0.783 ms/step, water216 2 - 5%,
  5,000 atoms a tie. Off by default: a queued step blocks default-stream work of the whole process (the first build
  hung in the tests).
- Where a LAMMPS step with `pair_style loupmd` goes (probes, 320 / 5,000 atoms, µs): launch 20 / 51, launch to the
  guard 208 / 225, force pass and results 571 / 7,588, LAMMPS's own work 17 / 200. The force pass equals the engine's
  own step; the fixed 0.2 ms before it is the start of the step graph on an idle GPU (not the host copies: a lab build
  without them showed 107 - 181 µs).
- LAMMPS's own features: 26 of 28 setups run with the pair styles (table in the plan).
- Tests on the final library: 105 pass (47 + 35 of the engine suite, 13 in `tests/test_device_io.py` with the new
  evaluate-ahead test, 10 in `tests/test_lammps.py`).

### 5.4 Fixes Found by the Family Work
- **POLAR LayerNorm-MLP reverse wrote its GEMM output over its own input** (`mlp_bwd`: after the first hidden layer
  the destination buffer was the one holding dz). Harmless while one GEMM tile covered all rows; from ~1,700 atoms
  the tiles raced: perfect NaCl 6x6x6 with POLAR-1-S had 3-11 eV/A forces (random per call) and MD went to NaN.
  Smaller cells changed at the rounding level (perfect NaCl 7x4x4: residual force 1.1e-4 -> 2.5e-6 eV/A). Fixed
  (alternating scratch buffers, LayerNorm reverse in place).
- **k-space phases as exact fixed point**: fractional coordinates are stored as 32-bit fixed point and n . s mod 1
  comes out of wrapping integer arithmetic, so the phase error no longer grows with |n| (elongated NaCl 10x4x4,
  perfect lattice: residual force 3.0e-4 -> 8.7e-5 eV/A).
- **Long-range models use float32 SIMT GEMMs only**: with the 3xTF32 hybrid GEMMs the RTX 4000 Ada failed the
  POLAR-1-S / -L stress gates (NaCl stress ratios 3.4-5.2, POLAR-1-L NaNbO3 up to 6.3) and POLAR-1-S NaNbO3_c0
  returned NaN; with SIMT GEMMs every checked configuration in the **original crystal gate** passes on both GPUs (5.2). This does not claim that every structure passes: the expanded S71 screen has a separate FP32 failure on S NaTaO3_c0. Other families keep the hybrid GEMMs (their original gates pass on both GPUs).
  POLAR's production default remains FP32; the rounded-split experiment is not adopted.
- **POLAR stress references needed two corrections**: reciprocal-cutoff crossings created discrete energy jumps in finite differences; freezing the integer index set removed those jumps but did not remove finite-step truncation on highly curved energies. Production now differentiates the native float64 energy through all strained geometry; frozen-set FD remains a convergence diagnostic. Cache namespace `gate-refs-3-polar-strain-autograd` invalidates the old targets. No yardstick, gate limit or absolute floor was relaxed. [Reference protocol and verification](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/OPTIMISATION_LEDGER.md#gate-polar-strain-autograd).
- **Tensor-core arithmetic has a separate error source**: rounded splitting plus isolated accumulation reduces the original split bias, but exact-TF32-input probes still show downward MMA accumulation bias. The original 90/90 local S/M and 58 original-crystal A100 passes used fixed-step stress targets. Expanded-screen diagnosis found additional FD truncation error: correcting only the target changes A100 S/Nb2O5 TC stress 3.722 -> 2.975 and S/Ta2O5 3.151 -> 0.644. L/Na2O remains a real TC failure: force 4.565 and corrected stress 4.749, while its FP32 baseline passes. M/NbCl5 is about 20% faster on A100 in both construction orders, but **no POLAR TC default is enabled**. [Arithmetic and scope](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/OPTIMISATION_LEDGER.md#gemm-tc-rounded-polar); [reference correction and local diagnosis](https://github.com/FZWINGEL-UBT/LoupMD/blob/HEAD/OPTIMISATION_LEDGER.md#gate-polar-strain-autograd).
- **Pipelined MD margin** (section 3.2, M1): 1 of ~1,600 steps of three 300 K benchmarks had run on an
  incomplete list with a two-step margin; three steps: 0 in every run.

### 5.5 Known Limitations
- MACE-POLAR-1: neutral, singlet, zero field, fully periodic (`include/loupmd.h`).
- MACE-POLAR-1 itself is not stable in 300 K MD on some larger cells: NbCl5 3x3x3 (S, L) and SrTiO3 from 6x6x6
  (M). MACE's own float64 forces after 5 fs of NVE from the same start agree with LoupMD (SrTiO3 6x6x6, POLAR-1-M:
  max |F| 84.83 eV/A in both, difference 7e-4 eV/A; NbCl5 3x3x3, POLAR-1-S: 6.74 eV/A after 1 fs in both, from
  0.61 eV/A at the unrelaxed ideal cell). The same models are stable on NaCl (all sizes run) and NbCl5 2x2x2.
  `bench_family.py` marks such runs `UNSTABLE`.
- Bundles of models with nonlinear (ordered-pair) radial blocks are large: MH-1 74-200 MB, POLAR-1-L 790 MB for
  3 species.
- Generic-path hot spots (5060 Ti, nsys, SrTiO3 5,000 atoms): MH-1 47 ms/step = SIMT SGEMMs ~50% (cuBLAS CUTLASS
  SIMT and the own SGEMM, chosen by the autotune), conv backward / forward of layer 1 12% / 8%, gate backward /
  forward 10% / 5% (estimated ~1 GB of traffic per backward call: near DRAM bandwidth), first-layer outer sum 5%, products 5%.

---

## 6. Release branch (`release/v1`): Stage 1 of the release plan

Measured on 15 November 2026 on the RTX 5060 Ti only (`sm_120`, WSL2, driver 621.14); the workstations were not
used. Plan and task ids: `PLAN.md`. Baseline: `plans/baseline-20261115.md` (the tree of `bac354c`, whose sources
equal `round6-hardening` `11778cd`; library sha256 `df58a9bd2623a502...`). Head: `release/v1` at `a68cc04`
(library `2e7e904abac64b91...`). Every GPU job ran after the card had been idle and under FastMACE's local GPU
reservation, with its own plan cache (`LOUP_CACHE_DIR=$HOME/.cache/loupmd-release`).

| Check | Baseline | Head |
|---|---|---|
| `pytest -q` | 71 passed | 205 passed (at `7bafa23`) |
| `python/test_gate.py` (OMAT-0 medium, oxide set, every forced variant) | PASS, worst force 1.56, stress 1.71 | PASS, worst force 1.55, stress 1.71 |
| `bench_md.py` A/B, baseline first (`NbCl5` / `SrTiO3`, ms/step) | 1.812 / 8.052 | 1.811 / 8.056 (0.9994 / 1.0006) |
| `bench_md.py` A/B, head first | 1.809 / 8.065 | 1.807 / 8.045 (0.9986 / 0.9975) |
| 100 run calls of 10 steps against one call of 1,000 (`SrTiO3` 5,000 atoms, wall time) | 1.1133, 1.1132 | 1.0106, 1.0056 |
| `thermo_every = 20` against off (`NbCl5` / `SrTiO3`) | not applicable | 1.0005, 1.0041 / 1.0003, 1.0007 |

- The standard benchmarks are a tie in both orders: Stage 1 changes no kernel of the default step.
- A run made of short calls cost 11% more than one long call because every call re-captured its graphs and ran
  a force pass before its first step; both are gone (ledger `md-graph-reuse`).
- Memory plan (`loup_plan_memory`, from a 135-atom probe): predicted 487.8 / 1,878.2 / 3,631.7 MB for 5,000 /
  20,480 / 40,000 `SrTiO3` atoms (OMAT-0 medium) against 513.8 / 1,851.8 / 3,636.5 MB measured (-5.1%, +1.4%,
  -0.1%); OMAT-0 small on the generic path at 5,000 atoms 467.3 against 507.5 MB (-7.9%).
- Open domain (testing only, `loup_debug_evaluate_domain`): a periodic cell with its images as ghosts against the
  periodic call, energy / forces / virial stress: OMAT-0 small 3.1e-7 eV/atom, 2.0e-6 eV/A, 2.9e-8 eV/A^3; OMAT-0
  medium on the generic path 1.7e-7, 2.1e-6, 3.2e-8; MH-1 1.5e-8, 1.4e-6, 4.2e-9; OFF23 medium 1.0e-8, 7.4e-7,
  1.1e-9; OMOL-0 extra large (three layers, chain fold off) 7.9e-10, 7.8e-7, 4.3e-10. The periodic call on other
  GEMM kernels (`LOUP_NO_HYBRID=1`) changes by 3.9e-10 to 6.3e-8 eV/atom and 5.5e-7 to 2.5e-6 eV/A. The energy
  deviation of the two OMAT-0 models is larger than that and its cause is not isolated (`PLAN.md` §1.3 D16).
- Energy-only pass (`loup_evaluate2`): equal to the full call's energy within 1e-11 relative on five model paths,
  relaxed and compressed; its speed was not measured.
- Not measured: anything on the RTX 4000 Ada; `nsys` kernel lists; the family benchmarks (`bench_family.py`).

### 6.1 After the merge of `round6-hardening` `e21faa2` (15 November 2026, 04:30 to 05:15)

RTX 5060 Ti only, same conditions as above. Head: `release/v1` at `11edd3c` (library sha256 `9f89f02c26e7792a...`,
`loup_version()` `1.0.0a1+2929486ab9da008c`); the later commits change Python only. Tip: `round6-hardening`
`e21faa2` built from a `git archive` (library `5cbfaca706805301...`). Each library has its own GEMM plan files.

| Check | Tip `e21faa2` | Head |
|---|---|---|
| `pytest -q` | not run | 212 passed (331 s) |
| `python/test_gate.py` (OMAT-0 medium, oxide set, every forced variant) | not run | PASS, 30 rows and 2 reorder checks, worst force 1.52, stress 1.68 |
| `bench_md.py`, tip first, twice (`NbCl5` / `SrTiO3` ms/step) | 1.805 / 8.008; 1.790 / 8.036 | 1.812 / 8.043 (1.0040 / 1.0044); 1.804 / 8.050 (1.0080 / 1.0017) |
| `bench_md.py`, head first, twice | 1.798 / 8.037; 1.802 / 8.038 | 1.807 / 8.019 (1.0052 / 0.9977); 1.793 / 8.030 (0.9946 / 0.9990) |
| `bench_md.py`, tip first, three fresh plan directories a side | 1.822 / 8.029; 1.808 / 8.057; 1.818 / 8.079 | 1.813 / 8.034 (0.9955 / 1.0006); 1.820 / 8.029 (1.0069 / 0.9965); 1.830 / 8.064 (1.0067 / 0.9981) |
| mean of the seven ratios | | 1.0030 / 0.9997 |
| `bench_family.py` OMAT-0 small `SrTiO3` (r6 head head r6) | 4.541 | 4.531 (0.9977) |
| `bench_family.py` OMAT-0 small `NbCl5` (six runs a side) | 1.058 (1.046 to 1.071) | 1.065 (1.043 to 1.115): 1.0066 |
| `bench_family.py` MH-1 `SrTiO3` | 34.978 | 35.010 (1.0009) |
| `bench_family.py` OFF23 medium `water216` (six runs a side) | 1.234 (1.217 to 1.244) | 1.250 (1.203 to 1.289): 1.0127 |
| the same, per block (18 blocks a side, `.tmp_o/water_blocks.py`) | 1.230 (1.127 to 1.317) | 1.223 (1.126 to 1.292): 0.9944 |
| 100 run calls of 10 steps against one call of 1,000 (`SrTiO3`) | not run | 1.0106 |

- Single `NbCl5` runs of the head spread from 1.783 to 1.839 ms (3%) across these jobs, the tip's from 1.781 to
  1.834 ms. The seven ratios' mean for `NbCl5` is 1.0030 with a standard error of 0.0021; `SrTiO3` 0.9997 with
  0.0010. Counted as a tie
  (`PLAN.md` §1.3 D21). The MD loop of the head differs from the tip's by Stage 1's host-side counters only.
- OFF23 medium on the 648-atom water box: no step is pipelined and the rebuild counts are equal in both builds
  (60, 52, 51, ... per 256 steps); its blocks spread by 13 to 15% in both, so the six-run means differ by noise.
  Observation, both builds: the final temperatures of these twelve runs are 272 to 295 K (mean 284 K) for a 300 K
  thermostat; not investigated here.
- Release tools on the same build (`h11` / `h12` snapshots: Python of `93f296e` / `9521e71`):
  `python -m loupmd bench --model omat0-medium` 1.795 / 7.997 and 1.830 / 8.040 ms against `bench_md.py` 1.807 /
  8.034 in between (-0.7% / -0.5% and +1.3% / +0.1%); `--quick` (`SrTiO3` 6x6x6, 1,080 atoms, 2 x 128 steps) 1.787
  and 1.767 ms; `--suite families` for `omat0-small` 4.540 ms; `--quick --compare mace` 395.8 ms/step for
  mace-torch 0.3.16's ASE calculator (float32, 3 x 20 steps) against 1.767: 224 times LoupMD's step;
  `--quick --ab - LOUP_NO_HYBRID=1` 1.774 against 1.781 ms (1.0042). Every record validates against
  `loupmd.bench/1`; the GPU read 1% utilisation before each run.
- `python -m loupmd validate --model omat0-medium`: PASSED, worst ratios energy 0.66, force 1.53, stress 1.67, from
  the reference file `python/test_gate.py` wrote (same key); `test_gate.py` on the same build PASS, 1.52 / 1.68.
  `--structure` on `SrTiO3` 3x3x3 (two copies rattled by 0.05 A, references computed on the GPU): PASSED, 0.89 /
  1.98 / 1.43.
- `lm.calc` (`tests/test_ase_calculator_gpu.py`): ASE `VelocityVerlet`, 1,000 steps of 1 fs on `SrTiO3` 3x3x3 from
  300 K: drift -0.0006 meV/atom/ps, fluctuation 0.0035 meV/atom, 137 K at the end.
- Not measured: anything on the RTX 4000 Ada; `nsys` kernel lists; the gates of the generic families on the merged
  code (`--set organic`, `--set crystals`); `loupmd bench` for models other than OMAT-0 medium and small.

### 6.2 Stage 3 front end and the thermostat target on the device (15 November 2026, 05:20 to 06:10)

RTX 5060 Ti only. Engine build of `e11370e` (library sha256 `6bd216e368ca63f0...`, `loup_version()`
`1.0.0a1+a4baf9f088519beb`) against the build of §6.1 (`9f89f02c26e7792a...`). The change: the Langevin target is
a device scalar that the first half-kick reads and the second advances (ledger `md-langevin-target`).

| Check | Result |
|---|---|
| `bench_md.py`, old build first (`NbCl5` / `SrTiO3`, new / old) | 1.817 / 8.015 against 1.802 / 8.024 ms: 1.0085 / 0.9989 |
| `bench_md.py`, new build first | 1.792 / 8.009 against 1.803 / 8.059 ms: 0.9943 / 0.9938 |
| `python/test_gate.py` | PASS, 30 rows and 2 reorder checks, worst force 1.56, stress 1.73 |
| `pytest -q` (tests of `cb8b020`) | 450 tests, 449 passed and 1 failed (`tests/test_sweeps.py`, the replay schedule on OFF23 medium; it then passed in 12 isolated repeats and had passed in the four full runs since the merge; its message was not kept) |
| ramp 200 to 400 K at 100 K/ps, 5,000 atoms, friction 0.02/fs (`tests/test_schedule_gpu.py`) | mean kinetic temperature 296.6 K, mean target 301.0 K (0.9855); last ten rows 387.4 K for 391.0 K; 7.985 ms/step against 7.839 on the 200 K hold before it |
| `Simulation`, rows and frames every 20 steps against none, 5,000 atoms, wall time of `run()` | 8.078, 8.123 against 7.977, 8.013 ms/step: 1.0132 (1.0132 on the build before, too) |
| resume after 500 of 1,000 NVE steps, 135 atoms | 7.3e-7 A from the uninterrupted run; two uninterrupted runs differ by 9.4e-7 A (7.0e-7 and 7.5e-7 on the build before) |
| `lm.calc`, ASE `VelocityVerlet`, 1 ps, 135 atoms | drift -0.0005 meV/atom/ps |
| `check="gate"` on `SrTiO3` 3x3x3 | passed, worst ratios energy 0.91, force 1.80, stress 1.44 |
| the same with `spline_table_1` of the bundle scaled by 1.02 | `GateFailed`, worst ratios 6,172 / 6,637 / 19,809; no step ran |
| `loupmd md NbCl5_R2SCAN.cif --model omat0-medium --temperature 300 --steps 2000 --timestep 1 --repeat 3 3 3` | 1.883 ms/step with output every 20 steps on `/mnt/d` (1.785 in the engine), 45.9 ns/day, 88 rebuilds, 0 dangerous |
| `loupmd init md ... --profile ultrafast --repeat 2 2 2`, then `loupmd run` (576 atoms, 9,000 steps) | 0.636 ms/step (0.619 in the engine), 135.8 ns/day |
| `lm.md`, `SrTiO3` 4x4x4 (320 atoms), 200 steps | 0.776 ms/step with output (0.675 in the engine) |

- The A/B is a tie: the two orders give 1.0085 and 0.9943 for `NbCl5`, 0.9989 and 0.9938 for `SrTiO3`. The kernel
  now does one FP64 square root and three multiplications more per atom and reads one more value.
- `loupmd md`'s Langevin friction is FastMACE's default, 0.001965/fs; `bench_md.py` uses 0.01/fs, so its 1.80 ms
  and the 1.785 ms here are not the same run.
- Not measured: anything on the RTX 4000 Ada; a schedule on a model of the generic path; the gate inside a run for
  a structure whose float64 reference does not fit the GPU; `loupmd run --resume` on the GPU.

### 6.3 Fixed atoms and the host-side optimisers (15 November 2026, 06:15 to 06:50)

RTX 5060 Ti only. Engine build of `06230cf` (library sha256 `6c2af2c880580942...`) against the build of §6.2
(`6bd216e368ca63f0...`). The engine change adds `loup_set_fixed_atoms` and makes the reported temperature count
3 (N - n_fixed) degrees of freedom; no kernel of the default step changed.

| Check | Result |
|---|---|
| `bench_md.py`, old build first, twice (`NbCl5` / `SrTiO3`, new / old) | 1.0124 / 1.0011 and 1.0050 / 1.0008 |
| `bench_md.py`, new build first, twice | 1.0009 / 0.9986 and 0.9946 / 0.9973 |
| mean of the four | 1.0032 / 0.9995 |
| `python/test_gate.py` | PASS, 30 rows and 2 reorder checks, worst force 1.54, stress 1.68 |
| `pytest -q` at `06230cf` | 458 passed |
| `pytest -q` at `4f20442` | 491 passed, 1 failed: the optimiser-cost test (FIRE 10.5%, LBFGS 87% of the force calls), fixed in the next commit |
| fixed atoms (`tests/test_fixed_atoms_gpu.py`) | 27 of 135 atoms fixed: positions bitwise unchanged after 1,000 Langevin steps; NVE with 20 fixed atoms drifts under 2e-5 eV/atom in 0.6 ps |
| LBFGS and FIRE against ASE's with `lm.calc`, rattled `SrTiO3` 3x3x3, `fmax` 0.05 | 15 steps (ASE 15) and 44 steps (ASE 44); positions within 2.7e-7 and 7.3e-8 A of ASE's |
| the optimiser's own time at 5,000 atoms, 40 steps | FIRE 0.077 ms a step (0.90% of the 8.4 ms force calls); LBFGS 1.407 ms (17.25%) |
| cell relaxation of `SrTiO3` 3x3x3 strained by 2%, `fmax` 0.002 | 157 steps (ASE's `FrechetCellFilter` 157); lattice constants within 1.0e-5 A; stress left 8.1e-5 eV/A^3 |

- The first version of the optimisers used `np.dot` / `np.vdot` on 15,000-element vectors, where NumPy's threaded
  BLAS call cost 0.03 to 0.8 ms each on this machine; plain sums (`einsum`) cost 5 us. LBFGS's two loops are now
  six matrix-vector products and two small triangular solves a step.
- At `1d7380e` the GPU tests of the optimisers and of fixed atoms pass (8 passed; FIRE 0.87%, LBFGS 18.96% of the
  force calls this time). `loupmd relax` on rattled `SrTiO3` 3x3x3: converged after 25 steps, 26 force calls in
  1.31 s. `loupmd md --schedule ramp:0:600:0.5,ramp:600:300:0.5` (135 atoms, 0.420 ms/step with output) and then
  `loupmd quench --min-K 300 --bin-K 150 --per-bin 1`: five frames, 27 to 33 LBFGS steps each, quenched energies
  -7.989531 to -7.989537 eV/atom.
- Not measured: anything on the RTX 4000 Ada; a cell relaxation with a model of the generic path; the full suite
  at `1d7380e` (the last full run, at `4f20442`, had 491 passed and the optimiser-cost test failing).

### 6.4 Centre of mass at rest (`fix_com`) and the current build against the merge build (15 November 2026, 06:55 to 07:35)

RTX 5060 Ti only. Engine build of `42cd77d` (library sha256 `7c835aab4e62167d...`). Two changes: `fix_com`
(the Langevin noise in two passes with FastMACE's mass-weighted projection, used only when it is on; NVE's total
momentum removed at the start of a call), and the Langevin noise coefficients formed once per step by one thread
of the second half-kick instead of per atom (the per-atom square root came in with the ramp of §6.2).

| Check | Result |
|---|---|
| `bench_md.py` against the merge build of §6.1 (`9f89f02c26e7792a`), merge build first, twice (`NbCl5` / `SrTiO3`, new / merge) | 1.0064 / 0.9982 and 1.0047 / 1.0005 |
| the same, new build first, twice | 0.9965 / 0.9964 (one `SrTiO3` run of the new build was disturbed, 8.763 ms, and is left out) and 0.9919 / 0.9976 |
| mean of the four | 0.9999 / 0.9982 |
| `python/test_gate.py` | PASS, 30 rows and 2 reorder checks, worst force 1.55, stress 1.64 |
| `pytest -q` | 496 passed |
| total momentum after 500 Langevin steps, 135 atoms, in units of sqrt(M kB T) | 1.6e-15 with `fix_com`, 1.40 without |
| NVE with `fix_com` from a start with a net drift | the total momentum falls below 1e-7 of its start value; without `fix_com` it is conserved to 1e-6 |
| Langevin with `fix_com` against without, 5,000 atoms, through `lm.Simulation` (a b b a) | 7.992, 7.986 against 7.961, 8.003 ms/step: 1.0009 (0.9995 on the build before) |

- Within one `bench_md.py` job the first run is the fastest for `NbCl5` (1.796 to 1.809 ms) and the later ones are
  slower (1.811 to 1.825), whichever library runs; the two orders cancel this. Across the four jobs the current
  build equals the merge build: nothing of Stage 1 to Stage 4 so far costs speed on the standard benchmarks.
- The build before this one (`fix_com` without the per-step coefficients, library `019f60731d9f9ad0`) read 1.0160 /
  1.0024 and 0.9958 / 0.9982 against the build of §6.3; its full suite: 496 passed and one outdated test.
- Not measured: `fix_com`'s cost on the 1,944-atom `NbCl5` cell; anything on the RTX 4000 Ada.

### 6.5 CSVR, the layout move and the skin chosen from the step size (15 November 2026, 12:05 to 13:10)

RTX 5060 Ti only. Engine builds: `6437f8e` (CSVR; library sha256 `cebdfa27f1af83de...`) and `705af4c` (the layout
move, `loup_get_step_displacement`; `885c3f49f6693412...`). Paths below are those after the move: the developer
scripts are `tools/dev/bench_md.py` and `tools/dev/test_gate.py`.

| Check | Result |
|---|---|
| CSVR's noise, 20,000 draws for 2, 3, 4, 405 and 15,000 degrees of freedom | Kolmogorov-Smirnov p = 0.80 against the normal; 0.80, 0.79, 0.90, 0.84, 0.84 against chi-square |
| CSVR against ASE 3.27's `Bussi` driven by `lm.calc`, the engine's noise fed to ASE, 200 steps, 135 atoms | positions within 2.5e-7 to 2.8e-7 A; transferred energy 2.955326 eV in both |
| CSVR, 20,000 steps of 1 fs at 300 K, tau 10 fs, 135 atoms, three runs | mean 300.5, 301.0, 300.5 K; Kolmogorov-Smirnov p = 0.886, 0.605, 0.639 against the canonical kinetic-energy distribution (190 samples 100 fs apart); conserved quantity drift 0.0000, 0.0000, +0.0003 meV/atom/ps, range 0.03 meV/atom while the thermostat moved 24 to 26 meV/atom |
| CSVR target ramp 100 to 500 K in 2 ps, tau 20 fs | 177 K at 0.5 ps, 284 K at 1 ps, 520 K at the end; held at 500 K: mean 527 K over 1 ps |
| CSVR against Langevin, 5,000 atoms at 300 K, through `lm.Simulation` (a b b a) | 7.988, 8.006 against 7.962, 7.986 ms/step: 1.0029 |
| `loupmd md NbCl5_R2SCAN.cif --repeat 3 3 3 --thermostat csvr --tau 100 --steps 2000` | 1.926 ms/step with output (1.818 in the engine), 96 rebuilds, 0 dangerous |
| gate, CSVR build and move build | PASS, worst force 1.57 / stress 1.55; PASS, 1.52 / 1.72 |
| `bench_md.py`, CSVR build against the build of §6.4, both orders (`NbCl5` / `SrTiO3`, new / old) | 1.0015 / 1.0137 and 0.9910 / 0.9990 |
| the same, move build against the build of §6.4 | 1.0051 / 1.0005 and 0.9987 / 0.9997; mean of these two 1.0019 / 1.0001 |
| `pytest tests/test_[a-e]*.py` on the move build | 240 passed |
| water 216 (MACE-OFF23 small), Langevin 300 K, 1 fs, skin 0.5 A | 0 of 800 steps in the pipelined loop, 0.676 ms/step |
| the same with `skin="auto"`: estimated 0.8 A, largest step measured 0.079 A, skin 0.8 A | 799 of 800 steps pipelined, 0.556 ms/step (0.82 of the fixed skin) |

- The four CSVR-or-later A/Bs against the build of §6.4 average 0.9991 (`NbCl5`) and 1.0032 (`SrTiO3`); the
  1.0137 comes from one job whose last `SrTiO3` run of the old build read 7.934 ms. The Langevin step of the
  benchmark is the same captured graph in all three builds.
- CSVR against NVE from the same start read 1.0137: NVE loses half its kinetic energy to the lattice and then
  rebuilds its neighbour list less often, so it is not the comparison for the thermostat's cost.
- Not run: the full suite on these builds. The run of the CSVR build ended with the crash of 12:32 (bug check
  0xD1 in `nvlddmkm.sys` while two sessions used the GPU), and the WSL distribution was shut down repeatedly from
  13:12 to 13:31 (PLAN.md D40). Anything on the RTX 4000 Ada: the workstations are down (O12).

### 6.6 Nose-Hoover chain, Berendsen NVT, LBFGS on the device and the generic path as the default (15 November 2026, 13:30 to 17:40)

RTX 5060 Ti only. Engine build of `763aaa5` (library sha256 `53abaad3e9aca96c...`); the generic default is
`5d7f363`. Where a row names `7b31011e...`, it was measured on the build before the last change to
`loup_minimize`, which differs in that function only.

| Check | Result |
|---|---|
| Nose-Hoover chain against ASE 3.27's `NoseHooverChainNVT` driven by `lm.calc`, 200 steps, 135 atoms, tdamp 50 fs | positions within 2.1e-7 A (3 thermostats x 1 loop), 2.2e-7 A (1 x 1), 2.5e-7 A (5 x 2); the chain's energy -3.919513 / -5.646661 / -3.204603 eV against ASE's -3.919514 / -5.646663 / -3.204602 |
| Nose-Hoover chain, 20,000 steps of 1 fs, tdamp 100 fs, 135 atoms, three runs | mean 299.6, 300.3, 298.0 K; conserved quantity drift +0.0002 meV/atom/ps, range 0.026 meV/atom while potential plus kinetic moved 29 to 36 meV/atom |
| Nose-Hoover target ramp 100 to 500 K in 2 ps, tdamp 25 fs, thermostat masses of 300 K | 196 K at 0.5 ps, 238 K at 1 ps, 494 K at the end; held at 500 K: mean 497 K |
| Nose-Hoover chain against Langevin, 5,000 atoms at 300 K, `lm.Simulation`, a b b a twice, 400 steps each | 8.157 to 8.223 against 8.119 to 8.159 ms/step, ratio of the medians 1.0067 (single a b b a runs before: 1.0077 and 1.0218) |
| Berendsen against ASE's `NVTBerendsen`, 200 steps, 135 atoms | positions within 2.0e-7 A (tau 50 fs from 300 K) and 2.1e-7 A (tau 2 fs from 900 K, the scale at its bound of 0.9) |
| Berendsen from 100 K to a 300 K target, tau 20 fs; then a ramp to 500 K in 2 ps | 285 K after 0.1 ps, 297 K after 1 ps; 394 K at a target of 400 K, 489 K at the end |
| LBFGS on the device against ASE's `LBFGS` with `lm.calc`, rattled `SrTiO3` 3x3x3 to 0.05 eV/A | 15 steps, ASE 15; positions within 2.5e-7 A |
| LBFGS on the device against the host LBFGS, to 0.02 eV/A, memory 100 and memory 4 | 22 steps each way, positions within 2.8e-7 and 2.2e-7 A; one step per call: 22 steps |
| the optimisers' own time at 5,000 atoms, 40 steps | LBFGS on the device 0.141 ms a step, 1.71% of the force calls (8.04 ms each); FIRE on the host 0.111 ms, 1.14% |
| the same before pinned buffers and the list check after the pass (`7b31011e...`) | LBFGS 0.825 ms a step, 9.70% (force calls 8.29 ms); on the host (§6.3) 1.4 ms, 17% |
| LBFGS with a skin of 0.2 A, rattle 0.12 A: list check before the force pass, after it, and the engine's choice | 30 steps and 5 rebuilds each; 31, 36 and 31 force passes (0, 5 and 0 repeated); positions within 3.7e-7 A |
| cell relaxation on the host (Frechet filter), strained `SrTiO3` 3x3x3 | 157 steps, ASE 157; lattice constants within 7.3e-6 A |
| gate, default (generic) and `--specialised` | PASS and PASS (exit 0 each); worst ratios in the rows the log kept: force 1.91, stress 1.10 and force 1.56, stress 1.53 |
| `bench_md.py`, this build against the build before CSVR (§6.4), both orders (`NbCl5` / `SrTiO3`, new / old), specialised kernels | 1.0035 / 0.9993 and 0.9954 / 0.9992 |
| `bench_md.py`, `LOUP_GENERIC=1` against `LOUP_GENERIC=0` in one library (`7b31011e...`), both orders | `NbCl5` 3x3x3 1.0409 and 1.0399; `SrTiO3` 10x10x10 1.0184 and 1.0144 |
| `loupmd bench --model omat0-medium`, generic path, two runs each | `NbCl5` 3x3x3 1.876, 1.886; `SrTiO3` 10x10x10 8.236, 8.250; `SrTiO3` 6x6x6 (quick) 1.830, 1.837 ms/step |
| the library of `make wheel-lib` (six architectures, 32 MB) on this card, `loupmd bench --quick` | 1.833 ms/step on `SrTiO3` 6x6x6 |
| `pytest tests/test_[a-e]*.py`; `test_f*.py test_gate_cache.py`; `test_[m-q]*.py`; `test_[r-z]*.py` on the tree of `5d7f363` less its last change | 247 passed; exit 0; exit 0; one failure (the sweep replay's energy, 1.6e-8 against a floor of 1e-8 eV/atom) |
| `pytest tests/test_sweeps.py tests/test_run_api.py` with the floor at 1e-7 | 25 passed |
| `tests/test_gate_wrapper.py` (19 minutes), on `7b31011e...` | 10 passed |
| open domain against the periodic call, today's build, two runs of the test and two of a probe | energy within 3.9e-9 (OMAT-0 small), 1.9e-8 (medium), 3.8e-8 (MH-1), 3.4e-9 (OFF23 medium), 1.8e-9 eV/atom (OMOL-0); forces within 1.8e-6 eV/A; the same periodic call with its atoms in another order: 2e-9 to 3.4e-8 eV/atom |
| the same on the two builds of the morning (`2e7e904a`, `9f89f02c`), default GEMMs and `LOUP_NO_HYBRID=1` | OMAT-0 small 2.9e-7 against 1.5e-8 and 4.6e-9; medium 1.6e-7 and 2.2e-7 against 2.6e-8 and 5.9e-9 eV/atom |

- The open domain's energy difference (PLAN.md D16) is the rounding of the tensor-core hybrid GEMMs: on the
  morning's builds it is there with the default GEMMs and gone with `LOUP_NO_HYBRID=1` on every engine. The
  domain's GEMMs have 843 rows where the periodic call has 135, and the autotune picks a kernel per shape from
  timings. Which kernels today's plan files pick was not read out; the difference is small today and can return
  with other plan files.
- The generic path costs 4.0% on `NbCl5` and 1.4 to 1.8% on `SrTiO3` against the specialised kernels in the same
  library. S63 (14 November) had 2.9% and 7.4%; the per-system conv variants (S64) came between.
- The graph-capture tests failed by chance on the generic path: the conv variants are timed at an engine's first
  MD rebuild and a faster one drops the graphs. On 135 atoms the three are near ties, so one of two engines doing
  the same steps captured three graphs more in 4 of 8 repeats. The tests now switch the timing off
  (`LOUP_CONV_TUNE=0`). The behaviour itself is unchanged: such a run captures its graphs twice instead of once.
- Not run: the suite as one run on the last tree (its parts ran on the tree before the sweep floor changed, and the
  two changed files after); `tests/test_gate_wrapper.py` on the last build; the family gates (`--set organic`,
  `--set crystals`); anything on the RTX 4000 Ada or an A100 (O12).

### 6.7 The variable cell and Berendsen NPT (15 November 2026, 17:20 to 18:45)

RTX 5060 Ti only. Engine builds: `1fe8f24` (the variable cell; library sha256 `fbbaee33a44c9267...`), `fd731a9`
(Berendsen NPT; `0e89b6d050da93ff...`) and `7df6798` (`loup_set_reference_volume`; `c640e85347aeb330...`).

| Check | Result |
|---|---|
| NVE through the variable-cell step with a constant cell, 135 atoms: forces after one step against the fixed-cell step, two runs | within 7.5e-7 and 1.6e-6 eV/A; two fixed-cell runs differ by 1.2e-6 |
| the same after 40 steps | positions within 4.3e-8 A, forces within 4.7e-6 eV/A; two fixed-cell runs: 4.9e-8 A, 4.5e-6 eV/A |
| a row's pressure against the stress of an evaluation at the same state plus the ideal-gas part | 6.3236 GPa both |
| cell and positions scaled by 1 - 2e-4 per step for 150 steps (0.9704 in length), then a new engine at the final cell | forces within 2.1e-6 eV/A (1.4e-6 in a second run), energy within 3.7e-8 eV/atom, 6 rebuilds, pressure 26.755 GPa both |
| the same with 1 + 2e-4 per step (1.0305) | forces within 1.8e-6 eV/A, energy within 3.9e-8 eV/atom, 6 rebuilds, pressure -6.329 GPa both |
| Langevin, 5,000 atoms, through the variable-cell step (constant cell) against the pipelined fixed-cell step, a b b a twice | 8.377 to 8.416 against 8.142 to 8.202 ms/step: 1.0296; a second job 8.511 to 8.562 against 8.329 to 8.361: 1.0263 |
| Berendsen NPT, `SrTiO3` 3x3x3 compressed by 1% (11.65 GPa at step 0), target 0 GPa, taup 100 fs, 200 steps | volume 1560.03 -> 1655.083 A^3; pressure 7.05 GPa at step 50, 1.78 GPa at step 200 |
| against ASE 3.27's `NPTBerendsen` taken with one force call per step, three jobs | volume within 3.4e-10, 2.2e-8 and 1.3e-9 relative; positions within 1.8e-7 to 3.0e-7 A |
| against ASE's own class (two force calls per step) | volume within 1.1e-5 relative; 3.2e-6 from a start 0.5 GPa off the target |
| mask (1, 1, 0) against ASE's `Inhomogeneous_NPTBerendsen` with one force call per step | cell lengths 11.86512, 11.86363, 11.59785 A from 11.59785; within 1.0e-9 relative; z unchanged bit for bit |
| to 0 GPa with taup 50 fs, 800 steps | 9.21 GPa at step 10; mean of the last 200 steps -0.022 GPa (scatter 0.14); volume 1678.07 A^3 |
| eight calls of 100 steps against one of 800 | volume within 2.2e-8 relative |
| `lm.Simulation` with `lm.integrators.Berendsen(pressure_GPa=0)`, 200 steps, against one engine call; the `NPTBerendsen` drop-in | volume within 5.8e-10 relative; 1.5e-9; resumed from the restart for 100 more steps: 1666.495 A^3 |
| gate on `1fe8f24`, default (generic) and `--specialised` | PASS, 18 rows, worst force 1.87, stress 1.26; PASS, 30 rows, 1.55 and 1.69 |
| gate on `7df6798` | PASS, 18 rows, 1.88 and 1.20; PASS, 30 rows, 1.55 and 1.71 |
| `bench_md.py`, `1fe8f24` against the build of §6.6, both orders, new / old: specialised kernels | `NbCl5` 1.0105 and 0.9973; `SrTiO3` 1.0028 and 0.9995 |
| the same on the generic path | `NbCl5` 0.9998 and 1.0007; `SrTiO3` 1.0015 and 1.0001 |
| `bench_md.py`, `7df6798` against the build of §6.6, generic path, both orders | `NbCl5` 1.0110 and 1.0000; `SrTiO3` 1.0016 and 0.9979 |
| suite on `1fe8f24`: `test_[a-e]*.py`; `test_f*.py test_gate_cache.py`; `test_[m-q]*.py`; `test_[r-z]*.py` | 247, 38, 150 and 115 passed, 1 skipped |
| suite on `7df6798` less its last change to `lm.md`: the first three parts | 252, 38 and 150 passed |

- The fixed-cell step is the same captured graph as before: the rebuild's two extra kernels and the device cell
  exist only on a handle that has run a variable-cell step.
- The variable-cell step's extra 2.6 to 3.0% is the sum of three things that were not measured apart: stress in
  every force pass, the Cartesian shifts formed per step (24 bytes written per edge), and one host wait per
  step in place of the pipelined loop.
- Berendsen NPT's distance from ASE's own class is PLAN.md D48.
- `test_[r-z]*.py` on `7df6798` ran after this was first written: 120 passed, 1 skipped.
- Not run: `tests/test_gate_wrapper.py` on these builds; the barostat on other systems than `SrTiO3` 3x3x3; its step time;
  anything on the RTX 4000 Ada or an A100 (O12).

### 6.8 Langevin BAOAB NPT, MTK NPT, and what two builds differ by in the benchmark (15 November 2026, 18:45 to 20:25)

RTX 5060 Ti only. Engine builds: `e689cf7` (BAOAB; library sha256 `342ca4cb0ca213fc...`) and `a8a3e06` (MTK;
`433ffe6558b55fa0...`, the build of every later commit of this section). With these every integrator kind of
`include/loupmd.h` is built.

| Check | Result |
|---|---|
| BAOAB NPT at a target of 0 K (nothing is drawn), hydrostatic, 100 steps from `SrTiO3` 3x3x3 compressed by 1%, against ASE 3.27's `LangevinBAOAB` driven by `lm.calc` | volume 1560.03 -> 1599.148 A^3; cell within 2.4e-9 of its length (3.7e-10 in the first run), positions within 9.6e-8 A, velocities within 7.1e-8 |
| the same with the full cell, against ASE's class with the identity in its drag | volume 1726.976 A^3; cell within 7.2e-10 of its length, positions within 1.1e-7 A |
| BAOAB NPT, `SrTiO3` 5x5x5 (625 atoms), 300 K, 1 GPa, T_tau 50 fs, P_tau 500 fs, 20,000 steps after 5,000, rows every 10 steps, blocks of 1,000 steps | pressure 1.000 +- 0.001 GPa, temperature 299.3 +- 0.4 K, volume 12.3305 A^3/atom, relative scatter 2.0e-3 |
| BAOAB NPT, 200 steps in one call, in two calls, from a state block imported into another engine after 100 | volume within 3.7e-9 and 3.0e-9 relative |
| `lm.md(ensemble="NPT")` at 300 K and 1 GPa from the compressed `SrTiO3` 3x3x3, then resumed from the restart | volume 1560.03 -> 1639.64 A^3 after 400 steps, 1707.65 after 600; mean pressure of steps 300 to 600 1.57 GPa from 11.65 at step 0; mean temperature 244 K (still expanding) |
| MTK NPT, isotropic, chains 3x1 and 3x1, 200 steps, against ASE's `IsotropicMTKNPT` | volume 1560.03 -> 1614.760 A^3, ASE the same to 3.5e-10 relative; cell within 1.4e-9 A, positions within 3.0e-7 A; the conserved quantity beside E_pot + E_kin -0.192892 eV in both |
| MTK NPT, full cell, against ASE's `MTKNPT` | volume 1614.554 A^3, relative 3.0e-10; cell within 5.4e-8 A, positions within 2.1e-7 A; -0.208253 eV in both |
| MTK NPT, isotropic, chains 2x2 and 4x3 | volume relative 7.6e-9; positions within 2.2e-7 A; 0.377626 against 0.377625 eV |
| MTK NPT, 20,000 steps of 1 fs at 300 K and 1 GPa, 135 atoms: conserved quantity | isotropic: drift +0.0002 meV/atom/ps, range 0.022 meV/atom; full cell: -0.0002 and 0.026; potential plus kinetic moved 27 to 28 meV/atom |
| the same runs, second half | isotropic 297.8 K, 0.980 GPa, 12.3395 A^3/atom; full cell 299.5 K, 1.004 GPa, 12.3433 A^3/atom |
| MTK NPT in one call, two calls, from an imported state block | volume within 7.3e-11 and 6.4e-9 relative |
| `lm.integrators.MTK` through `lm.Simulation`, and the `IsotropicMTKNPT` drop-in, against one engine call | volume within 6.0e-9 and 1.9e-9 relative |
| gate on `e689cf7`, default (generic) and `--specialised` | PASS, 18 rows, worst force 1.82, stress 1.41; PASS, 30 rows, 1.50 and 1.83 |
| gate on `a8a3e06` | PASS, 18 rows, 1.90 and 1.21; PASS, 30 rows, 1.57 and 1.71 |
| suite on `e689cf7` with the BAOAB front end: `test_[a-e]*.py`; `test_f*.py test_gate_cache.py`; `test_[m-q]*.py`; `test_[r-z]*.py` | 257, 38, 152 and 123 passed, 1 skipped |
| suite on `a8a3e06` with the MTK front end | 258, 38, 160 and 123 passed, 1 skipped |
| `bench_md.py`, generic path, `e689cf7` against the build of §6.6, each with its own stored plans, three pairs (new / old; old first, new first) | `NbCl5` 1.0127 and 1.0026, 1.0109 and 1.0032 (the first of these while CPU tests ran), 1.0099 and 1.0025; `SrTiO3` 0.9994 and 1.0009, 1.0093 and 1.0007, 1.0027 and 1.0003 |
| the same, `a8a3e06` against §6.6's build, old new new old twice | `NbCl5` 1.855, 1.852, 1.855, 1.852 against 1.832, 1.850, 1.841, 1.844 ms/step (1.0064); `SrTiO3` 8.049 against 8.041 (1.0010) |
| `e689cf7` against §6.6's build with a fresh plan directory per run, three runs of two each | `NbCl5` 1.853 to 1.864 (mean 1.855) against 1.828 to 1.860 (mean 1.849); `SrTiO3` 8.054 against 8.043 |
| four builds (§6.6's, `1fe8f24`, `7df6798`, `a8a3e06`), each with its own script, a fresh plan directory per run, four rounds | `NbCl5` means 1.853, 1.857, 1.861, 1.858 ms/step (single runs 1.839 to 1.864); `SrTiO3` 8.042, 8.055, 8.052, 8.047 (8.024 to 8.060); the last build against the first 1.0027 and 1.0006, and 1.001 and 1.000 without the job's first run (1.839, 8.024) |

- The fixed-cell benchmark has not changed: with fresh plans the four builds agree within 0.4% on `NbCl5` and 0.2% on `SrTiO3`, which is less than one build's own run-to-run spread (0.6 to 1.3%) and not in the order of the commits. The pairs with stored plans read up to 1.3% apart because each library keeps the GEMM plans it timed once, and because the first run of a job is about 1% faster than the later ones: it was the old build in every old-first pair and in round 1 of the four-build job.
- BAOAB's and MTK's own step times were not measured; both run in the variable-cell step of §6.7 (1.026 to 1.030
  of the pipelined fixed-cell step) with one single-thread kernel and one or two kinetic sums more.
- Not run: `tests/test_gate_wrapper.py` on these builds; the family gates (`--set organic`, `--set crystals`);
  the NPT integrators on any other system than `SrTiO3`; anything on the RTX 4000 Ada or an A100 (O12).

### 6.9 The family gates on the last integrator build, and kernel plugins (15 November 2026, 20:15 to 21:10)

RTX 5060 Ti only. Gates: `tools/dev/test_gate.py MODEL [--set ...]` on the build of `a8a3e06` (library sha256
`433ffe6558b55fa0...`), every model on the generic path, references from the cache except OMOL-0 with charge 0
and multiplicity 1 (computed on the CPU in this run). Each row: gate rows, failures, the worst force and stress
ratios (a quantity passes up to 3).

| Model, set | Result |
|---|---|
| MACE-OFF23 small, medium, large; OFF23b medium; OFF24 medium (`--set organic`; large and the last two with `--ref-device cpu`) | 8, 24, 8, 24, 24 rows, 0 failed; force 0.62, 0.33, 0.43, 0.94, 0.69; stress 1.88, 0.62, 0.91, 0.53, 1.03 |
| MACE-MH-1; MACE-POLAR-1 S, M, L (`--set crystals`; L with `--ref-device cpu`) | 18, 5, 18, 6 rows, 0 failed; force 0.90, 0.70, 2.10, 2.20; stress 0.31, 0.59, 0.73, 0.83 |
| MACE-OMAT-0 small; MP-0b3 medium; MPA-0 medium; MP-0 large (`MACE_MPtrj_2022.9`); MP-0 medium (default set) | 6, 18, 18, 6, 18 rows, 0 failed; force 1.34, 1.15, 2.02, 1.30, 0.63; stress 1.33, 0.83, 2.19, 0.99, 0.38 |
| MATPES PBE and r2SCAN (`--set crystals`) | 18 and 18 rows, 0 failed; force 1.02 and 1.41; stress 1.02 and 0.62 |
| MACE-OMOL-0 extra large (`--set organic --charge 0 --spin-multiplicity 1 --ref-device cpu`) | 8 rows, 0 failed; force 0.83, stress 0.73 |
| MACE-OMAT-0 medium, default set, generic and `--specialised`, on the build of `8b858e0` (`9d39c8e75f8571b1...`) | 18 and 30 rows, 0 failed |

Kernel plugins (`8b858e0`, PLAN.md S2-T06 and D57):

| Check | Result |
|---|---|
| `kernels.build_plugins` on `mace-omat-0-medium.model`, forced (nvcc 13, `-arch=sm_120`, the shared CUDA runtime) | two plugins, 76,368 and 157,720 bytes |
| `SrTiO3` 3x3x3 with the library's own kernels of one signature hidden, so the plugin's run; three jobs | energy within 1.1e-8 eV/atom, forces within 9.2e-7 to 1.2e-6 eV/A, stress within 5.1e-9 eV/A^3 of the library's own kernels |
| the same with nvcc's default static runtime in the plugin | `loup_evaluate: invalid resource handle`: kernels registered with a second copy of the runtime |
| a hidden signature and no plugin | `no compiled product kernel for signature ...` naming the folder searched and `loupmd build-kernels` |
| `loupmd build-kernels omat0-small` | "nothing to build: every kernel of mace-omat-0-small.model is there" |
| `codegen/gen_generic.py` after the change, against the tracked `generated_generic.cu`, `.cuh` and manifest | byte-identical |

- Not run: `loupmd validate --set organic | crystals` (the same library code as `test_gate.py`, through the
  command); the gate wrapper tests on these builds; a model whose kernels the library really lacks; a plugin built
  for another architecture than `sm_120`; anything on the RTX 4000 Ada or an A100 (O12).

### 6.10 The re-homed tests, NPT profiles and the pinned CUDA runtime (15 November 2026, 21:00 to 21:25)

RTX 5060 Ti only; the library is the build of `8b858e0` (sha256 `9d39c8e75f8571b1...`), unchanged since §6.9.

| Check | Result |
|---|---|
| `pytest -q tests/cpu` in the development environment, GPU hidden (after `fba7376`) | 327 passed, 1 skipped, 56 s |
| `pytest -q tests/cpu` in a venv with numpy, scipy, ase and pytest only (no torch, mace, e3nn, cuequivariance), no `nvidia-smi` on the PATH, no library in the tree, `LOUPMD_MODELS` unset (at `a80f166`) | 319 passed, 7 skipped, 23 s |
| `pytest tests/gpu -m "not acceptance" --durations=0` (at `a80f166`, before the full tier was marked) | 262 passed, 10 deselected, 612 s |
| the tiers by collection (at `7875527`) | 242 fast, 20 full, 10 acceptance |
| NPT profiles (`fba7376`, O23) on the fake engine: `loupmd md --profile` with a profile at 0.5 GPa | Langevin BAOAB at 0.5 GPa; `--friction` and `--pressure` keep or replace the profile's pressure |

The pinned CUDA runtime (PLAN.md D58). `tools/dev/bench_md.py`, generic path, a fresh plan directory per run, four
rounds alternating; "system" is `/usr/local/cuda-13.3` (cudart 13.3.29, cuBLAS 13.5.1.27, what every figure of
this file so far ran on), "wheels" the NVIDIA wheels the package pins (cuda-toolkit 13.0.3: cudart 13.0.96, cuBLAS
13.1.1.3), put first with `LD_LIBRARY_PATH`; the loaded libraries were read from `/proc/self/maps` on each side.

| Runtime | `NbCl5` 3x3x3, ms/step (mean; range) | `SrTiO3` 10x10x10, ms/step (mean; range) |
|---|---|---|
| system 13.3 | 1.862; 1.847 to 1.868 | 8.042; 8.013 to 8.061 |
| wheels 13.0.3 | 1.864; 1.859 to 1.866 | 8.047; 8.043 to 8.050 |
| wheels / system | 1.0012 | 1.0007 |

- A tie: the difference is inside the spread of either side.
- All 69 CUDA symbols `libloupmd.so` imports (`nm -D`) are defined in the wheels' `libcudart.so.13`,
  `libcublas.so.13` and `libcublasLt.so.13`. The local build needs GLIBC 2.38 and GLIBCXX 3.4.32, so the wheel's
  library has to come from the container build.
- Not run: the fast tier on its own (about 320 s of the 612 s run, by subtraction); the acceptance tier after the
  move; an NPT profile on the GPU; the wheel build (its scripts are written, the image is not built).

### 6.11 The tile planner, the fast tier alone and the version 0.1.0a1 (15 November 2026, 22:00 to 22:30)

RTX 5060 Ti only. The library is the build of the working tree with the planner and the version `0.1.0a1` (sha256
`929a8f5a57d5a5f4...`); the planner is host code that nothing in the step calls yet.

| Check | Result |
|---|---|
| `pytest tests/cpu/test_tile_plan.py` (g++ build of `src/tile_plan.cu`) | 14 passed; 1,026,895 atoms planned in 72 ms (criterion 0.5 s) |
| `pytest tests/gpu` fast tier alone (default selection) | 243 passed, 30 deselected, 284 s |
| `pytest tests/gpu -m full` | 20 passed, 253 deselected, 239 s |
| `tools/dev/test_gate.py`, default and `--specialised` | default: 18 rows PASS, 0 FAIL; `--specialised`: 32 PASS, 0 FAIL |

A/B against the build before (`9d39c8e75f8571b1...`, §6.10), `tools/dev/bench_md.py`, generic path, a fresh plan
directory per run, four rounds alternating:

| Build | `NbCl5` 3x3x3, ms/step (mean; range) | `SrTiO3` 10x10x10, ms/step (mean; range) |
|---|---|---|
| before (`9d39c8e7`) | 1.859; 1.850 to 1.869 | 8.037; 8.006 to 8.061 |
| with the planner (`929a8f5a`) | 1.862; 1.858 to 1.868 | 8.046; 8.041 to 8.058 |
| ratio | 1.0019 | 1.0012 |

- A tie: each difference is inside the other side's range, as expected for code the step does not run.
- Not run: the wheel (Docker Desktop does not start, PLAN.md D59), the acceptance tier, anything on another GPU.

### 6.12 Per-tile neighbour lists (15 November 2026, 22:35)

RTX 5060 Ti only; library of the working tree after `40bdf96` with `loup_debug_domain_edges` (sha256
`d289193f6b995db7...`). `pytest -s tests/gpu/test_tile_lists.py`: `SrTiO3` 20x20x20 (40,000 atoms; rattled by
0.05 A, sheared by up to 1%), MACE-OMAT-0 medium on the generic path, skin 0.5 A, planner reach = cutoff + skin +
0.01 A.

| Receiver cap | Tiles (grid) | Edges of the whole system | Edges in one list only | Ghost candidates | Sending along no edge |
|---|---|---|---|---|---|
| 12,000 | 4 (1x1x1) | 3,969,958 | 0 | 89,790 | 38,879 (43.3%) |
| 3,000 | 16 (2x2x2) | 3,969,958 | 0 | 103,230 | 28,654 (27.8%) |

- The candidates without an edge are those of the corners of a tile's bounding box (S5-T01 lists every image
  within reach of the box, not of the atoms): a tile that keeps them carries up to 43% more ghost rows than it needs.
- Not measured: the time of a tile's list build, and of a second build without the dropped candidates.
- `pytest tests/gpu` with no marker filter (fast, full and acceptance tiers, with the two tests above) on this
  build: 275 passed in 1,458 s. The acceptance tier after the move of S2-T11 thus passes as well.

### 6.13 The tiled call (15 November 2026, 23:30)

RTX 5060 Ti only; library of the working tree after `9abd36d` with `loup_debug_evaluate_tiled` (sha256
`d7ad0d9be7f8ce99...`). `pytest -s tests/gpu/test_tiled.py`, skin 0.5 A; each line compares the tiled call with
the whole-system call of the same build (energy per atom, largest force and stress component).

| Model | Atoms | Tiles | Default GEMMs: dE eV/atom, dF eV/A, dS eV/A^3 | No hybrids on either side | Whole system, default against no hybrids |
|---|---|---|---|---|---|
| OMAT-0 medium (generic) | 40,000 `SrTiO3` | 8 | 6.8e-7, 5.8e-6, 2.8e-8 | 1.2e-9, 1.8e-6, 2.1e-10 | 1.3e-8, 1.3e-6, 3.2e-9 |
| OMAT-0 small | 40,000 `SrTiO3` | 8 | 4.5e-7, 6.7e-6, 4.7e-8 | 1.2e-9, 1.7e-6, 1.6e-10 | 1.7e-10, 1.1e-6, 2.8e-10 |
| MH-1 | 24,565 `SrTiO3` | 8 | 4.4e-8, 5.5e-6, 4.3e-9 | 2.5e-10, 1.7e-6, 5.6e-10 | 4.4e-8, 1.6e-6, 1.6e-9 |
| OFF23 medium | 41,472 water | 8 | 4.3e-8, 2.9e-6, 1.5e-9 | 2.6e-10, 1.2e-6, 8.3e-11 | 4.0e-9, 1.6e-6, 6.4e-10 |
| OMOL-0 extra large (five sweeps) | 1,296 water | 4 | 5.9e-9, 1.2e-6, 1.4e-9 | 8.1e-10, 1.5e-6, 6.1e-10 | 1.9e-9, 1.2e-6, 1.1e-9 |

- Without hybrids the tiled call is the whole-system call to float32 rounding; with the default GEMMs the
  difference is the hybrid kernels' rounding where a tile's GEMM shape gets another kernel (PLAN.md D16, D60).
- MH-1's whole-system call runs out of memory at 40,000 atoms on 16 GB (24,565 fit): the case for tiling.
- No device memory is left behind: three tiled and two whole-system calls in one process leave 1,129 MiB in use
  before and after (`cudaMemGetInfo`).
- `pytest tests/gpu -m "not acceptance"`: 270 passed, 1 failed in 653 s. The failure, `test_the_calculator_equals_evaluate` (two engines of one bundle 3.0e-7 eV/atom apart against its bound of 2e-7), passed five runs in a row on this build and three on the build before; its bound is now 1e-6 eV/atom (PLAN.md D61).
- A/B against the build of §6.12 (the tiled code is not on the step path): four rounds alternating, a fresh plan directory per run: `NbCl5` 1.898 ms/step before and 1.894 after, `SrTiO3` 8.230 and 8.233 (ratios 0.998 and 1.0004), a tie. Both sides ran about 2% slower than the runs of §6.11 earlier that evening; only the alternating comparison counts.
- Not measured: the tiled call's time (every tile sweep sets its domain up again; S5-T06, S5-T10).

### 6.14 The gate in tiled mode and the tiled call's time (16 November 2026, 00:05)

RTX 5060 Ti only; library `d7ad0d9be7f8ce99...` (the build of `330e155`). `loupmd validate --model LABEL
--capacity tiled` (about four tiles per cell), references from the shared cache (`LOUP_GATE_CACHE`).

| Labels | Set | Worst ratio (energy, force, stress) | Result |
|---|---|---|---|
| omat0-medium | oxide | 0.59, 1.93, 1.32 | PASS |
| omat0-small | oxide | 0.35, 1.31, 1.44 | PASS |
| mp0-medium, mp0-large, mp0b3-medium | oxide | at most 0.13, 1.34, 0.95 | PASS |
| mpa0-medium | oxide | 0.32, 2.08, 2.19 | PASS |
| matpes-pbe, matpes-r2scan | crystals | at most 0.19, 1.38, 0.93 | PASS |
| mh1-omat, mh1-mp, mh1-r2scan | crystals | at most 0.10, 0.88, 0.36 | PASS |
| off23-small, off23-medium, off23-large, off23b-medium, off24-medium | organic | at most 0.01, 1.05, 1.74 | PASS |
| omol0-xl (charge 0, multiplicity 1) | organic | 0.00, 0.79, 0.88 | PASS (611 s, references on the CPU) |
| polar1-s | crystals | | refused: no sweeps with long range |

The tiled call's time (S5-T03's driver as committed; one warm-up call, then one timed call; the whole-system call
the mean of five after a warm-up):

| Model | Atoms | Whole system, us/atom | Tiled (tiles), us/atom | Tiled / whole |
|---|---|---|---|---|
| OMAT-0 small | 24,565 | 0.91 | 41.4 (2); 55.5 (3) | 46; 61 |
| OMAT-0 small | 40,000 | 0.90 | 30.1 (2); 75.0 (8) | 34; 83 |
| OMAT-0 medium | 24,565 | 1.65 | 45.1 (2); 44.4 (3) | 27; 27 |
| OMAT-0 medium | 40,000 | 1.66 | 25.9 (2); 67.1 (8) | 16; 40 |

- The time grows with the tiles, not the atoms: about 0.3 to 0.5 s per tile per call. Every tile sweep sets the
  handle up again (allocations, a list build with host syncs, GEMM tuning for new row counts), 24 set-ups and 8
  builds at 8 tiles. This is the eager stage of FastMACE's tiled design; FastMACE's steady tiled call is 1.05 to
  1.2 times its whole-system cost per atom (`FastMACE/docs/validation/tiled/tiled-1m-speed.md`), with a fixed
  workspace, bodies per padded slot size and kept lists (S5-T05, S5-T06, S5-T10).

### 6.15 The tile workspace (16 November 2026, 00:15)

RTX 5060 Ti only; library `045194b7dcd2a738...` (the working tree after `56a3a5d`). One set of buffers for every
tile instead of a full set-up per tile sweep (ledger `tile-workspace`). `pytest -s tests/gpu/test_tiled.py
tests/gpu/test_tile_lists.py tests/gpu/test_open_domain.py`: 15 passed, the tiled call's differences as in §6.13
(without hybrids at most 1.8e-9 eV/atom, 2.1e-6 eV/A).

| Model | Atoms | Tiles | Whole system, us/atom | Tiled before (§6.14) | Tiled now | Tiled / whole now |
|---|---|---|---|---|---|---|
| OMAT-0 small | 24,565 | 3; 2 | 0.92 | 55.5; 41.4 | 15.0; 12.8 | 16.4; 14.0 |
| OMAT-0 small | 40,000 | 8; 2 | 0.85 | 75.0; 30.1 | 23.2; 9.5 | 27.4; 11.2 |
| OMAT-0 medium | 24,565 | 3; 2 | 1.64 | 44.4; 45.1 | 19.1; 12.9 | 11.6; 7.8 |
| OMAT-0 medium | 40,000 | 8; 2 | 1.63 | 67.1; 25.9 | 19.7; 10.0 | 12.1; 6.1 |

### 6.16 Tile lists kept and the workspace kept between calls (16 November 2026, 00:40)

RTX 5060 Ti only; library `656d0a580da22ba9...` (the working tree after `31f0ac3`). Ledger `tile-kept-lists`.
`pytest tests/gpu/test_tiled.py tests/gpu/test_tile_lists.py`: 9 passed, with a new test that a kept workspace (other tiles, a smaller system) gives a fresh engine's result. Median of three tiled calls after a
warm-up call on the same engine (`.tmp_o/probe_tiled_time.py`):

| Model | Atoms | Tiles | Whole system, us/atom | Tiled before (§6.15) | Tiled now | Tiled / whole now |
|---|---|---|---|---|---|---|
| OMAT-0 small | 24,565 | 3; 2 | 0.91 | 15.0; 12.8 | 2.39; 1.94 | 2.6; 2.1 |
| OMAT-0 small | 40,000 | 8; 2 | 0.89 | 23.2; 9.5 | 2.55; 2.01 | 2.9; 2.3 |
| OMAT-0 medium | 24,565 | 3; 2 | 1.64 | 19.1; 12.9 | 4.01; 3.62 | 2.4; 2.2 |
| OMAT-0 medium | 40,000 | 8; 2 | 1.65 | 19.7; 10.0 | 4.33; 2.97 | 2.6; 1.8 |

- Phases of the second call (OMAT-0 medium, 40,000 atoms, 8 tiles, `LOUP_DEBUG_TILE_TIMES=1`): plan 3 ms,
  candidate lists 11, kept lists 23, state buffers 4, forward sweeps 10, last-layer sweeps 58, backward sweeps 20.
- The first tiled call on a new workspace is slow (sweeps 5.3 s at 8 tiles, 1.5 s at 2): each tile's row count is
  a GEMM shape of its own, looked up and timed once. Size buckets for the tile shapes are the next step.
- Not measured: the A/B of the step path (the tiled code and the new handle flag are not on it); other models.

### 6.17 The capacity mode (16 November 2026, 01:30)

RTX 5060 Ti only; library `6b30910ad0011307...` (the working tree after `4c93637`). `loup_plan_execution` and
`loupmd/capacity.py` (PLAN.md S5-T05, D62). `pytest -s tests/gpu/test_capacity.py`, OMAT-0 medium, skin 0.5 A:

| Cell | Atoms | Mode chosen | Cap, tiles | Plan: whole; tiled state + workspace | Budget | Device peak |
|---|---|---|---|---|---|---|
| `SrTiO3` 8x8x8, rattled | 2,560 | whole | - | 0.29 GiB; - | 13.91 GiB | (plan's estimate) |
| `SrTiO3` 40x40x40 | 320,000 | tiled | 65,536, 8 | 32.12 GiB; 2.34 + 8.10 GiB | 14.60 GiB | 8.22 GiB (56%) |

- 320,000 atoms: the energy per atom is the 4x4x4 cell's (whole-system call) to 1e-6 eV, the largest force within
  1e-5 eV/A of that cell's. No user setting: `capacity.evaluate(engine, atoms)`.
- The auto mode on 2,560 atoms gives the whole-system call's result to two engines' spread (D61).
- Tests on this build: `pytest tests/gpu` (all tiers) 286 passed in 760 s, `tests/gpu/test_capacity.py` among them; `pytest tests/cpu` 347 passed, 1 skipped.
- Not measured: the time per call at 320,000 atoms (the first call on a new workspace tunes every tile shape;
  S5-T10), other models, the A/B of the step path (the step path is not changed).

### 6.18 Tiled MD: lists kept across steps (16 November 2026, 02:20)

RTX 5060 Ti only; library `cc8832915e8d60fa...` (the working tree after `8afe99f`). PLAN.md S5-T06, D63.
`pytest -s tests/gpu/test_tiled_md.py`: 2 passed. Kept lists against the whole-system call without hybrids, 2,560
atoms in 3 tiles: within 1e-7 eV/atom and 1e-5 eV/A after moves under skin/2 (kept) and after a 0.28 A move
(rebuilt, same cap). Constant-energy runs, OMAT-0 medium, `SrTiO3`, 1 fs, skin 0.5 A, from 300 K:

| Atoms | Mode, cap, tiles | Steps | List builds | Time per step | Drift, meV/atom/ps | Total energy spread, meV/atom |
|---|---|---|---|---|---|---|
| 5,000 | tiled (set), 2,000, 3 | 400 | 18 | 22.8 ms | 0.0014 | 0.026 |
| 320,000 | tiled (plan), 65,536, 8 | 1,000 | 55 | 1.120 s = 3.50 us/atom | 0.0002 | 0.027 |

- 320,000 atoms: device peak 8.58 GiB of a 14.51 GiB budget; the whole-system call at 40,000 atoms takes
  1.65 us/atom, so the tiled step is 2.1 times as long per atom (`.tmp_o/probe_nve_320k.py`; 1,123 s wall).
- The step time includes the host integrator, the transfers and the 55 list builds (a build re-plans and lists
  every tile; one per 18 steps here).
- `pytest tests/cpu`: 350 passed, 1 skipped.
- Not measured: thermostatted tiled MD (not built, D63); other models; the step path's A/B (not changed).

### 6.19 Large boxes and the edge limit (16 November 2026, 03:30)

RTX 5060 Ti only; library `91fb0fdfb9026c7f...` (the working tree after `3c6ab5c`). PLAN.md S5-T09, D64.

- `pytest -s tests/gpu/test_large_box.py` (3 passed): a 1,080-atom `SrTiO3` piece near the far corner of a 1,000 A
  box against the same piece in a 100 A box, without hybrids: whole-system call 5.2e-9 eV/atom, 1.8e-6 eV/A;
  tiled call 6.7e-10 eV/atom, 8.7e-7 eV/A. With the edge limit lowered to 600,000, 13,720 atoms (about 1.37M
  edges) are refused by the whole-system call with the message and run in tiles by `capacity.evaluate`.
- Every list rebuild now sums the degrees in 64 bits (one kernel over the atoms and an 8-byte read with the edge
  count it already reads).
- `pytest tests/gpu -m "not acceptance"`: 281 passed in 642 s. `pytest tests/cpu`: 350 passed, 1 skipped.

| Round | NbCl5, S5-T06 build | NbCl5, this build | SrTiO3, S5-T06 build | SrTiO3, this build |
|---|---|---|---|---|
| 1 | 1.889 | 1.915 | 8.215 | 8.232 |
| 2 | 1.889 | 1.892 | 8.224 | 8.158 |
| 3 | 1.894 | 1.886 | 8.156 | 8.169 |
| 4 | 1.892 | 1.909 | 8.164 | 8.166 |
| Mean | 1.891 | 1.901 (+0.5%) | 8.190 | 8.181 (-0.1%) |

`tools/dev/bench_md.py`, OMAT-0 medium, ms per step, a fresh `LOUP_CACHE_DIR` per run. A tie: two builds read up to
1.3% apart on NbCl5 (§6.8), and the added work is a few microseconds per rebuild, about one rebuild per 20 steps
(estimate, not measured on its own).

### 6.20 The tiled mode in `lm.md` and `Simulation` (16 November 2026, 03:30)

RTX 5060 Ti only; library `91fb0fdfb9026c7f...` (no C change since §6.19; Python only). PLAN.md S5-T12, D65.

- `pytest -s tests/gpu/test_tiled_md.py` (5 passed in 32 s):
  - a tiled `Simulation` (cap 2,000, 3 tiles, host velocity Verlet) against the whole-system device NVE loop,
    5,000 atoms, 20 steps of 1 fs from 300 K, no hybrids: positions 3.6e-8 A, energy 8.4e-9 eV/atom apart;
  - tiled Langevin, 5,000 atoms from rest, 300 K, 0.05/fs, 200 steps of 2 fs: 298.9 K at the end, 30.7 ms per step
    (measured by the engine's wall clock around the host loop);
  - `loupmd md --capacity auto` on 320,000 atoms (`SrTiO3` 40^3), 10 steps: 8 tiles of at most 65,536; the report's
    plan line says so, memory "the whole system would need 32.12 GiB; tiled 10.45 GiB planned, 14.00 GiB free".
- `pytest tests/gpu -m "not acceptance"`: 284 passed in 604 s. Every GPU `Simulation` test now runs with
  `capacity="auto"`, so a probe tile is planned (lists only) before each whole-system run.
- `pytest tests/cpu`: 358 passed, 1 skipped.
- Not measured: the setup time the plan adds to a whole-system run (one 4,096-atom list build and its
  allocations; estimate well under a second); the step path is unchanged, so no step A/B was run.

### 6.21 Tile GEMM size buckets (16 November 2026, 04:10)

RTX 5060 Ti only; library `d2f9b371d1e43994...` (the working tree after `3f02afc`), against `91fb0fdf` (§6.19).
PLAN.md S5-T10, D66; ledger `tile-gemm-buckets`.

First tiled call on a new engine, the second call, and a call after a move that rebuilds the lists (new tile row
counts); `SrTiO3` 20^3 rattled, an empty plan cache per process (`.tmp_o/probe_first_call.py`):

| Model, tiles | Before (s): first, second, after a rebuild | Buckets (s) | Buckets off on the new build (s) |
|---|---|---|---|
| OMAT-0 medium, 12 of 5,000 | 5.95, 0.094, 4.36 | 2.21, 0.095, 0.86 | 5.56, 0.095, 4.39 |
| OMAT-0 medium, 2 of 20,000 | 1.80, 0.088, 0.38 | 1.74, 0.087, 0.13 | 1.70, 0.086, 0.35 |
| OMAT-0 small, 12 of 5,000 | 4.19, 0.056, 3.23 | 1.66, 0.056, 0.51 | 4.44, 0.056, 3.02 |

- `pytest -s tests/gpu/test_tiled.py -k buckets`: 114 GEMM shapes timed with buckets, 358 without (40,000 atoms,
  11 tiles of 5,000, no hybrids); results 3.7e-10 eV/atom and 1.9e-6 eV/A apart.
- Tiled MD, one run each (not an A/B): 5,000-atom NVE 18.9 -> 16.3 ms per step; Langevin 30.7 -> 17.9 ms per step.
- The tiled 3x gate (`loupmd validate --capacity tiled`) on this build: omat0-medium 0.57, 1.81, 1.23; omat0-small
  0.34, 1.31, 1.50; mp0-medium 0.02, 0.60, 0.52; mpa0-medium 0.33, 2.05, 2.23; matpes-pbe (crystals) 0.19, 1.04,
  1.00; mh1-omat (crystals) 0.10, 0.88, 0.29; off23-medium (organic) 0.01, 0.33, 0.54. All PASS (§6.14: the same
  labels before).
- `test_the_tiled_call_gives_the_whole_system_result` with the default GEMMs, fresh plans, three runs per build:
  before 0.48, 1.03, 0.72e-6 eV/atom; buckets 0.87, 0.12, 1.42e-6 (and 1.35e-6, 1.26e-6 in the suite runs);
  without hybrids at most 1.6e-9 on both. The bound is now 2e-6 (D66).
- Step A/B (whole-system path; four rounds alternating, a fresh plan directory per run), ms per step:

| Round | NbCl5, before | NbCl5, buckets | SrTiO3, before | SrTiO3, buckets |
|---|---|---|---|---|
| 1 | 1.895 | 1.897 | 8.215 | 8.227 |
| 2 | 1.896 | 1.903 | 8.228 | 8.246 |
| 3 | 1.899 | 1.915 | 8.221 | 8.230 |
| 4 | 1.916 | 1.910 | 8.221 | 8.221 |
| Mean | 1.902 | 1.906 (+0.2%) | 8.221 | 8.231 (+0.1%) |

  A tie: the whole-system path only reads one more flag on a plan-cache miss.
- `pytest tests/gpu -m "not acceptance"` on this build: 284 passed, 1 failed (the default-GEMM bound above, before
  D66). After the change `pytest tests/gpu/test_tiled.py`: 8 passed (default-GEMM dE 1.26e-6); the full
  tier not rerun.

### 6.22 The tiled wavefront (16 November 2026, 05:00)

RTX 5060 Ti only; library `695d6873c09336bc` (the working tree after `cd1a620`). PLAN.md S5-T08, D66, D67;
ledger `tile-wavefront`. OMAT-0 medium, `SrTiO3` rods rattled by 0.04 A, default GEMMs, skin 0.5 A
(`.tmp_o/wave_time.py`; one process per row, four calls each: the first builds the lists, the rest keep them).

| Atoms, receivers | Sweeps | Tiles | First call (s) | Kept call (s) | Device peak (GiB) |
|---|---|---|---|---|---|
| 368,640 (128x24x24), 20,000 | plain | 32 | 2.53, 2.28 | 0.808, 0.798 | 4.91 |
| 368,640, 20,000 | wavefront (forced) | 40 | 3.58, 3.31 | 0.809, 0.805 | 4.05 |
| 1,081,600 (320x26x26), 40,000 | wavefront (`auto`) | 34 | 7.17 | 2.354 | 10.84 |
| 1,081,600, the plan's cap (49,152; library `90a30122`) | wavefront (`auto`) | 32 | 8.99 | 2.357 | 11.83 |

- Measured: two runs per side at 368,640 atoms (not an A/B); kept calls tie. The first call is slower with the
  wavefront because the boundary skins make 8 more tiles (more GEMM row counts to time). Forces of the two
  sides 5.5e-6 eV/A apart with the default GEMMs (hybrid picks per tile shape, D66).
- The row pool: 119,833 of 1,081,600 atoms (11.1%) at 16 layers; 3,048 of 11,520 (26%) at 13 layers.
- Not measured: the plain call at 1,081,600 atoms (it would need about 30 GiB on this 16 GiB card; not tried,
  since WSL oversubscription has crashed this PC before).
- `pytest -s tests/gpu/test_tiled.py`: the wavefront against the plain call without hybrids, energy 9.8e-11
  relative, forces 1.3e-6 eV/A, stress 3.8e-10 eV/A^3. OMAT-0 small's tiled-vs-whole stress with the default
  GEMMs reached 1.09e-7 and 1.10e-7 with fresh plans (bound 1e-7); with fresh plans per run the library before
  S5-T08 gave 7.3e-8 and 5.1e-8, this one 9.2e-9 and 4.8e-8, so the bound is now 2e-7 (D66).
- The memory plan with the row pool (library `90a30122`): 1,081,600 atoms with no cap set get 49,152 receivers,
  15 layers, a pool of 134,328 atoms (12.4%), peak 11.83 GiB of a 13.38 GiB budget (88%). The capacity mode
  `wavefront` on 11,520 atoms (600 receivers): planned state 52 MiB against 85 MiB tiled, peak 585 against
  621 MiB, results as the plain call's without hybrids.
- Suites: `pytest tests/cpu` 365 passed, 1 skipped; `pytest tests/gpu -m "not acceptance"` on `695d6873` 286
  passed, on `90a30122` 287 passed and 1 failed (`test_output_every_20_steps_costs_at_most_three_percent`, 3.8%
  against 3%; passed three reruns alone on both libraries).

### 6.23 The receiver-cap screen and the tiled call's overheads (16 November 2026, 06:00)

RTX 5060 Ti only; library `90a30122589e77bd` (`deeae56`). PLAN.md S5-T10, D68; ledger `tile-overhead-screen`.
OMAT-0 medium, `SrTiO3` rattled by 0.04 A, default GEMMs, skin 0.5 A; one process per row, the median of three
calls with kept lists (`.tmp_o/wave_time.py`).

| Atoms | Receivers | Tiles | Kept call (s) | Device peak (GiB) |
|---|---|---|---|---|
| 320,000 (40^3, plain tiled) | 8,192 | 54 | 0.725 | 4.42 |
| | 16,384 | 27 | 0.705 | 4.47 |
| | 32,768 | 16 | 0.720 | 8.45 |
| | 49,152 | 8 | 0.679 | 8.57 |
| | 65,536 | 8 | 0.677 | 8.57 |
| 1,081,600 (rod 320x26x26, wavefront) | 16,384 | 96 | 2.402 | 6.70 |
| | 24,576 | 84 | 2.328 | 7.04 |
| | 32,768 | 36 | 2.387 | 9.72 |
| | 49,152 (the plan's) | 32 | 2.357 | 11.80 |

- 320,000 atoms at 65,536: 2.12 us per atom (the whole-system call is 1.65 at 40,000, status §6.16).
- Phases (`LOUP_DEBUG_TILE_TIMES=1`, `.tmp_o/rebuild_probe.py`, 320,000 atoms, 8 tiles): a kept call is
  forward 77, last layer 435-471, backward 154 ms; a call that rebuilds the lists (every atom moved 0.3 A) adds
  plan 16, candidates 43-45, kept lists 79-96 and state buffers 27 ms (about 190 ms); the first call of an
  engine 2.96 s (GEMM timing in the sweeps).
- Estimated from these, not built: CUDA graphs per bucket at most about 1 ms per tile (1.5% at 34 tiles of
  2.36 s); list builds without host round trips at most the 190 ms per rebuild, about 1% of a step at a rebuild
  every 20 steps.

### 6.24 The wavefront under the accuracy gate and in MD (16 November 2026, 06:30)

RTX 5060 Ti only; library `90a30122589e77bd`. PLAN.md S5-T08. `loupmd validate --model LABEL --capacity wavefront`
(about four tiles per cell, `LOUP_EXEC_WAVEFRONT`; the gate refuses a call that did not run the wavefront), worst
ratios energy, force, stress:

| Label | Set | Wavefront | Tiled (§6.21) |
|---|---|---|---|
| omat0-medium | oxide | 0.68, 1.92, 1.37 | 0.57, 1.81, 1.23 |
| omat0-small | oxide | 0.33, 1.31, 1.52 | 0.34, 1.31, 1.50 |
| mp0-medium | oxide | 0.04, 0.69, 1.07 | 0.02, 0.60, 0.52 |
| mpa0-medium | oxide | 0.36, 2.09, 2.16 | 0.33, 2.05, 2.23 |
| matpes-pbe | crystals | 0.18, 1.05, 0.89 | 0.19, 1.04, 1.00 |
| mh1-omat | crystals | 0.10, 0.86, 0.29 | 0.10, 0.88, 0.29 |
| off23-medium | organic | 0.01, 0.35, 0.51 | 0.01, 0.33, 0.54 |

All PASS. `tests/gpu/test_tiled_md.py::test_a_wavefront_simulation_follows_the_whole_systems_nve_trajectory`
(`SrTiO3` 64x6x6, 11,520 atoms, 600 receivers, 26 tiles, no hybrids): after 20 NVE steps of 1 fs from 300 K,
positions 3.8e-8 A and energy 6.9e-9 eV/atom from the whole-system device loop (the tiled engine: 3.5e-8 A).

### 6.25 Model coverage of S6-T06 (16 November 2026, 07:30)

RTX 5060 Ti only; library `90a30122589e77bd`, generic path (the default). `loupmd validate --model LABEL`, worst
ratios energy, force, stress: `mp0b3-medium` (oxide, 18 rows) 0.07, 1.14, 0.78; `mp0-large` (`MACE_MPtrj_2022.9.model`,
oxide, 6 rows) 0.14, 1.33, 1.10; `matpes-r2scan` (crystals, 18 rows) 0.12, 1.43, 0.98. All PASS.

### 6.26 Events, Monte Carlo and OMOL-0 XL charge (16 November 2026)

RTX 5060 Ti only. Measured with `tests/gpu/test_events_gpu.py` (library `af0d248587b5703f`, OMAT-0 medium, generic
path) and `loupmd validate` (library `90a30122589e77bd`):

| What | Measured |
| --- | --- |
| `Simulation.set_species` on SrTiO3 6x6x6 (1,080 atoms) | 170 to 207 ms per event (two runs: a full `loup_set_system`, the state put back); the next 10 steps 26.5 to 28.9 ms with the re-capture; energy against a fresh engine within 4e-6 eV |
| `lm.mc.Swap` on 256 atoms | 1.11 to 1.28 ms per attempt (two energy-only passes and the host's Metropolis test); move energies within 6.8e-13 eV of the full call |
| `lm.mc.Transmute` on 256 atoms | 7.4 ms per attempt in the counted setup (`loup_set_system`, fixed atoms, state); 67 ms wall time per attempt in all (the energy-only pass on the new system includes its first graph capture and list build, and a rejected attempt sets the system back) |
| OMOL-0 XL `organic` gate, neutral singlet | worst ratios 0.00, 0.85, 0.61; PASS (878 s) |
| OMOL-0 XL `organic` gate, charge +1, doublet | worst ratios 0.00, 0.31, 0.21; PASS (929 s) |

Per-atom energies (S6-T08, `tests/gpu/test_evaluate2.py`, SrTiO3 3x3x3 rattled, against MACE float64's per-atom
`energies`): relaxed, within 1.4e-5 eV per atom (MACE float32: 9.8e-6) on OMAT-0 medium, small and MH-1. **Open
finding, not of the per-atom split:** on the same cell compressed to 0.78 (47% of the volume, every atom in ZBL
range) the plain path's total energy is 7.5e-3 eV (5.5e-5 eV/atom) from MACE float64 on OMAT-0 medium, against
1.4e-4 eV for MACE float32, and per atom 1.8e-4 eV (MACE float32: 1.2e-5); MH-1 1.5e-5 eV/atom in total, 1.7e-4
per atom; OMAT-0 small 7.5e-6 eV/atom, 4.8e-5 per atom. The mean deviation is per species (Ti -1.0e-4, Sr -7.8e-5,
O -3.3e-5 eV on OMAT-0 medium), so it looks like an accuracy limit of the forward at very short distances, not
noise. No gate set covers this compression; forces were not compared. Not investigated further in this session.

The transmute cost is a full system setup per attempt (D71): a `loup_set_species` that keeps the buffers is the item
to build if that matters to the owner. Speed of plain MD is unchanged (no change to the step).

### 6.27 Dispersion kernel bake-off, S6-D02 (16 November 2026)

RTX 5060 Ti only; prototype `src/dispersion/d3_proto.cu` (not in `libloupmd.so`), details and every row in
`docs/validation/dispersion-bakeoff.md`. D3(BJ) two-body, PBE, against simple-dftd3 at 150 bohr:

| System | Plain 40 bohr sum (default) | Its error: energy, pressure, largest force | 40 bohr pairs, CN 30 (D73) |
| --- | ---: | --- | ---: |
| NbCl5 3x3x3 (1,944) | 2.48 ms | 0.58 meV/atom, 0.0065 GPa, 0.0066 meV/A | 2.01 ms |
| SrTiO3 10x10x10 (5,000) | 8.42 ms | 1.06 meV/atom, 0.029 GPa, 0.0066 meV/A | 6.68 ms |
| water 216 2x2x2 (5,184) | 9.88 ms | 0.064 meV/atom, 0.0020 GPa, 0.39 meV/A | 7.76 ms |

No candidate faster than the plain 40 bohr sum meets the accuracy contract literally on all three systems, so the
default is that sum. Shorter cutoffs with the tail correction fail on forces, and so does the long-range part
updated every k steps. The split sum was not prototyped. With the model's step on record (about 1.85 and 8.3 ms),
dispersion would cost 1.3 times the model on NbCl5 and 1.0 times on SrTiO3 at this kernel's speed.

### 6.28 The D3 term in the engine, S6-D04 (16 November 2026)

RTX 5060 Ti only. `src/dispersion/d3_pair.cu` is in `libloupmd.so` (side build `libloupmd_d3b.so`, sha
cba405445b767699): the bake-off's variant 1 with all four dampings (BJ, zero, modified BJ, modified zero), the
optional quintic switch, the energy-only path and per-atom energies. It reads the cell on the device at every
evaluation (the bin counts are fixed at setup, the reach is not), so the captured step stays exact in a
variable-cell run. `loup_d3_evaluate` runs it on its own; `loup_set_dispersion` adds it to every whole-system pass
of a handle (evaluate, per-atom, energy-only, the MD step, the variable-cell step). `lm.md(dispersion=)`, `loupmd md
--dispersion`, run files, restarts and `metadata.json` carry it.

Measured, `tests/gpu/test_d3.py` (20 passed):
- Against simple-dftd3 at the same settings (40/40 bohr, s9 = 0), every damping on NbCl5, paracetamol and SrTiO3
  2x2x2, and 20/30 bohr on SrTiO3: within 1e-6 eV/atom, 1e-5 eV/A, 1e-7 eV/A^3 (the plan's bounds; the test
  does not print the margins).
- `d3bj-mace` against torch-dftd's calculator as `mace_mp(dispersion=True)` builds it, at float64: the same bounds.
- In the engine (OMAT-0 medium, SrTiO3 3x3x3): energy, forces, stress and per-atom energies are the model's plus
  the term alone; after 200 captured NVE steps (13 list rebuilds) and after 200 variable-cell steps growing the cell
  0.02% per step (11 rebuilds), energy and forces on the device are the model's plus the term at the final
  positions and cell (1e-5 eV/atom, 1e-4 eV/A).
- Switch: forces are the central-difference gradient within 2e-5 eV/A; stress xx within 2.4e-7 eV/A^3 of it
  (rounding bound of the check 1.0e-6).

Time per captured evaluation, d3bj 40/40 bohr (`loup_d3_evaluate`, mean of 50 graph replays):

| System | Forces and stress | Energy only | Bake-off prototype |
| --- | ---: | ---: | ---: |
| NbCl5 3x3x3 (1,944) | 2.51 ms | 0.68 ms | 2.48 ms |
| SrTiO3 10x10x10 (5,000) | 8.48 ms | 1.43 ms | 8.42 ms |
| water 216 2x2x2 (5,184) | 9.87 ms | 1.53 ms | 9.88 ms |

Errors against the 150 bohr reference are the bake-off's (NbCl5 0.58 meV/atom, SrTiO3 1.06, water 0.064). Not
measured: an MD step with and without the term (the step cost should rise by about the table's first column), and
any other GPU. Runs without dispersion are unchanged in code path (`record_dispersion` returns at once); the GPU
suite on this library is recorded in PLAN.md's S6-D04 row.

### 6.29 The D3 three-body term, S6-D08 (16 November 2026)

RTX 5060 Ti only. `atm_kernel` in `src/dispersion/d3_pair.cu` (side build `libloupmd_d3c.so`, sha
523fc8430d43f194): the Axilrod-Teller-Muto term with simple-dftd3 1.6.0's convention for every damping (found by
comparing its s9 = 1 and s9 = 0 energies with a numpy sum on a small molecule: R0 = 4/3 R0ab per side, exponent
(alpha + 2) / 3). One block per atom lists its neighbours within the three-body cutoff into shared memory in chunks
of 384 and runs over the pairs of the list; each triangle is seen from its three corners, each keeping E/3, its
share of the virial, and its force and dE/dCN in full (they involve only its own two sides), so there are no
atomics on atoms. It runs after the pair kernel and before the coordination-number chain rule. 127 registers, no
spills (forces); 72 registers and 24 bytes of stack (energy only).

Measured, `tests/gpu/test_d3.py` (27 passed with the three-body tests):
- Against simple-dftd3 (s9 = 1, three-body cutoff 20 bohr, pairs and CN 40 bohr): NbCl5 BJ 6.1e-9 eV/atom,
  3.2e-8 eV/A, 2.8e-10 eV/A^3; paracetamol BJ 4.2e-9, 1.2e-7, 6.0e-10; SrTiO3 2x2x2 BJ 2.2e-8, 1.8e-8, 2.3e-9
  (its 14.8 bohr cell is shorter than the cutoff, so triangles hold two images of one atom); SrTiO3 zero 1.3e-8,
  6.8e-8, 5.4e-10; paracetamol zerom 3.5e-8, 4.3e-7, 5.1e-9. `d3-reference` (60/40/40 bohr, several chunks per
  atom) on SrTiO3 2x2x2: within the plan's bounds (1e-6 eV/atom, 1e-5 eV/A, 1e-7 eV/A^3).
- The three-body energy: NbCl5 +7.06 meV/atom (3.7% of the pair term), paracetamol +3.46 (4.9%), SrTiO3 +16.85
  (6.4%), as in the design's table 3.2.
- Per-atom energies sum to the total, the energy-only path gives the same energy, and with a 6 bohr switch the
  forces are the central-difference gradient within 2e-5 eV/A.

Time per captured evaluation (`loup_d3_evaluate`, forces and stress; energy only in brackets; 20 replays, 3 for
d3-reference):

| System | d3bj | d3bj-atm (three-body to 20 bohr) | d3-reference (60 / 40 / 40 bohr) |
| --- | ---: | ---: | ---: |
| NbCl5 3x3x3 (1,944) | 2.51 ms (0.69) | 12.34 ms (7.29) | 272 ms (124) |
| SrTiO3 10x10x10 (5,000) | 8.46 ms (1.40) | 102.0 ms (53.0) | 4,027 ms (2,072) |
| water 216 2x2x2 (5,184) | 9.81 ms (1.52) | 132.7 ms (64.8) | 5,639 ms (3,069) |

The three-body term costs 4 to 13 times the pair term at 20 bohr and is not usable for MD at 40 bohr. The kernel is
a first, correct version: the C6 of the side jk is formed per triangle from the 5x5 reference table in global
memory (25 FMA and 25 loads), and the neighbour walk covers the pair cutoff's bins. Not tried yet: per-species
projections of the weights in shared memory (as the pair kernel does), a walk sized to the three-body cutoff, and
a triangle loop that keeps side jk's C6 per (j, k) chunk pair. `lm.md` measures the term's time on the starting
structure at setup and the report shows it with the three-body share (`metadata.json` dispersion.cost).

### 6.30 S6-D06 groundwork: an Ewald split of the D3 pair sum (16 November 2026, CPU prototype)

Not built yet; numbers from numpy prototypes on the CPU (`.tmp_o` scratch, to move to `tools/dev` with the kernel).
The owner chose D74 (a): the split sum and the reciprocal-space sum are one method, S6-D06.

- **The C6 matrix is exactly separable.** C6_ij = u_i^T M u_j, u_i the atom's Gaussian weights placed at its
  (species, reference) slots and M the reference C6 table over those slots. With M = sum_c lam_c v_c v_c^T,
  C6_ij = sum_c lam_c q_ic q_jc, q_ic = v_c . u_i: one "charge" per atom and channel, at most 5 channels per species
  (NbCl5: 5 nonzero). C8 = 3 Q_i Q_j C6 is separable with the same channels scaled by sqrt(3) Q_i. No combination
  rule is assumed, so nothing is approximated.
- **The r^-6 and r^-8 Ewald splits** (h_long = (1 - e^-x sum_{m<p} x^m/m!) / r^2p, x = (beta r)^2; transform
  pi^{3/2} beta^{2p-3} / (p-1)! b^{2p-3} Gamma(3/2 - p, b^2), b = k / 2 beta; self term beta^2p / (2 p!) per C_ii)
  agree with radial quadrature to 1e-8 and with a direct lattice sum of a random separable C to 6e-9 relative.
- **Accuracy, NbCl5 3x3x3, energy against the 150 bohr sum** (CN to 40 bohr in both): the plain 40 bohr sum is off
  by 0.583 meV/atom. With the C6 part split and C8 summed to 40 bohr in real space: 0.002 to 0.007 meV/atom at a
  20 bohr real-space cutoff (beta 0.15 to 0.25 per bohr), 0.0004 at 30 bohr; 166 neighbours per atom within 20 bohr
  against about 1,300 within 40. With C8 also cut at the short cutoff and not split: 0.35 / 0.10 / 0.034 meV/atom
  at 20 / 25 / 30 bohr, so C8 needs its own Ewald part (formula checked; the accuracy run did not finish, below).
- **Cost model:** a direct k-space sum is N x (number of k-vectors) x channels, about as expensive as the plain sum at
  5,000 atoms (NbCl5 needs 16,000 to 73,000 k-vectors at beta 0.15 to 0.25). The gain needs a mesh (smooth PME):
  the k cutoff 2 beta x 4.5 at beta 0.15 implies a mesh spacing near 2.3 bohr (1.2 A, FourierD3's default).
  Forces and stress are not prototyped yet; the CN chain rule needs dE/dq_ic from the k-space part.
- **Not finished at first:** WSL stopped twice with Wsl/Service/E_UNEXPECTED (09:10, and during the NbCl5 rerun)
  while the other session held the GPU. The cause was most likely the prototype itself: ASE's 40 bohr neighbour list
  of NbCl5 3x3x3 asks for arrays of 42 million rows (973 MB each, several at once). Rerun with the address space
  capped at 8 GB (`ulimit -v`; the list then failed cleanly) and the pairs streamed in blocks of 48 atoms.
- **C6 and C8 both split (NbCl5 3x3x3, 1944 atoms, energy):** against the 150 bohr sum the error stopped falling at
  0.012 meV/atom for every beta at 20 to 25 bohr. That floor is the 150 bohr reference's own truncation: the uniform
  tail beyond 150 bohr is -0.0111 meV/atom (C6 only). Against the reference plus that tail: **0.0067 meV/atom at a
  20 bohr real-space cutoff and 0.0008 at 25 bohr, for beta 0.200 and 0.225 per bohr alike** (plain 40 bohr sum:
  0.594); at 15 bohr 0.06 to 0.08. The rest at 20 bohr is not the Ewald part but the BJ damping's departure from
  1/r^6 beyond the real-space cutoff (about (f/r)^6 of the tail, f near 7 bohr); a uniform-density correction for it
  (C6 f^6 / r^12 over the tail) would remove most of it and is not built. Consequence for the validation set (D73):
  the 150 bohr references are short of the infinite sum by about 0.01 meV/atom on NbCl5, a hundredth of the plain
  40 bohr sum's error, so they stay the reference with the tail estimate added where the split sum is compared.

### 6.31 The split sum on the GPU, S6-D06 (16 November 2026)

`long_range="split"`: the damped pair term minus its smooth long-range part (C6 and C8) in real space to
`pair_cutoff_bohr`, that part for every pair and image in reciprocal space through the exact channels of status
6.30 (`src/dispersion/d3_split.cuh`), on a smooth-PME mesh (`src/dispersion/d3_mesh.cuh`; cuFFT opened with
`dlopen`, D79). beta = 4.5 / real-space cutoff. The direct k sum stays as the mesh's reference (`LOUP_D3_KSUM=direct`,
testing only; refused above about 4e10 atom-k-channel products). Every damping and the three-body term work with it
(only the real-space kernel differs). Measured on the RTX 5060 Ti, `libloupmd_d3f.so` (a589b930c20f5c05).

**Accuracy against the infinite sum** (simple-dftd3 at 150 bohr plus the uniform tail beyond 150 bohr, estimated from
the 40 to 150 bohr difference; CN to 40 bohr everywhere), direct k sum, energy in meV/atom, max force error in eV/A:

| system (atoms) | plain 40 bohr | split 15 | split 20 | split 25 |
| --- | --- | --- | --- | --- |
| paracetamol (80) | 0.153, 7.1e-5 | 0.0064, 4.6e-6 | 0.0005, 1.7e-6 | 0.0001, 1.4e-6 |
| SrTiO3 2x2x2 (40) | 1.080, 4.5e-6 | 0.543, 1.9e-4 | 0.032, 4.2e-6 | 0.0039, 3.9e-7 |
| NbCl5 (72) | 0.594, 4.8e-6 | 0.077, 1.6e-4 | 0.0066, 5.0e-6 | 0.0007, 3.8e-7 |

Stress errors at 20 bohr: 1.3e-4 / 2.3e-3 / 3.0e-4 GPa against the plain sum's 5.0e-3 / 2.9e-2 / 6.6e-3. So at 20 bohr
the split sum is within the literal contract (no worse than the plain 40 bohr sum) in energy, force and stress on these
three, except SrTiO3's force at 4.2e-6 against 4.5e-6 (just inside). 15 bohr fails it in force.

**The mesh against the direct k sum** (rc 20 bohr), largest errors over paracetamol, SrTiO3 and NbCl5:

| order, spacing | dE meV/atom | dF eV/A | dS GPa | ms (NbCl5) |
| --- | --- | --- | --- | --- |
| 4, 1.0 A | 0.107 | 1.5e-3 | 1.1e-3 | 1.08 |
| 6, 1.0 A (D78's plan) | 4.4e-3 | 8.5e-5 | 9.5e-5 | 1.28 |
| 6, 0.6 A | 1.6e-4 | 4.6e-6 | 7.4e-6 | 1.40 |
| 8, 1.0 A | 5.3e-4 | 7.9e-6 | 1.8e-5 | 1.59 |
| **8, 0.8 A (default)** | 5.3e-4 | 1.4e-6 | 7.0e-6 | 1.62 |

The energy floor near 2e-4 to 5e-4 meV/atom (1 part in 1e6 of the k = 0 and self terms, which nearly cancel) is
float32 rounding of the channel values, the same in both sums, and inside the 1e-6 eV/atom tolerance. Order 6 at
1.0 A misses the force tolerance on NbCl5 by 8x, hence the default of order 8 at 0.8 A (D78 amended).

**Checks:** forces and stress are the gradient (central differences at h = 1e-2 A and strain 1e-3: noise from
float32 pair energies is near 1e-5 eV/A at h = 1e-3 A, so the precise check is the comparison with simple-dftd3
above); energy-only equals the full call to 4e-15 eV; per-atom energies sum to the total within 1e-7 eV.

**Cost on small cells** (40 to 80 atoms): the split sum is slower than the plain sum (1.2 to 3 ms against 0.7 to
0.85 ms), the mesh pipeline being 2 x channels x (spread, FFT, k-space, inverse FFT, gather) launches. The large
cells decide (below).

**Large cells** (`libloupmd_d3h.so`, d1653946c4f82dd5, which adds per-pass walk reaches; one run each, 20 replays of
the captured evaluation; errors against the cached 150 bohr references plus the tail beyond 150 bohr):

| system (atoms) | plain 40: ms, dE meV/atom, dF eV/A | split 20, mesh 0.8 A order 8 | split 25, same mesh |
| --- | --- | --- | --- |
| NbCl5 3x3x3 (1,944) | 2.61, 0.594, 5.7e-6 | 4.27 (energy only 2.62), 0.0068, 7.2e-6 | 4.43, 0.0008, 4.1e-7 |
| SrTiO3 10x10x10 (5,000) | 8.56, 1.080, 6.2e-6 | 12.67 (6.95), 0.0329, 9.2e-6 | 13.13, 0.0041, 9.2e-7 |
| water 216 2x2x2 (5,184) | 10.20, 0.065, 3.1e-4 | 9.52 (3.70), 0.0002, 6.3e-6 | 10.25, 0.0000, 5.6e-6 |
| SrTiO3 27^3 (98,415) | 152.8 | 203.4 | 213.9 |
| SrTiO3 58^3 (975,560) | 1493.9 | 1975.3 | 2080.9 |

Stress at 20 bohr: 3.0e-4 / 2.3e-3 / 4.9e-5 GPa against 6.6e-3 / 2.9e-2 / 2.0e-3. **The split sum is an accuracy
method, not a speed-up, at the record's 40 bohr CN cutoff:** at 20 bohr its force error exceeds the plain sum's on
NbCl5 (7.2e-6 against 5.7e-6) and SrTiO3 (9.2e-6 against 6.2e-6), both below the 1e-5 eV/A tolerance, so it misses
D73's literal contract there in force while being 10 to 300 times better in energy and stress; at 25 bohr it is
better in all three on all three systems, at 1.05 to 1.7 times the plain sum's time. Where the time goes: both
methods walk 40 bohr twice for the coordination numbers (count and chain rule), and the mesh costs about 5 ms at 5,000
atoms (energy only 6.95 ms against the plain sum's 1.40). Tuning ideas are in the ledger (`d3-split-mesh`). The
1,000,000-atom energies show the size of the plain sum's truncation in a large cell: -0.264539 against -0.265652
eV/atom, 1.1 meV/atom.

### 6.32 The automatic long-range choice, S6-D07 (16 November 2026)

Measured on the RTX 5060 Ti with `libloupmd_d3h.so` (d1653946c4f82dd5), using `loupmd.dispersion.choose` as D80
describes it:

- **Reference:** the split sum at 30 bohr, order 8, on a 0.6 A mesh.
- **Candidates:** plain 40, split 20 and split 25.
- **Kept:** a candidate whose deviations from the reference (energy per atom, largest per-atom force difference,
  largest stress component) are each no larger than the plain sum's.
- **Timing:** each kept candidate in two rounds of three replays; the faster round counts.

| system (atoms) | plain 40: dE meV/atom, dF eV/A, ms | split 20 | split 25 | chosen | setup |
|---|---|---|---|---|---|
| paracetamol (80) | 0.153, 8.3e-05, 0.73 | 0.0005, 4.6e-07, 3.03 | 0.00006, 4.1e-08, 3.06 | plain 40 | 0.12 s |
| SrTiO3 2x2x2 (40) | 1.080, 5.7e-06, 0.68 | 0.032, 5.1e-06, 2.10 | 0.0034, 4.5e-07, 2.12 | plain 40 | 0.12 s |
| NbCl5 (72) | 0.594, 5.2e-06, 0.85 | 0.0067, 5.9e-06 (dropped: force) | 0.0007, 4.2e-07, 1.56 | plain 40 | 0.10 s |
| SrTiO3 10^3 (5,000) | 1.081, 6.7e-06, 8.46 | 0.032, 9.6e-06 (dropped: force) | 0.0035, 1.0e-06, 12.97 | plain 40 | 0.35 s |
| SrTiO3 27^3 (98,415) | 1.081, 8.1e-06, 152.9 | 0.032, 1.4e-05 (dropped: force) | 0.0034, 1.4e-06, 212.8 | plain 40 | 5.4 s |
| SrTiO3 58^3 (975,560) | 1.081, 9.2e-06, 1492.9 | 0.032, 2.1e-05 (dropped: force) | 0.0034, 2.1e-06, 2081.5 | plain 40 | 44.9 s |

The candidates were also timed separately (three rounds of ten replays, `tests/gpu/test_d3.py`). On all three
benchmark cells the chosen candidate was the fastest of the kept ones.

A split candidate at 12 bohr on a 6 A mesh, made wrong on purpose, was off by 202 meV/atom and was dropped.

Not measured: a cell where the split sum is chosen. From status 6.31, water 216 2x2x2 should be one: split 20 took
9.52 ms against 10.20 ms for plain 40, and both are within the contract. No test was run on it.

Reading: under D73's literal contract the plain sum is its own bound and is always kept. The choice is therefore the
plain sum unless the split sum is also faster. The split sum's accuracy (30 to 2,500 times closer in energy) does
not count. To make accuracy count, the rule could be "the most accurate candidate within 1.5 times the fastest",
which would pick split 25 on every row above. That changes the contract, so it is left to the owner.

### 6.33 D3 tuning: float32 partial sums on the force path (16 November 2026)

RTX 5060 Ti only. The D3 force kernels added each pair's contributions straight into float64: three force
components, six virial components and dE/dCN (`pair_kernel`), nine in the chain rule (`cn_force_kernel`), and ten
per triangle in `atm_kernel`. That is 10 float64 adds and 10 float-to-double conversions per pair, and this card
runs float64 at 1/64 of float32's rate. The forces path therefore took about six times the energy-only path.

The change: each lane sums these in float32 and adds the partial sums to the float64 totals every 32 pairs or
triangles (`D3_FLUSH`). The coordination-number kernel already did this with 64 terms. The energy itself stays
float64 per pair, so the energy-only path gives the same energy: a first version that also summed the energy in
float32 put the two paths 1.3e-9 to 2.2e-9 apart, above the tests' 1e-9 relative bound. This is float32
arithmetic, within PLAN section 2.

Time per captured evaluation (forces and stress; minimum of three runs of 20 replays; A B B A in separate
processes, both orders agree within 1%):

| System | d3bj before -> after | split 25 before -> after | d3bj-atm (three-body to 20 bohr) before -> after |
| --- | ---: | ---: | ---: |
| NbCl5 3x3x3 (1,944) | 2.56 -> 1.36 ms | 4.46 -> 3.67 ms | 7.59 -> 5.80 ms |
| SrTiO3 10x10x10 (5,000) | 8.51 -> 3.67 ms | 13.16 -> 10.06 ms | 76.0 -> 54.9 ms |
| water 216 2x2x2 (5,184) | 10.08 -> 4.43 ms | 10.28 -> 6.75 ms | 103.1 -> 73.4 ms |

The libraries: `libloupmd_d3h.so` (before) to `libloupmd_d3j.so` (pair and chain-rule kernels,
c357289d34c8a705) to `libloupmd_d3k.so` (also `atm_kernel`, 7d1efc7fa71e94f7). The d3bj-atm "before" column is
d3j: the three-body step alone, since d3j already contains the pair change. Energy-only times are unchanged.

Results against the previous library: energies equal to 1e-15 eV/atom, forces within 2.2e-8 eV/A, stress within
1.3e-10 eV/A^3.

MD step of MACE-OMAT-0 medium (generic kernels) on SrTiO3, Langevin, median of 4 x 200 steps, A B B A:

| System | model alone | with d3bj, d3h | with d3bj, d3j |
| --- | ---: | ---: | ---: |
| SrTiO3 6x6x6 (1,080) | 1.89 ms | 4.56 ms (x2.41) | 3.06 ms (x1.62) |
| SrTiO3 10x10x10 (5,000) | 8.30 ms | 16.72 ms (x2.01) | 11.95 ms (x1.44) |

Tests: `tests/gpu/test_d3.py` 52 passed on d3j and on d3k; the GPU suite (`-m "not acceptance"`) 353 passed on
d3j (not rerun on d3k, which changes only `atm_kernel`, covered by test_d3.py). One test bound was loosened:
the engine test's energy-only check compared two engines' model energies at 1e-6 eV/atom. The model total's
float32 rounding reaches that (1.05e-6 seen once, with the D3 energies equal to 1e-16), and the forces-path check
beside it already used 1e-5.

What is left in the D3 step, from these numbers: the energy-only path (1.5 ms at 5,000 atoms) is the coordination
numbers and the pair walk; the forces path adds the second 40 bohr walk of the chain rule (about 2 ms). The
three-body term is dominated by forming C6_jk per triangle from the 5x5 reference table (status 6.29). Not tried:
float32 partials in the split sum's mesh kernels, a fused CN-count and chain-rule pass, and per-chunk-pair C6 in
the three-body loop.

Second step (`libloupmd_d3l.so`, da03339207d63d16): the chain rule read dE/dCN of atom j as float64 and converted
it for every pair. A float32 copy made once per atom (`to_float_kernel`) gives bit-identical forces and saves 1 to
5%: d3bj NbCl5 1.35 -> 1.33 ms, SrTiO3 3.67 -> 3.53, water 4.45 -> 4.21 (A B B A); the three-body term unchanged.
`tests/gpu/test_d3.py` 52 passed on d3l.

Third step (`libloupmd_d3m.so`, f907577c30169234): the walks visited every bin of a (2 reach + 1)^3 box, about
2.7 times the cutoff sphere's volume with bins of a quarter cutoff. Each column of bins is now skipped when its
axis lies farther than the cutoff plus the column's cross-section radius, and its z range is cut to the chord
(any triclinic cell; only bins that cannot hold a pair are skipped). Gains are small, because the distance test is
cheap next to the pair's work: d3bj NbCl5 1.33 -> 1.22 ms, SrTiO3 3.54 -> 3.46, water 4.20 -> 4.16; split 25
2 to 3%; three-body 1 to 2% (A B B A, both orders agree). Results equal within 4e-8 eV/A (summation order).
`tests/gpu/test_d3.py` 52 passed on d3m.

Fourth step (`libloupmd_d3n.so`, 7458a4c8045c3e24): the three-body loop formed C6_jk per triangle as
w_j^T C6ref[s_j, s_k] w_k (25 FMA and 25 table loads). Each entry j now projects u_j(s, y) = sum_x w_j[x]
C6ref[s_j, s](x, y) once into shared memory (S x 5 floats per thread, 2.5 KB per species per block beyond the 37
KB of chunk buffers; with more species than the card's opt-in shared memory allows, the old loop runs, and
`LOUP_D3_ATM_PROJ=0` forces it for tests). d3bj-atm NbCl5 5.66 -> 5.39 ms, SrTiO3 53.9 -> 51.0, water 72.6 -> 68.0
(5 to 6%, A B B A); d3bj unchanged. Results within 1.5e-9 eV/A. `tests/gpu/test_d3.py` 52 passed on d3n, and its 8
three-body tests with `LOUP_D3_ATM_PROJ=0`. So the C6 table was not the three-body term's main cost; the
per-triangle arithmetic (a square root, a power, the angle term and its derivatives) is.

GPU suite (`-m "not acceptance"`) on d3m: 353 passed (not rerun on d3n, which changes only the three-body kernel).

### 6.34 Tiled MD on the device and where the tiled call's time goes (16 November 2026, PLAN.md O31)

RTX 5060 Ti, OMAT-0 medium, `SrTiO3`. The integrator of a tiled run ran on the host in numpy (S5-T12); it now runs
on the device (`loup_tiled_run`, `ae341cc`). Per MD step, 20 steps after a warm-up, separate processes:

| System | Integrator | Host loop (ms) | Device loop (ms) |
| --- | --- | --- | --- |
| 320,000 atoms, 8 tiles of 65,536 | NVE | 712.5 (tiled call 704.4, rest 8.1) | 697.6 |
| 320,000 atoms, 8 tiles of 65,536 | Langevin | 744.4 and 806.9 (two runs; rest 41) | 706.5 |
| 1,081,600 atoms, wavefront, 32 tiles | Langevin | (NVE 2,536.5) | 2,382.2 |

So the integrator was 1-5% of a tiled step; the tiled call is the rest. Where that call's time goes, by `nsys`
(`.tmp_o/kern_cmp.py`): one kept tiled call on 320,000 atoms against eight whole-system calls on 40,000 (the same
number of atoms), no stress: kernels 627.0 against 526.5 ms, GPU span 677.6 against 533.8 ms, the GPU idle only
4.5 ms of the tiled span (so CUDA graphs or fewer host syncs would not help). The extra GPU work per call:

| Item | ms | Note |
| --- | --- | --- |
| Device copies of each tile's list into the handle before each sweep (4.1 GB) | 23.5 | `tile-list-borrow` below |
| Memsets: the pass's zero slab, 270 MB per sweep and tile (7.2 GB against 1.3 GB) | ~17 | the other branch's S99 (each forward conv kernel zeroes its own rows) removes most of it after the merge |
| Layer 0's forward again in the backward sweep (`first_fwd`, `gprod_fwd`, `ro_linear`, gathers) | ~26 | open: store it per tile if memory allows |
| Active-edge compaction in each of the three sweeps (`compute_and_count_active`, `scatter_active_edges`) | ~19 | open: once per tile and call |
| Row gathers / scatters between tile and whole-cell arrays | ~23 | inherent to the layout |
| More GEMM launches (`sgemm128`, CUTLASS) | ~22 | the recomputation and the tile shapes |

`tile-list-borrow`: the sweeps only read the tile's list, so `restore_tile_list` points the handle's list pointers
at the tile's buffers, and a scope guard gives the handle its own back when the call ends. A B B A, separate
processes, median of five kept calls (`.tmp_o/tiled_ab.py`): 672.1 / 668.4 / 659.6 / 673.3 ms (a b b a), b / a
0.987; forces against the copy build 1.8e-6 eV/A (run-to-run atomics), `test_kept_lists...` and the wavefront
Simulation test pass. Less than the 23.5 ms of copies: they partly overlapped other work.

`tile-active-once` (after `tile-list-borrow`): each sweep compacted its tile's active edges (`compute_and_count_active`,
the scan, `scatter_active_edges`) again, three times per tile and call. A tile now compacts them in its first sweep
of a call into a slot that it holds until its last sweep (layer 0's backward); the slots (160 MB each at 65,536
receivers) number the tiles in flight, within a quarter of the free memory. 320,000 atoms, 8 slots, A B B A
against the borrow build: 656.1 / 649.7 / 641.6 / 658.5 ms (a b b a), b / a 0.982; forces 1.6e-6 eV/A apart
(run-to-run atomics). The wavefront at 1,081,600 atoms has 5 tiles in flight but 1.3 GB free, so one slot: 2,256.7 /
2,257.5 / 2,268.0 / 2,287.1 ms, a tie (it helps the wavefront only where memory is to spare). `tests/gpu/
test_tiled_md.py` 10 passed; the kept-list and wavefront tests also with `LOUP_TILE_KEEP_ACTIVE=1` and `=0`.

Tile lists in host memory (O31, S5-T07 step 1, `7d74863`): with `LOUP_TILE_HOST_LISTS=1` the lists' edge
arrays are in mapped pinned host memory and the active-edge compaction reads them over the bus (44 B per edge per
call: shifts, senders and receivers in the count, senders, receivers and pairs in the scatter). Separate processes,
order 0 1 1 0, median of five kept calls:

| System | Device lists (ms) | Host lists (ms) | List build, device / host (ms) |
| --- | --- | --- | --- |
| 320,000 atoms, 8 tiles | 653.6, 655.3 | 753.6, 749.4 | 95, 77 / 657, 630 |
| 1,081,600 atoms, wavefront | 2,270.1, 2,289.2 (32 tiles, 1 active slot) | 2,744.8, 2,748.6 (19 tiles, 4 slots) | 302, 430 / 2,163, 1,918 |

The wavefront's host-list plan took 19 larger tiles (its device budget no longer holds the lists). The bus reads
cost about 100 ms per 320,000 atoms (about 14 GB/s); the builds pay for pinning. A fallback for cells that do not
fit otherwise, so the default path is unchanged; the copy of each tile's list into a device staging buffer on a
second stream, ahead of its first sweep, would hide most of the read time (not built).

`tile-slot-reserve` and `tile-keep-layer0` (`be75b89`):

- The active-edge slots now take the free memory less a reserve of max(256 MB, 2% of the card) instead of a
  quarter of it. The wavefront at 1,081,600 atoms then gets 5 slots (its tiles in flight) instead of 1: A B B A
  2,274.3 / 2,221.9 / 2,234.7 / 2,274.4 ms, b / a 0.979 (forces 2.1e-6 eV/A apart). With `LOUP_TILE_KEEP_ACTIVE`
  forced: 0 slots 2,272.0 / 2,277.2, 1 slot 2,290.2, 5 slots 2,233.3 / 2,214.8. A list rebuild at that size with
  the 5 slots: peak 13.7 of 14.6 GiB, no error.
- Layer 0's backward sweep replayed layer 0's forward (`first_fwd`, the species GEMMs, the product, `W_p`, the
  readout) to get the two things its backward reads, `msgf[0..3]` and `D` (8.2 KB per receiver at 128 channels).
  In the plain order each tile now keeps them from its forward sweep of layer 0 (the layer's pointers point at the
  tile's buffer, no copies) and its backward sweep adds only the readout's constant seed: for density layer 0 with
  the hidden table, skip folded and a linear readout (`GenericModel::sweep_keep_layer0`), within the same reserve.
  320,000 atoms (2.6 GB kept, 5.0 GB free): A B B A 642.2 / 598.9 / 596.3 / 644.1 ms, b / a 0.929; forces 1.8e-6
  eV/A apart. More than the replay's 26 ms of kernels in the profile: the replay also re-gathered and re-launched.
  Not in the wavefront (its tiles in flight would need it; memory is short there). Tiled label gates with it: the 8 oxide labels and mh1-omat passed; it engages for mp0b3-medium, mpa0-medium, omat0-small / -medium, matpes-pbe / -r2scan (not MP-0, MH-1, OFF, OMOL-0).

Tiled MD at the end of the O31 speed work (library `7be62d11b15db9ec`, commit `be75b89`; `.tmp_o/tiled_prof.py`,
device integrator, per step with the list rebuilds of the run): 320,000 atoms NVE 624.0 ms (1.95 us/atom; 697.6 at
`ae341cc`), Langevin 630.1 ms (1.97; 706.5); 1,081,600 atoms wavefront Langevin 2,283.5 ms (2.11; 2,382.2). The
whole-system call is 1.65 us/atom at 5,000-40,000 atoms.

Tiled capacity on the RTX 5060 Ti 16 GB after S5-T07 step 1 (planner only, `loup_plan_execution`, OMAT-0 medium,
rattled SrTiO3 cubes, memory fraction 0.9, 41 GB host with about 38 GB available; `.tmp_o/plan_sizes.py`, no force
call run at these sizes):

| Atoms | Plain order, device lists | Plain order, host lists | Wavefront, device lists | Wavefront, host lists |
| --- | --- | --- | --- | --- |
| 2,026,120 | refused (14.69 GiB state) | fits: cap 24,576, 12.07 GiB device, 7.44 GiB host | fits: cap 8,192, 11.94 GiB device | (device lists suffice) |
| 3,292,515 | refused (23.84 GiB) | refused (12.85 GiB state + 0.83 workspace > 13.13) | refused (14.93 GiB) | fits: cap 24,576, 10.46 GiB device, 12.09 GiB host |
| 5,000,000 | refused | refused (19.57 GiB state) | refused | fits: cap 16,384, 11.40 GiB device, 18.37 GiB host |
| 8,008,065 | refused | refused: lists over half of `MemAvailable` | refused | refused: lists over half of `MemAvailable` |

- Plain order: the limit is the whole-cell layer state on the device, between 2.0M and 3.3M atoms with host lists
  (below 2.0M without; smaller cubes not planned here). Host lists raise it by roughly half, not more.
- Wavefront: the row pool holds only the band, so with host lists the device holds 5M atoms with 1.7 GiB to
  spare; the limit is then the host RAM for the lists (36 B per edge, about 3.7 KB per atom at 6 Å, within half of
  `MemAvailable`), between 5.0M and 8.0M atoms on this PC. On a host with more RAM the device side would carry the
  wavefront further (not measured).
- For comparison (FastMACE's own records, not rerun here): whole system 69,120 OMAT-0 SrTiO3 atoms on a 20 GB RTX
  4000 Ada; tiled with the state aliased in host memory 70.96M NbCl5 atoms on that card with 250 GB of host;
  wavefront 179.7M on it and 397.5M on an A100 80 GB. FastMACE keeps every per-atom array in host memory, which is
  S5-T07 step 2 here.

`tile-host-stage` (O31, S5-T07): with host lists, each sweep that compacts a tile's active edges read the lists'
36 B per edge over the bus. The edge arrays of the next compacting sweep are now copied into one of two device
buffers on a copy stream while the current sweep runs (`StageRing`; the order of compacting sweeps follows the
slot rule of `use_active`, worked out before the sweeps). Host lists forced, separate processes, order 1 0 0 1,
median of five kept calls (`.tmp_o/tiled_ab.py`, `LOUP_TILE_HOST_STAGE`):

| System | Over the bus (ms) | Staged (ms) | b / a |
| --- | --- | --- | --- |
| 320,000 atoms, 8 tiles, 8 slots | 698.1, 705.0 | 608.4, 615.7 | 0.871 |
| 1,081,600 atoms, wavefront, 19 tiles, 5 slots | 2,532.9, 2,538.4 | 2,217.1, 2,197.1 | 0.870 |

Forces 1.5e-6 / 2.2e-6 eV/A apart (run-to-run atomics). With device lists the same calls took about 598-644 ms
(lever D build) and 2,215-2,234 ms (5 slots): the host lists now cost about what they save, so the fallback is
no longer 15-20% slower. Two buffers of 36 B per edge of the longest list (2 x 144 MB at 320,000 atoms), taken
before the slots within the same reserve. `test_tile_lists_in_host_memory...` (plain and wavefront, 0 / 1 / all
slots, staged and over the bus) 12 passed.

Whole-system memory against FastMACE (O32), RTX 5060 Ti 16 GB, OMAT-0 medium, rattled SrTiO3, Langevin MD. LoupMD
(`tmd8`, `.tmp_o/whole_mem2.py`): GPU memory in use from Windows `nvidia-smi` less the reading before the engine;
FastMACE (`9b801229`, its `tools/bench/capacity_scan.py point`, 20 + 50 steps, caches outside its checkout): free
memory at the start less the least free memory of its phases.

| Atoms | LoupMD: engine / after `set_system` / after `set_state` (lists) / after MD (GiB) | FastMACE (GiB) |
| --- | --- | --- |
| 13,720 | 0.28 / 1.47 / 1.73 / 1.73 | – |
| 40,000 | 0.28 / 3.62 / 4.33 / 4.33 | – |
| 87,880 | 0.28 / 7.61 / 9.13 / 9.13 (peak sampled at 20 Hz: 9.97) | 6.84 (reserved 6.78) |
| 135,000 | peak 12.93 | – |
| 163,840 | out of memory in `set_state` | 13.24 (reserved 11.55) |

LoupMD holds about 100-107 kB per atom (about 89 kB of per-atom buffers in `set_system`, about 18 kB of neighbour
list in `set_state`), FastMACE 84-87 kB in all (75.7 kB reserved by PyTorch at 163,840): the whole-system limit is
about 135,000-150,000 atoms here against FastMACE's 163,840. The per-atom buffers are the generic model's forward and
gradient buffers per layer and angular order (`GenericModel::alloc_system`), none shared between layers or reused
after their last use; sharing them by lifetime is the lead (not measured yet).

`tile-host-state` (O32, S5-T07 step 2, first part): the plain order's whole-system layer outputs `x` and their
gradients `dx` in pinned host memory, as FastMACE's host state. Each atom's host row sits in its tile's block of
locals (tile row order), so a tile's own rows go in and out as one copy; ghost rows are gathered and gradient rows
added on host threads (up to 8). The device holds four ring slots of a layer's rows (two in, two out). The copies run
on two streams (host to device, device to host) and the host work in tasks chained in tile order, overlapped with the
sweeps; the device-to-device copies into the ring are kernels so they do not wait behind the host copies on the copy
engines. The memory plan takes it only when no cap fits with the lists in host memory alone, within 60% of
`MemAvailable` with the lists (`host_state` in `LoupMemoryPlan` and `LoupExecution`); `LOUP_TILE_HOST_STATE=1|0`
forces it, `LOUP_TILE_HOST_PIPE=0` runs it without the overlap. The wavefront is off with it (plain order only).

320,000 atoms, OMAT-0 medium, 8 tiles, host lists, forced, separate processes, kept calls (`.tmp_o/pipe_check.py`):

| Layer state | Call (ms) | us / atom | Against the whole-system call (1.65 us / atom) |
| --- | --- | --- | --- |
| Device | 611 | 1.91 | 1.16x |
| Host, synchronous (`LOUP_TILE_HOST_PIPE=0`) | 902 | 2.82 | 1.71x |
| Host, overlapped | 750-780 | 2.34-2.44 | 1.42-1.48x |

FastMACE on this card (its records, 975,560 atoms): whole system 4.79 us / atom, tiled with the device state 6.42
(1.34x), with the host state 6.70 (1.40x). The host work itself is small (ghost gathers 20 ms, gradient adds 53 ms
per call); an nsys trace shows the host-to-device and device-to-host copies at 13-14 GB/s each but never at the same
time, and about four idle gaps of about 20 ms at the phase boundaries (each phase waits for the last tile's copies before
the next starts): the open cost. Energies: with the same GEMM plans host and device state agree to 1.4e-5 eV in all
and repeat to 6e-8 eV (no hybrids); the tests bound forces at 1e-5 eV/A. Not done yet: `dx` aliased onto `x`
(FastMACE's window, half the host memory), compact host lists, the wavefront's row pool on the host, and a force call
above the device-state limit (estimated, from the plan: plain order to the host RAM's limit, not run).

Two follow-ups on the host state (two-layer models with the pipeline; 320,000 atoms, forced, separate processes, fresh
plan caches, order a b b a b a a b, median of five kept calls each; `.tmp_o/tiled_ab.py`):

| Change | a (ms) | b (ms) | b / a (medians) |
| --- | --- | --- | --- |
| `tile-host-flow`: no drains between phases, tiles ordered by when their inputs are ready | 815.0, 815.7, 824.0, 813.2 | 813.7, 825.9, 834.8, 830.5 | 1.01 (no gain) |
| `tile-host-alias`: `dx` on `x`'s rows, gradients in window blocks until the last reader | 805.2, 813.9, 818.5, 815.7 | 768.9, 777.5, 791.7, 789.4 | 0.963 |

The flow change gains nothing: the 8 tiles of this cube all neighbour each other, so no tile's inputs are ready
before the last copy of the phase before, and the gaps were not the cost. The phase times say where it is: the
last-layer phase takes 515-565 ms (the main thread waits about 410 ms in all for the gradient copies out and the adds
behind them; the adds themselves 52-100 ms). It stays (neutral; the alias builds on its order). The alias removes the
separate `dx` array (half the layer state's host memory) and its zeroing per call. Forces 1.5e-6 eV/A apart (the
host adds' order). Open: the last-layer phase's gradient copies.

`tile-host-compact` (O32): the host lists keep each edge's sender and integer image shift (8 B instead of 36); each
compaction rebuilds receivers (row pointers), pairs (species) and Cartesian shifts (the tile's box, the list build's
own expression, so bitwise the same) on the device into the handle's own list buffers; a tile whose shifts do not
fit a byte or do not come back bit for bit keeps the 36 B form. Host lists forced, device state, 320,000 atoms (same
protocol): 613.2, 615.0, 631.3, 619.1 ms -> 599.2, 611.1, 600.9, 601.8 (b / a 0.975), staging buffers 2 x 32 MB,
forces 1.8e-6 eV/A apart. The plan counts 8 B per edge of host memory (4.5 times as many edges per GB).

`tile-host-dma` (O32): an nsys trace of the host-state call (`.tmp_o/prof_gaps.py`, `prof_gaplist.py`) put its
kernels at 597 ms, as many as the device state's call, and the rest in GPU gaps: 105 ms in six over 2 ms. Two fixes:
(1) the copies to and from the host run one at a time on this PC (WSL), in the order queued, so a tile's gradient
copy out (which waits for its sweep) queued ahead of the next tile's input copy held both back (18.6 ms, twice a
call): it is now queued after them; (2) with 8 neighbouring tiles every block's fold into `x` fell into the last add
of the phase (45.7 ms before the backward sweeps): a block whose window no later block takes keeps its gradients
there (pinned; the backward sweeps read it). Host state forced, 320,000 atoms: 729.2, 729.5, 730.7, 728.9 ms ->
652.9, 645.4, 652.5, 650.6 (b / a 0.893); the gaps over 2 ms are now 47 ms (15.9 forward to last-layer phase, 21.1
last-layer to backward). Host state against device state: about 651 against 601 ms (+8%; +27% at the first version),
2.03 us per atom, 1.23 times the whole-system call (FastMACE's host state: 1.40 times on this card).

`tile-host-edges` (O32): the two phase-boundary gaps. The last forward tile's outputs are still in the layer buffer,
so its last-layer sweep goes first and takes only its ghost rows from the host; the last last-layer tile's own
gradient rows are still in ring slot b, so its backward sweep adds them there to the other tiles' host adds while its
own host add does its ghost rows (tiles without ghosts of their own atoms only). A first build left the first tile
to the readiness order: right on the 2 x 2 x 2 cube, 50 eV off on the 40,000-atom planner test, where another tile
came first and overwrote the buffer; the tile is now always first. Host state forced, 320,000 atoms: 646.9, 648.9,
641.6, 651.5 -> 629.6, 631.2, 633.5, 631.4 ms (first build, b / a 0.974); the fixed build 638.8, 641.0 -> 621.6,
631.1 (b / a 0.98). The boundary gaps 9.4 and 15.6 ms (from 15.9 and 21.1). Host state about 630 ms against the
device state's 601 (+5%), 1.97 us per atom, 1.19 times the whole-system call.

Tiled capacity on the RTX 5060 Ti 16 GB after O32's host state, compact lists and alias (planner only,
`loup_plan_execution`, library `0add58dbf6d08b0c`, OMAT-0 medium, rattled SrTiO3 cubes, memory fraction 0.9,
`MemAvailable` 38.2 GiB; `.tmp_o/plan_sizes2.py`, no force call run at these sizes; `tiled` and `auto` plan alike):

| Atoms | Plan | Cap | Device (GiB) | Pinned host (GiB) |
| --- | --- | --- | --- | --- |
| 2,560,000 | host lists, layer state on the device | 16,384 | 12.63 | 2.09 |
| 5,000,000 | host lists and host state (plain order) | 65,536 | 11.02 | 15.30 |
| 8,640,000 | host lists, layer state on the device (the wavefront's pool) | 6,144 | 9.69 | 7.05 |
| 13,720,000 | host lists, layer state on the device (the wavefront's pool) | 6,144 | 12.41 | 11.20 |
| 20,480,000 | refused: the pool does not fit the device, the host state not 60% of `MemAvailable` | - | - | - |

- The plain order's host state carries a 5M cube in 65,536-receiver tiles (refused before O32; the wavefront does
  not apply there: the cube has fewer than 12 layers of tiles along its first axis at any cap).
- The host lists take 8 B per edge: 13.7M atoms need 11.2 GiB of them (36 B: about 50 GiB, refused).
- The limit on this PC is now between 13.7M and 20.5M atoms: the wavefront's row pool on the device at 6,144
  receivers, or the plain host state's `x` (about 2 KB per atom with the alias) within 60% of `MemAvailable`. The
  wavefront's pool in host memory (`tile-wave-host-pool` below) moves it to the host RAM for lists and pool together.

`tile-wave-host-pool` (O32): the wavefront's row pool in pinned host memory, as blocks of the most locals per tile:
a tile takes a block at its sweep 1 and gives it back at its sweep 3 (the device pool's schedule, so a ghost's block
is held whenever the device pool's row would be); its rows are the tile's locals in row order, ghosts point into
their owners' blocks. The sweeps run one after another with the plain host state's copies and host adds (no
pipeline); a block's gradient rows are zeroed at the tile's sweep 1 after a stream sync. The plan's fourth step
(after the plain order's host state; first when the wavefront is forced). 5,760 atoms: 7 blocks of 400 rows against
a device pool of 2,489. Wavefront at 1,081,600 atoms forced: wavefront sweeps about 2.26 s with the device pool,
about 3.10 s with the host pool (+37%; tick times of one run each side, not an A/B). Tests: host pool against device
pool (host lists 0 / 1, building and kept call) and the plan's step pass.

`tile-slot-reserve` (O32): force calls above the device-state limit (memory fraction 0.75, library `83c1daed`,
OMAT-0 medium SrTiO3 cubes, two calls each, `.tmp_o/big_call.py`): 2,560,000 atoms (host lists, cap 4,096) 19.7 s
building, 5.91 s kept (2.31 us per atom); 3,524,845 atoms ran out of device memory in the sweeps: the kept
active-edge slots took 24 x 221 MB of 5.8 GB free (their reserve was max(256 MB, 2% of the card) and ignored the
memory fraction), leaving about 500 MB. The slots' and kept layer 0's reserve now also keeps the part of the budget
the fraction leaves out: 3,524,845 atoms (cap 65,536, host lists and host state) 26.7 s building, 7.52 s kept
(2.13 us per atom); 5,000,000 atoms (cap 49,152, host lists and host state, 8.63 GiB device, 14.91 GiB pinned host)
35.1 s building, 10.66 s kept (2.13 us per atom), peak 13.46 GB of the 16 GB card (`nvidia-smi` every 2 s), energies
and forces finite. Cost at the default fraction 0.9: the 1,081,600-atom wavefront got 0 slots instead of 3-5
(2,232 / 2,200 -> 2,257 / 2,268 ms, four runs), won back by compact device lists below.

`tile-device-compact` (O32): the device lists keep their edges in the compact host lists' form (senders and integer
image shifts, 8 B per edge; the compaction's inputs decoded into the handle's own buffers per compaction;
`LOUP_TILE_DEVICE_COMPACT=0` keeps 36 B). Library `1f9796ba` against `83c1daed`, A B B A B A A B, fresh plans:
plain tiled 320,000 atoms 643.2, 638.7, 640.8, 639.9 -> 594.3, 593.5, 599.2, 603.7 ms (b / a 0.93; edges 284 MB);
wavefront 1,081,600 atoms 2,261.6, 2,258.1, 2,270.9, 2,256.2 -> 2,218.3, 2,204.6, 2,210.2, 2,204.4 ms (b / a 0.977;
edges 956 MB, so the plan takes 19 tiles instead of 32 and the slots come back). Forces between runs of one side
agree to 3e-6 eV/A on both libraries (the energies differ by up to 0.13 eV of 8.6 MeV between fresh plan picks with
the hybrid). The plan counts 8.8 B per device edge. Capacity (planner, the same cubes, fraction 0.9, `MemAvailable`
38.2 GiB): 1,080,000 atoms cap 49,152 on the device (12.12 GiB); 2,560,000 cap 4,096 with lists and state on the
device (12.92 GiB; host lists before); 5,000,000 host lists and host state as before; 8.64M and 13.72M the wavefront
with host lists as before; 20,480,000 refused (the host state beyond 60% of `MemAvailable`).

Where the tiled call's choices cost time at 2,560,000 atoms (library `1f9796ba`, cube, five kept calls each, shared
plan cache): the plan's cap 4,096 all on the device 5.70-5.80 s (wavefront or plain order); plain order with the
host state at caps 24,576 / 32,768 / 49,152: 5.39 / 5.35 / 5.40 s (16,384: 6.42, one noisy run, min 5.50); the
wavefront with host lists at cap 8,192: 5.41 s. The kept active-edge slots are worth 4.5% (plain host state at
32,768: 116 slots 5.34 s, none 5.58 s) but took about 9 GB there (40 B per edge each). Caps above 65,536 give
nothing at 320,000 atoms (8 tiles at 65,536 and 80,000: 593.6 / 598.3 ms; 110,000 runs out of memory). A list
rebuild after warm-up costs about 300 ms at 320,000 atoms (626 ms kept call), 700 ms at 1,081,600 (2.43 s) and
4.6 s at 2,560,000 with 891 tiles (6.15 s; candidate and list builds 3.5 s of it).

`tile-compact-slots` (O32): a tile of a compact list that gets no full slot takes a compact one (row pointers,
senders and integer image shifts, 8 B per edge); its first sweep packs the shifts after the compaction, its later
sweeps restore the receivers, vectors and spline locators from them (`tile_restore_active_kernel`, bit for bit: the
shift arithmetic with explicit rounding in encode, decode and restore). The mix: all full slots where they cover the
tiles in flight, else the most full slots that leave compact ones for the rest, else compact slots only. Full slots
lose the pairs no sweep reads (36 B per edge). `LOUP_TILE_KEEP_COMPACT=0|k`. Library `19477a6c` against `1f9796ba`:
3,524,845 atoms (fraction 0.75, host lists and host state; A B B A): 8 full slots, kept call 7.44 / 7.45 s -> 40
compact slots, 7.31 / 7.23 s (b / a about 0.975); 320,000 atoms 587.5, 595.0 -> 582.4, 581.7 ms; the wavefront at
1,081,600 atoms covers its 5 tiles in flight (3 full and 2 compact, or 5 full) instead of 3-4 (times not captured).
The 2,560,000-atom default plan leaves no memory for any slot (unchanged, 5.71-5.72 s).

`tile-plan-slot-room` (O32): what the 2,560,000-atom plan's choices cost (library `19477a6c`, cube, fraction 0.9,
median of five kept calls): the device plan at cap 4,096 (891 tiles, no slot) 5.73-5.75 s; the plain host state at
65,536 (54 tiles) 6.49 s, at 49,152 5.24 s (38 full and 26 compact slots), at 32,768 5.26 s (125 full slots). At
65,536 the call found no memory left for any slot (`cudaMemGetInfo` 0 MB at the slots) although the plan's estimate
(191 MB state, 10,578 MB workspace) left 4 GB; at 49,152 the estimate (8,352 MB) was above what the call used (7,954 MB
free at the slots). So the planner now (1) tries the plain host state's caps first with room for compact slots for
every tile (1.5 x 8 B per list edge: each slot holds the largest tile's list, 1.4x the edges' bytes at 65,536), and
(2) takes the host state at 4x to 8x the device plan's cap where that plan needs caps under 16,384 and 256 tiles or
more and the host state fits there with that room. Library `6ed34416` against `19477a6c` (A B B A, 2,560,000 atoms,
default plan): 5,750.6 / 5,760.9 ms -> 5,247.3 / 5,234.9 ms (b / a 0.911; cap 32,768, host lists and state, 125
tiles), peak 12.95 -> 12.84 GiB; 320,000 atoms unchanged (cap 65,536 on the device, 589.6 / 592.7 ms); 3,524,845
atoms at fraction 0.75 now cap 32,768 with 89 compact slots, kept call 7.22 s (cap 65,536: 7.26 s; one call each).
The 256-tile and 8x limits are where it was measured (2,560,000 atoms only); a host state at 65,536 with no slot
(6.49 s) is the plan it avoids.

`tile-grid-rows` (O32): why 65,536 found no memory. The call's free memory per phase (2,560,000 atoms, host state):
the workspace set-up took 12.6 GB at cap 65,536 (plan estimate 10.6 GB) and 5.0 GB at 49,152 (estimate 8.2 GB). The
grid fit (FastMACE's `fit_grid`: the fewest pieces) chose 3 x 3 x 3 blocks of about 95,000 atoms, each split in two
in atom order, so each piece's domain is its whole block and halo: the widest 65,536 locals and 69,464 ghosts
(54 tiles). 4 x 4 x 4 (64 tiles) has 39,957 + 25,778. With a reach the fit now takes the grid with the fewest rows
(each piece counting its block's atoms and the halo at the mean density over a shell `reach` thick). Library
`95ade41c` against `6ed34416` (A B B A): 320,000 atoms 585.2 / 587.6 -> 586.7 / 586.3 ms (8 tiles either way), the
wavefront at 1,081,600 2,168.4 / 2,170.0 -> 2,169.1 / 2,168.9 ms (19 tiles either way); 2,560,000 atoms with the host
state forced at cap 65,536: 54 tiles, 6.49 s, no slot -> 64 tiles, 5.23 s, 38 full and 26 compact slots; the default
plan unchanged (cap 32,768, 5.24 s). The plan's workspace estimate (rows = cap + halo) now overstates the largest caps
(10.6 GB estimated, about 5 GB used at 65,536).

`tile-slot-block` (O32): the 2,560,000-atom default plan's 125 slots of kept active edges (74 MB each by the slot's
own count) took 10.6 GB, 1.4 GB more: six allocations per slot, each rounded up. The call then had 522 MB free
against a 1,566 MB reserve. A slot is now one allocation cut at 256 B boundaries (full and compact slots alike):
1,659 MB free after the slots. Library `253b3a5b` against `a8885e3a` (fresh plan folders): 320,000 atoms 586.2 /
586.8 -> 586.2 / 585.7 ms; the wavefront at 1,081,600 (A B B A, then B A A B) 2,164.4 / 2,166.6 -> 2,173.1 / 2,172.6
and 2,168.6 / 2,173.0 -> 2,157.0 / 2,164.1 ms (a tie); 2,560,000 atoms 5,243.5 -> 5,285.3 (one each), then A B B A
5,236.5 / 5,239.7 -> 5,252.9 / 5,249.0 ms (b / a about 1.003-1.004, at the noise). Tiled tests 55 passed.
Correction: the 1.14 GB did not repeat. Later runs of the same library had 537-541 MB free after the slots, and
cudaMalloc alone (125 slots of the same sizes) takes 9,456 MB as six allocations each and 9,437 MB as one: about
20 MB apart. The free memory read in the call moves by about a gigabyte between runs; `tile-list-arena` below
compares two runs per side.

`tile-list-arena` (O32): cudaMalloc alone on the RTX 5060 Ti (WSL) takes about 1.3 MB more than asked per allocation
of a few MB, cut or not: 891 tile lists of the 2,560,000-atom device plan's sizes 2,606 MB asked, 3,737 MB used. The
tile lists' device arrays now come from chunks of 128 MB (an arena on the tiled state), and all full slots from one
chunk, all compact slots from another (one allocation each where that fails). Library `1ce7922d` against `253b3a5b`
(two runs each): the device plan's list builds 3,072 -> 2,550 MB, free after the slots 0 -> 468-471 MB; the default
plan (125 tiles, host state) free after the slots 537-541 -> 1,860 MB (both runs). Times: 2,560,000 atoms device plan
5,739.7 / 5,754.4 -> 5,738.7 / 5,734.7 ms, default plan 5,249.3 / 5,247.0 -> 5,238.8 / 5,242.8 ms; 320,000 atoms
585.0 / 589.6 -> 585.7 / 585.6 ms; the wavefront at 1,081,600 2,163.1 / 2,145.4 -> 2,168.8 / 2,163.9 ms (within its
2,145-2,173 ms spread across this session's runs). Tiled tests 55 passed.

Compact slots only (`LOUP_TILE_KEEP_ACTIVE=0 LOUP_TILE_KEEP_COMPACT=999`, library `1ce7922d`, A B B A against the
default): 2,560,000 atoms default plan 5,251.4 / 5,249.1 -> 5,314.0 / 5,338.4 ms (+1.5%) with the peak 12.84 ->
6.16 GiB (125 compact slots of 17 MB instead of 125 full of 74 MB); 320,000 atoms 584.6 / 585.4 -> 598.2 / 596.0 ms
(+2.1%); the wavefront at 1,081,600 2,170.2 / 2,169.8 -> 2,189.3 / 2,176.8 ms (+0.6%). Not the default (slower); the
setting for half the device memory at about 1.5% of the time. The restores write the receivers, vectors and spline
locators back into the handle's buffers each later sweep (about 28 B per edge written and read again).

`tile-pinned-reuse` (O32): a list rebuild at 2,560,000 atoms (default plan, host state; `rebuild_cost.py 80`) costs
7.5 s over a kept call (12.96 against 5.46 s): plan 0.19 s, candidates 0.45-0.64, list builds 1.5, the state's
allocations 1.5 (pinned host layer state) and the host windows 2.25 (pinned). A released tiled state's pinned host
buffers now stay on the handle as spares; the next state's set-up takes one of at least the size and at most 25%
more, and frees the rest at the end of its set-up (the planner counts the spares as available host memory).
Library `e14ae3bc` against `b4c57d9d`: state allocations 1,483-1,517 -> 37-39 ms; host windows 2,234-2,261 -> 41 ms
(the first rebuild 2,390: its windows found no spare of their size); rebuild call 12,991 / 12,937 -> 11,289 / 8,497 ms;
kept calls 5,439 / 5,470 -> 5,436 / 5,492 ms. Tiled, tiled-MD and tile-list tests 67 passed.
Then the host lists' mapped pinned edges the same way (library `7f0bf882` against `e14ae3bc`): list builds at a
rebuild 1,724 / 1,569 -> 892 / 801 ms; rebuild calls 11,511 / 8,129 -> 10,412 / 7,165 ms (the first rebuild's windows
still allocate); kept calls 5,442 / 5,531 -> 5,450 / 5,503 ms. 67 tests passed. A rebuild now costs about 1.7 s over a
kept call (7.2 against 5.5 s; 7.5 s before `tile-pinned-reuse`). At 320,000 atoms a rebuild costs 236 ms over a
618 ms kept call (plan 16, candidates 44, lists 78, state 26, slots 50 ms).

Suites on `b05fd9e` (library `7f0bf882`, built from it): `tests/cpu` 494 passed, 1 skipped; `tests/gpu -m "not
acceptance"` 396 passed, 1 failed: `test_auto_tiles_320000_atoms_without_a_user_setting` (the message was not kept).
It passed in the suite on `457196c` and in four runs alone and two after the files before it (peak 12.42 GiB against
the 13.14 GiB bound, on this library and the one before the pinned reuse): not reproduced. On `457196c` the
`LoupMemoryPlan` layout check failed (its C program lacked the O31/O32 fields; fixed in `868793d`) and the ASE
calculator test failed once (passed on rerun).

`tile-plan-fit` (O32, NEUTRAL, not kept): the planner's tile workspace estimate assumed blocks of `cap` atoms with
ghosts scaled from the smallest cap, about twice the workspace a call uses at large caps (320,000 atoms: 9.3 GB
estimated, about 5.1 GB used). A trial ran the grid fit for each candidate cap (wrapped fractions once, counts kept per
grid) and estimated from the widest piece and its halo: 320,000 atoms 9,329 -> 6,861 MB, 2,560,000 5,678 -> 4,232 MB,
the 1.08M rod 10,054 -> 10,378 MB; planning +0.1 s at 2.56M and +0.2 s on the rod. Plans changed only where memory is
short (fraction 0.75): 3,524,845 atoms cap 32,768 -> 49,152, 5,000,000 24,576 -> 32,768, but with the same tiles (125,
216; the grid fit by rows decides them), the same peak (10.85, 10.83 GiB) and tied times (A B A B: 7,196 / 7,206
against 7,218 / 7,236 ms; 10,284 / 10,228 against 10,222 / 10,282 ms). Reverted: the better estimate does not change
what runs.

8,008,065 atoms (SrTiO3 117^3, fraction 0.9, library `7f0bf882`): the default plan is the device wavefront at cap 6,144
(2,016 tiles, row pool 1.83M rows, host lists), kept call 17,243 ms, peak 13.10 GiB. The plain host state forced
(`LOUP_TILE_HOST_STATE=1`) plans cap 16,384 (512 tiles, 23.9 GB pinned host memory) and runs 16,592 ms, peak 12.97 GiB:
3.8% faster in one run each. The plan does not take it because the host state's 23.9 GB is at the 60% of
`MemAvailable` the plan allows (40 GB in this WSL); left as is. The forced wavefront host pool at this size took the
WSL distro down (the force skips the host-memory check), and a second forced host-pool run at 1,081,600 atoms (2.7 GB
planned, the host path) did the same a few minutes later. A third, at 320,000 atoms in a rod (160 x 20 x 20 cells,
1.5 GB host, cap 65,536, 8.2 GB tile workspace), ran three processes and took WSL down in the fourth (bus on; the
first bus-on process had finished). Three failures in three forced wavefront host-pool timing jobs, at 1.5 to tens of
GB of host memory, with and without the bus; the small host-pool tests (5,760 and 11,520 atoms) and every other mode
ran the same day without one, and the 1,081,600-atom forced run of 16 November finished. A fourth failure came during
`pytest tests/gpu/test_tiled.py -k "host and not wavefront"` (the plain host state, small systems, which passed the
same morning): after the first failure WSL fails in host-state work generally, so the mode is not shown to be the
cause; WSL or its GPU driver may have stayed unstable after the first failure (not checked: no reboot from this
session). Cause not found (the distro's logs go with it). Until a clean machine reproduces it or not, treat forced
host-state runs on WSL with care. A tile's rows can hold one host row more than once (grids with one or two tiles
along an axis), and the host state's gradient adds, split over host threads by tile row, could add into it from two
threads at once in the plain order's pipelined adds, the alias windows and the wavefront host pool.

After the owner restarted WSL (`wsl --shutdown`, not a reboot of the machine), the same day: the adds now split over
host threads by destination host row, so each host row has one writer (O32 race fix, 2b26d33, from the local branch
`wip/host-adds-by-row`). `tests/gpu/test_tiled.py -k host` 37 passed (the run that failed before the restart),
the whole file 55 passed, `tests/cpu` 494 passed, `tests/gpu -m "not acceptance"` 397 passed (7 D3 tests skipped:
`NbCl5_R2SCAN.cif` not present); no WSL failure. On a freshly started WSL the forced wavefront host pool then ran
three processes each at 320,000 atoms in a rod (fraction 0.6, 1.5 GB host, 935-953 ms) and 1,081,600 atoms
(fraction 0.9, 9.0 GB host, 3.35-3.40 s), the two cases that failed after the first failure, without a failure: the
later failures look like WSL's state after the first one rather than the mode. The first failure's cause: the 8M
forced host-pool plan (fraction 0.9, cap 65,536) needs 42.1 GB of pinned host memory against 40.1 GB available in
the WSL distro, and `LOUP_TILE_HOST_STATE=1` skipped the plan's 60% check. A plan that would pin more than 90% of
the available host memory is now refused with a message naming the forced setting (test
`test_a_forced_host_state_beyond_the_host_memory_is_refused`); the default plans stay within 60% and do not change.
All of `tests/gpu` on that library (bf595d5): 412 passed, 8 skipped, 1 failed:
`test_capacity.py::test_auto_tiles_320000_atoms_without_a_user_setting` (peak against the free memory read at the
call), which passed alone twice and with `test_capacity.py` and `test_tiled.py` twice (62 passed): not reproduced.

`tile-host-state-larger-cap` (O32, ADOPTED, 5060 Ti only): from 2^20 atoms a device plan below the largest cap gives
way to the plain host state where that reaches a larger cap. 1,080,000 atoms at fraction 0.9: device 49,152 (45 tiles)
2.285 / 2.271 s, 11.6-11.9 GiB -> host state 65,536 (27 tiles) 2.196 / 2.195 s, 10.56 GiB; at 0.75 / 0.5 -2.7% /
-4.7%; 8,008,065 at 0.75: 6,144 (wavefront) 17.58 / 17.60 s -> 16,384 16.79 / 16.67 s. Below 2^20 it lost (320,000 up
to +4.2%, 135,000 +10%). 4 of 35 plans change; tiled, memory-plan, capacity and tiled-MD tests 78 passed.

| atoms | fraction 0.9 | 0.5 | 0.35 | 0.25 |
| --- | --- | --- | --- | --- |
| 320,000 | 0.583 s, 11.26 GiB | 0.636 s, 4.78 GiB | 0.647 s, 4.78 GiB | 0.670 s, 3.64 GiB |
| 1,080,000 (this change) | 2.196 s, 10.56 GiB | 2.214 s, 7.06 GiB | 2.259 s, 5.06 GiB | 2.282 s, 3.62 GiB |
| 2,560,000 | 5.24 s, 12.84 GiB | 5.28 s, 7.23 GiB | 5.38 s, 4.98 GiB | 5.45 s, 3.52 GiB |
| 5,000,000 | 10.27 s, 13.05 GiB | 10.39 s, 7.22 GiB | 10.59 s, 5.04 GiB | 10.69 s, 3.62 GiB |

Kept calls, one run each (two at 1.08M / 0.9): from a million atoms a quarter of the card costs 2-4% of the time at
0.9. All of `tests/gpu` on the installed library at 97e365d: 413 passed, 8 skipped (the NbCl5 structure).

After the round6-hardening kernels are merged (S110: -18 to -22% VRAM in the whole-system path; not on release/v1 at
4a5e9c2): the tile workspace estimates and so the planner's caps change. Re-run the plan comparison (135,000 to 8M
atoms, fractions 0.9 to 0.25) and the kept-call times of the plans that move, and re-check the host-state rules of
this section (`tile-host-state-window`, `tile-slot-room-limit`, `tile-host-state-larger-cap`) against them.
(Done on 17 November 2026: "The tiled mode after the merge" below.)

`tile-host-state-larger-cap` on `MACE-OMAT-0 small` (measured on release/v1 before the merge, kept calls, one or
two runs each, 5060 Ti only): at fraction 0.9 the plan does not change (1,080,000 atoms 1.199-1.221 s, 2,560,000
atoms 2.94-2.97 s). At fraction 0.5, 1,080,000 atoms: default (cap 49,152, host state) 1.216 / 1.217 s against the
host state off (cap 32,768) 1.247 / 1.234 s, about -1.6%; 2,560,000 atoms: default (cap 32,768) 2.913 s against off
(cap 16,384) 3.083 / 3.101 s, about -5.8%. Peaks 7.23 against 7.18 GiB and 7.29 against 7.24 GiB.

Merge of round6-hardening 13d6337 into release/v1 (17 November 2026; PLAN.md D84 and D85; 5060 Ti only).
Decisions: the ABI-1 `LoupMDStats` fields stay (`dangerous_builds` is always 0; `pipelined_steps` now counts the
steps the GPU ran without waiting for a host-finished rebuild); the decaying step-displacement tracker stays only
for `loup_get_step_displacement`, the saved state and the automatic skin (ledger `md-disp-decay` superseded); the
chain fold is chosen per system (whole systems fold, tiled and domain systems do not, so the sweeps stay available,
and MACE-OMOL-0 extra large runs tiled without `LOUP_CHAIN_FOLD=0`); the tile lists' full form drops receivers and
pairs as S113 did for the whole system (36 -> 28 B per edge, `kTileFullEdgeB`); the variable cell keeps integer image
shifts as one `char4` per edge (4 B) formed after each rebuild; variable-cell runs take every rebuild on the host.
`results/` is not merged (local paths).

What the per-system fold does to a comparison of a tiled with a whole-system result (measured, `SrTiO3` 3x3x3,
three engines a side, differences in eV/atom, eV/A, eV/A^3):

| pair | OMAT-0 small | OMAT-0 medium (generic) |
| --- | --- | --- |
| whole, fold against fold | 0-3e-9, 6-8e-7, 2-6e-9 | 0-4e-9, 6-8e-7, 2-4e-9 |
| whole, no fold against no fold | 0, 6-9e-7, 2-3e-9 | 0-8e-9, 6-8e-7, 3-5e-9 |
| whole, fold against no fold | 2.4-2.8e-8, 1.8-2.1e-6, 1.4-1.8e-8 | 4.1-4.5e-8, 2.0-2.5e-6, 6-7e-9 |
| domain (no fold) against whole with the fold | 2.6-3.5e-8, 1.8-2.0e-6, 1.5-1.8e-8 | 2.9-3.4e-8, 2.0-2.4e-6, 6e-9-1.1e-8 |
| domain against whole without the fold | 1e-9-1.0e-8, 7-9e-7, 2-4e-9 | 9e-9-1.6e-8, 8e-7-1.0e-6, 5-6e-9 |

The fold is another order of float32 operations, a quarter of the gate's force floor (1e-5 eV/A) and a fifth of its
stress floor (1e-7 eV/A^3) at most. The tests whose bounds are those of the same operations (1e-7 eV/atom,
3e-6 or 1e-5 eV/A, 1e-8 or 3e-8 eV/A^3) take their whole-system reference without the fold
(`tests/gpu/gpu_support.py`, `unfolded`); with the folded reference `test_sweeps_on_a_periodic_system_without_ghosts`
failed once in the fast tier and passed alone.

Before the merge commit (library sha256 `74612462`): the merged tree built at the first compile;
`codegen/gen_generic.py` and `codegen/gen_kernels.py` reproduce `src/generated_generic.cu`, `.cuh`, the manifest,
`src/generated_kernels.cuh` and its signature byte for byte; `tests/cpu` 490 passed, 5 skipped; `tests/gpu -m fast`
352 passed, 2 failed (the fold's two premises above, both corrected in the tests), 7 skipped (the NbCl5 structure);
then every file of the full tier passed with the corrected tests (domain, sweeps, capacity and large box 25, tiled,
tile lists and memory plan 64, tiled MD 10, the integrators' full tests 12) and `-m acceptance` 15 passed, 1 skipped:
the default gate (OMAT-0 medium on the generic kernels, 18 rows) worst force ratio 2.05, stress 1.93.
All tiers again on d0d149f (the merge 09d6daa and the gate's follow-up; the same library): `tests/cpu` 490 passed,
5 skipped; `tests/gpu -m fast` 354 passed, 7 skipped; `-m full` 48 passed; `-m acceptance` 15 passed, 1 skipped
(417 passed, 8 skipped: the NbCl5 structure is not in the folder). `loupmd validate --capacity tiled` on default
engines: OMAT-0 small oxide worst force / stress ratio 1.29 / 1.47, OMAT-0 medium oxide 1.84 / 1.24 (wavefront
1.84 / 1.35, whole 1.92 / 1.38), OMOL-0 extra large organic 0.85 / 0.81.

(Peaks and budgets in this entry and the next were read from CUDA's free memory, which §6.35 shows to be wrong under
WSL 2: the budgets are 1.5 to 2 GiB too large and peaks above about 10.4 GiB are 1.2 GiB too high. The times and
plans stand for the fractions of that larger budget.)

The tiled mode after the merge (17 November 2026, 5060 Ti only): the merged library (sha256 `74612462`, commit
09d6daa) against the library of 97e365d, SrTiO3 cubes with 0.04 A of noise, skin 0.5 A, no stress. Plans
(`plan_execution` only): OMAT-0 medium and small, 135,000 / 320,000 / 1,080,000 / 2,560,000 / 3,524,845 / 5,000,000 /
8,008,065 atoms at fractions 0.9 / 0.75 / 0.5 / 0.35 / 0.25, 70 plans a library. The tile workspace is 2-4% smaller
for OMAT-0 medium (cap 65,536 at 320,000 atoms: 8.69 -> 8.38 GiB) and 3-5% for OMAT-0 small (6.78 -> 6.47 GiB); the
whole-system count is 4.7% and 5.7% smaller (135,000 atoms: 13.50 -> 12.87 GiB and 10.79 -> 10.17 GiB), not the 18-22%
of S110-S112, which are the specialised path's. 4 of 70 plans move, each to a larger cap at the same mode: OMAT-0
medium 1,080,000 atoms at 0.75 (49,152 -> 65,536); OMAT-0 small 320,000 at 0.5 and 1,080,000 at 0.5 (49,152 ->
65,536) and 5,000,000 at 0.25 (16,384 -> 24,576). No plan changes between device lists, host lists and host state.

Kept calls, each library in its own process with a fresh plan directory, order A B B A (5,000,000 atoms: A B in
one job, B A in the next), three kept calls a run up to 1,080,000 atoms and two above; the two runs of a side are
given, and the ratio is of their sums. OMAT-0 medium:

| atoms | fraction | cap, tiles | before the merge (s) | merged (s) | merged / before | peak (GiB) |
| --- | --- | --- | --- | --- | --- | --- |
| 320,000 | 0.9 | 65,536, 8 | 0.585 / 0.586 | 0.579 / 0.577 | 0.987 | 11.26 -> 11.07 |
| 320,000 | 0.5 | 32,768, 27 | 0.640 / 0.643 | 0.584 / 0.588 | 0.914 | 4.78 -> 7.17 |
| 320,000 | 0.35 | 24,576, 27 | 0.641 / 0.644 | 0.633 / 0.636 | 0.988 | 4.78 -> 4.72 |
| 320,000 | 0.25 | 12,288, 28 | 0.669 / 0.674 | 0.662 / 0.663 | 0.987 | 3.64 -> 3.59 |
| 1,080,000 | 0.9 | 65,536, 27 | 2.193 / 2.194 | 2.174 / 2.164 | 0.989 | 10.56 -> 10.37 |
| 1,080,000 | 0.75 | 49,152 -> 65,536, 27 | 2.209 / 2.195 | 2.160 / 2.167 | 0.983 | 10.56 -> 10.37-10.40 |
| 1,080,000 | 0.5 | 32,768, 64 | 2.218 / 2.213 | 2.189 / 2.179 | 0.986 | 7.06 -> 6.98 |
| 1,080,000 | 0.35 | 16,384, 125 | 2.283 / 2.260 | 2.226 / 2.230 | 0.981 | 5.06 -> 5.09 |
| 1,080,000 | 0.25 | 12,288, 125 | 2.287 / 2.286 | 2.247 / 2.248 | 0.983 | 3.62 -> 3.63 |
| 2,560,000 | 0.9 | 32,768, 125 | 5.255 / 5.227 | 5.170 / 5.166 | 0.986 | 12.84 -> 12.74 |
| 2,560,000 | 0.5 | 24,576, 125 | 5.318 / 5.287 | 5.217 / 5.213 | 0.983 | 7.23 -> 7.24 |
| 2,560,000 | 0.35 | 8,192, 343 | 5.404 / 5.397 | 5.320 / 5.311 | 0.984 | 4.98 -> 4.99 |
| 2,560,000 | 0.25 | 16,384, 216 | 5.451 / 5.430 | 5.369 / 5.376 | 0.988 | 3.52 -> 3.52 |
| 5,000,000 | 0.9 | 32,768, 216 | 10.291 / 10.285 | 10.116 / 10.165 | 0.986 | 13.05 -> 13.06 |
| 5,000,000 | 0.5 | 32,768, 216 | 10.440 / 10.469 | 10.270 / 10.298 | 0.984 | 7.22 -> 7.22 |
| 5,000,000 | 0.35 | 24,576, 216 | 10.624 / 10.617 | 10.472 / 10.479 | 0.986 | 5.04 -> 5.03 |
| 5,000,000 | 0.25 | 16,384, 343 | 10.720 / 10.709 | 10.583 / 10.565 | 0.987 | 3.62 -> 3.62 |
| 8,008,065 | 0.9 | 6,144, 2,016 (wavefront) | 17.326 / 17.310 | 16.965 / 17.002 | 0.981 | 13.10 -> 13.10-13.11 |

OMAT-0 small:

| atoms | fraction | cap, tiles | before the merge (s) | merged (s) | merged / before | peak (GiB) |
| --- | --- | --- | --- | --- | --- | --- |
| 320,000 | 0.5 | 49,152 -> 65,536, 8 | 0.352 / 0.354 | 0.347 / 0.346 | 0.982 | 6.49 -> 6.31 |
| 1,080,000 | 0.9 | 65,536, 45 | 1.213 / 1.206 | 1.182 / 1.200 | 0.985 | 12.80 -> 12.63 |
| 1,080,000 | 0.5 | 49,152 -> 65,536, 27 (host state) | 1.218 / 1.219 | 1.199 / 1.204 | 0.986 | 7.23 -> 7.15 |
| 2,560,000 | 0.9 | 65,536, 96 | 2.968 / 2.965 | 2.900 / 2.897 | 0.977 | 12.70 -> 12.74 |

Every plan is 1.1-2.3% faster with the merged library at an equal or slightly lower peak, in both orders. The one
larger step, 320,000 atoms of OMAT-0 medium at fraction 0.5 (-8.6%), is memory the smaller lists free within the
budget (the peak rises to the fraction's 7.17 GiB): for the kept slots of active edges or for the kept layer-0
results, which of the two was not told apart. Energies agree to 1e-7 eV/atom between the libraries up to 5,000,000 atoms and to
3e-7 at 8,008,065 (where two runs of one library differ by 2e-7).

The host-state rules of this section against the merged plans: `tile-host-state-larger-cap` and
`tile-slot-room-limit` pick the plans they picked before (1,080,000 atoms at 0.9: the host state at 65,536;
5,000,000 at 0.5: 32,768). `tile-host-state-window`'s plan for 8,008,065 atoms at 0.9 (the host state at 16,384,
23.9 GB of pinned host memory) was not taken by either library in these runs: both planned the device wavefront at
6,144 at 0.9 and at 0.75 (the table's row; the host state was 3.8% faster when it was measured). `MemAvailable` was
40.3 GB before the process started, and the host state may pin 60% of what is available when the plan is made:
23.9 GB is 59% of 40.3 GB, so on this WSL (39 GiB) that plan sits at the limit and a few hundred MB decide it.
Why these runs fell on the other side was not examined (a guess: the process's own arrays for 8M atoms); the
limit is not changed here.

`tile-shared-layers` (O31, ADOPTED, 5060 Ti only; PLAN.md D86): a sweep runs one layer, and of another layer it
reads and writes only the output and that output's gradient. A tiled or domain system therefore keeps its layers' own
buffers (x, the products' intermediates, messages, their gradients, the readout's hidden rows) in one arena as large
as the largest layer, each layer from the arena's start; the layer outputs, their gradients and the zero slab keep
buffers of their own (`GenericModel::share_layer_buffers`, set for domains in `set_system_impl`;
`LOUP_SWEEP_REPLAY` shares too, so the replay tests, which overwrite everything but the outputs with NaN, run the
shared layout on whole systems; `LOUP_TILE_SHARE_LAYERS=0` gives every buffer its own memory). A system that shares
refuses the whole pass. The tile workspace at cap 65,536: OMAT-0 medium 8.38 -> 5.62 GiB (-33%), OMAT-0 small
6.47 -> 3.96 GiB (-39%).

The plan still counts a row with every layer's buffers (`system_bytes_unshared`), so its caps are the ones measured
before and the whole-system count is unchanged; what the workspace no longer takes goes to the kept slots (they
fill the fraction's budget) and otherwise stays free. Two other plans were measured and not kept. Counting the
shared size in the cap search moved device plans to larger caps without room for their slots: 320,000 atoms at
fraction 0.5, cap 32,768 (27 tiles, every slot) 0.581 / 0.583 s -> cap 65,536 (8 tiles, no slot) 0.627 / 0.631 s;
1,080,000 at 0.9 left the host state for a device plan, 2.164 -> 2.183 s at a 2.5 GiB higher peak. With a rule that
also wants room for every tile's full slot (36 B per list edge) in device plans, 135,000 atoms at 0.25 went from
cap 16,384 (27 tiles) to 24,576 (8 tiles), 0.254 -> 0.266 s, and 320,000 at 0.25 from 12,288 to 4,096, 0.663 ->
0.674 s.

Kept calls, the library with the arena (sha256 `fea051bd`) against the merged library, each in its own process
with a fresh plan directory, A B B A, three kept calls a run up to 1,080,000 atoms and two above; every plan is
the same in both. Ratio of the two runs' sums, device peak before -> after. OMAT-0 medium:

| atoms | 0.9 | 0.5 | 0.35 | 0.25 |
| --- | --- | --- | --- | --- |
| 135,000 | 1.002, 5.05 -> 4.05 GiB | 1.000, 5.05 -> 4.05 | 0.994, 5.05 -> 4.05 | 0.994, 3.25 -> 2.86 |
| 320,000 | 1.005, 11.07 -> 9.03 | 1.008, 7.17 -> 6.46 | 0.996, 4.72 -> 4.02 | 0.963, 3.59 -> 3.52 |
| 1,080,000 | 1.002, 10.37 -> 8.34 | 0.999, 6.98 -> 5.99 | 1.000, 5.09 -> 5.09 | 0.996, 3.63 -> 3.62 |
| 2,560,000 | 1.009, 12.74 -> 11.57 | 1.002, 7.24 -> 7.25 | 1.002, 4.99 -> 5.00 | 0.992, 3.52 -> 3.52 |
| 5,000,000 (four kept calls, three runs against one) | 0.997, 13.06 -> 13.05 | 0.989, 7.22 -> 7.24 | 0.988, 5.03 -> 5.05 | 0.994, 3.62 -> 3.61 |
| 8,008,065 (wavefront) | 0.996, 13.10 -> 13.13 | | | |

OMAT-0 small (fractions 0.9 / 0.5 / 0.25): 320,000 atoms 1.000 / 0.874 / 0.999 at 8.75 -> 6.90, 6.31 -> 6.90 and
3.32 -> 2.68 GiB; 1,080,000 atoms 1.005 / 0.985 / 0.999 at 12.63 -> 10.78, 7.15 -> 6.76 and 3.64 -> 3.62 GiB;
2,560,000 atoms 0.994 / 0.995 / 0.969 at 12.74 -> 12.76, 7.25 -> 7.31 and 3.63 -> 3.65 GiB. In 30 plans the ratio is
0.874 to 1.009: within 1% in 24, and 1.1% to 12.6% faster in six (the largest: OMAT-0 small 320,000 atoms at 0.5,
0.346 -> 0.303 s, where every tile's slot of kept active edges now fits). The peak is 0.4 to 2.0 GiB lower (5-21%)
in 14 plans, 0.6 GiB higher in that one, and within 0.1 GiB in the rest, where the slots fill the budget.

Not explained: in the first A B run at 5,000,000 atoms one process of the arena library had two kept calls that took
twice as long (20.14 s beside 10.20 s at fraction 0.9, 18.46 s beside 10.47 s at 0.35; the 0.5 and 0.25 plans
between and after them ran normally). The same library's 62 other kept calls at that size were normal (6 in that
process, 8 in the B A run, 48 in three runs of four calls per plan with `LOUP_DEBUG_TILE_TIMES=1`), as were the 64 calls of the
libraries without the arena that day; the other checkout showed no activity at the time. Cause not found, and not
shown to be the arena's. The 5,000,000-atom row above is from the three later runs.

Tests on the library with the arena (sha256 `fea051bd`): `tests/cpu` 490 passed, 5 skipped; `tests/gpu -m fast`
356 passed, 7 skipped; `-m full` 48 passed; `-m acceptance` 15 passed, 1 skipped (419 passed, 8 skipped: the NbCl5
structure). `loupmd validate --capacity tiled`: OMAT-0 small oxide worst force / stress ratio 1.30 / 1.51, OMAT-0
medium oxide 1.83 / 1.28 (wavefront 1.83 / 1.27, whole 1.83 / 1.24), OMOL-0 extra large organic 0.87 / 0.78.
The committed source differs from that build's by one comment; its library (sha256 `57865727`) differs in four
bytes, and `tests/gpu/test_tiled.py`, `test_sweeps.py`, `test_engine.py` and `test_quick_gpu.py` pass on it (the
arena's own test failed once in seven runs of its first form, which asked for a lower peak on a 2,560-atom cell;
the failing assertion was not captured; the test now asks for the peak on 20,480 atoms, and passed five times).

`tile-wave-host-bus` (O32, NEUTRAL, not adopted; local branch `wip/tile-wave-host-bus`): the wavefront's host pool
mapped, its ghost gathers, gradient adds (plain adds in rounds of distinct host rows) and block zeroing as kernels on
the stream instead of host work after a synchronisation. `tests/gpu/test_tiled.py -k "wavefront or host"` 39 passed.
320,000 atoms in a rod at fraction 0.6 (9 tiles, 5 blocks of 46,000 rows; up to 4 add rounds): kept call bus on
928.8 ms against the host work 939.7 / 931.6 ms, peak 7.73 / 7.72 GiB, energies within 2e-8 eV / atom; the
synchronisations are not where the host pool's time goes (its copies are). Not adopted (one run on its side, no
gain to weigh against a new path). While writing it: the host path's gradient adds split a tile's rows over host threads, and a
tile whose ghosts hold an image of one of its own rows (grids with one tile along an axis) can add into one host row
from two threads at once. Not seen in a result (the wavefront host pool runs only forced or where the plain host state
does not fit); the branch's rounds avoid it.

`tile-host-state-window` (O32, ADOPTED, 5060 Ti only): 8,008,065 atoms (SrTiO3 117^3, OMAT-0 medium, fraction 0.9).
The device plan's cap 6,144 (2,016 tiles, wavefront) left the plain host state only 4x-8x that cap, where nothing
fits; at 16,384 (2.67x, 512 tiles, 23.9 GB host) it is faster, A B B A, two kept calls each:

| plan | kept (s) | cold (s) | peak (GiB) |
| --- | --- | --- | --- |
| device, cap 6,144 (old default) | 17.29 / 17.28 | 49.4 / 49.0 | 13.10 |
| host state, cap 16,384 (forced) | 16.60 / 16.64 | 40.6 / 39.0 | 12.97 |
| host state, new default (one run, cold GEMM plans) | 16.70 | 50.8 | 12.98 |

The search now takes 2.5x-4x after 8x-4x. Of 15 plans (320,000 to 8M atoms, fractions 0.9 / 0.75 / 0.5) only 8M at
0.9 changes. `tests/gpu/test_tiled.py`, `test_memory_plan.py`, `test_large_box.py` 64 passed; on the installed
library at 7774638 `tests/gpu -m "not acceptance"` 397 passed (7 D3 skips) and `-m acceptance` 15 passed (1 NbCl5
skip).

`tile-slot-room-limit` (O32, ADOPTED, 5060 Ti only): the plain host state's cap search wanted room for compact slots
of every tile at any cost in cap. 5,000,000 atoms at fraction 0.5 got cap 4,096 (1,362 tiles, 11.26 / 11.24 s, peak
7.26 GiB) where 32,768 fits (216 tiles, 10.44 / 10.39 s, 7.22 GiB). The search now drops the slot room when it costs
more than 4x in cap; where it costs 1.3x-2x (5M at 0.9 and 0.75, 2.56M at 0.5) the two tie within 0.7%, so those keep
it. Of 20 plans only 5M at 0.5 changes; the tiled, memory-plan, large-box and capacity tests 70 passed; on the
installed library at b8d302f `tests/gpu -m "not acceptance"` 397 passed (7 D3 skips), `-m acceptance` 15 passed (1
NbCl5 skip). 2,560,000 atoms at fraction 0.35 (cap 8,192, 343 tiles) 5.38 s against 5.32 / 5.39 s forced at 16,384 /
24,576: a tie, kept; at 4.98 GiB peak it is 3% slower than at fraction 0.9 (5.24 s, 12.84 GiB). 8M at fraction
0.75 (device, cap 6,144, 17.58 s, 10.91 GiB, one run): the host state forced at 12,288 with the lists on the device
17.28 s, 10.58 GiB; at 8,192 17.44 s (one run each). The window down to 2x changed none of 20 plans (it takes the
lists to host memory and wants slot room, which does not fit there); not pursued for 1.7% in one run.
The host state with the lists on the device (`LOUP_TILE_HOST_LISTS=0`, one run each, fraction 0.9): 2,560,000 atoms
cap 49,152 5.28 s against the default's lists in host memory at 32,768 5.25 s (peak 12.38 against 12.84 GiB, cold
12.9 against 16.9 s); 5,000,000 cap 12,288 10.50 s against 10.26 s (cold 23.5 against 34.0 s). Kept calls tie or
lose, so the plan stays; the cold calls are 24-31% shorter with device lists, not measured in a tiled MD run's list
rebuilds (an open question for the rebuild cost). Measured (`tile-host-state-device-lists`, NEUTRAL): with
calls after a move past half the skin, the forced device-lists plan at 49,152 rebuilds in 6.7 s against the
default's 7.1-10.1 s at the same kept time, but a planner rule for device lists changed 5 of 20 plans to caps no
larger than before, where kept calls tie or lose up to 2% and rebuilds are mixed; reverted.

`tile-pinned-headroom` (O32, ADOPTED, 5060 Ti only): the first list rebuild after the atoms moved found no spare pinned
buffer large enough and allocated anew (2,560,000 atoms: 10.22 s against 7.1-7.2 s for later rebuilds; 2.47 s host
windows, 0.56 s state buffers). New pinned buffers now have 1/32 room: first rebuild 7.06 / 7.09 s, kept calls
unchanged (5.23-5.25 s); 8M atoms first / second rebuild 23.06 / 22.79 s. Pinned host memory +3%, not in the plan's
host estimate. Tiled, memory-plan and tiled-MD tests 71 passed; on the installed library at f0406bf with the
kernel-plugin test's bounds at the gate's floors (b5a0b62) all of `tests/gpu` (fast, full and acceptance) 412 passed,
8 skipped (the NbCl5 structure).

### 6.35 The memory plan against what the calls take, and the capacity of the RTX 5060 Ti (18 November 2026, PLAN.md O33)

Everything in this section is measured on the RTX 5060 Ti in WSL 2 only.

**The free memory the plans start from.** Under WSL 2 `cudaMemGetInfo` does not give the card's free memory. With
Windows programs holding 2.9 GiB it reported 15.16 GiB free of 15.90 (NVML: 13.1 GiB free). It then fell by exactly
what the process allocated up to 10.2 GiB held, and by 1.2 GiB more at once at the next step (allocations of 512 MiB
and 1 GiB in a row, `torch.empty`; NVML's use rose by each allocation and nothing else). A single allocation of
64 MiB to 4 GiB takes its size, to 2 MiB. So every budget the plans made was 1.5 to 2 GiB too large, and every
device peak read above about 10.4 GiB held was 1.2 GiB too high: the peaks of §6.34 above that level (11.07, 12.74,
13.06 GiB ...) and the "1.1 GiB the counters miss" that MH-1 seemed to take at 20,480 atoms (11.6 GiB read, 9.97 by
NVML, 10.00 counted). The engine now takes the smaller of CUDA's and NVML's free memory wherever it plans or reads a
peak (`device_memory`, `libnvidia-ml.so.1` loaded at run time; 0.35 ms a query; `LOUP_NO_NVML=1` keeps CUDA's figure).
A memory fraction is now a fraction of the memory that is free in fact: at 0.9 the plans may use 11.8 GiB here, not
13.1 to 13.6, and today's plans at a fraction f have the memory §6.34's had at about 0.88 f.

**Whole systems.** `loup_plan_memory` scales the current system's buffers; `loup_plan_execution` counts a whole system
from a probe tile. The second ignored the skip-chain fold (a whole system never forms the non-last layers' outputs
and their gradients: 4% of OMAT-0 medium's rows) and both left 30 to 100 MB out that do not scale (now 64 MB instead
of 32). Plan / measured (NVML, from before `set_system` to after the first evaluation; the capacity plan, then the
scaled plan):

| model | atoms | measured (GiB) | capacity plan | scaled plan |
| --- | --- | --- | --- | --- |
| OMAT-0 medium | 5,000 / 40,000 / 98,415 | 0.521 / 3.701 / 9.092 | 1.001 / 1.004 / 0.995 | 1.004 / 1.005 / 0.996 |
| MH-1 | 5,000 / 20,480 | 2.525 / 9.975 | 0.987 / 1.004 | 0.994 / 1.005 |
| OMOL-0 extra large (water) | 648 / 5,184 | 1.250 / 8.619 | 0.891 / 0.981 | 0.961 / 0.991 |
| OFF23 medium (water) | 5,184 / 41,472 | 0.480 / 3.531 | 1.040 / 1.003 | 1.043 / 1.003 |
| POLAR-1-S (NaCl) | 1,728 / 8,000 / 21,952 | 0.578 / 2.441 / 6.582 | none | 1.029 / 1.011 / 1.008 |
| POLAR-1-M (NaCl) | 1,728 / 8,000 | 1.281 / 5.383 | none | 0.965 / 0.996 |
| POLAR-1-L (NaCl) | 1,728 | 2.348 | none | 0.949 |

Before: the capacity plan 1.03-1.06 at the larger sizes, the scaled plan 0.988-1.003 there and 0.94-0.98 at the
small ones. The long-range models' k-space and charge buffers (`src/polar.cu`) were not counted at all: the scaled
plan was 23% low (0.763 / 0.773 for POLAR-1-S) and counts them now (`PolarLR::system_bytes`). Open: for these
models `loup_plan_execution` gives no whole-system count (they have no probe tile). A first call takes more
for a moment than the system keeps: the GEMM timing writes into a scratch copy of each output (121,945 atoms of
OMAT-0 medium: 0.9 GiB above the 11.2 GiB kept). The plan's "fits whole" check now leaves room for the model's
largest buffer and the cache-flush buffer.

**Tiled systems.** The plan reported the estimate its cap search uses: every layer's own buffers (§6.34: the layers
now share an arena), a tile of `cap` receivers whatever the grid makes, 32 B a kept row, and none of the kept slots,
staging buffers and layer-0 results that the call adds within the fraction. Plan / peak was 0.55 to 2.07 on 13
plans (135,000 atoms at fraction 0.9: 8.40 GiB planned, 4.05 held; 1,080,000 at 0.25: 1.64 planned, 2.97 held).
`tile-plan-exact`: the cap search is unchanged (its rules were measured with those estimates), and what the plan
reports is computed for the chosen cap from the plan's own tiles (`tile_shape`: the widest domain, every tile's
rows, the tiles in flight, the wavefront's pool) and the call's own rules for slots, staging and layer 0. If what
the call must hold does not fit by these figures the cap steps down, or the plan refuses (13,720,000 atoms of
OMAT-0 medium were planned at 12.4 GiB of 11.8 allowed before). The slots' reserve also leaves room for the GEMM
timing's scratch, so a building call stays within the fraction. Plan / peak now, fractions 0.9 / 0.5 / 0.25:
OMAT-0 medium 135,000 atoms 1.017 / 1.017 / 1.024, 320,000 atoms 1.008 / 1.021 / 1.041, 1,080,000 atoms 1.011 /
1.015 / 1.049, 2,560,000 atoms 1.009 / 1.022 (0.9 / 0.5); OMAT-0 small 320,000 atoms 1.010 / 1.015, 1,080,000 atoms
1.011 / 1.012, 2,560,000 atoms 1.007 (0.9). The three plans of 64 to 216 tiles are the 4-5% ones: the plan counts every
ghost candidate as a kept row.

**Pinned host memory.** The host state's alias (the gradients of the layer outputs added into the outputs' rows) was
planned as four windows of a tile's rows. The call opens a window per block that another tile still reads, and in a
grid of tiles that is most of them: 27 of 27 at 1,080,000 atoms, 64 of 64 and 186 of 216 at 2,560,000. Planned
against pinned before: 4.52 against 5.58 GiB (1,080,000 atoms), 8.18 against 12.33 GiB (2,560,000). At 8,008,065
atoms the host-state plan of §6.34 (`tile-host-state-window`, "23.9 GB") comes to about 37 GiB of this machine's 39
by the corrected count (not measured), which may be why WSL became unstable in those runs. The plan now follows the call's window schedule
(`tile_shape`), and its cap search counts both arrays in full: planned / pinned 1.03 (1,080,000), 1.02 (2,560,000),
0.99 (5,000,000: 21.87 against 22.07 GiB). The host state may take two thirds of the available host memory by that
count (it was 60% of the low count, up to 96% in fact); a plan above that keeps the layer state on the device (the
wavefront), as 8,008,065 atoms of OMAT-0 medium now do.

**Capacity.** `docs/validation/capacity.md`: OMAT-0 medium runs 121,945 atoms whole (0.197 s a call, 1.61 us per
atom) and up to 10,985,000 atoms in tiles at fraction 0.9 (24.2 s, 2.20 us per atom, device peak 11.58 GiB, 8.2 GiB
pinned); 12,301,875 are refused. OMAT-0 small ran 20,480,000 atoms (24.5 s, 1.19 us per atom, 11.57 GiB, 15.2 GiB
pinned). From 1,080,000 to 10,985,000 atoms the kept call costs 2.00 to 2.20 us per atom (OMAT-0 medium).

Tests: `tests/gpu/test_memory_plan.py` asks the capacity plan's whole count within 4% of the measured system and
the tiled plan within 6% of the call's peak; the tests that find a plan's threshold by bisecting the fraction fix
the free memory the plan counts (`LOUP_DEBUG_PLAN_FREE`), since the true figure moves by MB with other programs.

All tiers on the library with these changes (sha256 `e021051e`): `tests/cpu` 490 passed, 5 skipped; `tests/gpu -m
fast` 359 passed, 7 skipped; `-m full` 48 passed; `-m acceptance` 15 passed, 1 skipped (422 passed, 8 skipped: the
NbCl5 structure). With the long-range models' buffers counted (library `8c82bc7e`, the release verification of
`docs/validation/release-0.0.1.md`): fast 360, full 48, acceptance 15 passed; the gate per label 37 passed (20
whole, 17 tiled); `loupmd bench` standard, the library of 97e365d against this one, a b b a twice: `NbCl5` 3x3x3
1.863 / 1.857 / 1.866 / 1.864 -> 1.724 / 1.726 / 1.728 / 1.729 ms/step (0.927), `SrTiO3` 10x10x10 8.069 / 8.096 /
8.118 / 8.128 -> 7.780 / 7.778 / 7.789 / 7.810 (0.961): what the merged kernels give the whole-system MD step.

### 6.36 The merge of develop (19 November 2026, PLAN.md O38)

`develop` `dec2e1f` (S115 to S146) was merged on the branch `merge/develop-s146` (`1d15783`; PLAN.md D92 for what
each side keeps, D93 and `00f6b75` for the two fixes the merged kernels needed on domains and tiles). Step times are
from the RTX 5060 Ti in WSL 2 only; the ledger's entry `rel-merge-develop` has every run.

**Tests.** RTX 5060 Ti (`sm_120`, library `7f976766de199e71`): `tests/cpu` 496 passed, 5 skipped (4 of them for
`LOUPMD_MODELS`, not set in that run); `tests/gpu` fast
385 passed and 7 skipped without the NbCl5 structure file, those 7 passed with `LOUPMD_BENCH_STRUCTURES` set; full
53 passed; acceptance 16 passed (the accuracy gates of ten model cases among them); the ten LAMMPS tests
(`tests/gpu/test_lammps.py`, in the fast tier's count) against an `lmp` rebuilt on this library. RTX 4000 Ada
(`sm_89`, `leto` and `leeloo`, library built there from `da43be7` with the toolchain on the network home and
libstdc++ linked in): `tests/cpu` 500 passed, 1 skipped, in 21 s on 24 workers; fast 350 passed, 41 skipped (no
`lmp`, no `dftd3` module there), 1 failed because the machine's `/usr/bin/nvcc` does not know `sm_89` (the
kernel-plugin test); full 52 passed, 1 skipped (a test for hosts with little memory); acceptance 14 passed, and the two MACE-OMOL-0 gates passed with the float64 reference on the CPU (`tools/dev/test_gate.py --ref-device cpu`; PyTorch MACE's reference does not fit the 20 GB card, which fails the tier's own two cases before LoupMD runs).

**Step times, RTX 5060 Ti** (a b b a, fresh GEMM plans per run, Langevin 300 K, median of six 256-step blocks):
merged against `develop`, a tie on all seven cases (0.989 to 1.003 in one round; OMAT-0 medium on 5,000 atoms
1.003, 1.001, 1.001, 0.998 and OFF23-M water 1.017, 1.003, 0.998, 1.011 over four rounds). Merged against the
branch before the merge: OMAT-0 medium `SrTiO3` 5,000 atoms 7.82 to 7.67 ms (0.980), MP-0 medium 1,080 atoms 1.76
to 0.67 ms (0.382), POLAR-1-S `NaCl` 216 atoms 1.30 to 1.12 ms (0.859), OMAT-0 small, OFF23-M water and MH-1
0.976 to 0.986.

**Not done.** Step times on the RTX 4000 Ada; the wheel with the merged sources (the wheel build's rule for
`src/jit.cu` is in the Makefile and compiles; the full build was not run); the export-version checks of D91 on the
merged code; NVRTC as a dependency of the wheel (D94).

### 6.37 LAMMPS's NVT and NPT at the engine's step time (19 November 2026, PLAN.md O40)

`run_style loupmd` now reads the input's fixes and runs the engine's integrator of that ensemble between LAMMPS's
output steps (stage L3 of `LAMMPS_SYMMETRIX_PARITY_PLAN.md`; PLAN.md D97 for the decisions; the ledger's entry
`lmp-run-style-fixes` has every run). All figures are from the RTX 5060 Ti in WSL 2, library `037b67e07ad2f5d2`.

**What is taken over.** `fix nve` (velocity Verlet); `fix nve` with `fix langevin`, `fix temp/csvr` or
`fix temp/berendsen` (and `fix press/berendsen`); `fix nvt` (Nose-Hoover chain); `fix npt ... iso`
(Martyna-Tobias-Klein); `fix setforce 0 0 0` and atoms outside the integrating fix's group (held atoms);
`fix momentum ... linear 1 1 1`. Any other fix that acts during the steps stops the run with its name.

**Step times** (MACE-OMAT-0 medium, rattled SrTiO3, 300 K, 1 fs, 2,000 steps after 200, thermo every 1,000, two
runs each with fresh GEMM plans; ms/step):

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

The run style is within 1% of the package's own loop in every row (0.996 to 1.012). LAMMPS integrating itself with
`pair_style loupmd` takes 1.04 to 1.27 times as long with `fix nvt` and 1.16 to 1.65 times with `fix npt`, where
every step moves the box and rebuilds the engine's list.

**Output inside a run.** At an output step LAMMPS takes the state back and the pair style evaluates. That evaluation
used to capture its own step graph over the integrator's, and the next block the integrator's again; it now runs
the force graph beside them. With that and with the pair style no longer sending an unchanged system at every
`run` command, Langevin on 320 atoms with output every 1,000 / 100 / 10 steps went from 0.600 / 0.617 / 0.920 to
0.580 / 0.594 / 0.734 ms per step, and the job's graph captures from 20 / 92 / 884 to 6 / 6 / 6. `fix nvt`: 0.648 /
0.660 / 0.866; `fix npt iso`: 0.765 / 0.785 / 1.010. An output step still costs two force passes.

**Tests.** Tests of `57bf988`. RTX 5060 Ti (`sm_120`, library `037b67e07ad2f5d2`): `tests/gpu/test_lammps_run_style.py` 31 passed and `tests/gpu/test_lammps.py` 10 passed against an `lmp` rebuilt on this library; `tests/gpu` fast 414 passed, 7 skipped for a wrong structure path in that run (they are in `tests/gpu/test_d3.py`, which passed whole, 53, with the right one); full 52 passed and 1 failed on a timing bound (`test_a_schedule_tracks_its_target_on_5000_atoms`: the ramp's step 3.5% above the hold's where 3% is allowed; four reruns, two on this library and two on the merge's, gave 0.1 to 1.0% and passed). RTX 4000 Ada (`sm_89`, library built on `leto` from `57bf988`): `tests/cpu` 500 passed, 1 skipped; fast 351 passed, 72 skipped (no `lmp` and no `dftd3` there), 2 failed, both the machine's: the kernel-plugin test (its `/usr/bin/nvcc` does not know `sm_89`) and the first device call after `loup_set_state`, whose child process crashed at `import torch` because that build exported its statically linked libstdc++ (linked again with those symbols hidden, `tests/gpu/test_device_io.py`, `test_engine.py` and `test_run_api.py`: 59 passed); full 52 passed, 1 skipped (`leeloo`).

**Not done.** the acceptance tier (no kernel and no arithmetic changed); LAMMPS on the RTX 4000 Ada and on native Linux; `fix npt aniso` / `tri` and fixes that only read the state every N steps (refused today); the wheel; a push (O37).

### 6.38 Systems too large for the card, and the first rebuild's timing (20 November 2026, PLAN.md O41)

The new version of the benchmark (`MargrafGroup/Benchmark_loup`: the package's own loop, `pair_style loupmd` and
LAMMPS with Symmetrix, 5k to 100k atoms of OMAT-0 medium, MH-1, OFF24 medium and POLAR-1-M) ran on the RTX 5060 Ti
in WSL 2 on 20 November and showed two things in the engine. RTX 5060 Ti only. (Corrected the same day: this section
first named OMAT-0 small and POLAR-1-S, which are not the benchmark's models.)

**A whole system too large for the card.** Under WSL 2 a `cudaMalloc` beyond the free memory succeeds: Windows'
video memory manager pages the allocations out to system memory and every kernel then runs at bus speed. MACE-MH-1
on 98,415 atoms, whole, filled the card and took minutes per step; on 50,820 atoms the model's rows took the last
14.3 GB and a later allocation failed after 34 s. The capacity plan does not see this, since a whole call
(`capacity="whole"`, the benchmark's first rung, and the LAMMPS pair style) and a long-range model are not planned.
The buffers that grow with the system are now allocated through `loup::device_malloc` (`src/model.hpp`, defined in
`src/engine.cu`), which refuses a request of 4 MiB or more that is larger than NVML's free figure, as a native
driver refuses it (CUDA's figure where NVML is missing: under WSL it falls 1.2 GiB too far above 10 GiB held, §6.35,
and would refuse requests that fit). With the library `42425b8a699e8a90`: MH-1 50,820 atoms, whole, out of memory
after about 4 s ("refused 297.8 MB with 230.2 MB free"); MH-1 98,415 atoms after 2.3 s ("refused 1345.5 MB with
148.2 MB free"); POLAR-1-M 51,840 atoms after 2.1 s; OMAT-0 medium on 98,415 atoms, whole, still runs (142.53 ms per
step). In the benchmark the LAMMPS cells of MH-1 and POLAR-1-M at 100k atoms and the own loop's POLAR-1-M at 50k now
end with out of memory, and the own loop's MH-1 at 98k goes on to the tiled call (8.17 to 8.27 µs/atom/step); a
15,400 MiB watchdog over every such run never fired. `LOUP_DEBUG_ALLOC_FREE=<MiB>` caps the free figure for the test
(`test_system_beyond_the_free_memory_refused_and_handle_takes_one_again`).

**The first rebuild's timing.** The benchmark's own loop times 20 steps after 5 from rest; on the water cells its
figure held a one-off cost of about 28 ms at 5k atoms and 0.5 s at 97k. That is the timing of the conv forward's
variants (`tune_rebuild_variants`, `sm_120` only), which waits for the first host-driven rebuild (the ledger's
`spl-multi-receiver`: timed on the set-up's lattice it picked wrongly for thermalised NbCl5) and which `step_ms`
leaves out (`LoupMDStats::tune_ms`): 31.5 ms on 5,184 atoms and 590.6 ms on 97,200. Every model of the benchmark
picks variant 2 (R5), 7 to 24% faster in the conv forward, so the timing pays for itself within about 50 to 100
steps. The SrTiO3 cells do not rebuild at all (none in 300 steps either) and run untuned. (Not, as first written
here, the LAMMPS pair style: `loup_evaluate`'s step goes through the same loop and times the variants at its first
rebuild; measured on water, §6.39.) The benchmark's warm-up and the timing of systems without a rebuild: §6.39.

**Tests** (library `42425b8a699e8a90`, RTX 5060 Ti): `tests/gpu/test_engine.py` and `test_memory_plan.py` 42
passed; `test_lammps.py` and `test_lammps_run_style.py` 41 passed against an `lmp` on this library; fast tier 419
passed, 7 skipped (the benchmark structures' folder unset; the skipping files again with it set and `LOUPMD_LMP`:
103 passed); full tier 53 passed. Not run: the acceptance tier (no kernel and no arithmetic changed), the RTX 4000
Ada, native Linux.

### 6.39 The benchmark's warm-up and systems without a rebuild (20 November 2026, PLAN.md O41)

The two follow-ups of §6.38 (the owner: "then do a and then after it b"), and a crash that the second one's tests
turned up. RTX 5060 Ti in WSL 2 only.

**(a) The benchmark's MD protocol.** In the local checkout of `Benchmark_loup` (879f4c0 plus local changes; not
pushed, the repository is the owner's), every code's MD now runs 100 warm-up and 200 measured steps up to the 1M
size, instead of 5 + 20 (`reproduce/bench.sh`: `MD_WARMUPS`, `MD_SAMPLES`; the ASE calls keep 5 + 20). From rest,
the first steps are not the steady state: LoupMD times its kernel variants at the first rebuild (§6.38), which the
warm-up now holds. `run_md.py` records `warmup_rebuilds`, so a one-off inside the measured block can be seen. The
benchmark was run again under this protocol (`~/loup_bench_runs/5060ti-20261120-v3`, library `42425b8a699e8a90`
for every LoupMD route).

**(b) Systems without a rebuild.** The conv forward's variants were timed only at a system's first MD rebuild, so a
system whose list is never rebuilt kept variant 0: a crystal near its lattice (the benchmark's SrTiO3 cells from
rest: no rebuild in 300 steps), short runs, and LAMMPS's pair style under `fix npt`. They are now timed also after
50 force passes without a timing (`tune_early_variants`, `kTuneEarlyPasses`); the first rebuild, if one comes, times
them again. Measured (NVE from rest, 100 + 200 steps, fresh process and plans per run, f g g f f g g f): OMAT-0
medium SrTiO3 5,000 atoms 7.288 to 7.131 ms per step (0.978), 10,140 atoms 14.870 to 14.547 (0.978); MH-1 5,000
29.413 to 29.169 (0.992); OFF24 medium water 5,184 a tie (0.999: it is timed at its first rebuild either way). The
timing costs 20 to 39 ms once (`tune_ms`). Ledger: `gen-conv-tune-early`. (§6.38's correction: `loup_evaluate`'s
step goes through the MD loop and was always timed at its first rebuild.)

**The fast tier's segmentation fault.** The fast tier crashed on the library of (b) with a segmentation fault. The
library before (b) (`42425b8a699e8a90`) crashed the same way, so (b) did not cause it. The cause: Python's garbage
collector can run an engine's `loup_destroy` in one of the package's output writer threads (`LoupEngine.__del__` of
an earlier test's engine) while the main thread's engine captures its graphs. A script that forces this
(`.tmp_o/destroy_race.py`: engine A destroyed in a worker thread after a random 0 to 80 ms while engine B, SrTiO3
320 atoms, runs 60 NVE steps) failed in every run. On `42425b8a699e8a90` and the library of (b) the first run's
capture was invalidated ("operation failed due to a previous error during capture") and the next `loup_create`
failed. With thread-local capture (below) the process crashed within the first 40 iterations in four runs out of
four. The SIGSEGV backtrace showed `loup_run_nve`'s error path in `cudaGraphDestroy`; other runs ended with glibc's
"double free or corruption" and "free(): invalid pointer".
Three faults made it:

1. *The trigger.* `cublasDestroy`, which cuBLAS documents as synchronising the device, invalidates every capture in
   progress on the device in any capture mode. With the destroy's parts left out one at a time, only leaving out
   the two cuBLAS handles' destruction made 40 of 40 iterations pass. Leaving out the cuBLAS destruction, everything,
   or serialising every entry point passed; leaving out only the GEMM cubin's unload, `free_system`, or the
   streams, events and workspaces did not. Thread-local capture mode, the first fix tried, was needed too:
   in global mode another thread's `cudaFree` invalidates the capture as well.
2. *A failed capture stayed open.* A `CUDA_CHECK` inside a capture returned -1 without ending it, and `guarded`
   closed captures only after an exception. The thread's next call failed with "operation not permitted when stream
   is capturing" (seen as `loup_create` failing after the failed run).
3. *A graph destroyed twice.* After an exception, `guarded` destroyed the graph that `cudaStreamEndCapture` returned.
   For a capture into a graph (the MD step graphs and their conditional bodies) that graph belongs to the handle or
   to a conditional node and was destroyed again later.

The fix (`src/engine.cu`):

- **Capture mode.** Every capture runs in thread-local mode (`kCaptureMode`).
- **`DeviceOrder`.** A process-wide shared lock. Every capture holds it shared from begin to end, so captures in
  several threads still run side by side. The calls that synchronise the device or use the legacy stream hold it
  exclusively: `loup_create` (the bundle's load), `loup_set_system`, `loup_destroy`, and the release of a tiled state.
- **`CaptureScope`.** It ends each capture on every path, and destroys the returned graph only when the capture
  made it.
- **`guarded`.** It closes a capture left open after a plain failure too, and never destroys the graph it gets back.

On the fixed library (`84d92d872ef41860`) the script ran 60 + 60 iterations (0 to 80 ms) and 40 (0 to 300 ms)
without a failed run. The new test `test_an_engine_destroyed_in_another_thread_leaves_a_run_alone`
(`tests/gpu/test_engine.py`) fails on `42425b8a699e8a90` and passes on the fixed library.

**Tests** (library `84d92d872ef41860`, RTX 5060 Ti): fast tier 381 passed, 48 skipped (the LAMMPS files without
`LOUPMD_LMP`, and the benchmark structures' folder unset), none failed. After the benchmark run: the full tier 53
passed, and the LAMMPS files (`test_lammps.py`, `test_lammps_run_style.py`, with the test build's `lmp` on this
library) 41 passed.

**Not covered.** Two engines driven at once from two threads on one GPU. Plain `cudaMemcpy` / `cudaMemset` (on the
legacy stream) remain in other entry points: 24 calls in `src/engine.cu`, some of them inside `set_system_impl`,
which holds the lock. One of them in one thread would invalidate a capture in the other. The package frees engines in
other threads but drives them from one.

### 6.40 The tiled mode in LAMMPS (20 November 2026, PLAN.md O42)

The owner: "Ok can we now work on the tiled mode in lammps? I want the same functionalities as in loupmd engine".
`LAMMPS_TILED_PLAN.md` stages LT0 to LT5; LT6 waits for the owner (below). RTX 5060 Ti in WSL 2 only; library
`4684594842169024` (§6.39's `84d92d872ef41860` plus LT0).

**What changed.**

- *Engine (LT0).* `loup_evaluate_tiled` is the tiled call under a public name (`include/loupmd.h`);
  `loup_debug_evaluate_tiled` stays as 0.0.1's name. The package's `evaluate_tiled` calls the new name when the
  library has it. Tiled MD's state arrays are allocated through `loup::device_malloc`, which refuses a request beyond
  NVML's free memory where WSL 2 would page the card out.
- *Pair style (LT1).* The keywords `capacity auto|whole|tiled|wavefront` (default `auto`), `receivers N` and
  `memory F` go to `loup_set_execution`. At each send of the system, any capacity but `whole` plans
  (`loup_plan_execution` on the unwrapped positions). A TILED plan makes every force call `loup_evaluate_tiled` with
  the plan's cap. After a box change the call keeps the cap; if it fails there, the pair style plans once more. The
  log has the plan's line at the first step, a warning after three steps in a row with a changed box, and a run-end
  line (tiled calls, tiled MD steps, list builds). Forced tiles with MACE-POLAR-1 and the wavefront with a model not
  of two layers are refused with the reason.
- *`loupmd/kk` (LT2).* In tiled mode it computes on LAMMPS's host arrays and syncs the forces back to the device
  at once. VerletKokkos marks the forces as modified in the pair style's execution space after `compute()`, and
  Kokkos aborts on a host copy marked modified ("Concurrent modification of host and device views in DualView
  atom:f"): the first test run's abort.
- *Run style (LT3).* On a tiled pair style it drives `loup_tiled_set_state`, `loup_tiled_run` and
  `loup_tiled_get_state` with the pair style's cap and skin. The atoms held by `fix setforce 0 0 0` become the tiled
  state's fixed atoms. The state is kept across runs on the pair style's serial and the held atoms. A barostat is
  refused.

**Tests.**

- `tests/gpu/test_lammps_tiled.py` (new; 2 fast, 18 full; `LOUPMD_LMP`): 20 passed.
  - Tiled against whole on 5,760 atoms, OMAT-0 medium in 12 tiles of 600, no hybrid GEMMs: dE at most 3.1e-9
    eV/atom, dF at most 3.2e-6 eV/Å, dP at most 1.4e-3 bar. This holds for the plain and `kk` styles and for the
    wavefront, host-list and host-state forms.
  - The run style's tiled MD against the engine's own tiled MD from Python (NVE, NVT, Langevin, Langevin at zero
    temperature, Berendsen) meets the bounds of the whole-mode tests.
  - Output every 10 steps and two `run` commands keep the trajectory, and build as many lists as the engine's own
    run (3 in 40 steps).
  - NVE drifts 0.0005 meV/atom/ps over 500 steps.
  - Sorting every step changes nothing: 7 list builds in 200 steps either way, which is LAMMPS's own 6 rebuilds
    under the same half-skin rule plus the first.
- `tests/gpu/test_tiled_md.py` gains two full tests:
  - an evaluation between two tiled-run blocks keeps the lists and the trajectory;
  - a passed cap survives a cell change, and 0 plans again.
- The other suites:

  | suite | result |
  |---|---|
  | LAMMPS whole files | 41 passed |
  | fast tier | 381 passed, 50 skipped |
  | full tier | 55 passed, 18 skipped (the LAMMPS files without `LOUPMD_LMP`) |
  | `tests/cpu` | 496 passed, 5 skipped |

The new file's first run had 7 failures. One was the `kk` abort. The other six were faults in the tests:

- a 1e-6 eV/Å bound between two processes' whole calls, against 1.1e-6 from the GEMM plan picks;
- list-build bounds that ignored the trajectory itself;
- a warning line inside a thermo block, which the parser now skips;
- a malformed `thermo_style` in the per-atom refusal case.

**Measurements.** All runs are 100 warm-up plus 200 measured NVE steps from rest, with fresh GEMM plans per run and
`capacity auto`. The cells are MH-1 on the benchmark's SrTiO3 structures. Figures are ms per step.

| atoms | tiles | own loop | pair style | run style | `loupmd/kk` |
|---:|---|---:|---:|---:|---:|
| 50,820 | 8 of at most 12,288 | 420.4 | 417.2, 417.8 | 424.5, 422.0 | 425.0 |
| 98,415 | 27 of at most 8,192 | 836.4 | 830.4 | 838.1 | 844.7 |

`loupmd/kk` ran with `-pk kokkos newton on neigh half`, since the input sets `newton on` and LAMMPS-Kokkos's default
full lists refuse it. The pair style and `loupmd/kk` are within 0.7% and 1.1% of the own loop; the run style is
within 0.7% in these runs, which hold two outputs per block.

- *Own loop.* `lm.Simulation`, as the benchmark's `run_md.py` runs it, on the same data files and library.
- *The benchmark's harness.* `local_run/lmp_loupmd.sh`, 3 trials, in `~/loup_bench_runs/5060ti-20261120-v3-lt`,
  where both cells ran out of memory whole this morning:

  | atoms | pair style | run style |
  |---:|---|---|
  | 50,820 | 8.21 µs/atom (417.2 ms) | 8.27 µs/atom (420.5 ms) |
  | 98,415 | 8.52 µs/atom (838.3 ms) | 8.67 µs/atom (853.4 ms; trials 8.56 to 8.69) |

- *OMAT-0 medium on 320,000 atoms* (8 tiles of 65,536; 10 + 40 steps): 537.2 ms per step under the run style, 512.9
  in the own loop.
- *Output steps.* The run style's extra over the pair style comes from the output steps. In tiled mode an output's
  evaluation is a full tiled call with the virial, since the engine's tiled MD forms no stress: 0.39 s on 50,820
  atoms. Thermo every 10 steps took 458.2 ms per step, against 423.3 every 200 (18 more outputs). A measured block
  of 200 steps holds two outputs (steps 200 and 300), which adds about 1%; the block of 40 at 320,000 atoms adds
  about 5%.
- *The probe.* `loup_plan_execution` took 26 to 122 ms (OMAT-0 medium and MH-1 at 5,000 and 53,240 atoms; the
  first call in a process is the slowest). `loup_set_system` with the first evaluation took 0.13 to 2.3 s.
  `capacity auto` costs the probe once per send of the system.
- *`fix npt` through the pair style, tiled* (10 + 30 steps, two runs each, alternating): 490.3 and 491.2 ms. The
  reference is `fix nve` with the virial in every step (`fix ave/time 1 1 1 c_thermo_press`): 427.0 and 420.8 ms.
  The difference is +67 ms, or 16%; every call builds the tile lists (30 in 30 steps). By the plan's rule (LT6 (a)
  only above about 10%), LT6 (a) qualifies. It waits for the owner.
- *NVML peaks.* About 1.05 GiB of the card is held by other programs. The peaks were 6.9 GiB at 50,820 atoms and 6.4
  GiB at 98,415; the plan counts 5.6 and 5.1 GB for the tiled state and workspace. OMAT-0 at 320,000 atoms peaked at
  10.8 GiB, against 9.5 GB in the plan.

**Not covered.** The `sm_89` workstations. A barostat in tiled MD (LT6 (a)). The whole-to-tiled fallback when a
list outgrows its buffers in a run (LT6 (b)). An output step without the extra tiled call: the last MD step of a
block would have to form the virial.

### 6.41 Barostats in tiled mode (20 November 2026, PLAN.md O42, D99)

The owner, after §6.40's 16%: "Start the barostat". `LAMMPS_TILED_PLAN.md` LT6 (a). RTX 5060 Ti in WSL 2 only;
library `ad99a7df36d5d9a6` (the test LAMMPS `~/loupmd_lammps` links it).

**What changed.**

- *Lists across a cell change (engine).* A tiled call in a cell other than its lists' build cell used to drop the
  tiled state and plan again. Now it keeps the lists by the variable-cell step's rule (`src/cell.cu`). With F = h0^-1
  h (row vectors), the lists stay while r_list (1 - |F - 1|_F) > r_max and every atom lies within (r_list (1 -
  |F - 1|_F) - r_max) / 2 of x0 F + t. Here t is the atoms' mean displacement, so LAMMPS's `fix npt`, which dilates
  about the box centre, counts no move. The build's reference stays fixed until the next build.
  `tile_place_rows_cell_kernel` places each tile's rows in the new cell from the kept offsets and the tile's origin.
  `receivers` 0 keeps the cap while the lists are kept. No new device memory but the barostat's 48 B virial, its cell
  block and a flag.
- *Barostats in tiled MD (engine).* `loup_tiled_run` takes `LOUP_BERENDSEN_NPT`, `LOUP_BAOAB_NPT` and
  `LOUP_MTK_NPT`, with the whole loop's kernels on a `CellDev` of the tiled state. Each step's tiled call carries the
  stress. The virial is kept across blocks (`virial_current`), and V0 is set per state (`loup_set_reference_volume`).
  The barostat's variables ride in the integrator state block, so a restart carries them. `loup_tiled_get_cell` is
  new. The validation is `loup_run`'s: no fixed atoms with a barostat, and BAOAB without `fix_com`.
- *A whole-mode fault found by the comparison.* MTK's barostat mass used `h->kinetic_dof()` before the call set
  `h->fix_com`. So the first call on an engine counted 3N degrees of freedom with `fixcm`, and later calls (or a
  graph capture after one) 3N - 3: W differed by 1 part in N. Tiled against whole, MTK differed by 4.4e-5 Å
  against the 1e-5 bound. It now uses the call's own count, 3 (N - fixed) - 3 with `fix_com`.
- *Python.* `TiledEngine` runs the three barostats on the device loop of a library with `loup_tiled_get_cell`,
  reads the cell from the device, and passes V0 on. The host loop (a dispersion term, `LOUP_TILED_HOST_MD=1`)
  refuses them by name, and so does `Simulation` when it starts.
- *LAMMPS.* The pair style's warning about rebuilds in every step is gone. `run_style loupmd` takes `fix npt ... iso`
  (MTK) and `fix press/berendsen` (Berendsen NPT) in tiled mode, and sets LAMMPS's box from `loup_tiled_get_cell`
  after each block.

**Tests.**

- `tests/gpu/test_tiled_md.py` (full tier):
  - A strained cell, 2,560 atoms of SrTiO3 at cap 1,000, with a shift and noise, keeps the lists. Against the
    whole call at the new cell: dilated ×1.003, dE 1.7e-8 eV/atom, dF 2.8e-6 eV/Å, dS 7.9e-10 eV/Å^3; sheared, dE
    3.5e-9, dF 3.6e-6, dS 1.6e-9. A ×1.05 strain builds again.
  - The cap after a cell change: ×1.002 with 0 keeps cap and lists; ×1.05 with the cap rebuilds at the cap; ×1.10
    with 0 plans again (65,536); the next call keeps.
  - The three barostats, tiled (5,000 atoms in 8 tiles of at most 2,000) against the whole loop, 20 steps at 2 GPa:
    MTK dx 7.0e-8 Å, dcell 1.5e-8 Å; BAOAB 9.6e-8, 7.3e-8; Berendsen 5.8e-8, 2.6e-8; dE at most 6.0e-8 eV/atom,
    with the cell moving 0.13 to 0.43 Å. BAOAB runs on atoms sorted by species, so that the tiled and whole runs
    draw the same noise per atom.
  - MTK in blocks against unbroken: dx 2.4e-7 Å, dcell 2.1e-7 Å; resumed from a restart: 1.0e-7, 3.8e-8. Force
    atomics differ between calls at about 1e-7, so the bounds are 1e-6.
  - The volume limit stops a tiled Berendsen run (`the cell diverged`).
- `tests/gpu/test_mtk_gpu.py`: 6 passed after the MTK fix (whole MTK against ASE: volume within 2.1e-9 relative).
- `tests/gpu/test_lammps_tiled.py`: 24 passed in 130 s.
  - `fix npt` through the tiled pair style builds tile lists 7 times in 200 steps, against LAMMPS's own 13 list
    builds (before: in every step).
  - The run style with `fix npt` and with `fix press/berendsen` against the engine's tiled run of the same
    ensemble: box within 1e-6.
  - Output every 10 of 40 steps builds as many lists as the engine's own run (3), for NPT and Berendsen NPT too.
- `tests/cpu/test_tiled_engine.py`: a fake device engine with barostats checks that the cell reaches thermo rows,
  atoms and restarts, and that the host loop refuses.
- The other suites:

  | suite | result |
  |---|---|
  | fast tier | 380 passed, 1 failed, 51 skipped |
  | full tier | 59 passed, 21 skipped (the LAMMPS files without `LOUPMD_LMP`) |
  | LAMMPS whole-cell files | 41 passed |
  | `tests/cpu` | not run: each workstation had another user's process on its GPU, and the suite does not run on this PC |

  The fast tier's failure is `test_memory_plan.py` at 20,480 atoms (whole mode, code this work does not touch). The
  drop in free memory read 1,963 MB against 2,073 MB predicted, while the engine's own count of the same system
  was 2,072.9. The file run again: 9 passed, and 40,000 atoms failed the other way (4,287 MB measured, 3,980
  predicted, own count 3,979.7). Under WSL 2 the free memory moves with what other programs hold. A native Linux
  workstation would settle it (the owner's suggestion); none was free.

**Measurements** (MH-1 on 50,820 atoms of SrTiO3, `capacity auto`, 8 tiles of at most 12,288; 10 warm-up + 30
measured steps from rest; fresh GEMM plans per run; two rounds). Figures are ms per step.

| run | round 1 | round 2 |
|---|---:|---:|
| LAMMPS `fix nve` with the virial in every step (`fix ave/time` on the pressure), pair style | 410.4 | 413.2 |
| LAMMPS `fix npt ... iso` through the pair style | 412.4 | 413.2 |
| `run_style loupmd` with `fix npt ... iso` (tiled MTK), thermo every 30 | 440.8 | 439.1 |
| own loop, NVE | 409.6 | 410.6 |
| own loop, MTK (iso, 0 GPa) | 410.6 | 412.3 |

- *`fix npt` through the pair style.* 491.2 and 490.3 ms in §6.40, 412.4 and 413.2 now: within 0.5% of the fixed
  cell with the virial. The measured 30 steps built no lists (the first call of the warm-up built them once);
  before, they built them in each of the 30. The fixed-cell reference reads 410-413 ms today against 421-427 in
  §6.40, so the comparison is within each round.
- *The package's MTK* costs 0.2% and 0.4% over NVE: the stress in every call. The cell grew from 605,240 to 622,633
  Å^3 (+2.9%) in the 40 steps from rest at 0 GPa.
- *The run style.* Its block of 30 steps holds two output steps (thermo 30: steps 30 and 40), each a tiled call
  with stress of about 0.4 s (§6.40). Taking two such calls of the own loop's step time out leaves 413.4 and 411.6
  ms per MD step (*estimate*, not measured on its own), the own loop's MTK time. A longer block shares the output
  steps out over more steps (§6.40: 423 against 420 ms in blocks of 200).

**Not covered.** The `sm_89` workstations. A barostat with a dispersion term in tiled mode (the host loop keeps the
cell fixed). LT6 (b). `fix npt` with `aniso` or `tri` under the run style, whole or tiled: the run style maps only
`iso`.
