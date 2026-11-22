#include "thermo.hpp"

namespace loup {

__global__ void thermo_kinetic_kernel(int N, const double* __restrict__ masses, const double* __restrict__ vel64,
                                      ThermoCtrl* __restrict__ ctrl) {
    const int every = ctrl->every;
    if (every <= 0 || (ctrl->step + 1ULL) % (unsigned long long)every != 0ULL) return;
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    double ke = 0.0;
    if (i < N) {
        const double vx = vel64[i * 3 + 0];
        const double vy = vel64[i * 3 + 1];
        const double vz = vel64[i * 3 + 2];
        ke = 0.5 * masses[i] * (vx * vx + vy * vy + vz * vz);
    }
    #pragma unroll
    for (int off = 16; off > 0; off >>= 1) ke += __shfl_xor_sync(0xffffffffu, ke, off);
    __shared__ double s_ke[8];
    const int warp = threadIdx.x >> 5;
    if ((threadIdx.x & 31) == 0) s_ke[warp] = ke;
    __syncthreads();
    if (threadIdx.x == 0) {
        double sum = 0.0;
        const int nw = blockDim.x >> 5;
        for (int w = 0; w < nw; ++w) sum += s_ke[w];
        atomicAdd(&ctrl->ke, sum);
    }
}

__global__ void thermo_row_kernel(int dof, double e0_total, double kb, const double* __restrict__ energy,
                                  ThermoCtrl* __restrict__ ctrl, LoupThermoRow* __restrict__ rows,
                                  const double* __restrict__ transferred, const CellDev* __restrict__ cell,
                                  const double* __restrict__ virial) {
    const unsigned long long step = ctrl->step + 1ULL;
    ctrl->step = step;
    const int every = ctrl->every;
    if (every <= 0 || step % (unsigned long long)every != 0ULL) return;
    if (ctrl->count < ctrl->capacity) {  // the host refuses a run that would not fit, so this always holds
        LoupThermoRow row;
        row.step = (long long)step;
        row.e_pot = e0_total + *energy;
        row.e_kin = ctrl->ke;
        row.temp_k = 2.0 * row.e_kin / ((double)dof * kb);
        row.pressure_gpa = 0.0;
        row.volume_a3 = 0.0;
        if (cell && virial) {  // the variable-cell step: its force pass carries stress
            const double volume = cell->volume;
            row.volume_a3 = volume;
            // minus a third of the stress's trace, plus the ideal-gas part 2 E_kin / (3 V); eV/A^3 -> GPa
            row.pressure_gpa = (2.0 * row.e_kin - (virial[0] + virial[3] + virial[5])) / (3.0 * volume) *
                               160.21766208;
        }
        row.conserved = row.e_pot + row.e_kin - (transferred ? transferred[0] : 0.0);
        rows[ctrl->count] = row;
        ctrl->count += 1;
    }
    ctrl->ke = 0.0;
}

}  // namespace loup
