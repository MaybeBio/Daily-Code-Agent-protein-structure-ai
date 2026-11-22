"""A compendium release is read without organism terms, cut to 64 tokens with its specials, sampled by cluster, and trains."""

import hashlib
import json
import random
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch

from pathlib import Path

from annotation_transformer import compendium
from annotation_transformer.pretrain import (
    IGNORE_INDEX,
    TokenSpace,
    collate,
    main,
    mask_for_mlm,
    read_split,
    read_token_space,
    training_batches,
)


TERMS = 100
ORGANISM = range(90, 100)  # the last ten terms are organism terms
LONG = list(range(80))  # one train entry longer than the 62 terms an input holds


def protein(split: str, index: int) -> str:
    return hashlib.sha256(f"{split}{index}".encode()).hexdigest()


def write_compendium(root: Path, held_out_curated: bool = False) -> Path:
    """A release of 64 train, 16 validation and 16 test rows: train row 0 holds organism terms only, train row 1 is LONG."""
    (root / "tables").mkdir(parents=True, exist_ok=True)
    terms = [f"av::go_bp::GO::GO:{index:07d}" for index in range(TERMS)]
    aspects = ["organism" if index in ORGANISM else "process_pathway" for index in range(TERMS)]
    pq.write_table(pa.table({"term_id": terms, "token": list(range(TERMS))}), root / "tables" / "tokens.parquet")
    pq.write_table(pa.table({"term_id": [*terms, "av::cazy::CAZy::AA1"], "fundamental_aspect": [*aspects, "domain_family"]}),
                   root / "tables" / "vocabulary.parquet")
    generator = torch.Generator().manual_seed(0)
    proteins, coarse = [], []
    for split, count in (("train", 64), ("validation", 16), ("test", 16)):
        rows = [sorted(torch.randperm(TERMS, generator=generator)[: 3 + index % 6].tolist()) for index in range(count)]
        if split == "train":
            rows[0], rows[1] = list(ORGANISM)[:3], LONG
        tiers = [["curated" if split == "train" and position % 3 == 0 else "experimental" for position in range(len(row))]
                 for row in rows]
        if held_out_curated and split == "validation":
            tiers[0][0] = "curated"
        names = [protein(split, index) for index in range(count)]
        pq.write_table(pa.table({
            "protein_id": names, "cluster_id": [f"{split}-c090-{index // 2}" for index in range(count)],
            "tokens": pa.array(rows, pa.list_(pa.int32())), "tiers": tiers,
        }), root / f"{split}.parquet")
        proteins += names
        coarse += [f"{split}-c050-{index // 4}" for index in range(count)]
    pq.write_table(pa.table({"protein_id": proteins, "c090": ["unused"] * len(proteins), "c050": coarse}),
                   root / "tables" / "clusters.parquet")
    return root


def test_the_token_space_appends_the_specials_after_the_terms_in_grammar_order(tmp_path: Path) -> None:
    space = read_token_space(write_compendium(tmp_path))
    assert space == TokenSpace(terms=TERMS, pad=TERMS, mask=TERMS + 3, size=TERMS + 5, bos=TERMS + 1, eos=TERMS + 2)


def test_the_reader_drops_organism_terms_and_the_rows_they_leave_empty(tmp_path: Path) -> None:
    release = write_compendium(tmp_path)
    rows = compendium.read_split(release, "train")
    assert rows.dropped == 1 and len(rows.entries) == 63 and rows.protein_id[0] == protein("train", 1)
    assert all(token not in ORGANISM for entry in rows.entries for token in entry)
    assert rows.entries[0] == LONG and rows.c050[0] == "train-c050-0" and rows.c090[0] == "train-c090-0"


def test_a_held_out_curated_term_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="curated"):
        compendium.read_split(write_compendium(tmp_path, held_out_curated=True), "validation")


def test_training_entries_are_ascending_subsets_of_at_most_62_terms_and_half_are_thinned() -> None:
    generator = random.Random(0)
    for _ in range(50):
        cut = compendium.train_entry(LONG, generator)
        assert len(cut) == compendium.MAX_TERMS and cut == sorted(cut) and set(cut) <= set(LONG)
    short = list(range(0, 40, 2))
    presented = [compendium.train_entry(short, generator) for _ in range(4000)]
    assert all(entry == sorted(entry) and entry and set(entry) <= set(short) for entry in presented)
    # Half are thinned to k of n, k uniform on 1..n, so a share (1 - 1/n) / 2 comes out shorter than the entry.
    shorter = sum(len(entry) < len(short) for entry in presented) / len(presented)
    assert abs(shorter - 0.5 * (1 - 1 / len(short))) < 0.03


def test_a_held_out_entry_is_cut_the_same_way_every_time() -> None:
    name = protein("test", 3)
    assert compendium.held_out_entry(LONG, name) == compendium.held_out_entry(LONG, name)
    assert len(compendium.held_out_entry(LONG, name)) == compendium.MAX_TERMS
    assert compendium.held_out_entry([1, 5, 9], name) == [1, 5, 9]
    with pytest.raises(ValueError, match="64-token"):
        compendium.wrap(LONG, TERMS + 1, TERMS + 2)


def test_cluster_batches_hold_distinct_clusters_and_reach_every_cluster() -> None:
    clusters = [f"c{index % 7}" for index in range(40)]
    stream = compendium.cluster_batches(clusters, 5, random.Random(1))
    seen = set()
    for _ in range(50):
        batch = next(stream)
        assert len({clusters[index] for index in batch}) == 5
        seen |= {clusters[index] for index in batch}
    assert seen == set(clusters)
    with pytest.raises(ValueError, match="distinct clusters"):
        next(compendium.cluster_batches(clusters, 8, random.Random(1)))


def test_training_batches_are_wrapped_and_never_hide_a_special(tmp_path: Path) -> None:
    release = write_compendium(tmp_path)
    space = read_token_space(release)
    batch = next(training_batches(release, space, 8, seed=3))
    assert len(batch) == 8 and all(row[0] == space.bos and row[-1] == space.eos and len(row) <= 64 for row in batch)
    input_ids, attention_mask = collate(batch, space.pad)
    _, labels = mask_for_mlm(input_ids, attention_mask, space, 0.5, torch.Generator().manual_seed(4))
    hidden = labels != IGNORE_INDEX
    assert (hidden.sum(dim=1) >= 1).all() and (input_ids[hidden] < space.terms).all()


def test_a_short_compendium_run_trains_and_scores_test_once_over_coarse_clusters(tmp_path: Path) -> None:
    release = write_compendium(tmp_path / "release")
    output = tmp_path / "run"
    arguments = [
        "--release", str(release), "--output", str(output), "--experiment", "2026-10-22_at_compendium_test", "--preset", "at_base",
        "--batch-size", "8", "--steps", "4", "--warmup", "1", "--eval-every", "2", "--no-wandb",
    ]
    assert main(arguments) == 0 and (output / "best" / "config.json").is_file()
    config = json.loads((output / "best" / "config.json").read_text(encoding="utf-8"))
    assert config["vocab_size"] == TERMS + 5 and config["bos_token_id"] == TERMS + 1 and config["eos_token_id"] == TERMS + 2
    evaluation = json.loads((output / "evaluation.json").read_text(encoding="utf-8"))
    assert evaluation["splits"]["test"]["rows"] == 16
    rows = pq.read_table(output / "rows_test.parquet").to_pydict()
    assert rows["cluster_id"] == read_split(release, "test")["cluster_id"] and rows["cluster_id"][0] == "test-c050-0"
