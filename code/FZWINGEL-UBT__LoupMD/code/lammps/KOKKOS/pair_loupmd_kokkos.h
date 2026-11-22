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
PairStyle(loupmd/kk,PairLoupMDKokkos<LMPDeviceType>);
PairStyle(loupmd/kk/device,PairLoupMDKokkos<LMPDeviceType>);
PairStyle(loupmd/kk/host,PairLoupMDKokkos<LMPHostType>);
// clang-format on
#else

// clang-format off
#ifndef LMP_PAIR_LOUPMD_KOKKOS_H
#define LMP_PAIR_LOUPMD_KOKKOS_H

#include "pair_loupmd.h"
#include "kokkos_type.h"

namespace LAMMPS_NS {

// pair_style loupmd with the atoms kept on the GPU: positions are read from, and forces added to, LAMMPS's Kokkos
// device views by the engine (loup_compute_device), behind the Kokkos execution space's stream. A step waits on the
// host only for the engine's neighbour-list decision, and for the energy / virial on the steps that need them.
// With a host execution space (loupmd/kk/host, or a Kokkos build without CUDA), and in tiled mode (a cell that does
// not fit the card whole, LAMMPS_TILED_PLAN.md LD5), it runs pair_style loupmd's compute on the host arrays: a tiled
// step takes hundreds of milliseconds, the arrays' transfers a few.
template<class DeviceType>
class PairLoupMDKokkos : public PairLoupMD {
 public:
  typedef DeviceType device_type;
  typedef ArrayTypes<DeviceType> AT;

  PairLoupMDKokkos(class LAMMPS *);
  void compute(int, int) override;
  void init_style() override;

 protected:
  int default_device() override;
  void sync_host_positions() override;

  Kokkos::View<double*[3], Kokkos::LayoutRight, DeviceType> d_xu;    // unwrapped positions of the local rows
  Kokkos::View<int*, DeviceType> d_id;                               // atom ID - 1 of each local row
  Kokkos::View<double*[3], Kokkos::LayoutRight, DeviceType> d_fs;    // forces, when LAMMPS's f is not double
};

}    // namespace LAMMPS_NS

#endif
#endif
