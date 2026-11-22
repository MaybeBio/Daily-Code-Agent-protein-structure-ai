"""The Supplement's converged-solver table: each protein task's two refitted probes against their AdamW originals.

    python -m plm_interpretability.solver_table SOLVER_CSV OUT_TEX
"""

from __future__ import annotations

import argparse
import pandas as pd

from pathlib import Path
from src.protify.interpretability.figures import TASK_LABELS
from src.protify.interpretability.trends import CONCEPT_ORDER

from plm_interpretability.figure_style import site_tex


SELECTIONS = {"best_any": "any site", "best_residual": "residual stream"}


def state(probe: str) -> str:
    """`site:layer` as the text names it: the site's macro name and its block."""
    site, layer = probe.split(":")
    return f"{site_tex(site)} {layer}"


def solver_table(table: pd.DataFrame, path: Path) -> Path:
    """A LaTeX table of the AdamW and converged-solver test scores of every refitted probe."""
    order = {task: index for index, task in enumerate(CONCEPT_ORDER)}
    table = table.sort_values(["task", "selection"], key=lambda column: column.map(order) if column.name == "task" else column)
    lines = [r"\begin{table}[!htbp]", r"\centering\small",
             r"\caption{\textbf{Converged solvers against the global AdamW setting.} For each protein task of ESMC-300 (one seed, "
             r"unit-norm states), the full-width probe chosen on validation among all sites and among residual-stream states, refitted "
             r"with a validation-tuned L2 penalty by L-BFGS (ridge regression for ProtParam). Scores are test MCC, and cosine similarity "
             r"for ProtParam. Converged fitting lifts the stream's probes more than those of the best site, so part of the intra-block "
             r"states' edge under AdamW is fitting.}",
             r"\label{tab:solver}", r"\begin{tabular}{@{}l l l r r r@{}}", r"\toprule",
             r"Task & Chosen among & State & AdamW & Solver & Difference \\", r"\midrule"]
    for _, row in table.iterrows():
        lines.append(f"{TASK_LABELS[row['task']]} & {SELECTIONS[row['selection']]} & {state(row['probe'])} & "
                     f"{row['adamw_test']:.3f} & {row['solver_test']:.3f} & {row['solver_test'] - row['adamw_test']:+.3f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("solver_csv", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    print(solver_table(pd.read_csv(args.solver_csv), args.out))


if __name__ == "__main__":
    main()
