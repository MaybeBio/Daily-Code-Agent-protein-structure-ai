"""The pretraining reads a release's vocabulary and train split, hides tokens correctly, and trains a step on CPU."""

import json
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch

from pathlib import Path

from annotation_transformer.pretrain import (
    IGNORE_INDEX,
    Schedule,
    TokenSpace,
    cluster_intervals,
    collate,
    main,
    mask_for_mlm,
    prior_statistics,
    read_token_space,
)


TERMS = 40
SPACE = TokenSpace(terms=TERMS, pad=TERMS, mask=TERMS + 3, size=TERMS + 5)


def write_release(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    tokens = [*range(TERMS), "<pad>", "<bos>", "<eos>", "<mask>", "<unk>"]
    aspects = ["go_bp"] * TERMS + ["special"] * 5
    pq.write_table(pa.table({"token": list(range(TERMS + 5)), "term_id": [str(item) for item in tokens], "aspect": aspects}), root / "vocabulary.parquet")
    generator = torch.Generator().manual_seed(0)
    for split, count in (("train", 64), ("validation", 16), ("test", 16)):
        rows = [sorted(torch.randperm(TERMS, generator=generator)[: 3 + index % 6].tolist()) for index in range(count)]
        pq.write_table(pa.table({
            "protein_id": [f"{split}{index}" for index in range(count)], "cluster_id": [f"{split}{index // 2}" for index in range(count)],
            "annotation_tokens": pa.array(rows, pa.list_(pa.int32())),
        }), root / f"{split}.parquet")
    return root


def test_token_space_comes_from_the_vocabulary_with_padding_after_the_terms(tmp_path: Path) -> None:
    assert read_token_space(write_release(tmp_path)) == SPACE


def test_collate_pads_with_the_pad_token_and_masks_it() -> None:
    input_ids, attention_mask = collate([[0, 5], [7]], SPACE.pad)
    assert input_ids.tolist() == [[0, 5], [7, SPACE.pad]] and attention_mask.tolist() == [[1, 1], [1, 0]]


def test_masking_hides_only_real_tokens_and_every_row_hides_one() -> None:
    rows = [list(range(30)), [1], [2, 3]]
    input_ids, attention_mask = collate(rows, SPACE.pad)
    corrupted, labels = mask_for_mlm(input_ids, attention_mask, SPACE, 0.15, torch.Generator().manual_seed(1))
    hidden = labels != IGNORE_INDEX
    assert (hidden.sum(dim=1) >= 1).all() and not (hidden & ~attention_mask.bool()).any()
    assert torch.equal(labels[hidden], input_ids[hidden])
    assert (corrupted[~hidden] == input_ids[~hidden]).all()
    changed = corrupted[hidden] != input_ids[hidden]
    assert (corrupted[hidden][changed] <= SPACE.mask).all() and (corrupted < SPACE.size).all()


def test_masking_shares_follow_eighty_ten_ten() -> None:
    input_ids = torch.randint(0, TERMS, (200, 100))
    corrupted, labels = mask_for_mlm(input_ids, torch.ones_like(input_ids), SPACE, 0.15, torch.Generator().manual_seed(2))
    hidden = labels != IGNORE_INDEX
    masked = (corrupted[hidden] == SPACE.mask).float().mean()
    assert abs(float(hidden.float().mean()) - 0.15) < 0.02 and abs(float(masked) - 0.8) < 0.03


def test_schedule_warms_up_then_decays_to_its_floor() -> None:
    schedule = Schedule(warmup=10, steps=110, floor=0.1)
    assert schedule.factor(0) == pytest.approx(0.1) and schedule.factor(9) == pytest.approx(1.0)
    assert schedule.factor(110) == pytest.approx(0.1) and schedule.factor(60) == pytest.approx(0.55)


def test_a_short_run_trains_selects_on_validation_and_scores_test_once(tmp_path: Path) -> None:
    release = write_release(tmp_path / "release")
    output = tmp_path / "run"
    arguments = [
        "--release", str(release), "--output", str(output), "--experiment", "2026-10-04_at_test", "--preset", "at_base",
        "--batch-size", "8", "--steps", "4", "--warmup", "1", "--eval-every", "2", "--no-wandb",
    ]
    assert main(arguments) == 0 and (output / "best" / "config.json").is_file() and (output / "last" / "config.json").is_file()
    assert not (output / "final").exists()
    scores = json.loads((output / "scores.json").read_text(encoding="utf-8"))
    assert {"best_validation_loss", "best_step", "validation_top5", "test_loss", "test_top1", "test_prior_top5"} <= scores.keys()
    evaluation = json.loads((output / "evaluation.json").read_text(encoding="utf-8"))
    test = evaluation["splits"]["test"]
    assert evaluation["selection_split"] == "validation" and test["rows"] == 16
    for name in ("model", "prior", "random_weights"):
        assert all(item["low"] <= item["value"] <= item["high"] for item in test[name].values())
    assert pq.read_table(output / "rows_test.parquet").num_rows == 16
    # The test split is read once: a second evaluation of the same run is refused.
    with pytest.raises(FileExistsError, match="read once"):
        main([*arguments, "--evaluate-only"])


def test_the_prior_and_the_bootstrap_use_the_same_hidden_positions_as_the_model() -> None:
    train = [[0, 1], [0, 2], [0, 1, 3]]
    rows = [[0, 1], [2, 3, 4], [0]]
    statistics = prior_statistics(train, rows, SPACE, 2, 0.15)
    assert statistics.hits.shape == (3, 2) and bool((statistics.hidden >= 1).all()) and bool((statistics.hits[:, 0] <= statistics.hits[:, 1]).all())
    # Every row's top-1 hits are within the row's hidden count, and token 0 (the most frequent) is the one a hit means.
    assert bool((statistics.hits[:, 1] <= statistics.hidden).all())
    intervals = cluster_intervals(statistics, ["a", "a", "b"])
    assert set(intervals) == {"loss", "top1", "top5"} and all(item["low"] <= item["value"] <= item["high"] for item in intervals.values())
    assert intervals["top1"]["value"] == pytest.approx(float(statistics.hits[:, 0].sum() / statistics.hidden.sum()))
