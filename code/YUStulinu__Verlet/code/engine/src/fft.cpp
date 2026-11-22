#include "verlet/fft.hpp"

#include <cmath>

#include "verlet/vec.hpp"

namespace verlet {

std::vector<int> fft_radices(int n) {
    std::vector<int> r;
    while (n % 4 == 0) { r.push_back(4); n /= 4; }
    for (int p : {2, 3, 5, 7}) while (n % p == 0) { r.push_back(p); n /= p; }
    for (int p = 11; n > 1; p += 2) while (n % p == 0) { r.push_back(p); n /= p; }
    return r;
}

int fft_friendly_size(int n) {
    for (int m = std::max(n, 1);; ++m) {
        int k = m;
        for (int p : {2, 3, 5, 7}) while (k % p == 0) k /= p;
        if (k == 1) return m;
    }
}

// One Stockham stage: for j in [0, n/R): read R values strided by n/R, twiddle,
// a DFT of size R, write them strided by Ns at the autosorted position.
static void stage(const cplx* in, cplx* out, int n, int R, int Ns, int sign) {
    const int m = n / R;
    cplx v[64];
    for (int j = 0; j < m; ++j) {
        int jm = j % Ns;
        double angle = sign * 2 * kPi * jm / (double(Ns) * R);
        for (int r = 0; r < R; ++r) v[r] = in[j + r * m] * std::polar(1.0, r * angle);
        cplx w[64];
        if (R == 2) {
            w[0] = v[0] + v[1];
            w[1] = v[0] - v[1];
        } else if (R == 4) {
            cplx a = v[0] + v[2], b = v[0] - v[2], c = v[1] + v[3], d = (v[1] - v[3]) * cplx(0, sign);
            w[0] = a + c;
            w[1] = b + d;
            w[2] = a - c;
            w[3] = b - d;
        } else {
            for (int k = 0; k < R; ++k) {
                cplx s = 0;
                for (int r = 0; r < R; ++r) s += v[r] * std::polar(1.0, sign * 2 * kPi * ((r * k) % R) / R);
                w[k] = s;
            }
        }
        int base = (j / Ns) * Ns * R + jm;
        for (int r = 0; r < R; ++r) out[base + r * Ns] = w[r];
    }
}

void fft_1d(cplx* data, int n, int sign, std::vector<cplx>& work) {
    if (n <= 1) return;
    work.resize(n);
    cplx* a = data;
    cplx* b = work.data();
    int Ns = 1;
    for (int R : fft_radices(n)) {
        stage(a, b, n, R, Ns, sign);
        Ns *= R;
        std::swap(a, b);
    }
    if (a != data)
        for (int i = 0; i < n; ++i) data[i] = a[i];
}

void fft_3d(std::vector<cplx>& g, int nx, int ny, int nz, int sign) {
    std::vector<cplx> line, work;
    // z lines (contiguous)
    for (int x = 0; x < nx; ++x)
        for (int y = 0; y < ny; ++y) fft_1d(&g[(size_t(x) * ny + y) * nz], nz, sign, work);
    // y lines
    line.resize(ny);
    for (int x = 0; x < nx; ++x)
        for (int z = 0; z < nz; ++z) {
            for (int y = 0; y < ny; ++y) line[y] = g[(size_t(x) * ny + y) * nz + z];
            fft_1d(line.data(), ny, sign, work);
            for (int y = 0; y < ny; ++y) g[(size_t(x) * ny + y) * nz + z] = line[y];
        }
    // x lines
    line.resize(nx);
    for (int y = 0; y < ny; ++y)
        for (int z = 0; z < nz; ++z) {
            for (int x = 0; x < nx; ++x) line[x] = g[(size_t(x) * ny + y) * nz + z];
            fft_1d(line.data(), nx, sign, work);
            for (int x = 0; x < nx; ++x) g[(size_t(x) * ny + y) * nz + z] = line[x];
        }
}

}  // namespace verlet
