// clang-format off
/* ----------------------------------------------------------------------
   LAMMPS - Large-scale Atomic/Molecular Massively Parallel Simulator
   https://www.lammps.org/, Sandia National Laboratories
   LAMMPS development team: developers@lammps.org

   This file is part of the LoupMD interface to LAMMPS (https://github.com/FZWINGEL-UBT/LoupMD, lammps/).
   It is distributed under the GNU General Public License, as LAMMPS is.

   See the README file in the top-level LAMMPS directory.
------------------------------------------------------------------------- */

#include "pair_loupmd_kokkos.h"

#include "atom_kokkos.h"
#include "atom_masks.h"
#include "domain.h"
#include "error.h"
#include "kokkos.h"
#include "neigh_request.h"
#include "neighbor.h"
#include "update.h"

#include "loupmd.h"

#include <type_traits>

using namespace LAMMPS_NS;

/* ---------------------------------------------------------------------- */

template<class DeviceType>
PairLoupMDKokkos<DeviceType>::PairLoupMDKokkos(LAMMPS *lmp) : PairLoupMD(lmp)
{
  respa_enable = 0;

  kokkosable = 1;
  atomKK = (AtomKokkos *) atom;
  execution_space = ExecutionSpaceFromDevice<DeviceType>::space;
  datamask_read = X_MASK | F_MASK | TYPE_MASK | TAG_MASK | IMAGE_MASK;
  datamask_modify = F_MASK;
}

/* ----------------------------------------------------------------------
   the engine runs on the GPU Kokkos uses, unless `device N` says otherwise
------------------------------------------------------------------------- */

template<class DeviceType>
int PairLoupMDKokkos<DeviceType>::default_device()
{
#ifdef KOKKOS_ENABLE_CUDA
  const int id = Kokkos::device_id();
  return id >= 0 ? id : 0;
#else
  return 0;
#endif
}

/* ---------------------------------------------------------------------- */

template<class DeviceType>
void PairLoupMDKokkos<DeviceType>::sync_host_positions()
{
  atomKK->sync(Host, X_MASK | IMAGE_MASK | TAG_MASK);
}

/* ----------------------------------------------------------------------
   The engine needs no neighbour list. LAMMPS-Kokkos, though, keeps its own per-step work on the device (the
   displacement check that triggers reneighbouring, the bond topology) only when a list is requested there; without
   one it falls back to the host and, with bonds and a host fix such as rigid/small, aborts on its bond list. An
   occasional list is requested and never built.
------------------------------------------------------------------------- */

template<class DeviceType>
void PairLoupMDKokkos<DeviceType>::init_style()
{
  PairLoupMD::init_style();

  auto request = neighbor->add_request(this, NeighConst::REQ_OCCASIONAL);
  request->set_kokkos_host(std::is_same_v<DeviceType,LMPHostType> && !std::is_same_v<DeviceType,LMPDeviceType>);
  request->set_kokkos_device(std::is_same_v<DeviceType,LMPDeviceType>);
}

/* ---------------------------------------------------------------------- */

template<class DeviceType>
void PairLoupMDKokkos<DeviceType>::compute(int eflag_in, int vflag_in)
{
#ifdef KOKKOS_ENABLE_CUDA
  if constexpr (std::is_same_v<DeviceType, Kokkos::Cuda>) {
    ev_init(eflag_in, vflag_in, 0);
    refuse_per_atom();

    // The system (atom count, types by ID) is checked on the host when a run starts and on reneighbouring steps. A
    // send under capacity auto, tiled or wavefront plans on the host positions (sync_host_positions).
    if (system_dirty || neighbor->ago == 0 || (int) z_sent.size() != atom->nlocal) {
      atomKK->sync(Host, TAG_MASK | TYPE_MASK | RMASS_MASK);
      ensure_system();
    }

    // Tiled mode: the host compute (LD5). The forces go back to the device at once: the integrator marks them as
    // modified in the pair style's execution space after compute(), which Kokkos refuses while the host copy is the
    // modified one.
    if (tiled_mode) {
      atomKK->sync(Host, datamask_read | RMASS_MASK);
      PairLoupMD::compute(eflag_in, vflag_in);
      atomKK->modified(Host, F_MASK);
      atomKK->sync(execution_space, F_MASK);
      return;
    }

    atomKK->sync(execution_space, X_MASK | F_MASK | TAG_MASK | IMAGE_MASK);
    auto x = atomKK->k_x.view<DeviceType>();
    auto f = atomKK->k_f.view<DeviceType>();
    auto tag = atomKK->k_tag.view<DeviceType>();
    auto image = atomKK->k_image.view<DeviceType>();

    const int n = atom->nlocal;
    if ((int) d_xu.extent(0) < n) {
      d_xu = decltype(d_xu)(Kokkos::view_alloc(Kokkos::WithoutInitializing, "loupmd:xu"), atom->nmax);
      d_id = decltype(d_id)(Kokkos::view_alloc(Kokkos::WithoutInitializing, "loupmd:id"), atom->nmax);
    }

    // Unwrapped positions (LAMMPS re-wraps atoms into the box when it reneighbours; the engine's skin check needs
    // continuous positions) and the engine's atom of each row: atom ID - 1.
    auto xu = d_xu;
    auto id = d_id;
    const double xprd = domain->xprd, yprd = domain->yprd, zprd = domain->zprd;
    const double xy = domain->xy, xz = domain->xz, yz = domain->yz;
    Kokkos::parallel_for("PairLoupMDKokkos::unwrap", Kokkos::RangePolicy<DeviceType>(0, n),
      KOKKOS_LAMBDA(const int i) {
        const imageint im = image(i);
        const double xbox = (double) ((int) (im & IMGMASK) - IMGMAX);
        const double ybox = (double) ((int) (im >> IMGBITS & IMGMASK) - IMGMAX);
        const double zbox = (double) ((int) (im >> IMG2BITS) - IMGMAX);
        xu(i, 0) = (double) x(i, 0) + xprd * xbox + xy * ybox + xz * zbox;
        xu(i, 1) = (double) x(i, 1) + yprd * ybox + yz * zbox;
        xu(i, 2) = (double) x(i, 2) + zprd * zbox;
        id(i) = (int) (tag(i) - 1);
      });

    LoupDeviceIO io{};
    io.n_rows = n;
    io.positions = xu.data();
    io.pos_row_stride = 3;
    io.pos_comp_stride = 1;
    io.ids = id.data();

    // Forces: straight into LAMMPS's f when it holds doubles (any layout), else through a double scratch.
    typedef typename decltype(f)::non_const_value_type f_value;
    const bool f_direct = std::is_same_v<f_value, double>;
    if (f_direct) {
      io.forces = reinterpret_cast<double *>(f.data());
      io.f_row_stride = (long long) f.stride(0);
      io.f_comp_stride = (long long) f.stride(1);
    } else {
      if ((int) d_fs.extent(0) < n)
        d_fs = decltype(d_fs)(Kokkos::view_alloc(Kokkos::WithoutInitializing, "loupmd:fs"), atom->nmax);
      auto fs = d_fs;
      Kokkos::parallel_for("PairLoupMDKokkos::zero", Kokkos::RangePolicy<DeviceType>(0, n),
        KOKKOS_LAMBDA(const int i) { fs(i, 0) = 0.0; fs(i, 1) = 0.0; fs(i, 2) = 0.0; });
      io.forces = fs.data();
      io.f_row_stride = 3;
      io.f_comp_stride = 1;
    }
    io.flags = (eflag_global ? LOUP_IO_ENERGY : 0) | (vflag_global ? LOUP_IO_VIRIAL : 0);

    double cell[9], energy = 0.0, vir[6] = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
    box_to_cell(cell);
    // The engine queues its work behind what Kokkos has queued, and makes Kokkos's stream wait for the forces.
    const cudaStream_t stream = DeviceType().cuda_stream();
    if (loup_compute_device(handle, &io, cell, (void *) stream, &energy, vir) != 0)
      error->one(FLERR, "Pair style loupmd/kk: the force evaluation failed: {}", loup_last_error(handle));

    if (!f_direct) {
      auto fs = d_fs;
      Kokkos::parallel_for("PairLoupMDKokkos::add", Kokkos::RangePolicy<DeviceType>(0, n),
        KOKKOS_LAMBDA(const int i) {
          f(i, 0) += (f_value) fs(i, 0);
          f(i, 1) += (f_value) fs(i, 1);
          f(i, 2) += (f_value) fs(i, 2);
        });
    }
    atomKK->modified(execution_space, F_MASK);

    if (eflag_global) eng_vdwl += energy;
    if (vflag_global)
      for (int k = 0; k < 6; k++) virial[k] += vir[k];
    return;
  }
#endif

  // a host execution space: pair_style loupmd's compute on LAMMPS's host arrays
  atomKK->sync(Host, datamask_read | RMASS_MASK);
  PairLoupMD::compute(eflag_in, vflag_in);
  atomKK->modified(Host, F_MASK);
}

namespace LAMMPS_NS {
template class PairLoupMDKokkos<LMPDeviceType>;
#ifdef LMP_KOKKOS_GPU
template class PairLoupMDKokkos<LMPHostType>;
#endif
}
