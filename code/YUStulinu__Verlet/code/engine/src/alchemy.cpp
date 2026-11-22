#include "verlet/alchemy.hpp"

#include <cmath>
#include <stdexcept>

namespace verlet {

AlchemicalForces::AlchemicalForces(const System& s, int first, int last, const EwaldParams& p,
                                   const std::function<std::unique_ptr<Forces>(const System&, const EwaldParams&)>& make)
    : sys_(s), first_(first), last_(last), cutoff_(p.cutoff) {
    // shortcut: one rigid water only; a flexible solute would also lose its intramolecular LJ and
    // non-excluded Coulomb here, so it needs those pairs kept apart before it can be allowed
    bool water = false;
    for (const Water& w : s.waters) water |= w.o == first && last - first == 3;
    if (!water) throw std::runtime_error("the alchemical solute must be one rigid water");
    q0_ = s.charge;
    eps0_.assign(s.epsilon.begin() + first, s.epsilon.begin() + last);
    disp_full_ = p.dispersion_correction ? dispersion_coefficient(s, p.cutoff) : 0;
    for (int i = first; i < last; ++i) sys_.epsilon[i] = 0;
    disp_none_ = p.dispersion_correction ? dispersion_coefficient(sys_, p.cutoff) : 0;
    inner_ = make(sys_, p);
}

void AlchemicalForces::apply_charges(double lq) {
    for (int i = first_; i < last_; ++i) sys_.charge[i] = lq * q0_[i];
    inner_->charges_changed();
}

void AlchemicalForces::set_state(LambdaState st) {
    st_ = st;
    apply_charges(st.q);
}

double AlchemicalForces::softcore(const std::vector<Vec3>& pos, Vec3 box, double lambda, std::vector<Vec3>* f, double* dlambda) const {
    const double rc2 = cutoff_ * cutoff_, a = alpha_sc_ * (1 - lambda);
    double e = 0, de = 0;
    const System& s0 = sys_;  // its solute epsilons are zero; eps0_ keeps the originals
    for (int i = first_; i < last_; ++i) {
        const double eps_i = eps0_[i - first_];
        if (eps_i == 0) continue;
        for (int j = 0; j < s0.n; ++j) {
            if (j >= first_ && j < last_) continue;
            if (s0.epsilon[j] == 0) continue;
            Vec3 d = min_image(pos[i] - pos[j], box);
            double r2 = dot(d, d);
            if (r2 >= rc2) continue;
            double sg = 0.5 * (s0.sigma[i] + s0.sigma[j]);
            double eps = std::sqrt(eps_i * s0.epsilon[j]);
            double u = std::pow(r2 / (sg * sg), 3);  // (r/s)^6
            double D = a + u;
            double inv = 1 / D;
            double ej = 4 * eps * (inv * inv - inv);
            e += lambda * ej;
            // dE/dlambda = 4 eps [(1/D^2 - 1/D) + lambda (-2/D^3 + 1/D^2) dD/dlambda], dD/dlambda = -alpha
            double dE_dD = 4 * eps * lambda * (-2 * inv * inv * inv + inv * inv);
            de += ej + dE_dD * (-alpha_sc_);
            if (f) {
                // dD/dr = 6 u / r -> F = -dE/dr * d/r = -dE_dD * 6 u / r^2 * d
                Vec3 fv = (-dE_dD * 6 * u / r2) * d;
                (*f)[i] += fv;
                (*f)[j] -= fv;
            }
        }
    }
    if (dlambda) *dlambda = de;
    return e;
}

void AlchemicalForces::compute(const std::vector<Vec3>& pos, Vec3 box, std::vector<Vec3>& f, EnergyTerms& e) {
    inner_->compute(pos, box, f, e);
    e.lj += softcore(pos, box, st_.lj, &f, nullptr);
    const double V = box.x * box.y * box.z;
    e.dispersion += st_.lj * (disp_full_ - disp_none_) / V;
}

void AlchemicalForces::energies_at(const std::vector<Vec3>& pos, Vec3 box, const std::vector<LambdaState>& states, std::vector<double>& u,
                                   double& du_dq, double& du_dlj) {
    // electrostatic part: U_q(l) = A + B l + C l^2 from three evaluations (l = 0, 0.5, 1)
    std::vector<Vec3> f;
    EnergyTerms e;
    double U[3];
    const double ls[3] = {0.0, 0.5, 1.0};
    for (int k = 0; k < 3; ++k) {
        apply_charges(ls[k]);
        inner_->compute(pos, box, f, e);
        U[k] = e.potential();
    }
    apply_charges(st_.q);
    const double A = U[0], C = 2 * (U[2] - 2 * U[1] + U[0]), B = U[2] - U[0] - C;
    const double V = box.x * box.y * box.z;
    auto uq = [&](double l) { return A + B * l + C * l * l; };
    // soft-core part for every distinct lambda_lj
    u.resize(states.size());
    for (size_t k = 0; k < states.size(); ++k) {
        double sc = softcore(pos, box, states[k].lj, nullptr, nullptr);
        u[k] = uq(states[k].q) + sc + states[k].lj * (disp_full_ - disp_none_) / V;
    }
    du_dq = B + 2 * C * st_.q;
    double d = 0;
    softcore(pos, box, st_.lj, nullptr, &d);
    du_dlj = d + (disp_full_ - disp_none_) / V;
}

}  // namespace verlet
