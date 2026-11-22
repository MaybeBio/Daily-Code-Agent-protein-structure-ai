// verlet: molecular dynamics from a .vsys system file.
//
//   verlet energy SYSTEM [--cutoff 0.9] [--tol 5e-4] [--platform cpu|cuda] [--forces OUT]
//   verlet run SYSTEM [--steps N] [--dt 0.002] [--temperature 300] [--friction 1]
//                     [--pressure BAR] [--minimize STEPS] [--report N] [--log FILE]
//                     [--traj FILE --traj-every N] [--out FINAL.vsys-positions]
//                     [--platform cpu|cuda] [--seed S] [--equilibrate STEPS] [--skin 0.15]
//   verlet fep SYSTEM --solute-molecule M --states "q:lj,..." --state K [run options]
//                     [--sample-every N] [--fep-out FILE]   (alchemical windows for free energies)
//
// Units: nm, ps, amu, kJ/mol, K, bar.
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <string>
#include <thread>
#ifdef _OPENMP
#include <omp.h>
#endif

#include "verlet/alchemy.hpp"
#include "verlet/forces.hpp"
#include "verlet/integrator.hpp"

using namespace verlet;

namespace {
std::map<std::string, std::string> parse(int argc, char** argv, int from) {
    std::map<std::string, std::string> a;
    for (int i = from; i < argc; ++i) {
        std::string k = argv[i];
        if (k.rfind("--", 0) == 0 && i + 1 < argc) a[k.substr(2)] = argv[++i];
    }
    return a;
}
double num(const std::map<std::string, std::string>& a, const char* k, double d) {
    auto it = a.find(k);
    return it == a.end() ? d : std::atof(it->second.c_str());
}
std::string str(const std::map<std::string, std::string>& a, const char* k, const std::string& d) {
    auto it = a.find(k);
    return it == a.end() ? d : it->second;
}

EwaldParams ewald_from_args(const System& s, const std::map<std::string, std::string>& a) {
    EwaldParams p = choose_ewald(num(a, "cutoff", 0.9), num(a, "tol", 5e-4), s.box);
    p.dispersion_correction = str(a, "dispersion", "on") == "on";
    p.skin = num(a, "skin", 0.15);
    if (a.count("grid")) {  // e.g. 48,48,48 (to use another program's choice)
        std::sscanf(a.at("grid").c_str(), "%d,%d,%d", &p.nx, &p.ny, &p.nz);
    }
    if (a.count("alpha")) p.alpha = num(a, "alpha", p.alpha);
    return p;
}

std::unique_ptr<Forces> platform_forces(const System& s, const EwaldParams& p, const std::string& plat) {
    if (plat == "cuda") {
        std::string why;
        auto f = make_cuda_forces(s, p, &why);
        if (f) return f;
        std::fprintf(stderr, "CUDA plugin not available (%s); using the CPU\n", why.c_str());
    }
    return make_cpu_forces(s, p);
}

std::unique_ptr<Forces> make_forces(const System& s, const std::map<std::string, std::string>& a) {
    std::string plat = str(a, "platform", "cuda");
    EwaldParams p = ewald_from_args(s, a);
    if (a.count("solute-molecule")) {  // alchemical decoupling of one molecule
        int m = int(num(a, "solute-molecule", 0));
        if (m < 0 || m + 1 >= int(s.molecules.size())) throw std::runtime_error("bad --solute-molecule");
        auto f = std::make_unique<AlchemicalForces>(s, s.molecules[m], s.molecules[m + 1], p,
                                                    [plat](const System& ss, const EwaldParams& pp) { return platform_forces(ss, pp, plat); });
        return f;
    }
    return platform_forces(s, p, plat);
}

std::vector<LambdaState> parse_states(const std::string& text) {
    // "q:lj,q:lj,..."
    std::vector<LambdaState> out;
    size_t pos = 0;
    while (pos < text.size()) {
        size_t comma = text.find(',', pos);
        std::string item = text.substr(pos, comma == std::string::npos ? std::string::npos : comma - pos);
        LambdaState s;
        if (std::sscanf(item.c_str(), "%lf:%lf", &s.q, &s.lj) != 2) throw std::runtime_error("bad lambda state " + item);
        out.push_back(s);
        if (comma == std::string::npos) break;
        pos = comma + 1;
    }
    return out;
}

void write_positions(const std::string& path, const State& st, const System& s) {
    std::ofstream o(path);
    o.precision(10);
    o << "box " << st.box.x << " " << st.box.y << " " << st.box.z << "\n";
    for (int i = 0; i < s.n; ++i) o << st.x[i].x << " " << st.x[i].y << " " << st.x[i].z << "\n";
}

void read_positions(const std::string& path, State& st, const System& s) {
    std::ifstream in(path);
    std::string tag;
    in >> tag >> st.box.x >> st.box.y >> st.box.z;
    for (int i = 0; i < s.n; ++i) in >> st.x[i].x >> st.x[i].y >> st.x[i].z;
    if (!in) throw std::runtime_error("cannot read positions from " + path);
}
}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: verlet energy|run SYSTEM [options]\n");
        return 2;
    }
    try {
        std::string cmd = argv[1];
#ifdef _OPENMP
        // hyperthreads slow the short parallel loops down: one thread per core unless OMP_NUM_THREADS says otherwise
        if (!std::getenv("OMP_NUM_THREADS")) omp_set_num_threads(std::max(1, int(std::thread::hardware_concurrency() / 2)));
#endif
        System s = System::load(argv[2]);
        auto a = parse(argc, argv, 3);
        State st;
        st.x = s.pos;
        st.box = s.box;
        if (a.count("positions")) {
            read_positions(a["positions"], st, s);
            s.box = st.box;  // the PME grid follows the starting box
        }
        auto forces = make_forces(s, a);
        const EwaldParams& ep = forces->ewald();
        std::fprintf(stderr, "%d atoms, %zu waters, box %.4f %.4f %.4f nm, %s, cutoff %.2f nm, alpha %.4f/nm, PME grid %dx%dx%d\n", s.n,
                     s.waters.size(), st.box.x, st.box.y, st.box.z, forces->name().c_str(), ep.cutoff, ep.alpha, ep.nx, ep.ny, ep.nz);
        if (cmd == "energy") {
            forces->compute(st.x, st.box, st.f, st.e);
            const EnergyTerms& e = st.e;
            std::printf("{\"bond\": %.10f, \"angle\": %.10f, \"torsion\": %.10f, \"pair14\": %.10f, \"lj\": %.10f, "
                        "\"coulomb_real\": %.10f, \"coulomb_recip\": %.10f, \"coulomb_self\": %.10f, \"coulomb_excl\": %.10f, "
                        "\"dispersion\": %.10f, \"nonbonded\": %.10f, \"total\": %.10f}\n",
                        e.bond, e.angle, e.torsion, e.pair14, e.lj, e.coulomb_real, e.coulomb_recip, e.coulomb_self, e.coulomb_excl,
                        e.dispersion, e.nonbonded(), e.potential());
            if (a.count("forces")) {
                std::ofstream o(a["forces"]);
                o.precision(12);
                for (auto& f : st.f) o << f.x << " " << f.y << " " << f.z << "\n";
            }
            return 0;
        }
        if (cmd != "run" && cmd != "fep") throw std::runtime_error("unknown command " + cmd);
        // alchemical windows: the state simulated, and the energies at every state written every sample
        AlchemicalForces* alch = dynamic_cast<AlchemicalForces*>(forces.get());
        std::vector<LambdaState> states;
        std::FILE* fep = nullptr;
        long sample_every = long(num(a, "sample-every", 500));
        if (cmd == "fep") {
            if (!alch) throw std::runtime_error("fep needs --solute-molecule");
            states = parse_states(str(a, "states", "1:1,0:1,0:0"));
            int k = int(num(a, "state", 0));
            if (k < 0 || k >= int(states.size())) throw std::runtime_error("bad --state");
            alch->set_state(states[k]);
            fep = std::fopen(str(a, "fep-out", "fep.csv").c_str(), "w");
            std::fprintf(fep, "# state %d of %zu: lambda_q %.4f lambda_lj %.4f; columns: time_ps, volume_nm3, dU/dlq, dU/dllj, U_k (kJ/mol)\n", k,
                         states.size(), states[k].q, states[k].lj);
            std::fprintf(fep, "time_ps,volume_nm3,du_dq,du_dlj");
            for (size_t j = 0; j < states.size(); ++j) std::fprintf(fep, ",u%zu", j);
            std::fprintf(fep, "\n");
        }
        const double dt = num(a, "dt", 0.002), T = num(a, "temperature", 300), gamma = num(a, "friction", 1.0);
        const long steps = long(num(a, "steps", 1000)), report = long(num(a, "report", 500));
        Integrator integ(s, *forces, dt, T, gamma, uint64_t(num(a, "seed", 1)));
        // put the starting positions on the constraints
        {
            std::vector<Vec3> ref = st.x;
            integ.constraints().positions(ref, st.x, st.box);
        }
        if (a.count("minimize")) {
            double e = minimize(s, *forces, integ.constraints(), st, int(num(a, "minimize", 1000)));
            std::fprintf(stderr, "minimized: %.2f kJ/mol\n", e);
        }
        forces->compute(st.x, st.box, st.f, st.e);
        integ.init_velocities(st, T);
        std::unique_ptr<Barostat> baro;
        if (a.count("pressure")) baro = std::make_unique<Barostat>(s, num(a, "pressure", 1), T, int(num(a, "barostat-every", 25)));
        std::FILE* log = a.count("log") ? std::fopen(a["log"].c_str(), "w") : nullptr;
        if (log)
            std::fprintf(log, "step,time_ps,potential,kinetic,total,temperature,volume_nm3,density_g_cm3,bond,angle,torsion,pair14,lj,"
                              "coulomb_real,coulomb_recip,coulomb_self,coulomb_excl,dispersion\n");
        std::unique_ptr<TrajectoryWriter> traj;
        long traj_every = long(num(a, "traj-every", 500));
        if (a.count("traj")) traj = std::make_unique<TrajectoryWriter>(a["traj"], s.n);
        long equil = long(num(a, "equilibrate", 0));
        auto t0 = std::chrono::steady_clock::now();
        auto t_prod = t0;
        for (long k = 0; k <= steps + equil; ++k) {
            if (k == equil) t_prod = std::chrono::steady_clock::now();
            if (k >= equil && (k - equil) % report == 0) {
                Thermo th = integ.thermo(st);
                const EnergyTerms& e = st.e;
                if (log)
                    std::fprintf(log, "%ld,%.4f,%.6f,%.6f,%.6f,%.4f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f\n", k - equil,
                                 (k - equil) * dt, th.potential, th.kinetic, th.total, th.temperature, th.volume, th.density, e.bond, e.angle,
                                 e.torsion, e.pair14, e.lj, e.coulomb_real, e.coulomb_recip, e.coulomb_self, e.coulomb_excl, e.dispersion);
                std::fprintf(stderr, "step %8ld  t %9.2f ps  E %14.3f  T %7.2f K  rho %.4f g/cm3\n", k - equil, (k - equil) * dt, th.total,
                             th.temperature, th.density);
            }
            if (traj && k >= equil && (k - equil) % traj_every == 0) traj->write(st);
            if (fep && k > equil && (k - equil) % sample_every == 0) {
                std::vector<double> u;
                double dq = 0, dlj = 0;
                alch->energies_at(st.x, st.box, states, u, dq, dlj);
                std::fprintf(fep, "%.4f,%.8f,%.6f,%.6f", (k - equil) * dt, st.box.x * st.box.y * st.box.z, dq, dlj);
                for (double v : u) std::fprintf(fep, ",%.6f", v);
                std::fprintf(fep, "\n");
                std::fflush(fep);
            }
            if (k == steps + equil) break;
            integ.step(st);
            if (baro) baro->apply(st, *forces, integ.rng());
            if (k % 1000 == 999) integ.remove_com_motion(st);
        }
        double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t_prod).count();
        double ns_per_day = steps * dt * 1e-3 / secs * 86400;
        std::fprintf(stderr, "%ld steps in %.2f s: %.2f ns/day\n", steps, secs, ns_per_day);
        std::printf("{\"atoms\": %d, \"steps\": %ld, \"dt_ps\": %g, \"seconds\": %.3f, \"ns_per_day\": %.3f, \"platform\": \"%s\"",
                    s.n, steps, dt, secs, ns_per_day, forces->name().c_str());
        if (baro) std::printf(", \"barostat_accepted\": %d, \"barostat_attempted\": %d", baro->accepted(), baro->attempted());
        std::printf("}\n");
        if (log) std::fclose(log);
        if (fep) std::fclose(fep);
        if (a.count("out")) write_positions(a["out"], st, s);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "error: %s\n", e.what());
        return 1;
    }
    return 0;
}
