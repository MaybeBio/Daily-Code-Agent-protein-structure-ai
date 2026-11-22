// Engine tests: FFT against a direct DFT, PME against the plain Ewald sum,
// every force term against finite differences of its energy, constraints
// (SETTLE against SHAKE, velocity constraints), and energy conservation of a
// short NVE run.
#include <cmath>
#include <cstdio>
#include <functional>
#include <random>
#include <string>

#include "verlet/alchemy.hpp"
#include "verlet/constraints.hpp"
#include "verlet/fft.hpp"
#include "verlet/forces.hpp"
#include "verlet/integrator.hpp"
#include "verlet/nonbonded.hpp"

using namespace verlet;

static int g_fail = 0, g_pass = 0;
static void check(bool ok, const char* what, double value = 0) {
    if (ok) ++g_pass;
    else {
        ++g_fail;
        std::printf("FAIL %s (%.3e)\n", what, value);
    }
}

static void test_fft() {
    std::mt19937 rng(1);
    std::normal_distribution<double> N;
    for (int n : {1, 2, 3, 4, 5, 7, 8, 12, 17, 18, 30, 48, 49, 64, 75, 96, 105, 128}) {
        std::vector<cplx> a(n), b;
        for (auto& x : a) x = {N(rng), N(rng)};
        b = a;
        std::vector<cplx> w;
        fft_1d(b.data(), n, -1, w);
        double err = 0;
        for (int k = 0; k < n; ++k) {
            cplx s = 0;
            for (int j = 0; j < n; ++j) s += a[j] * std::polar(1.0, -2 * kPi * double(j) * k / n);
            err = std::max(err, std::abs(s - b[k]) / std::sqrt(double(n)));
        }
        check(err < 1e-12, "fft vs dft", err);
        fft_1d(b.data(), n, +1, w);
        double back = 0;
        for (int j = 0; j < n; ++j) back = std::max(back, std::abs(b[j] / double(n) - a[j]));
        check(back < 1e-13, "fft round trip", back);
    }
    check(fft_friendly_size(17) == 18 && fft_friendly_size(97) == 98 && fft_friendly_size(1) == 1, "friendly sizes");
    int nx = 6, ny = 5, nz = 8;
    std::vector<cplx> g(nx * ny * nz);
    for (auto& x : g) x = {N(rng), 0};
    auto h = g;
    fft_3d(h, nx, ny, nz, -1);
    double err = 0;
    for (int kx = 0; kx < nx; ++kx)
        for (int ky = 0; ky < ny; ++ky)
            for (int kz = 0; kz < nz; ++kz) {
                cplx s = 0;
                for (int x = 0; x < nx; ++x)
                    for (int y = 0; y < ny; ++y)
                        for (int z = 0; z < nz; ++z)
                            s += g[(x * ny + y) * nz + z] *
                                 std::polar(1.0, -2 * kPi * (double(kx * x) / nx + double(ky * y) / ny + double(kz * z) / nz));
                err = std::max(err, std::abs(s - h[(kx * ny + ky) * nz + kz]));
            }
    check(err < 1e-10, "fft 3d", err);
}

static void test_pme_vs_ewald() {
    std::mt19937 rng(3);
    std::uniform_real_distribution<double> U(0, 1);
    Vec3 box{1.7, 1.9, 2.1};
    const int N = 40;
    std::vector<Vec3> x(N);
    std::vector<double> q(N);
    for (int i = 0; i < N; ++i) {
        x[i] = {U(rng) * box.x, U(rng) * box.y, U(rng) * box.z};
        q[i] = (i % 2 ? 1 : -1) * (0.3 + 0.5 * U(rng));
    }
    double qt = 0;
    for (double v : q) qt += v;
    q[0] -= qt;
    const double alpha = 3.0;
    std::vector<Vec3> fe(N), fp(N);
    double ee = ewald_reciprocal_direct(x, q, box, alpha, 12, &fe);
    EwaldParams p;
    p.alpha = alpha;
    p.nx = 48;
    p.ny = 50;
    p.nz = 54;
    PmeCpu pme;
    pme.setup(p);
    double ep = pme.compute(x, q, box, fp);
    check(std::fabs(ep - ee) < 1e-5 * std::fabs(ee), "pme energy vs ewald", ep - ee);
    double fmax = 0, ferr = 0;
    for (int i = 0; i < N; ++i) {
        fmax = std::max(fmax, norm(fe[i]));
        ferr = std::max(ferr, norm(fp[i] - fe[i]));
    }
    check(ferr < 1e-4 * fmax, "pme forces vs ewald", ferr / fmax);
    double h = 1e-6, worst = 0;
    for (int i = 0; i < 5; ++i)
        for (int d = 0; d < 3; ++d) {
            auto xp = x, xm = x;
            xp[i][d] += h;
            xm[i][d] -= h;
            double fd = -(ewald_reciprocal_direct(xp, q, box, alpha, 12) - ewald_reciprocal_direct(xm, q, box, alpha, 12)) / (2 * h);
            worst = std::max(worst, std::fabs(fd - fe[i][d]));
        }
    check(worst < 1e-4, "ewald forces vs finite differences", worst);
}

// forces of one kind of term against central differences of its energy
static void fd_check(const char* name, const System& s, std::function<double(const std::vector<Vec3>&, std::vector<Vec3>&)> eval,
                     double tol) {
    std::vector<Vec3> x = s.pos, f(s.n);
    eval(x, f);
    std::mt19937 rng(7);
    double worst = 0, scale = 0;
    for (int t = 0; t < 60; ++t) {
        int i = int(rng() % s.n), d = int(rng() % 3);
        double h = 1e-6;
        auto xp = x, xm = x;
        xp[i][d] += h;
        xm[i][d] -= h;
        std::vector<Vec3> dummy(s.n);
        double fd = -(eval(xp, dummy) - eval(xm, dummy)) / (2 * h);
        worst = std::max(worst, std::fabs(fd - f[i][d]));
        scale = std::max(scale, std::fabs(fd));
    }
    char msg[160];
    std::snprintf(msg, sizeof msg, "%s forces vs finite differences", name);
    check(worst < tol * std::max(1.0, scale), msg, worst);
}

static void test_bonded_fd(const System& s) {
    const char* names[] = {"bond", "angle", "torsion", "pair14"};
    for (int w = 0; w < 4; ++w) {
        System t = s;
        if (w != 0) t.bonds.clear();
        if (w != 1) t.angles.clear();
        if (w != 2) t.torsions.clear();
        if (w != 3) t.pairs14.clear();
        Bonded b(t);
        fd_check(names[w], t, [&](const std::vector<Vec3>& x, std::vector<Vec3>& f) {
            f.assign(t.n, Vec3{});
            EnergyTerms e;
            b.compute(x, t.box, f, e);
            return e.potential();
        }, 1e-5);
    }
}

static void test_nonbonded_fd(const char* name, const System& s) {
    EwaldParams p = choose_ewald(0.9, 5e-4, s.box);
    NonbondedCpu nb(s, p, 0.0);
    fd_check(name, s, [&](const std::vector<Vec3>& x, std::vector<Vec3>& f) {
        f.assign(s.n, Vec3{});
        EnergyTerms e;
        nb.compute(x, s.box, f, e);
        return e.nonbonded();
    }, 2e-4);
}

static void test_constraints(const System& w) {
    std::mt19937 rng(11);
    std::normal_distribution<double> N(0, 0.003);
    Constraints settle(w);
    std::vector<Vec3> ref = w.pos;
    settle.positions(std::vector<Vec3>(ref), ref, w.box);  // exact geometry first
    std::vector<Vec3> x = ref;
    for (auto& p : x) p += Vec3{N(rng), N(rng), N(rng)};
    std::vector<Vec3> xs = x;
    settle.positions(ref, xs, w.box);
    System sh = w;
    sh.waters.clear();
    for (auto& W : w.waters) {
        sh.constraints.push_back({W.o, W.h1, w.water_doh});
        sh.constraints.push_back({W.o, W.h2, w.water_doh});
        sh.constraints.push_back({W.h1, W.h2, w.water_dhh});
    }
    Constraints shake(sh, 1e-13);
    std::vector<Vec3> xk = x;
    shake.positions(ref, xk, w.box);
    double diff = 0, viol = 0;
    for (int i = 0; i < w.n; ++i) diff = std::max(diff, norm(xs[i] - xk[i]));
    for (auto& W : w.waters) {
        viol = std::max(viol, std::fabs(norm(xs[W.h1] - xs[W.o]) - w.water_doh));
        viol = std::max(viol, std::fabs(norm(xs[W.h2] - xs[W.h1]) - w.water_dhh));
    }
    check(viol < 1e-10, "settle satisfies the constraints", viol);
    check(diff < 1e-8, "settle equals shake", diff);
    std::vector<Vec3> v(w.n);
    for (auto& u : v) u = {N(rng) * 100, N(rng) * 100, N(rng) * 100};
    Vec3 p0{};
    for (int i = 0; i < w.n; ++i) p0 += w.mass[i] * v[i];
    settle.velocities(xs, v, w.box);
    double worst = 0;
    Vec3 p1{};
    for (int i = 0; i < w.n; ++i) p1 += w.mass[i] * v[i];
    for (auto& W : w.waters)
        for (auto [a, b] : {std::pair{W.o, W.h1}, std::pair{W.o, W.h2}, std::pair{W.h1, W.h2}})
            worst = std::max(worst, std::fabs(dot(v[a] - v[b], xs[a] - xs[b])));
    check(worst < 1e-9, "velocity settle", worst);
    check(norm(p1 - p0) < 1e-9, "velocity settle keeps momentum", norm(p1 - p0));
}

static void test_nve(const System& s) {
    EwaldParams p = choose_ewald(0.9, 5e-4, s.box);
    auto forces = make_cpu_forces(s, p);
    Integrator integ(s, *forces, 0.001, 300, 0.0, 5);
    State st;
    st.x = s.pos;
    st.box = s.box;
    {
        std::vector<Vec3> ref = st.x;
        integ.constraints().positions(ref, st.x, st.box);
    }
    minimize(s, *forces, integ.constraints(), st, 300);
    integ.init_velocities(st, 300);
    double e0 = integ.thermo(st).total, emax = 0;
    for (int k = 0; k < 200; ++k) {
        integ.step(st);
        emax = std::max(emax, std::fabs(integ.thermo(st).total - e0));
    }
    double ke = integ.thermo(st).kinetic;
    check(emax < 2e-3 * ke, "nve energy conservation (200 steps of 1 fs)", emax / ke);
}

static void test_alchemy(const System& w) {
    EwaldParams p = choose_ewald(0.9, 5e-4, w.box);
    auto make = [](const System& ss, const EwaldParams& pp) { return make_cpu_forces(ss, pp); };
    const int m = 5, first = w.molecules[m], last = w.molecules[m + 1];
    AlchemicalForces alch(w, first, last, p, make);
    auto plain = make_cpu_forces(w, p);
    std::vector<Vec3> fa, fp;
    EnergyTerms ea, epl;
    alch.set_state({1, 1});
    alch.compute(w.pos, w.box, fa, ea);
    plain->compute(w.pos, w.box, fp, epl);
    double fdiff = 0;
    for (int i = 0; i < w.n; ++i) fdiff = std::max(fdiff, norm(fa[i] - fp[i]));
    check(std::fabs(ea.potential() - epl.potential()) < 1e-8 * std::fabs(epl.potential()), "alchemy at lambda 1 = plain energy",
          ea.potential() - epl.potential());
    check(fdiff < 1e-7, "alchemy at lambda 1 = plain forces", fdiff);
    // an intermediate state: forces against finite differences of the energy
    alch.set_state({0.4, 0.6});
    fd_check("alchemical (lambda_q 0.4, lambda_lj 0.6)", w, [&](const std::vector<Vec3>& x, std::vector<Vec3>& f) {
        EnergyTerms e;
        alch.compute(x, w.box, f, e);
        return e.potential();
    }, 2e-4);
    // energies at other states: the current one must agree with compute(), and dU/dlambda with differences
    std::vector<LambdaState> states = {{1, 1}, {0.4, 0.6}, {0.4 + 1e-4, 0.6}, {0.4, 0.6 + 1e-4}, {0, 0}};
    std::vector<double> u;
    double dq = 0, dlj = 0;
    alch.energies_at(w.pos, w.box, states, u, dq, dlj);
    std::vector<Vec3> f;
    EnergyTerms e;
    alch.compute(w.pos, w.box, f, e);
    check(std::fabs(u[1] - e.potential()) < 1e-6 * std::fabs(e.potential()), "energies_at the current state", u[1] - e.potential());
    check(std::fabs(u[0] - epl.potential()) < 1e-6 * std::fabs(epl.potential()), "energies_at lambda 1", u[0] - epl.potential());
    check(std::fabs((u[2] - u[1]) / 1e-4 - dq) < 1e-3 * std::max(1.0, std::fabs(dq)), "dU/dlambda_q", (u[2] - u[1]) / 1e-4 - dq);
    check(std::fabs((u[3] - u[1]) / 1e-4 - dlj) < 1e-2 * std::max(1.0, std::fabs(dlj)), "dU/dlambda_lj", (u[3] - u[1]) / 1e-4 - dlj);
}

int main() {
    test_fft();
    test_pme_vs_ewald();
    System w = System::load("tests/data/water216.vsys");
    System pep = System::load("tests/data/chignolin_vac.vsys");
    test_bonded_fd(pep);
    test_nonbonded_fd("nonbonded water", w);
    test_nonbonded_fd("nonbonded peptide", pep);
    test_constraints(w);
    test_nve(w);
    test_alchemy(w);
    // input checks: a box too small for the cutoff, an alchemical solute that is not a rigid water
    auto throws = [](auto f) {
        try {
            f();
        } catch (const std::exception&) {
            return true;
        }
        return false;
    };
    check(throws([] { choose_ewald(0.9, 5e-4, Vec3{1.7, 3, 3}); }), "box below twice the cutoff is rejected");
    check(throws([&] {
        AlchemicalForces a(pep, pep.molecules[0], pep.molecules[1], choose_ewald(0.9, 5e-4, pep.box),
                           [](const System& ss, const EwaldParams& pp) { return make_cpu_forces(ss, pp); });
    }), "non-water alchemical solute is rejected");
    std::printf("%d passed, %d failed\n", g_pass, g_fail);
    return g_fail ? 1 : 0;
}
