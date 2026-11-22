// Loading the CUDA plugin (a shared library with a plain C interface, built
// separately with nvcc) at run time; the engine works without it.
//
// Search order: $VERLET_CUDA_PLUGIN, next to the executable, build/cuda/Release
// and build/cuda (relative to the executable's directory and its parents).
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <vector>

#include "verlet/cuda_plugin.h"
#include "verlet/forces.hpp"

#if defined(_WIN32)
#include <windows.h>
#else
#include <dlfcn.h>
#include <unistd.h>
#endif

namespace verlet {

namespace {

struct Api {
    decltype(&vc_create) create = nullptr;
    decltype(&vc_set_pme) set_pme = nullptr;
    decltype(&vc_set_charges) set_charges = nullptr;
    decltype(&vc_begin) begin = nullptr;
    decltype(&vc_end) end = nullptr;
    decltype(&vc_device) device = nullptr;
    decltype(&vc_destroy) destroy = nullptr;
};

std::filesystem::path exe_dir() {
#if defined(_WIN32)
    char buf[MAX_PATH];
    GetModuleFileNameA(nullptr, buf, MAX_PATH);
    return std::filesystem::path(buf).parent_path();
#else
    char buf[4096];
    ssize_t k = readlink("/proc/self/exe", buf, sizeof buf - 1);
    if (k <= 0) return ".";
    buf[k] = 0;
    return std::filesystem::path(buf).parent_path();
#endif
}

bool load_api(Api& api, std::string* why) {
#if defined(_WIN32)
    const char* name = "verlet_cuda.dll";
#else
    const char* name = "libverlet_cuda.so";
#endif
    std::vector<std::filesystem::path> cands;
    if (const char* env = std::getenv("VERLET_CUDA_PLUGIN")) cands.emplace_back(env);
    auto d = exe_dir();
    for (int up = 0; up < 3; ++up) {
        cands.push_back(d / name);
        cands.push_back(d / "build" / "cuda" / "Release" / name);
        cands.push_back(d / "build" / "cuda" / name);
        cands.push_back(d / "cuda" / "Release" / name);
        cands.push_back(d / "cuda" / name);
        d = d.parent_path();
    }
    for (auto& p : cands) {
        if (!std::filesystem::exists(p)) continue;
#if defined(_WIN32)
        HMODULE h = LoadLibraryA(p.string().c_str());
        if (!h) continue;
        auto sym = [&](const char* s) { return reinterpret_cast<void*>(GetProcAddress(h, s)); };
#else
        void* h = dlopen(p.string().c_str(), RTLD_NOW);
        if (!h) continue;
        auto sym = [&](const char* s) { return dlsym(h, s); };
#endif
        api.create = reinterpret_cast<decltype(api.create)>(sym("vc_create"));
        api.set_pme = reinterpret_cast<decltype(api.set_pme)>(sym("vc_set_pme"));
        api.set_charges = reinterpret_cast<decltype(api.set_charges)>(sym("vc_set_charges"));
        api.begin = reinterpret_cast<decltype(api.begin)>(sym("vc_begin"));
        api.end = reinterpret_cast<decltype(api.end)>(sym("vc_end"));
        api.device = reinterpret_cast<decltype(api.device)>(sym("vc_device"));
        api.destroy = reinterpret_cast<decltype(api.destroy)>(sym("vc_destroy"));
        if (api.create && api.set_pme && api.set_charges && api.begin && api.end && api.device && api.destroy) return true;
    }
    if (why) *why = std::string("no ") + name + " found (set VERLET_CUDA_PLUGIN)";
    return false;
}

class CudaForces : public Forces {
public:
    CudaForces(const System& s, const EwaldParams& p, Api api, void* ctx) : s_(s), p_(p), api_(api), ctx_(ctx), bonded_(s), skin_(p.skin) {
        disp_coef_ = p.dispersion_correction ? dispersion_coefficient(s, p.cutoff) : 0;
        for (double q : s.charge) {
            q2_ += q * q;
            qt_ += q;
        }
        name_ = std::string("cuda (") + api_.device(ctx_) + ")";
    }
    ~CudaForces() override {
        if (std::getenv("VERLET_PROFILE")) std::fprintf(stderr, "neighbor list: %ld rebuilds in %ld force calls\n", rebuilds_, calls_);
        api_.destroy(ctx_);
    }

    void compute(const std::vector<Vec3>& pos, Vec3 box, std::vector<Vec3>& f, EnergyTerms& e) override {
        const int n = s_.n;
        bool rebuild = last_.empty() || box.x != last_box_.x || box.y != last_box_.y || box.z != last_box_.z;
        if (!rebuild) {
            const double lim = 0.25 * skin_ * skin_;
            for (int i = 0; i < n; ++i) {
                Vec3 d = pos[i] - last_[i];
                if (dot(d, d) > lim) {
                    rebuild = true;
                    break;
                }
            }
        }
        ++calls_;
        if (rebuild) {
            ++rebuilds_;
            last_ = pos;
            last_box_ = box;
        }
        double b[3] = {box.x, box.y, box.z};
        if (api_.begin(ctx_, &pos[0].x, b, rebuild ? 1 : 0, 1)) throw std::runtime_error(std::string("CUDA: ") + api_.device(nullptr));
        // the bonded terms on the CPU meanwhile
        f.assign(n, Vec3{});
        e = EnergyTerms{};
        bonded_.compute(pos, box, f, e);
        double en[4];
        if (api_.end(ctx_, &f[0].x, en)) throw std::runtime_error(std::string("CUDA: ") + api_.device(nullptr));
        e.lj = en[0];
        e.coulomb_real = en[1];
        e.coulomb_recip = en[2];
        e.coulomb_excl = en[3];
        const double V = box.x * box.y * box.z, a = p_.alpha;
        e.coulomb_self = -kOneFourPiEps0 * a / std::sqrt(kPi) * q2_;
        if (std::fabs(qt_) > 1e-6) e.coulomb_self += -kOneFourPiEps0 * kPi * qt_ * qt_ / (2 * V * a * a);
        e.dispersion = disp_coef_ / V;
    }
    std::string name() const override { return name_; }
    const EwaldParams& ewald() const override { return p_; }
    void charges_changed() override {
        api_.set_charges(ctx_, s_.charge.data());
        q2_ = qt_ = 0;
        for (double q : s_.charge) {
            q2_ += q * q;
            qt_ += q;
        }
    }

private:
    const System& s_;
    EwaldParams p_;
    Api api_;
    void* ctx_;
    Bonded bonded_;
    double skin_, disp_coef_ = 0, q2_ = 0, qt_ = 0;
    std::vector<Vec3> last_;
    Vec3 last_box_{};
    std::string name_;
    long rebuilds_ = 0, calls_ = 0;
};

}  // namespace

std::unique_ptr<Forces> make_cuda_forces(const System& s, const EwaldParams& p, std::string* why) {
    Api api;
    if (!load_api(api, why)) return nullptr;
    std::vector<int> ex;
    for (auto [i, j] : s.exclusions) {
        ex.push_back(i);
        ex.push_back(j);
    }
    void* ctx = nullptr;
    char err[512] = {0};
    if (api.create(&ctx, s.n, s.charge.data(), s.sigma.data(), s.epsilon.data(), int(s.exclusions.size()), ex.data(), p.cutoff, p.skin, err,
                   sizeof err)) {
        if (why) *why = err;
        return nullptr;
    }
    if (api.set_pme(ctx, p.alpha, p.nx, p.ny, p.nz, p.order)) {
        if (why) *why = api.device(nullptr);
        api.destroy(ctx);
        return nullptr;
    }
    return std::make_unique<CudaForces>(s, p, api, ctx);
}

}  // namespace verlet
