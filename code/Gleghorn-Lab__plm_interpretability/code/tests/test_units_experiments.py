from __future__ import annotations

import pandas as pd
import pytest

from plm_interpretability.units import experiments


SAES = {
    "esmc_6b_layer60_k64_16384": {"repo": "biohub/ESMC-6B-sae-layer60-k64-codebook16384", "revision": "a" * 40, "block": 59},
    "esmc_6b_mlp_k64_131072": {"repo": "biohub/ESMC-6B-sae-mlp-k64-codebook131072", "revision": "b" * 40, "block": 59},
    "esmc_600_layer27_sweep": {"repo_pattern": "biohub/ESMC-600M-sae-layer27-k{k}-codebook{codebook}",
                               "k": [16, 64], "codebook": [8192, 16384], "block": 26},
    "interplm_esm2_8m": {"repo": "Elana/InterPLM-esm2-8m", "revision": "c" * 40, "layers": [1, 2]},
}


def test_sae_specs_read_the_preregistration_layout() -> None:
    specs = experiments.sae_specs(SAES, {"esmc_600_layer27_k64_8192": "d" * 40})
    residual = specs["esmc_6b_layer60_k64_16384"]
    assert (residual.layer, residual.block, residual.reads) == (60, 59, "stream")
    mlp = specs["esmc_6b_mlp_k64_131072"]
    assert (mlp.layer, mlp.block, mlp.reads) == (60, 59, "write")  # shard 60 holds block 59's write, as E0 found
    member = specs["esmc_600_layer27_k64_8192"]
    assert member.repo == "biohub/ESMC-600M-sae-layer27-k64-codebook8192" and member.revision == "d" * 40
    assert specs["esmc_600_layer27_k16_8192"].revision is None
    assert not any(name.startswith("interplm") for name in specs)
    assert len([name for name in specs if name.startswith("esmc_600_layer27")]) == 4


def test_dictionary_sites_name_preregistered_saes_at_their_block() -> None:
    names = {
        "esmc_6b_layer60_k64_16384": {"repo": "r", "revision": "a" * 40, "block": 59},
        "esmc_6b_layer60_k64_65536": {"repo": "r", "revision": "a" * 40, "block": 59},
        "esmc_6b_mlp_k64_131072": {"repo": "r", "revision": "a" * 40, "block": 59},
        "esmc_600_mlp_k64_131072": {"repo": "r", "revision": "a" * 40, "block": 26},
        "esmc_600_layer27_sweep": {"repo_pattern": "p{k}{codebook}", "k": [64], "codebook": [8192, 16384], "block": 26},
    }
    specs = experiments.sae_specs(names)
    for model, site in experiments.dictionary_sites().items():
        assert site.model == model
        assert all(specs[name].block == site.block for name in site.saes)
        assert [specs[name].reads for name in site.saes] == ["write", "stream", "stream"]


def test_esmc_retest_plans_read_their_models_saes_at_their_block() -> None:
    names = {
        "esmc_300_layer23_k64_16384": {"repo": "r", "revision": "a" * 40, "block": 22},
        "esmc_6b_layer60_k64_16384": {"repo": "r", "revision": "a" * 40, "block": 59},
        "esmc_6b_layer60_k64_65536": {"repo": "r", "revision": "a" * 40, "block": 59},
        "esmc_6b_mlp_k64_131072": {"repo": "r", "revision": "a" * 40, "block": 59},
        "esmc_600_mlp_k64_131072": {"repo": "r", "revision": "a" * 40, "block": 26},
        "esmc_600_layer27_sweep": {"repo_pattern": "p{k}{codebook}", "k": [64], "codebook": [8192, 16384], "block": 26},
    }
    specs = {**experiments.sae_specs(names), **experiments.depth_sae_specs()}
    plans = experiments.esmc_retest_plans()
    assert all(plans[model].model == model for model in ("esmc_300", "esmc_600", "esmc_6b"))
    for name, plan in plans.items():
        assert all(0 <= block < experiments.BLOCKS[plan.model] for block in plan.blocks), name
        assert all(sae.startswith(f"{plan.model}_") and specs[sae].block in plan.blocks for sae in plan.saes), name
    assert {specs[sae].block for sae in plans["esmc_600"].saes} == {26} and {specs[sae].block for sae in plans["esmc_6b"].saes} == {59}
    assert plans["esmc_600_depth"].blocks == tuple(range(36))
    halves = plans["esmc_6b_depth_a"].blocks + plans["esmc_6b_depth_b"].blocks
    assert len(halves) == 20 == len(set(halves)) and {19, 39, 59, 79} <= set(halves)
    assert all(len(plans[name].rotation_seeds) == 10 for name in ("esmc_600_rotations", "esmc_6b_rotations"))
    assert [specs[sae].reads for name in ("esmc_600_mlp", "esmc_6b_mlp") for sae in plans[name].saes] == ["write", "write"]
    assert all(specs[sae].reads == "stream" for name in ("esmc_300", "esmc_600", "esmc_6b") for sae in plans[name].saes)
    for name, blocks in (("esmc_600_depth_sae", tuple(range(36))), ("esmc_6b_depth_sae", tuple(sorted(halves)))):
        plan = plans[name]
        assert plan.blocks == blocks and [specs[sae].block for sae in plan.saes] == list(blocks) and plan.arms == ("residual",)
        assert all(specs[sae].layer == specs[sae].block + 1 and specs[sae].reads == "stream" and len(specs[sae].revision) == 40
                   for sae in plan.saes)
    assert len(experiments.depth_sae_specs()) == 36 + 80
    sites = experiments.dictionary_sites()
    for name in ("esmc_600_search", "esmc_6b_search"):  # E13s: E8's block, its three searches' starts and landings
        plan = plans[name]
        assert plan.searched and plan.blocks == (sites[plan.model].block,) and not plan.saes and plan.rotation_seeds == (0,)
        assert {arm for arm in plan.arms if arm.startswith(("mlp_start", "mlp_searched"))} == {
            f"mlp_{kind}{seed}" for kind in ("start", "searched") for seed in (24895, 24896, 24897)}
        assert "mlp_standard" in plan.arms and "mlp_poles" in plan.arms
    assert not any(plan.searched for name, plan in plans.items() if not name.endswith("_search"))


def test_plans_are_unique_and_name_their_saes() -> None:
    plans = experiments.experiment_plans()
    assert set(plans) == {"e2", "e2_sweep", "e3", "e4", "e5_600", "e5_6b"}
    for plan in plans.values():
        keys = [planned.key for planned in plan.plan]
        assert len(keys) == len(set(keys)), plan.name
        blocks = experiments.BLOCKS[plan.model]
        assert all(0 <= planned.basis.block < blocks for planned in plan.plan), plan.name
    e2 = plans["e2"]
    assert {planned.basis.block for planned in e2.plan} == set(range(36))
    assert e2.references == ("esmc_600_layer27_k64_16384", "esmc_600_layer27_k64_8192")
    rotations_26 = [planned for planned in e2.plan if planned.basis.block == 26 and planned.basis.kind == "rotation"]
    assert sorted(planned.basis.seed for planned in rotations_26) == list(range(10))
    labelled = [planned.key for planned in e2.plan if planned.profile == "selection"]
    assert "block26/native@esmc_600_layer27_k64_8192" in labelled and len(labelled) == 3
    e3 = plans["e3"]
    assert "esmc_6b_mlp_k64_131072" in e3.saes
    assert any(planned.basis.reads == "write" for planned in e3.plan)
    assert plans["e5_600"].random_init and plans["e5_600"].rates_from == "e2" and plans["e5_600"].proteins == 30_000
    assert len(plans["e2_sweep"].references) == 9


def test_hypothesis_sites_name_planned_pairs_and_read_their_tables(tmp_path) -> None:
    plans = experiments.experiment_plans()
    assert experiments.HYPOTHESIS_SITES["esmc_600"][2] == experiments.sweep_name(64, 8192)
    for experiment, block, reference in experiments.HYPOTHESIS_SITES.values():
        keys = experiments.site_keys(block, reference)
        planned = {item.key for item in plans[experiment].plan}
        assert {keys.native, keys.sign, keys.residual, keys.sae, *keys.rotated} <= planned
        assert len(keys.rotated) == len(experiments.ROTATION_SEEDS)
        control = plans[experiments.RANDOM_INIT_PASSES[experiment]]
        assert control.random_init and control.rates_from == experiment
        assert keys.native in {item.key for item in control.plan}  # the control is read at the same pair
    assert [model for model, _, _ in experiments.SCALE_SITES] == ["esmc_300", "esmc_600", "esmc_6b"]
    for model, experiment, key in experiments.SCALE_SITES:
        assert plans[experiment].model == model and key in {item.key for item in plans[experiment].plan}
        assert key.endswith("_k64_16384")  # one rate distribution across scale
    key = experiments.site_keys(26, experiments.sweep_name(64, 8192)).sae
    folder = tmp_path / "passes" / "e2" / "scores"
    folder.mkdir(parents=True)
    pd.DataFrame({"pole": [0, 1]}).to_parquet(folder / f"{experiments.stem('e2', key)}.parquet", index=False)
    assert experiments.score_table(tmp_path, "e2", key)["pole"].tolist() == [0, 1]
    with pytest.raises(KeyError, match="plans no pair"):
        experiments.stem("e4", key)
