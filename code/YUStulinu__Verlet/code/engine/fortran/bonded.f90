! Bonded interactions of the Amber force field, in modern Fortran:
!   bonds        E = k/2 (r - r0)^2
!   angles       E = k/2 (theta - theta0)^2
!   torsions     E = k (1 + cos(n phi - phase))   (proper and improper)
!   1-4 pairs    E = qq_scaled * 1/(4 pi eps0)/r + 4 eps_scaled ((s/r)^12 - (s/r)^6)
! Positions are in nm (minimum image in an orthorhombic box), energies in
! kJ/mol, forces are added to f. Called from C++ through ISO_C_BINDING.
module verlet_bonded
  use, intrinsic :: iso_c_binding, only: c_int, c_double
  implicit none
  private
  public :: verlet_bonded_forces

  real(c_double), parameter :: one_4pi_eps0 = 138.935456_c_double

contains

  pure function min_image(d, box) result(r)
    real(c_double), intent(in) :: d(3), box(3)
    real(c_double) :: r(3)
    r = d - box * anint(d / box)
  end function min_image

  pure function cross(a, b) result(c)
    real(c_double), intent(in) :: a(3), b(3)
    real(c_double) :: c(3)
    c = [a(2) * b(3) - a(3) * b(2), a(3) * b(1) - a(1) * b(3), a(1) * b(2) - a(2) * b(1)]
  end function cross

  subroutine verlet_bonded_forces(n, x, box, &
                                  nb, bidx, bpar, &
                                  na, aidx, apar, &
                                  nt, tidx, tper, tpar, &
                                  np, pidx, ppar, &
                                  f, energy) bind(C, name="verlet_bonded_forces")
    integer(c_int), value, intent(in) :: n, nb, na, nt, np
    real(c_double), intent(in) :: x(3, n), box(3)
    integer(c_int), intent(in) :: bidx(2, nb), aidx(3, na), tidx(4, nt), tper(nt), pidx(2, np)
    real(c_double), intent(in) :: bpar(2, nb), apar(2, na), tpar(2, nt), ppar(3, np)
    real(c_double), intent(inout) :: f(3, n)
    real(c_double), intent(out) :: energy(4)   ! bonds, angles, torsions, 1-4 pairs

    integer :: m, i, j, k, l
    real(c_double) :: d(3), r, dr, g, e
    real(c_double) :: u(3), v(3), ru, rv, c, theta, dtheta, fi(3), fk(3)
    real(c_double) :: b1(3), b2(3), b3(3), c12(3), c23(3), n12, n23, rb2, phi, s, fj(3), fl(3)
    real(c_double) :: inv_r2, s6, sg

    energy = 0

    ! bonds
    do m = 1, nb
      i = bidx(1, m) + 1
      j = bidx(2, m) + 1
      d = min_image(x(:, j) - x(:, i), box)
      r = norm2(d)
      dr = r - bpar(1, m)
      energy(1) = energy(1) + 0.5_c_double * bpar(2, m) * dr * dr
      g = bpar(2, m) * dr / r
      f(:, i) = f(:, i) + g * d
      f(:, j) = f(:, j) - g * d
    end do

    ! angles i-j-k (j at the vertex)
    do m = 1, na
      i = aidx(1, m) + 1
      j = aidx(2, m) + 1
      k = aidx(3, m) + 1
      u = min_image(x(:, i) - x(:, j), box)
      v = min_image(x(:, k) - x(:, j), box)
      ru = norm2(u)
      rv = norm2(v)
      c = max(-1.0_c_double, min(1.0_c_double, dot_product(u, v) / (ru * rv)))
      theta = acos(c)
      dtheta = theta - apar(1, m)
      energy(2) = energy(2) + 0.5_c_double * apar(2, m) * dtheta * dtheta
      s = max(sqrt(1 - c * c), 1e-12_c_double)
      g = apar(2, m) * dtheta / s   ! -dE/dc
      fi = g * (v / (ru * rv) - c * u / (ru * ru))
      fk = g * (u / (ru * rv) - c * v / (rv * rv))
      f(:, i) = f(:, i) + fi
      f(:, k) = f(:, k) + fk
      f(:, j) = f(:, j) - fi - fk
    end do

    ! periodic torsions i-j-k-l (Bekker's formulation of the forces)
    do m = 1, nt
      i = tidx(1, m) + 1
      j = tidx(2, m) + 1
      k = tidx(3, m) + 1
      l = tidx(4, m) + 1
      b1 = min_image(x(:, j) - x(:, i), box)
      b2 = min_image(x(:, k) - x(:, j), box)
      b3 = min_image(x(:, l) - x(:, k), box)
      c12 = cross(b1, b2)
      c23 = cross(b2, b3)
      n12 = dot_product(c12, c12)
      n23 = dot_product(c23, c23)
      if (n12 < 1e-24_c_double .or. n23 < 1e-24_c_double) cycle
      rb2 = norm2(b2)
      phi = atan2(rb2 * dot_product(b1, c23), dot_product(c12, c23))
      energy(3) = energy(3) + tpar(2, m) * (1 + cos(tper(m) * phi - tpar(1, m)))
      g = -tpar(2, m) * tper(m) * sin(tper(m) * phi - tpar(1, m))   ! dE/dphi
      ! forces on the outer atoms are normal to their planes; the inner ones
      ! balance them (no net force or torque)
      fi = g * rb2 / n12 * c12
      fl = -g * rb2 / n23 * c23
      s = -dot_product(b1, b2) / (rb2 * rb2)
      e = -dot_product(b3, b2) / (rb2 * rb2)
      fj = fi - (s * fi - e * fl)
      fk = fl + (s * fi - e * fl)
      f(:, i) = f(:, i) + fi
      f(:, j) = f(:, j) - fj
      f(:, k) = f(:, k) - fk
      f(:, l) = f(:, l) + fl
    end do

    ! 1-4 pairs: scaled Lennard-Jones and plain (not Ewald) Coulomb
    do m = 1, np
      i = pidx(1, m) + 1
      j = pidx(2, m) + 1
      d = min_image(x(:, i) - x(:, j), box)
      inv_r2 = 1 / dot_product(d, d)
      r = sqrt(dot_product(d, d))
      e = one_4pi_eps0 * ppar(1, m) / r
      g = e * inv_r2
      if (ppar(3, m) /= 0) then
        sg = ppar(2, m)
        s6 = (sg * sg * inv_r2)**3
        e = e + 4 * ppar(3, m) * (s6 * s6 - s6)
        g = g + 24 * ppar(3, m) * (2 * s6 * s6 - s6) * inv_r2
      end if
      energy(4) = energy(4) + e
      f(:, i) = f(:, i) + g * d
      f(:, j) = f(:, j) - g * d
    end do
  end subroutine verlet_bonded_forces

end module verlet_bonded
