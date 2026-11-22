"""The decision rules of the preregistration: medians over units, their bootstrap intervals, and the rotation test.

Units of two bases are different units, never pairs, so a difference of medians is bootstrapped by resampling each
basis's units within itself. The rotation test asks whether the native median exceeds every one of ten rotation
medians (a rank p of 1/11) and by more than the rotations' own range.

Symbols: a, b units of two bases; k rotations.
"""

from __future__ import annotations

import numpy as np

from dataclasses import dataclass


DRAWS = 1000
SEED = 24895
CHUNK = 100  # resamples drawn at a time: the same stream as drawing all at once, in a tenth of the memory


@dataclass(frozen=True)
class Interval:
    estimate: float
    low: float
    high: float

    def excludes(self, value: float) -> bool:
        return value < self.low or value > self.high

    def inside(self, low: float, high: float) -> bool:
        return low <= self.low and self.high <= high


def _resampled_medians(values: np.ndarray, generator: np.random.Generator, draws: int) -> np.ndarray:
    """The medians of `draws` resamples of `values`, `CHUNK` resamples at a time from one generator."""
    # values: (a,)
    medians = [np.median(values[generator.integers(0, values.size, (min(CHUNK, draws - start), values.size))], axis=1)
               for start in range(0, draws, CHUNK)]  # (chunk,) each
    return np.concatenate(medians)  # (draws,)


def median_difference(first: np.ndarray, second: np.ndarray, *, level: float = 0.95, draws: int = DRAWS, seed: int = SEED) -> Interval:
    """The median of `first` minus the median of `second`, with a percentile interval from resampling each set within
    itself; non-finite values are dropped first."""
    # first: (a,); second: (b,)
    first = np.asarray(first, dtype=np.float64)[np.isfinite(first)]  # (a,)
    second = np.asarray(second, dtype=np.float64)[np.isfinite(second)]  # (b,)
    if first.size == 0 or second.size == 0:
        raise ValueError("Both sets need at least one finite value.")
    generator = np.random.default_rng(seed)
    first_draws = _resampled_medians(first, generator, draws)  # (draws,)
    second_draws = _resampled_medians(second, generator, draws)  # (draws,)
    tail = (1 - level) / 2 * 100
    low, high = np.percentile(first_draws - second_draws, [tail, 100 - tail])
    return Interval(float(np.median(first) - np.median(second)), float(low), float(high))


def median_interval(values: np.ndarray, *, level: float = 0.95, draws: int = DRAWS, seed: int = SEED) -> Interval:
    """The median of one set of units, with a percentile interval from resampling them; non-finite values are dropped."""
    # values: (a,)
    values = np.asarray(values, dtype=np.float64)[np.isfinite(values)]  # (a,)
    if values.size == 0:
        raise ValueError("The set needs at least one finite value.")
    medians = _resampled_medians(values, np.random.default_rng(seed), draws)  # (draws,)
    tail = (1 - level) / 2 * 100
    low, high = np.percentile(medians, [tail, 100 - tail])
    return Interval(float(np.median(values)), float(low), float(high))


@dataclass(frozen=True)
class RotationTest:
    native: float
    rotations: tuple[float, ...]
    rank_p: float  # share of {native} and rotations at or above the native median
    range_gap: float  # native minus the best rotation, against the rotations' range

    @property
    def privileged(self) -> bool:
        """H2's rule: above every rotation, by more than the rotations' range."""
        spread = max(self.rotations) - min(self.rotations)
        return self.native > max(self.rotations) and self.range_gap > spread


def rotation_test(native: np.ndarray, rotated: list[np.ndarray]) -> RotationTest:
    """H2: is the native median above all rotation medians, by more than their range?"""
    # native: (a,); rotated: (k, a), a list of k arrays
    native_median = float(np.nanmedian(native))
    medians = tuple(float(np.nanmedian(values)) for values in rotated)
    at_or_above = 1 + sum(median >= native_median for median in medians)
    return RotationTest(
        native=native_median,
        rotations=medians,
        rank_p=at_or_above / (len(medians) + 1),
        range_gap=native_median - max(medians),
    )
