"""The survey's raw reruns staged into the archive's compacted layout read back through `overlay` exactly."""

from __future__ import annotations

import json
import numpy as np
import pandas as pd
import pytest

from pathlib import Path

from plm_interpretability import archive


def write_run(folder: Path, task: str, level: str, pair: bool = False) -> pd.DataFrame:
    """A finished task folder as Protify writes it: two probes, the full test split (resample 0) and seven halves."""
    folder.mkdir(parents=True)
    generator = np.random.default_rng(24895)
    rows = [{"task": task, "family": "full", "probe_name": f"resid_post:{layer}", "resample": resample, "plm": "trained",
             "probe": "trained", "control": "original", "score": float(generator.normal(0.5, 0.05))}
            for layer in (1, 2) for resample in range(8)]
    scores = pd.DataFrame(rows)
    scores.to_parquet(folder / "scores.parquet", index=False)
    probes = pd.DataFrame({"task": task, "family": "full", "probe_name": ["resid_post:1", "resid_post:2"], "best_step": [10, 12]})
    probes.to_parquet(folder / "training.parquet", index=False)
    probes[["task", "family", "probe_name"]].assign(validation_score=[0.4, 0.45], validation_loss=[0.6, 0.55]).to_parquet(
        folder / "validation.parquet", index=False)
    pd.DataFrame({"x": [1.0]}).to_parquet(folder / "elementwise.parquet", index=False)
    if pair:
        pd.DataFrame({"metric": ["roc_auc"], "estimate": [0.61]}).to_parquet(folder / "ranking.parquet", index=False)
        pd.DataFrame({"metric": ["roc_auc"], "low": [0.59], "high": [0.63]}).to_parquet(folder / "intervals.parquet", index=False)
    (folder / "run.json").write_text(json.dumps({"task": {"name": task, "level": level}}), encoding="utf-8")
    return scores


def test_staged_survey_reads_back_through_overlay(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    scores = write_run(raw / "run_onehot" / "results" / "linear_mean" / "go_cc", "go_cc", "protein")
    write_run(raw / "run_onehot" / "results" / "linear" / "ppi", "ppi", "pair", pair=True)
    (raw / "run_onehot" / "results" / "linear_mean" / "unfinished").mkdir()
    catalog = archive.stage_survey(raw, tmp_path / "survey")

    staged = tmp_path / "survey" / "runs" / "run_onehot"
    compact = pd.read_parquet(staged / "linear_mean" / "go_cc" / "scores.parquet").set_index("probe_name")
    for name, group in scores.groupby("probe_name"):
        assert compact.loc[name, "full"] == pytest.approx(group.loc[group["resample"] == 0, "score"].iloc[0], abs=1e-6)
        assert compact.loc[name, "halves_mean"] == pytest.approx(group.loc[group["resample"] > 0, "score"].mean(), abs=1e-6)
        assert compact.loc[name, "halves"] == 7
    probes = pd.read_parquet(staged / "linear_mean" / "go_cc" / "probes.parquet")
    assert probes["validation_score"].tolist() == [0.4, 0.45] and probes["best_step"].tolist() == [10, 12]
    assert sorted(path.name for path in (staged / "linear" / "ppi").iterdir()) == [
        "intervals.parquet", "probes.parquet", "ranking.parquet", "run.json", "scores.parquet"]
    assert not (staged / "linear_mean" / "unfinished").exists()
    assert sorted(item["path"] for item in catalog["omitted"]) == [
        "run_onehot/results/linear/ppi/elementwise.parquet", "run_onehot/results/linear_mean/go_cc/elementwise.parquet"]

    runs = tmp_path / "runs"
    (runs / "run_onehot" / "results").mkdir(parents=True)
    archive.overlay(tmp_path / "survey", runs)
    summary = archive.model_summary([runs / "run_onehot"], "linear_mean").set_index("probe_name")
    full = scores[scores["resample"] == 0].set_index("probe_name")["score"]
    np.testing.assert_allclose(summary.loc[full.index, "full"].to_numpy(), full.to_numpy(), atol=1e-6)
    np.testing.assert_allclose(summary.loc[["resid_post:1", "resid_post:2"], "validation_score"].to_numpy(), [0.4, 0.45])
    with pytest.raises(FileExistsError):
        archive.overlay(tmp_path / "survey", runs)  # a staged file never replaces one already there


def restored_task(folder: Path, sites: list[str], names: list[str]) -> None:
    """A restored task folder in the archive's compacted layout: one condition per probe and a run record of `sites`."""
    folder.mkdir(parents=True)
    keys = {"task": "topology", "family": "full", "probe_name": names}
    pd.DataFrame(keys | {"plm": "trained", "probe": "trained", "control": "original", "full": 0.5, "halves_mean": 0.5,
                         "halves_std": 0.01, "halves": 7}).to_parquet(folder / "scores.parquet", index=False)
    pd.DataFrame(keys | {"validation_score": 0.4, "validation_loss": 0.6}).to_parquet(folder / "probes.parquet", index=False)
    record = {"task": {"name": "topology", "level": "residue"}, "spec": {"sites": sites, "per_head": True}}
    (folder / "run.json").write_text(json.dumps(record), encoding="utf-8")


def test_merge_sites_joins_the_block_sites_to_the_stream_probes(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    stream, sites = runs / "run_6b_norm" / "results" / "linear" / "topology", runs / "run_6b_sites" / "results" / "linear" / "topology"
    restored_task(stream, ["embedding", "resid_post", "final_norm"], ["embedding:0", "resid_post:0", "final_norm:1"])
    restored_task(sites, ["q", "mlp_act"], ["q:0", "mlp_act:0"])
    added = archive.merge_sites(runs)

    assert added["probe_name"].tolist() == ["q:0", "mlp_act:0"] and set(added["root"]) == {"run_6b_norm"}
    assert not (runs / "run_6b_sites").exists()
    assert pd.read_parquet(stream / "scores.parquet")["probe_name"].tolist() == ["embedding:0", "resid_post:0", "final_norm:1", "q:0", "mlp_act:0"]
    assert len(pd.read_parquet(stream / "probes.parquet")) == 5
    record = json.loads((stream / "run.json").read_text(encoding="utf-8"))
    assert record["spec"]["sites"] == ["embedding", "q", "mlp_act", "resid_post", "final_norm"]  # in the sites' order
    assert record["merged_from"] == "run_6b_sites"

    restored_task(sites, ["resid_post"], ["resid_post:0"])  # a probe already in the target
    with pytest.raises(ValueError, match="resid_post:0"):
        archive.merge_sites(runs)


def test_merge_sites_joins_a_structure_roots_pair_tables(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    survey, structure = runs / "run_norm_s24896" / "results" / "linear" / "ppi2", runs / "run_norm_s24896_struct" / "results" / "linear" / "ppi2"
    restored_task(survey, ["embedding", "resid_post"], ["embedding:0", "resid_post:0"])
    restored_task(structure, ["structural"], ["structural:0"])
    for folder, names in ((survey, ["embedding:0", "resid_post:0"]), (structure, ["structural:0"])):
        pd.DataFrame({"task": "ppi2", "family": "full", "probe_name": names, "split": "test", "roc_auc": 0.6}).to_parquet(folder / "ranking.parquet", index=False)
    pd.DataFrame({"task": "ppi2", "family": "full", "probe_name": ["structural:0"]}).to_parquet(structure / "elementwise.parquet", index=False)
    added = archive.merge_sites(runs)

    assert added.to_dict("records") == [{"task": "topology", "family": "full", "probe_name": "structural:0", "root": "run_norm_s24896"}]
    assert pd.read_parquet(survey / "ranking.parquet")["probe_name"].tolist() == ["embedding:0", "resid_post:0", "structural:0"]
    assert not (survey / "elementwise.parquet").exists()  # a table the survey root never had is not joined
    assert json.loads((survey / "run.json").read_text(encoding="utf-8"))["spec"]["sites"] == ["embedding", "resid_post", "structural"]

    restored_task(structure, ["structural"], ["structural:1"])  # no ranking metrics, which the survey root has
    with pytest.raises(FileNotFoundError, match="ranking.parquet"):
        archive.merge_sites(runs)


def test_snapshot_resumes_after_the_rate_limit_and_raises_other_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def flaky(repo, **kwargs):
        calls.append(kwargs["allow_patterns"])
        if len(calls) < 3:
            raise RuntimeError("HTTP status client error (429 Too Many Requests)")
        return str(kwargs["local_dir"])

    monkeypatch.setattr(archive, "snapshot_download", flaky)
    assert archive.snapshot("repo", "rev", tmp_path, ["runs/*"], pause=0.0) == tmp_path
    assert calls == [["runs/*"]] * 3

    def broken(repo, **kwargs):
        calls.append(None)
        raise RuntimeError("404 Not Found")

    monkeypatch.setattr(archive, "snapshot_download", broken)
    with pytest.raises(RuntimeError, match="404"):
        archive.snapshot("repo", "rev", tmp_path, ["runs/*"], pause=0.0)
    assert calls[-2:] == [["runs/*"], None]  # one attempt, no retry


def test_prot_param_targets_are_compacted_for_full_width_probes(tmp_path: Path) -> None:
    folder = tmp_path / "raw" / "run_norm_s24896" / "results" / "linear_mean" / "prot_param"
    write_run(folder, "prot_param", "protein")
    rows = [{"task": "prot_param", "family": family, "probe_name": "resid_post:1", "label_index": target, "resample": resample,
             "score": 0.1 * target + 0.01 * resample} for family in ("full", "head") for target in range(2) for resample in range(8)]
    pd.DataFrame(rows).to_parquet(folder / "elementwise.parquet", index=False)
    catalog = archive.stage_survey(tmp_path / "raw", tmp_path / "survey")
    targets = pd.read_parquet(tmp_path / "survey" / "runs" / "run_norm_s24896" / "linear_mean" / "prot_param" / "elementwise.parquet")
    assert targets["family"].tolist() == ["full", "full"] and targets["label_index"].tolist() == [0, 1]
    np.testing.assert_allclose(targets["full"].to_numpy(), [0.0, 0.1], atol=1e-6)
    np.testing.assert_allclose(targets["halves_mean"].to_numpy(), [0.04, 0.14], atol=1e-6)
    assert not any(item["path"].endswith("elementwise.parquet") for item in catalog["omitted"])


def _summary(scores: list[float]) -> pd.DataFrame:
    rows = [{"task": "t", "family": "f", "probe_name": f"p{index}", "plm": "m", "probe": "linear", "control": "none",
             "mean": score, "std": 0.0, "full": score, "full_std": 0.0, "validation_score": score}
            for index, score in enumerate(scores)]
    return pd.DataFrame(rows)


def test_verify_refuses_a_score_missing_on_one_side_only() -> None:
    # A NaN difference used to drop out of the maximum, so a rebuilt summary of all-missing scores verified.
    reference = _summary([0.5, 0.7])

    assert archive.verify(_summary([0.5, 0.7]), reference) == 0.0
    assert archive.verify(_summary([0.5, np.nan]), _summary([0.5, np.nan])) == 0.0
    with pytest.raises(ValueError, match="missing"):
        archive.verify(_summary([np.nan, np.nan]), reference)
    with pytest.raises(ValueError, match="differs"):
        archive.verify(_summary([0.5, 0.8]), reference)
