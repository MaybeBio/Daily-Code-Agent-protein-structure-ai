from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from pathlib import Path
from scipy import stats
from scipy.spatial.distance import pdist
from sklearn.linear_model import Ridge

from plm_interpretability.units import subspaces
from plm_interpretability.units.concepts import ConceptProteins, ConceptTask


SPLIT_ROWS = {"train": np.arange(0, 600), "validation": np.arange(600, 750), "test": np.arange(750, 900)}
PROTPARAM = ("length", "mass", *subspaces.COMPOSITION, *subspaces.PHYSICOCHEMICAL)


def _planted_family(seed: int, rank: int = 2, width: int = 30, targets: int = 8) -> tuple[np.ndarray, subspaces.Family]:
    rng = np.random.default_rng(seed)
    features = rng.normal(size=(900, width))  # (n, w)
    mixing = rng.normal(size=(width, rank)) @ rng.normal(size=(rank, targets))  # (w, t), rank `rank`
    values = features @ mixing + 0.1 * rng.normal(size=(900, targets))  # (n, t)
    family = subspaces.Family("planted", "r2", "concepts", "planted", SPLIT_ROWS,
                              {split: values[index] for split, index in SPLIT_ROWS.items()})
    return features, family  # (n, w), family


def test_full_readout_is_ridge_and_the_planted_rank_is_found() -> None:
    features, family = _planted_family(0)
    split_features = {split: features[index] for split, index in SPLIT_ROWS.items()}
    table = subspaces.readout_scores(split_features, [family]).set_index("rank")
    assert list(table.index) == [1, 2, 4, 8] and bool(table.loc[8, "full"])
    assert (table["dimension"] == 2).all() and table.loc[2, "validation"] > 0.95 > table.loc[1, "validation"]
    mean, scale = split_features["train"].mean(axis=0), split_features["train"].std(axis=0, ddof=1)  # (w,), (w,)
    model = Ridge(alpha=float(table.loc[8, "penalty"])).fit((split_features["train"] - mean) / scale, family.values["train"])
    predicted = model.predict((split_features["validation"] - mean) / scale)  # (n_validation, t)
    assert table.loc[8, "validation"] == pytest.approx(subspaces.family_score(predicted, family, "validation"), abs=1e-9)
    assert 1.5 < table.loc[8, "stable_rank"] < 2.5


def test_spectral_directions_span_wide_features() -> None:
    features = torch.from_numpy(np.random.default_rng(1).normal(size=(20, 50)))  # (n, w), wider than tall
    values, vectors = subspaces.spectral(features)  # (k,), (w, k)
    assert values.shape == (20,)
    torch.testing.assert_close(vectors.T @ vectors, torch.eye(20, dtype=torch.float64), atol=1e-8, rtol=0)
    torch.testing.assert_close(features @ vectors @ vectors.T, features, atol=1e-8, rtol=0)
    torch.testing.assert_close(values.sort().values, (torch.linalg.svdvals(features) ** 2).sort().values, atol=1e-8, rtol=1e-10)


def test_lineage_distances_count_edges_and_scaling_recovers_euclidean_points() -> None:
    lineages = [(1, 2, 3, 4), (1, 2, 5), (1, 6)]
    np.testing.assert_array_equal(subspaces.lineage_distances(lineages, lineages), [[0, 3, 4], [3, 0, 3], [4, 3, 0]])
    points = np.random.default_rng(2).normal(size=(30, 2))  # (n, 2)
    distances = np.sqrt(((points[:, None] - points[None]) ** 2).sum(axis=-1))  # (n, n)
    coordinates = subspaces.mds_coordinates(distances, 2)  # (n, 2)
    np.testing.assert_allclose(pdist(coordinates), pdist(points), atol=1e-8)


def test_rank_lineages_skip_ranks_the_organisms_disagree_on() -> None:
    table = pd.DataFrame({"protein_id": ["a", "b", "c"], **{rank: [float(10 * depth + 1), float(10 * depth + 2), np.nan]
                                                            for depth, rank in enumerate(subspaces.TAXONOMIC_RANKS)}})
    table.loc[1, "class"] = np.nan  # b's organisms disagree at the class
    lineages = subspaces.rank_lineages(table)
    assert lineages["a"] == (1, 11, 21, 31, 41, 51, 61, 71) and lineages["c"] == ()
    assert lineages["b"] == (2, 12, 22, 42, 52, 62, 72)
    assert subspaces.lineage_distances([lineages["a"]], [lineages["b"]])[0, 0] == 15  # no shared taxon: 8 + 7 edges


def test_taxonomy_panel_takes_one_training_protein_from_each_cluster() -> None:
    atlas = pd.DataFrame({"accession": [f"P{row}" for row in range(14)], "sequence": ["MA"] * 14,
                          "cluster": [0, 0, 1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
                          "split": ["train"] * 12 + ["validation"] * 2})
    lineages = {f"P{row}": (1, 2, row) for row in range(14) if row != 4}
    panel = subspaces.taxonomy_panel(atlas, lineages, proteins=8, shares=(0.5, 0.25, 0.25), seed=3)
    chosen = atlas.set_index("accession").loc[list(panel.accessions)]
    assert len(panel.accessions) == 8 and chosen["cluster"].is_unique and (chosen["split"] == "train").all()
    assert "P4" not in panel.accessions and panel.lineages[0] == lineages[panel.accessions[0]]
    assert list(panel.split) == ["train"] * 4 + ["validation"] * 2 + ["test"] * 2
    assert subspaces.taxonomy_panel(atlas, lineages, proteins=8, shares=(0.5, 0.25, 0.25), seed=3).accessions == panel.accessions
    with pytest.raises(ValueError, match="fewer than 12"):
        subspaces.taxonomy_panel(atlas, lineages, proteins=12)


def _frames(labels: np.ndarray) -> dict[str, pd.DataFrame]:
    # labels: (n,) or (n, t)
    return {split: pd.DataFrame({"id": index.astype(str), "sequence": ["A"] * len(index), "label": list(labels[index])})
            for split, index in SPLIT_ROWS.items()}


def test_concept_families_follow_protparam_and_localization() -> None:
    rng = np.random.default_rng(4)
    values = rng.random((900, len(PROTPARAM))) + 0.5  # (n, 31)
    values[:, 0] = np.exp(rng.normal(5.5, 0.6, size=900))  # lengths
    classes = rng.integers(0, 4, size=900)  # (n,)
    classes[:3] = 4  # a class too rare to score
    tasks = {"prot_param": ConceptTask("prot_param", "protein", "regression", PROTPARAM, _frames(values)),
             "localization": ConceptTask("localization", "protein", "multiclass", ("a", "b", "c", "d", "e"), _frames(classes))}
    proteins = ConceptProteins([f"P{row}" for row in range(900)], {name: SPLIT_ROWS for name in tasks})
    families = {family.name: family for family in subspaces.concept_families(tasks, proteins)}
    assert list(families) == ["composition", "physicochemistry", "length", "localization"]
    assert families["composition"].targets == 20 and families["physicochemistry"].targets == 9
    np.testing.assert_allclose(families["composition"].values["train"].mean(axis=0), 0, atol=1e-12)
    np.testing.assert_allclose(families["composition"].values["test"][:, 0] * values[:600, 2].std() + values[:600, 2].mean(),
                               values[750:, 2])
    counts = families["length"].values["train"].sum(axis=0)  # (bins,)
    assert families["length"].targets == subspaces.LENGTH_BINS and counts.min() >= 59 and counts.max() <= 61
    assert families["localization"].targets == 4 and families["localization"].task == "localization"


def _planted_blocks(seed: int) -> tuple[np.ndarray, np.ndarray, subspaces.Family]:
    """40 poles in co-firing groups; poles 4 to 6 carry a three-target family, every other pole is noise."""
    rng = np.random.default_rng(seed)
    sources = rng.normal(size=(900, 14))  # (n, 14), each group's shared signal
    group = np.repeat(np.arange(14), [3, 3, 3, 3, 2, 2, 2, 2, 2, 2, 1, 1, 1, 1])  # (28,)
    grouped = sources[:, group] + 0.4 * rng.normal(size=(900, 28))  # (n, 28)
    poles = np.hstack((grouped, rng.normal(size=(900, 12))))  # (n, 40)
    values = poles[:, 3:6] @ rng.normal(size=(3, 3)) + 0.05 * rng.normal(size=(900, 3))  # (n, 3)
    family = subspaces.Family("planted", "r2", "concepts", "planted", SPLIT_ROWS,
                              {split: values[index] for split, index in SPLIT_ROWS.items()})
    return poles, np.corrcoef(poles.T), family  # (n, 40), (40, 40), family


def test_cofiring_blocks_recover_groups_and_beat_random_poles() -> None:
    poles, correlation, family = _planted_blocks(7)
    blocks = subspaces.cofiring_blocks(correlation)  # (40,)
    assert len(set(blocks[3:6])) == 1 and blocks[2] != blocks[3] and len(set(blocks[28:])) == 12
    split_features = {split: poles[index] for split, index in SPLIT_ROWS.items()}
    standard = {split: torch.from_numpy((array - split_features["train"].mean(axis=0)) / split_features["train"].std(axis=0, ddof=1))
                for split, array in split_features.items()}
    targets = {split: torch.from_numpy(values) for split, values in family.values.items()}
    columns = torch.tensor([[3, 4, 5], [0, 1, 2]])
    scores = subspaces.block_validation_r2(standard, columns, targets)  # (2,)
    model = Ridge(alpha=subspaces.BLOCK_PENALTY).fit(standard["train"][:, 3:6].numpy(), family.values["train"])
    expected = subspaces.family_score(model.predict(standard["validation"][:, 3:6].numpy()), family, "validation")
    assert float(scores[0]) == pytest.approx(expected, abs=1e-9) and float(scores[1]) < 0.2
    table = subspaces.run_blocks(split_features, [family], blocks, draws=5).iloc[0]
    assert table["best_size"] == 3 and table["best_test"] > 0.95 and table["blocks"] == 10
    assert table["null_high"] < table["best_test"] and table["null_at_or_above"] == 0.0


def test_e10_blocks_read_pooled_poles_beside_every_pole(tmp_path: Path) -> None:
    poles, correlation, family = _planted_blocks(8)
    (tmp_path / "features").mkdir()
    np.save(tmp_path / "features" / "block2_poles_mean.npy", poles.astype(np.float32))
    table = subspaces.run_e10_blocks(tmp_path, [family], 2, correlation, log=lambda message: None).iloc[0]
    assert table["block"] == 2 and table["best_size"] == 3 and table["all_poles_test"] > 0.95
    with pytest.raises(ValueError, match="covers 39 poles"):
        subspaces.run_e10_blocks(tmp_path, [family], 2, correlation[1:, 1:], log=lambda message: None)


def test_e10_reads_each_family_from_its_extraction(tmp_path: Path) -> None:
    rng = np.random.default_rng(5)
    features, family = _planted_family(6, width=12)
    lineages = [(1, 2 + branch, 10 + 3 * branch + leaf, 100 + row) for row, (branch, leaf) in
                enumerate(zip(rng.integers(0, 4, size=240), rng.integers(0, 3, size=240), strict=True))]
    tree = subspaces.mds_coordinates(subspaces.lineage_distances(lineages, lineages), 8)  # (240, 8)
    panel_features = np.hstack((tree, rng.normal(size=(240, 4)))) + 0.05 * rng.normal(size=(240, 12))  # (240, 12)
    for name, array in (("concepts", features), ("panel", panel_features)):
        (tmp_path / name / "features").mkdir(parents=True)
        for feature in subspaces.FEATURES:
            np.save(tmp_path / name / "features" / f"block4_{feature}.npy", array.astype(np.float32))
    split = np.array(["train"] * 160 + ["validation"] * 40 + ["test"] * 40, dtype=object)  # (240,)
    panel = subspaces.TaxonomyPanel(tuple(f"Q{row}" for row in range(240)), ("MA",) * 240, tuple(lineages), split)
    taxonomy = subspaces.taxonomy_family(panel, dimensions=8)
    assert taxonomy.targets == 8 and taxonomy.pairs["test"].shape == (40 * 39 // 2,)
    messages: list[str] = []
    table = subspaces.run_e10({"concepts": tmp_path / "concepts", "panel": tmp_path / "panel"}, [family, taxonomy], (4,),
                              log=messages.append)
    assert set(table["features"]) == set(subspaces.FEATURES) and len(messages) == 2
    full = table[table["full"]].set_index(["features", "family"])
    assert (full.loc[(slice(None), "planted"), "test"] > 0.95).all()
    # Path lengths are not Euclidean, so even the scaling coordinates themselves correlate imperfectly with them.
    ceiling = stats.spearmanr(pdist(tree[split == "test"]), taxonomy.pairs["test"]).statistic
    assert (full.loc[(slice(None), "taxonomy"), "test"] > 0.9 * ceiling).all() and ceiling > 0.6
    assert set(table.loc[table["family"] == "taxonomy", "rank"]) == {1, 2, 4, 8}
