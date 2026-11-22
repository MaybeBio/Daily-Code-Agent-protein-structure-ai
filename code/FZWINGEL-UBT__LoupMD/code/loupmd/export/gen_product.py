"""The product kernels' CUDA source (JIT_DESIGN.md stage 3): one factored symmetric contraction (FastMACE's
sc_factored program) as gprod_fwd / bwd / fwdc / bwdc and, for lmax_out 0, the fused readouts gprod_ro1(s|c)_fused.

codegen/gen_generic.py compiles the products of the build's models into the library; loupmd/export/generic.py stores
the same source in each bundle, so a model outside that set is compiled at load by NVRTC (src/generic.cu). Importing
this module changes no environment variables (gen_generic.py hides the GPU; the exporter must not).
"""
from __future__ import annotations


def _ptr_args(prefix, ls, const=True):
    q = "const float* __restrict__" if const else "float* __restrict__"
    return ", ".join(f"{q} {prefix}{l}" for l in ls)


# ----------------------------------------------------------------------------------------------- products
def _ssa(lines, i, op):
    from loupmd.export._fastmace import sc_factored

    sc_factored._emit_node(lines, i, op)


def emit_product(sig, prog, feats, sh):
    from loupmd.export._fastmace import sc_factored

    _expr, _literal = sc_factored._expr, sc_factored._literal

    seg_in, seg_w, seg_out, _ = sh
    assert seg_in == 16, seg_in
    lo = int(round(seg_out ** 0.5)) - 1
    assert (lo + 1) ** 2 == seg_out
    roots = [u for f in feats for u in (f or {}).values() if u is not None]
    used = prog.used(roots)
    head = [
        "  const int a = blockIdx.x, c = blockIdx.y * blockDim.x + threadIdx.x;",
        "  const float s = D ? 1.0f / (D[a] + 1.0f) : 1.0f;",
        "  const float* wr = w + (int64_t)sp[a] * w_stride + c;",
    ]
    loads = []
    for l in range(4):
        for m in range(2 * l + 1):
            loads.append(f"  const float x{l * l + m} = __ldg(m{l} + ((int64_t)a * {2 * l + 1} + {m}) * C + c) * s;")
    args_in = "int N, int C, " + _ptr_args("m", range(4)) + \
        ", const float* __restrict__ D, const float* __restrict__ w, int64_t w_stride, const int* __restrict__ sp"
    # S100: ro_w / energy (nullable): a folded linear readout of y0 (S73's energy target), E += sum_a y0[a] . ro_w in
    # double, one atomic per block; the backward adds its gradient seed (gseed = ro_w) to g0 at load, so no kernel
    # writes the seed into the upstream gradient buffer.
    F = [f'extern "C" __global__ void __launch_bounds__(128) gprod_fwd_{sig}(',
         f"    {args_in}, {_ptr_args('y', range(lo + 1), const=False)},",
         "    const float* __restrict__ ro_w, double* __restrict__ energy) {"] + head + loads
    for i in used:
        _ssa(F, i, prog.nodes[i])
    F.append("  float " + ", ".join(f"o{cc} = 0.0f" for cc in range(seg_out)) + ";")
    for b, f in enumerate(feats):
        items = [(cc, u) for cc, u in sorted((f or {}).items()) if u is not None]
        if items:
            F.append(f"  {{ const float wb = __ldg(wr + {b} * C);")
            F += [f"    o{cc} = fmaf(wb, {_expr(u)}, o{cc});" for cc, u in items]
            F.append("  }")
    for l in range(lo + 1):
        for m in range(2 * l + 1):
            F.append(f"  y{l}[((int64_t)a * {2 * l + 1} + {m}) * C + c] = o{l * l + m};")
    F += ["  if (ro_w) {",
          "    double e = (double)o0 * (double)__ldg(ro_w + c);",
          "    #pragma unroll",
          "    for (int off = 16; off > 0; off >>= 1) e += __shfl_xor_sync(0xffffffffu, e, off);",
          "    __shared__ double s_e[4];",
          "    if ((threadIdx.x & 31) == 0) s_e[threadIdx.x >> 5] = e;",
          "    __syncthreads();",
          "    if (threadIdx.x == 0) {",
          "      double t = 0.0;",
          "      for (int i = 0; i < (int)(blockDim.x >> 5); ++i) t += s_e[i];",
          "      atomicAdd(energy, t);",
          "    }",
          "  }",
          "}"]

    B = [f'extern "C" __global__ void __launch_bounds__(128) gprod_bwd_{sig}(',
         f"    {args_in}, {_ptr_args('gin', range(lo + 1))},",
         f"    {_ptr_args('dm', range(4), const=False)}, float* __restrict__ dD, const float* __restrict__ gseed) {{"] + \
        head + loads
    for l in range(lo + 1):
        for m in range(2 * l + 1):
            seed = " + (gseed ? __ldg(gseed + c) : 0.0f)" if l == 0 else ""
            B.append(f"  const float g{l * l + m} = __ldg(gin{l} + ((int64_t)a * {2 * l + 1} + {m}) * C + c){seed};")
    for i in used:
        _ssa(B, i, prog.nodes[i])
    adj = {}

    def add(u, ab):
        name = f"d{_expr(u)}"
        a_, b_ = ab
        if u in adj:
            B.append(f"  {name} = fmaf({a_}, {b_}, {name});")
        else:
            B.append(f"  float {name} = {a_} * {b_};")
        adj[u] = name

    for b, f in enumerate(feats):
        items = [(cc, u) for cc, u in sorted((f or {}).items()) if u is not None]
        if not items:
            continue
        B.append(f"  const float w{b} = __ldg(wr + {b} * C);")
        for cc, u in items:
            add(u, (f"w{b}", f"g{cc}"))
    for i in reversed(used):
        if i not in adj:
            continue
        op, da = prog.nodes[i], adj[i]
        if op[0] == "mul":
            add(op[1], (da, _expr(op[2])))
            add(op[2], (da, _expr(op[1])))
        elif op[0] == "lin":
            for cc, u in op[1]:
                add(u, (_literal(cc), da))
        else:
            for a_, b_ in op[1]:
                add(a_, (da, _expr(b_)))
                add(b_, (da, _expr(a_)))
    B.append("  float dot = 0.0f;")
    for l in range(4):
        for m in range(2 * l + 1):
            i = l * l + m
            dx = adj.get(-1 - i, "0.0f")
            B.append(f"  dot = fmaf({dx}, x{i}, dot);")
            B.append(f"  dm{l}[((int64_t)a * {2 * l + 1} + {m}) * C + c] = {dx} * s;")
    B += ["  if (dD) {",
          "    #pragma unroll",
          "    for (int off = 16; off > 0; off >>= 1) dot += __shfl_xor_sync(0xffffffffu, dot, off);",
          "    if ((threadIdx.x & 31) == 0) atomicAdd(dD + a, -s * dot);",
          "  }",
          "}"]
    # S130 / S132: compact channels (GenericLayer::lin_compact): the angular thread at compact position c reads degree
    # l >= 1 at its column pos[(l - 1) n_ang + c] of that degree's compact projection (-1: the channel's projection
    # column is exactly zero there, so is the input), degree 0 at position c; the feature weights w{b} at position c;
    # the adjoint seeded with g{cc}. Scalar-only positions run the S127 program (x1..x15 = 0 propagated).
    ops_s, used_s, feats_s = _scalar_prune(prog, feats)
    full_ops = dict(enumerate(prog.nodes))

    def cload_lines(w0):  # the widths are wl1..wl3, not w1..w3: the program's feature weights are w{b}
        out = ["    const int p1 = pos[c], p2 = pos[n_ang + c], p3 = pos[2 * n_ang + c];",
               f"    const float x0 = __ldg(m0 + (int64_t)a * {w0} + c) * s;"]
        for l in range(1, 4):
            for m in range(2 * l + 1):
                out.append(f"    const float x{l * l + m} = p{l} >= 0 ? "
                           f"__ldg(m{l} + ((int64_t)a * {2 * l + 1} + {m}) * wl{l} + p{l}) * s : 0.0f;")
        return out

    def wloads(dst, fs):
        for b, f in enumerate(fs):
            if any(u is not None for u in (f or {}).values()):
                dst.append(f"    const float w{b} = __ldg(wr + {b} * C);")

    def adjoint(dst, ops, ids, fs):
        adj = {}

        def add(u, ab):
            name = f"d{_expr(u)}"
            if u in adj:
                dst.append(f"    {name} = fmaf({ab[0]}, {ab[1]}, {name});")
            else:
                dst.append(f"    float {name} = {ab[0]} * {ab[1]};")
            adj[u] = name

        for b, f in enumerate(fs):
            for cc, u in sorted((f or {}).items()):
                if u is not None:
                    add(u, (f"w{b}", f"g{cc}"))
        for i in reversed(ids):
            if i not in adj:
                continue
            op, da = ops[i], adj[i]
            if op[0] == "mul":
                add(op[1], (da, _expr(op[2])))
                add(op[2], (da, _expr(op[1])))
            elif op[0] == "lin":
                for cc, u in op[1]:
                    add(u, (_literal(cc), da))
            else:
                for a_, b_ in op[1]:
                    add(a_, (da, _expr(b_)))
                    add(b_, (da, _expr(a_)))
        return adj

    # S132: the forward / backward products on compact channels of a non-terminal layer. The thread at compact position
    # c (angular first, then scalar-only, then the dead channels: no live input or no product weight) runs the full
    # program, the S127 program or nothing, and writes the outputs of channel oc = order[c] (zero for a dead one) in
    # the dense layout, so every consumer keeps its weights; the feature weights come permuted (position c's row). The
    # backward reads the dense output gradient of oc and writes the compact input gradient at the angular thread's
    # columns (degree l >= 1) and position c (degree 0); the pad columns stay zero from allocation.
    args_c = ("int N, int C, int kept, int n_ang, int wl0, int wl1, int wl2, int wl3, const int* __restrict__ order, "
              "const int* __restrict__ pos, " + _ptr_args("m", range(4)) +
              ", const float* __restrict__ D, const float* __restrict__ w, int64_t w_stride, const int* __restrict__ sp")
    head_c = [
        "  const int a = blockIdx.x, c = blockIdx.y * blockDim.x + threadIdx.x, oc = order[c];",
        "  const float s = D ? 1.0f / (D[a] + 1.0f) : 1.0f;",
        "  const float* wr = w + (int64_t)sp[a] * w_stride + c;",
    ]
    FC = [f'extern "C" __global__ void __launch_bounds__(128) gprod_fwdc_{sig}(',
          f"    {args_c}, {_ptr_args('y', range(lo + 1), const=False)},",
          "    const float* __restrict__ ro_w, double* __restrict__ energy) {"] + head_c
    FC.append("  float " + ", ".join(f"o{cc} = 0.0f" for cc in range(seg_out)) + ";")
    FC += ["  if (c < n_ang) {"] + cload_lines("wl0")
    for i in used:
        _ssa(FC, i, prog.nodes[i])
    wloads(FC, feats)
    for b, f in enumerate(feats):
        FC += [f"    o{cc} = fmaf(w{b}, {_expr(u)}, o{cc});" for cc, u in sorted((f or {}).items()) if u is not None]
    FC += ["  } else if (c < kept) {", "    const float x0 = __ldg(m0 + (int64_t)a * wl0 + c) * s;"]
    for i in used_s:
        _ssa(FC, i, ops_s[i])
    wloads(FC, feats_s)
    for b, f in enumerate(feats_s):
        FC += [f"    o{cc} = fmaf(w{b}, {_expr(u)}, o{cc});" for cc, u in sorted(f.items())]
    FC.append("  }")
    for l in range(lo + 1):
        for m in range(2 * l + 1):
            FC.append(f"  y{l}[((int64_t)a * {2 * l + 1} + {m}) * C + oc] = o{l * l + m};")
    FC += ["  if (ro_w) {",
           "    double e = (double)o0 * (double)__ldg(ro_w + oc);",
           "    #pragma unroll",
           "    for (int off = 16; off > 0; off >>= 1) e += __shfl_xor_sync(0xffffffffu, e, off);",
           "    __shared__ double s_e[4];",
           "    if ((threadIdx.x & 31) == 0) s_e[threadIdx.x >> 5] = e;",
           "    __syncthreads();",
           "    if (threadIdx.x == 0) {",
           "      double t = 0.0;",
           "      for (int i = 0; i < (int)(blockDim.x >> 5); ++i) t += s_e[i];",
           "      atomicAdd(energy, t);",
           "    }",
           "  }",
           "}"]
    BC = [f'extern "C" __global__ void __launch_bounds__(128) gprod_bwdc_{sig}(',
          f"    {args_c}, {_ptr_args('gin', range(lo + 1))},",
          f"    {_ptr_args('dm', range(4), const=False)}, float* __restrict__ dD, const float* __restrict__ gseed) {{"] + \
        head_c
    for l in range(lo + 1):
        for m in range(2 * l + 1):
            seed = " + (gseed ? __ldg(gseed + oc) : 0.0f)" if l == 0 else ""
            BC.append(f"  const float g{l * l + m} = __ldg(gin{l} + ((int64_t)a * {2 * l + 1} + {m}) * C + oc){seed};")
    BC += ["  float dot = 0.0f;", "  if (c < n_ang) {"] + cload_lines("wl0")
    for i in used:
        _ssa(BC, i, prog.nodes[i])
    wloads(BC, feats)
    adj_b = adjoint(BC, full_ops, used, feats)
    for l in range(4):
        for m in range(2 * l + 1):
            i = l * l + m
            dx = adj_b.get(-1 - i, "0.0f")
            BC.append(f"    dot = fmaf({dx}, x{i}, dot);")
            BC.append(f"    dm0[(int64_t)a * wl0 + c] = {dx} * s;" if l == 0 else
                      f"    if (p{l} >= 0) dm{l}[((int64_t)a * {2 * l + 1} + {m}) * wl{l} + p{l}] = {dx} * s;")
    BC += ["  } else if (c < kept) {", "    const float x0 = __ldg(m0 + (int64_t)a * wl0 + c) * s;"]
    for i in used_s:
        _ssa(BC, i, ops_s[i])
    wloads(BC, feats_s)
    dx0_b = adjoint(BC, ops_s, used_s, feats_s).get(-1, "0.0f")
    BC += [f"    dm0[(int64_t)a * wl0 + c] = {dx0_b} * s;", f"    dot = {dx0_b} * x0;",
           "  } else if (c < wl0) {", "    dm0[(int64_t)a * wl0 + c] = 0.0f;", "  }"]
    BC += ["  if (dD) {",
           "    #pragma unroll",
           "    for (int off = 16; off > 0; off >>= 1) dot += __shfl_xor_sync(0xffffffffu, dot, off);",
           "    if ((threadIdx.x & 31) == 0) atomicAdd(dD + a, -s * dot);",
           "  }",
           "}"]
    compact_src = "\n".join(FC) + "\n\n" + "\n".join(BC) + "\n"
    if lo == 0:
        # Fused product fwd + linear/bias/silu/linear readout fwd&bwd (ro_H = 16) + product bwd, one block per atom
        # (blockDim = C, 32..512, multiple of 32; generic.cu uses it only for C <= 512): generalises sc1_fused across
        # all model families.
        RF = [
            "template <int MAX_B, int MIN_BLK>",
            f"__global__ void __launch_bounds__(MAX_B, MIN_BLK) gprod_ro1_fused_{sig}(",
            f"    {args_in}, const float* __restrict__ sc_skip16, const float* __restrict__ ro_W1,",
            "    const float* __restrict__ ro_b1, const float* __restrict__ ro_W2, float ro_act_c,",
            "    float* __restrict__ d_hidden16, double* __restrict__ out_energy,",
            f"    {_ptr_args('dm', range(4), const=False)}, float* __restrict__ dD) {{",
            "  const int a = blockIdx.x, c = threadIdx.x;",
            "  if (a >= N) return;",
            "  const float s = D ? 1.0f / (D[a] + 1.0f) : 1.0f;",
            "  const float* wr = w + (int64_t)sp[a] * w_stride + c;",
        ] + loads
        for i in used:
            _ssa(RF, i, prog.nodes[i])
        RF.append("  float y0 = 0.0f;")
        for b, f in enumerate(feats):
            items = [(cc, u) for cc, u in sorted((f or {}).items()) if u is not None]
            if items:
                RF.append(f"  const float w{b} = __ldg(wr + {b} * C);")
                for cc, u in items:
                    assert cc == 0
                    RF.append(f"  y0 = fmaf(w{b}, {_expr(u)}, y0);")
        ro_block = [
            "  __shared__ float s_y[512];",
            "  __shared__ float s_part[32][16];",
            "  __shared__ float s_dh[16];",
            "  s_y[c] = y0;",
            "  __syncthreads();",
            "  {",
            "    const int k = c & 15, c0 = (c >> 4) * 16;",
            "    float p = 0.0f;",
            "    #pragma unroll",
            "    for (int q = 0; q < 16; ++q) p = fmaf(s_y[c0 + q], __ldg(ro_W1 + (c0 + q) * 16 + k), p);",
            "    s_part[c >> 4][k] = p;",
            "  }",
            "  __syncthreads();",
            "  if (c < 16) {",
            "    float hsum = (sc_skip16 ? __ldg(sc_skip16 + (int64_t)a * 16 + c) : 0.0f) + __ldg(ro_b1 + c);",
            "    const int n_chunks = C >> 4;",
            "    for (int j = 0; j < n_chunks; ++j) hsum += s_part[j][c];",
            "    const float sig = 1.0f / (1.0f + expf(-hsum));",
            "    const float w2 = __ldg(ro_W2 + c) * ro_act_c;",
            "    double e = (double)(hsum * sig) * (double)w2;",
            "    const float dh = sig * (1.0f + hsum * (1.0f - sig)) * w2;",
            "    s_dh[c] = dh;",
            "    d_hidden16[(int64_t)a * 16 + c] = dh;",
            "    #pragma unroll",
            "    for (int off = 8; off > 0; off >>= 1) e += __shfl_xor_sync(0x0000ffffu, e, off);",
            "    if (c == 0) atomicAdd(out_energy, e);",
            "  }",
            "  __syncthreads();",
            "  float g0 = 0.0f;",
            "  #pragma unroll",
            "  for (int k = 0; k < 16; ++k) g0 = fmaf(s_dh[k], __ldg(ro_W1 + c * 16 + k), g0);",
        ]
        RF += ro_block
        # Backward SSA reusing x0..x15, v_i, and w{b} already in registers
        adj_rf = {}
        def add_rf(u, ab):
            name = f"d{_expr(u)}"
            a_, b_ = ab
            if u in adj_rf:
                RF.append(f"  {name} = fmaf({a_}, {b_}, {name});")
            else:
                RF.append(f"  float {name} = {a_} * {b_};")
            adj_rf[u] = name
        for b, f in enumerate(feats):
            items = [(cc, u) for cc, u in sorted((f or {}).items()) if u is not None]
            for cc, u in items:
                add_rf(u, (f"w{b}", f"g{cc}"))
        for i in reversed(used):
            if i not in adj_rf:
                continue
            op, da = prog.nodes[i], adj_rf[i]
            if op[0] == "mul":
                add_rf(op[1], (da, _expr(op[2])))
                add_rf(op[2], (da, _expr(op[1])))
            elif op[0] == "lin":
                for cc, u in op[1]:
                    add_rf(u, (_literal(cc), da))
            else:
                for a_, b_ in op[1]:
                    add_rf(a_, (da, _expr(b_)))
                    add_rf(b_, (da, _expr(a_)))
        RF.append("  float dot = 0.0f;")
        for l in range(4):
            for m in range(2 * l + 1):
                i = l * l + m
                dx = adj_rf.get(-1 - i, "0.0f")
                RF.append(f"  dot = fmaf({dx}, x{i}, dot);")
                RF.append(f"  dm{l}[((int64_t)a * {2 * l + 1} + {m}) * C + c] = {dx} * s;")
        RF += [
            "  if (dD) {",
            "    #pragma unroll",
            "    for (int off = 16; off > 0; off >>= 1) dot += __shfl_xor_sync(0xffffffffu, dot, off);",
            "    __shared__ float red[16];",
            "    if ((c & 31) == 0) red[c >> 5] = dot;",
            "    __syncthreads();",
            "    if (c == 0) {",
            "      float total = 0.0f;",
            "      const int nw = C >> 5;",
            "      for (int w_i = 0; w_i < nw; ++w_i) total += red[w_i];",
            "      atomicAdd(dD + a, -s * total);",
            "    }",
            "  }",
            "}",
        ]
        # S127: the same fused kernel for a layer whose message has only its scalar part (S125's pruned layers:
        # lin_1..3 exactly zero): the program with x1..x15 = 0 propagated (dead mul / lin / dot terms and feature
        # terms dropped; the kept sums keep their order, so y0 and dm0 are the full kernel's values up to the sign of
        # zero), m0 the only input and dm0 the only gradient written (the pruned layer reads no other).
        RS = [
            "template <int MAX_B, int MIN_BLK>",
            f"__global__ void __launch_bounds__(MAX_B, MIN_BLK) gprod_ro1s_fused_{sig}(",
            f"    {args_in}, const float* __restrict__ sc_skip16, const float* __restrict__ ro_W1,",
            "    const float* __restrict__ ro_b1, const float* __restrict__ ro_W2, float ro_act_c,",
            "    float* __restrict__ d_hidden16, double* __restrict__ out_energy,",
            f"    {_ptr_args('dm', range(4), const=False)}, float* __restrict__ dD) {{",
            "  const int a = blockIdx.x, c = threadIdx.x;",
            "  if (a >= N) return;",
            "  const float s = D ? 1.0f / (D[a] + 1.0f) : 1.0f;",
            "  const float* wr = w + (int64_t)sp[a] * w_stride + c;",
            "  const float x0 = __ldg(m0 + (int64_t)a * C + c) * s;",
        ]
        for i in used_s:
            _ssa(RS, i, ops_s[i])
        RS.append("  float y0 = 0.0f;")
        for b, f in enumerate(feats_s):
            if f:
                RS.append(f"  const float w{b} = __ldg(wr + {b} * C);")
                RS += [f"  y0 = fmaf(w{b}, {_expr(u)}, y0);" for _, u in sorted(f.items())]
        RS += ro_block
        adj_s = {}
        def add_s(u, ab):
            name = f"d{_expr(u)}"
            if u in adj_s:
                RS.append(f"  {name} = fmaf({ab[0]}, {ab[1]}, {name});")
            else:
                RS.append(f"  float {name} = {ab[0]} * {ab[1]};")
            adj_s[u] = name
        for b, f in enumerate(feats_s):
            for cc, u in sorted(f.items()):
                add_s(u, (f"w{b}", f"g{cc}"))
        for i in reversed(used_s):
            if i not in adj_s:
                continue
            op, da = ops_s[i], adj_s[i]
            if op[0] == "mul":
                add_s(op[1], (da, _expr(op[2])))
                add_s(op[2], (da, _expr(op[1])))
            elif op[0] == "lin":
                for cc, u in op[1]:
                    add_s(u, (_literal(cc), da))
            else:
                for a_, b_ in op[1]:
                    add_s(a_, (da, _expr(b_)))
                    add_s(b_, (da, _expr(a_)))
        dx0 = adj_s.get(-1, "0.0f")
        RS += [
            f"  dm0[(int64_t)a * C + c] = {dx0} * s;",
            "  if (dD) {",
            f"    float dot = {dx0} * x0;",
            "    #pragma unroll",
            "    for (int off = 16; off > 0; off >>= 1) dot += __shfl_xor_sync(0xffffffffu, dot, off);",
            "    __shared__ float red[16];",
            "    if ((c & 31) == 0) red[c >> 5] = dot;",
            "    __syncthreads();",
            "    if (c == 0) {",
            "      float total = 0.0f;",
            "      const int nw = C >> 5;",
            "      for (int w_i = 0; w_i < nw; ++w_i) total += red[w_i];",
            "      atomicAdd(dD + a, -s * total);",
            "    }",
            "  }",
            "}",
        ]
        # S130: the same fused kernel on compact channels (GenericLayer::lin_compact, certified at load from exact
        # zeros): C = the kept channels (angular first, a multiple of 4 with zero-weight padding), blockDim = C rounded
        # up to 32. Threads c < n_ang run the full program with x_lm read at c < w_l of degree l's compact buffer (zero
        # beyond: an exactly zero projection column), the others the S127 scalar program (their x1..x15 are exactly
        # zero). Each branch recomputes its forward values after the readout barrier; dm_l is written at the angular
        # thread's columns (the pad columns stay zero from allocation).
        cloads = cload_lines("C")
        RC = [
            "template <int MAX_B, int MIN_BLK>",
            f"__global__ void __launch_bounds__(MAX_B, MIN_BLK) gprod_ro1c_fused_{sig}(",
            "    int N, int C, int n_ang, int wl1, int wl2, int wl3, const int* __restrict__ pos, " +
            _ptr_args("m", range(4)) + ",",
            "    const float* __restrict__ D, const float* __restrict__ w, int64_t w_stride, const int* __restrict__ sp,",
            "    const float* __restrict__ sc_skip16, const float* __restrict__ ro_W1, const float* __restrict__ ro_b1,",
            "    const float* __restrict__ ro_W2, float ro_act_c, float* __restrict__ d_hidden16,",
            f"    double* __restrict__ out_energy, {_ptr_args('dm', range(4), const=False)}, float* __restrict__ dD) {{",
            "  const int a = blockIdx.x, c = threadIdx.x;",
            "  if (a >= N) return;",
            "  const float s = D ? 1.0f / (D[a] + 1.0f) : 1.0f;",
            "  const float* wr = w + (int64_t)sp[a] * w_stride + c;",
            "  float y0 = 0.0f;",
            "  if (c < n_ang) {",
        ] + cloads
        for i in used:
            _ssa(RC, i, prog.nodes[i])
        wloads(RC, feats)
        for b, f in enumerate(feats):
            RC += [f"    y0 = fmaf(w{b}, {_expr(u)}, y0);" for _, u in sorted((f or {}).items()) if u is not None]
        RC += ["  } else if (c < C) {", "    const float x0 = __ldg(m0 + (int64_t)a * C + c) * s;"]
        for i in used_s:
            _ssa(RC, i, ops_s[i])
        wloads(RC, feats_s)
        for b, f in enumerate(feats_s):
            RC += [f"    y0 = fmaf(w{b}, {_expr(u)}, y0);" for _, u in sorted(f.items())]
        RC.append("  }")
        RC += [ln.replace("const int n_chunks = C >> 4;", "const int n_chunks = (int)(blockDim.x >> 4);")
               for ln in ro_block]
        RC += ["  float dot = 0.0f;", "  if (c < n_ang) {"] + cloads
        for i in used:
            _ssa(RC, i, prog.nodes[i])
        wloads(RC, feats)
        adj_c = adjoint(RC, full_ops, used, feats)
        for l in range(4):
            for m in range(2 * l + 1):
                i = l * l + m
                dx = adj_c.get(-1 - i, "0.0f")
                RC.append(f"    dot = fmaf({dx}, x{i}, dot);")
                RC.append(f"    dm0[(int64_t)a * C + c] = {dx} * s;" if l == 0 else
                          f"    if (p{l} >= 0) dm{l}[((int64_t)a * {2 * l + 1} + {m}) * wl{l} + p{l}] = {dx} * s;")
        RC += ["  } else if (c < C) {", "    const float x0 = __ldg(m0 + (int64_t)a * C + c) * s;"]
        for i in used_s:
            _ssa(RC, i, ops_s[i])
        wloads(RC, feats_s)
        dx0_c = adjoint(RC, ops_s, used_s, feats_s).get(-1, "0.0f")
        RC += [f"    dm0[(int64_t)a * C + c] = {dx0_c} * s;", f"    dot = {dx0_c} * x0;"]
        RC += [
            "  }",
            "  if (dD) {",
            "    #pragma unroll",
            "    for (int off = 16; off > 0; off >>= 1) dot += __shfl_xor_sync(0xffffffffu, dot, off);",
            "    __shared__ float red[16];",
            "    if ((c & 31) == 0) red[c >> 5] = dot;",
            "    __syncthreads();",
            "    if (c == 0) {",
            "      float total = 0.0f;",
            "      const int nw = (int)(blockDim.x >> 5);",
            "      for (int w_i = 0; w_i < nw; ++w_i) total += red[w_i];",
            "      atomicAdd(dD + a, -s * total);",
            "    }",
            "  }",
            "}",
        ]
        return ("\n".join(F) + "\n\n" + "\n".join(B) + "\n\n" + "\n".join(RF) + "\n\n" + "\n".join(RS) + "\n\n" +
                "\n".join(RC) + "\n\n" + compact_src, lo)
    return "\n".join(F) + "\n\n" + "\n".join(B) + "\n\n" + compact_src, lo


def _scalar_prune(prog, feats):
    """S127: prog's nodes with the inputs x1..x15 exactly zero: ops (node -> op without its zero terms) for the nodes
    that stay nonzero, the nodes the remaining feature terms need (ascending, SSA order) and the feature terms."""
    zero = set()
    ops = {}

    def z(u):
        return u in zero if u >= 0 else -1 - u >= 1

    for i, op in enumerate(prog.nodes):
        if op[0] == "mul":
            if z(op[1]) or z(op[2]):
                zero.add(i)
            else:
                ops[i] = op
        elif op[0] == "lin":
            t = tuple((c, u) for c, u in op[1] if not z(u))
            if t:
                ops[i] = ("lin", t)
            else:
                zero.add(i)
        else:
            t = tuple((a_, b_) for a_, b_ in op[1] if not (z(a_) or z(b_)))
            if t:
                ops[i] = ("dot", t)
            else:
                zero.add(i)
    feats_s = [{cc: u for cc, u in (f or {}).items() if u is not None and not z(u)} for f in feats]
    need, stack = set(), [u for f in feats_s for u in f.values() if u >= 0]
    while stack:
        i = stack.pop()
        if i in need:
            continue
        need.add(i)
        op = ops[i]
        refs = [op[1], op[2]] if op[0] == "mul" else [u for _, u in op[1]] if op[0] == "lin" else \
            [x for ab in op[1] for x in ab]
        stack += [u for u in refs if u >= 0]
    return ops, sorted(need), feats_s
