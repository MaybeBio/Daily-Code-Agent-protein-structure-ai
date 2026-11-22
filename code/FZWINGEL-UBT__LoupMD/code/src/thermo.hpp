#pragma once
// The thermo buffer (include/loupmd.h: loup_read_thermo): one row of energies every `every` steps, written on the
// device inside the captured MD step, so a run of any length needs no host round trip for its thermodynamic output.
#include <cuda_runtime.h>

#include "cell.hpp"
#include "loupmd.h"

namespace loup {

constexpr int kThermoCapacity = 4096;  // rows the device buffer holds between two loup_read_thermo calls

// Device-side control block. The host writes it at the start of every run call (it knows the step count and the
// number of unread rows exactly); the two kernels below advance it inside the step.
struct ThermoCtrl {
    unsigned long long step;  // MD steps completed since the last loup_set_state
    double ke;                // kinetic-energy accumulator of a row step, zero otherwise
    int every;                // a row every so many steps; 0: none
    int count;                // rows in the buffer
    int capacity;
    int pad;
};

// Sums the kinetic energy into ctrl->ke, on steps that write a row only (every thread returns at once otherwise).
// Runs after the integrator's last velocity update of the step.
__global__ void thermo_kinetic_kernel(int N, const double* __restrict__ masses, const double* __restrict__ vel64,
                                      ThermoCtrl* __restrict__ ctrl);

// Closes the step: counts it and, on a row step, appends the row. One thread. `dof`: the kinetic degrees of
// freedom the temperature counts, 3 (N - n_fixed), less 3 with fix_com. `transferred`: the energy a thermostat
// has put into the system (CSVR), which the conserved quantity subtracts; NULL for none. `cell` and `virial` (the
// six components of dE / d strain, as the force pass with stress leaves them): the variable-cell step's, for the
// row's volume and pressure; NULL in a fixed-cell step, whose rows carry 0 for both.
__global__ void thermo_row_kernel(int dof, double e0_total, double kb, const double* __restrict__ energy,
                                  ThermoCtrl* __restrict__ ctrl, LoupThermoRow* __restrict__ rows,
                                  const double* __restrict__ transferred, const CellDev* __restrict__ cell,
                                  const double* __restrict__ virial);

}  // namespace loup
