"""The study's figures: panels draw what their tables hold, loaders read what the hypotheses read, and Figures 2 to 6
build from a run directory (CPU)."""

import json
import numpy as np
import pandas as pd
import pytest

from pathlib import Path
from PIL import Image

from plm_interpretability.units import experiments, figures, missing, steering
from plm_interpretability.units.dictionary import THRESHOLDS
from plm_interpretability.units.exemplars import POLE_NAMES


WIDTHS = {"esmc_300": (960, 2560), "esmc_600": (1152, 3072), "esmc_6b": (2560, 6912)}  # each model's d and f
TERMS = pd.DataFrame({"token": range(8), "label": [f"term {token}" for token in range(8)],
                      "aspect": ["local_active_site", "local_strand", "local_domain", "local_disorder", "go_mf",
                                 "go_bp", "interpro", "keyword"]})
LOCAL_TERMS = [0, 1, 2, 3, 8]  # the local terms and the intrinsic token
SITE_LABELS = ["native\ngate-tagged", "native\nsign-only", "random\ninit", "residual\nstream", "SAE"]


def _write(path: Path, table: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(path, index=False)


def _units(experiment: str, key: str) -> int:
    """A planned pair's unit count in the real run: 2f poles, 2d residual poles or the SAE's codebook."""
    d, f = WIDTHS[experiments.experiment_plans()[experiment].model]
    if "/sae:" in key:
        return int(key.rsplit("_", 1)[1])
    return 2 * d if "/residual@" in key else 2 * f


def synthetic_run(root: Path, *, shrink: int = 64, seed: int = 7) -> Path:
    """A run directory holding every table Figures 2 and 3 read, each basis with its real unit count over `shrink`."""
    generator = np.random.default_rng(seed)
    _write(root / "inputs" / "terms.parquet", TERMS)
    (root / "inputs" / "atlas_set.json").write_text(json.dumps({"intrinsic_tokens": {"hydrophobic stretch": 8}}),
                                                    encoding="utf-8")
    pairs = {(experiment, key) for _, experiment, key in experiments.SCALE_SITES}
    pairs |= {("e2_sweep", planned.key) for planned in experiments.experiment_plans()["e2_sweep"].plan}
    trained, _, matched = experiments.HYPOTHESIS_SITES["esmc_600"]
    for block in range(experiments.BLOCKS["esmc_600"]):  # the depth atlas
        pairs |= {(trained, f"block{block}/native@{matched}"), (trained, f"block{block}/rotation0@{matched}"),
                  (experiments.RANDOM_INIT_PASSES[trained], f"block{block}/native@{matched}")}
    for experiment, block, reference in experiments.HYPOTHESIS_SITES.values():
        keys = experiments.site_keys(block, reference)
        pairs.add((experiments.RANDOM_INIT_PASSES[experiment], keys.native))
        for key in (keys.native, keys.sign, keys.residual, keys.sae, *keys.rotated):
            pairs.add((experiment, key))
            count = max(40, _units(experiment, key) // shrink)
            before = generator.normal(0.72 if "/native@" in key else 0.66, 0.06, count)  # (a,)
            before[:3] = np.nan  # poles without a testable term
            _write(missing.table_path(root, experiment, key),
                   pd.DataFrame({"pole": np.arange(count), "auroc_before": before,
                                 "auroc_after": before + generator.normal(0.02, 0.01, count),
                                 "precision_before": before - 0.3}))
    for experiment, key in sorted(pairs):
        count = max(40, _units(experiment, key) // shrink)
        native = "/native@" in key or "/sign@" in key
        local = generator.choice([-1, *LOCAL_TERMS], count)  # (a,)
        _write(root / "passes" / experiment / "scores" / f"{experiments.stem(experiment, key)}.parquet", pd.DataFrame({
            "pole": np.arange(count), "best_term": generator.integers(4, 8, count),
            "margin": generator.normal(0.12 if native else 0.08, 0.04, count),
            "held_out_auroc": generator.normal(0.72 if native else 0.66, 0.06, count),
            "best_local_term": local, "dominant": (generator.random(count) < 0.3) & (local >= 0)}))  # as local_scores
    arms = [*figures.E1_ARMS, *(f"{figures.E1_ROTATED}{seed}" for seed in range(3))]
    for model, layers in (("esm2_8m", range(1, 7)), ("esm2_650m", (1, 9, 18, 24, 30, 33))):
        _write(root / "retest" / model / "e1_summary.parquet", pd.DataFrame(
            [{"model": model, "layer": layer, "arm": arm, "share": float(generator.uniform(0, 0.3))} for layer in layers
             for arm in arms]))
    for model, (plan, _) in experiments.concept_plans().items():
        _write(root / "concepts" / model / "e6_rotation_summary.parquet", pd.DataFrame(
            [{"block": block, "features": features, "k": k, "native": 0.6 + 0.03 * np.log2(k),
              "best_rotation": 0.56 + 0.02 * np.log2(k), "rotation_range": 0.03, "rank_p": 1 / 11, "privileged": True}
             for block in plan.depths for features in ("mean", "poles") for k in (1, 2, 4, 8, 16)]))
    decisions = [
        {"hypothesis": "H4", "site": "esmc_600", "taken": True, "passed": False, "details": {
            "site": {"tested": True, "difference": {"estimate": 0.04, "low": 0.02, "high": 0.06}, "trained_poles": 50,
                     "random_poles": 40},
            "function": {"tested": False, "trained_poles": 5, "random_poles": 2}}},
        {"hypothesis": "H4", "site": "esmc_6b", "taken": False, "rejected_matches": ["block59/native@esmc_6b_layer60_k64_16384"]},
    ]
    (root / "decisions.json").write_text(json.dumps(decisions), encoding="utf-8")
    _causal_outputs(root, generator)
    _beyond_unit_outputs(root, generator)
    return root


def _json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _causal_outputs(root: Path, generator: np.random.Generator, poles: int = 60) -> None:
    """E7's tables as `ablation.run_h6`, `ablation.weak_strong` and the steering stage write them, and E9's."""
    statuses = ["tested"] * (poles - 6) + ["silent"] * 3 + ["too_few"] * 3
    rows = []
    for pole, status in enumerate(statuses):
        entry = {"pole": pole, "term": int(generator.integers(0, 4)), "proteins": 8, "status": status}
        if status == "tested":
            entry.update(drop=float(generator.normal(0.05, 0.02)), placebo_drops=list(generator.normal(0.01, 0.01, 10)),
                         outside_drop=None if pole % 9 == 0 else float(generator.normal(0.005, 0.004)))
        rows.append(entry)
    _write(root / "causal" / "h6.parquet", pd.DataFrame(rows))
    _json(root / "causal" / "weak_strong.json", {
        "weakest": 0.75, "proteins": 100, "removed_share": {"weak": 0.75, "strong": 0.07},
        "readout": {"intact": {"loss": 2.1, "accuracy": 0.38}, "weak": {"loss": 2.15, "accuracy": 0.37},
                    "strong": {"loss": 2.9, "accuracy": 0.2}}})
    pairs = [{"start": start, "end": end, "arm": arm, "residues": 64,
              "energy": float(abs(end - start) * {"manifold": 0.01, "linear": 0.03, "random": 0.05}[arm] + 0.02),
              "tracking": 0.9, "end_hydropathy": 0.0, "target_hydropathy": 0.0}
             for start, end in steering.steering_plan() for arm in steering.ARMS]
    _write(root / "causal" / "steering" / "steering.parquet", pd.DataFrame(pairs))
    _json(root / "causal" / "steering" / "receipt.json", {"summary": {
        "natural_energy": 0.02, "isometry": {"geodesic_r": 0.93, "straight_r": 0.71, "pairs": 45}}})
    targets = 40
    null = generator.uniform(0.01, 0.1, targets)  # (t,)
    _write(root / "concepts" / experiments.CAUSAL_MODEL / "e9_attribution.parquet", pd.DataFrame({
        "task": "go", "target": [f"GO:{index:07d}" for index in range(targets)], "accession": "GO", "delta": 1.0,
        "neuron_share": 0.5, "labeled_neurons": 4, "labeled_share": np.where(np.arange(targets) < 3, np.nan, null + 0.03),
        "null_mean": null, "null_low": null - 0.02, "null_high": null + 0.02, "null_rank": 0.1}))


def _beyond_unit_outputs(root: Path, generator: np.random.Generator) -> None:
    """E8's receipts as the dictionary stage writes them, and E10's and E11's tables."""
    for model, site in experiments.dictionary_sites().items():
        _json(root / "dictionary" / model / "receipt.json", {
            "dictionaries": {name: {"native_shares": {str(threshold): 0.6 - 0.2 * index for index, threshold in enumerate(THRESHOLDS)},
                                    "rotated_shares": {str(threshold): 0.1 / (index + 1) for index, threshold in enumerate(THRESHOLDS)}}
                             for name in site.saes},
            "rotation_search": {"residues": 1000, "native_objective": 9.0, "searches": [
                {"seed": seed, "start_recovery": 0.08, "recovery": 0.6 + 0.1 * index, "start_objective": 4.0,
                 "objective": 7.0 + index, "steps": 300} for index, seed in enumerate((24895, 24896, 24897))]}})
    families = {"composition": 20, "physicochemistry": 9, "length": 10, "localization": 10, "taxonomy": 32}
    for model, (plan, _) in experiments.concept_plans().items():
        rows = [{"family": family, "metric": "r2", "targets": targets, "rank": rank, "full": rank == targets, "validation": 0.5,
                 "test": 0.5, "penalty": 1.0, "dimension": 2 + depth, "stable_rank": 1.5 + depth, "block": block,
                 "features": features}
                for family, targets in families.items() for depth, block in enumerate(plan.depths)
                for features in ("z_mean", "stream_mean") for rank in (1, targets)]
        _write(root / "concepts" / model / "e10_subspaces.parquet", pd.DataFrame(rows))
        prints = [("extremes", "native"), ("extremes", "rotation0"), ("extremes", "rotation1"), ("mean", "native"),
                  ("mean", "rotation0"), ("sae", "native")]
        rows = [{"task": "go", "target": f"t{target}", "kind": "binary", "features": features, "basis": basis,
                 "pr_auc": float(generator.uniform(0.3, 0.8)), "roc_auc": 0.7, "balanced_mcc": 0.3}
                for target in range(25) for features, basis in prints]
        _write(root / "concepts" / model / "e11_scores.parquet", pd.DataFrame(rows).assign(block=plan.rotation_block))


def _axes():
    figure = figures.new_figure(2.0, 3.0)
    return figure, figure.add_subplot()


def test_basis_panel_draws_each_median_and_the_rotation_band() -> None:
    generator = np.random.default_rng(0)
    native, sae = generator.normal(0.7, 0.05, 400), generator.normal(0.65, 0.05, 300)  # (a,), (b,)
    corrected = native + 0.02  # (a,)
    figure, ax = _axes()
    groups = [figures.BasisGroup("native", native, figures.NATIVE, after=corrected),
              figures.BasisGroup("SAE", sae, figures.SAE)]
    figures.basis_panel(ax, groups, ylabel="held-out AUROC", band=(0.55, 0.6))
    medians = [container.lines[0].get_ydata()[0] for container in ax.containers]
    np.testing.assert_allclose(medians, [np.median(native), np.median(corrected), np.median(sae)])
    positions = [container.lines[0].get_xdata()[0] for container in ax.containers]
    assert positions == [0, 0.3, 1]  # the corrected median sits beside its basis
    band = ax.patches[0]
    assert band.get_y() == pytest.approx(0.55) and band.get_height() == pytest.approx(0.05)
    assert [label.get_text() for label in ax.get_xticklabels()] == ["native", "SAE"]


def test_track_panel_draws_the_own_pole_above_the_rest() -> None:
    position = np.arange(1, 11)
    track = pd.DataFrame({"position": position, "own": "negative", "threshold": 0.4,
                          "in_term": [False, True, True, False, False, True, True, True, False, False],
                          "positive": np.linspace(0, 1, 10), "negative": np.linspace(1, 0, 10),
                          "leak_positive": np.zeros(10), "leak_negative": np.full(10, 0.05)})
    figure, ax = _axes()
    figures.track_panel(ax, track.sample(frac=1, random_state=0), ymax=1.2)  # rows in any order
    own = max(ax.lines, key=lambda line: line.get_zorder())
    np.testing.assert_array_equal(own.get_ydata(), track["negative"])
    assert own.get_color() == figures.NATIVE
    shaded = [patch for patch in ax.patches]
    assert [(patch.get_x(), patch.get_width()) for patch in shaded] == [(1.5, 2.0), (5.5, 3.0)]  # two runs of the term
    assert figures.LEAK in [line.get_color() for line in ax.lines]
    figure, ax = _axes()
    figures.track_panel(ax, track, ymax=1.2, leaks=False)
    assert figures.LEAK not in [line.get_color() for line in ax.lines]  # the closed gate's output is left out


def _run(root, exemplars: int = 2) -> None:
    rows = []
    generator = np.random.default_rng(1)
    for exemplar in range(exemplars):
        for role in figures.CARRIER_ROLES:
            length = int(generator.integers(20, 40))
            poles = np.zeros((length, 4))
            poles[np.arange(length), generator.integers(0, 4, length)] = generator.random(length)
            rows.append(pd.DataFrame({"exemplar": exemplar, "kind": "site", "pole": 7 + exemplar, "term": 3, "own": "positive",
                                      "accession": f"P{exemplar}{role}", "role": role, "position": np.arange(1, length + 1),
                                      "residue": "A", **{name: poles[:, index] for index, name in enumerate(POLE_NAMES)},
                                      "in_term": np.arange(length) % 7 < 2, "threshold": 0.3}))
    (root / "exemplars").mkdir(parents=True)
    pd.concat(rows, ignore_index=True).to_parquet(root / "exemplars" / "tracks.parquet", index=False)
    (root / "causal" / "near_misses").mkdir(parents=True)
    summary = {"labeled_auroc": {"estimate": 0.71, "low": 0.62, "high": 0.79},
               "placebo_auroc": {"estimate": 0.52, "low": 0.45, "high": 0.6}}
    (root / "causal" / "near_misses" / "receipt.json").write_text(json.dumps({"summary": summary}), encoding="utf-8")
    (root / "inputs").mkdir(parents=True)
    pd.DataFrame({"token": [3], "label": ["Zinc binding at a very long site name past the cut"]}).to_parquet(
        root / "inputs" / "terms.parquet", index=False)


def test_figure_4_builds_from_a_run_and_saves_at_300_dpi(tmp_path) -> None:
    _run(tmp_path / "run")
    figure = figures.figure_4(tmp_path / "run")
    assert len(figure.axes) == 2 * len(figures.CARRIER_ROLES) + 2  # the tracks, panel B and the key
    labels = [ax.get_ylabel() for ax in figure.axes if ax.get_ylabel()]
    assert labels[0].startswith("site\nZinc binding") and labels[0].endswith("…")
    near = figure.axes[-2]
    np.testing.assert_allclose([container.lines[0].get_xdata()[0] for container in near.containers], [0.71, 0.52])
    path = figures.save_figure(figure, tmp_path / "figure_4.png")
    with Image.open(path) as image:
        assert image.info["dpi"] == pytest.approx((300, 300), abs=0.01)
        assert image.size[0] == pytest.approx(figures.WIDTH * 300, abs=2)


def test_basis_groups_read_the_site_and_band_the_rotation_medians(tmp_path) -> None:
    root = synthetic_run(tmp_path / "run")
    tables = figures.site_tables(root, "esmc_600")
    groups, band = figures.basis_groups(tables, "margin")
    medians = [np.median(table["margin"]) for table in tables.rotated]
    assert band == (min(medians), max(medians))  # the band H2 asks the native median to clear
    assert [group.label for group in groups] == SITE_LABELS
    np.testing.assert_array_equal(groups[0].values, tables.native["margin"])
    control = experiments.score_table(root, "e5_600", experiments.site_keys(26, experiments.sweep_name(64, 8192)).native)
    np.testing.assert_array_equal(groups[2].values, control["margin"])  # the random-init pass, at the same pair
    assert groups[2].marker == "s" and groups[1].hollow


def test_inheritance_groups_pair_each_basis_with_its_corrected_values(tmp_path) -> None:
    root = synthetic_run(tmp_path / "run")
    groups = figures.inheritance_groups(root, "esmc_6b")
    keys = experiments.site_keys(59, "esmc_6b_layer60_k64_16384")
    rotated = [pd.read_parquet(missing.table_path(root, "e3", key)) for key in keys.rotated]
    assert groups[2].medians == tuple(float(np.nanmedian(table["auroc_before"])) for table in rotated)
    assert groups[2].after == tuple(float(np.nanmedian(table["auroc_after"])) for table in rotated)
    native = pd.read_parquet(missing.table_path(root, "e3", keys.native))
    np.testing.assert_array_equal(groups[0].after, native["auroc_after"])
    figure, ax = _axes()
    figures.basis_panel(ax, groups, ylabel="held-out AUROC")
    assert len(ax.containers) == 2 * 4  # every single basis before and after; the rotations draw ranges


def test_dominant_shares_count_each_kind_over_all_units() -> None:
    table = pd.DataFrame({"best_local_term": [0, 0, 1, -1, 2, 8], "dominant": [True, False, True, False, True, True]})
    kinds = {0: "site", 1: "structure", 2: "domain", 8: "composition"}
    shares = figures.dominant_shares({"native": [table], "rotation": [table, table.assign(dominant=False)]}, kinds)
    native = shares[shares["basis"] == "native"].set_index("kind")["share"]
    assert native.to_dict() == pytest.approx({"site": 1 / 6, "structure": 1 / 6, "domain": 1 / 6, "composition": 1 / 6})
    assert sorted(shares.loc[shares["basis"] == "rotation", "copy"].unique()) == [0, 1]
    assert set(shares["kind"]) == {"site", "structure", "domain", "composition"}  # kinds no basis has are left out
    with pytest.raises(ValueError, match="no concept kind"):
        figures.dominant_shares({"native": [table]}, {0: "site"})


def test_sweep_medians_name_every_member_at_its_unit_count(tmp_path) -> None:
    root = synthetic_run(tmp_path / "run")
    medians = figures.sweep_medians(root)
    assert len(medians) == 2 * len(experiments.SWEEP_PASS_K) * len(experiments.SWEEP_PASS_CODEBOOKS)
    sae = medians[medians["basis"] == "sae"]
    assert set(zip(sae["k"], sae["codebook"], strict=True)) == {
        (k, codebook) for k in experiments.SWEEP_PASS_K for codebook in experiments.SWEEP_PASS_CODEBOOKS}
    assert (sae["units"] == sae["codebook"] // 64).all()
    assert (medians.loc[medians["basis"] == "native", "units"] == 6144 // 64).all()
    assert (medians["low"] <= medians["estimate"]).all() and (medians["estimate"] <= medians["high"]).all()


def test_figures_2_and_3_build_from_a_run(tmp_path) -> None:
    root = synthetic_run(tmp_path / "run")
    figure = figures.figure_2(root)
    assert len(figure.axes) == 1 + 4 + 1 + 2  # A, B's four, C and D's two models
    assert [text.get_text() for text in figure.axes[0].get_legend().get_texts()][-1] == "rotated intermediates"
    path = figures.save_figure(figure, tmp_path / "figure_2.png")
    with Image.open(path) as image:
        assert image.info["dpi"] == pytest.approx((300, 300), abs=0.01)
    figure = figures.figure_3(root)
    assert len(figure.axes) == 2 + 2 + 1 + 1
    pretraining = figure.axes[-1]
    assert [label.get_text() for label in pretraining.get_yticklabels()] == ["function", "site"]
    assert any(text.get_text().strip() == "too few poles" for text in pretraining.texts)
    assert [text.get_text() for text in pretraining.get_legend().get_texts()] == ["ESMC-600", "ESMC-6B, not taken"]
    figures.save_figure(figure, tmp_path / "figure_3.png")


def test_ablation_table_takes_each_tested_poles_excess(tmp_path) -> None:
    root = synthetic_run(tmp_path / "run")
    table = figures.ablation_table(root)
    tested = table[table["status"] == "tested"]
    np.testing.assert_allclose(tested["excess"], tested["drop"] - tested["placebo_drops"].map(np.mean))
    assert table.loc[table["status"] != "tested", "excess"].isna().all()
    assert set(figures.STEERING_STYLES) == set(steering.ARMS)


def test_figures_5_and_6_build_from_a_run(tmp_path) -> None:
    root = synthetic_run(tmp_path / "run")
    figure = figures.figure_5(root)
    assert len(figure.axes) == 1 + 2 + 1 + 1  # A, B's loss and accuracy, C and D
    ablation, loss, accuracy, steered, probes = figure.axes
    assert ablation.get_legend().get_texts()[0].get_text() == "54 of 60 labeled poles tested"
    assert [label.get_text() for label in loss.get_yticklabels()][1] == "weakest 75%\nremoved"
    np.testing.assert_allclose(accuracy.get_lines()[0].get_xdata(), [0.38, 0.37, 0.2])
    energies = {line.get_color(): line.get_ydata() for line in steered.get_lines() if len(line.get_ydata()) > 2}
    np.testing.assert_allclose(energies[figures.STEERING_STYLES["linear"][1]], 0.02 + 0.03 * np.arange(1, 10))
    assert probes.get_legend().get_texts()[0].get_text() == "above the null's 95% interval (37 of 37)"
    figures.save_figure(figure, tmp_path / "figure_5.png")
    figure = figures.figure_6(root)
    assert len(figure.axes) == 4 + 5 + 1  # A and B at two sites, C's five families, D
    copies = figure.axes[0]
    assert [line.get_ydata()[0] for line in copies.get_lines()][:2] == pytest.approx([60.0, 10.0])
    payoff_axes = figure.axes[-1]
    assert [label.get_text() for label in payoff_axes.get_xticklabels()][0] == "maxima and minima,\nnative − rotated"
    figures.save_figure(figure, tmp_path / "figure_6.png")


def test_depth_atlas_reads_every_block_of_each_basis(tmp_path) -> None:
    root = synthetic_run(tmp_path / "run")
    atlas = figures.depth_atlas(root, "margin")
    assert len(atlas) == 3 * experiments.BLOCKS["esmc_600"]
    control = experiments.score_table(root, "e5_600", "block3/native@esmc_600_layer27_k64_8192")["margin"]
    assert atlas.query("block == 3 and basis == 'random init'")["estimate"].item() == pytest.approx(np.median(control))
    figure = figures.FIGURES["depth_atlas"](root)
    assert len(figure.axes) == 2
    assert [text.get_text() for text in figure.axes[0].get_legend().get_texts()] == [
        "native poles", "rotated poles (seed 0)", "randomly initialized model"]
    figures.save_figure(figure, tmp_path / "figure_depth_atlas.png")


RETEST_SAE_BLOCKS = {"esmc_600_layer27_k64_8192": 26, "esmc_600_layer27_k64_16384": 26, "esmc_6b_layer60_k64_16384": 59,
                     "esmc_6b_layer60_k64_65536": 59, "esmc_300_layer23_k64_16384": 22, "esmc_600_mlp_k64_131072": 26,
                     "esmc_6b_mlp_k64_131072": 59}  # the preregistered SAEs E13 reads, by the block each reads


def _residue_run(root: Path) -> None:
    """E13's and E13x's summaries for every plan, each arm's concepts set by its name and block so readings stay apart."""
    blocks_of = {**RETEST_SAE_BLOCKS, **{name: spec.block for name, spec in experiments.depth_sae_specs().items()}}
    for name, plan in experiments.esmc_retest_plans().items():
        seeds = (0, 1, 2) if plan.rotation_seeds is None else plan.rotation_seeds
        arms = list(plan.arms or ("residual", "residual_poles", "mlp_native", "mlp_poles", *(f"mlp_rotation{seed}" for seed in seeds),
                                  *(("shuffled_mlp_poles",) if plan.shuffled else ())))
        rows = []
        for block in plan.blocks:
            for arm in arms + [f"sae:{sae}" for sae in plan.saes if blocks_of[sae] == block]:
                concepts = {"mlp_native": 200, "mlp_poles": 190, "residual": 5}.get(arm, 300 if arm.startswith("sae:") else 50)
                if arm.startswith("mlp_rotation"):
                    concepts = 40 + int(arm.removeprefix("mlp_rotation"))
                rows.append({"layer": block, "arm": arm, "identified_concepts": concepts + block, "associated_features": 2 * concepts,
                             "features": 1000, "share": 0.1, "mean_best_test_f1": 0.5, "model": name})
        _write(root / "retest_esmc" / name / "e13_summary.parquet", pd.DataFrame(rows))


def test_residue_figure_reads_every_plan_and_site(tmp_path) -> None:
    root = tmp_path / "run"
    _residue_run(root)
    summary = figures.residue_summary(root)
    assert set(summary["plan"]) == set(experiments.esmc_retest_plans())
    sites = figures.residue_sites(summary)
    assert list(sites) == ["ESMC-300\nblock 22", "ESMC-600\nblock 26", "ESMC-6B\nblock 59"]
    site = sites["ESMC-600\nblock 26"]
    assert site["mlp_native"] == [226.0] and site["rotations"] == [66.0 + seed for seed in range(10)]
    assert [len(sites[name]["rotations"]) for name in sites] == [3, 10, 10]
    assert site["searched"] == [76.0] * 3 and [len(sites[name]["searched"]) for name in sites] == [0, 3, 3]
    assert [len(sites[name]["stream_sae"]) for name in sites] == [1, 2, 2]
    assert [len(sites[name]["write_sae"]) for name in sites] == [0, 1, 1]
    figure = figures.FIGURES["residue"](root)
    depth_600, depth_6b, _ = figure.axes
    assert [len(line.get_xdata()) for line in depth_600.get_lines() if len(line.get_xdata()) > 2] == [36] * 5
    assert [len(line.get_xdata()) for line in depth_6b.get_lines() if len(line.get_xdata()) > 2] == [20] * 5
    sae_line = [line for line in depth_600.get_lines() if line.get_label() == "each layer's SAE on the stream"][0]
    np.testing.assert_array_equal(sae_line.get_ydata(), 300 + np.arange(36))
    with pytest.raises(ValueError, match="have not run"):
        figures.residue_sites(summary[summary["plan"] != "esmc_600_mlp"])
    path = figures.save_figure(figure, tmp_path / "figure_residue.png")
    with Image.open(path) as image:
        assert image.info["dpi"] == pytest.approx((300, 300), abs=0.01)


def test_metric_figure_reads_both_protein_metrics_and_the_residue_counts(tmp_path) -> None:
    root = synthetic_run(tmp_path / "run")
    _residue_run(root)
    keys = experiments.site_keys(26, "esmc_600_layer27_k64_8192")
    native = pd.read_parquet(missing.table_path(root, "e2", keys.native))
    for metric in figures.PROTEIN_METRICS:
        groups = figures.metric_groups(root, "esmc_600", metric)
        assert [group.label for group in groups] == list(figures.METRIC_BASES)
        np.testing.assert_array_equal(groups[0].values, native[metric])
        rotated = [pd.read_parquet(missing.table_path(root, "e2", key)) for key in keys.rotated]
        assert groups[1].medians == tuple(float(np.nanmedian(table[metric])) for table in rotated)
    units = figures.scored_units(root, "esmc_600")
    scored = f"{len(native) - 3:,}"  # three poles of every basis have no testable term
    assert units["neuron\npoles"] == scored
    concepts = figures.residue_concepts(figures.residue_summary(root), "esmc_600")
    assert concepts["neuron\npoles"] == [226.0] and concepts["stream\npoles"] == [76.0] and concepts["SAE\nlatents"] == [326.0]
    assert concepts["ten\nrotations"] == [66.0 + seed for seed in range(10)]
    figure = figures.FIGURES["metric"](root)
    assert len(figure.axes) == 6
    assert [text.get_text() for text in figure.axes[0].texts][0] == scored + "\nunits"


def test_save_figure_refuses_a_title_and_other_formats(tmp_path) -> None:
    figure, _ = _axes()
    with pytest.raises(ValueError, match="PNG"):
        figures.save_figure(figure, tmp_path / "figure.pdf")
    figure.suptitle("a title")
    with pytest.raises(ValueError, match="no title"):
        figures.save_figure(figure, tmp_path / "figure.png")
