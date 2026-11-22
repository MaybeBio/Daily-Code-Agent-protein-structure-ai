"""The gains inside the block: states chosen on validation, the stream around the chosen block, and the table's rule."""

from __future__ import annotations

import pandas as pd

from pathlib import Path

from plm_interpretability import cross_model


def summary(task: str, states: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """A one-task summary of full-width probes read by trained probes on original inputs: state to (validation, test)."""
    rows = [{"task": task, "family": "full", "probe_name": name, "plm": "trained", "probe": "trained", "control": "original",
             "site": name.split(":")[0], "layer": int(name.split(":")[1]), "validation_score": validation, "full": test}
            for name, (validation, test) in states.items()]
    return pd.DataFrame(rows)


# two blocks: the stream at depths 0 to 3, one attention state in block 0 and one feed-forward state in block 1
STATES = {"embedding:0": (0.10, 0.10), "resid_post:0": (0.30, 0.30), "resid_post:1": (0.50, 0.40), "final_norm:0": (0.45, 0.60),
          "k:0": (0.20, 0.90), "mlp_gate:1": (0.55, 0.70)}


def test_gaps_choose_on_validation_and_read_the_stream_around_the_block() -> None:
    gaps = cross_model.intra_block_gaps(summary("peptide", STATES), blocks=2)
    row = gaps.iloc[0]
    # the keys of block 0 test highest but validate lowest, so the gate of block 1 is chosen; the stream likewise
    assert (row["inside_site"], row["inside_layer"]) == ("mlp_gate", 1)
    assert (row["stream_site"], row["stream_layer"]) == ("resid_post", 1)
    # the gate of block 1 sits between the outputs of blocks 0 and 1, not beside the final norm
    assert row["same_depth_score"] == 0.40
    assert abs(row["lead"] - 0.30) < 1e-9 and abs(row["same_depth_lead"] - 0.30) < 1e-9


def test_gap_table_keeps_only_tasks_past_both_leads(tmp_path: Path) -> None:
    small = {**STATES, "mlp_gate:1": (0.55, 0.43)}  # leads the stream around its block by 0.03 only
    gaps = {model: pd.concat([cross_model.intra_block_gaps(summary("peptide", STATES), 2),
                              cross_model.intra_block_gaps(summary("lipidation", small), 2)])
            for model in cross_model.MODEL_COLORS}
    text = cross_model.gap_table(gaps, tmp_path / "gap_table.tex").read_text(encoding="utf-8")
    body = text.split(r"\toprule")[1]  # the caption names models too
    assert "Peptide" in body and "Lipidation" not in body
    assert body.index("ESMC-300") < body.index("ESMC-600") < body.index("ESMC-6B")  # the order of every figure


def test_kind_onsets_are_medians_over_each_kind_of_concept() -> None:
    profiles = pd.DataFrame({"category": ["function", "function", "function", "function", "composition"],
                             "onset_depth": [0.2, 0.4, 0.5, 0.9, 0.0]})
    onsets = cross_model.kind_onsets(profiles)
    # an even count takes the midpoint of its two middle onsets, as the medians the text quotes do
    assert abs(onsets["function"] - 0.45) < 1e-12 and onsets["composition"] == 0.0
