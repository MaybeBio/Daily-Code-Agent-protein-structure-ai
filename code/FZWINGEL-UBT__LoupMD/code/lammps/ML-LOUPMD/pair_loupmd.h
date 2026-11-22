/* -*- c++ -*- ----------------------------------------------------------
   LAMMPS - Large-scale Atomic/Molecular Massively Parallel Simulator
   https://www.lammps.org/, Sandia National Laboratories
   LAMMPS development team: developers@lammps.org

   This file is part of the LoupMD interface to LAMMPS (https://github.com/FZWINGEL-UBT/LoupMD, lammps/).
   It is distributed under the GNU General Public License, as LAMMPS is.

   See the README file in the top-level LAMMPS directory.
------------------------------------------------------------------------- */

#ifdef PAIR_CLASS
// clang-format off
PairStyle(loupmd,PairLoupMD);
// clang-format on
#else

#ifndef LMP_PAIR_LOUPMD_H
#define LMP_PAIR_LOUPMD_H

#include "pair.h"

#include <string>
#include <vector>

struct LoupHandle;

namespace LAMMPS_NS {

// MACE models through the LoupMD engine (libloupmd.so, CUDA). The engine evaluates the whole periodic system on one
// GPU with its own neighbour list; LAMMPS's neighbour lists and ghost atoms are not used. One MPI process.
// A cell that does not fit the card whole runs in tiles (the engine's capacity mode, LAMMPS_TILED_PLAN.md): the
// engine plans whole or tiled, and the tile size, each time the system is sent.
//
//   pair_style loupmd [device N] [skin S] [ghost yes|no] [ahead yes|no]
//                     [capacity auto|whole|tiled|wavefront] [receivers N] [memory F]
//   pair_coeff * * model.loup El1 El2 ...      (one element per atom type, in type order)
class PairLoupMD : public Pair {
 public:
  PairLoupMD(class LAMMPS *);
  ~PairLoupMD() override;
  void compute(int, int) override;
  void settings(int, char **) override;
  void coeff(int, char **) override;
  void init_style() override;
  double init_one(int, int) override;
  void finish() override;

  // for run_style loupmd, where the engine integrates: the engine holding the current system, and the cell
  LoupHandle *engine();
  void cell(double *c) const { box_to_cell(c); }
  // counts the systems the engine was given (loup_set_system or, in tiled mode, the plan; either drops the
  // engine's state): unchanged since a run ended means that the engine still holds that run's state
  bigint system_serial() const { return serial; }
  // the tiled mode (after engine() or a compute): the engine holds no whole system, the force call is
  // loup_evaluate_tiled with cap() receivers per tile, and MD runs through loup_tiled_*
  bool tiled() const { return tiled_mode; }
  int cap() const { return tile_cap; }
  // the system as sent: atomic numbers and masses by atom ID - 1, and the skin
  const std::vector<int> &sent_numbers() const { return z_sent; }
  const std::vector<double> &sent_masses() const { return m_sent; }
  double sent_skin() const { return skin_sent; }
  // the tiled force call on positions by atom ID - 1 (unwrapped) in the current box: energy, forces by atom ID - 1,
  // and the stress when `stress` is not null; counts the call for the run's line
  void evaluate_tiled(const double *x_by_tag, double *energy, double *f_by_tag, double *stress);
  // steps run_style loupmd ran in the engine's tiled MD (for the run's line)
  void note_tiled_md_steps(bigint n) { tiled_md_steps += n; }

 protected:
  LoupHandle *handle;           // the engine (created in init_style)
  std::string bundle;           // pair_coeff's .loup file
  std::string bundle_loaded;    // the file `handle` was created from
  int device;                   // CUDA device; -1: default_device()
  int device_loaded;
  double skin_user;             // the engine's list skin in A; < 0: LAMMPS's neighbor skin
  double rmax;                  // the model's cutoff, A
  bool ghost;                   // report the model's cutoff to LAMMPS (ghost atoms, forward communication)
  bool ahead;                   // the engine queues each next force pass ahead (loup_set_evaluate_ahead)
  std::vector<int> type2z;      // [ntypes + 1] atomic number of each atom type
  bool system_dirty;            // the engine has to be given the system again (init_style ran)
  std::vector<int> z_sent;      // atomic number by atom ID - 1 of the system the engine holds
  std::vector<double> m_sent;   // and its masses
  double skin_sent;
  bigint serial;                // systems sent so far (loup_set_system, or a plan in tiled mode)
  std::vector<double> xbuf, fbuf;    // host positions / forces by atom ID - 1 (the non-Kokkos compute)

  // the capacity mode
  int exec_mode;                // LOUP_EXEC_AUTO / WHOLE / TILED / WAVEFRONT (capacity keyword)
  int receivers_user;           // receivers keyword; 0: the plan's cap
  double memory_fraction;       // memory keyword: the share of the free device memory the plan may use
  int exec_sent[2];             // exec_mode and receivers_user of the system the engine holds
  double memory_sent;
  bool tiled_mode;              // the system the engine holds runs tiled
  int tile_cap;                 // its receivers per tile (passed to every tiled call, never 0)
  double cell_planned[9];       // the cell of the last plan
  bool plan_pending;           // the plan's line waits for the first tiled call (tiles, wavefront)
  double plan_whole_gib, plan_free_gib;
  bigint tiled_calls;           // tiled calls in this run, the run style's tiled MD steps, and the list builds the
  bigint tiled_md_steps;        // engine had when the run began
  bigint builds_at_start;

  virtual void allocate();
  virtual int default_device() { return 0; }
  virtual void sync_host_positions() {}    // loupmd/kk: x, image and tag to the host before they are read there
  // sends the system to the engine when it is new, an atom count / type / mass or the skin changed, or the
  // capacity settings did; in tiled mode or under capacity auto it plans first. have_x: xbuf already holds the
  // unwrapped positions by atom ID - 1 (the plan reads them)
  void ensure_system(bool have_x = false);
  void send_system(const std::vector<int> &z, const std::vector<double> &m, double skin, bool have_x);
  void gather_unwrapped();      // xbuf from atom->x
  void box_to_cell(double *) const;
  void refuse_per_atom() const;
};

}    // namespace LAMMPS_NS

#endif
#endif
