"""The paired test of neurons against rotations: Holm's correction, and one row a rotation over the concepts scored
under both bases (CPU)."""

import numpy as np
import pandas as pd
import pytest

from plm_interpretability.units import paired_rotations


def test_holm_is_monotone_and_keeps_the_given_order() -> None:
    p_values = np.array([0.04, 0.001, 0.03, 0.5])  # (t,)
    adjusted = paired_rotations.holm(p_values)  # (t,)
    np.testing.assert_allclose(adjusted, [0.09, 0.004, 0.09, 0.5])


def test_holm_caps_at_one() -> None:
    np.testing.assert_allclose(paired_rotations.holm(np.array([0.6, 0.9])), [1.0, 1.0])


def per_concept(generator: np.random.Generator) -> pd.DataFrame:
    """A per-concept table of one block: the neurons 0.1 above each of two rotations, one concept unscored."""
    concepts = [f"concept {index}" for index in range(paired_rotations.CONCEPTS)]
    base = generator.uniform(0.1, 0.7, len(concepts))  # (c,)
    arms = {"mlp_poles": base + 0.1, "mlp_rotation0": base + generator.normal(0, 0.01, len(concepts)),
            "mlp_rotation1": base + generator.normal(0, 0.01, len(concepts)), "residual": base}
    arms["mlp_rotation1"][0] = np.nan
    frames = [pd.DataFrame({"layer": 26, "arm": arm, "concept": concepts, "best_test_f1": scores})
              for arm, scores in arms.items()]
    return pd.concat(frames, ignore_index=True)


def test_one_row_a_rotation_over_the_concepts_scored_under_both() -> None:
    tests = paired_rotations.rotation_tests(per_concept(np.random.default_rng(3)), "ESMC-600", 26)
    assert list(tests["rotation"]) == ["mlp_rotation0", "mlp_rotation1"]
    assert list(tests["pairs"]) == [paired_rotations.CONCEPTS, paired_rotations.CONCEPTS - 1]
    assert (tests["neurons_higher"] == tests["pairs"]).all()
    np.testing.assert_allclose(tests["median_difference"], 0.1, atol=0.005)
    assert (tests["p_value"] < 1e-50).all()


def test_a_block_without_a_rotation_is_refused() -> None:
    table = per_concept(np.random.default_rng(3))
    with pytest.raises(AssertionError, match="lacks"):
        paired_rotations.rotation_tests(table[~table["arm"].str.startswith("mlp_rotation")], "ESMC-600", 26)
