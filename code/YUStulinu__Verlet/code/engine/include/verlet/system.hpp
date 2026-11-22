// The molecular system: atoms, parameters, bonded terms, exclusions,
// constraints and rigid waters, read from the .vsys file written by prep/.
#pragma once

#include <string>
#include <vector>

#include "vec.hpp"

namespace verlet {

struct Bond { int i, j; double r0, k; };
struct Angle { int i, j, k; double theta0, k_theta; };
struct Torsion { int i, j, k, l, n; double phase, k_phi; };
struct Pair14 { int i, j; double qq, sigma, epsilon; };
struct Constraint { int i, j; double d; };
struct Water { int o, h1, h2; };

struct System {
    int n = 0;
    Vec3 box;
    std::vector<std::string> name, resname, element;
    std::vector<int> resid;
    std::vector<double> mass, charge, sigma, epsilon;
    std::vector<Vec3> pos;
    std::vector<Bond> bonds;
    std::vector<Angle> angles;
    std::vector<Torsion> torsions;
    std::vector<Pair14> pairs14;
    std::vector<std::pair<int, int>> exclusions;  // i < j; no direct nonbonded interaction
    std::vector<Constraint> constraints;          // other than rigid waters
    std::vector<Water> waters;
    double water_doh = 0.09572, water_dhh = 0.15139;
    std::vector<int> molecules;  // first atom of each molecule, then n

    static System load(const std::string& path);
    int degrees_of_freedom() const { return 3 * n - static_cast<int>(constraints.size()) - 3 * static_cast<int>(waters.size()) - 3; }
    double total_mass() const;
    /// Exclusions of each atom (both directions), sorted.
    std::vector<std::vector<int>> exclusion_lists() const;
};

/// Put every molecule's center inside the box (molecules stay whole).
void wrap_molecules(const System& s, std::vector<Vec3>& pos, Vec3 box);

}  // namespace verlet
