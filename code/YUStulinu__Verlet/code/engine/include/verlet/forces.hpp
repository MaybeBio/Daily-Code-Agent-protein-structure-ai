// All forces of a system: bonded terms (Fortran, on the CPU) and nonbonded
// terms (C++ on the CPU, or the CUDA plugin on the GPU).
#pragma once

#include <memory>
#include <string>
#include <vector>

#include "nonbonded.hpp"
#include "system.hpp"

namespace verlet {

/// The bonded terms packed for the Fortran routine.
class Bonded {
public:
    explicit Bonded(const System& s);
    void compute(const std::vector<Vec3>& pos, Vec3 box, std::vector<Vec3>& f, EnergyTerms& e) const;

private:
    int n_;
    std::vector<int> bidx_, aidx_, tidx_, tper_, pidx_;
    std::vector<double> bpar_, apar_, tpar_, ppar_;
};

class Forces {
public:
    virtual ~Forces() = default;
    /// Forces (overwritten) and energy terms at positions in a box.
    virtual void compute(const std::vector<Vec3>& pos, Vec3 box, std::vector<Vec3>& f, EnergyTerms& e) = 0;
    virtual std::string name() const = 0;
    virtual const EwaldParams& ewald() const = 0;
    /// The charges of the System these forces were made for have changed.
    virtual void charges_changed() {}
};

/// Everything on the CPU (double precision).
std::unique_ptr<Forces> make_cpu_forces(const System& s, const EwaldParams& p);

/// Nonbonded and PME on the GPU through the CUDA plugin, bonded terms on the
/// CPU at the same time; nullptr (and a message) if the plugin cannot be loaded.
std::unique_ptr<Forces> make_cuda_forces(const System& s, const EwaldParams& p, std::string* why);

}  // namespace verlet
