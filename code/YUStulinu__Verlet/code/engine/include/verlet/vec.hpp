// 3-vectors and the constants of the unit system (nm, ps, amu, kJ/mol, e, K).
#pragma once

#include <cmath>

namespace verlet {

struct Vec3 {
    double x = 0, y = 0, z = 0;
    double& operator[](int i) { return i == 0 ? x : (i == 1 ? y : z); }
    double operator[](int i) const { return i == 0 ? x : (i == 1 ? y : z); }
};

inline Vec3 operator+(Vec3 a, Vec3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
inline Vec3 operator-(Vec3 a, Vec3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
inline Vec3 operator-(Vec3 a) { return {-a.x, -a.y, -a.z}; }
inline Vec3 operator*(double s, Vec3 a) { return {s * a.x, s * a.y, s * a.z}; }
inline Vec3 operator*(Vec3 a, double s) { return s * a; }
inline Vec3 operator/(Vec3 a, double s) { return {a.x / s, a.y / s, a.z / s}; }
inline Vec3& operator+=(Vec3& a, Vec3 b) { a.x += b.x; a.y += b.y; a.z += b.z; return a; }
inline Vec3& operator-=(Vec3& a, Vec3 b) { a.x -= b.x; a.y -= b.y; a.z -= b.z; return a; }
inline Vec3& operator*=(Vec3& a, double s) { a.x *= s; a.y *= s; a.z *= s; return a; }
inline double dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
inline Vec3 cross(Vec3 a, Vec3 b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
inline double norm(Vec3 a) { return std::sqrt(dot(a, a)); }
inline Vec3 mul(Vec3 a, Vec3 b) { return {a.x * b.x, a.y * b.y, a.z * b.z}; }

/// Minimum-image difference in an orthorhombic box.
inline Vec3 min_image(Vec3 d, Vec3 box) {
    d.x -= box.x * std::nearbyint(d.x / box.x);
    d.y -= box.y * std::nearbyint(d.y / box.y);
    d.z -= box.z * std::nearbyint(d.z / box.z);
    return d;
}

constexpr double kPi = 3.14159265358979323846;
constexpr double kOneFourPiEps0 = 138.935456;        // kJ mol^-1 nm e^-2 (OpenMM's value)
constexpr double kBoltzmann = 0.00831446261815324;  // kJ mol^-1 K^-1
constexpr double kBarToInternal = 0.0602214076;     // 1 bar in kJ mol^-1 nm^-3
constexpr double kAvogadro = 6.02214076e23;

}  // namespace verlet
