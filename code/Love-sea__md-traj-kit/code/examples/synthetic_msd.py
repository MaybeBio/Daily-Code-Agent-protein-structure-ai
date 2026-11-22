"""Synthetic constant-velocity example; contains no research data."""
import numpy as np
from md_traj_kit import Trajectory, mean_squared_displacement

times = np.arange(6, dtype=float)
positions = np.zeros((6, 2, 3))
positions[:, :, 0] = times[:, None] * 2.0
result = mean_squared_displacement(Trajectory(positions, times, unwrapped=True))
for lag, msd in zip(result["lag_time_ps"], result["msd_angstrom2"]):
    print(f"lag={lag:g} ps, MSD={msd:g} angstrom^2")
