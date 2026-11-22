// clang-format off
/* ----------------------------------------------------------------------
   LAMMPS - Large-scale Atomic/Molecular Massively Parallel Simulator
   https://www.lammps.org/, Sandia National Laboratories
   LAMMPS development team: developers@lammps.org

   This file is part of the LoupMD interface to LAMMPS (https://github.com/FZWINGEL-UBT/LoupMD, lammps/).
   It is distributed under the GNU General Public License, as LAMMPS is.

   See the README file in the top-level LAMMPS directory.
------------------------------------------------------------------------- */

#include "pair_loupmd.h"

#include "atom.h"
#include "comm.h"
#include "domain.h"
#include "error.h"
#include "force.h"
#include "memory.h"
#include "modify.h"
#include "neighbor.h"
#include "update.h"

#include "loupmd.h"

#include <cstring>

using namespace LAMMPS_NS;

namespace {
const char *const kSymbols[] = {
    "X",  "H",  "He", "Li", "Be", "B",  "C",  "N",  "O",  "F",  "Ne", "Na", "Mg", "Al", "Si", "P",  "S",
    "Cl", "Ar", "K",  "Ca", "Sc", "Ti", "V",  "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As",
    "Se", "Br", "Kr", "Rb", "Sr", "Y",  "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I",  "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho",
    "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W",  "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po",
    "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U",  "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md",
    "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds", "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og"};
const int kNumSymbols = sizeof(kSymbols) / sizeof(kSymbols[0]);

int atomic_number(const char *symbol)
{
  for (int z = 1; z < kNumSymbols; z++)
    if (strcmp(symbol, kSymbols[z]) == 0) return z;
  return 0;
}

const char *mode_name(int mode)
{
  switch (mode) {
    case LOUP_EXEC_WHOLE: return "whole";
    case LOUP_EXEC_TILED: return "tiled";
    case LOUP_EXEC_WAVEFRONT: return "wavefront";
    default: return "auto";
  }
}

constexpr double kGiB = 1024.0 * 1024.0 * 1024.0;
}    // namespace

/* ---------------------------------------------------------------------- */

PairLoupMD::PairLoupMD(LAMMPS *lmp) :
    Pair(lmp), handle(nullptr), device(-1), device_loaded(-1), skin_user(-1.0), rmax(0.0), ghost(true), ahead(false),
    system_dirty(true), skin_sent(-1.0), serial(0), exec_mode(LOUP_EXEC_AUTO), receivers_user(0),
    memory_fraction(0.9), memory_sent(-1.0), tiled_mode(false), tile_cap(0), plan_pending(false), plan_whole_gib(0.0), plan_free_gib(0.0), tiled_calls(0), tiled_md_steps(0),
    builds_at_start(0)
{
  single_enable = 0;
  restartinfo = 0;
  one_coeff = 1;
  manybody_flag = 1;
  no_virial_fdotr_compute = 1;    // the engine returns the virial, not pair forces
  centroidstressflag = CENTROID_NOTAVAIL;
  exec_sent[0] = exec_sent[1] = -1;
  for (int k = 0; k < 9; k++) cell_planned[k] = 0.0;
}

/* ---------------------------------------------------------------------- */

PairLoupMD::~PairLoupMD()
{
  if (copymode) return;

  if (handle) loup_destroy(handle);
  if (allocated) {
    memory->destroy(setflag);
    memory->destroy(cutsq);
  }
}

/* ---------------------------------------------------------------------- */

void PairLoupMD::allocate()
{
  allocated = 1;
  int np1 = atom->ntypes + 1;

  memory->create(setflag, np1, np1, "pair:setflag");
  memory->create(cutsq, np1, np1, "pair:cutsq");
  map = new int[np1];
}

/* ----------------------------------------------------------------------
   pair_style loupmd [device N] [skin S] [ghost yes|no] [ahead yes|no]
                     [capacity auto|whole|tiled|wavefront] [receivers N] [memory F]
------------------------------------------------------------------------- */

void PairLoupMD::settings(int narg, char **arg)
{
  // A pair_style command of the same style calls settings() again on this instance: every keyword not given takes
  // its default again.
  device = -1;
  skin_user = -1.0;
  ghost = true;
  ahead = false;
  exec_mode = LOUP_EXEC_AUTO;
  receivers_user = 0;
  memory_fraction = 0.9;
  int iarg = 0;
  while (iarg < narg) {
    if (strcmp(arg[iarg], "device") == 0) {
      if (iarg + 2 > narg) utils::missing_cmd_args(FLERR, "pair_style loupmd device", error);
      device = utils::inumeric(FLERR, arg[iarg + 1], false, lmp);
      if (device < 0) error->all(FLERR, "Pair style loupmd: device must be >= 0");
      iarg += 2;
    } else if (strcmp(arg[iarg], "skin") == 0) {
      if (iarg + 2 > narg) utils::missing_cmd_args(FLERR, "pair_style loupmd skin", error);
      skin_user = utils::numeric(FLERR, arg[iarg + 1], false, lmp);
      if (skin_user < 0.0) error->all(FLERR, "Pair style loupmd: skin must be >= 0");
      iarg += 2;
    } else if (strcmp(arg[iarg], "ghost") == 0) {
      if (iarg + 2 > narg) utils::missing_cmd_args(FLERR, "pair_style loupmd ghost", error);
      ghost = utils::logical(FLERR, arg[iarg + 1], false, lmp) != 0;
      iarg += 2;
    } else if (strcmp(arg[iarg], "ahead") == 0) {
      if (iarg + 2 > narg) utils::missing_cmd_args(FLERR, "pair_style loupmd ahead", error);
      ahead = utils::logical(FLERR, arg[iarg + 1], false, lmp) != 0;
      iarg += 2;
    } else if (strcmp(arg[iarg], "capacity") == 0) {
      if (iarg + 2 > narg) utils::missing_cmd_args(FLERR, "pair_style loupmd capacity", error);
      const char *v = arg[iarg + 1];
      if (strcmp(v, "auto") == 0) exec_mode = LOUP_EXEC_AUTO;
      else if (strcmp(v, "whole") == 0) exec_mode = LOUP_EXEC_WHOLE;
      else if (strcmp(v, "tiled") == 0) exec_mode = LOUP_EXEC_TILED;
      else if (strcmp(v, "wavefront") == 0) exec_mode = LOUP_EXEC_WAVEFRONT;
      else error->all(FLERR, "Pair style loupmd: capacity must be auto, whole, tiled or wavefront, not {}", v);
      iarg += 2;
    } else if (strcmp(arg[iarg], "receivers") == 0) {
      if (iarg + 2 > narg) utils::missing_cmd_args(FLERR, "pair_style loupmd receivers", error);
      receivers_user = utils::inumeric(FLERR, arg[iarg + 1], false, lmp);
      if (receivers_user < 0) error->all(FLERR, "Pair style loupmd: receivers must be >= 0 (0: the plan's)");
      iarg += 2;
    } else if (strcmp(arg[iarg], "memory") == 0) {
      if (iarg + 2 > narg) utils::missing_cmd_args(FLERR, "pair_style loupmd memory", error);
      memory_fraction = utils::numeric(FLERR, arg[iarg + 1], false, lmp);
      if (!(memory_fraction > 0.0 && memory_fraction <= 1.0))
        error->all(FLERR, "Pair style loupmd: memory must be above 0 and at most 1");
      iarg += 2;
    } else
      error->all(FLERR, "Unknown pair_style loupmd keyword: {}", arg[iarg]);
  }
}

/* ----------------------------------------------------------------------
   pair_coeff * * model.loup El1 El2 ...
------------------------------------------------------------------------- */

void PairLoupMD::coeff(int narg, char **arg)
{
  if (!allocated) allocate();

  if (narg != 3 + atom->ntypes)
    error->all(FLERR, "Pair style loupmd: use 'pair_coeff * * model.loup' followed by one element per atom type");
  if (strcmp(arg[0], "*") != 0 || strcmp(arg[1], "*") != 0)
    error->all(FLERR, "Pair style loupmd: pair_coeff must start with '* *'");

  map_element2type(narg - 3, arg + 3);

  bundle = arg[2];
  type2z.assign(atom->ntypes + 1, 0);
  for (int i = 1; i <= atom->ntypes; i++) {
    // The engine evaluates every atom of the system, so no type can be left out (NULL).
    if (map[i] < 0) error->all(FLERR, "Pair style loupmd does not support NULL elements: it evaluates every atom");
    type2z[i] = atomic_number(elements[map[i]]);
    if (type2z[i] == 0) error->all(FLERR, "Pair style loupmd: '{}' is not an element symbol", elements[map[i]]);
  }
}

/* ---------------------------------------------------------------------- */

void PairLoupMD::init_style()
{
  if (strcmp(update->unit_style, "metal") != 0) error->all(FLERR, "Pair style loupmd requires metal units");
  if (atom->tag_enable == 0) error->all(FLERR, "Pair style loupmd requires atom IDs");
  if (comm->nprocs != 1)
    error->all(FLERR, "Pair style loupmd runs on one MPI process: the engine evaluates the whole system on one GPU");
  if (domain->dimension != 3 || !domain->xperiodic || !domain->yperiodic || !domain->zperiodic)
    error->all(FLERR, "Pair style loupmd requires a 3d system that is periodic in x, y and z (put an isolated "
                      "system in a box with more than 2 (cutoff + skin) of vacuum)");
  if (atom->natoms > MAXSMALLINT) error->all(FLERR, "Pair style loupmd: too many atoms");
  if (atom->natoms > 0 && !atom->tag_consecutive())
    error->all(FLERR, "Pair style loupmd requires consecutive atom IDs 1 .. N (use 'reset_atoms id')");
  if (bundle.empty()) error->all(FLERR, "Pair style loupmd: no pair_coeff given");

  const int dev = device >= 0 ? device : default_device();
  if (!handle || bundle != bundle_loaded || dev != device_loaded) {
    if (handle) loup_destroy(handle);
    handle = loup_create(bundle.c_str(), dev);
    if (!handle)
      error->one(FLERR, "Pair style loupmd: could not load {} on CUDA device {}: {}", bundle, dev,
                 loup_last_error(nullptr));
    bundle_loaded = bundle;
    device_loaded = dev;
    z_sent.clear();
    tiled_mode = false;
  }
  rmax = loup_cutoff(handle);

  // `ahead yes`: the engine queues each next force pass ahead of the call that needs it, which takes the launch off
  // every step (3-7% of the step on cells of a few hundred atoms under WSL 2). Between two force calls the engine's
  // GPU stream then holds work that cannot run, and other GPU work of this process could wait for it forever. So it
  // is off by default, and never on with the KOKKOS or GPU package active: switch it on only when the engine is the
  // process's one GPU user. The tiled mode has no such queue: it ignores the keyword.
  const bool other_gpu_user = lmp->kokkos != nullptr || !modify->get_fix_by_style("^GPU").empty();
  loup_set_evaluate_ahead(handle, ahead && !other_gpu_user ? 1 : 0);

  // The capacity mode (LAMMPS_TILED_PLAN.md LD1): the engine's plan decides at each send of the system.
  if (loup_set_execution(handle, exec_mode, receivers_user, memory_fraction) != 0)
    error->all(FLERR, "Pair style loupmd: {}", loup_last_error(handle));
  if (exec_mode == LOUP_EXEC_TILED || exec_mode == LOUP_EXEC_WAVEFRONT) {
    LoupInfo info{};
    if (loup_get_info(handle, &info) == 0) {
      if (info.has_long_range)
        error->all(FLERR, "Pair style loupmd: capacity {}: long-range models (MACE-POLAR-1) cannot run in tiles; use "
                          "capacity whole or auto", mode_name(exec_mode));
      if (exec_mode == LOUP_EXEC_WAVEFRONT && info.n_layers != 2)
        error->all(FLERR, "Pair style loupmd: capacity wavefront needs a model of two layers, {} has {}; use "
                          "capacity tiled", bundle, info.n_layers);
    }
  }

  int zs[128];
  const int ns = loup_species(handle, zs, 128);
  for (int i = 1; i <= atom->ntypes; i++) {
    bool found = false;
    for (int s = 0; s < ns && s < 128; s++) found = found || zs[s] == type2z[i];
    if (!found) {
      std::string have;
      for (int s = 0; s < ns && s < 128; s++) have += std::string(s ? " " : "") + kSymbols[zs[s] < kNumSymbols ? zs[s] : 0];
      error->all(FLERR, "Pair style loupmd: element {} (atom type {}) is not in {}, which holds: {}",
                 kSymbols[type2z[i]], i, bundle, have);
    }
  }

  // the counts of the run's line (finish)
  tiled_calls = tiled_md_steps = 0;
  LoupExecution ex{};
  builds_at_start = loup_get_execution(handle, &ex) == 0 ? ex.list_builds : 0;

  // the engine builds its own neighbour list: none is requested from LAMMPS
  system_dirty = true;
}

/* ---------------------------------------------------------------------- */

double PairLoupMD::init_one(int i, int j)
{
  if (setflag[i][j] == 0) error->all(FLERR, "All pair coeffs are not set");
  // The engine builds its own periodic neighbour list and needs no ghost atoms. With `ghost no` LAMMPS is told a
  // cutoff of zero, so (unless another style or comm_modify asks for more) it creates no ghost atoms and skips their
  // communication in every step.
  return ghost ? rmax : 0.0;
}

/* ----------------------------------------------------------------------
   The engine keeps the system by atom ID (its atom k is the atom with ID k + 1), so LAMMPS may sort and reorder its
   atoms freely. It is given the system again when the atom count, an atom's type, a mass, the skin or the capacity
   settings changed; that is looked for when a run starts and on reneighbouring steps.
------------------------------------------------------------------------- */

void PairLoupMD::ensure_system(bool have_x)
{
  const int n = (int) atom->natoms;
  if (atom->nlocal != n)
    error->one(FLERR, "Pair style loupmd: {} of {} atoms are on this process", atom->nlocal, atom->natoms);
  if (!system_dirty && neighbor->ago != 0 && (int) z_sent.size() == n) return;

  const double skin = skin_user >= 0.0 ? skin_user : neighbor->skin;
  const tagint *tag = atom->tag;
  const int *type = atom->type;
  std::vector<int> z(n, 0);
  for (int i = 0; i < n; i++) {
    if (tag[i] < 1 || tag[i] > n)
      error->one(FLERR, "Pair style loupmd requires consecutive atom IDs 1 .. N (use 'reset_atoms id')");
    z[tag[i] - 1] = type2z[type[i]];
  }
  const bool same_exec =
      exec_mode == exec_sent[0] && receivers_user == exec_sent[1] && memory_fraction == memory_sent;
  if (!system_dirty && skin == skin_sent && z == z_sent && same_exec) return;

  std::vector<double> m(n, 0.0);
  for (int i = 0; i < n; i++) {
    if (z[i] == 0) error->one(FLERR, "Pair style loupmd requires consecutive atom IDs 1 .. N (use 'reset_atoms id')");
    m[tag[i] - 1] = atom->rmass ? atom->rmass[i] : atom->mass[type[i]];
  }
  // A run command sets system_dirty (init_style: the masses may be new). The same system again is not sent: the
  // engine would drop its list, its tuned plans and, under run_style loupmd, the thermostat's state.
  if (skin == skin_sent && z == z_sent && m == m_sent && same_exec) {
    system_dirty = false;
    return;
  }
  send_system(z, m, skin, have_x);
}

/* ----------------------------------------------------------------------
   The send (LAMMPS_TILED_PLAN.md LD1): under capacity auto, tiled or wavefront the engine plans first. A plan of
   WHOLE is today's path (loup_set_system); a plan of TILED gives no whole system to the engine: the pair style keeps
   the plan's cap and calls loup_evaluate_tiled with it, never with 0, so a cell that changes later does not make the
   engine plan (and drop its kept tile lists) again.
------------------------------------------------------------------------- */

void PairLoupMD::send_system(const std::vector<int> &z, const std::vector<double> &m, double skin, bool have_x)
{
  const int n = (int) z.size();
  tiled_mode = false;
  plan_pending = false;
  double cell[9];
  box_to_cell(cell);
  LoupMemoryPlan plan{};
  bool planned = false;
  if (exec_mode != LOUP_EXEC_WHOLE) {
    if (!have_x) gather_unwrapped();
    if (loup_plan_execution(handle, n, z.data(), xbuf.data(), cell, skin, &plan) != 0)
      error->one(FLERR, "Pair style loupmd: capacity {}: no plan for {} atoms: {}", mode_name(exec_mode), n,
                 loup_last_error(handle));
    planned = true;
    plan_whole_gib = (double) plan.whole_bytes / kGiB;
    plan_free_gib = (double) plan.free_bytes / kGiB;
    if (plan.mode == LOUP_EXEC_TILED) {
      tiled_mode = true;
      tile_cap = plan.receivers;
      memcpy(cell_planned, cell, sizeof(cell));
      plan_pending = true;    // the line follows the first tiled call, which knows the tiles and the schedule
      if (ahead && comm->me == 0) utils::logmesg(lmp, "LoupMD: 'ahead yes' has no effect in tiled mode\n");
    }
  }
  if (!tiled_mode) {
    if (loup_set_system(handle, n, z.data(), m.data(), skin) != 0) {
      LoupInfo info{};
      const bool long_range = loup_get_info(handle, &info) == 0 && info.has_long_range;
      error->one(FLERR, "Pair style loupmd: the engine refused the system: {}{}", loup_last_error(handle),
                 long_range ? " (the cell does not fit the card whole, and long-range models such as MACE-POLAR-1 "
                              "cannot run in tiles: use a smaller cell)" : "");
    }
    if (planned && plan.whole_bytes > 0 && comm->me == 0)
      utils::logmesg(lmp, "LoupMD: {} atoms run whole: the cell needs {:.2f} GiB, {:.2f} GiB free\n", n,
                     plan_whole_gib, plan_free_gib);
  }
  serial++;
  z_sent = z;
  m_sent = m;
  skin_sent = skin;
  exec_sent[0] = exec_mode;
  exec_sent[1] = receivers_user;
  memory_sent = memory_fraction;
  system_dirty = false;
}

/* ----------------------------------------------------------------------
   Unwrapped positions by atom ID - 1: the engine's skin check needs them continuous across LAMMPS's re-wrapping
   into the box (in tiled mode too: the kept tile lists compare plain Cartesian displacements).
------------------------------------------------------------------------- */

void PairLoupMD::gather_unwrapped()
{
  sync_host_positions();
  const int n = atom->nlocal;
  double **x = atom->x;
  const tagint *tag = atom->tag;
  const imageint *image = atom->image;
  xbuf.resize(3 * (size_t) n);
  for (int i = 0; i < n; i++) {
    double u[3];
    domain->unmap(x[i], image[i], u);
    const size_t k = 3 * (size_t) (tag[i] - 1);
    xbuf[k] = u[0];
    xbuf[k + 1] = u[1];
    xbuf[k + 2] = u[2];
  }
}

/* ---------------------------------------------------------------------- */

LoupHandle *PairLoupMD::engine()
{
  ensure_system();
  return handle;
}

/* ---------------------------------------------------------------------- */

void PairLoupMD::box_to_cell(double *cell) const
{
  // lattice vectors as rows: a = (xprd, 0, 0), b = (xy, yprd, 0), c = (xz, yz, zprd)
  cell[0] = domain->xprd; cell[1] = 0.0;          cell[2] = 0.0;
  cell[3] = domain->xy;   cell[4] = domain->yprd; cell[5] = 0.0;
  cell[6] = domain->xz;   cell[7] = domain->yz;   cell[8] = domain->zprd;
}

/* ---------------------------------------------------------------------- */

void PairLoupMD::refuse_per_atom() const
{
  if (eflag_atom || vflag_atom)
    error->all(FLERR, "Pair style loupmd does not provide per-atom energies or virials");
}

/* ----------------------------------------------------------------------
   The tiled force call (LD4) with the plan's cap. A box that changes in every step (fix npt, fix deform, box/relax)
   keeps the tile lists while the strain since their build leaves room for the atoms' moves (LAMMPS_TILED_PLAN.md
   LT6 (a)). When the call fails on a cell other than the plan's, the engine plans once more at this cell and the
   call is repeated (LD3): the tiles of a denser cell may need a smaller cap.
------------------------------------------------------------------------- */

void PairLoupMD::evaluate_tiled(const double *x, double *energy, double *f, double *stress)
{
  double cell[9];
  box_to_cell(cell);
  const int n = (int) z_sent.size();
  long long tiles = 0;
  int rc = loup_evaluate_tiled(handle, n, z_sent.data(), x, cell, tile_cap, skin_sent, energy, f, stress, &tiles);
  if (rc != 0 && memcmp(cell, cell_planned, sizeof(cell)) != 0) {
    const std::string first = loup_last_error(handle);
    const int mode = exec_mode == LOUP_EXEC_WAVEFRONT ? LOUP_EXEC_WAVEFRONT : LOUP_EXEC_TILED;
    LoupMemoryPlan plan{};
    if (loup_set_execution(handle, mode, receivers_user, memory_fraction) != 0 ||
        loup_plan_execution(handle, n, z_sent.data(), x, cell, skin_sent, &plan) != 0 ||
        loup_set_execution(handle, exec_mode, receivers_user, memory_fraction) != 0)
      error->one(FLERR, "Pair style loupmd: the tiled force evaluation failed ({}), and the plan at the new cell "
                        "failed too: {}", first, loup_last_error(handle));
    if (comm->me == 0)
      utils::logmesg(lmp, "LoupMD: the tiled call failed on a changed cell ({}): planned again, {} receivers per "
                          "tile instead of {}\n", first, plan.receivers, tile_cap);
    tile_cap = plan.receivers;
    memcpy(cell_planned, cell, sizeof(cell));
    serial++;    // the plan dropped the engine's tiled state
    rc = loup_evaluate_tiled(handle, n, z_sent.data(), x, cell, tile_cap, skin_sent, energy, f, stress, &tiles);
  }
  if (rc != 0)
    error->one(FLERR, "Pair style loupmd: the tiled force evaluation failed: {}", loup_last_error(handle));
  tiled_calls++;
  if (plan_pending) {
    plan_pending = false;
    LoupExecution ex{};
    if (loup_get_execution(handle, &ex) == 0 && comm->me == 0) {
      const char *where = ex.host_state ? "tile lists and layer state in host memory"
                        : ex.host_lists ? "tile lists in host memory" : "tile lists on the device";
      utils::logmesg(lmp, "LoupMD: {} atoms run tiled{}: {} tiles of at most {} atoms, {}; the whole cell would "
                          "need {:.2f} GiB, {:.2f} GiB free\n", n,
                     ex.mode == LOUP_EXEC_WAVEFRONT ? " (wavefront schedule)" : "", ex.tiles, ex.receivers, where,
                     plan_whole_gib, plan_free_gib);
    }
  }
}

/* ----------------------------------------------------------------------
   The run's line in tiled mode: the tiled calls of the pair style, the steps run_style loupmd ran in the engine's
   tiled MD, and the tile list builds of both.
------------------------------------------------------------------------- */

void PairLoupMD::finish()
{
  if (!handle || !tiled_mode || tiled_calls + tiled_md_steps == 0) return;
  LoupExecution ex{};
  if (loup_get_execution(handle, &ex) != 0) return;
  if (comm->me == 0)
    utils::logmesg(lmp, "LoupMD: tiled mode in this run: {} tiled force calls, {} tiled MD steps, tile lists built "
                        "{} times; {} tiles of at most {} atoms{}\n", tiled_calls, tiled_md_steps,
                   ex.list_builds - builds_at_start, ex.tiles, ex.receivers,
                   ex.mode == LOUP_EXEC_WAVEFRONT ? ", wavefront schedule" : "");
}

/* ----------------------------------------------------------------------
   Host arrays: positions go to the engine and forces come back through host memory (loup_evaluate, or
   loup_evaluate_tiled in tiled mode). The Kokkos style loupmd/kk keeps both on the GPU for a whole system.
------------------------------------------------------------------------- */

void PairLoupMD::compute(int eflag, int vflag)
{
  ev_init(eflag, vflag, 0);
  refuse_per_atom();
  gather_unwrapped();    // before ensure_system: a plan reads them
  ensure_system(true);

  const int n = atom->nlocal;
  double **f = atom->f;
  const tagint *tag = atom->tag;
  fbuf.resize(3 * (size_t) n);

  double cell[9], stress[9], energy = 0.0;
  box_to_cell(cell);
  if (tiled_mode) {
    // the stress only when LAMMPS asks for the virial: the sweeps skip it otherwise
    evaluate_tiled(xbuf.data(), &energy, fbuf.data(), vflag_global ? stress : nullptr);
  } else if (loup_evaluate(handle, xbuf.data(), cell, 1, &energy, fbuf.data(), stress) != 0) {
    // The stress is formed in every call: steps that need it then run the engine's captured graph as the others
    // do, instead of re-capturing it.
    error->one(FLERR, "Pair style loupmd: the force evaluation failed: {}", loup_last_error(handle));
  }

  for (int i = 0; i < n; i++) {
    const size_t k = 3 * (size_t) (tag[i] - 1);
    f[i][0] += fbuf[k];
    f[i][1] += fbuf[k + 1];
    f[i][2] += fbuf[k + 2];
  }

  if (eflag_global) eng_vdwl += energy;
  if (vflag_global) {
    // the engine's stress is dE/d(strain) / V; LAMMPS's virial is -dE/d(strain), as xx yy zz xy xz yz
    const double vol = domain->xprd * domain->yprd * domain->zprd;
    virial[0] -= stress[0] * vol;
    virial[1] -= stress[4] * vol;
    virial[2] -= stress[8] * vol;
    virial[3] -= stress[1] * vol;
    virial[4] -= stress[2] * vol;
    virial[5] -= stress[5] * vol;
  }
}
