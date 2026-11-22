from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp
import torch

from pathlib import Path
from torch import nn

from plm_interpretability.units import atlas, attribution, concepts, intrinsic
from plm_interpretability.units.causal import transformer_blocks
from plm_interpretability.units.concepts import ConceptProteins, ConceptTask


CPU = torch.device("cpu")


def _terms() -> tuple[pd.DataFrame, sp.csr_matrix]:
    terms = pd.DataFrame({"token": [0, 1, 2, 3],
                          "term_id": ["av::go_mf::GO::GO:0000001", "av::go_mf::GO::GO:0000002",
                                      "av::interpro::InterPro::IPR000001", "av::go_mf::GO::GO:0000003"]})
    ancestors = sp.csr_matrix(np.array([[0, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]))  # 0 is 1's parent
    return terms, ancestors


def test_accessions_tokens_and_labeled_neurons() -> None:
    assert attribution.concept_accession("ATP binding [GO:0005524]") == "GO:0005524"
    assert attribution.concept_accession("IPR000008__c2_domain") == "IPR000008"
    assert attribution.concept_accession("class_0") is None
    terms, ancestors = _terms()
    assert attribution.concept_tokens(terms, ancestors, "GO:0000001").tolist() == [0, 1]
    assert attribution.concept_tokens(terms, ancestors, "IPR000001").tolist() == [2]
    assert attribution.concept_tokens(terms, ancestors, "GO:9999999").tolist() == []
    scores = pd.DataFrame({"pole": np.arange(6), "best_term": [1, 3, 0, 0, 2, 1], "best_auroc": [0.9, 0.9, 0.5, 0.7, 0.9, 0.8]})
    # Units 0 (pole 0) and 2 (pole 5, its negative pole) qualify; pole 2 is below the AUROC threshold, pole 3 is unit 0.
    assert attribution.labeled_neurons(scores, np.array([0, 1]), units=3).tolist() == [0, 2]


def test_a_blocks_mean_write_is_its_down_projection_of_the_mean_products(tiny_esmc: nn.Module, tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    sequences = sorted("".join(rng.choice(list(intrinsic.AMINO_ACIDS), size=int(rng.integers(15, 30)))) for _ in range(6))
    plan = concepts.ExtractionPlan(depths=(1,), all_blocks=True)
    concepts.ConceptExtraction(tiny_esmc, plan, sequences, tmp_path, CPU, log=lambda message: None).run()
    lengths = [len(sequence) for sequence in sequences]
    states = atlas.calibration_states(tiny_esmc, tiny_esmc.tokenizer, sequences, [0, 1], np.ones(sum(lengths), dtype=bool),
                                      write_blocks=[0, 1], device=CPU)
    bounds = np.concatenate(([0], np.cumsum(lengths)))  # (n + 1,)
    for block in (0, 1):
        mean_write = np.stack([states[block].write[start:stop].double().mean(dim=0).numpy()
                               for start, stop in zip(bounds[:-1], bounds[1:], strict=True)])  # (n, d)
        down = transformer_blocks(tiny_esmc)[block].ffn[3].weight.detach().double().numpy()  # (d, f)
        z_mean = np.asarray(concepts.read_feature(tmp_path, block, "z_mean"), dtype=np.float64)  # (n, f)
        np.testing.assert_allclose(z_mean @ down.T, mean_write, atol=1e-5)


def test_e9_finds_the_neuron_a_probe_reads(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    n, units, width = 600, 6, 4
    (tmp_path / "features").mkdir()
    z = {block: rng.laplace(size=(n, units)) for block in (0, 1)}  # (n, f) each
    down = {block: torch.from_numpy(rng.normal(size=(width, units))) for block in (0, 1)}  # (d, f) each
    stream = sum(z[block] @ down[block].numpy().T for block in (0, 1)) + 0.01 * rng.normal(size=(n, width))  # (n, d)
    for block in (0, 1):
        np.save(tmp_path / "features" / f"block{block}_z_mean.npy", z[block].astype(np.float32))
    np.save(tmp_path / "features" / "block1_stream_mean.npy", stream.astype(np.float32))
    labels = z[1][:, 2] > 0.5  # (n,), carried by block 1's unit 2
    rows = {"train": np.arange(0, 400), "validation": np.arange(400, 450), "test": np.arange(450, 600)}
    frames = {split: pd.DataFrame({"id": index.astype(str), "sequence": ["A"] * len(index),
                                   "label": [np.array([value], dtype=np.int8) for value in labels[index]]})
              for split, index in rows.items()}
    tasks = {"go": ConceptTask("go", "protein", "multilabel", ("binding [GO:0000001]",), frames)}
    proteins = ConceptProteins([f"P{row}" for row in range(n)], {"go": rows})
    terms, ancestors = _terms()
    scores = {block: pd.DataFrame({"pole": np.arange(2 * units), "best_term": [3] * (2 * units), "best_auroc": [0.9] * (2 * units)})
              for block in (0, 1)}
    scores[1].loc[2, "best_term"] = 1  # block 1's unit 2 is labeled with a child of the concept's term
    table = attribution.run_e9(tmp_path, proteins, tasks, 1, scores, down, 1.0, terms, ancestors, log=lambda message: None)
    row = table.iloc[0]
    assert row["accession"] == "GO:0000001" and row["labeled_neurons"] == 1
    assert abs(row["neuron_share"] - 1) < 0.05  # the stream is all neurons here
    assert row["labeled_share"] > row["null_high"] and row["null_rank"] == 0.0
