import numpy as np
import pytest
from md_traj_kit import Trajectory, mean_squared_displacement

def test_stationary_atoms():
    p = np.broadcast_to(np.arange(6).reshape(2, 3), (5, 2, 3))
    result = mean_squared_displacement(Trajectory(p, np.arange(5), True))
    np.testing.assert_array_equal(result["msd_angstrom2"], np.zeros(5))

def test_constant_velocity_and_translation_invariance():
    t = np.arange(6) * 0.5
    velocity = np.array([2., -1., 3.])
    p = np.broadcast_to(t[:, None, None]*velocity, (6, 2, 3)).copy()
    for offset in (0., 100.):
        result = mean_squared_displacement(Trajectory(p+offset, t, True))
        np.testing.assert_allclose(result["msd_angstrom2"], 14*t**2)
        np.testing.assert_allclose(result["lag_time_ps"], t)

def test_wrapped_coordinates_rejected():
    with pytest.raises(ValueError, match="unwrapped"):
        Trajectory(np.zeros((3, 1, 3)), np.arange(3))

def test_irregular_sampling_rejected():
    trajectory = Trajectory(np.zeros((3, 1, 3)), np.array([0., 1., 3.]), True)
    with pytest.raises(ValueError, match="equally spaced"):
        mean_squared_displacement(trajectory)

@pytest.mark.parametrize("times", [np.array([0., 0., 1.]), np.array([0., np.nan, 2.])])
def test_invalid_times_rejected(times):
    with pytest.raises(ValueError):
        Trajectory(np.zeros((3, 1, 3)), times, True)
