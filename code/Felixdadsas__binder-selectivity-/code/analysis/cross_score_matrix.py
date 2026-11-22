"""Binder x target cross-scoring table.

The core result of the project: binders designed against BNP, scored on ANP and on
the scrambled control, and vice versa. A diagonal that stands out from the
off-diagonal is discrimination; a flat table is not.

NOT RUNNABLE YET, on purpose. It needs two things that do not exist yet:

  1. The column names in BoltzGen's all_designs_metrics.csv, read off a real
     results file (`python analysis/scores.py --columns <csv>`), so that
     `scores.SCORE_COLUMN` can be filled in. Nothing here may guess them.
  2. Re-scoring runs: each target's designs folded against the *other* targets.
     The design runs alone only score each binder against its own target.

Read before using any number this produces: the values are structural confidence
scores (pTM / pAE / iPTM / RMSD), not affinities, and nothing in this project has
been experimentally validated. A table that discriminates shows that the
*pipeline's own scores* separate homologous targets, not that the designs bind
selectively.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import scores

TARGETS = ("bnp", "anp", "scr")


def cross_score_matrix(runs: dict[tuple[str, str], str | Path], column: str) -> pd.DataFrame:
    """Mean `column` for each (designed-against, scored-against) pair.

    `runs` maps (designed_for, scored_on) -> results CSV or run directory.
    Missing pairs come back as NaN rather than being quietly dropped.
    """
    table = pd.DataFrame(index=list(TARGETS), columns=list(TARGETS), dtype=float)
    table.index.name = "designed_for"
    table.columns.name = "scored_on"

    for (designed_for, scored_on), path in runs.items():
        df = scores.load(path)
        if column not in df.columns:
            raise KeyError(
                f"{column!r} is not a column of {path}. Run "
                f"`python analysis/scores.py --columns {path}` and use a real name."
            )
        table.loc[designed_for, scored_on] = df[column].mean()

    return table.round(4)


def selectivity_delta(table: pd.DataFrame) -> pd.Series:
    """Own-target score minus the mean of the cross-target scores, per design set.

    Compare every value here against the noise floor from
    `scores.noise_floor` before calling any of it a result.
    """
    deltas = {}
    for t in table.index:
        own = table.loc[t, t]
        cross = table.loc[t, [c for c in table.columns if c != t]].mean()
        deltas[t] = own - cross
    return pd.Series(deltas, name="delta_own_minus_cross").round(4)


if __name__ == "__main__":
    raise SystemExit(
        "Not runnable yet: the score column is unknown and the re-scoring runs do "
        "not exist. See this file's docstring."
    )
