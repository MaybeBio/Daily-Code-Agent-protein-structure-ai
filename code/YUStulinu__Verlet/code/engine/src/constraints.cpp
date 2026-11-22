#include "verlet/constraints.hpp"

#include <cmath>
#include <stdexcept>

namespace verlet {

Constraints::Constraints(const System& s, double tol) : s_(s), tol_(tol) {
    invm_.resize(s.n);
    for (int i = 0; i < s.n; ++i) invm_[i] = s.mass[i] > 0 ? 1 / s.mass[i] : 0;
}

namespace {

// SETTLE for one water: old positions a0,b0,c0 (satisfying the constraints),
// new positions a1,b1,c1 (replaced by the constrained ones).
void settle_one(Vec3 a0, Vec3 b0, Vec3 c0, Vec3& a1, Vec3& b1, Vec3& c1, double mO, double mH, double doh, double dhh) {
    const double wt = mO + 2 * mH;
    const double rc = dhh / 2;
    const double ra = 2 * mH * std::sqrt(doh * doh - rc * rc) / wt;
    const double rb = std::sqrt(doh * doh - rc * rc) - ra;
    const Vec3 com = (mO * a1 + mH * (b1 + c1)) / wt;
    const Vec3 xa1 = a1 - com, xb1 = b1 - com, xc1 = c1 - com;
    const Vec3 xb0 = b0 - a0, xc0 = c0 - a0;
    Vec3 Z = cross(xb0, xc0);
    Vec3 X = cross(xa1, Z);
    Vec3 Y = cross(Z, X);
    X = X / norm(X);
    Y = Y / norm(Y);
    Z = Z / norm(Z);
    auto loc = [&](Vec3 v) { return Vec3{dot(X, v), dot(Y, v), dot(Z, v)}; };
    const Vec3 b0d = loc(xb0), c0d = loc(xc0);
    const double za1d = dot(Z, xa1);
    const Vec3 b1d = loc(xb1), c1d = loc(xc1);
    double sinphi = za1d / ra;
    double cosphi = std::sqrt(std::max(0.0, 1 - sinphi * sinphi));
    double sinpsi = (b1d.z - c1d.z) / (2 * rc * cosphi);
    double cospsi = std::sqrt(std::max(0.0, 1 - sinpsi * sinpsi));
    double ya2d = ra * cosphi;
    double xb2d = -rc * cospsi;
    double yb2d = -rb * cosphi - rc * sinpsi * sinphi;
    double yc2d = -rb * cosphi + rc * sinpsi * sinphi;
    double alpha = xb2d * (b0d.x - c0d.x) + b0d.y * yb2d + c0d.y * yc2d;
    double beta = xb2d * (c0d.y - b0d.y) + b0d.x * yb2d + c0d.x * yc2d;
    double gamma = b0d.x * b1d.y - b1d.x * b0d.y + c0d.x * c1d.y - c1d.x * c0d.y;
    double ab2 = alpha * alpha + beta * beta;
    double sinthe = (alpha * gamma - beta * std::sqrt(std::max(0.0, ab2 - gamma * gamma))) / ab2;
    double costhe = std::sqrt(std::max(0.0, 1 - sinthe * sinthe));
    Vec3 a3d{-ya2d * sinthe, ya2d * costhe, za1d};
    Vec3 b3d{xb2d * costhe - yb2d * sinthe, xb2d * sinthe + yb2d * costhe, b1d.z};
    Vec3 c3d{-xb2d * costhe - yc2d * sinthe, -xb2d * sinthe + yc2d * costhe, c1d.z};
    auto lab = [&](Vec3 v) { return v.x * X + v.y * Y + v.z * Z; };
    a1 = com + lab(a3d);
    b1 = com + lab(b3d);
    c1 = com + lab(c3d);
}

// Velocity constraint of one rigid water: the impulses along the three bonds
// that make every relative velocity along a bond zero (a 3x3 linear system).
void settle_velocity(Vec3 xa, Vec3 xb, Vec3 xc, Vec3& va, Vec3& vb, Vec3& vc, double ima, double imh, Vec3 box) {
    Vec3 eab = min_image(xb - xa, box), ebc = min_image(xc - xb, box), eca = min_image(xa - xc, box);
    eab = eab / norm(eab);
    ebc = ebc / norm(ebc);
    eca = eca / norm(eca);
    double vab = dot(vb - va, eab), vbc = dot(vc - vb, ebc), vca = dot(va - vc, eca);
    double d_ab_bc = dot(eab, ebc), d_ab_ca = dot(eab, eca), d_bc_ca = dot(ebc, eca);
    // impulses: t0 along eab (+ on b, - on a), t1 along ebc (+ on c, - on b), t2 along eca (+ on a, - on c);
    // row k: the change of the relative velocity along bond k
    double M[3][3] = {{ima + imh, -imh * d_ab_bc, -ima * d_ab_ca},
                      {-imh * d_ab_bc, 2 * imh, -imh * d_bc_ca},
                      {-ima * d_ab_ca, -imh * d_bc_ca, imh + ima}};
    double rhs[3] = {-vab, -vbc, -vca};
    // Cramer's rule
    auto det3 = [](double m[3][3]) {
        return m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
               m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
    };
    double D = det3(M), t[3];
    for (int c = 0; c < 3; ++c) {
        double Mc[3][3];
        for (int r = 0; r < 3; ++r)
            for (int k = 0; k < 3; ++k) Mc[r][k] = k == c ? rhs[r] : M[r][k];
        t[c] = det3(Mc) / D;
    }
    va += ima * (-t[0] * eab + t[2] * eca);
    vb += imh * (t[0] * eab - t[1] * ebc);
    vc += imh * (t[1] * ebc - t[2] * eca);
}

}  // namespace

void Constraints::positions(const std::vector<Vec3>& ref, std::vector<Vec3>& x, Vec3 box) const {
    if (!s_.waters.empty()) {
        const double mO = s_.mass[s_.waters[0].o], mH = s_.mass[s_.waters[0].h1];
#pragma omp parallel for schedule(static)
        for (int w = 0; w < int(s_.waters.size()); ++w) {
            const Water& W = s_.waters[w];
            // work around the oxygen (waters are kept whole)
            Vec3 a0 = ref[W.o], b0 = a0 + min_image(ref[W.h1] - a0, box), c0 = a0 + min_image(ref[W.h2] - a0, box);
            Vec3 a1 = x[W.o], b1 = a1 + min_image(x[W.h1] - a1, box), c1 = a1 + min_image(x[W.h2] - a1, box);
            settle_one(a0, b0, c0, a1, b1, c1, mO, mH, s_.water_doh, s_.water_dhh);
            x[W.o] = a1;
            x[W.h1] = b1;
            x[W.h2] = c1;
        }
    }
    iters_ = 0;
    if (s_.constraints.empty()) return;
    for (int it = 0; it < 1000; ++it) {
        bool done = true;
        for (const Constraint& c : s_.constraints) {
            Vec3 r = min_image(x[c.i] - x[c.j], box);
            double diff = c.d * c.d - dot(r, r);
            if (std::fabs(diff) > 2 * tol_ * c.d * c.d) done = false;
            Vec3 rr = min_image(ref[c.i] - ref[c.j], box);
            double g = diff / (2 * (invm_[c.i] + invm_[c.j]) * dot(r, rr));
            x[c.i] += g * invm_[c.i] * rr;
            x[c.j] -= g * invm_[c.j] * rr;
        }
        iters_ = it + 1;
        if (done) return;
    }
    throw std::runtime_error("SHAKE did not converge");
}

void Constraints::velocities(const std::vector<Vec3>& x, std::vector<Vec3>& v, Vec3 box) const {
    if (!s_.waters.empty()) {
        const double imO = invm_[s_.waters[0].o], imH = invm_[s_.waters[0].h1];
#pragma omp parallel for schedule(static)
        for (int w = 0; w < int(s_.waters.size()); ++w) {
            const Water& W = s_.waters[w];
            settle_velocity(x[W.o], x[W.h1], x[W.h2], v[W.o], v[W.h1], v[W.h2], imO, imH, box);
        }
    }
    if (s_.constraints.empty()) return;
    for (int it = 0; it < 1000; ++it) {
        bool done = true;
        for (const Constraint& c : s_.constraints) {
            Vec3 r = min_image(x[c.i] - x[c.j], box);
            Vec3 rv = v[c.i] - v[c.j];
            double k = -dot(rv, r) / ((invm_[c.i] + invm_[c.j]) * dot(r, r));
            if (std::fabs(dot(rv, r)) > tol_ * c.d) done = false;
            v[c.i] += k * invm_[c.i] * r;
            v[c.j] -= k * invm_[c.j] * r;
        }
        if (done) return;
    }
    throw std::runtime_error("RATTLE did not converge");
}

}  // namespace verlet
