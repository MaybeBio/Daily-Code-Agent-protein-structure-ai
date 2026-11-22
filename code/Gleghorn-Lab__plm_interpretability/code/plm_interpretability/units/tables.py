"""Tables of the native-unit study, written as LaTeX tabular bodies from a run's outputs; the manuscript keeps each
caption and inputs the body.

`decision_table` reports every preregistered decision as the run took it, H3 and H5 again after the test proteins
inherit close homologs' annotations, and a decision that was not taken with its reason, so the paper cannot leave one
out. `payoff_table` gives E11's comparisons under every metric, `inheritance_table` the missing-annotation correction
for every basis at the hypothesis sites, and `sae_labels_table` Supplement S2's labels of the ESMC-6B SAE on the
compendium. Numbers are as the run wrote them, rounded to three decimals or, for an estimate with its interval or a
decision's comparison, to as many as keep its numbers apart, at most six (`_decimals`).
"""

from __future__ import annotations

import json
import math
import pandas as pd

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import experiments
from .experiments import MODEL_NAMES, site_name
from .sae_labels import MIN_GLOBAL_AUROC


GATE_READ = ("H1", "H2", "H3", "H5")  # the decisions taken on both readings of the native products
METRIC_NAMES = {"margin": "margin", "held_out_auroc": "held-out AUROC"}
PAYOFF_METRICS = {"pr_auc": "PR AUC", "roc_auc": "ROC AUC", "balanced_mcc": "balanced MCC", "spearman": r"Spearman's $\rho$"}
PAYOFF_COMPARISONS = {"extremes: native - rotated": "maxima and minima, native minus rotated",
                      "mean: native - rotated": "means, native minus rotated",
                      "native extremes - SAE": "native maxima and minima minus SAE latents"}
BASIS_ORDER = ("native", "sign", "leak", "gate", "rotation", "residual", "sae")  # basis kinds as `inheritance_table` lists them
DIGITS = (3, 6)  # the fewest and the most decimals `_decimals` gives


@dataclass(frozen=True)
class DecisionRow:
    """One quantity of one decision as the table prints it."""

    hypothesis: str
    site: str
    reading: str
    quantity: str
    estimate: str
    outcome: str


def _number(value: float, digits: int = 3) -> str:
    """A number as text, a negative one with a true minus sign."""
    return f"{value:.{digits}f}".replace("-", "$-$")


def _decimals(*values: float) -> int:
    """The decimals that keep a group of numbers apart: enough for the smallest gap between them and for the smallest
    nonzero one, or a lone number's two significant digits, at least three and at most `DIGITS[1]`, since near-ceiling
    scores differ in the fourth and fifth."""
    finite = sorted({value for value in values if math.isfinite(value)})
    lone = 10 if len(finite) == 1 else 1  # a lone number keeps a second significant digit
    scales = [second - first for first, second in zip(finite, finite[1:], strict=False)] + [abs(value) / lone for value in finite if value]
    if not scales:
        return DIGITS[0]
    return min(DIGITS[1], max(DIGITS[0], math.ceil(-math.log10(min(scales)) - 1e-9)))  # 1e-9: log10 of a power of ten


def _interval(entry: Mapping[str, float]) -> str:
    """An estimate and its interval, at the decimals that keep the three apart (`_decimals`)."""
    digits = _decimals(entry["estimate"], entry["low"], entry["high"])
    return f"{_number(entry['estimate'], digits)} [{_number(entry['low'], digits)}, {_number(entry['high'], digits)}]"


def _p(value: float) -> str:
    """A p value in math mode, in scientific notation below 0.001."""
    if value >= 1e-3:
        return f"$p = {value:.3f}$"
    mantissa, exponent = f"{value:.1e}".split("e")
    return rf"$p = {mantissa} \times 10^{{{int(exponent)}}}$"


def _site(name: str, site: str) -> str:
    """Where a decision was taken: H4 by its model and the blocks its random-init pass plans, which it pools; H1 to H3
    and H5 at their site; the rest as the run named it."""
    if name == "H4":
        plans = experiments.experiment_plans()
        control = next(plans[pass_name] for pass_name in experiments.RANDOM_INIT_PASSES.values() if plans[pass_name].model == site)
        blocks = sorted({planned.basis.block for planned in control.plan})
        return f"{MODEL_NAMES[site]}, " + ("every block" if len(blocks) > 1 else f"block {blocks[0]}")
    if name == "H6":
        return f"{MODEL_NAMES[experiments.CAUSAL_MODEL]}, block {experiments.CAUSAL_BLOCK}"
    if site in experiments.HYPOTHESIS_SITES:
        return site_name(site)
    return MODEL_NAMES.get(site, site).replace("_", r"\_")


def _step(step: str) -> str:
    """H7's step `<larger>_minus_<smaller>` as the table names it."""
    larger, smaller = step.split("_minus_")
    return f"{MODEL_NAMES[larger]} minus {MODEL_NAMES[smaller]}"


def _quantities(name: str, details: Mapping[str, object]) -> list[tuple[str, str]]:
    """Each quantity a decision's rule reads, with its estimate, from the decision's details (`hypotheses`)."""
    if name == "H0":
        return [("cells where intermediate poles beat residual dimensions", f"{details['won']} of {details['of']}")]
    if name == "H1":
        return [("median margin, native minus residual", _interval(details["margin_difference"]))]
    if name == "H2":
        rows = []
        for metric, test in details.items():
            low, high = min(test["rotations"]), max(test["rotations"])
            digits = _decimals(test["native"], low, high)
            rows.append((f"median {METRIC_NAMES[metric]}, native against the ten rotations",
                         f"{_number(test['native'], digits)} against {_number(low, digits)} to {_number(high, digits)}"))
        return rows
    if name == "H3":
        return [(r"median held-out AUROC, native minus SAE, 90\% interval", _interval(details["held_out_difference"]))]
    if name == "H4":
        tested = {kind: kind_test for kind, kind_test in details.items() if kind_test["tested"]}
        above = sum(kind_test["difference"]["low"] > 0 for kind_test in tested.values())
        return [("kinds whose trained minus random-init median margin is above zero",
                 f"{above} of {len(tested)} tested; {len(details) - len(tested)} with too few poles")]
    if name == "H5":
        difference = details["median_difference"]
        return [("median held-out AUROC, native minus pooled rotations",
                 f"{_number(difference, _decimals(difference))}, {_p(details['p_value'])}")]
    if name == "H6":
        if "median_excess" not in details:
            return [(str(details["reason"]), "")]
        return [(f"median drop minus placebos' mean drop, {details['statuses'].get('tested', 0)} poles tested",
                 _interval(details["median_excess"]))]
    if name == "H7":
        return [(f"median margin, {_step(step)}", _interval(difference)) for step, difference in details.items()]
    raise ValueError(f"No table row for decision {name!r}.")


def decision_rows(decisions: Sequence[Mapping[str, object]], inherited: Sequence[Mapping[str, object]] = ()) -> list[DecisionRow]:
    """One row per decision and quantity in the order the run took them, then `inherited`, H3 and H5 taken again after
    inheritance (`missing` stage receipt); a decision not taken keeps a row with its reason."""
    rows = []
    for entry, after in [*((entry, False) for entry in decisions), *((entry, True) for entry in inherited)]:
        name, _, suffix = str(entry["hypothesis"]).partition("_")
        label = name + (", inherited labels" if after else "")
        reading = ("sign-only" if suffix == "sign" else "gate-tagged") if name in GATE_READ else ""
        site = _site(name, str(entry["site"]))
        if not entry["taken"]:
            reason = "rate match rejected" if entry.get("rejected_matches") else str(entry.get("reason", ""))
            rows.append(DecisionRow(label, site, reading, reason, "", "not taken"))
            continue
        outcome = "passed" if entry["passed"] else "failed"
        rows.extend(DecisionRow(label, site, reading, quantity, estimate, outcome)
                    for quantity, estimate in _quantities(name, entry["details"]))
    return rows


def decision_table(rows: Sequence[DecisionRow]) -> str:
    """The decisions as a tabular body the width of the page, the quantity column taking what the others leave and the
    decision's name wrapping, with a small space between hypotheses."""
    lines = [r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}p{1.6cm} l l >{\raggedright\arraybackslash}X l l@{}}",
             r"\toprule", r"Decision & Site & Reading & Quantity & Estimate & Outcome \\", r"\midrule"]
    previous = None
    for row in rows:
        if previous is not None and row.hypothesis != previous:
            lines.append(r"\addlinespace")
        lines.append(" & ".join((row.hypothesis, row.site, row.reading, row.quantity, row.estimate, row.outcome)) + r" \\")
        previous = row.hypothesis
    return "\n".join([*lines, r"\bottomrule", r"\end{tabularx}", ""])


def payoff_table(summaries: Mapping[str, pd.DataFrame]) -> str:
    """E11's comparisons under every metric, by model (`payoff.payoff_summary`): both fingerprints' medians over targets,
    the median per-target difference with its 95% interval, the share of targets the first wins, and the targets."""
    lines = [r"\begin{tabular}{@{}l >{\raggedright\arraybackslash}p{4.4cm} l c c c c c@{}}", r"\toprule",
             r"Model & Comparison & Metric & First & Second & Difference & First wins & Targets \\"]
    for model, summary in summaries.items():
        lines.append(r"\midrule")
        for index, row in enumerate(summary.itertuples(index=False)):
            if index and row.metric != summary["metric"].iloc[index - 1]:
                lines.append(r"\addlinespace")
            lines.append(" & ".join((
                MODEL_NAMES[model] if index == 0 else "", PAYOFF_COMPARISONS.get(row.comparison, row.comparison),
                PAYOFF_METRICS[row.metric], _number(row.first_median), _number(row.second_median),
                _interval({"estimate": row.difference, "low": row.low, "high": row.high}), _number(row.first_wins, 2),
                str(row.targets))) + r" \\")
    return "\n".join([*lines, r"\bottomrule", r"\end{tabular}", ""])


def _basis(key: str, reference: str) -> tuple[int, bool, int, str]:
    """A planned key's place in the table, by `BASIS_ORDER` with the site's own reference first, and its name there; a
    basis read at another SAE's rates, or another SAE, names it by its codebook."""
    kind, _, source = key.split("/", 1)[1].replace(":", "@").partition("@")
    order = next(index for index, prefix in enumerate(BASIS_ORDER) if kind.startswith(prefix))
    seed = int(kind.removeprefix("rotation")) if kind.startswith("rotation") else 0
    names = {"native": "native, gate-tagged", "sign": "native, sign-only", "leak": "leak poles", "gate": "gate",
             "residual": "residual stream", "sae": "SAE"}
    label = names.get(kind, f"rotation {seed}")
    if source != reference:
        codebook = int(source.rsplit("_", 1)[1])
        if kind != "sae":
            label += f", at {codebook:,}-latent rates"
        else:
            label = "MLP-output SAE" if "_mlp_" in source else f"SAE, {codebook:,} latents"
    return order, source != reference, seed, label


def inheritance_table(receipt: Mapping[str, object]) -> str:
    """The missing-annotation correction (`missing` stage receipt) for every basis at each site: poles rescored and the
    medians of held-out AUROC and average precision over poles scored both ways, before and after inheritance."""
    lines = [r"\begin{tabular}{@{}l l c c c c@{}}", r"\toprule",
             r"Site & Basis & Rescored & AUROC before & AUROC after & AP before, after \\"]
    for site, entry in receipt["sites"].items():
        reference = experiments.HYPOTHESIS_SITES[site][2]
        lines.append(r"\midrule")
        for index, key in enumerate(sorted(entry["bases"], key=lambda key: _basis(key, reference))):
            basis = entry["bases"][key]
            values = [basis[f"median_{metric}"] for metric in ("auroc_before", "auroc_after", "precision_before", "precision_after")]
            shown = ["--" if value is None else _number(value) for value in values]
            lines.append(" & ".join((site_name(site) if index == 0 else "", _basis(key, reference)[3],
                                     f"{basis['rescored']} of {basis['poles']}", shown[0], shown[1],
                                     f"{shown[2]}, {shown[3]}")) + r" \\")
    return "\n".join([*lines, r"\bottomrule", r"\end{tabular}", ""])


def sae_labels_table(receipt: Mapping[str, object]) -> str:
    """Supplement S2 on the compendium (`sae-labels` stage receipt): how many of the SAE's latents carry a label, how well
    the labels predict their terms on test proteins, and each arm's agreement with Biohub's descriptions."""
    labels, arms = receipt["labels"], receipt["agreement"]["arms"]

    def shown(entry: Mapping[str, float] | None) -> str:
        return "--" if entry is None else _interval(entry)

    rows = [
        ("Latents with a testable global term", f"{labels['with_testable_term']:,} of {labels['latents']:,}"),
        ("Best global term's training AUROC, median", shown(labels["best_auroc"])),
        (f"Latents whose best global term reaches {MIN_GLOBAL_AUROC}", f"{labels['global_labeled']:,}"),
        ("Held-out AUROC of the best global term, median", shown(labels["held_out_auroc"])),
        (f"The same, latents reaching {MIN_GLOBAL_AUROC}", shown(labels["held_out_auroc_labeled"])),
        ("Average precision, median, before inheritance", shown(labels["precision_before"])),
        ("Prevalence, median, before inheritance", shown(labels["prevalence_before"])),
        ("Average precision, median, after inheritance", shown(labels["precision_after"])),
        ("Prevalence, median, after inheritance", shown(labels["prevalence_after"])),
        ("Latents with a selected local label", f"{labels['with_local_label']:,} ({labels['local_labels']:,} labels)"),
        ("Latents with a single dominant local term", f"{labels['dominant']:,} ({_number(labels['dominant_share'])})"),
    ]
    for arm in ("global", "local"):
        entry = arms[arm]
        if not entry["included"]:
            rows.append((f"Matched win probability, {arm} representatives", "--"))
            continue
        low, high = entry["mean_excess_feature_bootstrap_95ci"]
        rows.append((f"Matched win probability, {arm} representatives",
                     f"{_number(entry['mean_matched_win_probability'], 4)} of {entry['included']:,} latents, "
                     f"{_p(entry['one_sided_permutation_p'])}"))
        rows.append((f"Paired excess, {arm} representatives",
                     f"{_number(entry['mean_semantic_excess'], 4)} [{_number(low, 4)}, {_number(high, 4)}]"))
    lines = [r"\begin{tabular}{@{}l l@{}}", r"\toprule", r"Quantity & Value \\", r"\midrule"]
    lines += [f"{name} & {value}" + r" \\" for name, value in rows]
    return "\n".join([*lines, r"\bottomrule", r"\end{tabular}", ""])


def write_tables(root: Path, folder: Path) -> list[Path]:
    """Every table whose inputs the run holds, written to `folder`; the decisions need `decisions.json`."""
    folder.mkdir(parents=True, exist_ok=True)
    receipt_path = root / "missing" / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else None
    decisions = json.loads((root / "decisions.json").read_text(encoding="utf-8"))
    tables = {"decisions": decision_table(decision_rows(decisions, receipt["decisions_after_inheritance"] if receipt else ()))}
    summaries = {model: root / "concepts" / model / "e11_summary.parquet" for model in experiments.concept_plans()}
    if all(path.exists() for path in summaries.values()):
        tables["payoff"] = payoff_table({model: pd.read_parquet(path) for model, path in summaries.items()})
    if receipt is not None:
        tables["inheritance"] = inheritance_table(receipt)
    labels_path = root / "sae_labels" / "receipt.json"
    if labels_path.exists():
        tables["sae_labels"] = sae_labels_table(json.loads(labels_path.read_text(encoding="utf-8")))
    written = []
    for name, text in tables.items():
        path = folder / f"{name}.tex"
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written
