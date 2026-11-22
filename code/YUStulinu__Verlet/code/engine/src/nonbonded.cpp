#include "verlet/nonbonded.hpp"

#include <algorithm>
#include <cmath>
#include <map>
#include <stdexcept>

namespace verlet {

EwaldParams choose_ewald(double cutoff, double tolerance, Vec3 box) {
    EwaldParams p;
    p.cutoff = cutoff;
    p.tolerance = tolerance;
    p.alpha = std::sqrt(-std::log(2 * tolerance)) / cutoff;
    auto dim = [&](double L) { return fft_friendly_size(std::max(6, int(std::ceil(2 * p.alpha * L / (3 * std::pow(tolerance, 0.2)))))); };
    p.nx = dim(box.x);
    p.ny = dim(box.y);
    p.nz = dim(box.z);
    if (std::min({box.x, box.y, box.z}) <= 2 * cutoff)  // minimum image would miss periodic copies
        throw std::runtime_error("the box must be larger than twice the cutoff");
    return p;
}

// ---- PME --------------------------------------------------------------------

void PmeCpu::bspline(double w, int n, double* data, double* ddata) {
    for (int k = 0; k < n; ++k) data[k] = 0;
    data[n - 1] = 0;
    data[1] = w;
    data[0] = 1 - w;
    for (int j = 3; j < n; ++j) {
        double div = 1.0 / (j - 1);
        data[j - 1] = div * w * data[j - 2];
        for (int k = 1; k < j - 1; ++k) data[j - k - 1] = div * ((w + k) * data[j - k - 2] + (j - k - w) * data[j - k - 1]);
        data[0] = div * (1 - w) * data[0];
    }
    ddata[0] = -data[0];
    for (int k = 1; k < n; ++k) ddata[k] = data[k - 1] - data[k];
    double div = 1.0 / (n - 1);
    data[n - 1] = div * w * data[n - 2];
    for (int k = 1; k < n - 1; ++k) data[n - k - 1] = div * ((w + k) * data[n - k - 2] + (n - k - w) * data[n - k - 1]);
    data[0] = div * (1 - w) * data[0];
}

std::vector<double> PmeCpu::bspline_moduli(int K, int order) {
    // M_n at the integers 1..n-1
    std::vector<double> M(order, 0.0), dM(order);
    bspline(0.0, order, M.data(), dM.data());  // data[k] = M_n(n - 1 - k)
    std::vector<double> m(order + 1, 0.0);
    for (int k = 0; k < order; ++k) m[order - 1 - k + 0] = M[k];  // m[x] = M_n(x)
    std::vector<double> mod(K);
    for (int i = 0; i < K; ++i) {
        double sc = 0, ss = 0;
        for (int k = 0; k < order - 1; ++k) {
            double arg = 2 * kPi * i * k / K;
            sc += m[k + 1] * std::cos(arg);
            ss += m[k + 1] * std::sin(arg);
        }
        mod[i] = sc * sc + ss * ss;
    }
    // the modulus vanishes at K/2 for odd orders: interpolate
    for (int i = 0; i < K; ++i)
        if (mod[i] < 1e-7) mod[i] = 0.5 * (mod[(i - 1 + K) % K] + mod[(i + 1) % K]);
    return mod;
}

double PmeCpu::compute(const std::vector<Vec3>& pos, const std::vector<double>& q, Vec3 box, std::vector<Vec3>& f) {
    const int n = p_.order, K[3] = {p_.nx, p_.ny, p_.nz};
    for (int d = 0; d < 3; ++d)
        if (mod_n_[d] != K[d]) {
            mod_[d] = bspline_moduli(K[d], n);
            mod_n_[d] = K[d];
        }
    const size_t G = size_t(K[0]) * K[1] * K[2];
    grid_.assign(G, cplx(0, 0));
    const int N = static_cast<int>(pos.size());
    std::vector<double> th(size_t(N) * 3 * n), dth(size_t(N) * 3 * n);
    std::vector<int> base(size_t(N) * 3);
    for (int i = 0; i < N; ++i) {
        for (int d = 0; d < 3; ++d) {
            double u = pos[i][d] / box[d];
            u = (u - std::floor(u)) * K[d];
            int iu = static_cast<int>(u);
            if (iu >= K[d]) iu = K[d] - 1;
            bspline(u - iu, n, &th[(size_t(i) * 3 + d) * n], &dth[(size_t(i) * 3 + d) * n]);
            base[size_t(i) * 3 + d] = iu - n + 1;
        }
        const double* tx = &th[(size_t(i) * 3 + 0) * n];
        const double* ty = &th[(size_t(i) * 3 + 1) * n];
        const double* tz = &th[(size_t(i) * 3 + 2) * n];
        for (int a = 0; a < n; ++a) {
            int gx = (base[i * 3] + a + K[0]) % K[0];
            for (int b = 0; b < n; ++b) {
                int gy = (base[i * 3 + 1] + b + K[1]) % K[1];
                double w = q[i] * tx[a] * ty[b];
                for (int c = 0; c < n; ++c) {
                    int gz = (base[i * 3 + 2] + c + K[2]) % K[2];
                    grid_[(size_t(gx) * K[1] + gy) * K[2] + gz] += w * tz[c];
                }
            }
        }
    }
    fft_3d(grid_, K[0], K[1], K[2], -1);
    const double V = box.x * box.y * box.z;
    const double pref = kOneFourPiEps0 / (kPi * V);
    const double fac = kPi * kPi / (p_.alpha * p_.alpha);
    double energy = 0;
    for (int x = 0; x < K[0]; ++x) {
        double mx = (x <= K[0] / 2 ? x : x - K[0]) / box.x;
        for (int y = 0; y < K[1]; ++y) {
            double my = (y <= K[1] / 2 ? y : y - K[1]) / box.y;
            for (int z = 0; z < K[2]; ++z) {
                size_t g = (size_t(x) * K[1] + y) * K[2] + z;
                if (x == 0 && y == 0 && z == 0) {
                    grid_[g] = 0;
                    continue;
                }
                double mz = (z <= K[2] / 2 ? z : z - K[2]) / box.z;
                double m2 = mx * mx + my * my + mz * mz;
                double eterm = pref * std::exp(-fac * m2) / (m2 * mod_[0][x] * mod_[1][y] * mod_[2][z]);
                energy += 0.5 * eterm * std::norm(grid_[g]);
                grid_[g] *= eterm;
            }
        }
    }
    fft_3d(grid_, K[0], K[1], K[2], +1);
    for (int i = 0; i < N; ++i) {
        const double* tx = &th[(size_t(i) * 3 + 0) * n];
        const double* ty = &th[(size_t(i) * 3 + 1) * n];
        const double* tz = &th[(size_t(i) * 3 + 2) * n];
        const double* dx = &dth[(size_t(i) * 3 + 0) * n];
        const double* dy = &dth[(size_t(i) * 3 + 1) * n];
        const double* dz = &dth[(size_t(i) * 3 + 2) * n];
        double fx = 0, fy = 0, fz = 0;
        for (int a = 0; a < n; ++a) {
            int gx = (base[i * 3] + a + K[0]) % K[0];
            for (int b = 0; b < n; ++b) {
                int gy = (base[i * 3 + 1] + b + K[1]) % K[1];
                for (int c = 0; c < n; ++c) {
                    int gz = (base[i * 3 + 2] + c + K[2]) % K[2];
                    double phi = grid_[(size_t(gx) * K[1] + gy) * K[2] + gz].real();
                    fx += dx[a] * ty[b] * tz[c] * phi;
                    fy += tx[a] * dy[b] * tz[c] * phi;
                    fz += tx[a] * ty[b] * dz[c] * phi;
                }
            }
        }
        f[i] -= q[i] * Vec3{fx * K[0] / box.x, fy * K[1] / box.y, fz * K[2] / box.z};
    }
    return energy;
}

double ewald_reciprocal_direct(const std::vector<Vec3>& pos, const std::vector<double>& q, Vec3 box, double alpha, int kmax,
                               std::vector<Vec3>* f) {
    const double V = box.x * box.y * box.z;
    const double pref = kOneFourPiEps0 / (kPi * V);
    double e = 0;
    const size_t N = pos.size();
    for (int a = -kmax; a <= kmax; ++a)
        for (int b = -kmax; b <= kmax; ++b)
            for (int c = -kmax; c <= kmax; ++c) {
                if (!a && !b && !c) continue;
                Vec3 m{a / box.x, b / box.y, c / box.z};
                double m2 = dot(m, m);
                double w = pref * std::exp(-kPi * kPi * m2 / (alpha * alpha)) / m2;
                double sr = 0, si = 0;
                for (size_t i = 0; i < N; ++i) {
                    double ph = 2 * kPi * dot(m, pos[i]);
                    sr += q[i] * std::cos(ph);
                    si += q[i] * std::sin(ph);
                }
                e += 0.5 * w * (sr * sr + si * si);
                if (f)
                    for (size_t i = 0; i < N; ++i) {
                        double ph = 2 * kPi * dot(m, pos[i]);
                        double g = w * q[i] * (std::sin(ph) * sr - std::cos(ph) * si) * 2 * kPi;
                        (*f)[i] += g * m;
                    }
            }
    return e;
}

double dispersion_coefficient(const System& s, double rc) {
    std::map<std::pair<double, double>, long long> classes;
    for (int i = 0; i < s.n; ++i) classes[{s.sigma[i], s.epsilon[i]}]++;
    std::vector<std::pair<std::pair<double, double>, long long>> cl(classes.begin(), classes.end());
    double sum1 = 0, sum2 = 0;
    for (size_t a = 0; a < cl.size(); ++a)
        for (size_t b = a; b < cl.size(); ++b) {
            double na = double(cl[a].second), nb = double(cl[b].second);
            double count = a == b ? na * (na + 1) / 2 : na * nb;
            double sg = 0.5 * (cl[a].first.first + cl[b].first.first);
            double ep = std::sqrt(cl[a].first.second * cl[b].first.second);
            double s6 = std::pow(sg, 6);
            sum1 += count * ep * s6 * s6;
            sum2 += count * ep * s6;
        }
    double N = s.n;
    double pairs = N * (N + 1) / 2;
    sum1 /= pairs;
    sum2 /= pairs;
    return 8 * N * N * kPi * (sum1 / (9 * std::pow(rc, 9)) - sum2 / (3 * std::pow(rc, 3)));
}

// ---- real space -------------------------------------------------------------

NonbondedCpu::NonbondedCpu(const System& s, const EwaldParams& p, double skin) : s_(s), p_(p), skin_(skin) {
    excl_ = s.exclusion_lists();
    disp_coef_ = p.dispersion_correction ? dispersion_coefficient(s, p.cutoff) : 0;
    pme_.setup(p_);
}

void NonbondedCpu::build_list(const std::vector<Vec3>& pos, Vec3 box) {
    ++builds_;
    const int N = s_.n;
    const double rl = p_.cutoff + skin_;
    int nc[3];
    for (int d = 0; d < 3; ++d) nc[d] = std::max(1, int(box[d] / rl));
    std::vector<std::vector<int>> cells(size_t(nc[0]) * nc[1] * nc[2]);
    auto cell_of = [&](Vec3 p, int* c) {
        for (int d = 0; d < 3; ++d) {
            double u = p[d] / box[d];
            u -= std::floor(u);
            c[d] = std::min(nc[d] - 1, int(u * nc[d]));
        }
    };
    std::vector<int> cidx(size_t(N) * 3);
    for (int i = 0; i < N; ++i) {
        cell_of(pos[i], &cidx[size_t(i) * 3]);
        cells[(size_t(cidx[i * 3]) * nc[1] + cidx[i * 3 + 1]) * nc[2] + cidx[i * 3 + 2]].push_back(i);
    }
    std::vector<std::vector<int>> lists(N);
    const double rl2 = rl * rl;
#pragma omp parallel for schedule(dynamic, 64)
    for (int i = 0; i < N; ++i) {
        const int* ci = &cidx[size_t(i) * 3];
        auto& L = lists[i];
        int range[3];
        for (int d = 0; d < 3; ++d) range[d] = nc[d] >= 3 ? 1 : (nc[d] == 2 ? 1 : 0);
        std::vector<int> seen_cells;
        for (int dx = -range[0]; dx <= range[0]; ++dx)
            for (int dy = -range[1]; dy <= range[1]; ++dy)
                for (int dz = -range[2]; dz <= range[2]; ++dz) {
                    int cx = (ci[0] + dx + nc[0]) % nc[0], cy = (ci[1] + dy + nc[1]) % nc[1], cz = (ci[2] + dz + nc[2]) % nc[2];
                    int c = (cx * nc[1] + cy) * nc[2] + cz;
                    if (std::find(seen_cells.begin(), seen_cells.end(), c) != seen_cells.end()) continue;
                    seen_cells.push_back(c);
                    for (int j : cells[c]) {
                        if (j <= i) continue;
                        Vec3 d = min_image(pos[j] - pos[i], box);
                        if (dot(d, d) > rl2) continue;
                        if (std::binary_search(excl_[i].begin(), excl_[i].end(), j)) continue;
                        L.push_back(j);
                    }
                }
    }
    nbr_start_.assign(N + 1, 0);
    for (int i = 0; i < N; ++i) nbr_start_[i + 1] = nbr_start_[i] + int(lists[i].size());
    nbr_.resize(nbr_start_[N]);
    for (int i = 0; i < N; ++i) std::copy(lists[i].begin(), lists[i].end(), nbr_.begin() + nbr_start_[i]);
    list_pos_ = pos;
    list_box_ = box;
}

void NonbondedCpu::compute(const std::vector<Vec3>& pos, Vec3 box, std::vector<Vec3>& f, EnergyTerms& e) {
    const int N = s_.n;
    bool rebuild = nbr_start_.empty() || box.x != list_box_.x || box.y != list_box_.y || box.z != list_box_.z;
    if (!rebuild) {
        double lim = 0.25 * skin_ * skin_;
        for (int i = 0; i < N && !rebuild; ++i) {
            Vec3 d = pos[i] - list_pos_[i];
            if (dot(d, d) > lim) rebuild = true;
        }
    }
    if (rebuild) build_list(pos, box);
    const double a = p_.alpha, rc2 = p_.cutoff * p_.cutoff;
    const double two_over_sqrtpi = 2 / std::sqrt(kPi);
    double elj = 0, ecoul = 0;
    std::vector<Vec3> fl(N);
#pragma omp parallel
    {
        std::vector<Vec3> ft(N);
        double lj = 0, cl = 0;
#pragma omp for schedule(dynamic, 64) nowait
        for (int i = 0; i < N; ++i) {
            Vec3 fi{};
            for (int k = nbr_start_[i]; k < nbr_start_[i + 1]; ++k) {
                int j = nbr_[k];
                Vec3 d = min_image(pos[i] - pos[j], box);
                double r2 = dot(d, d);
                if (r2 >= rc2) continue;
                double r = std::sqrt(r2), inv_r2 = 1 / r2;
                double qq = kOneFourPiEps0 * s_.charge[i] * s_.charge[j];
                double erfc_ar = std::erfc(a * r);
                double ec = qq * erfc_ar / r;
                double fr = (ec + qq * two_over_sqrtpi * a * std::exp(-a * a * r2)) * inv_r2;  // -dE/dr / r
                double eps = std::sqrt(s_.epsilon[i] * s_.epsilon[j]);
                if (eps != 0) {
                    double sg = 0.5 * (s_.sigma[i] + s_.sigma[j]);
                    double s6 = std::pow(sg * sg * inv_r2, 3);
                    lj += 4 * eps * (s6 * s6 - s6);
                    fr += 24 * eps * (2 * s6 * s6 - s6) * inv_r2;
                }
                cl += ec;
                Vec3 fv = fr * d;
                fi += fv;
                ft[j] -= fv;
            }
            ft[i] += fi;
        }
#pragma omp critical
        {
            for (int i = 0; i < N; ++i) fl[i] += ft[i];
            elj += lj;
            ecoul += cl;
        }
    }
    for (int i = 0; i < N; ++i) f[i] += fl[i];
    e.lj += elj;
    e.coulomb_real += ecoul;
    // excluded pairs: remove their reciprocal-space interaction
    double ex = 0;
    for (auto [i, j] : s_.exclusions) {
        Vec3 d = min_image(pos[i] - pos[j], box);
        double r2 = dot(d, d), r = std::sqrt(r2);
        double qq = kOneFourPiEps0 * s_.charge[i] * s_.charge[j];
        if (qq == 0) continue;
        double erf_ar = std::erf(a * r);
        ex -= qq * erf_ar / r;
        double fr = -(qq * erf_ar / r - qq * two_over_sqrtpi * a * std::exp(-a * a * r2)) / r2;
        f[i] += fr * d;
        f[j] -= fr * d;
    }
    e.coulomb_excl += ex;
    double q2 = 0, qt = 0;
    for (double q : s_.charge) {
        q2 += q * q;
        qt += q;
    }
    const double V = box.x * box.y * box.z;
    e.coulomb_self += -kOneFourPiEps0 * a / std::sqrt(kPi) * q2;
    if (std::fabs(qt) > 1e-6) e.coulomb_self += -kOneFourPiEps0 * kPi * qt * qt / (2 * V * a * a);  // neutralizing plasma
    e.dispersion += disp_coef_ / V;
    e.coulomb_recip += pme_.compute(pos, s_.charge, box, f);
}

}  // namespace verlet
