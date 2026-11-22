"""Compare vocabulary-derived feature interpretations with the released Biohub descriptions.

`biohub/ESMC-SAE-Features` publishes one agent-written description per feature of
`ESMC-6B-sae-layer60-k64-codebook16384`, together with the Swiss-Prot proteins that activate it
most strongly. Biohub published no numerical accuracy benchmark for those descriptions, so this
module does not claim to reproduce one. It measures four things that the released artifacts do
support:

1. Pipeline fidelity. Where do our recomputed activations rank the proteins Biohub lists as a
   feature's strongest Swiss-Prot activators? A faithful reimplementation puts them near the top.
2. Concordance. Is the vocabulary term our statistic assigns to a feature enriched among the
   proteins Biohub lists for that feature, relative to its Swiss-Prot base rate?
3. Category recovery. Does the vocabulary aspect of our top term agree with the agent's category?
4. Lexical agreement. Does our term label appear in the agent's summary text?

Observed schema of the released table, which differs from its README in one respect worth
recording: `top_swissprot_activations` holds exactly 20 entries per feature, not 100. The table
covers 16,384 features, 40,437 distinct Swiss-Prot accessions, and 327,680 feature-protein pairs.
206 features carry a null `category`.

Symbols: `c` codebook features, `t` vocabulary terms, `n` proteins.
"""

import numpy as np
import pandas as pd

from dataclasses import dataclass
from scipy import stats

from foundry.metrics.multiple_testing import benjamini_hochberg


FEATURE_TABLE_REPO = "biohub/ESMC-SAE-Features"
FEATURE_TABLE_FILE = "uniref90_feature_table.parquet"
EXPECTED_TOP_SWISSPROT = 20

# The agent category and the vocabulary aspect describe different axes and must not be scored as
# if one predicted the other. The category says *where in a protein* a feature fires: on a helix,
# on a binding site, on a disordered tail. The aspect says *which ontology names the concept*. A
# feature that fires on the Walker A helix of ABC transporters is category "Structural motif" and
# is correctly described by the InterPro entry "P-loop containing nucleoside triphosphate
# hydrolase", so demanding a structural aspect there would mark a correct answer wrong.
#
# What can be checked is compatibility: given the agent's category, is the aspect we assigned one
# that can express that concept at all. The residue-local aspects are the direct expression of a
# category; the global ontology aspects express it indirectly, by naming the family the feature
# belongs to. Both are listed, and the report presents the result as a compatibility rate and a
# contingency table rather than as an accuracy.
LOCAL_CATEGORY_ASPECTS = {
    "Catalytic function": ("local_active_site",),
    "Ligand-binding site": ("local_binding",),
    "Domain": ("local_domain", "local_interpro"),
    "Membrane-associated": ("local_transmembrane", "local_intramembrane", "local_topological_domain"),
    "Disorder": ("local_region", "local_compositional_bias"),
    "Compositional bias": ("local_compositional_bias",),
    "Structural motif": ("local_helix", "local_strand", "local_turn", "local_coiled_coil"),
    "Repeat": ("local_repeat",),
    "Sequence motif": ("local_motif",),
    "Post-translational modification": (
        "local_modified_residue",
        "local_glycosylation",
        "local_lipidation",
        "local_disulfide",
        "local_crosslink",
        "local_signal_peptide",
        "local_transit_peptide",
        "local_propeptide",
    ),
    "Interaction site": ("local_site", "local_dna_binding", "local_zinc_finger"),
    "Taxonomic bias": ("taxonomy",),
}

# Aspects that can name the family or function a feature belongs to, whatever its localization.
FAMILY_ASPECTS = ("interpro", "gene3d", "pfam", "ec", "rhea", "go_mf", "go_bp", "go_cc",
                  "cofactor", "keyword", "subcellular_location")

CATEGORY_TO_ASPECTS = {
    category: tuple(aspects) + FAMILY_ASPECTS
    for category, aspects in LOCAL_CATEGORY_ASPECTS.items()
}


def load_feature_table(local_path: str = "") -> pd.DataFrame:
    """Load the released feature table and assert the schema this module relies on."""
    if local_path:
        table = pd.read_parquet(local_path)
    else:
        from huggingface_hub import hf_hub_download

        table = pd.read_parquet(
            hf_hub_download(FEATURE_TABLE_REPO, FEATURE_TABLE_FILE, repo_type="dataset")
        )

    assert len(table) == 16_384, f"expected 16384 features, found {len(table)}"
    lengths = table["top_swissprot_activations"].map(len)
    assert lengths.min() == lengths.max() == EXPECTED_TOP_SWISSPROT, (
        f"released top_swissprot_activations is not uniformly {EXPECTED_TOP_SWISSPROT} entries"
    )
    return table


def reference_accessions(table: pd.DataFrame) -> pd.DataFrame:
    """Return the released (feature_id, accession, activation) triples as a flat frame."""
    feature_ids: list[int] = []
    accessions: list[str] = []
    activations: list[float] = []

    for feature_id, records in zip(table["feature_id"], table["top_swissprot_activations"], strict=False):
        for record in records:
            feature_ids.append(int(feature_id))
            accessions.append(str(record["uniprot_id"]))
            activations.append(float(record["activation"]))

    return pd.DataFrame(
        {"feature_id": feature_ids, "accession": accessions, "released_activation": activations}
    )


@dataclass(frozen=True, slots=True)
class FidelityResult:
    """Where our recomputed activations rank the released exemplar proteins."""

    percentile_rank: np.ndarray
    spearman_by_feature: np.ndarray
    fraction_in_top_100: float
    median_percentile: float


def pipeline_fidelity(
    pooled_max: np.ndarray,
    accession_to_row: dict[str, int],
    reference: pd.DataFrame,
    column_block: int = 512,
) -> FidelityResult:
    """Rank the released exemplars inside our own activation distribution for each feature.

    This is a reimplementation check, not a scientific result. Numerical drift is expected because
    the released activations came from fused kernels this environment does not have, so the
    expected outcome is a high percentile rank rather than an exact value match.
    """
    # pooled_max: (n, c)
    n_proteins = pooled_max.shape[0]
    reference = reference[reference["accession"].isin(accession_to_row)].copy()
    reference["row"] = reference["accession"].map(accession_to_row).astype(np.int64)

    percentiles: list[float] = []
    spearman: list[float] = []
    by_feature = dict(list(reference.groupby("feature_id", sort=True)))

    # Read the pooled matrix in contiguous column blocks. A memory-mapped `(n, c)` array is stored
    # row-major, so touching one column at a time walks the entire file per feature; at c = 16384
    # that is thousands of full passes over tens of gigabytes.
    for start in range(0, pooled_max.shape[1], column_block):
        stop = min(start + column_block, pooled_max.shape[1])
        block = np.asarray(pooled_max[:, start:stop], dtype=np.float32)  # (n, mc)
        order = np.sort(block, axis=0)  # (n, mc)

        for feature_id in range(start, stop):
            group = by_feature.get(feature_id)
            if group is None:
                continue
            rows = group["row"].to_numpy()  # (e,)
            values = block[rows, feature_id - start]  # (e,)
            # Midrank of each exemplar without ranking the whole column: the number of strictly
            # smaller values and the number of values at most equal bracket its rank.
            lower = np.searchsorted(order[:, feature_id - start], values, side="left")  # (e,)
            upper = np.searchsorted(order[:, feature_id - start], values, side="right")  # (e,)
            percentiles.extend(((lower + upper) / 2.0 / n_proteins).tolist())

            released = group["released_activation"].to_numpy()  # (e,)
            if len(np.unique(released)) > 1 and len(np.unique(values)) > 1:
                spearman.append(float(stats.spearmanr(released, values).statistic))

    percentile_rank = np.asarray(percentiles)  # (c*20,)
    in_top_100 = float(np.mean(percentile_rank >= 1.0 - 100.0 / n_proteins))

    return FidelityResult(
        percentile_rank=percentile_rank,
        spearman_by_feature=np.asarray(spearman),
        fraction_in_top_100=in_top_100,
        median_percentile=float(np.median(percentile_rank)),
    )


@dataclass(frozen=True, slots=True)
class ConcordanceResult:
    """Enrichment of each feature's assigned vocabulary term among the released exemplars."""

    frame: pd.DataFrame

    @property
    def fraction_significant(self) -> float:
        """Return the fraction of features whose assigned term is enriched at q < 0.01."""
        if not len(self.frame):
            return float("nan")
        return float((self.frame["q_value"] < 0.01).mean())

    @property
    def median_enrichment(self) -> float:
        if not len(self.frame):
            return float("nan")
        return float(self.frame["enrichment"].median())

    @property
    def pooled_enrichment(self) -> float:
        """Return total hits over total expected hits, summed across features.

        Twenty exemplars give almost no power per feature, so the pooled ratio is the statement
        worth reporting: across every scored feature, how many more of the agent's own exemplars
        carry our assigned term than chance would give.
        """
        if not len(self.frame):
            return float("nan")
        expected = float(self.frame["expected"].sum())
        return float(self.frame["n_hit"].sum()) / expected if expected > 0 else float("nan")

    @property
    def fraction_with_any_hit(self) -> float:
        """Return the fraction of features whose assigned term appears in at least one exemplar."""
        if not len(self.frame):
            return float("nan")
        return float((self.frame["n_hit"] > 0).mean())

    @property
    def expected_fraction_with_any_hit(self) -> float:
        """Return the same fraction expected by chance, from each feature's own base rate."""
        if not len(self.frame):
            return float("nan")
        none = (1.0 - self.frame["base_rate"]) ** self.frame["n_drawn"]
        return float((1.0 - none).mean())


def term_concordance(
    assigned_term: np.ndarray,
    term_carriers: dict[int, set[str]],
    reference: pd.DataFrame,
    analyzed_accessions: set[str],
    min_drawn: int = 5,
    prevalence: dict[int, float] | None = None,
    unit_of: dict[str, str] | None = None,
) -> ConcordanceResult:
    """Test whether each feature's assigned term is over-represented among its exemplars.

    The draw is restricted to the exemplars that are actually in the analyzed population, and the
    base rate is computed over that same population. Counting exemplars we hold no activations for
    would inflate the denominator and drive every enrichment toward zero, which is exactly what
    happens on a partial extraction.

    Per-feature power is limited by design: there are at most 20 exemplars, so a term with a 1%
    base rate has an expected count near 0.2 and a median count of zero even when the assignment is
    correct. The per-feature test is therefore reported alongside a pooled test over all features,
    which is the better-powered statement.
    """
    # assigned_term: (c,)
    # Hits are always counted against the full carrier set, because an exemplar either carries the
    # term or it does not. Only the *rate* those hits are compared against can be re-estimated, which
    # is what `prevalence` overrides for the background sensitivity. Restricting the carrier set
    # instead would drive every count to zero, since the background excludes the exemplars.
    #
    # `unit_of` maps an accession to its homology cluster. A hypergeometric draw assumes the drawn
    # items are exchangeable, and 90.5% of released exemplar sets contain two proteins from the same
    # 30% identity cluster, so a protein-level draw counts correlated evidence as independent.
    # Collapsing accessions to clusters makes the draw, the carrier set, and the population all
    # cluster-level, which is the unit the split and the discovery sampling already use.
    def unit(accession: str) -> str:
        return unit_of.get(accession, accession) if unit_of is not None else accession

    population_units = {unit(a) for a in analyzed_accessions}
    n_population = len(population_units)
    grouped = reference.groupby("feature_id")["accession"].apply(set)
    rows: list[dict[str, float | int]] = []

    for feature_id, exemplars in grouped.items():
        term = int(assigned_term[int(feature_id)])
        if term < 0:
            continue
        carriers = term_carriers.get(term)
        if not carriers:
            continue

        present = {unit(a) for a in exemplars & analyzed_accessions}
        n_drawn = len(present)
        if n_drawn < min_drawn:
            continue

        carrier_units = {unit(a) for a in carriers}
        n_hit = len(present & carrier_units)
        base_rate = (
            prevalence[term] if prevalence is not None and term in prevalence
            else len(carrier_units) / n_population
        )
        n_carriers_effective = max(1, int(round(base_rate * n_population)))
        rows.append(
            {
                "feature_id": int(feature_id),
                "term": term,
                "n_hit": n_hit,
                "n_drawn": n_drawn,
                "n_carriers": len(carrier_units),
                "base_rate": base_rate,
                "expected": base_rate * n_drawn,
                "enrichment": (n_hit / n_drawn) / base_rate if base_rate > 0 else np.nan,
                "p_value": float(
                    stats.hypergeom.sf(n_hit - 1, n_population, n_carriers_effective, n_drawn)
                ),
            }
        )

    columns = [
        "feature_id", "term", "n_hit", "n_drawn", "n_carriers",
        "base_rate", "expected", "enrichment", "p_value",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    frame["q_value"] = (
        benjamini_hochberg(frame["p_value"].to_numpy()) if len(frame) else np.zeros(0)
    )
    return ConcordanceResult(frame=frame)


def category_recovery(
    assigned_aspect: dict[int, str],
    table: pd.DataFrame,
) -> pd.DataFrame:
    """Cross-tabulate the agent category against the aspect of our assigned term.

    `compatible` means the aspect can express the category at all, directly through a matching
    residue-local aspect or indirectly by naming the family. `local_match` is the stricter and more
    interesting column: it is true only when we answered with the residue-local aspect that
    corresponds to the category, which is the part a global-only vocabulary cannot do.
    """
    rows: list[dict[str, object]] = []

    for feature_id, category in zip(table["feature_id"], table["category"], strict=False):
        aspect = assigned_aspect.get(int(feature_id))
        if aspect is None or not isinstance(category, str):
            continue
        rows.append(
            {
                "feature_id": int(feature_id),
                "category": category,
                "aspect": aspect,
                "compatible": aspect in CATEGORY_TO_ASPECTS.get(category, ()),
                "local_match": aspect in LOCAL_CATEGORY_ASPECTS.get(category, ()),
                "is_local_aspect": str(aspect).startswith("local_"),
            }
        )

    return pd.DataFrame(rows)


def _informative_tokens(text: str, min_token_length: int) -> set[str]:
    """Return the content words of a phrase, lowercased and stripped of punctuation."""
    tokens = set()
    for raw in str(text).casefold().replace("/", " ").replace("-", " ").split():
        token = raw.strip("(),.;:[]- ")
        if len(token) >= min_token_length:
            tokens.add(token)
    return tokens


def lexical_agreement(
    assigned_label: dict[int, str],
    table: pd.DataFrame,
    min_token_length: int = 4,
    agent_labels: dict[int, str] | None = None,
) -> pd.DataFrame:
    """Score whether our term name shares content words with the agent's description of a feature.

    This is the weakest comparison in this module because it turns on wording rather than biology,
    and it is reported as such. Two targets are scored. The agent's paragraph-length `summary` is
    permissive: a long paragraph shares words with almost any protein term. The short `label` served
    by the feature endpoint, a few words such as "P-loop Walker A S/T", is the strict target and the
    one worth quoting.
    """
    summaries = dict(zip(table["feature_id"].astype(int), table["summary"].astype(str), strict=False))
    exemplars = dict(zip(table["feature_id"].astype(int), table["exemplar_protein_families"].astype(str), strict=False))
    agent_labels = agent_labels or {}
    rows: list[dict[str, object]] = []

    for feature_id, label in assigned_label.items():
        tokens = _informative_tokens(label, min_token_length)
        if not tokens:
            continue

        summary = summaries.get(feature_id, "").casefold()
        exemplar = exemplars.get(feature_id, "").casefold()
        short = agent_labels.get(feature_id, "")
        short_tokens = _informative_tokens(short, min_token_length)

        rows.append(
            {
                "feature_id": feature_id,
                "label": label,
                "agent_label": short,
                "n_tokens": len(tokens),
                "summary_hits": sum(token in summary for token in tokens),
                "exemplar_hits": sum(token in exemplar for token in tokens),
                "any_hit": any(token in summary or token in exemplar for token in tokens),
                "label_hits": len(tokens & short_tokens),
                "label_any_hit": bool(tokens & short_tokens),
                "label_jaccard": (
                    len(tokens & short_tokens) / len(tokens | short_tokens)
                    if tokens | short_tokens
                    else 0.0
                ),
            }
        )

    return pd.DataFrame(rows)
