from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp
import torch

from collections.abc import Callable, Iterator
from torch import nn
from transformers import EsmConfig, EsmForMaskedLM, EsmTokenizer

from plm_interpretability.units import atlas, bases, capture, retest, rotation_search


ESM_VOCABULARY = ["<cls>", "<pad>", "<eos>", "<unk>", "L", "A", "G", "V", "S", "E", "R", "T", "I", "D", "P", "K", "Q", "N",
                  "F", "Y", "M", "H", "W", "C", "X", "B", "U", "Z", "O", ".", "-", "<null_1>", "<mask>"]


def _proteins(seed: int, lengths: list[int], domain_level: np.ndarray) -> sp.csr_matrix:
    """InterPLM-style labels for consecutive proteins: residue-level columns 0 or 1, domain-level columns numbering
    each domain from 1 across the whole shard."""
    # domain_level: (C,)
    rng = np.random.default_rng(seed)
    columns, counters = [], {}
    for length in lengths:
        block = np.zeros((length, len(domain_level)), dtype=np.uint32)  # (l, C)
        for concept, spans in enumerate(domain_level):
            if not spans:
                block[:, concept] = rng.random(length) < 0.2
                continue
            for _ in range(rng.integers(0, 3)):
                start = rng.integers(0, length - 3)
                counters[concept] = counters.get(concept, 0) + 1
                block[start:start + rng.integers(2, 6), concept] = counters[concept]
        columns.append(block)
    return sp.csr_matrix(np.vstack(columns))  # (n, C)


def _reference_counts(scaled: np.ndarray, labels: np.ndarray, thresholds: tuple[float, ...]) -> tuple[np.ndarray, ...]:
    """InterPLM's tp, fp and tp_per_domain, written out as its loops define them."""
    # scaled: (n, F); labels: (n, C)
    concepts, features = labels.shape[1], scaled.shape[1]
    tp, fp, domains = (np.zeros((concepts, features, len(thresholds))) for _ in range(3))
    for index, threshold in enumerate(thresholds):
        on = (scaled > threshold).astype(float)  # (n, F)
        for concept in range(concepts):
            label = labels[:, concept]  # (n,)
            tp[concept, :, index] = (on * (label > 0)[:, None]).sum(axis=0)
            fp[concept, :, index] = (on * (label == 0)[:, None]).sum(axis=0)
            for feature in range(features):
                hit = on[:, feature] * label  # (n,)
                domains[concept, feature, index] = len(set(hit[hit != 0].tolist()))
    return tp, fp, domains  # (C, F, T) each


def _block_states(model: nn.Module, tokenizer: EsmTokenizer, sequences: tuple[str, ...], token_budget: int) -> tuple[torch.Tensor, torch.Tensor]:
    """Block 3's stream and feed-forward input at every residue, in protein order, read in the batches `stream_arms`
    reads. A padded batch of other proteins moves a state in its last float bits, which can move a residue across a
    threshold, so the direct reading runs the same forward passes as the streamed one."""
    lengths = [len(sequence) for sequence in sequences]
    offsets = np.concatenate(([0], np.cumsum(lengths)))  # (p + 1,)
    rows, residuals, inputs = [], [], []
    for proteins in retest.protein_batches(lengths, token_budget):
        tokens = retest.encode_sequences(tokenizer, [sequences[protein] for protein in proteins], "cpu")
        with retest.EsmTaps(model, (3,)) as taps:
            residual, pre = taps.run(*tokens)[3]  # (n_batch, d), (n_batch, m)
        rows.append(np.concatenate([np.arange(offsets[protein], offsets[protein + 1]) for protein in proteins]))  # (n_batch,)
        residuals.append(residual)
        inputs.append(pre)
    order = torch.from_numpy(np.argsort(np.concatenate(rows)))  # (n,)
    return torch.cat(residuals)[order], torch.cat(inputs)[order]  # (n, d), (n, m)


def test_counts_and_f1_follow_interplm_definitions() -> None:
    domain_level = np.array([False, True, False, True])
    lengths = [30, 25, 40, 18, 27]
    labels = _proteins(0, lengths, domain_level)  # (n, C)
    scaled = np.random.default_rng(1).random((sum(lengths), 6)) ** 2  # (n, F)
    counts = retest.ConceptCounts(4, 6)
    offsets = np.cumsum([0, *lengths])
    for rows in (np.arange(offsets[0], offsets[2]), np.arange(offsets[2], offsets[5])):  # batches of whole proteins
        counts.update(torch.from_numpy(scaled[rows]).float(), retest.batch_labels(labels[rows], domain_level), chunk=4)
    dense = labels.toarray()  # (n, C)
    tp, fp, domains = _reference_counts(scaled.astype(np.float32), dense, retest.THRESHOLDS)
    np.testing.assert_array_equal(counts.positive.numpy(), tp)
    np.testing.assert_array_equal(counts.fired.numpy()[None] - counts.positive.numpy(), fp)
    np.testing.assert_array_equal(counts.domains.numpy()[domain_level], domains[domain_level])
    concepts = retest.ConceptSet(("a", "b", "c", "d"), domain_level, {"valid": (dense > 0).sum(axis=0)},
                                 {"valid": dense.max(axis=0)})
    present, f1, f1_domain = retest.f1_scores(counts, concepts, "valid")
    for concept, feature, index in zip(*np.nonzero(tp), strict=True):
        precision = tp[concept, feature, index] / (tp[concept, feature, index] + fp[concept, feature, index])
        recall = tp[concept, feature, index] / concepts.positives["valid"][concept]
        per_domain = domains[concept, feature, index] / concepts.domains["valid"][concept] if domain_level[concept] else recall
        assert bool(present[concept, feature, index])
        assert float(f1[concept, feature, index]) == pytest.approx(2 * precision * recall / (precision + recall))
        expected = 2 * precision * per_domain / (precision + per_domain) if precision + per_domain > 0 else 0.0
        assert float(f1_domain[concept, feature, index]) == pytest.approx(expected)
    assert int(present.sum()) == int((tp > 0).sum())


def _interplm_frame(present: torch.Tensor, f1: torch.Tensor, f1_domain: torch.Tensor, names: list[str]) -> pd.DataFrame:
    """`calculate_metrics`'s rows: one per concept, feature and threshold with a true positive."""
    # present, f1, f1_domain: (C, F, T)
    concept, feature, threshold = torch.nonzero(present, as_tuple=True)
    return pd.DataFrame({"concept": [names[index] for index in concept.tolist()], "feature": feature.numpy(),
                         "threshold_pct": threshold.numpy(), "f1": f1[present].numpy(), "f1_per_domain": f1_domain[present].numpy()})


def _interplm_report(valid: pd.DataFrame, test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """`report_metrics`'s two readings, as its pandas code reads them."""
    valid = valid[~valid["concept"].str.contains("amino_acid", case=False)]
    top = valid.sort_values(by=["f1_per_domain", "f1"], ascending=False).drop_duplicates("concept")[["feature", "concept"]]
    matched = pd.merge(test, top, on=["feature", "concept"], how="inner")
    best = matched.sort_values(["f1_per_domain", "f1"], ascending=False).drop_duplicates(subset="concept", keep="first")
    pairs = valid[valid["f1_per_domain"] > 0.5].drop_duplicates(subset=["feature", "concept"])[["concept", "feature"]]
    held = pd.merge(test, pairs, on=["feature", "concept"], how="inner")
    held = held[held["f1_per_domain"] > 0.5].drop_duplicates(subset=["feature", "concept"])
    return best, held


def test_report_reads_like_interplm_report_metrics() -> None:
    rng = np.random.default_rng(2)
    names = ["Helix", "Binding site_ATP", "amino_acid_A", "Domain_kinase", "Motif_x"]
    arrays = []
    for _ in retest.SPLITS:
        present = torch.from_numpy(rng.random((5, 40, 5)) < 0.3)  # (C, F, T)
        f1 = torch.from_numpy(rng.random((5, 40, 5)))  # (C, F, T)
        f1_domain = torch.from_numpy(rng.random((5, 40, 5)) * 0.9)  # (C, F, T)
        arrays.append((present, f1, f1_domain))
    concepts = retest.ConceptSet(tuple(names), np.zeros(5, dtype=bool), {}, {})
    for subset in (np.arange(40), np.arange(10, 25)):
        report = retest.interplm_report(arrays[0], arrays[1], concepts.reported, features=subset)
        best, held = _interplm_report(*(_interplm_frame(present[:, subset], f1[:, subset], f1_domain[:, subset], names)
                                        for present, f1, f1_domain in arrays))
        assert report.features == len(subset)
        for index, name in enumerate(names):
            row = best[best["concept"] == name]
            if row.empty:
                assert np.isnan(report.best_test_f1[index])
                continue
            assert report.best_test_f1[index] == pytest.approx(row["f1_per_domain"].item())
            assert report.best_feature[index] == subset[row["feature"].item()]
        expected = {(subset[feature], names.index(concept)) for concept, feature in zip(held["concept"], held["feature"], strict=True)}
        assert {tuple(pair) for pair in report.pairs.tolist()} == expected and expected
        assert np.isnan(report.best_test_f1[2]) and report.best_feature[2] == -1


def test_ranges_scale_like_interplm_and_shuffling_permutes_every_tensor() -> None:
    ranges = retest.FeatureRanges()
    values = torch.tensor([[-1.0, 0.0, 2.0], [3.0, 0.0, 4.0]])  # (n, F)
    for arm in ("residual", "mlp_poles"):
        ranges.update((1, arm), values)
    torch.testing.assert_close(ranges.scale((1, "residual"), values), torch.tensor([[0.0, 0.0, 0.0], [1.0, 0.0, 1.0]]))
    torch.testing.assert_close(ranges.scale((1, "mlp_poles"), values), torch.tensor([[-1 / 3, 0.0, 0.5], [1.0, 0.0, 1.0]]))
    model = nn.Sequential(nn.Linear(4, 3), nn.Linear(3, 2))
    shuffled = retest.shuffled_copy(model, seed=5)
    for original, copy in zip(model.parameters(), shuffled.parameters(), strict=True):
        torch.testing.assert_close(original.detach().reshape(-1).sort().values, copy.detach().reshape(-1).sort().values)
    assert not torch.equal(model[0].weight, shuffled[0].weight)
    torch.testing.assert_close(retest.poles(torch.tensor([[1.0, -2.0]])), torch.tensor([[1.0, 0.0, 0.0, 2.0]]))


@pytest.fixture(scope="module")
def tiny_esm2(tmp_path_factory: pytest.TempPathFactory) -> tuple[nn.Module, EsmTokenizer]:
    vocabulary = tmp_path_factory.mktemp("esm") / "vocab.txt"
    vocabulary.write_text("\n".join(ESM_VOCABULARY), encoding="utf-8")
    torch.manual_seed(0)
    config = EsmConfig(vocab_size=len(ESM_VOCABULARY), hidden_size=16, num_hidden_layers=3, num_attention_heads=2,
                       intermediate_size=32, max_position_embeddings=64, pad_token_id=1, mask_token_id=32,
                       position_embedding_type="rotary", emb_layer_norm_before=False, token_dropout=False)
    return EsmForMaskedLM(config).eval(), EsmTokenizer(str(vocabulary))


def test_taps_read_layer_outputs_and_intermediate_pre_activations(tiny_esm2: tuple[nn.Module, EsmTokenizer]) -> None:
    model, tokenizer = tiny_esm2
    sequences = ["MKVLA", "GH", "ACDEFGHIK"]
    inputs = retest.encode_sequences(tokenizer, sequences, "cpu")
    with retest.EsmTaps(model, (1, 3)) as taps:
        states = taps.run(*inputs)
    assert states[1][0].shape == (16, 16) and states[3][1].shape == (16, 32)
    activations: dict[str, torch.Tensor] = {}
    handle = model.esm.encoder.layer[0].intermediate.register_forward_hook(
        lambda _module, _inputs, output: activations.__setitem__("gelu", output))
    with torch.no_grad():
        output = model.esm(input_ids=inputs[0], attention_mask=inputs[1])
    handle.remove()
    torch.testing.assert_close(nn.functional.gelu(states[1][1]), activations["gelu"][inputs[2]])
    torch.testing.assert_close(states[3][0], output.last_hidden_state[inputs[2]])
    first = model.esm(input_ids=inputs[0][:1, :7], attention_mask=inputs[1][:1, :7]).last_hidden_state[0, 1:6]  # (5, d)
    with retest.EsmTaps(model, (3,)) as taps:
        alone = taps.run(inputs[0][:1, :7], inputs[1][:1, :7], inputs[2][:1, :7])
    torch.testing.assert_close(alone[3][0], first.detach(), atol=1e-5, rtol=1e-5)
    torch.testing.assert_close(states[3][0][:5], first.detach(), atol=1e-5, rtol=1e-5)


def test_two_passes_count_every_arm_as_a_direct_reading_does(tiny_esm2: tuple[nn.Module, EsmTokenizer]) -> None:
    model, tokenizer = tiny_esm2
    rng = np.random.default_rng(3)
    domain_level = np.array([False, True, True])
    shards = []
    for split, seed in (("valid", 4), ("test", 5)):
        sequences = tuple("".join(rng.choice(list("ACDEFGHIKLMNPQRSTVWY"), size=int(length)))
                          for length in rng.integers(8, 30, size=6))
        shards.append(retest.RetestShard(split, sequences, _proteins(seed, [len(sequence) for sequence in sequences], domain_level)))
    shuffled = retest.shuffled_copy(model)
    sae = nn.Sequential(nn.Linear(16, 24), nn.ReLU())

    def stream() -> retest.Iterator[retest.RetestBatch]:
        return retest.stream_arms(model, shuffled, tokenizer, (1, 3), shards, {3: sae}, device="cpu", token_budget=80)

    ranges = retest.collect_ranges(stream())
    concepts = retest.ConceptSet(("Helix", "Domain_a", "Region_b"), domain_level,
                                 {shard.split: (shard.labels.toarray() > 0).sum(axis=0) for shard in shards},
                                 {shard.split: shard.labels.toarray().max(axis=0) for shard in shards})
    counts = retest.collect_counts(stream(), shards, ranges, concepts)
    arms = {arm for _, arm, _ in counts}
    assert arms == {"residual", "residual_poles", "mlp_poles", "mlp_rotation0", "mlp_rotation1", "mlp_rotation2",
                    "shuffled_mlp_poles", "sae"} - set() and (1, "sae", "valid") not in counts
    for shard in shards:
        residual, pre = _block_states(model, tokenizer, shard.sequences, 80)  # (n, d), (n, m)
        for arm, values in (("residual", residual), ("mlp_poles", retest.poles(pre)), ("sae", sae(residual))):
            scaled = ranges.scale((3, arm), values.detach()).numpy()  # (n, F)
            tp, fp, domains = _reference_counts(scaled, shard.labels.toarray(), retest.THRESHOLDS)
            got = counts[3, arm, shard.split]
            np.testing.assert_array_equal(got.positive.numpy(), tp)
            np.testing.assert_array_equal(got.fired.numpy()[None] - got.positive.numpy(), fp)
            np.testing.assert_array_equal(got.domains.numpy()[domain_level], domains[domain_level])
    summary, per_concept = retest.retest_tables(counts, concepts)
    assert set(summary["arm"]) == arms | {"mlp_positive"} and set(per_concept["concept"]) == set(concepts.names)
    positive = summary[(summary["arm"] == "mlp_positive") & (summary["layer"] == 3)].iloc[0]
    assert positive["features"] == 32 and (summary["share"] <= 1).all()


def test_esmc_passes_count_every_arm_as_a_direct_reading_does(tiny_esmc: nn.Module, tiny_sae: Callable[..., nn.Module]) -> None:
    rng = np.random.default_rng(6)
    domain_level = np.array([False, True, True])
    shards = []
    for split, seed in (("valid", 7), ("test", 8)):
        sequences = tuple("".join(rng.choice(list("ACDEFGHIKLMNPQRSTVWY"), size=int(length)))
                          for length in rng.integers(8, 30, size=6))
        shards.append(retest.RetestShard(split, sequences, _proteins(seed, [len(sequence) for sequence in sequences], domain_level)))
    shuffled = retest.shuffled_copy(tiny_esmc)
    sae = tiny_sae()

    def stream() -> Iterator[retest.RetestBatch]:
        return retest.stream_esmc_arms(tiny_esmc, shuffled, (0, 2), shards, {2: {"tiny": sae}}, device="cpu", token_budget=80)

    ranges = retest.collect_ranges(stream())
    concepts = retest.ConceptSet(("Helix", "Domain_a", "Region_b"), domain_level,
                                 {shard.split: (shard.labels.toarray() > 0).sum(axis=0) for shard in shards},
                                 {shard.split: shard.labels.toarray().max(axis=0) for shard in shards})
    counts = retest.collect_counts(stream(), shards, ranges, concepts)
    arms = {arm for _, arm, _ in counts}
    assert arms == {"residual", "residual_poles", "mlp_native", "mlp_poles", "mlp_rotation0", "mlp_rotation1",
                    "mlp_rotation2", "shuffled_mlp_poles", "sae:tiny"} and (0, "sae:tiny", "valid") not in counts
    rotation = retest.haar_rotation(256, 1, dtype=torch.float32)  # (f, f)
    for shard in shards:
        # Read in the stream's own batches, whose padding a float32 forward is not exactly invariant to.
        lengths = [len(sequence) for sequence in shard.sequences]
        offsets = np.concatenate(([0], np.cumsum(lengths)))  # (p + 1,)
        direct: dict[str, torch.Tensor] = {}
        for proteins in retest.protein_batches(lengths, 80):
            rows = torch.as_tensor(np.concatenate([np.arange(offsets[protein], offsets[protein + 1]) for protein in proteins]))  # (n_b,)

            def read(states: capture.BlockStates, rows: torch.Tensor = rows) -> None:  # rows: (n_b,)
                arms = {"residual": states.stream.float(),  # (n_b, d)
                        "mlp_native": bases.basis_activations(bases.Basis("native", 2), states),  # (n_b, 2f)
                        "mlp_rotation1": bases.basis_activations(bases.Basis("rotation", 2, seed=1), states, rotation=rotation),
                        "sae:tiny": bases.basis_activations(bases.Basis("sae", 2, sae="tiny"), states, sae=sae)}  # (n_b, c)
                for arm, values in arms.items():
                    direct.setdefault(arm, torch.zeros(int(offsets[-1]), values.shape[1]))[rows] = values

            with capture.BlockReader(tiny_esmc, [2], read, stream_blocks=[2]) as reader:
                reader.run(*atlas.encode_batch(tiny_esmc.tokenizer, [shard.sequences[protein] for protein in proteins],
                                               torch.device("cpu")))
        for arm, values in direct.items():
            scaled = ranges.scale((2, arm), values).numpy()  # (n, F)
            tp, fp, domains = _reference_counts(scaled, shard.labels.toarray(), retest.THRESHOLDS)
            got = counts[2, arm, shard.split]
            np.testing.assert_array_equal(got.positive.numpy(), tp, err_msg=arm)
            np.testing.assert_array_equal(got.fired.numpy()[None] - got.positive.numpy(), fp, err_msg=arm)
            np.testing.assert_array_equal(got.domains.numpy()[domain_level], domains[domain_level], err_msg=arm)
    summary, _ = retest.retest_tables(counts, concepts)
    assert set(summary["layer"]) == {0, 2} and (summary["share"] <= 1).all()


def test_esmc_passes_keep_the_planned_arms_and_read_write_saes(tiny_esmc: nn.Module, tiny_sae: Callable[..., nn.Module]) -> None:
    rng = np.random.default_rng(9)
    sequences = tuple("".join(rng.choice(list("ACDEFGHIKLMNPQRSTVWY"), size=int(length))) for length in rng.integers(8, 30, size=5))
    lengths = [len(sequence) for sequence in sequences]
    shard = retest.RetestShard("valid", sequences, _proteins(10, lengths, np.array([False, True, True])))
    sae = tiny_sae()
    kept = ("residual", "mlp_poles", "mlp_rotation0")
    batches = list(retest.stream_esmc_arms(tiny_esmc, None, (0, 2), [shard], {2: {"tiny": sae}}, device="cpu", token_budget=80,
                                           rotation_seeds=(0,), sae_reads={"tiny": "write"}, arms=kept))
    assert all(set(batch.arms) == set(kept) for batch in batches if batch.layer == 0)
    assert all(set(batch.arms) == {*kept, "sae:tiny"} for batch in batches if batch.layer == 2)
    for batch, proteins in zip([batch for batch in batches if batch.layer == 2], retest.protein_batches(lengths, 80), strict=True):
        direct: dict[str, torch.Tensor] = {}

        def read(states: capture.BlockStates) -> None:
            direct["sae"] = bases.basis_activations(bases.Basis("sae", 2, sae="tiny", reads="write"), states, sae=sae)  # (n_b, c)

        with capture.BlockReader(tiny_esmc, [2], read, write_blocks=[2]) as reader:
            reader.run(*atlas.encode_batch(tiny_esmc.tokenizer, [sequences[protein] for protein in proteins], torch.device("cpu")))
        torch.testing.assert_close(batch.arms["sae:tiny"], direct["sae"])
    with pytest.raises(ValueError, match="not read"):
        next(retest.stream_esmc_arms(tiny_esmc, None, (2,), [shard], {}, device="cpu", token_budget=80,
                                     arms=("shuffled_mlp_poles",)))
    with pytest.raises(ValueError, match="not read"):
        next(retest.stream_esmc_arms(tiny_esmc, None, (2,), [shard], {}, device="cpu", token_budget=80, arms=("mlp_standard",)))


def test_esmc_passes_read_the_units_in_the_search_s_coordinates(tiny_esmc: nn.Module) -> None:
    rng = np.random.default_rng(11)
    sequences = tuple("".join(rng.choice(list("ACDEFGHIKLMNPQRSTVWY"), size=int(length))) for length in rng.integers(8, 30, size=4))
    lengths = [len(sequence) for sequence in sequences]
    shard = retest.RetestShard("valid", sequences, _proteins(12, lengths, np.array([False, True, True])))
    units = atlas.transformer_units(tiny_esmc)
    generator = torch.Generator().manual_seed(13)
    scale = torch.rand(units, generator=generator) + 0.5  # (f,)
    scale[3] = 0.0  # a unit constant over the search's sample
    standard = rotation_search.Standardization(torch.randn(units, generator=generator), scale)
    found = retest.haar_rotation(units, 5, dtype=torch.float32)  # (f, f), standing in for a searched rotation
    searched = {2: retest.SearchedBases(standard, {"start1": retest.haar_rotation(units, 1, dtype=torch.float32), "searched1": found})}
    kept = ("mlp_poles", "mlp_standard", "mlp_start1", "mlp_searched1")
    batches = list(retest.stream_esmc_arms(tiny_esmc, None, (2,), [shard], {}, device="cpu", token_budget=80,
                                           rotation_seeds=(), arms=kept, searched=searched))
    for batch, proteins in zip(batches, retest.protein_batches(lengths, 80), strict=True):
        assert set(batch.arms) == set(kept)
        direct: dict[str, torch.Tensor] = {}

        def read(states: capture.BlockStates) -> None:
            centered = (states.product().float() - standard.mean) / torch.where(scale > 0, scale, 1.0)  # (n_b, f)
            centered[:, 3] = 0.0
            direct["standard"], direct["searched"] = centered, centered @ found

        with capture.BlockReader(tiny_esmc, [2], read) as reader:
            reader.run(*atlas.encode_batch(tiny_esmc.tokenizer, [sequences[protein] for protein in proteins], torch.device("cpu")))
        for arm, values in (("mlp_standard", direct["standard"]), ("mlp_searched1", direct["searched"])):
            torch.testing.assert_close(batch.arms[arm], torch.cat((torch.relu(values), torch.relu(-values)), dim=1))
        assert batch.arms["mlp_standard"].shape == batch.arms["mlp_poles"].shape


def test_protein_batches_respect_the_token_budget() -> None:
    lengths = [10, 50, 3, 30, 28, 9]
    batches = retest.protein_batches(lengths, token_budget=64)
    assert sorted(np.concatenate(batches).tolist()) == list(range(6))
    for batch in batches:
        widest = max(lengths[protein] for protein in batch) + 2
        assert len(batch) == 1 or widest * len(batch) <= 64
    with pytest.raises(ValueError, match="rows for"):
        retest.RetestShard("valid", ("AC",), sp.csr_matrix(np.zeros((3, 1))))
