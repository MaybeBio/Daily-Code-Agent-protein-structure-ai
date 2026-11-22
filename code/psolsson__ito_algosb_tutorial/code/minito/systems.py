"""The Wolfe-Quapp potential and an overdamped Langevin simulator to generate reference data."""

import numpy as np


class WolfeQuapp:
    """Two-dimensional Wolfe-Quapp potential

        E(x, y) = x^4 + y^4 - 2 x^2 - 4 y^2 + x y + 0.3 x + 0.1 y

    It has three minima: a deep one at top-left, one at bottom-right and a
    shallow one at bottom-left. Transitions between top and bottom are rare at kT = 1.
    """

    dim = 2
    minima = np.array([[-1.174, 1.477], [1.124, -1.485], [-0.822, -1.367]])

    def energy(self, xy):
        x, y = xy[..., 0], xy[..., 1]
        return x**4 + y**4 - 2 * x**2 - 4 * y**2 + x * y + 0.3 * x + 0.1 * y

    def force(self, xy):
        x, y = xy[..., 0], xy[..., 1]
        fx = -(4 * x**3 - 4 * x + y + 0.3)
        fy = -(4 * y**3 - 8 * y + x + 0.1)
        return np.stack([fx, fy], axis=-1)

    def grid(self, lim=(-2.2, 2.2), n=200):
        """Return (X, Y, E) on a regular grid, for contour plots."""
        g = np.linspace(*lim, n)
        X, Y = np.meshgrid(g, g)
        return X, Y, self.energy(np.stack([X, Y], axis=-1))

    def free_energy_1d(self, kT, axis=0, lim=(-2.2, 2.2), n=200):
        """Exact free energy along x (axis=0) or y (axis=1), shifted to min 0."""
        X, Y, E = self.grid(lim, n)
        p = np.exp(-(E - E.min()) / kT).sum(axis=axis)  # E[i, j] = E(x_j, y_i)
        coord = X[0] if axis == 0 else Y[:, 0]
        F = -kT * np.log(p / p.sum())
        return coord, F - F.min()


def simulate(system, x0, kT=1.0, dt=2e-3, n_steps=100_000, stride=50, seed=0):
    """Overdamped Langevin dynamics, Euler-Maruyama integrator.

        x_{n+1} = x_n + F(x_n) dt + sqrt(2 kT dt) * noise

    Args:
        x0: starting points, shape (n_walkers, dim). All walkers are simulated in parallel.
        stride: save every `stride` integration steps.

    Returns:
        traj: array (n_walkers, n_steps // stride, dim), float32.
        The time between saved frames is dt * stride.
    """
    rng = np.random.default_rng(seed)
    x = np.array(x0, dtype=np.float64)
    n_frames = n_steps // stride
    traj = np.empty((x.shape[0], n_frames, x.shape[1]), dtype=np.float32)
    noise_scale = np.sqrt(2 * kT * dt)
    for i in range(n_frames * stride):
        x = x + system.force(x) * dt + noise_scale * rng.standard_normal(x.shape)
        if (i + 1) % stride == 0:
            traj[:, (i + 1) // stride - 1] = x
    return traj
