// The split sum of D3 (plan task S6-D06, decision D78), included by d3_pair.cu inside its anonymous namespace.
//
// The C6 and C8 matrices are exactly separable: in the basis of (species, reference) slots, C6_ij = sum_c lam_c
// q_ic q_jc with lam_c, v_c the eigenpairs of the reference C6 table and q_ic = sum_a w_ia v_c(s_i, a); C8_ij = 3 Q_i
// Q_j C6_ij takes the same channels scaled by sqrt(3) Q_i. So each of 1/r^6 and 1/r^8 takes an Ewald split with no
// combination rule:
//   1/r^2p = h_s + h_l,  h_l(r) = (1 - e^-x sum_{m<p} x^m/m!) / r^2p = e^-x sum_{m>=p} x^m/m! / r^2p,  x = (beta r)^2,
//   sum'_{i,j,n} C_ij h_l = 1/V sum_k hhat_p(k) sum_c lam_c |rho_c(k)|^2 - beta^2p/p! sum_i C_ii,
//   hhat_p(k) = pi^{3/2} beta^{2p-3} / (p-1)! * T_p(b),  T_p(b) = b^{2p-3} Gamma(3/2 - p, b^2),  b = k / (2 beta),
//   T_3 = 2/3 e (1 - 2 b^2) + 4/3 sqrt(pi) b^3 erfc b,  T_4 = e (2/5 - 4/15 b^2 + 8/15 b^4) - 8/15 sqrt(pi) b^5 erfc b,
// e = exp(-b^2) (the k = 0 term included: dispersion has no neutrality). The pair kernel sums the damped pair energy
// minus s6 C6 h_l6 + s8 C8 h_l8 to the pair cutoff; this file adds the k sum and the self term. Forces and virial: the
// k sum's direct r- and strain-derivatives, and dE/dq_ic into dE/dCN_i for the CN chain rule of the third pass.
// This is the direct k sum, the reference of the mesh (D78's order of work).

constexpr double SPLIT_BETA_RC = 4.5;       // beta = 4.5 / real-space cutoff: e^-x x^2/2 below 4e-7 at the cutoff
constexpr double SPLIT_B_MAX = 4.5;         // k sum to b = k / (2 beta) = 4.5: T_p below 1e-7 of T_p(0)
constexpr int SPLIT_MAX_CHANNELS = 64;

struct KVec {
    float kx, ky, kz, k;
    double a6, a8;          // energy factors: E_k = sum_c lam_c (a6 |rho6_c|^2 + a8 |rho8_c|^2)
    double d6, d8;          // the same with dhhat/dk in place of hhat
};

__device__ __forceinline__ void split_t(double b, double& t6, double& t8, double& dt6, double& dt8) {
    const double e = exp(-b * b), sp = 1.7724538509055160 * erfc(b);       // sqrt(pi) erfc b
    const double b2 = b * b, b3 = b2 * b, b4 = b2 * b2;
    t6 = 2.0 / 3.0 * e * (1.0 - 2.0 * b2) + 4.0 / 3.0 * b3 * sp;
    dt6 = 4.0 * b2 * sp - 4.0 * b * e;
    t8 = e * (0.4 - 4.0 / 15.0 * b2 + 8.0 / 15.0 * b4) - 8.0 / 15.0 * b4 * b * sp;
    dt8 = e * (-4.0 / 3.0 * b + 8.0 / 3.0 * b3) - 8.0 / 3.0 * b4 * sp;
}

// Per k: the vector from its integer index (k = 2 pi inv m, the cell read on the device), the energy factors with the
// half-space weight (2, or 1 for k = 0), and their k-derivatives.
__global__ void split_kvec_kernel(int nk, const int3* __restrict__ ms, const Grid* __restrict__ gp, double beta,
                                  double s6, double s8, KVec* __restrict__ kv) {
    const int t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= nk) return;
    const Grid& g = *gp;
    const int3 m = ms[t];
    const double TWO_PI = 6.283185307179586;
    const double kx = TWO_PI * (g.inv[0] * m.x + g.inv[1] * m.y + g.inv[2] * m.z);
    const double ky = TWO_PI * (g.inv[3] * m.x + g.inv[4] * m.y + g.inv[5] * m.z);
    const double kz = TWO_PI * (g.inv[6] * m.x + g.inv[7] * m.y + g.inv[8] * m.z);
    const double k = sqrt(kx * kx + ky * ky + kz * kz);
    double t6, t8, dt6, dt8;
    split_t(k / (2.0 * beta), t6, t8, dt6, dt8);
    const double PI15 = 5.568327996831708;     // pi^{3/2}
    const double b3 = beta * beta * beta, b5 = b3 * beta * beta;
    const double w = (m.x == 0 && m.y == 0 && m.z == 0) ? 1.0 : 2.0;
    const double f = -w / (2.0 * g.vol);       // E = -(s6 S6 + s8 S8), S = 1/(2V) sum_k hhat |rho|^2 + ...
    KVec o;
    o.kx = (float)kx; o.ky = (float)ky; o.kz = (float)kz; o.k = (float)k;
    o.a6 = f * s6 * PI15 * b3 / 2.0 * t6;
    o.a8 = f * s8 * PI15 * b5 / 6.0 * t8;
    o.d6 = f * s6 * PI15 * b3 / 2.0 * dt6 / (2.0 * beta);
    o.d8 = f * s8 * PI15 * b5 / 6.0 * dt8 / (2.0 * beta);
    kv[t] = o;
}

// Per sorted atom: fractional coordinates, the channel values q_ic and dq_ic/dCN_i.
__global__ void split_atom_kernel(int n, int nc, const float4* __restrict__ ps, const Grid* __restrict__ gp,
                                  const float* __restrict__ chan, const float* __restrict__ w,
                                  const float* __restrict__ dw, float3* __restrict__ frac, float* __restrict__ qc,
                                  float* __restrict__ dqc) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    const Grid& g = *gp;
    const float4 p = ps[i];
    const double x = p.x, y = p.y, z = p.z;
    frac[i] = make_float3((float)(x * g.inv[0] + y * g.inv[3] + z * g.inv[6]),
                          (float)(x * g.inv[1] + y * g.inv[4] + z * g.inv[7]),
                          (float)(x * g.inv[2] + y * g.inv[5] + z * g.inv[8]));
    const int s = __float_as_int(p.w);
    const float* v = chan + (size_t)s * MAXREF * nc;
    for (int c = 0; c < nc; ++c) {
        float q = 0.0f, dq = 0.0f;
        for (int a = 0; a < MAXREF; ++a) {
            q += w[(size_t)i * WSTRIDE + a] * v[a * nc + c];
            dq += dw[(size_t)i * MAXREF + a] * v[a * nc + c];
        }
        qc[(size_t)i * nc + c] = q;
        dqc[(size_t)i * nc + c] = dq;
    }
}

// Per (k, channel): rho6 = sum_i q_ic e^{i k r_i}, rho8 = sum_i sqrt(3) Q_i q_ic e^{i k r_i}.
__global__ void split_rho_kernel(int n, int nk, int nc, const int3* __restrict__ ms, const float3* __restrict__ frac,
                                 const float4* __restrict__ ps, const float* __restrict__ r2r4,
                                 const float* __restrict__ qc, double2* __restrict__ rho6, double2* __restrict__ rho8) {
    const int t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= nk * nc) return;
    const int kk = t / nc, c = t % nc;
    const int3 m = ms[kk];
    double r6 = 0.0, i6 = 0.0, r8 = 0.0, i8 = 0.0;
    for (int i = 0; i < n; ++i) {
        const float3 f = frac[i];
        float ph = (float)m.x * f.x + (float)m.y * f.y + (float)m.z * f.z;
        ph -= rintf(ph);
        float s, co;
        sincospif(2.0f * ph, &s, &co);
        const float q = qc[(size_t)i * nc + c];
        const float q8 = 1.7320508f * r2r4[__float_as_int(ps[i].w)] * q;
        r6 += (double)(q * co); i6 += (double)(q * s);
        r8 += (double)(q8 * co); i8 += (double)(q8 * s);
    }
    rho6[t] = make_double2(r6, i6);
    rho8[t] = make_double2(r8, i8);
}

// The k sum's energy and virial (dE/d strain: -delta_ab E_k - dE_k/dk k_a k_b / k).
__global__ void split_energy_kernel(int nk, int nc, const KVec* __restrict__ kv, const double* __restrict__ lam,
                                    const double2* __restrict__ rho6, const double2* __restrict__ rho8,
                                    double* __restrict__ acc) {
    const int t = blockIdx.x * blockDim.x + threadIdx.x;
    double e = 0.0, v[6] = {0, 0, 0, 0, 0, 0};
    if (t < nk * nc) {
        const KVec k = kv[t / nc];
        const double l = lam[t % nc];
        const double2 a = rho6[t], b = rho8[t];
        const double s6 = a.x * a.x + a.y * a.y, s8 = b.x * b.x + b.y * b.y;
        e = l * (k.a6 * s6 + k.a8 * s8);
        if (k.k > 0.0f) {
            const double dk = l * (k.d6 * s6 + k.d8 * s8) / (double)k.k;
            const double kx = k.kx, ky = k.ky, kz = k.kz;
            v[0] = -dk * kx * kx; v[1] = -dk * kx * ky; v[2] = -dk * kx * kz;
            v[3] = -dk * ky * ky; v[4] = -dk * ky * kz; v[5] = -dk * kz * kz;
        }
        v[0] -= e; v[3] -= e; v[5] -= e;
    }
    e = warp_sum(e);
    for (int c = 0; c < 6; ++c) v[c] = warp_sum(v[c]);
    if ((threadIdx.x & 31) == 0 && (e != 0.0 || v[0] != 0.0)) {
        atomicAdd(&acc[0], e);
        for (int c = 0; c < 6; ++c) atomicAdd(&acc[1 + c], v[c]);
    }
}

// Per sorted atom: its share of the k-sum energy and the self term, the k sum's force, and dE/dq_ic through
// dq_ic/dCN_i into dE/dCN_i. Runs after the pair (and three-body) kernels, before the CN chain rule.
template <bool FORCES>
__global__ void split_force_kernel(int n, int nk, int nc, const int3* __restrict__ ms, const KVec* __restrict__ kv,
                                   const double* __restrict__ lam, const double2* __restrict__ rho6,
                                   const double2* __restrict__ rho8, const float3* __restrict__ frac,
                                   const float4* __restrict__ ps, const float* __restrict__ r2r4,
                                   const float* __restrict__ qc, const float* __restrict__ dqc, double beta, double s6,
                                   double s8, double* __restrict__ acc, double* __restrict__ eatom,
                                   double* __restrict__ force_s, double* __restrict__ dedcn) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    double eself = 0.0;
    if (i < n) {
        const float3 f = frac[i];
        const float q8s = 1.7320508f * r2r4[__float_as_int(ps[i].w)];
        double ei = 0.0, fx = 0.0, fy = 0.0, fz = 0.0;
        double dq[SPLIT_MAX_CHANNELS];
        for (int c = 0; c < nc; ++c) dq[c] = 0.0;
        for (int kk = 0; kk < nk; ++kk) {
            const int3 m = ms[kk];
            float ph = (float)m.x * f.x + (float)m.y * f.y + (float)m.z * f.z;
            ph -= rintf(ph);
            float sn, cs;
            sincospif(2.0f * ph, &sn, &cs);
            const KVec k = kv[kk];
            double im = 0.0;
            for (int c = 0; c < nc; ++c) {
                const double2 a = rho6[(size_t)kk * nc + c], b = rho8[(size_t)kk * nc + c];
                // Re and Im of conj(rho) e^{i phi}
                const double re6 = a.x * cs + a.y * sn, im6 = a.x * sn - a.y * cs;
                const double re8 = b.x * cs + b.y * sn, im8 = b.x * sn - b.y * cs;
                const double l = lam[c], q = qc[(size_t)i * nc + c];
                ei += l * q * (k.a6 * re6 + k.a8 * q8s * re8);
                if (FORCES) {
                    dq[c] += 2.0 * l * (k.a6 * re6 + k.a8 * q8s * re8);
                    im += 2.0 * l * q * (k.a6 * im6 + k.a8 * q8s * im8);
                }
            }
            if (FORCES) { fx += im * k.kx; fy += im * k.ky; fz += im * k.kz; }
        }
        // self term: -(s6 S6 + s8 S8) with S_p's -beta^2p/p! sum_i C_ii
        const double b6 = beta * beta * beta * beta * beta * beta, b8 = b6 * beta * beta;
        double dcn = 0.0;
        for (int c = 0; c < nc; ++c) {
            const double l = lam[c], q = qc[(size_t)i * nc + c], q8 = q8s * q;
            eself += l * (s6 * b6 / 6.0 * q * q + s8 * b8 / 24.0 * q8 * q8) * 0.5;
            if (FORCES) dcn += (dq[c] + l * (s6 * b6 / 6.0 * q + s8 * b8 / 24.0 * q8 * q8s)) * dqc[(size_t)i * nc + c];
        }
        if (eatom) eatom[i] += ei + eself;
        if (FORCES) {
            force_s[3 * i + 0] += fx;
            force_s[3 * i + 1] += fy;
            force_s[3 * i + 2] += fz;
            dedcn[i] += dcn;
        }
    }
    eself = warp_sum(eself);
    if ((threadIdx.x & 31) == 0 && eself != 0.0) atomicAdd(&acc[0], eself);
}

// Host: the channels of the reference C6 table over the species present. In the basis of the slots (s, a < nref_s),
// M[(s,a),(t,b)] = C6ref(s, t)(a, b); Jacobi eigenpairs in float64; channels with |lam| above 1e-12 of the largest
// are kept. chan[s][a][c] = v_c(s, a) (0 for a >= nref_s).
inline int split_channels(int S, const std::vector<int>& nref, const std::vector<float>& c6, std::vector<float>& chan,
                          std::vector<double>& lam_out) {
    std::vector<int> slot_s, slot_a;
    for (int s = 0; s < S; ++s)
        for (int a = 0; a < nref[s]; ++a) { slot_s.push_back(s); slot_a.push_back(a); }
    const int d = (int)slot_s.size();
    std::vector<double> A((size_t)d * d), V((size_t)d * d, 0.0);
    for (int x = 0; x < d; ++x) {
        V[(size_t)x * d + x] = 1.0;
        for (int y = 0; y < d; ++y)
            A[(size_t)x * d + y] = c6[((size_t)slot_s[x] * S + slot_s[y]) * MAXREF * MAXREF + slot_a[x] * MAXREF +
                                      slot_a[y]];
    }
    for (int x = 0; x < d; ++x)          // the float table is symmetric up to rounding: symmetrise
        for (int y = x + 1; y < d; ++y) {
            const double m = 0.5 * (A[(size_t)x * d + y] + A[(size_t)y * d + x]);
            A[(size_t)x * d + y] = A[(size_t)y * d + x] = m;
        }
    for (int sweep = 0; sweep < 100; ++sweep) {
        double off = 0.0, diag = 0.0;
        for (int x = 0; x < d; ++x) {
            diag += A[(size_t)x * d + x] * A[(size_t)x * d + x];
            for (int y = x + 1; y < d; ++y) off += A[(size_t)x * d + y] * A[(size_t)x * d + y];
        }
        if (off <= 1e-30 * diag) break;
        for (int p = 0; p < d; ++p)
            for (int r = p + 1; r < d; ++r) {
                const double apr = A[(size_t)p * d + r];
                if (std::fabs(apr) < 1e-300) continue;
                const double theta = (A[(size_t)r * d + r] - A[(size_t)p * d + p]) / (2.0 * apr);
                const double t = (theta >= 0 ? 1.0 : -1.0) / (std::fabs(theta) + std::sqrt(theta * theta + 1.0));
                const double c = 1.0 / std::sqrt(t * t + 1.0), s = t * c;
                for (int k = 0; k < d; ++k) {        // columns p, r
                    const double akp = A[(size_t)k * d + p], akr = A[(size_t)k * d + r];
                    A[(size_t)k * d + p] = c * akp - s * akr;
                    A[(size_t)k * d + r] = s * akp + c * akr;
                }
                for (int k = 0; k < d; ++k) {        // rows p, r
                    const double apk = A[(size_t)p * d + k], ark = A[(size_t)r * d + k];
                    A[(size_t)p * d + k] = c * apk - s * ark;
                    A[(size_t)r * d + k] = s * apk + c * ark;
                }
                for (int k = 0; k < d; ++k) {
                    const double vkp = V[(size_t)k * d + p], vkr = V[(size_t)k * d + r];
                    V[(size_t)k * d + p] = c * vkp - s * vkr;
                    V[(size_t)k * d + r] = s * vkp + c * vkr;
                }
            }
    }
    double big = 0.0;
    for (int x = 0; x < d; ++x) big = std::max(big, std::fabs(A[(size_t)x * d + x]));
    std::vector<int> keep;
    for (int x = 0; x < d; ++x)
        if (std::fabs(A[(size_t)x * d + x]) > 1e-12 * big) keep.push_back(x);
    const int nc = (int)keep.size();
    if (nc > SPLIT_MAX_CHANNELS)
        throw std::invalid_argument("D3 split sum: " + std::to_string(nc) + " channels, more than the " +
                                    std::to_string(SPLIT_MAX_CHANNELS) + " built for");
    chan.assign((size_t)S * MAXREF * nc, 0.0f);
    lam_out.resize(nc);
    for (int c = 0; c < nc; ++c) {
        lam_out[c] = A[(size_t)keep[c] * d + keep[c]];
        for (int x = 0; x < d; ++x)
            chan[((size_t)slot_s[x] * MAXREF + slot_a[x]) * nc + c] = (float)V[(size_t)x * d + keep[c]];
    }
    return nc;
}

// Host: the half-space integer k indices (k = 0 first) within b_max of the k sum for this cell, with a 25% margin
// for cells that later grow or shear.
inline std::vector<int3> split_kset(const double cell_A[9], double beta) {
    double c[9];
    for (int k = 0; k < 9; ++k) c[k] = cell_A[k] / BOHR;
    const double kmax = 2.0 * beta * SPLIT_B_MAX * 1.25;
    int M[3];
    for (int a = 0; a < 3; ++a) {
        const double len = std::sqrt(c[3 * a] * c[3 * a] + c[3 * a + 1] * c[3 * a + 1] + c[3 * a + 2] * c[3 * a + 2]);
        M[a] = (int)std::ceil(kmax * len / (2.0 * M_PI));
    }
    const double det = c[0] * (c[4] * c[8] - c[5] * c[7]) - c[1] * (c[3] * c[8] - c[5] * c[6]) +
                       c[2] * (c[3] * c[7] - c[4] * c[6]);
    double inv[9];
    inv[0] = (c[4] * c[8] - c[5] * c[7]) / det; inv[1] = (c[2] * c[7] - c[1] * c[8]) / det;
    inv[2] = (c[1] * c[5] - c[2] * c[4]) / det; inv[3] = (c[5] * c[6] - c[3] * c[8]) / det;
    inv[4] = (c[0] * c[8] - c[2] * c[6]) / det; inv[5] = (c[2] * c[3] - c[0] * c[5]) / det;
    inv[6] = (c[3] * c[7] - c[4] * c[6]) / det; inv[7] = (c[1] * c[6] - c[0] * c[7]) / det;
    inv[8] = (c[0] * c[4] - c[1] * c[3]) / det;
    std::vector<int3> out{make_int3(0, 0, 0)};
    for (int x = 0; x <= M[0]; ++x)
        for (int y = -M[1]; y <= M[1]; ++y)
            for (int z = -M[2]; z <= M[2]; ++z) {
                if (x == 0 && (y < 0 || (y == 0 && z <= 0))) continue;      // half space, k = 0 apart
                const double kx = 2 * M_PI * (inv[0] * x + inv[1] * y + inv[2] * z);
                const double ky = 2 * M_PI * (inv[3] * x + inv[4] * y + inv[5] * z);
                const double kz = 2 * M_PI * (inv[6] * x + inv[7] * y + inv[8] * z);
                if (kx * kx + ky * ky + kz * kz <= kmax * kmax) out.push_back(make_int3(x, y, z));
            }
    return out;
}
