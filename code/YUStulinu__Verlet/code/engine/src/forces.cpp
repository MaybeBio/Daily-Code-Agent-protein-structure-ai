#include "verlet/forces.hpp"

extern "C" void verlet_bonded_forces(int n, const double* x, const double* box, int nb, const int* bidx, const double* bpar, int na,
                                     const int* aidx, const double* apar, int nt, const int* tidx, const int* tper, const double* tpar,
                                     int np, const int* pidx, const double* ppar, double* f, double* energy);

namespace verlet {

Bonded::Bonded(const System& s) : n_(s.n) {
    for (auto& b : s.bonds) {
        bidx_.insert(bidx_.end(), {b.i, b.j});
        bpar_.insert(bpar_.end(), {b.r0, b.k});
    }
    for (auto& a : s.angles) {
        aidx_.insert(aidx_.end(), {a.i, a.j, a.k});
        apar_.insert(apar_.end(), {a.theta0, a.k_theta});
    }
    for (auto& t : s.torsions) {
        tidx_.insert(tidx_.end(), {t.i, t.j, t.k, t.l});
        tper_.push_back(t.n);
        tpar_.insert(tpar_.end(), {t.phase, t.k_phi});
    }
    for (auto& p : s.pairs14) {
        pidx_.insert(pidx_.end(), {p.i, p.j});
        ppar_.insert(ppar_.end(), {p.qq, p.sigma, p.epsilon});
    }
}

void Bonded::compute(const std::vector<Vec3>& pos, Vec3 box, std::vector<Vec3>& f, EnergyTerms& e) const {
    static_assert(sizeof(Vec3) == 3 * sizeof(double), "Vec3 must be three packed doubles");
    double b[3] = {box.x, box.y, box.z}, en[4];
    auto ptr = [](const auto& v) { return v.empty() ? nullptr : v.data(); };
    verlet_bonded_forces(n_, &pos[0].x, b, int(bpar_.size() / 2), ptr(bidx_), ptr(bpar_),
                         int(apar_.size() / 2), ptr(aidx_), ptr(apar_), int(tper_.size()), ptr(tidx_), ptr(tper_), ptr(tpar_),
                         int(ppar_.size() / 3), ptr(pidx_), ptr(ppar_), &f[0].x, en);
    e.bond += en[0];
    e.angle += en[1];
    e.torsion += en[2];
    e.pair14 += en[3];
}

namespace {
class CpuForces : public Forces {
public:
    CpuForces(const System& s, const EwaldParams& p) : bonded_(s), nb_(s, p, p.skin) {}
    void compute(const std::vector<Vec3>& pos, Vec3 box, std::vector<Vec3>& f, EnergyTerms& e) override {
        f.assign(pos.size(), Vec3{});
        e = EnergyTerms{};
        bonded_.compute(pos, box, f, e);
        nb_.compute(pos, box, f, e);
    }
    std::string name() const override { return "cpu"; }
    const EwaldParams& ewald() const override { return nb_.params(); }

private:
    Bonded bonded_;
    NonbondedCpu nb_;
};
}  // namespace

std::unique_ptr<Forces> make_cpu_forces(const System& s, const EwaldParams& p) { return std::make_unique<CpuForces>(s, p); }

}  // namespace verlet
