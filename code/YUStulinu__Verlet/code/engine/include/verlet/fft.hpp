// A mixed-radix complex FFT (Stockham autosort; radices 2, 3, 4, 5, 7 and a
// generic odd-prime DFT), and its three-dimensional form for the PME grid.
// The same plan (radix sequence and stage formula) is used by the CUDA kernels.
#pragma once

#include <complex>
#include <vector>

namespace verlet {

using cplx = std::complex<double>;

/// The radix sequence for n (empty if n has a prime factor above 7... handled
/// by the generic stage, so any n >= 1 works).
std::vector<int> fft_radices(int n);

/// In-place 1D transform of `data` (length n): sign -1 forward (exp(-2 pi i jk/n)), +1 backward, unnormalized.
void fft_1d(cplx* data, int n, int sign, std::vector<cplx>& work);

/// In-place 3D transform of a grid stored [x][y][z] (z fastest).
void fft_3d(std::vector<cplx>& grid, int nx, int ny, int nz, int sign);

/// The smallest m >= n whose prime factors are all 2, 3, 5 or 7.
int fft_friendly_size(int n);

}  // namespace verlet
