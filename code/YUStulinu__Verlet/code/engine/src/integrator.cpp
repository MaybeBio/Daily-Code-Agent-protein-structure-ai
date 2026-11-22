#include "verlet/integrator.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#ifdef _OPENMP
#include <omp.h>
#endif

namespace verlet {

Integrator::Integrator(const System& s, Forces& forces, double dt, double temperature, double friction, uint64_t seed)
    : s_(s), forces_(forces), cons_(s), dt_(dt), T_(temperature), gamma_(friction), rng_(seed) {}

void Integrator::init_velocities(State& st, double T) {
    st.v.assign(s_.n, Vec3{});
    for (int i = 0; i < s_.n; ++i) {
        double sd = std::sqrt(kBoltzmann * T / s_.mass[i]);
        st.v[i] = {sd * gauss_(rng_), sd * gauss_(rng_), sd * gauss_(rng_)};
    }
    cons_.velocities(st.x, st.v, st.box);
    remove_com_motion(st);
    // rescale to the exact temperature
    double ke = 0;
    for (int i = 0; i < s_.n; ++i) ke += 0.5 * s_.mass[i] * dot(st.v[i], st.v[i]);
    double t_now = 2 * ke / (s_.degrees_of_freedom() * kBoltzmann);
    if (t_now > 0)
        for (auto& v : st.v) v *= std::sqrt(T / t_now);
}

void Integrator::remove_com_motion(State& st) const {
    Vec3 p{};
    double m = 0;
    for (int i = 0; i < s_.n; ++i) {
        p += s_.mass[i] * st.v[i];
        m += s_.mass[i];
    }
    Vec3 vc = p / m;
    for (auto& v : st.v) v -= vc;
}

void Integrator::step(State& st) {
    const int n = s_.n;
    const double dt = dt_;
    if (int(xold_.size()) != n) {
        xold_.resize(n);
        xunc_.resize(n);
    }
    // kick with the forces at x
#pragma omp parallel for schedule(static)
    for (int i = 0; i < n; ++i) st.v[i] += (dt / s_.mass[i]) * st.f[i];
    cons_.velocities(st.x, st.v, st.box);
    // drift half a step, friction and noise (one random stream per thread), drift half a step
    const double a = std::exp(-gamma_ * dt), b = std::sqrt(1 - a * a);
#pragma omp parallel
    {
#ifdef _OPENMP
        const int tid = omp_get_thread_num(), nt = omp_get_num_threads();
#else
        const int tid = 0, nt = 1;
#endif
#pragma omp single
        if (int(thread_rng_.size()) < nt)
            for (int t = int(thread_rng_.size()); t < nt; ++t) thread_rng_.emplace_back(rng_() + 0x9E3779B97F4A7C15ull * (t + 1));
        std::mt19937_64& r = thread_rng_[tid];
        std::normal_distribution<double> g(0.0, 1.0);
#pragma omp for schedule(static)
        for (int i = 0; i < n; ++i) {
            xold_[i] = st.x[i];
            st.x[i] += 0.5 * dt * st.v[i];
            if (gamma_ > 0) {
                double sd = b * std::sqrt(kBoltzmann * T_ / s_.mass[i]);
                st.v[i] = a * st.v[i] + Vec3{sd * g(r), sd * g(r), sd * g(r)};
            }
        }
    }
    if (gamma_ > 0) cons_.velocities(st.x, st.v, st.box);
#pragma omp parallel for schedule(static)
    for (int i = 0; i < n; ++i) {
        st.x[i] += 0.5 * dt * st.v[i];
        xunc_[i] = st.x[i];
    }
    // the velocity carried on is the one after friction and noise, plus the
    // constraint correction (not (x' - x)/dt, which would average the
    // velocities before and after the noise and halve the temperature)
    cons_.positions(xold_, st.x, st.box);
#pragma omp parallel for schedule(static)
    for (int i = 0; i < n; ++i) st.v[i] += (st.x[i] - xunc_[i]) / dt;
    forces_.compute(st.x, st.box, st.f, st.e);
    st.time += dt_;
    st.step += 1;
}

double Integrator::kinetic_energy(const State& st) const {
    std::vector<Vec3> v(st.v);
    for (int i = 0; i < s_.n; ++i) v[i] += (0.5 * dt_ / s_.mass[i]) * st.f[i];
    cons_.velocities(st.x, v, st.box);
    double ke = 0;
    for (int i = 0; i < s_.n; ++i) ke += 0.5 * s_.mass[i] * dot(v[i], v[i]);
    return ke;
}

Thermo Integrator::thermo(const State& st) const {
    Thermo t;
    t.potential = st.e.potential();
    t.kinetic = kinetic_energy(st);
    t.total = t.potential + t.kinetic;
    t.temperature = 2 * t.kinetic / (s_.degrees_of_freedom() * kBoltzmann);
    t.volume = st.box.x * st.box.y * st.box.z;
    t.density = s_.total_mass() / kAvogadro / (t.volume * 1e-21);  // g/cm^3
    return t;
}

// ---- barostat --------------------------------------------------------------

Barostat::Barostat(const System& s, double pressure_bar, double temperature, int frequency)
    : s_(s), P_(pressure_bar * kBarToInternal), kT_(kBoltzmann * temperature), freq_(frequency) {}

void Barostat::apply(State& st, Forces& forces, std::mt19937_64& rng) {
    if (freq_ <= 0 || st.step % freq_ != 0) return;
    const double V = st.box.x * st.box.y * st.box.z;
    if (dv_max_ == 0) dv_max_ = 0.01 * V;
    std::uniform_real_distribution<double> U(0, 1);
    const double dV = dv_max_ * (2 * U(rng) - 1);
    const double Vn = V + dV;
    const double scale = std::cbrt(Vn / V);
    const double cutoff = forces.ewald().cutoff;
    if (scale * std::min({st.box.x, st.box.y, st.box.z}) <= 2 * cutoff) return;  // never below twice the cutoff
    const int nmol = int(s_.molecules.size()) - 1;
    std::vector<Vec3> x_old = st.x;
    Vec3 box_old = st.box;
    for (int m = 0; m < nmol; ++m) {
        int a = s_.molecules[m], b = s_.molecules[m + 1];
        Vec3 c{};
        double mt = 0;
        for (int i = a; i < b; ++i) {
            c += s_.mass[i] * st.x[i];
            mt += s_.mass[i];
        }
        c = c / mt;
        Vec3 shift = (scale - 1) * c;
        for (int i = a; i < b; ++i) st.x[i] += shift;
    }
    st.box = scale * st.box;
    const double U0 = st.e.potential();
    std::vector<Vec3> f_new;
    EnergyTerms e_new;
    forces.compute(st.x, st.box, f_new, e_new);
    const double w = e_new.potential() - U0 + P_ * dV - nmol * kT_ * std::log(Vn / V);
    ++attempted_;
    ++window_att_;
    if (w <= 0 || U(rng) < std::exp(-w / kT_)) {
        ++accepted_;
        ++window_acc_;
        st.f = std::move(f_new);
        st.e = e_new;
    } else {
        st.x = std::move(x_old);
        st.box = box_old;
        forces.compute(st.x, st.box, st.f, st.e);  // restores neighbor lists and caches
    }
    if (window_att_ >= 10) {
        double rate = double(window_acc_) / window_att_;
        if (rate < 0.25) dv_max_ /= 1.1;
        else if (rate > 0.75) dv_max_ = std::min(dv_max_ * 1.1, 0.3 * V);
        window_att_ = window_acc_ = 0;
    }
}

// ---- minimization -------------------------------------------------------------

double minimize(const System& s, Forces& forces, Constraints& cons, State& st, int max_steps, double ftol) {
    forces.compute(st.x, st.box, st.f, st.e);
    double E = st.e.potential(), h = 0.01;  // nm, largest displacement
    std::vector<Vec3> x0, f0;
    EnergyTerms e0;
    for (int it = 0; it < max_steps; ++it) {
        double fmax = 0;
        for (auto& f : st.f) fmax = std::max(fmax, norm(f));
        if (fmax < ftol) break;
        x0 = st.x;
        f0 = st.f;
        e0 = st.e;
        for (int i = 0; i < s.n; ++i) st.x[i] += (h / fmax) * st.f[i];
        cons.positions(x0, st.x, st.box);
        forces.compute(st.x, st.box, st.f, st.e);
        if (st.e.potential() < E) {
            E = st.e.potential();
            h = std::min(h * 1.2, 0.05);
        } else {
            st.x = x0;
            st.f = f0;
            st.e = e0;
            h *= 0.5;
            if (h < 1e-7) break;
        }
    }
    return E;
}

// ---- trajectory -------------------------------------------------------------

TrajectoryWriter::TrajectoryWriter(const std::string& path, int n) : n_(n) {
    f_ = std::fopen(path.c_str(), "wb");
    if (!f_) throw std::runtime_error("cannot write " + path);
    std::fwrite("VTRJ", 1, 4, f_);
    int32_t nn = n;
    std::fwrite(&nn, 4, 1, f_);
}

TrajectoryWriter::~TrajectoryWriter() {
    if (f_) std::fclose(f_);
}

void TrajectoryWriter::write(const State& st) {
    int64_t step = st.step;
    double t = st.time, b[3] = {st.box.x, st.box.y, st.box.z};
    std::fwrite(&step, 8, 1, f_);
    std::fwrite(&t, 8, 1, f_);
    std::fwrite(b, 8, 3, f_);
    std::vector<float> xyz(size_t(n_) * 3);
    for (int i = 0; i < n_; ++i) {
        xyz[3 * i] = float(st.x[i].x);
        xyz[3 * i + 1] = float(st.x[i].y);
        xyz[3 * i + 2] = float(st.x[i].z);
    }
    std::fwrite(xyz.data(), 4, xyz.size(), f_);
    std::fflush(f_);
}

}  // namespace verlet
