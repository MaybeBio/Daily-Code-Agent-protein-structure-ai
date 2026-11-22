// Lowering of the kernel IR to NVRTC sources (kernel_ir.hpp, JIT_DESIGN.md).
#include "kernel_ir.hpp"

#include <cstdio>

namespace loup {

namespace {

// An exact float literal (hexadecimal: the value is the float's own, no decimal rounding)
std::string flit(float v) {
    char b[48];
    snprintf(b, sizeof(b), "%af", (double)v);
    return b;
}

// k == 0 ? v[0] : k == 1 ? v[1] : ... over the grid's bands
template <typename T, typename F>
std::string by_band(int nb, const T* v, F lit) {
    std::string s = lit(v[nb - 1]);
    for (int k = nb - 2; k >= 0; --k) s = "(k == " + std::to_string(k) + " ? " + lit(v[k]) + " : " + s + ")";
    return s;
}

}  // namespace

std::string layer0_jit_source(const Layer0IR& ir) {
    std::string s;
    s += "// LoupMD layer-0 kernels, JIT (kernel_ir.cu)\n";
    s += "#define LOUP_JIT_L0 1\n";
    s += "#define LOUP_JIT_L0_S " + std::to_string(ir.S) + "\n";
    s += "#define LOUP_JIT_L0_I " + std::to_string(ir.I) + "\n";
    s += "#define LOUP_JIT_L0_J " + std::to_string(ir.J) + "\n";
    s += "#define LOUP_JIT_L0_Jt " + std::to_string(ir.Jt) + "\n";
    s += "#define LOUP_JIT_L0_K0 " + std::to_string(ir.K0) + "\n";
    s += "#define LOUP_JIT_L0_sh_perm " + std::to_string(ir.sh_perm) + "\n";
    s += "#define LOUP_JIT_L0_pair_sym " + std::to_string(ir.pair_sym) + "\n";
    s += "#include \"kernels_common.cuh\"\n";
    if (!ir.bake_grid) {
        s += "#include \"layer0_kernels.cuh\"\n";
        return s;
    }
    s += "#define LOUP_JIT_L0_GRID 1\n";
    // locate_spline (kernels_common.cuh) on this grid: the same band test, operations and order
    const SplineGrid& g = ir.grid;
    const int nb = g.n_bands < 1 ? 1 : (g.n_bands > 8 ? 8 : g.n_bands);
    auto ilit = [](int v) { return std::to_string(v); };
    int cm1[8];
    for (int k = 0; k < 8; ++k) cm1[k] = g.counts[k] - 1;
    s += "__device__ __forceinline__ void loup_jit_l0_locate(float r, int& iv, float& t, float& sx_inv) {\n";
    s += "    int k = 0;\n";
    for (int i = 0; i < nb - 1 && i < 7; ++i)
        s += "    if (r >= " + flit(g.ends[i]) + ") k = " + std::to_string(i + 1) + ";\n";
    s += "    (void)k;\n";
    s += "    sx_inv = " + by_band(nb, g.inv_h, flit) + ";\n";
    s += "    float u = (r - " + by_band(nb, g.starts, flit) + ") * sx_inv;\n";
    s += "    u = u > 0.0f ? u : 0.0f;\n";
    s += "    int il = (int)u;\n";
    s += "    const int mx = " + by_band(nb, cm1, ilit) + ";\n";
    s += "    il = il < mx ? il : mx;\n";
    s += "    t = u - (float)il;\n";
    s += "    iv = " + by_band(nb, g.offsets, ilit) + " + il;\n";
    s += "}\n";
    s += "#include \"layer0_kernels.cuh\"\n";
    return s;
}

std::string conv_jit_source() {
    return "// LoupMD conv kernels, JIT (kernel_ir.cu)\n#include \"generated_conv.cuh\"\n";
}

std::vector<std::string> conv_jit_names(const ConvIR& ir, int* n_fwd_kernels, int* n_bwd_kernels) {
    const std::string C = std::to_string(ir.C), M = ir.C <= 256 ? "256" : "512";
    // the paired-edge decode (PAIR) as the C = 128 instances use it, up to 256 channels (S143: lx 1 at C 128 on the
    // run-time-width branch 2,053 us unpaired against 1,780 paired, OMAT-0 generic SrTiO3)
    const std::string pr = (ir.pair && ir.C <= 256) ? "true" : "false";
    std::vector<std::string> fk, bk;  // kernel templates up to the PRELOC / WANT_DX arguments
    if (ir.fwd) {
        if (ir.lx == 0) {
            fk = {"gconv_fwd_L0<1, " + pr + ", " + M + ", %P, " + C + ">"};
        } else if (ir.lx == 1) {
            fk = {std::string(ir.prune ? "gconv_fwd_L1s" : "gconv_fwd_L1") + "<1, " + pr + ", " + M + ", %P, " + C + ">"};
        } else {
            const std::string pa = ir.C <= 256 ? "1, true, 256" : "1, false, 512";
            fk = {"gconv_fwd_L2a<" + pa + ", %P, " + C + ">", "gconv_fwd_L2b<" + pa + ", %P, " + C + ">"};
        }
    }
    if (ir.bwd) {
        if (ir.lx == 0) bk = {"gconv_bwd_L0<%W, " + C + ", %P>"};
        else if (ir.lx == 1) bk = {std::string(ir.prune ? "gconv_bwd_L1s" : "gconv_bwd_L1") + "<%W, " + C + ", %P>"};
        else bk = {"gconv_bwd_L2lp<%W, " + C + ", %P>", "gconv_bwd_L2<%W, " + C + ", %P>"};
    }
    auto sub = [](std::string t, const char* key, const char* v) {
        const size_t k = t.find(key);
        if (k != std::string::npos) t.replace(k, 2, v);
        return t;
    };
    std::vector<std::string> out;
    for (const auto& t : fk)
        for (const char* p : {"false", "true"}) out.push_back(sub(t, "%P", p));
    for (const auto& t : bk)
        for (const char* w : {"false", "true"})
            for (const char* p : {"false", "true"}) out.push_back(sub(sub(t, "%W", w), "%P", p));
    *n_fwd_kernels = (int)fk.size();
    *n_bwd_kernels = (int)bk.size();
    return out;
}

std::string product_jit_source(const std::string& bundle_src) {
    return "// LoupMD product kernels, JIT (kernel_ir.cu; source from the bundle)\n#include \"kernels_common.cuh\"\n"
           "#include \"generated_sh16.cuh\"\n" +
           bundle_src;
}

std::vector<std::string> product_jit_names(const std::string& sig, int lmax_out) {
    std::vector<std::string> out = {"gprod_fwd_" + sig, "gprod_bwd_" + sig};
    if (lmax_out == 0)
        for (const char* v : {"ro1", "ro1s", "ro1c"})
            for (const char* cb : {"128, 4", "256, 2", "512, 1"})
                out.push_back(std::string("gprod_") + v + "_fused_" + sig + "<" + cb + ">");
    out.push_back("gprod_fwdc_" + sig);
    out.push_back("gprod_bwdc_" + sig);
    return out;
}

std::vector<std::string> layer0_jit_names(const Layer0IR& ir) {
    const std::string c = std::to_string(layer0_edge_cols(ir.J)), z = ir.zbl ? "true" : "false";
    return {"&first_fwd_kernel", "first_bwd_edge_kernel<" + c + ", " + z + ", false, 0>",
            "first_bwd_edge_kernel<" + c + ", " + z + ", true, 0>"};
}

}  // namespace loup
