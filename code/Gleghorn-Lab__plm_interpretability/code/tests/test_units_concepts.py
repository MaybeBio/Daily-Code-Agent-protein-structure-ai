from __future__ import annotations

import json
import numpy as np
import pandas as pd
import pytest
import torch

from collections.abc import Callable, Iterator
from pathlib import Path
from torch import nn

from plm_interpretability.units import atlas, bases, concepts, intrinsic
from plm_interpretability.units.poles import swiglu_poles
from plm_interpretability.units.rotations import haar_rotation


CPU = torch.device("cpu")


def _sequences(n: int, seed: int) -> list[str]:
    rng = np.random.default_rng(seed)
    return ["".join(rng.choice(list(intrinsic.AMINO_ACIDS), size=int(rng.integers(20, 45)))) for _ in range(n)]


def _write_task(root: Path, name: str, level: str, kind: str, labels: list[str], frames: dict[str, pd.DataFrame]) -> None:
    folder = root / name
    folder.mkdir(parents=True)
    metadata = {"config": name, "task_level": level, "task_type": kind, "num_labels": len(labels), "label_names": labels}
    (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    for split, frame in frames.items():
        frame.to_parquet(folder / f"{split}.parquet", index=False)


@pytest.fixture(scope="module")
def task_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("concepts")
    shared = _sequences(12, 0)
    binary = {split: pd.DataFrame({"id": [f"{split}{index}" for index in range(4)], "sequence": shared[start:start + 4],
                                   "label": [0, 1, 0, 1]})
              for split, start in (("train", 0), ("validation", 4), ("test", 8))}
    extra = _sequences(3, 1)
    multilabel = {split: pd.DataFrame({"id": ["a", "b"], "sequence": [shared[start], extra[index]],
                                       "label": [np.array([1, 0, 1], dtype=np.int8), np.array([0, 1, 0], dtype=np.int8)]})
                  for index, (split, start) in enumerate((("train", 0), ("validation", 5), ("test", 9)))}
    residue = {split: pd.DataFrame({"id": ["r"], "sequence": [shared[0]], "label": [np.zeros(len(shared[0]), dtype=np.int16)]})
               for split in concepts.SPLITS}
    _write_task(root, "binary_task", "protein", "binary", ["positive"], binary)
    _write_task(root, "multilabel_task", "protein", "multilabel", ["x", "y", "z"], multilabel)
    _write_task(root, "residue_task", "residue", "multiclass", ["a", "b"], residue)
    return root


def test_tasks_and_their_distinct_proteins(task_root: Path) -> None:
    tasks = concepts.load_tasks(task_root)
    assert sorted(tasks) == ["binary_task", "multilabel_task"]
    assert tasks["multilabel_task"].kind == "multilabel" and tasks["multilabel_task"].label_names == ("x", "y", "z")
    proteins = concepts.concept_proteins(tasks)
    assert len(proteins.sequences) == 12 + 3 and proteins.sequences == sorted(proteins.sequences)
    for name, task in tasks.items():
        for split, frame in task.frames.items():
            assert [proteins.sequences[row] for row in proteins.rows[name][split]] == frame["sequence"].tolist()
    cut = concepts.concept_proteins(tasks, max_residues=5)
    assert all(len(sequence) <= 5 for sequence in cut.sequences) and len(cut.sequences) <= 15
    with pytest.raises(ValueError, match="No residue-level"):
        concepts.load_tasks(task_root / "binary_task", level="residue")


def test_pooling_helpers_match_direct_statistics() -> None:
    generator = torch.Generator().manual_seed(0)
    values = torch.randn(30, 5, generator=generator)  # (r, w)
    owner = torch.tensor([0] * 7 + [1] * 13 + [2] * 10)  # (r,)
    per_protein = concepts.pooled(values, owner, 3)
    for protein in range(3):
        rows = values[owner == protein]  # (r_protein, w)
        torch.testing.assert_close(per_protein["mean"][protein], rows.mean(dim=0))
        torch.testing.assert_close(per_protein["max"][protein], rows.max(dim=0).values)
        torch.testing.assert_close(per_protein["min"][protein], rows.min(dim=0).values)
    assert set(concepts.pooled(values, owner, 3, ("mean",))) == {"mean"}
    indices = torch.randint(0, 9, (30, 2), generator=generator)  # (r, k)
    codes = torch.rand(30, 2, generator=generator)  # (r, k)
    dense = torch.zeros(30, 9).scatter_reduce(1, indices, codes, reduce="amax", include_self=True)  # (r, c)
    maxima = concepts.max_pooled_codes(indices, codes, owner, 3, 9)  # (n, c)
    for protein in range(3):
        torch.testing.assert_close(maxima[protein], dense[owner == protein].max(dim=0).values)


class _FirstBatches:
    """A pilot whose window is the first two batches."""

    def watch(self, indices: range) -> Iterator[int]:
        yield from list(indices)[:2]


def test_extraction_writes_each_proteins_pooled_features(tiny_esmc: nn.Module, tiny_sae: Callable[..., nn.Module],
                                                         task_root: Path, tmp_path: Path) -> None:
    sequences = concepts.concept_proteins(concepts.load_tasks(task_root)).sequences
    plan = concepts.ExtractionPlan(depths=(1, 2), rotation_block=2, rotation_seeds=(0, 3), sae="tiny", sae_block=1,
                                   all_blocks=True)
    sae = tiny_sae(seed=11)
    run = concepts.ConceptExtraction(tiny_esmc, plan, sequences, tmp_path / "whole", CPU, sae=sae, token_budget=160,
                                     log=lambda message: None)
    assert run.run()["complete"]
    lengths = [len(sequence) for sequence in sequences]
    states = atlas.calibration_states(tiny_esmc, tiny_esmc.tokenizer, sequences, [0, 1, 2], np.ones(sum(lengths), dtype=bool),
                                      stream_blocks=[1, 2], device=CPU)
    bounds = np.concatenate(([0], np.cumsum(lengths)))  # (n + 1,)
    rotation = haar_rotation(states[1].gate.shape[1], 3)  # (f, f)
    for block in (0, 1, 2):
        product = states[block].product()  # (r, f)
        expected = torch.stack([product[start:stop].mean(dim=0) for start, stop in zip(bounds[:-1], bounds[1:], strict=True)])
        np.testing.assert_allclose(concepts.read_feature(tmp_path / "whole", block, "z_mean"), expected.numpy(), atol=1e-5)
    product = states[2].product()  # (r, f)
    rotated = product @ rotation  # (r, f)
    poles = swiglu_poles(states[2].gate, states[2].up).main()  # (r, 2f)
    checks = {"z_max": (product, "max"), "z_min": (product, "min"), "rotation3_max": (rotated, "max"),
              "rotation3_min": (rotated, "min"), "poles_mean": (poles, "mean"), "gate_mean": (states[2].gate, "mean"),
              "stream_mean": (states[2].stream, "mean")}
    for name, (values, statistic) in checks.items():
        expected = torch.stack([getattr(values[start:stop], statistic)(dim=0) if statistic == "mean"
                                else getattr(values[start:stop], statistic)(dim=0).values
                                for start, stop in zip(bounds[:-1], bounds[1:], strict=True)])
        np.testing.assert_allclose(concepts.read_feature(tmp_path / "whole", 2, name), expected.float().numpy(), atol=1e-4,
                                   err_msg=name)
    latents = bases.basis_activations(bases.Basis("sae", 1, sae="tiny"), states[1], sae=sae)  # (r, c)
    expected = torch.stack([latents[start:stop].max(dim=0).values for start, stop in zip(bounds[:-1], bounds[1:], strict=True)])
    np.testing.assert_allclose(concepts.read_feature(tmp_path / "whole", 1, "sae_max"), expected.numpy(), atol=1e-4)
    partial = concepts.ConceptExtraction(tiny_esmc, plan, sequences, tmp_path / "resumed", CPU, sae=sae, token_budget=160,
                                         log=lambda message: None)
    assert not partial.run(_FirstBatches())["complete"] and partial.done == 2
    resumed = concepts.ConceptExtraction(tiny_esmc, plan, sequences, tmp_path / "resumed", CPU, sae=sae, token_budget=160,
                                         log=lambda message: None)
    assert resumed.done == 2 and resumed.run()["complete"]
    for block, name in run.widths:
        np.testing.assert_array_equal(concepts.read_feature(tmp_path / "resumed", block, name),
                                      concepts.read_feature(tmp_path / "whole", block, name))


def test_plans_check_their_sae_and_list_their_arrays() -> None:
    with pytest.raises(ValueError, match="depth block"):
        concepts.ExtractionPlan(depths=(1, 2), sae="tiny", sae_block=0)
    with pytest.raises(ValueError, match="needs its block"):
        concepts.ExtractionPlan(depths=(1,), sae="tiny")
    with pytest.raises(ValueError, match="both a block and seeds"):
        concepts.ExtractionPlan(depths=(1,), rotation_block=1)
    plan = concepts.ExtractionPlan(depths=(2, 4), rotation_block=4, rotation_seeds=(0, 1, 2), all_blocks=True)
    widths = concepts.feature_widths(plan, units=10, width=6)
    assert plan.blocks == (0, 1, 2, 3, 4)
    assert widths[(0, "z_mean")] == 10 and (0, "z_max") not in widths and widths[(4, "poles_mean")] == 20
    assert widths[(4, "rotation2_min")] == 10 and (2, "rotation0_max") not in widths
    assert widths[(2, "stream_mean")] == 6 and len(widths) == 3 + 2 * (len(concepts.UNIT_FEATURES) + 2) + 3 * 2
