# OMAT-0 Medium Speedup Research Brief

> **Historical.** The specialised path this brief describes was retired in S144 (19 November 2026, `JIT_DESIGN.md`
> stage 5). OMAT-0 medium now runs the generic path, which was 2.5-3% faster on the 5060 Ti
> (`OPTIMISATION_LEDGER.md`, `gen-retire-specialised`). Ideas below that name specialised kernels
> (`spline_forward_inter1`, `wprime_backward_inter1`, `tabled_outer_sum0_*`, `sc0_*`, `sc1_fused`) no longer apply.

Self-contained technical brief for searching for new speedup ideas on LoupMD's specialised **MACE-OMAT-0 medium**
path (`arch = omat0_medium_spec`). Snapshot: 13 November 2026. Companion files: `STATUS_AND_PROFILE.md` (sixth
update, 14:15) and `OPTIMISATION_LEDGER.md`.

---

## 1. Target, Acceptance Rules, and Constraints

- **Model:** `mace-omat-0-medium.model` — float32, `C = 128` channels, `l <= 3` SH (`16` components), correlation `3`,
  cutoff `r_max = 6.0` A, 2 interactions (`RealAgnosticDensityInteractionBlock` with `128x0e+128x1o` hidden irreps,
  `RealAgnosticDensityResidualInteractionBlock` with `128x0e` hidden irreps), 2 readouts (`readout[0]` linear,
  `readout[1]` `128 -> 16 -> 1` SiLU MLP), single head, ZBL pair repulsion (`p = 5`).
- **Standard benchmarks (`python/bench_md.py`):**
  - `NbCl5` 3x3x3 (`FastMACE/fastmace/protocols/data/NbCl5_R2SCAN.cif`, 1,944 atoms, `S = 2`, ~22 steps/rebuild).
  - `SrTiO3` 10x10x10 (cubic `a = 3.905` A, 5,000 atoms, `S = 3`, ~370k directed active edges, ~15 steps/rebuild).
  - Protocol: Langevin 300 K, `dt = 1.0` fs, `skin = 0.5` A, `friction = 0.01 / fs`, 100 warmup steps then median of
    6 x 256 steps.
- **Adoption bar (strict):**
  1. **Both GPUs, both build orders:** interleaved same-process A/B (`python/bench_md.py MODEL CIF - LOUP_LIB=./libloupmd_cand.so` -> runs `a b b a`, or `a b` and `b a` in separate invocations). Adopt only if it wins (or wins/ties cleanly) in **both** orders on **both** the RTX 5060 Ti and the RTX 4000 Ada. Keep candidate `.so` beside `libloupmd.so` (hybrid cubins are resolved relative to the `.so`). On the Ada, the first run in a sequence is systematically ~0.6% fast (biases order A against candidate).
  2. **Accuracy gate (`python/test_gate.py`):** 3x MACE float32-vs-float64 rule on `NaCl_2x2x2` (64 atoms), `SrTiO3_3x3x3` (135 atoms), `NbCl5_2x2x2` (576 atoms; tests `wprime_backward_inter1_rcv`), two rattled/strained configs each, plus the forced-variant matrix (`LOUP_SPLINE_VARIANT=R1|R1p|R4|R4p|R5`, `LOUP_WPRIME_THREADS=512`, `LOUP_WPRIME_RCV=1` on small cells, `LOUP_REORDER=0|1`):
     `dE <= max(3 * dE32, 0.01 meV/atom)`, `dF <= max(3 * dF32, 1e-5 eV/A)`, `dS <= max(3 * dS32, 1e-7 eV/A^3)`.
  3. **Test suite:** `pytest tests/` must pass (note `tests/test_export.py`, `tests/test_engine.py`, `tests/test_families.py`, `tests/test_gate_wrapper.py`).
  4. **Precision rules (never break):** no FP16, BF16, FP8, or 1xTF32 anywhere on the force path. Generality beyond `SrTiO3` and one GPU is required.
  5. **GEMM plan cache caution:** `~/.cache/loupmd/plans_<gpu>_sm<cc>_lt<ver>_hyb<0|1>_<lib_fnv_hash>.bin` keys by the library binary's FNV-1a hash (`library_build_hash()`). Still pass `LOUP_RETUNE=1` when testing changes that affect GEMM timings or when testing on a new machine state.
  6. **Documentation rule:** update `STATUS_AND_PROFILE.md` and `OPTIMISATION_LEDGER.md` together with any adopted or rejected experiment.

---

## 2. Hardware, Toolchain, and Exact Commands

| GPU | Arch | Specs / Notes |
|---|---|---|
| **RTX 5060 Ti** (local WSL2) | `sm_120` | 36 SMs, 32 MB L2, CUDA 13, 16 GB VRAM. Desktop shares GPU (higher noise: ~0.4-1.1%). `ncu` works. |
| **RTX 4000 Ada** (`ssh leeloo`) | `sm_89` | 48 SMs, 48 MB L2, 20 GB VRAM. **No `nvcc`** on `leeloo`. **No performance-counter permission** (`ERR_NVGPUCTRPERM` — `nsys` works, `ncu` does not). |

### Local (5060 Ti, WSL2 from `D:/Margraf/LoupMD`)
- Python (tests, gate, bench): `/home/fzwin/environments/mace_cueq_latest/bin/python`
- Python (kernel generator if needed): `/home/fzwin/environments/mace_cueq_oeq/bin/python`
- Models: `/home/fzwin/models/mace-omat-0-medium.model`
- Structures: `/mnt/d/Margraf/FastMACE/fastmace/protocols/data/NbCl5_R2SCAN.cif`
- Build: `make -j4 CUDA_ARCH=sm_120` (writes `build/sm_120/*.o` and `./libloupmd.so`).
- Regenerate specialised kernels:
  `python/gen_kernels.py /home/fzwin/models/mace-omat-0-medium.model src/generated_kernels.cuh` (also writes `src/generated_kernels_signature.h`).
  **Important current state:** `python/gen_kernels.py` line 516 currently has `DECODE_BIAS_FOLD = os.environ.get("LOUP_GEN_DECODE_FOLD", "1") != "0"`, whereas `src/generated_kernels.cuh` on disk currently has the unfolded `hb0` subtraction form (0 matches for `nw_hb`). Regenerating with defaults will switch that unless `LOUP_GEN_DECODE_FOLD=0` is set; check/gate if regenerating!
- Gate: `python/test_gate.py /home/fzwin/models/mace-omat-0-medium.model`
- Tests: `python -m pytest -x -q tests/test_engine.py tests/test_export.py`
- A/B bench: `python/bench_md.py /home/fzwin/models/mace-omat-0-medium.model /mnt/d/Margraf/FastMACE/fastmace/protocols/data/NbCl5_R2SCAN.cif - LOUP_LIB=./libloupmd_cand.so`
- Profile (`nsys`): `nsys profile -o /tmp/p --force-overwrite true -t cuda --cuda-graph-trace=node ...` (or `--capture-range=cudaProfilerApi`).
- Profile (`ncu`): works locally for single kernels or ranges.

### Remote (`leeloo`, Ada `sm_89`)
- Cross-compile objects locally: `make -j4 CUDA_ARCH=sm_89 objects` -> `build/sm_89/*.o`
- Remote workdir: `/mnt/homes/zwingel/loupmd_work` (note: do **not** use `strtol` in library code; must link against older glibc).
- Sync `.o` to `/tmp/loup_sm89/` and sources to workdir, then link on `leeloo`:
  ```bash
  E=/mnt/homes/zwingel/environments/mace_cueq_oeq
  CU13LIB=$E/lib/python3.10/site-packages/nvidia/cu13/lib
  g++ -shared /tmp/loup_sm89/*.o -L$CU13LIB -l:libcublas.so.13 -l:libcublasLt.so.13 -l:libcudart.so.13 -ldl -o libloupmd.so
  ```
- Models on `leeloo`: `/mnt/homes/zwingel/ResearchModule/Models/mace-omat-0-medium.model`
- `NbCl5` CIF on `leeloo`: `/mnt/homes/zwingel/FastMACE/fastmace/protocols/data/NbCl5_R2SCAN.cif`
- Note: `python/loupmd.py` preloads `nvidia/cu13/lib` automatically if `libcuda`/`libcublas` aren't on `LD_LIBRARY_PATH`.

---

## 3. Current Baseline & Where Every Microsecond Goes

### 3.1 MD Step Times (`bench_md.py`, ms/step)
- **5060 Ti (`sm_120`):**
  - Fifth-update baseline: `NbCl5` **1.849 ms**, `SrTiO3` **8.458 ms** (after review round 5 M1: 1.836 / 8.454 ms).
  - Round 6 (S1 pipeline switch tightened, `STATUS_AND_PROFILE.md` §3.2): `NbCl5` **1.81 ms**, `SrTiO3` **8.33 ms** (5060 Ti only; Ada not yet re-run after round 6).
- **Ada (`sm_89`):** `NbCl5` **2.056 ms**, `SrTiO3` **9.262 ms** (fifth-update build with round-5 M1).
- **Size scaling (5060 Ti, `SrTiO3` n^3, us/atom-step):** 135 atoms `3.00` (0.405 ms/step), 320 `2.18`, 1,080 `1.73`, 5,000 `1.66-1.68`, 20,480 `1.69-1.71`, 40,000 `1.71-1.72`.
- **NVE drift (`SrTiO3` 10^3, 1 ps @ 300 K, 1 fs):** `-0.00011` (5060 Ti), `-0.00012` (Ada) meV/atom/ps.

### 3.2 Stage Spans (steady-state non-rebuild step, us, `nsys --cuda-graph-trace=node`)
Span = wall-clock GPU time of the stage (forked GEMMs overlap on side streams). Profiled build (fifth update): 8.232 ms vs 8.458 ms unprofiled on 5060 Ti `SrTiO3`.

| Stage | 5060 Ti `SrTiO3` | 5060 Ti `NbCl5` | Ada `SrTiO3` | Ada `NbCl5` |
|---|---:|---:|---:|---:|
| `i0_fwd` (`tabled_outer_sum0_forward_kernel`) | 259.0 | 43.0 | 312.4 | 58.6 |
| `compose0_fwd` GEMMs | 299.7 | 88.8 | 351.7 | 88.7 |
| `sc0_forward` | 105.1 | 24.4 | 156.3 | 29.6 |
| `skip16` + `W_up` GEMMs | 66.5 | 28.7 | 66.0 | 27.2 |
| `spline_forward_inter1` (R5 / R1p / R5 / R4p) | **1,927.5** | **314.5** | **2,382.3** | **442.7** |
| `lin1` forward GEMMs | 468.6 | 200.6 | 562.9 | 193.4 |
| `sc1_fused` | 222.4 | 58.0 | 232.7 | 68.3 |
| `lin1` backward GEMMs | 549.7 | 175.7 | 557.8 | 196.7 |
| `wprime_backward_inter1_rcv` | **2,961.0** | **443.3** | **3,168.1** | **510.9** |
| `W_up^T` + skip backward GEMMs | 72.0 | 36.9 | 74.2 | 35.7 |
| `sc0_backward` | 230.9 | 63.0 | 273.8 | 84.8 |
| `compose0_bwd` GEMMs | 368.4 | 87.9 | 337.1 | 88.3 |
| `i0_bwd` (+ fused force/virial assembly) | 523.9 | 109.7 | 645.8 | 135.6 |
| Integrator, active-edge compaction, memset, gaps | 126.2 | 45.1 | 140.8 | 60.4 |
| **Step span** | **8,232.0** | **1,723.6** | **9,267.6** | **2,025.5** |
| GEMM groups (sum of spans) | 1,825.0 (22.2%) | 618.6 (35.9%) | 1,949.7 (21.0%) | 630.0 (31.1%) |

GPU idle inside a step: ~20 us (5060 Ti `SrTiO3`).

### 3.3 Top Kernels (us, kernel sum incl. side streams)

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

### 3.4 Neighbour Rebuild (cadence: ~1/15 steps `SrTiO3`, ~1/22 `NbCl5`)
Medians per rebuild (us):
- `fill_neighbors_kernel`: 5060 Ti `SrTiO3` 287 / `NbCl5` 163; Ada 401 / 186.
- `count_neighbors_kernel`: 5060 Ti 150 / 116; Ada 209 / 150.
- `gather_sorted_edges_kernel`: 5060 Ti 36 / 7; Ada 46 / 9.
- Total rebuild ~510 us (5060 Ti), ~684 us (Ada); amortised ~30-45 us/step.

### 3.5 Kernel Resource Usage (`cuobjdump -res-usage`; smem on `sm_120` includes 1 KB driver reserve)

| Kernel | `sm_120` Reg / Stack / Smem | `sm_89` Reg / Stack / Smem |
|---|---|---|
| `wprime_backward_inter1_rcv` (`512, 2`; launched 256 or 512) | 64 / 8 / 23,552 B (4 B spill outside channel loop) | 64 / 0 / 22,528 B |
| `wprime_backward_inter1` (`256, 4`; N < 512 fallback) | 64 / 0 / 24,388 B | 64 / 0 / 23,364 B |
| `spline_forward_inter1<1, paired / unpaired>` (`128`) | 96 / 79 regs, 3,584 B | 122 / 72 regs, 2,560 B |
| `spline_forward_inter1<4, paired / unpaired>` (`512`) | 123 / 94 regs, 11,264 B | 126 / 93 regs, 10,240 B |
| `spline_forward_inter1<5, unpaired>` (`640`) | 96 / 0 / 13,824 B | 95 / 0 / 12,800 B |
| `sgemm128_kernel` (`256, 2`, +48 KB dynamic) | 128 / 0 / 1,024 B | 128 / 0 / 0 B |
| `tabled_outer_sum0_forward_kernel` (`128`) | 96 / 0 / 9,216 B | 80 / 0 / 8,192 B |
| `tabled_outer_sum0_backward_kernel` (`128`) | 80 / 0 / 11,456 B | 80 / 8 / 10,432 B |
| `sc1_fused` (`128, 4`) | 113 / 0 / 2,128 B | 104 / 0 / 1,104 B |
| `sc0_forward` (`128`) / `sc0_backward` (`128, 4`) | 72 / 0 / 1,056 B; 128 / 0 / 1,040 B | 72 / 0 / 32 B; 128 / 32 / 16 B |

### 3.6 Nsight Compute Hardware Bottlenecks (`SrTiO3` 5k, 5060 Ti)
- **`wprime_backward_inter1_rcv`** (3.01 ms, 63% occupancy): **issue-bound** (`issue slots 80% busy`, `not_selected` dominant), 760 M instructions (was 818 M before items 27-28), L2 traffic 5.3 GB, L1 hit ~6-10.5%.
- **`spline_forward_inter1`** (`R1`: 2.04 ms, 41% occ, 96 regs): **L2-bound** (L2 83%, issue 71%, L2 traffic 3.92 GB, L1 hit 5%). `R4`: 33% occ, L1 hit 36%, L2 traffic 2.66 GB, 1.96 ms on `SrTiO3` (+7-10% on `NbCl5`).
- **`tabled_outer_sum0_backward_kernel`** (0.56 ms, 37% occ): L1 requests/edge ~11 (SH staged, `float2` pairs).
- **`tabled_outer_sum0_forward_kernel`** (0.25 ms, 39% occ): L1 hit 53% at 64 KB L1 carveout (vs 33% at 100 KB, 305 us).
- **`scatter_active_edges_kernel`** (0.05 ms, 80% occ): no SH output.

---

## 4. End-to-End Architecture & Exact Data Flow of OMAT-0 Medium

### 4.1 Code Map
- `python/export_omat0.py` (`EXPORTER_VERSION=4`): exports model weights + certified splines/tables to `.loup` (`LOUPC001` container).
- `python/gen_kernels.py` -> `src/generated_kernels.cuh` + `src/generated_kernels_signature.h`: generates `sc0_forward`, `sc0_backward`, `sc1_fused`, `spline_forward_inter1<R, PAIR>`, `wprime_backward_inter1`, `wprime_backward_inter1_rcv`.
- `src/model.hpp`, `src/model_loader.cu`: uploads tables/weights, builds `d_cubic_packed8_1` on host from `spline_table_1`.
- `src/interaction0.cu`: `tabled_outer_sum0_forward_kernel`, `tabled_outer_sum0_backward_kernel` (incl. SH pullback, ZBL, force/virial assembly).
- `src/neighbors.cu`: cell-list build, `count_neighbors`, `fill_neighbors`, `gather_sorted_edges`, `atom_order_keys`, `compute_and_count_active`, `scatter_active_edges`, `check_skin`.
- `src/integrator.cu`: `nve_{first,second}_half`, `langevin_{first,second}_half`, `kinetic_energy`.
- `src/sgemm.cu`: `loup::sgemm128` (128x128x16 and 128x64x16 `cp.async` SIMT SGEMM) + `transpose`.
- `src/engine.cu`: `LoupHandle`, `sgemm_rm` autotune + plan cache, `HybCubin` loader (`cubins/tf32x3_hyb_sm{80,90,120}.cubin`), `tune_l1`, `tune_rebuild_variants`, `rebuild_neighbors`, `record_force_pass`, adaptive MD loop.

### 4.2 Atom Ordering & Edge Contracts
- In `loup_set_system`: atoms are grouped contiguously by species `0..S-1` (`species_start[s]`, `species_count[s]`), mapped via `perm[dev_idx] -> orig_idx`.
- When `N * 4096 > l2_bytes` (above ~8k atoms on 5060 Ti, ~12k on Ada — so **not** active for `NbCl5` 1,944 or `SrTiO3` 5,000), every 16th rebuild Morton-sorts atoms within each species group (`atom_order_keys_kernel`).
- At rebuild (`rebuild_neighbors`):
  - Edges within `r_max + skin` are found in float32 pre-test + float64 fallback (`count_neighbors` + `fill_neighbors`).
  - `DeviceSegmentedSort::StableSortPairs` sorts each receiver's edge slice `[row_ptr[i], row_ptr[i+1])` by 32-bit key `(sym_pair << 19) | (__float_as_uint(r) >> 12)`.
  - **Contract:** for fixed receiver `i`, `sym_pair(sp_j, sp_i, S)` increases monotonically with sender species `sp_j`! Wait: check `sym_pair(a, b, S) = min*S - min*(min-1)/2 + (max - min)`: for fixed `sp_i`, as `sp_j` increases from `0..S-1`, for `sp_j <= sp_i`, `min=sp_j, max=sp_i`, `sym_pair` increases by `S - sp_j - 1 >= 0`; for `sp_j >= sp_i`, `min=sp_i, max=sp_j`, `sym_pair` increases by 1! So every receiver's row is grouped by ascending sender species, and within each sender species sorted by ascending `r`. Guarded by `check_row_species_order_kernel`.
  - `gather_sorted_edges` precomputes Cartesian float64 shifts `d_shift_cart[e, 3] = shift @ cell`, removing cell dependency from the force graph.
  - `E_graph` buckets `E_skin` upward to multiples of `8192` (re-captured only on overflow or >32,768 shrink).

### 4.3 Algebraic Folds Already Baked into OMAT-0 Medium
1. `node_embedding` + `inter[0].linear_up` + `conv0_tp_weights` (last FC layer) + `inter[0].skip_tp` + `inter[0].linear` are folded into **four matrices** `d_C0[l]` of shape `[S, S*64, 128]` (`l = 0..3`). Thus interaction 0 needs only the 66-column radial chain table `d_coef0` (`[P_sym, pieces0, 6, 66]`, Chebyshev deg 5, cols `0..63` + col `65` for `D0`) and its power-basis sibling `d_pcoef0` for backward.
2. `products[0].linear` (0e) is folded forward into `w_ro0 [128]` (with `scale_shift.scale`) AND into `W_up_0 [128, 128]`, `W_up_1 [128, 128]`, and `W_skip1_raw` (`W_skip1_16`). `ScaleShift.shift` is folded into `atomic_energies`.
3. `products[1].linear` + `readout[1].linear_1` + `scale` are folded into `W_p1_ro1 [128, 16]` and `W_skip1_16 [S, 128, 16]`; `readout[1].linear_2 * act_cst * scale` -> `W_ro1_2 [16]`.
4. `products[0]` and `products[1]` symmetric contractions use FastMACE's factored SSA DAGs (`w0_factored [S, 29, 128]`, `w1_factored [S, 13, 128]`).

### 4.4 Force Graph Sequence & Exact Shapes (`record_force_pass`, `compute_stress = 0` in MD)
Buffer aliasing active (`set_system_impl`): `d_dm1_* -> d_m1_*`, `d_dh0_* -> d_h0_*`, `d_dS0_* -> d_S0_*` (and `d_zero_slab` zero-fills only `[off_dx0, end)` = `dx0`, `dx1`, `energy_f64`, `forces_f64`, `virial_grad_f64` because `S0`, `D0` are completely overwritten by `i0_fwd`).

1. **Active edge compaction:**
   - `compute_and_count_active_kernel<<<(N+3)/4, 128>>>`: 1 warp/atom; computes `float4(fx, fy, fz, r)` from `d_pos64` + `d_shift_cart`, writes `d_tmp_vec_len`, counts `r < r_max` into `d_act_deg`.
   - `cub::DeviceScan::ExclusiveSum` -> `d_act_row_ptr[N+1]`, `d_E_act = d_act_row_ptr + N`.
   - `scatter_active_edges_kernel<<<(N+3)/4, 128>>>`: compacts `act_senders`, `act_receivers`, `act_pairs`, `act_vec_len`, computes `locate_spline(grid1, r)` -> `act_slab = p * total_intervals + iv` and `act_t_sx = (t, +-inv_h)`. No SH stored.
2. **Interaction 0 forward:**
   - `tabled_outer_sum0_forward_kernel<<<(N+3)/4, 128>>>`: 1 warp/receiver, 2 channels/lane. Stages 32 edges, computes `edge_sh16`, evaluates 6-term Clenshaw Chebyshev over `d_coef0`, accumulates `16` SH sums per sender species in registers, flushes `S0_l` (`[N * (2l+1), S*64]`, zeroing absent species) + `D0[N]`.
   - `compose0_fwd` (`gemm_fork` over `S * 4` lanes): for each species `s` (`ns = species_count[s]`) and `l in 0..3` (`d = 2l+1`):
     `S0_l[ns*d, S*64] @ C0_l[S*64, 128] -> m0_l[ns*d, 128]` (`beta=0`).
     At `SrTiO3` (`S=3, K0=192`): `ns=1000,1000,3000`, `M = ns*d = 1000..21000`, `N=128`, `K=192`.
3. **Product 0 + Readout 0 forward:**
   - `sc0_forward<<<N, 128>>>`: divides `m0_l` by `D0[a]+1`, runs 29-segment factored SSA (`w0_factored`), writes `h0_0[N,128]`, `h0_1[N*3,128]`, adds `y0 * w_ro0` to `d_energy_f64`.
4. **Interaction 1 prep GEMMs (`gemm_fork`):**
   - `skip16_fwd` (per species `s`): `h0_0[ns, 128] @ W_skip1_16[128, 16] -> sc_skip16[ns, 16]` (lane `2 + (s&1)`).
   - `W_up_0` (lane 0): `h0_0[N, 128] @ W_up_0[128, 128] -> x0[N, 128]`.
   - `W_up_1` (lane 1): `h0_1[N*3, 128] @ W_up_1[128, 128] -> x1[N*3, 128]`.
5. **Interaction 1 spline forward (HOTSPOT #2: ~23-26% of step):**
6. **`lin1` forward GEMMs (`gemm_fork`, 4 lanes):**
   - `l=0`: `[N, 256] @ [256, 128] -> b0[N, 128]`
   - `l=1`: `[N*3, 384] @ [384, 128] -> b1[N*3, 128]`
   - `l=2`: `[N*5, 384] @ [384, 128] -> b2[N*5, 128]`
   - `l=3`: `[N*7, 256] @ [256, 128] -> b3[N*7, 128]`
7. **Product 1 + Readout 1 forward+backward:**
   - `sc1_fused<<<N, 128>>>`: reads `b0..b3`, divides by `D1[a]+1`, runs 13-segment factored SSA -> `y1[N, 128]`, evaluates `128 -> 16 -> 1` readout MLP (with `sc_skip16`), adds energy, immediately differentiates `1 -> 16 -> 128` (`d_hidden16[N, 16]` saved for skip16 bwd) and `sc1` backward -> writes `db0..db3` (`16 * 128` floats/atom) and `dD1[N]`.
8. **`lin1` backward GEMMs (`gemm_fork`, 4 lanes, `transB = true`):**
   - `l=0..3`: `db_l[N*(2l+1), 128] @ W_lin1_l^T[128, K_l] -> dm1_l[N*(2l+1), K_l]` (aliased onto `m1_l`, `K_l = 256, 384, 384, 256`).
9. **Interaction 1 `w'` backward (HOTSPOT #1: ~34-36% of step):**
   - `wprime_backward_inter1_rcv<<<N, 256 or 512>>>` (for `N >= 512`, variant 256/512 timed at first rebuild):
     - Stages receiver's `q = M * dm1` (40 slots x 128 channels = `5120` floats, padded stride `44` -> `s_q[128 * 44]` = 22 KB smem, 1 barrier) once per block.
     - Block warps stride over receiver's active edges `eb..ee`. For each edge:
       - Loads `act_vec_len`, `act_senders[e]`, `act_slab[e]`, `act_t_sx[e]`.
       - Loops `channel = lane; channel < 128; channel += 32` (4 passes/edge):
         - Reads `x0[snd]`, `x1[snd]` (3 comps) via `__ldg`.
         - Reads 10 `uint2` entries from `d_cubic_packed8_1` (`[P_sym*intervals1, 1280]`: `20/19/12/8` signed quantised around `s = t-0.5` + 5-bit shared exp), unpacks `d0..d3` (4-6 ALU ops per path in current `.cuh`, or folded with `DECODE_BIAS_FOLD=1`), evaluates `w` and `2^8 * dw/dt`, pulls back Cartesian tensors for the 10 paths (`scalar`, `raise`, `lower`), accumulates `dx0_acc`, `dx1_{x,y,z}_acc` -> `atomicAdd` into `dx0[snd]`, `dx1[snd]`, accumulates `pull_Gx/y/z`, `pull_R`.
       - Warp-reduces `pull_Gx/y/z, pull_R`; lane 0 evaluates `density_table_1` derivative, projects `pull_G` perpendicular to `n`, writes `edge_force_1[e, 3]`.
10. **Interaction 1 backward GEMMs (`gemm_fork`):**
    - Lane 0: `dx0[N, 128] @ W_up_0^T[128, 128] -> dh0_0` (`beta=0`), then per-species `hidden16[ns, 16] @ W_skip1_16^T[16, 128] -> dh0_0` (`beta=1`).
    - Lane 1: `dx1[N*3, 128] @ W_up_1^T[128, 128] -> dh0_1` (`beta=0`).
11. **Product 0 + Readout 0 backward:**
    - `sc0_backward<<<N, 128>>>`: reads `m0_0..3`, `D0`, `dh0_0/1` (+ `w_ro0`), writes `dm0_0..3`, `dD0`.
12. **`compose0_bwd` GEMMs (`gemm_fork` over `S * 4` lanes):**
    - `dm0_l[ns*d, 128] @ C0_l^T[128, S*64] -> dS0_l[ns*d, S*64]` (aliased onto `S0_l`).
13. **Interaction 0 backward + force/virial assembly:**
    - `tabled_outer_sum0_backward_kernel<<<ceil(E/128), 128>>>`: 4 warps x 32 edges/warp, 2 channels/lane. Stages SH in `s_edge[4][32][20]`, walks edges, loads `dS0_l[rcv, snd_sp]` on group change, evaluates 6-term power-basis Horner for value + derivative on `d_pcoef0`, reduces `dsh0` via 16-shuffle fold into `s_edge` and `dr0` via warp reduce, then all 32 lanes assemble 32 edges in parallel: SH Cartesian pullback + ZBL (`p=5` fast path) + `edge_force_1[e]`, `atomicAdd` `double` into `d_forces_f64` (and `d_virial_grad_f64` when `compute_stress`).

### 4.5 `sgemm_rm` Autotuning & Backends (`src/engine.cu`)
- Candidates timed per `(M, N, K, transB, beta!=0)` during the uncaptured warmup pass (`lt_cache.empty()`):
  1. Up to 32 `cublasLtMatmul` heuristics (`REDUCTION_SCHEME_NONE`, no split-K).
  2. 3 hybrid `tf32x3` cubin tiles (`64x64`, `32x64`, `64x32`) when `alpha == 1 && beta == 0 && K%4==0 && N%4==0 && aligned16(A,B,C)`.
  3. `loup::sgemm128` (`128x128x16`, or `128x64x16` when `N%128!=0 && N%64==0`) when `alpha == 1 && K%16==0 && N%4==0 && aligned16(A,B,C)`. Uses pre-transposed `[K, N]` copy of `B` (`weight_kn`) when `transB`.
- **Cold-L2 rule:** if `M * K * 4 > l2_bytes / 2`, timed with a `2 * l2_bytes` memset flush before every launch (`cold = true`); otherwise timed hot (5 launches/round).
- Note for `SrTiO3` (`N=5000`, `l2_bytes = 32 MiB` = 33.6 MB on 5060 Ti, `48 MiB` = 50.3 MB on Ada):
  - `lin1_fwd` `l=1,2,3`: `M*K*4` = `15000*384*4 = 23.0 MB` (22.0 MiB), `25000*384*4 = 38.4 MB` (36.6 MiB),
    `35000*256*4 = 35.8 MB` (34.2 MiB) -> on 5060 Ti (`L2/2 = 16 MiB`) all three are timed cold; on Ada (`L2/2 = 24 MiB`),
    `l=1` (22.0 MiB) is timed **hot** even though `m1_0..3` together total 97 MB and stream from DRAM.
  - `compose0_fwd` (`O`, `ns=3000`, `K=192`): `l=3` `21000*192*4 = 16.1 MB` (15.4 MiB) -> timed hot on both GPUs.
- **Per-product winner persistence:** only persisted to disk if `best_ms < 0.97 * second_ms`.

---

## 5. Already Tried & Closed (Do NOT Repeat Blindly)

Summary of `OPTIMISATION_LEDGER.md` (96 entries; 31 adopted, ~35 rejected/superseded):
- **Splitting interaction 1 across streams or L2 receiver chunks:** two receiver halves on 2 streams (+0.7-0.9%), L2 chunks 650-1700 atoms (+0.2% to +2.8%). Launch/tail costs beat DRAM savings while `lin1` GEMMs are separate launches.
- **Register-raising tweaks inside 64-reg `w'`:** paired edges in `w'` (spills, 3.23 -> 3.28/3.35 ms), `x0` hoisting (spills at 64, slower at `(256,3)`/80 regs), T1 2-channel vectorised `w'` (+2.3% Ada), `(256, 3)` launch bounds (tie), 2/4-pass channel staging (3.40/3.80 ms).
- **Cache-placement schedules for `w'` / spline:** SM-local `%smid` persistent `w'` (40 B stack, 3.01 -> 3.24 ms), `L1::no_allocate` table loads (3.02 -> 3.12 ms — warps DO reuse table rows through L1), reversed block order (tie), strided receiver remap (tie), 16-edge spline tiles (tie), paired R5 spline (spills), lockstep R2/4 spline (slower than named barriers), `(128, 7)` spline on `sm_89` (spills, +17%/+3%), 4-byte far-edge table rows T2 (slower on both GPUs).
- **More `sgemm128` tile shapes / split-K / grouped / group policy:** 4-stage BK=8, reg-staged BK=8, 1 blk/SM, `64x128` / `128x64` for `N=128` (faster in cold microbench, slower +0.5-1.8% in MD pass), row-chunked hybrid (never picked), grouped species GEMM T4 (+1.7%/+0.8%), pre-transposed fwd weights (tie / +1.0%), split-K own SGEMM (slower at 135 atoms), grouped small-product own-SGEMM launch (faster at 135 atoms, +0.2-1.2% on benchmarks), per-group own-SGEMM policy tuned in context (-0.4-0.8% `NbCl5`, tie `SrTiO3`/Ada, not worth machinery), global cold-L2 autotune (+2.9% Ada), serialised GEMM groups (+2-5.7%), split-K cuBLASLt (-120 us idle when removed).
- **Interaction 0 & SC micro-tweaks:** i0 bwd receiver-owned T7 (+1.1-1.8%), i0 bwd prefetch/early-load/4-sums (551 -> 564-626 us), `sc0` per-species overlapped with `compose0` (+19/+47 us gaps), per-atom energy array T6 (+0.1-0.5%), single-pass decoupled look-back edge compaction (80 vs 96 us kernel, MD tie), Morton reorder below L2.

---

## 6. High-Leverage Directions Still Open for Research

Three buckets account for **83% of the step** (`SrTiO3` 5060 Ti: 6,842 of 8,232 us; Ada: 7,500 of 9,268 us):
`w'` (~35%), `spline` (~24%), and GEMMs (~22%). Everything else combined is ~18%.

1. **Structural break in `w'` (`wprime_backward_inter1_rcv`, 3,009 / 3,188 us):**
   - `w'` is **issue-bound at 63% occupancy** (760 M instructions, 80% issue busy, `not_selected` stalls). Micro-tweaks inside the 64-reg loop are exhausted; note `DECODE_BIAS_FOLD` in `gen_kernels.py` exists (50 instructions/edge-chunk saved: 4 FADD + 1 LOP3 per path) while `src/generated_kernels.cuh` on disk currently has the unfolded `hb0` form — check/A-B that first.
   - Check why `w'` gets 63% occupancy (`__launch_bounds__(512, 2)` at 64 regs = 1024 threads/SM = 32 of 48 warps = 66.7% max; 256 threads x 4 blocks/SM on 5060 Ti, 23.5 KB smem/block fits 4 blocks inside 100 KB) and why Ada (`48 SMs`, `3,188 us`) is slower than 5060 Ti (`36 SMs`, `3,009 us`) despite 33% more SMs: inspect `ncu` active warps, barrier/tail imbalance across receivers, and L2/DRAM traffic (`x0`/`x1` gathers + `atomicAdd`s).
   - Note `FastMACE` uses `TABLE_W` + `TABLE_PAIRS` on H200/A100 (`results/wprime-h200-20261111/`), whereas LoupMD uses the 8-byte `cubic_packed8_1` table (and has no padding edges because active edges are compacted).
2. **`spline_forward_inter1` (2,008 / 2,381 us, L2-bound 83%):**
   - Table size is `P_sym * intervals1 * 1280 * 8 B` (`P_sym = 6` for `SrTiO3`); edges scatter across intervals along `r`. Consecutive receivers share slabs in a crystal, which is why `R=4/5` cut L2 traffic 3.92 -> 2.66 GB (L1 hit 5% -> 36%).
   - **Block/receiver ordering for L2/L1 slab locality:** At `N = 5,000` Morton reorder is off (`N * 4096 < L2`). Inside `O` (`3,000` atoms), `SrTiO3` has 3 distinct oxygen sublattices `(0.5,0.5,0)`, `(0.5,0,0.5)`, `(0,0.5,0.5)`, so consecutive `O` atoms in caller order include different sublattices, and `Sr`/`Ti`/`O` sit in separate species ranges. Grouping blocks by species or sublattice/spatial order (cf. FastMACE's `BLOCK_ORDER`) could increase L1/L2 slab hits.
   - **Register count (`96` regs in `R1`, `94-123` in `R4`)** and why `R=5` unpaired won on `SrTiO3` (96 regs, 640 threads = 20 warps/block): check if `R=6` or `R=8` unpaired fits if `n_acc = 16` + `she[16]` register pressure is trimmed.
3. **Fuse `lin1` into `spline` / `w'` (Open #1, 469 + 550 = 1,019 us on 5060 Ti `SrTiO3`; 1,121 us on Ada):**
   - Currently `spline_forward_inter1` writes `m1_0..3` (`N x 4864` floats = 97 MB at `N=5000`), then 4 `lin1` GEMMs read all 97 MB back; reverse writes 97 MB `dm1_0..3` and `w'` reads it back.
   - Inside the 128-thread/receiver spline block this failed because reading 655 KB of `W_lin1` per block adds 3.3 GB L2 traffic and needs `38*R` accumulators.
   - **Alternative decomposition:** receiver-tiled tensor-core GEMM (`mma` / `wmma`) consuming spline/w' tiles across 64 or 128 receivers, so `W_lin1` (`[256/384, 128]`) is read once per 64-128-receiver tile (~50-80 MB total across 5,000 atoms instead of 3.3 GB) and `m1`/`dm1` stay out of DRAM.
4. **GEMM selection (`1,825 us` span on 5060 Ti, `1,950 us` on Ada):**
   - On 5060 Ti, `own sgemm128` dominates (`1,507 us` vs `705 us` `fm_tf32x3` + `385 us` cuBLAS); on Ada `fm_tf32x3` dominates (`1,929 us` vs `538 us` cuBLAS + `226 us` `own`).
   - Run `LOUP_DEBUG_GEMM=1` on both GPUs to see exact `(M, N, K)` choices, and check whether the `L2/2` cold-L2 rule misclassifies `lin1_fwd l=1` (`22.0 MiB < 24 MiB` on Ada) or `lin1_bwd` (`db_l` is smaller than `m1_l`). Also check whether 3xTF32 with larger `mma` tiles beats `sgemm128` on 5060 Ti (`hyb` only has `64x64`, `32x64`, `64x32`).
5. **Interaction 0 (`272 + 537 = 809 us` 5060 Ti; `314 + 649 = 963 us` Ada) and `sc0`/`sc1` (`574 us` 5060 Ti, `670 us` Ada):**
   - In `tabled_outer_sum0_backward_kernel`, every active edge does 3 `double atomicAdd`s for `rcv` and 3 for `snd` into `forces_f64` (`interaction0.cu:421-426`). Because active edges are sorted by receiver, a 32-edge warp touches only 1-2 receivers (~75 edges/atom on `SrTiO3`), so warp-aggregating the `rcv` force before `atomicAdd` cuts `forces_f64` atomic traffic roughly in half (check `ncu` atomic stall counters first).
   - Also note `tabled_outer_sum0_backward_kernel` handles channels `0..63` across 32 lanes (2/lane), col `64` unused, col `65` (`D0`) in `lane == 0`; `sc0_backward` uses `128` regs (32 B stack frame on `sm_89`) and `sc1_fused` uses `113` regs.
6. **Rebuild / active-edge compaction / MD loop / `tune_l1` (`~130 us/step` + ~35 us amortised rebuild):**
   - `compute_and_count_active` (47 us) + `ExclusiveSum` + `scatter_active_edges` (54 us) = ~101 us/step (`compute_and_count_active` writes `tmp_vec_len`, `scatter` reads it back).
   - Open review item `S2`: `d_max_step_disp2` never decays, so one fast step keeps light-atom systems unpipelined until `set_state`.
   - `tune_l1` carveouts were measured before items 23-31; re-checking `w'` and `i0_bwd` carveouts is cheap.

---

## 7. Quick Checklist for the Research Agent's First Turn

1. Read `STATUS_AND_PROFILE.md` and `OPTIMISATION_LEDGER.md` to confirm baseline and avoid closed directions.
2. Run `LOUP_DEBUG_GEMM=1 LOUP_DEBUG_SPLINE=1` on `SrTiO3` and `NbCl5` (5060 Ti + Ada) to see every chosen GEMM plan and spline/`w'` timing right now.
3. Run `ncu` on `wprime_backward_inter1_rcv`, `spline_forward_inter1`, and `tabled_outer_sum0_backward_kernel` on 5060 Ti to get exact stall reasons, L1/L2 hit rates, DRAM bytes, and atomic/issue counters for the current build.
4. Before any code edit, state the exact bottleneck, expected ceiling, and falsifier; test any candidate via `python/test_gate.py` + `pytest` + `bench_md.py` A/B in both orders on both GPUs.
