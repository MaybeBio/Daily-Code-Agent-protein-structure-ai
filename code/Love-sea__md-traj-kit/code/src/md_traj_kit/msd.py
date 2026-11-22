"""Time-origin averaged mean squared displacement."""
import numpy as np
from .core import Trajectory

def mean_squared_displacement(trajectory: Trajectory) -> dict[str, np.ndarray]:
    """Return lag_time_ps and msd_angstrom2, including zero lag.

    Averages over all atoms and all valid time origins, without removing
    center-of-mass drift. Requires equally spaced frames. O(T^2 N) time.
    """
    p, t = trajectory.positions, trajectory.times
    if len(t) > 2 and not np.allclose(np.diff(t), t[1]-t[0], rtol=1e-7, atol=1e-12):
        raise ValueError("MSD requires equally spaced times")
    msd = np.zeros(len(t))
    for lag in range(1, len(t)):
        displacement = p[lag:] - p[:-lag]
        msd[lag] = np.mean(np.sum(displacement**2, axis=-1))
    return {"lag_time_ps": t-t[0], "msd_angstrom2": msd}
