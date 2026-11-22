// SPDX-License-Identifier: LGPL-2.1-or-later
// Provenance: the integrators of this file follow the molecular-dynamics classes of ASE 3.27 (ase/md/verlet.py,
// langevin.py, bussi.py, nose_hoover_chain.py, nvtberendsen.py, langevinbaoab.py; LGPL-2.1-or-later, (c) the ASE
// developers, https://gitlab.com/ase/ase) in their coefficients and their order of operations; see NOTICE.md.
#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cmath>
#include <cstdint>

#include "cell.hpp"

namespace loup {

constexpr double ASE_FS = 0.09822694788464063;
constexpr double ASE_KB = 8.617330337217213e-5;

// Maximum over atoms and steps of the squared per-step displacement, as float bits (ordered like the floats
// themselves for non-negative values), for loup_get_step_displacement (the skin choice of loupmd.simulation) and
// the saved state; the MD loop itself checks every step's list exactly and does not read it. It decays in windows:
// max_step_disp2[0] is the maximum of the current window, [1] that of the previous one, and readers take the larger,
// so one fast step is forgotten two windows later (review item S2) while the value never falls below what the
// current window has seen. rotate_step_disp_kernel ends a window (run_md_loop decides when).
__device__ __forceinline__ void record_step_disp2(double d2, unsigned int* max_step_disp2) {
    const unsigned int bits = __float_as_uint((float)d2);
    const unsigned int m = __reduce_max_sync(0xffffffffu, bits);
    if ((threadIdx.x & 31) == 0 && m != 0u) atomicMax(max_step_disp2, m);
}

__global__ void rotate_step_disp_kernel(unsigned int* __restrict__ max_step_disp2) {
    max_step_disp2[1] = max_step_disp2[0];
    max_step_disp2[0] = 0u;
}

__global__ void nve_first_half_kernel(
    int N, double dt_ase,
    const double* __restrict__ forces,
    const double* __restrict__ inv_masses,
    double* __restrict__ pos64,
    double* __restrict__ vel64,
    unsigned int* __restrict__ max_step_disp2
) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    double d2 = 0.0;
    if (i < N) {
        double im = inv_masses[i];
        double half_dt_im = 0.5 * dt_ase * im;
        #pragma unroll
        for (int c = 0; c < 3; ++c) {
            int idx = i * 3 + c;
            double v = vel64[idx] + half_dt_im * forces[idx];
            vel64[idx] = v;
            const double dx = dt_ase * v;
            pos64[idx] += dx;
            d2 += dx * dx;
        }
    }
    record_step_disp2(d2, max_step_disp2);
}

__global__ void nve_second_half_kernel(
    int N, double dt_ase,
    const double* __restrict__ forces,
    const double* __restrict__ inv_masses,
    double* __restrict__ vel64
) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    double half_dt_im = 0.5 * dt_ase * inv_masses[i];
    #pragma unroll
    for (int c = 0; c < 3; ++c) {
        int idx = i * 3 + c;
        vel64[idx] += half_dt_im * forces[idx];
    }
}

// The noise coefficients of this step come from the device (target[2..4]: ASE's c3, c4, c5 without the mass
// factor, for the step's target temperature), so a ramp can move them every step and a changed temperature needs
// no new graph. The second half-kick's first thread forms them for the next step.
// S106: 32 atoms per 96-thread block. Thread (atom i, c) draws the c-th normal pair of atom i at Philox offset
// step * 16 + 4 c: the same 32-bit words, and so the same noise, as the three sequential curand_normal2_double calls
// of the former one-thread-per-atom kernel (each consumes 4 words from an aligned position; langevin_noise_kernel
// still draws them so), in a third of the double-precision latency chain. The same thread then updates component c
// of atom i (contiguous across the block). Offset counts 32-bit outputs; the three pairs consume 3 x 4 = 12, so 16
// per step keeps consecutive steps on disjoint words.
__global__ void __launch_bounds__(96) langevin_first_half_kernel(
    int N, double dt_ase, double c1, double c2, const double* __restrict__ target,
    unsigned long long seed, const unsigned long long* __restrict__ step_counter,
    const double* __restrict__ forces,
    const double* __restrict__ inv_masses,
    const double* __restrict__ sqrt_inv_masses,
    double* __restrict__ pos64,
    double* __restrict__ vel64,
    double* __restrict__ rnd_vel_save,
    unsigned int* __restrict__ max_step_disp2
) {
    __shared__ double s_n[32][6];  // per atom: xi[0..2], eta[0..2] = the three pairs in draw order
    __shared__ double s_d2[32][3];
    const int t = threadIdx.x, a = t / 3, c = t - 3 * a;
    const int i = blockIdx.x * 32 + a;
    if (i < N) {
        curandStatePhilox4_32_10_t rng;
        curand_init(seed, (unsigned long long)i, *step_counter * 16ULL + 4ULL * c, &rng);
        const double2 n = curand_normal2_double(&rng);
        s_n[a][2 * c] = n.x;
        s_n[a][2 * c + 1] = n.y;
    }
    __syncthreads();
    double dx = 0.0;
    if (i < N) {
        const double xi = s_n[a][c], eta = s_n[a][3 + c];
        const double im = inv_masses[i];
        const double sim = sqrt_inv_masses[i];
        const double c3 = target[2] * sim;
        const double c4 = target[3] * sim;
        const double c5 = target[4] * sim;
        const int idx = i * 3 + c;
        const double rnd_p = c5 * eta;
        const double rnd_v = c3 * xi - c4 * eta;
        rnd_vel_save[idx] = rnd_v;
        const double v = vel64[idx] + c1 * forces[idx] * im - c2 * vel64[idx] + rnd_v;
        dx = dt_ase * v + rnd_p;
        pos64[idx] += dx;
        vel64[idx] = (dx - rnd_p) / dt_ase;
    }
    s_d2[a][c] = dx * dx;
    __syncthreads();
    if (t < 32) record_step_disp2(s_d2[t][0] + s_d2[t][1] + s_d2[t][2], max_step_disp2);
}

// ---- fix_com: the noise of a step conditioned on a centre of mass at rest ----
// Both random terms of an atom have a covariance proportional to 1/m_i, so their conditional mean, given that the
// mass-weighted sum over all atoms is zero, is the same mass-weighted mean for every atom. The noise is therefore
// drawn in a pass of its own that also sums m_i * rnd over the atoms (com[0..2]: positions' term, com[3..5]:
// velocities'); the half-kick then subtracts com / M. Same random numbers as langevin_first_half_kernel.
__global__ void langevin_noise_kernel(
    int N, const double* __restrict__ target,
    unsigned long long seed, const unsigned long long* __restrict__ step_counter,
    const double* __restrict__ masses,
    const double* __restrict__ sqrt_inv_masses,
    double* __restrict__ rnd_pos,
    double* __restrict__ rnd_vel,
    double* __restrict__ com
) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    double sums[6] = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
    if (i < N) {
        unsigned long long step = *step_counter;
        curandStatePhilox4_32_10_t rng;
        curand_init(seed, (unsigned long long)i, step * 16ULL, &rng);
        double2 n0 = curand_normal2_double(&rng);
        double2 n1 = curand_normal2_double(&rng);
        double2 n2 = curand_normal2_double(&rng);
        double xi[3]  = {n0.x, n0.y, n1.x};
        double eta[3] = {n1.y, n2.x, n2.y};
        double sim = sqrt_inv_masses[i];
        double c3 = target[2] * sim;
        double c4 = target[3] * sim;
        double c5 = target[4] * sim;
        double m = masses[i];
        #pragma unroll
        for (int c = 0; c < 3; ++c) {
            double rnd_p = c5 * eta[c];
            double rnd_v = c3 * xi[c] - c4 * eta[c];
            rnd_pos[i * 3 + c] = rnd_p;
            rnd_vel[i * 3 + c] = rnd_v;
            sums[c] = m * rnd_p;
            sums[3 + c] = m * rnd_v;
        }
    }
    #pragma unroll
    for (int k = 0; k < 6; ++k) {
        double s = sums[k];
        #pragma unroll
        for (int off = 16; off > 0; off >>= 1) s += __shfl_xor_sync(0xffffffffu, s, off);
        if ((threadIdx.x & 31) == 0 && s != 0.0) atomicAdd(com + k, s);
    }
}

// The first half-kick with the noise of langevin_noise_kernel minus its mass-weighted mean. Writes the corrected
// velocity noise back for the second half-kick.
__global__ void langevin_first_half_fixcom_kernel(
    int N, double dt_ase, double c1, double c2, double inv_total_mass,
    const double* __restrict__ com,
    const double* __restrict__ forces,
    const double* __restrict__ inv_masses,
    const double* __restrict__ rnd_pos,
    double* __restrict__ rnd_vel,
    double* __restrict__ pos64,
    double* __restrict__ vel64,
    unsigned int* __restrict__ max_step_disp2
) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    double d2 = 0.0;
    if (i < N) {
        double im = inv_masses[i];
        #pragma unroll
        for (int c = 0; c < 3; ++c) {
            int idx = i * 3 + c;
            double rnd_p = rnd_pos[idx] - com[c] * inv_total_mass;
            double rnd_v = rnd_vel[idx] - com[3 + c] * inv_total_mass;
            rnd_vel[idx] = rnd_v;
            double v = vel64[idx] + c1 * forces[idx] * im - c2 * vel64[idx] + rnd_v;
            double dx = dt_ase * v + rnd_p;
            pos64[idx] += dx;
            vel64[idx] = (dx - rnd_p) / dt_ase;
            d2 += dx * dx;
        }
    }
    record_step_disp2(d2, max_step_disp2);
}

// The total momentum, summed into com[0..2] (zeroed by the caller), and its removal: v -= P / M.
__global__ void momentum_sum_kernel(int N, const double* __restrict__ masses, const double* __restrict__ vel64,
                                    double* __restrict__ com) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    #pragma unroll
    for (int c = 0; c < 3; ++c) {
        double s = i < N ? masses[i] * vel64[i * 3 + c] : 0.0;
        #pragma unroll
        for (int off = 16; off > 0; off >>= 1) s += __shfl_xor_sync(0xffffffffu, s, off);
        if ((threadIdx.x & 31) == 0 && s != 0.0) atomicAdd(com + c, s);
    }
}

__global__ void momentum_remove_kernel(int N, double inv_total_mass, const double* __restrict__ com,
                                       double* __restrict__ vel64) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    #pragma unroll
    for (int c = 0; c < 3; ++c) vel64[i * 3 + c] -= com[c] * inv_total_mass;
}

// Also advances the step counter and the thermostat's target: target[0] += target[1] (the ramp's change per step),
// then the next step's noise coefficients target[2..4] = a3, a4, a5 times sigma = sqrt(2 gamma kB T). Every
// first-half read of them for this step has completed.
__global__ void langevin_second_half_kernel(
    int N, double c1, double c2,
    const double* __restrict__ forces,
    const double* __restrict__ inv_masses,
    const double* __restrict__ rnd_vel_save,
    double* __restrict__ vel64,
    unsigned long long* __restrict__ step_counter,
    double* __restrict__ target, double a3, double a4, double a5, double two_fr_kb
) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i == 0) {
        (*step_counter) += 1ULL;
        const double next = target[0] + target[1];
        const double sigma = sqrt(two_fr_kb * fmax(next, 0.0));
        target[0] = next;
        target[2] = a3 * sigma;
        target[3] = a4 * sigma;
        target[4] = a5 * sigma;
    }
    if (i >= N) return;
    double im = inv_masses[i];
    #pragma unroll
    for (int c = 0; c < 3; ++c) {
        int idx = i * 3 + c;
        vel64[idx] += c1 * forces[idx] * im - c2 * vel64[idx] + rnd_vel_save[idx];
    }
}

// ---- CSVR: canonical sampling through velocity rescaling (Bussi, Donadio, Parrinello, J. Chem. Phys. 126, 014101
// (2007)), as ASE 3.27's Bussi does it: at the start of a step the velocities are scaled by alpha of equation A7,
// then the step is velocity Verlet. ----
// A step's noise: R1, a standard normal, and the sum of ndof - 1 squared standard normals, drawn as a chi-square
// variate, 2 Gamma((ndof - 1) / 2) (Marsaglia and Tsang, ACM Trans. Math. Softw. 26, 363 (2000)). One Philox stream
// apart from the atoms' (their subsequences are the atom indices), 256 words per step: the normal pair takes 4, a
// shape below 1 takes 2, and each of at most 32 rounds takes 6. A round accepts with a probability above 0.95.
constexpr unsigned long long kCsvrSequence = 1ULL << 40;

__device__ __forceinline__ void csvr_draw(unsigned long long seed, unsigned long long step, int ndof,
                                          double* normal, double* chi2) {
    curandStatePhilox4_32_10_t rng;
    curand_init(seed, kCsvrSequence, step * 256ULL, &rng);
    const double2 first = curand_normal2_double(&rng);
    *normal = first.x;
    *chi2 = 0.0;
    if (ndof <= 1) return;  // no further degrees of freedom
    double shape = 0.5 * (double)(ndof - 1);
    double boost = 1.0;
    if (shape < 1.0) {  // Gamma(a) = Gamma(a + 1) U^(1 / a)
        boost = pow(curand_uniform_double(&rng), 1.0 / shape);
        shape += 1.0;
    }
    const double d = shape - 1.0 / 3.0;
    const double c = 1.0 / sqrt(9.0 * d);
    double x = first.y;
    double gamma = d;  // the distribution's bulk; reached only if all 32 rounds reject
    for (int round = 0; round < 32; ++round) {
        if (round > 0) x = curand_normal2_double(&rng).x;
        const double u = curand_uniform_double(&rng);
        double v = 1.0 + c * x;
        if (v <= 0.0) continue;
        v = v * v * v;
        const double x2 = x * x;
        if (u < 1.0 - 0.0331 * x2 * x2 || log(u) < 0.5 * x2 + d * (1.0 - v + log(v))) {
            gamma = d * v;
            break;
        }
    }
    *chi2 = 2.0 * gamma * boost;
}

// Testing only (loup_debug_csvr_noise): the draws of steps first_step .. first_step + n - 1.
__global__ void csvr_noise_debug_kernel(unsigned long long seed, unsigned long long first_step, int n, int ndof,
                                        double* __restrict__ normal, double* __restrict__ chi2) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    csvr_draw(seed, first_step + (unsigned long long)i, ndof, normal + i, chi2 + i);
}

// One thread, after kinetic_energy_kernel has summed the kinetic energy into work[0]: alpha of this step into
// work[1], the energy the scaling adds into state[0] (ASE's transferred_energy), work[0] back to zero for the next
// step. Advances the step counter (the offset of the noise) and the target (target[0] += target[1], the ramp's
// change per step). A system at rest has nothing to scale: alpha is 1 until the forces have set it in motion.
__global__ void csvr_alpha_kernel(int ndof, double exp_term, double kb, unsigned long long seed,
                                  unsigned long long* __restrict__ step_counter, double* __restrict__ target,
                                  double* __restrict__ work, double* __restrict__ state) {
    const unsigned long long step = *step_counter;
    *step_counter = step + 1ULL;
    const double temp = fmax(target[0], 0.0);
    target[0] += target[1];
    const double kinetic = work[0];
    work[0] = 0.0;
    double alpha = 1.0;
    if (kinetic > 1e-100) {
        double normal, chi2;
        csvr_draw(seed, step, ndof, &normal, &chi2);
        // ASE's order of operations: energy_scaling_term = (1 - e) K_target / K / ndof, K_target = kT ndof / 2.
        const double target_kinetic = 0.5 * (temp * kb) * (double)ndof;
        const double scaling = (1.0 - exp_term) * target_kinetic / kinetic / (double)ndof;
        alpha = sqrt(exp_term + scaling * (chi2 + normal * normal) + 2.0 * normal * sqrt(exp_term * scaling));
        state[0] += (alpha * alpha - 1.0) * kinetic;
    }
    work[1] = alpha;
}

// Velocity Verlet's first half with the velocities scaled by alpha (work[1]) first.
__global__ void csvr_first_half_kernel(
    int N, double dt_ase, const double* __restrict__ work,
    const double* __restrict__ forces,
    const double* __restrict__ inv_masses,
    double* __restrict__ pos64,
    double* __restrict__ vel64,
    unsigned int* __restrict__ max_step_disp2
) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    double d2 = 0.0;
    if (i < N) {
        const double alpha = work[1];
        double half_dt_im = 0.5 * dt_ase * inv_masses[i];
        #pragma unroll
        for (int c = 0; c < 3; ++c) {
            int idx = i * 3 + c;
            double v = alpha * vel64[idx] + half_dt_im * forces[idx];
            vel64[idx] = v;
            const double dx = dt_ase * v;
            pos64[idx] += dx;
            d2 += dx * dx;
        }
    }
    record_step_disp2(d2, max_step_disp2);
}

// ---- Nose-Hoover chain (Martyna, Klein, Tuckerman 1992; Tuckerman et al. 2006), as ASE 3.27's
// NoseHooverChainNVT: the chain for dt / 2, a half kick, the drift, a half kick, the chain for dt / 2. ----
// One half of the chain, by one thread, after kinetic_energy_kernel has summed the kinetic energy into work[0].
// ASE scales the momenta and sums p^2 / m again after each of its 3 tloop sub-steps; a scaling by s multiplies
// that sum by s^2, so the sum is carried along and the velocities are scaled once by the product of the s
// (work[1]), as FastMACE does: the same algebra, different at rounding level.
//   state[0]: minus the thermostat's energy, N_f kT eta_0 + kT sum_{j>0} eta_j + sum_j p_j^2 / (2 Q_j), so that the
//             thermo row's conserved quantity is E_pot + E_kin - state[0] (ASE's get_conserved_energy);
//   state[1 .. tchain]: eta; state[1 + tchain .. 2 tchain]: p_eta.
// Q_0 = N_f q and Q_j = q with q = kT_mass tdamp^2; `ndof` (N_f) stands where ASE has 3 N. `delta` is dt / 2 in
// ASE time units. kT is the target of this step (target[0]); with `advance` the target moves on by target[1]
// afterwards (the second half of a step).
constexpr int kNhcMaxChain = 16;

__global__ void nhc_half_kernel(int ndof, int tchain, int tloop, double delta, double q, double kb, int advance,
                                double* __restrict__ target, double* __restrict__ work, double* __restrict__ state) {
    const double kT = kb * fmax(target[0], 0.0);
    if (advance) target[0] += target[1];
    double eta[kNhcMaxChain], p[kNhcMaxChain], Q[kNhcMaxChain];
    for (int j = 0; j < tchain; ++j) {
        eta[j] = state[1 + j];
        p[j] = state[1 + tchain + j];
        Q[j] = j == 0 ? (double)ndof * q : q;
    }
    double k2 = 2.0 * work[0];  // sum of p^2 / m
    work[0] = 0.0;
    double scale = 1.0;
    // The fourth-order Suzuki-Yoshida coefficients, ASE's expressions (Yoshida 1990).
    const double cbrt2 = cbrt(2.0);
    const double coeffs[3] = {1.0 / (2.0 - cbrt2), -cbrt2 / (2.0 - cbrt2), 1.0 / (2.0 - cbrt2)};
    for (int loop = 0; loop < tloop; ++loop) {
        for (int c = 0; c < 3; ++c) {
            const double d = coeffs[c] * delta / (double)tloop;
            const double d2 = 0.5 * d, d4 = 0.25 * d;
            for (int pass = 0; pass < 2; ++pass) {  // the chain down, the particles, the chain up
                for (int i = 0; i < tchain; ++i) {
                    const int j = pass == 0 ? tchain - 1 - i : i;
                    if (j < tchain - 1) p[j] *= exp(-d4 * p[j + 1] / Q[j + 1]);
                    const double g = j == 0 ? k2 - (double)ndof * kT : p[j - 1] * p[j - 1] / Q[j - 1] - kT;
                    p[j] += d2 * g;
                    if (j < tchain - 1) p[j] *= exp(-d4 * p[j + 1] / Q[j + 1]);
                }
                if (pass == 0) {
                    for (int j = 0; j < tchain; ++j) eta[j] += d * p[j] / Q[j];
                    const double s = exp(-d * p[0] / Q[0]);
                    scale *= s;
                    k2 *= s * s;
                }
            }
        }
    }
    double energy = (double)ndof * kT * eta[0];
    for (int j = 0; j < tchain; ++j) {
        if (j > 0) energy += kT * eta[j];
        energy += 0.5 * p[j] * p[j] / Q[j];
        state[1 + j] = eta[j];
        state[1 + tchain + j] = p[j];
    }
    state[0] = -energy;
    work[1] = scale;
}

// ---- Berendsen thermostat (Berendsen et al. 1984), as ASE 3.27's NVTBerendsen: at the start of a step the
// velocities are scaled by lambda = sqrt(1 + (T0 / T - 1) dt / taut), kept within [0.9, 1.1], then the step is
// velocity Verlet. Not canonical: for equilibration. ----
// One thread, after kinetic_energy_kernel has summed the kinetic energy into work[0]: lambda into work[1]; T counts
// `ndof` degrees of freedom; T0 is the target of this step (target[0]), which then moves on by target[1]. A
// system at rest has an infinite T0 / T, which ASE's bounds turn into 1.1.
__global__ void berendsen_scale_kernel(int ndof, double dt_over_tau, double kb, double* __restrict__ target,
                                       double* __restrict__ work) {
    const double t0 = fmax(target[0], 0.0);
    target[0] += target[1];
    const double kinetic = work[0];
    work[0] = 0.0;
    work[5] = kinetic;  // for the barostat's ideal-gas pressure (berendsen_npt_kernel)
    double scale = t0 > 0.0 ? 1.1 : 1.0;
    if (kinetic > 1e-100) {
        const double temp = 2.0 * kinetic / ((double)ndof * kb);
        scale = fmin(fmax(sqrt(1.0 + (t0 / temp - 1.0) * dt_over_tau), 0.9), 1.1);
    }
    work[1] = scale;
}

// v *= work[1]: the second chain half of a Nose-Hoover step.
__global__ void scale_velocities_kernel(int N, const double* __restrict__ work, double* __restrict__ vel64) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    const double s = work[1];
    #pragma unroll
    for (int c = 0; c < 3; ++c) vel64[i * 3 + c] *= s;
}

__global__ void kinetic_energy_kernel(
    int N,
    const double* __restrict__ masses,
    const double* __restrict__ vel64,
    double* __restrict__ out_ke
) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    double ke = 0.0;
    if (i < N) {
        double vx = vel64[i * 3 + 0];
        double vy = vel64[i * 3 + 1];
        double vz = vel64[i * 3 + 2];
        ke = 0.5 * masses[i] * (vx * vx + vy * vy + vz * vz);
    }
    #pragma unroll
    for (int off = 16; off > 0; off >>= 1) ke += __shfl_xor_sync(0xffffffffu, ke, off);
    __shared__ double s_ke[8];
    int warp = threadIdx.x >> 5;
    int lane = threadIdx.x & 31;
    if (lane == 0) s_ke[warp] = ke;
    __syncthreads();
    if (threadIdx.x == 0) {
        double sum = 0.0;
        int nw = blockDim.x >> 5;
        for (int w = 0; w < nw; ++w) sum += s_ke[w];
        atomicAdd(out_ke, sum);
    }
}

// ---- Langevin BAOAB NPT: ASE 3.27's LangevinBAOAB with a barostat (Leimkuhler and Matthews' BAOAB for the atoms,
// Quigley and Probert's Langevin-Hoover barostat for the cell), hydrostatic or with the full cell. ----
// The barostat's momentum p_eps and the cell force force_eps live in the integrator's state slots (state[1..9] and
// state[10..18]; the hydrostatic mode uses the first of each), so they travel in the state block. One step:
//   baoab_cell_first_kernel (one thread): barostat B (p += dt/2 F); the cell's first half step as a matrix M1 for
//     the atoms; the matrix of the atoms' O step (friction plus the barostat's drag on the velocities); barostat O
//     (friction and noise on p); the cell's second half step M2 from the new p; the cell's own deformation M1 M2.
//   baoab_first_kernel (per atom): B, x <- x M1, A, O, A, x <- x M2.
//   [force pass with stress]
//   kinetic_tensor_kernel, baoab_cell_second_kernel (one thread): the cell force from the velocities before the
//     last kick, the virial and the volume; barostat B. Then the atoms' last B (nve_second_half_kernel).
// Work slots (work[]): [0..5] sum m v v (xx, xy, xz, yy, yz, zz), [8..16] M1, [17..25] M2, [26..34] the O step's
// matrix, [35] the noise amplitude without the atom's 1 / sqrt(m).
constexpr int kBaoabM1 = 8, kBaoabM2 = 17, kBaoabVm = 26, kBaoabAmp = 35;
constexpr int kBaoabP = 1, kBaoabF = 10;

__device__ void mat3_mul_d(const double* a, const double* b, double* out) {
    for (int r = 0; r < 3; ++r)
        for (int c = 0; c < 3; ++c)
            out[r * 3 + c] = a[r * 3 + 0] * b[0 * 3 + c] + a[r * 3 + 1] * b[1 * 3 + c] + a[r * 3 + 2] * b[2 * 3 + c];
}

// exp(a) of a 3 x 3 matrix: scaling and squaring with a Taylor series, as FastMACE's expm_3x3 (exact in float64
// for |a| <= 1; a barostat half step moves |a| ~ 1e-4).
__device__ void mat3_expm(const double* a_in, double* out) {
    const int scaling = 2, degree = 14;
    double a[9], term[9], next[9];
    for (int i = 0; i < 9; ++i) {
        a[i] = a_in[i] / (double)(1 << scaling);
        term[i] = out[i] = (i % 4 == 0) ? 1.0 : 0.0;
    }
    for (int k = 1; k <= degree; ++k) {
        mat3_mul_d(term, a, next);
        for (int i = 0; i < 9; ++i) {
            term[i] = next[i] / (double)k;
            out[i] += term[i];
        }
    }
    for (int s = 0; s < scaling; ++s) {
        mat3_mul_d(out, out, next);
        for (int i = 0; i < 9; ++i) out[i] = next[i];
    }
}

__device__ void mat3_transpose(const double* a, double* out) {
    for (int r = 0; r < 3; ++r)
        for (int c = 0; c < 3; ++c) out[r * 3 + c] = a[c * 3 + r];
}

// The cell's half step for the atoms: x <- x m. Hydrostatic: every length times cbrt(exp(3 dt/2 p / W)); full:
// m = expm(dt/2 p / W)^T (ASE: cell @ expm(...).T, atoms scaled with it).
__device__ void baoab_cell_half(int full, double dt, double mass, const double* p, double* m) {
    if (!full) {
        const double f = cbrt(exp(0.5 * dt * 3.0 * p[0] / mass));
        for (int i = 0; i < 9; ++i) m[i] = (i % 4 == 0) ? f : 0.0;
        return;
    }
    double a[9], e[9];
    for (int i = 0; i < 9; ++i) a[i] = 0.5 * dt * p[i] / mass;
    mat3_expm(a, e);
    mat3_transpose(e, m);
}

__global__ void baoab_cell_first_kernel(
    int full, double dt, double gamma, double ou_unit, double gamma_b, double ou_b_unit, double mass, int ndof,
    double kb, unsigned long long seed, const unsigned long long* __restrict__ step_counter,
    double* __restrict__ target, double* __restrict__ state, double* __restrict__ work, CellDev* __restrict__ cell
) {
    const double temp = fmax(target[0], 0.0);
    target[0] += target[1];
    const double sqrt_kt = sqrt(kb * temp);
    double* p = state + kBaoabP;
    const double* f = state + kBaoabF;
    const int np = full ? 9 : 1;
    for (int i = 0; i < np; ++i) p[i] += 0.5 * dt * f[i];                    // barostat B
    baoab_cell_half(full, dt, mass, p, work + kBaoabM1);                      // barostat A, first half
    // O for the atoms: v <- v exp(-(gamma + drag) dt), drag = (1 + 3 / Ndof) p / W (hydrostatic) or the matrix
    // (p + Tr(p) / Ndof 1) / W (Quigley and Probert 2004, Eq. 5b; ASE 3.27 adds the trace to all nine elements)
    if (!full) {
        const double drag = (1.0 + 3.0 / (double)ndof) * p[0] / mass;
        const double e = exp(-(gamma + drag) * dt);
        for (int i = 0; i < 9; ++i) work[kBaoabVm + i] = (i % 4 == 0) ? e : 0.0;
    } else {
        const double trace = (p[0] + p[4] + p[8]) / (double)ndof;
        double a[9], e[9];
        for (int i = 0; i < 9; ++i) a[i] = -(((i % 4 == 0) ? gamma : 0.0) + (p[i] + ((i % 4 == 0) ? trace : 0.0)) / mass) * dt;
        mat3_expm(a, e);
        mat3_transpose(e, work + kBaoabVm);
    }
    work[kBaoabAmp] = ou_unit * sqrt_kt;
    if (gamma_b > 0.0) {                                                       // barostat O
        const double decay = exp(-gamma_b * dt);
        const double amp = ou_b_unit * sqrt_kt;
        for (int i = 0; i < np; ++i) p[i] *= decay;
        if (amp > 0.0) {
            // Its own Philox subsequence, beyond every atom's; 16 outputs per step as the atoms' draws.
            curandStatePhilox4_32_10_t rng;
            curand_init(seed, 1ULL << 41, step_counter[0] * 16ULL, &rng);
            if (!full) {
                p[0] += amp * curand_normal2_double(&rng).x;
            } else {
                double r[9];
                for (int i = 0; i < 8; i += 2) {
                    const double2 n = curand_normal2_double(&rng);
                    r[i] = n.x;
                    r[i + 1] = n.y;
                }
                r[8] = curand_normal2_double(&rng).x;
                for (int a = 0; a < 3; ++a)
                    for (int b = 0; b < 3; ++b) p[a * 3 + b] += amp * 0.5 * (r[a * 3 + b] + r[b * 3 + a]);
            }
        }
    }
    baoab_cell_half(full, dt, mass, p, work + kBaoabM2);                      // barostat A, second half
    mat3_mul_d(work + kBaoabM1, work + kBaoabM2, cell->move);                 // the cell: h <- h M1 M2
    cell->has_move = 1;
}

__global__ void baoab_first_kernel(
    int N, double dt, const double* __restrict__ work, unsigned long long seed,
    const unsigned long long* __restrict__ step_counter, const double* __restrict__ forces,
    const double* __restrict__ inv_masses, const double* __restrict__ sqrt_inv_masses,
    double* __restrict__ pos64, double* __restrict__ vel64, unsigned int* __restrict__ max_step_disp2
) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    double d2 = 0.0;
    if (i < N) {
        const double* m1 = work + kBaoabM1;
        const double* m2 = work + kBaoabM2;
        const double* vm = work + kBaoabVm;
        const double amp = work[kBaoabAmp] * sqrt_inv_masses[i];
        const double half_dt_im = 0.5 * dt * inv_masses[i];
        double x[3], v[3], t[3];
        #pragma unroll
        for (int c = 0; c < 3; ++c) {
            x[c] = pos64[i * 3 + c];
            v[c] = vel64[i * 3 + c] + half_dt_im * forces[i * 3 + c];        // B
        }
        const double x0[3] = {x[0], x[1], x[2]};
        #pragma unroll
        for (int c = 0; c < 3; ++c) t[c] = x[0] * m1[c] + x[1] * m1[3 + c] + x[2] * m1[6 + c];   // barostat A
        #pragma unroll
        for (int c = 0; c < 3; ++c) x[c] = t[c] + 0.5 * dt * v[c];           // A
        #pragma unroll
        for (int c = 0; c < 3; ++c) t[c] = v[0] * vm[c] + v[1] * vm[3 + c] + v[2] * vm[6 + c];   // O
        if (amp > 0.0) {
            curandStatePhilox4_32_10_t rng;
            curand_init(seed, (unsigned long long)i, step_counter[0] * 16ULL, &rng);
            const double2 n0 = curand_normal2_double(&rng);
            const double2 n1 = curand_normal2_double(&rng);
            t[0] += amp * n0.x;
            t[1] += amp * n0.y;
            t[2] += amp * n1.x;
        }
        #pragma unroll
        for (int c = 0; c < 3; ++c) {
            v[c] = t[c];
            x[c] += 0.5 * dt * v[c];                                          // A
        }
        #pragma unroll
        for (int c = 0; c < 3; ++c) {
            const double xn = x[0] * m2[c] + x[1] * m2[3 + c] + x[2] * m2[6 + c];   // barostat A
            pos64[i * 3 + c] = xn;
            vel64[i * 3 + c] = v[c];
            d2 += (xn - x0[c]) * (xn - x0[c]);
        }
    }
    record_step_disp2(d2, max_step_disp2);
}

// sum_i m_i v_i v_i^T: xx, xy, xz, yy, yz, zz into out[0..5] (zeroed by baoab_cell_second_kernel).
__global__ void kinetic_tensor_kernel(int N, const double* __restrict__ masses, const double* __restrict__ vel64,
                                      double* __restrict__ out) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    double k[6] = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
    if (i < N) {
        const double m = masses[i];
        const double vx = vel64[i * 3 + 0], vy = vel64[i * 3 + 1], vz = vel64[i * 3 + 2];
        k[0] = m * vx * vx; k[1] = m * vx * vy; k[2] = m * vx * vz;
        k[3] = m * vy * vy; k[4] = m * vy * vz; k[5] = m * vz * vz;
    }
    __shared__ double s_k[6][8];
    const int warp = threadIdx.x >> 5;
    #pragma unroll
    for (int a = 0; a < 6; ++a) {
        double v = k[a];
        #pragma unroll
        for (int off = 16; off > 0; off >>= 1) v += __shfl_xor_sync(0xffffffffu, v, off);
        if ((threadIdx.x & 31) == 0) s_k[a][warp] = v;
    }
    __syncthreads();
    if (threadIdx.x < 6) {
        double sum = 0.0;
        const int nw = blockDim.x >> 5;
        for (int w = 0; w < nw; ++w) sum += s_k[threadIdx.x][w];
        atomicAdd(out + threadIdx.x, sum);
    }
}

// The cell force (LangevinBAOAB._update_force_eps) from the kinetic tensor in work[0..5], the force pass's virial
// (dE / d strain: the stress times the volume) and the cell's volume; ext is the external stress in eV/A^3 (minus
// the target pressure). With `kick` also barostat B (p += dt/2 F); with `advance` the step counter moves on.
__global__ void baoab_cell_second_kernel(
    int full, int kick, int advance, double dt, int ndof, double ext, const double* __restrict__ virial,
    const CellDev* __restrict__ cell, double* __restrict__ work, double* __restrict__ state,
    unsigned long long* __restrict__ step_counter
) {
    const double volume = cell->volume;
    double* p = state + kBaoabP;
    double* f = state + kBaoabF;
    const double ke2 = work[0] + work[3] + work[5];
    if (!full) {
        const double tr_virial = -(virial[0] + virial[3] + virial[5]);       // -V Tr(stress)
        const double x = (ke2 + tr_virial) / (3.0 * volume);
        f[0] = 3.0 * volume * (x + ext) + (3.0 / (double)ndof) * ke2;
        if (kick) p[0] += 0.5 * dt * f[0];
    } else {
        const int map[9] = {0, 1, 2, 1, 3, 4, 2, 4, 5};
        for (int i = 0; i < 9; ++i) {
            const double x = (work[map[i]] - virial[map[i]]) / volume;
            const double unit = (i % 4 == 0) ? 1.0 : 0.0;
            f[i] = volume * (x + ext * unit) + ke2 / (double)ndof * unit;
            if (kick) p[i] += 0.5 * dt * f[i];
        }
    }
    for (int i = 0; i < 6; ++i) work[i] = 0.0;
    if (advance) step_counter[0] += 1ULL;
}

// ---- Martyna-Tobias-Klein NPT (Martyna, Tobias, Klein 1994), as ASE 3.27's IsotropicMTKNPT (the cell keeps its
// shape) and MTKNPT (the full cell): Nose-Hoover chains on the atoms and on the cell. ASE's step is
//   barostat chain, thermostat chain, cell kick, atom kick (dt/2 each); atom drift, cell drift (dt);
//   [forces and stress at the new positions and cell]
//   atom kick, cell kick, thermostat chain, barostat chain (dt/2 each).
// The first cell kick reads the stress of the last force pass plus the ideal-gas part of the momenta of then.
// State slots: [0] minus what the conserved quantity holds beside E_pot + E_kin (both chains' energies, the cell's
// kinetic energy and P V), [1..9] the cell momentum (the isotropic mode uses the first), then eta and p_eta of
// the thermostat (tchain each) and xi and p_xi of the barostat (pchain each). Work slots: [1] and [6] velocity
// scalings (the second half's is where scale_velocities_kernel reads it), [8..16] and [17..25] the atom kick's
// matrices (v <- v KD + dt/2 f/m KR), [26..34] and [35..43] the drift's (x <- x DG + dt v DR), [44..49] sum m v v.
// Counts: `ndof` stands where ASE has 3 N (and ndof / 3 where it has N), as in nhc_half_kernel; the barostat
// chain's own counts are ASE's (first mass 9 kT pdamp^2 in both modes; force and energy 1 kT isotropic, 9 kT full).
constexpr int kMtkMaxChain = 8;
constexpr int kMtkP = 1, kMtkChains = 10;
constexpr int kMtkKd = 8, kMtkKr = 17, kMtkDg = 26, kMtkDr = 35, kMtkScale = 6, kMtkK = 44;

// One Nose-Hoover chain for `delta`, as nhc_half_kernel's loop: k2 is twice the kinetic energy the chain is
// coupled to (carried along through its scalings), dof_force its count in the first link's force. Returns the
// product of the scalings.
__device__ double nhc_chain(int n, int loops, double delta, double kT, double dof_force, const double* Q,
                            double* eta, double* p, double k2) {
    double scale = 1.0;
    const double cbrt2 = cbrt(2.0);
    const double coeffs[3] = {1.0 / (2.0 - cbrt2), -cbrt2 / (2.0 - cbrt2), 1.0 / (2.0 - cbrt2)};
    for (int loop = 0; loop < loops; ++loop) {
        for (int c = 0; c < 3; ++c) {
            const double d = coeffs[c] * delta / (double)loops;
            const double d2 = 0.5 * d, d4 = 0.25 * d;
            for (int pass = 0; pass < 2; ++pass) {
                for (int i = 0; i < n; ++i) {
                    const int j = pass == 0 ? n - 1 - i : i;
                    if (j < n - 1) p[j] *= exp(-d4 * p[j + 1] / Q[j + 1]);
                    const double g = j == 0 ? k2 - dof_force * kT : p[j - 1] * p[j - 1] / Q[j - 1] - kT;
                    p[j] += d2 * g;
                    if (j < n - 1) p[j] *= exp(-d4 * p[j + 1] / Q[j + 1]);
                }
                if (pass == 0) {
                    for (int j = 0; j < n; ++j) eta[j] += d * p[j] / Q[j];
                    const double s = exp(-d * p[0] / Q[0]);
                    scale *= s;
                    k2 *= s * s;
                }
            }
        }
    }
    return scale;
}

// scipy.special.exprel: (exp(x) - 1) / x, 1 at 0.
__device__ double exprel_d(double x) { return fabs(x) < 1e-16 ? 1.0 : expm1(x) / x; }

// exp(a) and exprel(a) = sum_k a^k / (k + 1)! of a 3 x 3 matrix, as FastMACE's exp_and_exprel: b = a / 2^s,
// exprel(b) by Horner, exp(b) = 1 + b exprel(b), then s times exprel(2b) = exprel(b) (exp(b) + 1) / 2 and
// exp(2b) = exp(b)^2. For a symmetric a these are ASE's U f(L) U^T to rounding.
__device__ void mat3_exp_and_exprel(const double* a, double* e, double* r) {
    const int scaling = 4, degree = 14;
    double b[9], t[9];
    for (int i = 0; i < 9; ++i) {
        b[i] = a[i] / (double)(1 << scaling);
        r[i] = (i % 4 == 0) ? 1.0 : 0.0;
    }
    for (int k = degree - 1; k >= 1; --k) {
        mat3_mul_d(b, r, t);
        for (int i = 0; i < 9; ++i) r[i] = ((i % 4 == 0) ? 1.0 : 0.0) + t[i] / (double)(k + 1);
    }
    mat3_mul_d(b, r, t);
    for (int i = 0; i < 9; ++i) e[i] = ((i % 4 == 0) ? 1.0 : 0.0) + t[i];
    for (int s = 0; s < scaling; ++s) {
        double ep[9];
        for (int i = 0; i < 9; ++i) ep[i] = e[i] + ((i % 4 == 0) ? 1.0 : 0.0);
        mat3_mul_d(r, ep, t);
        for (int i = 0; i < 9; ++i) r[i] = 0.5 * t[i];
        mat3_mul_d(e, e, t);
        for (int i = 0; i < 9; ++i) e[i] = t[i];
    }
}

// exp(i L_(eps,2) delta): the cell momentum from the stress with the ideal-gas part. k: sum m v v of the momenta
// of now (xx, xy, xz, yy, yz, zz), virial: dE / d strain of the last force pass (the stress times the volume).
__device__ void mtk_kick_cell(int full, double delta, int ndof, double pressure, double volume, const double* k,
                              const double* virial, double* p) {
    const double ke2 = k[0] + k[3] + k[5];
    if (!full) {
        // pressure = -Tr(stress - K / V) / 3; G = 3 V (pressure - P) + sum(p^2 / m) / N
        const double internal = -((virial[0] + virial[3] + virial[5]) / volume - ke2 / volume) / 3.0;
        p[0] += delta * (3.0 * volume * (internal - pressure) + ke2 / ((double)ndof / 3.0));
        return;
    }
    const int map[9] = {0, 1, 2, 1, 3, 4, 2, 4, 5};
    for (int i = 0; i < 9; ++i) {
        const double unit = (i % 4 == 0) ? 1.0 : 0.0;
        const double minus_stress = -(virial[map[i]] / volume - k[map[i]] / volume);
        p[i] += delta * (volume * (minus_stress - pressure * unit) + ke2 / (double)ndof * unit);
    }
}

// The masses of both chains and the pointers into the state block.
struct MtkChains {
    double Q[kMtkMaxChain], R[kMtkMaxChain];
    double *eta, *p_eta, *xi, *p_xi;
};
__device__ void mtk_chains(int tchain, int pchain, int ndof, double q_t, double r_p, double* state, MtkChains* c) {
    for (int j = 0; j < tchain; ++j) c->Q[j] = j == 0 ? (double)ndof * q_t : q_t;
    for (int j = 0; j < pchain; ++j) c->R[j] = j == 0 ? 9.0 * r_p : r_p;
    c->eta = state + kMtkChains;
    c->p_eta = c->eta + tchain;
    c->xi = c->p_eta + tchain;
    c->p_xi = c->xi + pchain;
}

__device__ double mtk_cell_k2(int full, const double* p, double w) {
    if (!full) return p[0] * p[0] / w;
    double sum = 0.0;
    for (int i = 0; i < 9; ++i) sum += p[i] * p[i];
    return sum / w;
}

// The first half up to the drifts, by one thread, after kinetic_tensor_kernel: both chains, the cell kick, and the
// matrices of the atoms' kick and drift for mtk_first_atoms_kernel. q_t = kT_mass tdamp^2, r_p = kT_mass pdamp^2,
// w the cell's mass; pressure in eV/A^3.
__global__ void mtk_first_kernel(
    int full, double dt, int tchain, int tloop, int pchain, int ploop, int ndof, double q_t, double r_p, double w,
    double kb, double pressure, const double* __restrict__ target, double* __restrict__ state,
    double* __restrict__ work, const double* __restrict__ virial, CellDev* __restrict__ cell
) {
    const double kT = kb * fmax(target[0], 0.0);
    const double dt2 = 0.5 * dt;
    double* p = state + kMtkP;
    const int np = full ? 9 : 1;
    MtkChains c;
    mtk_chains(tchain, pchain, ndof, q_t, r_p, state, &c);
    const double sb = nhc_chain(pchain, ploop, dt2, kT, full ? 9.0 : 1.0, c.R, c.xi, c.p_xi, mtk_cell_k2(full, p, w));
    for (int i = 0; i < np; ++i) p[i] *= sb;
    double* tensor = work + kMtkK;
    const double st = nhc_chain(tchain, tloop, dt2, kT, (double)ndof, c.Q, c.eta, c.p_eta,
                                tensor[0] + tensor[3] + tensor[5]);
    double k[6];
    for (int i = 0; i < 6; ++i) {
        k[i] = st * st * tensor[i];  // of the velocities the thermostat has scaled
        tensor[i] = 0.0;
    }
    mtk_kick_cell(full, dt2, ndof, pressure, cell->volume, k, virial, p);
    work[kMtkScale] = st;
    if (!full) {
        const double x = (1.0 + 3.0 / (double)ndof) * p[0] * dt2 / w;
        const double rate = dt * p[0] / w;
        for (int i = 0; i < 9; ++i) {
            const double unit = (i % 4 == 0) ? 1.0 : 0.0;
            work[kMtkKd + i] = unit * exp(-x);
            work[kMtkKr + i] = unit * exprel_d(-x);
            work[kMtkDg + i] = unit * exp(rate);
            work[kMtkDr + i] = unit * exprel_d(rate);
        }
    } else {
        const double trace = (p[0] + p[4] + p[8]) / (double)ndof;
        double a[9];
        for (int i = 0; i < 9; ++i) a[i] = -(p[i] + ((i % 4 == 0) ? trace : 0.0)) * dt2 / w;
        mat3_exp_and_exprel(a, work + kMtkKd, work + kMtkKr);
        for (int i = 0; i < 9; ++i) a[i] = p[i] * dt / w;
        mat3_exp_and_exprel(a, work + kMtkDg, work + kMtkDr);
    }
    for (int i = 0; i < 9; ++i) cell->move[i] = work[kMtkDg + i];   // the cell drifts with the atoms: h <- h DG
    cell->has_move = 1;
}

// Every atom's first half: the thermostat's scaling, the kick with the cell momentum's drag, the drift.
__global__ void mtk_first_atoms_kernel(
    int N, double dt, const double* __restrict__ work, const double* __restrict__ forces,
    const double* __restrict__ inv_masses, double* __restrict__ pos64, double* __restrict__ vel64,
    unsigned int* __restrict__ max_step_disp2
) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    double d2 = 0.0;
    if (i < N) {
        const double* kd = work + kMtkKd;
        const double* kr = work + kMtkKr;
        const double* dg = work + kMtkDg;
        const double* dr = work + kMtkDr;
        const double st = work[kMtkScale];
        const double half_dt_im = 0.5 * dt * inv_masses[i];
        double x[3], v[3], a[3], t[3];
        #pragma unroll
        for (int c = 0; c < 3; ++c) {
            x[c] = pos64[i * 3 + c];
            v[c] = st * vel64[i * 3 + c];
            a[c] = half_dt_im * forces[i * 3 + c];
        }
        #pragma unroll
        for (int c = 0; c < 3; ++c)
            t[c] = v[0] * kd[c] + v[1] * kd[3 + c] + v[2] * kd[6 + c] + a[0] * kr[c] + a[1] * kr[3 + c] + a[2] * kr[6 + c];
        #pragma unroll
        for (int c = 0; c < 3; ++c) {
            v[c] = t[c];
            vel64[i * 3 + c] = v[c];
        }
        #pragma unroll
        for (int c = 0; c < 3; ++c) {
            const double xn = x[0] * dg[c] + x[1] * dg[3 + c] + x[2] * dg[6 + c] +
                              dt * (v[0] * dr[c] + v[1] * dr[3 + c] + v[2] * dr[6 + c]);
            pos64[i * 3 + c] = xn;
            d2 += (xn - x[c]) * (xn - x[c]);
        }
    }
    record_step_disp2(d2, max_step_disp2);
}

// The second half's atom kick, with the matrices of the first half (the cell momentum has not changed since).
__global__ void mtk_kick_kernel(int N, double dt, const double* __restrict__ work, const double* __restrict__ forces,
                                const double* __restrict__ inv_masses, double* __restrict__ vel64) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    const double* kd = work + kMtkKd;
    const double* kr = work + kMtkKr;
    const double half_dt_im = 0.5 * dt * inv_masses[i];
    double v[3], a[3];
    #pragma unroll
    for (int c = 0; c < 3; ++c) {
        v[c] = vel64[i * 3 + c];
        a[c] = half_dt_im * forces[i * 3 + c];
    }
    #pragma unroll
    for (int c = 0; c < 3; ++c)
        vel64[i * 3 + c] = v[0] * kd[c] + v[1] * kd[3 + c] + v[2] * kd[6 + c] + a[0] * kr[c] + a[1] * kr[3 + c] + a[2] * kr[6 + c];
}

// The rest of the second half, by one thread, after the atom kick and kinetic_tensor_kernel: the cell kick with
// the new stress, the thermostat chain (its scaling into work[1] for scale_velocities_kernel), the barostat
// chain, and what the conserved quantity holds beside E_pot + E_kin. The target moves on by target[1].
__global__ void mtk_second_kernel(
    int full, double dt, int tchain, int tloop, int pchain, int ploop, int ndof, double q_t, double r_p, double w,
    double kb, double pressure, double* __restrict__ target, double* __restrict__ state, double* __restrict__ work,
    const double* __restrict__ virial, const CellDev* __restrict__ cell
) {
    const double kT = kb * fmax(target[0], 0.0);
    target[0] += target[1];
    const double dt2 = 0.5 * dt;
    double* p = state + kMtkP;
    const int np = full ? 9 : 1;
    MtkChains c;
    mtk_chains(tchain, pchain, ndof, q_t, r_p, state, &c);
    double* tensor = work + kMtkK;
    mtk_kick_cell(full, dt2, ndof, pressure, cell->volume, tensor, virial, p);
    work[1] = nhc_chain(tchain, tloop, dt2, kT, (double)ndof, c.Q, c.eta, c.p_eta,
                        tensor[0] + tensor[3] + tensor[5]);
    for (int i = 0; i < 6; ++i) tensor[i] = 0.0;
    const double sb = nhc_chain(pchain, ploop, dt2, kT, full ? 9.0 : 1.0, c.R, c.xi, c.p_xi, mtk_cell_k2(full, p, w));
    for (int i = 0; i < np; ++i) p[i] *= sb;
    // ASE's get_conserved_energy beside the atoms' total energy
    double energy = (double)ndof * kT * c.eta[0];
    for (int j = 0; j < tchain; ++j) {
        if (j > 0) energy += kT * c.eta[j];
        energy += 0.5 * c.p_eta[j] * c.p_eta[j] / c.Q[j];
    }
    energy += (full ? 9.0 : 1.0) * kT * c.xi[0];
    for (int j = 0; j < pchain; ++j) {
        if (j > 0) energy += kT * c.xi[j];
        energy += 0.5 * c.p_xi[j] * c.p_xi[j] / c.R[j];
    }
    energy += 0.5 * mtk_cell_k2(full, p, w) + pressure * cell->volume;
    state[0] = -energy;
}

}  // namespace loup
