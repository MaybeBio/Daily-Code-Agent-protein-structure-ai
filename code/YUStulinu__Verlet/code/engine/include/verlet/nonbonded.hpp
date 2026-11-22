// Nonbonded interactions: Lennard-Jones with a plain cutoff and its long-range
// dispersion correction, and electrostatics by particle-mesh Ewald.
//
//   real space:  qi qj erfc(a r)/r + 4 eps ((s/r)^12 - (s/r)^6)  for r < cutoff, not excluded
//   reciprocal:  smooth PME (Essmann et al. 1995), B-splines of order 5
//   corrections: - qi qj erf(a r)/r for excluded pairs, - a/sqrt(pi) sum qi^2,
//                and the dispersion correction 8 pi N^2/V (<e s^12>/(9 rc^9) - <e s^6>/(3 rc^3))
// The parameters (a from the error tolerance, grid size) follow OpenMM's
// choices, so that the two codes compute the same quantity.
#pragma once

#include <vector>

#include "fft.hpp"
#include "system.hpp"

namespace verlet {

struct EwaldParams {
    double cutoff = 0.9;
    double tolerance = 5e-4;
    double alpha = 0;
    int nx = 0, ny = 0, nz = 0;
    int order = 5;
    bool dispersion_correction = true;
    double skin = 0.15;  // neighbor-list buffer (nm); rebuilt when an atom has moved skin/2
};

/// alpha and the grid dimensions for a box, as OpenMM chooses them.
EwaldParams choose_ewald(double cutoff, double tolerance, Vec3 box);

struct EnergyTerms {
    double bond = 0, angle = 0, torsion = 0, pair14 = 0;
    double lj = 0, coulomb_real = 0, coulomb_recip = 0, coulomb_self = 0, coulomb_excl = 0, dispersion = 0;
    double nonbonded() const { return lj + coulomb_real + coulomb_recip + coulomb_self + coulomb_excl + dispersion + pair14; }
    double bonded() const { return bond + angle + torsion; }
    double potential() const { return bonded() + nonbonded(); }
};

/// Smooth PME on the CPU (the reference for the GPU version).
class PmeCpu {
public:
    void setup(const EwaldParams& p) { p_ = p; }
    /// Reciprocal-space energy; forces are added.
    double compute(const std::vector<Vec3>& pos, const std::vector<double>& q, Vec3 box, std::vector<Vec3>& f);
    /// B-spline moduli |sum_k M_n(k+1) exp(2 pi i m k / K)|^2 for one dimension.
    static std::vector<double> bspline_moduli(int K, int order);
    /// B-spline weights and derivatives of order n at fraction w (theta[k] belongs to grid point floor(u) - n + 1 + k).
    static void bspline(double w, int n, double* theta, double* dtheta);

private:
    EwaldParams p_;
    std::vector<cplx> grid_;
    std::vector<double> mod_[3];
    int mod_n_[3] = {0, 0, 0};
};

/// Reciprocal-space energy by the plain Ewald sum over k vectors (for tests).
double ewald_reciprocal_direct(const std::vector<Vec3>& pos, const std::vector<double>& q, Vec3 box, double alpha, int kmax,
                               std::vector<Vec3>* f = nullptr);

/// The dispersion-correction coefficient c: E = c / V (OpenMM's formula, over all atom pairs).
double dispersion_coefficient(const System& s, double cutoff);

/// Real-space nonbonded on the CPU with a Verlet list (cutoff + skin), threads by OpenMP.
class NonbondedCpu {
public:
    NonbondedCpu(const System& s, const EwaldParams& p, double skin = 0.1);
    /// Real space + exclusion corrections + self energy + dispersion correction + PME.
    void compute(const std::vector<Vec3>& pos, Vec3 box, std::vector<Vec3>& f, EnergyTerms& e);
    const EwaldParams& params() const { return p_; }
    int list_builds() const { return builds_; }

private:
    const System& s_;
    EwaldParams p_;
    double skin_;
    std::vector<std::vector<int>> excl_;
    std::vector<int> nbr_start_, nbr_;  // half list (j > i in list order)
    std::vector<Vec3> list_pos_;
    Vec3 list_box_{};
    int builds_ = 0;
    double disp_coef_ = 0;
    PmeCpu pme_;

    void build_list(const std::vector<Vec3>& pos, Vec3 box);
};

}  // namespace verlet
