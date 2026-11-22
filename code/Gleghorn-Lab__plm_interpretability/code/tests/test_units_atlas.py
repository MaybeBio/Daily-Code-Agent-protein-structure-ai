from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from collections.abc import Callable
from pathlib import Path
from annotation_vocabulary.study.association import local_statistics
from torch import nn

from plm_interpretability.units import accumulate, atlas, bases, capture, firing_rates, rotations


TERM_COLUMNS = {10: {101: 0, 202: 1, 303: 2}, 50: {101: 0, 202: 1}}
CPU = torch.device("cpu")
BUDGET = 240


class _Interrupt(Exception):
    pass


def _proteins(n: int = 52, seed: int = 0) -> atlas.PassProteins:
    rng = np.random.default_rng(seed)
    splits = np.array(["train"] * 30 + ["validation"] * 6 + ["test"] * 8 + ["calibration"] * 8)[:n]
    accessions, sequences, local = [], [], []
    for index in range(n):
        length = int(rng.integers(12, 40))
        sequences.append("".join(rng.choice(list("ACDEFGHIKLMNPQRSTVWY"), size=length)))
        accessions.append(f"Q{index:04d}")
        tokens, starts, ends = [], [], []
        for _ in range(int(rng.integers(1, 5))):
            start = int(rng.integers(1, length))
            tokens.append(int(rng.choice([101, 202, 303, 999])))
            starts.append(start)
            ends.append(int(rng.integers(start, length + 1)))
        local.append(accumulate.LocalRuns.positives(np.array(tokens), np.array(starts), np.array(ends)))
    return atlas.PassProteins(accessions, sequences, splits, local)


REFERENCES = {"tiny": bases.Basis("sae", 1, sae="tiny"), "narrow": bases.Basis("sae", 1, sae="narrow")}
CODEBOOKS = {"tiny": 96, "narrow": 48}
PLAN = [
    *(atlas.PlannedBasis(bases.Basis("native", block), "contrast", "tiny") for block in (0, 1, 2)),
    atlas.PlannedBasis(bases.Basis("native", 1), "contrast", "narrow"),
    atlas.PlannedBasis(bases.Basis("rotation", 1, seed=0), "contrast", "tiny"),
    atlas.PlannedBasis(bases.Basis("residual", 1), "selection", "tiny"),
    atlas.PlannedBasis(REFERENCES["tiny"], "selection"),
]


@pytest.fixture(scope="module")
def calibrated(tiny_esmc: nn.Module, tiny_sae: Callable[..., nn.Module]) -> dict[str, object]:
    proteins = _proteins()
    calibration = [sequence for sequence, split in zip(proteins.sequence, proteins.split, strict=True) if split == "calibration"]
    rotation = rotations.haar_rotation(256, seed=0).float()  # (f, f)
    saes = {"tiny": tiny_sae(96, 8, seed=5), "narrow": tiny_sae(48, 4, seed=6)}
    matches, reference_rates = atlas.calibrate(tiny_esmc, tiny_esmc.tokenizer, calibration, PLAN, REFERENCES,
                                               rotations={0: rotation}, saes=saes, device=CPU, memory_budget=1,
                                               sample_size=150, token_budget=BUDGET)
    kept = proteins.split != "calibration"
    pass_proteins = atlas.PassProteins([a for a, keep in zip(proteins.accession, kept, strict=True) if keep],
                                       [s for s, keep in zip(proteins.sequence, kept, strict=True) if keep],
                                       proteins.split[kept], [x for x, keep in zip(proteins.local, kept, strict=True) if keep]).ordered()
    widths = {planned.basis.name: bases.basis_width(planned.basis, d=64, f=256, codebook=CODEBOOKS.get(planned.basis.sae or "", 0))
              for planned in PLAN}
    return {"matches": matches, "reference_rates": reference_rates, "proteins": pass_proteins, "widths": widths,
            "rotations": {0: rotation}, "saes": saes}


def _pass(model: nn.Module, calibrated: dict[str, object], output: Path, kind: type = atlas.AtlasPass,
          **options: object) -> atlas.AtlasPass:
    settings = {"token_budget": BUDGET, "log": lambda message: None, **options}
    return kind(
        model, model.tokenizer, PLAN, calibrated["proteins"], TERM_COLUMNS,
        thresholds={name: match.thresholds for name, match in calibrated["matches"].items()},
        widths=calibrated["widths"], output=output, device=CPU, rotations=calibrated["rotations"],
        saes=calibrated["saes"], **settings,
    )


def _direct(model: nn.Module, calibrated: dict[str, object]) -> dict[str, torch.Tensor]:
    """Every planned pair's sparsified activations over the pass's residues, in pass order, batch by batch, by key."""
    proteins: atlas.PassProteins = calibrated["proteins"]
    thresholds = {name: match.thresholds for name, match in calibrated["matches"].items()}
    parts: dict[str, list[torch.Tensor]] = {}

    def keep(states: capture.BlockStates) -> None:
        for planned in PLAN:
            basis = planned.basis
            if basis.block != states.block:
                continue
            values = bases.basis_activations(basis, states, rotation=calibrated["rotations"].get(basis.seed),
                                             sae=calibrated["saes"].get(basis.sae or ""))  # (r, w)
            if planned.reference is not None:
                values = firing_rates.sparsify(values, thresholds[planned.key])  # (r, w)
            parts.setdefault(planned.key, []).append(values)

    with capture.BlockReader(model, [0, 1, 2], keep, stream_blocks=[1]) as reader:
        for rows in atlas.length_batches(proteins.lengths, BUDGET):
            input_ids, attention_mask, residues = atlas.encode_batch(model.tokenizer, proteins.sequence[rows], CPU)
            reader.run(input_ids, attention_mask, residues)
    return {name: torch.cat(values) for name, values in parts.items()}  # each (r_total, w)


def _study(proteins: atlas.PassProteins, values: torch.Tensor, split: str, tokens: list[int]) -> dict[str, np.ndarray]:
    """The atlas study's own local sums over one split's proteins, every pole stored as a TopK slot."""
    # values: (r, w)
    lengths = proteins.lengths
    offsets = np.concatenate(([0], np.cumsum(lengths)[:-1]))  # (n,)
    chosen = np.flatnonzero(proteins.split == split)  # (n_split,)
    rows = np.concatenate([np.arange(offsets[index], offsets[index] + lengths[index]) for index in chosen])  # (r_split,)
    kept = values[torch.from_numpy(rows)].double().numpy()  # (r_split, w)
    frame = pd.DataFrame({"local_term_ids": [proteins.local[index].tokens for index in chosen],
                          "local_starts": [proteins.local[index].starts for index in chosen],
                          "local_ends": [proteins.local[index].ends for index in chosen]})
    split_lengths = lengths[chosen]  # (n_split,)
    split_offsets = np.concatenate(([0], np.cumsum(split_lengths)[:-1]))  # (n_split,)
    width = kept.shape[1]
    return local_statistics(frame, np.tile(np.arange(width), (len(kept), 1)), kept, split_offsets, split_lengths,
                            np.arange(width), np.array(tokens))  # each statistic (w, t) or (t,)


def test_calibration_puts_every_basis_at_the_reference_rates(calibrated: dict[str, object]) -> None:
    matches, reference_rates = calibrated["matches"], calibrated["reference_rates"]
    assert set(matches) == {planned.key for planned in PLAN if planned.reference is not None}
    assert {name: tuple(rates.shape) for name, rates in reference_rates.items()} == {"tiny": (96,), "narrow": (48,)}
    for planned in PLAN:
        if planned.reference is not None:
            achieved = matches[planned.key].achieved  # (w,)
            assert firing_rates.ks_distance(achieved, reference_rates[planned.reference]) < 0.1, planned.key
    narrow, wide = matches["block1/native@narrow"].achieved, matches["block1/native@tiny"].achieved  # (w,), (w,)
    assert float(narrow.mean()) < float(wide.mean())  # 4 of 48 latents fire less often than 8 of 96


def test_pass_scores_match_direct_computation(tiny_esmc: nn.Module, calibrated: dict[str, object], tmp_path: Path) -> None:
    run = _pass(tiny_esmc, calibrated, tmp_path / "pass", checkpoint_seconds=1e9)
    timing = run.run()
    assert timing["batches"] == len(run.batches) > 1
    proteins: atlas.PassProteins = calibrated["proteins"]
    direct = _direct(tiny_esmc, calibrated)
    owner = accumulate.protein_index(proteins.lengths.tolist())  # (r_total,)
    validation = torch.from_numpy(np.repeat(proteins.split == "validation", proteins.lengths))  # (r_total,)
    rates = run.validation_rates()
    for planned in PLAN:
        name = planned.key
        stored = np.load(tmp_path / "pass" / "maxima" / f"{planned.stem}.npy")
        expected = accumulate.protein_maxima(direct[name], owner, len(proteins.accession)).numpy()  # (n, w)
        np.testing.assert_allclose(stored, expected, rtol=1e-6, atol=1e-7, err_msg=name)
        np.testing.assert_allclose(rates[name].numpy(), (direct[name][validation] > 0).double().mean(dim=0).numpy(), err_msg=name)
        train_tokens = list(TERM_COLUMNS[atlas.PROFILES[planned.profile].min_informative])
        reference = _study(proteins, direct[name], "train", train_tokens)
        ours = run.train[name].study_sums()
        for key in atlas.PROFILES[planned.profile].keys:
            np.testing.assert_allclose(ours[key], reference[key], rtol=1e-5, atol=1e-6, err_msg=f"{name} {key}")
        held_out = _study(proteins, direct[name], "test", list(TERM_COLUMNS[50]))
        np.testing.assert_allclose(run.test[name].study_sums()["sum_difference"], held_out["sum_difference"], rtol=1e-5,
                                   atol=1e-6, err_msg=name)


def test_interrupted_pass_resumes_to_the_same_result(tiny_esmc: nn.Module, calibrated: dict[str, object], tmp_path: Path) -> None:
    straight = _pass(tiny_esmc, calibrated, tmp_path / "straight")
    straight.run()

    class Interrupted(atlas.AtlasPass):
        def _consume(self, states: capture.BlockStates) -> None:
            if self.done == 2:
                raise _Interrupt
            super()._consume(states)

    interrupted = _pass(tiny_esmc, calibrated, tmp_path / "resumed", kind=Interrupted, checkpoint_seconds=0.0)
    with pytest.raises(_Interrupt):
        interrupted.run()
    resumed = _pass(tiny_esmc, calibrated, tmp_path / "resumed")
    resumed.run()
    assert resumed.done == len(resumed.batches)
    for planned in PLAN:
        name, stem = planned.key, planned.stem
        np.testing.assert_array_equal(np.load(tmp_path / "resumed" / "maxima" / f"{stem}.npy"),
                                      np.load(tmp_path / "straight" / "maxima" / f"{stem}.npy"), err_msg=name)
        for key, values in straight.train[name].study_sums().items():
            np.testing.assert_allclose(resumed.train[name].study_sums()[key], values, rtol=1e-12, err_msg=f"{name} {key}")
        assert torch.equal(resumed.validation_counts[name], straight.validation_counts[name])
    with pytest.raises(ValueError):
        _pass(tiny_esmc, calibrated, tmp_path / "resumed", token_budget=BUDGET + 40).resume()


def test_given_rates_skip_the_reference_pass(tiny_esmc: nn.Module, calibrated: dict[str, object]) -> None:
    proteins = _proteins()
    calibration = [sequence for sequence, split in zip(proteins.sequence, proteins.split, strict=True) if split == "calibration"]
    native = [planned for planned in PLAN if planned.basis.kind == "native"]
    matches, rates = atlas.calibrate(tiny_esmc, tiny_esmc.tokenizer, calibration, native, REFERENCES, rotations={}, saes={},
                                     device=CPU, memory_budget=1, sample_size=150, token_budget=BUDGET,
                                     rates=calibrated["reference_rates"])
    for planned in native:
        assert torch.equal(matches[planned.key].thresholds, calibrated["matches"][planned.key].thresholds), planned.key
    with pytest.raises(ValueError):
        atlas.calibrate(tiny_esmc, tiny_esmc.tokenizer, calibration, native, REFERENCES, rotations={}, saes={}, device=CPU,
                        rates={"tiny": calibrated["reference_rates"]["tiny"]})
