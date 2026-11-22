// Holonomic constraints: rigid waters by SETTLE (Miyamoto and Kollman 1992,
// analytic) and other bonds (X-H) by SHAKE for positions and RATTLE for
// velocities.
#pragma once

#include <vector>

#include "system.hpp"

namespace verlet {

class Constraints {
public:
    explicit Constraints(const System& s, double tolerance = 1e-10);
    /// Move `x` (new positions) so that the constraints hold, along the
    /// directions of the bonds at `ref` (old positions).
    void positions(const std::vector<Vec3>& ref, std::vector<Vec3>& x, Vec3 box) const;
    /// Remove the velocity components along the constrained bonds.
    void velocities(const std::vector<Vec3>& x, std::vector<Vec3>& v, Vec3 box) const;
    int count() const { return int(s_.constraints.size() + 3 * s_.waters.size()); }
    int shake_iterations_last() const { return iters_; }

private:
    const System& s_;
    double tol_;
    std::vector<double> invm_;
    mutable int iters_ = 0;
};

}  // namespace verlet
