// Alchemical decoupling of one molecule (the solute) from its environment,
// for free energies of solvation.
//
//   electrostatics: the solute's charges are scaled by lambda_q (everything,
//     PME included, is then computed as usual; the energy is quadratic in lambda_q);
//   Lennard-Jones: solute-environment pairs use Beutler's soft core,
//     4 eps lambda (1/(a (1 - lambda) + (r/s)^6)^2 - 1/(a (1 - lambda) + (r/s)^6)), a = 0.5,
//     computed on the CPU (a small solute against every atom); the long-range
//     dispersion correction of the solute is scaled linearly with lambda_lj.
// The solute must be one rigid water (which has no intramolecular terms to keep).
#pragma once

#include <functional>
#include <memory>
#include <vector>

#include "forces.hpp"

namespace verlet {

struct LambdaState {
    double q = 1, lj = 1;
};

class AlchemicalForces : public Forces {
public:
    /// `make` builds the inner forces for a system (CPU or CUDA).
    AlchemicalForces(const System& s, int solute_first, int solute_last, const EwaldParams& p,
                     const std::function<std::unique_ptr<Forces>(const System&, const EwaldParams&)>& make);
    void set_state(LambdaState st);
    LambdaState state() const { return st_; }
    void compute(const std::vector<Vec3>& pos, Vec3 box, std::vector<Vec3>& f, EnergyTerms& e) override;
    std::string name() const override { return inner_->name() + " + alchemy"; }
    const EwaldParams& ewald() const override { return inner_->ewald(); }

    /// The potential energy at other lambda states, same positions:
    /// U_k for every state (kJ/mol); dU/dlambda_q and dU/dlambda_lj at the current state.
    void energies_at(const std::vector<Vec3>& pos, Vec3 box, const std::vector<LambdaState>& states, std::vector<double>& u,
                     double& du_dq, double& du_dlj);
    /// Soft-core solute-environment LJ energy at lambda (forces added if f != nullptr) plus its dE/dlambda.
    double softcore(const std::vector<Vec3>& pos, Vec3 box, double lambda, std::vector<Vec3>* f, double* dlambda) const;

private:
    System sys_;  // solute epsilon 0, charges scaled
    std::vector<double> q0_, eps0_;
    int first_, last_;  // solute atoms [first, last)
    LambdaState st_;
    double alpha_sc_ = 0.5, cutoff_;
    double disp_full_ = 0, disp_none_ = 0;  // dispersion coefficients with the solute's LJ on / off
    std::unique_ptr<Forces> inner_;
    void apply_charges(double lq);
};

}  // namespace verlet
