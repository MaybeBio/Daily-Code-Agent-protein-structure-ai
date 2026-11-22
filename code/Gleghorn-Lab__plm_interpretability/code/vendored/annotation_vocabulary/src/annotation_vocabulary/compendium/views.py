"""Views: task datasets read off the compendium, each a filter, a target rule, its negatives and the split it inherits.

The tier rule every view shares (the Atlas v3 pattern, Logan 2026-10-20): in train and calibration a protein's term is a label at
any label tier; in validation and test only experimental and signature labels score, and a curated one is masked, neither positive
nor negative. A guard is masked everywhere and a skipped code is ignored. A set view is closed world within the proteins observed
in its aspects (CAFA's rule): a protein is a row only where it has a label there, and every unlisted, unmasked term of the view is
its negative.

- `whole_vocabulary`: every vocabulary term as asserted, with its token, for the Translator, CAMP and Oracle One, and the
  observation units a protein's negatives come from (`observation_units`).
- `set_view`: a multi-label view of some aspects with true-path propagation, such as GO's three aspects or localization, over
  the vocabulary's terms and the ancestors that 10 or more train proteins reach (`set_view_terms`).
- `metal_ions`: the set view of which metal ions a protein binds, over GO's terms below metal ion binding, from its GO MF terms and
  the binding sites and cofactors of ChEBI metal ions, each statement at its own tier (`metal_assertions`).
- `modifications`: the set view of which modifications a protein carries, over keywlist's PTM keywords (Phosphoprotein,
  Glycoprotein, Acetylation, Ubl conjugation, Disulfide bond and the rest), each at the tier the pool gave it from the sites that
  imply it (`modification_assertions`).
- `modification_sites`: which residues carry each modification, the residue-level sites of ptmlist's modifications and of
  cross-links to ubiquitin-like proteins, each residue at its own tier, the other residues of a class's kind in a protein with a
  site of it its negatives (`modification_site_view`).
- `disordered_regions`: which residues are disordered, the residues of a protein's disordered regions (DisProt's curated ones and
  UniProt's), each at its own tier, and the residues DisProt states ordered; its other residues are its negatives, as CAID's
  DisProt reference counts them, and the residues a PDB structure observes (SIFTS) are its DisProt-PDB reference's only ones
  (`disorder_view`).
- `located_features`: which residues carry each of UniProt's other located features, binding and active sites, transmembrane,
  signal and transit spans, disulfide bonds, motifs, repeats, domains and regions among them, each residue at its feature's tier,
  and an aspect's type term, such as Active site, every residue of the aspect's other classes too; a protein's other residues are
  its negatives for a class it holds (`located_feature_view`).
- `lineage`: every protein's taxon at the eight named ranks where its organisms agree, the taxon Oracle's chained choices from
  domain to genus, and its organism split, which holds whole species out for the labels a protein inherits from its organism
  (`organisms.py`).
- `ec_view`: one EC number per enzyme, at its four levels, for a chained choice, and the confident non-enzymes, `non_enzyme` at
  level 1 (`non_enzymes.py`); `matched` marks the rows matched in lineage and length that answer whether a protein is an enzyme.
- `homodimer_view`: a binary choice, whether a protein is a homodimer or a monomer, from the oligomeric states its subunit
  comments state, each with its own sentence's evidence.
- `ph_optimum_view`: a regression view, the optimum pH that Swiss-Prot's pH-dependence texts state from a cited experiment, read
  as `ph_optimum_experimental_v2` reads them: the mean of a protein's distinct observations, and the observations.
- `melting_temperature_view`: a regression view, the melting point thermal proteome profiling of 13 organisms' lysates measured
  (the Meltome Atlas, read as `thermal_tm_experimental_v1` reads it): the mean of a pooled protein's observations, and the
  observations, each found through its accession, a secondary accession of a read entry or a fetched entry of the same sequence.
- `kinetic_view`: two regression views, kcat and KM, the mean log10 of the turnover numbers or Michaelis constants a protein's
  Swiss-Prot kinetics statements state from a cited experiment (`kinetics.py`), as `kcat_experimental_v1` defines its target,
  and the observations, each with its substrate, the ChEBI entity that names it, and the stated pH and temperature.

Each set and EC view reads one protein's rows at a time and no other's, so it runs on the pool whole or a partition at a time
(`tables.PARTITIONS`), its counts adding up; the EC view's `matched` is drawn over its whole table once the partitions are read. The
pH, melting temperature and kinetic views read their few thousand texts or rows whole.

The other Oracle releases become views one at a time (the compendium decision), each compared with its release:
TODO(compendium_view_ph_optimum): BRENDA's pH optima, `ph_optimum_experimental_v2`'s other source, join the pH view once BRENDA's
terms are settled (approvals item 57) and BRENDA joins the sources.
TODO(compendium_view_kcat): SABIO-RK's turnover numbers, `kcat_experimental_v1`'s source, join the kcat view, now Swiss-Prot's
alone, once the licence Logan is negotiating with HITS allows it (the kcat release decision) and SABIO-RK joins the sources.
TODO(compendium_view_metal_binding): the metal ion view says which metals a metal-binding protein binds;
`metal_ion_binding_experimental_v1`'s question, whether a protein binds one at all, needs its nonbinders' metal-free X-ray
structures, so it becomes a view once RCSB's chemical components of the cross-referenced PDB entries join the sources.
TODO(compendium_view_solubility): `solubility_experimental_v1` reads assays outside UniProt (eSOL and others), so it becomes a view
once those sources join the compendium's measurements.
TODO(compendium_view_expression): the E. coli expression release (`datasets/builders/expression_experimental`) likewise.
TODO(compendium_measured_entries): the melting temperature view loses 2,685 points of TrEMBL entries the pool does not admit,
most of them of the thermophiles and the psychrophile, whose proteomes UniProt has reviewed least, so its range is narrower than
the workbook's; the next edition admits an entry with a measurement to the pool, or the view takes a split of its own over them.
"""

from __future__ import annotations

import math
import re
import pyarrow as pa
import pyarrow.compute as pc

from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence

from foundry.protein.meltome import MELTING_POINTS_SHEET, SPECIES
from foundry.protein.ph_optimum import judge_text
from foundry.protein.uniprot_xml import EXPERIMENTAL as EXPERIMENTAL_CODE
from .non_enzymes import NON_ENZYME
from .ontologies import Edge
from .pool import entry_exclusion
from .tables import split_frame, take_by_key
from .tiers import GO_STOPLIST, LABEL_TIERS, TIERS
from .uniprot import FEATURE_TERMS
from .vocabulary import best_tiers
from ..experimental.pool import protein_id
from ..grammar import COMPENDIUM_ASPECT_ORDER, LOCAL_FEATURE_ASPECTS, build_vocabulary_index
from ..schema import TermKey, canonical_term_id


SCORING_SPLITS = ("validation", "test")
EXPERIMENTAL, SIGNATURE, CURATED, GUARD, SKIP = range(len(TIERS))
EC_LEVELS = 4
# The pooled assertion columns the views read.
VIEW_COLUMNS = ["protein_id", "term_id", "aspect", "source_database", "term", "tier", "negated"]
_ROW = [("protein_id", pa.string()), ("sequence", pa.string()), ("split", pa.string())]
WHOLE_VOCABULARY_SCHEMA = pa.schema([
    *_ROW, ("tokens", pa.list_(pa.int32())), *[(name, pa.list_(pa.string())) for name in ("terms", "tiers", "masked", "observed_units")],
])
TOKEN_SCHEMA = pa.schema([("term_id", pa.string()), ("token", pa.int32()), ("fundamental_aspect", pa.string()), ("unit", pa.string())])
SET_VIEW_SCHEMA = pa.schema([*_ROW, *[(name, pa.list_(pa.string())) for name in ("positives", "masked", "negated")]])
# A set view's terms (`set_view_terms`): each term's view, id and concept, whether it is a vocabulary term, and the train proteins
# that reach it by propagation.
VIEW_TERM_SCHEMA = pa.schema([
    ("view", pa.string()), ("term_id", pa.string()), ("aspect", pa.string()), ("source_database", pa.string()), ("accession", pa.string()),
    ("in_vocabulary", pa.bool_()), ("train_support", pa.int64()),
])
# The metal ion view (`metal_assertions`). Its root, GO's metal ion binding, says a protein binds some metal and names none, so it is
# no term of the view, and a protein that states only it, or only a metal GO has no term for, is no row.
METAL_VIEW = "metal_ions"
METAL_ION_BINDING = "GO:0046872"
METAL_SOURCES = ("local_binding", "cofactor")  # the aspects whose ChEBI metal ions the view reads, beside GO MF
# The GO term of a ChEBI metal ion: by the ion where GO tells its oxidation states apart, else by the element its ChEBI name gives.
# A metal GO names no term for (strontium, barium, the lanthanides) and ChEBI's classes of metal cations take the root.
METAL_GO = {
    "zinc": "GO:0008270", "calcium": "GO:0005509", "magnesium": "GO:0000287", "manganese": "GO:0030145", "iron": "GO:0005506",
    "copper": "GO:0005507", "nickel": "GO:0016151", "cobalt": "GO:0050897", "potassium": "GO:0030955", "sodium": "GO:0031402",
    "lithium": "GO:0031403", "cadmium": "GO:0046870", "mercury": "GO:0045340", "lead": "GO:0032791", "molybdenum": "GO:0030151",
    "vanadium": "GO:0051212",
}
OXIDATION_GO = {"iron(2+)": "GO:0008198", "iron(3+)": "GO:0008199", "copper(1+)": "GO:1903136", "copper(2+)": "GO:1903135"}
CHEBI_ION_NAME = re.compile(r"^([a-z]+)(?:\(\d\+\)| cation)$")
MODIFICATION_VIEW = "modifications"
MODIFICATION_CATEGORY = "PTM"  # keywlist's category of the keywords the modification view reads
# The modification site view (`modification_site_view`): which residues carry each modification. A site class is a vocabulary term of
# a residue-level modification aspect whose train sites sit on one residue at least `SITE_RESIDUE_SHARE` of the time.
SITE_VIEW = "modification_sites"
SITE_ASPECTS = ("local_modified_residue", "local_glycosylation", "local_lipidation", "local_crosslink")
SITE_COLUMNS = [*VIEW_COLUMNS, "start", "end"]
SITE_RESIDUE_SHARE = 0.95
# Where on the chain ptmlist puts a modification a residue may carry wherever it sits (`PP`, a cross-link's first residue first). An
# N- or C-terminal one, such as N-acetylalanine or an amide, is a question about the chain's end, not about which residue.
SITE_POSITIONS = ("Anywhere", "Protein core")
SITE_ENTRY = pa.struct([
    ("modification", pa.string()), ("residue", pa.string()), ("positions", pa.list_(pa.int32())), ("masked", pa.list_(pa.int32())),
])
SITE_VIEW_SCHEMA = pa.schema([*_ROW, ("sites", pa.list_(SITE_ENTRY))])
# The disordered residue view (`disorder_view`): UniProt's term for a disordered region, which DisProt's disordered regions join
# (`disprot.REGION_TERM`), and DisProt's ordered state.
DISORDER_VIEW = "disordered_regions"
DISORDERED = canonical_term_id("local_region", "UniProtKB-FT", "Disordered")
ORDERED = canonical_term_id("local_disorder", "IDPO", "IDPO:0000006")
DISORDER_VIEW_SCHEMA = pa.schema([
    *_ROW, *[(name, pa.list_(pa.int32())) for name in ("disordered", "masked", "ordered", "observed")],
])
# The located feature view (`located_feature_view`): which residues carry each of UniProt's other located features, a feature class
# a vocabulary term of these aspects but `DISORDERED`, whose residues are the disorder view's. A disulfide bond's located residues
# are its two cysteines, its start and end, not the run between them.
LOCATED_VIEW = "located_features"
LOCATED_ASPECTS = (
    "local_active_site", "local_binding", "local_site", "local_signal_peptide", "local_transit_peptide", "local_transmembrane",
    "local_intramembrane", "local_topological_domain", "local_disulfide", "local_dna_binding", "local_zinc_finger", "local_motif",
    "local_coiled_coil", "local_repeat", "local_domain", "local_region", "local_propeptide", "local_peptide",
)
PAIRED_ASPECTS = ("local_disulfide",)
# Each located aspect's type term, the class of a feature UniProt states without a description of its own (`uniprot.FEATURE_TERMS`).
# Where it is a class the view holds it the parent of the aspect's other terms, as the set views propagate, so a nucleophile, a
# helical span or a WD repeat is a residue of the aspect's type too, never its negative.
TYPE_TERMS = {
    aspect: canonical_term_id(aspect, "UniProtKB-FT", FEATURE_TERMS[key]) for key, aspect in LOCAL_FEATURE_ASPECTS.items() if aspect in LOCATED_ASPECTS
}
RESIDUE_RUN = pa.struct([("start", pa.int32()), ("end", pa.int32())])
LOCATED_ENTRY = pa.struct([("feature", pa.string()), ("residues", pa.list_(RESIDUE_RUN)), ("masked", pa.list_(RESIDUE_RUN))])
LOCATED_VIEW_SCHEMA = pa.schema([*_ROW, ("features", pa.list_(LOCATED_ENTRY))])
# The EC view's rows as `ec_view` reads them a partition at a time, and the view with the matching's `matched` beside them.
EC_LEVEL_SCHEMA = pa.schema([*_ROW, *[(f"level_{depth}", pa.string()) for depth in range(1, EC_LEVELS + 1)]])
EC_VIEW_SCHEMA = pa.schema([*EC_LEVEL_SCHEMA, ("matched", pa.bool_())])
# The two oligomeric states the homodimer view tells apart, and its rows.
HOMODIMER, MONOMER = "Homodimer", "Monomer"
HOMODIMER_VIEW_SCHEMA = pa.schema([*_ROW, ("homodimer", pa.bool_()), ("tier", pa.string())])
PH_KIND = "ph_dependence"  # the measurement texts the pH view reads
# One observation of the pH view: the optimum a text states, the entry that states it, the text and its experiment's citations.
PH_OBSERVATION = pa.struct([("ph", pa.float64()), ("accession", pa.string()), ("text", pa.string()), ("reference", pa.string())])
PH_VIEW_SCHEMA = pa.schema([*_ROW, ("ph_optimum", pa.float64()), ("observations", pa.list_(PH_OBSERVATION))])
# One observation of the melting temperature view: a Meltome Atlas melting point in degrees Celsius, the accession the workbook
# names, the lysate's species, the species' optimal growth temperature, the workbook row, and how the accession found the pooled
# sequence (`tm_entry`): `accession`, a read entry's own; `secondary_accession`, a read entry's secondary one (an accession of
# 2019 that UniProt has since merged into another entry); `sequence`, a fetched entry whose sequence the pool holds under another.
TM_OBSERVATION = pa.struct([
    ("tm", pa.float64()), ("accession", pa.string()), ("species", pa.string()), ("growth_temperature", pa.float64()), ("locator", pa.string()),
    ("matched_by", pa.string()),
])
TM_VIEW_SCHEMA = pa.schema([*_ROW, ("melting_temperature", pa.float64()), ("observations", pa.list_(TM_OBSERVATION))])
# The entry columns the melting temperature view reads: of a fetched entry (`meltome.FETCHED_ENTRY_SCHEMA`), and of a read entry
# with its secondary accessions (`tables.ENTRY_SCHEMA`).
TM_ENTRY_COLUMNS = ["accession", "organism", "fragment", "sequence"]
TM_READ_COLUMNS = [*TM_ENTRY_COLUMNS, "secondary_accessions"]
# The value views the measurements config joins, each its value and observations columns: one config, a protein a row, so a value
# view adds two columns and not a config to the Hub card's 200 lines, as the affinity release did for its assay conditions.
# One observation of a kinetic view (`kinetic_view`): the constant in inverse seconds (kcat) or molar (KM), its substrate as stated
# and the ChEBI entity that name names (`kinetics.chebi_names`), the stated pH and temperature, the entry, the statement verbatim
# and its citations.
KINETIC_OBSERVATION = pa.struct([
    ("value", pa.float64()), ("substrate", pa.string()), ("substrate_chebi", pa.string()), ("ph", pa.float64()),
    ("temperature", pa.float64()), ("accession", pa.string()), ("text", pa.string()), ("reference", pa.string()),
])
# The kinetic views by constant, each one's value column, and their rows.
KINETIC_VIEWS = {"kcat": "log10_kcat", "km": "log10_km"}
KINETIC_VIEW_SCHEMAS = {
    constant: pa.schema([*_ROW, (column, pa.float64()), ("observations", pa.list_(KINETIC_OBSERVATION))])
    for constant, column in KINETIC_VIEWS.items()
}
MEASURED = (
    ("ph_optimum", "ph_observations", PH_OBSERVATION), ("melting_temperature", "tm_observations", TM_OBSERVATION),
    ("log10_kcat", "kcat_observations", KINETIC_OBSERVATION), ("log10_km", "km_observations", KINETIC_OBSERVATION),
)
MEASUREMENT_VIEW_SCHEMA = pa.schema([
    *_ROW, *[field for value, observations, item in MEASURED for field in ((value, pa.float64()), (observations, pa.list_(item)))],
])


def classified(best: pa.Table, splits: pa.Table) -> pa.Table:
    """Each (protein, term) best tier joined to the protein's split, with `role`: positive, masked or ignored."""
    joined = best.join(splits, keys="protein_id", join_type="inner", use_threads=True)
    rank, split = joined["rank"], joined["split"]
    scoring = pc.is_in(split, pa.array(SCORING_SPLITS))
    positive = pc.or_(pc.less_equal(rank, SIGNATURE), pc.and_(pc.equal(rank, CURATED), pc.invert(scoring)))
    masked = pc.or_(pc.equal(rank, GUARD), pc.and_(pc.equal(rank, CURATED), scoring))
    role = pc.if_else(positive, "positive", pc.if_else(masked, "masked", "ignored"))
    return joined.append_column("role", role)


def observation_units(vocabulary: pa.Table) -> pa.ChunkedArray:
    """Each term's observation unit, `aspect/fundamental aspect`: its aspect within its fundamental aspect, so an EC number and
    GO MF's catalytic terms, GO MF's catalytic and other terms, and each keyword category stand apart. A protein with a positive
    in a unit is observed there and the unit's other terms are its negatives; a term of another unit is unknown for it (CAFA's
    rule, which the compendium decision takes), so no aspect's positive makes another aspect's terms negatives."""
    return pc.binary_join_element_wise(vocabulary["aspect"], vocabulary["fundamental_aspect"], "/")


def vocabulary_tokens(vocabulary: pa.Table) -> pa.Table:
    """Every vocabulary term's token, fundamental aspect and observation unit (`TOKEN_SCHEMA`), in token order:
    `grammar.build_vocabulary_index` over the vocabulary in the compendium's aspect order, so tokens follow the shared grammar."""
    kept = vocabulary.filter(vocabulary["in_vocabulary"])
    kept = kept.append_column("unit", observation_units(kept))
    index = build_vocabulary_index((TermKey.from_term_id(term_id) for term_id in kept["term_id"].to_pylist()), aspect_order=COMPENDIUM_ASPECT_ORDER)
    tokens = pa.table({
        "term_id": [term.term_id for term in index.term_to_token], "token": pa.array(list(index.term_to_token.values()), pa.int32()),
    })
    return tokens.join(kept.select(["term_id", "fundamental_aspect", "unit"]), keys="term_id", join_type="inner").select(TOKEN_SCHEMA.names).sort_by("token")


def whole_vocabulary(assertions: pa.Table, tokens: pa.Table, protein_to_split: Mapping[str, str], sequences: pa.Table) -> pa.Table:
    """The whole-vocabulary view (`WHOLE_VOCABULARY_SCHEMA`) over `tokens` (`vocabulary_tokens`).

    A row is a protein with at least one positive vocabulary term: its `tokens` ascending, `terms` and `tiers` beside them, `masked`
    (the vocabulary terms it holds only at a masked tier) and `observed_units` (the observation units of its positives,
    `observation_units`). `sequences` holds `protein_id` and `sequence`.
    """
    roles = classified(best_tiers(assertions), split_frame(protein_to_split)).join(tokens, keys="term_id", join_type="inner")
    roles = roles.sort_by([("protein_id", "ascending"), ("token", "ascending")])
    positive = roles.filter(pc.equal(roles["role"], "positive"))
    tier_names = pc.take(pa.array(TIERS), positive["rank"])
    grouped = pa.table({
        "protein_id": positive["protein_id"], "token": positive["token"], "term_id": positive["term_id"], "tier": tier_names,
        "unit": positive["unit"],
    }).group_by("protein_id", use_threads=False).aggregate([
        ("token", "list"), ("term_id", "list"), ("tier", "list"), ("unit", "distinct"),
    ]).rename_columns({"token_list": "tokens", "term_id_list": "terms", "tier_list": "tiers", "unit_distinct": "observed_units"})
    masked = roles.filter(pc.equal(roles["role"], "masked"))
    masked = masked.select(["protein_id", "term_id"]).group_by("protein_id", use_threads=False).aggregate([("term_id", "list")])
    proteins = grouped["protein_id"]
    view = grouped.append_column("split", take_by_key(proteins, split_frame(protein_to_split), "protein_id", "split"))
    view = view.append_column("sequence", take_by_key(proteins, sequences, "protein_id", "sequence"))
    if view["sequence"].null_count:
        raise ValueError(f"{view['sequence'].null_count} proteins of the view have no sequence")
    held = take_by_key(proteins, masked, "protein_id", "term_id_list")
    view = view.append_column("masked", pc.fill_null(held, pa.scalar([], pa.list_(pa.string()))))
    return view.select(WHOLE_VOCABULARY_SCHEMA.names).cast(WHOLE_VOCABULARY_SCHEMA).sort_by("protein_id")


def ancestor_map(edges: Collection[Edge], relations: Collection[str] = ("is_a", "part_of", "ec_parent")) -> dict[tuple[str, str], tuple[tuple[str, str], ...]]:
    """Each concept's ancestors along `relations`, as (database, accession) pairs, for true-path propagation."""
    up: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for child_database, child, parent_database, parent, relation in edges:
        if relation in relations:
            up.setdefault((child_database, child), []).append((parent_database, parent))
    closed: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {}
    for node in up:
        found: set[tuple[str, str]] = set()
        pending = list(up[node])
        while pending:
            parent = pending.pop()
            if parent not in found:
                found.add(parent)
                pending.extend(up.get(parent, ()))
        closed[node] = tuple(sorted(found))
    return closed


def propagated_support(
    assertions: pa.Table, protein_to_split: Mapping[str, str], *, aspects: Sequence[str],
    ancestors: Mapping[tuple[str, str], Sequence[tuple[str, str]]],
) -> Counter[tuple[str, str, str]]:
    """The train proteins of `assertions` that reach each concept of `aspects`, by (aspect, database, accession): a positive of a
    train protein (`classified`) reaches its own term and every ancestor `ancestors` holds, which stays in the term's namespace,
    and a protein counts once a concept. The pool's partitions hold disjoint proteins, so their counts add up."""
    scoped = assertions.filter(pc.is_in(assertions["aspect"], pa.array(list(aspects))))
    roles = classified(best_tiers(scoped), split_frame(protein_to_split))
    train = roles.filter(pc.and_(pc.equal(roles["role"], "positive"), pc.equal(roles["split"], "train")))
    described = scoped.group_by(["term_id", "aspect", "source_database", "term"]).aggregate([])
    concept = {term_id: (aspect, database, term) for term_id, aspect, database, term in zip(
        *(described[name].to_pylist() for name in ("term_id", "aspect", "source_database", "term")), strict=True)}
    reached: dict[str, set[tuple[str, str, str]]] = {}
    for protein, term_id in zip(train["protein_id"].to_pylist(), train["term_id"].to_pylist(), strict=True):
        aspect, database, accession = concept[term_id]
        found = reached.setdefault(protein, set())
        found.add((aspect, database, accession))
        found.update((aspect, parent_database, parent) for parent_database, parent in ancestors.get((database, accession), ()))
    return Counter(key for found in reached.values() for key in found)


def set_view_terms(
    view: str, aspects: Sequence[str], vocabulary: pa.Table, support: Mapping[tuple[str, str, str], int], *, minimum_support: int,
) -> pa.Table:
    """A set view's terms (`VIEW_TERM_SCHEMA`): every vocabulary term of `aspects`, and every concept outside the GO stoplist that
    `minimum_support` or more train proteins reach by propagation (`support`, `propagated_support` over the pool), the broad
    ancestors curators rarely assert, which the per-property releases and CAFA's propagated scoring count."""
    asserted = view_terms(vocabulary, aspects)
    broad = {key for key, count in support.items()
             if count >= minimum_support and key not in asserted and not (key[1] == "GO" and key[2] in GO_STOPLIST)}
    keys = sorted(set(asserted) | broad)
    return pa.table({
        "view": [view] * len(keys), "term_id": [asserted.get(key) or canonical_term_id(*key) for key in keys],
        "aspect": [key[0] for key in keys], "source_database": [key[1] for key in keys], "accession": [key[2] for key in keys],
        "in_vocabulary": [key in asserted for key in keys], "train_support": pa.array([support.get(key, 0) for key in keys], pa.int64()),
    }, schema=VIEW_TERM_SCHEMA)


def term_map(terms: pa.Table) -> dict[tuple[str, str, str], str]:
    """A term table's terms (`VIEW_TERM_SCHEMA` or the vocabulary's) by (aspect, database, accession), the form `set_view` reads."""
    return {(aspect, database, accession): term_id for term_id, aspect, database, accession in zip(
        *(terms[name].to_pylist() for name in ("term_id", "aspect", "source_database", "accession")), strict=True)}


def set_view(
    assertions: pa.Table, terms: Mapping[tuple[str, str, str], str], protein_to_split: Mapping[str, str], sequences: pa.Table, *,
    aspects: Sequence[str], ancestors: Mapping[tuple[str, str], Sequence[tuple[str, str]]], propagate: bool = True,
) -> tuple[pa.Table, dict[str, int]]:
    """A closed-world multi-label view of `aspects`: rows are the proteins with a positive in them, labels propagated up.

    A term is a label of the view when it is one of `terms` (`term_map` of `set_view_terms`, or of `view_terms` alone); a
    propagated ancestor counts when it is one too. A protein's `negated` holds the view terms an experimental NOT assertion denies,
    which a model may read as explicit negatives. Returns the view and its row counts.
    """
    allowed = terms
    scoped = assertions.filter(pc.is_in(assertions["aspect"], pa.array(list(aspects))))
    roles = classified(best_tiers(scoped), split_frame(protein_to_split))
    described = scoped.group_by(["term_id", "aspect", "source_database", "term"]).aggregate([])
    concept = {term_id: (aspect, database, term) for term_id, aspect, database, term in zip(
        *(described[name].to_pylist() for name in ("term_id", "aspect", "source_database", "term")), strict=True)}

    def closure(term_id: str) -> list[str]:
        aspect, database, accession = concept[term_id]
        found = [term_id] if (aspect, database, accession) in allowed else []
        if propagate:
            found.extend(allowed[(aspect, parent_database, parent)] for parent_database, parent in ancestors.get((database, accession), ())
                         if (aspect, parent_database, parent) in allowed)
        return found

    positives: dict[str, set[str]] = {}
    masked: dict[str, set[str]] = {}
    for protein, term_id, role in zip(*(roles[name].to_pylist() for name in ("protein_id", "term_id", "role")), strict=True):
        if role == "positive":
            positives.setdefault(protein, set()).update(closure(term_id))
        elif role == "masked":
            masked.setdefault(protein, set()).update(closure(term_id))
    denied: dict[str, set[str]] = {}
    nots = scoped.filter(pc.and_(scoped["negated"], pc.equal(scoped["tier"], "experimental")))
    for protein, term_id in zip(nots["protein_id"].to_pylist(), nots["term_id"].to_pylist(), strict=True):
        if term_id in concept and concept[term_id] in allowed:
            denied.setdefault(protein, set()).add(term_id)
    rows = sorted(protein for protein, found in positives.items() if found)
    sequence_of = dict(zip(sequences["protein_id"].to_pylist(), sequences["sequence"].to_pylist(), strict=True))
    view = pa.table({
        "protein_id": rows, "sequence": [sequence_of[protein] for protein in rows], "split": [protein_to_split[protein] for protein in rows],
        "positives": [sorted(positives[protein]) for protein in rows],
        "masked": [sorted(masked.get(protein, set()) - positives[protein]) for protein in rows],
        "negated": [sorted(denied.get(protein, set()) - positives[protein]) for protein in rows],
    }, schema=SET_VIEW_SCHEMA)
    counts = {"rows": len(rows), **{f"rows:{name}": count for name, count in Counter(view["split"].to_pylist()).items()}}
    return view, counts


def view_terms(vocabulary: pa.Table, aspects: Sequence[str]) -> dict[tuple[str, str, str], str]:
    """The vocabulary terms of `aspects`, by (aspect, database, accession): a set view's asserted terms (`set_view_terms`)."""
    return term_map(vocabulary.filter(pc.and_(vocabulary["in_vocabulary"], pc.is_in(vocabulary["aspect"], pa.array(list(aspects))))))


def metal_ion_terms(names: Mapping[str, str], metal_ions: Collection[str]) -> dict[str, str]:
    """Each ChEBI metal ion's GO term, by its ChEBI name in `names`: `OXIDATION_GO`, else `METAL_GO` by the name's element, else
    `METAL_ION_BINDING`."""
    terms: dict[str, str] = {}
    for accession in sorted(metal_ions):
        name = names.get(accession, "")
        element = CHEBI_ION_NAME.match(name)
        terms[accession] = OXIDATION_GO.get(name) or (METAL_GO.get(element.group(1)) if element else None) or METAL_ION_BINDING
    return terms


def metal_assertions(
    assertions: pa.Table, ion_terms: Mapping[str, str], metal_terms: Collection[str],
) -> tuple[pa.Table, Counter[str]]:
    """The metal ion view's statements as GO MF assertions (`VIEW_COLUMNS`), each at the tier of the statement it reads: a binding
    site or cofactor (`METAL_SOURCES`) of a ChEBI metal ion as the ion's GO term (`ion_terms`, from `metal_ion_terms`), and a GO MF
    assertion of `metal_terms`, metal ion binding and every GO term below it, as itself. Returns them and the statements and
    proteins of each source, with its statements of the root (`<source>:root`): a metal GO names no term for, or none named."""
    counts: Counter[str] = Counter()
    parts = []
    for aspect in (*METAL_SOURCES, "go_mf"):
        named = pa.array(sorted(metal_terms if aspect == "go_mf" else ion_terms), pa.string())
        read = assertions.filter(pc.and_(pc.equal(assertions["aspect"], aspect), pc.is_in(assertions["term"], named))).select(VIEW_COLUMNS)
        if aspect != "go_mf":
            terms = [ion_terms[term] for term in read["term"].to_pylist()]
            read = pa.table({
                "protein_id": read["protein_id"], "term_id": [canonical_term_id("go_mf", "GO", term) for term in terms],
                "aspect": ["go_mf"] * len(terms), "source_database": ["GO"] * len(terms), "term": terms, "tier": read["tier"],
                "negated": read["negated"],
            }, schema=read.schema)
        counts[f"statements:{aspect}"] += read.num_rows
        counts[f"statements:{aspect}:root"] += pc.sum(pc.equal(read["term"], METAL_ION_BINDING)).as_py() or 0
        counts[f"proteins:{aspect}"] += len(pc.unique(read["protein_id"]))
        parts.append(read)
    return pa.concat_tables(parts), counts


def subset_view_terms(
    view: str, concept: tuple[str, str], accessions: Collection[str], vocabulary: pa.Table, support: Mapping[tuple[str, str, str], int], *,
    minimum_support: int,
) -> pa.Table:
    """`set_view_terms` over the vocabulary's terms of one (aspect, database) `concept` among `accessions`, with `support` counted by
    `propagated_support` over the view's own statements: the metal ion and modification views' terms (`VIEW_TERM_SCHEMA`)."""
    aspect, _ = concept
    named = pa.array(sorted(accessions), pa.string())
    within = vocabulary.filter(pc.and_(pc.equal(vocabulary["aspect"], aspect), pc.is_in(vocabulary["accession"], named)))
    kept = set(named.to_pylist())
    counted = {key: count for key, count in support.items() if key[:2] == concept and key[2] in kept}
    return set_view_terms(view, (aspect,), within, counted, minimum_support=minimum_support)


def metal_view_terms(
    vocabulary: pa.Table, support: Mapping[tuple[str, str, str], int], metal_terms: Collection[str], *, minimum_support: int,
) -> pa.Table:
    """The metal ion view's terms: the GO MF terms below metal ion binding, the root left out (`subset_view_terms`), with `support`
    counted over the view's own statements (`metal_assertions`)."""
    return subset_view_terms(METAL_VIEW, ("go_mf", "GO"), set(metal_terms) - {METAL_ION_BINDING}, vocabulary, support,
                             minimum_support=minimum_support)


def modification_assertions(assertions: pa.Table, keywords: Collection[str]) -> pa.Table:
    """The modification view's statements (`VIEW_COLUMNS`): the keyword assertions of `keywords`, keywlist's PTM category, each at
    the tier the pool gave it, the best of its own code's and that of the sites and terms that imply it (`pool.inherit_keyword_tiers`)."""
    named = pa.array(sorted(keywords), pa.string())
    return assertions.filter(pc.and_(pc.equal(assertions["aspect"], "keyword"), pc.is_in(assertions["term"], named))).select(VIEW_COLUMNS)


def site_classes(positions: Mapping[str, str | None]) -> set[str]:
    """The site classes among residue-level modification terms, by term id with their ptmlist position (`PP`): those a residue may
    carry wherever it sits (`SITE_POSITIONS`); a terminal modification, or a term ptmlist does not name, is none."""
    return {term_id for term_id, position in positions.items() if position is not None and position.startswith(SITE_POSITIONS)}


def single_sites(sites: pa.Table, classes: Collection[str]) -> pa.Table:
    """The rows of `sites` (`SITE_COLUMNS`) of `classes` that name one residue; a cross-link within the chain joins two, and is left
    out."""
    named = pc.is_in(sites["term_id"], pa.array(sorted(classes), pa.string()))
    return sites.filter(pc.and_(pc.and_(named, pc.is_valid(sites["start"])), pc.equal(sites["start"], sites["end"])))


def site_residues(
    sites: pa.Table, classes: Collection[str], sequence_of: Mapping[str, str], protein_to_split: Mapping[str, str], *,
    share: float = SITE_RESIDUE_SHARE,
) -> dict[str, str]:
    """Each site class's residue, by term id: the one residue that `share` or more of its train sites at a label tier sit on, in
    the protein's sequence (`sequence_of`); a class whose sites spread over residues, or without a train site, has none."""
    labelled = single_sites(sites, classes)
    labelled = labelled.filter(pc.and_(pc.invert(labelled["negated"]), pc.is_in(labelled["tier"], pa.array(list(LABEL_TIERS)))))
    letters: dict[str, Counter[str]] = {}
    for protein, term_id, start in zip(*(labelled[name].to_pylist() for name in ("protein_id", "term_id", "start")), strict=True):
        sequence = sequence_of.get(protein, "")
        if protein_to_split.get(protein) == "train" and 0 < start <= len(sequence):
            letters.setdefault(term_id, Counter())[sequence[start - 1]] += 1
    found: dict[str, str] = {}
    for term_id, counted in letters.items():
        letter, count = counted.most_common(1)[0]
        if count >= share * sum(counted.values()):
            found[term_id] = letter
    return found


def modification_site_view(
    sites: pa.Table, residues: Mapping[str, str], protein_to_split: Mapping[str, str], sequences: pa.Table,
) -> tuple[pa.Table, dict[str, int]]:
    """Which residues carry each modification (`SITE_VIEW_SCHEMA`), a protein a row: for each site class of `residues` (from
    `site_residues`) the protein has a scored site of, an entry with the class, its residue, those positions and the class's masked
    ones. Every other residue of the class's kind in the sequence is its negative there, so a protein is a negative for a class
    only where it has a site of it. Each residue takes the views' tier rule (`classified`) on its own. Returns the view and its
    counts per split: rows, classes held, sites, masked sites and negatives, and the sites off their class's residue, left out."""
    scoped = single_sites(sites, residues)
    keyed = pa.table({
        "protein_id": scoped["protein_id"], "tier": scoped["tier"], "negated": scoped["negated"],
        "term_id": pc.binary_join_element_wise(scoped["term_id"], pc.cast(scoped["start"], pa.string()), "@"),
    })
    roles = classified(best_tiers(keyed), split_frame(protein_to_split))
    wanted = set(pc.unique(roles["protein_id"]).to_pylist())
    sequence_of = {protein: sequence for protein, sequence in zip(sequences["protein_id"].to_pylist(), sequences["sequence"].to_pylist(), strict=True)
                   if protein in wanted}
    held: dict[str, dict[str, tuple[set[int], set[int]]]] = {}
    counts: Counter[str] = Counter()
    for protein, key, role in zip(*(roles[name].to_pylist() for name in ("protein_id", "term_id", "role")), strict=True):
        if role == "ignored":
            continue
        term_id, _, position = key.rpartition("@")
        start, sequence = int(position), sequence_of[protein]
        if not 0 < start <= len(sequence) or sequence[start - 1] != residues[term_id]:
            counts["sites:off_residue"] += 1
            continue
        positive, masked = held.setdefault(protein, {}).setdefault(term_id, (set(), set()))
        (positive if role == "positive" else masked).add(start)
    rows = sorted(protein for protein, found in held.items() if any(positive for positive, _ in found.values()))
    entries: list[list[dict[str, object]]] = []
    for protein in rows:
        split, sequence = protein_to_split[protein], sequence_of[protein]
        found = []
        for term_id in sorted(term_id for term_id, (positive, _) in held[protein].items() if positive):
            positive, masked = held[protein][term_id]
            found.append({"modification": term_id, "residue": residues[term_id], "positions": sorted(positive), "masked": sorted(masked)})
            counts[f"classes:{split}"] += 1
            counts[f"sites:{split}"] += len(positive)
            counts[f"masked:{split}"] += len(masked)
            counts[f"negatives:{split}"] += sequence.count(residues[term_id]) - len(positive) - len(masked)
        entries.append(found)
        counts["rows"] += 1
        counts[f"rows:{split}"] += 1
    view = pa.table({
        "protein_id": rows, "sequence": [sequence_of[protein] for protein in rows], "split": [protein_to_split[protein] for protein in rows],
        "sites": entries,
    }, schema=SITE_VIEW_SCHEMA)
    return view, dict(counts)


def disorder_view(
    regions: pa.Table, protein_to_split: Mapping[str, str], sequences: pa.Table, observed: Mapping[str, Collection[tuple[int, int]]],
) -> tuple[pa.Table, dict[str, int]]:
    """Which residues are disordered (`DISORDER_VIEW_SCHEMA`), a protein a row, from the pooled rows (`SITE_COLUMNS`) of a
    disordered region (`DISORDERED`) and of DisProt's ordered state (`ORDERED`). Each residue of a region takes the views' tier
    rule (`classified`) on its own: `disordered` where it is positive, `ordered` where an ordered region is and no disordered one,
    and `masked` where its best disordered tier is one the split does not score (MobiDB-lite's predictions everywhere, a curated
    region in validation and test) and no paper shows it ordered. A protein is a row when it has a disordered residue, and its
    residues neither disordered nor masked are its negatives, as CAID's DisProt reference counts them (Necci et al. 2021,
    doi:10.1038/s41592-021-01117-3), `ordered` among them the ones a paper shows. `observed` holds the residues a PDB structure
    observes, from each protein's segments (`sifts.observed_segments`): CAID's DisProt-PDB reference takes as its negatives the
    observed residues neither disordered nor masked, and scores no other. Returns the view and its counts per split: rows, rows
    with an observed residue, and disordered, masked, negative, ordered, observed and DisProt-PDB negative residues."""
    stated = regions.filter(pc.and_(pc.is_valid(regions["start"]), pc.is_valid(regions["end"])))
    labelled = stated.filter(pc.and_(pc.and_(pc.equal(stated["term_id"], DISORDERED), pc.invert(stated["negated"])),
                                     pc.is_in(stated["tier"], pa.array(list(LABEL_TIERS)))))
    wanted = pc.unique(labelled["protein_id"])
    stated = stated.filter(pc.is_in(stated["protein_id"], wanted))
    # One key a residue of each term, `D@<position>` or `O@<position>`, so the tier rule reads each residue on its own.
    proteins: list[str] = []
    keys: list[str] = []
    tiers: list[str] = []
    negated: list[bool] = []
    for protein, term_id, tier, denied, start, end in zip(
        *(stated[name].to_pylist() for name in ("protein_id", "term_id", "tier", "negated", "start", "end")), strict=True,
    ):
        label = "D" if term_id == DISORDERED else "O"
        for position in range(start, end + 1):
            proteins.append(protein)
            keys.append(f"{label}@{position}")
            tiers.append(tier)
            negated.append(denied)
    keyed = pa.table({"protein_id": proteins, "term_id": keys, "tier": tiers, "negated": negated},
                     schema=pa.schema([("protein_id", pa.string()), ("term_id", pa.string()), ("tier", pa.string()), ("negated", pa.bool_())]))
    roles = classified(best_tiers(keyed), split_frame(protein_to_split))
    held: dict[str, tuple[set[int], set[int], set[int]]] = {}
    for protein, key, role in zip(*(roles[name].to_pylist() for name in ("protein_id", "term_id", "role")), strict=True):
        label, _, position = key.partition("@")
        disordered, ordered, masked = held.setdefault(protein, (set(), set(), set()))
        if role == "positive":
            (disordered if label == "D" else ordered).add(int(position))
        elif role == "masked" and label == "D":
            masked.add(int(position))
    rows = sorted(protein for protein, (disordered, _, _) in held.items() if disordered)
    named = set(rows)
    sequence_of = {protein: sequence for protein, sequence in zip(sequences["protein_id"].to_pylist(), sequences["sequence"].to_pylist(), strict=True)
                   if protein in named}
    columns: dict[str, list[list[int]]] = {"disordered": [], "masked": [], "ordered": [], "observed": []}
    counts: Counter[str] = Counter()
    for protein in rows:
        disordered, ordered, masked = held[protein]
        ordered -= disordered
        masked -= disordered | ordered
        seen = {position for first, last in observed.get(protein, ()) for position in range(first, last + 1)}
        split, length = protein_to_split[protein], len(sequence_of[protein])
        if max(disordered | ordered | masked | seen) > length:
            raise ValueError(f"a region or an observed segment of {protein} runs past its {length} residues")
        for name, found in (("disordered", disordered), ("masked", masked), ("ordered", ordered), ("observed", seen)):
            columns[name].append(sorted(found))
            counts[f"{name}:{split}"] += len(found)
        counts[f"negatives:{split}"] += length - len(disordered) - len(masked)
        counts[f"pdb_negatives:{split}"] += len(seen - disordered - masked)
        counts["rows"] += 1
        counts[f"rows:{split}"] += 1
        counts[f"observed_rows:{split}"] += 1 if seen else 0
    view = pa.table({
        "protein_id": rows, "sequence": [sequence_of[protein] for protein in rows], "split": [protein_to_split[protein] for protein in rows],
        **columns,
    }, schema=DISORDER_VIEW_SCHEMA)
    return view, dict(counts)


def merged_runs(runs: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Runs of residues, (first, last), as the fewest sorted disjoint runs that cover the same residues."""
    found: list[list[int]] = []
    for first, last in sorted(runs):
        if found and first <= found[-1][1] + 1:
            found[-1][1] = max(found[-1][1], last)
        else:
            found.append([first, last])
    return [(first, last) for first, last in found]


def runs_without(runs: Sequence[tuple[int, int]], cut: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """The residues of sorted disjoint `runs` outside sorted disjoint `cut`, as runs."""
    found: list[tuple[int, int]] = []
    for first, last in runs:
        start = first
        for cut_first, cut_last in cut:
            if cut_last < start or cut_first > last:
                continue
            if cut_first > start:
                found.append((start, cut_first - 1))
            start = cut_last + 1
        if start <= last:
            found.append((start, last))
    return found


def residue_count(runs: Iterable[tuple[int, int]]) -> int:
    return sum(last - first + 1 for first, last in runs)


def located_feature_view(
    features: pa.Table, classes: Collection[str], protein_to_split: Mapping[str, str], sequences: pa.Table,
) -> tuple[pa.Table, dict[str, int]]:
    """Which residues carry each located feature class (`LOCATED_VIEW_SCHEMA`), a protein a row: for each class of `classes` (term
    ids of `LOCATED_ASPECTS`) the protein has a scored residue of, an entry with the class and its residues and masked residues as
    runs. Each feature of the pooled rows (`SITE_COLUMNS`) but `DISORDERED`'s, a run of residues or a disulfide bond's two
    cysteines (`PAIRED_ASPECTS`), takes the views' tier rule (`classified`) on its own, under its class and under its aspect's
    type term where that is a class (`TYPE_TERMS`): its residues are the class's where it labels in the protein's split, and
    masked where it does not (a guard everywhere, a curated feature in validation and test) and no labelling feature of the
    class covers them. Every other residue of a protein is its negative for a class it holds, so a protein is a negative for a
    class only where it has a residue of it. A feature off its sequence is left out. Returns the view and its counts per split:
    rows, entries in all and per aspect, residues, masked residues and negatives, and the distinct features off their sequence."""
    stated = features.filter(pc.and_(pc.not_equal(features["term_id"], DISORDERED),
                                     pc.and_(pc.is_valid(features["start"]), pc.is_valid(features["end"]))))
    named = pc.unique(stated["protein_id"])
    wanted = set(named.to_pylist())
    sequence_of = {protein: sequence for protein, sequence in zip(sequences["protein_id"].to_pylist(), sequences["sequence"].to_pylist(), strict=True)
                   if protein in wanted}
    length = pc.take(pa.array([len(sequence_of[protein]) for protein in named.to_pylist()], pa.int32()),
                     pc.index_in(stated["protein_id"], value_set=named))  # (features,)
    inside = pc.and_(pc.and_(pc.greater(stated["start"], 0), pc.less_equal(stated["start"], stated["end"])), pc.less_equal(stated["end"], length))
    counts: Counter[str] = Counter()
    counts["features:off_sequence"] = stated.filter(pc.invert(inside)).group_by(["protein_id", "term_id", "start", "end"]).aggregate([]).num_rows
    stated = stated.filter(inside)
    # Each feature under its own class, and lifted to its aspect's type term where that is a class and the feature's term another.
    parents = {aspect: term for aspect, term in TYPE_TERMS.items() if term in classes}
    parent_of = pc.take(pa.array(list(parents.values()), pa.string()), pc.index_in(stated["aspect"], value_set=pa.array(list(parents), pa.string())))
    lifted = pc.and_kleene(pc.is_valid(parent_of), pc.not_equal(stated["term_id"], parent_of))
    read = ["protein_id", "term_id", "tier", "negated", "start", "end"]
    own = stated.filter(pc.is_in(stated["term_id"], value_set=pa.array(sorted(classes), pa.string()))).select(read)
    placed = pa.concat_tables([own, stated.filter(lifted).select(read).set_column(1, "term_id", pc.filter(parent_of, lifted))])
    keyed = pa.table({
        "protein_id": placed["protein_id"], "tier": placed["tier"], "negated": placed["negated"],
        "term_id": pc.binary_join_element_wise(placed["term_id"], pc.cast(placed["start"], pa.string()), pc.cast(placed["end"], pa.string()), "@"),
    })
    roles = classified(best_tiers(keyed), split_frame(protein_to_split))
    held: dict[str, dict[str, tuple[list[tuple[int, int]], list[tuple[int, int]]]]] = {}
    for protein, key, role in zip(*(roles[name].to_pylist() for name in ("protein_id", "term_id", "role")), strict=True):
        if role == "ignored":
            continue
        rest, _, end = key.rpartition("@")
        term_id, _, start = rest.rpartition("@")
        first, last = int(start), int(end)
        runs = [(first, first), (last, last)] if term_id.split("::")[1] in PAIRED_ASPECTS else [(first, last)]
        positive, masked = held.setdefault(protein, {}).setdefault(term_id, ([], []))
        (positive if role == "positive" else masked).extend(runs)
    rows = sorted(protein for protein, found in held.items() if any(positive for positive, _ in found.values()))
    entries: list[list[dict[str, object]]] = []
    for protein in rows:
        split, length = protein_to_split[protein], len(sequence_of[protein])
        found = []
        for term_id in sorted(term_id for term_id, (positive, _) in held[protein].items() if positive):
            positive, masked = held[protein][term_id]
            residues = merged_runs(positive)
            hidden = runs_without(merged_runs(masked), residues)
            found.append({"feature": term_id, "residues": [{"start": first, "end": last} for first, last in residues],
                          "masked": [{"start": first, "end": last} for first, last in hidden]})
            counts[f"entries:{split}"] += 1
            counts[f"entries:{term_id.split('::')[1]}:{split}"] += 1
            counts[f"residues:{split}"] += residue_count(residues)
            counts[f"masked:{split}"] += residue_count(hidden)
            counts[f"negatives:{split}"] += length - residue_count(residues) - residue_count(hidden)
        entries.append(found)
        counts["rows"] += 1
        counts[f"rows:{split}"] += 1
    view = pa.table({
        "protein_id": rows, "sequence": [sequence_of[protein] for protein in rows], "split": [protein_to_split[protein] for protein in rows],
        "features": entries,
    }, schema=LOCATED_VIEW_SCHEMA)
    return view, dict(counts)


def ec_levels(number: str) -> list[str]:
    """An EC number's four levels, broadest first: 1.1.1.1 gives 1.-.-.-, 1.1.-.-, 1.1.1.- and 1.1.1.1."""
    parts = number.split(".")
    return [".".join(parts[:depth] + ["-"] * (EC_LEVELS - depth)) for depth in range(1, EC_LEVELS + 1)]


def ec_view(
    assertions: pa.Table, protein_to_split: Mapping[str, str], sequences: pa.Table, non_enzymes: Collection[str] = frozenset(),
) -> tuple[pa.Table, dict[str, int]]:
    """The enzymes with exactly one complete EC number at a label tier their split scores, with its four levels, and the proteins
    of `non_enzymes` (`non_enzymes.candidates`) this partition holds, `non_enzyme` at level 1 and no lower level (`EC_LEVEL_SCHEMA`).

    A protein with two or more distinct EC numbers has no single answer and is left out, counted, as `ec_experimental_v3` does. A
    candidate holds no EC number at any tier, so it is never an enzyme row too.
    """
    scoped = assertions.filter(pc.equal(assertions["aspect"], "ec"))
    roles = classified(best_tiers(scoped), split_frame(protein_to_split))
    positive = roles.filter(pc.equal(roles["role"], "positive"))
    numbers: dict[str, set[str]] = {}
    for protein, term_id in zip(positive["protein_id"].to_pylist(), positive["term_id"].to_pylist(), strict=True):
        numbers.setdefault(protein, set()).add(TermKey.from_term_id(term_id).accession)
    sequence_of = dict(zip(sequences["protein_id"].to_pylist(), sequences["sequence"].to_pylist(), strict=True))
    levels = {protein: ec_levels(next(iter(found))) for protein, found in numbers.items() if len(found) == 1}
    held = {protein for protein in non_enzymes if protein in sequence_of and protein in protein_to_split}
    if held & set(numbers):
        raise ValueError(f"{len(held & set(numbers))} non-enzymes hold an EC number, such as {sorted(held & set(numbers))[0]}")
    levels.update({protein: [NON_ENZYME, None, None, None] for protein in held})
    rows = sorted(levels)
    view = pa.table({
        "protein_id": rows, "sequence": [sequence_of[protein] for protein in rows], "split": [protein_to_split[protein] for protein in rows],
        **{f"level_{depth + 1}": [levels[protein][depth] for protein in rows] for depth in range(EC_LEVELS)},
    }, schema=EC_LEVEL_SCHEMA)
    counts = {"rows": len(rows), "non_enzymes": len(held), "multiple_ec": sum(len(found) > 1 for found in numbers.values()),
              **{f"rows:{name}": count for name, count in Counter(view["split"].to_pylist()).items()}}
    return view, counts


def homodimer_view(assertions: pa.Table, protein_to_split: Mapping[str, str], sequences: pa.Table) -> tuple[pa.Table, dict[str, int]]:
    """Whether a protein is a homodimer, as `homodimer_experimental_v1` asks: the proteins whose subunit comments state `Homodimer`
    or `Monomer` at a label tier their split scores, each state with its own sentence's evidence (`uniprot.oligomeric_states`),
    with that state's best tier (`HOMODIMER_VIEW_SCHEMA`).

    A protein takes the state it states at its best tier, so an experiment outranks a curator's transfer by similarity, which
    another entry of the same sequence may carry (`resolved_by_tier` counts them). One that states both at its best tier is left
    out, counted, as v1 leaves out an entry or a sequence whose statements conflict; every other state, a heterodimer, a
    homotrimer or a dimer of unnamed parts, is neither class. A monomer statement is the only negative, a non-homodimer under
    the conditions its paper reports.
    """
    scoped = assertions.filter(pc.and_(pc.equal(assertions["aspect"], "oligomeric_state"),
                                       pc.is_in(assertions["term"], pa.array([HOMODIMER, MONOMER]))))
    roles = classified(best_tiers(scoped), split_frame(protein_to_split))
    positive = roles.filter(pc.equal(roles["role"], "positive"))
    states: dict[str, dict[str, int]] = {}  # each protein's states at a scored label tier, with the best tier rank of each
    for protein, term_id, rank in zip(*(positive[name].to_pylist() for name in ("protein_id", "term_id", "rank")), strict=True):
        states.setdefault(protein, {})[TermKey.from_term_id(term_id).accession] = rank
    chosen: dict[str, tuple[str, int]] = {}  # each protein's one state at its best tier, and that tier's rank
    for protein, found in states.items():
        best = min(found.values())
        stated = [name for name, rank in found.items() if rank == best]
        if len(stated) == 1:
            chosen[protein] = (stated[0], best)
    sequence_of = dict(zip(sequences["protein_id"].to_pylist(), sequences["sequence"].to_pylist(), strict=True))
    rows = sorted(chosen)
    view = pa.table({
        "protein_id": rows, "sequence": [sequence_of[protein] for protein in rows], "split": [protein_to_split[protein] for protein in rows],
        "homodimer": [chosen[protein][0] == HOMODIMER for protein in rows], "tier": [TIERS[chosen[protein][1]] for protein in rows],
    }, schema=HOMODIMER_VIEW_SCHEMA)
    counts = {"rows": len(rows), "homodimers": sum(view["homodimer"].to_pylist()), "both_states": len(states) - len(rows),
              "resolved_by_tier": sum(len(states[protein]) == 2 for protein in rows),
              **{f"rows:{name}": count for name, count in Counter(view["split"].to_pylist()).items()}}
    return view, counts


def ph_optimum_view(
    texts: pa.Table, protein_to_split: Mapping[str, str], sequences: pa.Table, reviewed: Collection[str],
) -> tuple[pa.Table, dict[str, int]]:
    """The proteins whose Swiss-Prot entries state one point optimum pH from a cited experiment, each with the mean of its distinct
    observations and the observations themselves (`PH_VIEW_SCHEMA`), as `ph_optimum_experimental_v2` reads Swiss-Prot.

    `texts` are pooled measurement texts (`MEASUREMENT_TEXT_SCHEMA` with `protein_id`), and `reviewed` the Swiss-Prot accessions.
    A pH-dependence text of a reviewed entry is an observation when `foundry.protein.ph_optimum.judge_text` gives it no reason and
    its ECO:0000269 code has a citation (`no_citation` otherwise); a comment scoped to a molecule is not read at all
    (`uniprot.read_entry`). A protein's observation that states the pH, text and citations of an earlier one, from its entry or
    another entry of its sequence, is that one (`duplicate_assertion`). Each text read is counted as an observation or under its
    one reason.
    """
    texts = texts.filter(pc.equal(texts["kind"], PH_KIND))
    sequences = sequences.filter(pc.is_in(sequences["protein_id"], value_set=texts["protein_id"].combine_chunks()))
    sequence_of = dict(zip(sequences["protein_id"].to_pylist(), sequences["sequence"].to_pylist(), strict=True))
    counts: Counter[str] = Counter()
    observed: dict[str, dict[tuple[float, str, str], str]] = {}  # each protein's observations, (pH, text, citations) to accession
    for row in sorted(texts.to_pylist(), key=lambda row: (row["protein_id"] or "", row["accession"])):
        if row["protein_id"] not in sequence_of:
            continue
        if row["accession"] not in reviewed:
            counts["unreviewed_texts"] += 1
            continue
        counts["texts"] += 1
        reason, value, _ = judge_text(row["text"], row["codes"])
        cited = dict(zip(row["codes"], row["references"], strict=True)).get(EXPERIMENTAL_CODE, "")
        if reason is None and not cited:
            reason = "no_citation"
        found = observed.setdefault(row["protein_id"], {})
        if reason is None and (value, row["text"], cited) in found:
            reason = "duplicate_assertion"
        if reason is not None:
            counts[f"excluded:{reason}"] += 1
            continue
        found[(value, row["text"], cited)] = row["accession"]
        counts["observations"] += 1
    rows = sorted(protein for protein, found in observed.items() if found)
    view = pa.table({
        "protein_id": rows, "sequence": [sequence_of[protein] for protein in rows], "split": [protein_to_split[protein] for protein in rows],
        "ph_optimum": [math.fsum(ph for ph, _, _ in observed[protein]) / len(observed[protein]) for protein in rows],
        "observations": [[{"ph": ph, "accession": accession, "text": text, "reference": reference}
                          for (ph, text, reference), accession in observed[protein].items()] for protein in rows],
    }, schema=PH_VIEW_SCHEMA)
    counts.update({"rows": len(rows), **{f"rows:{name}": count for name, count in Counter(view["split"].to_pylist()).items()}})
    return view, dict(counts)


def entries_by_accession(read: pa.Table) -> tuple[dict[str, dict[str, object]], dict[str, list[dict[str, object]]]]:
    """Read entries (`TM_READ_COLUMNS`) by primary accession, an accession read twice keeping its first entry, as the pool does,
    and by secondary accession, every entry that lists it: `tm_entry`'s lookups."""
    by_accession: dict[str, dict[str, object]] = {}
    for entry in read.select(TM_READ_COLUMNS).to_pylist():
        by_accession.setdefault(str(entry["accession"]), entry)
    by_secondary: dict[str, list[dict[str, object]]] = {}
    for entry in by_accession.values():
        for other in entry["secondary_accessions"] or []:
            by_secondary.setdefault(str(other), []).append(entry)
    return by_accession, by_secondary


def tm_entry(
    identifier: str, read: Mapping[str, Mapping[str, object]], secondary: Mapping[str, Sequence[Mapping[str, object]]],
    fetched: Mapping[str, Mapping[str, object]],
) -> tuple[Mapping[str, object] | None, str]:
    """The entry a workbook accession names and how it was found (`TM_OBSERVATION`'s `matched_by`), or None and the reason no
    entry was: a secondary accession of several read entries (`secondary_of_several_entries`, a split UniProt has made since) or
    an accession the release holds as no entry's primary accession and no read entry's secondary one (`not_in_the_release`)."""
    if identifier in read:
        return read[identifier], "accession"
    if len(secondary.get(identifier, ())) > 1:
        return None, "secondary_of_several_entries"
    if identifier in secondary:
        return secondary[identifier][0], "secondary_accession"
    if identifier in fetched:
        return fetched[identifier], "sequence"
    return None, "not_in_the_release"


def melting_temperature_view(
    rows: pa.Table, read: pa.Table, fetched: pa.Table, protein_to_split: Mapping[str, str],
) -> tuple[pa.Table, dict[str, int]]:
    """The pooled proteins whose Meltome Atlas rows state a melting point, each with the mean of its observations and the
    observations themselves (`TM_VIEW_SCHEMA`), as `thermal_tm_experimental_v1` reads the workbook.

    `rows` are the workbook's rows (`meltome.MELTOME_ROW_SCHEMA`), `read` the read entries that hold their accessions as the
    primary accession or a secondary one (`TM_READ_COLUMNS`), an accession read twice keeping its first entry, as the pool does,
    and `fetched` the entries of the pinned release that the accessions no read entry holds name (`TM_ENTRY_COLUMNS`). A row is an
    observation unless, the first that applies: it states no melting point or names no UniProtKB identifier
    (`foundry.protein.meltome`); it names an isoform, which the pool of canonical sequences never holds (`isoform_identifier`); no
    entry is found for it (`tm_entry`); the entry is of another species than the lysate (`organism_differs_from_lysate_species`,
    v1's rule, since the point would go to another species' sequence); the entry's sequence is not a row (`pool.entry_exclusion`:
    `fragment`, `over_length_limit`); a fetched entry's sequence is no pooled one (`entry_outside_the_pool`, a TrEMBL entry the
    pool does not admit); or a read entry's protein is outside the split, which a full build's split never leaves
    (`outside_the_split`). A species that lists an accession twice is refused, as v1 refuses it. Each row is counted as an
    observation, by how its entry was found, or under its one reason.
    """
    by_accession, by_secondary = entries_by_accession(read)
    by_fetch = {str(entry["accession"]): entry for entry in fetched.select(TM_ENTRY_COLUMNS).to_pylist()}
    counts: Counter[str] = Counter()
    observed: dict[str, list[dict[str, object]]] = {}  # each protein's observations, in workbook order
    seen: set[tuple[str, str]] = set()
    sequence_of: dict[str, str] = {}
    for row in rows.to_pylist():
        counts["sheet_rows"] += 1
        reason, entry, matched_by = row["reason"], None, ""
        if reason is None:
            if "-" in row["identifier"]:
                reason = "isoform_identifier"
            else:
                entry, matched_by = tm_entry(row["identifier"], by_accession, by_secondary, by_fetch)
                if entry is None:
                    reason = matched_by
                elif str(entry["organism"]).split()[:2] != SPECIES[row["species"]].split():
                    reason = "organism_differs_from_lysate_species"
                else:
                    reason = entry_exclusion(entry)
        if reason is None:
            protein = protein_id(str(entry["sequence"]))
            if protein not in protein_to_split:
                reason = "entry_outside_the_pool" if matched_by == "sequence" else "outside_the_split"
        if reason is not None:
            counts[f"excluded:{reason}"] += 1
            continue
        if (row["species"], row["identifier"]) in seen:
            raise ValueError(f"{row['species']} lists {row['identifier']} twice with a melting point; a second measurement needs its own rule")
        seen.add((row["species"], row["identifier"]))
        sequence_of[protein] = str(entry["sequence"])
        observed.setdefault(protein, []).append({
            "tm": row["tm"], "accession": row["identifier"], "species": row["species"], "growth_temperature": row["growth_temperature"],
            "locator": f"{MELTING_POINTS_SHEET}/R{row['number']}", "matched_by": matched_by,
        })
        counts["observations"] += 1
        counts[f"observations:by_{matched_by}"] += 1
    proteins = sorted(observed)
    view = pa.table({
        "protein_id": proteins, "sequence": [sequence_of[protein] for protein in proteins],
        "split": [protein_to_split[protein] for protein in proteins],
        "melting_temperature": [math.fsum(item["tm"] for item in observed[protein]) / len(observed[protein]) for protein in proteins],
        "observations": [observed[protein] for protein in proteins],
    }, schema=TM_VIEW_SCHEMA)
    counts.update({"rows": len(proteins), "several_observations": sum(len(observed[protein]) > 1 for protein in proteins),
                   **{f"rows:{name}": count for name, count in Counter(view["split"].to_pylist()).items()}})
    return view, dict(counts)


def kinetic_view(statements: pa.Table, constant: str, protein_to_split: Mapping[str, str], sequences: pa.Table) -> tuple[pa.Table, dict[str, int]]:
    """The proteins with a `constant`, "kcat" or "km", that a cited experiment measured (`kinetics.kinetic_statements`), each
    with the mean log10 of its distinct observations in inverse seconds or molar and the observations, as `kcat_experimental_v1`
    defines its target. A protein's statement of the value, substrate, conditions and citations of an earlier one, from its entry
    or another entry of its sequence, is that one (`duplicate_assertion`); a statement without ECO:0000269 or a citation is not
    an observation."""
    column = KINETIC_VIEWS[constant]
    counts: Counter[str] = Counter()
    observed: dict[str, dict[tuple[float, str, str, str], dict[str, object]]] = {}
    for row in statements.filter(pc.equal(statements["constant"], constant)).to_pylist():
        if row["protein_id"] not in protein_to_split:
            continue
        reference = "; ".join(row["references"])
        if not row["experimental"] or not reference:
            counts["excluded:" + ("not_experimental" if not row["experimental"] else "no_citation")] += 1
            continue
        found = observed.setdefault(row["protein_id"], {})
        key = (row["value"], row["substrate"], row["conditions"], reference)
        if key in found:
            counts["excluded:duplicate_assertion"] += 1
            continue
        found[key] = {"value": row["value"], "substrate": row["substrate"], "substrate_chebi": row["substrate_chebi"], "ph": row["ph"],
                      "temperature": row["temperature"], "accession": row["accession"], "text": row["text"], "reference": reference}
        counts["observations"] += 1
    proteins = sorted(observed)
    held = sequences.filter(pc.is_in(sequences["protein_id"], value_set=pa.array(proteins, pa.string())))
    sequence_of = dict(zip(held["protein_id"].to_pylist(), held["sequence"].to_pylist(), strict=True))
    view = pa.table({
        "protein_id": proteins, "sequence": [sequence_of[protein] for protein in proteins],
        "split": [protein_to_split[protein] for protein in proteins],
        column: [math.fsum(math.log10(item["value"]) for item in observed[protein].values()) / len(observed[protein]) for protein in proteins],
        "observations": [list(observed[protein].values()) for protein in proteins],
    }, schema=KINETIC_VIEW_SCHEMAS[constant])
    counts.update({"rows": len(proteins), **{f"rows:{name}": count for name, count in Counter(view["split"].to_pylist()).items()}})
    return view, dict(counts)


def measurement_view(views: Mapping[str, pa.Table]) -> tuple[pa.Table, dict[str, int]]:
    """The value views (`MEASURED`: `ph_optimum_view`, `melting_temperature_view` and the two of `kinetic_view`, by value
    column) as one table, a protein a row with each view's value and observations, null where that view does not hold the protein
    (`MEASUREMENT_VIEW_SCHEMA`)."""
    rows: dict[str, dict[str, object]] = {}
    for value, observations, _ in MEASURED:
        for row in views[value].to_pylist():
            found = rows.setdefault(row["protein_id"], {name: row[name] for name in ("protein_id", "sequence", "split")})
            found[value], found[observations] = row[value], row["observations"]
    view = pa.Table.from_pylist([rows[protein] for protein in sorted(rows)], schema=MEASUREMENT_VIEW_SCHEMA)
    counts = {"rows": view.num_rows, **{f"rows_with:{value}": views[value].num_rows for value, _, _ in MEASURED},
              **{f"rows:{name}": count for name, count in Counter(view["split"].to_pylist()).items()}}
    return view, counts
