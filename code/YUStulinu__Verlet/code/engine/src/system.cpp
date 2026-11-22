#include "verlet/system.hpp"

#include <algorithm>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace verlet {

namespace {
std::istringstream next_line(std::ifstream& f) {
    std::string line;
    if (!std::getline(f, line)) throw std::runtime_error("vsys: unexpected end of file");
    return std::istringstream(line);
}
int section(std::ifstream& f, const char* name, std::istringstream* rest = nullptr) {
    auto ls = next_line(f);
    std::string tag;
    int n = 0;
    ls >> tag >> n;
    if (tag != name) throw std::runtime_error(std::string("vsys: expected section ") + name + ", found " + tag);
    if (rest) *rest = std::move(ls);
    return n;
}
}  // namespace

System System::load(const std::string& path) {
    std::ifstream f(path);
    if (!f) throw std::runtime_error("cannot open " + path);
    std::string magic;
    std::getline(f, magic);
    if (magic != "verlet-system 1") throw std::runtime_error(path + ": not a verlet system file");
    System s;
    {
        auto ls = next_line(f);
        std::string tag;
        ls >> tag >> s.box.x >> s.box.y >> s.box.z;
    }
    s.n = section(f, "atoms");
    for (int i = 0; i < s.n; ++i) {
        auto ls = next_line(f);
        std::string name, res, chain, el;
        int resid;
        double m, q, sg, ep;
        Vec3 p;
        ls >> name >> res >> resid >> chain >> el >> m >> q >> sg >> ep >> p.x >> p.y >> p.z;
        s.name.push_back(name);
        s.resname.push_back(res);
        s.resid.push_back(resid);
        s.element.push_back(el);
        s.mass.push_back(m);
        s.charge.push_back(q);
        s.sigma.push_back(sg);
        s.epsilon.push_back(ep);
        s.pos.push_back(p);
    }
    int nb = section(f, "bonds");
    for (int k = 0; k < nb; ++k) { auto l = next_line(f); Bond b; l >> b.i >> b.j >> b.r0 >> b.k; s.bonds.push_back(b); }
    int na = section(f, "angles");
    for (int k = 0; k < na; ++k) { auto l = next_line(f); Angle a; l >> a.i >> a.j >> a.k >> a.theta0 >> a.k_theta; s.angles.push_back(a); }
    int nt = section(f, "torsions");
    for (int k = 0; k < nt; ++k) { auto l = next_line(f); Torsion t; l >> t.i >> t.j >> t.k >> t.l >> t.n >> t.phase >> t.k_phi; s.torsions.push_back(t); }
    int np = section(f, "pairs14");
    for (int k = 0; k < np; ++k) { auto l = next_line(f); Pair14 p; l >> p.i >> p.j >> p.qq >> p.sigma >> p.epsilon; s.pairs14.push_back(p); }
    int ne = section(f, "exclusions");
    for (int k = 0; k < ne; ++k) { auto l = next_line(f); int i, j; l >> i >> j; s.exclusions.push_back({std::min(i, j), std::max(i, j)}); }
    int nc = section(f, "constraints");
    for (int k = 0; k < nc; ++k) { auto l = next_line(f); Constraint c; l >> c.i >> c.j >> c.d; s.constraints.push_back(c); }
    std::istringstream rest;
    int nw = section(f, "waters", &rest);
    rest >> s.water_doh >> s.water_dhh;
    for (int k = 0; k < nw; ++k) { auto l = next_line(f); Water w; l >> w.o >> w.h1 >> w.h2; s.waters.push_back(w); }
    int nm = section(f, "molecules");
    auto l = next_line(f);
    s.molecules.resize(nm + 1);
    for (int k = 0; k <= nm; ++k) l >> s.molecules[k];
    return s;
}

double System::total_mass() const {
    double m = 0;
    for (double x : mass) m += x;
    return m;
}

std::vector<std::vector<int>> System::exclusion_lists() const {
    std::vector<std::vector<int>> ex(n);
    for (auto [i, j] : exclusions) {
        ex[i].push_back(j);
        ex[j].push_back(i);
    }
    for (auto& e : ex) std::sort(e.begin(), e.end());
    return ex;
}

void wrap_molecules(const System& s, std::vector<Vec3>& pos, Vec3 box) {
    for (size_t m = 0; m + 1 < s.molecules.size(); ++m) {
        int a = s.molecules[m], b = s.molecules[m + 1];
        // make the molecule whole around its first atom, then shift its center into the box
        Vec3 c{};
        double mt = 0;
        for (int i = a; i < b; ++i) {
            if (i > a) pos[i] = pos[a] + min_image(pos[i] - pos[a], box);
            c += s.mass[i] * pos[i];
            mt += s.mass[i];
        }
        c = c / mt;
        Vec3 shift{box.x * std::floor(c.x / box.x), box.y * std::floor(c.y / box.y), box.z * std::floor(c.z / box.z)};
        for (int i = a; i < b; ++i) pos[i] -= shift;
    }
}

}  // namespace verlet
