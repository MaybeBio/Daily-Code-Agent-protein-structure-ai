/* -*- c++ -*- ----------------------------------------------------------
   LAMMPS - Large-scale Atomic/Molecular Massively Parallel Simulator
   https://www.lammps.org/, Sandia National Laboratories
   LAMMPS development team: developers@lammps.org

   This file is part of the LoupMD interface to LAMMPS (https://github.com/FZWINGEL-UBT/LoupMD, lammps/).
   It is distributed under the GNU General Public License, as LAMMPS is.

   See the README file in the top-level LAMMPS directory.
------------------------------------------------------------------------- */

#ifdef INTEGRATE_CLASS
// clang-format off
IntegrateStyle(loupmd,IntegrateLoupMD);
// clang-format on
#else

#ifndef LMP_INTEGRATE_LOUPMD_H
#define LMP_INTEGRATE_LOUPMD_H

#include "integrate.h"

#include <string>
#include <vector>

namespace LAMMPS_NS {

// The LoupMD engine integrates: between the steps at which LAMMPS writes output (thermo, dump, restart) the engine
// runs its own MD loop on the GPU, at the engine's own step time, and LAMMPS gets positions, velocities and the box
// back at those steps only. Requires pair_style loupmd. A cell the pair style runs in tiles (capacity) runs in the
// engine's tiled MD (loup_tiled_*; LAMMPS_TILED_PLAN.md LD6): NVE, Langevin, CSVR, Nose-Hoover chain and Berendsen
// NVT on a fixed cell, with held atoms and the centre of mass at rest; a barostat is refused there.
//
//   run_style loupmd                            the ensemble is taken from the input's fixes (README.md has the table:
//                                               fix nve, nvt, npt iso, langevin, temp/csvr, temp/berendsen,
//                                               press/berendsen, setforce 0 0 0, momentum). The engine's integrator
//                                               of that ensemble runs instead of the fixes; a fix it has no
//                                               counterpart for is refused by name.
//   run_style loupmd nve                        no fix that acts during the steps may be defined
//   run_style loupmd langevin T damp seed       (T in K, damp in ps as fix langevin's)
class IntegrateLoupMD : public Integrate {
 public:
  IntegrateLoupMD(class LAMMPS *, int, char **);

  void init() override;
  void setup(int) override;
  void setup_minimal(int) override;
  void run(int) override;
  void force_clear() override;

 protected:
  // The ensemble the engine integrates, in LAMMPS's metal units.
  struct Ensemble {
    int kind = 0;                       // LOUP_NVE ... of loupmd.h
    double t_start = 0.0, t_stop = 0.0; // K; a ramp over the run as the fixes'
    double tau_t = 0.0;                 // ps: Tdamp, or fix langevin's damp
    double pressure = 0.0;              // bar
    double tau_p = 0.0;                 // ps: Pdamp
    double modulus = 0.0;               // bar: fix press/berendsen's bulk modulus
    int tchain = 0, tloop = 0, pchain = 0, ploop = 0;
    int cell_full = 0;                  // 0: the box keeps its shape (iso); 1: each box vector on its own
    int cell_mask[3] = {1, 1, 1};
    int momentum = 0;                   // the input asks for a centre of mass at rest (fix momentum, zero yes)
    unsigned long long seed = 0;
  };

  int from_fixes;               // 1: run_style loupmd without an ensemble: read the fixes
  Ensemble ens;
  std::vector<std::string> lines;       // what was taken over from which fix, for the log
  int move_groupbit;            // atoms outside the integrating fix's group are held in place
  std::vector<int> hold_groupbits;      // groups of fix setforce 0 0 0
  std::vector<class Fix *> hold_fixes;  // those fixes: they zero the forces LAMMPS sees at its output steps
  std::vector<class Fix *> stood_in;    // the fixes the engine integrates for: their setup() is not called
  std::vector<unsigned long long> csvr_seeds;   // per fix temp/csvr seen, in order (drawn once from the fix)
  std::vector<std::string> csvr_ids;

  class PairLoupMD *pair;
  int triclinic;
  bool varcell;                 // the ensemble moves the box
  bool box_moved;               // since LAMMPS last set up its communication
  int fix_com;                  // what the engine is told (decided with the state's momentum)
  bigint nfixed;
  std::vector<double> xbuf, vbuf;
  std::vector<int> fixed;       // by ID - 1: nonzero = held in place
  std::vector<double> snap_x, snap_v;   // the state the engine holds, as push_state would send it
  double snap_cell[9];
  std::string snap_key;         // ensemble_key() of the run that left it
  bigint snap_serial;           // the pair style's system_serial() then
  std::vector<int> snap_fixed;  // and the held atoms (tiled mode: they are part of the engine's state)
  bool engine_current;          // snap_* is what the engine holds (a run ended there)
  bool tiled;                   // this run is in the engine's tiled MD (pair->tiled() after the setup's forces)
  bigint tiled_md_serial;       // the system_serial() of the engine's tiled MD state (-1: none sent)
  std::vector<unsigned char> fixed_flags;

  void read_fixes();            // the ensemble from the input's fixes (errors name the fix and say why)
  std::string ensemble_key() const;
  void checks();
  void check_tiled();           // after the setup's forces: the mode is known; refuses what tiled MD cannot run
  void describe();
  void setup_fixes(int);        // Modify::setup() without the setup() of the fixes in stood_in
  void reneighbor();            // LAMMPS's own bookkeeping after the atoms moved: wrap, ghosts, lists
  void forces(bigint);          // energy / virial flags of this step, the pair style's compute, the held atoms' zeros
  void gather(std::vector<double> &, std::vector<double> &, double *);   // LAMMPS's state as the engine takes it
  void push_state();            // LAMMPS positions and velocities to the engine
  void pull_state();            // and back, with the box when the ensemble moves it
  void pull_box();
};

}    // namespace LAMMPS_NS

#endif
#endif
