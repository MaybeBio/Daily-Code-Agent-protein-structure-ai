"""The main text's figure from dense neurons to curated labels: what a labeled neuron looks like on real proteins, which
concepts the neurons mark and which only an SAE marks, whether SAE latents are the neurons again, and whether curated
labels and the descriptions Biohub's language-model pipeline wrote for the same SAE latents name the same biology.

Every number is read from the neuron study's archive (`GleghornLab/esmc_native_units_results`): residue tracks of
labeled poles in the schema of `exemplars.track_table` (`exemplars/tracks.parquet`, or any table of that schema), E13's
per-concept scores on InterPLM's evaluation at the feed-forward write's SAE (`retest_esmc/<model>_mlp`), the
groups-of-poles fits (`coalitions/<model>/report.json`) and the agreement of curated labels with Biohub's descriptions
(`sae_labels/receipt.json`). Colors, the panel letter and the track drawing are `figures`'s, so a hue means here what
it means in every figure of the study. Kinds of unit are listed from worst to best: rotations, neurons, SAE.

Symbols: c concepts on InterPLM's evaluation; s sizes of a group of poles; l residues of one protein.

    PYTHONPATH="<plm_interpretability>;<ws>;<ws>/projects/representation/annotation_vocabulary/src;<ws>/models" \
        py -m plm_interpretability.units.label_figure --root <archive> --out fig5_labels.png [--tracks T [--concepts C ...]]
"""

from __future__ import annotations

import argparse
import json
import numpy as np
import pandas as pd

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from . import experiments
from .exemplars import POLE_NAMES
from .experiments import MODEL_NAMES
from .figures import (HEADROOM, INK, LEAK, MUTED, NATIVE, OPPOSITE, ROTATION, SAE, STYLE, _grid, letter, new_figure,
                      save_figure, track_panel)
from ..figure_style import ROW_BAND


if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure


WIDTH = 7.09  # inches, 180 mm, the journal's full width
CUT = 0.5  # a unit reads a concept when its best test F1 exceeds this, the rule of `coalitions.concept_latents`
TRACKED = "0.7"  # the correlation at which a fit of poles tracks an SAE latent, the dictionary test's
MODELS = ("esmc_600", "esmc_6b")
NEITHER = "#e6e8eb"  # concepts no unit reads: lighter than the rotations' gray, which marks a control
TRACK_ROW = 0.62  # inches per exemplar row of panel A, its residue ticks included
LABEL_SPACE = 0.22  # width of panel A's column of row names, as a share of one track's
# A carrier's UniProt primary gene name, read from rest.uniprot.org on 2026-11-16 (the lengths there match the tracks');
# a carrier without one is named by its accession.
CARRIER_NAMES = {"Q8GP19": "RssA", "A7MRY4": "LuxN", "A7HD43": "GcHK", "P9WGL4": "PdtaS",
                 "Q1EBV7": "BASS2", "Q01289": "POR", "Q9FYB5": "ATJ11", "Q9AWA5": "R1"}
# Panel A's columns by the roles a tracks table holds, with a short head for each: Figure 4's frozen exemplars
# (`exemplars`), or the chosen poles on InterPLM's evaluation (`concept_exemplars`): all three carriers drawn at random,
# so a row shows what an arbitrary carrier looks like and not the strongest, then the protein without the concept.
ARCHIVE_COLUMNS = {"top1": "strongest carrier", "top2": "second", "top3": "third", "drawn": "random carrier"}
CONCEPT_COLUMNS = {"drawn1": "random carrier", "drawn2": "random carrier", "drawn3": "random carrier",
                   "negative": "without the concept"}
DEFAULT_EXEMPLARS = (2,)  # the archive's chloroplast transit peptide pole; its phosphohistidine pole is noisy
# The chosen poles a concept table draws by default, chosen on 2026-11-16 from all eight poles' tracks for range (a
# domain, a zinc finger, a DNA-binding motif, a targeting peptide) among those whose three random carriers all read
# cleanly; N-linked glycosylation is left out because two of its three random carriers barely cross its threshold.
DEFAULT_CONCEPTS = ("Domain_Protein kinase", "Zinc finger_NR C4-type", "Domain_HTH lacI-type", "Transit peptide_Chloroplast")
# A Swiss-Prot concept of `scripts/exemplar_concepts.csv` as a row of panel A names it; any other by its name's tail.
CONCEPT_NAMES = {"Domain_Response regulatory": "response\nregulatory domain", "Motif_Nudix box": "Nudix box",
                 "Transit peptide_Chloroplast": "chloroplast\ntransit peptide", "Domain_Protein kinase": "protein kinase\ndomain",
                 "Zinc finger_NR C4-type": "nuclear receptor\nzinc finger",
                 "Glycosylation_N-linked (GlcNAc...) asparagine": "N-linked\nglycosylation",
                 "Domain_HTH lacI-type": "LacI-type HTH", "Domain_SH2": "SH2 domain"}
# An exemplar's term as the figure names it, by the term's token in `inputs/terms.parquet`; any other term is named by
# its label there.
TERM_NAMES = {58165: "phospho-\nhistidine", 58038: "chloroplast\ntransit\npeptide"}
# Swiss-Prot's feature types as E13's concept names begin, as the figure names them; a type no unit reads in either model
# joins `OTHERS`.
CATEGORY_NAMES = {"Domain": "domain", "Region": "region", "Motif": "motif", "Zinc finger": "zinc finger",
                  "Active site": "active site", "Transit peptide": "transit peptide", "Signal peptide": "signal peptide",
                  "Modified residue": "modified residue", "Glycosylation": "glycosylation"}
OTHERS = "seven others"
SEGMENTS = ("neurons_only", "both", "sae_only", "neither")
SEGMENT_NAMES = {"neurons_only": "neurons only", "both": "both", "sae_only": "SAE only", "neither": "neither"}
MODEL_MARKERS = {"esmc_600": "o", "esmc_6b": "s"}
AGREEMENT_ARMS = {"global": "protein-level\nlabels", "local": "residue-level\nlabels"}


# -- loaders -----------------------------------------------------------------------------------------------------------


def write_sae(model: str) -> str:
    """The name of the SAE on a model's feed-forward write at its dictionary site, the first of the site's SAEs."""
    name = experiments.dictionary_sites()[model].saes[0]
    assert "_mlp_" in name, f"{name} does not read the feed-forward write."
    return name


def concept_routes(root: Path, model: str) -> pd.DataFrame:
    """Each concept of E13's write plan at three quarters of the stack, by whether the neurons' best pole, the write
    SAE's best latent, both or neither read it (best test F1 above `CUT`), with its Swiss-Prot feature type."""
    table = pd.read_parquet(root / "retest_esmc" / f"{model}_mlp" / "e13_per_concept.parquet")
    sae = f"sae:{write_sae(model)}"
    f1 = table.pivot_table(index="concept", columns="arm", values="best_test_f1")  # (c, arms)
    feature = table.pivot_table(index="concept", columns="arm", values="best_feature")  # (c, arms)
    neurons = (f1["mlp_native"] > CUT).to_numpy()  # (c,)
    latents = ((f1[sae] > CUT) & (feature[sae] >= 0)).to_numpy()  # (c,)
    route = np.select([neurons & latents, neurons, latents], ["both", "neurons_only", "sae_only"], "neither")  # (c,)
    category = f1.index.str.split("_").str[0]  # (c,)
    return pd.DataFrame({"concept": f1.index, "category": category, "route": route})


def coalition_report(root: Path, model: str) -> dict[str, object]:
    """The groups-of-poles fits at a model's dictionary site (`coalitions.coalition_report` with its concepts)."""
    return json.loads((root / "coalitions" / model / "report.json").read_text(encoding="utf-8"))


def agreement_report(root: Path) -> dict[str, object]:
    """The agreement of curated labels with Biohub's descriptions of its described ESMC-6B SAE (`sae_labels.agreement`)."""
    receipt = json.loads((root / "sae_labels" / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["latents"] == "block59/sae:esmc_6b_layer60_k64_16384", f"Unexpected latents {receipt['latents']}."
    return receipt["agreement"]


def check_routes(routes: pd.DataFrame, report: Mapping[str, object]) -> None:
    """The concepts the SAE alone reads, and those both read, are the ones the coalition report fit."""
    counts = routes["route"].value_counts()
    concepts = report["concepts"]
    assert int(counts.get("sae_only", 0)) == concepts["sae_only"]["concepts"], "SAE-only concepts differ from the report."
    assert int(counts.get("both", 0)) == concepts["shared"]["concepts"], "Shared concepts differ from the report."


def route_counts(routes: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Concepts by feature type and route for each model, the types in a shared order (most concepts read first) and
    every type that no unit reads in any model merged into `OTHERS`."""
    read = pd.concat([table[table["route"] != "neither"] for table in routes.values()])
    order = [category for category in read["category"].value_counts().index if category in CATEGORY_NAMES]
    unnamed = sorted(set(read["category"]) - set(CATEGORY_NAMES))
    assert not unnamed, f"Feature types read by some unit but unnamed: {unnamed}"
    counts = {}
    for model, table in routes.items():
        named = table["category"].map(CATEGORY_NAMES).fillna(OTHERS)
        grid = pd.crosstab(named, table["route"]).reindex(columns=list(SEGMENTS), fill_value=0)  # (types, routes)
        counts[model] = grid.reindex([CATEGORY_NAMES[category] for category in order] + [OTHERS], fill_value=0)
        assert int(counts[model].to_numpy().sum()) == len(table), "A concept was lost while counting routes."
    return counts


def site_title(model: str) -> str:
    """A model's dictionary site as a coverage panel's title, e.g. "ESMC-600, block 26"."""
    return f"{MODEL_NAMES[model]}, block {experiments.dictionary_sites()[model].block}"


def term_name(term: int, labels: pd.Series) -> str:
    """An exemplar's term as a row of panel A names it: `TERM_NAMES`, else its label in the vocabulary."""
    if term in TERM_NAMES:
        return TERM_NAMES[term]
    assert term in labels.index, f"Term {term} is not in the vocabulary."
    return str(labels[term])


def is_concept_table(tracks: pd.DataFrame) -> bool:
    """Whether a tracks table holds chosen poles on InterPLM's evaluation (`concept_exemplars`) rather than Figure 4's
    exemplars on the atlas's carriers."""
    return "concept" in tracks.columns


def row_name(chosen: pd.DataFrame, labels: pd.Series) -> str:
    """An exemplar's row label: its concept and the pole's test F1 for a concept table, else its vocabulary term."""
    if not is_concept_table(chosen):
        return term_name(int(chosen["term"].iloc[0]), labels)
    concept = str(chosen["concept"].iloc[0])
    name = CONCEPT_NAMES.get(concept, concept.split("_", 1)[-1])
    return f"{name}\ntest F1 {float(chosen['test_f1'].iloc[0]):.2f}"


def table_exemplars(tracks: pd.DataFrame, concepts: Sequence[str]) -> list[int]:
    """The exemplars of a concept table that draw the named concepts, in their order."""
    by_concept = tracks.drop_duplicates("concept").set_index("concept")["exemplar"]
    missing = [concept for concept in concepts if concept not in by_concept.index]
    assert not missing, f"Concepts {missing} have no tracks."
    return [int(by_concept[concept]) for concept in concepts]


def carrier_name(accession: str) -> str:
    """A carrier as its track names it: its gene name in `CARRIER_NAMES`, or its accession where none is recorded."""
    return CARRIER_NAMES.get(accession, accession)


def exemplar_inputs(root: Path, tracks_path: Path | None = None, exemplars: Sequence[int] | None = None,
                    concepts: Sequence[str] | None = None) -> tuple[pd.DataFrame, pd.Series, list[int], dict[str, str]]:
    """Panel A's tracks table (the archive's Figure 4 exemplars unless `tracks_path` names another), the vocabulary's
    labels by term token, the exemplars to draw in order and the columns (role -> head): for a concept table the named
    `concepts`, `DEFAULT_CONCEPTS` by default, under `CONCEPT_COLUMNS`; otherwise `exemplars`, `DEFAULT_EXEMPLARS` by
    default, under `ARCHIVE_COLUMNS`."""
    tracks = pd.read_parquet(tracks_path or root / "exemplars" / "tracks.parquet")
    labels = pd.read_parquet(root / "inputs" / "terms.parquet").set_index("token")["label"]
    if is_concept_table(tracks):
        columns = CONCEPT_COLUMNS
        exemplars = list(exemplars) if exemplars is not None else table_exemplars(tracks, concepts or DEFAULT_CONCEPTS)
    else:
        assert concepts is None, "Only a concept table is drawn by concept."
        columns = ARCHIVE_COLUMNS
        exemplars = list(exemplars) if exemplars is not None else list(DEFAULT_EXEMPLARS)
    return tracks, labels, exemplars, dict(columns)


def coverage_inputs(root: Path) -> tuple[dict[str, pd.DataFrame], dict[str, dict[str, object]]]:
    """Each model's concepts by feature type and route (`route_counts`) and its groups-of-poles report, the routes
    checked against the report's concept counts."""
    routes = {model: concept_routes(root, model) for model in MODELS}
    reports = {model: coalition_report(root, model) for model in MODELS}
    for model in MODELS:
        check_routes(routes[model], reports[model])
    return route_counts(routes), reports


# -- panels ------------------------------------------------------------------------------------------------------------


def exemplar_rows(ax_rows: Sequence[Sequence[Axes]], tracks: pd.DataFrame, exemplars: Sequence[int],
                  labels: pd.Series, columns: Mapping[str, str], *, leaks: bool = True) -> None:
    """Each exemplar a row of its proteins in the order of `columns` (a role and its head, written over the first
    row), its concept or term named at the left and each protein at its top right, on a y axis shared within the row
    by the tracks it shows. `leaks=False` leaves each neuron's leaks out of its tracks."""
    # tracks: `exemplars.track_table`'s schema; labels: term token -> label; columns: role -> head
    assert len(exemplars) == len(ax_rows), "One row of axes per exemplar."
    for row, (axes, exemplar) in enumerate(zip(ax_rows, exemplars, strict=True)):
        chosen = tracks[tracks["exemplar"] == exemplar]
        assert not chosen.empty, f"Exemplar {exemplar} has no tracks."
        shown = chosen[chosen["role"].isin(list(columns))]
        highest = float(np.nanmax(shown[list(POLE_NAMES)].to_numpy()))
        for column, (ax, (role, head)) in enumerate(zip(axes, columns.items(), strict=True)):
            if row == 0:
                ax.set_title(head, fontsize=6, color=MUTED, pad=2)
            carrier = chosen[chosen["role"] == role]
            if carrier.empty:  # an exemplar with fewer carriers leaves that place blank
                ax.set_axis_off()
                continue
            track_panel(ax, carrier, ymax=HEADROOM * highest, leaks=leaks)
            ax.text(0.98, 0.97, carrier_name(str(carrier["accession"].iloc[0])), transform=ax.transAxes, ha="right",
                    va="top", fontsize=5.5, color=INK)
            if column == 0:
                ax.set_ylabel(row_name(chosen, labels), fontsize=6.5, rotation=0, ha="right", va="center", labelpad=4)
            else:  # the row shares one scale, read off its first track
                ax.tick_params(labelleft=False)


def track_handles(*, leaks: bool = True) -> list[object]:
    """The key to the tracks: the labeled pole, its neuron's other pole and (unless `leaks=False`) leaks, the threshold
    and the term's residues."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    leak = [Line2D([], [], color=LEAK, linewidth=0.8, label="leaks")] if leaks else []
    return [Line2D([], [], color=NATIVE, linewidth=0.9, label="labeled pole's activation"),
            Line2D([], [], color=OPPOSITE, linewidth=0.6, label="same neuron's other pole"),
            *leak,
            Line2D([], [], color=MUTED, linewidth=0.6, linestyle=(0, (3, 2)), label="threshold"),
            Patch(facecolor=ROW_BAND, edgecolor="none", label="term's residues")]


def track_key(ax: Axes) -> None:
    """The key to the tracks, in one row above the first track row."""
    handles = track_handles()
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 1.22), ncol=len(handles), handlelength=1.8,
              handletextpad=0.5, columnspacing=1.2, borderaxespad=0.0)


class _SplitHandler:
    """A legend handle for concepts both bases read: the neurons' red over the SAE's yellow, as the bars draw it."""

    def legend_artist(self, legend: object, handle: object, fontsize: float, box: object) -> object:
        from matplotlib.patches import Rectangle

        x, y = box.xdescent, box.ydescent
        width, height = box.width, box.height
        upper = Rectangle((x, y + height / 2), width, height / 2, facecolor=NATIVE, edgecolor="none",
                          transform=box.get_transform())
        lower = Rectangle((x, y), width, height / 2, facecolor=SAE, edgecolor="none", transform=box.get_transform())
        box.add_artist(upper)
        box.add_artist(lower)
        return upper


def route_panel(ax: Axes, counts: pd.DataFrame, *, labels: bool) -> None:
    """Concepts of each feature type as one bar, from the left: read by the neurons only (red), by both (red over
    yellow), by the SAE only (yellow) and by neither (pale); each route's total in the key."""
    # counts: one model's `route_counts`, (types, routes)
    import matplotlib

    from matplotlib.patches import Patch

    rows = np.arange(len(counts))  # (types,)
    height = 0.72
    with matplotlib.rc_context(STYLE):
        left = np.zeros(len(counts))  # (types,)
        for segment in SEGMENTS:
            width = counts[segment].to_numpy(dtype=np.float64)  # (types,)
            if segment == "both":
                ax.barh(rows - height / 4, width, height=height / 2, left=left, color=NATIVE, linewidth=0, zorder=3)
                ax.barh(rows + height / 4, width, height=height / 2, left=left, color=SAE, linewidth=0, zorder=3)
            else:
                color = {"neurons_only": NATIVE, "sae_only": SAE, "neither": NEITHER}[segment]
                ax.barh(rows, width, height=height, left=left, color=color, linewidth=0, zorder=3)
            left = left + width
        ax.set_yticks(rows, list(counts.index) if labels else [""] * len(rows))
        ax.set_ylim(len(rows) - 0.4, -0.6)
        ax.tick_params(axis="y", length=0)
        ax.set_xlabel("concepts")
        _grid(ax, "x")
        totals = counts.sum()
        handles = [Patch(facecolor=NATIVE, label=f"{SEGMENT_NAMES['neurons_only']}  {totals['neurons_only']}"),
                   Patch(label=f"{SEGMENT_NAMES['both']}  {totals['both']}"),
                   Patch(facecolor=SAE, label=f"{SEGMENT_NAMES['sae_only']}  {totals['sae_only']}"),
                   Patch(facecolor=NEITHER, label=f"{SEGMENT_NAMES['neither']}  {totals['neither']}")]
        ax.legend(handles=handles, handler_map={handles[1]: _SplitHandler()}, loc="lower right", handlelength=1.2,
                  handletextpad=0.5, borderaxespad=0.2, labelspacing=0.3, frameon=True, facecolor="white",
                  edgecolor="none", framealpha=1.0, borderpad=0.3)


def coalition_lines(ax: Axes, reports: Mapping[str, Mapping[str, object]], *, right: float,
                    ) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """Against the largest group of poles a fit may use, the share of each model's write-SAE activity on latents that a
    held-out fit tracks at r of at least 0.7: a rotation's poles (gray, dashed) below the neurons' poles (red), a
    model's marker on both its lines, the x axis running to `right`. Returns each model's neuron line as (model, sizes,
    shares in percent)."""
    import matplotlib

    with matplotlib.rc_context(STYLE):
        lines = []
        for model, report in reports.items():
            sizes = np.array([int(size) for size in report["sizes"]])  # (s,)
            shares = report["shares"][TRACKED]
            marker = MODEL_MARKERS[model]
            for basis, color, dash in (("rotation", ROTATION, (0, (3, 2))), ("native", NATIVE, "-")):
                values = np.array([100 * shares[basis]["mass_share"][str(size)] for size in sizes])  # (s,)
                ax.plot(sizes, values, color=color, linestyle=dash, marker=marker, markersize=2.8, zorder=3)
                if basis == "native":
                    lines.append((model, sizes, values))
        ax.set_xscale("log", base=2)
        ax.set_xticks([1, 4, 16, 64], ["1", "4", "16", "64"])
        ax.minorticks_off()
        ax.set_xlim(0.55, right)
        ax.spines["bottom"].set_bounds(1, 64)
        ax.set_ylim(0, 45)
        ax.set_yticks([0, 10, 20, 30, 40])
        ax.set_xlabel("poles per fit, at most")
        ax.set_ylabel("SAE activity tracked (%)")
        _grid(ax)
    return lines  # each model's (name, sizes (s,), shares (s,))


def coalition_panel(ax: Axes, reports: Mapping[str, Mapping[str, object]]) -> None:
    """`coalition_lines`, each model named at its line's end with the shares at one pole and at 64; the concepts only
    the SAE reads whose latent the neurons' fit tracks, as counts."""
    import matplotlib

    lines = coalition_lines(ax, reports, right=64 * 6.5)
    sizes = lines[-1][1]  # (s,)
    with matplotlib.rc_context(STYLE):
        highest = max(values[0] for _, _, values in lines)
        for model, sizes, values in lines:
            above = values[0] == highest  # the upper line's start is labeled above it, the lower line's below
            ax.text(sizes[0], values[0] + (2.2 if above else -2.2), f"{values[0]:.0f}%", ha="center",
                    va="bottom" if above else "top", fontsize=6, color=NATIVE)
            ax.text(sizes[-1] * 1.18, values[-1], f"{values[-1]:.0f}%  {MODEL_NAMES[model]}", ha="left", va="center",
                    fontsize=6, color=NATIVE)
        ax.text(sizes[-1] * 1.18, 2.0, "rotated\npoles", ha="left", va="center", fontsize=6, color=MUTED)
        tracked = []
        for model, report in reports.items():
            sae_only = report["concepts"]["sae_only"]
            reached = sum(int(count) for count in sae_only["native"]["reached_by_size"].values())
            tracked.append(f"{MODEL_NAMES[model]}  {reached} of {sae_only['concepts']}")
        ax.text(0.30, 0.27, "SAE-only concepts tracked\n" + "\n".join(tracked), transform=ax.transAxes, ha="left",
                va="center", fontsize=6, color=INK, linespacing=1.3)


def agreement_panel(ax: Axes, agreement: Mapping[str, object], *, annotate: bool = True,
                    arm_names: Mapping[str, str] = AGREEMENT_ARMS) -> None:
    """For protein-level and residue-level labels, the mean probability that a latent's curated label is closer to its
    own Biohub description than to a matched one, against chance (dashed): each arm named by `arm_names`, and with
    `annotate` the chance line and each probability written in place."""
    import matplotlib

    arms = agreement["arms"]
    assert list(arm_names) == list(AGREEMENT_ARMS), f"Arm names {list(arm_names)} differ from {list(AGREEMENT_ARMS)}."
    with matplotlib.rc_context(STYLE):
        chance = {float(arms[arm]["win_probability_chance"]) for arm in AGREEMENT_ARMS}
        assert len(chance) == 1, "The arms disagree on chance."
        (level,) = chance
        ax.axvline(level, color=MUTED, linewidth=0.8, linestyle=(0, (3, 2)), zorder=1)
        if annotate:
            ax.text(level - 0.006, len(AGREEMENT_ARMS) - 0.55, "chance", ha="right", va="bottom", fontsize=6,
                    color=MUTED)
        for row, arm in enumerate(AGREEMENT_ARMS):
            value = float(arms[arm]["mean_matched_win_probability"])
            ax.plot([level, value], [row, row], color=SAE, linewidth=2.2, solid_capstyle="butt", zorder=2)
            ax.plot(value, row, marker="o", color=SAE, markeredgecolor=INK, markeredgewidth=0.6, markersize=6,
                    linestyle="none", zorder=3)
            if annotate:
                ax.text(value + 0.012, row, f"{value:.2f}", ha="left", va="center", fontsize=6.5, color=INK)
        ax.set_yticks(range(len(AGREEMENT_ARMS)), list(arm_names.values()))
        ax.set_ylim(len(AGREEMENT_ARMS) - 0.45, -0.6)
        ax.set_xlim(0.45, 0.78)
        ax.set_xticks([0.5, 0.6, 0.7])
        ax.set_xlabel("probability the own description\nis closer than a matched one")
        ax.tick_params(axis="y", length=0)
        _grid(ax, "x")


# -- the figure --------------------------------------------------------------------------------------------------------


def figure_labels(root: Path, tracks_path: Path | None = None, exemplars: Sequence[int] | None = None,
                  concepts: Sequence[str] | None = None) -> Figure:
    """(A) labeled poles along proteins, one row per exemplar of a tracks table (the archive's Figure 4 exemplars unless
    `tracks_path` names another): for a concept table (`concept_exemplars`) the named `concepts`, `DEFAULT_CONCEPTS` by
    default, on two random carriers, the strongest and a protein without the concept; otherwise `exemplars` on their
    three strongest held-out carriers and one drawn at random; (B) the concepts of each Swiss-Prot feature type read by
    the neurons, the write SAE, both or neither, at three quarters of ESMC-600 and ESMC-6B; (C) the write SAE's activity
    that groups of poles track; (D) curated labels against Biohub's descriptions of the same latents."""
    import matplotlib

    tracks, labels, exemplars, columns = exemplar_inputs(root, tracks_path, exemplars, concepts)
    counts, reports = coverage_inputs(root)
    rows = len(exemplars)
    with matplotlib.rc_context(STYLE):
        heights = [TRACK_ROW * rows, 1.55, 1.3]  # inches of panel A, B and the row of C and D
        figure = new_figure(sum(heights) + 1.75, width=WIDTH)
        outer = figure.add_gridspec(3, 1, height_ratios=heights, hspace=0.75 / np.mean(heights), left=0.115,
                                    right=0.985, top=1 - 0.3 / (sum(heights) + 1.75), bottom=0.5 / (sum(heights) + 1.75))
        # An empty first column makes room for the rows' names, which are longer than B's tick labels.
        upper = outer[0].subgridspec(rows, len(columns) + 1, width_ratios=[LABEL_SPACE] + [1.0] * len(columns),
                                     hspace=0.62 if rows > 1 else 0.3, wspace=0.16)
        ax_rows = [[figure.add_subplot(upper[row, column + 1]) for column in range(len(columns))] for row in range(rows)]
        exemplar_rows(ax_rows, tracks, exemplars, labels, columns)
        for ax in ax_rows[-1]:
            ax.set_xlabel("residue", fontsize=6.5, labelpad=1)
        letter(ax_rows[0][0], "A")
        track_key(ax_rows[0][0])
        middle = outer[1].subgridspec(1, len(MODELS), wspace=0.06)
        for column, model in enumerate(MODELS):
            ax = figure.add_subplot(middle[0, column])
            route_panel(ax, counts[model], labels=column == 0)
            ax.set_title(site_title(model), loc="left", fontsize=6.5, color=INK, pad=3)
            if column == 0:
                letter(ax, "B")
        lower = outer[2].subgridspec(1, 2, width_ratios=[1.0, 1.0], wspace=0.55)
        fits = figure.add_subplot(lower[0])
        coalition_panel(fits, reports)
        letter(fits, "C")
        agreement = figure.add_subplot(lower[1])
        agreement_panel(agreement, agreement_report(root))
        letter(agreement, "D")
    return figure


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, required=True, help="the neuron study's archive")
    parser.add_argument("--out", type=Path, required=True, help="the PNG to write")
    parser.add_argument("--tracks", type=Path, default=None, help="a tracks table of the archive's schema to draw in A")
    parser.add_argument("--exemplars", type=int, nargs="+", default=None,
                        help="the exemplars of the tracks table to draw, one row each, in order")
    parser.add_argument("--concepts", nargs="+", default=None,
                        help="for a concept table, the concepts to draw, one row each, in order (DEFAULT_CONCEPTS)")
    arguments = parser.parse_args()
    figure = figure_labels(arguments.root, arguments.tracks, arguments.exemplars, arguments.concepts)
    print(save_figure(figure, arguments.out))


if __name__ == "__main__":
    main()
