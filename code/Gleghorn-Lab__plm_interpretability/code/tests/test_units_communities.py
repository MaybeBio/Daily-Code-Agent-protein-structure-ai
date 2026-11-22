from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from torch import nn

from plm_interpretability.units import atlas, causal, communities


SEQUENCES = ["MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ", "MSDNELTRAVQEAGYKPTWLAHHGKEIRVAMDQ", "MAHHHHHHVGTGSNDDDDKSPDPKLMNQRSTVW"]


def _batch(model: nn.Module) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    input_ids, attention_mask, _ = atlas.encode_batch(model.tokenizer, SEQUENCES, torch.device("cpu"))  # (b, l) each
    residues = [communities.prompt_residues(len(sequence), row) for row, sequence in enumerate(SEQUENCES)]
    return input_ids, attention_mask, communities.position_mask(residues, tuple(input_ids.shape))  # (b, l) each


def test_prompt_residues_are_seeded_by_protein() -> None:
    first = communities.prompt_residues(200, 7)
    assert np.array_equal(first, communities.prompt_residues(200, 7))
    assert not np.array_equal(first, communities.prompt_residues(200, 8))
    assert len(first) == 30 and len(np.unique(first)) == 30 and first.max() < 200
    assert len(communities.prompt_residues(3, 0)) == 1


def test_attribute_keeps_each_blocks_largest_scores(tiny_esmc: nn.Module) -> None:
    input_ids, attention_mask, positions = _batch(tiny_esmc)
    attribution = communities.attribute(tiny_esmc, input_ids, attention_mask, positions, tiny_esmc.tokenizer.mask_token_id)
    prompts, blocks = int(positions.sum()), len(causal.transformer_blocks(tiny_esmc))
    units = atlas.transformer_units(tiny_esmc)
    assert attribution.indices.shape == (prompts, blocks, communities.TOP_K)
    assert bool((attribution.scores[..., :-1] >= attribution.scores[..., 1:]).all()) and bool((attribution.scores >= 0).all())
    assert int(attribution.quadrants.max()) <= 3
    assert torch.equal(attribution.quadrant_counts.sum(dim=1), torch.full((blocks,), prompts * units))
    assert bool((attribution.log_prob <= 0).all())
    # The hooks are gone, and a second call gives the same units.
    assert not causal.transformer_blocks(tiny_esmc)[0].ffn[causal.SWIGLU_INDEX]._forward_hooks
    again = communities.attribute(tiny_esmc, input_ids, attention_mask, positions, tiny_esmc.tokenizer.mask_token_id)
    assert torch.equal(again.indices, attribution.indices)


def test_attribute_by_activation_keeps_the_largest_activations(tiny_esmc: nn.Module, tmp_path) -> None:
    input_ids, attention_mask, positions = _batch(tiny_esmc)
    mask_id = tiny_esmc.tokenizer.mask_token_id
    seen = []
    block = causal.transformer_blocks(tiny_esmc)[0]
    handle = block.ffn[causal.SWIGLU_INDEX].register_forward_hook(lambda module, args, output: seen.append(output.detach()))
    attribution = communities.attribute(tiny_esmc, input_ids, attention_mask, positions, mask_id, by="activation")
    handle.remove()
    expected = seen[0][positions].float().abs().topk(communities.TOP_K, dim=1)  # the first block's own output at the prompts
    assert torch.equal(attribution.indices[:, 0], expected.indices)
    torch.testing.assert_close(attribution.scores[:, 0], expected.values)
    # A pass by activation keeps the same prompts in the same rows as the pass by attribution, and stops at `parts`.
    proteins, device = np.array([2, 0, 1]), torch.device("cpu")
    for by in communities.SCORES:
        communities.run_attribution(tiny_esmc, SEQUENCES, proteins, device, tmp_path / by, token_budget=128, budget_seconds=1e9,
                                    part_proteins=2, target=0, by=by, log=lambda _: None)
    first, second = (communities.read_attribution(tmp_path / by) for by in communities.SCORES)
    assert np.array_equal(first["protein"], second["protein"]) and np.array_equal(first["residue"], second["residue"])
    cut = communities.run_attribution(tiny_esmc, SEQUENCES, proteins, device, tmp_path / "cut", token_budget=128, budget_seconds=1e9,
                                      part_proteins=2, target=0, by="activation", parts=1, log=lambda _: None)
    assert cut["parts"] == 1 and len(list((tmp_path / "cut").glob("part_*.npz"))) == 1


def test_a_single_target_is_exact_across_proteins(tiny_esmc: nn.Module) -> None:
    """One target a protein, differentiated in a batch, gives the scores of that protein run alone."""
    input_ids, attention_mask, positions = _batch(tiny_esmc)
    mask_id = tiny_esmc.tokenizer.mask_token_id
    targets = torch.zeros_like(positions)
    for row in range(len(SEQUENCES)):
        targets[row, positions[row].nonzero()[0]] = True
    batched = communities.attribute(tiny_esmc, input_ids, attention_mask, positions, mask_id, targets=targets)
    chosen = targets[positions]
    alone = communities.attribute(tiny_esmc, input_ids[:1], attention_mask[:1], positions[:1], mask_id, targets=targets[:1])
    torch.testing.assert_close(batched.scores[chosen][0], alone.scores[targets[:1][positions[:1]]][0], rtol=1e-3, atol=1e-6)
    overlap = communities.summed_against_single(tiny_esmc, SEQUENCES, [0, 1, 2], torch.device("cpu"))
    assert 0.0 <= overlap <= 1.0


def test_run_and_read_attribution_resume(tiny_esmc: nn.Module, tmp_path) -> None:
    proteins = np.array([2, 0, 1])
    receipt = communities.run_attribution(tiny_esmc, SEQUENCES, proteins, torch.device("cpu"), tmp_path, token_budget=128,
                                          budget_seconds=1e9, part_proteins=2, log=lambda _: None)
    assert receipt["parts"] == 2
    arrays = communities.read_attribution(tmp_path)
    expected = sum(len(communities.prompt_residues(len(sequence), row)) for row, sequence in enumerate(SEQUENCES))
    assert len(arrays["protein"]) == expected == arrays["indices"].shape[0]
    for protein in range(3):
        assert np.array_equal(np.sort(arrays["residue"][arrays["protein"] == protein]),
                              communities.prompt_residues(len(SEQUENCES[protein]), protein))
    again = communities.run_attribution(tiny_esmc, SEQUENCES, proteins, torch.device("cpu"), tmp_path, token_budget=128,
                                        budget_seconds=1e9, part_proteins=2, log=lambda _: None)
    assert again["prompts_this_run"] == 0 and again["parts"] == 2


def test_a_target_keeps_one_prompt_a_protein(tiny_esmc: nn.Module, tmp_path) -> None:
    proteins, device = np.array([0, 1, 2]), torch.device("cpu")
    for target in (0, 1):
        communities.run_attribution(tiny_esmc, SEQUENCES, proteins, device, tmp_path / f"target_{target:02d}", token_budget=128,
                                    budget_seconds=1e9, target=target, log=lambda _: None)
    arrays = communities.read_attribution(tmp_path)
    assert len(arrays["protein"]) == 6
    for protein in range(3):
        residues = communities.prompt_residues(len(SEQUENCES[protein]), protein)
        taken = residues[communities.prompt_order(len(residues), protein)[:2]]
        assert arrays["residue"][arrays["protein"] == protein].tolist() == taken.tolist()
    beyond = communities.run_attribution(tiny_esmc, SEQUENCES, proteins, device, tmp_path / "beyond", token_budget=128,
                                         budget_seconds=1e9, target=99, log=lambda _: None)
    assert beyond["prompts_this_run"] == 0 and beyond["parts"] == 1 and not list((tmp_path / "beyond").glob("part_*"))


def _planted(prompts: int = 4000, units: int = 16) -> np.ndarray:
    generator = np.random.default_rng(0)
    indices = np.stack([generator.permuted(np.tile(np.arange(units), (prompts, 1)), axis=1)[:, :2] for _ in range(2)], axis=1)
    together = generator.random(prompts) < 0.1
    indices[together, 0, 0], indices[together, 1, 0] = 3, 5
    for block, unit in ((0, 3), (1, 5)):  # the planted units appear only together
        stray = ~together[:, None] & (indices[:, block] == unit)
        indices[:, block][stray] = 0
        clash = together & (indices[:, block, 1] == unit)
        indices[clash, block, 1] = 1
    return indices.astype(np.int16)  # (p, 2, 2)


def test_cooccurrence_edges_find_a_planted_pair() -> None:
    indices = _planted()
    graph = communities.cooccurrence_edges(indices, 16, chunk=1000)
    ids = communities.neuron_ids(indices, 16)
    assert np.array_equal(graph.kept, np.bincount(ids.reshape(-1), minlength=32))
    edges = {tuple(edge): (z, count) for edge, z, count in zip(graph.edges.tolist(), graph.z, graph.count, strict=True)}
    z, count = edges[(3, 16 + 5)]
    assert count == int(((ids[:, 0] == 3).any(axis=1) & (ids[:, 1] == 21).any(axis=1)).sum()) and z > 50
    assert all(first < second for first, second in edges)
    assert not np.isin(graph.always_on, [3, 21]).any()


def test_shuffled_communities_keep_blocks_and_sizes() -> None:
    found = [np.array([0, 1, 16, 17]), np.array([2, 18]), np.array([3, 4, 19])]
    dealt = communities.shuffled_communities(found, 16, seed=1)
    for before, after in zip(found, dealt, strict=True):
        assert np.array_equal(np.bincount(before // 16, minlength=2), np.bincount(after // 16, minlength=2))
    assert np.array_equal(np.sort(np.concatenate(dealt)), np.sort(np.concatenate(found)))


def test_candidates_and_subspans() -> None:
    found = [np.array([0, 1, 2]), np.array([0, 5]), np.array([9, 10])]
    attributed = np.array([[0, 1, 5], [9, 3, 4], [6, 7, 8]])
    chosen = communities.candidates(attributed, found, 16, limit=2)
    assert chosen[0].tolist() == [1, 0] and chosen[1].tolist() == [2] and chosen[2].tolist() == []
    assert communities.subspans([4]) == [(4,)]
    assert communities.subspans([1, 3]) == [(1, 3), (1,), (3,)]
    assert communities.subspans([0, 1, 2, 3, 5, 7, 8, 9]) == [
        (0, 1, 2, 3, 5, 7, 8, 9), (0, 1, 2, 3), (5, 7, 8, 9), (0, 1), (2, 3), (5, 7), (8, 9)]


def test_evaluate_edits_only_the_listed_units(tiny_esmc: nn.Module) -> None:
    units = atlas.transformer_units(tiny_esmc)
    proteins = [0, 1, 2]
    column = int(communities.prompt_residues(len(SEQUENCES[1]), 1)[0]) + 1
    every = np.arange(units, 2 * units)  # block 1's units
    rows = [
        communities.Intervention(1, column),
        communities.Intervention(1, column, (1,), every, keep=True),  # every unit kept: nothing is set to zero
        communities.Intervention(1, column, (1,), every),  # every unit of block 1 set to zero
        communities.Intervention(1, column, (1,), np.zeros(0, dtype=np.int64), keep=True),  # the same, said the other way
        communities.Intervention(0, 3),
    ]
    out = communities.evaluate(tiny_esmc, SEQUENCES, proteins, rows, torch.device("cpu"), token_budget=128)
    torch.testing.assert_close(out[1], out[0])
    torch.testing.assert_close(out[3], out[2])
    assert float(communities.kl_divergence(out[:1], out[2:3])) > 0
    input_ids, attention_mask, positions = _batch(tiny_esmc)
    with torch.inference_mode():
        logits = tiny_esmc(input_ids=input_ids.masked_fill(positions, tiny_esmc.tokenizer.mask_token_id),
                           attention_mask=attention_mask).logits
    torch.testing.assert_close(out[0], torch.log_softmax(logits[1, column].float(), dim=-1), rtol=1e-4, atol=1e-5)
    assert not causal.transformer_blocks(tiny_esmc)[1].ffn[causal.SWIGLU_INDEX]._forward_hooks


def test_run_tests_and_leave_one_out(tiny_esmc: nn.Module) -> None:
    units = atlas.transformer_units(tiny_esmc)
    input_ids, attention_mask, positions = _batch(tiny_esmc)
    attribution = communities.attribute(tiny_esmc, input_ids, attention_mask, positions, tiny_esmc.tokenizer.mask_token_id)
    attributed = communities.neuron_ids(attribution.indices, units).reshape(len(attribution.indices), -1).numpy()  # (s, n * k)
    where = positions.nonzero()
    prompts = pd.DataFrame({"protein": where[:, 0].numpy(), "column": where[:, 1].numpy(), "attributed": list(attributed)})
    # One community of every unit: its removal is the layers' removal, and keeping it changes nothing.
    whole = [np.arange(3 * units)]
    frame, tested = communities.run_tests(tiny_esmc, SEQUENCES, [0, 1, 2], prompts, {"discovered": whole}, np.zeros(0, dtype=np.int64),
                                          units, torch.device("cpu"), token_budget=256, budget_seconds=1e9, chunk=4,
                                          log=lambda _: None)
    assert tested == len(prompts) and set(frame["blocks"]) == {3, 2, 1}
    ran = frame[frame["layer_necessity"] >= communities.NECESSITY]
    torch.testing.assert_close(torch.tensor(ran["necessity"].to_numpy()), torch.tensor(ran["layer_necessity"].to_numpy()),
                               rtol=1e-4, atol=1e-5)
    assert bool((ran["sufficiency"].abs() < 1e-5).all()) and bool(ran["explains"].all())
    assert frame.loc[frame["layer_necessity"] < communities.NECESSITY, "necessity"].isna().all()
    report = communities.coverage(frame, tested)
    assert set(report["discovered"]) == {"1", "4", "12"} and report["discovered"]["4"] == 0.0
    small = [np.array([0, units, 2 * units])]
    forced = frame.assign(explains=True, span="0,1,2", necessity=1.0)
    alone = communities.leave_one_out(tiny_esmc, SEQUENCES, [0, 1, 2], prompts, forced, small, units, torch.device("cpu"),
                                      token_budget=256, per_community=3)
    assert alone["unit"].tolist() == [0, units, 2 * units] and bool((alone["median_alone"] >= -1e-6).all())


def test_leiden_separates_two_cliques() -> None:
    first, second = np.arange(0, 5), np.arange(10, 15)
    edges = np.array([[a, b] for group in (first, second) for a in group for b in group if a < b] + [[4, 10]])
    z = np.array([40.0] * (len(edges) - 1) + [9.0])
    graph = communities.Graph(edges, z, np.full(len(edges), 9), np.zeros(32, dtype=np.int64), np.zeros(0, dtype=np.int64), 100)
    found, report = communities.leiden_communities(graph, resolutions=(16.0, 32.0))
    assert sorted(tuple(members) for members in found) == [tuple(first), tuple(second)]
    assert report[0]["kept"] == 2 and report[1]["new"] == 0
