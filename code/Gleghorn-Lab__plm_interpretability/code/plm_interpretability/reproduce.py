"""Redraw every figure and table of the paper from the public results archive.

    python -m plm_interpretability.reproduce --out reproduced [--archive archive]

Downloads the archive at its pinned revision (or reads `--archive`), restores Protify's run layout, checks each
model's rebuilt probe summary against the one written when the figures were first drawn, then runs Protify's own
drawing code as the study did (`figures` per model, `trends` across models, `compare` across input treatments) and
draws the cross-model figures and tables. The three-seed pooling and MLP study has an archive of its own, which also
holds the survey's mean-only additions, ESMC-600's probe variants and geometry, and its causal analyses: from it
`plm_interpretability.pooling_study`, `probe_gap`, `causal_figures` and `familiarity` draw theirs. `plm_interpretability.published` draws
the tuned pair probes beside published predictors from one more table of the first archive. Outputs:
`<out>/{pooling,probe_gap,causal,familiarity,trends,trends_mean,main,raw,esmc600,esmc6b,compare,cross_model,cross_model_mean,published}`.
"""

from __future__ import annotations

import argparse
import json
import pandas as pd

from collections.abc import Sequence
from pathlib import Path
from src.protify.interpretability import figures, trends
from src.protify.interpretability.selection import rank_settings

from plm_interpretability import archive, causal_figures, cross_model, familiarity, figure_style, pooling_study, probe_gap, published, solver_table


PROTEIN_SWEEPS = ("p_b256", "p_b1024")
RESIDUE_SWEEPS = ("r_t32768", "r_t131072")
PHOSPHO = ("phospho", "phospho_s24896", "phospho_s24897")
REFERENCES = {"ESMC-300": "main", "ESMC-600": "esmc600", "ESMC-6B": "esmc6b"}


def _roots(runs: Path, names: Sequence[str]) -> list[Path]:
    return [runs / name for name in names]


def draw_model(runs: Path, roots: Sequence[str], out: Path, blocks: int, random_roots: Sequence[str] = (),
               shared: tuple[str, str] | None = None, label: str = "linear") -> list[Path]:
    """Protify's `figures` command for one model. `shared` names the trained and random-init roots whose sweeps,
    phosphomimetic scans and principal coordinates the figures read (run once, on raw states, and borrowed by every
    input treatment); without it the figures leave them out."""
    first = runs / roots[0]
    source = runs / (shared[0] if shared else roots[0])
    metadata = {path.parent.name: json.loads(path.read_text(encoding="utf-8"))["task"]
                for path in (first / "results" / label).glob("*/run.json")}
    rankings = {}
    if shared is not None:
        rankings = {regime: rank_settings(archive.read_sweeps(source, labels)) for regime, labels in (("protein", PROTEIN_SWEEPS), ("residue", RESIDUE_SWEEPS))}
    phospho = [source / "interventions" / label for label in PHOSPHO if (source / "interventions" / label / "scores.parquet").exists()] if shared else []
    latent = {}
    if shared is not None:
        random_source = runs / shared[1]
        latent = {name: root / "latent" / "pca" for name, root in (("trained model", source), ("random-init model", random_source))
                  if (root / "latent" / "pca").exists()}
    return figures.draw(_roots(runs, roots), out, blocks, label, _roots(runs, random_roots), phospho, latent, rankings, metadata)


def verify(runs: Path, analyses: Path, added: pd.DataFrame) -> None:
    """Each model's rebuilt summary against the one Protify wrote when the figures were drawn, leaving out the probes
    `archive.merge_sites` added to the model's roots after it (`added`)."""
    for model, folder in REFERENCES.items():
        reference = analyses / folder / "summary.parquet"
        if reference.exists():
            mine = added[added["root"].isin(archive.MODELS[model])]
            later = set(map(tuple, mine[["task", "family", "probe_name"]].itertuples(index=False)))
            summary = archive.model_summary(_roots(runs, archive.MODELS[model]))
            summary = summary[[key not in later for key in zip(summary["task"], summary["family"], summary["probe_name"], strict=True)]]
            difference = archive.verify(summary.reset_index(drop=True), pd.read_parquet(reference))
            print(f"{model}: summary matches the archive's to {difference:.1e}")


def cross_model_figures(runs: Path, out: Path, label: str = "linear") -> list[Path]:
    """The figures and tables across ESMC-300, ESMC-600 and ESMC-6B: which kinds of state read which kinds of concept
    (the main text), and the Supplement's."""
    summaries = {model: archive.model_summary(_roots(runs, roots), label) for model, roots in archive.MODELS.items()}
    # the gains inside the block read the main text's pair task beside the concepts
    gaps = {model: cross_model.intra_block_gaps(summary[summary["task"] != "ppi2"], archive.BLOCKS[model])
            for model, summary in summaries.items()}
    summaries = {model: summary[~summary["task"].isin(trends.PAIR_TASKS)] for model, summary in summaries.items()}
    random = archive.model_summary(_roots(runs, archive.RANDOM["ESMC-300 random init"]), label)
    onehot = archive.model_summary(_roots(runs, archive.BASELINES["OneHot-Protein"][:1]), label)
    best = cross_model.best_table(summaries, archive.BLOCKS)
    out.mkdir(parents=True, exist_ok=True)
    best.to_csv(out / "best_states_all.csv", index=False, float_format="%.4f")
    kinds = pd.concat([cross_model.kind_gaps(summary).assign(model=model) for model, summary in summaries.items()])
    kinds.to_csv(out / "state_concepts.csv", float_format="%.4f")
    written = [cross_model.state_concepts(summaries, out / "state_concepts.png"), out / "state_concepts.csv",
               cross_model.depth_all(summaries, archive.BLOCKS, random, onehot, out / "depth_all.png"),
               cross_model.site_gaps_all(summaries, out / "site_gaps_all.png"),
               cross_model.best_depth_all(best, out / "best_depth_all.png"),
               cross_model.best_block_tables(best, out / "best_blocks.tex"), out / "best_states_all.csv"]
    pd.concat([gap.assign(model=model) for model, gap in gaps.items()]).to_csv(out / "intra_block_gaps.csv", index=False, float_format="%.4f")
    written += [cross_model.gap_table(gaps, out / "gap_table.tex"), out / "intra_block_gaps.csv"]
    structure = cross_model.structure_table(summaries, best)
    if not structure.empty:  # the structure stream's probes, joined to every root of the main text
        random_best = cross_model.best_table({"ESMC-300 random init": random}, {"ESMC-300 random init": archive.BLOCKS["ESMC-300"]})
        random_structure = cross_model.structure_table({"ESMC-300 random init": random}, random_best)
        pd.concat([structure, random_structure]).to_csv(out / "structure_stream.csv", index=False, float_format="%.4f")
        written += [cross_model.structure_gaps(structure, out / "structure_gaps.png"), out / "structure_stream.csv"]
    return written


def pooling(source: Path, out: Path) -> list[Path]:
    """The three-seed pooling and MLP study's Supplement figures and tables: the gains and differences of every model
    with their intervals, and ESMC-300's and ESMC-6B's linear and MLP probes on both poolings, compared along depth and
    by site (`<out>/compare_esmc300`, `<out>/compare_esmc6b`)."""
    written = pooling_study.write_all(source / "runs" / "tables", out, pooling_study.task_sizes(None))
    for model, names in archive.POOLING_ROOTS.items():
        roots = [source / "runs" / root for root in names]
        # the reference first: the main text's pooling, mean and variance
        variants = {name: [(root, label) for root in roots]
                    for name, label in (("linear", "linear"), ("MLP", "mlp"), ("linear, mean", "linear_mean"), ("MLP, mean", "mlp_mean"))}
        written += figures.compare(variants, out / f"compare_{model.lower().replace('-', '')}", archive.BLOCKS[model])
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="folder for the figures and tables")
    parser.add_argument("--archive", type=Path, default=None, help="an archive already downloaded (default: download into <out>/archive)")
    parser.add_argument("--pooling-archive", type=Path, default=None,
                        help="the pooling study's archive already downloaded (default: download into <out>/pooling_archive)")
    args = parser.parse_args()
    figure_style.install()
    # the pooling study's tables are not compacted, so they are drawn before `install` swaps Protify's readers
    pooled = args.pooling_archive or archive.download_pooling(args.out / "pooling_archive")
    sizes = pooling_study.task_sizes(None)
    written = pooling(pooled, args.out / "pooling")
    written += probe_gap.write_all(pooled / "runs" / "tables", pooled / "runs", pooled / "geometry", args.out / "probe_gap", sizes)
    written += causal_figures.write_all(pooled / "causal", args.out / "causal")
    written += familiarity.write_all(pooled / "familiarity", args.out / "familiarity")
    source = args.archive or archive.download(args.out / "archive")
    runs = archive.overlay(pooled / "survey", archive.restore(source, args.out / "runs"))
    added = archive.merge_sites(runs)  # ESMC-6B's residue probes inside the block, joined to its stream probes
    # The Supplement's mean-only label on every root of the survey it repeats; raw states have no mean-only probes at
    # every seed and are read under mean and variance pooling only.
    for group in (archive.MODELS, archive.RANDOM, archive.BASELINES):
        for roots in group.values():
            for root in _roots(runs, roots):
                archive.compose(root)
    archive.install()
    verify(runs, source / "analyses" / "final2", added)
    # The main text reads every model under mean and variance pooling (`linear`), with both pair tasks; the Supplement
    # repeats its trends on the pooled mean (`MEAN_POOLED`), with `ppi` alone, since `ppi2` ran under mean and variance.
    for label, folder in (("linear", "trends"), (archive.MEAN_POOLED, "trends_mean")):
        models = [trends.ModelRuns(model, tuple(_roots(runs, roots)), label) for model, roots in archive.MODELS.items()]
        random = [trends.ModelRuns(model, tuple(_roots(runs, roots)), label) for model, roots in archive.RANDOM.items()]
        baselines = [trends.ModelRuns(model, tuple(_roots(runs, roots)), label) for model, roots in archive.BASELINES.items()]
        written += trends.trends(models, args.out / folder, random, baselines)
    written += draw_model(runs, archive.MODELS["ESMC-300"], args.out / "main", 30, archive.RANDOM["ESMC-300 random init"], shared=("run", "run_random"))
    written += draw_model(runs, archive.RAW, args.out / "raw", 30, archive.RANDOM_RAW, shared=("run", "run_random"), label="linear")
    written += draw_model(runs, archive.MODELS["ESMC-600"], args.out / "esmc600", 36)
    written += draw_model(runs, archive.MODELS["ESMC-6B"], args.out / "esmc6b", 80)
    # Raw against unit-norm states, three seeds each, on the pooled mean and variance (raw states have no mean-only
    # probes at seed 24897).
    variants = {"unit-norm": [(root, "linear") for root in _roots(runs, archive.MODELS["ESMC-300"])],
                "raw": [(root, "linear") for root in _roots(runs, archive.RAW)]}
    written += figures.compare(variants, args.out / "compare", 30)
    written += cross_model_figures(runs, args.out / "cross_model")
    written += cross_model_figures(runs, args.out / "cross_model_mean", archive.MEAN_POOLED)[:2]
    written.append(solver_table.solver_table(pd.read_csv(source / "analyses" / "solver_check.csv"), args.out / "cross_model" / "solver_table.tex"))
    # the tuned pair probes' summary joined the archive after the survey's pinned revision, so it has its own pin
    tuned = source / published.SUMMARY_FILE
    written += published.write_all(tuned if tuned.exists() else published.download_summary(args.out / "archive"), args.out / "published")
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
