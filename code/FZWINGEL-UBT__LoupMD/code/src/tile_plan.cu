// Tile planner of the tiled capacity mode (PLAN.md S5-T01; tiled.hpp says what a plan is).
//
// Host code only: no CUDA call, no device memory, so tests/cpu/test_tile_plan.py compiles this file with g++ alone.
// The rules are FastMACE's (fastmace/model/tiled.py: _grid_shape, fit_grid, plan_tiles, _split_block), without its
// boundary skin; the ghost candidates are LoupMD's own, because here a tile is an open domain that is handed its
// ghosts (PLAN.md S1-T09) where FastMACE's tiles build periodic lists.
//
// Memory beside the plan itself: 4 bytes per atom for the block index and 4 for the bin order. Fractional
// coordinates are recomputed where they are needed (a 3x3 product) and never stored for the whole system.
#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>

#include "loupmd.h"
#include "tiled.hpp"

namespace loup {
namespace {

struct Geometry {
    double inv[9];       // the inverse of the cell: frac_i = sum_j pos_j inv[3 j + i]
    double spacing[3];   // the plane spacing of each axis, Angstrom
    double volume;
};

Geometry geometry_of(const double* c) {
    Geometry g;
    const double det = c[0] * (c[4] * c[8] - c[5] * c[7]) - c[1] * (c[3] * c[8] - c[5] * c[6]) +
                       c[2] * (c[3] * c[7] - c[4] * c[6]);
    if (!(std::fabs(det) > 1e-12) || !std::isfinite(det)) throw std::runtime_error("plan_tiles: the cell has no volume");
    g.volume = std::fabs(det);
    g.inv[0] = (c[4] * c[8] - c[5] * c[7]) / det;
    g.inv[1] = (c[2] * c[7] - c[1] * c[8]) / det;
    g.inv[2] = (c[1] * c[5] - c[2] * c[4]) / det;
    g.inv[3] = (c[5] * c[6] - c[3] * c[8]) / det;
    g.inv[4] = (c[0] * c[8] - c[2] * c[6]) / det;
    g.inv[5] = (c[2] * c[3] - c[0] * c[5]) / det;
    g.inv[6] = (c[3] * c[7] - c[4] * c[6]) / det;
    g.inv[7] = (c[1] * c[6] - c[0] * c[7]) / det;
    g.inv[8] = (c[0] * c[4] - c[1] * c[3]) / det;
    for (int i = 0; i < 3; i++)  // column i of the inverse is the reciprocal vector of axis i
        g.spacing[i] = 1.0 / std::sqrt(g.inv[i] * g.inv[i] + g.inv[3 + i] * g.inv[3 + i] + g.inv[6 + i] * g.inv[6 + i]);
    return g;
}

// The fractional coordinates of atom `a` wrapped into [0, 1), and the whole cells taken off.
inline void wrapped(const Geometry& g, const double* positions, int64_t a, double f[3], int32_t whole[3]) {
    const double* p = positions + 3 * a;
    for (int i = 0; i < 3; i++) {
        const double x = p[0] * g.inv[i] + p[1] * g.inv[3 + i] + p[2] * g.inv[6 + i];
        if (!(std::fabs(x) < 1e9))  // also NaN and infinity
            throw std::runtime_error("plan_tiles: the position of atom " + std::to_string(a) +
                                     (std::isfinite(x) ? " is more than 1e9 cells away" : " is not finite"));
        double cells = std::floor(x);
        double rest = x - cells;
        if (rest >= 1.0) {  // x a hair below a whole number
            rest = 0.0;
            cells += 1.0;
        }
        f[i] = rest;
        whole[i] = static_cast<int32_t>(cells);
    }
}

inline int64_t cell_index(const double f[3], const int k[3]) {
    int64_t b[3];
    for (int i = 0; i < 3; i++) b[i] = std::min<int64_t>(static_cast<int64_t>(f[i] * k[i]), k[i] - 1);
    return (b[0] * k[1] + b[1]) * k[2] + b[2];
}

int64_t count_of(const int k[3], const char* what) {
    for (int i = 0; i < 3; i++)
        if (k[i] < 1) throw std::runtime_error(std::string("plan_tiles: ") + what + " must have at least one block per axis");
    const double total = static_cast<double>(k[0]) * k[1] * k[2];
    if (total >= 2147483647.0) throw std::runtime_error(std::string("plan_tiles: ") + what + " has more than 2^31 blocks");
    return static_cast<int64_t>(k[0]) * k[1] * k[2];
}

// FastMACE's _grid_shape: blocks per axis so that a block is about cubic and holds about `receivers` atoms.
void rule_grid(const Geometry& g, int64_t n, int receivers, double scale, int k[3]) {
    const double side = std::cbrt(g.volume * static_cast<double>(std::min<int64_t>(receivers, n)) / static_cast<double>(n));
    for (int i = 0; i < 3; i++) k[i] = std::max(1, static_cast<int>(std::nearbyint(scale * g.spacing[i] / side)));
}

// FastMACE's fit_grid: of the rule's grid and finer ones, the grid with the fewest pieces of at most `receivers`
// atoms; the coarser one on a tie. The rule aims at `receivers` atoms per block on average, so on a crystal most
// blocks can sit just above the cap and split into a full tile and a small remainder with a large halo.
//
// O32: with a reach, the grid with the fewest rows instead (the coarser one on a tie): a piece of a split block takes
// the atoms in atom order, so its domain is about the whole block and its halo, and every piece counts as
// (block atoms + halo), the halo at the system's mean density over the block's shell `reach` thick. 2,560,000 atoms
// at cap 65,536: the fewest pieces were 3 x 3 x 3 blocks of 95,000 split in two (54 tiles, the widest domain 65,536
// locals and 69,464 ghosts: a 12.6 GB workspace); 4 x 4 x 4 (64 tiles of 40,000 and 26,000 ghosts) has fewer rows.
void fit_grid(const Geometry& g, const double* positions, int64_t n, int receivers, double reach, int k[3]) {
    static const double scales[] = {1.0, 1.04, 1.08, 1.12, 1.17, 1.22, 1.28};
    double best = -1.0;
    int seen[7][3];
    int n_seen = 0;
    std::vector<int64_t> counts;
    for (double scale : scales) {
        int trial[3];
        rule_grid(g, n, receivers, scale, trial);
        bool again = false;
        for (int s = 0; s < n_seen; s++) again = again || (seen[s][0] == trial[0] && seen[s][1] == trial[1] && seen[s][2] == trial[2]);
        if (again) continue;
        std::memcpy(seen[n_seen++], trial, sizeof(trial));
        counts.assign(static_cast<size_t>(count_of(trial, "the grid")), 0);
        for (int64_t a = 0; a < n; a++) {
            double f[3];
            int32_t whole[3];
            wrapped(g, positions, a, f, whole);
            counts[static_cast<size_t>(cell_index(f, trial))]++;
        }
        double halo = 0.0;  // ghosts of a block: the mean density over the shell `reach` thick around it
        if (reach > 0.0) {
            double inner = 1.0, outer = 1.0;
            for (int i = 0; i < 3; i++) {
                const double side = g.spacing[i] / trial[i];
                inner *= side;
                outer *= side + 2.0 * reach;
            }
            halo = static_cast<double>(n) / g.volume * (outer - inner);
        }
        double score = 0.0;
        for (int64_t c : counts) {
            const int64_t pieces = (c + receivers - 1) / receivers;
            score += reach > 0.0 ? static_cast<double>(pieces) * (static_cast<double>(c) + halo)
                                 : static_cast<double>(pieces);
        }
        if (best < 0.0 || score < best) {
            best = score;
            std::memcpy(k, trial, sizeof(trial));
        }
    }
}

inline int64_t floor_div(int64_t a, int64_t b) { return a >= 0 ? a / b : -((-a + b - 1) / b); }

}  // namespace

TilePlan plan_tiles(const double* positions, int64_t n, const double* cell, int receivers, int64_t edges,
                    const int32_t* degree, double reach, const int* shape, double boundary_skin) {
    if (!positions || !cell) throw std::runtime_error("plan_tiles: positions and cell are needed");
    if (n < 1 || n > std::numeric_limits<int32_t>::max()) throw std::runtime_error("plan_tiles: the atom count must be from 1 to 2^31 - 1");
    if (receivers < 1) throw std::runtime_error("plan_tiles: receivers must be positive");
    if (!(reach >= 0.0) || !std::isfinite(reach)) throw std::runtime_error("plan_tiles: reach must be finite and not negative");
    if (edges < 0) throw std::runtime_error("plan_tiles: the edge cap must not be negative");
    if (edges > 0 && !degree) throw std::runtime_error("plan_tiles: the edge cap needs the atoms' edge counts");
    const Geometry g = geometry_of(cell);

    TilePlan plan;
    if (shape) {
        std::memcpy(plan.grid, shape, sizeof(plan.grid));
    } else {
        fit_grid(g, positions, n, receivers, reach, plan.grid);
    }
    const int* k = plan.grid;
    if (!(boundary_skin >= 0.0) || !std::isfinite(boundary_skin))
        throw std::runtime_error("plan_tiles: boundary_skin must be finite and not negative");
    // With the boundary skins: two more layers of blocks along axis 0, the first and the last, for the atoms within
    // boundary_skin of the faces (only when the grid has two layers or more and a skin is thinner than a layer).
    const double skin_f = boundary_skin / g.spacing[0];
    const bool split = boundary_skin > 0.0 && k[0] >= 2 && skin_f < 1.0 / k[0];
    const int64_t layer = static_cast<int64_t>(k[1]) * k[2];
    const int64_t blocks = count_of(k, "the grid") + (split ? 2 * layer : 0);

    // ---- the atoms of each block, in atom order (a counting sort) ----
    std::vector<int32_t> block(static_cast<size_t>(n));
    std::vector<int64_t> start(static_cast<size_t>(blocks) + 1, 0);
    for (int64_t a = 0; a < n; a++) {
        double f[3];
        int32_t whole[3];
        wrapped(g, positions, a, f, whole);
        int64_t b = cell_index(f, k);
        if (split) {  // layers shift by one; the skins take layer 0 and the new last layer
            const int64_t across = b % layer, l0 = b / layer;
            if (l0 == 0 && f[0] < skin_f) b = across;
            else if (l0 == k[0] - 1 && f[0] >= 1.0 - skin_f) b = (static_cast<int64_t>(k[0]) + 1) * layer + across;
            else b = (l0 + 1) * layer + across;
        }
        block[static_cast<size_t>(a)] = static_cast<int32_t>(b);
        start[static_cast<size_t>(b) + 1]++;
    }
    for (int64_t b = 0; b < blocks; b++) start[static_cast<size_t>(b) + 1] += start[static_cast<size_t>(b)];
    plan.local.resize(static_cast<size_t>(n));
    {
        std::vector<int64_t> fill(start.begin(), start.end() - 1);
        for (int64_t a = 0; a < n; a++) plan.local[static_cast<size_t>(fill[static_cast<size_t>(block[static_cast<size_t>(a)])]++)] = static_cast<int32_t>(a);
    }
    block.clear();
    block.shrink_to_fit();

    // ---- pieces: FastMACE's _split_block. A piece ends before the atom that would take it past a cap ----
    plan.local_ptr.push_back(0);
    for (int64_t b = 0; b < blocks; b++) {
        const int64_t stop = start[static_cast<size_t>(b) + 1];
        int64_t piece = start[static_cast<size_t>(b)];
        while (piece < stop) {
            int64_t cut = std::min<int64_t>(piece + receivers, stop);
            if (edges > 0) {
                int64_t sum = 0;
                int64_t j = piece;
                while (j < cut) {
                    const int64_t d = degree[plan.local[static_cast<size_t>(j)]];
                    if (j > piece && sum + d > edges) break;
                    sum += d;
                    j++;
                }
                cut = j;
            }
            plan.local_ptr.push_back(cut);
            piece = cut;
        }
    }
    const int64_t tiles = plan.tiles();

    // ---- each local's shift into the cell, and its tile ----
    plan.local_shift.resize(3 * static_cast<size_t>(n));
    std::vector<int32_t> tile_of;
    if (reach > 0.0) tile_of.resize(static_cast<size_t>(n));
    for (int64_t t = 0; t < tiles; t++) {
        for (int64_t p = plan.local_ptr[static_cast<size_t>(t)]; p < plan.local_ptr[static_cast<size_t>(t) + 1]; p++) {
            const int32_t a = plan.local[static_cast<size_t>(p)];
            double f[3];
            int32_t whole[3];
            wrapped(g, positions, a, f, whole);
            for (int i = 0; i < 3; i++) plan.local_shift[3 * static_cast<size_t>(p) + i] = -whole[i];
            if (reach > 0.0) tile_of[static_cast<size_t>(a)] = static_cast<int32_t>(t);
        }
    }
    plan.ghost_ptr.assign(static_cast<size_t>(tiles) + 1, 0);
    if (reach == 0.0) return plan;

    // ---- ghost candidates ----
    // Bins of fractional coordinates about `reach` wide (and of at least about eight atoms), with their atoms.
    const double width = std::max(reach, std::cbrt(8.0 * g.volume / static_cast<double>(n)));
    int m[3];
    for (int i = 0; i < 3; i++) m[i] = std::max(1, static_cast<int>(std::min(1048576.0, std::floor(g.spacing[i] / width))));
    const int64_t bins = count_of(m, "the bin grid");
    std::vector<int64_t> bin_start(static_cast<size_t>(bins) + 1, 0);
    std::vector<int32_t> bin_atom(static_cast<size_t>(n));
    {
        std::vector<int32_t> bin(static_cast<size_t>(n));
        for (int64_t a = 0; a < n; a++) {
            double f[3];
            int32_t whole[3];
            wrapped(g, positions, a, f, whole);
            const int64_t b = cell_index(f, m);
            bin[static_cast<size_t>(a)] = static_cast<int32_t>(b);
            bin_start[static_cast<size_t>(b) + 1]++;
        }
        for (int64_t b = 0; b < bins; b++) bin_start[static_cast<size_t>(b) + 1] += bin_start[static_cast<size_t>(b)];
        std::vector<int64_t> fill(bin_start.begin(), bin_start.end() - 1);
        for (int64_t a = 0; a < n; a++) bin_atom[static_cast<size_t>(fill[static_cast<size_t>(bin[static_cast<size_t>(a)])]++)] = static_cast<int32_t>(a);
    }
    // A plane's distance bounds every distance across it: an atom within `reach` of a local differs from it by at
    // most reach / spacing in each fractional coordinate. A hair more, so that rounding never loses a neighbour.
    double r[3];
    for (int i = 0; i < 3; i++) r[i] = reach / g.spacing[i] * (1.0 + 1e-12) + 1e-12;
    for (int64_t t = 0; t < tiles; t++) {
        double lo[3] = {2.0, 2.0, 2.0}, hi[3] = {-1.0, -1.0, -1.0};
        for (int64_t p = plan.local_ptr[static_cast<size_t>(t)]; p < plan.local_ptr[static_cast<size_t>(t) + 1]; p++) {
            double f[3];
            int32_t whole[3];
            wrapped(g, positions, plan.local[static_cast<size_t>(p)], f, whole);
            for (int i = 0; i < 3; i++) {
                lo[i] = std::min(lo[i], f[i]);
                hi[i] = std::max(hi[i], f[i]);
            }
        }
        int64_t first[3], last[3];
        for (int i = 0; i < 3; i++) {  // one bin more on each side: the test below is the exact one
            lo[i] -= r[i];
            hi[i] += r[i];
            first[i] = static_cast<int64_t>(std::floor(lo[i] * m[i])) - 1;
            last[i] = static_cast<int64_t>(std::floor(hi[i] * m[i])) + 1;
        }
        for (int64_t b0 = first[0]; b0 <= last[0]; b0++) {
            const int64_t image0 = floor_div(b0, m[0]);
            for (int64_t b1 = first[1]; b1 <= last[1]; b1++) {
                const int64_t image1 = floor_div(b1, m[1]);
                for (int64_t b2 = first[2]; b2 <= last[2]; b2++) {
                    const int64_t image2 = floor_div(b2, m[2]);
                    const int64_t bin = ((b0 - image0 * m[0]) * m[1] + (b1 - image1 * m[1])) * m[2] + (b2 - image2 * m[2]);
                    const bool home = image0 == 0 && image1 == 0 && image2 == 0;
                    for (int64_t q = bin_start[static_cast<size_t>(bin)]; q < bin_start[static_cast<size_t>(bin) + 1]; q++) {
                        const int32_t a = bin_atom[static_cast<size_t>(q)];
                        if (home && tile_of[static_cast<size_t>(a)] == t) continue;  // a local of this tile
                        double f[3];
                        int32_t whole[3];
                        wrapped(g, positions, a, f, whole);
                        const double x0 = f[0] + static_cast<double>(image0), x1 = f[1] + static_cast<double>(image1),
                                     x2 = f[2] + static_cast<double>(image2);
                        if (x0 < lo[0] || x0 > hi[0] || x1 < lo[1] || x1 > hi[1] || x2 < lo[2] || x2 > hi[2]) continue;
                        plan.ghost.push_back(a);
                        plan.ghost_shift.push_back(static_cast<int32_t>(image0) - whole[0]);
                        plan.ghost_shift.push_back(static_cast<int32_t>(image1) - whole[1]);
                        plan.ghost_shift.push_back(static_cast<int32_t>(image2) - whole[2]);
                    }
                }
            }
        }
        plan.ghost_ptr[static_cast<size_t>(t) + 1] = static_cast<int64_t>(plan.ghost.size());
    }
    return plan;
}

void tile_dependencies(const TilePlan& plan, std::vector<int64_t>& needs_ptr, std::vector<int64_t>& needs,
                       std::vector<int64_t>& ready) {
    const int64_t tiles = plan.tiles();
    int32_t most = -1;
    for (int32_t a : plan.local) most = std::max(most, a);
    std::vector<int64_t> tile_of(static_cast<size_t>(most) + 1, -1);
    for (int64_t t = 0; t < tiles; t++)
        for (int64_t p = plan.local_ptr[static_cast<size_t>(t)]; p < plan.local_ptr[static_cast<size_t>(t) + 1]; p++)
            tile_of[static_cast<size_t>(plan.local[static_cast<size_t>(p)])] = t;
    needs_ptr.assign(static_cast<size_t>(tiles) + 1, 0);
    needs.clear();
    ready.resize(static_cast<size_t>(tiles));
    for (int64_t t = 0; t < tiles; t++) ready[static_cast<size_t>(t)] = t;
    std::vector<int64_t> mark(static_cast<size_t>(tiles), -1), mine;
    for (int64_t t = 0; t < tiles; t++) {
        mine.clear();
        auto take = [&](int32_t a) {
            const int64_t u = tile_of[static_cast<size_t>(a)];
            if (mark[static_cast<size_t>(u)] == t) return;
            mark[static_cast<size_t>(u)] = t;
            mine.push_back(u);
            ready[static_cast<size_t>(u)] = std::max(ready[static_cast<size_t>(u)], t);
        };
        for (int64_t p = plan.local_ptr[static_cast<size_t>(t)]; p < plan.local_ptr[static_cast<size_t>(t) + 1]; p++)
            take(plan.local[static_cast<size_t>(p)]);
        for (int64_t p = plan.ghost_ptr[static_cast<size_t>(t)]; p < plan.ghost_ptr[static_cast<size_t>(t) + 1]; p++)
            take(plan.ghost[static_cast<size_t>(p)]);
        std::sort(mine.begin(), mine.end());
        needs.insert(needs.end(), mine.begin(), mine.end());
        needs_ptr[static_cast<size_t>(t) + 1] = static_cast<int64_t>(needs.size());
    }
}

std::vector<SweepStep> wavefront_schedule(int64_t tiles, const int64_t* needs_ptr, const int64_t* needs,
                                          const int64_t* ready, const int64_t* counts, int group, int64_t* peak) {
    if (tiles < 1 || !needs_ptr || !needs || !ready || !counts)
        throw std::runtime_error("wavefront_schedule: tiles must be positive and needs, ready and counts given");
    for (int64_t t = 0; t < tiles; t++) {
        bool self = false;
        for (int64_t i = needs_ptr[t]; i < needs_ptr[t + 1]; i++) {
            if (needs[i] < 0 || needs[i] >= tiles)
                throw std::runtime_error("wavefront_schedule: tile " + std::to_string(t) + " needs a tile out of range");
            self = self || needs[i] == t;
        }
        if (!self) throw std::runtime_error("wavefront_schedule: tile " + std::to_string(t) + " does not need itself");
        if (ready[t] < t || ready[t] >= tiles)
            throw std::runtime_error("wavefront_schedule: tile " + std::to_string(t) + " is ready before its own sweep 2");
    }
    const int64_t step = std::max(1, group);
    std::vector<int64_t> order(static_cast<size_t>(tiles));
    for (int64_t t = 0; t < tiles; t++) order[static_cast<size_t>(t)] = t;
    std::stable_sort(order.begin(), order.end(), [&](int64_t a, int64_t b) { return ready[a] < ready[b]; });
    std::vector<char> done(static_cast<size_t>(tiles), 0);
    std::vector<SweepStep> steps;
    steps.reserve(3 * static_cast<size_t>(tiles));
    int64_t live = 0, most = 0, next3 = 0;
    for (int64_t start = 0; start < tiles; start += step) {
        const int64_t stop = std::min(tiles, start + step);
        for (int64_t t = start; t < stop; t++)
            for (int64_t i = needs_ptr[t]; i < needs_ptr[t + 1]; i++) {
                const int64_t u = needs[i];
                if (done[static_cast<size_t>(u)]) continue;
                done[static_cast<size_t>(u)] = 1;
                steps.push_back({1, u});
                live += counts[u];
                most = std::max(most, live);
            }
        for (int64_t t = start; t < stop; t++) steps.push_back({2, t});
        while (next3 < tiles && ready[order[static_cast<size_t>(next3)]] < stop) {
            const int64_t u = order[static_cast<size_t>(next3++)];
            steps.push_back({3, u});
            live -= counts[u];
        }
    }
    if (peak) *peak = most;
    return steps;
}

}  // namespace loup

// ------------------------------------------------------------------------------------------------- C interface
namespace {
thread_local loup::TilePlan t_plan;
thread_local std::string t_error;
}  // namespace

extern "C" {

int loup_tile_plan(const double* positions, long long n_atoms, const double* cell, int receivers, long long edges,
                   const int* degree, double reach, const int* shape, long long* n_tiles, long long* n_ghosts,
                   int* grid) {
    try {
        t_plan = loup::plan_tiles(positions, n_atoms, cell, receivers, edges, degree, reach, shape);
    } catch (const std::exception& e) {
        t_plan = loup::TilePlan();
        t_error = e.what();
        return -1;
    }
    t_error.clear();
    if (n_tiles) *n_tiles = t_plan.tiles();
    if (n_ghosts) *n_ghosts = static_cast<long long>(t_plan.ghost.size());
    if (grid) std::memcpy(grid, t_plan.grid, sizeof(t_plan.grid));
    return 0;
}

int loup_tile_plan_copy(long long* local_ptr, int* local, int* local_shift, long long* ghost_ptr, int* ghost,
                        int* ghost_shift) {
    if (t_plan.local_ptr.empty()) {
        t_error = "loup_tile_plan_copy: there is no plan; call loup_tile_plan first";
        return -1;
    }
    const size_t tiles = t_plan.local_ptr.size();
    if (local_ptr)
        for (size_t i = 0; i < tiles; i++) local_ptr[i] = t_plan.local_ptr[i];
    if (ghost_ptr)
        for (size_t i = 0; i < tiles; i++) ghost_ptr[i] = t_plan.ghost_ptr[i];
    if (local) std::memcpy(local, t_plan.local.data(), t_plan.local.size() * sizeof(int32_t));
    if (local_shift) std::memcpy(local_shift, t_plan.local_shift.data(), t_plan.local_shift.size() * sizeof(int32_t));
    if (ghost && !t_plan.ghost.empty()) std::memcpy(ghost, t_plan.ghost.data(), t_plan.ghost.size() * sizeof(int32_t));
    if (ghost_shift && !t_plan.ghost_shift.empty())
        std::memcpy(ghost_shift, t_plan.ghost_shift.data(), t_plan.ghost_shift.size() * sizeof(int32_t));
    return 0;
}

const char* loup_tile_plan_error(void) { return t_error.c_str(); }

int loup_tile_plan_wavefront(const double* positions, long long n_atoms, const double* cell, int receivers,
                             double reach, double boundary_skin, const int* shape, long long* n_tiles,
                             long long* n_ghosts, int* grid) {
    try {
        t_plan = loup::plan_tiles(positions, n_atoms, cell, receivers, 0, nullptr, reach, shape, boundary_skin);
    } catch (const std::exception& e) {
        t_plan = loup::TilePlan();
        t_error = e.what();
        return -1;
    }
    t_error.clear();
    if (n_tiles) *n_tiles = t_plan.tiles();
    if (n_ghosts) *n_ghosts = static_cast<long long>(t_plan.ghost.size());
    if (grid) std::memcpy(grid, t_plan.grid, sizeof(t_plan.grid));
    return 0;
}

int loup_tile_dependencies(long long* needs_ptr, long long* needs, long long* ready, long long* n_needs) {
    if (t_plan.local_ptr.empty()) {
        t_error = "loup_tile_dependencies: there is no plan; call loup_tile_plan first";
        return -1;
    }
    std::vector<int64_t> p, nd, r;
    loup::tile_dependencies(t_plan, p, nd, r);
    if (n_needs) *n_needs = static_cast<long long>(nd.size());
    if (needs_ptr) for (size_t i = 0; i < p.size(); i++) needs_ptr[i] = p[i];
    if (needs) for (size_t i = 0; i < nd.size(); i++) needs[i] = nd[i];
    if (ready) for (size_t i = 0; i < r.size(); i++) ready[i] = r[i];
    return 0;
}

int loup_wavefront_schedule(long long tiles, const long long* needs_ptr, const long long* needs,
                            const long long* ready, const long long* counts, int group, int* out_sweep,
                            long long* out_tile, long long* out_peak) {
    static_assert(sizeof(long long) == sizeof(int64_t), "long long is 64 bits");
    try {
        int64_t peak = 0;
        const auto steps = loup::wavefront_schedule(tiles, reinterpret_cast<const int64_t*>(needs_ptr),
                                                    reinterpret_cast<const int64_t*>(needs),
                                                    reinterpret_cast<const int64_t*>(ready),
                                                    reinterpret_cast<const int64_t*>(counts), group, &peak);
        for (size_t i = 0; i < steps.size(); i++) {
            if (out_sweep) out_sweep[i] = steps[i].sweep;
            if (out_tile) out_tile[i] = steps[i].tile;
        }
        if (out_peak) *out_peak = peak;
    } catch (const std::exception& e) {
        t_error = e.what();
        return -1;
    }
    t_error.clear();
    return 0;
}

}  // extern "C"
