from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp
import torch

from dataclasses import dataclass
from torch import nn

from plm_interpretability.units import atlas, concept_groups
from plm_interpretability.units.capture import BlockReader, BlockStates


SEQUENCES = ("MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ", "MSDNELTRAVQEAGYKPTWLAHHGKEIRVAMDQ", "MAHHHHHHVGTGSNDDDDKSPDPKLMNQRSTVW",
             "MLEERLGLIEVQAPILSRVGDGTQDNLSGAEKA", "MGSSHHHHHHSSGLVPRGSHMASMTGGQQMGRG")


@dataclass(frozen=True)
class _Shard:
    split: str
    sequences: tuple[str, ...]
    labels: sp.csr_matrix


def _shard() -> _Shard:
    """Concept 0 on residues 5 to 14 of every protein; concept 1 on two residues of the second protein alone."""
    lengths = [len(sequence) for sequence in SEQUENCES]
    labels = sp.lil_matrix((sum(lengths), 2), dtype=np.float32)
    offsets = np.concatenate(([0], np.cumsum(lengths)))
    for protein in range(len(SEQUENCES)):
        labels[offsets[protein] + 5:offsets[protein] + 15, 0] = 1.0
    labels[offsets[1] + 2, 1] = 1.0
    labels[offsets[1] + 20, 1] = 1.0
    return _Shard("test", SEQUENCES, labels.tocsr())


def test_groups_and_carriers() -> None:
    table = pd.DataFrame({"layer": [0, 1, 2, 0, 1], "arm": ["mlp_native"] * 4 + ["residual"],
                          "concept": ["a", "a", "a", "b", "b"], "best_feature": [4, 9, 2, 7, 1],
                          "best_test_f1": [0.9, 0.4, 0.6, 0.55, 0.99]})
    groups = concept_groups.concept_groups(table)
    assert groups["a"]["layer"].tolist() == [0, 2] and groups["b"]["best_feature"].tolist() == [7]
    shard = _shard()
    lengths = [len(sequence) for sequence in SEQUENCES]
    assert {protein: residues.tolist() for protein, residues in concept_groups.carriers(shard.labels, lengths, 1).items()} == {1: [2, 20]}
    found = concept_groups.carriers(shard.labels, lengths, 0)
    assert sorted(found) == [0, 1, 2, 3, 4] and found[3].tolist() == list(range(5, 15))


def _firing_poles(model: nn.Module) -> list[int]:
    """In each block, the pole that fires on the most residues of the test proteins."""
    counts: dict[int, torch.Tensor] = {}

    def keep(states: BlockStates) -> None:
        is_open = states.gate > 0
        counts[states.block] = torch.cat(((is_open & (states.up > 0)).sum(dim=0), (is_open & (states.up < 0)).sum(dim=0)))

    input_ids, attention_mask, residues = atlas.encode_batch(model.tokenizer, list(SEQUENCES), torch.device("cpu"))
    with BlockReader(model, [0, 1, 2], keep) as reader:
        reader.run(input_ids, attention_mask, residues)
    return [int(counts[block].argmax()) for block in range(3)]


def test_a_group_is_set_against_its_placebos(tiny_esmc: nn.Module) -> None:
    poles = _firing_poles(tiny_esmc)
    per_concept = pd.DataFrame({"layer": [0, 1, 2, 0], "arm": ["mlp_native"] * 4, "concept": ["wide", "wide", "wide", "rare"],
                                "best_feature": [*poles, poles[0]], "best_test_f1": [0.6, 0.9, 0.7, 0.8]})
    table = concept_groups.run_concept_groups(tiny_esmc, per_concept, ("wide", "rare"), [_shard()], torch.device("cpu"),
                                              log=lambda _: None)
    rows = table.set_index("concept")
    assert rows.loc["rare", "status"] == "too_few" and rows.loc["rare", "proteins"] == 1
    wide = rows.loc["wide"]
    assert wide["status"] == "tested" and wide["members"] == 3 and wide["proteins"] == 5 and wide["masked"] == 5 * 8
    assert wide["firing_members"] == 3 and wide["blocks"] == "0,1,2" and wide["single_block"] == 1
    assert len(wide["placebo_drops"]) == 10 and np.isfinite(wide["drop"]) and np.isfinite(wide["outside_drop"])
    report = concept_groups.group_report(table)
    assert report["tested"] == 1 and report["statuses"] == {"tested": 1, "too_few": 1}
    assert report["median_excess"] == wide["drop"] - np.mean(wide["placebo_drops"])
    limited = concept_groups.run_concept_groups(tiny_esmc, per_concept, ("wide", "rare"), [_shard()], torch.device("cpu"),
                                                limit=1, log=lambda _: None)
    assert limited["concept"].tolist() == ["rare"]
