// clang-format off
/* ----------------------------------------------------------------------
   LAMMPS - Large-scale Atomic/Molecular Massively Parallel Simulator
   https://www.lammps.org/, Sandia National Laboratories
   LAMMPS development team: developers@lammps.org

   This file is part of the LoupMD interface to LAMMPS (https://github.com/FZWINGEL-UBT/LoupMD, lammps/).
   It is distributed under the GNU General Public License, as LAMMPS is.

   See the README file in the top-level LAMMPS directory.
------------------------------------------------------------------------- */

#include "integrate_loupmd.h"

#include "atom.h"
#include "comm.h"
#include "compute.h"
#include "domain.h"
#include "error.h"
#include "fix_langevin.h"
#include "fix_momentum.h"
#include "fix_nh.h"
#include "fix_press_berendsen.h"
#include "fix_setforce.h"
#include "fix_temp_berendsen.h"
#include "force.h"
#include "group.h"
#include "label_map.h"
#include "modify.h"
#include "neighbor.h"
#include "output.h"
#include "pair_loupmd.h"
#include "random_mars.h"
#include "timer.h"
#include "update.h"

#if __has_include("fix_temp_csvr.h")
#include "fix_temp_csvr.h"    // package EXTRA-FIX
#define LOUPMD_HAVE_TEMP_CSVR 1
#endif

#include "loupmd.h"

#include <algorithm>
#include <cmath>
#include <cstring>

using namespace LAMMPS_NS;
using namespace FixConst;

// LAMMPS's metal velocities are in A/ps; the engine's are in ASE units (A per ASE time unit; 1 fs is
// 0.09822694788464063 of them), so v[A/ps] = 1000 * 0.0982269... * v[ASE].
static constexpr double kVelLmpPerAse = 98.22694788464063;
static constexpr double kGPaPerBar = 1.0e-4;
static const char kVerlet[] = "Use the default run style (run_style verlet) with pair_style loupmd for this input";

/* ----------------------------------------------------------------------
   The fixes keep their settings in protected members. A class derived from a fix may name them, and the pointer to
   such a member is a pointer to a member of the fix itself, so it reads the setting from the fix object. The
   constants are those of the fixes' source files (their enums are not in the headers). Only what a fix sets in its
   constructor or through fix_modify is read: the run style's init() runs before the fixes' own.
------------------------------------------------------------------------- */

namespace {

enum { TSTYLE_CONSTANT = 0 };                      // fix_langevin.cpp, fix_temp_csvr.cpp, fix_temp_berendsen.cpp
enum { PCOUPLE_NONE = 0, PCOUPLE_XYZ = 1 };        // fix_nh.cpp, fix_press_berendsen.cpp
enum { PSTYLE_ISO = 0, PSTYLE_ANISO = 1 };

struct NHSettings {
  double t_start, t_stop, t_freq, drag, p_start[3], p_stop[3], p_freq[3];
  int tstat, pstat, pstyle, pcouple, allremap, p_flag[6], tchain, pchain, tloop, ploop, mtk, deviatoric, tcompute,
      pcompute;
};

struct PeekNH : FixNH {
  static NHSettings read(const FixNH *f)
  {
    NHSettings s;
    s.t_start = f->*(&PeekNH::t_start);
    s.t_stop = f->*(&PeekNH::t_stop);
    s.t_freq = f->*(&PeekNH::t_freq);
    s.drag = f->*(&PeekNH::drag);
    s.tstat = f->*(&PeekNH::tstat_flag);
    s.pstat = f->*(&PeekNH::pstat_flag);
    s.pstyle = f->*(&PeekNH::pstyle);
    s.pcouple = f->*(&PeekNH::pcouple);
    s.allremap = f->*(&PeekNH::allremap);
    for (int i = 0; i < 6; i++) s.p_flag[i] = (f->*(&PeekNH::p_flag))[i];
    for (int i = 0; i < 3; i++) {
      s.p_start[i] = (f->*(&PeekNH::p_start))[i];
      s.p_stop[i] = (f->*(&PeekNH::p_stop))[i];
      s.p_freq[i] = (f->*(&PeekNH::p_freq))[i];
    }
    s.tchain = f->*(&PeekNH::mtchain);
    s.pchain = f->*(&PeekNH::mpchain);
    s.tloop = f->*(&PeekNH::nc_tchain);
    s.ploop = f->*(&PeekNH::nc_pchain);
    s.mtk = f->*(&PeekNH::mtk_flag);
    s.deviatoric = f->*(&PeekNH::deviatoric_flag);
    s.tcompute = f->*(&PeekNH::tcomputeflag);
    s.pcompute = f->*(&PeekNH::pcomputeflag);
    return s;
  }
};

struct LangevinSettings {
  double t_start, t_stop, t_period;
  int seed, tstyle, zero, omega, angmom;
  bool scaled, own_temp;
};

struct PeekLangevin : FixLangevin {
  static LangevinSettings read(const FixLangevin *f, int ntypes)
  {
    LangevinSettings s;
    s.t_start = f->*(&PeekLangevin::t_start);
    s.t_stop = f->*(&PeekLangevin::t_stop);
    s.t_period = f->*(&PeekLangevin::t_period);
    s.seed = f->*(&PeekLangevin::seed);
    s.tstyle = f->*(&PeekLangevin::tstyle);
    s.zero = f->*(&PeekLangevin::zeroflag);
    s.omega = f->*(&PeekLangevin::oflag);
    s.angmom = f->*(&PeekLangevin::osflag);
    s.own_temp = (f->*(&PeekLangevin::id_temp)) != nullptr;    // fix_modify temp
    const double *ratio = f->*(&PeekLangevin::ratio);
    s.scaled = false;
    for (int i = 1; ratio && i <= ntypes; i++) s.scaled = s.scaled || ratio[i] != 1.0;
    return s;
  }
};

struct TempSettings {
  double t_start, t_stop, t_period;
  int tstyle, own_compute;
};

struct PeekTempBerendsen : FixTempBerendsen {
  static TempSettings read(const FixTempBerendsen *f)
  {
    return {f->*(&PeekTempBerendsen::t_start), f->*(&PeekTempBerendsen::t_stop), f->*(&PeekTempBerendsen::t_period),
            f->*(&PeekTempBerendsen::tstyle), f->*(&PeekTempBerendsen::tflag)};
  }
};

#ifdef LOUPMD_HAVE_TEMP_CSVR
struct PeekTempCSVR : FixTempCSVR {
  static TempSettings read(const FixTempCSVR *f)
  {
    return {f->*(&PeekTempCSVR::t_start), f->*(&PeekTempCSVR::t_stop), f->*(&PeekTempCSVR::t_period),
            f->*(&PeekTempCSVR::tstyle), f->*(&PeekTempCSVR::tflag)};
  }
  static RanMars *random_of(const FixTempCSVR *f) { return f->*(&PeekTempCSVR::random); }
};
#endif

struct PressSettings {
  double modulus, p_start[3], p_stop[3], p_period[3];
  int pstyle, pcouple, allremap, p_flag[3];
};

struct PeekPressBerendsen : FixPressBerendsen {
  static PressSettings read(const FixPressBerendsen *f)
  {
    PressSettings s;
    s.modulus = f->*(&PeekPressBerendsen::bulkmodulus);
    s.pstyle = f->*(&PeekPressBerendsen::pstyle);
    s.pcouple = f->*(&PeekPressBerendsen::pcouple);
    s.allremap = f->*(&PeekPressBerendsen::allremap);
    for (int i = 0; i < 3; i++) {
      s.p_flag[i] = (f->*(&PeekPressBerendsen::p_flag))[i];
      s.p_start[i] = (f->*(&PeekPressBerendsen::p_start))[i];
      s.p_stop[i] = (f->*(&PeekPressBerendsen::p_stop))[i];
      s.p_period[i] = (f->*(&PeekPressBerendsen::p_period))[i];
    }
    return s;
  }
};

struct PeekSetForce : FixSetForce {
  // true for 'fix ID group setforce 0.0 0.0 0.0': three constants, all zero, no region
  static bool holds(const FixSetForce *f)
  {
    if (f->*(&PeekSetForce::xstr) || f->*(&PeekSetForce::ystr) || f->*(&PeekSetForce::zstr)) return false;
    if (f->*(&PeekSetForce::idregion)) return false;
    if (f->*(&PeekSetForce::xstyle) != CONSTANT || f->*(&PeekSetForce::ystyle) != CONSTANT ||
        f->*(&PeekSetForce::zstyle) != CONSTANT)
      return false;
    return f->*(&PeekSetForce::xvalue) == 0.0 && f->*(&PeekSetForce::yvalue) == 0.0 &&
        f->*(&PeekSetForce::zvalue) == 0.0;
  }
};

struct PeekMomentum : FixMomentum {
  // true for 'fix ID all momentum N linear 1 1 1' without angular or rescale
  static bool linear_all(const FixMomentum *f)
  {
    return f->*(&PeekMomentum::linear) && !(f->*(&PeekMomentum::angular)) && !(f->*(&PeekMomentum::rescale)) &&
        f->*(&PeekMomentum::xflag) && f->*(&PeekMomentum::yflag) && f->*(&PeekMomentum::zflag);
  }
};

}    // namespace

/* ----------------------------------------------------------------------
   run_style loupmd [nve | langevin T damp seed]
------------------------------------------------------------------------- */

IntegrateLoupMD::IntegrateLoupMD(LAMMPS *lmp, int narg, char **arg) :
    Integrate(lmp, narg, arg), from_fixes(0), move_groupbit(1), pair(nullptr), triclinic(0), varcell(false),
    box_moved(false), fix_com(0), nfixed(0), snap_serial(-1), engine_current(false), tiled(false),
    tiled_md_serial(-1)
{
  memset(snap_cell, 0, sizeof(snap_cell));
  if (narg == 0) {
    from_fixes = 1;
  } else if (strcmp(arg[0], "nve") == 0) {
    if (narg != 1) error->all(FLERR, "run_style loupmd nve takes no further arguments");
    ens.kind = LOUP_NVE;
    lines.emplace_back("nve (run_style loupmd nve): velocity Verlet");
  } else if (strcmp(arg[0], "langevin") == 0) {
    if (narg != 4) error->all(FLERR, "run_style loupmd langevin needs: T damp seed");
    ens.kind = LOUP_LANGEVIN;
    ens.t_start = ens.t_stop = utils::numeric(FLERR, arg[1], false, lmp);
    ens.tau_t = utils::numeric(FLERR, arg[2], false, lmp);
    ens.seed = (unsigned long long) utils::bnumeric(FLERR, arg[3], false, lmp);
    if (ens.t_start < 0.0 || ens.tau_t <= 0.0)
      error->all(FLERR, "run_style loupmd langevin: T must be >= 0 and damp > 0");
    lines.push_back(fmt::format("langevin {} K, damp {} ps (run_style loupmd langevin): Langevin, the "
                                "Vanden-Eijnden-Ciccotti scheme", ens.t_start, ens.tau_t));
  } else
    error->all(FLERR, "Unknown run_style loupmd ensemble: {} (nve, langevin T damp seed, or nothing: the ensemble "
                      "is then taken from the input's fixes)", arg[0]);
}

/* ---------------------------------------------------------------------- */

void IntegrateLoupMD::init()
{
  Integrate::init();

  pair = dynamic_cast<PairLoupMD *>(force->pair);
  if (!pair) error->all(FLERR, "run_style loupmd requires pair_style loupmd (alone, not inside pair_style hybrid)");
  if (lmp->kokkos)
    error->all(FLERR, "run_style loupmd runs without the KOKKOS package switched on (no '-k on' / '-sf kk'): the "
                      "engine integrates on the GPU itself");
  if (force->bond || force->angle || force->dihedral || force->improper || force->kspace)
    error->all(FLERR, "run_style loupmd: the engine computes all forces, so bonded and kspace styles cannot be used");

  // as Verlet: how the pair style is asked for the virial, and the computes that need energy / virial on a step
  if (force->newton_pair) virial_style = VIRIAL_FDOTR;
  else virial_style = VIRIAL_PAIR;
  ev_setup();
  if (modify->get_fix_by_id("package_omp")) external_force_clear = 1;

  triclinic = domain->triclinic;
  if (from_fixes) read_fixes();
}

/* ----------------------------------------------------------------------
   The ensemble from the input's fixes. Every fix that acts during the steps is either taken over (the engine has
   an integrator for it) or refused by name with the reason: nothing is dropped silently.
------------------------------------------------------------------------- */

void IntegrateLoupMD::read_fixes()
{
  ens = Ensemble();
  lines.clear();
  hold_groupbits.clear();
  hold_fixes.clear();
  stood_in.clear();
  varcell = false;

  auto refuse = [this](const Fix *fix, const std::string &why) {
    error->all(FLERR, "run_style loupmd cannot take over fix {} ({}): {}. {}", fix->id, fix->style, why, kVerlet);
  };
  const int step_mask = INITIAL_INTEGRATE | POST_INTEGRATE | PRE_EXCHANGE | PRE_NEIGHBOR | POST_NEIGHBOR |
      PRE_FORCE | PRE_REVERSE | POST_FORCE | FINAL_INTEGRATE | END_OF_STEP;

  Fix *integrator = nullptr, *thermostat = nullptr, *barostat = nullptr;
  const auto &fixes = modify->get_fix_list();
  for (std::size_t i = 0; i < fixes.size(); i++) {
    Fix *fix = fixes[i];
    const std::string style = fix->style;
    if (style == "nve" || style == "nvt" || style == "npt") {
      if (integrator) refuse(fix, fmt::format("fix {} integrates already, and the engine runs one integrator",
                                               integrator->id));
      integrator = fix;
    } else if (style == "langevin" || style == "temp/csvr" || style == "temp/berendsen") {
      if (thermostat) refuse(fix, fmt::format("fix {} is a thermostat already", thermostat->id));
      thermostat = fix;
    } else if (style == "press/berendsen") {
      if (barostat) refuse(fix, fmt::format("fix {} is a barostat already", barostat->id));
      barostat = fix;
    } else if (style == "setforce") {
      auto *sf = dynamic_cast<FixSetForce *>(fix);
      if (!sf || !PeekSetForce::holds(sf))
        refuse(fix, "only 'setforce 0.0 0.0 0.0' on a group, without a region or variables, is taken over (as "
                    "atoms held in place)");
      hold_groupbits.push_back(fix->groupbit);
      hold_fixes.push_back(fix);
      lines.push_back(fmt::format("fix {} (setforce 0 0 0): its atoms are held in place", fix->id));
    } else if (style == "momentum") {
      auto *mom = dynamic_cast<FixMomentum *>(fix);
      if (!mom || fix->igroup != 0 || !PeekMomentum::linear_all(mom))
        refuse(fix, "only 'momentum N linear 1 1 1' on group all is taken over");
      ens.momentum = 1;
      stood_in.push_back(fix);
      lines.push_back(fmt::format("fix {} (momentum linear): the centre of mass is kept at rest", fix->id));
    } else if (modify->fmask[i] & step_mask) {
      refuse(fix, "it acts during the steps, and the engine has no counterpart for it");
    }
  }
  if (!integrator)
    error->all(FLERR, "run_style loupmd: the input has no fix nve, fix nvt or fix npt, so there is no ensemble to "
                      "run (or name it: run_style loupmd nve)");
  if (group->dynamic[integrator->igroup])
    refuse(integrator, "its group is dynamic, and the engine decides once per run which atoms move");
  move_groupbit = integrator->groupbit;
  stood_in.push_back(integrator);
  if (thermostat) stood_in.push_back(thermostat);
  if (barostat) stood_in.push_back(barostat);
  auto same_atoms = [&](const Fix *fix) {
    if (fix->igroup != 0 && fix->groupbit != integrator->groupbit)
      refuse(fix, fmt::format("its group must be all or the group of fix {}", integrator->id));
  };
  const std::string istyle = integrator->style;

  if (istyle == "nve") {
    if (barostat && !(thermostat && strcmp(thermostat->style, "temp/berendsen") == 0))
      refuse(barostat, "the engine's Berendsen barostat comes with the Berendsen thermostat (add fix "
                       "temp/berendsen)");
    if (!thermostat) {
      ens.kind = LOUP_NVE;
      lines.push_back(fmt::format("fix {} (nve): velocity Verlet", integrator->id));
    } else if (strcmp(thermostat->style, "langevin") == 0) {
      same_atoms(thermostat);
      auto *fl = dynamic_cast<FixLangevin *>(thermostat);
      if (!fl) refuse(thermostat, "not the plain fix langevin");
      const LangevinSettings s = PeekLangevin::read(fl, atom->ntypes);
      if (s.tstyle != TSTYLE_CONSTANT) refuse(thermostat, "its temperature is a variable");
      if (s.own_temp) refuse(thermostat, "a temperature compute of its own (fix_modify temp)");
      if (s.omega || s.angmom) refuse(thermostat, "omega / angmom thermostatting");
      if (s.scaled) refuse(thermostat, "per-type scale factors");
      ens.kind = LOUP_LANGEVIN;
      ens.t_start = s.t_start;
      ens.t_stop = s.t_stop;
      ens.tau_t = s.t_period;
      ens.seed = (unsigned long long) s.seed;
      if (s.zero) ens.momentum = 1;
      lines.push_back(fmt::format("fix {} (nve) + fix {} (langevin {} -> {} K, damp {} ps{}): Langevin, the "
                                  "Vanden-Eijnden-Ciccotti scheme (not fix langevin's own)", integrator->id,
                                  thermostat->id, s.t_start, s.t_stop, s.t_period, s.zero ? ", zero yes" : ""));
    } else if (strcmp(thermostat->style, "temp/csvr") == 0) {
#ifdef LOUPMD_HAVE_TEMP_CSVR
      same_atoms(thermostat);
      auto *fc = dynamic_cast<FixTempCSVR *>(thermostat);
      if (!fc) refuse(thermostat, "not the plain fix temp/csvr");
      const TempSettings s = PeekTempCSVR::read(fc);
      if (s.tstyle != TSTYLE_CONSTANT) refuse(thermostat, "its temperature is a variable");
      if (!s.own_compute) refuse(thermostat, "a temperature compute of its own (fix_modify temp)");
      ens.kind = LOUP_CSVR;
      ens.t_start = s.t_start;
      ens.t_stop = s.t_stop;
      ens.tau_t = s.t_period;
      // the fix keeps no seed, only its generator: one number drawn from it, once, seeds the engine's noise
      std::size_t k = 0;
      while (k < csvr_ids.size() && csvr_ids[k] != thermostat->id) k++;
      if (k == csvr_ids.size()) {
        csvr_ids.emplace_back(thermostat->id);
        csvr_seeds.push_back(1ULL + (unsigned long long) (PeekTempCSVR::random_of(fc)->uniform() * 4503599627370496.0));
      }
      ens.seed = csvr_seeds[k];
      lines.push_back(fmt::format("fix {} (nve) + fix {} (temp/csvr {} -> {} K, Tdamp {} ps): velocity rescaling "
                                  "of Bussi, Donadio and Parrinello", integrator->id, thermostat->id, s.t_start,
                                  s.t_stop, s.t_period));
#else
      refuse(thermostat, "this LAMMPS was built without the EXTRA-FIX package");
#endif
    } else {    // temp/berendsen, with or without press/berendsen
      same_atoms(thermostat);
      auto *fb = dynamic_cast<FixTempBerendsen *>(thermostat);
      if (!fb) refuse(thermostat, "not the plain fix temp/berendsen");
      const TempSettings s = PeekTempBerendsen::read(fb);
      if (s.tstyle != TSTYLE_CONSTANT) refuse(thermostat, "its temperature is a variable");
      if (!s.own_compute) refuse(thermostat, "a temperature compute of its own (fix_modify temp)");
      ens.kind = LOUP_BERENDSEN_NVT;
      ens.t_start = s.t_start;
      ens.t_stop = s.t_stop;
      ens.tau_t = s.t_period;
      std::string text = fmt::format("fix {} (nve) + fix {} (temp/berendsen {} -> {} K, Tdamp {} ps)",
                                     integrator->id, thermostat->id, s.t_start, s.t_stop, s.t_period);
      if (barostat) {
        if (barostat->igroup != 0) refuse(barostat, "its group must be all (the whole cell is scaled)");
        auto *fp = dynamic_cast<FixPressBerendsen *>(barostat);
        if (!fp) refuse(barostat, "not the plain fix press/berendsen");
        const PressSettings p = PeekPressBerendsen::read(fp);
        if (!p.allremap) refuse(barostat, "dilate with a group");
        int first = -1;
        for (int d = 0; d < 3; d++) {
          if (!p.p_flag[d]) continue;
          if (first < 0) first = d;
          if (p.p_start[d] != p.p_stop[d]) refuse(barostat, "a pressure ramp");
          if (p.p_start[d] != p.p_start[first] || p.p_period[d] != p.p_period[first])
            refuse(barostat, "different pressures or Pdamp per direction (the engine has one of each)");
        }
        if (first < 0) refuse(barostat, "no direction is barostatted");
        if (p.pstyle == PSTYLE_ISO && p.pcouple == PCOUPLE_XYZ) {
          ens.cell_full = 0;
        } else if (p.pstyle == PSTYLE_ANISO && p.pcouple == PCOUPLE_NONE && !triclinic) {
          ens.cell_full = 1;
          for (int d = 0; d < 3; d++) ens.cell_mask[d] = p.p_flag[d] ? 1 : 0;
        } else {
          refuse(barostat, "only 'iso', and 'aniso' or single directions without couple in an orthogonal box, "
                           "are taken over");
        }
        ens.kind = LOUP_BERENDSEN_NPT;
        ens.pressure = p.p_start[first];
        ens.tau_p = p.p_period[first];
        ens.modulus = p.modulus;
        varcell = true;
        text += fmt::format(" + fix {} (press/berendsen {} {} bar, Pdamp {} ps, modulus {} bar)", barostat->id,
                            ens.cell_full ? "per direction" : "iso", ens.pressure, ens.tau_p, ens.modulus);
      }
      lines.push_back(text + (barostat ? ": Berendsen thermostat and barostat" : ": Berendsen thermostat"));
    }
  } else {    // nvt, npt
    if (thermostat) refuse(thermostat, fmt::format("fix {} thermostats already", integrator->id));
    if (barostat) refuse(barostat, fmt::format("fix {} is the integrator, and it has no Berendsen barostat",
                                               integrator->id));
    auto *nh = dynamic_cast<FixNH *>(integrator);
    if (!nh) refuse(integrator, "not the plain fix nvt / npt");
    const NHSettings s = PeekNH::read(nh);
    if (!s.tstat) refuse(integrator, "no thermostat");
    if (!s.tcompute) refuse(integrator, "a temperature compute of its own (fix_modify temp)");
    if (s.drag != 0.0) refuse(integrator, "drag");
    ens.t_start = s.t_start;
    ens.t_stop = s.t_stop;
    ens.tau_t = 1.0 / s.t_freq;
    ens.tchain = s.tchain;
    ens.tloop = s.tloop;
    if (istyle == "nvt") {
      if (s.pstat) refuse(integrator, "a barostat in fix nvt");
      if (s.tchain < 1 || s.tchain > 16) refuse(integrator, "tchain must be from 1 to 16");
      ens.kind = LOUP_NHC;
      lines.push_back(fmt::format("fix {} (nvt {} -> {} K, Tdamp {} ps, tchain {}): Nose-Hoover chain",
                                  integrator->id, s.t_start, s.t_stop, ens.tau_t, s.tchain));
    } else {
      if (!s.pstat) refuse(integrator, "no barostat");
      if (integrator->igroup != 0) refuse(integrator, "its group must be all (the whole cell is scaled)");
      if (s.pstyle != PSTYLE_ISO || s.pcouple != PCOUPLE_XYZ || !s.p_flag[0] || !s.p_flag[1] || !s.p_flag[2] ||
          s.p_flag[3] || s.p_flag[4] || s.p_flag[5])
        refuse(integrator, "only 'iso' is taken over (the engine's other cell mode moves all nine components of "
                           "the box, which neither aniso nor tri does)");
      if (s.p_start[0] != s.p_stop[0]) refuse(integrator, "a pressure ramp");
      if (!s.mtk) refuse(integrator, "mtk no");
      if (!s.allremap) refuse(integrator, "dilate with a group");
      if (s.deviatoric) refuse(integrator, "a deviatoric target stress");
      if (!s.pcompute) refuse(integrator, "a pressure compute of its own (fix_modify press)");
      if (s.tchain < 1 || s.tchain > 8) refuse(integrator, "tchain must be from 1 to 8 with a barostat");
      if (s.pchain < 1 || s.pchain > 8) refuse(integrator, "pchain must be from 1 to 8");
      ens.kind = LOUP_MTK_NPT;
      ens.pressure = s.p_start[0];
      ens.tau_p = 1.0 / s.p_freq[0];
      ens.pchain = s.pchain;
      ens.ploop = s.ploop;
      varcell = true;
      lines.push_back(fmt::format("fix {} (npt {} -> {} K, Tdamp {} ps, iso {} bar, Pdamp {} ps): "
                                  "Martyna-Tobias-Klein, isotropic", integrator->id, s.t_start, s.t_stop, ens.tau_t,
                                  ens.pressure, ens.tau_p));
    }
  }
  if (integrator->igroup != 0)
    lines.push_back(fmt::format("atoms outside group {} are held in place", group->names[integrator->igroup]));
}

/* ----------------------------------------------------------------------
   Everything that makes the ensemble what it is: the engine carries a thermostat's and a barostat's variables from
   one run to the next only under the same key.
------------------------------------------------------------------------- */

std::string IntegrateLoupMD::ensemble_key() const
{
  std::string key = fmt::format("{} {} {} {} {} {} {} {} {} {} {} {} {} {}{}{} {} {}", ens.kind, ens.t_start,
                                ens.t_stop, ens.tau_t, ens.pressure, ens.tau_p, ens.modulus, ens.tchain, ens.tloop,
                                ens.pchain, ens.ploop, ens.cell_full, ens.cell_mask[0], ens.cell_mask[1],
                                ens.cell_mask[2], ens.momentum, ens.seed, update->dt);
  for (const auto &line : lines) key += "|" + line;
  return key;
}

/* ----------------------------------------------------------------------
   Modify::setup() without the setup() of the fixes the engine stands in for. Theirs prepares a step the fix will
   not take (fix langevin's adds its forces to those LAMMPS has), and several assume run_style verlet or respa.
------------------------------------------------------------------------- */

void IntegrateLoupMD::setup_fixes(int vflag)
{
  if (!from_fixes) {
    modify->setup(vflag);
    return;
  }
  // in Modify::setup()'s order: dynamic groups, the computes (degrees of freedom), then the fixes
  const auto &fixes = modify->get_fix_list();
  for (auto *fix : fixes)
    if (strcmp(fix->style, "GROUP") == 0) fix->setup(vflag);
  for (auto *compute : modify->get_compute_list()) compute->setup();
  for (auto *fix : fixes)
    if (std::find(stood_in.begin(), stood_in.end(), fix) == stood_in.end()) fix->setup(vflag);
  if (atom->labelmapflag && atom->lmap->checkflag) atom->lmap->check_labels();
}

/* ----------------------------------------------------------------------
   With an ensemble named on the run_style line no fix may act during the steps: none would take effect.
------------------------------------------------------------------------- */

void IntegrateLoupMD::checks()
{
  if (from_fixes) return;    // read_fixes() has classified every fix
  if (modify->n_initial_integrate || modify->n_post_integrate || modify->n_pre_exchange || modify->n_pre_neighbor ||
      modify->n_post_neighbor || modify->n_pre_force || modify->n_pre_reverse || modify->n_post_force_any ||
      modify->n_final_integrate || modify->n_end_of_step)
    error->all(FLERR, "run_style loupmd {}: the engine integrates this ensemble itself, so no fix may act during "
                      "the steps. Use 'run_style loupmd' without an ensemble to have the input's fixes taken over, "
                      "or the default run style with pair_style loupmd", ens.kind == LOUP_NVE ? "nve" : "langevin");
}

/* ---------------------------------------------------------------------- */

void IntegrateLoupMD::describe()
{
  for (const auto &line : lines) utils::print(screen, "  Ensemble      : {}\n", line);
  utils::print(screen, "  Integrator    : the LoupMD engine's{}{}\n", tiled ? " tiled MD" : "",
               fix_com ? "; centre of mass kept at rest (3N - 3 degrees of freedom)" : "");
  if (tiled) {
    LoupExecution ex{};
    if (loup_get_execution(pair->engine(), &ex) == 0)
      utils::print(screen, "  Capacity      : tiled{}, {} tiles of at most {} atoms{}\n",
                   ex.mode == LOUP_EXEC_WAVEFRONT ? " (wavefront schedule)" : "", ex.tiles, ex.receivers,
                   ex.host_state ? ", tile lists and layer state in host memory"
                   : ex.host_lists ? ", tile lists in host memory" : "");
  }
  if (nfixed) utils::print(screen, "  Held in place : {} atoms\n", nfixed);
}

/* ----------------------------------------------------------------------
   The pair style plans whole or tiled when it sends the system, in the setup's force call: only then is the mode
   known (LAMMPS_TILED_PLAN.md LD6). The engine's tiled MD runs every integrator the run style maps a fix to, the
   barostats too (fix npt, press/berendsen; LT6 (a)): it keeps its tile lists across the cell's changes.
------------------------------------------------------------------------- */

void IntegrateLoupMD::check_tiled()
{
  tiled = pair->tiled();
  if (!tiled) return;
  if (ens.kind != LOUP_NVE && ens.kind != LOUP_LANGEVIN && ens.kind != LOUP_CSVR && ens.kind != LOUP_NHC &&
      ens.kind != LOUP_BERENDSEN_NVT && ens.kind != LOUP_BERENDSEN_NPT && ens.kind != LOUP_BAOAB_NPT &&
      ens.kind != LOUP_MTK_NPT)
    error->all(FLERR, "run_style loupmd: the engine's tiled MD has no integrator of kind {} (it runs nve, langevin, "
                      "temp/csvr, nvt, npt, temp/berendsen and press/berendsen). {}", ens.kind, kVerlet);
}

/* ---------------------------------------------------------------------- */

void IntegrateLoupMD::setup(int flag)
{
  if (comm->me == 0 && screen) {
    fputs("Setting up LoupMD run ...\n", screen);
    if (flag) {
      utils::print(screen, "  Unit style    : {}\n"
                           "  Current step  : {}\n"
                           "  Time step     : {}\n",
                   update->unit_style, update->ntimestep, update->dt);
      timer->print_timeout(screen);
    }
  }

  checks();
  update->setupflag = 1;

  // setup domain, communication and neighboring as Verlet does

  atom->setup();
  modify->setup_pre_exchange();
  if (triclinic) domain->x2lamda(atom->nlocal);
  domain->pbc();
  domain->reset_box();
  comm->setup();
  if (neighbor->style) neighbor->setup_bins();
  comm->exchange();
  if (atom->sortfreq > 0) atom->sort();
  comm->borders();
  if (triclinic) domain->lamda2x(atom->nlocal + atom->nghost);
  domain->image_check();
  domain->box_too_small_check();
  modify->setup_pre_neighbor();
  neighbor->build(1);
  modify->setup_post_neighbor();
  neighbor->ncalls = 0;
  box_moved = false;

  // forces of the current state through the pair style, then hand the state to the engine

  force->setup();
  forces(update->ntimestep);
  check_tiled();
  modify->setup_pre_reverse(eflag, vflag);
  if (force->newton) comm->reverse_comm();

  setup_fixes(vflag);
  output->setup(flag);
  update->setupflag = 0;

  push_state();
  if (flag && comm->me == 0 && screen) describe();
}

/* ----------------------------------------------------------------------
   setup without output; flag = 0: the previous run left everything current
------------------------------------------------------------------------- */

void IntegrateLoupMD::setup_minimal(int flag)
{
  checks();
  update->setupflag = 1;

  if (flag) {
    modify->setup_pre_exchange();
    if (triclinic) domain->x2lamda(atom->nlocal);
    domain->pbc();
    domain->reset_box();
    comm->setup();
    if (neighbor->style) neighbor->setup_bins();
    comm->exchange();
    comm->borders();
    if (triclinic) domain->lamda2x(atom->nlocal + atom->nghost);
    domain->image_check();
    domain->box_too_small_check();
    modify->setup_pre_neighbor();
    neighbor->build(1);
    modify->setup_post_neighbor();
    neighbor->ncalls = 0;
    box_moved = false;
  }

  forces(update->ntimestep);
  check_tiled();
  modify->setup_pre_reverse(eflag, vflag);
  if (force->newton) comm->reverse_comm();

  setup_fixes(vflag);
  update->setupflag = 0;

  push_state();
}

/* ----------------------------------------------------------------------
   Blocks of engine steps up to the next step at which LAMMPS writes output; there the state comes back, LAMMPS
   wraps the atoms and rebuilds its ghosts, and the pair style evaluates energy, forces and virial for the output.
------------------------------------------------------------------------- */

void IntegrateLoupMD::run(int n)
{
  LoupHandle *engine = pair->engine();

  LoupIntegrator it;
  memset(&it, 0, sizeof(it));
  it.size = sizeof(it);
  it.kind = ens.kind;
  it.dt_fs = update->dt * 1000.0;
  if (ens.kind == LOUP_LANGEVIN) it.friction_per_fs = 1.0 / (ens.tau_t * 1000.0);
  else it.tau_t_fs = ens.tau_t * 1000.0;
  // The thermostat's and the barostat's masses are made for one temperature for the whole run (a ramp moves the
  // target, not the masses), so that every block runs the same captured step.
  it.mass_temp_k = ens.t_start > 0.0 ? ens.t_start : ens.t_stop;
  it.pressure_gpa = ens.pressure * kGPaPerBar;
  it.tau_p_fs = ens.tau_p * 1000.0;
  if (ens.modulus > 0.0) it.compressibility_per_gpa = 1.0 / (ens.modulus * kGPaPerBar);
  it.chain_length = ens.tchain;
  it.chain_loops = ens.tloop;
  it.p_chain_length = ens.pchain;
  it.p_chain_loops = ens.ploop;
  it.cell_mode = ens.cell_full ? LOUP_CELL_FULL : LOUP_CELL_HYDROSTATIC;
  for (int d = 0; d < 3; d++) it.cell_mask[d] = ens.cell_mask[d];
  it.fix_com = fix_com;
  // The engine's noise is a function of the seed, the atom and the steps taken on the system it holds: the stream
  // runs on from run to run, through a new state too. A system given again (new masses, another atom count) counts
  // its steps from zero and would repeat the first one's noise, so every system after the first moves the seed.
  it.seed = ens.seed + (unsigned long long) (pair->system_serial() - 1) * 0x9E3779B97F4A7C15ULL;
  // a temperature ramp runs over the whole run, as the fixes': the target of step s is t_start + (s - beginstep) rate
  const double span = (double) (update->endstep - update->beginstep);
  const double rate = span > 0.0 ? (ens.t_stop - ens.t_start) / span : 0.0;
  it.temp_rate_k_per_step = rate;

  timer->init_timeout();
  bigint remaining = n;
  while (remaining > 0) {
    if (timer->check_timeout((int) (n - remaining))) {
      update->nsteps = (int) (n - remaining);
      break;
    }

    bigint nblock = remaining;
    if (output->next > update->ntimestep && output->next - update->ntimestep < nblock)
      nblock = output->next - update->ntimestep;

    timer->stamp();
    it.temp_k = ens.t_start + rate * (double) (update->ntimestep - update->beginstep);
    LoupMDStats stats;
    if (tiled) {
      // the tiled MD (thermo_every 0: LAMMPS writes its own thermo at the output steps)
      if (loup_tiled_run(engine, &it, (int) nblock, &stats, nullptr, 0, nullptr, nullptr) != 0)
        error->one(FLERR, "run_style loupmd: the engine's tiled run failed: {}", loup_last_error(engine));
      pair->note_tiled_md_steps(nblock);
    } else if (loup_run(engine, &it, (int) nblock, &stats) != 0) {
      error->one(FLERR, "run_style loupmd: the engine's run failed: {}", loup_last_error(engine));
    }
    timer->stamp(Timer::PAIR);

    update->ntimestep += nblock;
    remaining -= nblock;

    if (update->ntimestep == output->next || remaining == 0) {
      pull_state();
      reneighbor();
      timer->stamp(Timer::COMM);
      forces(update->ntimestep);
      timer->stamp(Timer::PAIR);
      if (update->ntimestep == output->next) {
        output->write(update->ntimestep);
        timer->stamp(Timer::OUTPUT);
      }
    }
  }

  // What the engine holds now, as the next run's setup would send it: if nothing has changed by then, the engine
  // keeps its state, with the thermostat's and the barostat's variables.
  gather(snap_x, snap_v, snap_cell);
  snap_key = ensemble_key();
  snap_serial = pair->system_serial();
  snap_fixed = fixed;
  engine_current = true;
}

/* ---------------------------------------------------------------------- */

void IntegrateLoupMD::force_clear()
{
  if (external_force_clear) return;

  size_t n = atom->nlocal;
  if (force->newton) n += atom->nghost;
  if (n) memset(&atom->f[0][0], 0, 3 * sizeof(double) * n);
}

/* ---------------------------------------------------------------------- */

void IntegrateLoupMD::forces(bigint step)
{
  ev_set(step);
  force_clear();
  if (pair_compute_flag) force->pair->compute(eflag, vflag);
  // fix setforce 0 0 0, as after every force call under run_style verlet: the forces LAMMPS writes for held atoms
  // are zero, and the fix's own totals (f_ID[1..3]) are those of this step
  for (auto *fix : hold_fixes) fix->post_force(vflag);
}

/* ---------------------------------------------------------------------- */

void IntegrateLoupMD::reneighbor()
{
  if (triclinic) domain->x2lamda(atom->nlocal);
  domain->pbc();
  if (box_moved) {
    domain->reset_box();
    comm->setup();
    if (neighbor->style) neighbor->setup_bins();
    box_moved = false;
  }
  comm->exchange();
  comm->borders();
  if (triclinic) domain->lamda2x(atom->nlocal + atom->nghost);
  neighbor->build(1);
}

/* ----------------------------------------------------------------------
   The engine keeps atoms by ID (its atom k is the atom with ID k + 1) and positions unwrapped.
------------------------------------------------------------------------- */

void IntegrateLoupMD::gather(std::vector<double> &xs, std::vector<double> &vs, double *cell)
{
  const int n = atom->nlocal;
  double **x = atom->x;
  double **v = atom->v;
  const tagint *tag = atom->tag;
  const imageint *image = atom->image;

  xs.resize(3 * (size_t) n);
  vs.resize(3 * (size_t) n);
  for (int i = 0; i < n; i++) {
    double u[3];
    domain->unmap(x[i], image[i], u);
    const size_t k = 3 * (size_t) (tag[i] - 1);
    for (int c = 0; c < 3; c++) {
      xs[k + c] = u[c];
      vs[k + c] = v[i][c] / kVelLmpPerAse;
    }
  }
  pair->cell(cell);
}

/* ---------------------------------------------------------------------- */

void IntegrateLoupMD::push_state()
{
  LoupHandle *engine = pair->engine();
  const int n = atom->nlocal;
  double **v = atom->v;
  const tagint *tag = atom->tag;
  const int *mask = atom->mask;

  // Atoms held in place: outside the integrating fix's group, or in a 'setforce 0 0 0' group. The second kind only
  // stands still in LAMMPS when it is at rest, so anything else is refused.
  fixed.assign(n, 0);
  nfixed = 0;
  if (from_fixes) {
    for (int i = 0; i < n; i++) {
      bool held = !(mask[i] & move_groupbit);
      if (!held) {
        for (int bit : hold_groupbits) held = held || (mask[i] & bit);
        if (held && (v[i][0] != 0.0 || v[i][1] != 0.0 || v[i][2] != 0.0))
          error->one(FLERR, "run_style loupmd: atom {} is in a 'fix setforce 0 0 0' group and has a velocity. The "
                            "engine holds such atoms in place, while LAMMPS lets them drift: set their velocity to "
                            "zero (velocity GROUP set 0.0 0.0 0.0). {}", tag[i], kVerlet);
      }
      if (held) {
        fixed[tag[i] - 1] = 1;
        nfixed++;
      }
    }
    if (nfixed == n) error->one(FLERR, "run_style loupmd: every atom is held in place");
    if (nfixed && varcell)
      error->one(FLERR, "run_style loupmd: a barostat with {} atoms held in place (scaling the cell would move "
                        "them). {}", nfixed, kVerlet);
  }

  // The centre of mass. LAMMPS's thermostats count 3N - 3 degrees of freedom; the engine does when it keeps the
  // centre of mass at rest, which it can when the state has no total momentum and no atom is held.
  fix_com = 0;
  if (from_fixes && nfixed == 0) {
    if (ens.momentum) {
      fix_com = 1;
    } else if (ens.kind != LOUP_NVE && ens.kind != LOUP_LANGEVIN) {
      double vcm[3];
      group->vcm(0, group->mass(0), vcm);
      if (fabs(vcm[0]) < 1.0e-9 && fabs(vcm[1]) < 1.0e-9 && fabs(vcm[2]) < 1.0e-9) fix_com = 1;
    }
  }

  // The engine keeps its state, with the thermostat's and the barostat's variables and its place in the noise
  // stream, when nothing has changed since a run ended there: the same system and ensemble, the same velocities
  // and box, and positions that differ by rounding only (LAMMPS wraps through fractional coordinates, which moves
  // the last bits; the positions themselves reached the engine with the force call of this setup). Anything else
  // is a new state, and those variables start from zero as under a newly defined fix.
  double cell[9];
  gather(xbuf, vbuf, cell);
  bool unchanged = engine_current && pair->system_serial() == snap_serial && ensemble_key() == snap_key &&
      vbuf == snap_v && xbuf.size() == snap_x.size() && memcmp(cell, snap_cell, sizeof(snap_cell)) == 0;
  for (size_t k = 0; unchanged && k < xbuf.size(); k++) unchanged = fabs(xbuf[k] - snap_x[k]) <= 1.0e-9;

  if (tiled) {
    // The engine's tiled MD (LD6): the held atoms are part of its state. A new state continues the noise stream of
    // the system the engine holds (its counter), and the thermostat's variables start from zero.
    unchanged = unchanged && tiled_md_serial == pair->system_serial() && fixed == snap_fixed;
    if (!unchanged) {
      unsigned long long noise = 0;
      if (tiled_md_serial == pair->system_serial() &&
          loup_tiled_get_state(engine, nullptr, nullptr, nullptr, nullptr, &noise, nullptr, nullptr) != 0)
        error->one(FLERR, "run_style loupmd: could not read the engine's tiled state: {}", loup_last_error(engine));
      fixed_flags.assign(fixed.begin(), fixed.end());
      const std::vector<int> &z = pair->sent_numbers();
      const std::vector<double> &m = pair->sent_masses();
      if ((int) z.size() != n)
        error->one(FLERR, "run_style loupmd: the pair style holds {} atoms, LAMMPS {}", z.size(), n);
      if (loup_tiled_set_state(engine, n, z.data(), m.data(), xbuf.data(), vbuf.data(), cell,
                               nfixed ? fixed_flags.data() : nullptr, pair->cap(), pair->sent_skin(), noise, nullptr,
                               -1) != 0)
        error->one(FLERR, "run_style loupmd: the engine refused the tiled state: {}", loup_last_error(engine));
      tiled_md_serial = pair->system_serial();
    }
    engine_current = false;
    return;
  }

  if (!unchanged && loup_set_state(engine, xbuf.data(), vbuf.data(), cell) != 0)
    error->one(FLERR, "run_style loupmd: the engine refused the state: {}", loup_last_error(engine));
  if (loup_set_fixed_atoms(engine, nfixed ? fixed.data() : nullptr) != 0)
    error->one(FLERR, "run_style loupmd: the engine refused the held atoms: {}", loup_last_error(engine));
  engine_current = false;
}

/* ----------------------------------------------------------------------
   The engine scales the cell and the positions about the origin; LAMMPS's box follows: its lower corner keeps its
   fractional coordinates. In tiled mode the cell is the tiled MD's (loup_tiled_get_cell).
------------------------------------------------------------------------- */

void IntegrateLoupMD::pull_box()
{
  double c[9];
  LoupHandle *engine = pair->engine();
  if ((tiled ? loup_tiled_get_cell(engine, c) : loup_get_cell(engine, c)) != 0)
    error->one(FLERR, "run_style loupmd: could not read the engine's cell: {}", loup_last_error(engine));
  const double scale = fabs(c[0]) + fabs(c[4]) + fabs(c[8]);
  if (fabs(c[1]) > 1.0e-9 * scale || fabs(c[2]) > 1.0e-9 * scale || fabs(c[5]) > 1.0e-9 * scale)
    error->one(FLERR, "run_style loupmd: the engine's cell is no longer of LAMMPS's triangular form");

  // fractional coordinates of the lower corner in the old box (rows a = (xprd, 0, 0), b = (xy, yprd, 0),
  // c = (xz, yz, zprd)), then the same in the new one
  const double sz = domain->boxlo[2] / domain->zprd;
  const double sy = (domain->boxlo[1] - domain->yz * sz) / domain->yprd;
  const double sx = (domain->boxlo[0] - domain->xy * sy - domain->xz * sz) / domain->xprd;
  domain->boxlo[0] = c[0] * sx + c[3] * sy + c[6] * sz;
  domain->boxlo[1] = c[4] * sy + c[7] * sz;
  domain->boxlo[2] = c[8] * sz;
  domain->boxhi[0] = domain->boxlo[0] + c[0];
  domain->boxhi[1] = domain->boxlo[1] + c[4];
  domain->boxhi[2] = domain->boxlo[2] + c[8];
  if (triclinic) {
    domain->xy = c[3];
    domain->xz = c[6];
    domain->yz = c[7];
  }
  domain->set_global_box();
  domain->set_local_box();
  box_moved = true;
}

/* ---------------------------------------------------------------------- */

void IntegrateLoupMD::pull_state()
{
  LoupHandle *engine = pair->engine();
  const int n = atom->nlocal;
  double **x = atom->x;
  double **v = atom->v;
  const tagint *tag = atom->tag;
  imageint *image = atom->image;

  if (varcell) pull_box();

  xbuf.resize(3 * (size_t) n);
  vbuf.resize(3 * (size_t) n);
  if (tiled) {
    if (loup_tiled_get_state(engine, xbuf.data(), vbuf.data(), nullptr, nullptr, nullptr, nullptr, nullptr) != 0)
      error->one(FLERR, "run_style loupmd: could not read the engine's tiled state: {}", loup_last_error(engine));
  } else if (loup_get_state(engine, xbuf.data(), vbuf.data(), nullptr, nullptr) != 0) {
    error->one(FLERR, "run_style loupmd: could not read the engine's state: {}", loup_last_error(engine));
  }

  // unwrapped positions with zero image flags, wrapped into the box by LAMMPS (which sets the flags). An atom held
  // in place keeps the position, the image flags and the velocity LAMMPS has for it.
  const imageint zero_image = ((imageint) IMGMAX << IMG2BITS) | ((imageint) IMGMAX << IMGBITS) | IMGMAX;
  for (int i = 0; i < n; i++) {
    const size_t k = 3 * (size_t) (tag[i] - 1);
    if (nfixed && fixed[tag[i] - 1]) continue;
    for (int c = 0; c < 3; c++) {
      x[i][c] = xbuf[k + c];
      v[i][c] = vbuf[k + c] * kVelLmpPerAse;
    }
    image[i] = zero_image;
    domain->remap(x[i], image[i]);
  }
}
