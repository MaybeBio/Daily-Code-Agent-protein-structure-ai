"""Two readings of the survey added for a review of the manuscript, from the tables the states figure reads.

    python -m plm_interpretability.survey_checks --survey SURVEY --out FOLDER

`SURVEY` is the survey's archive as `state_figure` reads it. Neither reading was fixed in advance.

- Onsets (`onsets.csv`). A task's onset is the first relative depth at which its stream score comes within 5% of its
  highest. The archived onsets are reproduced, then recomputed on a running mean over three depths and as the first
  depth from which the score stays within 5% of its highest for three depths in a row, which answers whether a single
  noisy depth sets an onset.
- Pooled or tokens (`sites.csv`). For each residue-level task, whose probes read unpooled tokens, and each pooled
  InterPro site task, the stream's state and the query or key state are each chosen on validation and their test
  scores set side by side, which answers whether attention's projections lead the stream only under pooling.

Symbols: d depths of one model's stream.
"""

from __future__ import annotations

import argparse
import json
import numpy as np
import pandas as pd

from collections.abc import Mapping
from pathlib import Path


STREAM = ("embedding", "resid_post", "final_norm")
PROJECTIONS = ("q", "k")
SHARE = 0.95  # an onset: the first depth within 5% of the highest score
WINDOW = 3  # depths in the running mean, and in a row for the persistent onset
RESIDUE_TASKS = ("functional_sites", "lipidation", "peptide", "phosphorylation", "post_translational_modification",
                 "secondary_structure", "ssp_q3", "ssp_q8", "topology")
POOLED_TASKS = ("interpro_binding_site", "interpro_active_site", "interpro_conserved_site")


def headline(summary: pd.DataFrame) -> pd.DataFrame:
    """The full-width probes of the trained model on original inputs."""
    kept = ((summary["plm"] == "trained") & (summary["probe"] == "trained") & (summary["control"] == "original")
            & (summary["family"] == "full"))
    return summary[kept]


def stream_curve(summary: pd.DataFrame, task: str, blocks: int) -> pd.DataFrame:
    """One task's stream scores by depth: the embedding at 0, block k's output at k + 1 and the final norm last."""
    curve = headline(summary)
    curve = curve[curve["site"].isin(STREAM) & (curve["task"] == task)].copy()
    curve["depth"] = np.where(curve["site"] == "embedding", 0,
                              np.where(curve["site"] == "final_norm", blocks + 1, curve["layer"] + 1))
    curve["relative_depth"] = curve["depth"] / (blocks + 1)
    return curve.sort_values("depth")


def onset(scores: np.ndarray, depths: np.ndarray) -> float:
    """The first depth at which the score comes within 5% of its highest."""
    # scores, depths: (d,)
    return float(depths[scores >= SHARE * scores.max()].min())


def running_mean(scores: np.ndarray) -> np.ndarray:
    """A centered mean over three depths, over the two that exist at either end."""
    # scores: (d,)
    padded = np.pad(scores.astype(np.float64), 1, constant_values=np.nan)  # (d + 2,)
    windows = np.lib.stride_tricks.sliding_window_view(padded, WINDOW)  # (d, 3)
    return np.nanmean(windows, axis=1)  # (d,)


def persistent_onset(scores: np.ndarray, depths: np.ndarray) -> float:
    """The first depth from which the score stays within 5% of its highest for three depths in a row, or to the end;
    NaN when no depth starts such a run."""
    # scores, depths: (d,)
    within = scores >= SHARE * scores.max()  # (d,)
    for index in range(len(within)):
        if within[index : index + WINDOW].all():
            return float(depths[index])
    return float("nan")


def onset_table(summaries: Mapping[str, pd.DataFrame], archived: pd.DataFrame, blocks: Mapping[str, int]) -> pd.DataFrame:
    """One row a model and task: its onset as archived and under the two smoother definitions."""
    # archived: Protify's `stream_profiles.csv`, indexed by model and task
    rows = []
    for model, summary in summaries.items():
        for task in sorted(summary["task"].unique()):
            if (model, task) not in archived.index:
                continue
            curve = stream_curve(summary, task, blocks[model])
            scores, depths = curve["full"].to_numpy(), curve["relative_depth"].to_numpy()  # (d,), (d,)
            raw = onset(scores, depths)
            assert abs(raw - archived.at[(model, task), "onset_depth"]) < 5e-4, f"{model} {task}: the onset is not the archived one."
            rows.append({"model": model, "task": task, "category": archived.at[(model, task), "category"], "raw": raw,
                         "running_mean": onset(running_mean(scores), depths), "persistent": persistent_onset(scores, depths)})
    return pd.DataFrame(rows)


def chosen(rows: pd.DataFrame) -> pd.Series:
    """The probe with the highest validation score."""
    return rows.loc[rows["validation_score"].idxmax()]


def site_table(summaries: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """One row a model and task: the validation-chosen stream state and query or key state, with their test scores."""
    rows = []
    for model, summary in summaries.items():
        table = headline(summary)
        for level, tasks in (("residue", RESIDUE_TASKS), ("pooled", POOLED_TASKS)):
            for task in tasks:
                probes = table[table["task"] == task]
                stream, projections = probes[probes["site"].isin(STREAM)], probes[probes["site"].isin(PROJECTIONS)]
                assert len(stream) and len(projections), f"{model} {task}: the stream or the projections were not probed."
                a, b = chosen(stream), chosen(projections)
                rows.append({"model": model, "task": task, "level": level, "stream_site": a["site"],
                             "stream_block": int(a["layer"]), "stream_score": float(a["full"]),
                             "projection_site": b["site"], "projection_block": int(b["layer"]),
                             "projection_score": float(b["full"])})
    return pd.DataFrame(rows)


def main() -> None:
    from . import archive, state_figure  # Protify's modules load only when the archive is read

    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--survey", type=Path, required=True, help="The survey's archive.")
    parser.add_argument("--out", type=Path, required=True, help="The folder for onsets.csv and sites.csv.")
    arguments = parser.parse_args()
    summaries = state_figure.survey_summaries(arguments.survey)
    profiles = arguments.survey / "analyses" / "final2" / "trends" / "stream_profiles.csv"
    onsets = onset_table(summaries, pd.read_csv(profiles).set_index(["model", "task"]), archive.BLOCKS)
    sites = site_table(summaries)
    arguments.out.mkdir(parents=True, exist_ok=True)
    onsets.to_csv(arguments.out / "onsets.csv", index=False)
    sites.to_csv(arguments.out / "sites.csv", index=False)
    medians = onsets.groupby(["model", "category"])[["raw", "running_mean"]].median()
    moved = (onsets["running_mean"] - onsets["raw"]).abs()  # (tasks,)
    persistent = (onsets["persistent"] - onsets["raw"]).abs()  # (tasks,), NaN where no run exists
    print(json.dumps({
        "onsets": int(len(onsets)), "running_mean_within_0.05": int((moved <= 0.05).sum()),
        "largest_change_of_a_kind_median": float((medians["running_mean"] - medians["raw"]).abs().max()),
        "persistent_moved_by_more_than_0.05": int((persistent > 0.05).sum()),
        "persistent_without_a_run": int(onsets["persistent"].isna().sum())}, indent=2))
    print(sites.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
