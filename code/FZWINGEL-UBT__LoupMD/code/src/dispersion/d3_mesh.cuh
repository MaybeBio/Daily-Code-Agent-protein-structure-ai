// The mesh of the split sum: smooth PME (plan task S6-D06, decisions D78, D79), included by d3_pair.cu inside its
// anonymous namespace after d3_split.cuh (needs <cufft.h> and <dlfcn.h> included before).
//
// Per component (a channel c of C6, or of C8 with the values scaled by sqrt(3) Q_i): the values v_i spread on a
// K0 x K1 x K2 mesh over the cell with cardinal B-splines of order P (Essmann et al. 1995), a real-to-complex FFT,
// E = sum_m c(m) |F(m)|^2 over every m, c(m) = lam_c (-s / 2V) hhat_p(k_m) B(m) with B the Euler-spline moduli
// |b0 b1 b2|^2; the half spectrum scaled to 2 c F and transformed back is dE/dQ at each mesh point, gathered per atom
// into dE/dv_i (into dE/dCN_i through dv_i/dCN_i) and the force; the virial as the direct k sum's. cuFFT is opened
// with dlopen when a mesh is first made (D79), so the library loads and every other method runs without it.

struct CufftApi {
    cufftResult (*plan3d)(cufftHandle*, int, int, int, cufftType) = nullptr;
    cufftResult (*set_stream)(cufftHandle, cudaStream_t) = nullptr;
    cufftResult (*d2z)(cufftHandle, cufftDoubleReal*, cufftDoubleComplex*) = nullptr;
    cufftResult (*z2d)(cufftHandle, cufftDoubleComplex*, cufftDoubleReal*) = nullptr;
    cufftResult (*destroy)(cufftHandle) = nullptr;
    std::string error;
};

inline const CufftApi& cufft_api() {
    static const CufftApi api = [] {
        CufftApi a;
        void* h = nullptr;
        for (const char* name : {"libcufft.so.12", "libcufft.so.13", "libcufft.so"})
            if ((h = dlopen(name, RTLD_NOW | RTLD_LOCAL)) != nullptr) break;
        if (!h) {
            a.error = "cuFFT (libcufft.so.12) was not found: install it with pip install 'cuda-toolkit[cufft]' at the "
                      "version of the CUDA runtime, or use long_range='none'";
            return a;
        }
        a.plan3d = reinterpret_cast<decltype(a.plan3d)>(dlsym(h, "cufftPlan3d"));
        a.set_stream = reinterpret_cast<decltype(a.set_stream)>(dlsym(h, "cufftSetStream"));
        a.d2z = reinterpret_cast<decltype(a.d2z)>(dlsym(h, "cufftExecD2Z"));
        a.z2d = reinterpret_cast<decltype(a.z2d)>(dlsym(h, "cufftExecZ2D"));
        a.destroy = reinterpret_cast<decltype(a.destroy)>(dlsym(h, "cufftDestroy"));
        if (!a.plan3d || !a.set_stream || !a.d2z || !a.z2d || !a.destroy) a.error = "cuFFT lacks a needed function";
        return a;
    }();
    return api;
}

#define CF(x) do { cufftResult r_ = (x); if (r_ != CUFFT_SUCCESS) \
    throw std::runtime_error(std::string("D3 mesh: cuFFT error ") + std::to_string((int)r_) + " at " + __FILE__ + \
                             ":" + std::to_string(__LINE__)); } while (0)

// Cardinal B-spline weights of order P at the offset w in [0, 1) and their w-derivatives (Essmann et al. 1995).
template <int P>
__device__ __forceinline__ void bspline(float w, float* m, float* dm) {
    m[P - 1] = 0.0f;
    m[1] = w;
    m[0] = 1.0f - w;
#pragma unroll
    for (int j = 3; j < P; ++j) {
        const float div = 1.0f / (j - 1);
        m[j - 1] = div * w * m[j - 2];
#pragma unroll
        for (int k = 1; k < j - 1; ++k) m[j - k - 1] = div * ((w + k) * m[j - k - 2] + (j - k - w) * m[j - k - 1]);
        m[0] = div * (1.0f - w) * m[0];
    }
    dm[0] = -m[0];
#pragma unroll
    for (int j = 1; j < P; ++j) dm[j] = m[j - 1] - m[j];
    const float div = 1.0f / (P - 1);
    m[P - 1] = div * w * m[P - 2];
#pragma unroll
    for (int k = 1; k < P - 1; ++k) m[P - k - 1] = div * ((w + k) * m[P - k - 2] + (P - k - w) * m[P - k - 1]);
    m[0] = div * (1.0f - w) * m[0];
}

struct MeshDims {
    int k[3];
};

__device__ __forceinline__ float comp_scale(int i, bool c8, const float4* ps, const float* r2r4) {
    return c8 ? 1.7320508f * r2r4[__float_as_int(ps[i].w)] : 1.0f;
}

template <int P>
__device__ __forceinline__ void mesh_weights(const float3 f, const MeshDims& d, float (&m)[3][P], float (&dm)[3][P],
                                             int (&base)[3]) {
    const float fr[3] = {f.x - floorf(f.x), f.y - floorf(f.y), f.z - floorf(f.z)};
    for (int a = 0; a < 3; ++a) {
        const float u = fr[a] * d.k[a];
        const int iu = min((int)u, d.k[a] - 1);
        base[a] = iu;
        bspline<P>(u - iu, m[a], dm[a]);
    }
}

template <int P>
__global__ void pme_spread_kernel(int n, int nc, int c, bool c8, MeshDims d, const float3* __restrict__ frac,
                                  const float4* __restrict__ ps, const float* __restrict__ r2r4,
                                  const float* __restrict__ qc, double* __restrict__ grid) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    const float v = qc[(size_t)i * nc + c] * comp_scale(i, c8, ps, r2r4);
    float m[3][P], dm[3][P];
    int base[3];
    mesh_weights<P>(frac[i], d, m, dm, base);
    for (int x = 0; x < P; ++x) {
        const int gx = (base[0] + x) % d.k[0];
        for (int y = 0; y < P; ++y) {
            const int gy = (base[1] + y) % d.k[1];
            const float wxy = v * m[0][x] * m[1][y];
            const size_t row = ((size_t)gx * d.k[1] + gy) * d.k[2];
            for (int z = 0; z < P; ++z) atomicAdd(&grid[row + (base[2] + z) % d.k[2]], (double)(wxy * m[2][z]));
        }
    }
}

// Per half-spectrum entry (R2C layout K0 x K1 x (K2/2 + 1)): the component's energy and virial, and F scaled to
// 2 c(m) F(m) (its inverse transform is dE/dQ).
__global__ void pme_kspace_kernel(MeshDims d, const Grid* __restrict__ gp, double beta, double s, int p, double lam,
                                  const double* __restrict__ bmod0, const double* __restrict__ bmod1,
                                  const double* __restrict__ bmod2, cufftDoubleComplex* __restrict__ F,
                                  double* __restrict__ acc) {
    const int h2 = d.k[2] / 2 + 1;
    const long long total = (long long)d.k[0] * d.k[1] * h2;
    const long long t = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    double e = 0.0, v[6] = {0, 0, 0, 0, 0, 0};
    if (t < total) {
        const int m2 = (int)(t % h2), m1 = (int)((t / h2) % d.k[1]), m0 = (int)(t / ((long long)h2 * d.k[1]));
        const int n0 = m0 <= d.k[0] / 2 ? m0 : m0 - d.k[0];
        const int n1 = m1 <= d.k[1] / 2 ? m1 : m1 - d.k[1];
        const Grid& g = *gp;
        const double TWO_PI = 6.283185307179586;
        const double kx = TWO_PI * (g.inv[0] * n0 + g.inv[1] * n1 + g.inv[2] * m2);
        const double ky = TWO_PI * (g.inv[3] * n0 + g.inv[4] * n1 + g.inv[5] * m2);
        const double kz = TWO_PI * (g.inv[6] * n0 + g.inv[7] * n1 + g.inv[8] * m2);
        const double k = sqrt(kx * kx + ky * ky + kz * kz);
        double t6, t8, dt6, dt8;
        split_t(k / (2.0 * beta), t6, t8, dt6, dt8);
        const double PI15 = 5.568327996831708;
        const double b3 = beta * beta * beta;
        const double pre = p == 6 ? PI15 * b3 / 2.0 : PI15 * b3 * beta * beta / 6.0;
        const double hh = pre * (p == 6 ? t6 : t8), dh = pre * (p == 6 ? dt6 : dt8) / (2.0 * beta);
        const double B = bmod0[m0] * bmod1[m1] * bmod2[m2];
        const double f = -s / (2.0 * g.vol) * lam * B;
        const double c = f * hh;
        const double w = (m2 == 0 || (d.k[2] % 2 == 0 && m2 == d.k[2] / 2)) ? 1.0 : 2.0;
        const cufftDoubleComplex z = F[t];
        const double a2 = z.x * z.x + z.y * z.y;
        e = w * c * a2;
        if (k > 0.0) {
            const double dk = w * f * dh * a2 / k;
            v[0] = -dk * kx * kx; v[1] = -dk * kx * ky; v[2] = -dk * kx * kz;
            v[3] = -dk * ky * ky; v[4] = -dk * ky * kz; v[5] = -dk * kz * kz;
        }
        v[0] -= e; v[3] -= e; v[5] -= e;
        F[t] = make_cuDoubleComplex(2.0 * c * z.x, 2.0 * c * z.y);
    }
    e = warp_sum(e);
    for (int q = 0; q < 6; ++q) v[q] = warp_sum(v[q]);
    if ((threadIdx.x & 31) == 0 && (e != 0.0 || v[0] != 0.0)) {
        atomicAdd(&acc[0], e);
        for (int q = 0; q < 6; ++q) atomicAdd(&acc[1 + q], v[q]);
    }
}

// Per atom: phi = dE/dv_i = sum_g dE/dQ(g) W_i(g) and its gradient; dE/dq_ic into dE/dCN_i, half of v phi into the
// atom's energy, -v grad phi into the force.
template <int P, bool FORCES>
__global__ void pme_gather_kernel(int n, int nc, int c, bool c8, MeshDims d, const Grid* __restrict__ gp,
                                  const float3* __restrict__ frac, const float4* __restrict__ ps,
                                  const float* __restrict__ r2r4, const float* __restrict__ qc,
                                  const float* __restrict__ dqc, const double* __restrict__ dedq,
                                  double* __restrict__ eatom, double* __restrict__ force_s,
                                  double* __restrict__ dedcn) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    const float scale = comp_scale(i, c8, ps, r2r4);
    const float v = qc[(size_t)i * nc + c] * scale;
    float m[3][P], dm[3][P];
    int base[3];
    mesh_weights<P>(frac[i], d, m, dm, base);
    double phi = 0.0, g0 = 0.0, g1 = 0.0, g2 = 0.0;      // the gradient in mesh units u_a
    for (int x = 0; x < P; ++x) {
        const int gx = (base[0] + x) % d.k[0];
        for (int y = 0; y < P; ++y) {
            const int gy = (base[1] + y) % d.k[1];
            const size_t row = ((size_t)gx * d.k[1] + gy) * d.k[2];
            double s = 0.0, sz = 0.0;
            for (int z = 0; z < P; ++z) {
                const double q = dedq[row + (base[2] + z) % d.k[2]];
                s += q * m[2][z];
                if (FORCES) sz += q * dm[2][z];
            }
            phi += s * m[0][x] * m[1][y];
            if (FORCES) {
                g0 += s * dm[0][x] * m[1][y];
                g1 += s * m[0][x] * dm[1][y];
                g2 += sz * m[0][x] * m[1][y];
            }
        }
    }
    if (eatom) eatom[i] += 0.5 * v * phi;
    if (FORCES) {
        const Grid& g = *gp;
        const double ga[3] = {g0 * d.k[0], g1 * d.k[1], g2 * d.k[2]};       // du_a/dr_b = K_a inv[b][a]
        for (int b = 0; b < 3; ++b)
            force_s[3 * i + b] -= v * (ga[0] * g.inv[3 * b] + ga[1] * g.inv[3 * b + 1] + ga[2] * g.inv[3 * b + 2]);
        dedcn[i] += phi * scale * dqc[(size_t)i * nc + c];
    }
}

// Host: the Euler-spline moduli |b(m)|^2 of order P along an axis of K points.
inline std::vector<double> pme_moduli(int K, int P) {
    // M_P at the integers by M_n(x) = (x M_{n-1}(x) + (n - x) M_{n-1}(x - 1)) / (n - 1), M_2(1) = 1
    std::vector<double> mp(P + 1, 0.0);
    mp[1] = 1.0;
    for (int n = 3; n <= P; ++n) {
        std::vector<double> cur(P + 1, 0.0);
        for (int x = 1; x < n; ++x) cur[x] = (x * mp[x] + (n - x) * mp[x - 1]) / (n - 1);
        mp = cur;
    }
    std::vector<double> out(K);
    for (int m = 0; m < K; ++m) {
        double re = 0.0, im = 0.0;
        for (int k = 0; k <= P - 2; ++k) {
            const double a = 2.0 * M_PI * m * k / K;
            re += mp[k + 1] * std::cos(a);
            im += mp[k + 1] * std::sin(a);
        }
        const double den = re * re + im * im;
        out[m] = den > 1e-14 ? 1.0 / den : 0.0;
    }
    for (int m = 0; m < K; ++m)          // a zero of the denominator (odd orders at K / 2): the neighbours' mean
        if (out[m] == 0.0) out[m] = 0.5 * (out[(m + K - 1) % K] + out[(m + 1) % K]);
    return out;
}

// Host: the smallest K >= k whose prime factors are 2, 3 and 5.
inline int pme_good_size(int k) {
    for (int n = std::max(k, 1);; ++n) {
        int r = n;
        for (int p : {2, 3, 5})
            while (r % p == 0) r /= p;
        if (r == 1) return n;
    }
}
