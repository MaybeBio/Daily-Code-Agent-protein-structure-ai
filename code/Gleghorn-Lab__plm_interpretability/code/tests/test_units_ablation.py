from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from torch import nn

from plm_interpretability.units import ablation, atlas, causal, intrinsic
from plm_interpretability.units.capture import BlockStates


CPU = torch.device("cpu")


def _proteins(n: int = 40) -> pd.DataFrame:
    """Odd rows are test proteins. Term 7 covers residues 3 to 15 of every protein; term 8 sits at residue 12 of rows
    1, 16 and 31 (two of them held out); term 9 starts past every protein's end."""
    rng = np.random.default_rng(0)
    rows = []
    for index in range(n):
        length = int(rng.integers(25, 40))
        has_site = index % 15 == 1
        rows.append({
            "accession": f"Q{index:03d}", "split": "test" if index % 2 else "train",
            "sequence": "".join(rng.choice(list(intrinsic.AMINO_ACIDS), size=length)),
            "local_term_ids": np.array([7, 8, 9] if has_site else [7, 9]),
            "local_starts": np.array([3, 12, 500] if has_site else [3, 500]),
            "local_ends": np.array([15, 12, 510] if has_site else [15, 510]),
        })
    return pd.DataFrame(rows)


def _values(model: nn.Module, proteins: pd.DataFrame) -> torch.Tensor:
    total = int(proteins["sequence"].str.len().sum())
    states = atlas.calibration_states(model, model.tokenizer, proteins["sequence"].tolist(), [1], np.ones(total, dtype=bool),
                                      device=CPU)[1]
    return causal.nonfiring_means(states.gate, states.up)  # (p,)


def test_labeled_poles_need_a_dominant_term_among_their_labels() -> None:
    labels = pd.DataFrame({"pole": [0, 0, 1, 2, 3], "term": [5, 6, 6, 7, 8], "mean_difference": [0.5, 0.4, 0.3, 0.2, 0.1]})
    scores = pd.DataFrame({"pole": [0, 1, 2, 3], "best_local_term": [6, 9, 7, 8], "dominant": [True, True, False, True]})
    chosen = ablation.labeled_poles(labels, scores)
    assert chosen.to_dict(orient="list") == {"pole": [0, 3], "term": [6, 8]}
    assert len(ablation.labeled_poles(labels, scores, limit=1)) == 1


def test_intervals_carriers_sites_and_masks() -> None:
    proteins = _proteins()
    row = proteins.iloc[1]
    assert ablation.term_intervals(row, 7) == [(2, 14)] and ablation.term_intervals(row, 9) == []
    carriers = ablation.held_out_carriers(proteins)
    assert carriers[8] == [1, 31] and len(carriers[7]) == 20
    regions, chosen, outside = ablation.ablation_sites([[(2, 8)], [(0, 1), (5, 5)]], [12, 7], masked=3, seed=0)
    assert regions[0].tolist() == list(range(2, 9)) and regions[1].tolist() == [0, 1, 5]
    assert len(chosen[0]) == 3 and set(chosen[0]) <= set(regions[0]) and chosen[1].tolist() == [0, 1, 5]
    assert len(outside[0]) == 3 and not set(outside[0]) & set(regions[0])
    assert len(outside[1]) == 3 and set(outside[1]) <= {2, 3, 4, 6}
    mask = ablation.column_mask(regions, (2, 12))  # (b, l)
    assert mask[0].nonzero().flatten().tolist() == list(range(3, 10)) and mask[1].nonzero().flatten().tolist() == [1, 2, 6]


def test_removed_mass_and_matched_placebos() -> None:
    generator = torch.Generator().manual_seed(0)
    gate, up = torch.randn(50, 4, generator=generator), torch.randn(50, 4, generator=generator)  # (r, f)
    values = torch.randn(8, generator=generator, dtype=torch.float64)  # (p,)
    removed = ablation.removed_mass(BlockStates(block=0, gate=gate, up=up), values)  # (p,)
    product = torch.nn.functional.silu(gate.double()) * up.double()  # (r, f)
    fires = (gate[:, 1] > 0) & (up[:, 1] < 0)  # unit 1's negative pole, column 5
    assert float(removed[5]) == pytest.approx(float((product[fires, 1] - values[5]).abs().sum()))
    mass = torch.tensor([1.0, 2.0, 0.0, 4.0, 1.1, 8.0, 0.9, 1.0], dtype=torch.float64)  # (p,)
    # From pole 0 (mass 1) on a log scale: pole 7 at 0, 6 at 0.105, 1 at 0.693, 3 at 1.386, 5 at 2.079; 4 is excluded and
    # 2 removes nothing.
    assert ablation.matched_placebos(mass, 0, [4], count=3) == [7, 6, 1]
    assert ablation.matched_placebos(mass, 0, [4], count=7) == [7, 6, 1, 3, 5]


def test_ablating_a_pole_against_its_placebos(tiny_esmc: nn.Module) -> None:
    proteins = _proteins()
    values = _values(tiny_esmc, proteins)  # (p,)
    frame = proteins.iloc[[1, 3, 5, 7]]
    sequences = frame["sequence"].tolist()
    intervals = [ablation.term_intervals(row, 7) for _, row in frame.iterrows()]
    entry = ablation.ablate_pole(tiny_esmc, 1, 0, 7, sequences, intervals, values, [1], CPU)
    assert entry["status"] == "tested" and entry["masked"] == 4 * ablation.MASKED_PER_PROTEIN and entry["removed"] > 0
    assert len(entry["placebo_drops"]) == len(set(entry["placebo_poles"])) == ablation.PLACEBOS
    assert not {0, 1} & set(entry["placebo_poles"])
    assert np.isfinite([entry["drop"], entry["outside_drop"], *entry["placebo_drops"]]).all()
    assert ablation.ablate_pole(tiny_esmc, 1, 0, 7, sequences, intervals, values, [1], CPU) == entry


def test_h6_runs_over_labeled_poles(tiny_esmc: nn.Module) -> None:
    proteins = _proteins()
    values = _values(tiny_esmc, proteins)  # (p,)
    labels = pd.DataFrame({"pole": [0, 1, 2], "term": [7, 8, 7], "mean_difference": [0.5, 0.4, 0.3]})
    scores = pd.DataFrame({"pole": [0, 1, 2], "best_local_term": [7, 8, 7], "dominant": [True, True, False]})
    table = ablation.run_h6(tiny_esmc, 1, labels, scores, proteins, values, CPU, log=lambda message: None).set_index("pole")
    assert table.index.tolist() == [0, 1]
    assert table.loc[1, "status"] == "too_few" and table.loc[1, "proteins"] == 2
    assert table.loc[0, "status"] == "tested" and table.loc[0, "proteins"] == ablation.PROTEINS_PER_POLE
    assert 2 not in table.loc[0, "placebo_poles"]  # pole 2 carries the same label


def test_weak_and_strong_removal_read_the_masked_tokens(tiny_esmc: nn.Module) -> None:
    sequences = _proteins()["sequence"].tolist()
    report = ablation.weak_strong(tiny_esmc, sequences[:20], sequences[20:], CPU, residues=400, token_budget=300,
                                  log=lambda message: None)
    assert set(report["readout"]) == {"intact", "weak", "strong"}
    assert report["removed_share"]["weak"] == pytest.approx(0.75, abs=0.02)
    assert 0 < report["removed_share"]["strong"] < report["removed_share"]["weak"]
    chosen = ablation.readout_positions(np.array([len(sequence) for sequence in sequences[20:]]))
    assert report["readout"]["intact"]["masked"] == sum(len(positions) for positions in chosen)
    input_ids, attention_mask, _ = atlas.encode_batch(tiny_esmc.tokenizer, sequences[20:], CPU)  # (b, l) each
    positions = ablation.column_mask(chosen, tuple(input_ids.shape))  # (b, l)
    true, _ = causal.masked_readout(tiny_esmc, input_ids, attention_mask, positions, tiny_esmc.tokenizer.mask_token_id)
    assert report["readout"]["intact"]["loss"] == pytest.approx(float(-true.double().mean()), rel=1e-4)
    assert report["readout"]["weak"]["loss"] != report["readout"]["intact"]["loss"]
