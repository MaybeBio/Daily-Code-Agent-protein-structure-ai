"""Analysis helpers for part 1: free energies, basins and Markov state models (via deeptime)."""

import numpy as np
import torch
import matplotlib.pyplot as plt
from deeptime.clustering import KMeans
from deeptime.markov import TransitionCountEstimator, TransitionCountModel
from deeptime.markov.msm import MaximumLikelihoodMSM

from minito.ito import sample

BASIN_NAMES = ["top-left", "bottom-right", "bottom-left"]


def basin(xy):
    """Assign each point to one of the three Wolfe-Quapp basins (0, 1 or 2)."""
    xy = np.asarray(xy)
    x, y = xy[..., 0], xy[..., 1]
    return np.where(y > 0, 0, np.where(x > -0.3, 1, 2))


def basin_populations(xy):
    """Fraction of points in each basin."""
    b = basin(xy).ravel()
    return np.bincount(b, minlength=3) / b.size


def free_energy_1d(samples, kT, bins):
    """F(q) = -kT log p(q) from samples of a 1D coordinate q, shifted to min 0."""
    p, edges = np.histogram(samples, bins=bins, density=True)
    centers = 0.5 * (edges[1:] + edges[:-1])
    with np.errstate(divide="ignore"):
        F = -kT * np.log(p)
    return centers, F - F[np.isfinite(F)].min()


def free_energy_2d(samples, kT, bins):
    """2D free energy surface from (N, 2) samples, shifted to min 0 (empty bins are NaN)."""
    H, xe, ye = np.histogram2d(samples[:, 0], samples[:, 1], bins=bins, density=True)
    with np.errstate(divide="ignore"):
        F = -kT * np.log(H.T)
    F[~np.isfinite(F)] = np.nan
    return xe, ye, F - np.nanmin(F)


def plot_potential(ax, system, levels=np.arange(-7, 2, 0.5), **kwargs):
    X, Y, E = system.grid()
    ax.contour(X, Y, E, levels=levels, colors="0.6", linewidths=0.6, **kwargs)
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_aspect("equal")


# --------------------------------------------------------------------------------------
# Markov state models
# --------------------------------------------------------------------------------------
def make_states(trajs, n_states=40, seed=13):
    """k-means clustering of the 2D space into discrete states (fit on reference data)."""
    data = np.asarray(trajs).reshape(-1, 2)
    stride = max(1, len(data) // 50_000)
    return KMeans(n_clusters=n_states, max_iter=200, fixed_seed=seed).fit(data[::stride]).fetch_model()


def msm_from_trajectories(dtrajs, lag):
    """Reversible maximum-likelihood MSM from discrete trajectories at a given lag (in frames)."""
    counts = TransitionCountEstimator(lagtime=lag, count_mode="sliding").fit_fetch(list(dtrajs))
    return MaximumLikelihoodMSM().fit_fetch(counts.submodel_largest())


def msm_from_ito(model, states, x_start, lag, ode_steps=50):
    """MSM implied by the ITO at a given lag.

    Every start point x_start[i] is propagated by ONE sample of the learned transition density
    p(x_{t+lag} | x_t). Counting state-to-state transitions gives the transition matrix T(lag).
    If x_start is drawn from equilibrium, this mirrors how an MSM is estimated from MD data.
    """
    x_end = sample(model, torch.as_tensor(x_start, dtype=torch.float32), lag, ode_steps).numpy()
    s0, s1 = states.transform(np.asarray(x_start, dtype=np.float32)), states.transform(x_end)
    n = states.n_clusters
    C = np.zeros((n, n))
    np.add.at(C, (s0, s1), 1)
    counts = TransitionCountModel(C, lagtime=lag)
    return MaximumLikelihoodMSM().fit_fetch(counts.submodel_largest())
