// Time integration: the "Langevin middle" scheme (Zhang et al. 2019; the
// scheme of OpenMM's LangevinMiddleIntegrator), which with zero friction is
// leapfrog Verlet (NVE); a Monte Carlo barostat for NPT; steepest-descent
// minimization with constraints.
#pragma once

#include <cstdint>
#include <cstdio>
#include <string>
#include <random>
#include <vector>

#include "constraints.hpp"
#include "forces.hpp"

namespace verlet {

struct State {
    std::vector<Vec3> x, v, f;  // positions, velocities (v at t - dt/2), forces at x
    Vec3 box;
    double time = 0;
    int64_t step = 0;
    EnergyTerms e;
};

struct Thermo {
    double potential, kinetic, total, temperature, volume, density;  // kJ/mol, K, nm^3, g/cm^3
};

class Integrator {
public:
    Integrator(const System& s, Forces& forces, double dt, double temperature, double friction, uint64_t seed);
    void init_velocities(State& st, double temperature);
    void step(State& st);
    /// Kinetic energy at the time of the positions: v(t) = v(t - dt/2) + dt/2 f/m, constrained.
    double kinetic_energy(const State& st) const;
    Thermo thermo(const State& st) const;
    void remove_com_motion(State& st) const;
    Constraints& constraints() { return cons_; }
    const System& system() const { return s_; }
    Forces& forces() { return forces_; }
    std::mt19937_64& rng() { return rng_; }
    double dt() const { return dt_; }
    double temperature() const { return T_; }

private:
    const System& s_;
    Forces& forces_;
    Constraints cons_;
    double dt_, T_, gamma_;
    std::mt19937_64 rng_;
    std::normal_distribution<double> gauss_{0.0, 1.0};
    std::vector<Vec3> xold_, xunc_;
    std::vector<std::mt19937_64> thread_rng_;
};

/// Isotropic Monte Carlo barostat (molecule centers scaled, Metropolis on
/// dU + P dV - N kT ln(V'/V)), adapting the volume step like OpenMM's.
class Barostat {
public:
    Barostat(const System& s, double pressure_bar, double temperature, int frequency);
    /// Try a volume move if the step is a multiple of the frequency; forces are recomputed on acceptance.
    void apply(State& st, Forces& forces, std::mt19937_64& rng);
    int attempted() const { return attempted_; }
    int accepted() const { return accepted_; }

private:
    const System& s_;
    double P_, kT_;
    int freq_;
    double dv_max_ = 0;
    int attempted_ = 0, accepted_ = 0, window_att_ = 0, window_acc_ = 0;
};

/// Steepest descent with an adaptive step, keeping constraints; returns the final potential energy.
double minimize(const System& s, Forces& forces, Constraints& cons, State& st, int max_steps, double ftol = 10.0);

/// Binary trajectory: "VTRJ", int32 atoms, then frames of int64 step, double time, double box[3], float xyz[3 n].
class TrajectoryWriter {
public:
    TrajectoryWriter(const std::string& path, int n);
    ~TrajectoryWriter();
    void write(const State& st);

private:
    std::FILE* f_ = nullptr;
    int n_;
};

}  // namespace verlet
