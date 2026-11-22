from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

import compendium_fixtures as fixtures

from collections.abc import Iterator
from pathlib import Path
from torch import nn

from fastplms.models.esm_plusplus.modeling_esm_plusplus_sae import ESMplusplusSAELayer, ESMplusplusSAEParams
from plm_interpretability.units import atlas, atlas_set, bases, coalitions, compendium, experiments, passes, rotation_search
from plm_interpretability.units.atlas import transformer_units
from plm_interpretability.units.poles import swiglu_poles


CPU = torch.device("cpu")
N_TERMS = len(fixtures.TERMS)


def _sae(seed: int = 7) -> nn.Module:
    generator = torch.Generator().manual_seed(seed)
    layer = ESMplusplusSAELayer(ESMplusplusSAEParams(d_model=64, codebook_dim=96, k=8, layer=2))
    with torch.no_grad():
        layer.W_enc.copy_(torch.randn(64, 96, generator=generator) / 8)
        layer.b_dec.copy_(torch.randn(64, generator=generator) / 10)
        layer.W_dec.copy_(torch.randn(96, 64, generator=generator) / 8)
    return layer


class _FirstBatch:
    """A pilot whose window is the first batch."""

    def watch(self, indices: range) -> Iterator[int]:
        yield indices[0]


PLAN = experiments.PassPlan("tiny", "tiny", (
    atlas.PlannedBasis(bases.Basis("native", 0), "contrast", "tiny"),
    atlas.PlannedBasis(bases.Basis("native", 1), "selection", "tiny"),
    atlas.PlannedBasis(bases.Basis("rotation", 1, seed=0), "contrast", "tiny"),
    atlas.PlannedBasis(bases.Basis("residual", 1), "selection", "tiny"),
    atlas.PlannedBasis(bases.Basis("sae", 1, sae="tiny"), "selection"),
), budget_hours=0.01)


@pytest.fixture(scope="module")
def inputs(tmp_path_factory: pytest.TempPathFactory) -> passes.PassInputs:
    directory = tmp_path_factory.mktemp("inputs")
    built, found = fixtures.build(n_clusters=90, members=3)
    passes.write_inputs(built, found.words, compendium.ancestor_matrix(found.words, fixtures.HIERARCHY), directory,
                        note="synthetic")
    return passes.PassInputs.read(directory)


def test_inputs_round_trip(inputs: passes.PassInputs) -> None:
    assert inputs.vocabulary_size == N_TERMS and len(inputs.digest) == 64
    assert set(inputs.term_columns) == {atlas_set.MIN_SELECTION, atlas_set.MIN_DOMINANCE}
    binding = 4  # the binding class, held by every protein
    assert binding in inputs.term_columns[atlas_set.MIN_SELECTION]
    tokens = inputs.tokens(atlas_set.MIN_SELECTION)
    assert [inputs.term_columns[atlas_set.MIN_SELECTION][int(token)] for token in tokens] == list(range(len(tokens)))
    assert inputs.ancestors.shape == (N_TERMS, N_TERMS)
    assert inputs.unit.shape == (N_TERMS,) and inputs.unit[-1] == -1  # the organism term
    assert inputs.scopes == {5: 15}  # the phosphoserine class, on serine


def test_pass_and_scores_end_to_end(tiny_esmc: nn.Module, inputs: passes.PassInputs, tmp_path: Path) -> None:
    output = tmp_path / "pass"
    receipt = passes.run_pass(tiny_esmc, {"tiny": _sae()}, {"tiny": (1, "stream")}, PLAN, inputs, output, CPU,
                              log=lambda message: None, token_budget=400)
    assert receipt["complete"] and receipt["atlas_set_digest"] == inputs.digest
    assert set(receipt["acceptance"]) == {planned.key for planned in PLAN.plan if planned.reference is not None}
    assert all(0 <= check["ks"] <= 1 for check in receipt["acceptance"].values())
    tables = passes.score_pass(PLAN, inputs, output)
    for planned in PLAN.plan:
        table = tables[planned.key]
        assert len(table) == np.load(output / "maxima" / f"{planned.stem}.npy", mmap_mode="r").shape[1]
        assert {"best_term", "margin", "held_out_auroc", "best_local_term", "dominant"} <= set(table.columns)
        assert (output / "scores" / f"{planned.stem}.parquet").exists()
        labels = output / "scores" / f"{planned.stem}.labels_local.parquet"
        assert labels.exists() == (planned.profile == "selection")
    rerun = passes.run_pass(tiny_esmc, {"tiny": _sae()}, {"tiny": (1, "stream")}, PLAN, inputs, output, CPU,
                            log=lambda message: None, token_budget=400)
    assert rerun["pass_digest"] == receipt["pass_digest"] and rerun["acceptance"] == receipt["acceptance"]


def test_random_initialization_reuses_the_trained_rates(tiny_esmc: nn.Module, inputs: passes.PassInputs, tmp_path: Path) -> None:
    trained = passes.run_pass(tiny_esmc, {"tiny": _sae()}, {"tiny": (1, "stream")}, PLAN, inputs, tmp_path / "trained",
                              CPU, log=lambda message: None, token_budget=400)
    rates = torch.load(tmp_path / "trained" / "calibration.pt", weights_only=True)["rates"]
    control = experiments.PassPlan("tiny_random", "tiny", (atlas.PlannedBasis(bases.Basis("native", 1), "contrast", "tiny"),),
                                   budget_hours=0.01, proteins=60, random_init=True, rates_from="tiny")
    torch.manual_seed(3)
    random_model = type(tiny_esmc)(tiny_esmc.config).eval()
    receipt = passes.run_pass(random_model, {}, {"tiny": (1, "stream")}, control, inputs, tmp_path / "random", CPU,
                              given_rates=rates, given_validation_rates=trained["validation_reference_rates"],
                              log=lambda message: None, token_budget=400)
    assert receipt["complete"] and abs(receipt["proteins"] - 60) <= 3
    assert receipt["validation_reference_rates"] == trained["validation_reference_rates"]
    random_tables = passes.score_pass(control, inputs, tmp_path / "random")
    key = "block1/native@tiny"
    trained_tables = passes.subset_scores(PLAN, 60, inputs, tmp_path / "trained", [key])
    assert len(trained_tables[key]) == len(random_tables[key])
    proteins = atlas_set.pass_proteins(inputs.frame).ordered()
    chosen = atlas_set.pass_proteins(inputs.frame, subset=60).ordered()
    rows = [proteins.accession.index(accession) for accession in chosen.accession]
    maxima = np.load(tmp_path / "trained" / "maxima" / "block1__native--tiny.npy")[rows]  # (n_subset, w)
    np.testing.assert_array_equal(trained_tables[key]["active_train_proteins"], (maxima[chosen.split == "train"] > 0).sum(axis=0))


def test_dictionary_test_and_rotation_search(tiny_esmc: nn.Module, inputs: passes.PassInputs, tmp_path: Path) -> None:
    saes, reads = {"stream": _sae(), "write": _sae(seed=9)}, {"stream": "stream", "write": "write"}
    output = tmp_path / "e8"
    report = passes.run_dictionary(tiny_esmc, saes, reads, 1, inputs, output, CPU, residues=600, sample=300, seeds=(1, 2),
                                   steps=20, token_budget=400, cofiring=True, keep_rotations=True, log=lambda message: None)
    proteins = atlas_set.residue_budget_proteins(inputs.frame, 600).ordered()
    total = int(proteins.lengths.sum())
    assert report["complete"] and report["residues"] == total >= 600
    states = atlas.calibration_states(tiny_esmc, tiny_esmc.tokenizer, proteins.sequence, [1], np.ones(total, dtype=bool),
                                      stream_blocks=[1], write_blocks=[1], token_budget=400, device=CPU)[1]
    poles = swiglu_poles(states.gate, states.up).main().double()  # (r, 2f)
    cofiring = np.load(output / "pole_cofiring.npy")  # (2f, 2f)
    np.testing.assert_allclose(cofiring, torch.corrcoef(poles.T).nan_to_num(0.0).numpy(), atol=1e-5)
    assert report["pole_cofiring"] == {"poles": poles.shape[1], "residues": total}
    for name, sae in saes.items():
        basis = bases.Basis("sae", 1, sae=name, reads=reads[name])
        latents = bases.basis_activations(basis, states, sae=sae).double()  # (r, m)
        expected = torch.corrcoef(torch.cat((latents, poles), dim=1).T)[:96, 96:].nan_to_num(0.0)  # (m, p)
        table = pd.read_parquet(output / f"{name}.parquet")
        np.testing.assert_allclose(table["best_correlation"], expected.max(dim=1).values.numpy(), atol=1e-6)
        np.testing.assert_allclose(table["mass"], latents.sum(dim=0).numpy(), rtol=1e-6)
        shares = report["dictionaries"][name]["native_shares"]
        assert 1 >= shares["0.5"] >= shares["0.7"] >= shares["0.9"] >= 0
        assert table["write_cosine"].abs().le(1 + 1e-9).all()
    search = report["rotation_search"]
    assert search["residues"] == 300 and [entry["seed"] for entry in search["searches"]] == [1, 2]
    assert all(entry["objective"] >= entry["start_objective"] and 0 < entry["recovery"] <= 1 for entry in search["searches"])
    assert np.load(output / "axis_recovery.npz")["2"].shape == (transformer_units(tiny_esmc),)
    # E13s reads the units in the search's coordinates: the kept standardization is the sample's, and each kept
    # rotation reaches the objective the search reported on it
    sample = states.product()[torch.from_numpy(atlas.residue_sample(total, 300, atlas_set.SUBSET_SEED))]  # (300, f)
    kept = np.load(output / "searched.npz")
    standard = rotation_search.standardization(sample)
    np.testing.assert_allclose(kept["mean"], standard.mean.numpy(), rtol=1e-5, atol=1e-7)
    np.testing.assert_allclose(kept["scale"], standard.scale.numpy(), rtol=1e-5)
    for entry in search["searches"]:
        rotation = torch.from_numpy(kept[f"rotation{entry['seed']}"]).double()  # (f, f)
        torch.testing.assert_close(rotation.T @ rotation, torch.eye(rotation.shape[0], dtype=torch.float64), atol=1e-5, rtol=0)
        objective = float(rotation_search.fourth_power_objective(standard.apply(sample), rotation))
        assert objective == pytest.approx(entry["objective"], rel=1e-4)
    partial = passes.run_dictionary(tiny_esmc, saes, reads, 1, inputs, tmp_path / "pilot", CPU, residues=600, sample=300,
                                    token_budget=400, pilot=_FirstBatch(), log=lambda message: None)
    assert not partial["complete"] and partial["search_pilot"]["steps"] == passes.PILOT_SEARCH_STEPS
    assert not (tmp_path / "pilot" / "report.json").exists()


def test_coalition_fits_read_held_out_residues_and_keep_the_dictionary_test_s_copies(tiny_esmc: nn.Module,
                                                                                    inputs: passes.PassInputs) -> None:
    sae = _sae(seed=9)
    frame, receipt = coalitions.run_coalitions(tiny_esmc, sae, 1, inputs, CPU, residues=2_000, token_budget=400, chunk=40,
                                               log=lambda message: None)
    proteins = atlas_set.residue_budget_proteins(inputs.frame, 2_000).ordered()
    total = int(proteins.lengths.sum())
    assert receipt["complete"] and receipt["residues"] == total == sum(receipt["half_residues"].values())
    assert min(receipt["half_residues"].values()) > 0.3 * total and len(frame) == 96 and receipt["alive"] <= 96
    # the copies over both halves are the dictionary test's
    states = atlas.calibration_states(tiny_esmc, tiny_esmc.tokenizer, proteins.sequence, [1], np.ones(total, dtype=bool),
                                      write_blocks=[1], token_budget=400, device=CPU)[1]
    poles = swiglu_poles(states.gate, states.up).main().double()  # (r, 2f)
    latents = bases.basis_activations(bases.Basis("sae", 1, sae="write", reads="write"), states, sae=sae).double()  # (r, m)
    expected = torch.corrcoef(torch.cat((latents, poles), dim=1).T)[:96, 96:].nan_to_num(0.0)  # (m, p)
    np.testing.assert_allclose(frame["best_correlation"], expected.max(dim=1).values.numpy(), atol=1e-4)
    np.testing.assert_allclose(frame["mass"], latents.sum(dim=0).numpy(), rtol=1e-4)
    alive = frame["native_fit_1"].notna().to_numpy()  # (m,)
    assert alive.sum() == receipt["alive"]
    for basis in coalitions.BASES:
        fitted = frame.loc[alive, [f"{basis}_fit_{size}" for size in coalitions.SIZES]].to_numpy()  # (m_alive, s)
        held = frame.loc[alive, [f"{basis}_held_out_{size}" for size in coalitions.SIZES]].to_numpy()  # (m_alive, s)
        assert (np.diff(fitted, axis=1) >= -1e-6).all() and (fitted <= 1 + 1e-6).all() and (np.abs(held) <= 1 + 1e-6).all()
    chosen = np.stack(frame.loc[alive, "native_poles"].to_numpy())  # (m_alive, k)
    assert chosen.shape[1] == max(coalitions.SIZES) and all(len(set(row)) == len(row) for row in chosen)
    report = coalitions.coalition_report(frame)
    shares = report["0.7"]["native"]["mass_share"]
    assert 0 <= shares["1"] <= shares["8"] <= shares["64"] <= 1
    partial, pilot_receipt = coalitions.run_coalitions(tiny_esmc, sae, 1, inputs, CPU, residues=2_000, token_budget=400,
                                                       pilot=_FirstBatch(), log=lambda message: None)
    assert partial is None and not pilot_receipt["complete"]
